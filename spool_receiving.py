"""Immutable physical-spool arrival decisions and retained MTR revisions.

An uploaded file or material reference never supplies QA acceptance. A current
Pass is a signed inspection of one exact spool and its then-current evidence.
"""
from datetime import timezone
import hashlib
import json
import re
from urllib.parse import quote
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import Field, model_validator
from sqlalchemy import (CheckConstraint, Column, DateTime, ForeignKey, Integer,
                        JSON, LargeBinary, String, Text, UniqueConstraint, func, select)
from sqlalchemy.orm import Session, deferred
from read_projection import (read_cached, reader_role, read_get, projection_get,
                             PROJECTION_MISSING)

from main import Base, Employee, Item, audit, auth, db, lock_item, utcnow
from orders import Input, _commit, _key, read_snapshot
from permissions import has_capability


router = APIRouter(prefix='/api/spool-boms', tags=['spool arrival and MTRs'])
CHECKS = [
    {'key': 'identity', 'label': 'The arriving physical spool and assembly identity match this record'},
    {'key': 'bom', 'label': 'The delivered materials match the current spool BOM'},
    {'key': 'heat_numbers', 'label': 'The recorded heat numbers match the material markings'},
    {'key': 'mtrs', 'label': 'The MTRs have been checked against the materials and heat numbers'},
    {'key': 'condition', 'label': 'The arriving materials are in acceptable condition'},
]


class SpoolArrivalInspection(Base):
    __tablename__ = 'spool_arrival_inspections'
    __table_args__ = (
        UniqueConstraint('spool_id', 'version', name='uq_spool_arrival_version'),
        CheckConstraint("result IN ('Pass', 'Fail')", name='ck_spool_arrival_result'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    spool_id = Column(String(60), ForeignKey('items.id'), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    result = Column(String(10), nullable=False)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    reference = Column(String(300), nullable=False)
    notes = Column(Text, nullable=False)
    checks = Column(JSON, nullable=False)
    basis_sha256 = Column(String(64), nullable=False)
    basis = deferred(Column(JSON, nullable=False))


class SpoolMaterialInspection(Base):
    __tablename__ = 'spool_material_inspections'
    __table_args__ = (
        UniqueConstraint('spool_id', 'piece_key', 'version', name='uq_spool_material_inspection_version'),
        CheckConstraint("result IN ('Pass', 'Fail')", name='ck_spool_material_inspection_result'),
        CheckConstraint("check_code = 'QA-001'", name='ck_spool_material_inspection_code'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    spool_id = Column(String(60), ForeignKey('items.id'), nullable=False, index=True)
    # The physical row may be archived on explicit BOM adoption. Its QA events
    # retain their own source snapshot and never cascade with current rows.
    piece_key = Column(String(32), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    check_code = Column(String(20), nullable=False, default='QA-001')
    result = Column(String(10), nullable=False)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    reference = Column(String(300), nullable=False)
    notes = Column(Text, nullable=False)
    basis_sha256 = Column(String(64), nullable=False)
    basis = deferred(Column(JSON, nullable=False))


class SpoolMtrDocument(Base):
    __tablename__ = 'spool_mtr_documents'
    __table_args__ = (UniqueConstraint('spool_id', 'reference_key', 'version', name='uq_spool_mtr_revision'),)
    id = Column(String(60), primary_key=True)
    spool_id = Column(String(60), ForeignKey('items.id'), nullable=False, index=True)
    reference = Column(String(300), nullable=False)
    reference_key = Column(String(300), nullable=False)
    version = Column(Integer, nullable=False)
    revision = Column(String(80), nullable=False, default='')
    filename = Column(String(200), nullable=False)
    media_type = Column(String(160), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    selection_sha256 = Column(String(64), nullable=False)
    page_count = Column(Integer, nullable=False)
    source_files = Column(JSON, nullable=False)
    scope_snapshot = Column(JSON, nullable=False)
    uploaded_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    reason = Column(Text, nullable=False)


class SpoolMtrFile(Base):
    __tablename__ = 'spool_mtr_files'
    document_id = Column(String(60), ForeignKey('spool_mtr_documents.id'), primary_key=True)
    content = deferred(Column(LargeBinary, nullable=False))


class ArrivalChecks(Input):
    identity: bool = Field(default=False, strict=True)
    bom: bool = Field(default=False, strict=True)
    heat_numbers: bool = Field(default=False, strict=True)
    mtrs: bool = Field(default=False, strict=True)
    condition: bool = Field(default=False, strict=True)


class InspectionDecisionIn(Input):
    """A Pass is signed by its actor and evidence; only Fail needs a reason."""
    result: str = Field(pattern='^(Pass|Fail)$')
    reference: str = Field(default='', max_length=300)
    notes: str = Field(default='', max_length=3000)

    @model_validator(mode='after')
    def require_failure_details(self):
        if self.result == 'Fail':
            errors = []
            if len(self.reference) < 2:
                errors.append('Fail requires an inspection reference of at least 2 characters')
            if len(self.notes) < 4:
                errors.append('Fail requires a failure reason of at least 4 characters')
            if errors:
                raise ValueError('; '.join(errors))
        return self


class ArrivalIn(InspectionDecisionIn):
    expected_version: int = Field(ge=0, le=2147483646, strict=True)
    basis_sha256: str = Field(min_length=64, max_length=64)
    checks: ArrivalChecks


class MaterialInspectionIn(InspectionDecisionIn):
    expected_version: int = Field(ge=0, le=2147483646, strict=True)
    basis_sha256: str = Field(min_length=64, max_length=64)


class MaterialPassExpectationIn(Input):
    piece_key: str = Field(min_length=1, max_length=32)
    expected_version: int = Field(ge=0, le=2147483646, strict=True)
    basis_sha256: str = Field(min_length=64, max_length=64)


class MaterialPassAllIn(Input):
    expected_trace_version: int = Field(ge=0, le=2147483646, strict=True)
    expected_bom_sha256: str = Field(min_length=64, max_length=64)
    reference: str = Field(default='', max_length=300)
    notes: str = Field(default='', max_length=3000)
    pieces: list[MaterialPassExpectationIn] = Field(min_length=1, max_length=500)


def _stamp(value):
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def is_physical_spool(s, item):
    if item is None or item.kind == 'Assembly':
        return False
    if item.kind == 'Spool':
        return True
    from tracking import SpoolPlan
    from order_spools import OrderSpool
    return bool(read_get(s, SpoolPlan, item.id) or read_get(s, OrderSpool, item.id))


def physical_spool_number(s, item, values=None):
    # Legacy tracked Parts may have no declared spool number. Their Item ID is
    # still the exact physical identity; do not invent a drawing/part number.
    return item.google_part_number or ''


def retained_parent_matches(s, item, saved, current_parent):
    """Permit only the existing audited collection of an unparented spool.

    Receipt and local documents may precede assembly collection. The immutable
    assembly_link event proves that the released physical spool was collected
    through that controlled route; ordinary plan edits cannot create it.
    """
    previous = saved.get('assembly_id') or None
    current_parent = current_parent or None
    if previous == current_parent:
        return True
    if previous or not current_parent:
        return False
    from flow import FlowEvent
    from order_spools import OrderSpool
    from tracking import SpoolPlan
    if read_get(s, OrderSpool, item.id) is not None:
        return False
    child_plan, parent_plan = read_get(s, SpoolPlan, item.id), read_get(s, SpoolPlan, current_parent)
    if (child_plan is None or parent_plan is None or child_plan.assembly_id != current_parent
            or not saved.get('project_id') or item.project != saved['project_id']
            or child_plan.project_id != saved['project_id'] or parent_plan.project_id != saved['project_id']):
        return False
    events = list(s.scalars(select(FlowEvent).where(FlowEvent.item_id == item.id,
        FlowEvent.action == 'assembly_link').order_by(FlowEvent.sequence).limit(2)))
    return bool(len(events) == 1 and events[0].data.get('assembly_id') == current_parent
                and events[0].data.get('quality_release_preserved') is True)


def guard_receiving_identity(s, item, values=None):
    """An MTR or arrival decision cannot move to another physical identity."""
    from order_spools import effective_parent_id
    record = projection_get(s, 'first_mtr', item.id)
    if record is PROJECTION_MISSING:
        record = s.scalar(select(SpoolMtrDocument).where(SpoolMtrDocument.spool_id == item.id)
            .order_by(SpoolMtrDocument.uploaded_at, SpoolMtrDocument.id).limit(1))
    saved = record.scope_snapshot if record else None
    if saved is None:
        inspection = _latest(s, item.id)
        saved = inspection.basis.get('context') if inspection else None
    if saved is None:
        piece_inspection = projection_get(s, 'latest_material_inspection', item.id)
        if piece_inspection is PROJECTION_MISSING:
            piece_inspection = s.scalar(select(SpoolMaterialInspection).where(
                SpoolMaterialInspection.spool_id == item.id).order_by(SpoolMaterialInspection.id.desc()).limit(1))
        saved = piece_inspection.basis.get('context') if piece_inspection else None
    if saved is None:
        return
    project = values.get('project_id') if values is not None else item.project
    parent = values.get('assembly_id') if values is not None else effective_parent_id(s, item.id)
    if (not is_physical_spool(s, item) or _key(physical_spool_number(s, item, values)) != _key(saved.get('spool_number') or '')
            or (project or '') != (saved.get('project_id') or '') or not retained_parent_matches(s, item, saved, parent)):
        raise HTTPException(409, 'This physical spool has MTR or arrival inspection history. Retain its spool number, purchase order and assembly identity.')


def _scope_items(s, item, include_children=True, seen=None):
    from order_spools import effective_children
    seen = set() if seen is None else seen
    if item is None or item.id in seen:
        return []
    seen.add(item.id)
    if is_physical_spool(s, item):
        return [item]
    if item.kind != 'Assembly' or not include_children:
        return []
    result = []
    for child, _ in effective_children(s, item.id, include_removed=False):
        result.extend(_scope_items(s, child, True, seen))
    return sorted(result, key=lambda value: value.id)


def _can_edit(user):
    return has_capability(user, 'allocate_parts') or has_capability(user, 'inspect')


def _context(s, item_id):
    from spool_documents import _target
    return _target(s, 'spools', item_id)


def _locked_reason(s, item):
    from spool_boms import _locked_reason as material_locked
    return material_locked(s, item)


@read_cached(lambda s, item_id: item_id)
def _latest(s, item_id):
    cached = projection_get(s, 'latest_arrival', item_id)
    if cached is not PROJECTION_MISSING:
        return cached
    return s.scalar(select(SpoolArrivalInspection).where(SpoolArrivalInspection.spool_id == item_id)
        .order_by(SpoolArrivalInspection.version.desc()).limit(1))


def _inspection_view(row):
    if row is None:
        return None
    return {key: getattr(row, key) for key in ('id', 'spool_id', 'version', 'result', 'actor',
            'reference', 'notes', 'checks', 'basis_sha256')} | {'at': _stamp(row.at)}


def _mtr_view(row, urls=True):
    value = {key: getattr(row, key) for key in ('id', 'spool_id', 'reference', 'version', 'revision',
        'filename', 'media_type', 'size_bytes', 'sha256', 'page_count', 'uploaded_by', 'reason')}
    value.update(document_id=row.id, uploaded_at=_stamp(row.uploaded_at))
    if urls:
        value.update(view_url='/api/spool-boms/mtr-files/' + quote(row.id, safe=''),
                     download_url='/api/spool-boms/mtr-files/' + quote(row.id, safe='') + '?download=1')
    return value


@read_cached(lambda s, item_id: item_id)
def _current_mtrs(s, item_id):
    cached = projection_get(s, 'current_mtrs', item_id)
    if cached is not PROJECTION_MISSING:
        return cached
    latest = select(SpoolMtrDocument.reference_key,
        func.max(SpoolMtrDocument.version).label('version')).where(SpoolMtrDocument.spool_id == item_id)
    latest = latest.group_by(SpoolMtrDocument.reference_key).subquery()
    return list(s.scalars(select(SpoolMtrDocument).join(latest,
        (SpoolMtrDocument.reference_key == latest.c.reference_key) &
        (SpoolMtrDocument.version == latest.c.version)).where(SpoolMtrDocument.spool_id == item_id)
        .order_by(SpoolMtrDocument.reference_key)))


def mtr_detail(s, item, user=None):
    from spool_documents import MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_FILES, MAX_PAGES
    history = s.scalars(select(SpoolMtrDocument).where(SpoolMtrDocument.spool_id == item.id)
        .order_by(SpoolMtrDocument.uploaded_at.desc(), SpoolMtrDocument.id.desc()).limit(50))
    return {'current': [_mtr_view(row) for row in _current_mtrs(s, item.id)],
            'history': [_mtr_view(row) for row in history],
            'can_upload': _can_edit(user) and not _locked_reason(s, item),
            'limits': {'max_file_bytes': MAX_FILE_BYTES, 'max_total_bytes': MAX_TOTAL_BYTES,
                       'max_files': MAX_FILES, 'max_pages': MAX_PAGES}}


def _receipt_context(s, state):
    context = dict(state['context'])
    prior = _latest(s, state['item'].id)
    prior_context = (prior.basis or {}).get('context') if prior else None
    if (prior_context and not prior_context.get('assembly_id') and context.get('assembly_id')
            and retained_parent_matches(s, state['item'], prior_context, context['assembly_id'])):
        for key in ('assembly_id', 'assembly_number', 'gpn_id'):
            context[key] = prior_context.get(key)
    return context


def _material_inspection_view(row):
    if row is None:
        return None
    return {key: getattr(row, key) for key in ('id', 'spool_id', 'piece_key', 'version',
        'check_code', 'result', 'actor', 'reference', 'notes', 'basis_sha256')} | {'at': _stamp(row.at)}


@read_cached(lambda s, item_id: item_id)
def _current_material_inspections(s, item_id):
    cached = projection_get(s, 'current_material_inspections', item_id)
    if cached is not PROJECTION_MISSING:
        return cached
    latest = select(SpoolMaterialInspection.piece_key,
        func.max(SpoolMaterialInspection.version).label('version')).where(
        SpoolMaterialInspection.spool_id == item_id).group_by(SpoolMaterialInspection.piece_key).subquery()
    return {row.piece_key: row for row in s.scalars(select(SpoolMaterialInspection).join(latest,
        (SpoolMaterialInspection.piece_key == latest.c.piece_key) &
        (SpoolMaterialInspection.version == latest.c.version)).where(SpoolMaterialInspection.spool_id == item_id))}


def _material_qa_bases(s, state):
    from spool_documents import spool_document_scope_basis
    source = state['source_status']
    stable_source = lambda value: ({key: value.get(key) for key in
        ('kind', 'document_id', 'sha256', 'catalog_sha256', 'structured')} if value else None)
    shared = {'check_code': 'QA-001', 'basis_version': 1, 'spool_id': state['item'].id,
        'context': _receipt_context(s, state),
        'current_bom_source': stable_source(source['current']),
        'pinned_bom_source': stable_source(source['pinned']),
        'documents': spool_document_scope_basis(s, state['item'].id)}
    mtrs = {row.reference_key: _mtr_view(row, urls=False) for row in _current_mtrs(s, state['item'].id)}
    return {row['piece_key']: {**shared, 'piece_key': row['piece_key'], 'material': dict(row),
        'mtr_document': mtrs.get(_key(row['mtr_reference']))} for row in state['materials']}


def _material_pass_blockers(state, material):
    """Evidence prerequisites, independent of the previous inspection result."""
    blockers = []
    if not material['persisted']:
        blockers.append('Save this physical material record before recording QA-001.')
    if state['source_status']['changed']:
        blockers.append('Adopt and review the current BOM before approving this piece.')
    if not material['heat_number'].strip():
        blockers.append('Enter and save this piece\'s heat number before Pass.')
    if not material['mtr_reference'].strip():
        blockers.append('Enter and save this piece\'s MTR reference before Pass.')
    return blockers


def material_qa_states(s, state, user=None, *, bases=None):
    """Per-piece decisions: sibling edits never change this piece's basis."""
    bases = _material_qa_bases(s, state) if bases is None else bases
    latest = _current_material_inspections(s, state['item'].id)
    permitted = has_capability(user, 'quality_review') and not _locked_reason(s, state['item'])
    result = {}
    for material in state['materials']:
        key = material['piece_key']
        pass_blockers = _material_pass_blockers(state, material)
        blockers = list(pass_blockers)
        digest = _digest(bases[key])
        decision = latest.get(key)
        current = bool(decision and decision.result == 'Pass' and decision.basis_sha256 == digest and not blockers)
        status = ('pending' if decision is None else 'failed' if decision.result == 'Fail'
                  else 'passed' if current else 'needs_reinspection')
        if status == 'pending':
            blockers.insert(0, 'QA-001 has not been recorded for this physical piece.')
        elif status == 'failed':
            blockers.insert(0, 'QA-001 failed. Correct the findings and record a new inspection.')
        elif status == 'needs_reinspection':
            blockers.insert(0, 'This piece or its source/MTR evidence changed after QA-001 Pass. Reinspection is required.')
        result[key] = {'code': 'QA-001', 'version': decision.version if decision else 0,
            'status': status, 'can_proceed': current, 'basis_sha256': digest,
            'latest': _material_inspection_view(decision), 'blockers': blockers, 'pass_blockers': pass_blockers,
            'history_url': f'/api/spool-boms/spools/{quote(state["item"].id, safe="")}/materials/{quote(key, safe="")}/qa-001',
            'permissions': {'can_inspect': bool(permitted and material['persisted'])}}
    return result


@read_cached(lambda s, item: item.id)
def _basis(s, item):
    from spool_boms import physical_bom_state, spool_bom_basis
    from spool_documents import spool_document_scope_basis
    state = physical_bom_state(s, item.id)
    materials = state['materials']
    source = state['source_status']
    blockers = []
    if not state['definition']:
        blockers.append('Upload or extract a structured BOM for this physical spool.')
    elif not state['definition'].get('traceable', True):
        blockers.extend(state['definition'].get('trace_blockers', ['The physical material-piece basis needs review.']))
    if not state['trace']:
        blockers.append('Save the material register for this individual spool.')
    if source['changed']:
        blockers.append('The effective BOM has changed. Adopt and review its current revision for this spool.')
    missing = [row['piece_key'] for row in materials if not row['heat_number'].strip() or not row['mtr_reference'].strip()]
    if missing:
        blockers.append('Heat number and MTR reference are required for every material piece: ' + ', '.join(missing[:20]) + ('.' if len(missing) <= 20 else ' …'))
    if not materials:
        blockers.append('A complete physical material-piece register is required for arrival approval.')
    qa = material_qa_states(s, state)
    incomplete_qa = [row['piece_identifier'] for row in materials if not qa[row['piece_key']]['can_proceed']]
    if incomplete_qa:
        blockers.append('A current QA-001 Pass is required for every physical material piece: '
            + ', '.join(incomplete_qa[:20]) + ('.' if len(incomplete_qa) <= 20 else ' …'))
    evidence = {'spool_id': item.id, 'context': _receipt_context(s, state),
        'material_trace': spool_bom_basis(s, item.id),
        'current_bom_source': source['current'], 'pinned_bom_source': source['pinned'],
        'documents': spool_document_scope_basis(s, item.id),
        'mtr_documents': [_mtr_view(row, urls=False) for row in _current_mtrs(s, item.id)],
        'piece_inspections': [{'piece_key': row['piece_key'], 'piece_identifier': row['piece_identifier'],
            'version': qa[row['piece_key']]['version'], 'status': qa[row['piece_key']]['status'],
            'current_pass': qa[row['piece_key']]['can_proceed'],
            'basis_sha256': qa[row['piece_key']]['basis_sha256'],
            'inspection': qa[row['piece_key']]['latest']} for row in materials]}
    # Keep display-only URLs out of signed acceptance fingerprints.
    for key in ('current_bom_source', 'pinned_bom_source'):
        if evidence[key]:
            evidence[key] = {field: value for field, value in evidence[key].items()
                             if field not in ('download_url', 'view_url')}
    return evidence, list(dict.fromkeys(blockers))


@read_cached(lambda s, item, user=None, history=False: (item.id, reader_role(user), history))
def _physical_summary(s, item, user=None, history=False):
    from removals import require_active_item
    try:
        require_active_item(s, item.id)
    except HTTPException as error:
        if error.status_code != 409:
            raise
        # Removed records remain inspectable by history/list/packet readers.
        # Do not resolve an active document scope or imply an operational Pass.
        latest = _latest(s, item.id)
        return {'required': True, 'spool_id': item.id, 'version': latest.version if latest else 0,
            'status': 'removed', 'can_proceed': False, 'basis_sha256': '',
            'blockers': [str(error.detail)], 'latest': _inspection_view(latest),
            'history': ([_inspection_view(row) for row in s.scalars(select(SpoolArrivalInspection)
                .where(SpoolArrivalInspection.spool_id == item.id)
                .order_by(SpoolArrivalInspection.version.desc()).limit(50))] if history else []),
            'permissions': {'can_inspect': False}, 'checks_catalog': CHECKS}
    evidence, blockers = _basis(s, item)
    digest = _digest(evidence)
    latest = _latest(s, item.id)
    current = bool(latest and latest.result == 'Pass' and latest.basis_sha256 == digest and not blockers)
    if latest is None:
        status, message = 'pending', 'QA/QC arrival inspection has not been recorded.'
    elif latest.result == 'Fail':
        status, message = 'failed', 'The arrival inspection failed. QA/QC must record a new passing inspection after correction.'
    elif not current:
        status, message = 'needs_reinspection', 'The BOM, heat/MTR register or source evidence changed after the arrival Pass. QA/QC reinspection is required.'
    else:
        status, message = 'passed', ''
    if message:
        blockers.insert(0, message)
    result = {'required': True, 'spool_id': item.id, 'version': latest.version if latest else 0,
        'status': status, 'can_proceed': current, 'basis_sha256': digest,
        'blockers': list(dict.fromkeys(blockers)), 'latest': _inspection_view(latest),
        'history': [], 'permissions': {'can_inspect': has_capability(user, 'quality_review') and not _locked_reason(s, item)},
        'checks_catalog': CHECKS}
    if history:
        result['history'] = [_inspection_view(row) for row in s.scalars(select(SpoolArrivalInspection)
            .where(SpoolArrivalInspection.spool_id == item.id).order_by(SpoolArrivalInspection.version.desc()).limit(50))]
    return result


def receiving_summary(s, item, user=None):
    if is_physical_spool(s, item):
        return _physical_summary(s, item, user)
    children = _scope_items(s, item)
    summaries = [_physical_summary(s, child, user) for child in children]
    return {'required': bool(summaries), 'version': 0,
        'status': ('passed' if all(row['can_proceed'] for row in summaries) else 'pending') if summaries else 'not_applicable',
        'can_proceed': all(row['can_proceed'] for row in summaries),
        'blockers': [f"{row['spool_id']}: {message}" for row in summaries for message in row['blockers']],
        'children': summaries, 'latest': None, 'history': [], 'permissions': {'can_inspect': False}}


def receiving_errors(s, item, include_children=True):
    result = []
    for child in _scope_items(s, item, include_children):
        result.extend(f'{child.id}: {message}' for message in _physical_summary(s, child)['blockers'])
    return list(dict.fromkeys(result))


def require_receiving_pass(s, item):
    errors = receiving_errors(s, item)
    if errors:
        raise HTTPException(409, {'receiving_blockers': errors})


def receiving_scope_basis(s, item_id):
    result = []
    for item in _scope_items(s, read_get(s, Item, item_id)):
        summary = _physical_summary(s, item)
        result.append({'spool_id': item.id, 'basis_sha256': summary['basis_sha256'],
            'current_pass': summary['can_proceed'], 'inspection': summary['latest'],
            'mtr_documents': [_mtr_view(row, urls=False) for row in _current_mtrs(s, item.id)]})
    return result


def spool_mtr_scope_metadata(s, item_id):
    return [_mtr_view(row) for item in _scope_items(s, read_get(s, Item, item_id)) for row in _current_mtrs(s, item.id)]


def spool_mtr_retained_file(s, document_id):
    row = read_get(s, SpoolMtrDocument, document_id)
    file = read_get(s, SpoolMtrFile, document_id) if row else None
    if file is None or len(file.content) != row.size_bytes or hashlib.sha256(file.content).hexdigest() != row.sha256:
        raise HTTPException(503, 'The retained MTR could not be verified. Contact an administrator.')
    return {**_mtr_view(row, urls=False), 'content': file.content}


def spool_mtr_packet_files(s, item_id):
    return [spool_mtr_retained_file(s, metadata['document_id']) for metadata in spool_mtr_scope_metadata(s, item_id)]


def source_changed(s, scope, identity, actor, reason):
    """Stop running work on exactly the affected physical scope, never siblings by number."""
    from order_spools import OrderSpool
    from production import pause_receiving_scope
    from removals import item_not_removed
    from spool_boms import ensure_material_piece_records
    identities = [identity] if scope == 'spools' else list(s.scalars(
        select(OrderSpool.item_id).join(Item, Item.id == OrderSpool.item_id)
        .where(OrderSpool.requirement_id == identity, item_not_removed(Item.id))))
    s.flush()
    for item_id in sorted(set(identities)):
        item = read_get(s, Item, item_id)
        if item is not None:
            ensure_material_piece_records(s, item, actor, reason)
            pause_receiving_scope(s, item, actor, utcnow(), reason)


@router.post('/spools/{item_id}/materials/{piece_key}/qa-001', status_code=201)
def inspect_material(item_id: str, piece_key: str, data: MaterialInspectionIn,
                     user: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    from spool_boms import physical_bom_state, _spool_detail
    if not has_capability(user, 'quality_review'):
        raise HTTPException(403, 'Only QA/QC or an administrator can record QA-001.')
    lock_topology(s)
    item = lock_item(s, item_id)
    state = physical_bom_state(s, item.id)
    if _locked_reason(s, item):
        raise HTTPException(409, _locked_reason(s, item))
    bases = _material_qa_bases(s, state)
    qa = material_qa_states(s, state, user, bases=bases).get(piece_key)
    if qa is None:
        raise HTTPException(404, 'This physical material piece is not in the current pinned BOM.')
    if not qa['permissions']['can_inspect']:
        raise HTTPException(409, 'Save this physical material record before recording QA-001.')
    if data.expected_version != qa['version']:
        raise HTTPException(409, 'QA-001 changed for this piece. Reload before recording a new decision.')
    if data.basis_sha256 != qa['basis_sha256']:
        raise HTTPException(409, 'This material piece, BOM or MTR changed. Reload and inspect the current evidence.')
    basis = bases[piece_key]
    material = basis['material']
    if data.result == 'Pass' and (state['source_status']['changed']
            or not material['heat_number'].strip() or not material['mtr_reference'].strip()):
        raise HTTPException(409, 'QA-001 Pass requires this piece\'s current BOM, heat number and MTR reference.')
    row = SpoolMaterialInspection(spool_id=item.id, piece_key=piece_key,
        version=data.expected_version + 1, check_code='QA-001', result=data.result,
        actor=user.badge, reference=data.reference, notes=data.notes,
        basis_sha256=data.basis_sha256, basis=basis)
    s.add(row)
    s.flush()
    audit(s, item.id, user.badge, 'SPOOL_MATERIAL_QA001_INSPECTED', _material_inspection_view(row))
    source_changed(s, 'spools', item.id, user.badge, f'QA-001 {data.result} recorded for {material["piece_identifier"]}')
    result = _spool_detail(s, item.id, user)
    _commit(s)
    return result


@router.post('/spools/{item_id}/materials/qa-001/pass-all')
def pass_all_materials(item_id: str, data: MaterialPassAllIn,
                       user: Employee = Depends(auth), s: Session = Depends(db)):
    """One reviewed physical spool, validated in full before any QA event is added."""
    from flow import lock_topology
    from spool_boms import physical_bom_state, _spool_detail
    if not has_capability(user, 'quality_review'):
        raise HTTPException(403, 'Only QA/QC or an administrator can record QA-001.')
    lock_topology(s)
    # lock_topology refreshes employee authority after a queued write resumes.
    if not has_capability(user, 'quality_review'):
        raise HTTPException(403, 'Only QA/QC or an administrator can record QA-001.')
    item = lock_item(s, item_id)
    state = physical_bom_state(s, item.id)
    blockers = []
    locked = _locked_reason(s, item)
    if locked:
        blockers.append(locked)
    trace = state['trace']
    if data.expected_trace_version != (trace.version if trace else 0):
        blockers.append('Material traceability changed. Reload the saved rows before using PASS ALL.')
    if data.expected_bom_sha256 != state['source_status']['expected_bom_sha256']:
        blockers.append('The BOM source changed. Reload and review the current physical material records.')
    if not state['definition'] or not state['definition'].get('traceable', True) or not state['materials']:
        blockers.append('A current structured BOM with distinct physical material records is required for PASS ALL.')
    if state['source_status']['changed']:
        blockers.append('Adopt and review the current BOM before using PASS ALL.')

    bases = _material_qa_bases(s, state)
    states = material_qa_states(s, state, user, bases=bases)
    incoming = {row.piece_key: row for row in data.pieces}
    current_keys = set(states)
    if len(incoming) != len(data.pieces) or set(incoming) != current_keys:
        blockers.append('Supply every current physical piece exactly once, including pieces already at Pass; reload this spool.')
    piece_blockers = []
    for material in state['materials']:
        key = material['piece_key']
        qa = states[key]
        expected = incoming.get(key)
        errors = list(qa['pass_blockers'])
        if expected is None:
            errors.append('This physical piece was omitted from PASS ALL. Reload the complete spool record.')
        else:
            if expected.expected_version != qa['version']:
                errors.append('QA-001 changed for this piece. Reload and review its latest decision.')
            if expected.basis_sha256 != qa['basis_sha256']:
                errors.append('This piece, BOM or MTR evidence changed. Reload and inspect the current evidence.')
        if errors:
            piece_blockers.append({'piece_key': key, 'piece_identifier': material['piece_identifier'],
                'piece_label': material['piece_label'], 'blockers': errors})
    for key in sorted(set(incoming) - current_keys):
        piece_blockers.append({'piece_key': key, 'piece_identifier': None, 'piece_label': None,
            'blockers': ['This piece does not belong to the current pinned BOM of the selected physical spool.']})
    if blockers or piece_blockers:
        raise HTTPException(409, {'message': 'PASS ALL was not saved. Resolve the listed issues and review this spool again.',
            'blockers': blockers, 'piece_blockers': piece_blockers})

    # The lock protects every checked source and row until commit. Do not append
    # a redundant event for an already-current Pass or manufacture arrival QA.
    passed = [row['piece_key'] for row in state['materials'] if not states[row['piece_key']]['can_proceed']]
    unchanged = [row['piece_key'] for row in state['materials'] if states[row['piece_key']]['can_proceed']]
    now = utcnow()
    events = []
    for key in passed:
        event = SpoolMaterialInspection(spool_id=item.id, piece_key=key,
            version=states[key]['version'] + 1, check_code='QA-001', result='Pass',
            actor=user.badge, at=now, reference=data.reference, notes=data.notes,
            basis_sha256=states[key]['basis_sha256'], basis=bases[key])
        s.add(event)
        events.append(event)
    if events:
        s.flush()
        for event in events:
            audit(s, item.id, user.badge, 'SPOOL_MATERIAL_QA001_INSPECTED', _material_inspection_view(event))
        source_changed(s, 'spools', item.id, user.badge, 'QA-001 PASS ALL recorded for the reviewed physical material pieces')
    result = _spool_detail(s, item.id, user)
    result['qa001_bulk_result'] = {'spool_id': item.id, 'passed_count': len(passed),
        'already_passed_count': len(unchanged), 'passed_piece_keys': passed, 'already_passed_piece_keys': unchanged}
    _commit(s)
    return result


@router.get('/spools/{item_id}/materials/{piece_key}/qa-001')
def material_inspection_history(item_id: str, piece_key: str, user: Employee = Depends(auth), s: Session = Depends(db)):
    _context(s, item_id)
    rows = list(s.scalars(select(SpoolMaterialInspection).where(SpoolMaterialInspection.spool_id == item_id,
        SpoolMaterialInspection.piece_key == piece_key).order_by(SpoolMaterialInspection.version.desc()).limit(50)))
    return {'spool_id': item_id, 'piece_key': piece_key, 'code': 'QA-001',
            'history': [_material_inspection_view(row) for row in rows]}


@router.post('/spools/{item_id}/arrival-inspections', status_code=201)
def inspect_arrival(item_id: str, data: ArrivalIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    from spool_boms import _spool_detail
    if not has_capability(user, 'quality_review'):
        raise HTTPException(403, 'Only QA/QC or an administrator can record an arrival inspection.')
    lock_topology(s)
    item = lock_item(s, item_id)
    _context(s, item_id)
    locked = _locked_reason(s, item)
    if locked:
        raise HTTPException(409, locked)
    latest = _latest(s, item.id)
    if data.expected_version != (latest.version if latest else 0):
        raise HTTPException(409, 'The arrival inspection changed. Reload this spool before recording a new decision.')
    evidence, blockers = _basis(s, item)
    if data.basis_sha256 != _digest(evidence):
        raise HTTPException(409, 'The spool BOM, materials or MTRs changed. Reload and inspect the current evidence.')
    checks = data.checks.model_dump()
    if data.result == 'Pass' and (blockers or not all(checks.values())):
        errors = blockers + ([] if all(checks.values()) else ['Confirm every arrival inspection check before recording Pass.'])
        raise HTTPException(409, {'receiving_blockers': errors})
    row = SpoolArrivalInspection(spool_id=item.id, version=data.expected_version + 1,
        result=data.result, actor=user.badge, reference=data.reference, notes=data.notes,
        checks=checks, basis_sha256=data.basis_sha256, basis=evidence)
    s.add(row)
    s.flush()
    audit(s, item.id, user.badge, 'SPOOL_ARRIVAL_INSPECTED', _inspection_view(row))
    source_changed(s, 'spools', item.id, user.badge, 'Arrival inspection recorded: ' + data.result)
    result = _spool_detail(s, item.id, user)
    _commit(s)
    return result


def _prepare_mtr(files, context):
    from spool_documents import _prepare
    if not files or any(not (file.filename or '').lower().endswith(('.pdf', '.jpg', '.jpeg', '.png')) for file in files):
        raise HTTPException(415, 'MTR files must be PDF, PNG or JPEG pages.')
    return _prepare(files, 'isometric', '', context)


@router.post('/spools/{item_id}/mtr-preview')
def preview_mtr(item_id: str, files: list[UploadFile] = File(...), user: Employee = Depends(auth), s: Session = Depends(db)):
    if not _can_edit(user):
        raise HTTPException(403, 'Your position can view MTRs but cannot upload them.')
    context, item, _ = _context(s, item_id)
    prepared = _prepare_mtr(files, context)
    return {key: prepared[key] for key in ('selection_sha256', 'filename', 'page_count', 'size_bytes', 'sha256', 'media_type', 'source_files')}


@router.post('/spools/{item_id}/mtr-documents', status_code=201)
def upload_mtr(item_id: str, files: list[UploadFile] = File(...), reference: str = Form(...),
               expected_version: int = Form(...), expected_sha256: str = Form(...),
               revision: str = Form(''), reason: str = Form(...),
               user: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    from spool_boms import _spool_detail
    from spool_documents import MAX_SCOPE_BYTES, _safe_filename
    if not _can_edit(user):
        raise HTTPException(403, 'Your position can view MTRs but cannot upload them.')
    reference, revision, reason = reference.strip(), revision.strip(), reason.strip()
    if (not 2 <= len(reference) <= 300 or not 4 <= len(reason) <= 3000 or len(revision) > 80
            or expected_version < 0 or any(ord(char) < 32 for char in reference + revision)):
        raise HTTPException(422, 'Enter an MTR reference, a valid revision, and a 4–3,000-character upload reason.')
    initial, _, _ = _context(s, item_id)
    prepared = _prepare_mtr(files, initial)
    if prepared['selection_sha256'] != expected_sha256:
        raise HTTPException(409, 'The MTR file selection changed. Preview it again before saving.')
    lock_topology(s)
    s.expire_all()
    item = lock_item(s, item_id)
    context, _, _ = _context(s, item_id)
    if context != initial:
        raise HTTPException(409, 'The spool identity changed while the MTR was prepared. Reload this spool.')
    if not _can_edit(user):
        raise HTTPException(403, 'Your position cannot upload MTRs.')
    locked = _locked_reason(s, item)
    if locked:
        raise HTTPException(409, locked)
    latest = s.scalar(select(func.max(SpoolMtrDocument.version)).where(
        SpoolMtrDocument.spool_id == item.id, SpoolMtrDocument.reference_key == _key(reference))) or 0
    if expected_version != latest:
        raise HTTPException(409, 'This MTR reference has a newer saved revision. Reload before uploading.')
    used = s.scalar(select(func.sum(SpoolMtrDocument.size_bytes)).where(SpoolMtrDocument.spool_id == item.id)) or 0
    if used + prepared['size_bytes'] > MAX_SCOPE_BYTES:
        raise HTTPException(413, 'This spool MTR history exceeds the 256 MiB limit. Contact an administrator.')
    filename = prepared['filename'] if len(files) == 1 and (files[0].filename or '').lower().endswith('.pdf') else _safe_filename(reference + '-MTR.pdf')
    row = SpoolMtrDocument(id='mtr_' + uuid.uuid4().hex, spool_id=item.id,
        reference=reference, reference_key=_key(reference), version=latest + 1, revision=revision,
        filename=filename, media_type='application/pdf', size_bytes=prepared['size_bytes'],
        sha256=prepared['sha256'], selection_sha256=prepared['selection_sha256'], page_count=prepared['page_count'],
        source_files=prepared['source_files'], scope_snapshot=context, uploaded_by=user.badge, reason=reason)
    s.add(row)
    s.flush()
    s.add(SpoolMtrFile(document_id=row.id, content=prepared['content']))
    audit(s, item.id, user.badge, 'SPOOL_MTR_UPLOADED', _mtr_view(row, urls=False))
    source_changed(s, 'spools', item.id, user.badge, 'MTR revision uploaded: ' + reference)
    result = _spool_detail(s, item.id, user)
    _commit(s)
    return result


@router.get('/mtr-files/{document_id}')
def mtr_file(document_id: str, download: bool = False, user: Employee = Depends(auth), s: Session = Depends(db)):
    row = read_get(s, SpoolMtrDocument, document_id)
    if row is None:
        raise HTTPException(404, 'MTR document not found.')
    _context(s, row.spool_id)
    retained = spool_mtr_retained_file(s, row.id)
    fallback = re.sub(r'[^a-zA-Z0-9._ -]', '_', row.filename)
    return Response(retained['content'], media_type='application/pdf', headers={
        'Content-Disposition': ('attachment' if download else 'inline') + f'; filename="{fallback}"; filename*=UTF-8\'\'{quote(row.filename)}',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'SAMEORIGIN', 'Content-Security-Policy': "frame-ancestors 'self'"})
