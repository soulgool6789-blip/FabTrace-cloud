"""Receiving may defer heat identity; post-fabrication checks may not."""
from copy import deepcopy

from sqlalchemy import select

from receiving_helpers import (accept_arrival, approve_materials, receiving_detail,
    record_arrival, save_receiving_materials, upload_receiving_bom)
from test_arrival_pass_readiness import pass_payload
from test_material_piece_qa_bulk import pass_all, pass_all_body
from test_order_labels import public_qr_url  # autouse physical-label fixture
from test_progress import database_state
from test_spool_bom_view_only import setup, shared_bom
from test_spool_receiving import create_spool
from tracking_helpers import ok


def deferred_spool(api, *, quantity=2):
    item_id = create_spool(api)
    upload_receiving_bom(api, item_id, quantity=quantity)
    return item_id, save_receiving_materials(api, item_id, heat='')


def test_piece_and_arrival_pass_can_explicitly_defer_heat_until_post_fabrication(api):
    from spool_receiving import SpoolArrivalInspection, SpoolMaterialInspection

    item_id, saved = deferred_spool(api)
    trace = saved['traceability']
    assert trace['receiving_complete'] and not trace['complete'] and not trace['heat_numbers_complete']
    assert trace['heat_required_for_receiving'] is False
    assert trace['heat_required_from_step'] == 15
    assert trace['heat_required_at_label'] == 'QA/QC-003 - Inspect Welds'
    assert all(not row['qa001']['pass_blockers'] for row in trace['materials'])
    assert record_arrival(api, item_id).status_code == 409, 'Real piece QA is still required'
    reviewed = approve_materials(api, item_id)
    assert all(row['qa001']['can_proceed'] for row in reviewed['traceability']['materials'])
    assert reviewed['arrival']['pass_blockers'] == []
    assert reviewed['arrival']['deferred_checks'] == ['heat_numbers']
    assert {row['key'] for row in reviewed['arrival']['checks_catalog']} == {'identity', 'bom', 'mtrs', 'condition'}
    assert 'heat' not in next(row['label'] for row in reviewed['arrival']['checks_catalog'] if row['key'] == 'mtrs').lower()
    accepted = ok(record_arrival(api, item_id), 201)
    arrival = accepted['arrival']
    assert arrival['can_proceed'] and arrival['latest']['checks']['heat_numbers'] is False
    assert arrival['latest']['deferred_checks'] == ['heat_numbers']
    assert arrival['latest']['checks_catalog'] == reviewed['arrival']['checks_catalog']
    assert len(arrival['latest']['heat_deferral']['pieces']) == 2
    assert arrival['latest']['heat_deferral']['required_from_step'] == 15
    assert all(not row['heat_number'] for row in accepted['traceability']['materials'])
    with api.session_factory() as session:
        inspection = session.scalar(select(SpoolArrivalInspection).where(SpoolArrivalInspection.spool_id == item_id))
        assert inspection.basis['checks_catalog'] == arrival['latest']['checks_catalog']
        assert inspection.basis['deferred_checks'] == ['heat_numbers']
        pieces = list(session.scalars(select(SpoolMaterialInspection).where(SpoolMaterialInspection.spool_id == item_id)))
        assert len(pieces) == 2 and all(row.basis['heat_deferral']['required_from_step'] == 15 for row in pieces)
        assert all(not row.basis['material']['heat_number'] for row in pieces)
    piece = accepted['traceability']['materials'][0]
    history = ok(api.get(piece['qa001']['history_url']))['history']
    assert history[0]['heat_deferral']['pieces'][0]['piece_key'] == piece['piece_key']


def test_pass_all_accepts_saved_mtrs_without_heat_and_keeps_each_piece_audited(api):
    item_id, saved = deferred_spool(api, quantity=3)
    passed = ok(pass_all(api, item_id, pass_all_body(saved)))
    assert passed['qa001_bulk_result']['passed_count'] == 3
    assert all(row['qa001']['can_proceed'] for row in passed['traceability']['materials'])
    assert passed['arrival']['latest'] is None and not passed['arrival']['can_proceed']
    again = ok(pass_all(api, item_id))
    assert again['qa001_bulk_result']['passed_count'] == 0
    assert again['qa001_bulk_result']['already_passed_count'] == 3
    for row in again['traceability']['materials']:
        history = ok(api.get(row['qa001']['history_url']))['history']
        assert len(history) == 1 and history[0]['heat_deferral']['pieces'][0]['piece_key'] == row['piece_key']


def test_deferred_heat_never_waives_current_qa_or_permits_false_heat_verification(api):
    item_id, _ = deferred_spool(api)
    before = database_state(api)
    missing_qa = record_arrival(api, item_id)
    assert missing_qa.status_code == 409
    assert 'current QA-001 Pass' in missing_qa.text
    assert database_state(api) == before
    approved = approve_materials(api, item_id)
    invalid = pass_payload(approved)
    invalid['checks']['heat_numbers'] = True
    before = database_state(api)
    response = api.post('/api/spool-boms/spools/' + item_id + '/arrival-inspections', invalid, role='inspector')
    assert response.status_code == 409
    assert 'Do not mark absent heat numbers as verified' in response.json()['detail']['receiving_blockers'][0]
    assert database_state(api) == before
    assert ok(record_arrival(api, item_id), 201)['arrival']['can_proceed']


def test_adding_heat_requires_fresh_piece_and_arrival_reviews_and_keeps_deferred_history(api):
    item_id, _ = deferred_spool(api)
    approve_materials(api, item_id)
    accepted = ok(record_arrival(api, item_id), 201)
    original = deepcopy(accepted['arrival']['latest'])
    changed = save_receiving_materials(api, item_id, heat='POST-FABRICATION-HEAT')
    assert changed['traceability']['complete'] and changed['traceability']['heat_numbers_complete']
    assert changed['arrival']['status'] == 'needs_reinspection'
    assert all(row['qa001']['status'] == 'needs_reinspection' for row in changed['traceability']['materials'])
    assert changed['arrival']['latest'] == original
    assert changed['arrival']['deferred_checks'] == []
    assert 'heat_numbers' in {row['key'] for row in changed['arrival']['checks_catalog']}
    assert record_arrival(api, item_id).status_code == 409
    approve_materials(api, item_id)
    reinspection = ok(record_arrival(api, item_id), 201)
    assert reinspection['arrival']['can_proceed']
    assert reinspection['arrival']['latest']['checks']['heat_numbers'] is True
    assert 'deferred_checks' not in reinspection['arrival']['latest']
    assert reinspection['arrival']['history'][1] == original
    assert 'heat_numbers' not in {row['key'] for row in original['checks_catalog']}
    for piece in reinspection['traceability']['materials']:
        history = ok(api.get(piece['qa001']['history_url']))['history']
        assert len(history) == 2 and 'heat_deferral' not in history[0] and history[1]['heat_deferral']


def test_complete_heat_evidence_keeps_legacy_shape_hashes_and_current_acceptance(api):
    from main import Item
    from spool_boms import physical_bom_state
    from spool_receiving import (SpoolArrivalInspection, SpoolMaterialInspection,
        _basis, _digest, _material_qa_bases)

    item_id = create_spool(api)
    accepted = accept_arrival(api, item_id)
    before = database_state(api)
    with api.session_factory() as session:
        state = physical_bom_state(session, item_id)
        bases = _material_qa_bases(session, state)
        pieces = list(session.scalars(select(SpoolMaterialInspection).where(SpoolMaterialInspection.spool_id == item_id)))
        for piece in pieces:
            assert set(bases[piece.piece_key]) == {'check_code', 'basis_version', 'spool_id', 'context',
                'current_bom_source', 'pinned_bom_source', 'documents', 'piece_key', 'material', 'mtr_document'}
            assert bases[piece.piece_key] == piece.basis
            assert _digest(bases[piece.piece_key]) == piece.basis_sha256
        evidence, blockers = _basis(session, session.get(Item, item_id))
        assert not blockers
        assert set(evidence) == {'spool_id', 'context', 'material_trace', 'current_bom_source',
            'pinned_bom_source', 'documents', 'mtr_documents', 'piece_inspections'}
        receipt = session.scalar(select(SpoolArrivalInspection).where(SpoolArrivalInspection.spool_id == item_id))
        assert evidence == receipt.basis
        assert _digest(evidence) == receipt.basis_sha256 == accepted['arrival']['basis_sha256']
    assert receiving_detail(api, item_id)['arrival']['can_proceed']
    assert database_state(api) == before


def test_post_fabrication_heat_helper_checks_only_exact_active_physical_scope(api):
    from main import Item
    from read_projection import read_projection
    from spool_boms import spool_heat_errors

    saved, children = setup(api, quantity=2)
    shared_bom(api, saved)
    foreign, foreign_children = setup(api, order='UNRELATED-HEAT-PO')
    shared_bom(api, foreign)
    first, second = children
    save_receiving_materials(api, first['id'], heat='POST-FAB-HEAT')
    before = database_state(api)
    with api.session_factory() as session:
        own = session.get(Item, first['id'])
        other = session.get(Item, second['id'])
        parent = session.get(Item, second['assembly_id'])
        with read_projection(session):
            assert spool_heat_errors(session, own) == []
            errors = spool_heat_errors(session, other)
            assert len(errors) == 3 and all(second['id'] in message for message in errors)
            assert all(foreign_children[0]['id'] not in message for message in errors)
            assert spool_heat_errors(session, parent) == errors
            assert spool_heat_errors(session, parent, include_children=False) == []
            errors.append('Caller-local note')
            assert 'Caller-local note' not in spool_heat_errors(session, parent)
    assert database_state(api) == before
    save_receiving_materials(api, second['id'], heat='SECOND-POST-FAB-HEAT')
    with api.session_factory() as session:
        assert spool_heat_errors(session, session.get(Item, second['assembly_id'])) == []
        assert spool_heat_errors(session, session.get(Item, foreign_children[0]['id']))


def test_post_fabrication_heat_helper_rejects_missing_register_and_changed_source(api):
    from main import Item
    from spool_boms import spool_heat_errors

    item_id = create_spool(api)
    with api.session_factory() as session:
        assert 'Save the physical material-piece register' in spool_heat_errors(session, session.get(Item, item_id))[0]
    accept_arrival(api, item_id)
    upload_receiving_bom(api, item_id, quantity=2)
    with api.session_factory() as session:
        errors = spool_heat_errors(session, session.get(Item, item_id))
        assert any('Adopt the current BOM' in message for message in errors)


def test_removed_tracked_spool_retains_read_access_without_resolving_its_bom(api, monkeypatch):
    import spool_boms
    from main import Item
    from test_removal_orders import change
    from tracking_helpers import make_spool

    item_id = make_spool(api, item_id='REMOVED-DEFERRED-HEAT')
    accepted = accept_arrival(api, item_id)
    change(api, 'item', item_id)
    before = database_state(api)

    def no_active_bom(*args, **kwargs):
        raise AssertionError('A removed record must not resolve an active physical BOM')

    monkeypatch.setattr(spool_boms, 'physical_bom_state', no_active_bom)
    with api.session_factory() as session:
        errors = spool_boms.spool_heat_errors(session, session.get(Item, item_id))
        assert errors and all('removed' in message.lower() for message in errors)
    item = ok(api.get('/api/items/' + item_id))
    assert item['receiving']['latest'] == accepted['arrival']['latest']
    assert item['receiving']['status'] == 'removed' and not item['can_mutate']
    tracked = ok(api.get('/api/tracking/spools/' + item_id))
    assert not tracked['can_mutate']
    admin = ok(api.get('/api/admin/items/' + item_id))
    assert admin['allowed_actions'] == []
    assert database_state(api) == before
