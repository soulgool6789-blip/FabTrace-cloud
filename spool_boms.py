"""Spool drawing BOMs and per-physical-piece material traceability.

Catalog entries are reference quantities for one spool. Recording a supplier,
heat or MTR never creates receipt, inventory allocation, weld work or QA
acceptance. A saved physical register pins its original source definition;
each material piece and every correction belong to that exact spool ID.
"""
from copy import deepcopy
from datetime import timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import json
import secrets
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field, field_validator, model_validator
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, or_, select
from sqlalchemy.orm import Session
from read_projection import read_cached, read_get, projection_get, PROJECTION_MISSING

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
HEAT_REQUIRED_FROM_STEP = 15
HEAT_REQUIRED_AT_LABEL = 'QA/QC-003 - Inspect Welds'


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


class MaterialQaGuardIn(Input):
    piece_key: str = Field(min_length=1, max_length=32)
    expected_version: int = Field(ge=0, le=2147483646, strict=True)
    basis_sha256: str = Field(min_length=64, max_length=64)


class TraceabilityIn(Input):
    expected_version: int = Field(ge=0, le=2147483646, strict=True)
    reason: str = Field(min_length=4, max_length=3000)
    materials: list[MaterialIn] = Field(min_length=1, max_length=500)
    expected_bom_sha256: str = Field(default='', max_length=64)
    qa001_guard: MaterialQaGuardIn | None = None

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
    result['_source'] = {'kind': 'catalog', 'document_id': None,
        'sha256': result['source_workbook']['sha256'], 'catalog_sha256': _CATALOG_HASH,
        'filename': result['source_workbook']['filename'], 'revision': result['revision'],
        'download_url': result['source_workbook']['download_url'], 'structured': True}
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
    from spool_receiving import is_physical_spool, physical_spool_number
    if s is None or not is_physical_spool(s, item):
        return None
    from order_spools import spool_qr_identity
    qr = spool_qr_identity(s, item.id)
    trace = read_get(s, SpoolBomTrace, item.id)
    return {'api_url': '/api/spool-boms/spools/' + quote(item.id, safe=''),
        'item_id': item.id, 'spool_number': physical_spool_number(s, item),
        'qr_alias': qr.display_code if qr else None, 'display_code': qr.display_code if qr else item.id,
        'catalog_id': trace.catalog_id if trace else '',
        'revision': trace.definition.get('revision', '') if trace else '',
        'line_count': len(trace.definition.get('lines', [])) if trace else 0}


def guard_spool_bom_identity(s, item, values=None):
    from spool_receiving import is_physical_spool, physical_spool_number
    trace = read_get(s, SpoolBomTrace, item.id)
    if trace and (not is_physical_spool(s, item) or _key(physical_spool_number(s, item, values)) != _key(trace.spool_number)):
        raise HTTPException(409, 'This spool has recorded material traceability. Its saved BOM spool number must be retained.')


def _piece_definitions(definition):
    result = []
    if not definition or not definition.get('traceable', True):
        return result
    for line_number, line in enumerate(definition['lines'], 1):
        for number in range(1, line['quantity'] + 1):
            result.append({'piece_key': f'{line.get("piece_key_prefix", line["item"])}-{number}', 'item': line['item'],
                'line_number': line_number, 'piece_number': number, 'pieces_on_line': line['quantity'],
                'piece_label': f'Item {line["item"]} · Piece {number:03d} of {line["quantity"]:03d}',
                **{key: line.get(key, '') for key in ('tas_ln_number', 'description', 'material', 'length_inches', 'length_display')},
                'part_number': line.get('part_number', line.get('tas_ln_number', '')),
                'size': line.get('size', ''), 'unit': line.get('unit', 'EA')})
    return result


def _source_hash(source):
    stable = {key: source.get(key) for key in ('kind', 'document_id', 'sha256', 'catalog_sha256')} if source else None
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _uploaded_definition(document, context):
    bom = document.bom or {}
    if not bom.get('lines'):
        return None
    lines, blockers, total = [], [], 0
    for index, source in enumerate(bom['lines'], 1):
        quantity = source.get('quantity')
        try:
            value = Decimal(str(quantity))
            whole = value.is_finite() and value > 0 and value == value.to_integral_value() and value <= 500
        except (InvalidOperation, ValueError):
            whole = False
        unit = str(source.get('unit') or 'EA').strip()
        if not whole or _key(unit) not in ('ea', 'each', 'pc', 'pcs', 'piece', 'pieces', 'no', 'nos'):
            blockers.append(f'BOM line {index}: confirm a positive whole-piece quantity and piece unit before material traceability. The source quantity was retained unchanged.')
        safe_quantity = int(value) if whole else quantity
        if whole:
            total += safe_quantity
        prefix = 'L' + hashlib.sha256(f'{document.id}:{document.sha256}:{index}'.encode()).hexdigest()[:20]
        lines.append({**deepcopy(source), 'quantity': safe_quantity, 'piece_key_prefix': prefix,
            'tas_ln_number': str(source.get('part_number') or ''),
            'length_display': str(source.get('length') or ''), 'length_inches': None,
            'unit': unit, 'item': str(source.get('item') or index)})
    if total > 500:
        blockers.append('The BOM exceeds the 500-piece material-register limit. Review a smaller explicit physical-piece scope; quantities were not rounded or truncated.')
    metadata = _document_source(document)
    return {'catalog_id': 'uploaded:' + document.id, 'spool_number': context['spool_number'],
        'revision': document.revision, 'lines': lines, 'line_count': len(lines),
        'total_pieces': total if not blockers else None, 'traceable': not blockers,
        'trace_blockers': blockers, '_source': metadata,
        'source_workbook': {'filename': document.filename, 'sha256': document.sha256,
                            'download_url': metadata['download_url']}}


def _document_source(document):
    return {'kind': 'uploaded', 'document_id': document.id, 'sha256': document.sha256,
        'filename': document.filename, 'revision': document.revision,
        'structured': bool((document.bom or {}).get('lines')),
        'download_url': '/api/spool-documents/files/' + quote(document.id, safe='') + '?download=1'}


@read_cached(lambda s, item_id: item_id)
def physical_bom_state(s, item_id):
    """Current/pinned source and physical rows without receiving projection recursion."""
    from spool_documents import _target, _material_bom_document
    context, item, requirement = _target(s, 'spools', item_id)
    trace = read_get(s, SpoolBomTrace, item.id)
    viewed_document, document, _ = _material_bom_document(s, item.id, requirement)
    current_definition = _uploaded_definition(document, context) if document else _definition(context['spool_number'])
    current = _document_source(document) if document else deepcopy((current_definition or {}).get('_source'))
    viewed = ({**_document_source(viewed_document),
               'view_url': '/api/spool-documents/files/' + quote(viewed_document.id, safe='')}
              if viewed_document is not None else None)
    uses_shared = bool(viewed_document is not None and document is not None and viewed_document.id != document.id)
    definition = deepcopy(trace.definition) if trace else current_definition
    pinned = deepcopy((definition or {}).get('_source')) if trace else None
    if trace and not pinned:
        # Existing 777 trace definitions predate this additive source metadata.
        workbook = definition.get('source_workbook') or {}
        pinned = {'kind': 'catalog', 'document_id': None, 'sha256': trace.source_sha256,
            'catalog_sha256': definition.get('catalog_sha256', _CATALOG_HASH),
            'filename': workbook.get('filename', ''), 'revision': definition.get('revision', ''),
            'download_url': workbook.get('download_url', ''), 'structured': True}
    changed = bool(trace and _source_hash(pinned) != _source_hash(current))
    blockers = (current_definition or {}).get('trace_blockers', [])
    adoptable = bool(current_definition and current_definition.get('traceable', True))
    return {'item': item, 'trace': trace, 'definition': definition,
        'current_definition': current_definition, 'context': context,
        'materials': _materials(s, item.id, definition),
        'source_status': {'current': current, 'pinned': pinned, 'changed': changed,
            'viewed_bom': viewed, 'uses_shared_structured_bom': uses_shared,
            'adoptable': adoptable, 'can_adopt': False,
            'blocked_reason': ' '.join(blockers) if blockers else '' if adoptable else 'Upload or extract a structured whole-piece BOM.',
            'expected_bom_sha256': _source_hash(current)}}


def _stamp(value):
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _materials(s, spool_id, definition):
    rows = projection_get(s, 'bom_materials', spool_id)
    if rows is PROJECTION_MISSING:
        rows = s.scalars(select(SpoolBomMaterial).where(SpoolBomMaterial.spool_id == spool_id))
    saved = {row.piece_key: row for row in rows}
    result = []
    source = (definition or {}).get('_source') or {
        'kind': 'catalog', 'sha256': ((definition or {}).get('source_workbook') or {}).get('sha256'),
        'catalog_sha256': (definition or {}).get('catalog_sha256')}
    source_stamp = _source_hash(source)[:8].upper()
    for piece in _piece_definitions(definition):
        row = saved.get(piece['piece_key'])
        result.append({**piece, **{key: getattr(row, key) if row else '' for key in MATERIAL_FIELDS},
                       'piece_identifier': f'{spool_id}/MAT-{source_stamp}-{piece["line_number"]:03d}-{piece["piece_number"]:03d}',
                       'persisted': row is not None,
                       'updated_by': row.updated_by if row else None,
                       'updated_at': _stamp(row.updated_at) if row else None})
    return result


BACKFILL_ACTOR = 'system:material-piece-backfill'


def ensure_system_backfill_actor(s):
    """Attribute automatic blank-record creation without changing human accounts."""
    actor = read_get(s, Employee, BACKFILL_ACTOR)
    if actor is None:
        from main import password_hash
        actor = Employee(badge=BACKFILL_ACTOR, name='Automatic material record setup',
            role='misc', active=False, pin_hash=password_hash.hash(secrets.token_urlsafe(48)))
        s.add(actor)
        s.flush()
    elif actor.active or actor.role != 'misc':
        raise RuntimeError('The material backfill system identity must be disabled and have the misc role.')
    return actor.badge


def ensure_material_piece_records(s, item_or_id, actor, reason, *, uploaded_only=True):
    """Persist blank physical pieces once; caller holds topology and owns commit.

    An existing pin is never replaced or filled from another source. Revisions
    continue through the explicit adoption workflow, which keeps old history.
    """
    from spool_receiving import is_physical_spool
    item = read_get(s, Item, item_or_id) if isinstance(item_or_id, str) else item_or_id
    if not is_physical_spool(s, item) or read_get(s, SpoolBomTrace, item.id) is not None:
        return 0
    state = physical_bom_state(s, item.id)
    definition, source = state['current_definition'], state['source_status']['current']
    if (not definition or not definition.get('traceable', True)
            or uploaded_only and (not source or source['kind'] != 'uploaded')):
        return 0
    pieces = _piece_definitions(definition)
    if not pieces:
        return 0
    if actor == BACKFILL_ACTOR:
        actor = ensure_system_backfill_actor(s)
    now = utcnow()
    trace = SpoolBomTrace(spool_id=item.id, catalog_id=definition['catalog_id'],
        spool_number=definition['spool_number'], source_sha256=definition['source_workbook']['sha256'],
        definition=deepcopy(definition), version=1, created_by=actor, updated_by=actor,
        created_at=now, updated_at=now)
    s.add(trace)
    s.flush()
    for piece in pieces:
        s.add(SpoolBomMaterial(spool_id=item.id, piece_key=piece['piece_key'],
            **{key: '' for key in MATERIAL_FIELDS}, updated_by=actor, updated_at=now))
    changes = [{'type': 'pieces_initialized', 'source': source, 'piece_count': len(pieces),
                'after_definition': deepcopy(definition), 'material_values_blank': True}]
    s.add(SpoolBomEvent(spool_id=item.id, version=1, actor=actor, at=now, reason=reason, changes=changes))
    audit(s, item.id, actor, 'SPOOL_MATERIAL_PIECES_INITIALIZED', {
        'source': source, 'piece_count': len(pieces), 'reason': reason, 'material_values_blank': True})
    s.flush()
    return len(pieces)


def backfill_material_piece_records(s, actor=BACKFILL_ACTOR, *, batch_size=100):
    """Bound memory while initializing existing uploaded BOMs; no acceptance."""
    from tracking import SpoolPlan
    from removals import item_not_removed, require_active_item
    if not 1 <= batch_size <= 500:
        raise ValueError('Material backfill batch_size must be between 1 and 500.')
    last_id = ''
    result = {'created_spools': 0, 'created_pieces': 0, 'skipped': 0, 'unavailable': 0}
    while True:
        ids = list(s.scalars(select(Item.id).where(Item.id > last_id, Item.kind != 'Assembly',
            or_(Item.kind == 'Spool', select(SpoolPlan.item_id).where(SpoolPlan.item_id == Item.id).exists(),
                select(OrderSpool.item_id).where(OrderSpool.item_id == Item.id).exists()),
            ~select(SpoolBomTrace.spool_id).where(SpoolBomTrace.spool_id == Item.id).exists(),
            item_not_removed(Item.id)).order_by(Item.id).limit(batch_size)))
        if not ids:
            break
        for item_id in ids:
            try:
                require_active_item(s, item_id)
                count = ensure_material_piece_records(s, item_id, actor,
                    'Initialize distinct blank pieces from the already uploaded physical BOM.')
            except HTTPException as error:
                if error.status_code not in (404, 409):
                    raise
                result['unavailable'] += 1
                continue
            result['created_spools'] += bool(count)
            result['created_pieces'] += count
            result['skipped'] += not bool(count)
        last_id = ids[-1]
    return result


@read_cached(lambda s, spool_id: spool_id)
def spool_bom_basis(s, spool_id):
    """Stable, saved physical trace basis for packet fingerprints; no writes."""
    trace = read_get(s, SpoolBomTrace, spool_id)
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
    item = read_get(s, Item, item_id)
    if item is None:
        return []
    from spool_receiving import is_physical_spool
    if is_physical_spool(s, item):
        basis = spool_bom_basis(s, item.id)
        return [{'spool_id': item.id, **basis}] if basis else []
    if item.kind != 'Assembly':
        return []
    bases = []
    for child, _ in effective_children(s, item.id, include_removed=False):
        bases.extend(spool_bom_scope_basis(s, child.id, seen))
    return sorted({basis['spool_id']: basis for basis in bases}.values(), key=lambda basis: basis['spool_id'])


@read_cached(lambda s, item, include_children=True: (item.id, include_children))
def spool_heat_errors(s, item, include_children=True):
    """Post-fabrication heat completeness for exactly the active physical scope."""
    from spool_receiving import _scope_items
    try:
        require_active_item(s, item.id)
    except HTTPException as error:
        if error.status_code != 409:
            raise
        # Historical readers retain the record and its block without resolving
        # an active BOM or making removed material eligible for release.
        return [f'{item.id}: {error.detail}']
    errors = []
    for spool in _scope_items(s, item, include_children):
        state = physical_bom_state(s, spool.id)
        if not state['trace'] or not state['materials']:
            errors.append(f'{spool.id}: Save the physical material-piece register and heat numbers before {HEAT_REQUIRED_AT_LABEL}.')
            continue
        if state['source_status']['changed']:
            errors.append(f'{spool.id}: Adopt the current BOM before verifying post-fabrication heat numbers.')
        for piece in state['materials']:
            if not piece['persisted'] or not piece['heat_number'].strip():
                errors.append(f'{spool.id}: Record the heat number for {piece["piece_identifier"]} before {HEAT_REQUIRED_AT_LABEL}.')
    return list(dict.fromkeys(errors))


def _can_edit(user):
    return has_capability(user, 'allocate_parts') or has_capability(user, 'inspect')


def _locked_reason(s, item):
    if item.released:
        return 'This spool is released. Return it to work before changing its material traceability.'
    parent_id = effective_parent_id(s, item.id)
    parent = read_get(s, Item, parent_id) if parent_id else None
    if parent and parent.released:
        return 'The parent assembly is released. Return it to work before changing child material traceability.'
    return ''


def _spool(s, item_id):
    state = physical_bom_state(s, item_id)
    return state['item'], state['trace'], state['definition'], state['context']


def _spool_detail(s, item_id, user):
    from spool_receiving import _physical_summary, mtr_detail, material_qa_states
    from flow import flow_stage_for_item
    from flow_stages import stage_status
    state = physical_bom_state(s, item_id)
    item, trace, definition, context = (state[key] for key in ('item', 'trace', 'definition', 'context'))
    qa = material_qa_states(s, state, user)
    arrival = _physical_summary(s, item, user, history=True)
    flow_stage = flow_stage_for_item(s, item, receiving=arrival)
    # Presentation only: saved material/evidence fingerprints remain independent
    # of production movement. Each piece keeps its own incoming QA status.
    materials = [{**row, 'qa001': qa[row['piece_key']],
                  'flow_stage': (dict(flow_stage) if qa[row['piece_key']]['can_proceed']
                                 else stage_status('qa_001', item.id))}
                 for row in state['materials']]
    from order_spools import spool_qr_identity
    qr = spool_qr_identity(s, item.id)
    display_context = {**context, 'qr_alias': qr.display_code if qr else None,
                       'display_code': qr.display_code if qr else item.id}
    locked = _locked_reason(s, item)
    history = list(s.scalars(select(SpoolBomEvent).where(SpoolBomEvent.spool_id == item.id)
                  .order_by(SpoolBomEvent.version.desc()).limit(50)))
    source_status = {**state['source_status'], 'can_adopt': bool(trace and state['source_status']['changed']
        and state['source_status']['adoptable'] and _can_edit(user) and not locked)}
    base = definition or {'spool_number': context['spool_number'], 'revision': '', 'lines': [],
                           'line_count': 0, 'total_pieces': None, 'traceable': False}
    return {**base, 'context': display_context, 'bom_available': definition is not None,
        'flow_stage': flow_stage,
        'source_status': source_status, 'arrival': arrival,
        'mtr_documents': mtr_detail(s, item, user), 'traceability': {
        'configured': trace is not None, 'version': trace.version if trace else 0,
        'editable': bool(_can_edit(user) and not locked and definition and definition.get('traceable', True)
                         and not source_status['changed']),
        'locked_reason': locked or ('Adopt the current BOM before editing its material register.' if source_status['changed'] else source_status['blocked_reason']),
        'complete': bool(trace and materials and not source_status['changed']
                         and all(row['heat_number'] and row['mtr_reference'] for row in materials)),
        'receiving_complete': bool(trace and materials and not source_status['changed']
                                  and all(row['persisted'] and row['mtr_reference'].strip() for row in materials)),
        'heat_numbers_complete': bool(trace and materials and not source_status['changed']
                                     and all(row['persisted'] and row['heat_number'].strip() for row in materials)),
        'heat_required_for_receiving': False, 'heat_required_from_step': HEAT_REQUIRED_FROM_STEP,
        'heat_required_at_label': HEAT_REQUIRED_AT_LABEL,
        'materials': materials, 'history': [{'version': event.version, 'actor': event.actor,
            'at': _stamp(event.at), 'reason': event.reason,
            'detail_url': f'/api/spool-boms/spools/{quote(item.id, safe="")}/history/{event.version}',
            'changes': [{key: value for key, value in change.items()
                         if key not in ('before_definition', 'before_materials', 'after_definition')}
                        for change in event.changes]} for event in history]}}


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
    state = physical_bom_state(s, item_id)
    item, trace, definition = state['item'], state['trace'], state['definition']
    locked = _locked_reason(s, item)
    if locked:
        raise HTTPException(409, locked)
    version = trace.version if trace else 0
    if data.expected_version != version:
        raise HTTPException(409, 'Material traceability has changed. Reload the saved BOM before applying your changes.')
    if not definition or not definition.get('traceable', True):
        raise HTTPException(409, state['source_status']['blocked_reason'])
    if state['source_status']['changed']:
        raise HTTPException(409, 'The current BOM changed. Adopt its new revision before editing traceability.')
    # Older catalog-only clients remain safe because that in-process source is
    # immutable. Uploaded BOMs always require the exact reviewed source token.
    if ((data.expected_bom_sha256 or state['source_status']['current']['kind'] == 'uploaded')
            and data.expected_bom_sha256 != state['source_status']['expected_bom_sha256']):
        raise HTTPException(409, 'The BOM source changed. Reload and review the current material rows.')
    if data.qa001_guard is not None:
        # A combined UI action must inspect the evidence it actually reviewed,
        # before its own material edit legitimately creates a fresh QA basis.
        from spool_receiving import material_qa_states
        guard = data.qa001_guard
        qa = material_qa_states(s, state, user).get(guard.piece_key)
        if qa is None or guard.expected_version != qa['version'] or guard.basis_sha256 != qa['basis_sha256']:
            raise HTTPException(409, 'QA-001 or this piece\'s BOM/MTR evidence changed. No material changes were saved; reload and review before Pass.')
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
    if data.qa001_guard is not None and any(change['piece_key'] != data.qa001_guard.piece_key for change in changes):
        raise HTTPException(409, 'Save heat/MTR and Pass can change only the reviewed piece. Save other material drafts separately.')
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
            row = read_get(s, SpoolBomMaterial, (item.id, change['piece_key']))
            if row is None:
                raise HTTPException(409, 'The saved material register is incomplete. Contact an administrator before changing it.')
            for field, value in change['after'].items():
                setattr(row, field, value)
            row.updated_by, row.updated_at = user.badge, now
    s.add(SpoolBomEvent(spool_id=item.id, version=trace.version, actor=user.badge,
        at=now, reason=data.reason, changes=changes))
    audit(s, item.id, user.badge, 'SPOOL_BOM_TRACEABILITY_UPDATED', {
        'catalog_id': trace.catalog_id, 'version': trace.version, 'reason': data.reason, 'changes': changes})
    from spool_receiving import source_changed
    source_changed(s, 'spools', item.id, user.badge, 'Material traceability changed: ' + data.reason)
    result = _spool_detail(s, item.id, user)
    _commit(s)
    return result


class AdoptBomIn(Input):
    expected_version: int = Field(ge=1, le=2147483646, strict=True)
    expected_bom_sha256: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=4, max_length=3000)


@router.post('/spools/{item_id}/adopt-bom')
def adopt_bom(item_id: str, data: AdoptBomIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    if not _can_edit(user):
        raise HTTPException(403, 'Your position cannot adopt a physical spool BOM.')
    lock_topology(s)
    lock_item(s, item_id)
    state = physical_bom_state(s, item_id)
    item, trace, definition = state['item'], state['trace'], state['current_definition']
    if _locked_reason(s, item):
        raise HTTPException(409, _locked_reason(s, item))
    if not trace or trace.version != data.expected_version:
        raise HTTPException(409, 'The physical BOM register changed. Reload before adopting a new revision.')
    if data.expected_bom_sha256 != state['source_status']['expected_bom_sha256']:
        raise HTTPException(409, 'The uploaded BOM source changed. Reload before adopting its revision.')
    if not state['source_status']['changed'] or not state['source_status']['adoptable']:
        raise HTTPException(409, state['source_status']['blocked_reason'] or 'There is no different valid BOM to adopt.')
    before_definition, before_materials = deepcopy(trace.definition), deepcopy(state['materials'])
    changes = [{'type': 'bom_adopted', 'before_source': state['source_status']['pinned'],
        'after_source': state['source_status']['current'], 'before_definition': before_definition,
        'before_materials': before_materials, 'after_definition': deepcopy(definition),
        'previous_material_count': len(before_materials),
        'new_material_count': len(_piece_definitions(definition)),
        'traceability_reset': True}]
    for row in s.scalars(select(SpoolBomMaterial).where(SpoolBomMaterial.spool_id == item.id)):
        s.delete(row)
    s.flush()
    now = utcnow()
    trace.catalog_id, trace.spool_number = definition['catalog_id'], definition['spool_number']
    trace.source_sha256, trace.definition = definition['source_workbook']['sha256'], deepcopy(definition)
    trace.version += 1
    trace.updated_by, trace.updated_at = user.badge, now
    for piece in _piece_definitions(definition):
        s.add(SpoolBomMaterial(spool_id=item.id, piece_key=piece['piece_key'],
            **{key: '' for key in MATERIAL_FIELDS}, updated_by=user.badge, updated_at=now))
    s.add(SpoolBomEvent(spool_id=item.id, version=trace.version, actor=user.badge,
        at=now, reason=data.reason, changes=changes))
    audit(s, item.id, user.badge, 'SPOOL_BOM_ADOPTED', {'version': trace.version, 'reason': data.reason,
        'before_source': state['source_status']['pinned'], 'after_source': state['source_status']['current'],
        'material_traceability_reset': True})
    from spool_receiving import source_changed
    source_changed(s, 'spools', item.id, user.badge, 'New physical BOM adopted: ' + data.reason)
    result = _spool_detail(s, item.id, user)
    _commit(s)
    return result


@router.get('/spools/{item_id}/history/{version}')
def trace_history(item_id: str, version: int, user: Employee = Depends(auth), s: Session = Depends(db)):
    _spool(s, item_id)
    event = read_get(s, SpoolBomEvent, (item_id, version))
    if event is None:
        raise HTTPException(404, 'Material history revision not found.')
    return {'spool_id': item_id, 'version': event.version, 'actor': event.actor,
        'at': _stamp(event.at), 'reason': event.reason, 'changes': event.changes}

