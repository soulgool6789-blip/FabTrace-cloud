"""Current logistics and QA positions coexist with retained 24-step records."""

import importlib

import pytest

from conftest import BADGES
from station_helpers import move
from test_flow import (ROOT, action_body, advance as advance_step, completed_spool,
                       create_item, detail, enroll, inspect_dimensions, link_spool)
from test_flow_testing import advance, body, decide
from test_progress import database_state
from tracking_helpers import ok


def assembly(api, *, legacy=False):
    parent = create_item(api, 'CATALOG-ASSEMBLY', kind='Assembly')
    child = completed_spool(api, 'CATALOG-CHILD')
    enroll(api, parent, 'assembly', expected_children=1, legacy_catalog=legacy)
    link_spool(api, parent, child)
    return parent


def reject_without_writes(api, item_id, payload, status, *, role='handler', action='advance'):
    before = database_state(api)
    response = api.post(f'{ROOT}/items/{item_id}/{action}', payload, role=role)
    assert response.status_code == status, response.text
    assert database_state(api) == before
    return response


@pytest.mark.parametrize('step', [18, 19])
def test_a_new_catalog_cannot_start_inside_an_unrecorded_testing_phase(api, step):
    from receiving_helpers import ensure_scope_arrival
    item_id = create_item(api, 'CATALOG-BASELINE', kind='Assembly')
    ensure_scope_arrival(api, item_id)
    reject_without_writes(api, item_id, {
        'route': 'assembly', 'expected_children': 1, 'start_step': step,
        'baseline_reference': 'EXISTING-WORK-REGISTER',
        'baseline_reason': 'Controlled enrollment of earlier production work'},
        422, role='admin', action='start')
    assert detail(api, item_id)['flow'] is None


def test_new_late_baseline_return_to_testing_requires_a_fresh_explicit_decision(api):
    item_id = create_item(api, 'CATALOG-LATE-BASELINE', kind='Assembly')
    baseline = enroll(api, item_id, 'assembly', start_step=22, expected_children=1)
    assert baseline['flow']['testing'] is None
    assert baseline['flow']['current']['return_steps'] == [17, 20, 21]
    payload = {'expected_version': baseline['flow']['version'],
        'reason': 'Final inspection found a condition requiring fresh testing',
        'reference': 'CONTROLLED-FINAL-NCR'}
    for target in (18, 19):
        reject_without_writes(api, item_id, {**payload, 'return_step': target},
                              422, role='inspector', action='fail')
    returned = ok(api.post(f'{ROOT}/items/{item_id}/fail',
        {**payload, 'return_step': 17}, role='inspector'))
    assert returned['flow']['current_step'] == 17
    assert returned['flow']['testing']['active']
    assert returned['flow']['testing']['phase'] == 'decision'
    assert returned['flow']['testing']['decision'] is None
    assert returned['events'][:len(baseline['events'])] == baseline['events']
    assert not any(row['data'].get('test_result') for row in returned['events'])
    reject_without_writes(api, item_id, body(api, item_id), 422)


@pytest.mark.parametrize('legacy', [False, True], ids=['current-25', 'retained-24'])
def test_catalog_binding_keeps_the_real_floor_ready_shipment_and_delivery_steps(api, legacy):
    item_id = assembly(api, legacy=legacy)
    version = 'CLM-24-v6' if legacy else 'CLM-25-v1'
    first = detail(api, item_id)
    assert first['flow']['catalog_version'] == version
    assert first['flow']['route_definition']['last_step'] == (24 if legacy else 25)
    assert first['flow']['ready_to_ship_step'] == (23 if legacy else 24)
    assert first['flow']['shipment_step'] == (24 if legacy else 25)
    flow = importlib.import_module('flow')
    with api.session_factory() as session:
        assert session.get(flow.FlowPlan, item_id).catalog_version == (None if legacy else version)
    saved = database_state(api)
    assert detail(api, item_id)['events'] == first['events']
    assert database_state(api) == saved

    inspect_dimensions(api, item_id)
    no = decide(api, item_id, 'NO')
    assert no['flow']['current_step'] == 20
    assert {row['status'] for row in no['flow']['steps'] if row['number'] in (18, 19)} == {'not_required'}
    advance(api, item_id, role='handler')
    advance(api, item_id, role='painter')
    at_qa = detail(api, item_id)
    assert at_qa['flow']['current']['display_qa_code'] == ('QA/QC-005' if legacy else 'QA/QC-006')
    move(api, item_id, 'qa_004' if legacy else 'qa_final')
    inspect_dimensions(api, item_id)
    released = advance(api, item_id, role='inspector')
    retained_events = released['events']
    assert released['flow']['current_step'] == 23
    assert released['item']['released'] is True
    assert not released['flow']['shipped_at']

    if not legacy:
        assert released['flow']['current']['title'] == 'Return to Floor'
        assert released['flow']['current']['handoff_location_id'] == 'floor'
        base = action_body(api, item_id)
        for fields, status, role in (
            ({'scanned_item_id': 'ANOTHER-ASSEMBLY'}, 422, 'handler'),
            ({'location_id': 'ready_to_ship'}, 422, 'handler'),
            ({'receiver_badge': BADGES['painter']}, 422, 'handler'),
            ({'expected_version': base['expected_version'] - 1}, 409, 'handler'),
            ({}, 403, 'painter'),
        ):
            reject_without_writes(api, item_id, {**base, **fields}, status, role=role)
        at_ready = advance_step(api, item_id, role='handler')
        assert at_ready['flow']['current_step'] == 24
        assert at_ready['item']['location'] == 'Floor'
        floor_event = at_ready['events'][-1]
        assert floor_event['step'] == 23 and floor_event['action'] == 'advance'
        assert floor_event['data']['handoff']['to']['location_id'] == 'floor'
        assert floor_event['data']['handoff']['scanned_item_id'] == item_id
        assert floor_event['data']['handoff']['receiver_badge'] == BADGES['handler']
        reject_without_writes(api, item_id,
            action_body(api, item_id, location_id='floor'), 422)
        reject_without_writes(api, item_id,
            action_body(api, item_id, receiver_badge=BADGES['painter']), 422)
    else:
        assert released['flow']['current']['title'] == 'Release to Ready to Ship'

    at_ship = advance_step(api, item_id, role='handler', location_id='ready_to_ship')
    assert at_ship['flow']['current_step'] == (24 if legacy else 25)
    assert at_ship['flow']['current']['is_shipment']
    assert at_ship['flow']['status'] == 'active' and not at_ship['flow']['shipped_at']
    assert at_ship['item']['location'] == 'Ready To Ship'
    assert at_ship['events'][:len(retained_events)] == retained_events
    process = at_ship['production_process']
    assert 'pause' in process['permissions']['allowed_actions']
    paused = ok(api.post(f'/api/tracking/spools/{item_id}/process', {
        'action': 'pause', 'expected_version': process['version'], 'notes': 'Awaiting the customer carrier'}, role='handler'), 201)
    ok(api.post(f'/api/tracking/spools/{item_id}/process', {
        'action': 'resume', 'expected_version': paused['version']}, role='handler'), 201)
    reject_without_writes(api, item_id, action_body(api, item_id, carrier=''), 422)
    shipped = advance_step(api, item_id, role='handler')
    assert shipped['flow']['status'] == 'shipped' and shipped['flow']['current_step'] is None
    assert shipped['flow']['carrier'] == 'Test carrier'
    assert shipped['events'][-1]['step'] == (24 if legacy else 25)
    assert shipped['events'][-1]['data']['definition_version'] == version
    delivered = ok(api.post(f'{ROOT}/items/{item_id}/deliver', {
        'expected_version': shipped['flow']['version'], 'receipt_reference': 'CUSTOMER-RECEIPT',
        'recipient': 'Customer receiver'}, role='handler'))
    assert delivered['flow']['status'] == 'delivered'
    assert delivered['events'][-1]['step'] == (24 if legacy else 25)
    assert delivered['events'][:len(shipped['events'])] == shipped['events']
    assert len(delivered['flow']['steps']) == (8 if legacy else 9)
    if legacy:
        assert not any(row['number'] == 25 for row in delivered['flow']['steps'])


@pytest.mark.parametrize('legacy', [False, True], ids=['separate-pressure-QA005', 'retained-shared-QA004'])
def test_test_reports_and_reviews_require_their_catalogs_exact_qa_position(api, legacy):
    item_id = assembly(api, legacy=legacy)
    inspect_dimensions(api, item_id)
    decide(api, item_id)
    advance(api, item_id, role='ndt')
    reject_without_writes(api, item_id,
        body(api, item_id, location_id='qa_pressure_results'), 422, role='ndt')
    ndt = advance(api, item_id, role='ndt')
    assert ndt['flow']['current']['display_qa_code'] == 'QA/QC-004'
    assert ndt['flow']['current']['qa_stage'] == 'qa_test_results'
    advance(api, item_id, role='inspector')
    advance(api, item_id, role='handler')
    advance(api, item_id, role='pressure_testing_technician')
    expected = 'qa_test_results' if legacy else 'qa_pressure_results'
    wrong = 'qa_pressure_results' if legacy else 'qa_test_results'
    reject_without_writes(api, item_id, body(api, item_id, location_id=wrong),
                          422, role='pressure_testing_technician')
    pressure = advance(api, item_id, role='pressure_testing_technician')
    assert pressure['flow']['testing']['phase'] == 'pressure_qa'
    assert pressure['flow']['current']['qa_stage'] == expected
    assert pressure['flow']['current']['display_qa_code'] == ('QA/QC-004' if legacy else 'QA/QC-005')
    numbered_current = next(row for row in pressure['flow']['steps'] if row['status'] == 'current')
    assert all(numbered_current[key] == value for key, value in pressure['flow']['current'].items())
    move(api, item_id, wrong, role='inspector')
    misplaced = detail(api, item_id)
    assert wrong in {row['key'] for row in misplaced['stage_catalog']}
    reject_without_writes(api, item_id, body(api, item_id), 409, role='inspector')
    move(api, item_id, expected, role='inspector')
    approved = advance(api, item_id, role='inspector')
    qa = approved['events'][-1]
    assert qa['data']['test_kind'] == 'pressure' and qa['data']['test_result'] == 'PASS'
    assert qa['data']['step_definition']['qa_stage'] == expected
    assert qa['data']['step_definition']['display_qa_code'] == ('QA/QC-004' if legacy else 'QA/QC-005')
    assert qa['data']['definition_version'] == ('CLM-24-v6' if legacy else 'CLM-25-v1')
