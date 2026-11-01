"""Live spool labels and colors for UI responses only.

These projections never form part of saved BOM, receiving, or dossier evidence.
Permanent aliases are read, never allocated, and copies retain their Item IDs.
"""
from collections import defaultdict

from sqlalchemy import func, select

_UNSET = object()


def identity_fields(item, identity=None, *, is_spool=True):
    alias = identity.display_code if identity else None
    return {'google_part_number': item.google_part_number,
            'spool_number': (identity.spool_number if identity else item.google_part_number) if is_spool else '',
            'qr_alias': alias, 'display_code': alias or item.id}


def item_presentation(s, item, *, plan=_UNSET, receiving=None, identity=_UNSET):
    from flow import FlowPlan, flow_stage_for_item
    from order_spools import spool_qr_identity
    from tracking import SpoolPlan
    identity = spool_qr_identity(s, item.id) if identity is _UNSET else identity
    plan = s.get(FlowPlan, item.id) if plan is _UNSET else plan
    is_spool = bool(identity or item.kind == 'Spool' or item.kind != 'Assembly'
                    and (plan and plan.route == 'spool' or s.get(SpoolPlan, item.id)))
    route = plan.route if plan else ('assembly' if item.kind == 'Assembly' else
                                    'spool' if is_spool else 'component')
    return {**identity_fields(item, identity, is_spool=is_spool),
            'item_kind': item.kind, 'route': route,
            'flow_stage': flow_stage_for_item(s, item, plan=plan, receiving=receiving)}


def item_presentations(s, items):
    """Batch identities/plans; compute each selected physical item's stage once."""
    from flow import FlowPlan
    from order_spools import SpoolQrIdentity
    items = list(items)
    ids = {item.id for item in items}
    if not ids:
        return {}
    identities = {row.item_id: row for row in s.scalars(select(SpoolQrIdentity).where(SpoolQrIdentity.item_id.in_(ids)))}
    plans = {row.item_id: row for row in s.scalars(select(FlowPlan).where(FlowPlan.item_id.in_(ids)))}
    return {item.id: item_presentation(s, item, plan=plans.get(item.id), identity=identities.get(item.id))
            for item in items}


def requirement_presentations(s, requirement_ids):
    """Describe actual copies; a mixed requirement never receives one color."""
    from main import Item
    from order_setup import OrderSpoolRequirement
    from order_spools import OrderSpool, SpoolQrIdentity
    from orders import OrderAssembly, OrderGpn, _key
    from removals import item_not_removed, gpn_not_removed
    from tracking import SpoolPlan

    ids = set(requirement_ids)
    if not ids:
        return {}
    requirements = list(s.scalars(select(OrderSpoolRequirement).where(
        OrderSpoolRequirement.id.in_(ids), OrderSpoolRequirement.active.is_(True))))
    by_number = {(row.gpn_id, row.normalized_number): row.id for row in requirements}
    group_ids = {row.gpn_id for row in requirements}
    query = (select(Item, OrderSpool, OrderGpn.id, SpoolQrIdentity)
        .outerjoin(OrderSpool, OrderSpool.item_id == Item.id)
        .outerjoin(SpoolPlan, SpoolPlan.item_id == Item.id)
        .join(OrderAssembly, OrderAssembly.item_id == func.coalesce(OrderSpool.assembly_id, SpoolPlan.assembly_id))
        .join(OrderGpn, OrderGpn.id == OrderAssembly.gpn_id)
        .outerjoin(SpoolQrIdentity, SpoolQrIdentity.item_id == Item.id)
        .where(Item.kind == 'Spool', OrderGpn.id.in_(group_ids),
               item_not_removed(Item.id), item_not_removed(OrderAssembly.item_id), gpn_not_removed(OrderGpn.id))
        .order_by(Item.google_part_number, SpoolQrIdentity.sequence, Item.id))
    physical = defaultdict(list)
    rows = list(s.execute(query)) if group_ids else []
    selected = []
    for item, registration, group_id, identity in rows:
        requirement_id = registration.requirement_id if registration else by_number.get((group_id, _key(item.google_part_number)))
        if requirement_id in ids and by_number.get((group_id, _key(item.google_part_number))) == requirement_id:
            selected.append((item, requirement_id, identity))
    displays = item_presentations(s, [row[0] for row in selected])
    for item, requirement_id, _ in selected:
        physical[requirement_id].append({'item_id': item.id, **displays[item.id]})
    result = {}
    for identifier in ids:
        copies = physical[identifier]
        states = {(row['flow_stage']['key'], row['flow_stage']['color'], row['flow_stage'].get('blocked', False))
                  for row in copies}
        common = {**copies[0]['flow_stage'], 'source_item_id': None, 'inherited': False} if len(states) == 1 else None
        result[identifier] = {'physical_spools': copies, 'physical_spools_total': len(copies),
            'flow_stage_state': 'not_registered' if not copies else 'common' if common else 'mixed',
            'flow_stage': common}
    return result
