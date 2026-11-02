"""Separate business identifiers without changing signed spool evidence."""
import csv
import io

import pytest

from receiving_helpers import approve_materials, receiving_detail, record_arrival
from test_order_labels import generate, labels, public_qr_url
from test_progress import database_state
from test_spool_documents import NUMBER, bom_csv, request_upload, requirement_path, setup
from tracking_helpers import ok


def identity_path(saved):
    return (f'/api/order-setup/{saved["order"]["project_id"]}/assemblies/'
            f'{saved["assemblies"][0]["gpn_id"]}/identity')


def identify(api, saved, number='000123'):
    current = ok(api.get('/api/order-setup/' + saved['order']['project_id']))
    return ok(api.patch(identity_path(saved), {
        'expected_version': current['order']['version'], 'assembly_number': number,
        'reason': 'Record the separately supplied assembly number'}))


def split_csv(gpn, assembly_number):
    content = io.StringIO(newline='')
    writer = csv.writer(content)
    writer.writerow(['spool_number', 'assembly_number', 'gpn', 'item', 'quantity', 'description'])
    writer.writerow([NUMBER, assembly_number, gpn, '1', 2, 'Two independently tracked flanges'])
    return content.getvalue().encode()


def test_assembly_number_edit_preserves_signed_arrival_piece_and_document_history(api):
    saved = setup(api, quantity=1)
    path = requirement_path(saved)
    uploaded = ok(request_upload(api, path))
    generate(api, saved['order']['project_id'])
    item = labels(api, saved['order']['project_id'])['items'][0]
    approve_materials(api, item['id'])
    before = ok(record_arrival(api, item['id']), 201)
    assert before['arrival']['can_proceed']
    assert before['assembly_identity'] == {'gpn': saved['assemblies'][0]['gpn'], 'assembly_number': ''}
    updated = identify(api, saved)
    after = receiving_detail(api, item['id'])
    assert after['assembly_identity'] == {'gpn': saved['assemblies'][0]['gpn'], 'assembly_number': '000123'}
    assert updated['assemblies'][0]['gpn_id'] == saved['assemblies'][0]['gpn_id']
    assert after['context'] == before['context']
    assert after['arrival']['can_proceed']
    assert after['arrival']['basis_sha256'] == before['arrival']['basis_sha256']
    assert after['arrival']['latest'] == before['arrival']['latest']
    assert after['arrival']['history'] == before['arrival']['history']
    assert [row['qa001'] for row in after['traceability']['materials']] == [
        row['qa001'] for row in before['traceability']['materials']]
    document_view = ok(api.get(path))
    assert document_view['context'] == uploaded['context']
    assert document_view['assembly_identity'] == after['assembly_identity']
    assert document_view['active'] == uploaded['active']
    assert document_view['history'] == uploaded['history']
    current_item = labels(api, saved['order']['project_id'])['items'][0]
    assert (current_item['id'], current_item['qr_url']) == (item['id'], item['qr_url'])


@pytest.mark.parametrize('wrong_field', ['assembly_number', 'gpn'])
def test_upload_checks_separate_assembly_and_gpn_columns_independently(api, wrong_field):
    saved = setup(api, quantity=1)
    saved = identify(api, saved)
    group = saved['assemblies'][0]
    path = requirement_path(saved)
    values = {'assembly_number': group['assembly_number'], 'gpn': group['gpn']}
    accepted = ok(request_upload(api, path, files=[
        ('Independent.csv', split_csv(**values), 'text/csv')]))
    bom = accepted['active']['bom']['bom']
    assert bom['assembly_identity'] == values
    assert bom['lines'][0]['assembly_number'] == '000123'
    assert bom['lines'][0]['gpn'] == group['gpn']
    before = database_state(api)
    wrong = {**values, wrong_field: 'FOREIGN-RECORD'}
    rejected = request_upload(api, path, files=[
        ('Foreign.csv', split_csv(**wrong), 'text/csv')], version=1)
    assert rejected.status_code == 422, rejected.text
    assert ('different assembly number' if wrong_field == 'assembly_number' else 'different GPN') in rejected.text
    assert database_state(api) == before


def test_number_edit_requires_fresh_document_preview_but_keeps_saved_scope(api):
    saved = setup(api, quantity=1)
    path = requirement_path(saved)
    files = [('files', ('BOM.csv', bom_csv(), 'text/csv'))]
    preview = ok(api.request('POST', path + '/preview', data={'kind': 'bom'}, files=files))
    identify(api, saved)
    before = database_state(api)
    response = api.request('POST', path + '/upload', files=files, data={
        'kind': 'bom', 'expected_version': 0, 'expected_sha256': preview['selection_sha256'],
        'reason': 'Save after assembly number was entered'})
    assert response.status_code == 409, response.text
    assert database_state(api) == before
    fresh = ok(request_upload(api, path))
    assert fresh['assembly_identity']['assembly_number'] == '000123'
    assert fresh['version'] == 1


@pytest.mark.parametrize('use_gpn_as_number', [False, True])
def test_unknown_assembly_number_is_not_inferred_from_bom_or_gpn(api, use_gpn_as_number):
    saved = setup(api, quantity=1)
    group = saved['assemblies'][0]
    number = group['gpn'] if use_gpn_as_number else '000456'
    path = requirement_path(saved)
    files = [('Independent.csv', split_csv(group['gpn'], number), 'text/csv')]
    before = database_state(api)
    rejected = request_upload(api, path, files=files)
    assert rejected.status_code == 422, rejected.text
    assert 'Enter the actual Assembly Number in setup' in rejected.text
    assert database_state(api) == before

    identify(api, saved, number=number)
    accepted = ok(request_upload(api, path, files=files))
    assert accepted['active']['bom']['bom']['assembly_identity'] == {
        'gpn': group['gpn'], 'assembly_number': number}
