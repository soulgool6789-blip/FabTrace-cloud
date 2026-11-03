"""Quantity setup stays visible in progress and separate from physical BOMs."""
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import ok
from test_exports import Workbook
from test_order_setup import branch, create_setup, detail
from test_progress import database_state


def two_branches(api):
    return create_setup(api, assemblies=[branch(), branch('000-GPN-B', 2, [
        {'spool_number': '000-SP-C', 'quantity_per_assembly': 4}])])


def register_assembly(api, setup, index=0, item_id='PHYSICAL-ASSEMBLY-1'):
    project_id = setup['order']['project_id']
    current = detail(api, project_id)
    row = current['assemblies'][index]
    return ok(api.post(f'/api/orders/{project_id}/gpn-assemblies', {
        'expected_version': current['order']['version'], 'gpn_id': row['gpn_id'],
        'gpn': row['gpn'], 'assembly_number': row['assembly_number'],
        'required_spools': row['spools_per_assembly'],
        'create_item': {'id': item_id, 'handler': BADGES['handler'], 'location': 'Receiving'},
    }), 201)


def register_spool(api, project_id, assembly_id, number='000-SP-A', item_id='PHYSICAL-SPOOL-1'):
    ok(api.post('/api/items', {'id': item_id, 'kind': 'Spool', 'project': project_id,
        'google_part_number': number, 'location': 'Receiving', 'handler': BADGES['handler'],
        'welds_required': 0}), 201)
    ok(api.post(f'/api/tracking/spools/{item_id}/plan', {
        'project_id': project_id, 'assembly_id': assembly_id, 'planned_welds': 0,
        'zero_weld_reason': 'Synthetic bolted scope', 'drawing_revision': 'Synthetic Rev A'}))
    return item_id


def test_saved_quantities_appear_in_progress_without_inventing_physical_steps(api):
    setup = two_branches(api)
    project_id = setup['order']['project_id']
    before = database_state(api)
    report = ok(api.get('/api/progress/orders', params={'project_id': project_id}))
    assert report['summary']['items'] == 0
    assert report['summary']['total_steps'] == 0
    assert report['summary']['percent'] is None
    assert report['summary']['missing_assemblies'] == 5
    assert report['summary']['missing_spools'] == 17
    assert not report['summary']['complete'] and not report['summary']['scope_complete']
    groups = report['orders'][0]['gpns']
    assert all(not row['setup_needed'] and row['registration_needed'] for row in groups)
    assert [row['quantity_plan']['assembly_quantity'] for row in groups] == [3, 2]
    assert [row['summary']['missing_spools'] for row in groups] == [9, 8]
    assert database_state(api) == before


def test_progress_counts_registered_and_unregistered_quantity_shortages_once(api):
    setup = two_branches(api)
    project_id = setup['order']['project_id']
    register_assembly(api, setup)
    first = ok(api.get('/api/progress/orders', params={'project_id': project_id}))
    assert first['summary']['items'] == 1
    assert first['summary']['missing_assemblies'] == 4
    assert first['summary']['missing_spools'] == 17
    assert first['summary']['total_steps'] == 6
    register_spool(api, project_id, 'PHYSICAL-ASSEMBLY-1')
    second = ok(api.get('/api/progress/orders', params={'project_id': project_id}))
    assert second['summary']['items'] == 2
    assert second['summary']['missing_assemblies'] == 4
    assert second['summary']['missing_spools'] == 16
    assert second['summary']['total_steps'] == 14
    assert second['summary']['completed_steps'] == 0
    other = create_setup(api, number='000124')
    all_orders = ok(api.get('/api/progress/orders'))
    assert all_orders['summary']['missing_assemblies'] == 7
    assert all_orders['summary']['missing_spools'] == 25
    selected = ok(api.get('/api/progress/orders', params={'project_id': other['order']['project_id']}))
    assert selected['summary']['missing_assemblies'] == 3
    assert selected['summary']['missing_spools'] == 9


def workbook(api, project_id, **filters):
    response = api.get(f'/api/orders/{project_id}/bom.xlsx', params=filters)
    assert response.status_code == 200, response.text
    return Workbook(response.content)


def test_setup_excel_preserves_text_numbers_and_multiplies_only_business_quantities(api):
    setup = two_branches(api)
    project_id = setup['order']['project_id']
    before = database_state(api)
    book = workbook(api, project_id)
    rows = book.records('Setup quantities')
    assert [row['Total quantity'].value for row in rows] == [6, 3, 8]
    assert [row['Assembly quantity'].value for row in rows] == [3, 3, 2]
    assert [row['Quantity per assembly'].value for row in rows] == [2, 1, 4]
    assert all(row['PO number'].value == '000123' and row['PO number'].kind == 'inlineStr' for row in rows)
    assert all(row['Spool number'].value.startswith('000-SP-') for row in rows)
    assert not book.formulas
    assert all(row['Required quantity'].value is None for row in book.records('Bill of materials'))
    assert database_state(api) == before


def test_physical_assembly_excel_uses_one_unit_and_does_not_multiply_component_bom(api):
    setup = two_branches(api)
    project_id = setup['order']['project_id']
    register_assembly(api, setup)
    spool_id = register_spool(api, project_id, 'PHYSICAL-ASSEMBLY-1')
    ok(api.put(f'/api/parts/spools/{spool_id}/plan', {
        'expected_version': 0, 'reference': 'SYNTHETIC-BOM', 'reason': 'Set actual component scope',
        'lines': [{'part_number': 'MAT-00001', 'description': 'Synthetic component', 'required_qty': 4}]}))
    before = database_state(api)
    book = workbook(api, project_id, assembly_id='PHYSICAL-ASSEMBLY-1')
    rows = book.records('Setup quantities')
    assert [row['Assembly quantity'].value for row in rows] == [1, 1]
    assert [row['Total quantity'].value for row in rows] == [2, 1]
    assert all(row['Assembly ID'].value == 'PHYSICAL-ASSEMBLY-1' for row in rows)
    bom = book.records('Bill of materials')
    assert len(bom) == 1 and bom[0]['Required quantity'].value == 4
    whole = workbook(api, project_id)
    material = [row for row in whole.records('Bill of materials') if row['Spool ID'].value == spool_id]
    assert len(material) == 1 and material[0]['Required quantity'].value == 4
    assert database_state(api) == before


def test_backend_excel_includes_both_quantity_tables_and_retained_lines(api):
    setup = two_branches(api)
    response = api.get('/api/exports/excel')
    assert response.status_code == 200, response.text
    book = Workbook(response.content)
    assert len(book.records('Assembly quantity plans')) == 2
    assert len(book.records('Spool quantity plans')) == 3
    assert {row['assembly_quantity'].value for row in book.records('Assembly quantity plans')} == {2, 3}
    with api.session_factory() as session:
        assert len(session.execute(select(api.application.Base.metadata.tables['items'])).all()) == 0

