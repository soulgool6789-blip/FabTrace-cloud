"""QR labels omit assignment while retaining permanent identity and custody metadata."""
import importlib
import io
import re
from xml.etree import ElementTree

from PIL import Image
import pytest
import qrcode

from conftest import BADGES
from test_order_labels import generate, labels, overview, public_qr_url
from test_order_setup import branch, create_setup
from test_progress import database_state
from test_removal_orders import change
from tracking_helpers import ok


NS = {'svg': 'http://www.w3.org/2000/svg'}


def registered(api, *, assembly_number='ACTUAL-000321', count=2):
    setup = create_setup(api, assemblies=[{
        **branch('GPN-009876', 1, [{'spool_number': '643-777-PCW-03-01',
                                  'quantity_per_assembly': count}]),
        'assembly_number': assembly_number}])
    project = setup['order']['project_id']
    generate(api, project)
    return setup, labels(api, project)['items']


def download(api, project, item_id, **kwargs):
    return api.get(f'/api/order-labels/{project}/labels/{item_id}/download.svg', **kwargs)


def captions(root, field):
    return ' '.join(node.text or '' for node in root.findall(f"svg:text[@data-field='{field}']", NS))


def svg_matrix(root):
    qr = root.find("svg:svg[@id='label-qr']", NS)
    count = int(qr.attrib['viewBox'].split()[-1])
    path = qr.find('svg:path', NS).attrib['d']
    points = {(int(x), int(y)) for x, y in re.findall(r'M(\d+) (\d+)h1v1h-1z', path)}
    return [[(x, y) in points for x in range(count)] for y in range(count)]


def expected_matrix(payload):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.get_matrix()


def test_label_response_separates_real_assembly_gpn_and_current_spool_employee(api):
    setup, rows = registered(api)
    project = setup['order']['project_id']
    first = rows[0]
    with api.session_factory() as session:
        # The parent and other spools retain the generation employee.
        session.get(api.application.Item, first['id']).handler = BADGES['welder']
        employee = session.get(api.application.Employee, BADGES['welder'])
        employee.name = 'Renée <Lead> & "Welder"'
        employee.active = False
        session.commit()
    before = database_state(api)
    result = labels(api, project)
    assigned = next(row for row in result['items'] if row['id'] == first['id'])
    assert assigned['handler'] == BADGES['welder']
    assert assigned['handler_name'] == 'Renée <Lead> & "Welder"'
    assert assigned['assembly_number'] == 'ACTUAL-000321'
    assert assigned['gpn'] == 'GPN-009876'
    assert assigned['assembly_id'] == first['assembly_id']
    assert assigned['qr_alias'] == first['qr_alias'] and assigned['qr_url'] == first['qr_url']
    other = next(row for row in result['items'] if row['id'] != first['id'])
    assert other['handler'] == BADGES['handler'] and other['handler_name'] == 'Test handler'
    group = overview(api, project)['groups'][0]
    assert group['assembly_number'] == 'ACTUAL-000321' and group['gpn'] == 'GPN-009876'
    assert database_state(api) == before


def test_full_download_contains_escaped_captions_and_the_existing_bare_qr_matrix(api):
    setup, rows = registered(api, assembly_number='ACTUAL-000321 <script> & "A"')
    project, row = setup['order']['project_id'], rows[0]
    with api.session_factory() as session:
        session.get(api.application.Employee, BADGES['handler']).name = 'A <script> & B'
        session.commit()
    before = database_state(api)
    result = download(api, project, row['id'], role='inspector')
    assert result.status_code == 200, result.text
    assert result.headers['content-type'].startswith('image/svg+xml')
    assert result.headers['content-disposition'].startswith('attachment;')
    assert 'no-store' in result.headers['cache-control']
    assert result.headers['x-content-type-options'] == 'nosniff'
    root = ElementTree.fromstring(result.content)
    assert captions(root, 'spool') == row['qr_alias']
    assert captions(root, 'purchase-order') == 'P.O. 000123'
    assert captions(root, 'gpn') == 'GPN GPN-009876'
    assert captions(root, 'assembly-number') == 'Assembly Number ' + row['assembly_number']
    assert captions(root, 'assigned-to') == ''
    rendered = ' '.join(root.itertext())
    assert all(value not in rendered for value in ('Assigned', 'A <script> & B', BADGES['handler']))
    assert row['assembly_id'] not in result.text
    assert '&lt;script&gt;' in result.text and not root.findall('.//svg:script', NS)
    assert not root.findall('.//svg:image', NS)
    assert not any(key.endswith('href') for node in root.iter() for key in node.attrib)
    matrix = svg_matrix(root)
    assert matrix == expected_matrix(row['qr_url'])
    # Compare every module with the old bare-PNG endpoint, not just a URL string.
    png = api.get('/api/items/' + row['id'] + '/qr.png')
    assert png.status_code == 200
    image = Image.open(io.BytesIO(png.content)).convert('L')
    scale = image.width // len(matrix)
    assert scale > 0 and image.width == image.height == scale * len(matrix)
    assert [[image.getpixel((x * scale + scale // 2, y * scale + scale // 2)) == 0
             for x in range(len(matrix))] for y in range(len(matrix))] == matrix
    assert database_state(api) == before


def test_redownload_is_identical_after_assignment_changes_without_replacing_qr_or_qa(api):
    setup, rows = registered(api)
    project, row = setup['order']['project_id'], rows[0]
    original_content = download(api, project, row['id']).content
    original = ElementTree.fromstring(original_content)
    with api.session_factory() as session:
        session.get(api.application.Item, row['id']).handler = BADGES['welder']
        session.get(api.application.Employee, BADGES['welder']).name = 'New current employee'
        session.commit()
    before = database_state(api)
    refreshed_content = download(api, project, row['id']).content
    refreshed = ElementTree.fromstring(refreshed_content)
    assert original_content == refreshed_content
    assert captions(original, 'assigned-to') == captions(refreshed, 'assigned-to') == ''
    for root in (original, refreshed):
        rendered = ' '.join(root.itertext())
        assert all(value not in rendered for value in (
            'Assigned', 'Test handler', 'New current employee', BADGES['handler'], BADGES['welder']))
    assert svg_matrix(original) == svg_matrix(refreshed)
    assert captions(original, 'spool') == captions(refreshed, 'spool')
    assert database_state(api) == before


def test_download_needs_authentication_and_exact_active_order_spool_scope(api):
    setup, rows = registered(api)
    project, row = setup['order']['project_id'], rows[0]
    other = create_setup(api, number='OTHER-PO')['order']['project_id']
    before = database_state(api)
    assert download(api, project, row['id'], role=None).status_code == 401
    assert download(api, other, row['id']).status_code == 404
    assert download(api, project, row['assembly_id']).status_code == 404
    assert download(api, project, 'UNKNOWN-SPOOL').status_code == 404
    assert download(api, 'UNKNOWN-ORDER', row['id']).status_code == 404
    for role in BADGES:
        assert download(api, project, row['id'], role=role).status_code == 200
    assert database_state(api) == before


def test_shared_gpn_labels_keep_distinct_assembly_numbers_and_exact_group_filters(api):
    setup = create_setup(api, assemblies=[{
        **branch('SHARED-GPN', 1, [{'spool_number': 'SHARED-SPOOL', 'quantity_per_assembly': 1}]),
        'assembly_number': number} for number in ('ACTUAL-001', 'ACTUAL-002')])
    project = setup['order']['project_id']
    generate(api, project)
    before = database_state(api)
    aliases = set()
    for group in setup['assemblies']:
        selected = labels(api, project, gpn_id=group['gpn_id'])
        assert selected['total'] == len(selected['items']) == 1
        row = selected['items'][0]
        assert row['gpn_id'] == group['gpn_id']
        assert row['gpn'] == 'SHARED-GPN'
        assert row['assembly_number'] == group['assembly_number']
        root = ElementTree.fromstring(download(api, project, row['id']).content)
        assert captions(root, 'assembly-number') == 'Assembly Number ' + group['assembly_number']
        assert captions(root, 'gpn') == 'GPN SHARED-GPN'
        aliases.add(row['qr_alias'])
    assert len(aliases) == 2
    assert database_state(api) == before


@pytest.mark.parametrize('scope', ['spool', 'parent', 'gpn', 'order'])
def test_removed_scope_cannot_be_downloaded_as_an_active_label(api, scope):
    setup, rows = registered(api)
    project, row = setup['order']['project_id'], rows[0]
    kind, identifier = {'spool': ('item', row['id']), 'parent': ('item', row['assembly_id']),
        'gpn': ('gpn', row['gpn_id']), 'order': ('order', project)}[scope]
    change(api, kind, identifier)
    before = database_state(api)
    assert download(api, project, row['id']).status_code == 404
    assert api.get('/api/order-labels/items/' + row['id'] + '/download.svg').status_code == 404
    assert database_state(api) == before


def test_legacy_blank_assembly_is_not_inferred_and_legacy_qr_payload_is_retained(api):
    from test_assembly_identity import legacy_unnamed
    setup, rows = registered(api)
    setup = legacy_unnamed(api, setup)
    project, row = setup['order']['project_id'], rows[0]
    registry = importlib.import_module('order_spools')
    with api.session_factory() as session:
        session.delete(session.get(registry.SpoolQrIdentity, row['id']))
        session.commit()
    before = database_state(api)
    result = labels(api, project)['items'][0]
    assert result['assembly_number'] == ''
    root = ElementTree.fromstring(download(api, project, row['id']).content)
    assert captions(root, 'assembly-number') == ''
    assert captions(root, 'gpn') == 'GPN GPN-009876'
    assert row['assembly_id'] not in ' '.join(root.itertext())
    assert svg_matrix(root) == expected_matrix(api.application.phone_link('item', row['id']))
    assert database_state(api) == before


def test_download_does_not_offer_an_unconfigured_qr_and_does_not_write(api, monkeypatch):
    setup, rows = registered(api)
    project, row = setup['order']['project_id'], rows[0]
    monkeypatch.setattr(api.application, 'PUBLIC_BASE_URL', 'http://localhost:8000')
    before = database_state(api)
    assert download(api, project, row['id']).status_code == 503
    assert database_state(api) == before


def test_long_unicode_captions_wrap_without_truncation_or_unsafe_markup(api):
    module = importlib.import_module('order_labels')
    assembly_number = 'Étage 組立 <script> & 長い識別番号 ' + 'W' * 80
    name = 'Hidden <employee> & name'
    number = '0123456789' * 16
    source = module._label_svg(code=number + '-[001]', purchase_order='PO-' + number,
        gpn='GPN-' + number, assembly_number=assembly_number,
        handler='TRAINING-EMPLOYEE', handler_name=name,
        qr_url='https://fabtrace-label-tests.example/?spool=training')
    root = ElementTree.fromstring(source)
    height = int(root.attrib['viewBox'].split()[-1])
    assert root.attrib['width'] == '2.4in' and height > 735
    assert captions(root, 'assembly-number').replace(' ', '') == (
        'Assembly Number ' + assembly_number).replace(' ', '')
    assert captions(root, 'assigned-to') == ''
    assert all(value not in ' '.join(root.itertext()) for value in ('Assigned', name, 'TRAINING-EMPLOYEE'))
    assert b'&lt;script&gt;' in source
    assert captions(root, 'spool').replace(' ', '') == number + '-[001]'
    for node in root.findall('svg:text', NS):
        assert float(node.attrib['y']) < height - 20
    assert not root.findall('.//svg:script', NS)


def test_item_detail_and_generic_download_share_canonical_order_fields_and_assignment(api):
    setup, rows = registered(api)
    project, row = setup['order']['project_id'], rows[0]
    with api.session_factory() as session:
        session.get(api.application.Item, row['id']).handler = BADGES['welder']
        session.get(api.application.Employee, BADGES['welder']).name = 'Current <Welder> & team'
        session.commit()
    before = database_state(api)
    detail = ok(api.get('/api/items/' + row['id']))
    label = detail['qr_label']
    assert label['purchase_order'] == setup['order']['purchase_order']
    assert label['gpn'] == 'GPN-009876' and label['assembly_number'] == 'ACTUAL-000321'
    assert label['handler'] == BADGES['welder'] and label['handler_name'] == 'Current <Welder> & team'
    assert label['display_code'] == row['qr_alias'] and label['qr_url'] == row['qr_url']
    generic = api.get(label['download_url'])
    assert generic.status_code == 200
    generic_root = ElementTree.fromstring(generic.content)
    order_root = ElementTree.fromstring(download(api, project, row['id']).content)
    assert svg_matrix(generic_root) == svg_matrix(order_root)
    for field in ('kind', 'spool', 'purchase-order', 'gpn', 'assembly-number'):
        assert captions(generic_root, field) == captions(order_root, field)
    for root in (generic_root, order_root):
        assert captions(root, 'assigned-to') == ''
        assert all(value not in ' '.join(root.itertext()) for value in (
            'Assigned', 'Current <Welder> & team', BADGES['welder']))
    assert database_state(api) == before


@pytest.mark.parametrize('kind', ['Spool', 'Part'])
def test_unmapped_item_labels_show_real_kind_without_assignment_or_invented_order_fields(api, kind):
    setup = create_setup(api)
    item_id = 'UNMAPPED-' + kind.upper()
    created = ok(api.post('/api/items', {'id': item_id, 'kind': kind,
        'google_part_number': 'KNOWN-ITEM-NUMBER',
        # Even a matching display string is not a registered/planned relation.
        'project': setup['order']['project_id'], 'location': 'Synthetic receiving',
        'handler': BADGES['welder']}), 201)
    before = database_state(api)
    item = ok(api.get('/api/items/' + item_id))
    label = item['qr_label']
    assert label['kind'] == kind
    assert label['purchase_order'] == label['gpn'] == label['assembly_number'] == ''
    response = api.get(label['download_url'], role='handler')
    assert response.status_code == 200
    root = ElementTree.fromstring(response.content)
    assert captions(root, 'kind') == kind.upper()
    assert captions(root, 'assigned-to') == ''
    assert all(value not in ' '.join(root.itertext()) for value in ('Assigned', 'Test welder', BADGES['welder']))
    assert captions(root, 'purchase-order') == captions(root, 'gpn') == captions(root, 'assembly-number') == ''
    if kind == 'Part':
        assert captions(root, 'item') == item_id
        assert captions(root, 'part-number') == 'Google part number KNOWN-ITEM-NUMBER'
    else:
        assert captions(root, 'spool') == created['qr_alias']
        assert captions(root, 'part-number') == ''
    assert svg_matrix(root) == expected_matrix(item['qr_url'])
    assert database_state(api) == before


def test_legacy_tracked_part_uses_saved_plan_po_without_guessing_gpn_or_assembly(api):
    setup = create_setup(api)
    project = setup['order']['project_id']
    api.item('LEGACY-PLANNED-LABEL', kind='Part')
    ok(api.post('/api/tracking/spools/LEGACY-PLANNED-LABEL/plan', {
        'project_id': project, 'planned_welds': 1}))
    before = database_state(api)
    detail = ok(api.get('/api/items/LEGACY-PLANNED-LABEL'))
    label = detail['qr_label']
    assert detail['kind'] == 'Part' and label['kind'] == 'Spool'
    assert label['purchase_order'] == setup['order']['purchase_order']
    assert label['gpn'] == label['assembly_number'] == label['part_number'] == ''
    root = ElementTree.fromstring(api.get(label['download_url']).content)
    assert captions(root, 'kind') == 'SPOOL'
    assert svg_matrix(root) == expected_matrix(detail['qr_url'])
    assert database_state(api) == before


def test_batch_label_preview_is_bounded_ordered_current_authenticated_and_read_only(api):
    setup, rows = registered(api)
    selected = [row['id'] for row in reversed(rows)]
    with api.session_factory() as session:
        session.get(api.application.Item, selected[0]).handler = BADGES['welder']
        session.get(api.application.Employee, BADGES['welder']).name = 'Latest batch employee'
        session.commit()
    before = database_state(api)
    path = '/api/order-labels/items/preview'
    preview = ok(api.get(path, params=[('item_id', identifier) for identifier in selected], role='inspector'))
    assert preview['qr_ready']
    assert [row['id'] for row in preview['items']] == selected
    assert preview['items'][0]['handler_name'] == 'Latest batch employee'
    assert preview['items'][1]['handler_name'] == 'Test handler'
    assert all(row['assembly_number'] == 'ACTUAL-000321' for row in preview['items'])
    assert api.get(path, params={'item_id': selected[0]}, role=None).status_code == 401
    assert api.get(path).status_code == 422
    assert api.get(path, params=[('item_id', selected[0])] * 101).status_code == 422
    assert api.get(path, params=[('item_id', selected[0]), ('item_id', 'UNKNOWN')]).status_code == 404
    assert api.get(path, params={'item_id': rows[0]['assembly_id']}).status_code == 404
    generic = '/api/order-labels/items/' + rows[0]['id'] + '/download.svg'
    assert api.get(generic, role=None).status_code == 401
    assert api.get('/api/order-labels/items/' + rows[0]['assembly_id'] + '/download.svg').status_code == 409
    assert ok(api.get('/api/items/' + rows[0]['assembly_id']))['qr_label'] is None
    assert database_state(api) == before

