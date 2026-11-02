"""Recorded custody and location handoffs, separate from production acceptance.

Badge values identify the sending and receiving employees. The authenticated
operator records the handoff; neither scanned badge is a login or signature.
Current-state rows are additive. Existing immutable audit/flow events retain
the historical snapshots, including the labels in use when a move occurred.
"""

from dataclasses import dataclass
import datetime as dt
from typing import Literal
import unicodedata
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from main import Base, Employee, Item, audit, auth, db, item_dict, permit, require_unreleased, utcnow


from permissions import ROLE_IDS

router = APIRouter(tags=['transfers'])
TRANSFER_ROLES = ROLE_IDS
MANAGE_ROLES = ('admin', 'supervisor')
KEEP_CURRENT = 'current'
LOCATIONS = (
    {'id': 'inventory', 'label': 'Inventory'},
    {'id': 'qa_001', 'label': 'QA/QC-001'},
    {'id': 'fabrication_prep', 'label': 'Prep/Fabrication'},
    {'id': 'qa_002', 'label': 'QA/QC-002'},
    {'id': 'floor', 'label': 'Floor'},
    {'id': 'welding', 'label': 'Process Welder'},
    {'id': 'qa_003', 'label': 'QA/QC-003'},
    {'id': 'testing', 'label': 'Testing'},
    {'id': 'qa_test_results', 'label': 'QA/QC-004'},
    {'id': 'blast_paint', 'label': 'Paint'},
    {'id': 'qa_004', 'label': 'QA/QC-005'},
    {'id': 'ready_to_ship', 'label': 'Ready To Ship'},
    {'id': 'receiving', 'label': 'Receiving'},
    {'id': 'material_storage', 'label': 'Material storage'},
    {'id': 'kitting', 'label': 'Kitting / component selection'},
    {'id': 'production_staging', 'label': 'Production staging'},
    {'id': 'fit_up', 'label': 'Fit-up'},
    {'id': 'qa_qc', 'label': 'QA / QC inspection', 'active': False},
    {'id': 'assembly', 'label': 'Assembly'},
    {'id': 'shipping', 'label': 'Shipping / dispatch'},
)
STATUSES = (
    {'id': 'queued', 'label': 'Queued'},
    {'id': 'in_progress', 'label': 'In progress'},
    {'id': 'awaiting_inspection', 'label': 'Awaiting inspection'},
    {'id': 'waiting_material', 'label': 'Waiting for material'},
    {'id': 'paused', 'label': 'Paused'},
    {'id': 'ready_next_operation', 'label': 'Ready for next operation'},
)
LOCATION_BY_ID = {row['id']: row for row in LOCATIONS}
STATUS_BY_ID = {row['id']: row for row in STATUSES}
OperationalStatus = Literal['queued', 'in_progress', 'awaiting_inspection', 'waiting_material', 'paused', 'ready_next_operation']


class ItemTransferState(Base):
    __tablename__ = 'item_transfer_states'
    __table_args__ = (CheckConstraint('version >= 1', name='ck_transfer_state_version'),)
    item_id = Column(String(60), ForeignKey('items.id'), primary_key=True)
    version = Column(Integer, nullable=False)
    # Built-in IDs and optional custom-location IDs share the same namespace.
    # A null ID preserves a legacy free-text location without inventing a site.
    location_id = Column(String(80))
    operational_status = Column(String(40))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class TransferLocation(Base):
    __tablename__ = 'transfer_locations'
    __table_args__ = (CheckConstraint('version >= 1', name='ck_transfer_location_version'),)
    id = Column(String(80), primary_key=True)
    label = Column(String(160), nullable=False)
    normalized_label = Column(String(480), nullable=False, unique=True)
    active = Column(Boolean, nullable=False, default=True)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    @field_validator('*', mode='before')
    @classmethod
    def no_null_characters(cls, value):
        if isinstance(value, str) and '\x00' in value:
            raise ValueError('Text cannot contain a null character')
        return value


class TransferIn(Input):
    sender_badge: str = Field(min_length=2, max_length=80)
    handler: str = Field(min_length=2, max_length=80)
    location_id: str = Field(min_length=1, max_length=80)
    operational_status: OperationalStatus
    expected_transfer_version: int = Field(ge=0, strict=True)
    notes: str = Field(default='', max_length=1000)
    expected_handler: str | None = Field(default=None, max_length=80)
    scan_method: Literal['manual', 'employee_qr'] = 'manual'


class LocationIn(Input):
    label: str = Field(min_length=2, max_length=160)

    @field_validator('label')
    @classmethod
    def clean_label(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('Location names cannot contain control characters')
        value = ' '.join(value.split())
        if len(value) < 2:
            raise ValueError('Location name must contain at least two characters')
        # Compatibility characters can expand substantially during NFKC
        # normalization; reject an overlong canonical name before SQL writes.
        if len(_normal_label(value)) > 480:
            raise ValueError('Location name is too long after Unicode normalization')
        return value


class LocationUpdate(LocationIn):
    active: bool = Field(strict=True)
    expected_version: int = Field(ge=1, strict=True)


def _utc(value):
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


def _stamp(value):
    return _utc(value).isoformat() if value else None


def _normal_label(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def location_dict(row):
    return {'id': row.id, 'label': row.label, 'kind': 'custom', 'active': row.active,
        'version': row.version, 'created_by': row.created_by, 'created_at': _stamp(row.created_at),
        'updated_by': row.updated_by, 'updated_at': _stamp(row.updated_at)}


def transfer_snapshot(s, item, user=None):
    from removals import item_is_removed, removal_summary
    state = s.get(ItemTransferState, item.id)
    employee = s.get(Employee, item.handler)
    status = state.operational_status if state else None
    active = not item_is_removed(s, item.id)
    return {'item_id': item.id, 'version': state.version if state else 0,
        'removal': removal_summary(s, 'item', item.id), 'can_mutate': active,
        'handler': item.handler, 'handler_name': employee.name if employee else item.handler,
        'handler_active': bool(employee and employee.active), 'location': item.location,
        'location_id': state.location_id if state and state.location_id else KEEP_CURRENT,
        'operational_status': status, 'status_label': STATUS_BY_ID[status]['label'] if status in STATUS_BY_ID else 'Not recorded',
        'updated_at': _stamp(state.updated_at) if state else None,
        'updated_by': state.updated_by if state else None, 'released': item.released,
        'can_transfer': bool(active and user and user.role in TRANSFER_ROLES and not item.released)}


def _locked_state(s, item, expected_version):
    state = s.scalar(select(ItemTransferState).where(ItemTransferState.item_id == item.id)
        .with_for_update().execution_options(populate_existing=True))
    version = state.version if state else 0
    if expected_version is None:
        raise HTTPException(422, 'Refresh the current transfer state before selecting the location')
    if version != expected_version:
        raise HTTPException(409, {'message': 'The item handoff changed; refresh and scan both badges again. No changes were saved.',
            'current_transfer_version': version})
    return state


def _destination(s, item, state, location_id):
    if location_id == KEEP_CURRENT:
        return state.location_id if state else None, item.location
    if location_id in LOCATION_BY_ID:
        return location_id, LOCATION_BY_ID[location_id]['label']
    row = s.scalar(select(TransferLocation).where(TransferLocation.id == location_id)
        .with_for_update().execution_options(populate_existing=True)) if location_id else None
    if not row or not row.active:
        raise HTTPException(422, 'Select an active destination location or keep the recorded current location')
    return row.id, row.label


@dataclass(frozen=True)
class CheckedLocation:
    state: ItemTransferState | None
    location_id: str | None
    location: str


@dataclass(frozen=True)
class CheckedTransfer(CheckedLocation):
    sender: Employee
    receiver: Employee
    operational_status: str


def validate_location(s, item, *, expected_transfer_version, location_id):
    from removals import require_active_item
    require_active_item(s, item.id)
    state = _locked_state(s, item, expected_transfer_version)
    destination_id, label = _destination(s, item, state, location_id)
    return CheckedLocation(state, destination_id, label)


def validate_transfer(s, item, *, sender_badge, receiver_badge, location_id,
                      operational_status, expected_transfer_version, allow_no_change=False):
    """Caller must hold the flow topology lock and the current Item row lock."""
    if not sender_badge or not receiver_badge:
        raise HTTPException(422, 'Scan both the sending and receiving employee badges')
    if operational_status not in STATUS_BY_ID:
        raise HTTPException(422, 'Select a current operational work status')
    selected = validate_location(s, item, expected_transfer_version=expected_transfer_version, location_id=location_id)
    employees = {row.badge: row for row in s.scalars(select(Employee)
        .where(Employee.badge.in_({sender_badge, receiver_badge})).order_by(Employee.badge)
        .with_for_update().execution_options(populate_existing=True))}
    sender, receiver = employees.get(sender_badge), employees.get(receiver_badge)
    if not sender or not sender.active:
        raise HTTPException(404, 'Active sending employee badge not found')
    if not receiver or not receiver.active:
        raise HTTPException(404, 'Active receiving employee badge not found')
    if sender.badge != item.handler:
        raise HTTPException(409, 'The sending badge must match the recorded current custodian; refresh and scan that employee badge')
    current_status = selected.state.operational_status if selected.state else None
    if not allow_no_change and (item.handler, item.location, current_status) == (receiver.badge, selected.location, operational_status):
        raise HTTPException(409, 'No change to current custodian, location or operational status')
    return CheckedTransfer(selected.state, selected.location_id, selected.location, sender, receiver, operational_status)


def _update_state(s, item, selected, actor, at, status):
    state = selected.state
    if state and at < _utc(state.updated_at):
        raise HTTPException(409, 'Server clock precedes the last handoff update; retry when time has caught up')
    if state is None:
        state = ItemTransferState(item_id=item.id, version=0, created_at=at)
        s.add(state)
    state.version += 1
    state.location_id = selected.location_id
    state.operational_status = status
    state.updated_by = actor.badge
    state.updated_at = at
    item.location = selected.location
    item.updated_at = at
    return state


def record_transfer(s, item, selected, actor, at, *, notes='', scan_method='manual', flow_step=None, scanned_item_id=None):
    before = {'handler': item.handler, 'location': item.location,
        'location_id': selected.state.location_id if selected.state else None,
        'operational_status': selected.state.operational_status if selected.state else None}
    previous_version = selected.state.version if selected.state else 0
    state = _update_state(s, item, selected, actor, at, selected.operational_status)
    item.handler = selected.receiver.badge
    details = {'from': before,
        'to': {'handler': item.handler, 'location': item.location, 'location_id': state.location_id,
            'operational_status': state.operational_status, 'name': selected.receiver.name},
        'sender': {'badge': selected.sender.badge, 'name': selected.sender.name},
        'receiver': {'badge': selected.receiver.badge, 'name': selected.receiver.name},
        'sender_badge': selected.sender.badge, 'receiver_badge': selected.receiver.badge,
        'custody_changed': before['handler'] != item.handler,
        'location_changed': before['location'] != item.location,
        'status_changed': before['operational_status'] != state.operational_status,
        'previous_transfer_version': previous_version, 'transfer_version': state.version,
        'handoff_recorded_by': actor.badge, 'recorder': {'badge': actor.badge, 'name': actor.name},
        'sender_acknowledged': False, 'recipient_acknowledged': False,
        'notes': notes, 'scan_method': scan_method}
    if flow_step is not None:
        details.update(flow_step=flow_step, scanned_item_id=scanned_item_id)
    audit(s, item.id, actor.badge, 'TRANSFER', details)
    return details


def record_location(s, item, selected, actor, at):
    before = {'location': item.location, 'location_id': selected.state.location_id if selected.state else None}
    previous_version = selected.state.version if selected.state else 0
    status = selected.state.operational_status if selected.state else None
    state = _update_state(s, item, selected, actor, at, status)
    details = {'from': before, 'to': {'location': item.location, 'location_id': state.location_id},
        'handler': item.handler, 'custody_changed': False, 'flow_step': 3,
        'previous_transfer_version': previous_version, 'transfer_version': state.version}
    audit(s, item.id, actor.badge, 'LOCATION_CAPTURED', details)
    return details


def _commit(s):
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, 'Conflicting handoff or location update; refresh and retry. No changes were saved.') from None


@router.get('/api/transfers/options')
def options(u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow_stations import LOCATION_STAGES
    return {'locations': [{**row, 'kind': 'builtin', 'active': row.get('active', True), 'version': 0,
                           'flow_stage_key': LOCATION_STAGES.get(row['id'])} for row in LOCATIONS]
        + [location_dict(row) for row in s.scalars(select(TransferLocation).order_by(TransferLocation.label, TransferLocation.id))],
        'statuses': STATUSES, 'keep_current_location_id': KEEP_CURRENT,
        'can_manage_locations': u.role in MANAGE_ROLES}


@router.get('/api/transfers/items/{item_id}')
def get_transfer(item_id: str, u: Employee = Depends(auth), s: Session = Depends(db)):
    item = s.get(Item, item_id)
    if not item:
        raise HTTPException(404, 'Item not found')
    return transfer_snapshot(s, item, u)


@router.post('/api/items/{item_id}/transfer')
def transfer(item_id: str, data: TransferIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import FlowPlan, _event, lock_topology
    from removals import require_active_item
    lock_topology(s)
    permit(u, *TRANSFER_ROLES)
    item = s.scalar(select(Item).where(Item.id == item_id).with_for_update().execution_options(populate_existing=True))
    if not item:
        raise HTTPException(404, 'Item not found')
    require_active_item(s, item_id)
    require_unreleased(item)
    if data.expected_handler is not None and data.expected_handler != item.handler:
        raise HTTPException(409, 'Item custodian changed since scanning; refresh and scan both badges again')
    selected = validate_transfer(s, item, sender_badge=data.sender_badge, receiver_badge=data.handler,
        location_id=data.location_id, operational_status=data.operational_status,
        expected_transfer_version=data.expected_transfer_version)
    now = _utc(utcnow())
    details = record_transfer(s, item, selected, u, now, notes=data.notes, scan_method=data.scan_method)
    plan = s.scalar(select(FlowPlan).where(FlowPlan.item_id == item.id).execution_options(populate_existing=True))
    if plan:
        # Invalidate old traveler forms without advancing a step, touching QA,
        # changing the process clock or rewriting the time a step was entered.
        _event(s, item, plan, u.badge, 'custody_transfer', plan.current_step, now, notes=data.notes, data=details)
    _commit(s)
    return item_dict(s, item, u)


def _check_label(s, label, exclude_id=None):
    normalized = _normal_label(label)
    if normalized in {_normal_label(row['label']) for row in LOCATIONS}:
        raise HTTPException(409, 'A built-in location already uses this name')
    query = select(TransferLocation).where(TransferLocation.normalized_label == normalized)
    if exclude_id is not None:
        query = query.where(TransferLocation.id != exclude_id)
    if s.scalar(query):
        raise HTTPException(409, 'A custom location already uses this name; reactivate it if needed')
    return normalized


@router.post('/api/transfers/locations', status_code=201)
def create_location(data: LocationIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    permit(u, *MANAGE_ROLES)
    normalized = _check_label(s, data.label)
    now = _utc(utcnow())
    row = TransferLocation(id='custom_' + uuid.uuid4().hex, label=data.label, normalized_label=normalized,
        active=True, version=1, created_by=u.badge, created_at=now, updated_by=u.badge, updated_at=now)
    s.add(row)
    audit(s, None, u.badge, 'TRANSFER_LOCATION_CREATED', location_dict(row))
    _commit(s)
    return location_dict(row)


@router.patch('/api/transfers/locations/{location_id}')
def update_location(location_id: str, data: LocationUpdate, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    permit(u, *MANAGE_ROLES)
    row = s.scalar(select(TransferLocation).where(TransferLocation.id == location_id)
        .with_for_update().execution_options(populate_existing=True))
    if not row:
        raise HTTPException(404, 'Custom location not found; built-in work centers cannot be edited')
    if row.version != data.expected_version:
        raise HTTPException(409, {'message': 'Location changed; refresh and retry', 'current_version': row.version})
    if (row.label, row.active) == (data.label, data.active):
        raise HTTPException(409, 'No change to the location name or active status')
    normalized = _check_label(s, data.label, row.id)
    before = location_dict(row)
    row.label, row.normalized_label, row.active = data.label, normalized, data.active
    row.version += 1
    row.updated_by, row.updated_at = u.badge, _utc(utcnow())
    audit(s, None, u.badge, 'TRANSFER_LOCATION_UPDATED', {'from': before, 'to': location_dict(row)})
    _commit(s)
    return location_dict(row)

