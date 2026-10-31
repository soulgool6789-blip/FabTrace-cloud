"""Upload scope, complete drawing pages, and immutable spool document revisions."""
import csv
import importlib
import io
from hashlib import sha256

import pytest
from openpyxl import Workbook
from PIL import Image
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from fastapi import HTTPException

from conftest import BADGES
from tracking_helpers import ok
from test_order_labels import generate, labels, public_qr_url
from test_order_setup import branch, create_setup, detail, edit_body
from test_progress import database_state
from test_removal_orders import change


ROOT = '/api/spool-documents'
NUMBER = '643-712-A-PCW-01-01'


def setup(api, number='DOC-PO-001', quantity=2):
    return create_setup(api, number=number, assemblies=[branch('643-712-A-PCW-01', quantity, [
        {'spool_number': NUMBER, 'quantity_per_assembly': 1, 'welds_per_spool': 2}])])


def requirement_path(saved):
    return ROOT + '/requirements/' + saved['assemblies'][0]['spools'][0]['id']


def bom_csv(number=NUMBER, quantity=2):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['spool_number', 'item', 'quantity', 'unit', 'part_number', 'description', 'material', 'length', 'notes'])
    writer.writerow([number, 1, quantity, 'EA', '000123', 'Weldneck flange', 'A105', '', 'Drawing sheet 2'])
    writer.writerow([number, 2, 1, 'EA', '000456', 'Pipe', 'A53B', '16 3/4 in', 'One physical spool'])
    return output.getvalue().encode()


def pdf(pages=3):
    writer = PdfWriter()
    for index in range(pages):
        writer.add_blank_page(width=600 + index, height=800 + index)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def request_upload(api, path, files=None, kind='bom', version=0, role='admin', **fields):
    files = files or [('BOM.csv', bom_csv(), 'text/csv')]
    attached = [('files', value) for value in files]
    preview = api.request('POST', path + '/preview', role=role, data={
        'kind': kind, 'sheet': fields.get('sheet', '')}, files=attached)
    if preview.status_code != 200:
        return preview
    return api.request('POST', path + '/upload', role=role,
        data={'kind': kind, 'expected_version': str(version),
              'expected_sha256': preview.json()['selection_sha256'],
              'revision': '2', 'reason': 'Upload reviewed reference for this spool', **fields}, files=attached)


def test_preview_is_read_only_upload_retains_grid_original_and_does_not_create_production(api):
    saved = setup(api)
    path = requirement_path(saved)
    before = database_state(api)
    empty = ok(api.get(path))
    assert empty['version'] == 0 and empty['active'] == {'bom': None, 'isometric': None}
    preview = ok(api.request('POST', path + '/preview', data={'kind': 'bom'},
        files=[('files', ('BOM.csv', bom_csv(), 'text/csv'))]))
    assert preview['bom']['line_count'] == 2
    assert preview['bom']['lines'][0]['part_number'] == '000123'
    assert preview['bom']['lines'][0]['quantity'] == 2
    assert preview['bom']['quantity_basis'] == 'one_spool'
    assert database_state(api) == before
    uploaded = ok(request_upload(api, path))
    document = uploaded['active']['bom']
    assert uploaded['version'] == 1 and document['scope_kind'] == 'requirement'
    assert not document['inherited'] and document['bom']['line_count'] == 2
    response = api.get(document['download_url'])
    assert response.content == bom_csv()
    assert response.headers['content-type'].startswith('text/csv')
    assert 'attachment' in response.headers['content-disposition']
    assert document['sha256'] == sha256(bom_csv()).hexdigest()
    assert api.get(document['download_url'], role=None).status_code == 401
    models = importlib.import_module('spool_documents')
    with api.session_factory() as s:
        assert len(s.scalars(select(models.SpoolDocument)).all()) == 1
        assert s.scalars(select(api.application.Item)).all() == []
        for name in ('spool_bom_traces', 'spool_bom_materials', 'tracking_welds', 'inspections', 'flow_plans'):
            assert s.execute(select(api.application.Base.metadata.tables[name])).all() == []


def test_inheritance_uses_exact_requirement_and_local_override_is_one_physical_spool(api):
    saved = setup(api)
    other = setup(api, number='DOC-PO-OTHER')
    path = requirement_path(saved)
    uploaded = ok(request_upload(api, path))
    requirement_doc = uploaded['active']['bom']['id']
    assert ok(api.get(requirement_path(other)))['active']['bom'] is None
    generate(api, saved['order']['project_id'])
    children = labels(api, saved['order']['project_id'])['items']
    assert len(children) == 2
    for child in children:
        data = ok(api.get(ROOT + '/spools/' + child['id']))
        assert data['active']['bom']['id'] == requirement_doc
        assert data['active']['bom']['inherited'] and data['version'] == 0
        assert data['context']['assembly_id'] == child['assembly_id']
    first_path = ROOT + '/spools/' + children[0]['id']
    updated = ok(request_upload(api, first_path, files=[('Local.csv', bom_csv(quantity=3), 'text/csv')]))
    assert not updated['active']['bom']['inherited']
    assert updated['active']['bom']['id'] != requirement_doc
    assert updated['active']['bom']['bom']['lines'][0]['quantity'] == 3
    second = ok(api.get(ROOT + '/spools/' + children[1]['id']))
    assert second['active']['bom']['id'] == requirement_doc
    models = importlib.import_module('spool_documents')
    with api.session_factory() as s:
        for child in children:
            basis = models.spool_document_scope_basis(s, child['id'])
            assert basis[0]['spool_id'] == child['id']
            assert basis[0]['scope_kind'] == ('spool' if child is children[0] else 'requirement')
            files = models.spool_document_packet_files(s, child['id'])
            assert sha256(files[0]['content']).hexdigest() == files[0]['sha256']


def test_full_multipage_isometric_is_viewable_and_bom_is_separate(api):
    path = requirement_path(setup(api))
    bom = ok(request_upload(api, path))['active']['bom']
    result = ok(request_upload(api, path, kind='isometric', version=1,
        files=[('643-712-A.pdf', pdf(4), 'application/pdf')]))
    assert result['active']['bom']['id'] == bom['id']
    drawing = result['active']['isometric']
    assert drawing['page_count'] == 4
    response = api.get(drawing['view_url'], role='welder')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    assert response.headers['content-disposition'].startswith('inline')
    retained = PdfReader(io.BytesIO(response.content))
    assert [float(page.mediabox.width) for page in retained.pages] == [600, 601, 602, 603]
    assert api.get(drawing['download_url']).headers['content-disposition'].startswith('attachment')


def test_camera_scans_and_pdf_pages_merge_in_selected_order(api):
    path = requirement_path(setup(api))
    picture = io.BytesIO()
    Image.new('RGB', (320, 640), 'white').save(picture, 'JPEG')
    result = ok(request_upload(api, path, kind='isometric', files=[
        ('first.jpg', picture.getvalue(), 'image/jpeg'), ('remaining.pdf', pdf(2), 'application/pdf')]))
    drawing = result['active']['isometric']
    assert drawing['page_count'] == 3
    assert [source['filename'] for source in drawing['source_files']] == ['first.jpg', 'remaining.pdf']
    downloaded = PdfReader(io.BytesIO(api.get(drawing['view_url']).content))
    assert float(downloaded.pages[0].mediabox.height) > float(downloaded.pages[0].mediabox.width)
    assert [float(page.mediabox.width) for page in downloaded.pages[1:]] == [600, 601]


def test_revisions_keep_original_bytes_and_stale_writes_do_not_duplicate(api):
    path = requirement_path(setup(api))
    original = ok(request_upload(api, path))['active']['bom']
    changed = ok(request_upload(api, path, files=[('BOM.csv', bom_csv(quantity=3), 'text/csv')], version=1))
    assert changed['version'] == 2 and len(changed['history']) == 2
    assert api.get(original['download_url']).content == bom_csv()
    assert api.get(changed['active']['bom']['download_url']).content == bom_csv(quantity=3)
    before = database_state(api)
    response = request_upload(api, path, version=1)
    assert response.status_code == 409
    assert database_state(api) == before


def test_upload_must_match_preview_and_retains_authoritative_file_values(api):
    path = requirement_path(setup(api))
    preview = ok(api.request('POST', path + '/preview', data={'kind': 'bom'},
        files=[('files', ('BOM.csv', bom_csv(), 'text/csv'))]))
    before = database_state(api)
    response = api.request('POST', path + '/upload', data={'kind': 'bom', 'expected_version': '0',
        'reason': 'Reviewed upload', 'expected_sha256': preview['selection_sha256']},
        files=[('files', ('BOM.csv', bom_csv(quantity=9), 'text/csv'))])
    assert response.status_code == 409
    assert database_state(api) == before


@pytest.mark.parametrize('role', [None, 'welder', 'painter', 'finisher', 'misc', 'process_welder', 'fitup_welder'])
def test_upload_role_limits_and_read_access(api, role):
    path = requirement_path(setup(api))
    before = database_state(api)
    assert request_upload(api, path, role=role).status_code == (401 if role is None else 403)
    assert database_state(api) == before
    response = api.get(path, role=role)
    assert response.status_code == (401 if role is None else 200)
    if role:
        assert not response.json()['editable']


@pytest.mark.parametrize('role', ['admin', 'supervisor', 'handler', 'inspector'])
def test_authorized_document_positions_can_upload(api, role):
    path = requirement_path(setup(api))
    assert request_upload(api, path, role=role).status_code == 200


def test_released_spool_or_parent_blocks_shared_requirement_and_physical_uploads(api):
    saved = setup(api)
    path = requirement_path(saved)
    generate(api, saved['order']['project_id'])
    child = labels(api, saved['order']['project_id'])['items'][0]
    with api.session_factory() as s:
        item = s.get(api.application.Item, child['id'])
        item.released = True
        s.commit()
    assert not ok(api.get(path))['editable']
    assert request_upload(api, path).status_code == 409
    assert request_upload(api, ROOT + '/spools/' + child['id']).status_code == 409
    with api.session_factory() as s:
        item = s.get(api.application.Item, child['id'])
        item.released = False
        parent = s.get(api.application.Item, child['assembly_id'])
        parent.released = True
        s.commit()
    assert request_upload(api, path).status_code == 409
    assert request_upload(api, ROOT + '/spools/' + child['id']).status_code == 409


def test_removed_scope_blocks_current_upload_but_retained_document_helper_is_stable(api):
    saved = setup(api)
    path = requirement_path(saved)
    document = ok(request_upload(api, path))['active']['bom']
    change(api, 'order', saved['order']['project_id'])
    assert api.get(path).status_code in (404, 409)
    assert request_upload(api, path).status_code in (404, 409)
    models = importlib.import_module('spool_documents')
    with api.session_factory() as s:
        frozen = models.spool_document_retained_file(s, document['id'])
        assert frozen['content'] == bom_csv() and frozen['sha256'] == document['sha256']


def test_xlsx_worksheet_selection_and_formula_rejection(api):
    path = requirement_path(setup(api))
    workbook = Workbook()
    for index, name in enumerate(('Spool 1', 'Spool 2')):
        sheet = workbook.active if index == 0 else workbook.create_sheet()
        sheet.title = name
        sheet.append(['spool_number', 'item', 'quantity', 'part_number', 'description'])
        sheet.append([NUMBER, 1, index + 1, '0000123', 'Pipe'])
    output = io.BytesIO()
    workbook.save(output)
    attached = [('files', ('BOM.xlsx', output.getvalue(), 'application/octet-stream'))]
    preview = ok(api.request('POST', path + '/preview', data={'kind': 'bom'}, files=attached))
    assert preview['sheet_required'] and preview['sheets'] == ['Spool 1', 'Spool 2']
    saved = ok(request_upload(api, path, files=[attached[0][1]], sheet='Spool 2'))
    assert saved['active']['bom']['bom']['lines'][0]['quantity'] == 2
    assert saved['active']['bom']['bom']['lines'][0]['part_number'] == '0000123'
    workbook['Spool 2']['C2'] = '=1+1'
    output = io.BytesIO()
    workbook.save(output)
    response = request_upload(api, path, files=[('BOM.xlsx', output.getvalue(), 'application/octet-stream')], sheet='Spool 2', version=1)
    assert response.status_code == 422 and 'formulas' in response.text


@pytest.mark.parametrize('payload, filename, kind, status', [
    (b'', 'Empty.pdf', 'isometric', 422),
    (b'<html>fake</html>', 'fake.pdf', 'isometric', 415),
    (b'not an image', 'fake.jpg', 'isometric', 415),
    (b'no headers', 'bad.csv', 'bom', 422),
    (b'description,quantity\nPipe,-1\n', 'negative.csv', 'bom', 422),
    (b'description,quantity\nPipe,NaN\n', 'invalid.csv', 'bom', 422),
    (b'description,quantity\nPipe,inf\n', 'invalid.csv', 'bom', 422),
    (bom_csv(number='OTHER-SPOOL'), 'wrong.csv', 'bom', 422),
])
def test_invalid_documents_fail_without_writes(api, payload, filename, kind, status):
    path = requirement_path(setup(api))
    before = database_state(api)
    response = request_upload(api, path, files=[(filename, payload, 'application/octet-stream')], kind=kind)
    assert response.status_code == status, response.text
    assert database_state(api) == before


def test_mixed_spool_csv_filters_only_selected_number_and_warns(api):
    path = requirement_path(setup(api))
    data = bom_csv() + b'OTHER-SPOOL,9,100,EA,OTHER,Other assembly flange,A105,,Excluded\n'
    result = ok(request_upload(api, path, files=[('Combined.csv', data, 'text/csv')]))
    bom = result['active']['bom']['bom']
    assert len(bom['lines']) == 2
    assert bom['warnings'] and '1 row' in bom['warnings'][0]


def test_limits_reject_large_uploads_before_parsing(api, monkeypatch):
    path = requirement_path(setup(api))
    models = importlib.import_module('spool_documents')
    monkeypatch.setattr(models, 'MAX_FILE_BYTES', 10)
    response = request_upload(api, path)
    assert response.status_code == 413


def test_pdf_bom_remains_viewable_without_inventing_line_items(api):
    path = requirement_path(setup(api))
    result = ok(request_upload(api, path, files=[('Scanned-BOM.pdf', pdf(2), 'application/pdf')]))
    document = result['active']['bom']
    assert document['bom'] is None and document['page_count'] == 2
    assert len(PdfReader(io.BytesIO(api.get(document['view_url']).content)).pages) == 2


def test_template_is_authenticated_and_downloadable(api):
    response = api.get(ROOT + '/template.csv')
    assert response.status_code == 200 and 'spool_number' in response.text
    assert api.get(ROOT + '/template.csv', role=None).status_code == 401


def test_upload_does_not_rewrite_saved_heat_mtr_material_or_qa_records(api):
    from test_spool_reference_bom import physical_copies, trace_record, trace_body
    _, children = physical_copies(api)
    child = children[0]
    trace = ok(api.put(child['bom']['api_url'] + '/traceability',
        trace_body(trace_record(api, child)), role='handler'))
    with api.session_factory() as s:
        tables = [api.application.Base.metadata.tables[name] for name in
                  ('spool_bom_traces', 'spool_bom_materials', 'spool_bom_events', 'tracking_welds', 'inspections')]
        before = {table.name: s.execute(select(table)).all() for table in tables}
    path = ROOT + '/spools/' + child['id']
    result = ok(request_upload(api, path, files=[('User-BOM.csv', bom_csv(number=child['spool_number']), 'text/csv')]))
    assert result['active']['bom']['bom']['line_count'] == 2
    assert trace_record(api, child) == trace
    with api.session_factory() as s:
        assert {table.name: s.execute(select(table)).all() for table in tables} == before


def test_uploaded_document_prevents_renumbering_an_unregistered_physical_spool(api):
    row = ok(api.post('/api/items', {'id': 'DOC-LEGACY-SPOOL', 'kind': 'Spool',
        'google_part_number': NUMBER, 'location': 'Synthetic receiving', 'handler': BADGES['handler']}), 201)
    path = ROOT + '/spools/' + row['id']
    document = ok(request_upload(api, path))['active']['bom']
    before = database_state(api)
    response = api.patch('/api/items/' + row['id'] + '/part-number', {'google_part_number': 'ANOTHER-SPOOL'})
    assert response.status_code == 409, response.text
    assert database_state(api) == before
    assert ok(api.get(path))['active']['bom']['id'] == document['id']


def test_pdf_action_walk_handles_cycles_and_rejects_excessive_depth(application):
    models = importlib.import_module('spool_documents')
    cyclic = {'/AA': {'/JS': 'untrusted script'}}
    cyclic['parent'] = cyclic
    models._strip_pdf_actions(cyclic)
    assert '/AA' not in cyclic and cyclic['parent'] is cyclic
    root, current = {}, None
    current = root
    for _ in range(105):
        current['child'] = {}
        current = current['child']
    with pytest.raises(HTTPException) as error:
        models._strip_pdf_actions(root)
    assert error.value.status_code == 415


@pytest.mark.parametrize('change_kind', ['assembly_number', 'spool_number', 'remove_spool'])
def test_setup_identity_changes_keep_uploaded_requirement_history_accessible(api, change_kind):
    saved = create_setup(api, number='DOC-IDENTITY-PO', assemblies=[branch('643-712-A-PCW-01', 2, [
        {'spool_number': NUMBER, 'quantity_per_assembly': 1, 'welds_per_spool': 2},
        {'spool_number': 'UNRELATED-SPOOL', 'quantity_per_assembly': 1, 'welds_per_spool': 0}])])
    path = requirement_path(saved)
    document = ok(request_upload(api, path))['active']['bom']
    history = ok(api.get(path))
    body = edit_body(saved)
    if change_kind == 'assembly_number':
        body['gpn'] = 'A-DIFFERENT-ASSEMBLY'
    elif change_kind == 'spool_number':
        body['spools'][0]['spool_number'] = 'A-DIFFERENT-SPOOL'
    else:
        body['spools'] = [line for line in body['spools'] if line['spool_number'] != NUMBER]
    before = database_state(api)
    response = api.patch('/api/order-setup/' + saved['order']['project_id'] + '/assemblies/' +
        saved['assemblies'][0]['gpn_id'], body)
    assert response.status_code == 409, response.text
    assert 'uploaded' in response.text.lower() and 'retain' in response.text.lower()
    assert database_state(api) == before
    assert ok(api.get(path)) == history
    assert api.get(document['download_url']).content == bom_csv()


def test_document_backed_setup_still_allows_quantities_welds_and_unrelated_spool_changes(api):
    saved = create_setup(api, number='DOC-EDIT-PO', assemblies=[branch('643-712-A-PCW-01', 2, [
        {'spool_number': NUMBER, 'quantity_per_assembly': 1, 'welds_per_spool': 2},
        {'spool_number': 'UNRELATED-SPOOL', 'quantity_per_assembly': 1, 'welds_per_spool': 0}])])
    path = requirement_path(saved)
    document = ok(request_upload(api, path))['active']['bom']
    body = edit_body(saved, assembly_quantity=4)
    body['spools'][0]['quantity_per_assembly'] = 3
    body['spools'][0]['welds_per_spool'] = 7
    body['spools'][1]['spool_number'] = 'UPDATED-UNRELATED-SPOOL'
    result = ok(api.patch('/api/order-setup/' + saved['order']['project_id'] + '/assemblies/' +
        saved['assemblies'][0]['gpn_id'], body))
    requirement = next(line for line in result['assemblies'][0]['spools'] if line['spool_number'] == NUMBER)
    assert result['assemblies'][0]['assembly_quantity'] == 4
    assert requirement['quantity_per_assembly'] == 3 and requirement['welds_per_spool'] == 7
    assert requirement['id'] == saved['assemblies'][0]['spools'][0]['id']
    after = ok(api.get(path))
    assert after['active']['bom']['id'] == document['id'] and after['version'] == 1
    assert api.get(document['download_url']).content == bom_csv()


def test_alternate_order_gpn_editor_cannot_rename_document_backed_assembly(api):
    saved = setup(api)
    path = requirement_path(saved)
    original = ok(request_upload(api, path))
    project = saved['order']['project_id']
    group = saved['assemblies'][0]
    before = database_state(api)
    response = api.patch(f'/api/orders/{project}/gpns/{group["gpn_id"]}', {
        'expected_version': saved['order']['version'], 'gpn': 'DIFFERENT-ASSEMBLY',
        'description': '', 'reason': 'Attempt a synthetic assembly identity edit'})
    assert response.status_code == 409 and 'uploaded' in response.text.lower()
    assert database_state(api) == before and ok(api.get(path)) == original
    # Descriptive maintenance does not change the selected assembly identity.
    ok(api.patch(f'/api/orders/{project}/gpns/{group["gpn_id"]}', {
        'expected_version': saved['order']['version'], 'gpn': group['gpn'],
        'description': 'Clarified assembly description', 'reason': 'Clarify the description only'}))
    assert ok(api.get(path))['active']['bom']['id'] == original['active']['bom']['id']


def test_combined_assembly_editor_cannot_rename_document_backed_requirement_scope(api):
    from test_order_setup_integration import register_assembly
    saved = setup(api)
    path = requirement_path(saved)
    original = ok(request_upload(api, path))
    register_assembly(api, saved, item_id='DOC-REGISTERED-ASSEMBLY')
    project = saved['order']['project_id']
    current = detail(api, project)
    before = database_state(api)
    response = api.patch(f'/api/orders/{project}/gpn-assemblies/DOC-REGISTERED-ASSEMBLY', {
        'expected_version': current['order']['version'], 'gpn': 'DIFFERENT-ASSEMBLY',
        'required_spools': 1, 'reason': 'Attempt an alternate synthetic assembly rename'})
    assert response.status_code == 409 and 'uploaded' in response.text.lower()
    assert database_state(api) == before and ok(api.get(path)) == original
