"""GPN masters and assembly definitions are distinct, durable PO records."""
import json

import pytest
from sqlalchemy import delete, select

from test_assembly_identity import named_branch
from test_order_setup import create_setup, detail
from test_orders import current
from test_order_labels import generate, labels, public_qr_url
from test_progress import database_state
from receiving_helpers import accept_arrival, receiving_detail
from tracking_helpers import ok


def path(saved, record=None):
    root = f'/api/order-setup/{saved["order"]["project_id"]}/gpn-records'
    return root + ('/' + record if record else '')


def test_multiple_assemblies_share_one_distinct_gpn_record_and_reads_never_write(api):
    saved = create_setup(api, assemblies=[named_branch('643-777', '001193403'),
                                         named_branch('643-778', '001193403')])
    assert len(saved['assemblies']) == 2
    assert len(saved['gpn_records']) == 1
    record = saved['gpn_records'][0]
    assert record['gpn'] == '001193403' and record['assembly_count'] == 2
    ids = {row['gpn_id'] for row in saved['assemblies']}
    assert record['id'] not in ids
    assert set(record['assembly_definition_ids']) == ids
    assert {row['gpn_record_id'] for row in saved['assemblies']} == {record['id']}
    before = database_state(api)
    detail(api, saved['order']['project_id'])
    production = current(api, saved['order']['project_id'])
    assert production['totals']['gpn_count'] == 1
    assert len(production['gpns']) == 2  # retained assembly-setup compatibility
    assert database_state(api) == before


def test_independent_gpn_create_then_add_and_edit_assembly_preserves_siblings(api):
    saved = create_setup(api, assemblies=[named_branch('FIRST', 'GPN-A')])
    original = saved['assemblies'][0]
    saved = ok(api.post(path(saved), {'expected_version': saved['order']['version'],
        'gpn': '000-GPN-B', 'description': 'Cooling pipe design'}), 201)
    record_id = saved['saved_gpn_record_id']
    assert next(row for row in saved['gpn_records'] if row['id'] == record_id)['assembly_count'] == 0
    assert len(saved['assemblies']) == 1
    project = saved['order']['project_id']
    saved = ok(api.post(f'/api/order-setup/{project}/assemblies', {
        **named_branch('SECOND', '000-GPN-B'), 'expected_version': saved['order']['version']}), 201)
    second = next(row for row in saved['assemblies'] if row['assembly_number'] == 'SECOND')
    assert second['gpn_record_id'] == record_id
    saved = ok(api.patch(f'/api/order-setup/{project}/assemblies/{second["gpn_id"]}/identity', {
        'expected_version': saved['order']['version'], 'assembly_number': 'SECOND-REVISED',
        'reason': 'Correct the assembly designation'}))
    assert next(row for row in saved['assemblies'] if row['gpn_id'] == original['gpn_id']) == original
    assert next(row for row in saved['gpn_records'] if row['id'] == record_id)['gpn'] == '000-GPN-B'
    assert {row['gpn_id'] for row in saved['assemblies']} == {original['gpn_id'], second['gpn_id']}


def test_gpn_edit_changes_current_label_for_all_assemblies_without_changing_evidence(api):
    saved = create_setup(api, assemblies=[named_branch('ASM-A', 'OLD-GPN'),
                                         named_branch('ASM-B', 'OLD-GPN')])
    project = saved['order']['project_id']
    generate(api, project)
    spool = labels(api, project)['items'][0]
    accepted = accept_arrival(api, spool['id'])
    saved = detail(api, project)
    record_id = saved['gpn_records'][0]['id']
    before = json.loads(database_state(api))
    result = ok(api.patch(path(saved, record_id), {
        'expected_version': saved['order']['version'], 'gpn': '001193403',
        'description': 'Correct supplier GPN', 'reason': 'Confirmed the separate Google part number'}))
    assert result['order']['version'] == saved['order']['version'] + 1
    assert result['saved_gpn_record_id'] == record_id
    assert {row['gpn_label'] for row in result['assemblies']} == {'001193403'}
    assert {row['gpn'] for row in result['assemblies']} == {'OLD-GPN'}
    assert {row['assembly_number'] for row in result['assemblies']} == {'ASM-A', 'ASM-B'}
    after = json.loads(database_state(api))
    allowed = {'order_gpns', 'order_google_part_numbers', 'purchase_orders', 'audit_events'}
    for table in set(before) - allowed:
        assert before[table] == after[table], table
    checked = receiving_detail(api, spool['id'])
    assert checked['arrival']['basis_sha256'] == accepted['arrival']['basis_sha256']
    assert checked['arrival']['latest'] == accepted['arrival']['latest']
    assert checked['arrival']['can_proceed']
    assert after['audit_events'][-1]['event'] == 'ORDER_GPN_RECORD_UPDATED'


def test_adding_assembly_to_current_po_keeps_registered_spools_and_qa(api):
    saved = create_setup(api, assemblies=[named_branch('EXISTING', 'GPN-SHARED')])
    project = saved['order']['project_id']
    generate(api, project)
    spool = labels(api, project)['items'][0]
    accepted = accept_arrival(api, spool['id'])
    saved = detail(api, project)
    original = saved['assemblies'][0]
    before = json.loads(database_state(api))
    added = ok(api.post(f'/api/order-setup/{project}/assemblies', {
        **named_branch('ADDITIONAL', 'GPN-SHARED', quantity=2),
        'expected_version': saved['order']['version']}), 201)
    assert len(added['assemblies']) == 2 and len(added['gpn_records']) == 1
    assert next(row for row in added['assemblies'] if row['gpn_id'] == original['gpn_id']) == original
    new = next(row for row in added['assemblies'] if row['assembly_number'] == 'ADDITIONAL')
    assert new['gpn_record_id'] == original['gpn_record_id']
    assert new['assembly_quantity'] == 2 and new['registered_assemblies'] == 0
    after = json.loads(database_state(api))
    for table in ('items', 'order_assemblies', 'order_spools', 'spool_qr_identities',
                  'flow_events', 'spool_arrival_inspections', 'spool_material_inspections'):
        assert after.get(table) == before.get(table), table
    retained = labels(api, project)['items']
    assert len(retained) == 1
    for key in ('id', 'qr_alias', 'assembly_id', 'spool_number'):
        assert retained[0][key] == spool[key]
    assert receiving_detail(api, spool['id'])['arrival']['latest'] == accepted['arrival']['latest']


def test_migration_adds_only_missing_links_and_is_idempotent(api):
    from orders import AssemblyGpnLink, GooglePartNumber, backfill_gpn_records
    saved = create_setup(api, assemblies=[named_branch('A', 'GPN-SHARED'),
                                         named_branch('B', 'GPN-SHARED'),
                                         named_branch('C', 'GPN-OTHER')])
    with api.session_factory() as session:
        session.execute(delete(AssemblyGpnLink))
        session.execute(delete(GooglePartNumber))
        session.commit()
    before = json.loads(database_state(api))
    with api.session_factory() as session:
        assert backfill_gpn_records(session) == 3
        session.commit()
        assert len(session.scalars(select(GooglePartNumber)).all()) == 2
        assert len(session.scalars(select(AssemblyGpnLink)).all()) == 3
    after = json.loads(database_state(api))
    for table in set(before) - {'order_google_part_numbers', 'order_assembly_gpn_links'}:
        assert before[table] == after[table], table
    snapshot = database_state(api)
    with api.session_factory() as session:
        assert backfill_gpn_records(session) == 0
        session.commit()
    assert database_state(api) == snapshot
    restored = detail(api, saved['order']['project_id'])
    assert {r['gpn_id'] for r in restored['assemblies']} == {r['gpn_id'] for r in saved['assemblies']}


@pytest.mark.parametrize('role', [None, 'inspector', 'welder'])
def test_gpn_record_writes_require_manager_authority(api, role):
    saved = create_setup(api)
    record_id = saved['gpn_records'][0]['id']
    before = database_state(api)
    for response in (
        api.post(path(saved), {'expected_version': 1, 'gpn': 'UNAUTHORIZED'}, role=role),
        api.patch(path(saved, record_id), {'expected_version': 1, 'gpn': 'UNAUTHORIZED',
            'reason': 'This update must be rejected'}, role=role),
    ):
        assert response.status_code == (401 if role is None else 403)
    assert database_state(api) == before


def test_gpn_edits_reject_cross_order_duplicate_and_stale_requests_atomically(api):
    saved = create_setup(api, assemblies=[named_branch('A', 'GPN-A'), named_branch('B', 'GPN-B')])
    other = create_setup(api, number='OTHER-PO')
    first, second = saved['gpn_records']
    before = database_state(api)
    assert api.patch(path(saved, other['gpn_records'][0]['id']), {
        'expected_version': 1, 'gpn': 'MOVED', 'reason': 'Invalid cross-order ID'}).status_code == 404
    assert api.patch(path(saved, first['id']), {
        'expected_version': 1, 'gpn': second['gpn'], 'reason': 'Do not silently merge these records'}).status_code == 409
    assert api.post(path(saved), {'expected_version': 1, 'gpn': ' gpn-a '}).status_code == 409
    assert database_state(api) == before
    changed = ok(api.patch(path(saved, first['id']), {
        'expected_version': 1, 'gpn': 'GPN-A-NEW', 'reason': 'Verified current identifier'}))
    snapshot = database_state(api)
    assert api.patch(path(saved, first['id']), {
        'expected_version': 1, 'gpn': 'STALE', 'reason': 'Outdated form must be rejected'}).status_code == 409
    assert database_state(api) == snapshot
    assert changed['order']['version'] == 2
