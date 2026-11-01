"""PO quantities generate one durable QR identity per physical spool.

Reads never create inventory. Versioned generation registers only missing
physical identities using actual custody, without inventing production or QA.
"""
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from main import (Employee, Item, audit, auth, db, phone_link, phone_qr_ready,
                  require_phone_qr_ready)
from orders import (Input, OrderAssembly, OrderGpn, PurchaseOrder, _commit,
                    _event, _flush, _gpn, _key, _locked, _validate_assembly_scope,
                    read_snapshot)
from order_setup import guard_assembly_registration, requirements_by_gpn
from order_spools import (OrderSpool, SpoolQrIdentity, effective_children_by_assembly,
                          ensure_spool_qr_identity, guard_registered_spool, pending_declared_spools,
                          WELD_GENERATION_LIMIT, SPOOL_INITIALIZATION_LIMIT)
from permissions import has_capability
from removals import gpn_not_removed, item_not_removed, project_not_removed
from tracking import SpoolPlan, initialize_order_weld_scope, new_id
from spool_boms import ensure_material_piece_records, item_bom_summary


router = APIRouter(prefix='/api/order-labels', tags=['purchase order QR labels'])
GENERATION_LIMIT = 500
PAGE_LIMIT = 100
LabelKind = Literal['Spool']


class GenerateLabelsIn(Input):
    expected_version: int = Field(ge=1, strict=True)
    gpn_id: str | None = Field(default=None, min_length=1, max_length=60)
    kind: LabelKind = 'Spool'
    location: str = Field(min_length=1, max_length=160)
    handler: str = Field(min_length=2, max_length=80)


def _scope(s, project_id, gpn_id=None):
    order = s.scalar(select(PurchaseOrder).where(
        PurchaseOrder.project_id == project_id,
        project_not_removed(PurchaseOrder.project_id)))
    if order is None:
        raise HTTPException(404, 'Active purchase order not found')
    if gpn_id is not None:
        groups = [_gpn(s, project_id, gpn_id)]
    else:
        groups = s.scalars(select(OrderGpn).where(
            OrderGpn.project_id == project_id, gpn_not_removed(OrderGpn.id))
            .order_by(OrderGpn.gpn, OrderGpn.id)).all()
    ids = [group.id for group in groups]
    plans = requirements_by_gpn(s, ids)
    counts = defaultdict(int)
    if ids:
        counts.update(s.execute(select(OrderAssembly.gpn_id, func.count(Item.id))
            .join(Item, Item.id == OrderAssembly.item_id)
            .where(OrderAssembly.gpn_id.in_(ids), item_not_removed(Item.id))
            .group_by(OrderAssembly.gpn_id)).all())
    return order, groups, plans, counts


def _order_dict(order):
    return {'project_id': order.project_id, 'purchase_order': order.purchase_order,
            'version': order.version}


def _spool_query(*columns):
    # Registered ownership is authoritative. Legacy planned children use their
    # existing parent; a registered child later planned is still one QR row.
    return (select(*columns).select_from(Item)
        .outerjoin(OrderSpool, OrderSpool.item_id == Item.id)
        .outerjoin(SpoolPlan, SpoolPlan.item_id == Item.id)
        .join(OrderAssembly, OrderAssembly.item_id ==
              func.coalesce(OrderSpool.assembly_id, SpoolPlan.assembly_id))
        .join(OrderGpn, OrderGpn.id == OrderAssembly.gpn_id)
        .where(Item.kind == 'Spool', item_not_removed(Item.id), item_not_removed(OrderAssembly.item_id)))


def _overview(s, scope, user, kind='Spool'):
    order, groups, plans, assembly_counts = scope
    counts, pending, undeclared = defaultdict(int), defaultdict(int), defaultdict(int)
    ids = [group.id for group in groups]
    requirements = {group_id: {_key(line['spool_number']): line for line in plan['spools']}
                    for group_id, plan in plans.items()}
    if ids:
        counts.update(s.execute(_spool_query(OrderGpn.id, func.count(Item.id))
            .where(OrderGpn.id.in_(ids)).group_by(OrderGpn.id)).all())
        for group_id, number in s.execute(_spool_query(OrderGpn.id, Item.google_part_number)
                .where(OrderGpn.id.in_(ids), SpoolPlan.item_id.is_(None))):
            line = requirements.get(group_id, {}).get(_key(number or ''))
            (pending if line and line['welds_per_spool'] is not None else undeclared)[group_id] += 1
    rows = []
    for group in groups:
        plan = plans.get(group.id)
        assembly_quantity = plan['assembly_quantity'] if plan is not None else None
        quantity = plan['total_spools'] if plan is not None else None
        rows.append({'gpn_id': group.id, 'gpn': group.gpn,
            'assembly_quantity': assembly_quantity, 'planned_quantity': quantity,
            'registered_assembly_quantity': assembly_counts[group.id],
            'remaining_assembly_quantity': max(0, assembly_quantity - assembly_counts[group.id]) if plan is not None else None,
            'registered_quantity': counts[group.id],
            'remaining_weld_spools': pending[group.id],
            'undeclared_weld_spools': undeclared[group.id],
            'remaining_quantity': max(0, quantity - counts[group.id]) if quantity is not None else None})
    unknown = sum(row['assembly_quantity'] is None for row in rows)
    return {'order': _order_dict(order), 'kind': kind, 'groups': rows,
            'totals': {'registered_quantity': sum(row['registered_quantity'] for row in rows),
                'remaining_quantity': None if unknown else sum(row['remaining_quantity'] for row in rows),
                'remaining_weld_spools': sum(pending.values()),
                'undeclared_weld_spools': sum(undeclared.values()),
                'undeclared_groups': unknown},
            'qr_ready': phone_qr_ready(),
            'permissions': {'can_manage': has_capability(user, 'manage_production')},
            'limit': GENERATION_LIMIT, 'weld_limit': WELD_GENERATION_LIMIT}


@router.get('/{project_id}')
def label_overview(project_id: str,
                   gpn_id: str | None = Query(default=None, min_length=1, max_length=60),
                   kind: LabelKind = Query(default='Spool'),
                   user: Employee = Depends(auth), s: Session = Depends(db)):
    role = user.role
    s.rollback()
    with read_snapshot(s) as snapshot:
        return _overview(snapshot, _scope(snapshot, project_id, gpn_id), role, kind)


@router.get('/{project_id}/labels')
def list_labels(project_id: str,
                gpn_id: str | None = Query(default=None, min_length=1, max_length=60),
                kind: LabelKind = Query(default='Spool'),
                offset: int = Query(default=0, ge=0),
                limit: int = Query(default=PAGE_LIMIT, ge=1, le=PAGE_LIMIT),
                user: Employee = Depends(auth), s: Session = Depends(db)):
    s.rollback()
    with read_snapshot(s) as snapshot:
        scope = _scope(snapshot, project_id, gpn_id)
        order, groups, plans, _ = scope
        ids = [group.id for group in groups]
        ready, items = phone_qr_ready(), []
        requirements = {group_id: {_key(line['spool_number']): line for line in plan['spools']}
                        for group_id, plan in plans.items()}
        query = _spool_query(Item, OrderGpn, OrderAssembly.item_id, SpoolPlan.item_id,
            SpoolPlan.planned_welds, SpoolQrIdentity).outerjoin(
                SpoolQrIdentity, SpoolQrIdentity.item_id == Item.id)
        rows = snapshot.execute(query.where(OrderGpn.id.in_(ids))
            .order_by(OrderGpn.gpn, Item.google_part_number, SpoolQrIdentity.sequence, Item.created_at, Item.id)
            .offset(offset).limit(limit)).all() if ids else []
        from spool_presentation import item_presentations
        displays = item_presentations(snapshot, [row[0] for row in rows])
        for item, group, parent_id, plan_id, planned_welds, identity in rows:
            requirement = requirements.get(group.id, {}).get(_key(item.google_part_number or ''))
            alias = identity.display_code if identity else None
            items.append({'id': item.id, 'kind': 'Spool',
                **displays[item.id],
                'assembly_id': parent_id, 'weld_plan_exists': plan_id is not None,
                'welds_per_spool': requirement['welds_per_spool'] if requirement else None,
                'planned_welds': planned_welds,
                'bom': item_bom_summary(item, snapshot),
                'purchase_order': order.purchase_order, 'gpn_id': group.id, 'gpn': group.gpn,
                'qr_url': phone_link('spool', alias) if ready and alias else
                          phone_link('item', item.id) if ready else None})
        total = snapshot.scalar(_spool_query(func.count(Item.id)).where(OrderGpn.id.in_(ids))) if ids else 0
        return {'order': _order_dict(order), 'kind': kind, 'items': items,
                'total': total, 'offset': offset, 'limit': limit, 'qr_ready': ready}


def _spool_deficits(s, order, groups, plans):
    """Validate every existing selected parent before reserving any new IDs."""
    from flow import FlowPlan
    group_by_id = {group.id: group for group in groups}
    parents = s.execute(select(OrderAssembly, Item)
        .join(Item, Item.id == OrderAssembly.item_id)
        .where(OrderAssembly.gpn_id.in_(group_by_id), item_not_removed(Item.id))
        .order_by(OrderAssembly.gpn_id, Item.created_at, Item.id)).all()
    children = effective_children_by_assembly(s, [mapping.item_id for mapping, _ in parents],
        include_removed=False)
    deficits = []
    for mapping, parent in parents:
        group, plan = group_by_id[mapping.gpn_id], plans[mapping.gpn_id]
        if (_key(parent.google_part_number or '') != group.normalized_gpn or
                mapping.required_spools != plan['spools_per_assembly']):
            raise HTTPException(409, 'An existing physical assembly does not match its saved GPN or spool quantity. Review its scope before generating labels.')
        _validate_assembly_scope(s, order, parent, mapping.required_spools)
        traveler = s.get(FlowPlan, parent.id)
        required = {_key(line['spool_number']): line for line in plan['spools']}
        assigned = defaultdict(int)
        for child, child_plan in children.get(parent.id, []):
            guard_registered_spool(s, child)
            key = _key(child.google_part_number or '')
            if child.kind != 'Spool' or (child_plan.project_id if child_plan else child.project) != order.project_id:
                raise HTTPException(409, 'An existing child is not a physical spool in this purchase-order project.')
            if key not in required:
                raise HTTPException(409, f'Existing spool {child.id} does not match a saved spool number for its physical assembly.')
            assigned[key] += 1
            if assigned[key] > required[key]['quantity_per_assembly']:
                raise HTTPException(409, 'Registered spools exceed a saved per-assembly spool quantity. Review the existing physical records before generating labels.')
        for key, line in required.items():
            missing = line['quantity_per_assembly'] - assigned[key]
            if missing:
                if parent.released:
                    raise HTTPException(409, 'Return the released purchase-order assembly to work before generating missing child spools.')
                if traveler and (traveler.status != 'active' or traveler.current_step not in (17, 18)):
                    raise HTTPException(409, 'Generate missing child spools while the assembly traveler is collecting or identifying its spool scope at step 17 or 18.')
                deficits.append((group, parent.id, line, missing))
    return deficits


def _item_values(item_id, kind, project_id, number, data, welds_required=0):
    return {'id': item_id, 'description': '', 'kind': kind, 'project': project_id,
            'google_part_number': number, 'drawing': '', 'location': data.location,
            'handler': data.handler, 'welds_required': welds_required}


@router.post('/{project_id}/generate')
def generate_labels(project_id: str, data: GenerateLabelsIn,
                    user: Employee = Depends(auth), s: Session = Depends(db)):
    from administration import employee_is_removed

    order = _locked(s, project_id, data.expected_version, user)
    require_phone_qr_ready()
    scope = _scope(s, project_id, data.gpn_id)
    _, groups, plans, counts = scope
    if not groups or any(group.id not in plans for group in groups):
        raise HTTPException(409, 'Enter the assembly and spool quantities for every selected Google part number before generating new labels. Existing labels can still be printed.')

    missing_parents = []
    for group in groups:
        plan = plans[group.id]
        missing = plan['assembly_quantity'] - counts[group.id]
        if missing < 0 or not plan['spools_per_assembly']:
            raise HTTPException(409, 'Registered assemblies or saved spool quantities are inconsistent. Review the existing scope before generating labels.')
        if missing:
            guard_assembly_registration(s, group, plan['spools_per_assembly'])
            missing_parents.append((group, plan, missing))
    # Validate all retained scope even when the first group fills this batch.
    deficits = _spool_deficits(s, order, groups, plans)
    pending = pending_declared_spools(s, project_id, plans)
    employee = s.scalar(select(Employee).where(Employee.badge == data.handler)
        .with_for_update().execution_options(populate_existing=True))
    if not employee or not employee.active or employee_is_removed(s, employee.badge):
        raise HTTPException(422, 'Choose an active employee handler badge')

    remaining_slots, remaining_welds = GENERATION_LIMIT, WELD_GENERATION_LIMIT
    initialized = []
    for entry in pending:
        count = entry[2]['welds_per_spool']
        if len(initialized) >= SPOOL_INITIALIZATION_LIMIT or count > remaining_welds:
            break
        initialized.append(entry)
        remaining_welds -= count

    assemblies, spools = [], []
    batches = defaultdict(int)

    def reserve_spools(group, parent_id, line, missing):
        nonlocal remaining_slots, remaining_welds
        count = line['welds_per_spool']
        quantity = min(missing, remaining_slots)
        if count:
            quantity = min(quantity, remaining_welds // count)
        for _ in range(quantity):
            values = _item_values(new_id('SPL'), 'Spool', project_id,
                                  line['spool_number'], data, count or 0)
            spools.append((group, parent_id, line, Item(**values), values))
        remaining_slots -= quantity
        remaining_welds -= quantity * (count or 0)
        return quantity

    # Finish already-registered parents before adding more. Every new parent
    # gets at least one spool in this batch; parent records never receive QRs.
    for group, parent_id, line, missing in deficits:
        reserve_spools(group, parent_id, line, missing)
        if not remaining_slots:
            break
    for group, plan, missing in missing_parents:
        for _ in range(min(missing, remaining_slots // 2)):
            if remaining_slots < 2 or not any(
                    (line['welds_per_spool'] or 0) <= remaining_welds for line in plan['spools']):
                break
            values = _item_values(new_id('ASM'), 'Assembly', project_id, group.gpn, data)
            item = Item(**values)
            assemblies.append((group, plan, item, values))
            batches[group.id] += 1
            remaining_slots -= 1
            for line in plan['spools']:
                reserve_spools(group, item.id, line, line['quantity_per_assembly'])
                if not remaining_slots:
                    break

    created_ids = [item.id for _, _, item, _ in assemblies] + [item.id for _, _, _, item, _ in spools]
    if not created_ids and not initialized:
        result = _overview(s, scope, user)
        return {**result, 'created_count': 0, 'created_assembly_count': 0,
                'created_spool_count': 0, 'created_ids': [],
                'initialized_weld_spool_count': 0, 'created_weld_count': 0,
                'remaining_weld_spools': result['totals']['remaining_weld_spools'],
                'remaining_quantity': result['totals']['remaining_quantity']}
    if created_ids and (len(set(created_ids)) != len(created_ids) or s.scalar(
            select(Item.id).where(Item.id.in_(created_ids)).limit(1))):
        raise HTTPException(409, 'A generated item ID already exists. No records were saved; refresh and retry.')

    s.add_all([item for _, _, item, _ in assemblies])
    _flush(s)
    for group, plan, item, values in assemblies:
        _validate_assembly_scope(s, order, item, plan['spools_per_assembly'])
        s.add(OrderAssembly(item_id=item.id, gpn_id=group.id,
            assembly_part_number=group.gpn, required_spools=plan['spools_per_assembly'],
            notes='', created_by=user.badge))
        audit(s, item.id, user.badge, 'ITEM_CREATED', {
            **values, 'source': 'purchase_order_labels', 'gpn_id': group.id,
            'purchase_order': order.purchase_order})
    _flush(s)
    s.add_all([item for _, _, _, item, _ in spools])
    _flush(s)
    for group, parent_id, line, item, values in spools:
        s.add(OrderSpool(item_id=item.id, assembly_id=parent_id,
            requirement_id=line['id'], created_by=user.badge))
        audit(s, item.id, user.badge, 'ITEM_CREATED', {
            **values, 'source': 'purchase_order_labels', 'gpn_id': group.id,
            'assembly_id': parent_id, 'requirement_id': line['id'],
            'purchase_order': order.purchase_order})
    _flush(s)
    for _, _, _, item, _ in spools:
        ensure_spool_qr_identity(s, item, user.badge, source='purchase_order_labels')
        ensure_material_piece_records(s, item, user.badge,
            'Initialize physical material pieces from the uploaded purchase-order spool BOM.')
    created_welds = 0
    for item, parent_id, line in initialized:
        ensure_spool_qr_identity(s, item, user.badge, source='purchase_order_weld_count')
        ensure_material_piece_records(s, item, user.badge,
            'Initialize physical material pieces while declaring the saved spool weld count.')
        created_welds += initialize_order_weld_scope(s, item, project_id, parent_id,
                                                   line['welds_per_spool'], user.badge)
    for _, parent_id, line, item, _ in spools:
        if line['welds_per_spool'] is not None:
            created_welds += initialize_order_weld_scope(s, item, project_id, parent_id,
                                                       line['welds_per_spool'], user.badge)
    _event(s, order, user, 'SPOOL_LABELS_GENERATED', after={
        'selected_gpn_id': data.gpn_id, 'kind': 'Spool',
        'created_count': len(created_ids), 'created_assembly_count': len(assemblies),
        'created_spool_count': len(spools), 'created_ids': created_ids,
        'initialized_weld_spool_count': len(initialized),
        'initialized_spool_ids': [item.id for item, _, _ in initialized],
        'created_weld_count': created_welds,
        'location': data.location, 'handler': data.handler,
        'groups': [{'gpn_id': group.id, 'gpn': group.gpn, 'created_quantity': batches[group.id]}
                   for group in groups if batches[group.id]]})
    _flush(s)
    result = _overview(s, _scope(s, project_id, data.gpn_id), user)
    result.update(created_count=len(created_ids), created_assembly_count=len(assemblies),
                  created_spool_count=len(spools), created_ids=created_ids,
                  initialized_weld_spool_count=len(initialized), created_weld_count=created_welds,
                  remaining_weld_spools=result['totals']['remaining_weld_spools'],
                  remaining_quantity=result['totals']['remaining_quantity'])
    _commit(s)
    return result
