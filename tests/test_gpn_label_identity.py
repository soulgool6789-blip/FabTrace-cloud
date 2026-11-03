"""Current business GPN labels never rewrite retained fabrication identities."""
import json
from xml.etree import ElementTree

import pytest
from sqlalchemy import select

from conftest import BADGES
from receiving_helpers import accept_arrival, receiving_detail, upload_receiving_bom
from test_assembly_identity import legacy_unnamed
from test_order_label_download import captions, download, expected_matrix, svg_matrix
from test_order_labels import generate, labels, overview, public_qr_url
from test_order_setup import ROOT, branch, create_setup, detail
from test_orders import current
from test_progress import database_state
from tracking_helpers import ok


RECORDED_GPN = '1193403643-777'
CURRENT_GPN = '1193403'
ASSEMBLY_NUMBER = '643-777'
INITIAL_ASSEMBLY_NUMBER = 'SYNTHETIC-LEGACY-ASSEMBLY'


def setup(api, *, number='LOCAL-GPN-LABEL-PO', quantity=1):
    return create_setup(api, number=number, assemblies=[branch(RECORDED_GPN, quantity, [
        {'spool_number': '643-777-PCW-03-01', 'quantity_per_assembly': 1, 'welds_per_spool': 0},
        {'spool_number': '643-777-PCW-03-02', 'quantity_per_assembly': 1, 'welds_per_spool': 0},
    ], assembly_number=INITIAL_ASSEMBLY_NUMBER)])


def path(saved, index=0):
    return f'{ROOT}/{saved["order"]["project_id"]}/assemblies/{saved["assemblies"][index]["gpn_id"]}/identity'


def body(saved, **values):
    return {'expected_version': saved['order']['version'], 'assembly_number': ASSEMBLY_NUMBER,
            'gpn_label': CURRENT_GPN, 'reason': 'Correct the explicitly verified current GPN and Assembly Number',
            **values}


def preview(api, items):
    return ok(api.get('/api/order-labels/items/preview',
        params=[('item_id', row['id']) for row in items]))['items']


def test_exact_eighteen_assembly_thirty_six_spool_correction_preserves_qr_materials_and_real_qa(api):
    saved = setup(api, quantity=18)
    project = saved['order']['project_id']
    target = saved['assemblies'][0]['gpn_id']
    other = create_setup(api, number='LOCAL-OTHER-PO', assemblies=[branch(CURRENT_GPN, 1)])
    other_project = other['order']['project_id']
    other_before = detail(api, other_project)
    generate(api, project)
    before_labels = labels(api, project)['items']
    assert len(before_labels) == 36 and len({row['assembly_id'] for row in before_labels}) == 18
    assert {row['gpn'] for row in before_labels} == {RECORDED_GPN}
    assert {row['assembly_number'] for row in before_labels} == {INITIAL_ASSEMBLY_NUMBER}
    first = before_labels[0]
    # Use a retained uploaded source and real per-piece/arrival API approvals.
    upload_receiving_bom(api, first['id'], quantity=3)
    accepted = accept_arrival(api, first['id'])
    assert accepted['arrival']['can_proceed']
    assert len(accepted['traceability']['materials']) == 3
    before_documents = ok(api.get('/api/spool-documents/spools/' + first['id']))
    original_png = api.get('/api/items/' + first['id'] + '/qr.png')
    assert original_png.status_code == 200
    # These are retained unnamed records, not newly accepted blank identities.
    # Seed that historical metadata after generating the named physical scope
    # and recording real receiving/QA evidence, then verify its safe repair.
    saved = legacy_unnamed(api, saved)
    before_labels = labels(api, project)['items']
    assert {row['assembly_number'] for row in before_labels} == {''}
    assert saved['assemblies'][0]['gpn_label'] == RECORDED_GPN
    before = json.loads(database_state(api))

    changed = ok(api.patch(path(saved), body(saved), role='supervisor'))
    assert changed['saved_gpn_ids'] == [target]
    assert changed['order']['version'] == saved['order']['version'] + 1
    changed_group = changed['assemblies'][0]
    assert changed_group['gpn'] == RECORDED_GPN
    assert changed_group['gpn_label'] == CURRENT_GPN
    assert changed_group['assembly_number'] == ASSEMBLY_NUMBER
    after = json.loads(database_state(api))
    for table in set(before) - {'order_gpns', 'order_google_part_numbers',
                                'order_assembly_gpn_links', 'purchase_orders', 'audit_events'}:
        assert after[table] == before[table], table
    # A legacy single-assembly identity correction now explicitly re-parents
    # that assembly to the separate current GPN record; physical evidence is
    # still byte-for-byte unchanged by the correction above.
    assert changed_group['gpn_record_id'] != saved['assemblies'][0]['gpn_record_id']
    assert next(row for row in changed['gpn_records']
                if row['id'] == changed_group['gpn_record_id'])['gpn'] == CURRENT_GPN
    old_group = next(row for row in before['order_gpns'] if row['id'] == target)
    new_group = next(row for row in after['order_gpns'] if row['id'] == target)
    assert old_group['gpn_label'] is None and new_group['gpn_label'] == CURRENT_GPN
    assert new_group['gpn'] == old_group['gpn'] == RECORDED_GPN
    assert new_group['normalized_gpn'] == old_group['normalized_gpn']
    assert [row for row in after['order_gpns'] if row['id'] != target] == [
        row for row in before['order_gpns'] if row['id'] != target]
    assert len(after['audit_events']) == len(before['audit_events']) + 1
    event = after['audit_events'][-1]
    assert event['event'] == 'ORDER_SETUP_ASSEMBLY_IDENTITY_UPDATED'
    assert event['actor'] == BADGES['supervisor']
    assert event['details']['before']['gpn_label'] is None
    assert event['details']['before']['business_gpn'] == RECORDED_GPN
    assert event['details']['after']['gpn'] == RECORDED_GPN
    assert event['details']['after']['business_gpn'] == CURRENT_GPN
    assert detail(api, other_project) == other_before

    output = labels(api, project)['items']
    assert len(output) == 36
    durable = lambda rows: {row['id']: (row['assembly_id'], row['qr_alias'], row['qr_url']) for row in rows}
    assert durable(output) == durable(before_labels)
    assert {row['gpn'] for row in output} == {CURRENT_GPN}
    assert {row['assembly_number'] for row in output} == {ASSEMBLY_NUMBER}
    label_group = overview(api, project)['groups'][0]
    assert label_group['gpn'] == CURRENT_GPN and label_group['assembly_number'] == ASSEMBLY_NUMBER
    cards = preview(api, output)
    assert len(cards) == 36 and {row['id'] for row in cards} == {row['id'] for row in output}
    assert {row['gpn'] for row in cards} == {CURRENT_GPN}
    assert {row['assembly_number'] for row in cards} == {ASSEMBLY_NUMBER}
    prior_urls = {row['id']: row['qr_url'] for row in before_labels}
    for row in output:
        response = download(api, project, row['id'])
        assert response.status_code == 200, response.text
        svg = ElementTree.fromstring(response.content)
        assert captions(svg, 'gpn') == 'GPN ' + CURRENT_GPN
        assert captions(svg, 'assembly-number') == 'Assembly Number ' + ASSEMBLY_NUMBER
        assert RECORDED_GPN not in response.text
        assert svg_matrix(svg) == expected_matrix(prior_urls[row['id']])
    generic_svg = api.get('/api/order-labels/items/' + first['id'] + '/download.svg')
    assert generic_svg.status_code == 200
    assert captions(ElementTree.fromstring(generic_svg.content), 'gpn') == 'GPN ' + CURRENT_GPN
    assert api.get('/api/items/' + first['id'] + '/qr.png').content == original_png.content

    receipt = receiving_detail(api, first['id'])
    assert receipt['assembly_identity'] == {'gpn': CURRENT_GPN, 'assembly_number': ASSEMBLY_NUMBER}
    assert receipt['context'] == accepted['context']
    assert receipt['context']['assembly_number'] == RECORDED_GPN
    for key in ('arrival', 'traceability', 'source_status'):
        assert receipt[key] == accepted[key], key
    documents = ok(api.get('/api/spool-documents/spools/' + first['id']))
    assert documents['assembly_identity'] == receipt['assembly_identity']
    assert {key: value for key, value in documents.items() if key != 'assembly_identity'} == {
        key: value for key, value in before_documents.items() if key != 'assembly_identity'}
    physical = current(api, project)
    assert {row['gpn_label'] for row in physical['gpns'] + physical['assemblies']} == {CURRENT_GPN}
    assert all(row['gpn'] == row['google_part_number'] == row['assembly_part_number'] == RECORDED_GPN
               for row in physical['assemblies'])
    assert json.loads(database_state(api)) == after, 'Reading/reprinting current labels must not write records'


def test_omitted_label_preserves_correction_and_unconfirmed_gpn_is_never_split(api):
    from orders import OrderGpn, business_gpn
    saved = setup(api)
    assert saved['assemblies'][0]['gpn_label'] == RECORDED_GPN
    before_label = body(saved)
    del before_label['gpn_label']
    numbered = ok(api.patch(path(saved), before_label))
    assert numbered['assemblies'][0]['gpn_label'] == RECORDED_GPN
    corrected = ok(api.patch(path(numbered), body(numbered)))
    older_client = body(corrected, assembly_number='643-777-VERIFIED')
    del older_client['gpn_label']
    retained = ok(api.patch(path(corrected), older_client))
    assert retained['assemblies'][0]['gpn_label'] == CURRENT_GPN
    assert retained['assemblies'][0]['gpn'] == RECORDED_GPN
    before_read = database_state(api)
    progress = ok(api.get('/api/progress/orders', params={'project_id': retained['order']['project_id']}))
    assert progress['orders'][0]['gpns'][0]['gpn'] == CURRENT_GPN
    assert progress['orders'][0]['gpns'][0]['assembly_number'] == '643-777-VERIFIED'
    assert database_state(api) == before_read
    with api.session_factory() as session:
        group = session.scalar(select(OrderGpn))
        assert group.gpn_label == CURRENT_GPN and business_gpn(group) == CURRENT_GPN


@pytest.mark.parametrize('role', [None, 'handler', 'inspector', 'pressure_testing_technician'])
def test_current_gpn_correction_retains_management_authority(api, role):
    saved = setup(api)
    before = database_state(api)
    response = api.patch(path(saved), body(saved), role=role)
    assert response.status_code == (401 if role is None else 403), response.text
    assert database_state(api) == before


@pytest.mark.parametrize('label', [None, '', '   ', 'X' * 161, 'BAD\x00GPN', True])
def test_invalid_or_null_explicit_gpn_labels_cannot_erase_the_recorded_identity(api, label):
    saved = setup(api)
    before = database_state(api)
    response = api.patch(path(saved), body(saved, gpn_label=label))
    assert response.status_code == 422, response.text
    assert database_state(api) == before


def test_current_gpn_correction_keeps_version_order_scope_and_assembly_uniqueness_guards(api):
    saved = setup(api)
    other = create_setup(api, number='FOREIGN-GPN-LABEL-PO', assemblies=[branch('UNCONFIRMED-643-777')])
    project = saved['order']['project_id']
    saved = ok(api.post(f'{ROOT}/{project}/assemblies', {
        **branch('INDEPENDENT-GPN'), 'assembly_number': 'OCCUPIED-ASSEMBLY',
        'expected_version': saved['order']['version']}), 201)
    index = next(i for i, row in enumerate(saved['assemblies']) if row['gpn'] == RECORDED_GPN)
    corrected = ok(api.patch(path(saved, index), body(saved)))
    before = database_state(api)
    assert api.patch(path(saved, index), body(saved)).status_code == 409
    assert api.patch(path(corrected, index), body(corrected, assembly_number='occupied-assembly')).status_code == 409
    foreign = f'{ROOT}/{project}/assemblies/{other["assemblies"][0]["gpn_id"]}/identity'
    assert api.patch(foreign, body(corrected)).status_code == 422
    assert api.patch(path(corrected, index), {**body(corrected), 'gpn': CURRENT_GPN}).status_code == 422
    assert database_state(api) == before
    assert detail(api, other['order']['project_id'])['assemblies'][0]['gpn_label'] == 'UNCONFIRMED-643-777'

