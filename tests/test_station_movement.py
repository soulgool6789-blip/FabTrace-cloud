"""Station is recorded transport; work, QA and QR reads are separate facts."""
from receiving_helpers import accept_arrival
from station_helpers import move
from test_flow import advance, detail, enroll, inspect_dimensions
from test_order_labels import generate, labels, public_qr_url
from test_production_progress import flatten
from test_progress import database_state
from test_spool_status_presentation import seed
from tracking_helpers import ok


def stages(api, project):
    flow = {row['item_id']: row['flow_stage'] for row in ok(api.get('/api/flow/board', params={'project_id': project}))['items']}
    progress = flatten(ok(api.get('/api/progress/orders', params={'project_id': project})))
    assert all(progress[identifier]['flow_stage'] == stage for identifier, stage in flow.items())
    return flow


def test_pending_inventory_moves_only_on_an_authenticated_exact_copy_transfer(api):
    _, project, _ = seed(api)
    generate(api, project)
    first, second = labels(api, project)['items']
    initial = stages(api, project)
    assert all(stage['key'] == 'inventory' and stage['color'] == 'black' and stage['blocked'] for stage in initial.values())
    before = database_state(api)
    assert detail(api, first['id'])['flow_stage'] == initial[first['id']]
    assert stages(api, project) == initial
    assert database_state(api) == before
    ok(api.post('/api/items/' + first['id'] + '/scan'))
    scanned = ok(api.get('/api/items/' + first['id']))
    assert scanned['transfer']['version'] == 0 and scanned['flow_stage'] == initial[first['id']]

    moved = move(api, first['id'], 'qa_001', status='awaiting_inspection')
    assert moved['flow_stage']['key'] == 'qa_001' and moved['flow_stage']['blocked']
    assert not moved['receiving']['can_proceed'] and not moved['flow_enabled'] and not moved['released']
    assert stages(api, project)[second['id']] == initial[second['id']]
    station_event = moved['flow_stage']['position_event_id']
    accept_arrival(api, first['id'])
    accepted = ok(api.get('/api/items/' + first['id']))
    assert accepted['flow_stage']['key'] == 'qa_001'
    assert accepted['flow_stage']['position_event_id'] == station_event
    prepared = move(api, first['id'], 'fabrication_prep')
    assert prepared['flow_stage']['key'] == 'preparation' and prepared['flow_stage']['color'] == 'red'
    assert not prepared['flow_enabled'] and not prepared['released']
    final = stages(api, project)
    assert final[first['id']]['key'] == 'preparation' and final[second['id']]['key'] == 'inventory'


def test_numbered_progress_and_quality_results_do_not_transport_a_spool(api):
    _, project, _ = seed(api)
    generate(api, project)
    item_id = labels(api, project)['items'][0]['id']
    enrolled = enroll(api, item_id, 'spool', start_step=10)
    assert enrolled['flow_stage']['key'] == 'inventory'
    move(api, item_id, 'fabrication_prep')
    current = advance(api, item_id)
    assert current['flow']['current_step'] == 11 and current['flow_stage']['key'] == 'preparation'
    move(api, item_id, 'qa_002', status='awaiting_inspection')
    inspect_dimensions(api, item_id)
    passed = advance(api, item_id, role='inspector')
    assert passed['flow']['current_step'] == 12 and passed['flow_stage']['key'] == 'qa_002'
    # A real required handoff can move the item; the numeric advance alone did not.
    handed = advance(api, item_id, location_id='floor')
    assert handed['flow']['current_step'] == 13 and handed['flow_stage']['key'] == 'floor'
    assert stages(api, project)[item_id]['key'] == 'floor'


def test_explicit_qa_choices_and_ambiguous_historical_destinations_remain_distinct(api):
    _, project, _ = seed(api)
    generate(api, project)
    item_id = labels(api, project)['items'][0]['id']
    options = ok(api.get('/api/transfers/options'))['locations']
    assert {row['flow_stage_key'] for row in options if row.get('active') and row.get('flow_stage_key')} == {
        'inventory', 'qa_001', 'preparation', 'qa_002', 'floor', 'welding', 'qa_003', 'testing', 'paint', 'qa_004', 'ready_to_ship'}
    assert not next(row for row in options if row['id'] == 'qa_qc')['active']
    legacy = move(api, item_id, 'qa_qc')
    assert legacy['flow_stage']['key'] == 'inventory' and legacy['flow_stage']['needs_station_selection']
    assert legacy['flow_stage']['recorded_location_id'] == 'qa_qc'
    # The same old identifier has an exact QA meaning only when the event at
    # the time of that transfer records a particular numbered QA checkpoint.
    enroll(api, item_id, 'spool', start_step=11)
    assert detail(api, item_id)['flow_stage']['key'] == 'inventory'
    move(api, item_id, 'floor')
    identified = move(api, item_id, 'qa_qc')
    assert identified['flow_stage']['key'] == 'qa_002' and not identified['flow_stage']['needs_station_selection']
    custom = ok(api.post('/api/transfers/locations', {'label': 'Synthetic storage annex'}), 201)
    unknown = move(api, item_id, custom['id'])
    assert unknown['flow_stage']['key'] == 'qa_002' and unknown['flow_stage']['needs_station_selection']
    assert unknown['flow_stage']['position_event_id'] == identified['flow_stage']['position_event_id']
    explicit = move(api, item_id, 'qa_003')
    assert explicit['flow_stage']['key'] == 'qa_003' and not explicit['flow_stage']['needs_station_selection']
