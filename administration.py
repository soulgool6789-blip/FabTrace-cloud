"""Explicit administrative decisions, separate from technical QA acceptance.

Release and custody exceptions append to the existing protected audit history.
No inspection, work event or recipient badge scan is invented by an override.
"""

import datetime as dt
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from main import (APP_VERSION, Base, Employee, Item, Audit, ITEM_KEYS, audit, auth, db,
                  item_dict, password_hash, permit, utcnow)


router = APIRouter(prefix='/api/admin', tags=['administration'])
RELEASE_EVENTS = ('FINAL_RELEASE', 'ADMIN_RELEASE_OVERRIDE', 'ADMIN_RETURN_TO_WORK', 'REOPENED')
ADMIN_EVENTS = ('ADMIN_RELEASE_OVERRIDE', 'ADMIN_RETURN_TO_WORK', 'ADMIN_CUSTODY_CORRECTION')
from permissions import (Role, ASSIGNABLE_ROLE_IDS, role_catalog, legacy_role_catalog,
                         role_label, user_permissions)


class EmployeeAccessState(Base):
    __tablename__ = 'employee_access_states'
    __table_args__ = (
        CheckConstraint('version >= 1', name='ck_employee_access_version'),
        CheckConstraint('session_version >= 0', name='ck_employee_session_version'),
    )
    badge = Column(String(80), ForeignKey('employees.badge'), primary_key=True)
    version = Column(Integer, nullable=False)
    session_version = Column(Integer, nullable=False, default=0)
    updated_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class EmployeeRemovalState(Base):
    """Current roster removal state; the employee identity is never deleted.

    Each removal/restoration also appends a protected Audit event. Keeping this
    additive table separate leaves existing employee records and foreign keys
    intact during upgrades and preserves their historical meaning.
    """
    __tablename__ = 'employee_removal_states'
    __table_args__ = (
        CheckConstraint(
            '(removed = true AND restored_at IS NULL AND restored_by IS NULL AND restoration_reason IS NULL) '
            'OR (removed = false AND restored_at IS NOT NULL AND restored_by IS NOT NULL AND restoration_reason IS NOT NULL)',
            name='ck_employee_removal_state'),
    )
    badge = Column(String(80), ForeignKey('employees.badge'), primary_key=True)
    removed = Column(Boolean, nullable=False, default=True)
    removed_at = Column(DateTime(timezone=True), nullable=False)
    removed_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    removal_reason = Column(Text, nullable=False)
    restored_at = Column(DateTime(timezone=True))
    restored_by = Column(String(80), ForeignKey('employees.badge'))
    restoration_reason = Column(Text)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @field_validator('*', mode='before')
    @classmethod
    def no_null_characters(cls, value):
        if isinstance(value, str) and '\x00' in value:
            raise ValueError('Text cannot contain a null character')
        return value


class ReasonIn(Input):
    reason: str = Field(min_length=4, max_length=3000)

    @field_validator('reason', mode='before')
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class DecisionIn(ReasonIn):
    expected_version: str = Field(pattern=r'^[a-f0-9]{64}$', strict=True)
    reference: str = Field(default='', max_length=500)

    @field_validator('reference', mode='before')
    @classmethod
    def trim_reference(cls, value):
        return value.strip() if isinstance(value, str) else value


class CustodyIn(DecisionIn):
    handler: str = Field(min_length=2, max_length=80)
    location_id: str = Field(min_length=1, max_length=80)
    operational_status: Literal['queued', 'in_progress', 'awaiting_inspection', 'waiting_material', 'paused', 'ready_next_operation']

    @field_validator('handler', 'location_id', mode='before')
    @classmethod
    def trim_identity(cls, value):
        return value.strip() if isinstance(value, str) else value


class EmployeeUpdateIn(ReasonIn):
    expected_version: int = Field(ge=0, strict=True)
    name: str = Field(min_length=2, max_length=160)
    role: Role
    active: bool = Field(strict=True)

    @field_validator('name', mode='before')
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class EmployeeRemovalIn(ReasonIn):
    expected_version: int = Field(ge=0, strict=True)


class PinIn(ReasonIn):
    expected_version: int = Field(ge=0, strict=True)
    pin: str = Field(min_length=8, max_length=128)

    @field_validator('pin')
    @classmethod
    def nonblank_pin(cls, value):
        if not value.strip():
            raise ValueError('PIN cannot be blank')
        return value


def _utc(value):
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


def _stamp(value):
    return _utc(value).isoformat() if value else None


def _dict(row, keys):
    return {key: _stamp(value) if isinstance(value, dt.datetime) else value
            for key in keys for value in (getattr(row, key),)}


def session_version(s, badge):
    state = s.get(EmployeeAccessState, badge)
    return state.session_version if state else 0


def employee_not_removed():
    """SQL predicate for operational rosters; never filter historical joins."""
    return ~select(EmployeeRemovalState.badge).where(
        EmployeeRemovalState.badge == Employee.badge,
        EmployeeRemovalState.removed.is_(True)).exists()


def employee_is_removed(s, badge):
    state = s.scalar(select(EmployeeRemovalState).where(EmployeeRemovalState.badge == badge)
        .execution_options(populate_existing=True))
    return bool(state and state.removed)


def validate_session(s, user, payload):
    version = payload.get('sv', 0)
    if employee_is_removed(s, user.badge) or type(version) is not int or version != session_version(s, user.badge):
        raise HTTPException(401, 'Your account access changed. Sign in again with your current badge and PIN.')
    s.info['authenticated_session'] = (user.badge, version)


def refresh_session_authority(s):
    """Revalidate a queued writer after the shared topology lock is held.

    No Employee row lock is taken: Item writers later acquire Employee foreign
    key locks, and reversing that order would create a lock inversion.
    """
    authenticated = s.info.get('authenticated_session')
    if authenticated is None:
        return None  # Internal migration/projection callers have no session.
    badge, validated_version = authenticated
    current = s.scalar(select(Employee).where(Employee.badge == badge)
        .execution_options(populate_existing=True))
    access = s.scalar(select(EmployeeAccessState).where(EmployeeAccessState.badge == badge)
        .execution_options(populate_existing=True))
    version = access.session_version if access else 0
    if not current or not current.active or employee_is_removed(s, badge) or version != validated_version:
        raise HTTPException(401, 'Your account access changed while this request was waiting. Sign in again.')
    return current


def release_summary(s, item):
    """Pure, non-recursive projection; normal historical release remains compatible."""
    result = {'mode': 'not_released', 'label': 'Not released', 'qa_released': False,
              'active_override': False, 'override': None}
    if not item.released:
        return result
    latest = s.scalar(select(Audit).where(Audit.item_id == item.id,
        Audit.event.in_(RELEASE_EVENTS)).order_by(Audit.id.desc()).limit(1))
    if latest and latest.event == 'ADMIN_RELEASE_OVERRIDE':
        details = latest.details
        result.update(mode='admin_override', label='Administrative release', active_override=True,
            override={'audit_id': latest.id, 'actor': latest.actor, 'at': _stamp(latest.at),
                'reason': details.get('reason', ''), 'reference': details.get('reference', ''),
                'bypassed_blockers': details.get('bypassed_blockers', []),
                'prior_flow': details.get('prior_flow')})
    else:
        result.update(mode='qa', label='QA released', qa_released=True)
    return result


def active_override(s, item):
    return release_summary(s, item)['override']


def locked_admin(s, user):
    """Serialize administrative decisions, then refresh the actor's authority."""
    from flow import lock_topology
    lock_topology(s)
    # Account mutations share the topology lock. Do not lock the actor row
    # before Item: legacy work inserts take an Employee FK key-share lock
    # after Item, so reversing those locks could deadlock a queued decision.
    current = s.scalar(select(Employee).where(Employee.badge == user.badge)
        .execution_options(populate_existing=True))
    if not current or not current.active or employee_is_removed(s, user.badge):
        raise HTTPException(401, 'Inactive employee')
    permit(current, 'admin')
    access = s.scalar(select(EmployeeAccessState).where(EmployeeAccessState.badge == current.badge)
        .execution_options(populate_existing=True))
    version = access.session_version if access else 0
    if s.info.get('authenticated_session') != (current.badge, version):
        raise HTTPException(401, 'Your account access changed while this request was waiting. Sign in again.')
    return current


def _locked_item(s, item_id, user):
    current = locked_admin(s, user)
    item = s.scalar(select(Item).where(Item.id == item_id).with_for_update()
        .execution_options(populate_existing=True))
    if not item:
        raise HTTPException(404, 'Item not found')
    from removals import require_active_item
    require_active_item(s, item_id)
    return item, current


def _commit(s):
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, 'Conflicting administrative change; refresh and review the latest record. No changes were saved.') from None


def _flow_record(s, item):
    from flow import FlowPlan, PLAN_KEYS
    plan = s.scalar(select(FlowPlan).where(FlowPlan.item_id == item.id)
        .execution_options(populate_existing=True))
    return plan, _dict(plan, PLAN_KEYS) if plan else None


def decision_basis(s, item, *, for_update=False):
    from main import release_blockers
    from transfers import transfer_snapshot
    blockers = release_blockers(s, item, for_update=for_update)
    plan, flow = _flow_record(s, item)
    transfer = transfer_snapshot(s, item)
    latest_audit_id = s.scalar(select(func.max(Audit.id)).where(Audit.item_id == item.id)) or 0
    data = {'item': _dict(item, ITEM_KEYS), 'flow': flow, 'blockers': blockers,
            'transfer_version': transfer['version'], 'latest_audit_id': latest_audit_id}
    version = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    return version, blockers, plan, flow


def _check_version(s, item, expected):
    version, blockers, plan, prior_flow = decision_basis(s, item, for_update=True)
    if expected != version:
        raise HTTPException(409, 'This item or its release checks changed. Refresh and review the current record before applying an administrative decision.')
    return blockers, plan, prior_flow


def admin_detail(s, item, user):
    from removals import item_is_removed, removal_summary
    from spool_receiving import receiving_errors
    from tracking import post_fabrication_heat_errors
    version, blockers, plan, _ = decision_basis(s, item)
    release = release_summary(s, item)
    actions = ['custody_correction']
    if not item.released and not receiving_errors(s, item) and not post_fabrication_heat_errors(s, item):
        actions.append('release_override')
    elif item.released and (not plan or plan.status not in ('shipped', 'delivered')):
        actions.append('return_to_work')
    active = not item_is_removed(s, item.id)
    if not active:
        actions = []
    history = s.scalars(select(Audit).where(Audit.item_id == item.id,
        Audit.event.in_(ADMIN_EVENTS)).order_by(Audit.id.desc()).limit(100)).all()
    return {'item': item_dict(s, item, user), 'version': version, 'release': release,
            'removal': removal_summary(s, 'item', item.id), 'can_mutate': active,
            'blockers': blockers, 'allowed_actions': actions,
            'history': [_dict(row, ('id', 'item_id', 'actor', 'event', 'details', 'at')) for row in history]}


@router.get('/overview')
def overview(u: Employee = Depends(auth), s: Session = Depends(db)):
    from removals import item_not_removed
    permit(u, 'admin')
    employees = s.scalars(select(Employee).where(employee_not_removed())).all()
    items = s.scalars(select(Item).where(item_not_removed())).all()
    return {'version': APP_VERSION, 'counts': {'items': len(items),
        'released': sum(bool(row.released) for row in items),
        'admin_released': sum(bool(active_override(s, row)) for row in items),
        'on_hold': sum(bool(row.on_hold) for row in items), 'employees': len(employees),
        'active_admins': sum(row.active and row.role == 'admin' for row in employees),
        'removed_employees': s.scalar(select(func.count()).select_from(EmployeeRemovalState)
            .where(EmployeeRemovalState.removed.is_(True)))},
        'capabilities': ['release_override', 'return_to_work', 'custody_correction', 'employee_access',
                         'pin_reset', 'employee_remove', 'employee_restore']}


@router.get('/items')
def items(search: str = '', limit: int = 100, offset: int = 0,
          u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import FlowPlan
    from removals import item_not_removed
    permit(u, 'admin')
    limit, offset = min(max(limit, 1), 200), max(offset, 0)
    query = select(Item).where(item_not_removed())
    if search:
        value = '%' + search[:100] + '%'
        query = query.where(Item.id.ilike(value) | Item.description.ilike(value) | Item.project.ilike(value))
    total = s.scalar(select(func.count()).select_from(query.subquery()))
    result = []
    for item in s.scalars(query.order_by(Item.updated_at.desc(), Item.id).limit(limit).offset(offset)):
        release = release_summary(s, item)
        flow = s.get(FlowPlan, item.id)
        result.append({**_dict(item, ('id', 'description', 'kind', 'project', 'location', 'handler', 'released')),
            'release_mode': release['mode'], 'release_label': release['label'],
            'flow_step': flow.current_step if flow else None, 'flow_status': flow.status if flow else None})
    return {'items': result, 'total': total, 'limit': limit, 'offset': offset}


@router.get('/items/{item_id}')
def get_item(item_id: str, u: Employee = Depends(auth), s: Session = Depends(db)):
    permit(u, 'admin')
    item = s.get(Item, item_id)
    if not item:
        raise HTTPException(404, 'Item not found')
    return admin_detail(s, item, u)


@router.post('/items/{item_id}/release')
def release_override(item_id: str, data: DecisionIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import step_definition, _event
    from production import sync_flow_process
    item, actor = _locked_item(s, item_id, u)
    blockers, plan, prior_flow = _check_version(s, item, data.expected_version)
    if item.released:
        raise HTTPException(409, 'This item is already released. Review its current release record.')
    from spool_receiving import require_receiving_pass
    require_receiving_pass(s, item)
    from tracking import post_fabrication_heat_errors
    heat_errors = post_fabrication_heat_errors(s, item)
    if heat_errors:
        raise HTTPException(409, {'release_blockers': heat_errors})
    now = _utc(utcnow())
    details = {'reason': data.reason, 'reference': data.reference, 'bypassed_blockers': blockers,
        'prior_flow': prior_flow, 'prior_release': {'released': item.released,
            'released_at': _stamp(item.released_at), 'released_by': item.released_by},
        'quality_acceptance_recorded': False, 'physical_work_recorded': False}
    item.released, item.released_at, item.released_by, item.updated_at = True, now, actor.badge, now
    if plan:
        if plan.route in ('spool', 'assembly'):
            target = 16 if plan.route == 'spool' else 23
            plan.current_step, plan.status, plan.step_entered_at, plan.completed_at = target, 'active', now, None
        else:
            target = None
            plan.current_step, plan.status, plan.step_entered_at, plan.completed_at = None, 'admin_released', None, None
        _event(s, item, plan, actor.badge, 'admin_release', prior_flow['current_step'], now,
            reference=data.reference, notes=data.reason,
            data={**details, 'next_step': target, 'skipped_steps_not_completed': True})
        sync_flow_process(s, item, actor.badge, step_definition(plan, target) if target else None, now,
            'Administrative release override; missing work and QA remain unverified. ' + data.reason)
    else:
        sync_flow_process(s, item, actor.badge, None, now,
            'Process timing stopped by an administrative release override. ' + data.reason)
    audit(s, item.id, actor.badge, 'ADMIN_RELEASE_OVERRIDE', details)
    _commit(s)
    return admin_detail(s, item, actor)


@router.post('/items/{item_id}/return-to-work')
def return_to_work(item_id: str, data: DecisionIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import current_step_definition, _event, guard_reopen, on_item_reopened
    from production import sync_flow_process
    from tracking import is_tracked, reopen_tracked
    item, actor = _locked_item(s, item_id, u)
    _, plan, current_flow = _check_version(s, item, data.expected_version)
    if not item.released:
        raise HTTPException(409, 'This item is already open for work.')
    if plan and plan.status in ('shipped', 'delivered'):
        raise HTTPException(409, 'An actual shipped or delivered record cannot be undone by returning it to production.')
    release = release_summary(s, item)
    override = release['override']
    now = _utc(utcnow())
    if not override:
        guard_reopen(s, item)
    item.released, item.released_at, item.released_by, item.updated_at = False, None, None, now
    if override:
        prior = override.get('prior_flow')
        if plan and prior:
            # Keep all historical timestamps/attempts; the resumed step gets a
            # new timed visit. No inspection or actual work state is replaced.
            target = prior['current_step']
            plan.current_step, plan.status = target, prior['status']
            from flow_testing import ACTIVE_PHASES, FlowTestingState, PHASE_STEP, PROTOCOL
            testing = s.get(FlowTestingState, item.id) if plan.route == 'assembly' else None
            pending_phase = (testing.phase if testing and testing.protocol == PROTOCOL
                             and testing.phase in ACTIVE_PHASES else None)
            if pending_phase:
                target = PHASE_STEP[pending_phase]
                plan.current_step, plan.status = target, 'active'
            plan.step_entered_at = now if target is not None and plan.status == 'active' else None
            plan.completed_at = (dt.datetime.fromisoformat(prior['completed_at'])
                                 if prior.get('completed_at') and not pending_phase else None)
            _event(s, item, plan, actor.badge, 'admin_return_to_work', target, now,
                reference=data.reference, notes=data.reason,
                data={'return_step': target, 'override_audit_id': override['audit_id'],
                      'prior_override_flow': current_flow,
                      **({'restored_testing_phase': pending_phase} if pending_phase else {})})
            sync_flow_process(s, item, actor.badge, current_step_definition(s, plan) if target is not None and plan.status == 'active' else None,
                now, 'Returned to the pre-override production position. ' + data.reason)
    else:
        item.reinspection_due, item.dimensional, item.weld = True, 'Not started', 'Not started'
        if is_tracked(s, item):
            reopen_tracked(s, item, actor.badge, 'Administrative return to work: ' + data.reason)
        on_item_reopened(s, item, actor.badge, now)
    audit(s, item.id, actor.badge, 'ADMIN_RETURN_TO_WORK', {'reason': data.reason,
        'reference': data.reference, 'previous_release': release, 'restored_prior_flow': bool(override),
        'fresh_qa_required': not bool(override)})
    _commit(s)
    return admin_detail(s, item, actor)


@router.post('/items/{item_id}/custody')
def custody_correction(item_id: str, data: CustodyIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import _event
    from transfers import transfer_snapshot, validate_location, _update_state
    item, actor = _locked_item(s, item_id, u)
    _, plan, _ = _check_version(s, item, data.expected_version)
    current = transfer_snapshot(s, item)
    selected = validate_location(s, item, expected_transfer_version=current['version'], location_id=data.location_id)
    receiver = s.scalar(select(Employee).where(Employee.badge == data.handler).with_for_update()
        .execution_options(populate_existing=True))
    if not receiver or not receiver.active or employee_is_removed(s, data.handler):
        raise HTTPException(422, 'Select an active employee as the corrected custodian.')
    if (item.handler, item.location, current['operational_status']) == (receiver.badge, selected.location, data.operational_status):
        raise HTTPException(409, 'No change to the current custodian, location or work status.')
    now = _utc(utcnow())
    before = {'handler': item.handler, 'location': item.location, 'location_id': current['location_id'],
              'operational_status': current['operational_status']}
    updated = _update_state(s, item, selected, actor, now, data.operational_status)
    item.handler = receiver.badge
    details = {'reason': data.reason, 'reference': data.reference,
        'administrative_correction': True, 'badge_scans_recorded': False,
        'from': before, 'to': {'handler': receiver.badge, 'name': receiver.name,
            'location': item.location, 'location_id': updated.location_id, 'operational_status': updated.operational_status},
        'custody_changed': before['handler'] != receiver.badge,
        'previous_transfer_version': current['version'], 'transfer_version': updated.version}
    if plan:
        _event(s, item, plan, actor.badge, 'admin_custody_correction', plan.current_step, now,
               reference=data.reference, notes=data.reason, data=details)
    audit(s, item.id, actor.badge, 'ADMIN_CUSTODY_CORRECTION', details)
    _commit(s)
    return admin_detail(s, item, actor)


def _active_admin_count(s):
    return s.scalar(select(func.count()).select_from(Employee).where(
        Employee.active.is_(True), Employee.role == 'admin', employee_not_removed()))


def _employee_dict(s, employee, *, active_admins=None, assigned_item_count=None):
    access = s.get(EmployeeAccessState, employee.badge)
    removal = s.get(EmployeeRemovalState, employee.badge)
    removed = bool(removal and removal.removed)
    active_admins = _active_admin_count(s) if active_admins is None else active_admins
    last_admin = employee.active and employee.role == 'admin' and active_admins <= 1
    if assigned_item_count is None:
        assigned_item_count = s.scalar(select(func.count()).select_from(Item).where(Item.handler == employee.badge))
    return {**_dict(employee, ('badge', 'name', 'role', 'active')),
        'role_label': role_label(employee), 'permissions': user_permissions(employee),
        'version': access.version if access else 0,
        'removed': removed, 'removed_at': _stamp(removal.removed_at) if removal else None,
        'removed_by': removal.removed_by if removal else None,
        'removal_reason': removal.removal_reason if removal else None,
        'restored_at': _stamp(removal.restored_at) if removal else None,
        'restored_by': removal.restored_by if removal else None,
        'restoration_reason': removal.restoration_reason if removal else None,
        'can_edit': not removed, 'can_reset_pin': not removed,
        'can_remove': not removed and not last_admin, 'can_restore': removed,
        'remove_block_reason': 'Keep at least one active administrator.' if not removed and last_admin else None,
        'assigned_item_count': assigned_item_count}


@router.get('/employees')
def employees(include_removed: bool = False, u: Employee = Depends(auth), s: Session = Depends(db)):
    permit(u, 'admin')
    query = select(Employee).order_by(Employee.name, Employee.badge)
    if not include_removed:
        query = query.where(employee_not_removed())
    rows = s.scalars(query).all()
    active_admins = _active_admin_count(s)
    assigned = dict(s.execute(select(Item.handler, func.count()).group_by(Item.handler)).all())
    return {'employees': [_employee_dict(s, row, active_admins=active_admins,
                                        assigned_item_count=assigned.get(row.badge, 0)) for row in rows],
            # Older open pages use this full list to retain an employee's
            # saved selection. New controls filter selectable:false entries.
            'roles': role_catalog() + legacy_role_catalog(),
            'legacy_roles': legacy_role_catalog(), 'active_admins': active_admins,
            'removed_count': s.scalar(select(func.count()).select_from(EmployeeRemovalState)
                .where(EmployeeRemovalState.removed.is_(True)))}


def _locked_employee(s, badge, user, expected):
    actor = locked_admin(s, user)
    employee = s.scalar(select(Employee).where(Employee.badge == badge).with_for_update()
        .execution_options(populate_existing=True))
    if not employee:
        raise HTTPException(404, 'Employee badge not found')
    access = s.scalar(select(EmployeeAccessState).where(EmployeeAccessState.badge == badge).with_for_update()
        .execution_options(populate_existing=True))
    version = access.version if access else 0
    if version != expected:
        raise HTTPException(409, 'The employee record changed. Refresh before making another access change.')
    return employee, access, actor


def _update_access(s, employee, access, actor, now, revoke):
    if access is None:
        access = EmployeeAccessState(badge=employee.badge, version=0, session_version=0)
        s.add(access)
    access.version += 1
    access.session_version += int(revoke)
    access.updated_by, access.updated_at = actor.badge, now
    return access


@router.patch('/employees/{badge}')
def update_employee(badge: str, data: EmployeeUpdateIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    employee, access, actor = _locked_employee(s, badge, u, data.expected_version)
    if employee_is_removed(s, badge):
        raise HTTPException(409, 'Restore this removed employee before editing their account.')
    if data.role not in ASSIGNABLE_ROLE_IDS and data.role != employee.role:
        raise HTTPException(422, 'This position is retained only for an existing assignment. Choose a current position.')
    if (employee.name, employee.role, employee.active) == (data.name, data.role, data.active):
        raise HTTPException(409, 'No change to the employee profile or access.')
    if employee.active and employee.role == 'admin' and not (data.active and data.role == 'admin'):
        if _active_admin_count(s) <= 1:
            raise HTTPException(409, 'Keep at least one active administrator. Add or promote another administrator before removing this access.')
    before = _employee_dict(s, employee)
    revoke = (employee.role, employee.active) != (data.role, data.active)
    employee.name, employee.role, employee.active = data.name, data.role, data.active
    _update_access(s, employee, access, actor, _utc(utcnow()), revoke)
    s.flush()
    after = _employee_dict(s, employee)
    audit(s, None, actor.badge, 'EMPLOYEE_UPDATED', {'reason': data.reason,
        'from': before, 'to': after, 'existing_sessions_revoked': revoke})
    _commit(s)
    return {**after, 'reauthenticate': revoke and actor.badge == employee.badge}


@router.post('/employees/{badge}/pin')
def reset_pin(badge: str, data: PinIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    employee, access, actor = _locked_employee(s, badge, u, data.expected_version)
    if employee_is_removed(s, badge):
        raise HTTPException(409, 'Restore this removed employee before resetting their PIN.')
    employee.pin_hash = password_hash.hash(data.pin)
    access = _update_access(s, employee, access, actor, _utc(utcnow()), True)
    audit(s, None, actor.badge, 'EMPLOYEE_PIN_RESET', {'badge': employee.badge, 'reason': data.reason,
        'version': access.version, 'existing_sessions_revoked': True})
    _commit(s)
    return {**_employee_dict(s, employee), 'reauthenticate': actor.badge == employee.badge}


@router.post('/employees/{badge}/remove')
def remove_employee(badge: str, data: EmployeeRemovalIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    employee, access, actor = _locked_employee(s, badge, u, data.expected_version)
    removal = s.scalar(select(EmployeeRemovalState).where(EmployeeRemovalState.badge == badge)
        .with_for_update().execution_options(populate_existing=True))
    if removal and removal.removed:
        raise HTTPException(409, 'This employee has already been removed.')
    if employee.active and employee.role == 'admin' and _active_admin_count(s) <= 1:
        raise HTTPException(409, 'Keep at least one active administrator. Add or promote another administrator before removing this employee.')
    before = _employee_dict(s, employee)
    now = _utc(utcnow())
    if removal is None:
        removal = EmployeeRemovalState(badge=badge)
        s.add(removal)
    removal.removed, removal.removed_at, removal.removed_by = True, now, actor.badge
    removal.removal_reason = data.reason
    removal.restored_at, removal.restored_by, removal.restoration_reason = None, None, None
    employee.active = False
    _update_access(s, employee, access, actor, now, True)
    s.flush()
    after = _employee_dict(s, employee)
    audit(s, None, actor.badge, 'EMPLOYEE_REMOVED', {'badge': badge, 'reason': data.reason,
        'from': before, 'to': after, 'existing_sessions_revoked': True, 'custody_reassigned': False})
    _commit(s)
    return {**after, 'reauthenticate': actor.badge == badge}


@router.post('/employees/{badge}/restore')
def restore_employee(badge: str, data: EmployeeRemovalIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    employee, access, actor = _locked_employee(s, badge, u, data.expected_version)
    removal = s.scalar(select(EmployeeRemovalState).where(EmployeeRemovalState.badge == badge)
        .with_for_update().execution_options(populate_existing=True))
    if not removal or not removal.removed:
        raise HTTPException(409, 'This employee is not removed.')
    before = _employee_dict(s, employee)
    now = _utc(utcnow())
    removal.removed, removal.restored_at, removal.restored_by = False, now, actor.badge
    removal.restoration_reason = data.reason
    # Roster restoration is explicit and does not silently re-enable access or
    # revive a previously revoked session. The administrator can review the
    # position/PIN and activate the account through the existing edit controls.
    employee.active = False
    _update_access(s, employee, access, actor, now, True)
    s.flush()
    after = _employee_dict(s, employee)
    audit(s, None, actor.badge, 'EMPLOYEE_RESTORED', {'badge': badge, 'reason': data.reason,
        'from': before, 'to': after, 'existing_sessions_revoked': True, 'access_restored': False})
    _commit(s)
    return {**after, 'reauthenticate': False}

