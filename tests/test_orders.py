"""PO-first planning preserves unique physical identities and quality gates."""
import importlib

import pytest
from sqlalchemy import event, select

from conftest import BADGES
from tracking_helpers import ok
from test_admin import release as admin_release
from test_flow import PROJECT, completed_spool, create_item, detail as flow_detail, enroll, link_spool
from test_progress import database_state
from test_dossier import config_body, configure, issued_fixture, packet


ROOT = '/api/orders'


def new_order(api, number='PO-100', customer='Synthetic customer', **values):
    return ok(api.post(ROOT, {'expected_version': 0, 'purchase_order': number,
                              'customer': customer, 'name': 'Synthetic PO job', **values}), 201)


def current(api, project_id):
    return ok(api.get(ROOT + '/' + project_id))


def version(api, project_id):
    return current(api, project_id)['order']['version']


def group(api, project_id, number='GPN-001'):
    result = ok(api.post(f'{ROOT}/{project_id}/gpns', {
        'expected_version': version(api, project_id), 'gpn': number, 'description': 'Synthetic GPN family',
    }), 201)
    return next(row['id'] for row in result['gpns'] if row['gpn'] == number)


def assembly_body(api, project_id, gpn_id, item_id='ORDER-ASM-01', count=2, *, create=True, **values):
    body = {'expected_version': version(api, project_id), 'gpn_id': gpn_id, 'item_id': item_id,
            'assembly_part_number': 'ASM-DESIGN-01', 'required_spools': count, 'notes': 'Synthetic order scope', **values}
    if create:
        body['create_item'] = {'id': item_id, 'description': 'Synthetic physical assembly',
                               'google_part_number': 'PHYSICAL-PART-GPN', 'drawing': 'SYNTHETIC-ISO-REV-A',
                               'location': 'Receiving', 'handler': BADGES['handler'], 'welds_required': 0}
    return body


def add_assembly(api, project_id, gpn_id, **values):
    return ok(api.post(f'{ROOT}/{project_id}/assemblies', assembly_body(api, project_id, gpn_id, **values)), 201)


def setup(api, *, count=2):
    order = new_order(api)
    project_id = order['order']['project_id']
    gpn_id = group(api, project_id)
    detail = add_assembly(api, project_id, gpn_id, count=count)
    return project_id, gpn_id, detail


def plan(api, item_id, project_id, assembly_id=None, planned=0):
    existing = ok(api.get(f'/api/tracking/spools/{item_id}'))['plan']
    body = {'project_id': project_id, 'assembly_id': assembly_id, 'planned_welds': planned,
            'zero_weld_reason': 'Synthetic assembly has no extra joining welds' if planned == 0 else '',
            'drawing_revision': 'SYNTHETIC-REV-A'}
    if existing:
        body['expected_version'] = existing['version']
    return api.post(f'/api/tracking/spools/{item_id}/plan', body)


def reject(api, response, before, codes=(409, 422)):
    assert response.status_code in codes, response.text
    assert database_state(api) == before


def test_po_first_creation_builds_hierarchy_without_inventing_physical_progress(api):
    project_id, gpn_id, detail = setup(api)
    assert project_id.startswith('PO-')
    assert detail['order']['purchase_order'] == 'PO-100'
    assert detail['order']['version'] == 3
    assert detail['gpns'][0]['gpn'] == 'GPN-001'
    item = detail['assemblies'][0]
    assert item['assembly_part_number'] == 'ASM-DESIGN-01'
    assert item['google_part_number'] == 'PHYSICAL-PART-GPN'
    assert item['gpn_id'] == gpn_id
    assert item['planning_needed'] and item['count_editable']
    assert {k: detail['totals'][k] for k in ('required_spools', 'linked_spools', 'missing_spools', 'ready_spools', 'not_ready_spools')} == {
        'required_spools': 2, 'linked_spools': 0, 'missing_spools': 2, 'ready_spools': 0, 'not_ready_spools': 0}
    flow = flow_detail(api, 'ORDER-ASM-01')
    assert flow['flow'] is None and flow['events'] == []
    assert flow['order_scope']['required_spools'] == 2
    assert flow['order_scope']['purchase_order'] == 'PO-100'
    assert not flow['item']['released']
    tracked = ok(api.get('/api/tracking/spools/ORDER-ASM-01'))
    assert tracked['plan'] is None and tracked['welds'] == []
    assert {event['event'] for event in detail['events']} == {'ORDER_CREATED', 'ORDER_GPN_CREATED', 'ORDER_ASSEMBLY_CREATED'}


def test_managed_assembly_cannot_use_legacy_release_before_its_traveler(api):
    project_id, _, _ = setup(api)
    for kind in ('Dimensional', 'Weld'):
        ok(api.post('/api/items/ORDER-ASM-01/inspect', {
            'kind': kind, 'result': 'Pass', 'report': 'SYNTHETIC-LEGACY-REPORT',
            'measurements': 'Synthetic test observations on an unplanned order assembly',
        }, role='inspector'))
    before = database_state(api)
    response = api.post('/api/items/ORDER-ASM-01/release', {'reference': 'SYNTHETIC-RELEASE'}, role='inspector')
    reject(api, response, before, (409,))
    assert 'assembly traveler' in response.text
    detail = current(api, project_id)
    assert any('traveler' in message for message in detail['assemblies'][0]['blockers'])
    admin_release(api, 'ORDER-ASM-01')
    assert flow_detail(api, 'ORDER-ASM-01')['release_control']['active_override']


def test_po_number_uses_job_packet_minimum_length(api):
    before = database_state(api)
    reject(api, api.post(ROOT, {'purchase_order': '1'}), before, (422,))


@pytest.mark.parametrize('role', [None, 'handler', 'welder', 'fitup_welder', 'process_welder', 'inspector', 'painter', 'finisher', 'misc'])
def test_only_admin_and_supervisor_can_change_orders_with_no_partial_writes(api, role):
    project_id, gpn_id, _ = setup(api)
    current_version = version(api, project_id)
    body = assembly_body(api, project_id, gpn_id, item_id='UNAUTHORIZED-ASM')
    before = database_state(api)
    expected = 401 if role is None else 403
    for response in (
        api.post(ROOT, {'purchase_order': 'UNAUTHORIZED-PO'}, role=role),
        api.patch(f'{ROOT}/{project_id}', {'expected_version': current_version, 'purchase_order': 'CHANGED', 'reason': 'Unapproved change'}, role=role),
        api.post(f'{ROOT}/{project_id}/gpns', {'expected_version': current_version, 'gpn': 'UNAUTHORIZED'}, role=role),
        api.patch(f'{ROOT}/{project_id}/gpns/{gpn_id}', {'expected_version': current_version, 'gpn': 'CHANGED', 'reason': 'Unapproved change'}, role=role),
        api.post(f'{ROOT}/{project_id}/assemblies', body, role=role),
        api.patch(f'{ROOT}/{project_id}/assemblies/ORDER-ASM-01', {'expected_version': current_version, 'assembly_part_number': 'CHANGED', 'required_spools': 3, 'reason': 'Unapproved change'}, role=role),
    ):
        assert response.status_code == expected, response.text
    assert database_state(api) == before


def test_reads_are_authorized_and_pure_even_for_legacy_projects(api):
    create_item(api, 'LEGACY-ASM', kind='Assembly')
    before = database_state(api)
    assert api.get(ROOT, role=None).status_code == 401
    assert api.get(ROOT + '/UNKNOWN', role=None).status_code == 401
    assert api.get(ROOT + '/UNKNOWN').status_code == 404
    result = ok(api.get(ROOT))
    assert result['orders'] == []
    assert result['unassigned_projects'][0]['id'] == PROJECT
    assert database_state(api) == before
    project_id, _, _ = setup(api)
    before = database_state(api)
    for role in BADGES:
        assert api.get(ROOT, role=role).status_code == 200
        detail = ok(api.get(ROOT + '/' + project_id, role=role))
        assert detail['permissions']['can_manage'] == (role in ('admin', 'supervisor'))
    assert database_state(api) == before


def test_order_reads_release_auth_connection_before_opening_snapshot(api):
    project_id, _, _ = setup(api)
    with api.session_factory() as session:
        engine = session.get_bind()
    borrowed = 0
    peak = 0

    def checkout(*_):
        nonlocal borrowed, peak
        borrowed += 1
        peak = max(peak, borrowed)

    def checkin(*_):
        nonlocal borrowed
        borrowed -= 1

    event.listen(engine, 'checkout', checkout)
    event.listen(engine, 'checkin', checkin)
    try:
        assert api.get(ROOT).status_code == 200
        assert api.get(ROOT + '/' + project_id).status_code == 200
        assert peak == 1
        assert borrowed == 0
    finally:
        event.remove(engine, 'checkout', checkout)
        event.remove(engine, 'checkin', checkin)


def test_normalized_po_and_gpn_uniqueness_roll_back_without_orphan_projects(api):
    detail = new_order(api, number='PO  100', customer='Synthetic  Customer')
    project_id = detail['order']['project_id']
    before = database_state(api)
    reject(api, api.post(ROOT, {'purchase_order': 'po 100', 'customer': ' synthetic customer '}), before, (409,))
    second = new_order(api, number='po 100', customer='Another customer')
    assert second['order']['project_id'] != project_id
    group(api, project_id, number='GPN  123')
    before = database_state(api)
    reject(api, api.post(f'{ROOT}/{project_id}/gpns', {'expected_version': version(api, project_id), 'gpn': 'gpn 123'}), before, (409,))
    group(api, second['order']['project_id'], number='gpn 123')


def test_maximum_unicode_identifiers_survive_casefold_expansion(api):
    value = '\u0390'  # Casefold expands one valid character to three characters.
    detail = new_order(api, number=value * 200, customer=value * 200)
    project_id = detail['order']['project_id']
    group(api, project_id, number=value * 160)
    result = current(api, project_id)
    assert result['order']['purchase_order'] == value * 200
    assert result['gpns'][0]['gpn'] == value * 160
    orders = importlib.import_module('orders')
    with api.session_factory() as session:
        assert len(session.get(orders.PurchaseOrder, project_id).normalized_number) == 600
        assert len(session.scalar(select(orders.OrderGpn)).normalized_gpn) == 480


def test_adopting_existing_project_is_explicit_and_preserves_legacy_identity(api):
    create_item(api, 'LEGACY-ASM', kind='Assembly')
    before = database_state(api)
    reject(api, api.post(ROOT, {'purchase_order': 'PO-ADOPT', 'existing_project_id': PROJECT}), before, (422,))
    reject(api, api.post(ROOT, {'purchase_order': 'PO-ADOPT', 'existing_project_id': PROJECT,
                               'customer': 'Unrelated customer', 'notes': 'Review existing project scope'}), before, (409,))
    detail = new_order(api, number='PO-ADOPT', customer='', existing_project_id=PROJECT,
                       notes='Reviewed existing project and purchase order reference')
    assert detail['order']['project_id'] == PROJECT
    assert detail['available_assemblies'][0]['item_id'] == 'LEGACY-ASM'
    assert detail['available_assemblies'][0]['planning_needed'] is False
    gpn_id = group(api, PROJECT)
    detail = add_assembly(api, PROJECT, gpn_id, item_id='LEGACY-ASM', count=2, create=False)
    assert detail['assemblies'][0]['planning_needed'] is False
    assert ok(api.get('/api/tracking/spools/LEGACY-ASM'))['plan']['project_id'] == PROJECT
    assert detail['available_assemblies'] == []


def test_existing_dossier_po_is_guarded_in_both_directions_and_old_issues_stay_current(api):
    issued = issued_fixture(api, 'ORDER-LEGACY-ISSUED')
    before = database_state(api)
    reject(api, api.post(ROOT, {'purchase_order': 'WRONG-PO', 'existing_project_id': PROJECT,
                               'notes': 'Reviewed old project scope'}), before, (409,))
    detail = new_order(api, number='TEST-PO-JOB-PACKET', customer='', existing_project_id=PROJECT,
                       notes='Reviewed exact existing controlled purchase order')
    assert packet(api, 'ORDER-LEGACY-ISSUED')['latest_issue'] == issued
    cfg = ok(api.get(f'/api/dossier/projects/{PROJECT}'))
    before = database_state(api)
    reject(api, api.put(f'/api/dossier/projects/{PROJECT}/config', {
        **config_body(purchase_order='WRONG-PO'), 'expected_version': cfg['version'],
    }), before, (409,))
    reject(api, api.patch(f'{ROOT}/{PROJECT}', {'expected_version': detail['order']['version'],
              'purchase_order': 'WRONG-PO', 'reason': 'Cannot replace a controlled source'}), before, (409,))


@pytest.mark.parametrize('count', [0, -1, 10001, True, 1.5, '2'])
def test_required_spool_count_is_a_positive_whole_number_and_registration_is_atomic(api, count):
    detail = new_order(api)
    project_id = detail['order']['project_id']
    gpn_id = group(api, project_id)
    body = assembly_body(api, project_id, gpn_id, count=count)
    before = database_state(api)
    reject(api, api.post(f'{ROOT}/{project_id}/assemblies', body), before, (422,))


def test_atomic_new_assembly_rejects_bad_custodian_or_identity_without_creating_items(api):
    detail = new_order(api)
    project_id = detail['order']['project_id']
    gpn_id = group(api, project_id)
    body = assembly_body(api, project_id, gpn_id)
    body['create_item']['handler'] = 'MISSING-BADGE'
    before = database_state(api)
    reject(api, api.post(f'{ROOT}/{project_id}/assemblies', body), before, (422,))
    body['create_item']['handler'] = BADGES['handler']
    body['create_item']['id'] = 'DIFFERENT-ASSEMBLY-ID'
    reject(api, api.post(f'{ROOT}/{project_id}/assemblies', body), before, (422,))
    body['create_item']['id'] = body['item_id']
    body['create_item']['released'] = True
    reject(api, api.post(f'{ROOT}/{project_id}/assemblies', body), before, (422,))


def test_cross_order_gpn_and_assembly_links_are_rejected(api):
    project_id, gpn_id, _ = setup(api)
    second = new_order(api, number='PO-200')['order']['project_id']
    second_group = group(api, second)
    body = assembly_body(api, project_id, second_group, item_id='WRONG-GPN-ASM')
    before = database_state(api)
    reject(api, api.post(f'{ROOT}/{project_id}/assemblies', body), before, (422,))
    create_item(api, 'OTHER-PROJECT-ASM', kind='Assembly', project=second)
    body = assembly_body(api, project_id, gpn_id, item_id='OTHER-PROJECT-ASM', create=False)
    before = database_state(api)
    reject(api, api.post(f'{ROOT}/{project_id}/assemblies', body), before, (409,))
    body = assembly_body(api, second, second_group, item_id='ORDER-ASM-01', create=False)
    reject(api, api.post(f'{ROOT}/{second}/assemblies', body), before, (409,))


def test_linked_spool_counts_missing_scope_and_legacy_planner_guards(api):
    project_id, _, _ = setup(api, count=1)
    ok(plan(api, 'ORDER-ASM-01', project_id))
    create_item(api, 'ORDER-SPOOL-01', kind='Spool', project=project_id)
    ok(plan(api, 'ORDER-SPOOL-01', project_id, 'ORDER-ASM-01'))
    detail = current(api, project_id)
    assert detail['totals']['linked_spools'] == 1 and detail['totals']['missing_spools'] == 0
    assert detail['totals']['ready_spools'] == 0 and detail['totals']['not_ready_spools'] == 1
    create_item(api, 'ORDER-SPOOL-02', kind='Spool', project=project_id)
    before = database_state(api)
    reject(api, plan(api, 'ORDER-SPOOL-02', project_id, 'ORDER-ASM-01'), before, (409,))
    create_item(api, 'ORDER-COMPONENT', kind='Part', project=project_id)
    before = database_state(api)
    reject(api, plan(api, 'ORDER-COMPONENT', project_id, 'ORDER-ASM-01'), before, (422,))
    other = new_order(api, number='OTHER-PO')['order']['project_id']
    before = database_state(api)
    reject(api, plan(api, 'ORDER-ASM-01', other), before, (409, 422))
    reject(api, plan(api, 'ORDER-SPOOL-01', other), before, (409,))


def test_count_cannot_shrink_below_unique_links_or_change_after_traveler_start(api):
    project_id, _, _ = setup(api)
    ok(plan(api, 'ORDER-ASM-01', project_id))
    for item_id in ('COUNT-SPOOL-01', 'COUNT-SPOOL-02'):
        create_item(api, item_id, kind='Spool', project=project_id)
        ok(plan(api, item_id, project_id, 'ORDER-ASM-01'))
    values = {'expected_version': version(api, project_id), 'assembly_part_number': 'ASM-DESIGN-01',
              'required_spools': 1, 'reason': 'Synthetic scope correction'}
    before = database_state(api)
    reject(api, api.patch(f'{ROOT}/{project_id}/assemblies/ORDER-ASM-01', values), before, (409,))
    reject(api, api.post('/api/flow/items/ORDER-ASM-01/start', {'route': 'assembly', 'expected_children': 3}), before, (409,))
    enrolled = enroll(api, 'ORDER-ASM-01', 'assembly', expected_children=2)
    assert enrolled['order_scope']['required_spools'] == 2
    assert current(api, project_id)['assemblies'][0]['count_editable'] is False
    values['required_spools'] = 3
    before = database_state(api)
    reject(api, api.patch(f'{ROOT}/{project_id}/assemblies/ORDER-ASM-01', values), before, (409,))
    reject(api, api.post('/api/flow/items/ORDER-ASM-01/scope', {'expected_version': enrolled['flow']['version'],
              'expected_children': 3, 'reference': 'SYNTHETIC-SCOPE', 'reason': 'Try old UI count change'}), before, (409,))


def test_released_order_parent_blocks_link_detach_and_child_scope_edits_without_a_traveler(api):
    project_id, _, _ = setup(api, count=2)
    ok(plan(api, 'ORDER-ASM-01', project_id))
    create_item(api, 'SCOPE-CHILD-01', kind='Spool', project=project_id)
    create_item(api, 'SCOPE-CHILD-02', kind='Spool', project=project_id)
    ok(plan(api, 'SCOPE-CHILD-01', project_id, 'ORDER-ASM-01'))
    admin_release(api, 'ORDER-ASM-01')
    assert flow_detail(api, 'ORDER-ASM-01')['flow'] is None
    before = database_state(api)
    reject(api, plan(api, 'SCOPE-CHILD-02', project_id, 'ORDER-ASM-01'), before, (409,))
    reject(api, plan(api, 'SCOPE-CHILD-01', project_id), before, (409,))
    reject(api, plan(api, 'SCOPE-CHILD-01', project_id, 'ORDER-ASM-01', planned=1), before, (409,))
    assert flow_detail(api, 'ORDER-ASM-01')['item']['released']


def test_ready_spools_require_ordinary_qa_and_completed_spool_route(api):
    create_item(api, 'READY-ASM', kind='Assembly')
    new_order(api, number='PO-READY', customer='', existing_project_id=PROJECT, notes='Reviewed existing assembly scope')
    gpn_id = group(api, PROJECT)
    add_assembly(api, PROJECT, gpn_id, item_id='READY-ASM', count=2, create=False)
    enroll(api, 'READY-ASM', 'assembly', expected_children=2)
    completed_spool(api, 'READY-SPOOL')
    link_spool(api, 'READY-ASM', 'READY-SPOOL')
    detail = current(api, PROJECT)
    assert detail['totals']['linked_spools'] == detail['totals']['ready_spools'] == 1
    assert detail['totals']['missing_spools'] == 1
    assert detail['totals']['not_ready_spools'] == 0
    assert detail['assemblies'][0]['spools'][0]['ready_for_assembly']


def test_admin_override_never_counts_as_ordinary_ready_spool(api):
    project_id, _, _ = setup(api, count=1)
    ok(plan(api, 'ORDER-ASM-01', project_id))
    create_item(api, 'OVERRIDE-SPOOL', kind='Spool', project=project_id)
    ok(plan(api, 'OVERRIDE-SPOOL', project_id, 'ORDER-ASM-01'))
    enroll(api, 'OVERRIDE-SPOOL', 'spool')
    admin_release(api, 'OVERRIDE-SPOOL')
    detail = current(api, project_id)
    assert detail['totals']['linked_spools'] == 1
    assert detail['totals']['ready_spools'] == 0
    assert detail['totals']['not_ready_spools'] == 1
    assert any('Administrative release' in text for text in detail['assemblies'][0]['spools'][0]['blockers'])


def test_stale_forms_and_duplicate_linking_never_create_another_physical_identity(api):
    project_id, gpn_id, detail = setup(api)
    before = database_state(api)
    reject(api, api.post(f'{ROOT}/{project_id}/gpns', {'expected_version': 1, 'gpn': 'STALE-GPN'}), before, (409,))
    body = assembly_body(api, project_id, gpn_id, create=False)
    reject(api, api.post(f'{ROOT}/{project_id}/assemblies', body), before, (409,))
    body = assembly_body(api, project_id, gpn_id, item_id='STALE-NEW-ASM')
    body['expected_version'] = 1
    reject(api, api.post(f'{ROOT}/{project_id}/assemblies', body), before, (409,))
    changed = ok(api.patch(f'{ROOT}/{project_id}/assemblies/ORDER-ASM-01', {
        'expected_version': detail['order']['version'], 'assembly_part_number': 'ASM-CORRECTED',
        'required_spools': 3, 'notes': 'Updated planned requirement', 'reason': 'Approved revised drawing scope',
    }, role='supervisor'))
    assert changed['assemblies'][0]['assembly_part_number'] == 'ASM-CORRECTED'
    assert changed['assemblies'][0]['google_part_number'] == 'PHYSICAL-PART-GPN'
    assert changed['order']['version'] == detail['order']['version'] + 1
    assert changed['events'][0]['details']['reason'] == 'Approved revised drawing scope'


def test_additive_schema_has_no_backfill_or_inferred_order_rows(api):
    create_item(api, 'SCHEMA-LEGACY', kind='Assembly')
    orders = importlib.import_module('orders')
    before = database_state(api)
    with api.session_factory() as session:
        api.application.Base.metadata.create_all(session.get_bind())
        for model in (orders.PurchaseOrder, orders.OrderGpn, orders.OrderAssembly):
            assert session.execute(select(model)).all() == []
    assert database_state(api) == before
