"""Mandatory arrival QA across every physical-spool work entry point.

These tests deliberately create unaccepted identities through public APIs.
Blocked writes are compared against the complete isolated database, including
audit, work, timers, and release records.
"""
import importlib

import pytest
from sqlalchemy import event

from conftest import BADGES
from tracking_helpers import add_weld, ok
from test_admin import disposition_body
from test_progress import database_state
from receiving_helpers import accept_arrival, receiving_detail, record_arrival, save_receiving_materials


PROJECT = 'ARRIVAL-GATE-PROJECT'


def pending_spool(api, item_id='ARRIVAL-SPOOL', *, tracked=True, kind='Spool', planned=1,
                  assembly_id=None):
    response = api.post('/api/tracking/projects', {'id': PROJECT, 'name': 'Synthetic arrival gate project'})
    assert response.status_code in (201, 409), response.text
    ok(api.post('/api/items', {
        'id': item_id, 'kind': kind, 'project': PROJECT,
        'google_part_number': 'SYNTHETIC-SPOOL-NUMBER',
        'description': 'Synthetic physical spool awaiting arrival QA',
        'location': 'Receiving', 'handler': BADGES['handler'], 'welds_required': planned,
    }), 201)
    if tracked:
        ok(api.post(f'/api/tracking/spools/{item_id}/plan', {
            'project_id': PROJECT, 'planned_welds': planned, 'assembly_id': assembly_id,
            'zero_weld_reason': 'Synthetic bolted scope' if not planned else '',
        }))
    return item_id


def blocked_without_changes(api, path, body, *, role='admin'):
    before = database_state(api)
    response = api.post(path, body, role=role)
    assert response.status_code == 409, response.text
    assert 'arrival' in response.text.lower() or 'receiving' in response.text.lower(), response.text
    assert database_state(api) == before


@pytest.mark.parametrize('kind', ['Spool', 'Part'])
def test_pending_arrival_blocks_fitup_and_independent_timer_for_true_and_legacy_spools(api, kind):
    item_id = pending_spool(api, kind=kind)
    weld = add_weld(api, item_id)
    item = ok(api.get('/api/items/' + item_id))
    assert item['receiving']['required'] and item['receiving']['status'] == 'pending'
    assert not item['permissions']['can_weld'] and not item['permissions']['can_release']
    current = ok(api.get('/api/tracking/welds/' + weld['id']))
    assert current['allowed_operations'] == []
    blocked_without_changes(api, '/api/tracking/welds/' + weld['id'] + '/work',
                            {'operation': 'fitup', 'notes': 'Should be rejected before any work'}, role='welder')
    blocked_without_changes(api, f'/api/tracking/spools/{item_id}/process',
                            {'action': 'start', 'process_key': 'welding', 'expected_version': 0}, role='welder')


def test_untracked_physical_spool_cannot_use_legacy_aggregate_weld_entry(api):
    item_id = pending_spool(api, tracked=False)
    blocked_without_changes(api, f'/api/items/{item_id}/weld',
                            {'count': 1, 'weld_ids': 'SYNTHETIC-W01'}, role='welder')


@pytest.mark.parametrize('step', [9, 14, 15])
def test_pending_arrival_blocks_traveler_start_including_late_baselines_without_timer_or_flow_events(api, step):
    item_id = pending_spool(api, planned=0)
    blocked_without_changes(api, f'/api/flow/items/{item_id}/start', {
        'route': 'spool', 'start_step': step, 'expected_children': 0,
        'material_reference': 'SYNTHETIC-LEGACY-KIT-REFERENCE',
        'baseline_reference': 'SYNTHETIC-BASELINE',
        'baseline_reason': 'A baseline cannot replace the actual arrival decision',
    }, role='supervisor')


def test_arrival_is_not_overridden_by_ordinary_or_administrative_release(api):
    item_id = pending_spool(api, planned=0)
    blocked_without_changes(api, f'/api/items/{item_id}/release',
                            {'reference': 'SYNTHETIC-FINAL-QA'}, role='inspector')
    body = disposition_body(api, item_id)
    blocked_without_changes(api, f'/api/admin/items/{item_id}/release', body)
    assert 'release_override' not in ok(api.get(f'/api/admin/items/{item_id}'))['allowed_actions']


def test_arrival_pending_keeps_identity_qr_and_corrective_recording_available_but_blocks_rework_completion(api, monkeypatch):
    item_id = pending_spool(api, tracked=False)
    monkeypatch.setattr(api.application, 'PUBLIC_BASE_URL', 'https://fabtrace.example.invalid')
    assert api.get(f'/api/items/{item_id}/qr.png').status_code == 200
    record = ok(api.post(f'/api/items/{item_id}/rework', {
        'kind': 'Arrival correction', 'reason': 'Synthetic material damage needs correction',
        'assigned': BADGES['handler'],
    }, role='inspector'), 201)
    rework_id = record['reworks'][0]['id']
    assert not record['reworks'][0]['can_close']
    blocked_without_changes(api, f'/api/items/{item_id}/rework/{rework_id}/close',
                            {'notes': 'Cannot claim correction completed before arrival acceptance'}, role='supervisor')
    assert api.get(f'/api/items/{item_id}/audit', role='inspector').status_code == 200


def test_arrival_pending_propagates_to_assembly_work_and_current_progress(api):
    assembly = pending_spool(api, 'ARRIVAL-ASSEMBLY', kind='Assembly', planned=0)
    spool_id = pending_spool(api, 'ARRIVAL-CHILD', planned=0, assembly_id=assembly)
    blocked_without_changes(api, f'/api/flow/items/{assembly}/start', {
        'route': 'assembly', 'expected_children': 1,
    }, role='supervisor')
    blocked_without_changes(api, f'/api/admin/items/{assembly}/release', disposition_body(api, assembly))
    report = ok(api.get('/api/progress/projects/' + PROJECT))
    rows = {row['id']: row for row in report['items']}
    for item_id in (spool_id, assembly):
        assert not rows[item_id]['fabrication_finished']
        assert any('arrival' in value.lower() or 'receiving' in value.lower()
                   for value in rows[item_id]['blockers'])
        assert not rows[item_id]['receiving']['can_proceed']


def test_component_receipt_route_remains_available_for_genuine_untracked_parts(api):
    component_id = pending_spool(api, 'ARRIVAL-COMPONENT', tracked=False, kind='Part', planned=0)
    item = ok(api.get('/api/items/' + component_id))
    assert not item['receiving']['required']
    current = ok(api.post(f'/api/flow/items/{component_id}/start', {'route': 'component'}, role='supervisor'), 201)
    assert current['flow']['current_step'] == 1
    assert current['production_process']['status'] == 'running'


def test_arrival_fail_pauses_work_and_blocks_resume_move_and_further_welding_until_new_pass(api):
    item_id = pending_spool(api)
    weld = add_weld(api, item_id)
    accept_arrival(api, item_id)
    route = f'/api/tracking/spools/{item_id}/process'
    started = ok(api.post(route, {'action': 'start', 'process_key': 'welding', 'expected_version': 0}, role='welder'), 201)
    assert started['status'] == 'running'
    ok(api.post('/api/tracking/welds/' + weld['id'] + '/work', {'operation': 'fitup'}, role='welder'))
    failed = ok(record_arrival(api, item_id, result='Fail'), 201)
    assert failed['arrival']['status'] == 'failed'
    paused = ok(api.get(route, role='welder'))
    assert paused['status'] == 'paused' and paused['events'][-1]['event'] == 'pause'
    assert 'finish' in paused['permissions']['allowed_actions']
    assert 'resume' not in paused['permissions']['allowed_actions']
    for action in ('resume', 'move'):
        body = {'action': action, 'expected_version': paused['version']}
        if action == 'move':
            body['process_key'] = 'fit_up'
        blocked_without_changes(api, route, body, role='welder')
    blocked_without_changes(api, '/api/tracking/welds/' + weld['id'] + '/work',
                            {'operation': 'root'}, role='welder')
    passed = ok(record_arrival(api, item_id), 201)
    assert passed['arrival']['status'] == 'passed'
    assert [row['result'] for row in passed['arrival']['history']] == ['Pass', 'Fail', 'Pass']
    assert ok(api.get(route))['status'] == 'paused', 'A QA Pass does not silently resume physical work'
    resumed = ok(api.post(route, {'action': 'resume', 'expected_version': paused['version']}, role='welder'), 201)
    assert resumed['status'] == 'running'


def test_material_change_stales_arrival_and_pauses_both_spool_and_parent_without_changing_old_decision(api):
    assembly = pending_spool(api, 'ARRIVAL-PARENT', kind='Assembly', planned=0)
    item_id = pending_spool(api, 'ARRIVAL-MATERIAL', planned=0, assembly_id=assembly)
    passed = accept_arrival(api, item_id)['arrival']['latest']
    ok(api.post(f'/api/flow/items/{item_id}/start', {
        'route': 'spool', 'expected_children': 0, 'material_reference': 'SYNTHETIC-KIT',
    }, role='supervisor'), 201)
    ok(api.post(f'/api/flow/items/{assembly}/start', {
        'route': 'assembly', 'expected_children': 1,
    }, role='supervisor'), 201)
    changed = save_receiving_materials(api, item_id, heat='CORRECTED-SYNTHETIC-HEAT')
    assert changed['arrival']['status'] == 'needs_reinspection'
    assert changed['arrival']['latest'] == passed
    for identifier in (item_id, assembly):
        clock = ok(api.get(f'/api/tracking/spools/{identifier}/process'))
        assert clock['status'] == 'paused'
        assert clock['events'][-1]['event'] == 'pause'
        blocked_without_changes(api, f'/api/tracking/spools/{identifier}/process',
                                {'action': 'resume', 'expected_version': clock['version']})


def test_corrective_fail_changes_step_without_starting_work_and_later_explicit_resume_uses_correct_step(api):
    item_id = pending_spool(api, planned=0)
    accept_arrival(api, item_id)
    ok(api.post(f'/api/flow/items/{item_id}/start', {
        'route': 'spool', 'start_step': 11, 'expected_children': 0,
        'material_reference': 'SYNTHETIC-KIT', 'baseline_reference': 'SYNTHETIC-BASELINE',
        'baseline_reason': 'Retained synthetic fit-up position for corrective routing',
    }, role='supervisor'), 201)
    ok(record_arrival(api, item_id, result='Fail'), 201)
    detail = ok(api.get(f'/api/flow/items/{item_id}'))
    corrected = ok(api.post(f'/api/flow/items/{item_id}/fail', {
        'expected_version': detail['flow']['version'], 'return_step': 10,
        'reason': 'Synthetic dimensional correction while arrival is blocked',
        'reference': 'SYNTHETIC-EXCEPTION',
    }, role='inspector'))
    assert corrected['flow']['current_step'] == 10
    assert corrected['production_process']['current'] is None
    assert corrected['production_process']['status'] == 'finished'
    assert corrected['production_process']['events'][-1]['event'] == 'finish'
    ok(record_arrival(api, item_id), 201)
    route = f'/api/tracking/spools/{item_id}/process'
    clock = ok(api.get(route, role='welder'))
    assert clock['permissions']['allowed_actions'] == ['resume']
    resumed = ok(api.post(route, {'action': 'resume', 'expected_version': clock['version']}, role='welder'), 201)
    assert resumed['current']['process_key'] == 'clm_10'
    assert resumed['current']['active_seconds'] >= 0


def test_stale_arrival_blocks_flow_advance_before_any_confirmation_or_timer_is_saved(api):
    from test_flow import action_body
    item_id = pending_spool(api, planned=0)
    accept_arrival(api, item_id)
    ok(api.post(f'/api/flow/items/{item_id}/start', {
        'route': 'spool', 'start_step': 14, 'expected_children': 0,
        'material_reference': 'SYNTHETIC-KIT', 'baseline_reference': 'SYNTHETIC-BASELINE',
        'baseline_reason': 'Retained synthetic late position for gate verification',
    }, role='supervisor'), 201)
    body = action_body(api, item_id)
    save_receiving_materials(api, item_id, reference='CORRECTED-SYNTHETIC-MTR')
    blocked_without_changes(api, f'/api/flow/items/{item_id}/advance', body, role='welder')


def test_spool_detail_receiving_queries_do_not_grow_with_each_weld(api):
    item_id = pending_spool(api, planned=8)
    add_weld(api, item_id, 'W01')
    engine = api.session_factory.kw['bind']

    def count_material_reads():
        statements = []
        def record(_connection, _cursor, statement, _parameters, _context, _many):
            if 'spool_bom_materials' in statement.lower() or 'spool_mtr_documents' in statement.lower():
                statements.append(statement)
        event.listen(engine, 'before_cursor_execute', record)
        try:
            ok(api.get('/api/tracking/spools/' + item_id))
        finally:
            event.remove(engine, 'before_cursor_execute', record)
        return len(statements)

    small = count_material_reads()
    for number in range(2, 9):
        add_weld(api, item_id, f'W{number:02d}')
    large = count_material_reads()
    assert small > 0
    assert large <= small + 2, (small, large)


def test_controlled_initial_assembly_collection_preserves_physical_receipt_and_rejects_reparenting(api):
    from test_flow import create_item, enroll, link_spool, detail, advance, inspect_dimensions, PROJECT as flow_project
    from test_spool_receiving import upload_mtr
    parent = create_item(api, 'ARRIVAL-COLLECTION-PARENT', kind='Assembly')
    enroll(api, parent, 'assembly', expected_children=1)
    child = create_item(api, 'ARRIVAL-COLLECTION-CHILD', kind='Spool')
    mtr = ok(upload_mtr(api, child), 201)['mtr_documents']['current'][0]
    original_mtr = api.get(mtr['view_url']).content
    enroll(api, child, 'spool', start_step=15)
    inspect_dimensions(api, child)
    advance(api, child, role='inspector')
    advance(api, child)
    before = receiving_detail(api, child)
    assert before['arrival']['can_proceed']
    original_source = before['source_status']
    linked = link_spool(api, parent, child)
    after = receiving_detail(api, child)
    assert after['arrival']['can_proceed']
    assert after['arrival']['basis_sha256'] == before['arrival']['basis_sha256']
    assert after['arrival']['latest'] == before['arrival']['latest']
    assert after['traceability'] == before['traceability']
    assert after['source_status'] == original_source
    assert api.get(original_source['current']['download_url']).status_code == 200
    assert api.get(mtr['view_url']).content == original_mtr
    assert linked['receiving']['can_proceed']
    other = create_item(api, 'ARRIVAL-COLLECTION-OTHER', kind='Assembly', project=flow_project)
    enroll(api, other, 'assembly', expected_children=1)
    current = detail(api, other)
    snapshot = database_state(api)
    response = api.post(f'/api/flow/items/{other}/link-spool', {
        'expected_version': current['flow']['version'], 'spool_id': child,
        'reference': 'Reparenting is not an initial collection',
    })
    assert response.status_code == 409
    assert database_state(api) == snapshot
