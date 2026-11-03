"""Simple order quantities, before physical inventory or production is registered.

An assembly setup has independent Assembly Number and GPN fields. Its quantity describes the number to build;
spool requirements describe quantities per assembly. These additive planning
records never create physical IDs, custody, travelers, work or QA acceptance.
"""
from collections import defaultdict
from itertools import groupby

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator, model_validator
from sqlalchemy import (Boolean, CheckConstraint, Column, DateTime, ForeignKey,
                        Integer, String, UniqueConstraint, select)
from sqlalchemy.orm import Session

from main import Base, Employee, Item, auth, db, permit, utcnow
from tracking import Project, new_id
from flow import lock_topology
from orders import (Input, OrderAssembly, OrderGpn, PurchaseOrder, _commit, _event,
                    _flush, _gpn, _key, _locked, _guard_group_number,
                    _set_assembly_number, business_gpn, read_snapshot,
                    sync_gpn_record, gpn_record_rows, CreateGpnRecordIn,
                    EditGpnRecordIn, create_gpn_record_value, edit_gpn_record_value)
from permissions import has_capability
from removals import (gpn_not_removed, item_not_removed, project_is_removed,
                      project_not_removed)


router = APIRouter(prefix='/api/order-setup', tags=['simple purchase order setup'])


class OrderAssemblyRequirement(Base):
    __tablename__ = 'order_assembly_requirements'
    __table_args__ = (CheckConstraint('assembly_quantity >= 1 AND assembly_quantity <= 10000',
                                     name='ck_order_assembly_requirement_quantity'),)
    gpn_id = Column(String(60), ForeignKey('order_gpns.id'), primary_key=True)
    assembly_quantity = Column(Integer, nullable=False)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class OrderSpoolRequirement(Base):
    __tablename__ = 'order_spool_requirements'
    __table_args__ = (
        UniqueConstraint('gpn_id', 'normalized_number', name='uq_order_spool_requirement_number'),
        CheckConstraint('quantity_per_assembly >= 1 AND quantity_per_assembly <= 10000',
                        name='ck_order_spool_requirement_quantity'),
    )
    id = Column(String(60), primary_key=True)
    gpn_id = Column(String(60), ForeignKey('order_gpns.id'), nullable=False, index=True)
    spool_number = Column(String(160), nullable=False)
    normalized_number = Column(String(480), nullable=False)
    quantity_per_assembly = Column(Integer, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class OrderSpoolWeldRequirement(Base):
    """An explicit weld count; an absent row preserves undeclared legacy scope."""
    __tablename__ = 'order_spool_weld_requirements'
    __table_args__ = (CheckConstraint('welds_per_spool >= 0 AND welds_per_spool <= 500',
                                     name='ck_order_spool_weld_requirement_count'),)
    requirement_id = Column(String(60), ForeignKey('order_spool_requirements.id'), primary_key=True)
    welds_per_spool = Column(Integer, nullable=False)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class SpoolRequirementIn(Input):
    spool_number: str = Field(min_length=1, max_length=160)
    quantity_per_assembly: int = Field(ge=1, le=10000, strict=True)
    welds_per_spool: int | None = Field(default=None, ge=0, le=500, strict=True)


class AssemblyRequirementIn(Input):
    gpn: str = Field(min_length=1, max_length=160)
    assembly_number: str = Field(default='', max_length=160)
    assembly_quantity: int = Field(ge=1, le=10000, strict=True)
    spools: list[SpoolRequirementIn] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def unique_spool_scope(self):
        keys = [_key(row.spool_number) for row in self.spools]
        if len(keys) != len(set(keys)):
            raise ValueError('Enter each spool number once per assembly and use its quantity')
        if sum(row.quantity_per_assembly for row in self.spools) > 10000:
            raise ValueError('One assembly can require at most 10,000 total spools')
        return self


class CreateSetupIn(Input):
    expected_version: int = Field(default=0, ge=0, le=0, strict=True)
    purchase_order: str = Field(min_length=2, max_length=200)
    assemblies: list[AssemblyRequirementIn] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_assembly_numbers(self):
        keys = [('assembly', _key(row.assembly_number)) if row.assembly_number
                else ('gpn', _key(row.gpn)) for row in self.assemblies]
        if len(keys) != len(set(keys)):
            raise ValueError('Enter each Assembly Number once per P.O.; when it is unknown, enter each GPN once and use its quantity')
        return self


class AddAssemblyRequirementIn(AssemblyRequirementIn):
    expected_version: int = Field(ge=1, strict=True)


class EditAssemblyRequirementIn(AddAssemblyRequirementIn):
    assembly_number: str | None = Field(default=None, max_length=160)
    reason: str = Field(min_length=4, max_length=3000)


class EditAssemblyIdentityIn(Input):
    expected_version: int = Field(ge=1, strict=True)
    assembly_number: str = Field(max_length=160)
    gpn_label: str | None = Field(default=None, min_length=1, max_length=160)
    reason: str = Field(min_length=4, max_length=3000)

    @field_validator('gpn_label')
    @classmethod
    def provided_gpn_label_is_not_null(cls, value):
        if value is None:
            raise ValueError('Provide a nonblank current GPN label, or omit it to retain the existing value')
        return value


def _requirement_weld_progress(s, requirements, plans, weld_counts):
    """Current-cycle weld completion for exact registered physical copies.

    Required copies that have not been registered remain in the denominator.
    A physical identity, aggregate counter or old repair cycle cannot create
    completed individual welds. These are read-only counts, not QA acceptance.
    """
    from order_spools import OrderSpool
    from tracking import SpoolPlan, Weld, WeldWork

    by_id = {row.id: row for row in requirements}
    quantities = {row.gpn_id: row.assembly_quantity for row in plans}
    result = {}
    for requirement in requirements:
        count = weld_counts[requirement.id]
        required = requirement.quantity_per_assembly * quantities.get(requirement.gpn_id, 0)
        result[requirement.id] = {
            'defined': count is not None, 'percent': 0 if count else None,
            'completed': 0, 'total': count * required if count is not None else None,
            'registered_spools': 0, 'required_spools': required, 'scope_warning': '',
            'basis': 'Completed current-cycle individual welds across the required physical spools; arrival QA and final release are separate.'}
    if not by_id:
        return result

    registered, warnings = {}, defaultdict(set)
    records = s.execute(select(
        OrderSpool.item_id, OrderSpool.requirement_id, OrderSpool.assembly_id,
        Item.kind, Item.project, Item.google_part_number,
        OrderAssembly.gpn_id, OrderGpn.project_id,
        SpoolPlan.project_id.label('plan_project_id'),
        SpoolPlan.assembly_id.label('plan_assembly_id'), SpoolPlan.planned_welds)
        .join(Item, Item.id == OrderSpool.item_id)
        .join(OrderAssembly, OrderAssembly.item_id == OrderSpool.assembly_id)
        .join(OrderGpn, OrderGpn.id == OrderAssembly.gpn_id)
        .outerjoin(SpoolPlan, SpoolPlan.item_id == Item.id)
        .where(OrderSpool.requirement_id.in_(by_id), item_not_removed(Item.id),
               item_not_removed(OrderSpool.assembly_id)))
    for row in records:
        requirement = by_id[row.requirement_id]
        if (row.kind != 'Spool' or row.gpn_id != requirement.gpn_id
                or row.project != row.project_id
                or _key(row.google_part_number or '') != requirement.normalized_number):
            warnings[row.requirement_id].add('A registered spool has inconsistent order or spool identity.')
            continue
        result[row.requirement_id]['registered_spools'] += 1
        registered[row.item_id] = row
        declared = weld_counts[row.requirement_id]
        if declared is not None and (row.planned_welds != declared
                or row.plan_project_id != row.project_id
                or row.plan_assembly_id != row.assembly_id):
            warnings[row.requirement_id].add('A physical spool needs its declared weld plan checked.')

    defined = defaultdict(int)
    if registered:
        # Stream work grouped by weld. This avoids one query per weld and does
        # not load full work history, material details or document bytes.
        query = (select(Weld.id, Weld.item_id, Weld.completed_at,
                        Weld.required_operations, WeldWork.operation)
            .join(OrderSpool, OrderSpool.item_id == Weld.item_id)
            .outerjoin(WeldWork, (WeldWork.weld_id == Weld.id) & (WeldWork.cycle == Weld.cycle))
            .where(OrderSpool.requirement_id.in_(by_id),
                   item_not_removed(Weld.item_id), item_not_removed(OrderSpool.assembly_id))
            .order_by(Weld.item_id, Weld.id))
        for _, group in groupby(s.execute(query).yield_per(1000), key=lambda row: row.id):
            first = next(group)
            row = registered.get(first.item_id)
            if row is None:
                continue
            defined[first.item_id] += 1
            operations = {first.operation, *(work.operation for work in group)}
            required = set(first.required_operations or [])
            if first.completed_at is not None and required and 'complete' in operations and required <= operations:
                result[row.requirement_id]['completed'] += 1
        for item_id, row in registered.items():
            count = weld_counts[row.requirement_id]
            if count is not None and defined[item_id] != count:
                warnings[row.requirement_id].add('The individual weld records do not match the declared weld count.')

    for identity, progress in result.items():
        if progress['registered_spools'] > progress['required_spools']:
            warnings[identity].add('Registered physical spools exceed the required quantity.')
        progress['scope_warning'] = ' '.join(sorted(warnings[identity]))
        if progress['scope_warning'] or not progress['total']:
            progress['percent'] = None
        else:
            progress['percent'] = round(min(100, progress['completed'] / progress['total'] * 100), 1)
    return result


def requirements_by_gpn(s, gpn_ids):
    """Load declared requirements once; callers select active/historical groups."""
    from spool_boms import requirement_bom_summary
    from spool_documents import SpoolDocument, SpoolDocumentSet
    ids = set(gpn_ids)
    if not ids:
        return {}
    plans = s.scalars(select(OrderAssemblyRequirement)
                      .where(OrderAssemblyRequirement.gpn_id.in_(ids))).all()
    lines, weld_counts = defaultdict(list), {}
    for row, declared in s.execute(select(OrderSpoolRequirement, OrderSpoolWeldRequirement)
            .outerjoin(OrderSpoolWeldRequirement,
                       OrderSpoolWeldRequirement.requirement_id == OrderSpoolRequirement.id).where(
            OrderSpoolRequirement.gpn_id.in_(ids), OrderSpoolRequirement.active.is_(True))
            .order_by(OrderSpoolRequirement.spool_number, OrderSpoolRequirement.id)):
        lines[row.gpn_id].append(row)
        weld_counts[row.id] = declared.welds_per_spool if declared else None
    # A lightweight file-status projection keeps order setup useful after a
    # reload without loading PDF bytes or every retained material table.
    documents = defaultdict(set)
    requirement_ids = [line.id for group in lines.values() for line in group]
    weld_progress = _requirement_weld_progress(
        s, [line for group in lines.values() for line in group], plans, weld_counts)
    if requirement_ids:
        for requirement_id, kind in s.execute(select(
                SpoolDocumentSet.requirement_id, SpoolDocument.kind)
                .join(SpoolDocument, SpoolDocument.set_id == SpoolDocumentSet.id)
                .where(SpoolDocumentSet.requirement_id.in_(requirement_ids)).distinct()):
            documents[requirement_id].add(kind)
    result = {}
    for plan in plans:
        spools = [{'id': line.id, 'spool_number': line.spool_number,
                   'quantity_per_assembly': line.quantity_per_assembly,
                   'welds_per_spool': weld_counts[line.id],
                   'bom': requirement_bom_summary(line),
                   'weld_progress': weld_progress[line.id],
                   'documents': {kind: kind in documents[line.id] for kind in ('bom', 'isometric')},
                   'total_quantity': line.quantity_per_assembly * plan.assembly_quantity}
                  for line in lines[plan.gpn_id]]
        per_assembly = sum(line['quantity_per_assembly'] for line in spools)
        result[plan.gpn_id] = {'gpn_id': plan.gpn_id,
            'assembly_quantity': plan.assembly_quantity, 'spools_per_assembly': per_assembly,
            'total_spools': per_assembly * plan.assembly_quantity, 'spools': spools}
    return result


def _permissions(user):
    return {'can_manage': has_capability(user, 'manage_production'),
            'can_remove': getattr(user, 'role', user) == 'admin'}


def _totals(rows):
    unknown = sum(row['assembly_quantity'] is None for row in rows)
    assembly_quantity = sum(row['assembly_quantity'] or 0 for row in rows)
    total_spools = sum(row['total_spools'] or 0 for row in rows)
    return {'assembly_types': len(rows), 'undeclared_groups': unknown,
            'assembly_quantity': None if unknown or not rows else assembly_quantity,
            'total_spools': None if unknown or not rows else total_spools,
            'known_assembly_quantity': assembly_quantity, 'known_total_spools': total_spools}


def _groups(s, project_ids, *, include_status=False):
    groups = s.scalars(select(OrderGpn).where(OrderGpn.project_id.in_(project_ids),
        gpn_not_removed(OrderGpn.id)).order_by(OrderGpn.gpn, OrderGpn.id)).all()
    plans = requirements_by_gpn(s, [row.id for row in groups])
    from spool_presentation import requirement_presentations
    displays = requirement_presentations(s, [line['id'] for plan in plans.values()
        for line in plan['spools']]) if include_status else {}
    mappings = s.scalars(select(OrderAssembly)
        .where(OrderAssembly.gpn_id.in_([row.id for row in groups]))).all() if groups else []
    active_ids = set(s.scalars(select(Item.id).where(
        Item.id.in_([row.item_id for row in mappings]), item_not_removed(Item.id)))) if mappings else set()
    history, active = defaultdict(int), defaultdict(int)
    for mapping in mappings:
        history[mapping.gpn_id] += 1
        active[mapping.gpn_id] += int(mapping.item_id in active_ids)
    rows = defaultdict(list)
    for group in groups:
        plan = plans.get(group.id)
        rows[group.project_id].append({'gpn_id': group.id, 'gpn': group.gpn,
            'gpn_label': business_gpn(group),
            'assembly_number': group.assembly_number, 'assembly_number_editable': True,
            'planned': plan is not None, 'legacy_scope': plan is None,
            'assembly_quantity': plan['assembly_quantity'] if plan else None,
            'spools_per_assembly': plan['spools_per_assembly'] if plan else None,
            'total_spools': plan['total_spools'] if plan else None,
            'spools': [{**line, **displays.get(line['id'], {})} for line in plan['spools']] if plan else [],
            'registered_assemblies': active[group.id], 'editable': not history[group.id],
            'welds_editable': bool(plan and any(line['welds_per_spool'] is None for line in plan['spools'])),
            'locked_reason': ('Physical assembly records already exist. Their production scope is retained; '
                              'open Production records to review them.') if history[group.id] else ''})
    return rows


def setup_detail(s, project_id, user):
    order = s.scalar(select(PurchaseOrder).where(PurchaseOrder.project_id == project_id,
        project_not_removed(PurchaseOrder.project_id)))
    if order is None:
        raise HTTPException(404, 'Active purchase order not found')
    rows = _groups(s, {project_id}, include_status=True)[project_id]
    records = gpn_record_rows(s, project_id, rows)
    return {'order': {'project_id': order.project_id, 'purchase_order': order.purchase_order,
                     'customer': order.customer, 'version': order.version},
            'assemblies': rows, 'gpn_records': records,
            'totals': _totals(rows), 'permissions': _permissions(user)}


def _saved_detail(s, project_id, user, gpn_ids):
    return {**setup_detail(s, project_id, user), 'saved_gpn_ids': list(gpn_ids)}


def _list(s, user):
    orders = s.scalars(select(PurchaseOrder).where(project_not_removed(PurchaseOrder.project_id))
        .order_by(PurchaseOrder.purchase_order, PurchaseOrder.project_id)).all()
    rows = _groups(s, {order.project_id for order in orders}) if orders else {}
    return {'orders': [{'project_id': order.project_id, 'purchase_order': order.purchase_order,
                        'customer': order.customer, 'version': order.version,
                        **_totals(rows[order.project_id])} for order in orders],
            'permissions': _permissions(user)}


def _basis(s, group):
    plan = requirements_by_gpn(s, {group.id}).get(group.id)
    return {'gpn_id': group.id, 'gpn': group.gpn, 'gpn_label': group.gpn_label,
            'assembly_number': group.assembly_number, 'requirements': plan}


def _save_requirements(s, group, data, user):
    from spool_documents import guard_document_requirement_identity
    from removals import spool_line_is_removed
    existing = {line.normalized_number: line for line in s.scalars(
        select(OrderSpoolRequirement).where(OrderSpoolRequirement.gpn_id == group.id))}
    for values in data.spools:
        line = existing.get(_key(values.spool_number))
        if line is not None and spool_line_is_removed(s, line.id):
            raise HTTPException(409, f'Spool entry {line.spool_number} has been removed. '
                'Restore it from Removed records before adding it to this assembly again.')
    guard_document_requirement_identity(s, group,
        spool_numbers=[line.spool_number for line in data.spools])
    plan = s.get(OrderAssemblyRequirement, group.id)
    if plan is None:
        plan = OrderAssemblyRequirement(gpn_id=group.id,
            assembly_quantity=data.assembly_quantity, created_by=user.badge)
        s.add(plan)
    else:
        plan.assembly_quantity = data.assembly_quantity
        plan.updated_at = utcnow()
    active = set()
    for values in data.spools:
        normalized = _key(values.spool_number)
        active.add(normalized)
        line = existing.get(normalized)
        if line is None:
            line = OrderSpoolRequirement(id=new_id('OSPOOL'), gpn_id=group.id,
                spool_number=values.spool_number, normalized_number=normalized,
                quantity_per_assembly=values.quantity_per_assembly, active=True, created_by=user.badge)
            s.add(line)
        else:
            line.spool_number = values.spool_number
            line.quantity_per_assembly = values.quantity_per_assembly
            line.active = True
            line.updated_at = utcnow()
        # Flush the parent requirement first: this is an additive table, so a
        # deploy never rewrites an old requirement or invents a legacy count.
        if values.welds_per_spool is not None:
            _flush(s)
            declared = s.get(OrderSpoolWeldRequirement, line.id)
            if declared is None:
                s.add(OrderSpoolWeldRequirement(requirement_id=line.id,
                    welds_per_spool=values.welds_per_spool, created_by=user.badge))
            else:
                declared.welds_per_spool = values.welds_per_spool
                declared.updated_at = utcnow()
    for normalized, line in existing.items():
        if normalized not in active and line.active:
            line.active = False
            line.updated_at = utcnow()
    _flush(s)


def _add_group(s, order, data, user):
    _guard_group_number(s, order.project_id, data.gpn, data.assembly_number)
    group = OrderGpn(id=new_id('OGPN'), project_id=order.project_id, gpn=data.gpn,
                     normalized_gpn=_key(data.gpn), description='', created_by=user.badge)
    _set_assembly_number(group, data.assembly_number)
    s.add(group)
    _flush(s)
    sync_gpn_record(s, group)
    _save_requirements(s, group, data, user)
    return group


def guard_assembly_registration(s, group, required_spools, item_id=None):
    """Physical writers already hold the topology lock and active-scope guards."""
    plan = requirements_by_gpn(s, {group.id}).get(group.id)
    if plan is None:
        return
    item = s.get(Item, item_id) if item_id is not None else None
    if item is not None and _key(item.google_part_number or '') != group.normalized_gpn:
        raise HTTPException(409, 'The physical assembly part number must match its planned Google part number.')
    if not plan['spools_per_assembly'] or required_spools != plan['spools_per_assembly']:
        raise HTTPException(409, f'This assembly number requires {plan["spools_per_assembly"]} spools per assembly from its saved setup.')
    query = select(OrderAssembly.item_id).where(OrderAssembly.gpn_id == group.id,
                                                item_not_removed(OrderAssembly.item_id))
    if item_id is not None:
        query = query.where(OrderAssembly.item_id != item_id)
    count = len(s.scalars(query).all())
    if count >= plan['assembly_quantity']:
        raise HTTPException(409, 'The required number of physical assemblies is already registered for this assembly number.')
    if item_id is not None:
        from order_spools import effective_children
        limits = {_key(line['spool_number']): line['quantity_per_assembly'] for line in plan['spools']}
        assigned = defaultdict(int)
        for child, _ in effective_children(s, item_id, include_removed=False):
            key = _key(child.google_part_number or '')
            if key not in limits:
                raise HTTPException(409, f'Linked spool {child.id} does not match a required spool number in the saved assembly setup.')
            assigned[key] += 1
            if assigned[key] > limits[key]:
                raise HTTPException(409, 'The existing linked spool quantities exceed the saved per-assembly spool requirements.')


def guard_spool_requirement(s, item, assembly_id):
    """Apply declared spool-number quantities to one actual parent assembly."""
    from order_spools import effective_children, guard_registered_spool
    guard_registered_spool(s, item)
    mapping = s.get(OrderAssembly, assembly_id) if assembly_id else None
    if mapping is None or s.get(OrderAssemblyRequirement, mapping.gpn_id) is None:
        return
    key = _key(item.google_part_number or '')
    line = s.scalar(select(OrderSpoolRequirement).where(
        OrderSpoolRequirement.gpn_id == mapping.gpn_id,
        OrderSpoolRequirement.normalized_number == key,
        OrderSpoolRequirement.active.is_(True)))
    if line is None:
        raise HTTPException(409, 'This spool number is not listed in the assembly setup. The physical spool part number must match one of its required spool numbers.')
    peers = [peer for peer, _ in effective_children(s, assembly_id, include_removed=False)
             if peer.id != item.id]
    if sum(_key(peer.google_part_number or '') == key for peer in peers) >= line.quantity_per_assembly:
        raise HTTPException(409, f'This assembly already has the required {line.quantity_per_assembly} physical spool(s) for spool number {line.spool_number}.')


def guard_declared_weld_count(s, item, assembly_id, planned_welds):
    mapping = s.get(OrderAssembly, assembly_id) if assembly_id else None
    if mapping is None:
        return
    declared = s.scalar(select(OrderSpoolWeldRequirement)
        .join(OrderSpoolRequirement, OrderSpoolRequirement.id == OrderSpoolWeldRequirement.requirement_id)
        .where(OrderSpoolRequirement.gpn_id == mapping.gpn_id,
               OrderSpoolRequirement.normalized_number == _key(item.google_part_number or ''),
               OrderSpoolRequirement.active.is_(True)))
    if declared and planned_welds != declared.welds_per_spool:
        raise HTTPException(409, f'This spool requires {declared.welds_per_spool} welds from its purchase-order setup. '
            'Its individual weld plan must retain that declared count.')


def _declare_registered_weld_counts(s, order, group, data, user):
    """Permit only first declarations after physical quantity scope is locked."""
    from order_spools import initialize_declared_spools, pending_declared_spools
    saved = requirements_by_gpn(s, {group.id}).get(group.id)
    message = ('Physical assembly records already exist. Only previously undeclared weld counts can be set here; '
               'assembly numbers, quantities, spool numbers and declared weld counts are locked.')
    if (saved is None or data.gpn != group.gpn or data.assembly_quantity != saved['assembly_quantity']
            or (data.assembly_number is not None and data.assembly_number != group.assembly_number)):
        raise HTTPException(409, message)
    incoming = {_key(line.spool_number): line for line in data.spools}
    if set(incoming) != {_key(line['spool_number']) for line in saved['spools']}:
        raise HTTPException(409, message)
    additions = []
    for line in saved['spools']:
        values = incoming[_key(line['spool_number'])]
        if values.spool_number != line['spool_number'] or values.quantity_per_assembly != line['quantity_per_assembly']:
            raise HTTPException(409, message)
        count = values.welds_per_spool
        if line['welds_per_spool'] is not None:
            if count is not None and count != line['welds_per_spool']:
                raise HTTPException(409, message)
        elif count is not None:
            line['welds_per_spool'] = count
            additions.append((line['id'], count))
    if not additions:
        raise HTTPException(409, message)
    pending = pending_declared_spools(s, order.project_id, {group.id: saved})
    before = _basis(s, group)
    for requirement_id, count in additions:
        s.add(OrderSpoolWeldRequirement(requirement_id=requirement_id,
            welds_per_spool=count, created_by=user.badge))
    _flush(s)
    initialized, created_welds = initialize_declared_spools(s, order.project_id, pending, user.badge)
    _event(s, order, user, 'SETUP_WELD_COUNTS_DECLARED', before=before,
        after={**_basis(s, group), 'initialized_spool_ids': initialized,
               'created_weld_count': created_welds,
               'remaining_weld_spools': len(pending) - len(initialized)}, reason=data.reason)
    _commit(s)
    result = _saved_detail(s, order.project_id, user, [group.id])
    result.update(initialized_weld_spool_count=len(initialized), created_weld_count=created_welds,
                  remaining_weld_spools=len(pending) - len(initialized))
    return result


@router.get('')
def list_setup(user: Employee = Depends(auth), s: Session = Depends(db)):
    role = user.role
    s.rollback()
    with read_snapshot(s) as snapshot:
        return _list(snapshot, role)


@router.get('/{project_id}')
def get_setup(project_id: str, user: Employee = Depends(auth), s: Session = Depends(db)):
    role = user.role
    s.rollback()
    with read_snapshot(s) as snapshot:
        return setup_detail(snapshot, project_id, role)


@router.post('', status_code=201)
def create_setup(data: CreateSetupIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    lock_topology(s)
    permit(user, 'admin', 'supervisor')
    # This form deliberately asks for no customer. An existing same-number P.O.
    # must be opened explicitly rather than duplicated under a blank customer.
    duplicates = s.scalars(select(PurchaseOrder).where(
        PurchaseOrder.normalized_number == _key(data.purchase_order))).all()
    if duplicates:
        if all(project_is_removed(s, order.project_id) for order in duplicates):
            raise HTTPException(409, 'That P.O. is in Removed records. Restore it to use the same number and its retained history.')
        raise HTTPException(409, 'That P.O. number already exists. Open its existing setup.')
    project = Project(id=new_id('PO'), name=('PO ' + data.purchase_order)[:200],
        client='', description='', created_by=user.badge)
    s.add(project)
    _flush(s)
    order = PurchaseOrder(project_id=project.id, purchase_order=data.purchase_order,
        normalized_number=_key(data.purchase_order), customer='', normalized_customer='',
        notes='', version=1, created_by=user.badge)
    s.add(order)
    _flush(s)
    groups = [_add_group(s, order, values, user) for values in data.assemblies]
    _event(s, order, user, 'SETUP_CREATED', first=True, after={
        'purchase_order': order.purchase_order, 'assemblies': [_basis(s, group) for group in groups]})
    _commit(s)
    return _saved_detail(s, project.id, user, [group.id for group in groups])


@router.post('/{project_id}/assemblies', status_code=201)
def add_assembly_requirement(project_id: str, data: AddAssemblyRequirementIn,
                             user: Employee = Depends(auth), s: Session = Depends(db)):
    order = _locked(s, project_id, data.expected_version, user)
    group = _add_group(s, order, data, user)
    _event(s, order, user, 'SETUP_ASSEMBLY_ADDED', after=_basis(s, group))
    _commit(s)
    return _saved_detail(s, project_id, user, [group.id])


@router.patch('/{project_id}/assemblies/{gpn_id}')
def edit_assembly_requirement(project_id: str, gpn_id: str, data: EditAssemblyRequirementIn,
                              user: Employee = Depends(auth), s: Session = Depends(db)):
    order = _locked(s, project_id, data.expected_version, user)
    group = _gpn(s, project_id, gpn_id)
    from spool_documents import guard_document_requirement_identity
    guard_document_requirement_identity(s, group, gpn=data.gpn)
    if s.scalar(select(OrderAssembly.item_id).where(OrderAssembly.gpn_id == group.id).limit(1)):
        return _declare_registered_weld_counts(s, order, group, data, user)
    assembly_number = group.assembly_number if data.assembly_number is None else data.assembly_number
    _guard_group_number(s, project_id, data.gpn, assembly_number, excluding=group.id)
    before = _basis(s, group)
    group.gpn, group.normalized_gpn, group.updated_at = data.gpn, _key(data.gpn), utcnow()
    _set_assembly_number(group, assembly_number)
    sync_gpn_record(s, group)
    _save_requirements(s, group, data, user)
    _event(s, order, user, 'SETUP_ASSEMBLY_UPDATED', before=before,
           after=_basis(s, group), reason=data.reason)
    _commit(s)
    return _saved_detail(s, project_id, user, [group.id])


@router.patch('/{project_id}/assemblies/{gpn_id}/identity')
def edit_assembly_identity(project_id: str, gpn_id: str, data: EditAssemblyIdentityIn,
                           user: Employee = Depends(auth), s: Session = Depends(db)):
    """Correct current business labels without rewriting production identities."""
    order = _locked(s, project_id, data.expected_version, user)
    group = _gpn(s, project_id, gpn_id)
    _guard_group_number(s, project_id, group.gpn, data.assembly_number, excluding=group.id)
    before = {'gpn_id': group.id, 'gpn': group.gpn, 'gpn_label': group.gpn_label,
              'business_gpn': business_gpn(group), 'assembly_number': group.assembly_number}
    _set_assembly_number(group, data.assembly_number)
    if data.gpn_label is not None:
        group.gpn_label = data.gpn_label
    group.updated_at = utcnow()
    sync_gpn_record(s, group)
    _event(s, order, user, 'SETUP_ASSEMBLY_IDENTITY_UPDATED', before=before,
        after={'gpn_id': group.id, 'gpn': group.gpn, 'gpn_label': group.gpn_label,
               'business_gpn': business_gpn(group), 'assembly_number': group.assembly_number},
        reason=data.reason)
    _commit(s)
    return _saved_detail(s, project_id, user, [group.id])


@router.post('/{project_id}/gpn-records', status_code=201)
def create_setup_gpn_record(project_id: str, data: CreateGpnRecordIn,
                            user: Employee = Depends(auth), s: Session = Depends(db)):
    order = _locked(s, project_id, data.expected_version, user)
    record = create_gpn_record_value(s, order, data, user)
    _commit(s)
    return {**setup_detail(s, project_id, user), 'saved_gpn_record_id': record.id}


@router.patch('/{project_id}/gpn-records/{gpn_record_id}')
def edit_setup_gpn_record(project_id: str, gpn_record_id: str, data: EditGpnRecordIn,
                          user: Employee = Depends(auth), s: Session = Depends(db)):
    order = _locked(s, project_id, data.expected_version, user)
    record = edit_gpn_record_value(s, order, gpn_record_id, data, user)
    _commit(s)
    return {**setup_detail(s, project_id, user), 'saved_gpn_record_id': record.id}


