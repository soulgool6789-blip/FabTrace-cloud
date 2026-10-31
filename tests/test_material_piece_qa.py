"""Saved physical BOM pieces and explicit, immutable QA-001 decisions."""
from copy import deepcopy

import pytest
from sqlalchemy import func, select

from conftest import BADGES
from receiving_helpers import (accept_arrival, approve_materials, receiving_detail,
    record_arrival, save_receiving_materials, upload_receiving_bom)
from test_order_labels import generate, labels, public_qr_url
from test_progress import database_state
from test_spool_receiving import create_spool, upload_mtr
from tracking_helpers import ok


def decide(api, item_id, piece, result='Pass', role='inspector', **changes):
    qa = piece['qa001']
    return api.post(f'/api/spool-boms/spools/{item_id}/materials/{piece["piece_key"]}/qa-001', {
        'expected_version': qa['version'], 'basis_sha256': qa['basis_sha256'],
        'result': result, 'reference': 'PIECE-QA-001-TEST',
        'notes': 'Synthetic incoming dimensions and evidence reviewed', **changes}, role=role)


def edit_piece(api, item_id, index, **changes):
    detail = receiving_detail(api, item_id)
    fields = ('piece_key', 'supplier', 'supplier_piece_id', 'heat_number', 'mtr_reference', 'mtr_url', 'notes')
    materials = [{key: row[key] for key in fields} for row in detail['traceability']['materials']]
    materials[index].update(changes)
    return ok(api.put(f'/api/spool-boms/spools/{item_id}/traceability', {
        'expected_version': detail['traceability']['version'],
        'expected_bom_sha256': detail['source_status']['expected_bom_sha256'],
        'reason': 'Correct only the independently identified physical piece', 'materials': materials}, role='handler'))


def test_upload_quantity_persists_distinct_blank_records_without_any_acceptance(api):
    from spool_boms import SpoolBomMaterial, SpoolBomTrace
    from spool_receiving import SpoolMaterialInspection
    item_id = create_spool(api)
    upload_receiving_bom(api, item_id, quantity=2)
    before = database_state(api)
    detail = receiving_detail(api, item_id)
    rows = detail['traceability']['materials']
    assert detail['traceability']['configured'] and detail['traceability']['version'] == 1
    assert len(rows) == 2 and all(row['persisted'] for row in rows)
    assert len({row['piece_key'] for row in rows}) == len({row['piece_identifier'] for row in rows}) == 2
    assert [row['piece_number'] for row in rows] == [1, 2]
    assert [row['piece_label'] for row in rows] == ['Item 1 · Piece 001 of 002', 'Item 1 · Piece 002 of 002']
    assert all(not row['heat_number'] and not row['mtr_reference'] and row['qa001']['status'] == 'pending' for row in rows)
    assert not detail['arrival']['can_proceed']
    with api.session_factory() as s:
        assert s.get(SpoolBomTrace, item_id).version == 1
        assert s.scalar(select(func.count()).select_from(SpoolBomMaterial)) == 2
        assert s.scalar(select(func.count()).select_from(SpoolMaterialInspection)) == 0
    assert database_state(api) == before, 'Viewing records must not create or approve pieces'


def test_requirements_initialize_existing_and_later_physical_copies_in_exact_scope(api):
    from test_spool_documents import setup, requirement_path, request_upload
    from spool_boms import SpoolBomMaterial
    saved, other = setup(api), setup(api, number='PIECE-OTHER-PO', quantity=1)
    generate(api, saved['order']['project_id'])
    generate(api, other['order']['project_id'])
    ok(request_upload(api, requirement_path(saved)))
    first = labels(api, saved['order']['project_id'])['items']
    for item in first:
        rows = receiving_detail(api, item['id'])['traceability']['materials']
        assert len(rows) == 3 and all(row['persisted'] for row in rows)
    unrelated = labels(api, other['order']['project_id'])['items'][0]
    assert not receiving_detail(api, unrelated['id'])['traceability']['configured']
    later = setup(api, number='PIECE-LATER-PO', quantity=1)
    ok(request_upload(api, requirement_path(later)))
    generate(api, later['order']['project_id'])
    late_id = labels(api, later['order']['project_id'])['items'][0]['id']
    assert all(row['persisted'] for row in receiving_detail(api, late_id)['traceability']['materials'])
    with api.session_factory() as s:
        assert s.scalar(select(func.count()).select_from(SpoolBomMaterial)) == 9


def test_reviewed_isometric_import_initializes_each_selected_spool_piece(api):
    from test_isometric_import import setup, path, preview, save
    saved = setup(api, quantity=1)
    generate(api, saved['order']['project_id'])
    data = ok(preview(api, path(saved)))
    ok(save(api, path(saved), data))
    for item in labels(api, saved['order']['project_id'])['items']:
        detail = receiving_detail(api, item['id'])
        assert len(detail['traceability']['materials']) == 3
        assert all(row['persisted'] and row['qa001']['status'] == 'pending' for row in detail['traceability']['materials'])


@pytest.mark.parametrize('role', [None, 'handler', 'supervisor', 'welder', 'painter', 'misc'])
def test_only_qa_roles_can_record_piece_decisions(api, role):
    item_id = create_spool(api)
    upload_receiving_bom(api, item_id)
    piece = receiving_detail(api, item_id)['traceability']['materials'][0]
    before = database_state(api)
    assert decide(api, item_id, piece, 'Fail', role).status_code == (401 if role is None else 403)
    assert database_state(api) == before


def test_piece_fail_can_record_missing_materials_pass_requires_complete_basis(api):
    item_id = create_spool(api)
    upload_receiving_bom(api, item_id)
    piece = receiving_detail(api, item_id)['traceability']['materials'][0]
    assert decide(api, item_id, piece).status_code == 409
    failed = ok(decide(api, item_id, piece, 'Fail'), 201)
    assert failed['traceability']['materials'][0]['qa001']['status'] == 'failed'
    completed = save_receiving_materials(api, item_id)
    assert completed['traceability']['materials'][0]['qa001']['status'] == 'failed'
    passed = ok(decide(api, item_id, completed['traceability']['materials'][0]), 201)
    qa = passed['traceability']['materials'][0]['qa001']
    assert qa['version'] == 2 and qa['can_proceed']
    assert [row['result'] for row in ok(api.get(qa['history_url']))['history']] == ['Pass', 'Fail']
    assert not passed['arrival']['can_proceed'], 'Piece QA does not invent the overall arrival inspection'


def test_piece_edits_invalidate_only_that_piece_qa_and_stale_requests_do_not_write(api):
    item_id = create_spool(api)
    upload_receiving_bom(api, item_id, quantity=2)
    save_receiving_materials(api, item_id)
    approved = approve_materials(api, item_id)
    original = deepcopy(approved['traceability']['materials'])
    changed = edit_piece(api, item_id, 1, heat_number='SECOND-HEAT-CORRECTED')
    first, second = changed['traceability']['materials']
    assert {key: value for key, value in first['qa001'].items() if key != 'permissions'} == {
        key: value for key, value in original[0]['qa001'].items() if key != 'permissions'}
    assert second['qa001']['status'] == 'needs_reinspection'
    assert second['qa001']['latest'] == original[1]['qa001']['latest']
    before = database_state(api)
    assert decide(api, item_id, original[1]).status_code == 409
    assert decide(api, item_id, first, expected_version=0).status_code == 409
    assert database_state(api) == before
    corrected = ok(decide(api, item_id, second), 201)
    assert corrected['traceability']['materials'][1]['qa001']['version'] == 2
    assert all(row['qa001']['can_proceed'] for row in corrected['traceability']['materials'])


def test_matching_mtr_revision_stales_only_relevant_piece_qa(api):
    item_id = create_spool(api)
    upload_receiving_bom(api, item_id, quantity=2)
    save_receiving_materials(api, item_id, reference='MTR-FIRST')
    edit_piece(api, item_id, 1, mtr_reference='MTR-SECOND')
    approved = approve_materials(api, item_id)
    ok(upload_mtr(api, item_id, reference='MTR-FIRST'), 201)
    first, second = receiving_detail(api, item_id)['traceability']['materials']
    assert first['qa001']['status'] == 'needs_reinspection'
    assert second['qa001'] == approved['traceability']['materials'][1]['qa001']


def test_overall_arrival_requires_every_current_piece_pass_and_qa_fail_blocks_again(api):
    item_id = create_spool(api)
    upload_receiving_bom(api, item_id, quantity=2)
    saved = save_receiving_materials(api, item_id)
    assert record_arrival(api, item_id).status_code == 409
    first = ok(decide(api, item_id, saved['traceability']['materials'][0]), 201)
    assert record_arrival(api, item_id).status_code == 409
    approved = approve_materials(api, item_id)
    accepted = ok(record_arrival(api, item_id), 201)
    assert accepted['arrival']['can_proceed']
    failed = ok(decide(api, item_id, approved['traceability']['materials'][1], 'Fail'), 201)
    assert not failed['arrival']['can_proceed']
    assert failed['arrival']['latest'] == accepted['arrival']['latest']
    assert record_arrival(api, item_id).status_code == 409


def test_source_adoption_keeps_old_piece_qa_history_and_starts_new_pieces_pending(api):
    item_id = create_spool(api)
    accepted = accept_arrival(api, item_id)
    old_piece = accepted['traceability']['materials'][0]
    upload_receiving_bom(api, item_id, quantity=2)
    current = receiving_detail(api, item_id)
    assert current['traceability']['materials'][0]['heat_number'] == old_piece['heat_number']
    assert current['traceability']['materials'][0]['qa001']['status'] == 'needs_reinspection'
    adopted = ok(api.post(f'/api/spool-boms/spools/{item_id}/adopt-bom', {
        'expected_version': current['traceability']['version'],
        'expected_bom_sha256': current['source_status']['expected_bom_sha256'],
        'reason': 'Adopt reviewed new material source without transferring old identities'}))
    assert len(adopted['traceability']['materials']) == 2
    assert all(not row['heat_number'] and row['qa001']['status'] == 'pending' for row in adopted['traceability']['materials'])
    assert old_piece['piece_identifier'] not in {row['piece_identifier'] for row in adopted['traceability']['materials']}
    history = ok(api.get(old_piece['qa001']['history_url']))
    assert history['history'][0] == old_piece['qa001']['latest']
    assert decide(api, item_id, old_piece).status_code == 404


def test_trace_payload_cannot_write_or_overwrite_piece_qa(api):
    item_id = create_spool(api)
    accepted = accept_arrival(api, item_id)
    piece = accepted['traceability']['materials'][0]
    before = database_state(api)
    response = api.put(f'/api/spool-boms/spools/{item_id}/traceability', {
        'expected_version': accepted['traceability']['version'],
        'expected_bom_sha256': accepted['source_status']['expected_bom_sha256'],
        'reason': 'Attempt invalid mixed material and QA write',
        'materials': [{'piece_key': piece['piece_key'], 'heat_number': 'NEW', 'qa001': {'result': 'Pass'}}]}, role='handler')
    assert response.status_code == 422 and database_state(api) == before


def test_backfill_only_creates_blank_missing_uploaded_pieces_and_is_idempotent(api, monkeypatch):
    import spool_boms
    from spool_receiving import SpoolMaterialInspection
    existing, missing = create_spool(api), create_spool(api, 'PIECE-OLD-UPLOAD')
    accepted = accept_arrival(api, existing)
    with monkeypatch.context() as patch:
        patch.setattr(spool_boms, 'ensure_material_piece_records', lambda *args, **kwargs: 0)
        upload_receiving_bom(api, missing, quantity=2)
    assert not receiving_detail(api, missing)['traceability']['configured']
    with api.session_factory() as s:
        before = s.scalar(select(func.count()).select_from(SpoolMaterialInspection))
        result = spool_boms.backfill_material_piece_records(s, batch_size=1)
        assert result['created_spools'] == 1 and result['created_pieces'] == 2
        s.commit()
        actor = s.get(api.application.Employee, spool_boms.BACKFILL_ACTOR)
        assert not actor.active and actor.role == 'misc'
        assert s.scalar(select(func.count()).select_from(SpoolMaterialInspection)) == before
        assert spool_boms.backfill_material_piece_records(s, batch_size=1)['created_spools'] == 0
        s.commit()
    assert receiving_detail(api, existing) == accepted
    rows = receiving_detail(api, missing)['traceability']['materials']
    assert all(row['persisted'] and not row['heat_number'] and not row['mtr_reference']
               and row['qa001']['status'] == 'pending' for row in rows)


def test_backfill_without_an_eligible_bom_does_not_create_a_system_identity(api):
    from spool_boms import BACKFILL_ACTOR, backfill_material_piece_records
    create_spool(api)
    with api.session_factory() as s:
        assert backfill_material_piece_records(s)['created_spools'] == 0
        assert s.get(api.application.Employee, BACKFILL_ACTOR) is None
