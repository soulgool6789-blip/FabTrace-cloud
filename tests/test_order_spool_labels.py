"""PO-derived spool QR identities retain exact physical parent and scope."""
from collections import Counter, defaultdict
import importlib

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import ok
from test_order_setup import branch, create_setup
from test_order_setup_integration import register_assembly, register_spool
from test_order_labels import (ROOT, PUBLIC_URL, generate, generation_body,
                               labels, overview, public_qr_url)
from test_progress import database_state
from test_removal_orders import change


def scoped_setup(api):
    return create_setup(api, assemblies=[
        branch('000-GPN-A', 3, [{'spool_number': '000-SP-A', 'quantity_per_assembly': 2}]),
        branch('000-GPN-B', 2, [{'spool_number': '000-SP-B', 'quantity_per_assembly': 1}]),
    ])


def test_spool_overview_reads_saved_total_quantities_without_registration(api):
    setup = scoped_setup(api)
    project = setup['order']['project_id']
    before = database_state(api)
    result = overview(api, project, kind='Spool')
    assert result['kind'] == 'Spool'
    assert [row['planned_quantity'] for row in result['groups']] == [6, 2]
    assert [row['assembly_quantity'] for row in result['groups']] == [3, 2]
    assert [row['remaining_assembly_quantity'] for row in result['groups']] == [3, 2]
    assert result['totals'] == {'registered_quantity': 0, 'remaining_quantity': 8,
        'undeclared_groups': 0, 'remaining_weld_spools': 0, 'undeclared_weld_spools': 0}
    assert labels(api, project, kind='Spool')['items'] == []
    assert overview(api, project)['totals']['remaining_quantity'] == 8
    assert database_state(api) == before


def test_spool_generation_creates_missing_parents_and_exact_child_quantity_without_work(api):
    setup = scoped_setup(api)
    project = setup['order']['project_id']
    result = generate(api, project, kind='Spool')
    assert result['created_count'] == 13
    assert result['created_assembly_count'] == 5 and result['created_spool_count'] == 8
    assert result['remaining_quantity'] == 0 and result['order']['version'] == 2
    assert [row['registered_quantity'] for row in result['groups']] == [6, 2]
    assert [row['registered_assembly_quantity'] for row in result['groups']] == [3, 2]
    output = labels(api, project, kind='Spool')
    assert output['total'] == len(output['items']) == 8
    assert labels(api, project)['total'] == 8
    assert len(set(result['created_ids'])) == 13
    registry = importlib.import_module('order_spools')
    orders = importlib.import_module('orders')
    setup_models = importlib.import_module('order_setup')
    by_parent = defaultdict(Counter)
    with api.session_factory() as session:
        for row in output['items']:
            item = session.get(api.application.Item, row['id'])
            mapping = session.get(registry.OrderSpool, item.id)
            parent = session.get(orders.OrderAssembly, mapping.assembly_id)
            requirement = session.get(setup_models.OrderSpoolRequirement, mapping.requirement_id)
            assert item.id.startswith('SPL-') and item.kind == row['kind'] == 'Spool'
            assert item.google_part_number == row['spool_number'] == requirement.spool_number
            assert row['assembly_id'] == parent.item_id
            assert row['gpn_id'] == parent.gpn_id == requirement.gpn_id
            assert item.project == project and item.handler == BADGES['handler']
            assert item.location == 'Synthetic receiving bay'
            assert not row['weld_plan_exists'] and not item.released
            assert item.welds_done == item.welds_required == 0
            assert item.dimensional == item.weld == 'Not started'
            assert row['qr_url'] == PUBLIC_URL + '/?item=' + item.id
            by_parent[parent.item_id][row['spool_number']] += 1
        assert len(by_parent) == 5
        assert Counter(tuple(sorted(numbers.items())) for numbers in by_parent.values()) == {
            (('000-SP-A', 2),): 3, (('000-SP-B', 1),): 2}
        for name in ('tracking_spool_plans', 'tracking_welds', 'flow_plans', 'flow_events',
                     'tracking_process_events', 'inspections', 'reworks', 'item_transfer_events'):
            table = api.application.Base.metadata.tables.get(name)
            if table is not None:
                assert session.execute(select(table)).all() == [], name
        generated = session.scalars(select(api.application.Audit).where(
            api.application.Audit.event == 'ORDER_SPOOL_LABELS_GENERATED')).all()
        assert len(generated) == 1 and generated[0].details['version'] == 2
        assert generated[0].details['after']['created_spool_count'] == 8
    before = database_state(api)
    repeated = generate(api, project, kind='Spool', location='Must retain original custody')
    assert repeated['created_count'] == repeated['created_assembly_count'] == repeated['created_spool_count'] == 0
    assert repeated['order']['version'] == 2
    assert labels(api, project, kind='Spool') == output
    assert database_state(api) == before
    assert api.post(f'{ROOT}/{project}/generate', generation_body(api, project,
        kind='Spool', expected_version=1)).status_code == 409
    assert database_state(api) == before


def test_selected_spool_generation_reuses_parent_records_and_keeps_other_gpn_unregistered(api):
    setup = scoped_setup(api)
    project, selected = setup['order']['project_id'], setup['assemblies'][1]['gpn_id']
    parent_ids = {'RETAIN-PARENT-1', 'RETAIN-PARENT-2'}
    for parent in sorted(parent_ids):
        register_assembly(api, setup, index=1, item_id=parent)
    originals = {parent: ok(api.get('/api/items/' + parent)) for parent in parent_ids}
    assert labels(api, project, gpn_id=selected)['items'] == []
    result = generate(api, project, kind='Spool', gpn_id=selected)
    assert result['created_assembly_count'] == 0 and result['created_spool_count'] == 2
    assert result['created_count'] == 2 and result['remaining_quantity'] == 0
    assert not parent_ids & set(result['created_ids'])
    for parent in parent_ids:
        assert ok(api.get('/api/items/' + parent)) == originals[parent]
        assert originals[parent]['qr_url'] is None
    assert [row['registered_quantity'] for row in overview(api, project)['groups']] == [0, 2]
    assert {row['assembly_id'] for row in labels(api, project)['items']} == parent_ids


def test_existing_planned_spools_are_reused_only_under_their_exact_physical_parent(api):
    setup = create_setup(api, assemblies=[branch(quantity=2)])
    project = setup['order']['project_id']
    register_assembly(api, setup, item_id='KEEP-PARENT')
    register_spool(api, project, 'KEEP-PARENT', item_id='KEEP-SPOOL')
    ok(api.post('/api/items', {'id': 'UNASSIGNED-SAME-NUMBER', 'kind': 'Spool', 'project': project,
        'google_part_number': '000-SP-A', 'location': 'Original bay', 'handler': BADGES['welder']}), 201)
    with api.session_factory() as session:
        item = session.get(api.application.Item, 'KEEP-SPOOL')
        original = {column.name: getattr(item, column.name) for column in item.__table__.columns}
    result = generate(api, project, kind='Spool')
    assert result['created_assembly_count'] == 1 and result['created_spool_count'] == 5
    rows = labels(api, project, kind='Spool')['items']
    assert len(rows) == 6
    assert next(row for row in rows if row['id'] == 'KEEP-SPOOL')['weld_plan_exists']
    assert all(row['id'] != 'UNASSIGNED-SAME-NUMBER' for row in rows)
    assert Counter(row['assembly_id'] for row in rows)['KEEP-PARENT'] == 3
    with api.session_factory() as session:
        item = session.get(api.application.Item, 'KEEP-SPOOL')
        assert {column.name: getattr(item, column.name) for column in item.__table__.columns} == original
        assert session.get(importlib.import_module('order_spools').OrderSpool, item.id) is None
    assert generate(api, project, kind='Spool')['created_count'] == 0


def test_registered_spool_plan_and_number_are_pinned_and_plan_does_not_duplicate_labels(api):
    setup = create_setup(api, assemblies=[branch(quantity=2)])
    project = setup['order']['project_id']
    generate(api, project, kind='Spool')
    rows = labels(api, project, kind='Spool')['items']
    chosen = rows[0]
    other_parent = next(row['assembly_id'] for row in rows if row['assembly_id'] != chosen['assembly_id'])
    other_project = create_setup(api, number='OTHER-PO')['order']['project_id']
    body = {'project_id': project, 'assembly_id': chosen['assembly_id'], 'planned_welds': 2}
    before = database_state(api)
    for parent in (None, other_parent):
        assert api.post(f'/api/tracking/spools/{chosen["id"]}/plan', {**body, 'assembly_id': parent}).status_code == 409
    assert api.post(f'/api/tracking/spools/{chosen["id"]}/plan', {**body, 'project_id': other_project}).status_code == 409
    assert api.patch(f'/api/items/{chosen["id"]}/part-number', {'google_part_number': 'OTHER-SPOOL'}).status_code == 409
    assert database_state(api) == before
    ok(api.post(f'/api/tracking/spools/{chosen["id"]}/plan', body))
    after = labels(api, project, kind='Spool')
    assert after['total'] == 6
    assert sum(row['id'] == chosen['id'] for row in after['items']) == 1
    assert next(row for row in after['items'] if row['id'] == chosen['id'])['weld_plan_exists']
    assert generate(api, project, kind='Spool')['created_count'] == 0
    assert overview(api, project, kind='Spool')['totals']['registered_quantity'] == 6


@pytest.mark.parametrize('state,allowed', [('released', False), ('past_collection', False), ('collection', True)])
def test_existing_parent_scope_is_only_filled_before_release_and_during_collection(api, state, allowed):
    setup = create_setup(api, assemblies=[branch(quantity=1,
        spools=[{'spool_number': 'ONE', 'quantity_per_assembly': 1}])])
    project = setup['order']['project_id']
    parent = 'EXISTING-PARENT'
    register_assembly(api, setup, item_id=parent)
    if state == 'released':
        from test_admin import release
        release(api, parent)
    else:
        ok(api.post(f'/api/tracking/spools/{parent}/plan', {
            'project_id': project, 'planned_welds': 0, 'zero_weld_reason': 'Synthetic bolted assembly scope'}))
        ok(api.post(f'/api/flow/items/{parent}/start', {
            'route': 'assembly', 'expected_children': 1,
            'start_step': 19 if state == 'past_collection' else 17,
            'baseline_reference': 'SYNTHETIC-BASELINE',
            'baseline_reason': 'Retained synthetic workflow baseline'}), 201)
    before = database_state(api)
    response = api.post(f'{ROOT}/{project}/generate', generation_body(api, project, kind='Spool'))
    if allowed:
        assert ok(response)['created_spool_count'] == 1
    else:
        assert response.status_code == 409
        assert database_state(api) == before
    assert all(row['kind'] == 'Spool' and row['id'] != parent for row in labels(api, project)['items'])
    assert ok(api.get('/api/items/' + parent))['qr_url'] is None


def test_per_number_overcapacity_is_validated_even_after_other_group_fills_batch(api):
    setup = create_setup(api, assemblies=[
        branch('000-GPN-A', 500, [{'spool_number': 'ONE', 'quantity_per_assembly': 1}]),
        branch('000-GPN-B', 1),
    ])
    project = setup['order']['project_id']
    register_assembly(api, setup, index=1, item_id='INVALID-PARENT')
    for index, number in enumerate(('000-SP-A', '000-SP-A', '000-SP-B')):
        register_spool(api, project, 'INVALID-PARENT', number, f'EXISTING-{index}')
    # Retained historical corruption must be rejected, never hidden by a full
    # first-group batch or repaired by creating additional physical identities.
    with api.session_factory() as session:
        session.get(api.application.Item, 'EXISTING-2').google_part_number = '000-SP-A'
        session.commit()
    before = database_state(api)
    response = api.post(f'{ROOT}/{project}/generate', generation_body(api, project, kind='Spool'))
    assert response.status_code == 409 and 'quantity' in response.text
    assert database_state(api) == before


@pytest.mark.parametrize('assemblies,quantity,first_counts,remaining,second_counts', [
    (1, 501, (1, 499), 2, (0, 2)),
    (500, 1, (250, 250), 250, (250, 250)),
])
def test_total_item_batch_limit_bounds_parent_and_spool_creation(api, assemblies, quantity,
        first_counts, remaining, second_counts):
    setup = create_setup(api, assemblies=[branch(quantity=assemblies,
        spools=[{'spool_number': 'BATCH-SPOOL', 'quantity_per_assembly': quantity}])])
    project = setup['order']['project_id']
    first = generate(api, project, kind='Spool')
    assert first['created_count'] == 500
    assert (first['created_assembly_count'], first['created_spool_count']) == first_counts
    assert first['remaining_quantity'] == remaining
    second = generate(api, project, kind='Spool')
    assert (second['created_assembly_count'], second['created_spool_count']) == second_counts
    assert second['remaining_quantity'] == 0
    assert not set(first['created_ids']) & set(second['created_ids'])
    pages = [labels(api, project, kind='Spool', offset=offset)['items']
             for offset in range(0, assemblies * quantity, 100)]
    ids = [row['id'] for page in pages for row in page]
    assert len(ids) == len(set(ids)) == assemblies * quantity
    assert generate(api, project, kind='Spool')['created_count'] == 0


def test_removed_spool_gets_new_identity_and_does_not_poison_repeated_generation(api):
    setup = create_setup(api, assemblies=[branch(quantity=1)])
    project = setup['order']['project_id']
    generate(api, project, kind='Spool')
    original = labels(api, project, kind='Spool')['items'][0]
    change(api, 'item', original['id'])
    assert overview(api, project, kind='Spool')['totals']['remaining_quantity'] == 1
    replacement = generate(api, project, kind='Spool')
    assert replacement['created_assembly_count'] == 0 and replacement['created_spool_count'] == 1
    new_id = replacement['created_ids'][0]
    assert new_id != original['id']
    rows = labels(api, project, kind='Spool')['items']
    assert all(row['id'] != original['id'] for row in rows)
    assert next(row for row in rows if row['id'] == new_id)['assembly_id'] == original['assembly_id']
    assert generate(api, project, kind='Spool')['created_count'] == 0
    preview = ok(api.get('/api/removals/item/' + original['id'], params={'action': 'restore'}))
    assert not preview['can_proceed'] and any('exceed' in message for message in preview['blockers'])


def test_spool_generation_bad_kind_auth_and_cross_kind_id_collision_are_atomic(api, monkeypatch):
    setup = create_setup(api, assemblies=[branch(quantity=1,
        spools=[{'spool_number': 'ONE', 'quantity_per_assembly': 1}])])
    project = setup['order']['project_id']
    before = database_state(api)
    for endpoint in (f'{ROOT}/{project}', f'{ROOT}/{project}/labels'):
        for kind in ('Part', 'Assembly'):
            assert api.get(endpoint, params={'kind': kind}).status_code == 422
    for kind in ('Part', 'Assembly'):
        assert api.post(f'{ROOT}/{project}/generate', generation_body(api, project, kind=kind)).status_code == 422
    assert api.post(f'{ROOT}/{project}/generate', generation_body(api, project, kind='Spool'), role='welder').status_code == 403
    module = importlib.import_module('order_labels')
    monkeypatch.setattr(module, 'new_id', lambda prefix: 'SAME-ASM-AND-SPOOL-ID')
    assert api.post(f'{ROOT}/{project}/generate', generation_body(api, project, kind='Spool')).status_code == 409
    assert database_state(api) == before


def test_late_spool_registration_failure_rolls_back_new_parents_and_all_children(api, monkeypatch):
    setup = create_setup(api, assemblies=[branch(quantity=1)])
    project = setup['order']['project_id']
    module = importlib.import_module('order_labels')
    original_audit = module.audit
    before = database_state(api)

    def fail_child_audit(s, item_id, actor, event, details):
        if details.get('kind') == 'Spool':
            raise HTTPException(409, 'Synthetic late spool registration conflict')
        return original_audit(s, item_id, actor, event, details)

    monkeypatch.setattr(module, 'audit', fail_child_audit)
    assert api.post(f'{ROOT}/{project}/generate', generation_body(api, project, kind='Spool')).status_code == 409
    assert database_state(api) == before

