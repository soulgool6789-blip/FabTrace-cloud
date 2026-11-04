"""Explicit receiving corrections preserve failures until QA reinspects them."""

from copy import deepcopy

import pytest

from conftest import BADGES
from receiving_helpers import (approve_materials, receiving_detail, receiving_rework_body,
    record_arrival, record_receiving_rework, save_receiving_materials, upload_receiving_bom)
from test_material_piece_qa import decide, edit_piece
from test_material_piece_qa_bulk import pass_all, pass_all_body
from test_progress import database_state
from test_spool_receiving import create_spool
from tracking_helpers import ok


DEFECT = 'The received pipe end is damaged and must be repaired before fabrication.'
CORRECTION = 'Squared the damaged pipe end and verified the remaining length against the drawing.'
REFERENCE = 'RECEIVING-CORRECTION-01'


def failed_receipt(api, kind='material', item_id='REWORK-RECEIPT-01'):
    create_spool(api, item_id)
    upload_receiving_bom(api, item_id, quantity=2)
    detail = save_receiving_materials(api, item_id)
    if kind == 'material':
        piece = detail['traceability']['materials'][0]
        detail = ok(decide(api, item_id, piece, 'Fail', notes=DEFECT), 201)
        return detail, piece['piece_key']
    approve_materials(api, item_id)
    return ok(record_arrival(api, item_id, result='Fail', notes=DEFECT), 201), None


def qa_view(detail, piece_key=None):
    return (next(row['qa001'] for row in detail['traceability']['materials'] if row['piece_key'] == piece_key)
            if piece_key is not None else detail['arrival'])


def rework_path(item_id):
    return f'/api/spool-boms/spools/{item_id}/receiving-rework'


def test_material_failure_blocks_single_and_bulk_pass_until_correction_then_requires_qa(api):
    item_id = 'REWORK-RECEIPT-01'
    failed, piece_key = failed_receipt(api)
    qa = qa_view(failed, piece_key)
    original = deepcopy(qa['latest'])
    finding = qa['rework']
    assert finding['error_description'] == DEFECT
    assert finding['failure_reference'] == original['reference']
    assert finding['completion'] is None and finding['status'] == 'awaiting_rework'
    assert finding['return_title'] == 'Inventory / material receiving'
    assert qa['pass_blockers'] and not qa['can_proceed']
    before = database_state(api)
    assert decide(api, item_id, failed['traceability']['materials'][0]).status_code == 409
    bulk = pass_all(api, item_id, pass_all_body(failed))
    assert bulk.status_code == 409 and 'rework' in bulk.text
    assert database_state(api) == before, 'Rejected PASS ALL must not pass the unaffected piece either'

    corrected = ok(record_receiving_rework(api, item_id, piece_key=piece_key,
        description=CORRECTION, reference=REFERENCE), 201)
    corrected_qa = qa_view(corrected, piece_key)
    assert corrected_qa['latest'] == original and corrected_qa['version'] == qa['version']
    assert corrected_qa['status'] == 'failed' and not corrected_qa['can_proceed']
    assert not corrected_qa['pass_blockers']
    completion = corrected_qa['rework']['completion']
    assert completion['actor'] == BADGES['handler']
    assert completion['error_description'] == DEFECT and completion['description'] == CORRECTION
    assert completion['reference'] == REFERENCE
    assert completion['failure_id'] == original['id']
    assert corrected_qa['rework']['status'] == 'awaiting_reinspection'
    assert not corrected_qa['rework']['can_complete']
    assert not corrected['arrival']['can_proceed']
    assert decide(api, item_id, corrected['traceability']['materials'][0], role='handler').status_code == 403

    reviewed = ok(pass_all(api, item_id, pass_all_body(corrected)))
    assert reviewed['qa001_bulk_result']['passed_count'] == 2
    reviewed_qa = qa_view(reviewed, piece_key)
    assert reviewed_qa['can_proceed'] and reviewed_qa['rework'] is None
    history = ok(api.get(reviewed_qa['history_url']))['history']
    assert history[-1] == original and history[0]['actor'] == BADGES['inspector']
    assert [row['result'] for row in history] == ['Pass', 'Fail']
    arrived = ok(record_arrival(api, item_id), 201)
    assert arrived['arrival']['can_proceed']
    assert arrived['arrival']['rework_history'] == [completion]

    # A new failure needs its own correction; the earlier one cannot be reused.
    old_payload = receiving_rework_body(failed, piece_key=piece_key)
    again = ok(decide(api, item_id, arrived['traceability']['materials'][0], 'Fail',
        notes='A different physical defect was found during the next inspection'), 201)
    assert qa_view(again, piece_key)['rework']['completion'] is None
    assert pass_all(api, item_id).status_code == 409
    assert api.post(rework_path(item_id), old_payload, role='handler').status_code == 409


def test_arrival_correction_keeps_error_visible_and_never_records_a_qa_pass_itself(api):
    item_id = 'REWORK-RECEIPT-01'
    failed, _ = failed_receipt(api, 'arrival')
    original = deepcopy(failed['arrival']['latest'])
    payload = receiving_rework_body(failed, description=CORRECTION, reference=REFERENCE)
    item = ok(api.get('/api/items/' + item_id, role='handler'))
    assert item['receiving']['rework']['error_description'] == DEFECT
    assert any(DEFECT in value for value in item['receiving']['blockers'])
    assert record_arrival(api, item_id).status_code == 409
    corrected = ok(api.post(rework_path(item_id), payload, role='supervisor'), 201)
    assert corrected['arrival']['latest'] == original
    assert corrected['arrival']['status'] == 'failed' and not corrected['arrival']['can_proceed']
    finding = corrected['arrival']['rework']
    assert finding['error_description'] == DEFECT and finding['status'] == 'awaiting_reinspection'
    assert finding['completion']['actor'] == BADGES['supervisor']
    assert len(corrected['arrival']['history']) == 1
    before = database_state(api)
    assert api.post(rework_path(item_id), payload, role='supervisor').status_code == 409
    assert database_state(api) == before

    passed = ok(record_arrival(api, item_id, notes='QA verified the repaired pipe end and accepted arrival'), 201)
    assert passed['arrival']['can_proceed'] and passed['arrival']['rework'] is None
    assert passed['arrival']['history'][-1] == original
    assert passed['arrival']['latest']['actor'] == BADGES['inspector']
    assert passed['arrival']['rework_history'] == [finding['completion']]
    assert api.post(rework_path(item_id), payload, role='supervisor').status_code == 409


@pytest.mark.parametrize('kind', ['arrival', 'material'])
def test_receiving_review_and_correction_have_separate_roles(api, kind):
    item_id = 'REWORK-RECEIPT-01'
    failed, piece_key = failed_receipt(api, kind)
    payload = receiving_rework_body(failed, piece_key=piece_key)
    for role in ('handler', 'supervisor', 'inspector', 'painter'):
        view = ok(api.get('/api/spool-boms/spools/' + item_id, role=role))
        qa = qa_view(view, piece_key)
        assert qa['permissions']['can_inspect'] is (role == 'inspector')
        assert qa['rework']['can_complete'] is (role in ('handler', 'supervisor'))
    before = database_state(api)
    for role in (None, 'inspector', 'painter', 'ndt', 'process_welder'):
        response = api.post(rework_path(item_id), payload, role=role)
        assert response.status_code == (401 if role is None else 403), response.text
    assert database_state(api) == before


def test_material_rework_requires_current_failure_version_basis_and_nonblank_evidence(api):
    item_id = 'REWORK-RECEIPT-01'
    failed, piece_key = failed_receipt(api)
    payload = receiving_rework_body(failed, piece_key=piece_key)
    before = database_state(api)
    for fields, status in [
        ({'description': ''}, 422), ({'description': '    '}, 422), ({'reference': ' '}, 422),
        ({'inspection_kind': 'weld'}, 422), ({'failure_id': 9999999}, 404),
        ({'expected_version': payload['expected_version'] + 1}, 409), ({'basis_sha256': '0' * 64}, 409),
    ]:
        response = api.post(rework_path(item_id), {**payload, **fields}, role='handler')
        assert response.status_code == status, response.text
    assert database_state(api) == before

    edit_piece(api, item_id, 0, heat_number='CORRECTED-HEAT-MARKING')
    changed = receiving_detail(api, item_id)
    assert qa_view(changed, piece_key)['basis_sha256'] != payload['basis_sha256']
    before = database_state(api)
    assert api.post(rework_path(item_id), payload, role='handler').status_code == 409
    assert database_state(api) == before
    fresh = receiving_rework_body(changed, piece_key=piece_key, description=CORRECTION, reference=REFERENCE)
    corrected = ok(api.post(rework_path(item_id), fresh, role='admin'), 201)
    assert qa_view(corrected, piece_key)['rework']['completion']['actor'] == BADGES['admin']
    assert api.post(rework_path(item_id), fresh, role='handler').status_code == 409


@pytest.mark.parametrize('kind, status', [('material', 404), ('arrival', 409)])
def test_receiving_correction_cannot_be_recorded_for_another_physical_spool(api, kind, status):
    first, first_key = failed_receipt(api, kind, 'REWORK-FIRST')
    second, second_key = failed_receipt(api, kind, 'REWORK-SECOND')
    payload = receiving_rework_body(first, piece_key=first_key)
    before = database_state(api)
    response = api.post(rework_path('REWORK-SECOND'), payload, role='handler')
    assert response.status_code == status, response.text
    assert database_state(api) == before
    assert qa_view(receiving_detail(api, 'REWORK-SECOND'), second_key)['rework']['completion'] is None
    assert receiving_detail(api, 'REWORK-FIRST')['arrival']['rework_history'] == []
