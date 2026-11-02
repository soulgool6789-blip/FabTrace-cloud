"""Heat and MTR evidence may be deferred at receiving, with an audited deadline."""
from copy import deepcopy

import pytest
from sqlalchemy import select

from conftest import BADGES
from receiving_helpers import (approve_materials, receiving_detail, record_arrival,
    save_receiving_materials, upload_receiving_bom)
from test_arrival_pass_readiness import pass_payload
from test_material_piece_qa import decide, edit_piece
from test_material_piece_qa_bulk import pass_all, pass_all_body
from test_order_labels import public_qr_url  # autouse physical-label fixture
from test_progress import database_state
from test_spool_bom_view_only import setup, shared_bom
from test_spool_receiving import create_spool
from tracking_helpers import ok


def deferred_spool(api, *, quantity=2, heat=''):
    item_id = create_spool(api)
    upload_receiving_bom(api, item_id, quantity=quantity)
    if heat:
        return item_id, save_receiving_materials(api, item_id, heat=heat, reference='')
    return item_id, receiving_detail(api, item_id)


def test_blank_heat_and_mtr_allow_real_piece_bulk_and_arrival_decisions_with_honest_history(api):
    from spool_receiving import SpoolArrivalInspection, SpoolMaterialInspection

    item_id, saved = deferred_spool(api, quantity=3)
    trace = saved['traceability']
    assert trace['receiving_complete'] and not trace['complete']
    assert not trace['heat_numbers_complete'] and not trace['mtr_references_complete']
    for name in ('heat', 'mtr'):
        assert trace[name + '_required_for_receiving'] is False
        assert trace[name + '_required_from_step'] == 15
        assert trace[name + '_required_at_label'] == 'QA/QC-003 - Inspect Welds'
    assert all(row['persisted'] and row['qa001']['latest'] is None for row in trace['materials'])
    assert all(not row['qa001']['pass_blockers'] for row in trace['materials'])
    assert saved['arrival']['latest'] is None and not saved['arrival']['can_proceed']
    assert record_arrival(api, item_id).status_code == 409, 'Actual QA-001 approval is still required'

    individual = ok(decide(api, item_id, trace['materials'][0]), 201)
    passed = ok(pass_all(api, item_id, pass_all_body(individual)))
    assert passed['qa001_bulk_result']['passed_count'] == 2
    assert passed['qa001_bulk_result']['already_passed_count'] == 1
    assert passed['traceability']['materials'][0]['qa001']['latest'] == individual['traceability']['materials'][0]['qa001']['latest']
    assert all(row['qa001']['can_proceed'] for row in passed['traceability']['materials'])
    assert passed['arrival']['latest'] is None
    assert passed['arrival']['pass_blockers'] == []
    assert passed['arrival']['deferred_checks'] == ['heat_numbers', 'mtrs']
    assert [check['key'] for check in passed['arrival']['checks_catalog']] == ['identity', 'bom', 'condition']

    accepted = ok(record_arrival(api, item_id), 201)
    arrival = accepted['arrival']
    assert arrival['can_proceed']
    assert arrival['latest']['checks'] == {
        'identity': True, 'bom': True, 'heat_numbers': False, 'mtrs': False, 'condition': True}
    assert arrival['latest']['deferred_checks'] == ['heat_numbers', 'mtrs']
    assert arrival['latest']['checks_catalog'] == passed['arrival']['checks_catalog']
    assert all(not row['heat_number'] and not row['mtr_reference'] for row in accepted['traceability']['materials'])
    with api.session_factory() as session:
        receipt = session.scalar(select(SpoolArrivalInspection).where(SpoolArrivalInspection.spool_id == item_id))
        pieces = list(session.scalars(select(SpoolMaterialInspection).where(SpoolMaterialInspection.spool_id == item_id)))
        assert len(pieces) == 3 and len({row.id for row in pieces}) == 3
        assert all(row.actor == BADGES['inspector'] and row.result == 'Pass' for row in pieces)
        for name in ('heat_deferral', 'mtr_deferral'):
            assert len(receipt.basis[name]['pieces']) == 3
            assert receipt.basis[name]['required_from_step'] == 15
            assert arrival['latest'][name] == receipt.basis[name]
            assert all(row.basis[name]['pieces'] == [{
                'piece_key': row.piece_key, 'piece_identifier': row.basis['material']['piece_identifier']}]
                for row in pieces)
    piece = accepted['traceability']['materials'][0]
    history = ok(api.get(piece['qa001']['history_url']))['history']
    assert len(history) == 1 and history[0]['heat_deferral'] and history[0]['mtr_deferral']


@pytest.mark.parametrize('heat', ['', 'RECORDED-HEAT'], ids=['both-deferred', 'only-mtr-deferred'])
def test_missing_mtr_cannot_be_claimed_verified_and_actual_remaining_checks_stay_required(api, heat):
    item_id, saved = deferred_spool(api, quantity=1, heat=heat)
    approved = approve_materials(api, item_id)
    arrival = approved['arrival']
    assert arrival['deferred_checks'] == (['heat_numbers'] if not heat else []) + ['mtrs']
    assert ('heat_numbers' in {row['key'] for row in arrival['checks_catalog']}) == bool(heat)
    assert 'mtrs' not in {row['key'] for row in arrival['checks_catalog']}
    path = '/api/spool-boms/spools/' + item_id + '/arrival-inspections'
    before = database_state(api)
    false_mtr = pass_payload(approved)
    false_mtr['checks']['mtrs'] = True
    response = api.post(path, false_mtr, role='inspector')
    assert response.status_code == 409
    assert 'Do not mark missing MTRs as verified' in response.text
    missing_check = pass_payload(approved)
    missing_check['checks']['heat_numbers' if heat else 'condition'] = False
    response = api.post(path, missing_check, role='inspector')
    assert response.status_code == 409 and 'Confirm every arrival inspection check' in response.text
    assert database_state(api) == before
    accepted = ok(api.post(path, pass_payload(approved), role='inspector'), 201)
    latest = accepted['arrival']['latest']
    assert latest['checks']['heat_numbers'] is bool(heat) and latest['checks']['mtrs'] is False
    assert ('heat_deferral' in latest) == (not heat)
    assert latest['mtr_deferral']['pieces'][0]['piece_key'] == saved['traceability']['materials'][0]['piece_key']


def test_later_mtr_entry_stales_only_affected_piece_and_retains_original_deferred_decision(api):
    item_id, _ = deferred_spool(api)
    approve_materials(api, item_id)
    accepted = ok(record_arrival(api, item_id), 201)
    original = deepcopy(accepted['arrival']['latest'])
    original_pieces = deepcopy(accepted['traceability']['materials'])

    changed = edit_piece(api, item_id, 0, mtr_reference='LATER-MTR-A')
    first, second = changed['traceability']['materials']
    assert first['qa001']['status'] == 'needs_reinspection'
    assert second['qa001']['can_proceed'] and second['qa001']['latest'] == original_pieces[1]['qa001']['latest']
    assert changed['arrival']['status'] == 'needs_reinspection'
    assert changed['arrival']['latest'] == original
    assert changed['arrival']['mtr_deferral']['pieces'] == [{
        'piece_key': second['piece_key'], 'piece_identifier': second['piece_identifier']}]
    before = database_state(api)
    assert decide(api, item_id, original_pieces[0]).status_code == 409
    assert record_arrival(api, item_id).status_code == 409
    assert database_state(api) == before
    reviewed = ok(decide(api, item_id, first), 201)
    first_decision = deepcopy(reviewed['traceability']['materials'][0]['qa001']['latest'])

    changed = edit_piece(api, item_id, 1, mtr_reference='LATER-MTR-B')
    assert changed['traceability']['mtr_references_complete']
    assert changed['traceability']['receiving_complete'] and not changed['traceability']['complete']
    assert changed['traceability']['materials'][0]['qa001']['latest'] == first_decision
    assert changed['traceability']['materials'][0]['qa001']['can_proceed']
    assert changed['traceability']['materials'][1]['qa001']['status'] == 'needs_reinspection'
    assert changed['arrival']['deferred_checks'] == ['heat_numbers']
    assert changed['arrival']['mtr_deferral'] is None
    assert 'mtrs' in {row['key'] for row in changed['arrival']['checks_catalog']}
    approve_materials(api, item_id)
    reinspected = ok(record_arrival(api, item_id), 201)
    assert reinspected['arrival']['can_proceed']
    assert reinspected['arrival']['latest']['checks']['mtrs'] is True
    assert 'mtr_deferral' not in reinspected['arrival']['latest']
    assert reinspected['arrival']['history'][1] == original
    assert 'mtrs' not in {row['key'] for row in original['checks_catalog']}
    for piece in reinspected['traceability']['materials']:
        history = ok(api.get(piece['qa001']['history_url']))['history']
        assert len(history) == 2
        assert 'mtr_deferral' not in history[0] and history[1]['mtr_deferral']


def test_deferral_keeps_qa_authority_and_current_bom_adoption_guards(api):
    item_id, saved = deferred_spool(api)
    before = database_state(api)
    assert decide(api, item_id, saved['traceability']['materials'][0], role='handler').status_code == 403
    assert pass_all(api, item_id, role='handler').status_code == 403
    assert record_arrival(api, item_id, role='handler').status_code == 403
    assert database_state(api) == before
    upload_receiving_bom(api, item_id, quantity=3, part='NEEDS-ADOPTION')
    changed = receiving_detail(api, item_id)
    assert changed['source_status']['changed'] and not changed['traceability']['receiving_complete']
    before = database_state(api)
    response = decide(api, item_id, changed['traceability']['materials'][0])
    assert response.status_code == 409 and 'current BOM' in response.text
    response = pass_all(api, item_id)
    assert response.status_code == 409 and 'Adopt' in response.text
    response = record_arrival(api, item_id)
    assert response.status_code == 409 and 'Adopt' in response.text
    assert database_state(api) == before


def test_post_fabrication_helper_requires_mtrs_for_exact_active_copy_and_retains_cache_isolation(api):
    from main import Item
    from read_projection import read_projection
    from spool_boms import spool_heat_errors

    saved, children = setup(api, quantity=2)
    shared_bom(api, saved)
    foreign, foreign_children = setup(api, order='UNRELATED-MTR-PO')
    shared_bom(api, foreign)
    first, second = children
    save_receiving_materials(api, first['id'], heat='KNOWN-HEAT', reference='')
    save_receiving_materials(api, second['id'])
    before = database_state(api)
    with api.session_factory() as session:
        with read_projection(session):
            errors = spool_heat_errors(session, session.get(Item, first['id']))
            assert len(errors) == 3 and all(first['id'] in message and 'MTR reference' in message for message in errors)
            assert all('heat number' not in message for message in errors)
            assert all(foreign_children[0]['id'] not in message for message in errors)
            parent = session.get(Item, first['assembly_id'])
            assert spool_heat_errors(session, parent) == errors
            assert spool_heat_errors(session, parent, include_children=False) == []
            assert spool_heat_errors(session, session.get(Item, second['id'])) == []
            errors.append('Caller-local note')
            assert 'Caller-local note' not in spool_heat_errors(session, parent)
    assert database_state(api) == before
    completed = save_receiving_materials(api, first['id'], heat='KNOWN-HEAT', reference='LATER-MTR')
    assert completed['traceability']['complete'] and completed['arrival']['latest'] is None
    with api.session_factory() as session:
        assert spool_heat_errors(session, session.get(Item, first['assembly_id'])) == []
        assert spool_heat_errors(session, session.get(Item, foreign_children[0]['id']))


def test_heat_only_acceptance_keeps_its_signed_schema_catalog_and_history(api):
    from main import Item
    from spool_boms import physical_bom_state
    from spool_receiving import (SpoolArrivalInspection, SpoolMaterialInspection,
        _basis, _digest, _material_qa_bases)

    item_id, _ = deferred_spool(api)
    save_receiving_materials(api, item_id, heat='', reference='EXISTING-MTR')
    approve_materials(api, item_id)
    accepted = ok(record_arrival(api, item_id), 201)
    latest = deepcopy(accepted['arrival']['latest'])
    assert latest['deferred_checks'] == ['heat_numbers'] and 'mtr_deferral' not in latest
    assert next(row['label'] for row in latest['checks_catalog'] if row['key'] == 'mtrs') == (
        'The MTRs have been checked against the materials and current MTR references')
    before = database_state(api)
    with api.session_factory() as session:
        state = physical_bom_state(session, item_id)
        bases = _material_qa_bases(session, state)
        pieces = list(session.scalars(select(SpoolMaterialInspection).where(SpoolMaterialInspection.spool_id == item_id)))
        for piece in pieces:
            assert set(bases[piece.piece_key]) == {'check_code', 'basis_version', 'spool_id', 'context',
                'current_bom_source', 'pinned_bom_source', 'documents', 'piece_key', 'material', 'mtr_document', 'heat_deferral'}
            assert bases[piece.piece_key] == piece.basis
            assert _digest(bases[piece.piece_key]) == piece.basis_sha256
        evidence, blockers = _basis(session, session.get(Item, item_id))
        assert not blockers
        assert set(evidence) == {'spool_id', 'context', 'material_trace', 'current_bom_source',
            'pinned_bom_source', 'documents', 'mtr_documents', 'piece_inspections',
            'heat_deferral', 'deferred_checks', 'checks_catalog'}
        receipt = session.scalar(select(SpoolArrivalInspection).where(SpoolArrivalInspection.spool_id == item_id))
        assert evidence == receipt.basis
        assert _digest(evidence) == receipt.basis_sha256 == accepted['arrival']['basis_sha256']
    current = receiving_detail(api, item_id)
    assert current['arrival']['can_proceed'] and current['arrival']['latest'] == latest
    assert database_state(api) == before
