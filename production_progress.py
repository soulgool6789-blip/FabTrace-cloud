"""Read-only P.O. production trees over recorded fabrication and physical scope.

This projection never changes the historical progress/dossier basis. A physical
identity appears once in its P.O. tree, while each parent summarizes its unique
descendants. Recorded steps, physical finish, declared quantities and shipment
remain separate facts.
"""
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from main import Employee, Item, Rework, auth, db, utcnow
from tracking import SpoolPlan, TrackingHold
from flow import (FlowPlan, FlowEvent, FlowException, ROUTE_BY_ID, STEP_BY_NUMBER,
                  LEGACY_STEP_17, LEGACY_VERSION, VERSION, catalog_version, route_definition,
                  step_definition, ready_to_ship_step, shipment_step, flow_stage_for_item)
from orders import PurchaseOrder, OrderGpn, OrderAssembly, business_gpn, read_snapshot, gpn_record_rows
from progress import project_rows, _stamp
from removals import item_not_removed, project_not_removed, gpn_not_removed
from order_setup import requirements_by_gpn
from flow_stages import stages_for_versions
from flow_stations import station_positions
from flow_testing import FlowTestingState, project_step_states


router = APIRouter(prefix='/api/progress', tags=['P.O. production progress'])
DEFINITIONS = {
    'recorded_progress': 'Current recorded fabrication steps through final QA at step 22, weighted by each unique physical item. The current route’s shipment Floor return at 23, ready-to-ship at 24, shipment at 25 and delivery are separate. Historical 24-step travelers keep their saved shipping positions.',
    'expected_steps': 'Parts and spools each have eight applicable fabrication steps; assemblies have six through final inspection. Explicitly not-required testing steps are excluded. A route that has not started contributes no completed steps.',
    'finished': 'Current physical preparation or ordinary fabrication release from the existing quality projection. This is separate from the recorded-step percentage.',
    'scope': 'Declared spool/BOM shortfalls and unassigned or undeclared scope remain visible. A recorded 100% alone does not mean the P.O. is complete.',
    'baseline': 'Earlier steps adopted with a historical baseline remain not recorded. Rework and return events reset downstream recorded steps.',
    'holds': 'Hold indicators describe current item holds, tracking holds, open rework or process exceptions. Other readiness warnings are shown separately.',
    'routes': 'A part follows preparation, a spool follows fabrication, and an assembly follows final assembly/finish. Parent work is not credited to a child’s own route.',
    'flow_colors': 'Individual spool colors show the last recorded station transfer. New records stay in Inventory until movement is recorded. QA results, work steps and release blockers do not move a spool. Completed linked children follow a later recorded parent movement.',
    'testing': 'Step 17 records the required YES/NO decision. YES requires separate NDT and pressure-test attempts with QA/QC approval and floor handoffs; NO excludes only the testing review and testing Floor-return steps. Current routes distinguish NDT QA/QC-004, pressure QA/QC-005 and final QA/QC-006. Numeric step 18 counts once in overall progress; its two recorded review phases are shown separately by station. Required non-testing quality gates remain before coating.',
    'station_time': 'Elapsed calendar time from saved physical station transfers; same-station custody handoffs do not reset the clock. Separate visits retain returns and rework. Unknown historical entries remain unrecorded. Shared assembly visits are identified.',
}
COUNT_KEYS = ('items', 'parts', 'spools', 'assemblies', 'finished', 'wip', 'on_hold',
              'planning_needed', 'completed_steps', 'total_steps', 'not_recorded_steps', 'not_required_steps',
              'missing_assemblies', 'missing_spools', 'missing_parts', 'undeclared_scope', 'shipped', 'delivered')


def _group(rows, field):
    result = defaultdict(list)
    for row in rows:
        result[getattr(row, field)].append(row)
    return result


def _route(item, plan, flow):
    if flow and flow.route in ROUTE_BY_ID:
        return flow.route
    if item.kind == 'Assembly':
        return 'assembly'
    if item.kind == 'Spool' or plan:
        return 'spool'
    return 'component'


def _testing_review_stages(flow, events, testing, current_definition):
    """Project each recorded test review without duplicating numeric step 18.

    A numeric advance alone never proves both tests passed. Saved phase
    results distinguish NDT from pressure, including returns and new cycles.
    """
    keys = {'ndt': 'qa_test_results', 'pressure': 'qa_pressure_results'}
    pending = 'not_recorded' if flow and flow.baseline_step > 18 else 'pending'
    states = {key: pending for key in keys.values()}
    for event in events:
        data = event.data or {}
        action = data.get('testing_action')
        typed = data.get('testing_protocol') == 'CLM-TEST-v1'
        if typed and action in ('restart', 'decision'):
            status = 'not_required' if action == 'decision' and data.get('testing_decision') == 'NO' else 'pending'
            states = {key: status for key in keys.values()}
        elif typed and data.get('test_kind') in keys:
            key = keys[data['test_kind']]
            if action == 'review' and data.get('test_result') == 'PASS' and event.action == 'advance':
                states[key] = 'completed'
            elif action in ('start', 'complete', 'correct') or action == 'review' and (
                    data.get('test_result') == 'FAIL' or event.action == 'fail'):
                states[key] = 'pending'
        elif event.action in ('fail', 'reopen', 'admin_return_to_work'):
            target = data.get('return_step', event.step)
            if type(target) is int and target <= 18:
                states = {key: 'pending' for key in keys.values()}
    if testing and testing.decision == 'NO' and testing.phase == 'not_required':
        states = {key: 'not_required' for key in keys.values()}
    if flow and flow.status == 'active' and flow.current_step == 18:
        key = {'ndt_qa': 'qa_test_results', 'pressure_qa': 'qa_pressure_results'}.get(
            getattr(testing, 'phase', None))
        key = key or (current_definition or {}).get('flow_stage_key')
        if key in states:
            states[key] = 'current'
    return states


def _steps(route, flow, events, testing=None, current_definition=None):
    definition = route_definition(flow) if flow else ROUTE_BY_ID[route]
    version = catalog_version(flow) if flow else VERSION
    states = {n: 'not_recorded' if flow and n < flow.baseline_step else 'pending'
              for n in range(definition['first_step'], definition['last_step'] + 1)}
    definitions = {n: step_definition(flow, n) if flow else STEP_BY_NUMBER[n] for n in states}
    for event in events:
        if event.action in ('fail', 'reopen', 'admin_return_to_work'):
            target = (event.data or {}).get('return_step', event.step)
            if type(target) is int:
                for number in states:
                    if number >= target:
                        states[number] = 'pending'
        elif event.action == 'advance' and event.step in states and not (event.data or {}).get('phase_only'):
            states[event.step] = 'completed'
    states = project_step_states(states, testing)
    actual_current = flow.current_step if flow and flow.status == 'active' else None
    states = {number: 'pending' if state == 'current' and number != actual_current else state
              for number, state in states.items()}
    if flow and flow.status == 'active' and flow.current_step in states:
        states[flow.current_step] = 'current'
    if route == 'assembly' and flow and testing is None and definition['last_step'] == 24:
        definitions[17] = LEGACY_STEP_17
    # Actual saved definitions remain authoritative for completed history.
    # Current and unrecorded positions use the traveler's own frozen catalog.
    for event in events:
        saved = (event.data or {}).get('step_definition')
        if event.action == 'advance' and states.get(event.step) == 'completed' and isinstance(saved, dict):
            definitions[event.step] = {**definitions[event.step], **saved}
    if current_definition and flow and flow.current_step in states:
        definitions[flow.current_step] = current_definition
    review_stages = (_testing_review_stages(flow, events, testing, current_definition)
                     if route == 'assembly' and definition['last_step'] == 25 else None)
    return [{'number': n, 'title': definitions[n]['title'], 'state': state,
             'stage': definitions[n]['flow_stage_key'], 'qa': definitions[n]['qa'],
             'catalog_version': version, 'fabrication': n <= 22,
             **({'stage_states': review_stages} if n == 18 and review_stages is not None else {})}
            for n, state in states.items()]


def _finish_summary(value):
    result = dict(value)
    total = result['total_steps']
    result['recorded_percent'] = round(result['completed_steps'] / total * 100, 1) if total else 0
    result['percent'] = result['recorded_percent'] if result['items'] else None
    result['scope_complete'] = bool(result['items'] and not (
        result['missing_assemblies'] or result['missing_spools'] or result['missing_parts'] or result['undeclared_scope']))
    result['complete'] = bool(result['scope_complete'] and not result['wip']
                              and total and result['completed_steps'] == total)
    return result


def _summary(nodes, identifiers, extra_undeclared=0):
    result = {key: 0 for key in COUNT_KEYS}
    for identifier in set(identifiers):
        for key in COUNT_KEYS:
            result[key] += nodes[identifier]['_counts'][key]
    result['undeclared_scope'] += extra_undeclared
    return _finish_summary(result)


def _catalog_versions(nodes, identifiers):
    identifiers = set(identifiers)
    versions = {nodes[identifier].get('catalog_version') or next(
        (step['catalog_version'] for step in nodes[identifier]['steps'] if step.get('catalog_version')), VERSION)
        for identifier in identifiers}
    if any((nodes[identifier].get('flow_stage') or {}).get('key') == 'qa_004' for identifier in identifiers):
        versions.add(LEGACY_VERSION)
    if any((nodes[identifier].get('flow_stage') or {}).get('key') in ('qa_pressure_results', 'qa_final')
           for identifier in identifiers):
        versions.add(VERSION)
    return versions or {VERSION}


def _stages(nodes, identifiers, summary, last_applicable_step=None):
    identifiers = set(identifiers)
    catalog = stages_for_versions(_catalog_versions(nodes, identifiers))
    if last_applicable_step is None:
        last_applicable_step = max(number for stage in catalog for number in stage['steps'])
    steps = [{**step, 'stage': key, 'state': state}
             for identifier in identifiers for step in nodes[identifier]['steps']
             for key, state in (step.get('stage_states') or {step['stage']: step['state']}).items()]
    result = []
    for stage in catalog:
        all_selected = [step for step in steps if step['stage'] == stage['key']]
        selected = [step for step in all_selected if step['state'] != 'not_required']
        not_required = len(all_selected) - len(selected)
        total = len(selected)
        completed = sum(step['state'] == 'completed' for step in selected)
        current = sum(step['state'] == 'current' for step in selected)
        # Shared stations retain missing scope from every applicable route.
        missing = (summary['missing_parts'] if stage['key'] in ('inventory', 'qa_001') else
                   summary['missing_parts'] + summary['missing_spools'] if stage['key'] == 'preparation' else
                   summary['missing_parts'] + summary['missing_spools'] + summary['missing_assemblies'] if stage['key'] == 'floor' else
                   summary['missing_spools'] if stage['key'] in ('qa_002', 'welding', 'qa_003') else
                   summary['missing_assemblies'] if stage['key'] in (
                       'testing', 'qa_test_results', 'qa_pressure_results', 'paint', 'qa_004', 'qa_final') else 0)
        unrecorded = sum(step['state'] == 'not_recorded' for step in selected)
        unknown = bool((summary['undeclared_scope'] or summary['missing_spools'] or not summary['items'])
                       and stage['steps'][0] <= last_applicable_step)
        state = ('completed' if total and completed == total and not missing else
                 'current' if current else 'not_recorded' if total and unrecorded == total else
                 'pending' if total or missing else 'not_required' if not_required else
                 'scope_unknown' if unknown else 'not_applicable')
        result.append({'key': stage['key'], 'label': stage['label'], 'completed': completed,
            'color': stage['color'], 'color_label': stage['color_label'], 'qa': stage['qa'],
            'total': total, 'not_recorded': unrecorded, 'not_required': not_required, 'current': current,
            'state': state, 'percent': round(completed / total * 100, 1) if total else None,
            'missing_records': missing, 'separate': stage['separate']})
    return result


def _tree(s, selected_project_id=''):
    orders = s.scalars(select(PurchaseOrder).where(project_not_removed(PurchaseOrder.project_id))
        .order_by(PurchaseOrder.purchase_order, PurchaseOrder.project_id)).all()
    choices = [{'project_id': order.project_id, 'purchase_order': order.purchase_order,
                'customer': order.customer} for order in orders]
    if selected_project_id and selected_project_id not in {o.project_id for o in orders}:
        raise HTTPException(404, 'Active purchase order not found')
    if selected_project_id:
        orders = [order for order in orders if order.project_id == selected_project_id]
    project_ids = {order.project_id for order in orders}
    groups = s.scalars(select(OrderGpn).where(OrderGpn.project_id.in_(project_ids),
        gpn_not_removed(OrderGpn.id)).order_by(OrderGpn.gpn, OrderGpn.id)).all() if project_ids else []
    group_by_id = {group.id: group for group in groups}
    quantity_plans = requirements_by_gpn(s, group_by_id)
    mappings = s.scalars(select(OrderAssembly).where(OrderAssembly.gpn_id.in_(group_by_id),
        item_not_removed(OrderAssembly.item_id)).order_by(OrderAssembly.item_id)).all() if groups else []
    mapping_by_item = {mapping.item_id: mapping for mapping in mappings}
    # One existing physical/QA projection per request, never one per P.O., node,
    # dossier or material line. Its historical semantics remain unchanged.
    rows = project_rows(s, selected_project_id or None) if project_ids else []
    candidate_ids = [row['id'] for row in rows if row['project_id'] in project_ids]
    items = {item.id: item for item in s.scalars(select(Item).where(
        Item.id.in_(candidate_ids), item_not_removed(Item.id))).all()} if candidate_ids else {}
    rows = [row for row in rows if row['id'] in items and row['project_id'] in project_ids]
    ids = set(items)
    from order_spools import SpoolQrIdentity
    from spool_presentation import identity_fields
    identities = {row.item_id: row for row in s.scalars(select(SpoolQrIdentity).where(SpoolQrIdentity.item_id.in_(ids)))}
    plans = {row.item_id: row for row in s.scalars(select(SpoolPlan).where(SpoolPlan.item_id.in_(ids))).all()}
    flows = {row.item_id: row for row in s.scalars(select(FlowPlan).where(FlowPlan.item_id.in_(ids))).all()}
    testing_states = {row.item_id: row for row in s.scalars(select(FlowTestingState).where(FlowTestingState.item_id.in_(ids))).all()}
    stations, stage_cache = station_positions(s, items.values(), flows=flows, plans=plans), {}
    events = _group(s.scalars(select(FlowEvent).where(FlowEvent.item_id.in_(ids),
        FlowEvent.action.in_(('advance', 'fail', 'reopen', 'admin_return_to_work')))
        .order_by(FlowEvent.item_id, FlowEvent.sequence)).all(), 'item_id')
    holds = _group(s.scalars(select(TrackingHold).where(TrackingHold.item_id.in_(ids),
        TrackingHold.closed_at.is_(None))).all(), 'item_id')
    reworks = _group(s.scalars(select(Rework).where(Rework.item_id.in_(ids),
        Rework.closed_at.is_(None))).all(), 'item_id')
    exceptions = _group(s.scalars(select(FlowException).where(FlowException.item_id.in_(ids),
        FlowException.closed_at.is_(None))).all(), 'item_id')
    badges = {item.handler for item in items.values()}
    staff = {row.badge: row.name for row in s.scalars(select(Employee).where(Employee.badge.in_(badges))).all()}
    nodes = {}
    for row in rows:
        identifier = row['id']
        item, plan, flow = items[identifier], plans.get(identifier), flows.get(identifier)
        route = _route(item, plan, flow)
        from flow import current_step_definition
        current_definition = current_step_definition(s, flow) if flow and flow.current_step else None
        steps = _steps(route, flow, events[identifier], testing_states.get(identifier), current_definition)
        shipping_steps = (ready_to_ship_step(flow), shipment_step(flow))
        not_required = sum(step['fabrication'] and step['state'] == 'not_required' for step in steps)
        fabrication = [step for step in steps if step['fabrication'] and step['state'] != 'not_required']
        completed = sum(step['state'] == 'completed' for step in fabrication)
        unrecorded = sum(step['state'] == 'not_recorded' for step in fabrication)
        reasons = (['Item is on hold'] if item.on_hold else [])
        reasons += ['Open hold: ' + hold.reason for hold in holds[identifier]]
        reasons += ['Open rework: ' + rework.reason for rework in reworks[identifier]]
        reasons += [f'Open process exception at step {exception.step}: {exception.reason}'
                    for exception in exceptions[identifier]]
        reasons = list(dict.fromkeys(reasons))
        parts = row.get('parts')
        part_summary = ({'configured': True, 'reference': parts['reference'],
                         **parts['totals']} if parts else None)
        nodes[identifier] = {'id': identifier, 'item_kind': item.kind, 'route': route,
            'catalog_version': catalog_version(flow),
            **identity_fields(item, identities.get(identifier), is_spool=route == 'spool'),
            'part_number': item.google_part_number, 'project_id': row['project_id'],
            'parent_id': row['parent_id'], 'location': item.location, 'handler': item.handler,
            'handler_name': staff.get(item.handler, item.handler),
            'current_step': row['current_step'], 'current_title': current_definition['title'] if current_definition else row['current_title'],
            'flow_stage': {**stations[identifier], 'blocked': bool(reasons
                    or row['administrative_release'] or (row.get('receiving') or {}).get('required')
                    and not (row.get('receiving') or {}).get('can_proceed')
                    or (row['current_step'] in shipping_steps or stations[identifier]['key'] == 'ready_to_ship')
                    and not row['fabrication_finished'])},
            'status': row['status'], 'fabrication_finished': row['fabrication_finished'],
            'on_hold': bool(reasons), 'hold_reasons': reasons, 'blockers': row['blockers'],
            'receiving': row.get('receiving'),
            'administrative_release': row['administrative_release'],
            'route_started': flow is not None, 'flow_status': row['flow_status'],
            'step_entered_at': _stamp(flow.step_entered_at) if flow else None,
            'progress': {'completed': completed, 'total': len(fabrication),
                         'not_recorded': unrecorded, 'not_required': not_required,
                         'percent': round(completed / len(fabrication) * 100, 1) if fabrication else 0},
            'steps': steps, 'parts': part_summary, 'required_spools': None,
            'linked_spools': 0, 'missing_spools': 0, 'children': [], 'warnings': [],
            '_counts': {**{key: 0 for key in COUNT_KEYS}, 'items': 1,
                'parts': int(route == 'component'), 'spools': int(route == 'spool'),
                'assemblies': int(route == 'assembly'), 'finished': int(row['fabrication_finished']),
                'wip': int(not row['fabrication_finished']), 'on_hold': int(bool(reasons)),
                'planning_needed': int(not flow), 'completed_steps': completed,
                'total_steps': len(fabrication), 'not_recorded_steps': unrecorded, 'not_required_steps': not_required,
                'shipped': int(row['flow_status'] in ('shipped', 'delivered')),
                'delivered': int(row['flow_status'] == 'delivered')}}
        if route == 'assembly' and (stations[identifier]['key'] == 'ready_to_ship' or row['current_step'] in shipping_steps
                                    or row['flow_status'] in ('shipped', 'delivered')):
            # Check authoritative shipping readiness once per candidate assembly,
            # not once per descendant part. Optional project/packet gates and a
            # late child defect must give the same color in every workspace.
            nodes[identifier]['flow_stage'] = flow_stage_for_item(
                s, item, plan=flow, receiving=row.get('receiving'), stations=stations, stage_cache=stage_cache)

    # Keep every physical ID in exactly one tree. Contradictory/cyclic legacy
    # links are displayed as unassigned scope warnings rather than duplicated.
    parents = {}
    for identifier, node in nodes.items():
        parent_id = node['parent_id']
        if parent_id and (parent_id not in nodes or nodes[parent_id]['project_id'] != node['project_id']):
            node['warnings'].append('Parent item is missing, removed or outside this P.O.')
            node['_counts']['undeclared_scope'] += 1
        elif parent_id:
            parents[identifier] = parent_id
    cycles = set()
    for identifier in parents:
        chain, seen = [], set()
        current = identifier
        while current in parents and current not in seen:
            seen.add(current); chain.append(current); current = parents[current]
        if current in seen:
            cycles.update(chain[chain.index(current):])
    for identifier in cycles:
        parents.pop(identifier, None)
        nodes[identifier]['warnings'].append('Circular parent relationship requires correction')
        nodes[identifier]['_counts']['undeclared_scope'] += 1
    for identifier, parent_id in parents.items():
        nodes[parent_id]['children'].append(nodes[identifier])

    # Movement already resolved the station and its actual source. A later
    # quality restriction remains visible without relocating any child.
    resolved_stages = set()

    def resolve_stage(identifier):
        node = nodes[identifier]
        if identifier in resolved_stages:
            return node['flow_stage']
        resolved_stages.add(identifier)
        source_id = node['flow_stage']['source_item_id']
        if source_id != identifier and source_id in nodes:
            node['flow_stage']['blocked'] = bool(node['flow_stage']['blocked'] or resolve_stage(source_id)['blocked'])
        return node['flow_stage']

    for identifier in nodes:
        resolve_stage(identifier)
    for identifier, node in nodes.items():
        node['children'].sort(key=lambda child: (child['route'], child['id']))
        plan, flow = plans.get(identifier), flows.get(identifier)
        if node['route'] in ('spool', 'assembly') and not plan:
            node['warnings'].append('Actual weld plan and drawing scope have not been declared')
            node['_counts']['undeclared_scope'] += 1
        if node['route'] == 'assembly':
            mapping = mapping_by_item.get(identifier)
            required = mapping.required_spools if mapping else (
                flow.expected_children if flow and flow.route == 'assembly' else None)
            spools = [child for child in node['children'] if child['route'] == 'spool']
            node['required_spools'], node['linked_spools'] = required, len(spools)
            if required is None or required < 1:
                node['warnings'].append('Required spool count has not been declared')
                node['_counts']['undeclared_scope'] += 1
            else:
                node['missing_spools'] = max(0, required - len(spools))
                node['_counts']['missing_spools'] = node['missing_spools']
                if node['missing_spools']:
                    node['warnings'].append(f'{node["missing_spools"]} required spool(s) still to link')
                if len(spools) > required:
                    node['warnings'].append('Linked spools exceed the declared requirement')
                    node['_counts']['undeclared_scope'] += 1
            if len(spools) != len(node['children']):
                node['warnings'].append('Assembly contains an unexpected physical child type')
                node['_counts']['undeclared_scope'] += 1
        elif node['route'] == 'spool':
            children = [child for child in node['children'] if child['route'] == 'component']
            parts = node['parts']
            if not parts and flow and (flow.expected_children > 0 or flow.material_reference.strip()):
                parts = node['parts'] = {'configured': False, 'legacy_scope': True,
                    'reference': flow.material_reference, 'required_qty': flow.expected_children,
                    'assigned_qty': len(children),
                    'received_qty': sum(any(step['number'] == 1 and step['state'] == 'completed'
                                            for step in child['steps']) for child in children),
                    'prepared_qty': sum(child['fabrication_finished'] for child in children),
                    'short_qty': max(0, flow.expected_children - len(children))}
            if parts:
                missing = max(parts['short_qty'], max(0, parts['required_qty'] - len(children)))
                node['_counts']['missing_parts'] = missing
                if missing:
                    node['warnings'].append(f'{missing} required physical part(s) still to assign')
                if parts['configured'] and parts['required_qty'] < 1:
                    node['warnings'].append('The parts list has no active required lines')
                    node['_counts']['undeclared_scope'] += 1
                if len(children) > parts['required_qty']:
                    node['warnings'].append('Linked physical parts exceed the declared requirement')
                    node['_counts']['undeclared_scope'] += 1
            else:
                node['warnings'].append('Required material quantities have not been declared')
                node['_counts']['undeclared_scope'] += 1
            if len(children) != len(node['children']):
                node['warnings'].append('Spool contains an unexpected physical child type')
                node['_counts']['undeclared_scope'] += 1

    def complete_node(node):
        identifiers = {node['id']}
        for child in node['children']:
            identifiers.update(complete_node(child))
        node['_ids'] = identifiers
        node['summary'] = _summary(nodes, identifiers)
        node['stages'] = _stages(nodes, identifiers, node['summary'],
                               max(step['number'] for step in node['steps']))
        return identifiers

    roots = [node for identifier, node in nodes.items() if identifier not in parents]
    for node in roots:
        complete_node(node)
    roots_by_project = _group_dicts(roots, 'project_id')
    groups_by_project = _group(groups, 'project_id')
    mappings_by_group = _group(mappings, 'gpn_id')
    results = []
    for order in orders:
        project_roots = roots_by_project[order.project_id]
        root_by_id = {node['id']: node for node in project_roots}
        placed, gpns, extra_scope = set(), [], 0
        planned_gaps = {'missing_assemblies': 0, 'missing_spools': 0}
        warnings = []
        for group in groups_by_project[order.project_id]:
            assemblies, group_warnings = [], []
            for mapping in mappings_by_group[group.id]:
                if mapping.item_id not in root_by_id:
                    group_warnings.append(f'{mapping.item_id}: mapped assembly is outside the expected top-level P.O. scope')
                    continue
                assemblies.append(root_by_id[mapping.item_id])
                placed.add(mapping.item_id)
            identifiers = {value for node in assemblies for value in node['_ids']}
            quantity_plan = quantity_plans.get(group.id)
            setup_needed = not assemblies and not quantity_plan
            if setup_needed:
                group_warnings.append('Finish GPN / Assembly setup and declare its required spools')
            unknown = len(group_warnings)
            missing_assemblies = max(0, quantity_plan['assembly_quantity'] - len(assemblies)) if quantity_plan else 0
            unregistered_spools = missing_assemblies * quantity_plan['spools_per_assembly'] if quantity_plan else 0
            if quantity_plan:
                if missing_assemblies:
                    group_warnings.append(f'{missing_assemblies} of {quantity_plan["assembly_quantity"]} planned physical assemblies still to register')
                if len(assemblies) > quantity_plan['assembly_quantity']:
                    group_warnings.append('Registered physical assemblies exceed the saved P.O. quantity')
                    unknown += 1
                if not quantity_plan['spools']:
                    group_warnings.append('The saved assembly quantity has no active spool requirements')
                    unknown += 1
            extra_scope += unknown
            summary = _summary(nodes, identifiers, unknown)
            summary['missing_assemblies'] += missing_assemblies
            summary['missing_spools'] += unregistered_spools
            summary = _finish_summary(summary)
            planned_gaps['missing_assemblies'] += missing_assemblies
            planned_gaps['missing_spools'] += unregistered_spools
            gpns.append({'id': group.id, 'gpn': business_gpn(group), 'assembly_number': group.assembly_number,
                'setup_needed': setup_needed,
                'quantity_plan': quantity_plan, 'registered_assemblies': len(assemblies),
                'registration_needed': bool(missing_assemblies),
                'summary': summary, 'stages': _stages(nodes, identifiers, summary),
                'warnings': group_warnings, 'assemblies': assemblies})
        unassigned = [node for node in project_roots if node['id'] not in placed]
        if unassigned:
            warnings.append(f'{len(unassigned)} physical item branch(es) are not assigned to a GPN / Assembly')
            extra_scope += len(unassigned)
        if not gpns:
            warnings.append('No active GPN / Assembly scope has been declared')
            extra_scope += 1
        identifiers = {identifier for identifier, node in nodes.items() if node['project_id'] == order.project_id}
        summary = _summary(nodes, identifiers, extra_scope)
        for field, count in planned_gaps.items():
            summary[field] += count
        summary = _finish_summary(summary)
        canonical_gpns = gpn_record_rows(s, order.project_id, gpns)
        results.append({'project_id': order.project_id, 'purchase_order': order.purchase_order,
            'customer': order.customer, 'version': order.version, 'summary': summary,
            'stages': _stages(nodes, identifiers, summary), 'gpns': gpns, 'gpn_records': canonical_gpns,
            'unassigned': unassigned, 'warnings': warnings})
    overall = {key: sum(order['summary'][key] for order in results) for key in COUNT_KEYS}
    overall = _finish_summary(overall)
    overall['purchase_orders'] = len(results)
    overall['gpns'] = sum(len(order['gpns']) for order in results)
    stages = _stages(nodes, nodes, overall)
    for node in nodes.values():
        node.pop('_counts', None); node.pop('_ids', None)
    return {'as_of': _stamp(utcnow()), 'selected_project_id': selected_project_id,
            'choices': choices, 'definitions': DEFINITIONS,
            'stage_catalog': list(stages_for_versions(_catalog_versions(nodes, nodes))),
            'summary': overall, 'stages': stages, 'orders': results}


def _group_dicts(rows, field):
    result = defaultdict(list)
    for row in rows:
        result[row[field]].append(row)
    return result


@router.get('/orders')
def order_progress(project_id: str = Query('', max_length=80),
                   user: Employee = Depends(auth), s: Session = Depends(db)):
    # Authentication's connection is released before opening a separate,
    # consistent snapshot; GET cannot exhaust the pool by holding two leases.
    s.rollback()
    with read_snapshot(s) as snapshot:
        return _tree(snapshot, project_id)


