"""Real extraction, exact-scope inheritance and atomic reviewed drawing imports."""
import copy
import importlib
import io
import json
from hashlib import sha256

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader
from PIL import Image
from sqlalchemy import select

from isometric_fixtures import DEFAULT_ROWS, make_bom_pdf, make_isometric_pdf
from test_order_setup import branch, create_setup
from test_order_labels import generate, labels, public_qr_url
from test_progress import database_state
from test_removal_orders import change
from test_spool_documents import ROOT, bom_csv, request_upload
from tracking_helpers import ok


NUMBERS = ['TEST-100-SPOOL-01', 'TEST-100-SPOOL-02']


def setup(api, number='ISOMETRIC-001', numbers=NUMBERS, quantity=2, extra=None):
    groups = [branch('TEST-100', quantity, [{'spool_number': value, 'quantity_per_assembly': 1,
        'welds_per_spool': 2} for value in numbers])]
    if extra:
        groups.append(extra)
    return create_setup(api, number=number, assemblies=groups)


def path(saved, index=0, group=0):
    return ROOT + '/requirements/' + saved['assemblies'][group]['spools'][index]['id']


def preview(api, location, content=None, document_id=None, role='admin', source_mode=None):
    kwargs = ({'data': {'document_id': document_id}} if document_id else
        {'files': [('files', ('test-isometric.pdf', content or make_isometric_pdf(), 'application/pdf'))]})
    if source_mode is not None:
        kwargs.setdefault('data', {})['source_mode'] = source_mode
    return api.request('POST', location + '/isometric-preview', role=role, **kwargs)


def review_body(data):
    mappings = []
    for candidate in data['candidates']:
        if not candidate['selected']:
            continue
        field = 'spool_id' if candidate.get('matched_spool_id') else 'requirement_id'
        target_id = candidate.get('matched_spool_id') or candidate.get('matched_requirement_id')
        target = next(target for target in data['targets'] if target.get(field) == target_id)
        mappings.append({'candidate_id': candidate['candidate_id'], field: target_id,
                         'expected_version': target['version'], 'lines': copy.deepcopy(candidate['lines'])})
    return {'preview_token': data['preview_token'], 'reviewed': True,
            'revision': 'A', 'reason': 'Reviewed exact drawing and material table', 'mappings': mappings}


def save(api, location, data, content=None, review=None, role='admin'):
    args = {'data': {'review': json.dumps(review or review_body(data))}}
    if data['source']['kind'] == 'upload':
        args['files'] = [('files', ('test-isometric.pdf', content or make_isometric_pdf(), 'application/pdf'))]
    return api.request('POST', location + '/isometric-import', role=role, **args)


def test_native_preview_then_atomic_shared_drawing_and_separate_excel_boms(api):
    saved = setup(api)
    before = database_state(api)
    data = ok(preview(api, path(saved)))
    assert database_state(api) == before
    assert data['source']['page_count'] == 3
    assert [candidate['source_pages'] for candidate in data['candidates']] == [[2], [3]]
    assert all(candidate['selected'] for candidate in data['candidates'])
    assert len(data['excluded_pages']) == 1
    result = ok(save(api, path(saved), data))
    rows = result['package_result']['requirements']
    assert result['package_result']['count'] == len(rows) == 2
    assert result['version'] == 2
    assert [row['version'] for row in rows] == [2, 2]
    drawings = [row['isometric_document'] for row in rows]
    assert drawings[0]['id'] != drawings[1]['id']
    assert drawings[0]['sha256'] == drawings[1]['sha256']
    for row in rows:
        drawing = row['isometric_document']
        content = api.get(drawing['view_url']).content
        assert len(PdfReader(io.BytesIO(content)).pages) == 3
        assert sha256(content).hexdigest() == drawing['sha256']
        bom = row['bom_document']
        assert bom['bom']['line_count'] == 2
        assert bom['bom']['quantity_basis'] == 'one_spool'
        assert bom['bom']['provenance']['original_lines']
        assert not bom['bom']['provenance']['edited']
        workbook = load_workbook(io.BytesIO(api.get(bom['excel_url']).content), data_only=False)
        sheet = workbook['BOM']
        assert sheet['A12'].value == row['spool_number']
        assert sheet['E12'].value == '000123'
        assert sheet['E12'].data_type == 's'
        assert sheet['C12'].value == 2
        assert sheet['C12'].number_format == '0'
        assert sheet['C12'].alignment.horizontal == 'center'
        assert sheet['D12'].alignment.horizontal == 'center'
        assert sheet['E12'].alignment.horizontal == 'left'
        assert sheet['B6'].alignment.horizontal == 'left'
        assert sheet['I13'].value == '16 3/4"'
        workbook.close()
        module = importlib.import_module('spool_documents')
        source_rows, _, _ = module._xlsx_rows(api.get(bom['excel_url']).content, 'BOM')
        roundtrip = module._bom_grid(source_rows, row['spool_number'], 'TEST-100', 'BOM')
        assert roundtrip['lines'] == bom['bom']['lines']
    models = importlib.import_module('spool_documents')
    with api.session_factory() as session:
        assert len(session.scalars(select(models.SpoolDocument)).all()) == 4
        assert len(session.scalars(select(models.SpoolDocumentFile)).all()) == 3
        assert len(session.scalars(select(models.SpoolDocumentFileLink)).all()) == 1
        assert session.scalars(select(api.application.Item)).all() == []


def test_import_matches_only_selected_po_assembly_and_all_physical_copies_inherit(api):
    saved = setup(api, extra=branch('ZZ-ANOTHER-ASSEMBLY', 1, [
        {'spool_number': NUMBERS[0], 'quantity_per_assembly': 1}]))
    other = setup(api, number='ISOMETRIC-002')
    data = ok(preview(api, path(saved)))
    assert len(data['targets']) == 2
    result = ok(save(api, path(saved), data))
    assert ok(api.get(path(other)))['active']['bom'] is None
    assert ok(api.get(path(saved, group=1)))['active']['isometric'] is None
    generate(api, saved['order']['project_id'])
    items = labels(api, saved['order']['project_id'])['items']
    documents = {row['spool_number']: row for row in result['package_result']['requirements']}
    inherited = 0
    for item in items:
        detail = ok(api.get(ROOT + '/spools/' + item['id']))
        if detail['context']['gpn_id'] == saved['assemblies'][0]['gpn_id']:
            inherited += 1
            expected = documents[detail['context']['spool_number']]
            assert detail['active']['bom']['id'] == expected['bom_document']['id']
            assert detail['active']['isometric']['inherited']
        else:
            assert detail['active']['bom'] is None
    assert inherited == 4


def test_physical_package_is_local_then_saved_source_explicitly_shared_with_same_assembly(api):
    saved = setup(api)
    generate(api, saved['order']['project_id'])
    children = labels(api, saved['order']['project_id'])['items']
    first = next(child for child in children if child['spool_number'] == NUMBERS[0])
    location = ROOT + '/spools/' + first['id']
    data = ok(preview(api, location))
    assert len(data['targets']) == 1
    assert sum(candidate['selected'] for candidate in data['candidates']) == 1
    result = ok(save(api, location, data))
    original_bom = result['active']['bom']['id']
    original_drawing = result['active']['isometric']['id']
    assert result['package_result']['count'] == 1 and not result['active']['bom']['inherited']
    assert ok(api.get(path(saved)))['active']['bom'] is None
    shared = ok(preview(api, path(saved), document_id=original_drawing))
    assert shared['source']['kind'] == 'saved'
    assert shared['source']['view_url'].endswith(original_drawing)
    assert shared['warning_count'] == 1 and 'override' in shared['warnings'][0]
    shared_result = ok(save(api, path(saved), shared))
    assert shared_result['package_result']['count'] == 2
    still_local = ok(api.get(location))
    assert still_local['active']['bom']['id'] == original_bom
    assert still_local['active']['isometric']['id'] == original_drawing
    for child in children:
        if child['id'] != first['id']:
            assert ok(api.get(ROOT + '/spools/' + child['id']))['active']['isometric']['inherited']
    other = setup(api, number='ISOMETRIC-003')
    assert preview(api, path(other), document_id=original_drawing).status_code == 409
    change(api, 'item', first['assembly_id'])
    assert api.get(ROOT + '/files/' + original_drawing).status_code in (404, 409)
    for row in shared_result['package_result']['requirements']:
        assert api.get(row['isometric_document']['view_url']).status_code == 200


def test_saved_drawing_regenerates_bom_without_reupload_or_duplicate_drawing_revision(api, monkeypatch):
    saved = setup(api)
    first = ok(save(api, path(saved), ok(preview(api, path(saved)))))
    old_bom, old_drawing = first['active']['bom'], first['active']['isometric']
    old_bytes = api.get(old_bom['download_url']).content
    data = ok(preview(api, path(saved), document_id=old_drawing['id']))
    def never_extract_twice(*args, **kwargs):
        raise AssertionError('Saving a signed review must not repeat extraction or OCR')
    monkeypatch.setattr(importlib.import_module('isometric_import'), '_extract', never_extract_twice)
    review = review_body(data)
    review['mappings'][0]['lines'][0]['quantity'] = 7
    review['mappings'][0]['lines'][0]['description'] = '=DANGEROUS_FORMULA()'
    result = ok(save(api, path(saved), data, review=review))
    assert result['version'] == 3
    assert result['active']['isometric']['id'] == old_drawing['id']
    assert result['active']['bom']['id'] != old_bom['id']
    assert result['active']['bom']['bom']['provenance']['edited']
    assert api.get(old_bom['download_url']).content == old_bytes
    workbook = load_workbook(io.BytesIO(api.get(result['active']['bom']['excel_url']).content), data_only=False)
    assert workbook['BOM']['F12'].value == '=DANGEROUS_FORMULA()'
    assert workbook['BOM']['F12'].data_type == 's'
    assert workbook['BOM']['C12'].value == 7
    workbook.close()


@pytest.mark.parametrize('fault', ['cross_order', 'stale_version', 'duplicate_target', 'negative_quantity', 'duplicate_item', 'missing_review', 'wrong_origin', 'other_user', 'changed_source'])
def test_invalid_review_is_atomic_and_keeps_all_existing_documents(api, fault):
    saved = setup(api)
    location = path(saved)
    data = ok(preview(api, location))
    review = review_body(data)
    content, role, save_path = None, 'admin', location
    if fault == 'cross_order':
        other = setup(api, number='ISOMETRIC-OTHER')
        review['mappings'][1]['requirement_id'] = other['assemblies'][0]['spools'][1]['id']
    elif fault == 'stale_version':
        ok(request_upload(api, path(saved, 1), files=[('bom.csv', bom_csv(NUMBERS[1]), 'text/csv')]))
    elif fault == 'duplicate_target':
        review['mappings'][1]['requirement_id'] = review['mappings'][0]['requirement_id']
    elif fault == 'negative_quantity':
        review['mappings'][1]['lines'][0]['quantity'] = -3
    elif fault == 'duplicate_item':
        review['mappings'][1]['lines'][1]['item'] = review['mappings'][1]['lines'][0]['item']
    elif fault == 'missing_review':
        review['reviewed'] = False
    elif fault == 'wrong_origin':
        save_path = path(saved, 1)
    elif fault == 'other_user':
        role = 'supervisor'
    elif fault == 'changed_source':
        content = make_isometric_pdf(revision='B')
    before = database_state(api)
    response = save(api, save_path, data, content=content, review=review, role=role)
    assert response.status_code in (409, 422), response.text
    assert database_state(api) == before


def test_selected_released_spool_after_preview_blocks_entire_shared_import(api):
    saved = setup(api)
    generate(api, saved['order']['project_id'])
    data = ok(preview(api, path(saved)))
    child = next(child for child in labels(api, saved['order']['project_id'])['items']
                 if child['spool_number'] == NUMBERS[1])
    with api.session_factory() as session:
        session.get(api.application.Item, child['id']).released = True
        session.commit()
    before = database_state(api)
    assert save(api, path(saved), data).status_code == 409
    assert database_state(api) == before
    locked = ok(preview(api, path(saved)))
    assert sum(target['editable'] for target in locked['targets']) == 1
    assert sum(candidate['selected'] for candidate in locked['candidates']) == 1


def test_ambiguous_duplicate_tables_are_not_selected_and_manual_assignment_stays_scoped(api):
    saved = setup(api)
    content = make_isometric_pdf(spools=[{'number': 'UNMATCHED-001'}, {'number': 'DUPLICATE-001'},
                                         {'number': 'DUPLICATE-001'}])
    data = ok(preview(api, path(saved), content))
    assert len(data['candidates']) == 3
    assert not any(candidate['selected'] for candidate in data['candidates'])
    candidate = data['candidates'][0]
    review = review_body(data)
    review['mappings'] = [{'candidate_id': candidate['candidate_id'],
        'requirement_id': data['targets'][1]['requirement_id'], 'expected_version': 0,
        'lines': candidate['lines']}]
    result = ok(save(api, path(saved), data, content=content, review=review))
    # The initial source requirement was deliberately not chosen.
    assert result['active']['bom'] is None
    imported = result['package_result']['requirements'][0]['bom_document']
    assert imported['bom']['provenance']['manually_assigned']
    assert imported['bom']['lines'][0]['spool_number'] == NUMBERS[1]


def test_shared_bytes_survive_source_removal_and_historical_packet_resolution(api):
    saved = setup(api)
    result = ok(save(api, path(saved), ok(preview(api, path(saved)))))
    rows = result['package_result']['requirements']
    first, second = [row['isometric_document'] for row in rows]
    content = api.get(second['view_url']).content
    models = importlib.import_module('spool_documents')
    # Historical packets retain exact linked IDs even after their order removal.
    change(api, 'order', saved['order']['project_id'])
    assert api.get(second['view_url']).status_code in (404, 409)
    with api.session_factory() as session:
        retained = models.spool_document_retained_file(session, second['id'])
        assert retained['content'] == content
        assert retained['sha256'] == first['sha256']


def test_legacy_tabular_bom_gets_formula_safe_excel_without_mutation(api):
    saved = setup(api)
    result = ok(request_upload(api, path(saved), files=[('bom.csv', bom_csv(NUMBERS[0]), 'text/csv')]))
    bom = result['active']['bom']
    before = database_state(api)
    response = api.get(bom['excel_url'])
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook['BOM']['E12'].value == '000123'
    assert workbook['BOM']['I13'].value == '16 3/4 in'
    assert database_state(api) == before
    assert api.get(bom['excel_url'], role=None).status_code == 401


def test_busy_preview_returns_retry_and_does_not_read_uploaded_file(api, monkeypatch):
    saved = setup(api)
    module = importlib.import_module('isometric_import')
    def unexpected(*args, **kwargs):
        raise AssertionError('A busy review must not read or normalize a drawing')
    monkeypatch.setattr(module, '_source', unexpected)
    assert module._WORK_SLOT.acquire(blocking=False)
    try:
        assert preview(api, path(saved)).status_code == 429
    finally:
        module._WORK_SLOT.release()


def test_incomplete_source_rows_require_correction_and_retain_blank_original_values(api):
    saved = setup(api, numbers=[NUMBERS[0]])
    source_rows = copy.deepcopy(DEFAULT_ROWS)
    source_rows[0][0] = ''
    source_rows[0][1] = ''
    content = make_isometric_pdf(spools=[{'number': NUMBERS[0], 'rows': source_rows}])
    data = ok(preview(api, path(saved), content))
    assert len(data['candidates']) == 1
    candidate = data['candidates'][0]
    assert candidate['review_required'] and candidate['validation_errors']
    review = review_body(data)
    assert save(api, path(saved), data, content, review=review).status_code == 422
    missing = next(line for line in review['mappings'][0]['lines'] if not line['item'])
    missing['item'], missing['quantity'], missing['source_page'] = '2', 1, '999'
    result = ok(save(api, path(saved), data, content, review=review))
    bom = result['active']['bom']['bom']
    assert bom['provenance']['edited']
    assert any(line['item'] == '' and line['quantity'] is None for line in bom['provenance']['original_lines'])
    assert all(line['source_page'] == '2' for line in bom['lines'])
    assert bom['provenance']['source_validation_errors']
    assert 'original_lines' not in result['history'][0]['bom']['provenance']


def test_preview_token_cannot_authenticate_as_login_cookie_and_expired_review_is_rejected(api):
    saved = setup(api)
    data = ok(preview(api, path(saved)))
    api.client.cookies.clear()
    api.client.cookies.set('fabtrace_session', data['preview_token'])
    assert api.client.get(path(saved)).status_code == 401
    module = importlib.import_module('isometric_import')
    claim = api.application.jwt.decode(data['preview_token'], api.application.JWT_SECRET,
        algorithms=['HS256'], audience=module.TOKEN_AUDIENCE)
    claim['exp'] = 1
    review = review_body(data)
    review['preview_token'] = api.application.jwt.encode(claim, api.application.JWT_SECRET, algorithm='HS256')
    before = database_state(api)
    assert save(api, path(saved), data, review=review).status_code == 409
    assert database_state(api) == before


def test_oversized_extraction_does_not_issue_unsaveable_preview_and_large_review_is_clear_413(api, monkeypatch):
    saved = setup(api, numbers=[NUMBERS[0]])
    module = importlib.import_module('isometric_import')
    extractor = importlib.import_module('isometric_bom').extract_isometric_boms
    extraction = extractor(make_isometric_pdf(spools=[{'number': NUMBERS[0]}]))
    line = extraction['candidates'][0]['lines'][0]
    extraction['candidates'][0]['lines'] = [{**line, 'item': str(index), 'notes': 'N' * 900}
                                           for index in range(1, 501)]
    extraction['candidates'][0]['line_count'] = 500
    monkeypatch.setattr(module, '_extract', lambda *_: extraction)
    before = database_state(api)
    response = preview(api, path(saved))
    assert response.status_code == 413
    assert 'smaller drawing set' in response.json()['detail']
    assert 'preview_token' not in response.json()
    assert database_state(api) == before
    # This is below the framework's 1 MiB part ceiling but over our 900 KiB
    # review limit, verifying the real multipart route gives an actionable 413.
    review = json.dumps({'reviewed': True, 'padding': 'R' * (950 * 1024)})
    response = api.request('POST', path(saved) + '/isometric-import', data={'review': review},
        files=[('files', ('test-isometric.pdf', make_isometric_pdf(), 'application/pdf'))])
    assert response.status_code == 413
    assert 'Select fewer spools' in response.json()['detail']
    assert database_state(api) == before


@pytest.mark.parametrize('source_layout', ['crop', 'empty_drawing_template'])
def test_standalone_pdf_bom_retains_source_and_excel_without_replacing_existing_drawing(api, source_layout):
    saved = setup(api, numbers=[NUMBERS[0]])
    location = path(saved)
    complete = make_isometric_pdf([{'number': NUMBERS[0]}])
    initial = ok(save(api, location, ok(preview(api, location, complete)), content=complete))
    drawing = initial['active']['isometric']
    drawing_bytes = api.get(drawing['view_url']).content
    content = (make_bom_pdf(spool_number=NUMBERS[0]) if source_layout == 'crop' else
               make_isometric_pdf([{'number': NUMBERS[0]}], include_assembly=False, include_geometry=False))
    data = ok(preview(api, location, content))
    assert data['source']['classification'] == data['source']['document_kind'] == 'bom'
    review = review_body(data)
    review['source_mode'] = 'isometric'  # Unsigned client data cannot change classification.
    result = ok(save(api, location, data, content=content, review=review))
    row = result['package_result']['requirements'][0]
    assert row['saved_kinds'] == ['bom'] and row['has_isometric']
    assert result['package_result']['created_isometric_count'] == 0
    assert result['active']['isometric']['id'] == drawing['id']
    assert api.get(drawing['view_url']).content == drawing_bytes
    bom = result['active']['bom']
    assert bom['source_document_kind'] == 'bom'
    assert bom['source_document_id'] == row['source_document']['id']
    assert bom['source_view_url'] == row['source_document']['view_url']
    retained = api.get(bom['source_view_url'])
    assert retained.headers['content-type'] == 'application/pdf'
    assert len(PdfReader(io.BytesIO(retained.content)).pages) == 1
    assert row['source_document']['source_files'][0]['sha256'] == sha256(content).hexdigest()
    assert sha256(retained.content).hexdigest() == row['source_document']['sha256']
    assert row['source_document']['kind'] == 'bom'
    # Saved BOM images/PDFs can be analyzed again without reuploading or
    # duplicating the retained source PDF; only the reviewed Excel is revised.
    repeated = ok(preview(api, location, document_id=bom['source_document_id']))
    updated = ok(save(api, location, repeated))
    assert updated['version'] == result['version'] + 1
    assert updated['active']['bom']['source_document_id'] == bom['source_document_id']
    assert updated['active']['isometric']['id'] == drawing['id']


def test_unlabeled_assembly_upload_requires_spool_selection_and_never_uses_first_origin(api):
    saved = setup(api)
    content = make_bom_pdf()
    data = ok(preview(api, path(saved), content))
    candidate = data['candidates'][0]
    assert candidate['spool_number'] == '' and candidate['review_required']
    assert not candidate['selected'] and candidate['matched_requirement_id'] is None
    before = database_state(api)
    assert save(api, path(saved), data, content=content).status_code == 422
    assert database_state(api) == before
    review = review_body(data)
    review['mappings'] = [{'candidate_id': candidate['candidate_id'],
        'requirement_id': data['targets'][1]['requirement_id'], 'expected_version': 0,
        'lines': candidate['lines']}]
    result = ok(save(api, path(saved), data, content=content, review=review))
    assert result['version'] == 0 and result['active'] == {'bom': None, 'isometric': None}
    row = result['package_result']['requirements'][0]
    assert row['spool_number'] == NUMBERS[1]
    assert row['saved_kinds'] == ['bom'] and not row['has_isometric']
    assert row['isometric_document'] is None
    assert row['bom_document']['bom']['provenance']['source_spool_number'] == ''
    assert row['bom_document']['bom']['provenance']['manually_assigned']


def test_one_unlabeled_bom_uses_only_single_eligible_context_and_multiple_tables_stay_unassigned(api):
    saved = setup(api, numbers=[NUMBERS[0]])
    content = make_bom_pdf()
    data = ok(preview(api, path(saved), content))
    candidate = data['candidates'][0]
    assert candidate['selected'] and candidate['assignment_basis'] == 'selected_scope'
    assert candidate['review_required'] and not candidate['quantity_basis_verified']
    result = ok(save(api, path(saved), data, content=content))
    assert result['active']['isometric'] is None
    assert result['active']['bom']['bom']['line_count'] == 2
    multiple = ok(preview(api, path(saved), make_bom_pdf(table_count=2)))
    assert len(multiple['candidates']) == 2
    assert all(not candidate['selected'] for candidate in multiple['candidates'])


@pytest.mark.parametrize('full_sheet', [True, False])
def test_image_upload_analysis_splits_full_sheet_or_bom_crop_without_kind_contamination(api, monkeypatch, full_sheet):
    saved = setup(api, numbers=[NUMBERS[0]])
    picture = io.BytesIO()
    Image.new('RGB', (1200, 800) if full_sheet else (900, 240), 'white').save(picture, 'PNG')
    image_bytes = picture.getvalue()
    class OCR:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def __call__(self, content, page_number, width, height):
            return {'drawing': 'TEST-100' if full_sheet else '', 'revision': 'A' if full_sheet else '',
                'drawing_geometry': full_sheet,
                'tables': [{'rows': [*copy.deepcopy(DEFAULT_ROWS),
                    ['ITEM', 'QTY', 'PART NUMBER', 'DESCRIPTION', 'LENGTH', 'MATERIAL'],
                    [f'"{NUMBERS[0]}" QTY. SHOWN FOR ONE (1)', None, None, None, None, None]],
                    'bbox': [width * .51, height * .6, width * .98, height * .9] if full_sheet else [0, 0, width, height]}],
                'warnings': []}
    monkeypatch.setattr(importlib.import_module('isometric_ocr'), 'LocalOCRProvider', OCR)
    files = [('files', ('uploaded-image.png', image_bytes, 'image/png'))]
    data = ok(api.request('POST', path(saved) + '/isometric-preview', data={'source_mode': 'auto'}, files=files))
    expected_kind = 'isometric' if full_sheet else 'bom'
    assert data['source']['document_kind'] == expected_kind
    assert data['candidates'][0]['source_method'] == 'ocr'
    result = ok(api.request('POST', path(saved) + '/isometric-import',
        data={'review': json.dumps(review_body(data))}, files=files))
    assert result['active']['bom']['bom']['line_count'] == 2
    assert bool(result['active']['isometric']) is full_sheet
    assert result['active']['bom']['source_document_kind'] == expected_kind
    retained = api.get(result['active']['bom']['source_view_url'])
    assert len(PdfReader(io.BytesIO(retained.content)).pages) == 1
    assert result['package_result']['requirements'][0]['source_document']['source_files'][0]['sha256'] == sha256(image_bytes).hexdigest()


def test_unknown_pdf_does_not_choose_document_kind_or_fabricate_bom(api):
    saved = setup(api)
    content = make_bom_pdf(commercial=True)
    before = database_state(api)
    data = ok(preview(api, path(saved), content))
    assert data['source']['classification'] == 'unknown' and data['source']['document_kind'] is None
    assert data['candidates'] == []
    assert save(api, path(saved), data, content=content).status_code == 422
    assert database_state(api) == before


def test_explicit_bom_source_choice_is_signed_and_keeps_full_sheet_in_bom_history(api):
    saved = setup(api, numbers=[NUMBERS[0]])
    content = make_isometric_pdf([{'number': NUMBERS[0]}])
    data = ok(preview(api, path(saved), content, source_mode='bom'))
    assert data['source']['classification'] == 'isometric'
    assert data['source']['document_kind'] == 'bom' and data['source']['source_mode'] == 'bom'
    result = ok(save(api, path(saved), data, content=content))
    assert result['active']['isometric'] is None
    assert result['active']['bom']['source_document_kind'] == 'bom'


def test_multiple_scanned_bom_pages_can_be_retained_as_one_viewable_source(api):
    saved = setup(api, numbers=[NUMBERS[0]])
    files = [('one.pdf', make_bom_pdf(), 'application/pdf'), ('two.pdf', make_bom_pdf(), 'application/pdf')]
    result = ok(request_upload(api, path(saved), kind='bom', files=files))
    assert result['active']['bom']['page_count'] == 2
    assert result['active']['isometric'] is None


@pytest.mark.parametrize('role', [None, 'welder', 'painter'])
def test_review_permissions_cannot_write_or_extract(api, role):
    saved = setup(api)
    before = database_state(api)
    assert preview(api, path(saved), role=role).status_code == (401 if role is None else 403)
    assert database_state(api) == before
