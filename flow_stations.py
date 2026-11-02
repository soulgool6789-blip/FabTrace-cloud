"""Current physical stations from recorded movement, never inferred QA/work.

The numbered traveler still owns production and release gates. This read model
only answers where an individual record was last moved. Unknown historical
destinations retain the last identified process and ask for an explicit station.
"""
from collections import defaultdict
import datetime as dt

from sqlalchemy import select

from flow_stages import stage_status


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
            FlowEvent.action.in_(('advance', 'assembly_link', 'custody_transfer')))
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
    facts, completed, linked_at = {}, {}, {}

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
                          mapped(location_id, step, transfer_definitions.get(data.get('transfer_version')))))
        # A retained current-state row is evidence when older movement audit
        # history is unavailable. Item.location alone never establishes a move.
        state = states.get(identifier)
        if not moves and state and state.location_id:
            moves.append((state.updated_at, None, state.location_id, item.location,
                          'recorded_state', mapped(state.location_id, None)))
        for moved_at, event_id, location_id, label, source, key in moves:
            latest_at = _time(moved_at)
            if key:
                stage = {**stage_status(key, identifier), 'position_source': source,
                    'position_recorded_at': latest_at.isoformat(), 'position_event_id': event_id}
                at = latest_at
            stage.update(recorded_location_id=location_id, recorded_location_label=label,
                         needs_station_selection=not bool(key))
        facts[identifier] = {'stage': stage, 'at': at, 'latest_at': latest_at}
        flow = flows.get(identifier)
        advances = [row for row in events[identifier] if row.action == 'advance']
        if flow and flow.route == 'component':
            prep_at = [_time(row.at) for row in advances if row.step == 7]
            done_at = [_time(row.at) for row in advances if row.step == 8]
            completed[identifier] = max((at for at in done_at if any(prep <= at for prep in prep_at)), default=None)
        elif flow and flow.route == 'spool':
            completed[identifier] = max((_time(row.at) for row in advances if row.step == 16), default=None)
            if completed[identifier] is None and flow.status == 'completed':
                completed[identifier] = _time(flow.completed_at)
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
            and expected and route(parent_id) == expected and completed.get(identifier)
            and linked_at.get(identifier) and project(identifier) == project(parent_id))
        if eligible:
            parent = resolve(parent_id, visiting | {identifier})
            threshold = max(value for value in (completed[identifier], linked_at[identifier], own['latest_at']) if value)
            if parent['at'] and parent['at'] > threshold:
                own = {**parent, 'stage': {**parent['stage'], 'inherited': True}}
        resolved[identifier] = own
        return own

    # Include loaded ancestors so quality checks can share the same movement
    # snapshot without reading it again for every completed physical child.
    return {identifier: resolve(identifier, set())['stage'] for identifier in items}

