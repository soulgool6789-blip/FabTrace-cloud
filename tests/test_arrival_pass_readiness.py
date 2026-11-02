"""A selectable arrival decision stays distinct from its evidence prerequisites."""
from copy import deepcopy

from receiving_helpers import (CHECKS, accept_arrival, approve_materials,
    receiving_detail, record_arrival, save_receiving_materials, upload_receiving_bom)
from test_progress import database_state
from test_removal_orders import change
from test_spool_receiving import create_spool
from tracking_helpers import ok


def ready_spool(api):
    item_id = create_spool(api)
    upload_receiving_bom(api, item_id, quantity=2)
    save_receiving_materials(api, item_id)
    approve_materials(api, item_id)
    return item_id


def pass_payload(detail, **changes):
    arrival = detail['arrival']
    return {'expected_version': arrival['version'], 'basis_sha256': arrival['basis_sha256'],
        'result': 'Pass', 'reference': '', 'notes': '', 'checks': dict(CHECKS), **changes}


def assert_pass_rejected_without_writes(api, item_id, detail):
    before = database_state(api)
    response = api.post('/api/spool-boms/spools/' + item_id + '/arrival-inspections',
        pass_payload(detail), role='inspector')
    assert response.status_code == 409
    assert response.json()['detail']['receiving_blockers'] == detail['arrival']['pass_blockers']
    assert database_state(api) == before


def test_pending_ready_spool_can_be_inspected_but_still_requires_role_and_checklist(api):
    item_id = ready_spool(api)
    before = database_state(api)
    detail = receiving_detail(api, item_id)
    arrival = detail['arrival']
    assert arrival['status'] == 'pending' and not arrival['can_proceed']
    assert arrival['latest'] is None and arrival['pass_blockers'] == []
    assert arrival['blockers'] == ['QA/QC arrival inspection has not been recorded.']
    assert arrival['permissions']['can_inspect']
    handler = ok(api.get('/api/spool-boms/spools/' + item_id, role='handler'))
    assert handler['arrival']['pass_blockers'] == []
    assert not handler['arrival']['permissions']['can_inspect']
    path = '/api/spool-boms/spools/' + item_id + '/arrival-inspections'
    assert api.post(path, pass_payload(detail), role='handler').status_code == 403
    assert api.post(path, pass_payload(detail), role=None).status_code == 401
    incomplete = api.post(path, pass_payload(detail, checks={**CHECKS, 'condition': False}), role='inspector')
    assert incomplete.status_code == 409
    assert incomplete.json()['detail']['receiving_blockers'] == [
        'Confirm every arrival inspection check before recording Pass.']
    assert database_state(api) == before
    accepted = ok(api.post(path, pass_payload(detail), role='inspector'), 201)
    assert accepted['arrival']['can_proceed'] and accepted['arrival']['pass_blockers'] == []
    assert accepted['arrival']['latest']['result'] == 'Pass'
    assert accepted['arrival']['latest']['reference'] == accepted['arrival']['latest']['notes'] == ''


def test_previous_fail_is_history_not_a_prerequisite_for_the_next_pass(api):
    item_id = ready_spool(api)
    failed = ok(record_arrival(api, item_id, result='Fail'), 201)
    assert failed['arrival']['status'] == 'failed' and not failed['arrival']['can_proceed']
    assert failed['arrival']['pass_blockers'] == []
    assert 'arrival inspection failed' in failed['arrival']['blockers'][0]
    accepted = ok(record_arrival(api, item_id), 201)
    assert accepted['arrival']['can_proceed'] and accepted['arrival']['pass_blockers'] == []
    assert [row['result'] for row in accepted['arrival']['history']] == ['Pass', 'Fail']
    assert accepted['arrival']['history'][1] == failed['arrival']['latest']


def test_stale_arrival_is_ready_after_affected_piece_evidence_is_reinspected(api):
    item_id = create_spool(api)
    accepted = accept_arrival(api, item_id)
    changed = save_receiving_materials(api, item_id, heat='VERIFIED-NEW-HEAT')
    assert changed['arrival']['status'] == 'needs_reinspection'
    assert any('current QA-001 Pass' in message for message in changed['arrival']['pass_blockers'])
    assert_pass_rejected_without_writes(api, item_id, changed)
    reviewed = approve_materials(api, item_id)
    assert reviewed['arrival']['status'] == 'needs_reinspection'
    assert reviewed['arrival']['latest'] == accepted['arrival']['latest']
    assert reviewed['arrival']['pass_blockers'] == []
    assert reviewed['arrival']['basis_sha256'] != accepted['arrival']['basis_sha256']
    reinspection = ok(record_arrival(api, item_id), 201)
    assert reinspection['arrival']['can_proceed']
    assert [row['result'] for row in reinspection['arrival']['history']] == ['Pass', 'Pass']


def test_missing_bom_heat_mtr_and_piece_qa_remain_authoritative_pass_blockers(api):
    item_id = create_spool(api)
    missing = receiving_detail(api, item_id)
    blockers = missing['arrival']['pass_blockers']
    assert any('structured BOM' in message for message in blockers)
    assert any('Save the material register' in message for message in blockers)
    assert any('physical material-piece register' in message for message in blockers)
    assert 'QA/QC arrival inspection has not been recorded.' not in blockers
    assert_pass_rejected_without_writes(api, item_id, missing)
    upload_receiving_bom(api, item_id)
    for heat, reference in [('', 'MTR-LOCAL-1'), ('HEAT-LOCAL-1', '')]:
        incomplete = save_receiving_materials(api, item_id, heat=heat, reference=reference)
        blockers = incomplete['arrival']['pass_blockers']
        assert any('Heat number and MTR reference are required' in message for message in blockers)
        assert any('current QA-001 Pass' in message for message in blockers)
        assert_pass_rejected_without_writes(api, item_id, incomplete)
    completed = save_receiving_materials(api, item_id)
    assert completed['traceability']['complete']
    assert len(completed['arrival']['pass_blockers']) == 1
    assert 'current QA-001 Pass' in completed['arrival']['pass_blockers'][0]
    assert_pass_rejected_without_writes(api, item_id, completed)
    approved = approve_materials(api, item_id)
    assert approved['arrival']['pass_blockers'] == []
    assert approved['arrival']['latest'] is None and not approved['arrival']['can_proceed']


def test_changed_bom_keeps_adoption_and_current_piece_qa_prerequisites(api):
    item_id = create_spool(api)
    accepted = accept_arrival(api, item_id)
    upload_receiving_bom(api, item_id, quantity=2, part='REPLACEMENT')
    changed = receiving_detail(api, item_id)
    assert changed['source_status']['changed']
    assert changed['arrival']['latest'] == accepted['arrival']['latest']
    assert any('Adopt and review' in message for message in changed['arrival']['pass_blockers'])
    assert any('current QA-001 Pass' in message for message in changed['arrival']['pass_blockers'])
    assert_pass_rejected_without_writes(api, item_id, changed)


def test_readiness_lists_do_not_mutate_basis_or_cached_sibling_responses(api):
    from main import Item
    from read_projection import read_projection
    from spool_receiving import _basis, _physical_summary

    item_id = create_spool(api)
    before = database_state(api)
    with api.session_factory() as session:
        item = session.get(Item, item_id)
        with read_projection(session):
            evidence, prerequisites = _basis(session, item)
            original = deepcopy(prerequisites)
            summary = _physical_summary(session, item, 'inspector')
            assert summary['pass_blockers'] == original
            assert summary['blockers'] == ['QA/QC arrival inspection has not been recorded.'] + original
            summary['pass_blockers'].append('Caller-local readiness note')
            assert 'Caller-local readiness note' not in summary['blockers']
            summary['blockers'].append('Caller-local status note')
            again = _physical_summary(session, item, 'inspector')
            assert again['pass_blockers'] == original
            assert again['blockers'] == ['QA/QC arrival inspection has not been recorded.'] + original
            assert _basis(session, item) == (evidence, original)
    assert database_state(api) == before


def test_removed_spool_has_a_readiness_blocker_without_reviving_acceptance(api):
    item_id = create_spool(api)
    accepted = accept_arrival(api, item_id)
    change(api, 'item', item_id)
    before = database_state(api)
    retained = ok(api.get('/api/items/' + item_id))['receiving']
    assert retained['status'] == 'removed'
    assert retained['pass_blockers'] == retained['blockers'] and retained['pass_blockers']
    assert not retained['permissions']['can_inspect'] and not retained['can_proceed']
    assert retained['latest'] == accepted['arrival']['latest']
    assert database_state(api) == before
