"""Saved BOM pages resolve exact physical pieces without changing evidence."""
import pytest

from receiving_helpers import accept_arrival, adopt_current_bom, upload_receiving_bom
from test_order_labels import generate, labels, public_qr_url
from test_progress import database_state
from test_removal_orders import change
from test_spool_documents import ROOT, bom_csv, requirement_path, request_upload, setup
from test_spool_receiving import create_spool
from tracking_helpers import ok


def physical_setup(api, *, number='MATERIAL-PAGE-PO', quantity=1):
    saved = setup(api, number=number, quantity=quantity)
    document = ok(request_upload(api, requirement_path(saved)))['active']['bom']
    generate(api, saved['order']['project_id'])
    return saved, document, labels(api, saved['order']['project_id'])['items']


def records(api, path, spool_id=None, role='admin'):
    return api.get(path + '/material-records', role=role,
        params={'spool_id': spool_id} if spool_id is not None else {})


def test_physical_saved_bom_opens_distinct_records_and_alias_without_writes(api):
    _, document, children = physical_setup(api)
    child = children[0]
    before = database_state(api)
    view = ok(records(api, ROOT + '/spools/' + child['id']))
    assert view['selected_spool_id'] == child['id'] and not view['selection_required']
    assert view['document_id'] == document['id'] and view['record_matches_document']
    assert view['source_match']['reason_code'] == 'matched'
    assert view['source_match']['effective_matches_document'] and view['source_match']['pinned_matches_document']
    assert view['spools'] == [{'item_id': child['id'], 'display_code': child['display_code'],
        'spool_number': child['spool_number'], 'assembly_id': child['assembly_id']}]
    record = view['record']
    assert record['context']['item_id'] == child['id']
    assert record['context']['display_code'] == child['display_code']
    rows = record['traceability']['materials']
    assert len(rows) == 3 and len({row['piece_identifier'] for row in rows}) == 3
    assert [row['piece_number'] for row in rows] == [1, 2, 1]
    assert all(row['persisted'] and row['qa001']['status'] == 'pending' for row in rows)
    assert database_state(api) == before


def test_requirement_without_physical_spools_does_not_invent_records(api):
    saved = setup(api, quantity=1)
    path = requirement_path(saved)
    document = ok(request_upload(api, path))['active']['bom']
    before = database_state(api)
    view = ok(records(api, path))
    assert view['document_id'] == document['id']
    assert view['spools'] == [] and view['selected_spool_id'] is None
    assert view['selection_required'] and view['record'] is None and not view['record_matches_document']
    assert view['source_match']['reason_code'] == 'no_physical_spools'
    assert database_state(api) == before


def test_shared_requirement_demands_selection_and_never_inherits_sibling_approval(api):
    saved, _, children = physical_setup(api, quantity=2)
    path = requirement_path(saved)
    accepted = accept_arrival(api, children[0]['id'])
    before = database_state(api)
    unselected = ok(records(api, path))
    assert unselected['selection_required'] and unselected['record'] is None
    assert unselected['source_match']['reason_code'] == 'selection_required'
    assert {row['item_id'] for row in unselected['spools']} == {row['id'] for row in children}
    first = ok(records(api, path, children[0]['id']))
    second = ok(records(api, path, children[1]['id']))
    assert first['record']['arrival']['latest'] == accepted['arrival']['latest']
    assert first['record']['arrival']['can_proceed']
    assert all(row['qa001']['can_proceed'] for row in first['record']['traceability']['materials'])
    assert not second['record']['arrival']['can_proceed']
    assert all(row['qa001']['status'] == 'pending' and not row['heat_number']
        for row in second['record']['traceability']['materials'])
    assert database_state(api) == before


def test_single_registered_copy_is_selected_for_requirement(api):
    saved, _, children = physical_setup(api)
    view = ok(records(api, requirement_path(saved)))
    assert view['selected_spool_id'] == children[0]['id']
    assert not view['selection_required'] and view['record_matches_document']


def test_foreign_same_number_and_unregistered_selections_are_rejected(api):
    saved, _, children = physical_setup(api)
    _, _, foreign = physical_setup(api, number='OTHER-MATERIAL-PAGE-PO')
    unregistered = create_spool(api, 'UNREGISTERED-SAME-NUMBER', children[0]['spool_number'])
    before = database_state(api)
    for target in (foreign[0]['id'], unregistered, 'DOES-NOT-EXIST'):
        assert records(api, requirement_path(saved), target).status_code == 404
        assert records(api, ROOT + '/spools/' + children[0]['id'], target).status_code == 404
    assert database_state(api) == before


@pytest.mark.parametrize('role', ['welder', 'handler', 'inspector'])
def test_material_record_read_respects_existing_edit_and_qa_permissions(api, role):
    _, _, children = physical_setup(api)
    path = ROOT + '/spools/' + children[0]['id']
    before = database_state(api)
    record = ok(records(api, path, role=role))['record']
    assert record['traceability']['editable'] is (role in ('handler', 'inspector'))
    assert all(row['qa001']['permissions']['can_inspect'] is (role == 'inspector')
        for row in record['traceability']['materials'])
    assert records(api, path, role=None).status_code == 401
    assert database_state(api) == before


def test_removed_copy_is_excluded_and_released_copy_remains_read_only(api):
    from test_admin import release
    saved, _, children = physical_setup(api, quantity=2)
    removed, released = children
    change(api, 'item', removed['assembly_id'])
    accept_arrival(api, released['id'])
    release(api, released['id'])
    before = database_state(api)
    view = ok(records(api, requirement_path(saved)))
    assert view['selected_spool_id'] == released['id'] and len(view['spools']) == 1
    assert view['record_matches_document']
    assert not view['record']['traceability']['editable']
    assert not view['record']['arrival']['permissions']['can_inspect']
    assert all(not row['qa001']['permissions']['can_inspect'] for row in view['record']['traceability']['materials'])
    assert records(api, requirement_path(saved), removed['id']).status_code == 404
    assert records(api, ROOT + '/spools/' + removed['id']).status_code == 409
    assert database_state(api) == before


def test_individual_override_cannot_display_its_approval_on_shared_bom(api):
    saved, shared, children = physical_setup(api)
    child = children[0]
    upload_receiving_bom(api, child['id'], part='INDIVIDUAL-MATERIAL')
    adopt_current_bom(api, child['id'])
    accepted = accept_arrival(api, child['id'])
    local_id = accepted['source_status']['pinned']['document_id']
    before = database_state(api)
    shared_view = ok(records(api, requirement_path(saved)))
    assert shared_view['document_id'] == shared['id']
    assert not shared_view['record_matches_document']
    assert shared_view['source_match']['reason_code'] == 'individual_override'
    assert shared_view['source_match']['effective_document_id'] == local_id
    assert shared_view['source_match']['record_document_id'] == local_id
    assert shared_view['record']['arrival']['latest'] == accepted['arrival']['latest']
    local_view = ok(records(api, ROOT + '/spools/' + child['id']))
    assert local_view['document_id'] == local_id and local_view['record_matches_document']
    assert database_state(api) == before


def test_new_document_never_matches_old_pinned_rows_and_history_is_identifiable(api):
    saved, original, children = physical_setup(api)
    child = children[0]
    accepted = accept_arrival(api, child['id'])
    current = ok(request_upload(api, requirement_path(saved), version=1,
        files=[('revision-b.csv', bom_csv(quantity=3), 'text/csv')]))['active']['bom']
    before = database_state(api)
    view = ok(records(api, ROOT + '/spools/' + child['id']))
    assert view['document_id'] == current['id'] != original['id']
    assert not view['record_matches_document']
    assert view['source_match']['reason_code'] == 'pinned_revision'
    assert view['source_match']['effective_document_id'] == current['id']
    assert view['source_match']['pinned_document_id'] == original['id']
    assert view['record']['arrival']['latest'] == accepted['arrival']['latest']
    assert view['record']['arrival']['status'] == 'needs_reinspection'
    assert database_state(api) == before
    adopt_current_bom(api, child['id'])
    adopted = ok(records(api, requirement_path(saved)))
    assert adopted['record_matches_document'] and adopted['document_id'] == current['id']
    assert adopted['document_id'] != original['id'], 'Historical file viewers can reject a current-record response by exact file ID'
    assert all(row['qa001']['status'] == 'pending' for row in adopted['record']['traceability']['materials'])


def test_missing_or_unstructured_bom_has_no_false_material_match(api):
    from test_spool_documents import pdf
    item_id = create_spool(api)
    path = ROOT + '/spools/' + item_id
    before = database_state(api)
    missing = ok(records(api, path))
    assert missing['document_id'] is None and not missing['record_matches_document']
    assert missing['record']['traceability']['materials'] == []
    assert missing['source_match']['reason_code'] == 'no_document'
    assert database_state(api) == before
    ok(request_upload(api, path, files=[('BOM-scan.pdf', pdf(), 'application/pdf')]))
    before = database_state(api)
    source = ok(records(api, path))
    assert source['document_id'] and not source['record_matches_document']
    assert source['source_match']['reason_code'] == 'unavailable'
    assert source['record']['traceability']['materials'] == []
    assert database_state(api) == before
