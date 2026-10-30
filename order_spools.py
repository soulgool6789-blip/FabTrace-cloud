"""Physical PO spool identities, before their real weld scope is declared.

Registration fixes the saved spool requirement and exact physical assembly. It
does not create a weld plan, production traveler, collection event or QA record.
Legacy planned children remain usable without changing their retained identity.
"""
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import Column, DateTime, ForeignKey, String, or_, select

from main import Base, Item, utcnow
from tracking import SpoolPlan


class OrderSpool(Base):
    __tablename__ = 'order_spools'
    item_id = Column(String(60), ForeignKey('items.id'), primary_key=True)
    assembly_id = Column(String(60), ForeignKey('order_assemblies.item_id'), nullable=False, index=True)
    requirement_id = Column(String(60), ForeignKey('order_spool_requirements.id'), nullable=False, index=True)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


def registered_spool(s, item_id):
    return s.get(OrderSpool, item_id)


def effective_parent_id(s, item_id):
    registration = registered_spool(s, item_id)
    if registration:
        return registration.assembly_id
    plan = s.get(SpoolPlan, item_id)
    return plan.assembly_id if plan else None


def effective_children_by_assembly(s, assembly_ids, *, include_removed=True):
    """Read the union once; a registered child with a plan appears only once.

    Kept removal history is included by default, matching the existing planning
    and removal relationship readers. Active label/count callers opt out.
    """
    ids = set(assembly_ids)
    children = defaultdict(dict)
    if not ids:
        return {}
    query = (select(Item, SpoolPlan, OrderSpool)
        .outerjoin(SpoolPlan, SpoolPlan.item_id == Item.id)
        .outerjoin(OrderSpool, OrderSpool.item_id == Item.id)
        .where(or_(SpoolPlan.assembly_id.in_(ids), OrderSpool.assembly_id.in_(ids)))
        .order_by(Item.id))
    if not include_removed:
        from removals import item_not_removed
        query = query.where(item_not_removed(Item.id))
    for item, plan, registration in s.execute(query):
        parents = {value for value in (
            plan.assembly_id if plan else None,
            registration.assembly_id if registration else None,
        ) if value in ids}
        for parent_id in parents:
            children[parent_id][item.id] = (item, plan)
    return {parent_id: list(rows.values()) for parent_id, rows in children.items()}


def effective_children(s, assembly_id, *, include_removed=True):
    return effective_children_by_assembly(s, [assembly_id],
        include_removed=include_removed).get(assembly_id, [])


def effective_child_ids(s, assembly_id, *, include_removed=True):
    return [item.id for item, _ in effective_children(s, assembly_id,
        include_removed=include_removed)]


def guard_registered_spool(s, item, values=None):
    """Keep generated identity, PO and intended parent fixed in every writer."""
    registration = registered_spool(s, item.id)
    if registration is None:
        return
    from orders import OrderAssembly, OrderGpn, _key
    from order_setup import OrderSpoolRequirement
    from removals import require_active_item, require_active_gpn
    mapping = s.get(OrderAssembly, registration.assembly_id)
    requirement = s.get(OrderSpoolRequirement, registration.requirement_id)
    if mapping is None or requirement is None or requirement.gpn_id != mapping.gpn_id or not requirement.active:
        raise HTTPException(409, 'This registered spool does not match an active requirement in its purchase-order assembly.')
    group = s.get(OrderGpn, mapping.gpn_id)
    require_active_gpn(s, mapping.gpn_id)
    require_active_item(s, mapping.item_id)
    if item.kind != 'Spool' or _key(item.google_part_number or '') != requirement.normalized_number:
        raise HTTPException(409, 'The registered physical spool part number must match its saved purchase-order spool requirement.')
    if item.project != group.project_id:
        raise HTTPException(409, 'This registered spool must remain in its purchase-order project.')
    plan = s.get(SpoolPlan, item.id)
    if plan and (plan.project_id != group.project_id or plan.assembly_id != registration.assembly_id):
        raise HTTPException(409, 'This registered spool has conflicting weld-plan scope. Correct the retained scope before changing its work.')
    if values is not None and (values.get('project_id') != group.project_id or
                               values.get('assembly_id') != registration.assembly_id):
        raise HTTPException(409, 'This registered spool must retain its exact purchase-order assembly and project when declaring its weld plan.')
