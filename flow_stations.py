"""Current physical stations from recorded movement, never inferred QA/work.

The numbered traveler still owns production and release gates. This read model
only answers where an individual record was last moved. Unknown historical
destinations retain the last identified process and ask for an explicit station.
"""
from collections import defaultdict
import datetime as dt

from sqlalchemy import select

from flow_stages import stage_status
from station_timing import station_visit_history


LOCATION_STAGES = {
    'inventory': 'inventory', 'receiving': 'inventory', 'material_storage': 'inventory',
    'qa_001': 'qa_001', 'qa_002': 'qa_002', 'qa_003': 'qa_003', 'qa_004': 'qa_004',
    'qa_test_results': 'qa_test_results',
    'kitting': 'preparation', 'fabrication_prep': 'preparation', 'fit_up': 'preparation',
    'floor': 'floor', 'production_staging': 'floor', 'welding': 'welding',
    'testing': 'testing', 'assembly': 'testing', 'blast_paint': 'paint',
    'shipping': 'ready_to_ship', 'ready_to_ship': 'ready_to_ship',
}
QA_STEPS = {2: 'qa_001', 11: 'qa_002', 15: 'qa_003', 18: 'qa_test_results', 22: 'qa_004'}


def _time(value):
    if value is None:
        return None
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


def station_positions(s, items, *, flows=None, plans=None):
    """Batch movement and relationship facts for these items and their parents."""
    from flow import ComponentLink, FlowEvent, FlowPlan
    from main import Audit, Item
    from order_spools import OrderSpool
    from removals import item_not_removed
    from tracking import SpoolPlan
    from transfers import ItemTransferState, LOCATIONS

    items = {item.id: item for item in items}
    flows, plans = dict(flows or {}), dict(plans or {})
    links, registrations, parents = {}, {}, {}
    pending = set(items)
    while pending:
        flows.update({row.item_id: row for row in s.scalars(select(FlowPlan).where(FlowPlan.item_id.in_(pending)))})
        plans.update({row.item_id: row for row in s.scalars(select(SpoolPlan).where(SpoolPlan.item_id.in_(pending)))})
        links.update({row.component_id: row for row in s.scalars(select(ComponentLink).where(ComponentLink.component_id.in_(pending)))})
        registrations.update({row.item_id: row for row in s.scalars(select(OrderSpool).where(OrderSpool.item_id.in_(pending)))})
        for identifier in pending:
            link, registration, plan = links.get(identifier), registrations.get(identifier), plans.get(identifier)
            parents[identifier] = (link.spool_id if link else registration.assembly_id if registration else
                                   plan.assembly_id if plan else None)
        missing = {parents[identifier] for identifier in pending if parents[identifier] and parents[identifier] not in items}
        ancestors = list(s.scalars(select(Item).where(Item.id.in_(missing), item_not_removed(Item.id)))) if missing else []
        pending = {item.id for item in ancestors}
        items.update({item.id: item for item in ancestors})
    if not items:
        return {}
    ids = set(items)
    active = set(s.scalars(select(Item.id).where(Item.id.in_(ids), item_not_removed(Item.id))))
    states = {row.item_id: row for row in s.scalars(select(ItemTransferState).where(ItemTransferState.item_id.in_(ids)))}
    events = defaultdict(list)
    for row in s.scalars(select(FlowEvent).where(FlowEvent.item_id.in_(ids),
            FlowEvent.action.in_(('advance', 'assembly_link', 'custody_transfer',
                                 'fail', 'reopen', 'admin_return_to_work')))
            .order_by(FlowEvent.item_id, FlowEvent.sequence)):
        events[row.item_id].append(row)
    audits = defaultdict(list)
    for row in s.scalars(select(Audit).where(Audit.item_id.in_(ids),
            Audit.event.in_(('TRANSFER', 'LOCATION_CAPTURED', 'TRACKING_PLAN_SAVED')))
            .order_by(Audit.item_id, Audit.at, Audit.id)):
        audits[row.item_id].append(row)
    labels = {' '.join(row['label'].casefold().split()): row['id'] for row in LOCATIONS}
    labels.update({'fabrication preparation': 'fabrication_prep', 'welding': 'welding',
                   'blast / paint': 'blast_paint'})
    # Label-only historical movements predate the new explicit test-review
    # station. Their old QA/QC-004 label identified final inspection.
    labels['qa/qc-004'] = 'qa_004'
    facts, completion_windows, linked_at = {}, {}, {}

    def completed_intervals(flow, rows):
        if not flow or flow.route not in ('component', 'spool'):
            return []
        last_step = 8 if flow.route == 'component' else 16
        intervals, opened, prepared = [], None, False
        for event in rows:
            at = _time(event.at)
            if event.action == 'advance':
                if event.step == 7:
                    prepared = True
                if event.step == last_step and (flow.route == 'spool' or prepared) and opened is None:
                    opened = [at, None]
                    intervals.append(opened)
            elif event.action in ('fail', 'reopen', 'admin_return_to_work'):
                target = (event.data or {}).get('return_step', event.step)
                if type(target) is int and target <= last_step:
                    if opened is not None:
                        opened[1], opened = at, None
                    if target <= 7:
                        prepared = False
        if not intervals and flow.route == 'spool' and flow.status == 'completed' and flow.completed_at:
            intervals.append([_time(flow.completed_at), None])
        return intervals

    def movement_position(identifier, movements):
        stage = {**stage_status('inventory', identifier), 'position_source': 'inventory_default',
            'position_recorded_at': None, 'position_event_id': None,
            'recorded_location_id': None, 'recorded_location_label': None,
            'needs_station_selection': False}
        at, latest_at = None, None
        for movement in movements:
            latest_at = movement['at']
            key = movement['stage_key']
            if key:
                stage = {**stage_status(key, movement['source_item_id'], inherited=movement['inherited']),
                    'position_source': movement['evidence_source'],
                    'position_recorded_at': latest_at.isoformat(), 'position_event_id': movement['event_id']}
                at = latest_at
            stage.update(recorded_location_id=movement['location_id'], recorded_location_label=movement['location_label'],
                         needs_station_selection=not bool(key))
        return {'stage': stage, 'at': at, 'latest_at': latest_at, 'movements': movements}

    def mapped(location_id, step, definition=None):
        if location_id != 'qa_qc':
            return LOCATION_STAGES.get(location_id)
        # Step 18 used to identify an assembly; it did not establish a QA
        # station. Only an actual movement recorded against the revised QA
        # definition disambiguates the retired generic QA/QC destination.
        if step == 18 and (definition or {}).get('display_qa_code') != 'QA/QC-004':
            return None
        return QA_STEPS.get(step)

    for identifier, item in items.items():
        stage = {**stage_status('inventory', identifier), 'position_source': 'inventory_default',
            'position_recorded_at': None, 'position_event_id': None,
            'recorded_location_id': None, 'recorded_location_label': None,
            'needs_station_selection': False}
        at, latest_at = None, None
        transfer_steps = {(row.data or {}).get('transfer_version'): row.step
                          for row in events[identifier] if row.action == 'custody_transfer'}
        transfer_definitions = {}
        for row in events[identifier]:
            data = row.data or {}
            transfer_version = data.get('transfer_version') or (data.get('handoff') or {}).get('transfer_version')
            if transfer_version is not None:
                transfer_definitions[transfer_version] = data.get('step_definition')
        moves = []
        for row in audits[identifier]:
            data = row.details or {}
            if row.event == 'TRACKING_PLAN_SAVED':
                before, after = data.get('before') or {}, data.get('after') or {}
                if after.get('assembly_id') == parents[identifier] and before.get('assembly_id') != parents[identifier]:
                    linked_at[identifier] = _time(row.at)
                continue
            before, after = data.get('from'), data.get('to')
            before = before if isinstance(before, dict) else {}
            after = after if isinstance(after, dict) else {}
            location_id = after.get('location_id')
            label = after.get('location') or data.get('location')
            if location_id is None and label:
                location_id = labels.get(' '.join(label.casefold().split()))
            changed = (data.get('location_changed') is True
                       or after.get('location_id') != before.get('location_id')
                       or bool(label and label != before.get('location')))
            if not changed or not (location_id or label):
                continue
            step = data.get('flow_step', transfer_steps.get(data.get('transfer_version')))
            moves.append((row.at, row.id, location_id, label,
                          'location_capture' if row.event == 'LOCATION_CAPTURED' else 'transfer',
                          mapped(location_id, step, transfer_definitions.get(data.get('transfer_version'))),
                          row.actor, after.get('handler') or data.get('handler'), data.get('notes', '')))
        # A retained current-state row is evidence when older movement audit
        # history is unavailable. Item.location alone never establishes a move.
        state = states.get(identifier)
        if not moves and state and state.location_id:
            moves.append((state.updated_at, None, state.location_id, item.location,
                          'recorded_state', mapped(state.location_id, None), None, item.handler, ''))
        movements = []
        for moved_at, event_id, location_id, label, source, key, actor, handler, notes in moves:
            latest_at = _time(moved_at)
            movements.append({'at': latest_at, 'event_id': event_id, 'stage_key': key,
                'source_item_id': identifier, 'inherited': False, 'evidence_source': source,
                'actor': actor, 'handler_badge': handler, 'notes': notes,
                'location_id': location_id, 'location_label': label})
            if key:
                stage = {**stage_status(key, identifier), 'position_source': source,
                    'position_recorded_at': latest_at.isoformat(), 'position_event_id': event_id}
                at = latest_at
            stage.update(recorded_location_id=location_id, recorded_location_label=label,
                         needs_station_selection=not bool(key))
        facts[identifier] = {'stage': stage, 'at': at, 'latest_at': latest_at, 'movements': movements}
        flow = flows.get(identifier)
        completion_windows[identifier] = completed_intervals(flow, events[identifier])
        if identifier in links:
            linked_at[identifier] = _time(links[identifier].assigned_at)
        elif identifier in registrations:
            linked_at[identifier] = _time(registrations[identifier].created_at)
        else:
            for row in events[identifier]:
                if row.action == 'assembly_link' and (row.data or {}).get('assembly_id') == parents[identifier]:
                    linked_at[identifier] = _time(row.at)
            if identifier not in linked_at and parents[identifier] and identifier in plans:
                linked_at[identifier] = _time(plans[identifier].updated_at or plans[identifier].created_at)

    resolved = {}

    def route(identifier):
        flow, item = flows.get(identifier), items[identifier]
        return flow.route if flow else ('assembly' if item.kind == 'Assembly' else
            'spool' if item.kind == 'Spool' or identifier in plans or identifier in registrations else 'component')

    def project(identifier):
        plan = plans.get(identifier)
        return plan.project_id if plan else items[identifier].project

    def resolve(identifier, visiting):
        if identifier in resolved:
            return resolved[identifier]
        own = facts[identifier]
        parent_id = parents.get(identifier)
        own_route = route(identifier)
        expected = {'component': 'spool', 'spool': 'assembly'}.get(own_route)
        eligible = (identifier in active and parent_id in active and parent_id not in visiting
            and expected and route(parent_id) == expected and completion_windows.get(identifier)
            and linked_at.get(identifier) and project(identifier) == project(parent_id))
        if eligible:
            parent = resolve(parent_id, visiting | {identifier})
            # Retain every eligible parent visit, including those preceding a
            # later independent child transfer or another rework cycle. Current
            # position is the last real movement, not the last completion time.
            inherited = [{**row, 'inherited': True} for row in parent['movements']
                if any(row['at'] > max(start, linked_at[identifier]) and
                       (end is None or row['at'] < end)
                       for start, end in completion_windows[identifier])]
            movements = sorted(own['movements'] + inherited,
                               key=lambda row: (row['at'], row.get('event_id') or 0))
            own = movement_position(identifier, movements)
        resolved[identifier] = own
        return own

    # Include loaded ancestors so quality checks can share the same movement
    # snapshot without reading it again for every completed physical child.
    result = {}
    for identifier in items:
        fact = resolve(identifier, set())
        result[identifier] = {**fact['stage'], **station_visit_history(fact['movements'])}
    return result


