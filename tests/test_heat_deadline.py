"""Heat/MTR may be recorded after fabrication, but not waived at acceptance.

Every normal fixture uses the public BOM, material QA, arrival, weld and traveler
APIs. Blocked operations are checked against all persisted records and audit.
"""
import importlib

import pytest
from sqlalchemy import select

from conftest import BADGES
from receiving_helpers import (
    approve_materials, receiving_detail, save_receiving_materials, upload_receiving_bom,
)
from test_admin import disposition_body
from test_flow import (
    ROOT as FLOW, PROJECT, action_body, advance, completed_spool, create_item,
    detail as flow_detail, enroll, inspect_dimensions, link_spool,
)
from test_progress import database_state
from tracking_helpers import (
    accept_weld, add_weld, approve, find_requirement, ok, ready_to_weld,
    review, submit, weld as weld_detail,
)


def record_current_arrival(api, item_id):
    current = receiving_detail(api, item_id)
    return ok(api.post(f'/api/spool-boms/spools/{item_id}/arrival-inspections', {
        'expected_version': current['arrival']['version'],
        'basis_sha256': current['arrival']['basis_sha256'],
        'result': 'Pass', 'reference': 'TEST-HEAT-TIMING-RECEIPT',
        'notes': 'Actual available evidence reviewed; deferred heat/MTR is not certified.',
        'checks': {check['key']: True for check in current['arrival']['checks_catalog']},
    }, role='inspector'), 201)


def receive(api, item_id, *, heat='', reference='TEST-CURRENT-MTR'):
    current = receiving_detail(api, item_id)
    if not current['bom_available']:
        upload_receiving_bom(api, item_id)
    current = receiving_detail(api, item_id)
    if any(row['heat_number'] != heat or row['mtr_reference'] != reference
           for row in current['traceability']['materials']):
        save_receiving_materials(api, item_id, heat=heat, reference=reference)
    approve_materials(api, item_id)
    return record_current_arrival(api, item_id)


def blocked(api, path, body, *, role='admin', expected='heat'):
    before = database_state(api)
    response = api.post(path, body, role=role)
    assert response.status_code == 409, response.text
    assert expected.lower() in response.text.lower(), response.text
    assert database_state(api) == before
    return response


def finish_weld(api, weld_id):
    for operation in ('root', 'fill_cap', 'complete'):
        ok(api.post(f'/api/tracking/welds/{weld_id}/work', {
            'operation': operation, 'notes': 'Actual synthetic fabrication operation',
        }, role='welder'))


def fill_weld_heats(api, item_id, weld_id, *, with_mtrs=False):
    current = weld_detail(api, item_id, weld_id)
    return ok(api.patch(f'/api/tracking/welds/{weld_id}', {
        'expected_version': current['version'], 'heat_a': 'TEST-LATE-HEAT-A',
        'heat_b': 'TEST-LATE-HEAT-B',
        **({'mtr_a': 'TEST-LATE-MTR-A', 'mtr_b': 'TEST-LATE-MTR-B'} if with_mtrs else {}),
        'change_reason': 'Record the actual heat/MTR evidence after fabrication',
    }, role='supervisor'))


def test_blank_heat_and_mtr_allow_fabrication_through_step14_but_qa003_needs_fresh_complete_evidence(api):
    item_id = create_item(api, 'HEAT-FABRICATION', kind='Spool', planned=1)
    accepted = receive(api, item_id, reference='')
    assert accepted['arrival']['can_proceed']
    assert accepted['arrival']['latest']['checks']['heat_numbers'] is False
    assert accepted['arrival']['latest']['checks']['mtrs'] is False
    record = add_weld(api, item_id, heat_a='', heat_b='', mtr_a='', mtr_b='')
    enroll(api, item_id, 'spool', start_step=10)
    ready_to_weld(api, item_id, record['id'])
    for step in (11, 12, 13, 14):
        assert advance(api, item_id)['flow']['current_step'] == step
    finish_weld(api, record['id'])
    completed = weld_detail(api, item_id, record['id'])
    assert completed['production_complete'] and not completed['qa_accepted']
    at_qa = advance(api, item_id, role='welder')
    assert at_qa['flow']['current_step'] == 15
    assert ok(api.get(f'/api/items/{item_id}'))['welds_done'] == 1
    assert at_qa['receiving']['can_proceed']
    assert at_qa['production_process']['current']['process_key'] == 'clm_15'
    response = blocked(api, f'{FLOW}/items/{item_id}/advance', action_body(api, item_id), role='inspector')
    assert 'MTR' in response.text

    visual = find_requirement(api, item_id, record['id'], code='VT')
    submitted = submit(api, item_id, visual['id'])
    blocked(api, f"/api/tracking/requirements/{visual['id']}/review", {
        'expected_version': submitted['version'], 'decision': 'accepted',
        'notes': 'Post-fabrication acceptance still needs the actual heat numbers',
    }, role='inspector')
    nde = find_requirement(api, item_id, record['id'], code='NDE_PLAN')
    blocked(api, f"/api/tracking/requirements/{nde['id']}/review", {
        'expected_version': nde['version'], 'decision': 'not_applicable',
        'notes': 'Non-applicability of a test cannot waive heat traceability',
    }, role='inspector')
    rejected = ok(review(api, item_id, visual['id'], decision='rejected'))
    assert rejected['status'] == 'rejected', 'Corrective QA remains available without heat'

    # Entering real heat/MTR data preserves work but changes the inspected evidence.
    material = save_receiving_materials(api, item_id, heat='TEST-LATE-BOM-HEAT',
                                       reference='TEST-CURRENT-MTR')
    assert material['arrival']['status'] == 'needs_reinspection'
    assert all(not row['qa001']['can_proceed'] for row in material['traceability']['materials'])
    updated = fill_weld_heats(api, item_id, record['id'], with_mtrs=True)
    assert updated['cycle'] == completed['cycle']
    assert updated['completed_at'] == completed['completed_at']
    assert updated['work'] == completed['work']
    assert updated['production_complete']
    assert any(row['status'] == 'pending' for row in updated['requirements'])
    approve_materials(api, item_id)
    record_current_arrival(api, item_id)
    accept_weld(api, item_id, record['id'])
    inspect_dimensions(api, item_id)
    released = advance(api, item_id, role='inspector')
    assert released['flow']['current_step'] == 16 and released['item']['released']
    assert weld_detail(api, item_id, record['id'])['work'] == completed['work']


@pytest.mark.parametrize('field,check,label', [
    ('component_b', 'materials', 'Component B piece / lot identity'),
    ('wps_revision', 'procedure', 'WPS revision'),
])
def test_component_identity_and_wps_still_gate_before_welding_when_heat_and_mtr_are_deferred(api, field, check, label):
    item_id = create_item(api, 'TRACEABILITY-EARLY-CONTROLS', kind='Spool', planned=1)
    receive(api, item_id, reference='')
    record = add_weld(api, item_id, heat_a='', heat_b='', mtr_a='', mtr_b='', **{field: ''})
    ok(api.post(f"/api/tracking/welds/{record['id']}/work", {'operation': 'fitup'}, role='welder'))
    material = find_requirement(api, item_id, record['id'], check=check)
    current = submit(api, item_id, material['id'])
    response = blocked(api, f"/api/tracking/requirements/{material['id']}/review", {
        'expected_version': current['version'], 'decision': 'accepted',
        'notes': 'Component identity and WPS remain required before fabrication',
    }, role='inspector', expected=label)
    assert label + ' missing' in response.text
    assert 'MTR reference missing' not in response.text and 'heat missing' not in response.text
    blocked(api, f"/api/tracking/welds/{record['id']}/work",
            {'operation': 'root'}, role='welder', expected=label)


@pytest.mark.parametrize('missing', ['heat', 'MTR'])
def test_custom_post_weld_control_and_filtered_release_cannot_waive_heat_or_mtr(api, missing):
    item_id = create_item(api, 'HEAT-CUSTOM-REVIEW', kind='Spool', planned=1)
    receive(api, item_id, heat='TEST-BOM-HEAT')
    record = add_weld(api, item_id, **({'heat_a': '', 'heat_b': ''} if missing == 'heat'
                                     else {'mtr_a': '', 'mtr_b': ''}))
    ready_to_weld(api, item_id, record['id'])
    finish_weld(api, record['id'])
    custom = ok(api.post(f"/api/tracking/welds/{record['id']}/requirements", {
        'code': 'CUSTOM-POST', 'label': 'Project post-fabrication review',
        'stage': 'after_welding', 'check': 'none', 'allow_na': True,
        'evidence_required': False, 'source': 'Synthetic project requirement',
    }), 201)
    for decision in ('accepted', 'not_applicable'):
        blocked(api, f"/api/tracking/requirements/{custom['id']}/review", {
            'expected_version': custom['version'], 'decision': decision,
            'notes': 'A custom checklist cannot waive the heat/MTR deadline',
        }, role='inspector', expected=missing)
    tracking = importlib.import_module('tracking')
    with api.session_factory() as session:
        row = session.get(tracking.Weld, record['id'])
        errors = tracking._weld_blockers(session, row, include_production=False, requirement_stages=())
        assert errors and all(missing in message for message in errors)
    fill_weld_heats(api, item_id, record['id'], with_mtrs=missing == 'MTR')
    current = next(row for row in weld_detail(api, item_id, record['id'])['requirements']
                   if row['id'] == custom['id'])
    ok(api.post(f"/api/tracking/requirements/{custom['id']}/review", {
        'expected_version': current['version'], 'decision': 'not_applicable',
        'notes': 'Actual heat/MTR entered; authorized project non-applicability remains usable',
    }, role='inspector'))


@pytest.mark.parametrize('missing', ['heat', 'MTR'])
def test_legacy_weld_pass_and_release_require_heat_and_mtr_but_fail_and_work_remain_available(api, missing):
    item_id = api.item('HEAT-LEGACY', kind='Spool')['id']
    receive(api, item_id, heat='' if missing == 'heat' else 'TEST-AVAILABLE-HEAT',
            reference='TEST-CURRENT-MTR' if missing == 'heat' else '')
    ok(api.post(f'/api/items/{item_id}/weld', {
        'count': 1, 'weld_ids': 'LEGACY-W01', 'notes': 'Fabrication before heat registration',
    }, role='welder'))
    inspect_dimensions(api, item_id)
    inspection = {'kind': 'Weld', 'result': 'Pass', 'report': 'TEST-POST-FABRICATION',
                  'measurements': 'Actual post-fabrication weld inspection'}
    blocked(api, f'/api/items/{item_id}/inspect', inspection, role='inspector', expected=missing)
    failed = ok(api.post(f'/api/items/{item_id}/inspect', {
        **inspection, 'result': 'Fail',
    }, role='inspector'))
    assert failed['weld'] == 'Fail'
    blocked(api, f'/api/items/{item_id}/release', {'reference': 'TEST-ORDINARY-RELEASE'},
            role='inspector', expected=missing)
    admin = ok(api.get(f'/api/admin/items/{item_id}'))
    assert 'release_override' not in admin['allowed_actions']
    blocked(api, f'/api/admin/items/{item_id}/release', disposition_body(api, item_id), expected=missing)
    receive(api, item_id, heat='TEST-LEGACY-LATE-HEAT')
    rework = next(row for row in failed['reworks'] if row['closed_at'] is None)
    ok(api.post(f"/api/items/{item_id}/rework/{rework['id']}/close", {
        'notes': 'Actual correction complete; fresh inspection follows',
    }, role='supervisor'))
    inspect_dimensions(api, item_id)
    ok(api.post(f'/api/items/{item_id}/inspect', inspection, role='inspector'))
    released = ok(api.post(f'/api/items/{item_id}/release', {
        'reference': 'TEST-CURRENT-ORDINARY-RELEASE',
    }, role='inspector'))
    assert released['released']


@pytest.mark.parametrize('missing', ['heat', 'MTR'])
def test_zero_weld_spool_still_needs_bom_piece_heat_and_mtr_at_qa003(api, missing):
    item_id = create_item(api, 'HEAT-ZERO-WELD', kind='Spool', planned=0)
    receive(api, item_id, heat='' if missing == 'heat' else 'TEST-AVAILABLE-HEAT',
            reference='TEST-CURRENT-MTR' if missing == 'heat' else '')
    enroll(api, item_id, 'spool', start_step=14)
    assert advance(api, item_id)['flow']['current_step'] == 15
    inspect_dimensions(api, item_id)
    blocked(api, f'{FLOW}/items/{item_id}/advance', action_body(api, item_id), role='inspector', expected=missing)
    report = ok(api.get('/api/progress/projects/' + PROJECT))
    row = next(value for value in report['items'] if value['id'] == item_id)
    assert row['receiving']['can_proceed'] and not row['fabrication_finished']
    assert any(missing.lower() in reason.lower() for reason in row['blockers'])
    receive(api, item_id, heat='TEST-ZERO-WELD-HEAT')
    assert advance(api, item_id, role='inspector')['item']['released']


@pytest.mark.parametrize('missing', ['heat', 'MTR'])
def test_downstream_timers_need_heat_and_mtr_but_fabrication_and_finish_do_not(api, missing):
    item_id = create_item(api, 'HEAT-MANUAL-TIMER', kind='Spool', planned=0)
    deferred = {'heat': '' if missing == 'heat' else 'TEST-AVAILABLE-HEAT',
                'reference': 'TEST-CURRENT-MTR' if missing == 'heat' else ''}
    receive(api, item_id, **deferred)
    path = f'/api/tracking/spools/{item_id}/process'
    current = ok(api.get(path))
    allowed = {row['key'] for row in current['permissions']['allowed_processes']}
    assert {'material_prep', 'cutting_beveling', 'fit_up', 'welding', 'dimensional'} <= allowed
    for key in ('nde', 'pwht', 'coating', 'final_qa', 'dispatch'):
        assert key not in allowed
        blocked(api, path, {'action': 'start', 'process_key': key, 'expected_version': 0}, expected=missing)
    welding = ok(api.post(path, {'action': 'start', 'process_key': 'welding',
                                'expected_version': 0}), 201)
    blocked(api, path, {'action': 'move', 'process_key': 'nde',
                       'expected_version': welding['version']}, expected=missing)
    finished = ok(api.post(path, {'action': 'finish', 'expected_version': welding['version']}), 201)
    assert finished['status'] == 'finished'
    dimension = ok(api.post(path, {'action': 'start', 'process_key': 'dimensional',
                                  'expected_version': finished['version']}), 201)
    finished = ok(api.post(path, {'action': 'finish', 'expected_version': dimension['version']}), 201)
    receive(api, item_id, heat='TEST-TIMER-HEAT')
    testing = ok(api.post(path, {'action': 'start', 'process_key': 'nde',
                                'expected_version': finished['version']}), 201)
    assert testing['status'] == 'running'
    receive(api, item_id, **deferred)
    paused = ok(api.get(path))
    assert paused['status'] == 'paused'
    assert 'resume' not in paused['permissions']['allowed_actions']
    assert not paused['receiving_blockers'] and paused['heat_blockers']
    blocked(api, path, {'action': 'resume', 'expected_version': paused['version']}, expected=missing)
    assert ok(api.post(path, {'action': 'finish', 'expected_version': paused['version']}), 201)['status'] == 'finished'


@pytest.mark.parametrize('missing', ['heat', 'MTR'])
def test_assembly_work_at17_can_defer_heat_and_mtr_but_release_to_testing_cannot(api, missing):
    assembly = create_item(api, 'HEAT-ASSEMBLY', kind='Assembly', planned=1)
    child = completed_spool(api, 'HEAT-ASSEMBLY-CHILD')
    record = add_weld(api, assembly, **({'heat_a': '', 'heat_b': ''} if missing == 'heat'
                                      else {'mtr_a': '', 'mtr_b': ''}))
    enroll(api, assembly, 'assembly', expected_children=1)
    link_spool(api, assembly, child)
    ready_to_weld(api, assembly, record['id'])
    finish_weld(api, record['id'])
    assert weld_detail(api, assembly, record['id'])['production_complete']
    blocked(api, f'{FLOW}/items/{assembly}/advance', action_body(api, assembly), expected=missing)
    fill_weld_heats(api, assembly, record['id'], with_mtrs=missing == 'MTR')
    accept_weld(api, assembly, record['id'])
    advanced = advance(api, assembly)
    assert advanced['flow']['current_step'] == 18


@pytest.mark.parametrize('start_step', [18, 20])
def test_late_assembly_baseline_cannot_skip_post_fabrication_heat_gate(api, start_step):
    assembly = create_item(api, 'HEAT-LATE-ASSEMBLY', kind='Assembly', planned=1)
    add_weld(api, assembly, heat_a='', heat_b='')
    blocked(api, f'{FLOW}/items/{assembly}/start', {
        'route': 'assembly', 'start_step': start_step, 'expected_children': 1,
        'baseline_reference': 'TEST-LATE-BASELINE',
        'baseline_reason': 'A baseline does not replace missing material heat records',
    })


@pytest.mark.parametrize('field,label', [('heat_number', 'heat'), ('mtr_reference', 'MTR')])
def test_active_child_heat_and_mtr_are_rechecked_at_assembly_testing_and_admin_release(api, field, label):
    assembly = create_item(api, 'HEAT-CHILD-SCOPE', kind='Assembly', planned=0)
    child = completed_spool(api, 'HEAT-CHILD-RETAINED')
    enroll(api, assembly, 'assembly', expected_children=1)
    link_spool(api, assembly, child)
    # Model a retained incomplete traceability record. No old approval is rewritten.
    boms = importlib.import_module('spool_boms')
    with api.session_factory() as session:
        piece = session.scalar(select(boms.SpoolBomMaterial).where(boms.SpoolBomMaterial.spool_id == child))
        setattr(piece, field, '')
        session.commit()
    tracking = importlib.import_module('tracking')
    with api.session_factory() as session:
        parent = session.get(api.application.Item, assembly)
        assert tracking.post_fabrication_heat_errors(session, parent, include_children=False) == []
        errors = tracking.post_fabrication_heat_errors(session, parent)
        assert any(child in message and label in message for message in errors)
    response = blocked(api, f'{FLOW}/items/{assembly}/advance', action_body(api, assembly), expected=label)
    assert child in response.text
    blocked(api, f'/api/admin/items/{assembly}/release', disposition_body(api, assembly), expected=label)
