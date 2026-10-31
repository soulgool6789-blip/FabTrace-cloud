"""Exact physical BOMs, heat/MTR identity and immutable arrival QA evidence."""
from copy import deepcopy
from hashlib import sha256
import io

import pytest
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select

from conftest import BADGES
from test_order_labels import public_qr_url
from tracking_helpers import ok, make_spool
from receiving_helpers import (CHECKS, accept_arrival, receiving_detail, record_arrival,
                               save_receiving_materials, upload_receiving_bom)
from test_progress import database_state


def create_spool(api, item_id='RECEIVE-01', number='SOURCE-01'):
    ok(api.post('/api/items', {'id': item_id, 'kind': 'Spool', 'google_part_number': number,
        'description': 'Synthetic arrival spool', 'location': 'Receiving bay',
        'handler': BADGES['handler'], 'welds_required': 1}), 201)
    return item_id


def pdf(pages=1):
    writer = PdfWriter()
    for index in range(pages):
        writer.add_blank_page(width=500 + index, height=700)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def upload_mtr(api, item_id, content=None, reference='MTR-LOCAL-1', version=0, role='handler', **fields):
    files = [('files', ('certificate.pdf', content if content is not None else pdf(2), 'application/pdf'))]
    path = '/api/spool-boms/spools/' + item_id
    preview = api.request('POST', path + '/mtr-preview', files=files, role=role)
    if preview.status_code != 200:
        return preview
    return api.request('POST', path + '/mtr-documents', files=files, role=role, data={
        'reference': reference, 'expected_version': version,
        'expected_sha256': preview.json()['selection_sha256'], 'revision': 'A',
        'reason': 'Retain synthetic MTR for this physical spool', **fields})


def test_missing_bom_is_visible_fail_is_recordable_but_no_acceptance_is_invented(api):
    item_id = create_spool(api)
    before = database_state(api)
    view = receiving_detail(api, item_id)
    assert not view['bom_available'] and view['lines'] == []
    assert view['traceability']['materials'] == []
    assert view['arrival']['status'] == 'pending' and not view['arrival']['can_proceed']
    assert database_state(api) == before
    assert record_arrival(api, item_id).status_code == 409
    failed = ok(record_arrival(api, item_id, result='Fail', notes='Missing BOM and supplier material certificates'), 201)
    assert failed['arrival']['status'] == 'failed'
    assert failed['arrival']['latest']['actor'] == BADGES['inspector']
    assert failed['arrival']['latest']['result'] == 'Fail'
    assert not failed['traceability']['configured']
    assert api.get('/api/items/' + item_id).json()['receiving']['status'] == 'failed'


@pytest.mark.parametrize('role', ['handler', 'supervisor', 'welder', 'painter', None])
def test_only_qa_capability_can_record_arrival(api, role):
    item_id = create_spool(api)
    before = database_state(api)
    result = record_arrival(api, item_id, result='Fail', role=role)
    assert result.status_code == (401 if role is None else 403)
    assert database_state(api) == before


def test_each_physical_copy_has_independent_material_rows_mtrs_and_qa(api):
    first, second = create_spool(api), create_spool(api, 'RECEIVE-02')
    upload_receiving_bom(api, first, quantity=2)
    upload_receiving_bom(api, second, quantity=2)
    saved = save_receiving_materials(api, first, heat='HEAT-FIRST', reference='MTR-FIRST')
    assert len(saved['traceability']['materials']) == 2
    assert all(row['heat_number'] == 'HEAT-FIRST' for row in saved['traceability']['materials'])
    assert all(not row['heat_number'] for row in receiving_detail(api, second)['traceability']['materials'])
    accepted = ok(record_arrival(api, first), 201)
    assert accepted['arrival']['can_proceed']
    assert not receiving_detail(api, second)['arrival']['can_proceed']
    stored = ok(upload_mtr(api, first, reference='MTR-FIRST'), 201)
    assert stored['arrival']['status'] == 'needs_reinspection'
    assert receiving_detail(api, second)['mtr_documents']['current'] == []


def test_heat_edit_stales_pass_fail_remains_until_new_qa_pass_and_all_history_survives(api):
    item_id = create_spool(api)
    accepted = accept_arrival(api, item_id)
    first_review = accepted['arrival']['latest']['id']
    changed = save_receiving_materials(api, item_id, heat='HEAT-CORRECTED')
    assert changed['arrival']['status'] == 'needs_reinspection' and not changed['arrival']['can_proceed']
    failed = ok(record_arrival(api, item_id, result='Fail', notes='Heat marking requires supplier verification'), 201)
    assert failed['arrival']['status'] == 'failed'
    corrected = save_receiving_materials(api, item_id, heat='HEAT-VERIFIED')
    assert corrected['arrival']['status'] == 'failed'
    passed = ok(record_arrival(api, item_id, notes='Supplier evidence checked and material marking verified'), 201)
    assert passed['arrival']['can_proceed']
    assert [row['result'] for row in passed['arrival']['history']] == ['Pass', 'Fail', 'Pass']
    assert passed['arrival']['history'][-1]['id'] == first_review


def test_arrival_version_basis_and_explicit_checks_are_authoritative(api):
    item_id = create_spool(api)
    upload_receiving_bom(api, item_id)
    saved = save_receiving_materials(api, item_id)
    payload = {'expected_version': 0, 'basis_sha256': saved['arrival']['basis_sha256'],
        'result': 'Pass', 'reference': 'CHECK-01', 'notes': 'Inspect against current materials', 'checks': CHECKS}
    missing_check = {**payload, 'checks': {**CHECKS, 'mtrs': False}}
    assert api.post(f'/api/spool-boms/spools/{item_id}/arrival-inspections', missing_check, role='inspector').status_code == 409
    save_receiving_materials(api, item_id, heat='NEW-HEAT')
    assert api.post(f'/api/spool-boms/spools/{item_id}/arrival-inspections', payload, role='inspector').status_code == 409
    accepted = ok(record_arrival(api, item_id), 201)
    payload['basis_sha256'] = accepted['arrival']['basis_sha256']
    assert api.post(f'/api/spool-boms/spools/{item_id}/arrival-inspections', payload, role='inspector').status_code == 409
    assert len(receiving_detail(api, item_id)['arrival']['history']) == 1


def test_new_bom_revision_requires_explicit_adoption_and_retains_old_material_snapshot(api):
    item_id = create_spool(api)
    initial = accept_arrival(api, item_id)
    old_key = initial['traceability']['materials'][0]['piece_key']
    upload_receiving_bom(api, item_id, quantity=2, part='000999', description='Replacement reviewed material')
    changed = receiving_detail(api, item_id)
    assert changed['source_status']['changed'] and changed['source_status']['can_adopt']
    assert changed['arrival']['status'] == 'needs_reinspection'
    assert changed['traceability']['materials'][0]['heat_number'] == 'HEAT-LOCAL-1'
    adopted = ok(api.post(f'/api/spool-boms/spools/{item_id}/adopt-bom', {
        'expected_version': changed['traceability']['version'],
        'expected_bom_sha256': changed['source_status']['expected_bom_sha256'],
        'reason': 'Explicitly adopt the revised physical material basis'}))
    assert not adopted['source_status']['changed']
    assert len(adopted['traceability']['materials']) == 2
    assert all(not row['heat_number'] and not row['mtr_reference'] for row in adopted['traceability']['materials'])
    assert old_key not in {row['piece_key'] for row in adopted['traceability']['materials']}
    history = ok(api.get(adopted['traceability']['history'][0]['detail_url']))
    assert history['changes'][0]['before_materials'][0]['heat_number'] == 'HEAT-LOCAL-1'
    assert history['changes'][0]['before_definition']['lines'][0]['part_number'] == '000123'
    assert not adopted['arrival']['can_proceed']


@pytest.mark.parametrize('quantity,unit', [(1.5, 'EA'), (501, 'EA'), (2, 'FT')])
def test_non_piece_or_oversized_bom_is_viewable_without_rounded_materials(api, quantity, unit):
    item_id = create_spool(api)
    upload_receiving_bom(api, item_id, quantity=quantity, unit=unit)
    detail = receiving_detail(api, item_id)
    assert detail['bom_available'] and detail['lines'][0]['quantity'] == quantity
    assert not detail['traceability']['editable'] and detail['traceability']['materials'] == []
    assert detail['source_status']['blocked_reason']
    assert record_arrival(api, item_id).status_code == 409
    assert record_arrival(api, item_id, result='Fail').status_code == 201


def test_duplicate_item_labels_are_separate_bounded_physical_rows(api):
    item_id = create_spool(api)
    path = '/api/spool-documents/spools/' + item_id
    content = b'item,quantity,unit,part_number,description\n1,1,EA,000111,First flange\n1,1,EA,000222,Second flange\n'
    files = [('files', ('duplicate-labels.csv', content, 'text/csv'))]
    preview = ok(api.request('POST', path + '/preview', files=files, data={'kind': 'bom'}))
    ok(api.request('POST', path + '/upload', files=files, data={'kind': 'bom', 'expected_version': 0,
        'expected_sha256': preview['selection_sha256'], 'reason': 'Keep literal source item labels'}))
    rows = receiving_detail(api, item_id)['traceability']['materials']
    assert len(rows) == 2 and len({row['piece_key'] for row in rows}) == 2
    assert {row['part_number'] for row in rows} == {'000111', '000222'}


def test_mtr_upload_retains_full_pages_authenticated_view_and_prior_revisions(api):
    item_id = create_spool(api)
    first = ok(upload_mtr(api, item_id), 201)['mtr_documents']['current'][0]
    response = api.get(first['view_url'], role='welder')
    assert response.status_code == 200 and response.headers['content-disposition'].startswith('inline')
    assert response.headers['content-security-policy'] == "frame-ancestors 'self'"
    assert response.headers['x-frame-options'] == 'SAMEORIGIN'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert len(PdfReader(io.BytesIO(response.content)).pages) == 2
    assert sha256(response.content).hexdigest() == first['sha256']
    assert api.get(first['view_url'], role=None).status_code == 401
    assert api.get(first['download_url']).headers['content-disposition'].startswith('attachment')
    before = database_state(api)
    assert upload_mtr(api, item_id, pdf(3)).status_code == 409
    assert database_state(api) == before
    second = ok(upload_mtr(api, item_id, pdf(3), version=1), 201)
    assert second['mtr_documents']['current'][0]['version'] == 2
    assert len(second['mtr_documents']['history']) == 2
    assert api.get(first['view_url']).content == response.content
    from spool_receiving import spool_mtr_retained_file
    with api.session_factory() as s:
        assert spool_mtr_retained_file(s, first['id'])['content'] == response.content


@pytest.mark.parametrize('role', ['welder', 'painter', None])
def test_mtr_upload_permissions_and_preview_source_binding(api, role):
    item_id = create_spool(api)
    before = database_state(api)
    assert upload_mtr(api, item_id, role=role).status_code == (401 if role is None else 403)
    assert database_state(api) == before
    assert upload_mtr(api, item_id, expected_sha256='0' * 64).status_code == 409
    assert database_state(api) == before


def test_mtr_or_arrival_history_alone_preserves_physical_identity(api):
    first, second = create_spool(api), create_spool(api, 'RECEIVE-02')
    ok(upload_mtr(api, first), 201)
    ok(record_arrival(api, second, result='Fail'), 201)
    for item_id in (first, second):
        response = api.patch('/api/items/' + item_id + '/part-number', {'google_part_number': 'DIFFERENT'})
        assert response.status_code == 409 and 'history' in response.text
        assert receiving_detail(api, item_id)['spool_number'] == 'SOURCE-01'


def test_legacy_tracked_part_with_blank_number_can_use_exact_spool_receiving(api):
    item_id = make_spool(api, item_id='LEGACY-PHYSICAL-SPOOL')
    detail = receiving_detail(api, item_id)
    assert detail['context']['item_id'] == item_id and detail['spool_number'] == ''
    assert accept_arrival(api, item_id)['arrival']['can_proceed']
    component = 'GENUINE-COMPONENT'
    api.item(component)
    assert api.get('/api/spool-boms/spools/' + component).status_code == 404


def test_mtr_content_hash_tamper_is_detected_in_isolated_test_database(api):
    item_id = create_spool(api)
    document = ok(upload_mtr(api, item_id), 201)['mtr_documents']['current'][0]
    from spool_receiving import SpoolMtrFile
    # SQLite unit fixtures intentionally lack PostgreSQL immutable triggers;
    # this exercises the authenticated download's defense in depth.
    with api.session_factory() as s:
        s.get(SpoolMtrFile, document['id']).content = b'corrupted test bytes'
        s.commit()
    assert api.get(document['view_url']).status_code == 503


@pytest.mark.parametrize('reference', ['   ', 'A', 'MTR\x01BAD', 'R' * 301])
def test_mtr_reference_must_be_nonblank_bounded_and_safe(api, reference):
    item_id = create_spool(api)
    before = database_state(api)
    assert upload_mtr(api, item_id, reference=reference).status_code == 422
    assert database_state(api) == before


def test_mtr_reference_revisions_are_normalized_and_isolated_by_spool(api):
    first, second = create_spool(api), create_spool(api, 'RECEIVE-02')
    original = ok(upload_mtr(api, first, reference='MTR 0007'), 201)['mtr_documents']['current'][0]
    updated = ok(upload_mtr(api, first, pdf(3), reference='  mtr   0007  ', version=1), 201)
    assert len(updated['mtr_documents']['current']) == 1
    assert updated['mtr_documents']['current'][0]['version'] == 2
    assert len(updated['mtr_documents']['history']) == 2
    independent = ok(upload_mtr(api, first, reference='MTR 0008'), 201)
    assert sorted(row['version'] for row in independent['mtr_documents']['current']) == [1, 2]
    sibling = ok(upload_mtr(api, second, reference='MTR 0007'), 201)['mtr_documents']['current'][0]
    assert sibling['version'] == 1 and sibling['id'] != original['id']
    assert len(receiving_detail(api, second)['mtr_documents']['history']) == 1


def test_mtr_history_quota_counts_retained_revisions_not_only_current_files(api, monkeypatch):
    import spool_documents
    item_id = create_spool(api)
    first = ok(upload_mtr(api, item_id), 201)['mtr_documents']['current'][0]
    second = ok(upload_mtr(api, item_id, version=1), 201)['mtr_documents']['current'][0]
    monkeypatch.setattr(spool_documents, 'MAX_SCOPE_BYTES', first['size_bytes'] + second['size_bytes'])
    before = database_state(api)
    blocked = upload_mtr(api, item_id, reference='ANOTHER-MTR')
    assert blocked.status_code == 413 and 'history' in blocked.text
    assert database_state(api) == before
    assert api.get(first['view_url']).status_code == 200
    assert len(receiving_detail(api, item_id)['mtr_documents']['history']) == 2


def test_unstructured_bom_cannot_be_adopted_or_approved_and_old_materials_survive(api):
    from test_spool_documents import request_upload
    item_id = create_spool(api)
    accepted = accept_arrival(api, item_id)
    source = ok(api.get('/api/spool-documents/spools/' + item_id))
    ok(request_upload(api, '/api/spool-documents/spools/' + item_id, version=source['version'],
        files=[('viewable-only.pdf', pdf(), 'application/pdf')]))
    current = receiving_detail(api, item_id)
    assert current['source_status']['changed'] and not current['source_status']['adoptable']
    assert current['traceability']['materials'] == accepted['traceability']['materials']
    before = database_state(api)
    response = api.post(f'/api/spool-boms/spools/{item_id}/adopt-bom', {
        'expected_version': current['traceability']['version'],
        'expected_bom_sha256': current['source_status']['expected_bom_sha256'],
        'reason': 'Attempt to adopt a PDF with no reviewed material grid'})
    assert response.status_code == 409
    assert record_arrival(api, item_id).status_code == 409
    assert database_state(api) == before
    assert record_arrival(api, item_id, result='Fail').status_code == 201


def test_adoption_requires_current_source_version_and_material_edit_capability(api):
    item_id = create_spool(api)
    accepted = accept_arrival(api, item_id)
    upload_receiving_bom(api, item_id, quantity=2)
    current = receiving_detail(api, item_id)
    body = {'expected_version': current['traceability']['version'],
        'expected_bom_sha256': current['source_status']['expected_bom_sha256'],
        'reason': 'Review a new material basis for this exact spool'}
    before = database_state(api)
    assert api.post(f'/api/spool-boms/spools/{item_id}/adopt-bom', body, role='welder').status_code == 403
    assert api.post(f'/api/spool-boms/spools/{item_id}/adopt-bom', {
        **body, 'expected_bom_sha256': accepted['source_status']['expected_bom_sha256']}).status_code == 409
    assert api.post(f'/api/spool-boms/spools/{item_id}/adopt-bom', {
        **body, 'expected_version': body['expected_version'] + 1}).status_code == 409
    assert database_state(api) == before
    adopted = ok(api.post(f'/api/spool-boms/spools/{item_id}/adopt-bom', body, role='handler'))
    assert adopted['traceability']['version'] == body['expected_version'] + 1
    assert all(not row['heat_number'] for row in adopted['traceability']['materials'])


def test_shared_bom_receiving_uses_exact_po_and_retains_a_physical_override(api):
    from test_spool_documents import setup, requirement_path, request_upload, bom_csv
    from test_order_labels import generate, labels
    first_order, other_order = setup(api), setup(api, number='RECEIVING-OTHER-PO', quantity=1)
    shared = ok(request_upload(api, requirement_path(first_order)))['active']['bom']
    generate(api, first_order['order']['project_id'])
    generate(api, other_order['order']['project_id'])
    first, local = labels(api, first_order['order']['project_id'])['items']
    other = labels(api, other_order['order']['project_id'])['items'][0]
    accepted = accept_arrival(api, first['id'])
    assert accepted['source_status']['pinned']['document_id'] == shared['id']
    assert not receiving_detail(api, other['id'])['bom_available']
    upload_receiving_bom(api, local['id'], part='LOCAL-ONLY')
    local_accepted = accept_arrival(api, local['id'])
    local_source = local_accepted['source_status']['current']['document_id']
    ok(request_upload(api, requirement_path(first_order), version=1,
        files=[('revised.csv', bom_csv(quantity=3), 'text/csv')]))
    assert receiving_detail(api, first['id'])['arrival']['status'] == 'needs_reinspection'
    untouched = receiving_detail(api, local['id'])
    assert untouched['arrival']['can_proceed']
    assert untouched['source_status']['current']['document_id'] == local_source
    assert untouched['traceability']['materials'] == local_accepted['traceability']['materials']
    assert not receiving_detail(api, other['id'])['bom_available']


def test_removed_physical_history_reads_and_shared_source_updates_do_not_reactivate_it(api):
    from test_spool_documents import setup, requirement_path, request_upload, bom_csv
    from test_order_labels import generate, labels
    from test_removal_orders import change
    saved = setup(api)
    path = requirement_path(saved)
    ok(request_upload(api, path))
    generate(api, saved['order']['project_id'])
    removed, active = labels(api, saved['order']['project_id'])['items']
    accepted = accept_arrival(api, removed['id'])
    certificate = ok(upload_mtr(api, removed['id']), 201)['mtr_documents']['current'][0]
    # Remove the complete declared assembly branch; an individual required
    # child cannot be removed while its parent keeps that declared quantity.
    change(api, 'item', removed['assembly_id'])
    retained = ok(api.get('/api/items/' + removed['id']))['receiving']
    assert retained['status'] == 'removed' and not retained['can_proceed']
    assert retained['latest']['id'] == accepted['arrival']['latest']['id']
    assert not retained['permissions']['can_inspect']
    ok(request_upload(api, path, version=1, files=[('changed.csv', bom_csv(quantity=3), 'text/csv')]))
    assert receiving_detail(api, active['id'])['lines'][0]['quantity'] == 3
    from spool_receiving import spool_mtr_retained_file
    with api.session_factory() as s:
        assert spool_mtr_retained_file(s, certificate['id'])['sha256'] == certificate['sha256']
    assert api.get(certificate['view_url']).status_code == 409
