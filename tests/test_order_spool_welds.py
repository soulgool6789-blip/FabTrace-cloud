"""Declared PO weld counts create distinct pending weld scope per physical spool."""
import importlib

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import ok
from test_order_setup import branch, create_setup, detail, edit_body
from test_order_labels import generate, labels, overview, public_qr_url
from test_progress import database_state


def declared_setup(api, quantity=1, spools=None):
    return create_setup(api, assemblies=[branch(quantity=quantity, spools=spools or [
        {'spool_number': 'SPOOL-A', 'quantity_per_assembly': 3, 'welds_per_spool': 2}])])


def declare(api, setup, count):
    project, group = setup['order']['project_id'], setup['assemblies'][0]['gpn_id']
    current = detail(api, project)
    body = edit_body(current)
    body['spools'] = [{**line, 'welds_per_spool': count} for line in body['spools']]
    return api.patch(f'/api/order-setup/{project}/assemblies/{group}', body)


def test_eighteen_spools_get_eighteen_qrs_and_their_own_numbered_pending_welds(api):
    setup = declared_setup(api, spools=[
        {'spool_number': 'SPOOL-A', 'quantity_per_assembly': 12, 'welds_per_spool': 2},
        {'spool_number': 'SPOOL-B', 'quantity_per_assembly': 6, 'welds_per_spool': 4}])
    project = setup['order']['project_id']
    assert [row['welds_per_spool'] for row in setup['assemblies'][0]['spools']] == [2, 4]
    assert labels(api, project)['items'] == []
    result = generate(api, project)
    assert result['created_assembly_count'] == 1
    assert result['created_spool_count'] == 18
    assert result['created_weld_count'] == 48
    printed = labels(api, project)
    assert printed['kind'] == 'Spool' and printed['total'] == 18
    assert len({row['qr_url'] for row in printed['items']}) == 18
    tracking = importlib.import_module('tracking')
    with api.session_factory() as s:
        all_weld_ids = set()
        for row in printed['items']:
            expected = 2 if row['spool_number'] == 'SPOOL-A' else 4
            item = s.get(api.application.Item, row['id'])
            plan = s.get(tracking.SpoolPlan, item.id)
            assert plan.planned_welds == row['planned_welds'] == row['welds_per_spool'] == expected
            assert plan.assembly_id == row['assembly_id']
            welds = s.scalars(select(tracking.Weld).where(tracking.Weld.item_id == item.id)
                             .order_by(tracking.Weld.number)).all()
            assert [w.number for w in welds] == [f'W{i:02d}' for i in range(1, expected + 1)]
            assert all(w.id not in all_weld_ids for w in welds)
            all_weld_ids.update(w.id for w in welds)
            for weld in welds:
                assert weld.completed_at is None and weld.completed_by is None
                assert weld.required_operations == ['root', 'fill_cap']
                requirements = s.scalars(select(tracking.WeldRequirement)
                    .where(tracking.WeldRequirement.weld_id == weld.id)).all()
                assert {r.code for r in requirements} == {'MATERIALS', 'PROCEDURE', 'FIT_UP', 'VT', 'NDE_PLAN', 'FINAL_QA'}
                assert all(r.status == 'pending' for r in requirements)
            assert item.welds_required == expected and item.welds_done == 0
            assert item.last_work_at is None and not item.released
            assert item.dimensional == item.weld == 'Not started'
        assert len(all_weld_ids) == 48
        for name in ('tracking_weld_work', 'tracking_requirement_reviews', 'flow_plans',
                     'flow_events', 'tracking_process_events', 'inspections'):
            assert s.execute(select(api.application.Base.metadata.tables[name])).all() == []
    before = database_state(api)
    repeated = generate(api, project)
    assert repeated['created_count'] == repeated['created_weld_count'] == 0
    assert database_state(api) == before
    assert labels(api, project) == printed
    spool_id = printed['items'][0]['id']
    rejected = api.post(f'/api/items/{spool_id}/inspect', {
        'kind': 'Weld', 'result': 'Pass', 'report': 'Synthetic report',
        'measurements': 'Cannot accept individual welds in an aggregate inspection'}, role='inspector')
    assert rejected.status_code == 409
    assert database_state(api) == before


def test_identical_spool_numbers_in_different_assemblies_have_separate_records(api):
    setup = declared_setup(api, quantity=2)
    project = setup['order']['project_id']
    generate(api, project)
    rows = labels(api, project)['items']
    assert len(rows) == 6 and len({r['assembly_id'] for r in rows}) == 2
    tracking = importlib.import_module('tracking')
    with api.session_factory() as s:
        assert len(s.scalars(select(tracking.Weld)).all()) == 12
        assert len({w.id for w in s.scalars(select(tracking.Weld))}) == 12


@pytest.mark.parametrize('count', [-1, 501, 2.5, True, '3'])
def test_invalid_weld_counts_are_rejected_without_partial_setup(api, count):
    before = database_state(api)
    response = api.post('/api/order-setup', {'purchase_order': 'COUNT-CHECK', 'assemblies': [
        branch(quantity=1, spools=[{'spool_number': 'S', 'quantity_per_assembly': 1,
                                  'welds_per_spool': count}])]})
    assert response.status_code == 422
    assert database_state(api) == before


def test_explicit_zero_is_distinct_from_undeclared_and_does_not_invent_welds(api):
    setup = declared_setup(api, spools=[
        {'spool_number': 'BOLTED', 'quantity_per_assembly': 1, 'welds_per_spool': 0},
        {'spool_number': 'LEGACY', 'quantity_per_assembly': 1}])
    project = setup['order']['project_id']
    generate(api, project)
    rows = {row['spool_number']: row for row in labels(api, project)['items']}
    assert rows['BOLTED']['weld_plan_exists'] and rows['BOLTED']['planned_welds'] == 0
    assert not rows['LEGACY']['weld_plan_exists'] and rows['LEGACY']['welds_per_spool'] is None
    tracking = importlib.import_module('tracking')
    with api.session_factory() as s:
        plan = s.get(tracking.SpoolPlan, rows['BOLTED']['id'])
        assert 'explicitly declared' in plan.zero_weld_reason
        assert s.scalars(select(tracking.Weld)).all() == []
    assert overview(api, project)['totals']['undeclared_weld_spools'] == 1


def test_existing_legacy_spools_receive_declared_welds_without_changing_qrs(api):
    setup = create_setup(api, assemblies=[branch(quantity=1)])
    project = setup['order']['project_id']
    generate(api, project)
    original = labels(api, project)['items']
    assert detail(api, project)['assemblies'][0]['welds_editable']
    saved = ok(declare(api, setup, 3))
    assert saved['initialized_weld_spool_count'] == 3 and saved['created_weld_count'] == 9
    assert not saved['assemblies'][0]['editable'] and not saved['assemblies'][0]['welds_editable']
    current = labels(api, project)['items']
    assert {row['id']: row['qr_url'] for row in current} == {row['id']: row['qr_url'] for row in original}
    assert all(row['planned_welds'] == 3 for row in current)
    before = database_state(api)
    assert declare(api, setup, 4).status_code == 409
    assert database_state(api) == before


def test_conflicting_existing_plan_blocks_declaration_without_overwriting_work(api):
    setup = create_setup(api, assemblies=[branch(quantity=1)])
    project = setup['order']['project_id']
    generate(api, project)
    row = labels(api, project)['items'][0]
    ok(api.post(f'/api/tracking/spools/{row["id"]}/plan', {
        'project_id': project, 'assembly_id': row['assembly_id'], 'planned_welds': 2}))
    ok(api.post(f'/api/tracking/spools/{row["id"]}/welds', {'number': 'CUSTOM-07'}), 201)
    before = database_state(api)
    response = declare(api, setup, 3)
    assert response.status_code == 409 and 'different weld plan' in response.text
    assert database_state(api) == before


def test_matching_existing_plan_and_custom_weld_identity_are_preserved(api):
    setup = create_setup(api, assemblies=[branch(quantity=1)])
    project = setup['order']['project_id']
    generate(api, project)
    row = labels(api, project)['items'][0]
    ok(api.post(f'/api/tracking/spools/{row["id"]}/plan', {
        'project_id': project, 'assembly_id': row['assembly_id'], 'planned_welds': 2}))
    weld = ok(api.post(f'/api/tracking/spools/{row["id"]}/welds', {'number': 'CUSTOM-07'}), 201)
    ok(declare(api, setup, 2))
    retained = ok(api.get(f'/api/tracking/spools/{row["id"]}'))
    assert [w['id'] for w in retained['welds']] == [weld['id']]
    assert retained['welds'][0]['number'] == 'CUSTOM-07'
    before = database_state(api)
    response = api.post(f'/api/tracking/spools/{row["id"]}/plan', {
        'expected_version': retained['plan']['version'], 'project_id': project,
        'assembly_id': row['assembly_id'], 'planned_welds': 3})
    assert response.status_code == 409 and 'declared count' in response.text
    assert database_state(api) == before


def test_physical_group_weld_declaration_cannot_change_locked_quantity_scope(api):
    setup = create_setup(api, assemblies=[branch(quantity=1)])
    project, group = setup['order']['project_id'], setup['assemblies'][0]['gpn_id']
    generate(api, project)
    body = edit_body(detail(api, project), assembly_quantity=2)
    body['spools'][0]['welds_per_spool'] = 3
    before = database_state(api)
    assert api.patch(f'/api/order-setup/{project}/assemblies/{group}', body).status_code == 409
    assert database_state(api) == before


def test_weld_generation_limit_is_resumable_without_duplicate_ids(api, monkeypatch):
    module = importlib.import_module('order_labels')
    monkeypatch.setattr(module, 'WELD_GENERATION_LIMIT', 5)
    setup = declared_setup(api, spools=[
        {'spool_number': 'SPOOL', 'quantity_per_assembly': 3, 'welds_per_spool': 3}])
    project = setup['order']['project_id']
    first = generate(api, project)
    assert first['created_assembly_count'] == first['created_spool_count'] == 1
    assert first['created_weld_count'] == 3 and first['remaining_quantity'] == 2
    second = generate(api, project)
    third = generate(api, project)
    assert second['created_assembly_count'] == third['created_assembly_count'] == 0
    assert second['created_weld_count'] == third['created_weld_count'] == 3
    assert third['remaining_quantity'] == 0
    assert len({row['id'] for row in labels(api, project)['items']}) == 3
    assert generate(api, project)['created_weld_count'] == 0


def test_legacy_declaration_backfill_is_bounded_and_generation_finishes_it(api, monkeypatch):
    spools = importlib.import_module('order_spools')
    label_module = importlib.import_module('order_labels')
    monkeypatch.setattr(spools, 'WELD_GENERATION_LIMIT', 5)
    monkeypatch.setattr(label_module, 'WELD_GENERATION_LIMIT', 5)
    setup = create_setup(api, assemblies=[branch(quantity=1)])
    project = setup['order']['project_id']
    generate(api, project)
    original_ids = {row['id'] for row in labels(api, project)['items']}
    declared = ok(declare(api, setup, 3))
    assert declared['created_weld_count'] == 3 and declared['remaining_weld_spools'] == 2
    first = generate(api, project)
    second = generate(api, project)
    assert first['created_count'] == second['created_count'] == 0
    assert first['initialized_weld_spool_count'] == second['initialized_weld_spool_count'] == 1
    assert second['remaining_weld_spools'] == second['remaining_quantity'] == 0
    assert {row['id'] for row in labels(api, project)['items']} == original_ids


def test_late_weld_requirement_failure_rolls_back_parent_spools_welds_and_order_version(api, monkeypatch):
    setup = declared_setup(api)
    project = setup['order']['project_id']
    tracking = importlib.import_module('tracking')
    actual = tracking._add_requirement
    calls = []
    def fail_after_one_requirement(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise HTTPException(409, 'Synthetic late weld requirement failure')
        return actual(*args, **kwargs)
    monkeypatch.setattr(tracking, '_add_requirement', fail_after_one_requirement)
    before = database_state(api)
    response = api.post(f'/api/order-labels/{project}/generate', {
        'expected_version': setup['order']['version'], 'location': 'Test bay',
        'handler': BADGES['handler']})
    assert response.status_code == 409
    assert database_state(api) == before


def test_assembly_qr_api_kind_is_rejected_without_creating_records(api):
    setup = declared_setup(api)
    project = setup['order']['project_id']
    before = database_state(api)
    for endpoint in (f'/api/order-labels/{project}', f'/api/order-labels/{project}/labels'):
        assert api.get(endpoint, params={'kind': 'Assembly'}).status_code == 422
    response = api.post(f'/api/order-labels/{project}/generate', {
        'expected_version': 1, 'kind': 'Assembly', 'location': 'Test bay',
        'handler': BADGES['handler']})
    assert response.status_code == 422
    assert database_state(api) == before


def test_initializer_adds_weld_requirement_table_without_rewriting_legacy_records(api, monkeypatch):
    from sqlalchemy import inspect, text
    setup = create_setup(api, assemblies=[branch(quantity=1)])
    project = setup['order']['project_id']
    generate(api, project)
    before = database_state(api)
    engine = api.session_factory.kw['bind']
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE order_spool_weld_requirements'))
    assert 'order_spool_weld_requirements' not in inspect(engine).get_table_names()
    initializer = importlib.import_module('init_db')
    monkeypatch.setattr(initializer, 'engine', engine)
    initializer.initialize()
    initializer.initialize()
    assert 'order_spool_weld_requirements' in inspect(engine).get_table_names()
    assert database_state(api) == before
    current = detail(api, project)
    assert all(line['welds_per_spool'] is None for line in current['assemblies'][0]['spools'])
    assert all(not row['weld_plan_exists'] for row in labels(api, project)['items'])
