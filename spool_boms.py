"""Approved spool drawing BOMs and per-physical-piece material traceability.

Catalog entries are reference quantities for one spool. Recording a supplier,
heat or MTR never creates receipt, inventory allocation, weld work or QA
acceptance. A saved physical register pins its original approved definition;
each material piece and every correction belong to that exact spool ID.
"""
from copy import deepcopy
from datetime import timezone
from pathlib import Path
import hashlib
import json
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field, field_validator, model_validator
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, select
from sqlalchemy.orm import Session

from main import Base, Employee, Item, audit, auth, db, lock_item, utcnow
from orders import Input, OrderAssembly, OrderGpn, PurchaseOrder, _commit, _key, read_snapshot
from order_setup import OrderSpoolRequirement
from order_spools import OrderSpool, effective_parent_id, guard_registered_spool
from flow import lock_topology
from permissions import has_capability
from removals import require_active_gpn, require_active_item, require_active_project


router = APIRouter(prefix='/api/spool-boms', tags=['spool bills of materials'])
DATA_DIR = Path(__file__).resolve().parent / 'data' / 'spool-boms'
_CATALOG_BYTES = (DATA_DIR / '643-777-rev2.json').read_bytes()
_CATALOG = json.loads(_CATALOG_BYTES)
_CATALOG_HASH = hashlib.sha256(_CATALOG_BYTES).hexdigest()
_DEFINITIONS = {_key(row['spool_number']): row for row in _CATALOG['spools']}
MATERIAL_FIELDS = ('supplier', 'supplier_piece_id', 'heat_number', 'mtr_reference', 'mtr_url', 'notes')


class SpoolBomTrace(Base):
    __tablename__ = 'spool_bom_traces'
    spool_id = Column(String(60), ForeignKey('items.id'), primary_key=True)
    catalog_id = Column(String(160), nullable=False)
    spool_number = Column(String(160), nullable=False)
    source_sha256 = Column(String(64), nullable=False)
    definition = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class SpoolBomMaterial(Base):
    __tablename__ = 'spool_bom_materials'
    spool_id = Column(String(60), ForeignKey('spool_bom_traces.spool_id'), primary_key=True)
    piece_key = Column(String(32), primary_key=True)
    supplier = Column(String(160), nullable=False, default='')
    supplier_piece_id = Column(String(160), nullable=False, default='')
    heat_number = Column(String(160), nullable=False, default='')
    mtr_reference = Column(String(300), nullable=False, default='')
    mtr_url = Column(String(2000), nullable=False, default='')
    notes = Column(Text, nullable=False, default='')
    updated_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class SpoolBomEvent(Base):
    __tablename__ = 'spool_bom_events'
    spool_id = Column(String(60), ForeignKey('spool_bom_traces.spool_id'), primary_key=True)
    version = Column(Integer, primary_key=True)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    reason = Column(Text, nullable=False)
    changes = Column(JSON, nullable=False)


class MaterialIn(Input):
    piece_key: str = Field(min_length=1, max_length=32)
    supplier: str = Field(default='', max_length=160)
    supplier_piece_id: str = Field(default='', max_length=160)
    heat_number: str = Field(default='', max_length=160)
    mtr_reference: str = Field(default='', max_length=300)
    mtr_url: str = Field(default='', max_length=2000)
    notes: str = Field(default='', max_length=3000)

    @field_validator('mtr_url')
    @classmethod
    def document_link(cls, value):
        if value:
            try:
                parsed = urlsplit(value)
                if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                        or parsed.password is not None or any(c.isspace() for c in value)):
                    raise ValueError
                parsed.port
            except ValueError:
                raise ValueError('MTR document links must be valid HTTPS URLs without embedded login credentials')
        return value


class TraceabilityIn(Input):
    expected_version: int = Field(ge=0, le=2147483646, strict=True)
    reason: str = Field(min_length=4, max_length=3000)
    materials: list[MaterialIn] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def unique_pieces(self):
        keys = [row.piece_key for row in self.materials]
        if len(keys) != len(set(keys)):
            raise ValueError('Each material piece must be supplied exactly once')
        return self


def _definition(number):
    row = _DEFINITIONS.get(_key(number or ''))
    if row is None:
        return None
    result = {key: deepcopy(value) for key, value in _CATALOG.items() if key != 'spools'}
    result.update(deepcopy(row))
    result.update(catalog_sha256=_CATALOG_HASH, line_count=len(row['lines']),
                  total_pieces=sum(line['quantity'] for line in row['lines']))
    result['source_workbook']['download_url'] = '/api/spool-boms/workbooks/643-777-rev2.xlsx'
    return result


def _descriptor(definition, kind, identity):
    if definition is None:
        return None
    return {'catalog_id': definition['catalog_id'], 'spool_number': definition['spool_number'],
            'revision': definition['revision'], 'line_count': definition['line_count'],
            'api_url': f'/api/spool-boms/{kind}/{quote(identity, safe="")}'}


def requirement_bom_summary(requirement):
    return _descriptor(_definition(requirement.spool_number), 'requirements', requirement.id)


def item_bom_summary(item, s=None):
    if item.kind != 'Spool':
        return None
    trace = s.get(SpoolBomTrace, item.id) if s is not None else None
    definition = trace.definition if trace else _definition(item.google_part_number)
    if trace and _key(item.google_part_number or '') != _key(trace.spool_number):
        return None
    return _descriptor(definition, 'spools', item.id)


def guard_spool_bom_identity(s, item):
    trace = s.get(SpoolBomTrace, item.id)
    if trace and (item.kind != 'Spool' or _key(item.google_part_number or '') != _key(trace.spool_number)):
        raise HTTPException(409, 'This spool has recorded material traceability. Its saved BOM spool number must be retained.')


def _piece_definitions(definition):
    result = []
    for line in definition['lines']:
        for number in range(1, line['quantity'] + 1):
            result.append({'piece_key': f'{line["item"]}-{number}', 'item': line['item'],
                'piece_number': number, 'pieces_on_line': line['quantity'],
                **{key: line[key] for key in ('tas_ln_number', 'description', 'material', 'length_inches', 'length_display')}})
    return result


def _stamp(value):
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat() if value is not None else None


def _materials(s, spool_id, definition):
    saved = {row.piece_key: row for row in s.scalars(
        select(SpoolBomMaterial).where(SpoolBomMaterial.spool_id == spool_id))}
    result = []
    for piece in _piece_definitions(definition):
        row = saved.get(piece['piece_key'])
        result.append({**piece, **{key: getattr(row, key) if row else '' for key in MATERIAL_FIELDS},
                       'updated_by': row.updated_by if row else None,
                       'updated_at': _stamp(row.updated_at) if row else None})
    return result


def spool_bom_basis(s, spool_id):
    """Stable, saved physical trace basis for packet fingerprints; no writes."""
    trace = s.get(SpoolBomTrace, spool_id)
    if trace is None:
        return None
    return {'catalog_id': trace.catalog_id, 'spool_number': trace.spool_number,
            'source_sha256': trace.source_sha256, 'version': trace.version,
            'materials': _materials(s, spool_id, trace.definition)}


def spool_bom_trace_records(s, spool_id):
    basis = spool_bom_basis(s, spool_id)
    return [{'spool_id': spool_id, **row} for row in basis['materials']] if basis else []


def spool_bom_scope_basis(s, item_id, seen=None):
    """Saved trace basis for a physical spool or its assembly's active spools."""
    from order_spools import effective_children
    seen = set(seen or ())
    if item_id in seen:
        return []
    seen.add(item_id)
    item = s.get(Item, item_id)
    if item is None:
        return []
    if item.kind == 'Spool':
        basis = spool_bom_basis(s, item.id)
        return [{'spool_id': item.id, **basis}] if basis else []
    if item.kind != 'Assembly':
        return []
    bases = []
    for child, _ in effective_children(s, item.id, include_removed=False):
        bases.extend(spool_bom_scope_basis(s, child.id, seen))
    return sorted({basis['spool_id']: basis for basis in bases}.values(), key=lambda basis: basis['spool_id'])


def _can_edit(user):
    return has_capability(user, 'allocate_parts') or has_capability(user, 'inspect')


def _locked_reason(s, item):
    if item.released:
        return 'This spool is released. Return it to work before changing its material traceability.'
    parent_id = effective_parent_id(s, item.id)
    parent = s.get(Item, parent_id) if parent_id else None
    if parent and parent.released:
        return 'The parent assembly is released. Return it to work before changing child material traceability.'
    return ''


def _spool(s, item_id):
    item = s.get(Item, item_id)
    if item is None or item.kind != 'Spool':
        raise HTTPException(404, 'Spool not found')
    require_active_item(s, item.id)
    guard_registered_spool(s, item)
    guard_spool_bom_identity(s, item)
    trace = s.get(SpoolBomTrace, item.id)
    definition = deepcopy(trace.definition) if trace else _definition(item.google_part_number)
    if definition is None:
        raise HTTPException(404, 'No approved bill of materials is linked to this spool number')
    registration = s.get(OrderSpool, item.id)
    parent_id = effective_parent_id(s, item.id)
    mapping = s.get(OrderAssembly, parent_id) if parent_id else None
    group = s.get(OrderGpn, mapping.gpn_id) if mapping else None
    order = s.get(PurchaseOrder, item.project)
    context = {'kind': 'spool', 'item_id': item.id,
        'requirement_id': registration.requirement_id if registration else None,
        'assembly_id': parent_id, 'assembly_number': group.gpn if group else None,
        'project_id': item.project, 'purchase_order': order.purchase_order if order else None}
    return item, trace, definition, context


def _spool_detail(s, item_id, user):
    item, trace, definition, context = _spool(s, item_id)
    materials = _materials(s, item.id, definition)
    locked = _locked_reason(s, item)
    history = list(s.scalars(select(SpoolBomEvent).where(SpoolBomEvent.spool_id == item.id)
                  .order_by(SpoolBomEvent.version.desc()).limit(50)))
    return {**definition, 'context': context, 'traceability': {
        'configured': trace is not None, 'version': trace.version if trace else 0,
        'editable': _can_edit(user) and not locked, 'locked_reason': locked,
        'complete': all(row['heat_number'] and row['mtr_reference'] for row in materials),
        'materials': materials, 'history': [{'version': event.version, 'actor': event.actor,
            'at': _stamp(event.at), 'reason': event.reason, 'changes': event.changes} for event in history]}}


@router.get('/workbooks/643-777-rev2.xlsx')
def approved_workbook(user: Employee = Depends(auth)):
    filename = _CATALOG['source_workbook']['filename']
    path = DATA_DIR / filename
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != _CATALOG['source_workbook']['sha256']:
        raise HTTPException(503, 'The approved BOM workbook is unavailable. Please contact an administrator.')
    return FileResponse(path, filename=filename,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Cache-Control': 'private, no-store'})


@router.get('/requirements/{requirement_id}')
def requirement_bom(requirement_id: str, user: Employee = Depends(auth), s: Session = Depends(db)):
    s.rollback()
    with read_snapshot(s) as snapshot:
        requirement = snapshot.get(OrderSpoolRequirement, requirement_id)
        if requirement is None or not requirement.active:
            raise HTTPException(404, 'Active spool requirement not found')
        group = snapshot.get(OrderGpn, requirement.gpn_id)
        if group is None:
            raise HTTPException(404, 'Assembly number not found')
        require_active_gpn(snapshot, group.id)
        require_active_project(snapshot, group.project_id)
        definition = _definition(requirement.spool_number)
        if definition is None:
            raise HTTPException(404, 'No approved bill of materials is linked to this spool number')
        order = snapshot.get(PurchaseOrder, group.project_id)
        return {**definition, 'context': {'kind': 'requirement', 'requirement_id': requirement.id,
            'assembly_id': None, 'assembly_number': group.gpn, 'project_id': group.project_id,
            'purchase_order': order.purchase_order if order else None}}


@router.get('/spools/{item_id}')
def spool_bom(item_id: str, user: Employee = Depends(auth), s: Session = Depends(db)):
    role = user.role
    s.rollback()
    with read_snapshot(s) as snapshot:
        return _spool_detail(snapshot, item_id, role)


@router.put('/spools/{item_id}/traceability')
def save_traceability(item_id: str, data: TraceabilityIn,
                      user: Employee = Depends(auth), s: Session = Depends(db)):
    if not _can_edit(user):
        raise HTTPException(403, 'Only material coordinators, supervisors, administrators and QA/QC can update material traceability.')
    lock_topology(s)
    lock_item(s, item_id)
    item, trace, definition, _ = _spool(s, item_id)
    locked = _locked_reason(s, item)
    if locked:
        raise HTTPException(409, locked)
    version = trace.version if trace else 0
    if data.expected_version != version:
        raise HTTPException(409, 'Material traceability has changed. Reload the saved BOM before applying your changes.')
    pieces = _piece_definitions(definition)
    incoming = {row.piece_key: row.model_dump(exclude={'piece_key'}) for row in data.materials}
    if set(incoming) != {row['piece_key'] for row in pieces}:
        raise HTTPException(422, 'Supply each physical material piece from this spool BOM exactly once')
    current = {row['piece_key']: row for row in _materials(s, item.id, definition)}
    changes = []
    for piece in pieces:
        key = piece['piece_key']
        before = {field: current[key][field] for field in MATERIAL_FIELDS}
        after = incoming[key]
        if before != after:
            changes.append({'piece_key': key, 'before': before, 'after': after})
    if not changes:
        raise HTTPException(400, 'No material traceability changes to save')
    now = utcnow()
    if trace is None:
        trace = SpoolBomTrace(spool_id=item.id, catalog_id=definition['catalog_id'],
            spool_number=definition['spool_number'], source_sha256=definition['source_workbook']['sha256'],
            definition=deepcopy(definition), version=1, created_by=user.badge, updated_by=user.badge,
            created_at=now, updated_at=now)
        s.add(trace)
        s.flush()
        for piece in pieces:
            s.add(SpoolBomMaterial(spool_id=item.id, piece_key=piece['piece_key'],
                **incoming[piece['piece_key']], updated_by=user.badge, updated_at=now))
    else:
        trace.version += 1
        trace.updated_by, trace.updated_at = user.badge, now
        for change in changes:
            row = s.get(SpoolBomMaterial, (item.id, change['piece_key']))
            if row is None:
                raise HTTPException(409, 'The saved material register is incomplete. Contact an administrator before changing it.')
            for field, value in change['after'].items():
                setattr(row, field, value)
            row.updated_by, row.updated_at = user.badge, now
    s.add(SpoolBomEvent(spool_id=item.id, version=trace.version, actor=user.badge,
        at=now, reason=data.reason, changes=changes))
    audit(s, item.id, user.badge, 'SPOOL_BOM_TRACEABILITY_UPDATED', {
        'catalog_id': trace.catalog_id, 'version': trace.version, 'reason': data.reason, 'changes': changes})
    _commit(s)
    return _spool_detail(s, item.id, user)
