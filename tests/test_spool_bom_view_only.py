"""A physical PDF remains viewable without hiding its setup material list."""
import importlib
import io

from openpyxl import Workbook
from sqlalchemy import func, select

from receiving_helpers import (accept_arrival, adopt_current_bom, receiving_detail,
                               record_arrival)
# public_qr_url is the autouse fixture required for physical label generation.
from test_order_labels import generate, labels, public_qr_url
from test_order_setup import branch, create_setup
from test_progress import database_state
from test_spool_documents import pdf, request_upload, requirement_path
from tracking_helpers import ok


NUMBER = '643-777-PCW-03-01'


def setup(api, *, order='VIEW-ONLY-PO', quantity=1):
    saved = create_setup(api, number=order, assemblies=[branch('643-777-PCW-03', quantity, [
        {'spool_number': NUMBER, 'quantity_per_assembly': 1, 'welds_per_spool': 2}])])
    generate(api, saved['order']['project_id'])
    return saved, labels(api, saved['order']['project_id'])['items']


def structured_file(quantity=2, unit='EA'):
    book = Workbook()
    sheet = book.active
    sheet.append(['spool_number', 'item', 'quantity', 'unit', 'part_number', 'description', 'material'])
    sheet.append([NUMBER, 1, quantity, unit, '100708', 'Weldneck flange', 'A105'])
    sheet.append([NUMBER, 2, 1, 'EA', '102391', 'Pipe', 'A53B'])
    content = io.BytesIO()
    book.save(content)
    return (NUMBER + '_BOM.xlsx', content.getvalue(),
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def shared_bom(api, saved, *, quantity=2, version=0):
    return ok(request_upload(api, requirement_path(saved), version=version,
        files=[structured_file(quantity)]))['active']['bom']


def local_pdf(api, child, *, version=0, pages=3):
    return ok(request_upload(api, '/api/spool-documents/spools/' + child['id'], version=version,
        files=[('643-777.pdf', pdf(pages), 'application/pdf')]))['active']['bom']


def test_startup_backfill_restores_copy003_material_rows_without_any_acceptance(api, monkeypatch):
    import spool_boms
    import spool_documents
    from spool_receiving import SpoolArrivalInspection, SpoolMaterialInspection

    # Reproduce pre-fix records: the local PDF and shared XLSX already exist,
    # but automatic material initialization could not see the shared list.
    with monkeypatch.context() as old:
        old.setattr(spool_boms, 'ensure_material_piece_records', lambda *args, **kwargs: 0)
        saved, children = setup(api, quantity=3)
        child = children[2]
        viewed = local_pdf(api, child)
        material = shared_bom(api, saved)
    assert child['display_code'] == NUMBER + '-[003]'
    before = database_state(api)
    preview = receiving_detail(api, child['id'])
    assert not preview['traceability']['configured']
    assert len(preview['traceability']['materials']) == 3
    assert database_state(api) == before, 'Reading the resolved BOM must not initialize records'

    initializer = importlib.import_module('init_db')
    monkeypatch.setattr(initializer, 'engine', api.session_factory.kw['bind'])
    initializer.initialize()
    after = receiving_detail(api, child['id'])
    source = after['source_status']
    assert source['uses_shared_structured_bom']
    assert source['current']['document_id'] == source['pinned']['document_id'] == material['id']
    assert source['viewed_bom']['document_id'] == viewed['id']
    assert source['viewed_bom']['filename'] == '643-777.pdf'
    assert api.get(source['viewed_bom']['view_url']).content == pdf(3)
    assert source['current']['filename'] == NUMBER + '_BOM.xlsx'
    assert not source['changed']
    assert after['line_count'] == 2 and after['total_pieces'] == 3
    rows = after['traceability']['materials']
    assert len({row['piece_identifier'] for row in rows}) == 3
    assert all(row['persisted'] and not row['heat_number'] and not row['mtr_reference']
               and row['qa001']['status'] == 'pending' for row in rows)
    assert not after['arrival']['can_proceed'] and after['arrival']['latest'] is None
    assert record_arrival(api, child['id']).status_code == 409
    with api.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(SpoolArrivalInspection)) == 0
        assert session.scalar(select(func.count()).select_from(SpoolMaterialInspection)) == 0
        actor = session.get(api.application.Employee, spool_boms.BACKFILL_ACTOR)
        assert actor.role == 'misc' and not actor.active
        basis = spool_documents.spool_document_scope_basis(session, child['id'])
        files = spool_documents.spool_document_packet_files(session, child['id'])
        assert {row['document_id'] for row in basis} == {viewed['id'], material['id']}
        assert {row['document_id'] for row in files} == {viewed['id'], material['id']}
        assert len(files) == 2
    current = database_state(api)
    initializer.initialize()
    assert database_state(api) == current, 'The existing startup backfill must remain idempotent'

    path = '/api/spool-documents/spools/' + child['id']
    document_page = ok(api.get(path + '/material-records'))
    assert document_page['document_id'] == viewed['id']
    assert not document_page['record_matches_document']
    assert document_page['source_match']['reason_code'] == 'shared_material_source'
    shared_page = ok(api.get(requirement_path(saved) + '/material-records', params={'spool_id': child['id']}))
    assert shared_page['record_matches_document']
    assert api.get(path + '/material-records', role=None).status_code == 401


def test_new_shared_upload_initializes_blank_records_behind_existing_pdf(api):
    saved, children = setup(api)
    child = children[0]
    viewed = local_pdf(api, child)
    assert not receiving_detail(api, child['id'])['bom_available']
    material = shared_bom(api, saved)
    after = receiving_detail(api, child['id'])
    assert after['source_status']['viewed_bom']['document_id'] == viewed['id']
    assert after['source_status']['current']['document_id'] == material['id']
    assert after['traceability']['configured']
    assert len(after['traceability']['materials']) == 3
    assert all(not row['heat_number'] and row['qa001']['latest'] is None
               for row in after['traceability']['materials'])
    assert not after['arrival']['can_proceed']


def test_structured_local_bom_keeps_priority_and_requires_adoption_of_existing_pin(api):
    saved, children = setup(api, quantity=2)
    shared = shared_bom(api, saved)
    child, sibling = children
    sibling_before = receiving_detail(api, sibling['id'])
    viewed = local_pdf(api, child)
    path = '/api/spool-documents/spools/' + child['id']
    local = ok(request_upload(api, path, version=1, files=[structured_file(4)]))['active']['bom']
    current = receiving_detail(api, child['id'])
    assert current['source_status']['current']['document_id'] == local['id']
    assert current['source_status']['viewed_bom']['document_id'] == local['id']
    assert not current['source_status']['uses_shared_structured_bom']
    assert current['source_status']['pinned']['document_id'] == shared['id']
    assert current['source_status']['changed']
    assert current['total_pieces'] == 3, 'Saved rows must stay on their original material definition'
    adopted = adopt_current_bom(api, child['id'])
    assert adopted['total_pieces'] == 5 and not adopted['source_status']['changed']
    assert adopted['source_status']['pinned']['document_id'] == local['id']
    assert all(not row['heat_number'] and row['qa001']['latest'] is None
               for row in adopted['traceability']['materials'])
    assert api.get(viewed['view_url']).status_code == 200
    assert receiving_detail(api, sibling['id']) == sibling_before


def test_pdf_without_current_shared_structure_does_not_use_catalog_or_other_po(api):
    foreign, _ = setup(api, order='OTHER-PO')
    shared_bom(api, foreign)
    _, children = setup(api)
    child = children[0]
    # This number has a built-in reference BOM, but an uploaded current PDF
    # must not silently resurrect that older material basis.
    assert receiving_detail(api, child['id'])['bom_available']
    local_pdf(api, child)
    view = receiving_detail(api, child['id'])
    assert not view['bom_available'] and not view['source_status']['uses_shared_structured_bom']
    assert not view['traceability']['configured'] and view['traceability']['materials'] == []
    assert record_arrival(api, child['id']).status_code == 409


def test_invalid_structured_local_quantity_remains_a_blocker_instead_of_using_shared(api):
    saved, children = setup(api)
    shared = shared_bom(api, saved)
    child = children[0]
    path = '/api/spool-documents/spools/' + child['id']
    invalid = ok(request_upload(api, path, files=[structured_file(1.5)]))['active']['bom']
    view = receiving_detail(api, child['id'])
    assert view['source_status']['current']['document_id'] == invalid['id']
    assert view['source_status']['pinned']['document_id'] == shared['id']
    assert not view['source_status']['uses_shared_structured_bom']
    assert not view['source_status']['adoptable']
    assert 'whole-piece quantity' in view['source_status']['blocked_reason']
    assert record_arrival(api, child['id']).status_code == 409


def test_shared_revision_keeps_pinned_materials_and_requires_explicit_adoption(api):
    saved, children = setup(api)
    original = shared_bom(api, saved)
    child = children[0]
    viewed = local_pdf(api, child)
    accepted = accept_arrival(api, child['id'])
    assert accepted['arrival']['can_proceed'] and accepted['arrival']['latest']['result'] == 'Pass'
    assert all(row['qa001']['can_proceed'] for row in accepted['traceability']['materials'])
    assert accepted['source_status']['viewed_bom']['document_id'] == viewed['id']
    assert accepted['source_status']['pinned']['document_id'] == original['id']
    changed = shared_bom(api, saved, version=1, quantity=3)
    view = receiving_detail(api, child['id'])
    assert view['source_status']['viewed_bom']['document_id'] == viewed['id']
    assert view['source_status']['current']['document_id'] == changed['id']
    assert view['source_status']['pinned']['document_id'] == original['id']
    assert view['source_status']['changed'] and view['source_status']['can_adopt']
    assert view['arrival']['latest'] == accepted['arrival']['latest']
    assert view['arrival']['status'] == 'needs_reinspection'
    assert [row['heat_number'] for row in view['traceability']['materials']] == ['HEAT-LOCAL-1'] * 3
    assert record_arrival(api, child['id']).status_code == 409
    adopted = adopt_current_bom(api, child['id'])
    assert len(adopted['traceability']['materials']) == 4
    assert all(not row['heat_number'] and not row['mtr_reference']
               and row['qa001']['latest'] is None for row in adopted['traceability']['materials'])
    assert adopted['arrival']['latest'] == accepted['arrival']['latest']
    assert not adopted['arrival']['can_proceed']


def test_pdf_revision_invalidates_only_its_copy_qa_without_replacing_material_values(api):
    saved, children = setup(api, quantity=2)
    material = shared_bom(api, saved)
    child, sibling = children
    old_pdf = local_pdf(api, child)
    accepted = accept_arrival(api, child['id'])
    other = accept_arrival(api, sibling['id'])
    updated_pdf = local_pdf(api, child, version=1, pages=4)
    view = receiving_detail(api, child['id'])
    assert view['source_status']['current']['document_id'] == material['id']
    assert view['source_status']['pinned']['document_id'] == material['id']
    assert not view['source_status']['changed']
    assert view['source_status']['viewed_bom']['document_id'] == updated_pdf['id']
    assert view['arrival']['status'] == 'needs_reinspection'
    assert view['arrival']['latest'] == accepted['arrival']['latest']
    assert view['arrival']['basis_sha256'] != accepted['arrival']['basis_sha256']
    assert all(row['qa001']['status'] == 'needs_reinspection' for row in view['traceability']['materials'])
    assert [row['heat_number'] for row in view['traceability']['materials']] == ['HEAT-LOCAL-1'] * 3
    assert api.get(old_pdf['view_url']).content == pdf(3)
    assert api.get(updated_pdf['view_url']).content == pdf(4)
    assert receiving_detail(api, sibling['id']) == other
    assert record_arrival(api, child['id']).status_code == 409


def test_latest_shared_view_only_revision_never_uses_older_structured_history(api):
    saved, children = setup(api)
    original = shared_bom(api, saved)
    child = children[0]
    local = local_pdf(api, child)
    ok(request_upload(api, requirement_path(saved), version=1,
        files=[('shared-new-revision.pdf', pdf(5), 'application/pdf')]))
    view = receiving_detail(api, child['id'])
    assert not view['source_status']['uses_shared_structured_bom']
    assert view['source_status']['current']['document_id'] == local['id']
    assert view['source_status']['pinned']['document_id'] == original['id']
    assert view['source_status']['changed'] and not view['source_status']['adoptable']
    assert record_arrival(api, child['id']).status_code == 409
