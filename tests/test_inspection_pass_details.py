"""Pass details are optional without removing evidence or failure requirements."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from conftest import BADGES
from receiving_helpers import CHECKS, approve_materials
from test_material_piece_qa import edit_piece
from test_material_piece_qa_bulk import pass_all_body, prepared
from test_progress import database_state
from tracking_helpers import ok


ITEM = 'PASS-DETAILS-01'


def request_for(detail, kind):
    root = f'/api/spool-boms/spools/{ITEM}'
    if kind == 'bulk':
        body = pass_all_body(detail)
        del body['reference']
        del body['notes']
        return root + '/materials/qa-001/pass-all', body
    qa = detail['arrival'] if kind == 'arrival' else detail['traceability']['materials'][0]['qa001']
    body = {'expected_version': qa['version'], 'basis_sha256': qa['basis_sha256'], 'result': 'Pass'}
    if kind == 'arrival':
        body['checks'] = CHECKS.copy()
        return root + '/arrival-inspections', body
    return qa['history_url'], body


def ready_request(api, kind):
    detail = prepared(api, ITEM, quantity=3)
    if kind == 'arrival':
        detail = approve_materials(api, ITEM)
    return (*request_for(detail, kind), detail)


@pytest.mark.parametrize('kind', ['piece', 'bulk', 'arrival'])
@pytest.mark.parametrize('details', [{}, {'reference': ' \t ', 'notes': ' \n '},
                                    {'reference': ' R ', 'notes': ' X '}],
                         ids=['omitted', 'whitespace', 'optional-short-text'])
def test_pass_keeps_signed_evidence_without_requiring_invented_reason_or_reference(api, kind, details):
    from spool_receiving import SpoolArrivalInspection, SpoolMaterialInspection

    path, body, before = ready_request(api, kind)
    started = datetime.now(timezone.utc)
    saved = ok(api.post(path, {**body, **details}, role='inspector'), 200 if kind == 'bulk' else 201)
    if kind == 'arrival':
        decisions = [saved['arrival']['latest']]
        assert saved['arrival']['can_proceed']
        expected_bases = {body['basis_sha256']}
    else:
        rows = saved['traceability']['materials'][:1] if kind == 'piece' else saved['traceability']['materials']
        decisions = [row['qa001']['latest'] for row in rows]
        assert all(row['qa001']['can_proceed'] for row in rows)
        expected_bases = {row['qa001']['basis_sha256'] for row in before['traceability']['materials'][:len(rows)]}
        assert saved['arrival']['latest'] is None, 'Material Pass must not invent arrival approval'
        assert len({decision['piece_key'] for decision in decisions}) == len(rows)
        if kind == 'piece':
            assert all(row['qa001']['latest'] is None for row in saved['traceability']['materials'][1:])
        else:
            assert saved['qa001_bulk_result']['passed_count'] == 3
    assert len({decision['id'] for decision in decisions}) == len(decisions)
    assert {decision['basis_sha256'] for decision in decisions} == expected_bases
    for decision in decisions:
        assert decision['actor'] == BADGES['inspector'] and decision['spool_id'] == ITEM
        assert started <= datetime.fromisoformat(decision['at']) <= datetime.now(timezone.utc)
        assert decision['result'] == 'Pass'
        assert decision['reference'] == details.get('reference', '').strip()
        assert decision['notes'] == details.get('notes', '').strip()
    model = SpoolArrivalInspection if kind == 'arrival' else SpoolMaterialInspection
    with api.session_factory() as session:
        events = list(session.scalars(select(model).where(model.spool_id == ITEM)))
        assert len(events) == len(decisions)
        assert all(event.basis for event in events), 'Every signed decision must retain its real evidence snapshot'


@pytest.mark.parametrize('kind', ['piece', 'arrival'])
@pytest.mark.parametrize('details, message', [
    ({}, 'Fail requires an inspection reference'),
    ({'reference': 'REPORT-1'}, 'Fail requires a failure reason'),
    ({'notes': 'Material marking illegible'}, 'Fail requires an inspection reference'),
    ({'reference': 'REPORT-1', 'notes': ' \t '}, 'Fail requires a failure reason'),
    ({'reference': ' X ', 'notes': ' bad '}, 'Fail requires an inspection reference'),
])
def test_fail_still_requires_reference_and_reason_before_any_write(api, kind, details, message):
    path, body, _ = ready_request(api, kind)
    before = database_state(api)
    response = api.post(path, {**body, 'result': 'Fail', **details}, role='inspector')
    assert response.status_code == 422, response.text
    assert message in response.text
    assert database_state(api) == before


@pytest.mark.parametrize('kind', ['piece', 'bulk', 'arrival'])
def test_optional_pass_fields_keep_existing_length_limits(api, kind):
    path, body, _ = ready_request(api, kind)
    before = database_state(api)
    for field, length in [('reference', 301), ('notes', 3001)]:
        response = api.post(path, {**body, field: 'X' * length}, role='inspector')
        assert response.status_code == 422, response.text
        assert database_state(api) == before


@pytest.mark.parametrize('kind', ['piece', 'bulk', 'arrival'])
def test_omitted_optional_details_do_not_bypass_required_materials_or_arrival_checks(api, kind):
    path, body, detail = ready_request(api, kind)
    if kind == 'arrival':
        body['checks']['condition'] = False
    else:
        detail = edit_piece(api, ITEM, 0, mtr_reference='')
        path, body = request_for(detail, kind)
    before = database_state(api)
    response = api.post(path, body, role='inspector')
    assert response.status_code == 409, response.text
    assert database_state(api) == before


@pytest.mark.parametrize('kind', ['piece', 'arrival'])
def test_fail_reason_remains_in_history_after_pass_without_notes(api, kind):
    path, body, _ = ready_request(api, kind)
    failed = ok(api.post(path, {**body, 'result': 'Fail', 'reference': 'CHECK-FAIL-1',
        'notes': 'Material marking required reinspection'}, role='inspector'), 201)
    path, body = request_for(failed, kind)
    saved = ok(api.post(path, body, role='inspector'), 201)
    history = saved['arrival']['history'] if kind == 'arrival' else ok(api.get(path))['history']
    assert [decision['result'] for decision in history] == ['Pass', 'Fail']
    assert history[0]['reference'] == history[0]['notes'] == ''
    assert history[1]['reference'] == 'CHECK-FAIL-1'
    assert history[1]['notes'] == 'Material marking required reinspection'
