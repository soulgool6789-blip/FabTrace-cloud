"""Simple P.O. quantities remain separate from physical production records."""
import importlib

import pytest
from sqlalchemy import event, select

from conftest import BADGES
from tracking_helpers import ok
from test_orders import (add_assembly, assembly_body, current as physical_order,
                         group, new_order, plan, version)
from test_progress import database_state


ROOT = '/api/order-setup'


def branch(gpn='000-GPN-A', quantity=3, spools=None):
    return {'gpn': gpn, 'assembly_quantity': quantity,
            'spools': spools if spools is not None else [
                {'spool_number': '000-SP-A', 'quantity_per_assembly': 2},
                {'spool_number': '000-SP-B', 'quantity_per_assembly': 1}]}


def setup_body(number='000123', **values):
    return {'expected_version': 0, 'purchase_order': number,
            'assemblies': [branch()], **values}


def create_setup(api, **values):
    return ok(api.post(ROOT, setup_body(**values)), 201)


def detail(api, project_id):
    return ok(api.get(f'{ROOT}/{project_id}'))


def edit_body(result, *, index=0, **values):
    row = result['assemblies'][index]
    return {'expected_version': result['order']['version'], 'gpn': row['gpn'],
            'assembly_quantity': row['assembly_quantity'],
            'spools': [{key: line[key] for key in ('spool_number', 'quantity_per_assembly')}
                       for line in row['spools']],
            'reason': 'Correct the approved synthetic initial quantity requirement', **values}


def rejected(api, response, before, code=422):
    assert response.status_code == code, response.text
    assert database_state(api) == before


def test_setup_is_one_atomic_po_with_multiple_assembly_and_spool_quantities(api):
    result = create_setup(api, assemblies=[branch(), branch('000-GPN-B', 2, [
        {'spool_number': '000-SP-A', 'quantity_per_assembly': 4}])])
    assert result['order']['purchase_order'] == '000123'
    assert result['order']['customer'] == '' and result['order']['version'] == 1
    assert result['totals'] == {'assembly_types': 2, 'assembly_quantity': 5,
        'total_spools': 17, 'undeclared_groups': 0,
        'known_assembly_quantity': 5, 'known_total_spools': 17}
    first, second = result['assemblies']
    assert first['assembly_quantity'] == 3 and first['spools_per_assembly'] == 3
    assert [line['total_quantity'] for line in first['spools']] == [6, 3]
    assert second['assembly_quantity'] == 2 and second['total_spools'] == 8
    assert first['editable'] and first['planned'] and not first['legacy_scope']
    assert first['registered_assemblies'] == 0
    with api.session_factory() as s:
        for name in ('items', 'tracking_spool_plans', 'flow_plans', 'order_assemblies',
                     'flow_events', 'tracking_welds', 'tracking_process_events', 'inspections'):
            assert s.execute(select(api.application.Base.metadata.tables[name])).all() == []
        project = s.get(importlib.import_module('tracking').Project, result['order']['project_id'])
        assert project.name == 'PO 000123' and project.client == ''
        events = s.scalars(select(api.application.Audit)).all()
        assert len(events) == 1 and events[0].event == 'ORDER_SETUP_CREATED'
        assert len(events[0].details['after']['assemblies']) == 2
    listed = ok(api.get(ROOT))['orders'][0]
    assert listed['assembly_quantity'] == 5 and listed['total_spools'] == 17


@pytest.mark.parametrize('role', [None, 'handler', 'welder', 'fitup_welder', 'process_welder',
                                  'inspector', 'painter', 'finisher', 'misc'])
def test_write_permissions_reject_all_setup_mutations_without_partial_records(api, role):
    result = create_setup(api)
    project_id, gpn_id = result['order']['project_id'], result['assemblies'][0]['gpn_id']
    before = database_state(api)
    responses = [api.post(ROOT, setup_body('SECOND'), role=role),
        api.post(f'{ROOT}/{project_id}/assemblies', {**branch('SECOND'), 'expected_version': 1}, role=role),
        api.patch(f'{ROOT}/{project_id}/assemblies/{gpn_id}', edit_body(result), role=role)]
    assert {r.status_code for r in responses} == {401 if role is None else 403}
    assert database_state(api) == before


def test_supervisor_can_create_and_add_and_corrections_increment_one_order_version(api):
    result = ok(api.post(ROOT, setup_body(), role='supervisor'), 201)
    project_id = result['order']['project_id']
    result = ok(api.post(f'{ROOT}/{project_id}/assemblies', {
        **branch('SECOND', 2), 'expected_version': 1}, role='supervisor'), 201)
    assert result['order']['version'] == 2 and result['totals']['assembly_quantity'] == 5
    gpn_id = result['assemblies'][0]['gpn_id']
    result = ok(api.patch(f'{ROOT}/{project_id}/assemblies/{gpn_id}',
        edit_body(result, assembly_quantity=4), role='supervisor'))
    assert result['order']['version'] == 3 and result['totals']['assembly_quantity'] == 6
    events = physical_order(api, project_id)['events']
    assert [row['event'] for row in events] == [
        'ORDER_SETUP_ASSEMBLY_UPDATED', 'ORDER_SETUP_ASSEMBLY_ADDED', 'ORDER_SETUP_CREATED']
    assert events[0]['details']['before']['requirements']['assembly_quantity'] == 3
    assert events[0]['details']['after']['requirements']['assembly_quantity'] == 4


@pytest.mark.parametrize('bad', [0, -1, 10001, 1.5, True, '3', None])
def test_quantities_are_positive_whole_numbers_on_both_levels(api, bad):
    before = database_state(api)
    body = setup_body()
    body['assemblies'][0]['assembly_quantity'] = bad
    rejected(api, api.post(ROOT, body), before)
    body = setup_body()
    body['assemblies'][0]['spools'][0]['quantity_per_assembly'] = bad
    rejected(api, api.post(ROOT, body), before)


def test_empty_lists_excessive_scope_null_text_and_extra_fields_are_rejected(api):
    before = database_state(api)
    invalid = [setup_body(assemblies=[]), setup_body(assemblies=[branch(spools=[])]),
        setup_body(assemblies=[branch('N'+str(i)) for i in range(101)]),
        setup_body(assemblies=[branch(spools=[{'spool_number': str(i), 'quantity_per_assembly': 1}
                                             for i in range(201)])]),
        setup_body(assemblies=[branch(spools=[{'spool_number': 'A', 'quantity_per_assembly': 5001},
                                              {'spool_number': 'B', 'quantity_per_assembly': 5000}])]),
        setup_body(number='x'), setup_body(number='PO\x00NULL'),
        setup_body(assemblies=[branch('GPN\x00NULL')]),
        setup_body(assemblies=[branch(spools=[{'spool_number': 'S\x00NULL', 'quantity_per_assembly': 1}])]),
        {**setup_body(), 'create_physical_items': True}]
    for body in invalid:
        rejected(api, api.post(ROOT, body), before)


def test_normalized_duplicates_and_leading_zero_identifiers_are_preserved(api):
    before = database_state(api)
    for body in [setup_body(assemblies=[branch(' A  B '), branch('a b')]),
                 setup_body(assemblies=[branch(spools=[
                     {'spool_number': ' s  01 ', 'quantity_per_assembly': 1},
                     {'spool_number': 'S 01', 'quantity_per_assembly': 2}])])]:
        rejected(api, api.post(ROOT, body), before)
    result = create_setup(api, number=' 0000123 ', assemblies=[branch(' 0000456 ', 10000, [
        {'spool_number': ' 0000789 ', 'quantity_per_assembly': 10000}])])
    assert result['order']['purchase_order'] == '0000123'
    row = result['assemblies'][0]
    assert row['gpn'] == '0000456' and row['spools'][0]['spool_number'] == '0000789'
    assert row['total_spools'] == 100_000_000
    before = database_state(api)
    rejected(api, api.post(ROOT, setup_body('0000123')), before, 409)
    rejected(api, api.post(f'{ROOT}/{result["order"]["project_id"]}/assemblies', {
        **branch('0000456'), 'expected_version': 1}), before, 409)


def test_database_failure_rolls_back_po_project_and_partial_requirements(api, monkeypatch):
    module = importlib.import_module('order_setup')
    real_id = module.new_id
    monkeypatch.setattr(module, 'new_id', lambda prefix: 'CONFLICTING-SPOOL-ID' if prefix == 'OSPOOL' else real_id(prefix))
    before = database_state(api)
    rejected(api, api.post(ROOT, setup_body()), before, 409)


def test_simple_create_does_not_duplicate_an_existing_customer_specific_or_removed_po(api):
    from test_removals import change
    project_id = new_order(api, number='000123', customer='Existing named customer')['order']['project_id']
    before = database_state(api)
    rejected(api, api.post(ROOT, setup_body()), before, 409)
    change(api, 'order', project_id)
    before = database_state(api)
    response = api.post(ROOT, setup_body())
    rejected(api, response, before, 409)
    assert 'Removed records' in response.text


def test_stale_version_and_foreign_group_are_rejected_without_changing_setup(api):
    first, second = create_setup(api), create_setup(api, number='SECOND')
    project_id, gpn_id = first['order']['project_id'], first['assemblies'][0]['gpn_id']
    ok(api.post(f'{ROOT}/{project_id}/assemblies', {**branch('NEW'), 'expected_version': 1}), 201)
    before = database_state(api)
    rejected(api, api.patch(f'{ROOT}/{project_id}/assemblies/{gpn_id}', edit_body(first)), before, 409)
    rejected(api, api.post(f'{ROOT}/{project_id}/assemblies', {**branch('ANOTHER'), 'expected_version': 1}), before, 409)
    rejected(api, api.patch(f'{ROOT}/{project_id}/assemblies/{second["assemblies"][0]["gpn_id"]}',
        edit_body(first, expected_version=2)), before, 422)


def test_correction_retains_removed_spool_lines_and_reactivation_reuses_identity(api):
    result = create_setup(api)
    project_id, row = result['order']['project_id'], result['assemblies'][0]
    gpn_id, original = row['gpn_id'], {line['spool_number']: line['id'] for line in row['spools']}
    path = f'{ROOT}/{project_id}/assemblies/{gpn_id}'
    result = ok(api.patch(path, edit_body(result, gpn='CORRECTED', spools=[
        {'spool_number': '000-SP-A', 'quantity_per_assembly': 4}])))
    assert result['assemblies'][0]['spools_per_assembly'] == 4
    module = importlib.import_module('order_setup')
    with api.session_factory() as s:
        inactive = s.get(module.OrderSpoolRequirement, original['000-SP-B'])
        assert not inactive.active and inactive.quantity_per_assembly == 1
    result = ok(api.patch(path, edit_body(result, spools=branch()['spools'])))
    assert {line['spool_number']: line['id'] for line in result['assemblies'][0]['spools']} == original
    assert result['assemblies'][0]['gpn_id'] == gpn_id


def test_legacy_quantities_remain_undeclared_and_only_empty_groups_can_finish_setup(api):
    project_id = new_order(api)['order']['project_id']
    empty_id = group(api, project_id, 'EMPTY')
    physical_id = group(api, project_id, 'PHYSICAL')
    add_assembly(api, project_id, physical_id)
    result = detail(api, project_id)
    assert result['totals']['assembly_quantity'] is None and result['totals']['total_spools'] is None
    assert result['totals']['undeclared_groups'] == 2
    empty, physical = result['assemblies']
    assert empty['editable'] and not empty['planned']
    assert not physical['editable'] and physical['registered_assemblies'] == 1
    before = database_state(api)
    rejected(api, api.patch(f'{ROOT}/{project_id}/assemblies/{physical_id}', {
        **branch('PHYSICAL'), 'expected_version': result['order']['version'], 'reason': 'Review initial scope'}), before, 409)
    result = ok(api.patch(f'{ROOT}/{project_id}/assemblies/{empty_id}', {
        **branch('EMPTY'), 'expected_version': result['order']['version'], 'reason': 'Declare actual initial scope'}))
    assert result['assemblies'][0]['gpn_id'] == empty_id
    assert result['assemblies'][0]['assembly_quantity'] == 3
    assert result['totals']['assembly_quantity'] is None
    assert result['totals']['known_assembly_quantity'] == 3 and result['totals']['known_total_spools'] == 9
    assert result['totals']['undeclared_groups'] == 1


def test_planned_branch_locks_after_physical_registration_and_capacity_is_enforced(api):
    result = create_setup(api, assemblies=[branch(quantity=2)])
    project_id, gpn_id = result['order']['project_id'], result['assemblies'][0]['gpn_id']
    for index in range(2):
        body = assembly_body(api, project_id, gpn_id, item_id='SETUP-PHYSICAL-'+str(index), count=3,
                             assembly_part_number='000-GPN-A')
        body['create_item']['google_part_number'] = '000-GPN-A'
        ok(api.post('/api/orders/'+project_id+'/assemblies', body), 201)
    result = detail(api, project_id)
    assert not result['assemblies'][0]['editable'] and result['assemblies'][0]['registered_assemblies'] == 2
    before = database_state(api)
    rejected(api, api.patch(f'{ROOT}/{project_id}/assemblies/{gpn_id}', edit_body(result, assembly_quantity=3)), before, 409)
    body = assembly_body(api, project_id, gpn_id, item_id='OVER-CAPACITY', count=3,
                         assembly_part_number='000-GPN-A')
    body['create_item']['google_part_number'] = '000-GPN-A'
    rejected(api, api.post('/api/orders/'+project_id+'/assemblies', body), before, 409)


def _physical_assembly(api, result, item_id='PLANNED-ASSEMBLY'):
    project_id, row = result['order']['project_id'], result['assemblies'][0]
    body = assembly_body(api, project_id, row['gpn_id'], item_id=item_id,
                         count=row['spools_per_assembly'], assembly_part_number=row['gpn'])
    body['create_item']['google_part_number'] = row['gpn']
    ok(api.post('/api/orders/'+project_id+'/assemblies', body), 201)
    return item_id


def _spool(api, project_id, item_id, number):
    return ok(api.post('/api/items', {'id': item_id, 'kind': 'Spool',
        'project': project_id, 'google_part_number': number, 'location': 'Receiving',
        'handler': BADGES['handler'], 'welds_required': 0}), 201)['id']


def test_physical_count_and_assembly_number_cannot_override_saved_quantity_setup(api):
    result = create_setup(api)
    project_id, row = result['order']['project_id'], result['assemblies'][0]
    before = database_state(api)
    body = assembly_body(api, project_id, row['gpn_id'], count=2, assembly_part_number=row['gpn'])
    rejected(api, api.post('/api/orders/'+project_id+'/assemblies', body), before, 409)
    body['required_spools'] = 3
    body['assembly_part_number'] = 'WRONG-ASSEMBLY'
    rejected(api, api.post('/api/orders/'+project_id+'/assemblies', body), before, 409)
    body['assembly_part_number'] = row['gpn']
    rejected(api, api.post('/api/orders/'+project_id+'/assemblies', body), before, 409)
    body['create_item']['google_part_number'] = row['gpn']
    ok(api.post('/api/orders/'+project_id+'/assemblies', body), 201)
    before = database_state(api)
    rejected(api, api.patch('/api/orders/'+project_id+'/assemblies/ORDER-ASM-01', {
        'expected_version': version(api, project_id), 'assembly_part_number': row['gpn'],
        'required_spools': 2, 'reason': 'Attempt bypass of declared initial spool quantities'}), before, 409)
    rejected(api, api.patch('/api/items/ORDER-ASM-01/part-number', {
        'google_part_number': 'WRONG-ASSEMBLY'}), before, 409)
    rejected(api, api.patch('/api/orders/'+project_id+'/gpns/'+row['gpn_id'], {
        'expected_version': version(api, project_id), 'gpn': 'BYPASS',
        'reason': 'Attempt old endpoint number correction'}), before, 409)


def test_adopting_physical_assembly_requires_its_number_to_match_the_saved_assembly_type(api):
    result = create_setup(api)
    project_id, row = result['order']['project_id'], result['assemblies'][0]
    ok(api.post('/api/items', {'id': 'WRONG-NUMBER-ASSEMBLY', 'kind': 'Assembly',
        'project': project_id, 'google_part_number': 'OTHER-GPN', 'location': 'Receiving',
        'handler': BADGES['handler'], 'welds_required': 0}), 201)
    body = assembly_body(api, project_id, row['gpn_id'], item_id='WRONG-NUMBER-ASSEMBLY',
                         create=False, count=3, assembly_part_number=row['gpn'])
    before = database_state(api)
    rejected(api, api.post('/api/orders/'+project_id+'/assemblies', body), before, 409)


def test_combined_endpoint_registers_multiple_physical_assemblies_only_to_planned_capacity(api):
    result = create_setup(api, assemblies=[branch(quantity=2)])
    project_id, row = result['order']['project_id'], result['assemblies'][0]
    for index in range(2):
        response = ok(api.post('/api/orders/'+project_id+'/gpn-assemblies', {
            'expected_version': version(api, project_id), 'gpn_id': row['gpn_id'], 'gpn': row['gpn'],
            'required_spools': 3, 'create_item': {'location': 'Receiving', 'handler': BADGES['handler']}}), 201)
        assert response['selected_gpn_id'] == row['gpn_id']
    before = database_state(api)
    rejected(api, api.post('/api/orders/'+project_id+'/gpn-assemblies', {
        'expected_version': version(api, project_id), 'gpn': row['gpn'], 'required_spools': 3,
        'create_item': {'location': 'Receiving', 'handler': BADGES['handler']}}), before, 409)
    assert len(physical_order(api, project_id)['assemblies']) == 2


def test_linked_spool_numbers_and_quantities_are_validated_per_physical_assembly(api):
    result = create_setup(api, assemblies=[branch(quantity=2, spools=[
        {'spool_number': '000-SPOOL-A', 'quantity_per_assembly': 1},
        {'spool_number': '000-SPOOL-B', 'quantity_per_assembly': 1}])])
    project_id = result['order']['project_id']
    assembly_id = _physical_assembly(api, result)
    a = _spool(api, project_id, 'SPOOL-A-1', '000-spool-a')
    b = _spool(api, project_id, 'SPOOL-B-1', '000-SPOOL-B')
    extra = _spool(api, project_id, 'SPOOL-A-EXTRA', '000-SPOOL-A')
    wrong = _spool(api, project_id, 'SPOOL-WRONG', 'NOT-IN-SETUP')
    ok(plan(api, a, project_id, assembly_id))
    before = database_state(api)
    rejected(api, plan(api, extra, project_id, assembly_id), before, 409)
    rejected(api, plan(api, wrong, project_id, assembly_id), before, 409)
    ok(plan(api, b, project_id, assembly_id))
    before = database_state(api)
    rejected(api, api.patch('/api/items/'+b+'/part-number', {
        'google_part_number': '000-SPOOL-A'}), before, 409)
    rejected(api, api.patch('/api/items/'+b+'/part-number', {
        'google_part_number': 'NOT-IN-SETUP'}), before, 409)
    other = _physical_assembly(api, detail(api, project_id), 'SECOND-ASSEMBLY')
    ok(plan(api, extra, project_id, other))
    assert physical_order(api, project_id)['totals']['linked_spools'] == 3


@pytest.mark.parametrize('numbers', [('WRONG', '000-SP-B'), ('000-SP-B', '000-SP-B')])
def test_adopting_an_existing_assembly_checks_its_preexisting_spool_type_scope(api, numbers):
    result = create_setup(api)
    project_id, row = result['order']['project_id'], result['assemblies'][0]
    assembly_id = ok(api.post('/api/items', {'id': 'PREEXISTING-ASSEMBLY', 'kind': 'Assembly',
        'project': project_id, 'google_part_number': row['gpn'], 'location': 'Receiving',
        'handler': BADGES['handler'], 'welds_required': 0}), 201)['id']
    for index, number in enumerate(numbers):
        spool_id = _spool(api, project_id, 'PRELINKED-SPOOL-'+str(index), number)
        ok(plan(api, spool_id, project_id, assembly_id))
    before = database_state(api)
    body = assembly_body(api, project_id, row['gpn_id'], item_id=assembly_id, create=False,
                         count=3, assembly_part_number=row['gpn'])
    rejected(api, api.post('/api/orders/'+project_id+'/assemblies', body), before, 409)


def test_reads_require_auth_are_pure_and_release_the_auth_connection(api):
    result = create_setup(api)
    project_id = result['order']['project_id']
    before = database_state(api)
    assert api.get(ROOT, role=None).status_code == 401
    assert api.get(f'{ROOT}/{project_id}', role=None).status_code == 401
    assert api.get(ROOT+'/UNKNOWN').status_code == 404
    for role in BADGES:
        data = ok(api.get(ROOT, role=role))
        assert data['permissions']['can_manage'] == (role in ('admin', 'supervisor'))
        assert api.get(f'{ROOT}/{project_id}', role=role).status_code == 200
    with api.session_factory() as session:
        engine = session.get_bind()
    borrowed, unsafe = set(), []
    peak = 0

    def checkout(connection, record, proxy):
        nonlocal peak
        borrowed.add(id(record)); peak = max(peak, len(borrowed))

    def checkin(connection, record):
        borrowed.discard(id(record))

    def observe(connection, cursor, statement, parameters, context, many):
        sql = statement.upper().lstrip()
        if sql.startswith(('INSERT', 'UPDATE', 'DELETE', 'LOCK ')) or 'FOR UPDATE' in sql or 'PG_ADVISORY' in sql:
            unsafe.append(statement)

    event.listen(engine, 'checkout', checkout); event.listen(engine, 'checkin', checkin)
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        for path in (ROOT, ROOT+'/'+project_id):
            assert api.get(path).status_code == 200
            assert not borrowed
    finally:
        event.remove(engine, 'checkout', checkout); event.remove(engine, 'checkin', checkin)
        event.remove(engine, 'before_cursor_execute', observe)
    assert peak == 1 and not unsafe
    assert database_state(api) == before
