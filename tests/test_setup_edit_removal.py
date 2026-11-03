"""Saved setup removal preserves its identities, evidence and physical scope."""
import importlib
import json

import pytest

from tracking_helpers import ok
from test_order_setup import branch, create_setup, detail, edit_body, _physical_assembly
from test_progress import database_state
from test_removal_orders import change
from test_spool_documents import bom_csv, pdf, request_upload


ROOT = '/api/removals'


def setup(api, *, spools=None):
    return create_setup(api, assemblies=[branch('000-GPN-REMOVE', 1, spools or [
        {'spool_number': '000-SP-A', 'quantity_per_assembly': 1, 'welds_per_spool': 2},
        {'spool_number': '000-SP-B', 'quantity_per_assembly': 1, 'welds_per_spool': 1},
    ])])


def preview(api, line_id, action='remove'):
    return ok(api.get(f'{ROOT}/spool_line/{line_id}', params={'action': action}))


def change_body(review):
    return {key: review[key] for key in ('expected_version', 'preview_token', 'confirmation')} | {
        'reason': 'Correct this synthetic saved spool requirement with retained history'}


def rejected_change(api, line_id, review, action='remove'):
    before = database_state(api)
    result = api.post(f'{ROOT}/spool_line/{line_id}/{action}', change_body(review))
    assert result.status_code == 409, result.text
    assert database_state(api) == before


def retained_evidence(api):
    rows = json.loads(database_state(api))
    names = ('spool_document_sets', 'spool_documents', 'spool_document_files',
             'spool_document_file_links', 'order_spool_weld_requirements',
             'items', 'order_assemblies', 'order_spools', 'flow_plans',
             'flow_events', 'tracking_welds', 'tracking_process_events', 'inspections')
    return {name: rows[name] for name in names}


def test_saved_spool_with_documents_removes_and_restores_exact_requirement(api):
    saved = setup(api)
    project, assembly = saved['order']['project_id'], saved['assemblies'][0]
    line = assembly['spools'][0]
    path = '/api/spool-documents/requirements/' + line['id']
    bom = ok(request_upload(api, path, files=[
        ('Original-BOM.csv', bom_csv(line['spool_number']), 'text/csv')]))['active']['bom']
    drawing = ok(request_upload(api, path, kind='isometric', version=1,
        files=[('Original-drawing.pdf', pdf(2), 'application/pdf')]))['active']['isometric']
    content = {doc['id']: api.get(doc['download_url']).content for doc in (bom, drawing)}
    evidence = retained_evidence(api)

    reviewed = preview(api, line['id'])
    assert reviewed['can_proceed'], reviewed
    assert reviewed['kind'] == 'spool_line'
    assert {row['record_id'] for row in reviewed['affected']} == {line['id']}
    change(api, 'spool_line', line['id'])

    current = detail(api, project)
    assert current['order']['version'] == saved['order']['version'] + 1
    assert [row['id'] for row in current['assemblies'][0]['spools']] == [assembly['spools'][1]['id']]
    assert current['assemblies'][0]['spools_per_assembly'] == current['totals']['total_spools'] == 1
    assert retained_evidence(api) == evidence
    models = importlib.import_module('order_setup')
    removals = importlib.import_module('removals')
    with api.session_factory() as session:
        retained = session.get(models.OrderSpoolRequirement, line['id'])
        assert not retained.active
        assert (retained.gpn_id, retained.spool_number, retained.quantity_per_assembly) == (
            assembly['gpn_id'], line['spool_number'], line['quantity_per_assembly'])
        assert session.get(removals.RecordRemoval, ('spool_line', line['id'])).removed
    removed = ok(api.get(ROOT))['records']
    assert any(row['kind'] == 'spool_line' and row['record_id'] == line['id'] for row in removed)
    assert api.get(path).status_code == 404
    assert api.get(bom['download_url']).status_code == 404

    change(api, 'spool_line', line['id'], 'restore')
    restored = detail(api, project)
    assert [row['id'] for row in restored['assemblies'][0]['spools']] == [row['id'] for row in assembly['spools']]
    assert restored['totals'] == saved['totals']
    assert restored['assemblies'][0]['spools'][0]['welds_per_spool'] == 2
    assert retained_evidence(api) == evidence
    documents = ok(api.get(path))
    assert documents['version'] == 2
    for kind, original in (('bom', bom), ('isometric', drawing)):
        assert documents['active'][kind]['id'] == original['id']
        assert api.get(original['download_url']).content == content[original['id']]


def test_saved_spool_cannot_be_reactivated_by_an_ordinary_quantity_edit(api):
    saved = setup(api)
    project, assembly = saved['order']['project_id'], saved['assemblies'][0]
    removed = assembly['spools'][0]
    change(api, 'spool_line', removed['id'])
    current = detail(api, project)
    body = edit_body(current, spools=[{
        key: line[key] for key in ('spool_number', 'quantity_per_assembly', 'welds_per_spool')
    } for line in assembly['spools']])
    before = database_state(api)
    response = api.patch(f'/api/order-setup/{project}/assemblies/{assembly["gpn_id"]}', body)
    assert response.status_code == 409 and 'restor' in response.text.lower(), response.text
    assert database_state(api) == before

    # Editing the still-active scope is allowed and must leave the removed line alone.
    corrected = ok(api.patch(f'/api/order-setup/{project}/assemblies/{assembly["gpn_id"]}',
        edit_body(current, assembly_quantity=2)))
    assert len(corrected['assemblies'][0]['spools']) == 1
    models = importlib.import_module('order_setup')
    with api.session_factory() as session:
        assert not session.get(models.OrderSpoolRequirement, removed['id']).active


def test_last_saved_spool_line_requires_removing_its_assembly_instead(api):
    saved = setup(api, spools=[{'spool_number': 'ONLY-SPOOL', 'quantity_per_assembly': 1}])
    line = saved['assemblies'][0]['spools'][0]
    reviewed = preview(api, line['id'])
    assert not reviewed['can_proceed']
    assert any('last' in message.lower() and 'assembly' in message.lower() for message in reviewed['blockers'])
    rejected_change(api, line['id'], reviewed)


@pytest.mark.parametrize('removed_mapping', [False, True])
def test_any_physical_assembly_history_blocks_saved_line_removal(api, removed_mapping):
    saved = setup(api)
    line = saved['assemblies'][0]['spools'][0]
    item_id = _physical_assembly(api, saved, 'SPOOL-LINE-HISTORY')
    if removed_mapping:
        change(api, 'item', item_id)
    reviewed = preview(api, line['id'])
    assert not reviewed['can_proceed']
    assert any('physical' in message.lower() for message in reviewed['blockers'])
    rejected_change(api, line['id'], reviewed)


@pytest.mark.parametrize('removed_mapping', [False, True])
def test_restore_is_blocked_if_physical_scope_was_registered_after_removal(api, removed_mapping):
    saved = setup(api)
    project, line = saved['order']['project_id'], saved['assemblies'][0]['spools'][0]
    change(api, 'spool_line', line['id'])
    item_id = _physical_assembly(api, detail(api, project), 'SPOOL-LINE-AFTER-REMOVE')
    if removed_mapping:
        change(api, 'item', item_id)
    reviewed = preview(api, line['id'], 'restore')
    assert not reviewed['can_proceed']
    assert any('physical' in message.lower() for message in reviewed['blockers'])
    rejected_change(api, line['id'], reviewed, 'restore')
    orders = importlib.import_module('orders')
    with api.session_factory() as session:
        assert session.get(orders.OrderAssembly, item_id).required_spools == 1


@pytest.mark.parametrize('change_kind', ['quantity', 'document', 'registration'])
def test_saved_line_removal_preview_becomes_stale_when_linked_data_changes(api, change_kind):
    saved = setup(api)
    project, assembly = saved['order']['project_id'], saved['assemblies'][0]
    line = assembly['spools'][0]
    reviewed = preview(api, line['id'])
    assert reviewed['can_proceed']
    if change_kind == 'quantity':
        ok(api.patch(f'/api/order-setup/{project}/assemblies/{assembly["gpn_id"]}',
            edit_body(saved, assembly_quantity=2)))
    elif change_kind == 'document':
        ok(request_upload(api, '/api/spool-documents/requirements/' + line['id'], files=[
            ('New-BOM.csv', bom_csv(line['spool_number']), 'text/csv')]))
    else:
        _physical_assembly(api, saved, 'SPOOL-LINE-STALE-PREVIEW')
    rejected_change(api, line['id'], reviewed)


@pytest.mark.parametrize('parent_kind', ['gpn', 'order'])
def test_parent_restore_does_not_revive_independently_removed_spool_line(api, parent_kind):
    saved = setup(api)
    project, assembly = saved['order']['project_id'], saved['assemblies'][0]
    line = assembly['spools'][0]
    change(api, 'spool_line', line['id'])
    parent_id = project if parent_kind == 'order' else assembly['gpn_id']
    change(api, parent_kind, parent_id)
    reviewed = preview(api, line['id'], 'restore')
    assert not reviewed['can_proceed']
    rejected_change(api, line['id'], reviewed, 'restore')
    change(api, parent_kind, parent_id, 'restore')
    current = detail(api, project)
    assert [row['id'] for row in current['assemblies'][0]['spools']] == [assembly['spools'][1]['id']]
    assert any(row['kind'] == 'spool_line' and row['record_id'] == line['id']
               for row in ok(api.get(ROOT))['records'])
    change(api, 'spool_line', line['id'], 'restore')
    assert detail(api, project)['totals'] == saved['totals']


@pytest.mark.parametrize('role,status', [(None, 401), ('supervisor', 403), ('inspector', 403)])
def test_saved_line_removal_and_restore_require_existing_admin_permission(api, role, status):
    line = setup(api)['assemblies'][0]['spools'][0]
    reviewed = preview(api, line['id'])
    before = database_state(api)
    assert api.get(f'{ROOT}/spool_line/{line["id"]}', role=role).status_code == status
    assert api.post(f'{ROOT}/spool_line/{line["id"]}/remove', change_body(reviewed), role=role).status_code == status
    assert database_state(api) == before
    change(api, 'spool_line', line['id'])
    reviewed = preview(api, line['id'], 'restore')
    before = database_state(api)
    assert api.post(f'{ROOT}/spool_line/{line["id"]}/restore', change_body(reviewed), role=role).status_code == status
    assert database_state(api) == before


def test_restore_cannot_overfill_the_current_planned_spool_limit(api):
    saved = setup(api)
    project, assembly = saved['order']['project_id'], saved['assemblies'][0]
    line = assembly['spools'][0]
    change(api, 'spool_line', line['id'])
    current = detail(api, project)
    remaining = current['assemblies'][0]['spools'][0]
    ok(api.patch(f'/api/order-setup/{project}/assemblies/{assembly["gpn_id"]}',
        edit_body(current, spools=[{'spool_number': remaining['spool_number'],
            'quantity_per_assembly': 10000, 'welds_per_spool': remaining['welds_per_spool']}])))
    reviewed = preview(api, line['id'], 'restore')
    assert not reviewed['can_proceed']
    rejected_change(api, line['id'], reviewed, 'restore')


def test_restore_cannot_exceed_the_200_spool_definition_limit(api):
    saved = setup(api, spools=[{'spool_number': f'SPOOL-{index:03d}',
        'quantity_per_assembly': 1} for index in range(200)])
    project, assembly = saved['order']['project_id'], saved['assemblies'][0]
    removed = assembly['spools'][0]
    change(api, 'spool_line', removed['id'])
    current = detail(api, project)
    body = edit_body(current)
    body['spools'].append({'spool_number': 'SPOOL-NEW', 'quantity_per_assembly': 1})
    corrected = ok(api.patch(f'/api/order-setup/{project}/assemblies/{assembly["gpn_id"]}', body))
    assert len(corrected['assemblies'][0]['spools']) == 200
    reviewed = preview(api, removed['id'], 'restore')
    assert not reviewed['can_proceed'], 'Restoration must preserve the same saved-scope limits as editing'
    rejected_change(api, removed['id'], reviewed, 'restore')
