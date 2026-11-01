"""Live spool labels and colors for UI responses only.

These projections never form part of saved BOM, receiving, or dossier evidence.
Permanent aliases are read, never allocated, and copies retain their Item IDs.
"""
from collections import defaultdict
import re

from sqlalchemy import func, or_, select

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


def physical_spool_board(s, project_id='', subproject_id=''):
    """One live physical copy per current stage, including unstarted spools.

    The outer joins retain pre-traveler inventory and legacy tracked Parts.
    Context is loaded once; the existing resolver remains the source of stage
    and quality status. Reading this board never enrolls or moves a record.
    """
    from sqlalchemy.orm import aliased
    from main import Item
    from flow import FlowException, FlowPlan, STEP_BY_NUMBER, _step_errors
    from flow_stages import STAGES, STAGE_ORDER
    from order_spools import OrderSpool, SpoolQrIdentity
    from orders import OrderAssembly, OrderGpn, PurchaseOrder
    from removals import gpn_not_removed, item_not_removed, project_not_removed
    from spool_receiving import receiving_summary
    from tracking import Project, SpoolPlan

    parent = aliased(Item)
    parent_id = func.coalesce(OrderSpool.assembly_id, SpoolPlan.assembly_id)
    resolved_project = func.coalesce(SpoolPlan.project_id, OrderGpn.project_id, Item.project)
    query = (select(Item, FlowPlan, SpoolPlan, SpoolQrIdentity, OrderSpool,
                    OrderAssembly, OrderGpn, PurchaseOrder, Project.name, parent.google_part_number)
        .select_from(Item)
        .outerjoin(FlowPlan, FlowPlan.item_id == Item.id)
        .outerjoin(SpoolPlan, SpoolPlan.item_id == Item.id)
        .outerjoin(OrderSpool, OrderSpool.item_id == Item.id)
        .outerjoin(SpoolQrIdentity, SpoolQrIdentity.item_id == Item.id)
        .outerjoin(parent, parent.id == parent_id)
        .outerjoin(OrderAssembly, OrderAssembly.item_id == parent_id)
        .outerjoin(OrderGpn, OrderGpn.id == OrderAssembly.gpn_id)
        .outerjoin(PurchaseOrder, PurchaseOrder.project_id == resolved_project)
        .outerjoin(Project, Project.id == resolved_project)
        .where(Item.kind != 'Assembly',
               or_(Item.kind == 'Spool', SpoolPlan.item_id.is_not(None), OrderSpool.item_id.is_not(None)),
               item_not_removed(Item.id), item_not_removed(parent_id),
               project_not_removed(resolved_project), gpn_not_removed(OrderGpn.id)))
    if project_id:
        query = query.where(resolved_project == project_id)
    if subproject_id:
        query = query.where(SpoolPlan.subproject_id == subproject_id)
    rows = list(s.execute(query))
    identifiers = {row[0].id for row in rows}
    exceptions = dict(s.execute(select(FlowException.item_id, func.count(FlowException.id))
        .where(FlowException.item_id.in_(identifiers), FlowException.closed_at.is_(None))
        .group_by(FlowException.item_id)).all()) if identifiers else {}
    result, sequences = [], {}
    for item, flow, plan, identity, registration, mapping, group, order, project_name, parent_number in rows:
        arrival = receiving_summary(s, item)
        display = item_presentation(s, item, plan=flow, receiving=arrival, identity=identity)
        project = plan.project_id if plan else group.project_id if registration and group else item.project
        assembly_id = registration.assembly_id if registration else plan.assembly_id if plan else None
        sequences[item.id] = identity.sequence if identity else 0
        result.append({'item_id': item.id, 'description': item.description,
            **display, 'route': 'spool', 'project_id': project or '',
            'project_name': project_name or '', 'subproject_id': plan.subproject_id if plan else None,
            'purchase_order': order.purchase_order if order else None,
            'gpn_id': group.id if group else None, 'gpn': group.gpn if group else None,
            'assembly_id': assembly_id,
            'assembly_number': mapping.assembly_part_number if mapping else parent_number or None,
            'status': flow.status if flow else 'not_started',
            'current_step': flow.current_step if flow else None,
            'current_title': STEP_BY_NUMBER[flow.current_step]['title'] if flow and flow.current_step else '',
            'open_exceptions': exceptions.get(item.id, 0),
            'released': bool(item.released), 'blocked': display['flow_stage']['blocked'],
            'blockers': _step_errors(s, item, flow) if flow else arrival.get('blockers', [])})

    def number_key(value):
        return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                     for part in re.split(r'(\d+)', value or '') if part)

    result.sort(key=lambda row: (STAGE_ORDER[row['flow_stage']['key']],
        number_key(row['spool_number'] or row['item_id']), sequences[row['item_id']], row['item_id']))
    counts = {stage['key']: 0 for stage in STAGES}
    for row in result:
        counts[row['flow_stage']['key']] += 1
    return {'items': result, 'stage_catalog': STAGES, 'stage_counts': counts, 'total': len(result)}


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
