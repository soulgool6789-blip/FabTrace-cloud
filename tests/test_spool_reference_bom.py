"""Approved spool reference BOMs preserve quantities and physical identity.

Expected material values and workbook digest were independently checked against
the approved Rev 2 workbook, rather than derived from the application catalog.
All API fixtures use disposable local databases.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import importlib
import io
import json
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from conftest import BADGES
from tracking_helpers import ok
from test_order_labels import generate, labels, public_qr_url
from test_order_setup import branch, create_setup, detail, edit_body
from test_progress import database_state
from test_removal_orders import change


ROOT = '/api/spool-boms'
SPOOL_A = '643-777-PCW-03-01'
SPOOL_B = '643-777-PCW-03-02'
WORKBOOK_URL = ROOT + '/workbooks/643-777-rev2.xlsx'
APPROVED_SHA256 = 'e5bbba96703625a1fc4852abe3b5a119e2c7fba0ad6fb5b7c65df2fb511764b0'
EXPECTED_LINES = [
    {'item': 2, 'quantity': 1, 'tas_ln_number': '102391',
     'description': 'PIPE CARBON STEEL A53B ERW 4 IN SCH STD/40',
     'length_inches': 16.75, 'material': 'CARBON STEEL'},
    {'item': 1, 'quantity': 2, 'tas_ln_number': '100708',
     'description': 'FLANGE RAISED FACE WELDNECK BUTTWELD CARBON STEEL A105 B16.5 4 IN SCH 40/STD 150#',
     'length_inches': None, 'material': 'A105'},
]


def setup(api, *, number='BOM-PO-001', quantity=2, welds=2, spools=None):
    if spools is None:
        spools = [
            {'spool_number': SPOOL_A, 'quantity_per_assembly': 3},
            {'spool_number': SPOOL_B, 'quantity_per_assembly': 1},
        ]
        if welds is not None:
            spools = [{**row, 'welds_per_spool': welds} for row in spools]
    return create_setup(api, number=number,
        assemblies=[branch('643-777-PCW-03', quantity, spools)])


def assert_reference(record, number):
    assert record['spool_number'] == number
    assert record['drawing_number'] == '643-777'
    assert record['revision'] == '2'
    assert record['revision_date'] == '2025-02-24'
    assert record['source_sheet'] == (2 if number == SPOOL_A else 3)
    assert record['source_page_count'] == 3
    assert record['source_document'] == '643-777.pdf'
    assert record['quantity_basis'] == 'one_spool'
    assert record['quantity_basis_label'] == 'Quantities for one physical spool'
    assert record['line_count'] == 2 and record['total_pieces'] == 3
    keys = tuple(EXPECTED_LINES[0])
    assert [{key: line[key] for key in keys} for line in record['lines']] == EXPECTED_LINES
    pipe, flange = record['lines']
    assert pipe['length_display'] and '16' in pipe['length_display']
    assert flange['length_display'] in ('', '—'), 'A blank drawing length must never become zero'
    assert record['source_workbook']['sha256'] == APPROVED_SHA256
    assert record['source_workbook']['download_url'] == WORKBOOK_URL


def test_setup_requirement_links_keep_one_spool_material_quantities_and_are_read_only(api):
    saved = setup(api)
    project = saved['order']['project_id']
    group = saved['assemblies'][0]
    assert [row['total_quantity'] for row in group['spools']] == [6, 2]
    before = database_state(api)
    for requirement in group['spools']:
        descriptor = requirement['bom']
        assert descriptor == {
            'catalog_id': '643-777-rev2',
            'spool_number': requirement['spool_number'], 'revision': '2', 'line_count': 2,
            'api_url': f'{ROOT}/requirements/{requirement["id"]}'}
        record = ok(api.get(descriptor['api_url']))
        assert_reference(record, requirement['spool_number'])
        context = record['context']
        assert context['kind'] == 'requirement' and context['requirement_id'] == requirement['id']
        assert context['project_id'] == project and context['purchase_order'] == 'BOM-PO-001'
        assert context['assembly_number'] == group['gpn']
    assert detail(api, project)['assemblies'][0]['spools'] == group['spools']
    order = ok(api.get('/api/orders/' + project))
    assert order['gpns'][0]['quantity_plan']['spools'] == group['spools']
    assert labels(api, project)['items'] == []
    assert database_state(api) == before, 'BOM viewing must not create inventory, work or QA evidence'


def test_each_physical_copy_exposes_its_own_bom_link_and_exact_parent_context(api):
    saved = setup(api)
    project = saved['order']['project_id']
    generate(api, project)
    rows = labels(api, project)['items']
    assert len(rows) == 8 and len({row['assembly_id'] for row in rows}) == 2
    assert Counter(row['spool_number'] for row in rows) == {SPOOL_A: 6, SPOOL_B: 2}
    before = database_state(api)
    requirements = {row['spool_number']: row['id'] for row in saved['assemblies'][0]['spools']}
    links = set()
    for row in rows:
        link = row['bom']['api_url']
        assert link == f'{ROOT}/spools/{row["id"]}'
        links.add(link)
        record = ok(api.get(link))
        assert_reference(record, row['spool_number'])
        context = record['context']
        assert context['kind'] == 'spool' and context['item_id'] == row['id']
        assert context['requirement_id'] == requirements[row['spool_number']]
        assert context['assembly_id'] == row['assembly_id']
        assert context['assembly_number'] == '643-777-PCW-03'
        assert context['project_id'] == project and context['purchase_order'] == 'BOM-PO-001'
        item = ok(api.get('/api/items/' + row['id']))
        assert item['bom'] == row['bom']
        assert item['qr_url'] == row['qr_url'] and item['welds_required'] == 2
    assert len(links) == 8
    order = ok(api.get('/api/orders/' + project))
    physical = [child for parent in order['assemblies'] for child in parent['spools']]
    assert {child['item_id']: child['bom'] for child in physical} == {
        row['id']: row['bom'] for row in rows}
    assert database_state(api) == before


def test_download_is_the_approved_workbook_and_material_values_match_the_reference(api):
    saved = setup(api, quantity=1)
    before = database_state(api)
    response = api.get(WORKBOOK_URL)
    assert response.status_code == 200, response.text
    assert response.headers['content-type'].startswith(
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    assert 'attachment' in response.headers['content-disposition']
    assert sha256(response.content).hexdigest() == APPROVED_SHA256
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(io.BytesIO(response.content)) as archive:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(node.itertext()) for node in ET.fromstring(
                archive.read('xl/sharedStrings.xml'))]
        sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        rows = []
        for row in sheet.findall('s:sheetData/s:row', ns):
            values = {}
            for cell in row:
                value, inline = cell.find('s:v', ns), cell.find('s:is', ns)
                text = value.text if value is not None else ''.join(inline.itertext()) if inline is not None else ''
                if cell.get('t') == 's':
                    text = shared[int(text)]
                values[''.join(c for c in cell.get('r') if c.isalpha())] = text
            if values.get('A') in (SPOOL_A, SPOOL_B):
                rows.append(values)
    assert [row['A'] for row in rows] == [SPOOL_A, SPOOL_A, SPOOL_B, SPOOL_B]
    for number in (SPOOL_A, SPOOL_B):
        material_rows = [row for row in rows if row['A'] == number]
        assert [{'item': int(row['B']), 'quantity': int(row['C']), 'tas_ln_number': row['D'],
                 'description': row['E'], 'length_inches': float(row['F']) if row['F'] else None,
                 'material': row['G']} for row in material_rows] == EXPECTED_LINES
    for row in saved['assemblies'][0]['spools']:
        assert_reference(ok(api.get(row['bom']['api_url'])), row['spool_number'])
    assert database_state(api) == before


@pytest.mark.parametrize('number', [
    '643-777-PCW-03', '643-777-PCW-03-010', '643-777-PCW-03-01-X',
    '643-777-PCW-03-03', '643-777-PCW-03-01 Rev 2',
])
def test_similar_numbers_do_not_receive_an_unrelated_bom(api, number):
    saved = setup(api, quantity=1, spools=[{'spool_number': number, 'quantity_per_assembly': 1}])
    requirement = saved['assemblies'][0]['spools'][0]
    assert requirement.get('bom') is None
    generate(api, saved['order']['project_id'])
    row = labels(api, saved['order']['project_id'])['items'][0]
    assert row.get('bom') is None
    before = database_state(api)
    assert api.get(f'{ROOT}/requirements/{requirement["id"]}').status_code == 404
    assert api.get(f'{ROOT}/spools/{row["id"]}').status_code == 404
    assert ok(api.get('/api/items/' + row['id'])).get('bom') is None
    assert database_state(api) == before


def test_normalized_exact_spool_number_matches_without_changing_its_identity(api):
    saved = setup(api, quantity=1, spools=[
        {'spool_number': ' 643-777-pcw-03-01 ', 'quantity_per_assembly': 1}])
    requirement = saved['assemblies'][0]['spools'][0]
    assert requirement['spool_number'] == '643-777-pcw-03-01'
    assert_reference(ok(api.get(requirement['bom']['api_url'])), SPOOL_A)
    generate(api, saved['order']['project_id'])
    row = labels(api, saved['order']['project_id'])['items'][0]
    assert row['spool_number'] == '643-777-pcw-03-01'
    assert_reference(ok(api.get(row['bom']['api_url'])), SPOOL_A)


@pytest.mark.parametrize('kind', ['Part', 'Assembly'])
def test_nonspool_items_never_claim_a_spool_bom(api, kind):
    item = ok(api.post('/api/items', {'id': 'NOT-A-SPOOL', 'kind': kind,
        'google_part_number': SPOOL_A, 'location': 'Synthetic receiving',
        'handler': BADGES['handler']}), 201)
    before = database_state(api)
    assert item.get('bom') is None
    assert api.get(f'{ROOT}/spools/NOT-A-SPOOL').status_code == 404
    assert database_state(api) == before


def test_bom_views_and_downloads_require_login_but_all_active_roles_can_read(api):
    saved = setup(api, quantity=1)
    project = saved['order']['project_id']
    generate(api, project)
    row = labels(api, project)['items'][0]
    paths = [saved['assemblies'][0]['spools'][0]['bom']['api_url'], row['bom']['api_url'], WORKBOOK_URL]
    before = database_state(api)
    for path in paths:
        assert api.get(path, role=None).status_code == 401
    for role in BADGES:
        assert api.get(paths[0], role=role).status_code == 200
        assert api.get(paths[1], role=role).status_code == 200
    for path in (f'{ROOT}/requirements/UNKNOWN', f'{ROOT}/spools/UNKNOWN'):
        assert api.get(path).status_code == 404
    for path in ('/static/spool-boms/643-777-rev2.json',
                 '/static/spool-boms/643-777-rev2.xlsx',
                 '/data/spool-boms/643-777-rev2.xlsx'):
        assert api.get(path, role=None).status_code == 404
    assert database_state(api) == before


@pytest.mark.parametrize('kind', ['item', 'gpn', 'order'])
def test_removed_scope_cannot_expose_an_active_bom_link(api, kind):
    saved = setup(api, quantity=1, welds=None)
    project = saved['order']['project_id']
    group = saved['assemblies'][0]
    generate(api, project)
    row = labels(api, project)['items'][0]
    record_id = row['id'] if kind == 'item' else group['gpn_id'] if kind == 'gpn' else project
    change(api, kind, record_id)
    before = database_state(api)
    assert api.get(row['bom']['api_url']).status_code == 409
    assert ok(api.get('/api/items/' + row['id'])).get('bom') is None
    if kind != 'item':
        assert api.get(group['spools'][0]['bom']['api_url']).status_code == 409
    assert database_state(api) == before


def test_removed_requirement_does_not_keep_a_live_bom_association(api):
    saved = setup(api, quantity=1)
    project, group = saved['order']['project_id'], saved['assemblies'][0]
    original = group['spools'][0]
    body = edit_body(saved)
    body['spools'] = [line for line in body['spools'] if line['spool_number'] == SPOOL_B]
    ok(api.patch(f'/api/order-setup/{project}/assemblies/{group["gpn_id"]}', body))
    before = database_state(api)
    assert api.get(original['bom']['api_url']).status_code == 404
    assert database_state(api) == before


@pytest.mark.parametrize('conflict', ['spool_number', 'project', 'parent'])
def test_physical_bom_rejects_a_conflicting_registered_scope(api, conflict):
    saved = setup(api, quantity=1, welds=None)
    project = saved['order']['project_id']
    generate(api, project)
    row = next(row for row in labels(api, project)['items'] if row['spool_number'] == SPOOL_A)
    other = setup(api, number='BOM-OTHER-PO', quantity=1, welds=None)
    other_project = other['order']['project_id']
    generate(api, other_project)
    other_parent = labels(api, other_project)['items'][0]['assembly_id']
    with api.session_factory() as session:
        item = session.get(api.application.Item, row['id'])
        if conflict == 'spool_number':
            item.google_part_number = SPOOL_B
        elif conflict == 'project':
            item.project = other_project
        else:
            registration = session.get(importlib.import_module('order_spools').OrderSpool, item.id)
            registration.assembly_id = other_parent
        session.commit()
    before = database_state(api)
    assert api.get(row['bom']['api_url']).status_code == 409
    assert database_state(api) == before


def test_reference_reads_do_not_replace_an_existing_physical_material_plan(api):
    saved = setup(api, quantity=1)
    project = saved['order']['project_id']
    generate(api, project)
    row = labels(api, project)['items'][0]
    path = '/api/parts/spools/' + row['id']
    physical = ok(api.put(path + '/plan', {
        'expected_version': 0, 'reference': 'SYNTHETIC-EXISTING-PLAN',
        'reason': 'Retain explicitly configured physical material requirements',
        'lines': [{'part_number': 'KEEP-PART', 'description': 'Existing actual material requirement',
                   'required_qty': 7, 'notes': 'Existing controlled material plan'}]}))
    before = database_state(api)
    assert_reference(ok(api.get(row['bom']['api_url'])), row['spool_number'])
    assert ok(api.get(path)) == physical
    assert database_state(api) == before


TRACE_FIELDS = ('piece_key', 'supplier', 'supplier_piece_id', 'heat_number',
                'mtr_reference', 'mtr_url', 'notes')


def physical_copies(api, *, welds=2):
    row = {'spool_number': SPOOL_A, 'quantity_per_assembly': 2}
    if welds is not None:
        row['welds_per_spool'] = welds
    saved = setup(api, quantity=1, spools=[row])
    project = saved['order']['project_id']
    generate(api, project)
    return saved, labels(api, project)['items']


def trace_record(api, row, role='admin'):
    return ok(api.get(row['bom']['api_url'], role=role))


def trace_body(record, marker='A'):
    trace = record['traceability']
    return {'expected_version': trace['version'],
        'reason': 'Record independently identified synthetic received pieces',
        'materials': [{
            'piece_key': piece['piece_key'], 'supplier': 'Synthetic supplier ' + marker,
            'supplier_piece_id': marker + '-SUPPLIER-' + piece['piece_key'],
            'heat_number': marker + '-HEAT-' + piece['piece_key'],
            'mtr_reference': marker + '-MTR-' + piece['piece_key'],
            'mtr_url': 'https://mtr.example/' + marker + '/' + piece['piece_key'] + '.pdf',
            'notes': 'Synthetic receiving note ' + marker,
        } for piece in trace['materials']]}


def trace_values(record):
    return {piece['piece_key']: {key: piece[key] for key in TRACE_FIELDS}
            for piece in record['traceability']['materials']}


def test_initial_trace_has_three_unreceived_individual_pieces_without_writing_rows(api):
    _, rows = physical_copies(api)
    before = database_state(api)
    record = trace_record(api, rows[0])
    trace = record['traceability']
    assert trace['version'] == 0 and not trace['configured']
    assert trace['editable'] and not trace['locked_reason'] and trace['history'] == []
    materials = {piece['piece_key']: piece for piece in trace['materials']}
    assert set(materials) == {'2-1', '1-1', '1-2'}
    assert materials['2-1']['item'] == 2 and materials['2-1']['pieces_on_line'] == 1
    assert materials['2-1']['tas_ln_number'] == '102391'
    for key, number in (('1-1', 1), ('1-2', 2)):
        assert materials[key]['item'] == 1 and materials[key]['piece_number'] == number
        assert materials[key]['pieces_on_line'] == 2 and materials[key]['tas_ln_number'] == '100708'
    assert all(piece[key] == '' for piece in materials.values() for key in TRACE_FIELDS[1:])
    assert database_state(api) == before


def test_two_flange_heats_and_mtrs_persist_only_on_their_unique_physical_spool(api):
    _, rows = physical_copies(api)
    first, other = rows
    original_other = trace_record(api, other)
    original_tracking = ok(api.get('/api/tracking/spools/' + first['id']))
    initial = trace_record(api, first)
    body = trace_body(initial)
    ok(api.put(first['bom']['api_url'] + '/traceability', body, role='handler'))
    saved = trace_record(api, first)
    assert_reference(saved, SPOOL_A)
    trace = saved['traceability']
    assert trace['version'] == 1 and trace['configured']
    assert trace_values(saved) == {piece['piece_key']: piece for piece in body['materials']}
    pieces = {piece['piece_key']: piece for piece in trace['materials']}
    assert pieces['1-1']['heat_number'] != pieces['1-2']['heat_number']
    assert pieces['1-1']['mtr_reference'] != pieces['1-2']['mtr_reference']
    assert all(piece['updated_by'] == BADGES['handler'] and piece['updated_at'] for piece in pieces.values())
    assert trace_record(api, other) == original_other, 'Shared drawing numbers must never share receiving values'
    assert trace['history'][0]['version'] == 1 and trace['history'][0]['actor'] == BADGES['handler']
    assert trace['history'][0]['reason'] == body['reason'] and trace['history'][0]['at']
    current_tracking = ok(api.get('/api/tracking/spools/' + first['id']))
    for key in ('plan', 'welds', 'requirements', 'holds'):
        assert current_tracking[key] == original_tracking[key], key
    assert {key: value for key, value in current_tracking['production_process'].items() if key != 'as_of'} == {
        key: value for key, value in original_tracking['production_process'].items() if key != 'as_of'}
    assert all(weld['work'] == [] for weld in current_tracking['welds'])
    before = database_state(api)
    assert trace_record(api, first) == saved, 'A fresh request must load the persisted values'
    assert api.get(WORKBOOK_URL).content and sha256(api.get(WORKBOOK_URL).content).hexdigest() == APPROVED_SHA256
    assert database_state(api) == before


def test_corrections_keep_prior_heat_history_and_stale_or_nochange_writes_do_not_mutate(api):
    _, rows = physical_copies(api)
    row = rows[0]
    body = trace_body(trace_record(api, row))
    path = row['bom']['api_url'] + '/traceability'
    ok(api.put(path, body, role='handler'))
    first = trace_record(api, row)
    correction = {'expected_version': 1, 'reason': 'Correct the second flange heat from supplier MTR',
        'materials': [{key: piece[key] for key in TRACE_FIELDS}
                      for piece in first['traceability']['materials']]}
    next(piece for piece in correction['materials'] if piece['piece_key'] == '1-2')['heat_number'] = 'CORRECTED-SECOND-FLANGE'
    ok(api.put(path, correction, role='inspector'))
    second = trace_record(api, row)
    assert second['traceability']['version'] == 2
    assert trace_values(second)['1-1'] == trace_values(first)['1-1']
    assert trace_values(second)['1-2']['heat_number'] == 'CORRECTED-SECOND-FLANGE'
    history = {event['version']: event for event in second['traceability']['history']}
    assert set(history) == {1, 2} and history[2]['actor'] == BADGES['inspector']
    assert history[2]['reason'] == correction['reason']
    change_text = json.dumps(history[2]['changes'])
    assert 'A-HEAT-1-2' in change_text and 'CORRECTED-SECOND-FLANGE' in change_text
    before = database_state(api)
    assert api.put(path, body, role='handler').status_code == 409
    unchanged = {**correction, 'expected_version': 2, 'reason': 'No material value has actually changed'}
    assert api.put(path, unchanged, role='inspector').status_code == 400
    assert database_state(api) == before


@pytest.mark.parametrize('role', [None, *BADGES])
def test_material_receiving_changes_require_the_current_assigned_role(api, role):
    _, rows = physical_copies(api)
    row = rows[0]
    initial = trace_record(api, row)
    body = trace_body(initial)
    allowed = role in ('admin', 'supervisor', 'handler', 'inspector')
    if role is not None:
        assert trace_record(api, row, role=role)['traceability']['editable'] == allowed
    before = database_state(api)
    response = api.put(row['bom']['api_url'] + '/traceability', body, role=role)
    if allowed:
        assert response.status_code == 200, response.text
        assert trace_record(api, row)['traceability']['version'] == 1
    else:
        assert response.status_code == (401 if role is None else 403), response.text
        assert database_state(api) == before


@pytest.mark.parametrize('problem', [
    'missing_piece', 'duplicate_piece', 'unknown_piece', 'extra_quantity',
    'boolean_version', 'http_url', 'script_url', 'credential_url',
])
def test_invalid_material_scope_and_mtr_links_never_partially_save(api, problem):
    _, rows = physical_copies(api)
    row = rows[0]
    body = trace_body(trace_record(api, row))
    if problem == 'missing_piece':
        body['materials'].pop()
    elif problem == 'duplicate_piece':
        body['materials'][1]['piece_key'] = body['materials'][0]['piece_key']
    elif problem == 'unknown_piece':
        body['materials'][0]['piece_key'] = '99-1'
    elif problem == 'extra_quantity':
        body['materials'][0]['quantity'] = 100
    elif problem == 'boolean_version':
        body['expected_version'] = True
    else:
        body['materials'][0]['mtr_url'] = {
            'http_url': 'http://mtr.example/report.pdf',
            'script_url': 'javascript:alert(1)',
            'credential_url': 'https://synthetic-user:synthetic-password@mtr.example/report.pdf',
        }[problem]
    before = database_state(api)
    response = api.put(row['bom']['api_url'] + '/traceability', body, role='handler')
    assert response.status_code == 422, response.text
    assert database_state(api) == before


def test_trace_drafts_allow_missing_receiving_values_without_claiming_acceptance(api):
    _, rows = physical_copies(api)
    row = rows[0]
    initial = trace_record(api, row)
    body = {'expected_version': 0, 'reason': 'Save supplier identification pending the MTR package',
        'materials': [{key: piece[key] for key in TRACE_FIELDS}
                      for piece in initial['traceability']['materials']]}
    body['materials'][0]['supplier'] = 'Synthetic supplier only'
    ok(api.put(row['bom']['api_url'] + '/traceability', body, role='handler'))
    saved = trace_record(api, row)
    assert saved['traceability']['version'] == 1
    assert all(not piece['heat_number'] and not piece['mtr_reference']
               for piece in saved['traceability']['materials'])
    tracking = ok(api.get('/api/tracking/spools/' + row['id']))
    assert all(requirement['status'] == 'pending'
               for weld in tracking['welds'] for requirement in weld['requirements'])
    assert not tracking['item']['released']


@pytest.mark.parametrize('target', ['spool', 'parent'])
def test_released_scope_keeps_receiving_history_readable_but_blocks_corrections(api, target):
    from test_admin import release
    _, rows = physical_copies(api)
    row = rows[0]
    ok(api.put(row['bom']['api_url'] + '/traceability', trace_body(trace_record(api, row)), role='handler'))
    saved = trace_record(api, row)
    release(api, row['id'] if target == 'spool' else row['assembly_id'])
    current = trace_record(api, row)
    assert not current['traceability']['editable'] and current['traceability']['locked_reason']
    assert trace_values(current) == trace_values(saved)
    assert current['traceability']['history'] == saved['traceability']['history']
    before = database_state(api)
    assert api.put(row['bom']['api_url'] + '/traceability', trace_body(current, 'CHANGED')).status_code == 409
    assert database_state(api) == before


def test_receiving_records_follow_the_same_spool_into_production(api):
    _, rows = physical_copies(api)
    row = rows[0]
    ok(api.put(row['bom']['api_url'] + '/traceability', trace_body(trace_record(api, row)), role='handler'))
    saved = trace_record(api, row)
    # Establish an actual traveler through the existing API; BOM recording
    # itself must not invent an arrival, production event or approval.
    ok(api.post(f'/api/flow/items/{row["id"]}/start', {
        'route': 'spool', 'expected_children': 0,
        'material_reference': 'Synthetic approved material kit basis'}, role='supervisor'), 201)
    assert trace_record(api, row)['traceability'] == saved['traceability']
    assert trace_record(api, rows[1])['traceability']['version'] == 0


def test_removed_parent_blocks_receiving_writes_and_restore_retains_original_records(api):
    _, rows = physical_copies(api)
    row = rows[0]
    ok(api.put(row['bom']['api_url'] + '/traceability', trace_body(trace_record(api, row)), role='handler'))
    saved = trace_record(api, row)
    body = trace_body(saved, 'CHANGED')
    change(api, 'item', row['assembly_id'])
    before = database_state(api)
    assert api.put(row['bom']['api_url'] + '/traceability', body).status_code == 409
    assert api.get(row['bom']['api_url']).status_code == 409
    assert database_state(api) == before
    change(api, 'item', row['assembly_id'], 'restore')
    assert trace_record(api, row)['traceability'] == saved['traceability']


def test_an_empty_initial_save_does_not_create_a_received_material_register(api):
    _, rows = physical_copies(api)
    row = rows[0]
    initial = trace_record(api, row)
    body = {'expected_version': 0, 'reason': 'No material has been received yet',
            'materials': [{key: piece[key] for key in TRACE_FIELDS}
                          for piece in initial['traceability']['materials']]}
    before = database_state(api)
    assert api.put(row['bom']['api_url'] + '/traceability', body, role='handler').status_code == 400
    assert database_state(api) == before
    assert trace_record(api, row) == initial


def test_recorded_receiving_identity_prevents_renumbering_an_unregistered_physical_spool(api):
    row = ok(api.post('/api/items', {
        'id': 'SYNTHETIC-LEGACY-SPOOL', 'kind': 'Spool', 'google_part_number': SPOOL_A,
        'location': 'Synthetic receiving', 'handler': BADGES['handler']}), 201)
    number_path = '/api/items/' + row['id'] + '/part-number'
    # This legacy item has no generated-order registration. Its drawing number
    # can be corrected until physical receiving records establish its basis.
    ok(api.patch(number_path, {'google_part_number': SPOOL_B}))
    row = ok(api.patch(number_path, {'google_part_number': SPOOL_A}))
    ok(api.put(row['bom']['api_url'] + '/traceability',
               trace_body(trace_record(api, row)), role='handler'))
    saved = trace_record(api, row)
    before = database_state(api)
    response = api.patch(number_path, {'google_part_number': SPOOL_B})
    assert response.status_code == 409, response.text
    assert database_state(api) == before
    assert ok(api.get('/api/items/' + row['id']))['google_part_number'] == SPOOL_A
    assert trace_record(api, row) == saved


def test_receiving_register_retains_its_approved_basis_when_the_reference_catalog_changes(api, monkeypatch):
    _, rows = physical_copies(api)
    first, other = rows
    ok(api.put(first['bom']['api_url'] + '/traceability',
               trace_body(trace_record(api, first)), role='handler'))
    saved = trace_record(api, first)
    module = importlib.import_module('spool_boms')
    next_catalog = deepcopy(module._CATALOG)
    next_catalog['revision'] = 'SYNTHETIC-NEXT'
    next_definitions = deepcopy(module._DEFINITIONS)
    next_line = next(line for line in next_definitions[SPOOL_A.casefold()]['lines'] if line['item'] == 1)
    next_line['quantity'] = 3
    next_line['material'] = 'SYNTHETIC-NEW-MATERIAL'
    monkeypatch.setattr(module, '_CATALOG', next_catalog)
    monkeypatch.setattr(module, '_DEFINITIONS', next_definitions)
    monkeypatch.setattr(module, '_CATALOG_HASH', 'f' * 64)

    before = database_state(api)
    assert trace_record(api, first) == saved
    assert ok(api.get('/api/items/' + first['id']))['bom']['revision'] == '2'
    newer = trace_record(api, other)
    assert newer['revision'] == 'SYNTHETIC-NEXT' and newer['total_pieces'] == 4
    assert {piece['piece_key'] for piece in newer['traceability']['materials']} == {'2-1', '1-1', '1-2', '1-3'}
    assert database_state(api) == before

    correction = trace_body(saved, 'CORRECTED')
    ok(api.put(first['bom']['api_url'] + '/traceability', correction, role='inspector'))
    corrected = trace_record(api, first)
    assert_reference(corrected, SPOOL_A)
    assert corrected['catalog_sha256'] == saved['catalog_sha256']
    assert corrected['traceability']['version'] == 2
    assert trace_values(corrected) == {piece['piece_key']: piece for piece in correction['materials']}
