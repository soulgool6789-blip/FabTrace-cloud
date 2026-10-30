"""Removed planning records stay out of live orders and retain exportable history."""
import importlib

from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import ok
from test_orders import new_order, setup, plan, add_assembly, current, version
from test_order_exports import download, values
from test_exports import Workbook
from test_progress import database_state


def change(api, kind, record_id, action='remove'):
    preview = ok(api.get(f'/api/removals/{kind}/{record_id}', params={'action': action}))
    assert preview['can_proceed'], preview
    return ok(api.post(f'/api/removals/{kind}/{record_id}/{action}', {
        'expected_version': preview['expected_version'],
        'preview_token': preview['preview_token'],
        'confirmation': preview['confirmation'],
        'reason': 'Correcting a synthetic planning entry for removal coverage',
    }))


def test_removed_gpn_branch_excluded_from_active_order_and_unmapped_bom_fallback(api):
    project, gpn, detail = setup(api, count=1)
    api.item('REMOVE-SPOOL-01', kind='Spool', welds_required=0)
    ok(plan(api, 'REMOVE-SPOOL-01', project, 'ORDER-ASM-01'))
    before = current(api, project)
    change(api, 'gpn', gpn)
    hidden = current(api, project)
    assert hidden['gpns'] == hidden['assemblies'] == hidden['available_assemblies'] == []
    assert hidden['totals']['combined_count'] == 0
    book = download(api, project)
    assert b'REMOVE-SPOOL-01' not in book.xml
    assert b'ORDER-ASM-01' not in book.xml
    assert ok(api.get('/api/items/REMOVE-SPOOL-01'))['removal']['removed']
    before_failed = database_state(api)
    response = api.post(f'/api/orders/{project}/gpn-assemblies', {
        'expected_version': version(api, project), 'gpn': 'GPN-001', 'required_spools': 1,
        'create_item': {'location': 'Test receiving', 'handler': BADGES['handler']},
    })
    assert response.status_code == 409, response.text
    assert database_state(api) == before_failed
    change(api, 'gpn', gpn, 'restore')
    restored = current(api, project)
    assert restored['totals'] == before['totals']
    assert restored['assemblies'][0]['spools'][0]['item_id'] == 'REMOVE-SPOOL-01'
    assert not restored['assemblies'][0]['spools'][0]['ready_for_assembly']


def test_removed_po_is_not_offered_as_an_unassigned_project_and_keeps_reserved_number(api):
    project, gpn, detail = setup(api)
    change(api, 'order', project)
    register = ok(api.get('/api/orders'))
    assert project not in {r['project_id'] for r in register['orders']}
    assert project not in {r['id'] for r in register['unassigned_projects']}
    historical = current(api, project)
    assert historical['order']['removal']['removed']
    assert not historical['permissions']['can_manage']
    assert not historical['permissions']['can_remove']
    assert historical['gpns'][0]['id'] == gpn
    assert historical['assemblies'][0]['item_id'] == 'ORDER-ASM-01'
    book = download(api, project)
    info = {r['Entry']: r['Value'] for r in values(book, 'Export info')}
    assert 'Removed' in info['Record status']
    before_failed = database_state(api)
    duplicate = api.post('/api/orders', {'expected_version': 0, 'purchase_order': 'PO-100',
        'customer': 'Synthetic customer'})
    assert duplicate.status_code == 409 and 'Restore' in duplicate.text
    assert database_state(api) == before_failed
    change(api, 'order', project, 'restore')
    assert current(api, project)['permissions']['can_manage']
    assert project in {r['project_id'] for r in ok(api.get('/api/orders'))['orders']}


def test_single_combined_assembly_removal_does_not_reappear_as_finish_setup(api):
    project, gpn, _ = setup(api)
    change(api, 'item', 'ORDER-ASM-01')
    detail = current(api, project)
    assert detail['gpns'] == [] and detail['totals']['setup_needed_count'] == 0
    change(api, 'item', 'ORDER-ASM-01', 'restore')
    detail = current(api, project)
    assert detail['gpns'][0]['id'] == gpn and detail['assemblies'][0]['item_id'] == 'ORDER-ASM-01'


def test_shared_gpn_number_stays_locked_while_an_older_physical_instance_is_removed(api):
    project, gpn, _ = setup(api)
    add_assembly(api, project, gpn, item_id='ORDER-ASM-02', count=1)
    change(api, 'item', 'ORDER-ASM-01')
    detail = current(api, project)
    assert [r['item_id'] for r in detail['assemblies']] == ['ORDER-ASM-02']
    assert not detail['assemblies'][0]['number_editable']
    assert detail['totals']['required_spools'] == 1
    change(api, 'item', 'ORDER-ASM-01', 'restore')
    assert current(api, project)['totals']['required_spools'] == 3


def test_admin_backend_excel_includes_removal_state_and_unchanged_physical_identity(api):
    project = new_order(api)['order']['project_id']
    change(api, 'order', project)
    before = database_state(api)
    response = api.get('/api/exports/excel')
    assert response.status_code == 200, response.text
    book = Workbook(response.content)
    rows = values(book, 'Removed record states')
    row = next(row for row in rows if row['kind'] == 'order' and row['record_id'] == project)
    assert row['removed'] in (True, 1) and row['reason']
    assert any(row['project_id'] == project for row in values(book, 'Purchase orders'))
    assert database_state(api) == before


def test_removed_empty_gpn_cannot_be_edited_or_filled_through_legacy_api(api):
    orders = importlib.import_module('orders')
    from test_orders import group, assembly_body
    project = new_order(api)['order']['project_id']
    gpn = group(api, project)
    change(api, 'gpn', gpn)
    before = database_state(api)
    responses = [
        api.patch(f'/api/orders/{project}/gpns/{gpn}', {'expected_version': version(api, project),
            'gpn': 'REIDENTIFIED', 'reason': 'Do not change a removed GPN'}),
        api.post(f'/api/orders/{project}/assemblies', assembly_body(api, project, gpn)),
    ]
    assert all(r.status_code == 409 for r in responses), [r.text for r in responses]
    assert database_state(api) == before
    with api.session_factory() as session:
        assert session.scalar(select(orders.OrderGpn).where(orders.OrderGpn.id == gpn)).gpn == 'GPN-001'
