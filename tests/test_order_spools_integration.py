"""PO-created spool identities participate in existing work without inventing it."""
import importlib

import pytest
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import ok
from test_exports import Workbook
from test_flow import inspect_dimensions
from test_order_setup import branch, create_setup
from test_production_progress import flatten
from test_progress import database_state
from test_removal_orders import change


@pytest.fixture(autouse=True)
def public_qr_url(application, monkeypatch):
    monkeypatch.setattr(application, 'PUBLIC_BASE_URL', 'https://spool-integration.example')


def labels(api, project):
    return ok(api.get(f'/api/order-labels/{project}/labels', params={'kind': 'Spool'}))


def generate(api, project):
    overview = ok(api.get(f'/api/order-labels/{project}', params={'kind': 'Spool'}))
    return ok(api.post(f'/api/order-labels/{project}/generate', {
        'expected_version': overview['order']['version'], 'kind': 'Spool',
        'location': 'Synthetic spool receiving', 'handler': BADGES['handler'],
    }))


def registered(api, quantity=2):
    setup = create_setup(api, assemblies=[branch(quantity=quantity)])
    project = setup['order']['project_id']
    result = generate(api, project)
    assert result['created_assembly_count'] == quantity
    assert result['created_spool_count'] == quantity * 3
    rows = labels(api, project)['items']
    parents = sorted({row['assembly_id'] for row in rows})
    return project, parents, rows


def plan(api, project, row, **values):
    return api.post(f'/api/tracking/spools/{row["id"]}/plan', {
        'project_id': project, 'assembly_id': row['assembly_id'],
        'planned_welds': 1, 'drawing_revision': 'SYNTHETIC SPOOL Rev A', **values,
    })


def test_registered_children_have_real_parent_scope_but_no_work_or_release(api):
    project, parents, rows = registered(api)
    before = database_state(api)
    by_parent = {parent: {row['id'] for row in rows if row['assembly_id'] == parent}
                 for parent in parents}
    for parent in parents:
        flow = ok(api.get(f'/api/flow/items/{parent}'))
        assert {child['item_id'] for child in flow['spools']} == by_parent[parent]
        assert all(child['project_id'] == project for child in flow['spools'])
    for row in rows:
        flow = ok(api.get(f'/api/flow/items/{row["id"]}'))
        assert flow['parent']['item_id'] == row['assembly_id']
        assert flow['suggested_route'] == 'spool' and flow['flow'] is None
        tracking = ok(api.get(f'/api/tracking/spools/{row["id"]}'))
        assert tracking['registered_assembly_id'] == row['assembly_id']
        assert tracking['plan'] is None and tracking['welds'] == []
        assert not tracking['item']['released']
    assert database_state(api) == before, 'Reading scope must not enroll fabrication'

    spool = rows[0]['id']
    inspect_dimensions(api, spool)
    before_release = database_state(api)
    rejected = api.post(f'/api/items/{spool}/release', {'reference': 'SYNTHETIC-RELEASE'}, role='inspector')
    assert rejected.status_code == 409 and 'actual weld plan' in rejected.text
    assert database_state(api) == before_release
    with api.session_factory() as session:
        for name in ('tracking_spool_plans', 'tracking_welds', 'flow_plans', 'flow_events',
                     'tracking_process_events', 'item_transfer_states'):
            assert session.execute(select(api.application.Base.metadata.tables[name])).all() == []


def test_real_weld_plan_keeps_registered_parent_and_counts_identity_once(api):
    project, parents, rows = registered(api)
    spool = rows[0]
    alternate = next(parent for parent in parents if parent != spool['assembly_id'])
    before = database_state(api)
    for values in ({'assembly_id': None}, {'assembly_id': alternate}, {'planned_welds': 0}):
        response = plan(api, project, spool, **values)
        assert response.status_code in (409, 422), response.text
        assert database_state(api) == before
    saved = ok(plan(api, project, spool))
    assert saved['plan']['assembly_id'] == spool['assembly_id']
    assert saved['plan']['planned_welds'] == 1 and saved['welds'] == []
    assert saved['registered_assembly_id'] == spool['assembly_id']
    order = ok(api.get(f'/api/orders/{project}'))
    assembly = next(row for row in order['assemblies'] if row['item_id'] == spool['assembly_id'])
    assert assembly['linked_spools'] == 3 and assembly['missing_spools'] == 0
    assert len({row['item_id'] for row in assembly['spools']}) == 3
    current_labels = labels(api, project)
    assert current_labels['total'] == 6
    assert next(row for row in current_labels['items'] if row['id'] == spool['id'])['weld_plan_exists']
    assert generate(api, project)['created_count'] == 0
    before = database_state(api)
    assert plan(api, project, spool, expected_version=saved['plan']['version'], assembly_id=None).status_code == 409
    assert database_state(api) == before


def test_progress_places_unplanned_spools_under_each_parent_once(api):
    project, parents, rows = registered(api)
    for planned in (False, True):
        if planned:
            ok(plan(api, project, rows[0]))
        before = database_state(api)
        report = ok(api.get('/api/progress/orders', params={'project_id': project}))
        nodes = flatten(report)
        assert set(nodes) == set(parents) | {row['id'] for row in rows}
        assert report['summary']['items'] == 8 and report['summary']['spools'] == 6
        assert report['summary']['missing_spools'] == report['summary']['missing_assemblies'] == 0
        assert report['summary']['completed_steps'] == 0 and report['summary']['finished'] == 0
        assert not report['summary']['complete']
        for row in rows:
            node = nodes[row['id']]
            assert node['parent_id'] == row['assembly_id'] and node['route'] == 'spool'
            assert not node['route_started'] and node['progress']['completed'] == 0
            assert row['id'] in {child['id'] for child in nodes[row['assembly_id']]['children']}
        raw = ok(api.get(f'/api/progress/projects/{project}'))
        assert raw['total'] == 8
        assert all(row['scope_source'] == 'order_spool_registration'
                   for row in raw['items'] if row['id'] in {spool['id'] for spool in rows})
        assert database_state(api) == before


def test_a_real_zero_weld_plan_still_needs_its_recorded_spool_traveler(api):
    project, _, rows = registered(api, quantity=1)
    spool = rows[0]
    ok(plan(api, project, spool, planned_welds=0,
            zero_weld_reason='Synthetic controlled bolted spool scope'))
    inspect_dimensions(api, spool['id'])
    before = database_state(api)
    response = api.post(f'/api/items/{spool["id"]}/release',
        {'reference': 'SYNTHETIC-TRAVELER-BYPASS'}, role='inspector')
    assert response.status_code == 409 and 'spool traveler' in response.text
    assert database_state(api) == before


def test_single_unplanned_spool_removal_replacement_and_capacity_safe_restore(api):
    project, parents, rows = registered(api, quantity=1)
    original = rows[0]
    change(api, 'item', original['id'])
    assert labels(api, project)['total'] == 2
    assembly = ok(api.get(f'/api/orders/{project}'))['assemblies'][0]
    assert assembly['linked_spools'] == 2 and assembly['missing_spools'] == 1
    assert len(ok(api.get(f'/api/flow/items/{parents[0]}'))['spools']) == 2
    assert ok(api.get('/api/progress/orders', params={'project_id': project}))['summary']['missing_spools'] == 1
    before = database_state(api)
    assert plan(api, project, original).status_code == 409
    assert database_state(api) == before

    result = generate(api, project)
    assert result['created_count'] == result['created_spool_count'] == 1
    assert result['created_assembly_count'] == 0
    replacement = result['created_ids'][0]
    assert replacement != original['id']
    assert {row['id'] for row in labels(api, project)['items']} == (
        {row['id'] for row in rows} - {original['id']} | {replacement})
    assert generate(api, project)['created_count'] == 0
    assert len(ok(api.get(f'/api/flow/items/{parents[0]}'))['spools']) == 3
    ok(api.post(f'/api/tracking/spools/{parents[0]}/plan', {
        'project_id': project, 'planned_welds': 0,
        'zero_weld_reason': 'Synthetic bolted assembly with three child spools',
    }))
    ok(api.post(f'/api/flow/items/{parents[0]}/start', {
        'route': 'assembly', 'expected_children': 3,
    }), 201)
    progress = ok(api.get(f'/api/progress/projects/{project}'))
    parent_progress = next(row for row in progress['items'] if row['id'] == parents[0])
    assert not any('Child scope incomplete' in blocker for blocker in parent_progress['blockers'])
    preview = ok(api.get(f'/api/removals/item/{original["id"]}', params={'action': 'restore'}))
    assert not preview['can_proceed'] and any('quantity' in blocker or 'required spools' in blocker
                                              for blocker in preview['blockers'])
    before = database_state(api)
    rejected = api.post(f'/api/removals/item/{original["id"]}/restore', {
        'expected_version': preview['expected_version'], 'preview_token': preview['preview_token'],
        'confirmation': preview['confirmation'], 'reason': 'Synthetic capacity conflict check',
    })
    assert rejected.status_code == 409 and database_state(api) == before

    change(api, 'item', replacement)
    change(api, 'item', original['id'], 'restore')
    assert {row['id'] for row in labels(api, project)['items']} == {row['id'] for row in rows}
    assert generate(api, project)['created_count'] == 0
    registry = importlib.import_module('order_spools')
    with api.session_factory() as session:
        assert session.get(registry.OrderSpool, original['id']).assembly_id == parents[0]
        assert session.get(registry.OrderSpool, replacement).assembly_id == parents[0]


def test_spool_restore_respects_each_number_even_when_total_capacity_fits(api):
    project, _, rows = registered(api, quantity=1)
    original_a = next(row for row in rows if row['spool_number'] == '000-SP-A')
    original_b = next(row for row in rows if row['spool_number'] == '000-SP-B')
    change(api, 'item', original_a['id'])
    assert generate(api, project)['created_spool_count'] == 1
    change(api, 'item', original_b['id'])
    assert labels(api, project)['total'] == 2
    preview = ok(api.get(f'/api/removals/item/{original_a["id"]}', params={'action': 'restore'}))
    assert not preview['can_proceed']
    assert any('spool 000-SP-A' in blocker for blocker in preview['blockers'])
    assert not any('required spools' in blocker for blocker in preview['blockers']), 'Total would fit; the spool-number cap must block it'
    change(api, 'item', original_b['id'], 'restore')
    assert labels(api, project)['total'] == 3


def test_parent_removal_cascades_registry_and_retains_independent_child_removal(api):
    project, parents, rows = registered(api, quantity=1)
    change(api, 'item', rows[0]['id'])
    preview = ok(api.get(f'/api/removals/item/{parents[0]}'))
    assert preview['counts'] == {'orders': 0, 'gpns': 0, 'items': 3}
    change(api, 'item', parents[0])
    assert labels(api, project)['total'] == 0
    assert len(ok(api.get(f'/api/flow/items/{parents[0]}'))['spools']) == 3, 'Removed parent preserves history'
    assert all(ok(api.get(f'/api/items/{row["id"]}'))['removal']['removed'] for row in rows)
    change(api, 'item', parents[0], 'restore')
    assert labels(api, project)['total'] == 2
    assert ok(api.get(f'/api/items/{rows[0]["id"]}'))['removal']['removed']
    change(api, 'item', rows[0]['id'], 'restore')
    assert {row['id'] for row in labels(api, project)['items']} == {row['id'] for row in rows}
    ok(plan(api, project, rows[0]))
    planned_preview = ok(api.get(f'/api/removals/item/{rows[0]["id"]}'))
    assert not planned_preview['can_proceed'] and 'planned work' in ' '.join(planned_preview['blockers'])


def test_export_retains_registered_spools_without_invented_bom_or_duplicates(api):
    project, parents, rows = registered(api, quantity=1)
    ok(plan(api, project, rows[0]))
    before = database_state(api)
    response = api.get(f'/api/orders/{project}/bom.xlsx')
    assert response.status_code == 200, response.text
    book = Workbook(response.content)
    register = book.records('Spool register')
    assert len(register) == 3
    assert {row['Spool ID'].value for row in register} == {row['id'] for row in rows}
    assert {row['Assembly ID'].value for row in register} == set(parents)
    assert all(row['Required quantity'].value is None for row in book.records('Bill of materials'))
    raw = api.get('/api/exports/excel')
    assert raw.status_code == 200, raw.text
    backend = Workbook(raw.content)
    registrations = backend.records('Registered order spools')
    assert len(registrations) == 3
    assert {row['item_id'].value for row in registrations} == {row['id'] for row in rows}
    assert len(backend.records('Spool plans')) == 1
    assert database_state(api) == before
