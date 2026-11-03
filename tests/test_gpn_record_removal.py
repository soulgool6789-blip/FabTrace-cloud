"""Separate GPN removal retains exact assembly, spool and QA history."""
import json

import pytest
from sqlalchemy import inspect, select, text

from fixture_accounts import BADGES
from receiving_helpers import accept_arrival, receiving_detail
from test_assembly_identity import named_branch
from test_order_labels import generate, labels, public_qr_url
from test_order_setup import create_setup, detail
from test_orders import current
from test_progress import database_state
from test_removal_orders import change
from test_removals import body, preview, stable_business_state
from tracking_helpers import ok


def test_remove_canonical_gpn_hides_all_linked_assemblies_and_restores_exact_qa(api):
    from order_spools import OrderSpool
    from orders import OrderAssembly
    saved = create_setup(api, assemblies=[named_branch('ASM-A', '000-GPN-A'),
        named_branch('ASM-B', '000-GPN-A'), named_branch('ASM-C', '000-GPN-B')])
    project = saved['order']['project_id']
    canonical = next(row for row in saved['gpn_records'] if row['gpn'] == '000-GPN-A')
    definitions = canonical['assembly_definition_ids']
    generate(api, project)
    with api.session_factory() as session:
        assemblies = set(session.scalars(select(OrderAssembly.item_id).where(
            OrderAssembly.gpn_id.in_(definitions))))
        spools = set(session.scalars(select(OrderSpool.item_id).where(
            OrderSpool.assembly_id.in_(assemblies))))
    accepted_id = sorted(spools)[0]
    acceptance = accept_arrival(api, accepted_id)
    original_labels = labels(api, project)['items']
    before = stable_business_state(api)
    review = preview(api, 'gpn_record', canonical['id'])
    assert review['confirmation'] == '000-GPN-A' and 'P.O.' in review['title']
    assert review['counts'] == {'orders': 0, 'gpns': 2, 'items': 4, 'gpn_records': 1}
    assert {row['record_id'] for row in review['affected']} == {
        canonical['id'], *definitions, *assemblies, *spools}
    change(api, 'gpn_record', canonical['id'])
    hidden = detail(api, project)
    assert [row['gpn'] for row in hidden['gpn_records']] == ['000-GPN-B']
    assert [row['assembly_number'] for row in hidden['assemblies']] == ['ASM-C']
    assert current(api, project)['totals']['gpn_count'] == 1
    assert not ({row['id'] for row in labels(api, project)['items']} & spools)
    assert all(ok(api.get('/api/items/' + item_id))['removal']['removed']
               for item_id in assemblies | spools)
    assert stable_business_state(api) == before
    change(api, 'gpn_record', canonical['id'], 'restore')
    assert stable_business_state(api) == before
    assert labels(api, project)['items'] == original_labels
    restored = receiving_detail(api, accepted_id)
    assert restored['arrival']['latest'] == acceptance['arrival']['latest']
    assert restored['arrival']['basis_sha256'] == acceptance['arrival']['basis_sha256']
    assert restored['arrival']['can_proceed']


def test_independent_assembly_removal_stays_removed_across_parent_gpn_batch(api):
    saved = create_setup(api, assemblies=[named_branch('ASM-A'), named_branch('ASM-B')])
    project, canonical = saved['order']['project_id'], saved['gpn_records'][0]['id']
    first, second = saved['assemblies']
    change(api, 'gpn', first['gpn_id'])
    change(api, 'gpn_record', canonical)
    blocked = preview(api, 'gpn', first['gpn_id'], 'restore')
    assert not blocked['can_proceed'] and any('GPN record' in x for x in blocked['blockers'])
    assert detail(api, project)['gpn_records'] == []
    change(api, 'gpn_record', canonical, 'restore')
    active = detail(api, project)
    assert [row['gpn_id'] for row in active['assemblies']] == [second['gpn_id']]
    assert active['gpn_records'][0]['assembly_count'] == 1
    change(api, 'gpn', first['gpn_id'], 'restore')
    assert len(detail(api, project)['assemblies']) == 2


def test_po_batch_includes_empty_gpn_and_preserves_an_independent_removed_gpn(api):
    saved = create_setup(api, assemblies=[named_branch('ASM-A')])
    project = saved['order']['project_id']
    for name in ('EMPTY', 'INDEPENDENT'):
        saved = ok(api.post(f'/api/order-setup/{project}/gpn-records', {
            'expected_version': saved['order']['version'], 'gpn': name}), 201)
    identities = {row['gpn']: row['id'] for row in saved['gpn_records']}
    change(api, 'gpn_record', identities['INDEPENDENT'])
    change(api, 'order', project)
    historical = current(api, project)
    assert len(historical['gpn_records']) == 3
    assert all(row['removal']['removed'] for row in historical['gpn_records'])
    change(api, 'order', project, 'restore')
    assert {row['gpn'] for row in detail(api, project)['gpn_records']} == {'000-GPN-A', 'EMPTY'}
    change(api, 'gpn_record', identities['INDEPENDENT'], 'restore')
    assert len(detail(api, project)['gpn_records']) == 3


def test_removed_canonical_number_cannot_be_edited_recreated_or_assigned(api):
    saved = create_setup(api, assemblies=[named_branch('ASM-A', 'GPN-A'),
        named_branch('ASM-B', 'GPN-B')])
    project = saved['order']['project_id']
    removed = next(row for row in saved['gpn_records'] if row['gpn'] == 'GPN-A')
    other = next(row for row in saved['gpn_records'] if row['gpn'] == 'GPN-B')
    other_assembly = next(row for row in saved['assemblies'] if row['gpn'] == 'GPN-B')
    change(api, 'gpn_record', removed['id'])
    version = detail(api, project)['order']['version']
    before = database_state(api)
    root = f'/api/order-setup/{project}'
    responses = [
        api.patch(root + '/gpn-records/' + removed['id'], {
            'expected_version': version, 'gpn': 'RENAMED', 'reason': 'Removed record must remain reserved'}),
        api.post(root + '/gpn-records', {'expected_version': version, 'gpn': ' gpn-a '}),
        api.patch(root + '/gpn-records/' + other['id'], {
            'expected_version': version, 'gpn': 'GPN-A', 'reason': 'Do not merge into a removed record'}),
        api.post(root + '/assemblies', {**named_branch('ASM-NEW', 'GPN-A'), 'expected_version': version}),
        api.patch(root + '/assemblies/' + other_assembly['gpn_id'], {
            **named_branch('ASM-B', 'GPN-A'), 'expected_version': version,
            'reason': 'Do not assign an active assembly to a removed GPN'}),
    ]
    assert all(response.status_code == 409 for response in responses), [row.text for row in responses]
    assert all('restor' in response.text.lower() for response in responses)
    assert database_state(api) == before


def test_gpn_removal_preview_detects_added_assembly_and_reads_are_read_only(api):
    saved = create_setup(api, assemblies=[named_branch('ASM-A')])
    project, canonical = saved['order']['project_id'], saved['gpn_records'][0]['id']
    before = database_state(api)
    reviewed = preview(api, 'gpn_record', canonical)
    ok(api.get('/api/removals'))
    detail(api, project)
    assert database_state(api) == before
    saved = ok(api.post(f'/api/order-setup/{project}/assemblies', {
        **named_branch('ASM-B'), 'expected_version': saved['order']['version']}), 201)
    before = database_state(api)
    response = api.post(f'/api/removals/gpn_record/{canonical}/remove', body(reviewed))
    assert response.status_code == 409 and database_state(api) == before
    assert preview(api, 'gpn_record', canonical)['counts']['gpns'] == 2


@pytest.mark.parametrize('role', [None, 'supervisor', 'inspector', 'handler'])
def test_canonical_gpn_removal_remains_administrator_controlled(api, role):
    saved = create_setup(api)
    canonical = saved['gpn_records'][0]['id']
    reviewed = preview(api, 'gpn_record', canonical)
    before = database_state(api)
    expected = 401 if role is None else 403
    assert api.get(f'/api/removals/gpn_record/{canonical}', role=role).status_code == expected
    assert api.post(f'/api/removals/gpn_record/{canonical}/remove', body(reviewed), role=role).status_code == expected
    assert database_state(api) == before


def test_legacy_removal_schema_expansion_preserves_rows_indexes_and_triggers(api):
    from removal_migrations import migrate_removal_kinds
    from removals import RecordRemoval
    api.item('REMOVAL-MIGRATION-SYNTHETIC')
    change(api, 'item', 'REMOVAL-MIGRATION-SYNTHETIC')
    engine, table = api.session_factory.kw['bind'], RecordRemoval.__table__
    with engine.begin() as connection:
        rows = [dict(row) for row in connection.execute(select(table)).mappings()]
        sql = connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='record_removals'")).scalar_one()
        legacy = sql.replace("'gpn_record',", '').replace("'spool_line',", '')
        connection.exec_driver_sql('DROP TABLE record_removals')
        connection.exec_driver_sql(legacy)
        connection.execute(table.insert(), rows)
        connection.exec_driver_sql('CREATE INDEX removal_review_test_index ON record_removals(reason)')
        connection.exec_driver_sql('CREATE TRIGGER removal_review_test_trigger AFTER UPDATE ON record_removals BEGIN SELECT 1; END')
    before = json.loads(database_state(api))
    with engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        assert migrate_removal_kinds(connection)
        assert not migrate_removal_kinds(connection)
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        names = {row['name'] for row in inspect(connection).get_indexes('record_removals')}
        assert {'removal_review_test_index', 'ix_record_removals_batch_id'} <= names
        assert connection.execute(text("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name='removal_review_test_trigger'")).scalar_one() == 1
        checks = {row['name']: row['sqltext'] for row in inspect(connection).get_check_constraints('record_removals')}
        assert all('gpn_record' in checks[name] and 'spool_line' in checks[name]
                   for name in ('ck_record_removal_kind', 'ck_record_removal_root_kind'))
    assert json.loads(database_state(api)) == before
    change(api, 'item', 'REMOVAL-MIGRATION-SYNTHETIC', 'restore')
    saved = create_setup(api)
    change(api, 'gpn_record', saved['gpn_records'][0]['id'])
