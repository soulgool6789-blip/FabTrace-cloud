"""Versioned testing decisions use real API custody, reports and QA records."""

import importlib

import pytest
from sqlalchemy import select

from conftest import BADGES
from test_flow import (ROOT, completed_spool, create_item, detail, enroll,
                       inspect_dimensions, link_spool)
from tracking_helpers import (accept_weld, add_weld, approve, complete_weld,
                              find_requirement, ok, requirement, review, submit)


def assembly(api, name='TEST-PHASE-ASSEMBLY', *, planned=0):
    parent = create_item(api, name, kind='Assembly', planned=planned)
    child = completed_spool(api, name + '-CHILD')
    enroll(api, parent, 'assembly', expected_children=1)
    link_spool(api, parent, child)
    return parent


def body(api, item_id, **values):
    current = detail(api, item_id)
    step, testing = current['flow']['current'], current['flow']['testing']
    data = {'expected_version': current['flow']['version'],
            'confirmations': [check['id'] for check in step['checks']]}
    if step['requires_scan']:
        data['scanned_item_id'] = item_id
    if step['requires_reference']:
        data['reference'] = 'CONTROLLED-TEST-REPORT'
    if step.get('requires_child_scans'):
        data['scanned_child_ids'] = [row['item_id'] for row in current['spools']]
    if step.get('requires_handoff'):
        target = step.get('handoff_target_role') or 'handler'
        data.update(sender_badge=current['item']['handler'], receiver_badge=BADGES[target],
                    location_id=step.get('handoff_location_id') or 'blast_paint',
                    operational_status='in_progress', expected_transfer_version=current['transfer']['version'])
    if testing and testing['active']:
        data.update(testing_phase=testing['phase'], testing_attempt=testing['attempt'],
                    testing_action=testing['action'])
        if testing['requires_result']:
            data['test_result'] = 'PASS'
        if testing['action'] == 'correct':
            data['resolution'] = 'Corrected the failed test setup and verified the approved procedure'
        if testing['action'] == 'review' and testing.get('review_exception_ids'):
            data['resolution'] = 'Reviewed the completed correction and passing fresh test attempt'
    return {**data, **values}


def advance(api, item_id, *, role='admin', **values):
    return ok(api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id, **values), role=role))


def decide(api, item_id, value='YES'):
    return advance(api, item_id, role='handler', testing_decision=value)


def report(api, item_id, *, kind='ndt', result='PASS'):
    role = 'ndt' if kind == 'ndt' else 'pressure_testing_technician'
    advance(api, item_id, role=role)
    return advance(api, item_id, role=role, test_result=result,
                   reference=kind.upper() + '-REPORT')


def fail_body(api, item_id, **values):
    current = detail(api, item_id)
    testing = current['flow']['testing']
    target = testing['return_to']
    return {'expected_version': current['flow']['version'],
        'testing_phase': testing['phase'], 'testing_attempt': testing['attempt'],
        'testing_action': 'review', 'test_result': 'FAIL',
        'reason': 'Measured result does not meet the approved test requirement',
        'reference': 'QA-FAILED-TEST-REVIEW', 'scanned_item_id': item_id,
        'sender_badge': current['item']['handler'], 'receiver_badge': target['sender_badge'],
        'location_id': target['location_id'], 'operational_status': 'in_progress',
        'expected_transfer_version': current['transfer']['version'], **values}


def fail(api, item_id, **values):
    return ok(api.post(f'{ROOT}/items/{item_id}/fail', fail_body(api, item_id, **values), role='inspector'))


def to_ndt_qa(api, item_id):
    inspect_dimensions(api, item_id)
    decide(api, item_id)
    return report(api, item_id)


def finish_tests(api, item_id):
    to_ndt_qa(api, item_id)
    advance(api, item_id, role='inspector')
    advance(api, item_id, role='handler')
    report(api, item_id, kind='pressure')
    advance(api, item_id, role='inspector')
    return advance(api, item_id, role='handler')


def test_decision_is_required_and_no_keeps_non_test_quality_gates(api):
    item_id = assembly(api)
    before = detail(api, item_id)
    assert before['flow']['current']['title'] == 'Determine if Spool need to be sent to Testing'
    missing = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id), role='handler')
    assert missing.status_code == 422, missing.text
    assert detail(api, item_id)['events'] == before['events']
    no = decide(api, item_id, 'NO')
    assert no['flow']['current_step'] == 20
    assert no['flow']['testing']['decision'] == 'NO'
    assert {row['status'] for row in no['flow']['steps'] if row['number'] in (18, 19)} == {'not_required'}
    assert not [event for event in no['events'] if event['step'] == 18]
    blocked = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id), role='handler')
    assert blocked.status_code == 409, blocked.text
    assert 'dimensional' in blocked.text.lower()
    inspect_dimensions(api, item_id)
    assert advance(api, item_id, role='handler')['flow']['current_step'] == 21


def test_yes_has_two_distinct_role_controlled_tests_and_mandatory_floor_handoffs(api):
    item_id = assembly(api)
    at_ndt_qa = to_ndt_qa(api, item_id)
    testing = at_ndt_qa['flow']['testing']
    assert testing['phase'] == 'ndt_qa' and testing['report']['result'] == 'PASS'
    assert testing['return_to'] == {'sender_badge': BADGES['ndt'], 'sender_name': 'Test ndt',
                                  'location_id': 'testing', 'location_label': 'Testing'}
    at_floor = advance(api, item_id, role='inspector')
    assert at_floor['flow']['testing']['phase'] == 'floor_before_pressure'
    assert at_floor['item']['location'] == 'QA/QC-004'
    wrong_floor = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id, location_id='blast_paint'), role='handler')
    assert wrong_floor.status_code == 422, wrong_floor.text
    pressure = advance(api, item_id, role='handler')
    assert pressure['flow']['testing']['phase'] == 'pressure_test'
    assert pressure['item']['location'] == 'Floor'
    report(api, item_id, kind='pressure')
    final_floor = advance(api, item_id, role='inspector')
    states = {row['number']: row['status'] for row in final_floor['flow']['steps']}
    assert (states[17], states[18], states[19]) == ('completed', 'completed', 'current')
    finished = advance(api, item_id, role='handler')
    assert finished['flow']['current_step'] == 20
    assert finished['flow']['testing']['phase'] == 'complete'
    assert all(row['status'] == 'completed' for row in finished['flow']['steps'] if row['number'] in (17, 18, 19))
    reviews = [event for event in finished['events'] if event['data'].get('testing_action') == 'review']
    assert [(event['data']['test_kind'], event['data']['test_result'], event['actor']) for event in reviews] == [
        ('ndt', 'PASS', BADGES['inspector']), ('pressure', 'PASS', BADGES['inspector'])]
    assert reviews[0]['data']['phase_only'] is True and reviews[1]['data']['phase_only'] is False
    visits = finished['production_process']['visits']
    assert any('NDT' in row['process_name'] for row in visits)
    assert any('Pressure Test' in row['process_name'] for row in visits)
    advance(api, item_id, role='handler')
    advance(api, item_id, role='painter')
    inspect_dimensions(api, item_id)
    released = advance(api, item_id, role='inspector')
    assert released['flow']['current_step'] == 23
    assert released['item']['released'] is True


@pytest.mark.parametrize('role', ['ndt', 'pressure_testing_technician', 'inspector', 'painter'])
def test_decision_requires_the_assigned_material_position(api, role):
    item_id = assembly(api)
    response = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id, testing_decision='YES'), role=role)
    assert response.status_code == 403, response.text
    assert detail(api, item_id)['flow']['testing']['decision'] is None


def test_phase_attempt_report_result_and_qa_position_are_not_optional(api):
    item_id = assembly(api)
    inspect_dimensions(api, item_id)
    decide(api, item_id)
    original = body(api, item_id)
    for values in ({'testing_phase': 'pressure_test'}, {'testing_attempt': 2}, {'testing_action': 'complete'}):
        response = api.post(f'{ROOT}/items/{item_id}/advance', {**original, **values}, role='ndt')
        assert response.status_code == 409, response.text
    assert api.post(f'{ROOT}/items/{item_id}/advance', original, role='pressure_testing_technician').status_code == 403
    advance(api, item_id, role='ndt')
    report_body = body(api, item_id)
    for values in ({'test_result': None}, {'reference': ''}, {'receiver_badge': BADGES['handler']}, {'location_id': 'floor'}):
        response = api.post(f'{ROOT}/items/{item_id}/advance', {**report_body, **values}, role='ndt')
        assert response.status_code == 422, response.text
    advance(api, item_id, role='ndt')
    before = detail(api, item_id)
    assert api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id), role='ndt').status_code == 403
    missing = body(api, item_id)
    missing.pop('test_result')
    assert api.post(f'{ROOT}/items/{item_id}/advance', missing, role='inspector').status_code == 422
    assert detail(api, item_id)['events'] == before['events']


def test_failed_report_returns_exact_sender_and_requires_correction_then_fresh_test(api):
    item_id = assembly(api)
    inspect_dimensions(api, item_id)
    decide(api, item_id)
    report(api, item_id, result='FAIL')
    false_pass = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id), role='inspector')
    assert false_pass.status_code == 409, false_pass.text
    before = detail(api, item_id)
    for values in ({'receiver_badge': BADGES['pressure_testing_technician']}, {'location_id': 'floor'}, {'return_step': 17}):
        response = api.post(f'{ROOT}/items/{item_id}/fail', fail_body(api, item_id, **values), role='inspector')
        assert response.status_code == 422, response.text
    assert detail(api, item_id)['events'] == before['events']
    failed = fail(api, item_id)
    assert failed['flow']['testing']['phase'] == 'ndt_rework'
    assert failed['item']['handler'] == BADGES['ndt'] and failed['item']['location'] == 'Testing'
    assert failed['exceptions'][-1]['closed_at'] is None
    bypass = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id, testing_decision='NO'), role='ndt')
    assert bypass.status_code == 422, bypass.text
    missing = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id, resolution=''), role='ndt')
    assert missing.status_code == 422, missing.text
    corrected = advance(api, item_id, role='ndt')
    assert corrected['flow']['testing']['attempt'] == 2 and corrected['flow']['testing']['phase'] == 'ndt'
    assert corrected['exceptions'][-1]['closed_at'] is None
    report(api, item_id)
    no_dimensions = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id), role='inspector')
    assert no_dimensions.status_code == 409, no_dimensions.text
    inspect_dimensions(api, item_id)
    passed = advance(api, item_id, role='inspector')
    assert passed['exceptions'][-1]['closed_by'] == BADGES['inspector']
    assert passed['flow']['testing']['pending_exception_ids'] == []


def test_repeated_failures_close_only_the_explicit_corrected_test_chain(api):
    item_id = assembly(api)
    to_ndt_qa(api, item_id)
    for attempt in (1, 2):
        failed = fail(api, item_id)
        assert failed['flow']['testing']['attempt'] == attempt
        advance(api, item_id, role='ndt')
        inspect_dimensions(api, item_id)
        report(api, item_id)
    passed = advance(api, item_id, role='inspector')
    assert passed['flow']['testing']['attempt'] == 3
    assert len(passed['exceptions']) == 2
    assert all(row['closed_at'] for row in passed['exceptions'])
    corrections = [event for event in passed['events'] if event['data'].get('testing_action') == 'correct']
    assert [event['data']['correction']['exception_id'] for event in corrections] == [row['id'] for row in passed['exceptions']]


def test_physical_scope_changes_after_report_require_failure_and_retest(api):
    item_id = assembly(api)
    to_ndt_qa(api, item_id)
    before = detail(api, item_id)
    with api.session_factory() as session:
        item = session.get(api.application.Item, item_id)
        item.drawing = 'CONTROLLED-REVISION-B'
        session.commit()
    response = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id), role='inspector')
    assert response.status_code == 409, response.text
    assert 'changed after this test report' in response.text
    assert detail(api, item_id)['events'] == before['events']


def test_setup_scope_freezes_after_decision_but_repairs_are_allowed_during_correction(api):
    item_id = assembly(api)
    to_ndt_qa(api, item_id)
    fail(api, item_id)
    current = detail(api, item_id)
    response = api.post(f'{ROOT}/items/{item_id}/scope', {
        'expected_version': current['flow']['version'], 'expected_children': 2,
        'reason': 'Attempt to change tested physical scope', 'reference': 'SCOPE-CHANGE'})
    assert response.status_code == 409, response.text
    flow = importlib.import_module('flow')
    with api.session_factory() as session:
        item = session.get(api.application.Item, item_id)
        flow.guard_weld_operation(session, item, 'fitup')


def test_final_qa_return_restarts_a_required_cycle_and_cannot_jump_to_generic_test_qa(api):
    item_id = assembly(api)
    finish_tests(api, item_id)
    advance(api, item_id, role='handler')
    advance(api, item_id, role='painter')
    current = detail(api, item_id)
    assert current['flow']['current_step'] == 22
    assert current['flow']['current']['return_steps'] == [17, 20, 21]
    for target in (18, 19):
        response = api.post(f'{ROOT}/items/{item_id}/fail', {
            'expected_version': current['flow']['version'], 'return_step': target,
            'reason': 'Coating acceptance needs a construction review', 'reference': 'FINAL-FAIL'}, role='inspector')
        assert response.status_code == 422, response.text
    returned = ok(api.post(f'{ROOT}/items/{item_id}/fail', {
        'expected_version': current['flow']['version'], 'return_step': 17,
        'reason': 'Construction correction requires the testing route again', 'reference': 'FINAL-FAIL'}, role='inspector'))
    assert returned['flow']['testing']['cycle'] == 2
    assert returned['flow']['testing']['phase'] == 'decision'
    assert 'scope' not in returned['allowed_actions'] and 'link-spool' not in returned['allowed_actions']
    no = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id, testing_decision='NO'), role='handler')
    assert no.status_code == 409, no.text


def test_future_pressure_requirement_defers_only_until_its_qa_and_reviews_do_not_stale_reports(api):
    item_id = assembly(api)
    required = {}
    for kind, owner in (('NDT', 'ndt'), ('PRESSURE', 'pressure_testing_technician')):
        required[kind] = ok(api.post(f'/api/tracking/spools/{item_id}/requirements', {
            'code': kind + '-REPORT', 'label': kind + ' approved test report',
            'stage': 'after_welding', 'owner_role': owner,
            'evidence_required': True,
        }), 201)['id']
    to_ndt_qa(api, item_id)
    blocked_ndt = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id), role='inspector')
    assert blocked_ndt.status_code == 409, blocked_ndt.text
    assert 'NDT approved test report' in blocked_ndt.text
    assert 'PRESSURE approved test report' not in blocked_ndt.text
    submit(api, item_id, required['NDT'], reference='ACCEPTED-NDT-PROOF', result='pass', role='ndt')
    ok(review(api, item_id, required['NDT']))
    # QA evidence was signed after the physical report. Those acceptance acts
    # do not change construction/source scope or make the report stale.
    ndt_passed = advance(api, item_id, role='inspector')
    assert ndt_passed['flow']['testing']['phase'] == 'floor_before_pressure'
    advance(api, item_id, role='handler')
    report(api, item_id, kind='pressure')
    blocked_pressure = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id), role='inspector')
    assert blocked_pressure.status_code == 409, blocked_pressure.text
    assert 'PRESSURE approved test report' in blocked_pressure.text
    submit(api, item_id, required['PRESSURE'], reference='ACCEPTED-PRESSURE-PROOF',
           result='pass', role='pressure_testing_technician')
    ok(review(api, item_id, required['PRESSURE']))
    assert advance(api, item_id, role='inspector')['flow']['testing']['phase'] == 'floor_before_paint'


def test_pressure_failure_returns_to_pressure_sender_and_retests_same_kind(api):
    item_id = assembly(api)
    to_ndt_qa(api, item_id)
    advance(api, item_id, role='inspector')
    advance(api, item_id, role='handler')
    report(api, item_id, kind='pressure')
    failed = fail(api, item_id)
    assert failed['flow']['testing']['phase'] == 'pressure_rework'
    assert failed['item']['handler'] == BADGES['pressure_testing_technician']
    advance(api, item_id, role='pressure_testing_technician')
    inspect_dimensions(api, item_id)
    repeated = report(api, item_id, kind='pressure')
    assert repeated['flow']['testing']['attempt'] == 2
    assert repeated['flow']['testing']['test_kind'] == 'pressure'
    passed = advance(api, item_id, role='inspector')
    assert passed['flow']['testing']['phase'] == 'floor_before_paint'
    assert passed['exceptions'][-1]['closed_at']


def test_changed_source_after_qa_blocks_paint_and_controlled_restart_preserves_testing(api):
    item_id = assembly(api)
    finish_tests(api, item_id)
    before = detail(api, item_id)
    assert 'restart-testing' in before['allowed_actions']
    with api.session_factory() as session:
        session.get(api.application.Item, item_id).drawing = 'REVISED-POST-TEST-SCOPE'
        session.commit()
    blocked = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id), role='handler')
    assert blocked.status_code == 409, blocked.text
    assert 'changed after testing approval' in blocked.text
    payload = {'expected_version': before['flow']['version'],
               'reason': 'Revised construction source must be tested against current scope',
               'reference': 'CONTROLLED-RETEST-CHANGE'}
    url = f'{ROOT}/items/{item_id}/restart-testing'
    assert api.post(url, payload, role='handler').status_code == 403
    assert api.post(url, {**payload, 'expected_version': payload['expected_version'] - 1}, role='supervisor').status_code == 409
    restarted = ok(api.post(url, payload, role='supervisor'))
    assert restarted['flow']['current_step'] == 17
    assert restarted['flow']['testing']['cycle'] == 2
    assert restarted['flow']['testing']['decision'] == 'YES'
    assert restarted['flow']['testing']['report'] is None
    assert restarted['item']['handler'] == before['item']['handler']
    assert restarted['item']['location'] == before['item']['location']
    assert restarted['events'][-1]['action'] == 'reopen'
    assert restarted['events'][-1]['data']['testing_action'] == 'restart'
    assert 'scope' not in restarted['allowed_actions'] and 'link-spool' not in restarted['allowed_actions']
    no = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id, testing_decision='NO'), role='handler')
    assert no.status_code == 409, no.text
    decide(api, item_id, 'YES')
    report(api, item_id)
    advance(api, item_id, role='inspector')
    advance(api, item_id, role='handler')
    report(api, item_id, kind='pressure')
    advance(api, item_id, role='inspector')
    advance(api, item_id, role='handler')
    assert advance(api, item_id, role='handler')['flow']['current_step'] == 21


def test_pressure_repair_requires_fresh_ndt_and_carries_exact_exception_until_pressure_reinspection(api):
    item_id = assembly(api, planned=1)
    weld = add_weld(api, item_id)
    complete_weld(api, item_id, weld['id'])
    accept_weld(api, item_id, weld['id'])
    to_ndt_qa(api, item_id)
    advance(api, item_id, role='inspector')
    advance(api, item_id, role='handler')
    report(api, item_id, kind='pressure')
    failed = fail(api, item_id)
    original_exception = failed['exceptions'][-1]['id']
    restart_url = f'{ROOT}/items/{item_id}/restart-testing'
    premature = api.post(restart_url, {'expected_version': failed['flow']['version'],
        'reason': 'Attempt to bypass required pressure correction', 'reference': 'PREMATURE-RESTART'}, role='supervisor')
    assert premature.status_code == 409, premature.text
    # This is actual recorded construction repair, not a synthetic phase flag.
    ok(api.post(f"/api/tracking/welds/{weld['id']}/repairs", {
        'reason': 'Pressure failure requires repair of the physical assembly weld'}, role='inspector'), 201)
    complete_weld(api, item_id, weld['id'])
    accept_weld(api, item_id, weld['id'])
    advance(api, item_id, role='pressure_testing_technician')
    corrected = detail(api, item_id)
    assert 'restart-testing' in corrected['allowed_actions']
    assert any('changed after NDT approval' in message for message in corrected['flow']['blockers'])
    blocked_test = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id), role='pressure_testing_technician')
    assert blocked_test.status_code == 409, blocked_test.text
    inspect_dimensions(api, item_id)
    current = detail(api, item_id)
    restarted = ok(api.post(restart_url, {'expected_version': current['flow']['version'],
        'reason': 'Physical weld repair requires fresh NDT before the pressure retest',
        'reference': 'CONTROLLED-CONSTRUCTION-RETEST'}, role='supervisor'))
    assert restarted['flow']['testing']['cycle'] == 2
    assert restarted['flow']['testing']['pending_exception_ids'] == [original_exception]
    assert restarted['events'][-1]['data']['carried_exception_ids'] == [original_exception]
    decide(api, item_id)
    report(api, item_id)
    before_ndt_qa = detail(api, item_id)
    assert before_ndt_qa['flow']['testing']['review_exception_ids'] == []
    ndt_pass = advance(api, item_id, role='inspector')
    assert ndt_pass['exceptions'][-1]['closed_at'] is None
    assert ndt_pass['events'][-1]['data']['closed_exception_ids'] == []
    assert ndt_pass['events'][-1]['data']['remaining_exception_ids'] == [original_exception]
    # The old pressure exception must not deadlock the required interim floor
    # handoff, and NDT approval must not close it on behalf of pressure QA.
    advance(api, item_id, role='handler')
    report(api, item_id, kind='pressure')
    before_pressure_qa = detail(api, item_id)
    assert before_pressure_qa['flow']['testing']['review_exception_ids'] == [original_exception]
    passed = advance(api, item_id, role='inspector')
    assert passed['exceptions'][-1]['id'] == original_exception
    assert passed['exceptions'][-1]['closed_by'] == BADGES['inspector']
    assert passed['events'][-1]['data']['closed_exception_ids'] == [original_exception]
    assert passed['flow']['testing']['pending_exception_ids'] == []


def test_verification_cycle_reopening_does_not_claim_construction_changed(api):
    item_id = assembly(api, planned=1)
    weld = add_weld(api, item_id)
    complete_weld(api, item_id, weld['id'])
    accept_weld(api, item_id, weld['id'])
    visual = find_requirement(api, item_id, weld['id'], code='VT')['id']
    final = find_requirement(api, item_id, weld['id'], code='FINAL_QA')['id']
    old_cycle = requirement(api, item_id, final)['cycle']
    to_ndt_qa(api, item_id)
    submit(api, item_id, visual, reference='REVISED-VISUAL-EVIDENCE', result='pass')
    ok(review(api, item_id, visual))
    assert requirement(api, item_id, final)['cycle'] == old_cycle + 1
    assert advance(api, item_id, role='inspector')['flow']['testing']['phase'] == 'floor_before_pressure'
    approve(api, item_id, final, reference='REOPENED-FINAL-WELD-VERIFICATION')
    advance(api, item_id, role='handler')
    report(api, item_id, kind='pressure')
    submit(api, item_id, visual, reference='SECOND-VISUAL-RECORD', result='pass')
    ok(review(api, item_id, visual))
    assert requirement(api, item_id, final)['cycle'] == old_cycle + 2
    # Both the prior NDT prerequisite and this pressure report remain tied to
    # unchanged construction; actual final verification is still pending.
    assert advance(api, item_id, role='inspector')['flow']['testing']['phase'] == 'floor_before_paint'
    assert requirement(api, item_id, final)['status'] == 'pending'


@pytest.mark.parametrize('decision', ['YES', 'NO'])
def test_incomplete_own_welds_cannot_leave_decision_and_do_not_save_a_choice(api, decision):
    item_id = assembly(api, planned=1)
    before = detail(api, item_id)
    response = api.post(f'{ROOT}/items/{item_id}/advance',
                        body(api, item_id, testing_decision=decision), role='handler')
    assert response.status_code == 409, response.text
    assert 'planned individual weld' in response.text
    after = detail(api, item_id)
    assert after['flow']['current_step'] == 17 and after['flow']['testing']['decision'] is None
    assert after['flow']['version'] == before['flow']['version']
    assert after['events'] == before['events']
    flow_testing = importlib.import_module('flow_testing')
    with api.session_factory() as session:
        assert session.get(flow_testing.FlowTestingState, item_id) is None


def test_repair_opened_during_ndt_can_return_to_editable_fabrication_without_skipping_qa(api):
    item_id = assembly(api, planned=1)
    weld = add_weld(api, item_id)
    complete_weld(api, item_id, weld['id'])
    accept_weld(api, item_id, weld['id'])
    decide(api, item_id)
    advance(api, item_id, role='ndt')
    ok(api.post(f"/api/tracking/welds/{weld['id']}/repairs", {
        'reason': 'A physical defect was identified before the NDT report was completed'}, role='inspector'), 201)
    before = detail(api, item_id)
    blocked = api.post(f'{ROOT}/items/{item_id}/advance', body(api, item_id), role='ndt')
    assert blocked.status_code == 409, blocked.text
    assert 'individual welding operations are incomplete' in blocked.text
    assert 'restart-testing' in before['allowed_actions']
    restarted = ok(api.post(f'{ROOT}/items/{item_id}/restart-testing', {
        'expected_version': before['flow']['version'],
        'reason': 'Return the incomplete physical weld to controlled fabrication',
        'reference': 'NDT-CONSTRUCTION-RETURN'}))
    assert restarted['flow']['testing']['phase'] == 'decision'
    assert restarted['flow']['testing']['decision'] == 'YES'
    assert restarted['flow']['testing']['cycle'] == 2
    assert restarted['item']['location'] == before['item']['location']
    assert restarted['item']['handler'] == before['item']['handler']
    assert not [event for event in restarted['events'] if event['data'].get('testing_action') == 'review']
    assert 'scope' not in restarted['allowed_actions'] and 'link-spool' not in restarted['allowed_actions']
    complete_weld(api, item_id, weld['id'])
    assert decide(api, item_id)['flow']['testing']['phase'] == 'ndt'

