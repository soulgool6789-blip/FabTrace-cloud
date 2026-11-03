"""Required business assembly numbers preserve retained unnamed history."""
import importlib

import pytest

from conftest import BADGES
from test_order_labels import generate, generation_body, labels, public_qr_url
from test_order_setup import detail
from test_progress import database_state
from test_removal_orders import change
from tracking_helpers import ok


MISSING = object()


def branch(number='000-ASM-001', *, gpn='TEST-GPN', welds=0):
    return {'gpn': gpn, 'assembly_number': number, 'assembly_quantity': 1,
            'spools': [{'spool_number': '000-SPOOL-001', 'quantity_per_assembly': 1,
                        'welds_per_spool': welds}]}


def setup(api, *, number='000-ASM-001', welds=0):
    return ok(api.post('/api/order-setup', {'purchase_order': 'PO-REQUIRED-NUMBER',
        'assemblies': [branch(number, welds=welds)]}), 201)


def legacy_blank(api, saved, value=''):
    """Model a retained historical record, never an accepted new API write."""
    orders = importlib.import_module('orders')
    with api.session_factory() as session:
        group = session.get(orders.OrderGpn, saved['assemblies'][0]['gpn_id'])
        group.assembly_number = value
        group.normalized_assembly_number = None
        session.commit()
    return detail(api, saved['order']['project_id'])


def physical_body(saved, **values):
    group = saved['assemblies'][0]
    return {'expected_version': saved['order']['version'], 'gpn_id': group['gpn_id'],
        'item_id': 'REQUIRED-ASSEMBLY-01', 'assembly_part_number': group['gpn'],
        'required_spools': 1, 'create_item': {'id': 'REQUIRED-ASSEMBLY-01',
        'google_part_number': group['gpn'], 'location': 'Receiving',
        'handler': BADGES['handler']}, **values}


def register(api, saved, **values):
    project = saved['order']['project_id']
    return ok(api.post(f'/api/orders/{project}/assemblies', physical_body(saved, **values)), 201)


def quantity_body(saved, **values):
    group = saved['assemblies'][0]
    return {'expected_version': saved['order']['version'], 'gpn': group['gpn'],
        'assembly_quantity': group['assembly_quantity'],
        'spools': [{key: row[key] for key in
                   ('spool_number', 'quantity_per_assembly', 'welds_per_spool')}
                  for row in group['spools']],
        'reason': 'Correct the recorded assembly setup', **values}


def reject_without_writes(api, request, status):
    before = database_state(api)
    response = request()
    assert response.status_code == status, response.text
    assert database_state(api) == before, 'Rejection must retain every value, version and audit row'
    return response


@pytest.mark.parametrize('bad', [MISSING, '', ' \t\n ', None], ids=['omitted', 'empty', 'whitespace', 'null'])
def test_new_definitions_and_combined_registration_require_a_number_without_writes(api, bad):
    saved = setup(api)
    project, group = saved['order']['project_id'], saved['assemblies'][0]
    number = {} if bad is MISSING else {'assembly_number': bad}
    unnamed = branch('SECOND', gpn='NEW-GPN')
    del unnamed['assembly_number']
    unnamed.update(number)
    combined = {'expected_version': 1, 'gpn': 'NEW-GPN', 'required_spools': 1,
        'create_item': {'id': 'UNSAVED-ASSEMBLY', 'location': 'Receiving',
                        'handler': BADGES['handler']}, **number}
    requests = [
        ('/api/order-setup', {'purchase_order': 'PO-SECOND',
            'assemblies': [branch('VALID-FIRST'), unnamed]}),
        (f'/api/order-setup/{project}/assemblies', {'expected_version': 1, **unnamed}),
        (f'/api/orders/{project}/gpns', {'expected_version': 1, 'gpn': 'NEW-GPN', **number}),
        (f'/api/orders/{project}/gpn-assemblies', combined),
        (f'/api/orders/{project}/gpn-assemblies', {
            **combined, 'gpn_id': group['gpn_id'], 'gpn': group['gpn']}),
    ]
    for path, body in requests:
        response = reject_without_writes(api, lambda: api.post(path, body), 422)
        assert 'assembly_number' in response.text


@pytest.mark.parametrize('bad', ['', ' \t\n ', None], ids=['empty', 'whitespace', 'null'])
def test_all_assembly_edit_inputs_reject_clearing_without_writes(api, bad):
    saved = setup(api)
    physical = register(api, saved)
    project = saved['order']['project_id']
    saved = detail(api, project)
    group, version = saved['assemblies'][0], saved['order']['version']
    physical_id = physical['assemblies'][0]['item_id']
    requests = [
        (f'/api/order-setup/{project}/assemblies/{group["gpn_id"]}',
         quantity_body(saved, assembly_number=bad)),
        (f'/api/order-setup/{project}/assemblies/{group["gpn_id"]}/identity',
         {'expected_version': version, 'assembly_number': bad,
          'reason': 'Attempt to clear the business number'}),
        (f'/api/orders/{project}/gpns/{group["gpn_id"]}',
         {'expected_version': version, 'gpn': group['gpn'], 'assembly_number': bad,
          'reason': 'Attempt to clear the business number'}),
        (f'/api/orders/{project}/gpn-assemblies/{physical_id}',
         {'expected_version': version, 'gpn': group['gpn'], 'assembly_number': bad,
          'required_spools': 1, 'reason': 'Attempt to clear the business number'}),
    ]
    for path, body in requests:
        response = reject_without_writes(api, lambda: api.patch(path, body), 422)
        assert 'assembly_number' in response.text


def test_leading_zero_number_is_explicit_and_valid_omitted_patch_preserves_it(api):
    saved = setup(api, number=' 0000042 ')
    group, project = saved['assemblies'][0], saved['order']['project_id']
    assert group['assembly_number'] == '0000042'
    saved = ok(api.patch(f'/api/order-setup/{project}/assemblies/{group["gpn_id"]}',
        quantity_body(saved)))
    assert saved['assemblies'][0]['assembly_number'] == '0000042'
    physical = register(api, saved)  # Exact definition ID may reuse its saved number.
    item_id = physical['assemblies'][0]['item_id']
    assert physical['assemblies'][0]['assembly_number'] == '0000042'
    physical = ok(api.patch(f'/api/orders/{project}/gpn-assemblies/{item_id}', {
        'expected_version': physical['order']['version'], 'gpn': group['gpn'],
        'required_spools': 1, 'reason': 'Keep the supplied independent Assembly Number'}))
    assert physical['assemblies'][0]['assembly_number'] == '0000042'
    physical = ok(api.patch(f'/api/orders/{project}/gpns/{group["gpn_id"]}', {
        'expected_version': physical['order']['version'], 'gpn': group['gpn'],
        'reason': 'Keep the existing independent Assembly Number'}))
    assert physical['gpns'][0]['assembly_number'] == '0000042'


@pytest.mark.parametrize('supplied', ['', ' \t ', None, 'MISMATCH'])
def test_exact_definition_physical_registration_rejects_blank_or_mismatched_supplied_number(api, supplied):
    saved = setup(api)
    path = f'/api/orders/{saved["order"]["project_id"]}/assemblies'
    reject_without_writes(api, lambda: api.post(path,
        physical_body(saved, assembly_number=supplied)), 409 if supplied == 'MISMATCH' else 422)


def test_exact_definition_physical_registration_accepts_matching_number(api):
    saved = setup(api)
    registered = register(api, saved, assembly_number=saved['assemblies'][0]['assembly_number'])
    assert registered['assemblies'][0]['gpn_id'] == saved['assemblies'][0]['gpn_id']
    assert registered['assemblies'][0]['assembly_number'] == '000-ASM-001'


@pytest.mark.parametrize('with_physical', [False, True])
def test_omitted_edits_cannot_save_an_unresolved_historical_number(api, with_physical):
    saved = setup(api, welds=None)
    project = saved['order']['project_id']
    if with_physical:
        register(api, saved)
    saved = legacy_blank(api, saved)
    group, version = saved['assemblies'][0], saved['order']['version']
    body = quantity_body(saved)
    body['spools'][0]['welds_per_spool'] = 0
    requests = [
        (f'/api/order-setup/{project}/assemblies/{group["gpn_id"]}', body),
        (f'/api/orders/{project}/gpns/{group["gpn_id"]}',
         {'expected_version': version, 'gpn': group['gpn'],
          'reason': 'An unresolved Assembly Number cannot be saved'}),
    ]
    if with_physical:
        requests.extend([
            (f'/api/orders/{project}/assemblies/REQUIRED-ASSEMBLY-01',
             {'expected_version': version, 'assembly_part_number': group['gpn'],
              'required_spools': 1, 'reason': 'Update a retained physical record'}),
            (f'/api/orders/{project}/gpn-assemblies/REQUIRED-ASSEMBLY-01',
             {'expected_version': version, 'gpn': group['gpn'],
              'required_spools': 1, 'reason': 'Update a retained physical record'}),
        ])
    for path, values in requests:
        response = reject_without_writes(api, lambda: api.patch(path, values), 409)
        assert 'Assembly Number is required' in response.text and 'Edit assembly' in response.text


@pytest.mark.parametrize('supplied', [MISSING, '000-VERIFIED'], ids=['saved_number_missing', 'cannot_name_during_registration'])
def test_physical_registration_cannot_use_an_unnamed_selected_definition(api, supplied):
    saved = legacy_blank(api, setup(api), ' \t ')
    path = f'/api/orders/{saved["order"]["project_id"]}/assemblies'
    values = {} if supplied is MISSING else {'assembly_number': supplied}
    response = reject_without_writes(api, lambda: api.post(path, physical_body(saved, **values)), 409)
    assert 'Assembly Number is required' in response.text


@pytest.mark.parametrize('pending', ['parent', 'child', 'welds'])
def test_qr_generation_cannot_mutate_unnamed_scope_but_reading_remains_available(api, pending):
    saved = setup(api, welds=None if pending == 'welds' else 0)
    project = saved['order']['project_id']
    if pending == 'child':
        register(api, saved)
    elif pending == 'welds':
        generate(api, project)
        models = importlib.import_module('order_setup')
        with api.session_factory() as session:
            session.add(models.OrderSpoolWeldRequirement(
                requirement_id=saved['assemblies'][0]['spools'][0]['id'],
                welds_per_spool=0, created_by=BADGES['admin']))
            session.commit()
    saved = legacy_blank(api, saved)
    before = database_state(api)
    overview = ok(api.get(f'/api/order-labels/{project}'))
    listed = labels(api, project)
    assert overview['groups'][0]['assembly_number'] == ''
    assert database_state(api) == before
    if listed['items']:
        item = listed['items'][0]
        assert api.get(f'/api/order-labels/{project}/labels/{item["id"]}/download.svg').status_code == 200
        assert database_state(api) == before
    response = reject_without_writes(api, lambda: api.post(
        f'/api/order-labels/{project}/generate', generation_body(api, project)), 409)
    assert 'Assembly Number is required' in response.text


def test_complete_unnamed_history_allows_reprint_noop_restore_and_explicit_identity_repair(api):
    saved = setup(api)
    project = saved['order']['project_id']
    generate(api, project)
    saved = legacy_blank(api, saved)
    group, original = saved['assemblies'][0], labels(api, project)['items'][0]
    before = database_state(api)
    assert api.get(f'/api/order-labels/{project}/labels/{original["id"]}/download.svg').status_code == 200
    assert generate(api, project)['created_count'] == 0
    assert database_state(api) == before
    change(api, 'gpn', group['gpn_id'])
    change(api, 'gpn', group['gpn_id'], 'restore')
    saved = detail(api, project)
    assert saved['assemblies'][0]['assembly_number'] == ''
    assert saved['assemblies'][0]['spools'][0]['id'] == group['spools'][0]['id']
    changed = ok(api.patch(f'/api/order-setup/{project}/assemblies/{group["gpn_id"]}/identity', {
        'expected_version': saved['order']['version'], 'assembly_number': '000-REPAIRED',
        'reason': 'Record the actual number from the retained assembly drawing'}))
    assert changed['assemblies'][0]['gpn_id'] == group['gpn_id']
    assert changed['assemblies'][0]['assembly_number'] == '000-REPAIRED'
    current = labels(api, project)['items'][0]
    for field in ('id', 'qr_alias', 'assembly_id', 'spool_number'):
        assert current[field] == original[field]


def test_complete_unnamed_sibling_does_not_block_named_missing_copy_generation(api):
    saved = setup(api)
    project = saved['order']['project_id']
    generate(api, project)
    saved = legacy_blank(api, saved)
    original = labels(api, project)['items'][0]
    saved = ok(api.post(f'/api/order-setup/{project}/assemblies', {
        'expected_version': saved['order']['version'], **branch('000-NAMED-SECOND')}), 201)
    generated = generate(api, project)
    assert generated['created_spool_count'] == generated['created_assembly_count'] == 1
    assert next(row for row in labels(api, project)['items'] if row['id'] == original['id']) == original


@pytest.mark.parametrize('route', ['/api/orders', '/api/order-setup'])
def test_independent_gpn_record_still_does_not_require_an_assembly_number(api, route):
    saved = setup(api)
    project = saved['order']['project_id']
    created = ok(api.post(f'{route}/{project}/gpn-records', {
        'expected_version': saved['order']['version'], 'gpn': 'INDEPENDENT-GPN'}), 201)
    record = next(row for row in created['gpn_records'] if row['id'] == created['saved_gpn_record_id'])
    assert record['assembly_count'] == 0
    assert detail(api, project)['assemblies'] == saved['assemblies']
