"""PO-derived assembly QR labels keep physical identity and planning separate."""
import importlib

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import ok
from test_order_setup import branch, create_setup, detail, edit_body
from test_order_setup_integration import register_assembly
from test_progress import database_state
from test_removal_orders import change


ROOT = '/api/order-labels'
PUBLIC_URL = 'https://fabtrace-label-tests.example'


@pytest.fixture(autouse=True)
def public_qr_url(application, monkeypatch):
    monkeypatch.setattr(application, 'PUBLIC_BASE_URL', PUBLIC_URL)


def overview(api, project, **params):
    return ok(api.get(f'{ROOT}/{project}', params=params))


def generation_body(api, project, **values):
    return {'expected_version': overview(api, project)['order']['version'],
            'location': 'Synthetic receiving bay', 'handler': BADGES['handler'], **values}


def generate(api, project, **values):
    return ok(api.post(f'{ROOT}/{project}/generate', generation_body(api, project, **values)))


def labels(api, project, **params):
    return ok(api.get(f'{ROOT}/{project}/labels', params=params))


def test_overview_uses_declared_assembly_quantities_and_read_calls_do_not_write(api):
    setup = create_setup(api, assemblies=[branch('000-GPN-B', 2), branch('000-GPN-A', 3)])
    project = setup['order']['project_id']
    before = database_state(api)
    result = overview(api, project)
    assert [row['gpn'] for row in result['groups']] == ['000-GPN-A', '000-GPN-B']
    assert [row['assembly_quantity'] for row in result['groups']] == [3, 2]
    assert result['totals'] == {'registered_quantity': 0, 'remaining_quantity': 5,
                                'undeclared_groups': 0}
    assert result['qr_ready'] and result['limit'] == 500
    assert result['permissions']['can_manage']
    assert labels(api, project)['items'] == []
    for role in BADGES:
        read = ok(api.get(f'{ROOT}/{project}', role=role))
        assert read['permissions']['can_manage'] == (role in ('admin', 'supervisor'))
        assert api.get(f'{ROOT}/{project}/labels', role=role).status_code == 200
    assert api.get(f'{ROOT}/{project}', role=None).status_code == 401
    assert api.get(f'{ROOT}/{project}/labels', role=None).status_code == 401
    assert database_state(api) == before


def test_generate_registers_each_assembly_with_unique_qr_and_one_order_revision(api):
    setup = create_setup(api, assemblies=[branch(), branch('000-GPN-B', 2, [
        {'spool_number': '000-SP-C', 'quantity_per_assembly': 7}])])
    project = setup['order']['project_id']
    result = generate(api, project)
    assert result['created_count'] == len(set(result['created_ids'])) == 5
    assert result['order']['version'] == 2 and result['remaining_quantity'] == 0
    assert [row['registered_quantity'] for row in result['groups']] == [3, 2]
    printed = labels(api, project)
    assert printed['total'] == len(printed['items']) == 5
    assert {item['id'] for item in printed['items']} == set(result['created_ids'])
    assert len({item['qr_url'] for item in printed['items']}) == 5
    order_models = importlib.import_module('orders')
    with api.session_factory() as session:
        for output in printed['items']:
            item = session.get(api.application.Item, output['id'])
            mapping = session.get(order_models.OrderAssembly, item.id)
            assert item.id.startswith('ASM-') and len(item.id) <= 60
            assert item.kind == 'Assembly' and item.project == project
            assert item.google_part_number == mapping.assembly_part_number == output['gpn']
            assert mapping.gpn_id == output['gpn_id']
            assert mapping.required_spools == (3 if output['gpn'] == '000-GPN-A' else 7)
            assert item.location == 'Synthetic receiving bay' and item.handler == BADGES['handler']
            assert item.welds_required == item.welds_done == 0
            assert item.dimensional == item.weld == 'Not started'
            assert not item.released and item.released_at is None and item.released_by is None
            assert output['purchase_order'] == '000123'
            assert output['qr_url'] == PUBLIC_URL + '/?item=' + item.id
        for name in ('tracking_spool_plans', 'tracking_welds', 'flow_plans', 'flow_events',
                     'tracking_process_events', 'inspections', 'reworks', 'item_transfer_events'):
            table = api.application.Base.metadata.tables.get(name)
            if table is not None:
                assert session.execute(select(table)).all() == [], name
        events = session.scalars(select(api.application.Audit).order_by(api.application.Audit.id)).all()
        assert len([row for row in events if row.event == 'ITEM_CREATED']) == 5
        generated = [row for row in events if row.event == 'ORDER_ASSEMBLY_LABELS_GENERATED']
        assert len(generated) == 1 and generated[0].details['version'] == 2
        assert set(generated[0].details['after']['created_ids']) == set(result['created_ids'])
    for item in printed['items']:
        response = api.get('/api/items/' + item['id'] + '/qr.png', role='handler')
        assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
        assert response.content.startswith(b'\x89PNG\r\n\x1a\n') and len(response.content) > 300
        assert ok(api.get('/api/items/' + item['id']))['qr_url'] == item['qr_url']
    assert api.patch(f'/api/order-setup/{project}/assemblies/{setup["assemblies"][0]["gpn_id"]}',
                     edit_body(detail(api, project))).status_code == 409


def test_existing_physical_ids_are_reused_and_reprints_and_noop_do_not_mutate(api):
    setup = create_setup(api)
    project = setup['order']['project_id']
    register_assembly(api, setup, item_id='KEEP-EXISTING-ASSEMBLY')
    with api.session_factory() as session:
        prior = session.get(api.application.Item, 'KEEP-EXISTING-ASSEMBLY')
        original = {column.name: getattr(prior, column.name) for column in prior.__table__.columns}
    result = generate(api, project, location='Different registration bay', handler=BADGES['welder'])
    assert result['created_count'] == 2
    assert 'KEEP-EXISTING-ASSEMBLY' not in result['created_ids']
    with api.session_factory() as session:
        prior = session.get(api.application.Item, 'KEEP-EXISTING-ASSEMBLY')
        assert {column.name: getattr(prior, column.name) for column in prior.__table__.columns} == original
    before = database_state(api)
    first = labels(api, project)
    second = labels(api, project)
    assert second == first
    noop = generate(api, project, location='Do not overwrite custody', handler=BADGES['supervisor'])
    assert noop['created_count'] == 0 and noop['created_ids'] == []
    assert noop['order']['version'] == result['order']['version']
    assert database_state(api) == before
    stale = api.post(f'{ROOT}/{project}/generate', generation_body(api, project, expected_version=1))
    assert stale.status_code == 409 and database_state(api) == before


def test_selected_gpn_generates_only_its_missing_instances_and_retains_other_quantities(api):
    setup = create_setup(api, assemblies=[branch(), branch('000-GPN-B', 2)])
    project = setup['order']['project_id']
    selected = setup['assemblies'][1]['gpn_id']
    response = ok(api.post(f'{ROOT}/{project}/generate',
        generation_body(api, project, gpn_id=selected), role='supervisor'))
    assert response['created_count'] == 2 and len(response['groups']) == 1
    all_groups = overview(api, project)['groups']
    assert [row['registered_quantity'] for row in all_groups] == [0, 2]
    assert [row['remaining_quantity'] for row in all_groups] == [3, 0]
    assert labels(api, project, gpn_id=setup['assemblies'][0]['gpn_id'])['items'] == []
    assert {row['gpn_id'] for row in labels(api, project)['items']} == {selected}


def test_generation_is_bounded_and_paged_reprinting_uses_one_stable_identity_per_unit(api):
    setup = create_setup(api, assemblies=[branch('000-GPN-B', 8), branch('000-GPN-A', 496)])
    project = setup['order']['project_id']
    first = generate(api, project)
    assert first['created_count'] == 500 and first['remaining_quantity'] == 4
    assert [row['registered_quantity'] for row in first['groups']] == [496, 4]
    assert first['order']['version'] == 2
    second = generate(api, project)
    assert second['created_count'] == 4 and second['remaining_quantity'] == 0
    assert second['order']['version'] == 3
    assert not set(first['created_ids']) & set(second['created_ids'])
    before = database_state(api)
    pages = [labels(api, project, offset=offset) for offset in range(0, 600, 100)]
    assert [len(page['items']) for page in pages] == [100, 100, 100, 100, 100, 4]
    assert all(page['total'] == 504 for page in pages)
    ids = [item['id'] for page in pages for item in page['items']]
    assert len(set(ids)) == 504
    assert set(ids) == set(first['created_ids'] + second['created_ids'])
    assert labels(api, project, offset=600)['items'] == []
    assert labels(api, project, offset=100)['items'] == pages[1]['items']
    assert database_state(api) == before


@pytest.mark.parametrize('role', [None, *[role for role in BADGES if role not in ('admin', 'supervisor')]])
def test_generation_requires_current_management_authority(api, role):
    setup = create_setup(api)
    project = setup['order']['project_id']
    body = generation_body(api, project)
    before = database_state(api)
    response = api.post(f'{ROOT}/{project}/generate', body, role=role)
    assert response.status_code == (401 if role is None else 403)
    assert database_state(api) == before


@pytest.mark.parametrize('problem', ['unknown', 'inactive', 'removed'])
def test_invalid_current_custodian_prevents_all_registration(api, problem):
    setup = create_setup(api)
    project = setup['order']['project_id']
    handler = BADGES['handler']
    if problem == 'unknown':
        handler = 'UNKNOWN-BADGE'
    elif problem == 'inactive':
        with api.session_factory() as session:
            session.get(api.application.Employee, handler).active = False
            session.commit()
    else:
        from test_employee_removal import remove
        remove(api, handler)
    body = generation_body(api, project, handler=handler)
    before = database_state(api)
    assert api.post(f'{ROOT}/{project}/generate', body).status_code == 422
    assert database_state(api) == before


@pytest.mark.parametrize('url', ['http://testserver', 'https://localhost', 'https://example.com/path'])
def test_unconfigured_public_https_cannot_generate_or_offer_broken_qrs(api, monkeypatch, url):
    setup = create_setup(api)
    project = setup['order']['project_id']
    register_assembly(api, setup)
    monkeypatch.setattr(api.application, 'PUBLIC_BASE_URL', url)
    body = generation_body(api, project)
    before = database_state(api)
    assert not overview(api, project)['qr_ready']
    printed = labels(api, project)
    assert not printed['qr_ready'] and all(row['qr_url'] is None for row in printed['items'])
    assert api.post(f'{ROOT}/{project}/generate', body).status_code == 503
    assert api.get('/api/items/PHYSICAL-ASSEMBLY-1/qr.png').status_code == 503
    assert database_state(api) == before


def test_mixed_legacy_scope_keeps_known_ids_printable_and_requires_explicit_quantity_setup(api):
    setup = create_setup(api)
    project = setup['order']['project_id']
    legacy = ok(api.post(f'/api/orders/{project}/gpn-assemblies', {
        'expected_version': 1, 'gpn': 'LEGACY-ASSEMBLY', 'required_spools': 1,
        'create_item': {'id': 'KEEP-LEGACY-QR', 'location': 'Legacy bay', 'handler': BADGES['welder']},
    }), 201)
    current = overview(api, project)
    assert current['totals']['undeclared_groups'] == 1
    assert current['totals']['remaining_quantity'] is None
    assert labels(api, project)['items'][0]['id'] == 'KEEP-LEGACY-QR'
    before = database_state(api)
    body = generation_body(api, project)
    assert api.post(f'{ROOT}/{project}/generate', body).status_code == 409
    body['gpn_id'] = legacy['selected_gpn_id']
    assert api.post(f'{ROOT}/{project}/generate', body).status_code == 409
    assert database_state(api) == before
    selected = generate(api, project, gpn_id=setup['assemblies'][0]['gpn_id'])
    assert selected['created_count'] == 3
    assert 'KEEP-LEGACY-QR' in {row['id'] for row in labels(api, project)['items']}


def test_foreign_unknown_and_removed_scopes_reject_without_partial_registration(api):
    setup = create_setup(api, assemblies=[branch(), branch('000-GPN-B', 1)])
    project = setup['order']['project_id']
    other = create_setup(api, number='000124')
    before = database_state(api)
    for gpn in ('DOES-NOT-EXIST', other['assemblies'][0]['gpn_id']):
        assert api.get(f'{ROOT}/{project}', params={'gpn_id': gpn}).status_code == 422
        assert api.get(f'{ROOT}/{project}/labels', params={'gpn_id': gpn}).status_code == 422
        assert api.post(f'{ROOT}/{project}/generate', generation_body(api, project, gpn_id=gpn)).status_code == 422
    assert api.get(ROOT + '/MISSING').status_code == 404
    assert database_state(api) == before
    removed = setup['assemblies'][0]['gpn_id']
    change(api, 'gpn', removed)
    before = database_state(api)
    assert len(overview(api, project)['groups']) == 1
    assert api.get(f'{ROOT}/{project}', params={'gpn_id': removed}).status_code == 409
    assert api.post(f'{ROOT}/{project}/generate', generation_body(api, project, gpn_id=removed)).status_code == 409
    assert database_state(api) == before
    body = generation_body(api, project)
    change(api, 'order', project)
    before = database_state(api)
    assert api.get(f'{ROOT}/{project}').status_code == 404
    assert api.get(f'{ROOT}/{project}/labels').status_code == 404
    assert api.post(f'{ROOT}/{project}/generate', body).status_code == 409
    assert database_state(api) == before


def test_removed_physical_identity_is_retained_and_replacement_gets_a_new_qr(api):
    setup = create_setup(api, assemblies=[branch(quantity=1)])
    project = setup['order']['project_id']
    original = generate(api, project)['created_ids'][0]
    change(api, 'item', original)
    assert labels(api, project)['items'] == []
    assert overview(api, project)['groups'][0]['remaining_quantity'] == 1
    replacement = generate(api, project)['created_ids'][0]
    assert replacement != original
    assert labels(api, project)['items'][0]['id'] == replacement
    assert ok(api.get('/api/items/' + original))['removal']['removed']
    preview = ok(api.get('/api/removals/item/' + original, params={'action': 'restore'}))
    assert not preview['can_proceed']
    assert any('exceed' in message for message in preview['blockers'])


@pytest.mark.parametrize('values', [
    {'expected_version': True}, {'expected_version': 0}, {'location': ''},
    {'location': '   '}, {'handler': ''}, {'gpn_id': ''}, {'quantity': 10},
])
def test_invalid_generation_inputs_never_create_partial_items(api, values):
    setup = create_setup(api)
    project = setup['order']['project_id']
    body = generation_body(api, project, **values)
    before = database_state(api)
    assert api.post(f'{ROOT}/{project}/generate', body).status_code == 422
    assert database_state(api) == before


@pytest.mark.parametrize('params', [{'offset': -1}, {'limit': 0}, {'limit': 101},
                                    {'limit': 1.5}, {'gpn_id': ''}])
def test_invalid_label_pages_are_rejected(api, params):
    setup = create_setup(api)
    project = setup['order']['project_id']
    before = database_state(api)
    assert api.get(f'{ROOT}/{project}/labels', params=params).status_code == 422
    assert database_state(api) == before


def test_id_collision_and_late_scope_failure_roll_back_entire_batch(api, monkeypatch):
    setup = create_setup(api)
    project = setup['order']['project_id']
    module = importlib.import_module('order_labels')
    body = generation_body(api, project)
    before = database_state(api)
    with monkeypatch.context() as patch:
        patch.setattr(module, 'new_id', lambda prefix: 'COLLIDING-GENERATED-ID')
        assert api.post(f'{ROOT}/{project}/generate', body).status_code == 409
    assert database_state(api) == before
    original_check = module._validate_assembly_scope
    calls = []

    def fail_after_first(s, order, item, required_spools):
        calls.append(item.id)
        if len(calls) == 2:
            raise HTTPException(409, 'Synthetic late scope conflict')
        return original_check(s, order, item, required_spools)

    with monkeypatch.context() as patch:
        patch.setattr(module, '_validate_assembly_scope', fail_after_first)
        response = api.post(f'{ROOT}/{project}/generate', body)
        assert response.status_code == 409
    assert len(calls) == 2 and database_state(api) == before
