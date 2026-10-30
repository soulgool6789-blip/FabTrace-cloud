"""Reversible, administrator-controlled removal of order and physical records.

Removal hides a current working scope; original identities, links, quantities,
work and quality evidence are retained. A root operation marks its currently
active descendants in one batch. Restoring that root restores only that batch,
so earlier independent removals never become active by accident.
"""
import datetime as dt
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from main import Audit, Base, Employee, Item, audit, auth, db, permit, utcnow
from tracking import Project, SpoolPlan, new_id
from flow import ComponentLink, FlowPlan
from orders import OrderAssembly, OrderGpn, PurchaseOrder

router = APIRouter(prefix='/api/removals', tags=['removed records'])
Kind = Literal['order', 'gpn', 'item']
Action = Literal['remove', 'restore']
KINDS = ('order', 'gpn', 'item')


class RecordRemoval(Base):
    __tablename__ = 'record_removals'
    __table_args__ = (
        CheckConstraint("kind IN ('order','gpn','item')", name='ck_record_removal_kind'),
        CheckConstraint("root_kind IN ('order','gpn','item')", name='ck_record_removal_root_kind'),
        CheckConstraint('version >= 1', name='ck_record_removal_version'),
    )
    kind = Column(String(12), primary_key=True)
    record_id = Column(String(80), primary_key=True)
    removed = Column(Boolean, nullable=False)
    version = Column(Integer, nullable=False)
    batch_id = Column(String(60), nullable=False, index=True)
    root_kind = Column(String(12), nullable=False)
    root_id = Column(String(80), nullable=False)
    reason = Column(Text, nullable=False)
    changed_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class ChangeIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_version: int = Field(ge=0, strict=True)
    preview_token: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    confirmation: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=4, max_length=3000)

    @field_validator('*', mode='before')
    @classmethod
    def valid_text(cls, value):
        if isinstance(value, str) and '\x00' in value:
            raise ValueError('Text cannot contain a null character')
        return value


def _stamp(value):
    if value is None:
        return None
    return (value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None
            else value.astimezone(dt.timezone.utc)).isoformat()


def _values(row):
    if row is None:
        return None
    return {column.name: _stamp(value) if isinstance(value, dt.datetime) else value
            for column in row.__table__.columns for value in (getattr(row, column.name),)}


def _state(s, kind, record_id):
    return s.scalar(select(RecordRemoval).where(RecordRemoval.kind == kind,
        RecordRemoval.record_id == record_id).execution_options(populate_existing=True))


def removal_summary(s, kind, record_id):
    state = _state(s, kind, record_id)
    if state is None:
        return None
    return {'removed': state.removed, 'version': state.version, 'reason': state.reason,
            'at': _stamp(state.changed_at), 'actor': state.changed_by,
            'root_kind': state.root_kind, 'root_id': state.root_id, 'batch_id': state.batch_id}


# Keep these predicates correlated with the caller's actual identity column.
# Historical joins intentionally do not use them.
def _not_removed(kind, column):
    return ~select(RecordRemoval.record_id).where(RecordRemoval.kind == kind,
        RecordRemoval.record_id == column, RecordRemoval.removed.is_(True)).exists()


def item_not_removed(column=Item.id):
    return _not_removed('item', column)


def project_not_removed(column):
    return _not_removed('order', column)


def gpn_not_removed(column=OrderGpn.id):
    return _not_removed('gpn', column)


def item_is_removed(s, item_id):
    state = _state(s, 'item', item_id)
    return bool(state and state.removed)


def project_is_removed(s, project_id):
    state = _state(s, 'order', project_id)
    return bool(state and state.removed)


def gpn_is_removed(s, gpn_id):
    state = _state(s, 'gpn', gpn_id)
    return bool(state and state.removed)


def _parents(s, item_id):
    from parts import PartAllocation, PartLine
    from order_spools import registered_spool
    result = set()
    plan = s.get(SpoolPlan, item_id)
    if plan and plan.assembly_id:
        result.add(plan.assembly_id)
    registration = registered_spool(s, item_id)
    if registration:
        result.add(registration.assembly_id)
    link = s.get(ComponentLink, item_id)
    if link:
        result.add(link.spool_id)
    allocation = s.get(PartAllocation, item_id)
    if allocation:
        line = s.get(PartLine, allocation.line_id)
        if line:
            result.add(line.spool_id)
    return result


def _project_id(s, item_id, visited=None):
    """Match authoritative plan, parent scope, mapping, then exact legacy ID."""
    visited = set() if visited is None else visited
    if item_id in visited:
        return None
    visited.add(item_id)
    plan = s.get(SpoolPlan, item_id)
    if plan:
        return plan.project_id
    for parent in sorted(_parents(s, item_id)):
        project_id = _project_id(s, parent, visited)
        if project_id:
            return project_id
    mapping = s.get(OrderAssembly, item_id)
    if mapping:
        group = s.get(OrderGpn, mapping.gpn_id)
        if group:
            return group.project_id
    item = s.get(Item, item_id)
    return item.project if item else None


def require_active_project(s, project_id):
    if project_id and project_is_removed(s, project_id):
        raise HTTPException(409, 'This P.O. has been removed. An administrator must restore it from Removed records before changing its work.')


def require_active_gpn(s, gpn_id):
    if gpn_is_removed(s, gpn_id):
        raise HTTPException(409, 'This GPN / Assembly has been removed. An administrator must restore it from Removed records before making changes.')
    group = s.get(OrderGpn, gpn_id)
    if group:
        require_active_project(s, group.project_id)


def require_active_item(s, item_id):
    seen, pending = set(), [item_id]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if item_is_removed(s, current):
            raise HTTPException(409, 'This item or its parent has been removed. An administrator must restore it from Removed records before work, transfers or changes.')
        mapping = s.get(OrderAssembly, current)
        if mapping:
            require_active_gpn(s, mapping.gpn_id)
        pending.extend(_parents(s, current))
    require_active_project(s, _project_id(s, item_id))


def _record(s, kind, record_id):
    model = {'order': PurchaseOrder, 'gpn': OrderGpn, 'item': Item}[kind]
    row = s.get(model, record_id)
    if row is None:
        raise HTTPException(404, 'Record not found')
    return row


def _identity(s, kind, record_id):
    row = _record(s, kind, record_id)
    if kind == 'order':
        title, confirmation = 'P.O. ' + row.purchase_order, row.purchase_order
    elif kind == 'gpn':
        title, confirmation = 'GPN / Assembly ' + row.gpn, row.gpn
    else:
        title = row.kind + ' ' + row.id
        if row.google_part_number:
            title += ' · ' + row.google_part_number
        confirmation = row.id
    return {'kind': kind, 'record_id': record_id, 'title': title, 'confirmation': confirmation}


def _descendants(s, item_ids):
    from parts import PartAllocation, PartLine
    from order_spools import OrderSpool
    descendants = set(item_ids)
    while True:
        previous = len(descendants)
        if descendants:
            descendants.update(s.scalars(select(SpoolPlan.item_id).where(SpoolPlan.assembly_id.in_(descendants))))
            descendants.update(s.scalars(select(OrderSpool.item_id).where(OrderSpool.assembly_id.in_(descendants))))
            descendants.update(s.scalars(select(ComponentLink.component_id).where(ComponentLink.spool_id.in_(descendants))))
            descendants.update(s.scalars(select(PartAllocation.component_id).join(PartLine,
                PartLine.id == PartAllocation.line_id).where(PartLine.spool_id.in_(descendants))))
        if len(descendants) == previous:
            return descendants


def _scope(s, kind, record_id):
    from order_setup import OrderAssemblyRequirement

    _record(s, kind, record_id)
    orders, groups, items = set(), set(), set()
    if kind == 'order':
        orders.add(record_id)
        groups.update(s.scalars(select(OrderGpn.id).where(OrderGpn.project_id == record_id)))
        # Plan/parent/mapping precedence avoids sweeping a different project's
        # item merely because an old free-text Item.project value is stale.
        items.update(item.id for item in s.scalars(select(Item)).all()
                     if _project_id(s, item.id) == record_id)
    elif kind == 'gpn':
        groups.add(record_id)
    else:
        items.add(record_id)
    if groups:
        items.update(s.scalars(select(OrderAssembly.item_id).where(OrderAssembly.gpn_id.in_(groups))))
    items = _descendants(s, items)
    # A legacy grouping row follows its last physical instance out of the
    # working register. An explicit quantity plan remains independently useful:
    # removing one registered assembly must not erase the remaining PO demand.
    for mapping in s.scalars(select(OrderAssembly).where(OrderAssembly.item_id.in_(items))).all() if items else []:
        siblings = set(s.scalars(select(OrderAssembly.item_id).where(OrderAssembly.gpn_id == mapping.gpn_id)))
        active_siblings = {value for value in siblings if not item_is_removed(s, value)}
        if active_siblings.issubset(items) and s.get(OrderAssemblyRequirement, mapping.gpn_id) is None:
            groups.add(mapping.gpn_id)
    return sorted([('order', value) for value in orders] + [('gpn', value) for value in groups] + [('item', value) for value in items])


def _restore_scope(s, state):
    if state is None:
        return []
    rows = s.scalars(select(RecordRemoval).where(RecordRemoval.removed.is_(True),
        RecordRemoval.batch_id == state.batch_id, RecordRemoval.root_kind == state.root_kind,
        RecordRemoval.root_id == state.root_id)).all()
    return sorted((row.kind, row.record_id) for row in rows)


def _counts(keys):
    return {'orders': sum(kind == 'order' for kind, _ in keys),
            'gpns': sum(kind == 'gpn' for kind, _ in keys),
            'items': sum(kind == 'item' for kind, _ in keys)}


def _project_ids(s, keys):
    result = set()
    for kind, record_id in keys:
        if kind == 'order':
            result.add(record_id)
        elif kind == 'gpn':
            result.add(_record(s, kind, record_id).project_id)
        else:
            value = _project_id(s, record_id)
            if value and s.get(PurchaseOrder, value):
                result.add(value)
    return result


def _blockers(s, kind, record_id, action, state, scope):
    from production import SpoolProcessEvent
    from parts import PartAllocation
    from order_spools import registered_spool, effective_children
    blockers, scope_set = [], set(scope)
    if action == 'remove':
        if state and state.removed:
            return ['This record is already removed. Refresh Removed records to restore its original removal group.']
        for item_kind, item_id in scope:
            if item_kind == 'order':
                continue
            if item_kind == 'gpn':
                project_id = _record(s, item_kind, item_id).project_id
                if ('order', project_id) not in scope_set and project_is_removed(s, project_id):
                    blockers.append('Restore the parent P.O. before removing this GPN / Assembly separately.')
                continue
            for parent in sorted(_parents(s, item_id)):
                if ('item', parent) not in scope_set:
                    registration = registered_spool(s, item_id)
                    if (registration and parent == registration.assembly_id
                            and s.get(SpoolPlan, item_id) is None
                            and s.get(ComponentLink, item_id) is None
                            and s.get(PartAllocation, item_id) is None):
                        # A registration reserves identity and parent only. It
                        # can be removed/replaced without inventing an unlink
                        # or altering the saved demand. Keep its fixed parent
                        # for history and enforce capacity on restoration.
                        continue
                    if registration:
                        blockers.append(f'{item_id} has planned work in assembly {parent}. Remove the containing assembly/P.O. together to preserve its physical spool identities and work.')
                    else:
                        blockers.append(f'{item_id} is linked to {parent}. Unassign it through Spool parts or correct its weld plan first, or remove the containing assembly/P.O. together.')
            project_id = _project_id(s, item_id)
            if project_id and ('order', project_id) not in scope_set and project_is_removed(s, project_id):
                blockers.append(f'Restore the parent P.O. before removing {item_id} separately.')
            latest = s.scalar(select(SpoolProcessEvent).where(SpoolProcessEvent.item_id == item_id)
                .order_by(SpoolProcessEvent.sequence.desc()).limit(1))
            if latest and latest.event not in ('finish', 'release'):
                if s.get(FlowPlan, item_id):
                    blockers.append(f'{item_id} has an open numbered-process timer. Complete or close its route through Process flow before removal; removal cannot complete production or QA.')
                else:
                    blockers.append(f'{item_id} has an open process timer. Use Finish timer before removal; finishing a timer does not approve fabrication or QA.')
    else:
        if not state or not state.removed:
            return ['This record is not currently removed.']
        if (state.root_kind, state.root_id) != (kind, record_id):
            return [f'This record was removed with {_identity(s, state.root_kind, state.root_id)["title"]}. Restore that entry from Removed records.']
        for item_kind, item_id in scope:
            if item_kind == 'order':
                continue
            project_id = _record(s, item_kind, item_id).project_id if item_kind == 'gpn' else _project_id(s, item_id)
            if project_id and ('order', project_id) not in scope_set and project_is_removed(s, project_id):
                blockers.append('Restore the parent P.O. before restoring this removal group.')
            if item_kind == 'item':
                for parent in _parents(s, item_id):
                    if ('item', parent) not in scope_set and item_is_removed(s, parent):
                        blockers.append(f'Restore parent item {parent} before restoring {item_id}.')
                mapping = s.get(OrderAssembly, item_id)
                if mapping and ('gpn', mapping.gpn_id) not in scope_set and gpn_is_removed(s, mapping.gpn_id):
                    blockers.append('Restore the parent GPN / Assembly before restoring this item.')
        # Removing an actual assembly frees active capacity for a replacement.
        # Restoring the original identity must obey the same explicit quantity
        # cap, including every item restored together in this removal batch.
        from order_setup import OrderAssemblyRequirement, OrderSpoolRequirement
        from orders import _key
        restored_ids = {record_id for record_kind, record_id in scope if record_kind == 'item'}
        restored_mappings = s.scalars(select(OrderAssembly).where(
            OrderAssembly.item_id.in_(restored_ids))).all() if restored_ids else []
        for gpn_id in sorted({mapping.gpn_id for mapping in restored_mappings}):
            required = s.get(OrderAssemblyRequirement, gpn_id)
            if required is None:
                continue
            mappings = set(s.scalars(select(OrderAssembly.item_id).where(OrderAssembly.gpn_id == gpn_id)))
            active = set(s.scalars(select(Item.id).where(Item.id.in_(mappings), item_not_removed(Item.id))))
            if len(active | (restored_ids & mappings)) > required.assembly_quantity:
                group = s.get(OrderGpn, gpn_id)
                blockers.append(f'Restoring these records would exceed the {required.assembly_quantity} planned assembly quantity for {group.gpn}. Remove the replacement assembly before restoring its original identity.')
        # Count the registered/planned union once, including retained legacy
        # children. A restored spool must fit both its parent's total and the
        # declared quantity of that spool number.
        parent_ids = {parent for item_id in restored_ids for parent in _parents(s, item_id)}
        for parent_id in sorted(parent_ids):
            mapping = s.get(OrderAssembly, parent_id)
            if mapping is None:
                continue
            children = [(item, plan) for item, plan in effective_children(s, parent_id)
                        if item.id in restored_ids or not item_is_removed(s, item.id)]
            if len(children) > mapping.required_spools:
                blockers.append(f'Restoring these records would exceed the {mapping.required_spools} required spools for assembly {parent_id}. Remove the replacement scope before restoring its original identities.')
            required = s.get(OrderAssemblyRequirement, mapping.gpn_id)
            if required is None:
                continue
            limits = {row.normalized_number: row for row in s.scalars(select(OrderSpoolRequirement)
                .where(OrderSpoolRequirement.gpn_id == mapping.gpn_id,
                       OrderSpoolRequirement.active.is_(True))).all()}
            counts = {}
            for child, _ in children:
                number = _key(child.google_part_number or '')
                counts[number] = counts.get(number, 0) + 1
            for number, count in counts.items():
                limit = limits.get(number)
                if limit is None or count > limit.quantity_per_assembly:
                    label = limit.spool_number if limit else number or '(missing spool number)'
                    blockers.append(f'Restoring these records would exceed or conflict with the saved quantity for spool {label} in assembly {parent_id}. Resolve the replacement scope before restoring its original identities.')
    return list(dict.fromkeys(blockers))


def _preview(s, kind, record_id, action):
    from parts import PartAllocation, PartLine, SpoolPartsPlan
    from production import SpoolProcessEvent
    from transfers import ItemTransferState
    from order_spools import OrderSpool
    identity = _identity(s, kind, record_id)
    state = _state(s, kind, record_id)
    full_scope = _scope(s, kind, record_id) if action == 'remove' else _restore_scope(s, state)
    scope = [key for key in full_scope if action == 'restore' or not (
        (current := _state(s, *key)) and current.removed)]
    blockers = _blockers(s, kind, record_id, action, state, scope)
    item_ids = [value for target_kind, value in full_scope if target_kind == 'item']
    project_ids = _project_ids(s, full_scope)
    basis = {'action': action, 'kind': kind, 'record_id': record_id,
             'state': _values(state), 'scope': [], 'projects': [], 'blockers': blockers}
    for target_kind, value in full_scope:
        detail = {'kind': target_kind, 'record': _values(_record(s, target_kind, value)),
                  'removal': _values(_state(s, target_kind, value))}
        if target_kind == 'item':
            detail.update(plan=_values(s.get(SpoolPlan, value)), flow=_values(s.get(FlowPlan, value)),
                parts=_values(s.get(SpoolPartsPlan, value)), transfer=_values(s.get(ItemTransferState, value)),
                mapping=_values(s.get(OrderAssembly, value)),
                spool_registration=_values(s.get(OrderSpool, value)), parents=sorted(_parents(s, value)))
        basis['scope'].append(detail)
    for value in sorted(project_ids):
        basis['projects'].append(_values(s.get(PurchaseOrder, value)))
    if item_ids:
        basis['audit'] = [(item_id, audit_id) for item_id, audit_id in s.execute(select(
            Audit.item_id, func.max(Audit.id)).where(Audit.item_id.in_(item_ids)).group_by(Audit.item_id).order_by(Audit.item_id)).all()]
        basis['process'] = [_values(row) for row in s.scalars(select(SpoolProcessEvent).where(
            SpoolProcessEvent.item_id.in_(item_ids)).order_by(SpoolProcessEvent.id)).all()]
        basis['allocations'] = [_values(row) for row in s.scalars(select(PartAllocation).where(
            PartAllocation.component_id.in_(item_ids)).order_by(PartAllocation.component_id)).all()]
        basis['lines'] = [_values(row) for row in s.scalars(select(PartLine).where(
            PartLine.spool_id.in_(item_ids)).order_by(PartLine.id)).all()]
    token = hashlib.sha256(json.dumps(basis, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    return {**identity, 'expected_version': state.version if state else 0,
            'preview_token': token, 'action': action, 'counts': _counts(scope),
            'affected': [{key: value for key, value in _identity(s, target_kind, record).items() if key != 'confirmation'}
                         for target_kind, record in scope],
            'blockers': blockers, 'can_proceed': not blockers and bool(scope),
            'removal': removal_summary(s, kind, record_id)}


@router.get('')
def list_removed(user: Employee = Depends(auth), s: Session = Depends(db)):
    permit(user, 'admin')
    rows = s.scalars(select(RecordRemoval).where(RecordRemoval.removed.is_(True),
        RecordRemoval.kind == RecordRemoval.root_kind, RecordRemoval.record_id == RecordRemoval.root_id)
        .order_by(RecordRemoval.changed_at.desc(), RecordRemoval.kind, RecordRemoval.record_id)).all()
    return {'records': [{**_identity(s, row.kind, row.record_id), **removal_summary(s, row.kind, row.record_id),
        'counts': _counts(_restore_scope(s, row))} for row in rows], 'permissions': {'can_remove': True}}


@router.get('/{kind}/{record_id}')
def preview(kind: Kind, record_id: str, action: Action = Query('remove'),
            user: Employee = Depends(auth), s: Session = Depends(db)):
    permit(user, 'admin')
    return _preview(s, kind, record_id, action)


def _change(s, user, kind, record_id, action, data):
    from administration import locked_admin
    from orders import _event
    actor = locked_admin(s, user)
    # Every operational writer takes the same topology lock. Lock current rows
    # in a stable order after it; never use the active-item guard here because
    # restoration deliberately works on removed rows.
    current = _preview(s, kind, record_id, action)
    if data.expected_version != current['expected_version'] or data.preview_token != current['preview_token']:
        raise HTTPException(409, 'These records or their linked work changed. Refresh the removal preview and confirm the current scope. No changes were saved.')
    if data.confirmation != current['confirmation']:
        raise HTTPException(422, 'The confirmation does not match the displayed record number. No changes were saved.')
    if not current['can_proceed']:
        raise HTTPException(409, {'message': 'This removal change is blocked. No changes were saved.', 'blockers': current['blockers']})
    keys = [(row['kind'], row['record_id']) for row in current['affected']]
    for target_kind, value in keys:
        model = {'order': PurchaseOrder, 'gpn': OrderGpn, 'item': Item}[target_kind]
        column = model.project_id if target_kind == 'order' else model.id
        s.scalar(select(model).where(column == value).with_for_update().execution_options(populate_existing=True))
    now = utcnow()
    root_state = _state(s, kind, record_id)
    batch = new_id('RMV') if action == 'remove' else root_state.batch_id
    for target_kind, value in keys:
        before = removal_summary(s, target_kind, value)
        row = _state(s, target_kind, value)
        if row is None:
            row = RecordRemoval(kind=target_kind, record_id=value, version=0)
            s.add(row)
        row.removed = action == 'remove'
        row.version += 1
        row.batch_id = batch
        row.root_kind, row.root_id = kind, record_id
        row.reason, row.changed_by, row.changed_at = data.reason, actor.badge, now
        audit(s, value if target_kind == 'item' else None, actor.badge,
            'RECORD_REMOVED' if action == 'remove' else 'RECORD_RESTORED',
            {'kind': target_kind, 'record_id': value, 'root_kind': kind, 'root_id': record_id,
             'batch_id': batch, 'version': row.version, 'reason': data.reason,
             'before': before, 'after': {'removed': row.removed, 'version': row.version},
             'project_id': value if target_kind == 'order' else _record(s, target_kind, value).project_id
                if target_kind == 'gpn' else _project_id(s, value)})
    for project_id in sorted(_project_ids(s, keys)):
        order = s.get(PurchaseOrder, project_id)
        if order:
            _event(s, order, actor, 'RECORDS_REMOVED' if action == 'remove' else 'RECORDS_RESTORED',
                before=None, after={'root_kind': kind, 'root_id': record_id, 'batch_id': batch,
                    'affected': current['affected'], 'counts': current['counts']}, reason=data.reason)
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, 'A conflicting removal change occurred. Refresh the preview and retry. No changes were saved.') from None
    return {'removed': action == 'remove', 'kind': kind, 'record_id': record_id,
            'affected_count': len(keys), 'removal': removal_summary(s, kind, record_id)}


@router.post('/{kind}/{record_id}/remove')
def remove(kind: Kind, record_id: str, data: ChangeIn,
           user: Employee = Depends(auth), s: Session = Depends(db)):
    return _change(s, user, kind, record_id, 'remove', data)


@router.post('/{kind}/{record_id}/restore')
def restore(kind: Kind, record_id: str, data: ChangeIn,
            user: Employee = Depends(auth), s: Session = Depends(db)):
    return _change(s, user, kind, record_id, 'restore', data)
