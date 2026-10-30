"""Explicit order quantities survive reversible physical-record removal."""
import importlib

import pytest
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import ok
from test_progress import database_state
from test_removal_orders import change


def setup_body(number='SETUP-REMOVAL-001'):
    return {'expected_version': 0, 'purchase_order': number, 'assemblies': [{
        'gpn': '000-GPN-001', 'assembly_quantity': 2,
        'spools': [
            {'spool_number': '000-SP-A', 'quantity_per_assembly': 2},
            {'spool_number': '000-SP-B', 'quantity_per_assembly': 1},
        ],
    }]}


def create_setup(api):
    detail = ok(api.post('/api/order-setup', setup_body()), 201)
    return detail['order']['project_id'], detail['assemblies'][0]['gpn_id'], detail


def current(api, project_id):
    return ok(api.get('/api/order-setup/' + project_id))


def physical_assembly(api, project_id, gpn_id, item_id='SETUP-PHYSICAL-ASSEMBLY'):
    detail = current(api, project_id)
    return ok(api.post(f'/api/orders/{project_id}/assemblies', {
        'expected_version': detail['order']['version'], 'gpn_id': gpn_id,
        'item_id': item_id, 'assembly_part_number': '000-GPN-001',
        'required_spools': 3,
        'create_item': {'id': item_id,
            'google_part_number': '000-GPN-001', 'location': 'Synthetic receiving',
            'handler': BADGES['handler']},
    }), 201)


def planning_rows(api):
    setup = importlib.import_module('order_setup')
    with api.session_factory() as session:
        return (
            [(row.gpn_id, row.assembly_quantity) for row in session.scalars(
                select(setup.OrderAssemblyRequirement).order_by(setup.OrderAssemblyRequirement.gpn_id))],
            [(row.id, row.gpn_id, row.spool_number, row.quantity_per_assembly, row.active)
             for row in session.scalars(select(setup.OrderSpoolRequirement)
                .order_by(setup.OrderSpoolRequirement.id))],
        )


def test_last_physical_assembly_removal_retains_explicit_required_quantity(api):
    project, gpn, _ = create_setup(api)
    physical_assembly(api, project, gpn)
    planned = planning_rows(api)
    preview = ok(api.get('/api/removals/item/SETUP-PHYSICAL-ASSEMBLY'))
    assert preview['counts'] == {'orders': 0, 'gpns': 0, 'items': 1}
    change(api, 'item', 'SETUP-PHYSICAL-ASSEMBLY')

    detail = current(api, project)
    assert len(detail['assemblies']) == 1
    assert detail['assemblies'][0]['gpn_id'] == gpn
    assert detail['assemblies'][0]['assembly_quantity'] == 2
    assert detail['assemblies'][0]['registered_assemblies'] == 0
    assert not detail['assemblies'][0]['editable'], 'Removed physical history still locks its planning basis'
    assert planning_rows(api) == planned
    assert ok(api.get(f'/api/orders/{project}'))['gpns'][0]['id'] == gpn

    change(api, 'item', 'SETUP-PHYSICAL-ASSEMBLY', 'restore')
    restored = current(api, project)
    assert restored['assemblies'][0]['registered_assemblies'] == 1
    assert planning_rows(api) == planned
    assert ok(api.get('/api/items/SETUP-PHYSICAL-ASSEMBLY'))['id'] == 'SETUP-PHYSICAL-ASSEMBLY'


def test_gpn_removal_hides_inherited_plan_and_restore_preserves_earlier_item_removal(api):
    project, gpn, _ = create_setup(api)
    physical_assembly(api, project, gpn)
    change(api, 'item', 'SETUP-PHYSICAL-ASSEMBLY')
    planned = planning_rows(api)
    change(api, 'gpn', gpn)
    assert current(api, project)['assemblies'] == []
    assert planning_rows(api) == planned

    change(api, 'gpn', gpn, 'restore')
    restored = current(api, project)
    assert restored['assemblies'][0]['gpn_id'] == gpn
    assert restored['assemblies'][0]['assembly_quantity'] == 2
    assert restored['assemblies'][0]['registered_assemblies'] == 0
    assert ok(api.get('/api/items/SETUP-PHYSICAL-ASSEMBLY'))['removal']['removed']
    assert planning_rows(api) == planned


def test_po_removal_and_restore_preserve_quantity_and_spool_line_identities(api):
    project, gpn, before = create_setup(api)
    planned = planning_rows(api)
    change(api, 'order', project)
    assert project not in {row['project_id'] for row in ok(api.get('/api/order-setup'))['orders']}
    assert planning_rows(api) == planned
    change(api, 'order', project, 'restore')
    restored = current(api, project)
    assert restored['assemblies'][0]['gpn_id'] == gpn
    assert restored['assemblies'][0]['spools'] == before['assemblies'][0]['spools']
    assert restored['totals'] == before['totals']
    assert planning_rows(api) == planned


@pytest.mark.parametrize('kind', ['order', 'gpn'])
def test_setup_correction_invalidates_an_older_removal_preview(api, kind):
    project, gpn, before = create_setup(api)
    record_id = project if kind == 'order' else gpn
    preview = ok(api.get(f'/api/removals/{kind}/{record_id}'))
    branch = setup_body()['assemblies'][0]
    branch['assembly_quantity'] = 3
    corrected = ok(api.patch(f'/api/order-setup/{project}/assemblies/{gpn}', {
        'expected_version': before['order']['version'], 'reason': 'Correct required assembly quantity',
        **branch,
    }))
    assert corrected['assemblies'][0]['assembly_quantity'] == 3
    after_correction = database_state(api)
    response = api.post(f'/api/removals/{kind}/{record_id}/remove', {
        'expected_version': preview['expected_version'], 'preview_token': preview['preview_token'],
        'confirmation': preview['confirmation'], 'reason': 'Stale removal must not erase revised quantities',
    })
    assert response.status_code == 409, response.text
    assert database_state(api) == after_correction


def test_removed_quantity_plan_cannot_be_edited_or_recreated_as_an_active_gpn(api):
    project, gpn, _ = create_setup(api)
    change(api, 'gpn', gpn)
    version = current(api, project)['order']['version']
    branch = setup_body()['assemblies'][0]
    before = database_state(api)
    responses = [
        api.patch(f'/api/order-setup/{project}/assemblies/{gpn}', {
            'expected_version': version, 'reason': 'A removed requirement must be restored', **branch,
        }),
        api.post(f'/api/order-setup/{project}/assemblies', {'expected_version': version, **branch}),
    ]
    assert all(response.status_code == 409 for response in responses), [response.text for response in responses]
    assert database_state(api) == before


def test_restoring_original_assembly_cannot_overfill_replacement_capacity(api):
    body = setup_body()
    body['assemblies'][0]['assembly_quantity'] = 1
    detail = ok(api.post('/api/order-setup', body), 201)
    project, gpn = detail['order']['project_id'], detail['assemblies'][0]['gpn_id']
    physical_assembly(api, project, gpn)
    change(api, 'item', 'SETUP-PHYSICAL-ASSEMBLY')
    physical_assembly(api, project, gpn, 'SETUP-REPLACEMENT-ASSEMBLY')
    before = database_state(api)
    preview = ok(api.get('/api/removals/item/SETUP-PHYSICAL-ASSEMBLY', params={'action': 'restore'}))
    assert not preview['can_proceed']
    assert any('planned assembly quantity' in value for value in preview['blockers'])
    response = api.post('/api/removals/item/SETUP-PHYSICAL-ASSEMBLY/restore', {
        'expected_version': preview['expected_version'], 'preview_token': preview['preview_token'],
        'confirmation': preview['confirmation'], 'reason': 'Restore original despite filled replacement capacity',
    })
    assert response.status_code == 409, response.text
    assert database_state(api) == before

    change(api, 'item', 'SETUP-REPLACEMENT-ASSEMBLY')
    change(api, 'item', 'SETUP-PHYSICAL-ASSEMBLY', 'restore')
    assert current(api, project)['assemblies'][0]['registered_assemblies'] == 1
    assert not ok(api.get('/api/items/SETUP-PHYSICAL-ASSEMBLY'))['removal']['removed']
    assert ok(api.get('/api/items/SETUP-REPLACEMENT-ASSEMBLY'))['removal']['removed']
