"""Atomic QA-001 Pass All and evidence-guarded single-piece material edits."""
from copy import deepcopy

import pytest

from conftest import BADGES
from receiving_helpers import (accept_arrival, receiving_detail, save_receiving_materials,
                               upload_receiving_bom)
from test_material_piece_qa import decide, edit_piece
from test_order_labels import public_qr_url
from test_progress import database_state
from test_spool_receiving import create_spool, upload_mtr
from tracking_helpers import ok


def pass_all_body(detail):
    return {'expected_trace_version': detail['traceability']['version'],
        'expected_bom_sha256': detail['source_status']['expected_bom_sha256'],
        'reference': 'SYNTHETIC-PASS-ALL',
        'notes': 'Incoming dimensions and saved material evidence inspected for every listed physical piece',
        'pieces': [{'piece_key': row['piece_key'], 'expected_version': row['qa001']['version'],
                    'basis_sha256': row['qa001']['basis_sha256']}
                   for row in detail['traceability']['materials']]}


def pass_all(api, item_id, body=None, role='inspector'):
    return api.post(f'/api/spool-boms/spools/{item_id}/materials/qa-001/pass-all',
        body if body is not None else pass_all_body(receiving_detail(api, item_id)), role=role)


def prepared(api, item_id='BULK-QA-01', quantity=3):
    create_spool(api, item_id)
    upload_receiving_bom(api, item_id, quantity=quantity)
    return save_receiving_materials(api, item_id, role='inspector')


def guarded_edit_body(detail, index=0):
    fields = ('piece_key', 'supplier', 'supplier_piece_id', 'heat_number', 'mtr_reference', 'mtr_url', 'notes')
    piece = detail['traceability']['materials'][index]
    materials = [{key: row[key] for key in fields} for row in detail['traceability']['materials']]
    materials[index]['heat_number'] = 'HEAT-REVIEWED-CORRECTION'
    return {'expected_version': detail['traceability']['version'],
        'expected_bom_sha256': detail['source_status']['expected_bom_sha256'],
        'reason': 'Explicitly save only this inspected physical piece before its QA decision',
        'materials': materials, 'qa001_guard': {'piece_key': piece['piece_key'],
            'expected_version': piece['qa001']['version'], 'basis_sha256': piece['qa001']['basis_sha256']}}


def test_pass_all_records_distinct_events_at_one_time_for_exact_selected_copy_only(api):
    first = prepared(api)
    sibling = prepared(api, 'BULK-QA-SIBLING')
    result = ok(pass_all(api, 'BULK-QA-01', pass_all_body(first)))
    rows = result['traceability']['materials']
    decisions = [row['qa001']['latest'] for row in rows]
    assert all(row['qa001']['can_proceed'] for row in rows)
    assert len({row['id'] for row in decisions}) == 3
    assert len({row['piece_key'] for row in decisions}) == 3
    assert len({row['at'] for row in decisions}) == 1
    assert {row['actor'] for row in decisions} == {BADGES['inspector']}
    assert {row['reference'] for row in decisions} == {'SYNTHETIC-PASS-ALL'}
    assert {row['notes'] for row in decisions} == {pass_all_body(first)['notes']}
    assert result['qa001_bulk_result'] == {'spool_id': 'BULK-QA-01', 'passed_count': 3,
        'already_passed_count': 0, 'passed_piece_keys': [row['piece_key'] for row in rows],
        'already_passed_piece_keys': []}
    assert result['arrival']['latest'] is None and not result['arrival']['can_proceed']
    assert receiving_detail(api, 'BULK-QA-SIBLING') == sibling
    assert result['traceability']['version'] == first['traceability']['version']


def test_current_pass_is_preserved_and_repeating_all_current_is_a_write_free_noop(api):
    detail = prepared(api)
    detail = ok(decide(api, 'BULK-QA-01', detail['traceability']['materials'][0]), 201)
    existing = deepcopy(detail['traceability']['materials'][0]['qa001']['latest'])
    result = ok(pass_all(api, 'BULK-QA-01', pass_all_body(detail)))
    assert result['qa001_bulk_result']['passed_count'] == 2
    assert result['qa001_bulk_result']['already_passed_count'] == 1
    assert result['traceability']['materials'][0]['qa001']['latest'] == existing
    accepted = accept_arrival(api, 'BULK-QA-01')
    before = database_state(api)
    repeated = ok(pass_all(api, 'BULK-QA-01', pass_all_body(accepted)))
    assert repeated['qa001_bulk_result']['passed_count'] == 0
    assert repeated['qa001_bulk_result']['already_passed_count'] == 3
    assert repeated['arrival'] == accepted['arrival']
    assert database_state(api) == before


def test_reviewed_fail_and_stale_pass_can_be_reinspected_together(api):
    detail = prepared(api, quantity=2)
    failed = ok(decide(api, 'BULK-QA-01', detail['traceability']['materials'][0], 'Fail'), 201)
    passed = ok(decide(api, 'BULK-QA-01', failed['traceability']['materials'][1]), 201)
    changed = edit_piece(api, 'BULK-QA-01', 1, heat_number='NEW-CHECKED-HEAT')
    assert [row['qa001']['status'] for row in changed['traceability']['materials']] == ['failed', 'needs_reinspection']
    assert all(not row['qa001']['pass_blockers'] for row in changed['traceability']['materials'])
    result = ok(pass_all(api, 'BULK-QA-01', pass_all_body(changed)))
    assert result['qa001_bulk_result']['passed_count'] == 2
    assert [row['qa001']['version'] for row in result['traceability']['materials']] == [2, 2]
    history = ok(api.get(result['traceability']['materials'][0]['qa001']['history_url']))
    assert [row['result'] for row in history['history']] == ['Pass', 'Fail']


def test_shared_bom_piece_keys_do_not_authorize_a_different_physical_copy(api):
    from test_spool_document_material_records import physical_setup
    _, _, children = physical_setup(api, quantity=2)
    first = save_receiving_materials(api, children[0]['id'])
    second = save_receiving_materials(api, children[1]['id'])
    first_keys = [row['piece_key'] for row in first['traceability']['materials']]
    assert first_keys == [row['piece_key'] for row in second['traceability']['materials']]
    assert first['source_status']['expected_bom_sha256'] == second['source_status']['expected_bom_sha256']
    before = database_state(api)
    response = pass_all(api, children[0]['id'], pass_all_body(second))
    assert response.status_code == 409
    assert len(response.json()['detail']['piece_blockers']) == len(first_keys)
    assert database_state(api) == before


@pytest.mark.parametrize('field', ['heat_number', 'mtr_reference'])
def test_one_missing_evidence_field_blocks_entire_batch_with_named_piece(api, field):
    prepared(api)
    detail = edit_piece(api, 'BULK-QA-01', 1, **{field: ''})
    blocked = detail['traceability']['materials'][1]
    assert blocked['qa001']['pass_blockers']
    before = database_state(api)
    response = pass_all(api, 'BULK-QA-01', pass_all_body(detail))
    assert response.status_code == 409, response.text
    errors = response.json()['detail']['piece_blockers']
    assert len(errors) == 1 and errors[0]['piece_key'] == blocked['piece_key']
    assert errors[0]['piece_identifier'] == blocked['piece_identifier']
    assert ('heat number' if field == 'heat_number' else 'MTR reference') in ' '.join(errors[0]['blockers'])
    assert database_state(api) == before


@pytest.mark.parametrize('invalid', ['trace_version', 'source', 'qa_version', 'qa_basis', 'omitted', 'duplicate', 'foreign'])
def test_stale_or_incomplete_request_rejects_every_piece_without_writes(api, invalid):
    detail = prepared(api)
    body = pass_all_body(detail)
    if invalid == 'trace_version':
        body['expected_trace_version'] -= 1
    elif invalid == 'source':
        body['expected_bom_sha256'] = '0' * 64
    elif invalid == 'qa_version':
        body['pieces'][1]['expected_version'] += 1
    elif invalid == 'qa_basis':
        body['pieces'][1]['basis_sha256'] = '0' * 64
    elif invalid == 'omitted':
        body['pieces'].pop(1)
    elif invalid == 'duplicate':
        body['pieces'].append(deepcopy(body['pieces'][1]))
    else:
        body['pieces'][1]['piece_key'] = 'UNRELATED-PHYSICAL-PIECE'
    before = database_state(api)
    response = pass_all(api, 'BULK-QA-01', body)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['message']
    assert database_state(api) == before


def test_changed_bom_requires_adoption_even_with_fresh_bulk_tokens(api):
    prepared(api)
    upload_receiving_bom(api, 'BULK-QA-01', quantity=4)
    detail = receiving_detail(api, 'BULK-QA-01')
    assert detail['source_status']['changed']
    before = database_state(api)
    response = pass_all(api, 'BULK-QA-01', pass_all_body(detail))
    assert response.status_code == 409
    assert any('Adopt' in error for error in response.json()['detail']['blockers'])
    assert database_state(api) == before


@pytest.mark.parametrize('role', [None, 'handler', 'supervisor', 'welder', 'painter', 'misc'])
def test_pass_all_requires_qa_role(api, role):
    detail = prepared(api)
    before = database_state(api)
    assert pass_all(api, 'BULK-QA-01', pass_all_body(detail), role).status_code == (401 if role is None else 403)
    assert database_state(api) == before


def test_pass_all_rechecks_authority_refreshed_after_waiting_for_lock(api, monkeypatch):
    import flow
    detail = prepared(api)
    before = database_state(api)
    original = flow.lock_topology

    def refreshed_authority(s):
        original(s)
        # Simulate the authenticated employee's refreshed non-QA role in the
        # same Session; rollback must leave all pieces and this fixture intact.
        s.get(api.application.Employee, BADGES['inspector']).role = 'handler'

    monkeypatch.setattr(flow, 'lock_topology', refreshed_authority)
    assert pass_all(api, 'BULK-QA-01', pass_all_body(detail)).status_code == 403
    assert database_state(api) == before


def test_released_spool_rejects_even_all_current_pass_noop(api):
    from test_admin import release
    prepared(api)
    release(api, 'BULK-QA-01')
    detail = receiving_detail(api, 'BULK-QA-01')
    before = database_state(api)
    response = pass_all(api, 'BULK-QA-01', pass_all_body(detail), role='admin')
    assert response.status_code == 409
    assert response.json()['detail']['blockers']
    assert database_state(api) == before


def test_guarded_material_save_then_explicit_piece_pass_uses_only_reviewed_evidence(api):
    detail = prepared(api, quantity=2)
    original_second = deepcopy(detail['traceability']['materials'][1])
    body = guarded_edit_body(detail)
    saved = ok(api.put('/api/spool-boms/spools/BULK-QA-01/traceability', body, role='inspector'))
    assert saved['traceability']['materials'][0]['qa001']['status'] == 'pending'
    assert saved['traceability']['materials'][1] == original_second
    passed = ok(decide(api, 'BULK-QA-01', saved['traceability']['materials'][0]), 201)
    assert passed['traceability']['materials'][0]['qa001']['can_proceed']
    assert passed['traceability']['materials'][1]['qa001']['status'] == 'pending'
    assert not passed['arrival']['can_proceed']


@pytest.mark.parametrize('changed', ['qa_fail', 'mtr_revision', 'drawing'])
def test_guarded_material_save_rejects_changed_evidence_before_any_edit(api, changed):
    detail = prepared(api, quantity=2)
    body = guarded_edit_body(detail)
    if changed == 'qa_fail':
        ok(decide(api, 'BULK-QA-01', detail['traceability']['materials'][0], 'Fail'), 201)
    elif changed == 'mtr_revision':
        ok(upload_mtr(api, 'BULK-QA-01'), 201)
    else:
        from test_spool_documents import pdf, request_upload
        # The prior local BOM is document-set version 1; a drawing adds new evidence.
        ok(request_upload(api, '/api/spool-documents/spools/BULK-QA-01', kind='isometric', version=1,
            files=[('drawing.pdf', pdf(), 'application/pdf')]))
    before = database_state(api)
    response = api.put('/api/spool-boms/spools/BULK-QA-01/traceability', body, role='inspector')
    assert response.status_code == 409, response.text
    assert 'No material changes were saved' in response.json()['detail']
    assert database_state(api) == before


def test_guarded_material_action_cannot_save_a_sibling_draft(api):
    detail = prepared(api, quantity=2)
    body = guarded_edit_body(detail)
    body['materials'][1]['heat_number'] = 'UNREVIEWED-SIBLING-DRAFT'
    before = database_state(api)
    response = api.put('/api/spool-boms/spools/BULK-QA-01/traceability', body, role='inspector')
    assert response.status_code == 409
    assert 'only the reviewed piece' in response.json()['detail']
    assert database_state(api) == before


def test_qa_evidence_timestamps_canonicalize_equivalent_database_timezones(application):
    from datetime import datetime, timedelta, timezone
    from spool_boms import _stamp as material_stamp
    from spool_receiving import _digest, _stamp as inspection_stamp
    utc = datetime(2026, 10, 31, 18, 9, 35, 669771, tzinfo=timezone.utc)
    database_value = utc.astimezone(timezone(timedelta(hours=-7)))
    for stamp in (material_stamp, inspection_stamp):
        assert stamp(utc) == stamp(database_value) == stamp(utc.replace(tzinfo=None))
        assert _digest({'at': stamp(utc)}) == _digest({'at': stamp(database_value)})
