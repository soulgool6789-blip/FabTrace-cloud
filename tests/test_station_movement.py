"""Station is recorded transport; work, QA and QR reads are separate facts."""
import importlib

import pytest
from sqlalchemy import select

from receiving_helpers import accept_arrival
from station_helpers import move
from test_flow import advance, create_item, detail, enroll, inspect_dimensions
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
        'inventory', 'qa_001', 'preparation', 'qa_002', 'floor', 'welding', 'qa_003', 'testing', 'qa_test_results', 'qa_pressure_results', 'paint', 'qa_004', 'qa_final', 'ready_to_ship'}
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


def test_legacy_final_inspection_station_stays_pink_and_new_test_review_is_distinct(api, monkeypatch):
    _, project, _ = seed(api)
    generate(api, project)
    first, second = labels(api, project)['items']
    transfers = importlib.import_module('transfers')
    # Simulate the original final-inspection move with its original saved label.
    with monkeypatch.context() as old:
        old.setattr(transfers, 'LOCATION_BY_ID', {
            **transfers.LOCATION_BY_ID,
            'qa_004': {'id': 'qa_004', 'label': 'QA/QC-004'},
        })
        move(api, first['id'], 'qa_004')
    moved = move(api, second['id'], 'qa_test_results')
    assert moved['flow_stage']['key'] == 'qa_test_results'
    assert moved['flow_stage']['label'] == 'QA/QC-004'
    assert moved['flow_stage']['color'] == 'orange'
    before = database_state(api)
    current = stages(api, project)
    assert current[first['id']]['key'] == 'qa_004'
    assert current[first['id']]['label'] == 'QA/QC-005'
    assert current[first['id']]['color'] == 'pink'
    assert current[second['id']]['key'] == 'qa_test_results'
    assert current[second['id']]['color'] == 'orange'
    options = {row['id']: row for row in ok(api.get('/api/transfers/options'))['locations']}
    assert options['qa_004']['label'] == 'QA/QC-005'
    assert options['qa_test_results']['label'] == 'QA/QC-004'
    with api.session_factory() as session:
        audit = session.scalar(select(api.application.Audit).where(
            api.application.Audit.item_id == first['id'], api.application.Audit.event == 'TRANSFER'))
        assert audit.details['to']['location_id'] == 'qa_004'
        assert audit.details['to']['location'] == 'QA/QC-004'
    assert database_state(api) == before


def test_new_pressure_and_final_stations_retain_distinct_visits_and_legacy_final_meaning(api):
    item = api.item('QA-STATION-REVISION', kind='Spool', welds_required=0)
    identifier = item['id']
    legacy = move(api, identifier, 'qa_004')['flow_stage']
    pressure = move(api, identifier, 'qa_pressure_results')['flow_stage']
    final = move(api, identifier, 'qa_final')['flow_stage']
    assert (legacy['key'], legacy['label'], legacy['color']) == ('qa_004', 'QA/QC-005', 'pink')
    assert (pressure['key'], pressure['label'], pressure['color']) == ('qa_pressure_results', 'QA/QC-005', 'orange')
    assert (final['key'], final['label'], final['color']) == ('qa_final', 'QA/QC-006', 'pink')
    assert [(row['stage_key'], row['label']) for row in final['station_visits']] == [
        ('qa_004', 'QA/QC-005'), ('qa_pressure_results', 'QA/QC-005'), ('qa_final', 'QA/QC-006')]
    before = database_state(api)
    assert detail(api, identifier)['flow_stage'] == final
    assert database_state(api) == before


def test_label_only_legacy_qa005_remains_final_inspection(api):
    item = api.item('LEGACY-QA005-LABEL', kind='Spool', welds_required=0)
    move(api, item['id'], 'qa_004')
    with api.session_factory() as session:
        row = session.scalar(select(api.application.Audit).where(
            api.application.Audit.item_id == item['id'], api.application.Audit.event == 'TRANSFER'))
        row.details = {**row.details, 'to': {**row.details['to'], 'location_id': None, 'location': 'QA/QC-005'}}
        session.commit()
    before = database_state(api)
    stage = detail(api, item['id'])['flow_stage']
    assert stage['key'] == 'qa_004' and stage['color'] == 'pink'
    assert stage['station_visits'][0]['stage_key'] == 'qa_004'
    assert database_state(api) == before


@pytest.mark.parametrize('label_only', [False, True])
def test_recorded_pressure_review_definition_disambiguates_qa005_history(api, label_only):
    assembly = create_item(api, 'PRESSURE-QA-HISTORY', kind='Assembly')
    enroll(api, assembly, 'assembly', start_step=18, expected_children=1, legacy_catalog=True)
    move(api, assembly, 'testing')
    move(api, assembly, 'qa_qc')
    flow = importlib.import_module('flow')
    # Model an imported historical movement with its exact saved pressure
    # definition. The current cursor alone must not determine its station.
    with api.session_factory() as session:
        event = session.scalar(select(flow.FlowEvent).where(
            flow.FlowEvent.item_id == assembly, flow.FlowEvent.action == 'custody_transfer')
            .order_by(flow.FlowEvent.sequence.desc()))
        event.data = {**event.data, 'definition_version': 'CLM-25-v1',
            'step_definition': {'number': 18, 'title': 'QA/QC-005 - Verify Pressure Test Results',
                'display_qa_code': 'QA/QC-005', 'flow_stage_key': 'qa_pressure_results',
                'testing_phase': 'pressure_qa', 'catalog_version': 'CLM-25-v1'}}
        if label_only:
            audit = session.scalar(select(api.application.Audit).where(
                api.application.Audit.item_id == assembly, api.application.Audit.event == 'TRANSFER')
                .order_by(api.application.Audit.id.desc()))
            audit.details = {**audit.details, 'to': {**audit.details['to'],
                'location_id': None, 'location': 'QA/QC-005'}}
        session.commit()
    before = database_state(api)
    stage = detail(api, assembly)['flow_stage']
    assert stage['key'] == 'qa_pressure_results' and stage['label'] == 'QA/QC-005'
    assert stage['color'] == 'orange' and not stage['needs_station_selection']
    assert database_state(api) == before


@pytest.mark.parametrize('legacy_definition', [None, {
    'number': 18, 'title': 'Create Assembly ID', 'qa': False,
    'display_qa_code': None, 'flow_stage_key': 'testing',
}])
def test_historical_generic_step_18_move_needs_a_recorded_test_review_definition(api, legacy_definition):
    assembly = create_item(api, 'HISTORICAL-TESTING-ASSEMBLY', kind='Assembly')
    enroll(api, assembly, 'assembly', start_step=18, expected_children=1, legacy_catalog=True)
    move(api, assembly, 'testing')
    move(api, assembly, 'qa_qc')
    flow = importlib.import_module('flow')
    # Persist an isolated historical event exactly as a pre-v4 movement would
    # have described step 18; current catalog labels cannot replace this fact.
    with api.session_factory() as session:
        event = session.scalar(select(flow.FlowEvent).where(
            flow.FlowEvent.item_id == assembly, flow.FlowEvent.action == 'custody_transfer')
            .order_by(flow.FlowEvent.sequence.desc()))
        event.data = {**event.data, 'definition_version': 'CLM-24-v3',
                      'step_definition': legacy_definition}
        session.commit()
    before = database_state(api)
    historical = detail(api, assembly)['flow_stage']
    assert historical['key'] == 'testing' and historical['color'] == 'orange'
    assert historical['needs_station_selection']
    assert historical['recorded_location_id'] == 'qa_qc'
    assert database_state(api) == before
    move(api, assembly, 'testing')
    identified = move(api, assembly, 'qa_qc')['flow_stage']
    assert identified['key'] == 'qa_test_results'
    assert identified['label'] == 'QA/QC-004' and identified['color'] == 'orange'
    assert not identified['needs_station_selection']


