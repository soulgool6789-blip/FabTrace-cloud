"""Behavioral checks of PO-scoped BOMs, using the downloaded XLSX bytes."""
import importlib

import pytest
from sqlalchemy import select

from conftest import BADGES
from test_exports import Workbook, MIME, snapshot


def make_order(api, number='000012345', suffix=''):
    response = api.post('/api/orders', {'expected_version': 0, 'purchase_order': number,
        'customer': 'Synthetic customer', 'name': 'BOM export example' + suffix, 'notes': ''})
    assert response.status_code == 201, response.text
    return response.json()


def add_gpn(api, detail, gpn):
    project_id = detail['order']['project_id']
    response = api.post(f'/api/orders/{project_id}/gpns', {
        'expected_version': detail['order']['version'], 'gpn': gpn,
        'assembly_number': 'ASM-' + gpn.strip()[:156], 'description': 'Test assembly family'})
    assert response.status_code == 201, response.text
    detail = response.json()
    return detail, next(row['id'] for row in detail['gpns'] if row['gpn'] == gpn)


def add_assembly(api, detail, gpn_id, item_id, required=2, part_number=None):
    project_id = detail['order']['project_id']
    response = api.post(f'/api/orders/{project_id}/assemblies', {
        'expected_version': detail['order']['version'], 'gpn_id': gpn_id, 'item_id': item_id,
        'assembly_part_number': part_number if part_number is not None else '000099-' + item_id,
        'required_spools': required,
        'notes': 'Synthetic controlled assembly scope',
        'create_item': {'id': item_id, 'description': 'Test assembly ' + item_id,
            'google_part_number': 'PHYSICAL-' + item_id, 'drawing': 'TEST-DWG Rev A',
            'location': 'Receiving', 'handler': BADGES['handler'], 'welds_required': 0}})
    assert response.status_code == 201, response.text
    return response.json()


def plan(api, project, item, assembly=None, kind='Spool'):
    api.item(item, welds_required=0, kind=kind)
    response = api.post(f'/api/tracking/spools/{item}/plan', {
        'project_id': project, 'assembly_id': assembly, 'planned_welds': 0,
        'zero_weld_reason': 'Synthetic bolted scope; no joining welds', 'drawing_revision': 'Rev A'})
    assert response.status_code == 200, response.text


def plan_existing_assembly(api, project, item):
    response = api.post(f'/api/tracking/spools/{item}/plan', {
        'project_id': project, 'planned_welds': 0,
        'zero_weld_reason': 'Synthetic child spool assembly, no new joints', 'drawing_revision': 'Rev A'})
    assert response.status_code == 200, response.text


def part_lines(api, spool, *, notes='Synthetic notes'):
    response = api.put(f'/api/parts/spools/{spool}/plan', {
        'expected_version': 0, 'reference': 'BOM-0001 Rev A', 'reason': 'Initial approved test scope',
        'lines': [{'part_number': '000042', 'description': '=HYPERLINK("https://example.invalid","literal")',
                   'required_qty': 2, 'notes': notes},
                  {'part_number': '+PIPE-01', 'description': 'Pipe section Ω',
                   'required_qty': 1, 'notes': '@Literal notes'}]})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def order_scope(api):
    detail = make_order(api)
    detail, first_gpn = add_gpn(api, detail, '000007')
    detail = add_assembly(api, detail, first_gpn, 'ASM-A', required=2)
    detail, second_gpn = add_gpn(api, detail, 'OTHER-GPN')
    detail = add_assembly(api, detail, second_gpn, 'ASM-B', required=1)
    project = detail['order']['project_id']
    plan_existing_assembly(api, project, 'ASM-A')
    plan_existing_assembly(api, project, 'ASM-B')
    plan(api, project, 'SP-A', 'ASM-A')
    plan(api, project, 'SP-B', 'ASM-B')
    part_lines(api, 'SP-A')
    return {'project': project, 'first_gpn': first_gpn, 'second_gpn': second_gpn}


def download(api, project, suffix='bom.xlsx', role='admin', **params):
    response = api.get(f'/api/orders/{project}/{suffix}', role=role, params=params)
    assert response.status_code == 200, response.text
    assert response.headers['content-type'].split(';')[0] == MIME
    assert int(response.headers['content-length']) == len(response.content)
    assert 'no-store' in response.headers['cache-control']
    assert 'attachment;' in response.headers['content-disposition']
    return Workbook(response.content)


def values(workbook, sheet):
    return [{key: cell.value for key, cell in row.items()} for row in workbook.records(sheet)]


def test_bom_scope_quantities_gaps_and_literal_identifiers(api, order_scope):
    before = snapshot(api)
    book = download(api, order_scope['project'])
    assert list(book.sheets) == ['Assembly summary', 'Bill of materials', 'Spool register', 'Export info']
    summary = values(book, 'Assembly summary')
    first = next(row for row in summary if row['Assembly ID'] == 'ASM-A')
    assert first['PO number'] == '000012345' and first['GPN'] == '000007'
    assert first['Retained assembly part number'] == '000099-ASM-A'
    assert first['Assembly number'] == 'ASM-000007' and 'Assembly part number' not in first
    assert 'Assembly description' not in first
    assert all('Spool description' not in row for row in values(book, 'Spool register'))
    assert (first['Required spools'], first['Linked spools'], first['Missing spools']) == (2, 1, 1)
    assert first['Ready spools'] == 0 and first['Linked spools not ready'] == 1
    bom = values(book, 'Bill of materials')
    rows = [row for row in bom if row['Spool ID'] == 'SP-A']
    assert [row['Required quantity'] for row in rows] == [2, 1]
    assert sum(row['Required quantity'] for row in rows) == 3  # Not multiplied by two required spools.
    assert rows[0]['Material part number'] == '000042'
    assert rows[0]['Material description'].startswith('=HYPERLINK')
    assert rows[1]['Material part number'] == '+PIPE-01'
    assert rows[1]['Line notes'] == '@Literal notes'
    assert all(row['Assigned quantity'] == row['Received quantity'] == row['Prepared quantity'] == 0 for row in rows)
    unplanned = next(row for row in bom if row['Spool ID'] == 'SP-B')
    assert unplanned['Required quantity'] is None and unplanned['Planning status'] == 'BOM not planned'
    assert not book.formulas
    assert snapshot(api) == before


@pytest.mark.parametrize('suffix', ('bom.xlsx', 'bom-template.xlsx'))
def test_separate_numbers_preserve_unknown_assembly_drafts_and_leading_zeros(api, suffix):
    detail = make_order(api)
    detail, gpn_id = add_gpn(api, detail, '000007')
    detail = add_assembly(api, detail, gpn_id, 'COMBINED-ASM', required=3, part_number='000007')
    detail, draft_id = add_gpn(api, detail, '000008')
    project = detail['order']['project_id']
    plan_existing_assembly(api, project, 'COMBINED-ASM')
    plan(api, project, 'COMBINED-SP', 'COMBINED-ASM')
    part_lines(api, 'COMBINED-SP')
    # Retained unnamed history is explicit fixture state, not a new API write.
    orders = importlib.import_module('orders')
    with api.session_factory() as session:
        for identifier in (gpn_id, draft_id):
            group = session.get(orders.OrderGpn, identifier)
            group.assembly_number, group.normalized_assembly_number = '', None
        session.commit()
    before = snapshot(api)
    book = download(api, project, suffix=suffix)
    material_sheet = 'BOM template' if suffix == 'bom-template.xlsx' else 'Bill of materials'
    for sheet in ('Assembly summary', material_sheet, 'Spool register'):
        headers = book.headers(sheet)
        assert headers[:4] == ['PO number', 'GPN', 'Assembly number', 'Assembly ID']
        assert all(name not in headers for name in ('GPN / Assembly number', 'Assembly part number', 'Retained assembly part number'))
        rows = book.records(sheet)
        identity = next(row for row in rows if row['Assembly ID'].value == 'COMBINED-ASM')
        assert identity['GPN'].value == '000007'
        assert identity['GPN'].kind == 'inlineStr'
        assert identity['Assembly number'].value == ''
        draft = next(row for row in rows if row['GPN'].value == '000008')
        assert draft['Assembly ID'].value == ''
    summary = values(book, 'Assembly summary')
    planned = next(row for row in summary if row['Assembly ID'] == 'COMBINED-ASM')
    assert (planned['Required spools'], planned['Linked spools'], planned['Missing spools']) == (3, 1, 2)
    draft = next(row for row in summary if row['GPN'] == '000008')
    assert draft['Required spools'] is None and 'Finish assembly setup' in draft['Planning status']
    rows = [row for row in values(book, material_sheet) if row['Spool ID'] == 'COMBINED-SP']
    if suffix == 'bom.xlsx':
        assert [row['Required quantity'] for row in rows] == [2, 1]  # Never multiply by three required spools.
    else:
        assert len(rows) == 1 and rows[0]['Required quantity'] is None
    scoped_draft = download(api, project, suffix=suffix, gpn_id=draft_id)
    assert all(row['GPN'] == '000008' for row in values(scoped_draft, material_sheet))
    assert snapshot(api) == before


@pytest.mark.parametrize('suffix', ('bom.xlsx', 'bom-template.xlsx'))
def test_distinct_assembly_numbers_share_gpn_without_mixing_export_scope(api, suffix, monkeypatch):
    monkeypatch.setattr(importlib.import_module('main'), 'PUBLIC_BASE_URL', 'https://fabtrace.example')
    response = api.post('/api/order-setup', {
        'purchase_order': 'SPLIT-NUMBERS-PO',
        'assemblies': [
            {'gpn': '000007', 'assembly_number': number, 'assembly_quantity': 1,
             'spools': [{'spool_number': 'SPOOL-' + number, 'quantity_per_assembly': 1,
                         'welds_per_spool': 0}]}
            for number in ('000123', '000124')],
    })
    assert response.status_code == 201, response.text
    saved = response.json()
    project = saved['order']['project_id']
    generated = api.post(f'/api/order-labels/{project}/generate', {
        'expected_version': saved['order']['version'], 'kind': 'Spool',
        'location': 'Receiving', 'handler': BADGES['handler']})
    assert generated.status_code == 200, generated.text
    before = snapshot(api)
    material_sheet = 'BOM template' if suffix == 'bom-template.xlsx' else 'Bill of materials'
    for group in saved['assemblies']:
        book = download(api, project, suffix=suffix, gpn_id=group['gpn_id'])
        for sheet in ('Assembly summary', material_sheet, 'Spool register', 'Setup quantities'):
            rows = book.records(sheet)
            assert rows
            assert all(row['GPN'].value == '000007' for row in rows)
            assert all(row['Assembly number'].value == group['assembly_number'] for row in rows)
            assert all(row['GPN'].kind == row['Assembly number'].kind == 'inlineStr' for row in rows)
        setup = values(book, 'Setup quantities')
        assert {row['Spool number'] for row in setup} == {'SPOOL-' + group['assembly_number']}
        assert not book.formulas
    assert snapshot(api) == before


@pytest.mark.parametrize('suffix', ('bom.xlsx', 'bom-template.xlsx'))
def test_legacy_number_column_is_conditional_on_selected_scope(api, order_scope, suffix):
    project = order_scope['project']
    detail = api.get(f'/api/orders/{project}').json()
    detail, combined_id = add_gpn(api, detail, '000900')
    detail = add_assembly(api, detail, combined_id, 'COMBINED-C', required=1, part_number='000900')
    before = snapshot(api)
    material_sheet = 'BOM template' if suffix == 'bom-template.xlsx' else 'Bill of materials'
    book = download(api, project, suffix=suffix)
    for sheet in ('Assembly summary', material_sheet, 'Spool register'):
        assert 'Retained assembly part number' in book.headers(sheet)
        rows = values(book, sheet)
        assert all(row['Retained assembly part number'] == '000099-ASM-A'
                   for row in rows if row['Assembly ID'] == 'ASM-A')
        assert all(row['Retained assembly part number'] == ''
                   for row in rows if row['Assembly ID'] == 'COMBINED-C')
    for params in ({'gpn_id': combined_id}, {'assembly_id': 'COMBINED-C'}):
        scoped = download(api, project, suffix=suffix, **params)
        for sheet in ('Assembly summary', material_sheet, 'Spool register'):
            assert 'Retained assembly part number' not in scoped.headers(sheet)
            assert {row['Assembly ID'] for row in values(scoped, sheet)} == {'COMBINED-C'}
    assert snapshot(api) == before


def test_gpn_and_assembly_filters_never_leak_other_scope(api, order_scope):
    project = order_scope['project']
    first = download(api, project, gpn_id=order_scope['first_gpn'])
    assert {row['Assembly ID'] for row in values(first, 'Assembly summary')} == {'ASM-A'}
    assert {row['Spool ID'] for row in values(first, 'Bill of materials')} == {'SP-A'}
    second = download(api, project, assembly_id='ASM-B')
    assert {row['Spool ID'] for row in values(second, 'Bill of materials')} == {'SP-B'}
    for params in ({'gpn_id': 'missing'}, {'assembly_id': 'missing'},
                   {'gpn_id': order_scope['first_gpn'], 'assembly_id': 'ASM-B'}):
        assert api.get(f'/api/orders/{project}/bom.xlsx', params=params).status_code == 404
    foreign = make_order(api, 'FOREIGN-PO')
    foreign, gpn_id = add_gpn(api, foreign, 'FOREIGN-GPN')
    foreign = add_assembly(api, foreign, gpn_id, 'FOREIGN-ASM')
    assert api.get(f'/api/orders/{project}/bom.xlsx', params={'gpn_id': gpn_id}).status_code == 404
    assert api.get(f'/api/orders/{project}/bom-template.xlsx', params={'assembly_id': 'FOREIGN-ASM'}).status_code == 404


@pytest.mark.parametrize('role', tuple(BADGES))
def test_all_active_roles_can_download_scoped_bom_without_granting_full_export(api, order_scope, role):
    download(api, order_scope['project'], role=role)
    download(api, order_scope['project'], suffix='bom-template.xlsx', role=role)
    if role != 'admin':
        assert api.get('/api/exports/excel', role=role).status_code == 403


def test_download_requires_current_authentication_and_known_order(api, order_scope):
    for suffix in ('bom.xlsx', 'bom-template.xlsx'):
        assert api.get(f'/api/orders/{order_scope["project"]}/{suffix}', role=None).status_code == 401
        assert api.get(f'/api/orders/missing/{suffix}').status_code == 404


def test_template_is_editable_context_not_invented_material_or_receipt(api, order_scope):
    before = snapshot(api)
    book = download(api, order_scope['project'], suffix='bom-template.xlsx')
    assert list(book.sheets) == ['Assembly summary', 'BOM template', 'Spool register', 'Export info']
    rows = values(book, 'BOM template')
    assert all('Assembly description' not in row for row in values(book, 'Assembly summary'))
    assert all('Spool description' not in row for row in values(book, 'Spool register'))
    assert {row['Spool ID'] for row in rows} == {'SP-A', 'SP-B'}
    assert all(row['Material part number'] is None and row['Material description'] is None and
               row['Required quantity'] is None for row in rows)
    assert all(row['Unit'] == 'piece' for row in rows)
    assert not book.formulas
    info = {row['Entry']: row['Value'] for row in values(book, 'Export info')}
    assert 'does not change FabTrace' in info['Excel editing']
    assert snapshot(api) == before


def test_new_empty_order_and_unplanned_gpn_have_usable_blank_template(api):
    detail = make_order(api)
    project = detail['order']['project_id']
    book = download(api, project, suffix='bom-template.xlsx')
    rows = values(book, 'BOM template')
    assert len(rows) == 1 and rows[0]['PO number'] == '000012345'
    assert rows[0]['Required quantity'] is None and rows[0]['Spool ID'] == ''
    detail, gpn_id = add_gpn(api, detail, 'FUTURE-GPN')
    book = download(api, project, gpn_id=gpn_id)
    row = values(book, 'Bill of materials')[0]
    assert row['GPN'] == 'FUTURE-GPN' and row['Required quantity'] is None
    assert 'Finish assembly setup' in row['Planning status']


def test_legacy_unmapped_spools_and_assemblies_are_visible_unfiltered(api, order_scope):
    project = order_scope['project']
    plan(api, project, 'UNMAPPED-SP')
    part_lines(api, 'UNMAPPED-SP')
    plan(api, project, 'UNMAPPED-ASM', kind='Assembly')
    book = download(api, project)
    rows = values(book, 'Bill of materials')
    unmapped = [row for row in rows if row['Spool ID'] == 'UNMAPPED-SP']
    assert len(unmapped) == 2
    assert all('Not assigned' in row['Planning status'] for row in unmapped)
    asm = next(row for row in values(book, 'Assembly summary') if row['Assembly ID'] == 'UNMAPPED-ASM')
    assert asm['Required spools'] is None and 'not assigned' in asm['Planning status']
    filtered = download(api, project, gpn_id=order_scope['first_gpn'])
    assert 'UNMAPPED-SP' not in {row['Spool ID'] for row in values(filtered, 'Bill of materials')}
    assert 'UNMAPPED-ASM' not in {row['Assembly ID'] for row in values(filtered, 'Assembly summary')}


def test_long_unicode_notes_have_lossless_overflow_and_formula_safety(api, order_scope, monkeypatch):
    exports = importlib.import_module('exports')
    parts = importlib.import_module('parts')
    text_value = '=literal \U0001f527 Ω _x0001_ ' * 40
    with api.session_factory() as session:
        line = session.scalar(select(parts.PartLine).where(parts.PartLine.spool_id == 'SP-A', parts.PartLine.part_number == '000042'))
        line.notes = text_value
        session.commit()
    monkeypatch.setattr(exports, 'EXCEL_MAX_CELL_CHARS', 128)
    book = download(api, order_scope['project'])
    row = next(row for row in book.records('Bill of materials') if row['Material part number'].value == '000042')
    assert book.full_text(row, 'Line notes') == text_value
    assert not book.formulas
    assert 'Text overflow' in book.sheets


def test_full_admin_export_includes_order_models_with_exact_raw_columns(api, order_scope):
    response = api.get('/api/exports/excel')
    assert response.status_code == 200, response.text
    book = Workbook(response.content)
    assert book.headers('Purchase orders') == ['project_id', 'purchase_order', 'normalized_number',
        'customer', 'normalized_customer', 'notes', 'version', 'created_by', 'created_at', 'updated_at']
    assert book.headers('Order GPNs') == ['id', 'project_id', 'gpn', 'normalized_gpn', 'gpn_label',
        'assembly_number', 'normalized_assembly_number', 'description', 'created_by', 'created_at', 'updated_at']
    assert book.headers('Order assemblies') == ['item_id', 'gpn_id', 'assembly_part_number',
        'required_spools', 'notes', 'created_by', 'created_at', 'updated_at']
    assert values(book, 'Purchase orders')[0]['purchase_order'] == '000012345'
    assert len(values(book, 'Order assemblies')) == 2

