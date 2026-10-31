"""CLM's 24-step component, spool and assembly production traveler.

Checklist confirmations record observations, not weld or quality acceptance.
The traveler uses the existing weld/inspection gates and one process clock.
History is append-only; failed inspections return to explicit rework steps.
"""

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from main import Base, Employee, Item, Rework, asdict, audit, auth, db, lock_item, permit, utcnow
from permissions import flow_step_roles
from tracking import (SpoolPlan, Weld, WeldRequirement, WeldWork, _after,
    _production_complete, _requirement_satisfied, _reset_requirements,
    tracking_release_errors)


router = APIRouter(prefix='/api/flow', tags=['CLM process flow'])
VERSION = 'CLM-24-v2'
TOPOLOGY_LOCK = 0x4641425452414345
MANAGE = ['admin', 'supervisor']
HANDOFF = ['admin', 'supervisor', 'handler']
ROUTES = (
    {'id': 'component', 'label': 'Material / component preparation', 'first_step': 1, 'last_step': 8},
    {'id': 'spool', 'label': 'Spool fabrication', 'first_step': 9, 'last_step': 16},
    {'id': 'assembly', 'label': 'Final assembly through shipment', 'first_step': 17, 'last_step': 24},
)
ROUTE_BY_ID = {row['id']: row for row in ROUTES}
QA_CODES = {2: 'QA-001', 11: 'QA-002', 15: 'QA-003', 19: 'QA-004', 22: 'QA-005'}


def _step(number, title, section, checks):
    route = 'component' if number <= 8 else 'spool' if number <= 16 else 'assembly'
    return {
        'number': number, 'title': (QA_CODES[number] + '-' + title if number in QA_CODES else title),
        'qa_code': QA_CODES.get(number), 'route': route, 'section': section,
        'roles': list(flow_step_roles(number)),
        'checks': [{'id': f's{number}_{index}', 'label': label} for index, label in enumerate(checks, 1)],
        'requires_scan': number in (1, 3, 5, 6, 8, 9, 12, 13, 16, 17, 18, 20, 23, 24),
        'requires_handoff': number in (6, 8, 9, 12, 13, 16, 20, 23),
        'requires_location': number in (3, 6, 8, 9, 12, 13, 16, 20, 23),
        'requires_reference': number in (1, 2, 5, 11, 15, 19, 22, 23),
        'qa': number in (2, 11, 15, 19, 22),
        'return_steps': {2: [2], 11: [10], 15: [14], 19: [17, 18], 22: [17, 18, 19, 20, 21]}.get(number, []),
    }


STEPS = (
    _step(1, 'Receive Shipment', 'Material receipt', ['Scan the material barcode / ID', 'Verify against purchase order and BOM', 'Inspect material condition']),
    _step(2, 'Check Dimensions', 'Material receipt', ['Verify dimensions and material type against the isometric', 'Verify MTR and material documentation']),
    _step(3, 'Capture Location', 'Material receipt', ['Scan material into inventory', 'Record its storage location']),
    _step(4, 'Material in Inventory', 'Material receipt', ['Confirm the material is available for production']),
    _step(5, 'Select Components for Spool', 'Component preparation', ['Select components against the BOM / isometric', 'Scan components out of inventory']),
    _step(6, 'Release to Fabrication Prep Technician', 'Component preparation', ['Issue the selected components', 'Record the scanned handoff']),
    _step(7, 'Prep Components', 'Component preparation', ['Buff ends, clean and prepare surfaces', 'Mark or label the components as prepared']),
    _step(8, 'Return to Production', 'Component preparation', ['Material coordinator receives prepared components', 'Scan the components back into production']),
    _step(9, 'Release to Fit-Up Welder', 'Spool fabrication', ['Issue the required prepared components', 'Record the scanned handoff']),
    _step(10, 'Fit-Up & Tack Weld', 'Spool fabrication', ['Assemble the spool to its isometric', 'Record fit-up / tack work for each configured weld']),
    _step(11, 'Check Dimensions', 'Spool fabrication', ['Verify fit-up and alignment', 'Verify lengths, angles and applicable dimensions']),
    _step(12, 'Return to Production', 'Spool fabrication', ['Material coordinator receives the tacked spool', 'Record the scan update']),
    _step(13, 'Release to Process Welder', 'Spool fabrication', ['Issue the tacked spool to the process welder', 'Record the scanned handoff']),
    _step(14, 'Complete Welds', 'Spool fabrication', ['Complete all individual weld operations to the approved WPS']),
    _step(15, 'Inspect Welds', 'Spool fabrication', ['Review visual examination and required NDE', 'Verify welding standards / WPS requirements and all release checks']),
    _step(16, 'Scan Completed Spool', 'Spool fabrication', ['Material coordinator scans the completed spool back into production']),
    _step(17, 'Collect Spools for Assembly', 'Final assembly', ['Collect every required released spool', 'Scan each child spool barcode']),
    _step(18, 'Create Assembly ID', 'Final assembly', ['Verify the assembly ID and barcode / QR', 'Link all child spools to the parent assembly in the system']),
    _step(19, 'Assembly Inspection', 'Final assembly', ['Verify overall assembly dimensions against the isometric']),
    _step(20, 'Release to Sandblast & Paint', 'Sandblast & paint', ['Material coordinator issues the assembly', 'Record the scanned handoff']),
    _step(21, 'Sandblast & Paint', 'Sandblast & paint', ['Complete surface preparation and sandblasting', 'Apply paint to the approved specification']),
    _step(22, 'Final Inspection', 'Sandblast & paint', ['Inspect coating, dimensions and appearance', 'Verify all required documentation and final release checks']),
    _step(23, 'Release to Ready to Ship', 'Shipment', ['Material coordinator verifies ready-to-ship status', 'Scan and move the assembly to the shipping area', 'Generate and verify shipping documents']),
    _step(24, 'Ship to Customer', 'Shipment', ['Scan the assembly at shipping', 'Record shipment and its destination', 'Complete production records / close the work order']),
)
STEP_BY_NUMBER = {row['number']: row for row in STEPS}


class FlowPlan(Base):
    __tablename__ = 'flow_plans'
    item_id = Column(String(60), ForeignKey('items.id'), primary_key=True)
    route = Column(String(20), nullable=False)
    current_step = Column(Integer)
    status = Column(String(20), nullable=False, default='active')
    version = Column(Integer, nullable=False, default=1)
    expected_children = Column(Integer, nullable=False, default=0)
    baseline_step = Column(Integer, nullable=False)
    baseline_reference = Column(String(500), nullable=False, default='')
    baseline_reason = Column(Text, nullable=False, default='')
    material_reference = Column(String(500), nullable=False, default='')
    started_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    step_entered_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at = Column(DateTime(timezone=True))
    shipped_at = Column(DateTime(timezone=True))
    carrier = Column(String(200), nullable=False, default='')
    shipment_reference = Column(String(500), nullable=False, default='')
    destination = Column(String(500), nullable=False, default='')
    delivered_at = Column(DateTime(timezone=True))
    receipt_reference = Column(String(500), nullable=False, default='')
    recipient = Column(String(200), nullable=False, default='')


class FlowEvent(Base):
    __tablename__ = 'flow_events'
    __table_args__ = (UniqueConstraint('item_id', 'sequence', name='uq_flow_event_sequence'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(60), ForeignKey('items.id'), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    action = Column(String(40), nullable=False)
    step = Column(Integer)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    reference = Column(String(500), nullable=False, default='')
    notes = Column(Text, nullable=False, default='')
    data = Column(JSON, nullable=False, default=dict)


class FlowException(Base):
    __tablename__ = 'flow_exceptions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(60), ForeignKey('items.id'), nullable=False, index=True)
    step = Column(Integer, nullable=False)
    return_step = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    reference = Column(String(500), nullable=False)
    opened_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    closed_by = Column(String(80), ForeignKey('employees.badge'))
    closed_at = Column(DateTime(timezone=True))
    resolution = Column(Text, nullable=False, default='')


class ComponentLink(Base):
    __tablename__ = 'flow_component_links'
    component_id = Column(String(60), ForeignKey('items.id'), primary_key=True)
    spool_id = Column(String(60), ForeignKey('items.id'), nullable=False, index=True)
    assigned_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    assigned_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


PLAN_KEYS = tuple(FlowPlan.__table__.columns.keys())
EVENT_KEYS = tuple(FlowEvent.__table__.columns.keys())
EXCEPTION_KEYS = tuple(FlowException.__table__.columns.keys())


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    @field_validator('*', mode='before')
    @classmethod
    def no_null_characters(cls, value):
        if isinstance(value, str) and '\x00' in value:
            raise ValueError('Text cannot contain a null character')
        return value


class StartIn(Input):
    route: Literal['component', 'spool', 'assembly']
    expected_children: int = Field(default=0, ge=0, le=10000, strict=True)
    start_step: int | None = Field(default=None, ge=1, le=24, strict=True)
    baseline_reference: str = Field(default='', max_length=500)
    baseline_reason: str = Field(default='', max_length=3000)
    material_reference: str = Field(default='', max_length=500)
    notes: str = Field(default='', max_length=3000)


class VersionIn(Input):
    expected_version: int = Field(ge=1, strict=True)


class AdvanceIn(VersionIn):
    confirmations: list[str] = Field(default_factory=list, max_length=20)
    scanned_item_id: str = Field(default='', max_length=60)
    scanned_child_ids: list[str] = Field(default_factory=list, max_length=10000)
    reference: str = Field(default='', max_length=500)
    notes: str = Field(default='', max_length=3000)
    sender_badge: str = Field(default='', max_length=80)
    receiver_badge: str = Field(default='', max_length=80)
    location_id: str = Field(default='', max_length=80)
    operational_status: str = Field(default='', max_length=40)
    expected_transfer_version: int | None = Field(default=None, ge=0, strict=True)
    target_spool_id: str = Field(default='', max_length=60)
    carrier: str = Field(default='', max_length=200)
    shipment_reference: str = Field(default='', max_length=500)
    destination: str = Field(default='', max_length=500)
    resolution: str = Field(default='', max_length=3000)


class FailIn(VersionIn):
    reason: str = Field(min_length=4, max_length=3000)
    reference: str = Field(min_length=2, max_length=500)
    return_step: int | None = Field(default=None, ge=1, le=24, strict=True)


class DeliverIn(VersionIn):
    receipt_reference: str = Field(min_length=2, max_length=500)
    recipient: str = Field(min_length=2, max_length=200)
    notes: str = Field(default='', max_length=3000)


class LinkIn(VersionIn):
    spool_id: str = Field(min_length=3, max_length=60)
    reference: str = Field(default='', max_length=500)
    notes: str = Field(default='', max_length=3000)


class ScopeIn(VersionIn):
    expected_children: int = Field(ge=0, le=10000, strict=True)
    material_reference: str = Field(default='', max_length=500)
    reason: str = Field(min_length=4, max_length=3000)
    reference: str = Field(min_length=2, max_length=500)


def _utc(value):
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


def _dict(row, keys):
    return {key: (_utc(value).isoformat() if isinstance(value, dt.datetime) else value)
            for key in keys for value in (getattr(row, key),)}


def lock_topology(s):
    if s.get_bind().dialect.name == 'postgresql':
        s.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': TOPOLOGY_LOCK})
    from administration import refresh_session_authority
    refresh_session_authority(s)


def _locked(s, item_id):
    lock_topology(s)
    item = s.scalar(select(Item).where(Item.id == item_id).with_for_update().execution_options(populate_existing=True))
    if item is None:
        raise HTTPException(404, 'Item not found')
    from removals import require_active_item
    require_active_item(s, item_id)
    plan = s.scalar(select(FlowPlan).where(FlowPlan.item_id == item_id).execution_options(populate_existing=True))
    return item, plan


def _version(plan, expected):
    if plan is None:
        raise HTTPException(409, 'Start this item in its CLM process flow first')
    if plan.version != expected:
        raise HTTPException(409, {'message': 'Process flow changed; refresh and retry. No changes were saved.', 'current_version': plan.version})


def _commit(s):
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, 'Conflicting process-flow update; refresh and retry. No changes were saved.') from None


def _event(s, item, plan, actor, action, step, at, reference='', notes='', data=None, first=False):
    at = _utc(at)
    if plan.updated_at and at < _utc(plan.updated_at):
        raise HTTPException(409, 'Server clock precedes the last process-flow update; retry when time has caught up')
    if not first:
        plan.version += 1
    plan.updated_at = at
    item.updated_at = at
    data = {**(data or {}), 'definition_version': VERSION,
        'step_definition': STEP_BY_NUMBER.get(step)}
    row = FlowEvent(item_id=item.id, sequence=plan.version, action=action, step=step,
        actor=actor, at=at, reference=reference, notes=notes, data=data)
    s.add(row)
    s.flush()
    audit(s, item.id, actor, 'FLOW_EVENT', {'flow_event_id': row.id, 'sequence': row.sequence,
        'action': action, 'step': step, 'reference': reference, 'notes': notes, 'data': data})
    return row


def _sync(s, item, actor, step, at, notes):
    from production import sync_flow_process
    sync_flow_process(s, item, actor, STEP_BY_NUMBER[step] if step is not None else None, at, notes)


def _exceptions(s, item_id, open_only=False):
    query = select(FlowException).where(FlowException.item_id == item_id)
    if open_only:
        query = query.where(FlowException.closed_at.is_(None))
    return s.scalars(query.order_by(FlowException.id)).all()


def _component_ids(s, spool_id):
    return list(s.scalars(select(ComponentLink.component_id).where(ComponentLink.spool_id == spool_id).order_by(ComponentLink.component_id)))


def _spool_ids(s, assembly_id):
    from order_spools import effective_child_ids
    from removals import item_is_removed
    return effective_child_ids(s, assembly_id, include_removed=item_is_removed(s, assembly_id))


def _lock_children(s, item, plan):
    ids = _component_ids(s, item.id) if plan.route == 'spool' else _spool_ids(s, item.id) if plan.route == 'assembly' else []
    locked_ids = set(ids)
    if plan.route == 'assembly':
        for spool_id in ids:
            locked_ids.update(_component_ids(s, spool_id))
    for child_id in sorted(locked_ids):
        lock_item(s, child_id)
    return ids


def _project(s, item):
    plan = s.get(SpoolPlan, item.id)
    if plan:
        return plan.project_id, plan.subproject_id
    from order_spools import registered_spool
    registration = registered_spool(s, item.id)
    if registration:
        from orders import OrderAssembly, OrderGpn
        assembly = s.get(OrderAssembly, registration.assembly_id)
        group = s.get(OrderGpn, assembly.gpn_id) if assembly else None
        if group:
            return group.project_id, None
    link = s.get(ComponentLink, item.id)
    parent = s.get(SpoolPlan, link.spool_id) if link else None
    return (parent.project_id, parent.subproject_id) if parent else (item.project or '', None)


def _component_errors(s, item, plan):
    from parts import parts_blockers
    parts_errors = parts_blockers(s, item.id)
    ids = _component_ids(s, item.id)
    if plan.expected_children == 0:
        return parts_errors + ([] if not ids and len(plan.material_reference.strip()) >= 2 else ['Legacy material basis is missing, or components exist outside the declared zero-component scope'])
    errors = list(parts_errors)
    if len(ids) != plan.expected_children:
        errors.append(f'Prepared component scope incomplete: {len(ids)} linked of {plan.expected_children} declared')
    project_id, _ = _project(s, item)
    for child_id in ids:
        child = s.get(Item, child_id)
        flow = s.get(FlowPlan, child_id)
        if not child or child.kind != 'Part' or s.get(SpoolPlan, child_id):
            errors.append(f'{child_id}: link must identify an individual component')
        if not flow or flow.route != 'component' or flow.status != 'completed':
            errors.append(f'{child_id}: component preparation through step 8 is incomplete')
        if child and child.project != project_id:
            errors.append(f'{child_id}: component project does not match the spool')
        if _exceptions(s, child_id, True):
            errors.append(f'{child_id}: component has an open exception')
        if child:
            errors.extend(f'{child_id}: {error}' for error in _physical_hold_errors(s, child))
    return errors


def _assembly_errors(s, item, plan):
    ids = _spool_ids(s, item.id)
    errors = []
    if plan.expected_children < 1 or len(ids) != plan.expected_children:
        errors.append(f'Assembly spool scope incomplete: {len(ids)} linked of {plan.expected_children} declared')
    project_id, _ = _project(s, item)
    for child_id in ids:
        child = s.get(Item, child_id)
        child_plan = s.get(SpoolPlan, child_id)
        child_flow = s.get(FlowPlan, child_id)
        if not child or child.kind == 'Assembly' or not child_plan or child_plan.project_id != project_id:
            errors.append(f'{child_id}: child must be a spool in the same project')
            continue
        if not child_flow or child_flow.route != 'spool' or child_flow.status != 'completed':
            errors.append(f'{child_id}: spool traveler through step 16 is incomplete')
        if not child.released:
            errors.append(f'{child_id}: spool does not have final quality release')
        if _exceptions(s, child_id, True):
            errors.append(f'{child_id}: spool has an open exception')
        errors.extend(f'{child_id}: {error}' for error in tracking_release_errors(s, child))
        if child_flow and child_flow.route == 'spool':
            errors.extend(f'{child_id}: {error}' for error in _component_errors(s, child, child_flow))
    return errors


def _physical_hold_errors(s, item):
    from tracking import TrackingHold
    errors = ['Item is on hold'] if item.on_hold else []
    errors.extend('Open hold: ' + row.reason for row in s.scalars(select(TrackingHold).where(
        TrackingHold.item_id == item.id, TrackingHold.closed_at.is_(None))))
    if s.scalar(select(Rework.id).where(Rework.item_id == item.id, Rework.closed_at.is_(None)).limit(1)):
        errors.append('Open item rework must be resolved')
    return errors


def _weld_errors(s, item, step):
    plan = s.get(SpoolPlan, item.id)
    welds = s.scalars(select(Weld).where(Weld.item_id == item.id).order_by(Weld.number)).all()
    errors = []
    if not plan or len(welds) != plan.planned_welds:
        errors.append('Define every planned individual weld before completing this step')
    for weld in welds:
        if step in (10, 11) and not s.scalar(select(WeldWork.id).where(
                WeldWork.weld_id == weld.id, WeldWork.cycle == weld.cycle,
                WeldWork.operation == 'fitup').limit(1)):
            errors.append(f'{weld.number}: current-cycle fit-up work has not been recorded')
        if step == 14 and not _production_complete(s, weld):
            errors.append(f'{weld.number}: individual welding operations are incomplete')
    if step == 11:
        for req in s.scalars(select(WeldRequirement).where(
                WeldRequirement.item_id == item.id, WeldRequirement.stage == 'before_welding')):
            if not _requirement_satisfied(s, req):
                errors.append(req.label + ': before-welding acceptance is incomplete')
    return errors


def _step_errors(s, item, plan, *, allow_matching_exception=True, quality_for_update=False):
    if not plan or plan.status != 'active' or plan.current_step is None:
        return []
    step = plan.current_step
    from spool_receiving import receiving_errors
    errors = receiving_errors(s, item)
    if step in (7, 9, 10, 12, 13, 14, 16, 17, 18, 20, 21, 23, 24):
        errors.extend(_physical_hold_errors(s, item))
    if plan.route == 'spool':
        errors.extend(_component_errors(s, item, plan))
    elif plan.route == 'assembly':
        errors.extend(_assembly_errors(s, item, plan))
    if step in (10, 11, 14):
        errors.extend(_weld_errors(s, item, step))
    if step == 19 and (item.dimensional != 'Pass' or not item.dimension_at or not _after(item.dimension_at, item.last_work_at)):
        errors.append('Record a fresh passing dimensional inspection for the assembly')
    if step in (15, 22):
        errors.extend(tracking_release_errors(s, item))
    if step in (16, 23, 24) and not item.released:
        errors.append('Final quality release is required before this post-inspection step')
    if step in (20, 21, 23, 24):
        # Opt-in, project-scoped requirements use the same transaction and
        # topology lock as this traveler. Readiness is rechecked at the actual
        # coating/shipping step, including after a document or evidence change.
        from quality import production_gate_errors
        errors.extend(production_gate_errors(s, item, 'pre_coating' if step in (20, 21) else 'shipment',
                                            for_update=quality_for_update))
        from dossier import dossier_gate_errors
        errors.extend(dossier_gate_errors(s, item, phase='pre_coating' if step in (20, 21) else 'shipment',
                                          for_update=quality_for_update))
    if step in (5, 8) and not s.get(ComponentLink, item.id):
        errors.append('Assign this component to its target spool first')
    for exception in _exceptions(s, item.id, True):
        # Rework steps remain available. A matching QA step can resolve the
        # ticket with new evidence and explicit resolution notes.
        if step > exception.step or (step == exception.step and not allow_matching_exception):
            errors.append(f'Open exception from step {exception.step} requires passing reinspection')
    return list(dict.fromkeys(errors))


def flow_release_errors(s, item, approving_step=None, for_update=True):
    from order_spools import registered_spool
    registration = registered_spool(s, item.id)
    if registration and not s.get(SpoolPlan, item.id):
        return ['Declare the registered spool\'s actual weld plan and complete its spool traveler before ordinary final QA release']
    plan = s.get(FlowPlan, item.id)
    if not plan:
        from orders import OrderAssembly
        if s.get(OrderAssembly, item.id):
            return ['Start the purchase-order assembly traveler before ordinary final QA release; its required spools and QA steps must be recorded']
        if registration:
            return ['Start the purchase-order spool traveler before ordinary final QA release; its fabrication and QA steps must be recorded']
        return []
    required = 15 if plan.route == 'spool' else 22 if plan.route == 'assembly' else None
    if required is None:
        return ['Components complete preparation through their traveler; final spool release is not a component action']
    errors = []
    if approving_step != required or plan.current_step != required or plan.status != 'active':
        errors.append(f'Complete QA step {required} in the CLM process flow to approve final release')
    if for_update:
        _lock_children(s, item, plan)
    errors.extend(_component_errors(s, item, plan) if plan.route == 'spool' else _assembly_errors(s, item, plan))
    errors.extend(f'Open process-flow exception at step {row.step}' for row in _exceptions(s, item.id, True))
    return list(dict.fromkeys(errors))


def guard_plan_change(s, item, oldplan, values):
    flow = s.get(FlowPlan, item.id)
    if flow and flow.route == 'component':
        raise HTTPException(409, 'A component traveler cannot be converted into a spool plan')
    if s.get(ComponentLink, item.id):
        raise HTTPException(409, 'An assigned individual component cannot be converted into a spool')
    keys = ('project_id', 'subproject_id', 'assembly_id', 'planned_welds', 'drawing_revision', 'zero_weld_reason')
    if flow and oldplan and any(getattr(oldplan, key) != values[key] for key in keys):
        raise HTTPException(409, 'Traveler scope is established. Use its controlled child-link action; plan notes and due date remain editable.')
    if oldplan and oldplan.assembly_id:
        parent = s.get(FlowPlan, oldplan.assembly_id)
        if parent and any(getattr(oldplan, key) != values[key] for key in keys):
            raise HTTPException(409, 'This spool belongs to an assembly traveler; its project, scope and parent link are controlled')


def guard_reopen(s, item):
    flow = s.get(FlowPlan, item.id)
    if flow and flow.status in ('shipped', 'delivered'):
        raise HTTPException(409, 'A shipped or delivered assembly cannot be reopened through the production workflow')
    from order_spools import effective_parent_id
    parent_id = effective_parent_id(s, item.id)
    if parent_id:
        parent_item = lock_item(s, parent_id)
        parent = s.get(FlowPlan, parent_item.id)
        if parent and (parent.status != 'active' or (parent.current_step or 99) >= 19 or parent_item.released):
            raise HTTPException(409, 'Return the parent assembly to step 17 or 18 through its controlled QA/rework flow before reopening a child spool')


def on_item_reopened(s, item, actor, at):
    plan = s.get(FlowPlan, item.id)
    if not plan:
        return
    step = 15 if plan.route == 'spool' else 22 if plan.route == 'assembly' else None
    if step is None:
        return
    plan.status = 'active'
    plan.current_step = step
    plan.step_entered_at = at
    plan.completed_at = None
    _event(s, item, plan, actor, 'reopen', step, at, notes='Administrative reopen: fresh QA approval is required.', data={'return_step': step})
    _sync(s, item, actor, step, at, 'Administrative reopen of CLM traveler')


def guard_weld_operation(s, item, operation):
    from spool_receiving import require_receiving_pass
    require_receiving_pass(s, item)
    plan = s.get(FlowPlan, item.id)
    if not plan:
        return
    allowed = (10, 14) if operation == 'fitup' else (14,)
    if plan.route == 'assembly':
        allowed = (18,)
    if plan.status != 'active' or plan.current_step not in allowed:
        raise HTTPException(409, 'Record this work at the fabrication step in the CLM traveler: ' + ', '.join(map(str, allowed)))


def _step_states(s, plan):
    route = ROUTE_BY_ID[plan.route]
    states = {number: {**STEP_BY_NUMBER[number], 'status': 'not_recorded' if number < plan.baseline_step else 'pending',
        'completed_at': None, 'last_actor': None, 'attempts': 0} for number in range(route['first_step'], route['last_step'] + 1)}
    for event in s.scalars(select(FlowEvent).where(FlowEvent.item_id == plan.item_id).order_by(FlowEvent.sequence)):
        if event.action in ('fail', 'reopen', 'admin_return_to_work'):
            target = event.data.get('return_step', event.step)
            for number, state in states.items():
                if target is not None and number >= target:
                    state.update(status='pending', completed_at=None, last_actor=None)
        elif event.action == 'advance' and event.step in states:
            states[event.step].update(status='completed', completed_at=_utc(event.at).isoformat(), last_actor=event.actor)
            states[event.step]['attempts'] += 1
    if plan.status == 'active' and plan.current_step in states:
        states[plan.current_step]['status'] = 'current'
    return list(states.values())


def _summary(s, item, plan=None):
    from production import compact_process_summary, process_snapshot
    plan = plan if plan is not None else s.get(FlowPlan, item.id)
    project_id, subproject_id = _project(s, item)
    return {
        'item_id': item.id, 'description': item.description, 'route': plan.route if plan else None,
        'status': plan.status if plan else 'not_started', 'current_step': plan.current_step if plan else None,
        'current_title': STEP_BY_NUMBER[plan.current_step]['title'] if plan and plan.current_step else '',
        'step_entered_at': _utc(plan.step_entered_at).isoformat() if plan and plan.step_entered_at else None,
        'version': plan.version if plan else 0, 'project_id': project_id, 'subproject_id': subproject_id,
        'released': bool(item.released), 'open_exceptions': len(_exceptions(s, item.id, True)) if plan else 0,
        'blockers': _step_errors(s, item, plan) if plan else [],
        'production_process': compact_process_summary(process_snapshot(s, item.id)),
    }


def detail(s, item, user):
    from administration import release_summary
    from production import process_snapshot
    from parts import parts_summary
    from transfers import transfer_snapshot
    from orders import order_scope
    from spool_receiving import receiving_errors, receiving_summary
    arrival_blockers = receiving_errors(s, item)
    parts = parts_summary(s, item.id)
    plan = s.get(FlowPlan, item.id)
    process = process_snapshot(s, item.id, user=user)
    component_ids = _component_ids(s, item.id)
    spool_ids = _spool_ids(s, item.id)
    link = s.get(ComponentLink, item.id)
    spool_plan = s.get(SpoolPlan, item.id)
    from order_spools import effective_parent_id
    parent_id = link.spool_id if link else effective_parent_id(s, item.id)
    parent_item = s.get(Item, parent_id) if parent_id else None
    parent_plan = s.get(FlowPlan, parent_id) if parent_id else None
    actions = []
    if not plan and user.role in MANAGE and not arrival_blockers:
        actions.append('start')
    if plan and plan.status == 'active':
        step = STEP_BY_NUMBER[plan.current_step]
        if user.role in step['roles']:
            if not arrival_blockers:
                actions.append('advance')
            if step['qa']:
                actions.append('fail')
        if plan.route == 'component' and (plan.current_step <= 5 or not link) and user.role in HANDOFF:
            actions.append('assign-component')
        if plan.route == 'assembly' and plan.current_step in (17, 18) and user.role in MANAGE:
            actions.append('link-spool')
        if user.role in MANAGE and (plan.route == 'spool' and plan.current_step == 9 or plan.route == 'assembly' and plan.current_step in (17, 18)):
            actions.append('scope')
        actions.extend(action for action in process['permissions']['allowed_actions'] if action in ('pause', 'resume'))
    if plan and plan.status == 'shipped' and user.role in HANDOFF:
        actions.append('deliver')
    from removals import item_is_removed, removal_summary
    active = not item_is_removed(s, item.id)
    if not active:
        actions = []
    return {
        'removal': removal_summary(s, 'item', item.id), 'can_mutate': active,
        'receiving': receiving_summary(s, item, user),
        **({'parts': parts} if parts else {}),
        'order_scope': order_scope(s, item.id),
        'item': {**_dict(item, 'id description kind project drawing location handler released released_at released_by dimensional dimension_at last_work_at on_hold'.split()),
                 'release_control': release_summary(s, item)},
        'release_control': release_summary(s, item),
        'transfer': transfer_snapshot(s, item, user),
        'suggested_route': 'assembly' if item.kind == 'Assembly' else 'spool' if spool_plan or item.kind == 'Spool' else 'component',
        'flow': {**_dict(plan, PLAN_KEYS), 'steps': _step_states(s, plan),
            'current': STEP_BY_NUMBER[plan.current_step] if plan.current_step else None,
            'blockers': _step_errors(s, item, plan)} if plan else None,
        'production_process': process,
        'components': [_summary(s, s.get(Item, key)) for key in component_ids],
        'spools': [_summary(s, s.get(Item, key)) for key in spool_ids],
        'parent': {'item_id': parent_item.id, 'description': parent_item.description,
            'route': parent_plan.route if parent_plan else ('spool' if link else 'assembly')} if parent_item else None,
        'events': [_dict(row, EVENT_KEYS) for row in s.scalars(select(FlowEvent).where(FlowEvent.item_id == item.id).order_by(FlowEvent.sequence))],
        'exceptions': [_dict(row, EXCEPTION_KEYS) for row in _exceptions(s, item.id)],
        'allowed_actions': actions,
    }


@router.get('/catalog')
def catalog(u: Employee = Depends(auth)):
    return {'version': VERSION, 'steps': STEPS, 'routes': ROUTES}


@router.get('/items')
def items(project_id: str = '', subproject_id: str = '', u: Employee = Depends(auth), s: Session = Depends(db)):
    from removals import item_not_removed
    result = []
    for item, plan in s.execute(select(Item, FlowPlan).join(FlowPlan, FlowPlan.item_id == Item.id).where(item_not_removed()).order_by(Item.id)):
        project, subproject = _project(s, item)
        if project_id and project != project_id or subproject_id and subproject != subproject_id:
            continue
        result.append(_summary(s, item, plan))
    return {'items': result}


@router.get('/items/{item_id}')
def get_item(item_id: str, u: Employee = Depends(auth), s: Session = Depends(db)):
    item = s.get(Item, item_id)
    if not item:
        raise HTTPException(404, 'Item not found')
    return detail(s, item, u)


@router.post('/items/{item_id}/start', status_code=201)
def start(item_id: str, data: StartIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    permit(u, *MANAGE)
    item, existing = _locked(s, item_id)
    if existing:
        raise HTTPException(409, 'This item already has a CLM traveler')
    spool_plan = s.get(SpoolPlan, item.id)
    if data.route == 'component':
        if item.kind != 'Part' or spool_plan:
            raise HTTPException(422, 'Component travelers require an individual Part without a spool plan')
        if data.expected_children:
            raise HTTPException(422, 'A component does not declare child items')
    elif not spool_plan:
        raise HTTPException(409, 'Create the project and spool plan before starting a spool or assembly traveler')
    elif data.route == 'assembly' and item.kind != 'Assembly':
        raise HTTPException(422, 'An assembly traveler requires an Assembly item')
    elif data.route == 'spool' and item.kind == 'Assembly':
        raise HTTPException(422, 'An Assembly must use the assembly traveler')
    if data.route == 'assembly' and data.expected_children < 1:
        raise HTTPException(422, 'Declare at least one required child spool for the assembly')
    if data.route == 'assembly':
        from orders import guard_flow_scope as guard_order_scope
        guard_order_scope(s, item.id, data.expected_children)
    if data.route == 'spool' and data.expected_children == 0 and len(data.material_reference) < 2:
        raise HTTPException(422, 'Declare required components, or record the controlled legacy material basis for an existing spool')
    if data.route == 'spool':
        from parts import guard_flow_scope
        guard_flow_scope(s, item.id, data.expected_children)
    scope = ROUTE_BY_ID[data.route]
    step = data.start_step or scope['first_step']
    if not scope['first_step'] <= step <= scope['last_step']:
        raise HTTPException(422, 'The starting step must belong to the selected route')
    if step > scope['first_step'] and (len(data.baseline_reference) < 2 or len(data.baseline_reason) < 4):
        raise HTTPException(422, 'Starting later requires a baseline reference and reason; earlier steps will remain not recorded')
    post_qa = data.route == 'spool' and step == 16 or data.route == 'assembly' and step >= 23
    if bool(item.released) != bool(post_qa):
        raise HTTPException(409, 'A post-QA baseline requires an existing final quality release; earlier steps require an unreleased item')
    if post_qa:
        errors = tracking_release_errors(s, item)
        if errors:
            raise HTTPException(409, {'flow_blockers': errors})
    existing_children = _component_ids(s, item.id) if data.route == 'spool' else _spool_ids(s, item.id) if data.route == 'assembly' else []
    if len(existing_children) > data.expected_children:
        raise HTTPException(409, 'Existing child links exceed the declared scope')
    from spool_receiving import require_receiving_pass
    require_receiving_pass(s, item)
    now = _utc(utcnow())
    plan = FlowPlan(item_id=item.id, route=data.route, current_step=step, status='active', version=1,
        expected_children=data.expected_children, baseline_step=step, baseline_reference=data.baseline_reference,
        baseline_reason=data.baseline_reason, material_reference=data.material_reference,
        started_by=u.badge, started_at=now, step_entered_at=now, updated_at=now)
    s.add(plan)
    s.flush()
    _event(s, item, plan, u.badge, 'start', step, now, data.baseline_reference, data.notes,
        {'route': data.route, 'baseline_step': step, 'baseline_reason': data.baseline_reason,
         'expected_children': data.expected_children, 'material_reference': data.material_reference,
         'earlier_steps': 'not_recorded'}, first=True)
    _sync(s, item, u.badge, step, now, 'Start CLM traveler; earlier process times are not inferred')
    _commit(s)
    return detail(s, item, u)


def _verify_form(s, item, plan, data):
    from transfers import validate_location, validate_transfer
    step = STEP_BY_NUMBER[plan.current_step]
    expected = {row['id'] for row in step['checks']}
    if len(data.confirmations) != len(set(data.confirmations)) or set(data.confirmations) != expected:
        raise HTTPException(422, 'Confirm each checklist entry for the current step exactly once')
    if step['requires_scan'] and data.scanned_item_id != item.id:
        raise HTTPException(422, 'Scan or enter the exact current item ID to verify this step')
    if step['requires_reference'] and len(data.reference) < 2:
        raise HTTPException(422, 'An inspection, material or document reference is required for this step')
    selected = None
    if step['requires_handoff']:
        selected = validate_transfer(s, item, sender_badge=data.sender_badge, receiver_badge=data.receiver_badge,
            location_id=data.location_id, operational_status=data.operational_status,
            expected_transfer_version=data.expected_transfer_version, allow_no_change=True)
    elif step['number'] == 3:
        if data.sender_badge or data.receiver_badge or data.operational_status:
            raise HTTPException(422, 'This storage-location step does not record a badge handoff or operational status')
        selected = validate_location(s, item, expected_transfer_version=data.expected_transfer_version, location_id=data.location_id)
    elif data.sender_badge or data.receiver_badge or data.location_id or data.operational_status or data.expected_transfer_version is not None:
        raise HTTPException(422, 'Badge handoff and location fields are only accepted at the applicable process steps')
    if step['number'] == 5:
        link = s.get(ComponentLink, item.id)
        if not link or data.target_spool_id != link.spool_id:
            raise HTTPException(422, 'Verify the selected target spool ID against this component assignment')
    if step['number'] == 17:
        expected_ids = _spool_ids(s, item.id)
        if len(data.scanned_child_ids) != len(set(data.scanned_child_ids)) or set(data.scanned_child_ids) != set(expected_ids):
            raise HTTPException(422, 'Scan or enter each linked child spool exactly once')
    if step['number'] == 24 and any(len(value) < 2 for value in (data.carrier, data.shipment_reference, data.destination)):
        raise HTTPException(422, 'Record the carrier, shipment reference and destination before marking shipped')
    matching = [row for row in _exceptions(s, item.id, True) if row.step == step['number']]
    if matching and len(data.resolution) < 4:
        raise HTTPException(422, 'Record the corrective disposition / resolution for the open exception before passing reinspection')
    return selected, matching


def _fresh_dimensions_after_work(item, at):
    item.last_work_at = at
    item.dimensional = 'Not started'
    item.dimension_at = None
    item.reinspection_due = True


@router.post('/items/{item_id}/advance')
def advance(item_id: str, data: AdvanceIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    item, plan = _locked(s, item_id)
    _version(plan, data.expected_version)
    if plan.status != 'active' or plan.current_step is None:
        raise HTTPException(409, 'This traveler has no current production step')
    step = STEP_BY_NUMBER[plan.current_step]
    permit(u, *step['roles'])
    if item.released and step['number'] not in (16, 23, 24):
        raise HTTPException(409, 'Only post-QA handoff and shipping steps may change a released item')
    _lock_children(s, item, plan)
    selected, matching = _verify_form(s, item, plan, data)
    errors = _step_errors(s, item, plan, quality_for_update=True)
    if errors:
        raise HTTPException(409, {'flow_blockers': errors})
    now = _utc(utcnow())
    for exception in matching:
        exception.closed_by = u.badge
        exception.closed_at = now
        exception.resolution = data.resolution
    # Flush the matching resolution before final-release checks. Failure later
    # in this transaction rolls it back, so a failed pass cannot close tickets.
    s.flush()
    if step['number'] in (15, 22):
        from main import finalize_release
        finalize_release(s, item, u.badge, data.reference, at=now, flow_step=step['number'])
    handoff_data = None
    if step['requires_handoff']:
        from transfers import record_transfer
        handoff_data = record_transfer(s, item, selected, u, now, notes=data.notes,
            scan_method='flow_item_verification', scanned_item_id=data.scanned_item_id, flow_step=step['number'])
    elif step['number'] == 3:
        from transfers import record_location
        handoff_data = record_location(s, item, selected, u, now)
    if step['number'] in (7, 18, 21):
        _fresh_dimensions_after_work(item, now)
    completed_step = step['number']
    scope = ROUTE_BY_ID[plan.route]
    if completed_step == scope['last_step']:
        plan.current_step = None
        plan.step_entered_at = None
        plan.completed_at = now
        plan.status = 'shipped' if plan.route == 'assembly' else 'completed'
        if plan.route == 'assembly':
            plan.shipped_at = now
            plan.carrier = data.carrier
            plan.shipment_reference = data.shipment_reference
            plan.destination = data.destination
    else:
        plan.current_step += 1
        plan.step_entered_at = now
    _event(s, item, plan, u.badge, 'advance', completed_step, now, data.reference, data.notes,
        {**data.model_dump(exclude={'expected_version', 'reference', 'notes'}),
         **({'handoff': handoff_data} if handoff_data else {}),
         'closed_exception_ids': [row.id for row in matching], 'next_step': plan.current_step})
    _sync(s, item, u.badge, plan.current_step, now, f'CLM step {completed_step} completed')
    _commit(s)
    return detail(s, item, u)


@router.post('/items/{item_id}/fail')
def fail(item_id: str, data: FailIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    item, plan = _locked(s, item_id)
    _version(plan, data.expected_version)
    if plan.status != 'active' or plan.current_step is None:
        raise HTTPException(409, 'There is no active QA step to fail')
    step = STEP_BY_NUMBER[plan.current_step]
    permit(u, *step['roles'])
    if not step['qa']:
        raise HTTPException(409, 'Exception routing is available at the defined QA / material verification steps')
    if item.released:
        raise HTTPException(409, 'Reopen this released item before recording a new QA failure')
    target = data.return_step if data.return_step is not None else (21 if step['number'] == 22 else step['return_steps'][0])
    if target not in step['return_steps']:
        raise HTTPException(422, 'Choose one of this inspection step\'s allowed rework destinations')
    now = _utc(utcnow())
    row = FlowException(item_id=item.id, step=step['number'], return_step=target,
        reason=data.reason, reference=data.reference, opened_by=u.badge, opened_at=now)
    s.add(row)
    s.flush()
    if step['number'] in (11, 15):
        requirements = s.scalars(select(WeldRequirement).where(WeldRequirement.item_id == item.id)).all()
        affected = [req for req in requirements if (req.stage == 'before_welding') == (step['number'] == 11)]
        _reset_requirements(s, item, affected, u.badge, f'CLM step {step["number"]} failed: {data.reason}')
        item.reinspection_due = True
        item.weld = 'Not started'
        item.weld_at = None
    if step['number'] in (11, 15, 19, 22):
        item.dimensional = 'Not started'
        item.dimension_at = None
        item.reinspection_due = True
    failed_step = step['number']
    plan.current_step = target
    plan.step_entered_at = now
    _event(s, item, plan, u.badge, 'fail', failed_step, now, data.reference, data.reason,
        {'exception_id': row.id, 'return_step': target})
    _sync(s, item, u.badge, target, now, f'CLM QA exception {row.id}: {data.reason}')
    _commit(s)
    return detail(s, item, u)


@router.post('/items/{item_id}/deliver')
def deliver(item_id: str, data: DeliverIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    permit(u, *HANDOFF)
    item, plan = _locked(s, item_id)
    _version(plan, data.expected_version)
    if plan.route != 'assembly' or plan.status != 'shipped':
        raise HTTPException(409, 'Only a shipped assembly can receive a delivery confirmation')
    now = _utc(utcnow())
    plan.status = 'delivered'
    plan.delivered_at = now
    plan.receipt_reference = data.receipt_reference
    plan.recipient = data.recipient
    _event(s, item, plan, u.badge, 'deliver', 24, now, data.receipt_reference, data.notes,
        {'recipient': data.recipient, 'shipment_reference': plan.shipment_reference})
    _commit(s)
    return detail(s, item, u)


def _spool_assignment_open(s, item, plan):
    if item.released:
        return False
    flow = s.get(FlowPlan, item.id)
    return not flow or flow.route == 'spool' and flow.status == 'active' and flow.current_step == 9


@router.post('/items/{item_id}/assign-component', status_code=201)
def assign_component(item_id: str, data: LinkIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    permit(u, *HANDOFF)
    component, plan = _locked(s, item_id)
    _version(plan, data.expected_version)
    from parts import guard_component_assignment
    guard_component_assignment(s, item_id, data.spool_id)
    link = s.get(ComponentLink, component.id)
    if plan.route != 'component' or plan.status != 'active' or (plan.current_step > 5 and link):
        raise HTTPException(409, 'Component selection is fixed after step 5; a later baseline may record its missing original assignment')
    spool = lock_item(s, data.spool_id)
    spool_plan = s.get(SpoolPlan, spool.id)
    if not spool_plan or spool.kind == 'Assembly' or spool.id == component.id:
        raise HTTPException(422, 'Assign an individual component to a tracked spool')
    if not _spool_assignment_open(s, spool, spool_plan):
        raise HTTPException(409, 'Components must be assigned before the spool completes step 9')
    if component.project and component.project != spool_plan.project_id:
        raise HTTPException(409, 'Component and spool must belong to the same project')
    if link and link.spool_id == spool.id:
        raise HTTPException(409, 'This component is already assigned to that spool')
    old_spool = None
    if link:
        old_spool = lock_item(s, link.spool_id)
        if not _spool_assignment_open(s, old_spool, s.get(SpoolPlan, old_spool.id)):
            raise HTTPException(409, 'The original spool has already issued this component into production')
    spool_flow = s.get(FlowPlan, spool.id)
    current_count = len(_component_ids(s, spool.id))
    if spool_flow and (spool_flow.expected_children == 0 or current_count >= spool_flow.expected_children):
        raise HTTPException(409, 'The target spool already has its declared number of components')
    now = _utc(utcnow())
    before = link.spool_id if link else None
    if link:
        link.spool_id = spool.id
        link.assigned_by = u.badge
        link.assigned_at = now
    else:
        s.add(ComponentLink(component_id=component.id, spool_id=spool.id, assigned_by=u.badge, assigned_at=now))
    component.project = spool_plan.project_id
    _event(s, component, plan, u.badge, 'assign_component', plan.current_step, now, data.reference, data.notes,
        {'previous_spool_id': before, 'spool_id': spool.id})
    for parent_item in (old_spool, spool):
        parent_plan = s.get(FlowPlan, parent_item.id) if parent_item else None
        if parent_plan:
            _event(s, parent_item, parent_plan, u.badge, 'component_link', parent_plan.current_step, now,
                data.reference, data.notes, {'component_id': component.id, 'previous_spool_id': before, 'spool_id': spool.id})
        elif parent_item:
            audit(s, parent_item.id, u.badge, 'FLOW_COMPONENT_LINK', {'component_id': component.id, 'previous_spool_id': before, 'spool_id': spool.id})
    _commit(s)
    return detail(s, component, u)


@router.post('/items/{item_id}/link-spool', status_code=201)
def link_spool(item_id: str, data: LinkIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    permit(u, *MANAGE)
    assembly, plan = _locked(s, item_id)
    _version(plan, data.expected_version)
    if plan.route != 'assembly' or plan.status != 'active' or plan.current_step not in (17, 18) or assembly.released:
        raise HTTPException(409, 'Link child spools while collecting / identifying an unreleased assembly at step 17 or 18')
    child = lock_item(s, data.spool_id)
    child_plan = s.scalar(select(SpoolPlan).where(SpoolPlan.item_id == child.id).execution_options(populate_existing=True))
    assembly_plan = s.get(SpoolPlan, assembly.id)
    child_flow = s.get(FlowPlan, child.id)
    if child.kind == 'Assembly' or not child_plan or child.id == assembly.id:
        raise HTTPException(422, 'Assembly children must be individual tracked spools')
    from orders import guard_plan_scope
    guard_plan_scope(s, child, child_plan, {'project_id': child_plan.project_id, 'assembly_id': assembly.id})
    if child_plan.project_id != assembly_plan.project_id:
        raise HTTPException(409, 'Child spool and assembly must belong to the same project')
    if child_plan.assembly_id:
        raise HTTPException(409, 'This spool already has a parent assembly; the established relationship cannot be silently replaced')
    if not child_flow or child_flow.route != 'spool' or child_flow.status != 'completed' or not child.released:
        raise HTTPException(409, 'Complete the child spool through step 16 and final quality release before assembly collection')
    blockers = tracking_release_errors(s, child)
    if blockers or _exceptions(s, child.id, True):
        raise HTTPException(409, {'flow_blockers': blockers or ['The child spool has an open process exception']})
    if len(_spool_ids(s, assembly.id)) >= plan.expected_children:
        raise HTTPException(409, 'The assembly already has its declared number of child spools')
    now = _utc(utcnow())
    child_plan.assembly_id = assembly.id
    child_plan.version += 1
    child_plan.updated_at = now
    _event(s, assembly, plan, u.badge, 'link_spool', plan.current_step, now, data.reference, data.notes,
        {'spool_id': child.id, 'assembly_id': assembly.id, 'quality_release_preserved': True})
    _event(s, child, child_flow, u.badge, 'assembly_link', None, now, data.reference, data.notes,
        {'assembly_id': assembly.id, 'quality_release_preserved': True})
    _commit(s)
    return detail(s, assembly, u)


@router.post('/items/{item_id}/scope')
def update_scope(item_id: str, data: ScopeIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    permit(u, *MANAGE)
    item, plan = _locked(s, item_id)
    _version(plan, data.expected_version)
    if plan.route == 'spool':
        from parts import guard_flow_scope
        guard_flow_scope(s, item_id, data.expected_children)
    elif plan.route == 'assembly':
        from orders import guard_flow_scope as guard_order_scope
        guard_order_scope(s, item_id, data.expected_children)
    if plan.status != 'active' or item.released or not (
            plan.route == 'spool' and plan.current_step == 9 or
            plan.route == 'assembly' and plan.current_step in (17, 18)):
        raise HTTPException(409, 'Change child scope before spool step 9 is completed, or at assembly collection / identification steps 17–18')
    ids = _lock_children(s, item, plan)
    if data.expected_children < len(ids):
        raise HTTPException(409, 'Declared scope cannot be smaller than the existing child links')
    if plan.route == 'assembly' and data.expected_children < 1:
        raise HTTPException(422, 'An assembly must declare at least one child spool')
    if plan.route == 'spool' and data.expected_children == 0 and len(data.material_reference) < 2:
        raise HTTPException(422, 'A zero-component spool needs its controlled legacy material reference')
    before = {'expected_children': plan.expected_children, 'material_reference': plan.material_reference}
    after = {'expected_children': data.expected_children, 'material_reference': data.material_reference}
    if before == after:
        raise HTTPException(409, 'No child scope or material basis changed')
    plan.expected_children = data.expected_children
    plan.material_reference = data.material_reference
    now = _utc(utcnow())
    _event(s, item, plan, u.badge, 'scope', plan.current_step, now, data.reference, data.reason,
        {'before': before, 'after': after})
    _commit(s)
    return detail(s, item, u)
