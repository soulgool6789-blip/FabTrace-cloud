"""Optional per-spool parts quantities, tied to existing physical QR identities.

One allocation represents one individual Part. Receipt and preparation are
derived from recorded component steps, never from an editable completed count.
Scope edits retain immutable history and share the existing topology lock.
"""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from main import Base, Employee, Item, Rework, audit, auth, db, lock_item, utcnow, permit
from tracking import Project, SpoolPlan, TrackingHold, Weld, WeldWork, new_id
from flow import ComponentLink, FlowPlan, FlowEvent, FlowException, STEP_BY_NUMBER, lock_topology
from permissions import has_capability, require_capability

router = APIRouter(prefix='/api/parts', tags=['spool parts quantities'])
DEFINITIONS = {
    'unit': 'Whole physical pieces. Each assigned Part QR counts once.',
    'required': 'Quantities declared in the controlled spool parts list; missing physical items remain outstanding.',
    'assigned': 'Existing individual Part records assigned to this line and linked to this spool.',
    'received': 'Assigned parts with an actual recorded current-pass Receive Shipment step 1. A late baseline does not create receipt history.',
    'prepared': 'Assigned parts with recorded current-pass steps 7 and 8, a completed component route, matching identity/project and no current holds, rework or exceptions.',
    'short': 'Required pieces minus assigned physical pieces.',
    'remaining': 'Required pieces minus currently prepared pieces. This does not certify spool welding or final QA release.',
}


class SpoolPartsPlan(Base):
    __tablename__ = 'spool_parts_plans'
    spool_id = Column(String(60), ForeignKey('items.id'), primary_key=True)
    version = Column(Integer, nullable=False, default=1)
    reference = Column(String(500), nullable=False)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class PartLine(Base):
    __tablename__ = 'spool_part_lines'
    __table_args__ = (CheckConstraint('required_qty > 0 AND required_qty <= 10000', name='ck_spool_part_line_quantity'),)
    id = Column(String(60), primary_key=True)
    spool_id = Column(String(60), ForeignKey('spool_parts_plans.spool_id'), nullable=False, index=True)
    part_number = Column(String(160), nullable=False, default='')
    description = Column(String(500), nullable=False)
    required_qty = Column(Integer, nullable=False)
    notes = Column(Text, nullable=False, default='')
    active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class PartAllocation(Base):
    __tablename__ = 'spool_part_allocations'
    component_id = Column(String(60), ForeignKey('items.id'), primary_key=True)
    line_id = Column(String(60), ForeignKey('spool_part_lines.id'), nullable=False, index=True)
    assigned_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    assigned_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class PartEvent(Base):
    __tablename__ = 'spool_parts_events'
    __table_args__ = (UniqueConstraint('spool_id', 'sequence', name='uq_spool_parts_event_sequence'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    spool_id = Column(String(60), ForeignKey('items.id'), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    action = Column(String(40), nullable=False)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    reference = Column(String(500), nullable=False)
    reason = Column(Text, nullable=False)
    data = Column(JSON, nullable=False)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    @field_validator('*', mode='before')
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str) and '\x00' in value:
            raise ValueError('Text cannot contain a null character')
        return value


class LineIn(Input):
    id: str | None = Field(default=None, min_length=1, max_length=60)
    part_number: str = Field(default='', max_length=160)
    description: str = Field(min_length=1, max_length=500)
    required_qty: int = Field(ge=1, le=10000, strict=True)
    notes: str = Field(default='', max_length=3000)


class PlanIn(Input):
    expected_version: int = Field(ge=0, strict=True)
    reference: str = Field(min_length=2, max_length=500)
    reason: str = Field(min_length=4, max_length=3000)
    lines: list[LineIn] = Field(min_length=1, max_length=500)


class ChangeIn(Input):
    expected_version: int = Field(ge=1, strict=True)
    reference: str = Field(min_length=2, max_length=500)
    notes: str = Field(min_length=4, max_length=3000)


class AllocateIn(ChangeIn):
    line_id: str = Field(min_length=1, max_length=60)
    component_ids: list[str] = Field(min_length=1, max_length=1000)

    @field_validator('component_ids')
    @classmethod
    def ids(cls, values):
        values = [value.strip() for value in values]
        if any(not value or len(value) > 60 or '\x00' in value for value in values):
            raise ValueError('Enter valid individual component IDs')
        if len(values) != len(set(values)):
            raise ValueError('Each physical component ID can appear only once')
        return values


def _stamp(value):
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.isoformat()
    return value


def _row(row):
    return {column.name: _stamp(getattr(row, column.name)) for column in row.__table__.columns}


def _spool(s, spool_id):
    item, plan = s.get(Item, spool_id), s.get(SpoolPlan, spool_id)
    if not item:
        raise HTTPException(404, 'Spool not found')
    if not plan or item.kind == 'Assembly':
        raise HTTPException(409, 'Create a structured individual spool plan before adding its required parts')
    return item, plan


def _lines(s, spool_id, active=True):
    query = select(PartLine).where(PartLine.spool_id == spool_id)
    if active:
        query = query.where(PartLine.active.is_(True))
    return list(s.scalars(query.order_by(PartLine.created_at, PartLine.id)))


def _allocations(s, spool_id):
    return list(s.scalars(select(PartAllocation).join(PartLine, PartAllocation.line_id == PartLine.id)
        .where(PartLine.spool_id == spool_id).order_by(PartAllocation.component_id)))


def _edit_reason(s, item, spool_plan):
    if item.released:
        return 'This spool is released; its required parts and allocations are fixed.'
    traveler = s.get(FlowPlan, item.id)
    if traveler and (traveler.route != 'spool' or traveler.status != 'active' or traveler.current_step != 9):
        return 'Required parts and allocations are fixed after spool step 9 is completed.'
    if s.scalar(select(WeldWork.id).join(Weld, Weld.id == WeldWork.weld_id).where(Weld.item_id == item.id).limit(1)):
        return 'Weld work already exists; the physical parts scope is fixed.'
    if spool_plan.assembly_id:
        parent = s.get(FlowPlan, spool_plan.assembly_id)
        parent_item = s.get(Item, spool_plan.assembly_id)
        if parent and (parent.status != 'active' or (parent.current_step or 99) >= 19) or parent_item and parent_item.released:
            return 'The parent assembly has entered controlled production; child parts scope is fixed.'
    return ''


def _component_open(plan):
    return not plan or plan.route == 'component' and plan.status == 'active' and plan.current_step is not None and plan.current_step <= 5


def _recorded_steps(events):
    completed = set()
    for event in events:
        if event.action in ('fail', 'reopen', 'admin_return_to_work'):
            target = (event.data or {}).get('return_step', event.step)
            if target is not None:
                completed = {number for number in completed if number < target}
        elif event.action == 'advance' and event.step is not None:
            completed.add(event.step)
    return completed


def component_state(s, item, spool_plan, line=None, editable=False):
    flow = s.get(FlowPlan, item.id)
    events = list(s.scalars(select(FlowEvent).where(FlowEvent.item_id == item.id).order_by(FlowEvent.sequence)))
    completed = _recorded_steps(events)
    blockers = []
    if item.kind != 'Part' or s.get(SpoolPlan, item.id):
        blockers.append('Allocation must identify an individual Part without a spool plan')
    if item.project != spool_plan.project_id:
        blockers.append('Part project does not match its spool')
    if line and line.part_number and (item.google_part_number or '').strip() != line.part_number:
        blockers.append('Part number does not match the required line')
    if item.on_hold:
        blockers.append('Part is on hold')
    if s.scalar(select(TrackingHold.id).where(TrackingHold.item_id == item.id, TrackingHold.closed_at.is_(None)).limit(1)):
        blockers.append('Part has an open quality hold')
    if s.scalar(select(Rework.id).where(Rework.item_id == item.id, Rework.closed_at.is_(None)).limit(1)):
        blockers.append('Part has open rework')
    if s.scalar(select(FlowException.id).where(FlowException.item_id == item.id, FlowException.closed_at.is_(None)).limit(1)):
        blockers.append('Part has an open process exception')
    route_complete = bool(flow and flow.route == 'component' and flow.status == 'completed')
    if not flow:
        blockers.append('Start the component process traveler')
    elif flow.route != 'component':
        blockers.append('Part must use the component process route')
    elif not route_complete:
        blockers.append('Component preparation through step 8 is incomplete')
    if flow and (7 not in completed or 8 not in completed):
        blockers.append('Actual preparation step 7 and return step 8 are not both recorded in the current pass')
    return {'id': item.id, 'description': item.description, 'google_part_number': item.google_part_number,
        'handler': item.handler, 'location': item.location, 'current_step': flow.current_step if flow else None,
        'current_title': STEP_BY_NUMBER.get(flow.current_step, {}).get('title', '') if flow else '',
        'flow_status': flow.status if flow else 'not_started', 'baseline_step': flow.baseline_step if flow else None,
        'not_recorded_steps': [n for n in range(1, flow.baseline_step) if n not in completed] if flow else [],
        'received': bool(flow and flow.route == 'component' and 1 in completed),
        'prepared': bool(route_complete and 7 in completed and 8 in completed and not blockers),
        'blockers': blockers, 'can_remove': bool(editable and _component_open(flow))}


def _counts(required=0, assigned=0, received=0, prepared=0):
    return {'required_qty': required, 'assigned_qty': assigned, 'received_qty': received, 'prepared_qty': prepared,
        'short_qty': max(0, required - assigned), 'remaining_qty': max(0, required - prepared),
        'assigned_percent': round(min(100, assigned / required * 100), 1) if required else 0,
        'received_percent': round(min(100, received / required * 100), 1) if required else 0,
        'prepared_percent': round(min(100, prepared / required * 100), 1) if required else 0}


def parts_snapshot(s, spool_id):
    """Current quantities only; no elapsed time, side effects or approvals."""
    cfg = s.get(SpoolPartsPlan, spool_id)
    if not cfg:
        return None
    item, spool_plan = _spool(s, spool_id)
    reason = _edit_reason(s, item, spool_plan)
    allocations = _allocations(s, spool_id)
    links = {link.component_id: link for link in s.scalars(select(ComponentLink).where(ComponentLink.spool_id == spool_id))}
    rows, allocated, errors = [], set(), []
    for line in _lines(s, spool_id):
        components = []
        for allocation in allocations:
            if allocation.line_id != line.id:
                continue
            child = s.get(Item, allocation.component_id)
            if not child or allocation.component_id not in links:
                errors.append(f'{allocation.component_id}: allocation has no matching physical component link')
                continue
            allocated.add(child.id)
            component = component_state(s, child, spool_plan, line, not reason)
            components.append(component)
        counts = _counts(line.required_qty, len(components), sum(row['received'] for row in components), sum(row['prepared'] for row in components))
        rows.append({'id': line.id, 'part_number': line.part_number, 'description': line.description,
                     'notes': line.notes, **counts, 'components': components})
        if counts['assigned_qty'] > line.required_qty:
            errors.append(f'{line.description}: assigned quantity exceeds its requirement')
        if counts['short_qty']:
            errors.append(f"{line.description}: {counts['short_qty']} required piece(s) not assigned")
        if counts['remaining_qty']:
            errors.append(f"{line.description}: {counts['remaining_qty']} required piece(s) not currently prepared")
        for component in components:
            errors.extend(f"{component['id']}: {message}" for message in component['blockers'])
    unallocated = [component_state(s, s.get(Item, cid), spool_plan, editable=False) for cid in sorted(set(links) - allocated) if s.get(Item, cid)]
    if unallocated:
        errors.append(f'{len(unallocated)} linked component(s) have no required-parts line allocation')
    if not rows:
        errors.append('The configured spool parts list has no active required lines')
    totals = _counts(*(sum(row[key] for row in rows) for key in ('required_qty', 'assigned_qty', 'received_qty', 'prepared_qty')))
    traveler = s.get(FlowPlan, spool_id)
    if traveler and (traveler.route != 'spool' or traveler.expected_children != totals['required_qty']):
        errors.append('Traveler component scope does not match the required parts quantity')
    return {'configured': True, 'version': cfg.version, 'reference': cfg.reference, 'lines': rows, 'totals': totals,
        'unallocated_components': unallocated, 'blockers': list(dict.fromkeys(errors)), 'editable': not reason, 'locked_reason': reason}


def parts_blockers(s, spool_id):
    snapshot = parts_snapshot(s, spool_id)
    return ['Required parts: ' + message for message in snapshot['blockers']] if snapshot else []


def lock_parts_for_release(s, spool_id):
    """Mutation callers already own topology and spool locks; pin child facts."""
    if s.get(SpoolPartsPlan, spool_id):
        ids = set(s.scalars(select(ComponentLink.component_id).where(ComponentLink.spool_id == spool_id)))
        ids.update(row.component_id for row in _allocations(s, spool_id))
        for component_id in sorted(ids):
            lock_item(s, component_id)


def parts_summary(s, spool_id):
    snapshot = parts_snapshot(s, spool_id)
    return {key: snapshot[key] for key in ('configured', 'version', 'reference', 'totals', 'blockers')} if snapshot else None


def parts_basis(s, spool_id):
    """Stable BOM structure for QA/packet fingerprints; omit for legacy scope."""
    cfg = s.get(SpoolPartsPlan, spool_id)
    if not cfg:
        return None
    lines = _lines(s, spool_id)
    allocations = []
    for allocation in _allocations(s, spool_id):
        item = s.get(Item, allocation.component_id)
        allocations.append({**_row(allocation), 'part_number': item.google_part_number if item else None,
                            'project_id': item.project if item else None, 'kind': item.kind if item else None})
    return {'plan': _row(cfg), 'lines': [_row(line) for line in lines], 'allocations': allocations}


def _detail(s, item, spool_plan, user):
    from removals import item_is_removed, item_not_removed, removal_summary
    from flow import flow_stage_for_item
    active = not item_is_removed(s, item.id)
    cfg = s.get(SpoolPartsPlan, item.id)
    project = s.get(Project, spool_plan.project_id)
    reason = _edit_reason(s, item, spool_plan)
    snapshot = parts_snapshot(s, item.id) or {'configured': False, 'version': 0, 'reference': '', 'lines': [],
        'totals': _counts(), 'unallocated_components': [component_state(s, s.get(Item, link.component_id), spool_plan)
            for link in s.scalars(select(ComponentLink).where(ComponentLink.spool_id == item.id).order_by(ComponentLink.component_id))],
        'blockers': [], 'editable': not reason, 'locked_reason': reason}
    candidates = []
    for child in s.scalars(select(Item).where(Item.kind == 'Part', Item.project.in_(('', spool_plan.project_id)), item_not_removed()).order_by(Item.id)) if active else ():
        if child.id == item.id or child.released or s.get(SpoolPlan, child.id):
            continue
        link = s.get(ComponentLink, child.id)
        if link and link.spool_id != item.id:
            continue
        flow = s.get(FlowPlan, child.id)
        if link or _component_open(flow):
            candidates.append(component_state(s, child, spool_plan, editable=not reason))
    if not active:
        snapshot['editable'] = False
        snapshot['locked_reason'] = 'This record was removed. An administrator must restore it before changes.'
        for line in snapshot.get('lines', []):
            for component in line.get('components', []):
                component['can_remove'] = False
    # Add live colors at the UI boundary only; quantities, release checks and
    # material/dossier evidence must not depend on a changing display stage.
    stage_cache = {}

    def with_stage(component):
        identifier = component['id']
        if identifier not in stage_cache:
            stage_cache[identifier] = flow_stage_for_item(s, s.get(Item, identifier))
        return {**component, 'flow_stage': stage_cache[identifier]}

    presentation = {**snapshot,
        'lines': [{**line, 'components': [with_stage(c) for c in line.get('components', [])]}
                  for line in snapshot.get('lines', [])],
        'unallocated_components': [with_stage(c) for c in snapshot.get('unallocated_components', [])]}
    return {'removal': removal_summary(s, 'item', item.id), 'can_mutate': active,
        'item': {'id': item.id, 'description': item.description, 'google_part_number': item.google_part_number,
                    'flow_stage': flow_stage_for_item(s, item),
                    'project_id': spool_plan.project_id, 'project_name': project.name if project else '', 'subproject_id': spool_plan.subproject_id},
        **presentation, 'permissions': {'can_manage': active and has_capability(user, 'manage_production'),
                                  'can_allocate': active and has_capability(user, 'allocate_parts'), 'can_mutate': active},
        'candidates': candidates, 'definitions': DEFINITIONS,
        'events': [_row(event) for event in s.scalars(select(PartEvent).where(PartEvent.spool_id == item.id).order_by(PartEvent.sequence.desc()).limit(100))] if cfg else []}


def _locked(s, spool_id, expected, creating=False):
    lock_topology(s)
    item = lock_item(s, spool_id)
    _, spool_plan = _spool(s, spool_id)
    cfg = s.scalar(select(SpoolPartsPlan).where(SpoolPartsPlan.spool_id == spool_id).execution_options(populate_existing=True))
    version = cfg.version if cfg else 0
    if version != expected or not cfg and not creating:
        raise HTTPException(409, {'message': 'Spool parts changed; refresh and retry. No changes were saved.', 'current_version': version})
    reason = _edit_reason(s, item, spool_plan)
    if reason:
        raise HTTPException(409, reason)
    return item, spool_plan, cfg


def _event(s, item, cfg, user, action, reference, reason, data, first=False):
    now = utcnow()
    if not first:
        cfg.version += 1
    cfg.updated_at = now
    item.updated_at = now
    event = PartEvent(spool_id=item.id, sequence=cfg.version, action=action, actor=user.badge, at=now,
                      reference=reference, reason=reason, data=data)
    s.add(event)
    s.flush()
    audit(s, item.id, user.badge, 'SPOOL_PARTS_CHANGED', {'parts_event_id': event.id, 'sequence': cfg.version,
          'action': action, 'reference': reference, 'reason': reason, 'data': data})
    return now


def _flow_event(s, item, user, action, at, reference, notes, data):
    from flow import _event as append_flow_event
    plan = s.get(FlowPlan, item.id)
    if plan:
        append_flow_event(s, item, plan, user.badge, action, plan.current_step, at, reference, notes, data)


def _commit(s):
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, 'Conflicting parts update; refresh and retry. No changes were saved.') from None


@router.get('/spools')
def list_spools(project_id: str = Query('', max_length=80), user: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import flow_stage_for_item
    from removals import item_not_removed, project_not_removed
    query = select(Item, SpoolPlan).join(SpoolPlan, SpoolPlan.item_id == Item.id).where(
        Item.kind != 'Assembly', item_not_removed(), project_not_removed(SpoolPlan.project_id))
    if project_id:
        query = query.where(SpoolPlan.project_id == project_id)
    items = []
    for item, plan in s.execute(query.order_by(Item.id)):
        project = s.get(Project, plan.project_id)
        snapshot = parts_snapshot(s, item.id)
        reason = _edit_reason(s, item, plan)
        items.append({'item_id': item.id, 'description': item.description, 'project_id': plan.project_id,
            'flow_stage': flow_stage_for_item(s, item),
            'project_name': project.name if project else '', 'subproject_id': plan.subproject_id,
            'configured': bool(snapshot), 'version': snapshot['version'] if snapshot else 0,
            'totals': snapshot['totals'] if snapshot else _counts(), 'editable': not reason, 'locked_reason': reason})
    return {'items': items, 'definitions': DEFINITIONS}


@router.get('/spools/{spool_id}')
def get_spool(spool_id: str, user: Employee = Depends(auth), s: Session = Depends(db)):
    return _detail(s, *_spool(s, spool_id), user)


@router.put('/spools/{spool_id}/plan')
def save_plan(spool_id: str, data: PlanIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    require_capability(user, 'manage_production')
    item, spool_plan, cfg = _locked(s, spool_id, data.expected_version, creating=True)
    total = sum(line.required_qty for line in data.lines)
    if total > 10000:
        raise HTTPException(422, 'A spool parts list can require at most 10000 whole pieces')
    line_ids = [line.id for line in data.lines if line.id]
    if len(line_ids) != len(set(line_ids)):
        raise HTTPException(422, 'Each existing parts line can appear only once')
    existing = {line.id: line for line in _lines(s, spool_id, active=False)}
    if any(line_id not in existing for line_id in line_ids):
        raise HTTPException(422, 'An existing line ID must belong to this spool')
    allocations = _allocations(s, spool_id)
    for line in data.lines:
        linked = [a for a in allocations if a.line_id == line.id]
        if len(linked) > line.required_qty:
            raise HTTPException(409, 'Required quantity cannot be smaller than the allocated physical pieces')
        if line.part_number and any((s.get(Item, a.component_id).google_part_number or '').strip() != line.part_number for a in linked):
            raise HTTPException(409, 'The revised part number must match every allocated component')
    if any(a.line_id not in line_ids for a in allocations):
        raise HTTPException(409, 'Unassign allocated parts before removing their required line')
    linked_count = len(list(s.scalars(select(ComponentLink.component_id).where(ComponentLink.spool_id == spool_id))))
    if linked_count > total:
        raise HTTPException(409, 'Required total cannot be smaller than the existing linked component scope')
    before = parts_basis(s, spool_id)
    submitted = sorted((line.id, line.part_number, line.description, line.required_qty, line.notes) for line in data.lines if line.id)
    prior = sorted((line.id, line.part_number, line.description, line.required_qty, line.notes) for line in existing.values() if line.active)
    if cfg and len(submitted) == len(data.lines) and submitted == prior and data.reference == cfg.reference:
        raise HTTPException(409, 'No required parts or source reference changed')
    first = cfg is None
    if first:
        cfg = SpoolPartsPlan(spool_id=spool_id, reference=data.reference, version=1, created_by=user.badge)
        s.add(cfg)
        s.flush()
    else:
        cfg.reference = data.reference
    now = utcnow()
    for line in existing.values():
        if line.id not in line_ids and line.active:
            line.active = False
            line.updated_at = now
    for value in data.lines:
        row = existing.get(value.id)
        if row:
            for key in ('part_number', 'description', 'required_qty', 'notes'):
                setattr(row, key, getattr(value, key))
            row.active = True
            row.updated_at = now
        else:
            s.add(PartLine(id=new_id('PRT'), spool_id=spool_id, **value.model_dump(exclude={'id'}), created_by=user.badge))
    s.flush()
    traveler = s.get(FlowPlan, spool_id)
    old_count = traveler.expected_children if traveler else None
    if traveler:
        traveler.expected_children = total
    at = _event(s, item, cfg, user, 'plan', data.reference, data.reason,
                {'before': before, 'required_qty': total, 'lines': [_row(line) for line in _lines(s, spool_id)]}, first=first)
    _flow_event(s, item, user, 'parts_scope', at, data.reference, data.reason,
                {'previous_expected_children': old_count, 'expected_children': total, 'parts_version': cfg.version})
    _commit(s)
    return _detail(s, item, spool_plan, user)


@router.post('/spools/{spool_id}/allocations')
def allocate(spool_id: str, data: AllocateIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    require_capability(user, 'allocate_parts')
    item, spool_plan, cfg = _locked(s, spool_id, data.expected_version)
    line = s.get(PartLine, data.line_id)
    if not line or line.spool_id != spool_id or not line.active:
        raise HTTPException(422, 'Choose an active required-parts line on this spool')
    current = list(s.scalars(select(PartAllocation).where(PartAllocation.line_id == line.id)))
    if len(current) + len(data.component_ids) > line.required_qty:
        raise HTTPException(409, 'This allocation would exceed the line required quantity')
    children = []
    for component_id in sorted(data.component_ids):
        child = lock_item(s, component_id)
        if child.kind != 'Part' or child.id == spool_id or s.get(SpoolPlan, child.id) or child.released:
            raise HTTPException(422, 'Allocate an unreleased individual Part without a spool plan')
        if child.project and child.project != spool_plan.project_id:
            raise HTTPException(409, 'Component and spool must belong to the same project')
        if line.part_number and (child.google_part_number or '').strip() != line.part_number:
            raise HTTPException(422, f'{child.id}: part number does not match this required line')
        if s.get(PartAllocation, child.id):
            raise HTTPException(409, f'{child.id}: this physical part already has a required-line allocation')
        link = s.get(ComponentLink, child.id)
        if link and link.spool_id != spool_id:
            raise HTTPException(409, f'{child.id}: this physical part belongs to another spool')
        if not link and not _component_open(s.get(FlowPlan, child.id)):
            raise HTTPException(409, 'A new assignment must occur before component selection is completed')
        children.append((child, link))
    old_links = list(s.scalars(select(ComponentLink.component_id).where(ComponentLink.spool_id == spool_id)))
    new_links = sum(not link for _, link in children)
    required_total = sum(row.required_qty for row in _lines(s, spool_id))
    if len(old_links) + new_links > required_total:
        raise HTTPException(409, 'This spool already has its declared physical component scope; classify its linked parts first')
    now = utcnow()
    for child, link in children:
        before_project = child.project
        if not link:
            s.add(ComponentLink(component_id=child.id, spool_id=spool_id, assigned_by=user.badge, assigned_at=now))
        child.project = spool_plan.project_id
        child.updated_at = now
        s.add(PartAllocation(component_id=child.id, line_id=line.id, assigned_by=user.badge, assigned_at=now))
        audit(s, child.id, user.badge, 'SPOOL_PART_ALLOCATED', {'spool_id': spool_id, 'line_id': line.id,
              'previous_project_id': before_project, 'project_id': spool_plan.project_id, 'reference': data.reference, 'notes': data.notes})
        _flow_event(s, child, user, 'parts_allocate', now, data.reference, data.notes, {'spool_id': spool_id, 'line_id': line.id})
    _event(s, item, cfg, user, 'allocate', data.reference, data.notes, {'line_id': line.id, 'component_ids': sorted(data.component_ids)})
    _flow_event(s, item, user, 'parts_allocate', now, data.reference, data.notes,
                {'line_id': line.id, 'component_ids': sorted(data.component_ids), 'parts_version': cfg.version})
    _commit(s)
    return _detail(s, item, spool_plan, user)


@router.post('/spools/{spool_id}/allocations/{component_id}/remove')
def remove_allocation(spool_id: str, component_id: str, data: ChangeIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    require_capability(user, 'allocate_parts')
    item, spool_plan, cfg = _locked(s, spool_id, data.expected_version)
    child = lock_item(s, component_id)
    allocation = s.get(PartAllocation, component_id)
    line = s.get(PartLine, allocation.line_id) if allocation else None
    link = s.get(ComponentLink, component_id)
    if not line or line.spool_id != spool_id or not link or link.spool_id != spool_id:
        raise HTTPException(404, 'This component has no allocation on this spool')
    if not _component_open(s.get(FlowPlan, component_id)):
        raise HTTPException(409, 'A selected/prepared component cannot be unassigned after selection step 5')
    line_id = allocation.line_id
    s.delete(allocation)
    s.delete(link)
    now = _event(s, item, cfg, user, 'unassign', data.reference, data.notes, {'component_id': component_id, 'line_id': line_id})
    child.updated_at = now
    audit(s, child.id, user.badge, 'SPOOL_PART_UNASSIGNED', {'spool_id': spool_id, 'line_id': line_id, 'reference': data.reference, 'notes': data.notes})
    for changed in (child, item):
        _flow_event(s, changed, user, 'parts_unassign', now, data.reference, data.notes,
                    {'spool_id': spool_id, 'component_id': component_id, 'line_id': line_id, 'parts_version': cfg.version})
    _commit(s)
    return _detail(s, item, spool_plan, user)


def guard_component_assignment(s, component_id, spool_id):
    existing = s.get(ComponentLink, component_id)
    if s.get(PartAllocation, component_id) or s.get(SpoolPartsPlan, spool_id) or existing and s.get(SpoolPartsPlan, existing.spool_id):
        raise HTTPException(409, 'Assign this physical component through the spool required-parts list so its quantity and line remain traceable')


def guard_flow_scope(s, spool_id, expected_children):
    if s.get(SpoolPartsPlan, spool_id):
        required = sum(line.required_qty for line in _lines(s, spool_id))
        if expected_children != required:
            raise HTTPException(409, f'Traveler scope must match the required-parts list ({required} pieces); edit quantities in Spool parts')


def guard_plan_project(s, item, values):
    if s.get(SpoolPartsPlan, item.id):
        old = s.get(SpoolPlan, item.id)
        if old and old.project_id != values['project_id']:
            raise HTTPException(409, 'A spool with a controlled parts list cannot be moved to another project')
