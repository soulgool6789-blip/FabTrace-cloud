"""Open, signed inspection failures for actual physical spools.

This read model never enrolls travelers, changes routing, clears defects, or
creates acceptance. An assembly finding stays explicitly assembly-scoped when
shown against its affected spools. Missing evidence is not a failed inspection.
"""

from collections import defaultdict
from datetime import timezone
import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased, undefer


INSPECTION_NAMES = {
    '001': 'Material', '002': 'Isometric Dimensions Test',
    '003': 'Weld Inspection', '004': 'NDT Results',
    '005': 'Verify Pressure Testing', '006': 'Final Inspection',
}
QA_KEYS = {2: '001', 11: '002', 15: '003', 22: '006'}
RETURN_STATIONS = {
    1: {'id': 'inventory', 'label': 'Inventory / material receiving'},
    10: {'id': 'fit_up', 'label': 'Fit-up'},
    14: {'id': 'welding', 'label': 'Process Welder'},
    21: {'id': 'blast_paint', 'label': 'Paint'},
}
STATION_FIELDS = ('key', 'label', 'color', 'color_label', 'qa', 'source_item_id',
                  'inherited', 'position_source', 'position_recorded_at',
                  'position_event_id', 'recorded_location_id',
                  'recorded_location_label', 'needs_station_selection')


def _batches(values):
    values = sorted(set(values))
    for start in range(0, len(values), 400):
        yield values[start:start + 400]


def _stamp(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _heading(key):
    if key not in INSPECTION_NAMES:
        return {'inspection_key': 'legacy_testing', 'qa_code': None,
                'display_qa_code': None, 'title': 'Retained Test Results — test type not recorded'}
    return {'inspection_key': key, 'qa_code': 'QA-' + key,
            'display_qa_code': 'QA/QC-' + key,
            'title': 'QA/QC-' + key + ' - ' + INSPECTION_NAMES[key]}


def _role_names(roles):
    from permissions import ROLE_LABELS
    return [ROLE_LABELS.get(role, role) for role in roles if role != 'admin']


def _physical_spools(s, project_id):
    from main import Item
    from flow import FlowPlan
    from order_spools import OrderSpool, SpoolQrIdentity
    from orders import OrderAssembly, OrderGpn, PurchaseOrder
    from removals import gpn_not_removed, item_not_removed, project_not_removed
    from spool_presentation import identity_fields
    from tracking import SpoolPlan

    parent = aliased(Item)
    parent_id = func.coalesce(OrderSpool.assembly_id, SpoolPlan.assembly_id)
    project = func.coalesce(SpoolPlan.project_id, OrderGpn.project_id, Item.project)
    query = (select(Item, SpoolPlan, SpoolQrIdentity, OrderSpool, OrderAssembly,
                    OrderGpn, PurchaseOrder)
        .select_from(Item)
        .outerjoin(FlowPlan, FlowPlan.item_id == Item.id)
        .outerjoin(SpoolPlan, SpoolPlan.item_id == Item.id)
        .outerjoin(OrderSpool, OrderSpool.item_id == Item.id)
        .outerjoin(SpoolQrIdentity, SpoolQrIdentity.item_id == Item.id)
        .outerjoin(parent, parent.id == parent_id)
        .outerjoin(OrderAssembly, OrderAssembly.item_id == parent_id)
        .outerjoin(OrderGpn, OrderGpn.id == OrderAssembly.gpn_id)
        .outerjoin(PurchaseOrder, PurchaseOrder.project_id == project)
        .where(Item.kind != 'Assembly', or_(Item.kind == 'Spool',
               SpoolPlan.item_id.is_not(None), OrderSpool.item_id.is_not(None),
               SpoolQrIdentity.item_id.is_not(None), FlowPlan.route == 'spool'),
               item_not_removed(Item.id), item_not_removed(parent_id),
               project_not_removed(project), gpn_not_removed(OrderGpn.id)))
    if project_id:
        query = query.where(project == project_id)
    result = {}
    for item, plan, identity, registration, mapping, group, order in s.execute(query):
        assembly_id = registration.assembly_id if registration else plan.assembly_id if plan else None
        result[item.id] = {
            'item_id': item.id, 'description': item.description,
            'item_kind': item.kind,
            **identity_fields(item, identity),
            'project_id': (plan.project_id if plan else group.project_id if group else item.project) or '',
            'purchase_order': order.purchase_order if order else None,
            'assembly_id': assembly_id,
            'assembly_number': (mapping.assembly_part_number if mapping else
                                group.assembly_number if group else None),
            'released': bool(item.released), 'failures': [],
        }
    return result


def _source_records(s, spools):
    """Load actual source/parent relationships once per bounded set."""
    from flow import ComponentLink, FlowPlan
    from main import Item
    from order_spools import OrderSpool
    from removals import item_not_removed
    from tracking import SpoolPlan

    affected = defaultdict(set)
    for identifier, row in spools.items():
        affected[identifier].add(identifier)
        if row['assembly_id']:
            affected[row['assembly_id']].add(identifier)
    for batch in _batches(spools):
        for link in s.scalars(select(ComponentLink).where(ComponentLink.spool_id.in_(batch))):
            affected[link.component_id].add(link.spool_id)
    sources, parent_edges, pending = {}, {}, set(affected)
    while pending:
        loaded = []
        for batch in _batches(pending):
            loaded.extend(s.execute(select(Item, FlowPlan, SpoolPlan, OrderSpool)
                .outerjoin(FlowPlan, FlowPlan.item_id == Item.id)
                .outerjoin(SpoolPlan, SpoolPlan.item_id == Item.id)
                .outerjoin(OrderSpool, OrderSpool.item_id == Item.id)
                .where(Item.id.in_(batch), item_not_removed(Item.id))))
        next_ids = set()
        for item, flow, plan, registration in loaded:
            sources[item.id] = (item, flow)
            if item.kind != 'Assembly':
                continue
            parent_id = registration.assembly_id if registration else plan.assembly_id if plan else None
            if parent_id and parent_id != item.id:
                parent_edges[item.id] = parent_id
                if parent_id not in sources:
                    next_ids.add(parent_id)
        pending = next_ids - pending
    # A parent may be loaded before another child in the same batch. Compute
    # the closure after all edges are known so row order never drops children.
    for source_id, spool_ids in list(affected.items()):
        seen, parent_id = {source_id}, parent_edges.get(source_id)
        while parent_id in sources and parent_id not in seen:
            affected[parent_id].update(spool_ids)
            seen.add(parent_id)
            parent_id = parent_edges.get(parent_id)
    return sources, affected


def _testing_kind(exception, failed, state):
    if exception.step != 18:
        return None
    data = (failed.data or {}) if failed else {}
    definition = data.get('step_definition') or {}
    phase = data.get('testing_phase') or definition.get('testing_phase')
    if phase in ('ndt_qa', 'pressure_qa'):
        return 'ndt' if phase == 'ndt_qa' else 'pressure'
    if data.get('test_kind') in ('ndt', 'pressure'):
        return data['test_kind']
    # The per-exception association is evidence; the state's current test kind
    # alone may instead belong to a later attempt or another test.
    kind = (state.pending_exception_kinds or {}).get(str(exception.id)) if state else None
    return kind if kind in ('ndt', 'pressure') else None


def _flow_failure(item, plan, exception, defect, events, testing, employees):
    from flow import STEP_BY_NUMBER
    from flow_testing import TEST_ROLES

    failed = next((event for event in events if event.action == 'fail'
                   and (event.data or {}).get('exception_id') == exception.id), None)
    data = (failed.data or {}) if failed else {}
    definition = data.get('step_definition') or {}
    kind = _testing_kind(exception, failed, testing)
    key = ('004' if kind == 'ndt' else '005' if kind == 'pressure' else
           'legacy_testing') if exception.step == 18 else QA_KEYS[exception.step]
    heading = _heading(key)
    if key == 'legacy_testing' and definition.get('display_qa_code'):
        heading['display_qa_code'] = definition['display_qa_code']
        heading['title'] = definition['display_qa_code'] + ' - Retained Test Results — test type not recorded'
    target = defect['return_step']
    correction = defect['completion']
    roles = list(defect['responsible_roles'])
    station = RETURN_STATIONS.get(target)
    title = STEP_BY_NUMBER[target]['title'] if target in STEP_BY_NUMBER else 'Review the recorded return destination'
    employee, routing_note = None, ''
    routing_known = station is not None
    if exception.step == 18:
        roles = ['admin', TEST_ROLES[kind]] if kind else []
        title = ('NDT correction' if kind == 'ndt' else 'Pressure testing correction'
                 if kind == 'pressure' else 'Testing — confirm the recorded test and return destination')
        origin = data.get('return_to') or {}
        if not origin and failed:
            report_id = (data.get('report') or {}).get('event_id')
            report = next((event for event in events if event.id == report_id
                           and event.sequence < failed.sequence), None)
            origin = ((report.data or {}).get('return_to') or {}) if report else {}
        if origin.get('location_id') and origin.get('location_label'):
            station = {'id': origin['location_id'], 'label': origin['location_label']}
        else:
            station = None
        badge = origin.get('sender_badge')
        if badge:
            saved = employees.get(badge, {})
            employee = {'badge': badge, 'name': origin.get('sender_name') or saved.get('name') or badge,
                        'role': TEST_ROLES.get(kind)}
        routing_known = bool(kind and station and employee)
        if not routing_known:
            routing_note = 'The original test type, return station or testing custodian is not fully recorded. Review the source inspection before resending.'
    if item.released or plan is None or plan.status != 'active':
        status = 'return_required'
    elif correction:
        status = 'awaiting_reinspection'
    elif plan.current_step != target:
        status = 'return_required'
    else:
        status = 'needs_rework'
    return {
        'id': f'flow:{exception.id}', **heading,
        'reason': exception.reason, 'reference': exception.reference,
        'actor': exception.opened_by, 'at': _stamp(exception.opened_at),
        'source_item_id': item.id, 'source_kind': item.kind,
        'source_released': bool(item.released),
        'saved_qa_code': definition.get('qa_code') or definition.get('display_qa_code'),
        'saved_title': definition.get('title'),
        'testing_phase': data.get('testing_phase') or definition.get('testing_phase'),
        'status': status, 'return_step': target, 'return_title': title,
        'return_station': dict(station) if station else None,
        'return_roles': roles, 'return_positions': _role_names(roles),
        'return_employee': employee, 'routing_known': routing_known, 'routing_note': routing_note,
        'correction': correction, 'open_kind': 'flow', 'open_item_id': item.id,
    }


def _receiving_failure(decision, kind, row, audits, current_materials):
    completed = None
    for audit in audits:
        data = audit.details or {}
        if (data.get('inspection_kind') != kind or data.get('failure_id') != decision.id
                or _stamp(audit.at) < _stamp(decision.at)
                or data.get('failure_version', decision.version) != decision.version):
            continue
        description = data.get('description', '')
        if isinstance(description, str) and len(description.strip()) >= 4:
            completed = {'event_id': audit.id, 'description': description,
                         'actor': audit.actor, 'at': _stamp(audit.at),
                         'reference': data.get('reference', '')}
    piece_key = decision.piece_key if kind == 'material' else None
    material_current = piece_key is None or piece_key in current_materials
    material = ((decision.basis or {}).get('material') or {}) if kind == 'material' else {}
    roles = ['admin', 'supervisor', 'handler']
    return {
        'id': f'{kind}:{decision.id}', **_heading('001'),
        'reason': decision.notes, 'reference': decision.reference,
        'actor': decision.actor, 'at': _stamp(decision.at),
        'source_item_id': row['item_id'], 'source_kind': row['item_kind'], 'scope': 'spool',
        'source_released': row['released'], 'saved_qa_code': 'QA-001',
        'saved_title': None, 'testing_phase': None,
        'piece_key': piece_key, 'piece_identifier': material.get('piece_identifier'),
        'material_current': material_current,
        'status': ('return_required' if row['released'] else
                   'awaiting_reinspection' if completed else 'needs_rework'),
        'return_step': 1, 'return_title': 'Inventory / material receiving',
        'return_station': dict(RETURN_STATIONS[1]), 'return_roles': roles,
        'return_positions': _role_names(roles), 'return_employee': None,
        'routing_known': material_current,
        'routing_note': '' if material_current else
            'This failed piece is retained from an earlier BOM revision. QA/QC must review its disposition against the current material record; a BOM revision does not record a Pass.',
        'correction': completed, 'open_kind': 'material', 'open_item_id': row['item_id'],
    }


def inspection_failure_board(s, project_id=''):
    """Use one snapshot and bounded queries, without a per-spool detail loop."""
    with s.no_autoflush:
        return _inspection_failure_board(s, project_id)


def _inspection_failure_board(s, project_id):
    from flow import FlowEvent, FlowException, FlowTestingState, rework_defects_from_records
    from main import Audit, Employee
    from spool_boms import SpoolBomMaterial
    from spool_receiving import SpoolArrivalInspection, SpoolMaterialInspection

    spools = _physical_spools(s, project_id)
    if not spools:
        return {'spools': [], 'totals': {key: 0 for key in
            ('spools', 'failures', 'needs_rework', 'awaiting_reinspection', 'return_required')}}
    sources, affected = _source_records(s, spools)
    exceptions = defaultdict(list)
    for batch in _batches(sources):
        for row in s.scalars(select(FlowException).where(FlowException.item_id.in_(batch),
                FlowException.step.in_((2, 11, 15, 18, 22)), FlowException.closed_at.is_(None))
                .order_by(FlowException.id)):
            exceptions[row.item_id].append(row)
    events, testing, employees = defaultdict(list), {}, {}
    for batch in _batches(exceptions):
        for row in s.scalars(select(FlowEvent).where(FlowEvent.item_id.in_(batch),
                FlowEvent.action.in_(('fail', 'advance'))).order_by(FlowEvent.item_id, FlowEvent.sequence)):
            events[row.item_id].append(row)
        testing.update({row.item_id: row for row in s.scalars(select(FlowTestingState)
            .where(FlowTestingState.item_id.in_(batch)))})
    badges = {origin.get('sender_badge') for rows in events.values() for event in rows
              for origin in ((event.data or {}).get('return_to') or {},) if origin.get('sender_badge')}
    for batch in _batches(badges):
        employees.update({badge: {'name': name} for badge, name in
            s.execute(select(Employee.badge, Employee.name).where(Employee.badge.in_(batch)))})
    for source_id, rows in exceptions.items():
        item, plan = sources[source_id]
        defects = {row['id']: row for row in rework_defects_from_records(plan, rows, events[source_id])}
        for exception in rows:
            failure = _flow_failure(item, plan, exception, defects[exception.id],
                                    events[source_id], testing.get(source_id), employees)
            for spool_id in affected[source_id]:
                scope = 'assembly' if item.kind == 'Assembly' else 'spool' if source_id == spool_id else 'component'
                spools[spool_id]['failures'].append({**failure, 'scope': scope})
    for batch in _batches(spools):
        latest_arrival = select(SpoolArrivalInspection.spool_id,
            func.max(SpoolArrivalInspection.version).label('version')).where(
            SpoolArrivalInspection.spool_id.in_(batch)).group_by(SpoolArrivalInspection.spool_id).subquery()
        arrivals = list(s.scalars(select(SpoolArrivalInspection).join(latest_arrival,
            (SpoolArrivalInspection.spool_id == latest_arrival.c.spool_id) &
            (SpoolArrivalInspection.version == latest_arrival.c.version))
            .where(SpoolArrivalInspection.result == 'Fail')))
        latest_piece = select(SpoolMaterialInspection.spool_id, SpoolMaterialInspection.piece_key,
            func.max(SpoolMaterialInspection.version).label('version')).where(
            SpoolMaterialInspection.spool_id.in_(batch)).group_by(
            SpoolMaterialInspection.spool_id, SpoolMaterialInspection.piece_key).subquery()
        materials = list(s.scalars(select(SpoolMaterialInspection).join(latest_piece,
            (SpoolMaterialInspection.spool_id == latest_piece.c.spool_id) &
            (SpoolMaterialInspection.piece_key == latest_piece.c.piece_key) &
            (SpoolMaterialInspection.version == latest_piece.c.version))
            .where(SpoolMaterialInspection.result == 'Fail').options(undefer(SpoolMaterialInspection.basis))))
        failed_ids = {row.spool_id for row in (*arrivals, *materials)}
        if not failed_ids:
            continue
        audits, current_materials = defaultdict(list), defaultdict(set)
        for row in s.scalars(select(Audit).where(Audit.item_id.in_(failed_ids),
                Audit.event == 'QA001_REWORK_RECORDED').order_by(Audit.id)):
            audits[row.item_id].append(row)
        for spool_id, piece_key in s.execute(select(SpoolBomMaterial.spool_id,
                SpoolBomMaterial.piece_key).where(SpoolBomMaterial.spool_id.in_(failed_ids))):
            current_materials[spool_id].add(piece_key)
        for kind, decisions in (('arrival', arrivals), ('material', materials)):
            for decision in decisions:
                row = spools[decision.spool_id]
                row['failures'].append(_receiving_failure(decision, kind, row,
                    audits[decision.spool_id], current_materials[decision.spool_id]))
    rows = [row for row in spools.values() if row['failures']]
    # Colors follow recorded physical custody, independently of the failed
    # checkpoint and required return destination. Only displayed spools incur
    # station-history reads, using the established batched movement resolver.
    from flow_stations import station_positions
    for batch in _batches(row['item_id'] for row in rows):
        positions = station_positions(s, [sources[identifier][0] for identifier in batch],
            flows={identifier: sources[identifier][1] for identifier in batch
                   if sources[identifier][1] is not None})
        for identifier in batch:
            stage = positions[identifier]
            spools[identifier]['flow_stage'] = {key: stage[key] for key in STATION_FIELDS if key in stage}
    def natural(value):
        return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                     for part in re.split(r'(\d+)', value or '') if part)
    rows.sort(key=lambda row: (natural(row['qr_alias'] or row['spool_number'] or row['item_id']), row['item_id']))
    for row in rows:
        row['failures'].sort(key=lambda failure: (failure['inspection_key'], failure['at'] or '', failure['id']))
    unique = {failure['id']: failure for row in rows for failure in row['failures']}
    return {'spools': rows, 'totals': {'spools': len(rows), 'failures': len(unique),
        **{status: sum(failure['status'] == status for failure in unique.values())
           for status in ('needs_rework', 'awaiting_reinspection', 'return_required')}}}
