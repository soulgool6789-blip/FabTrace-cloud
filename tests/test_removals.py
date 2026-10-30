"""Reversible removal preserves traceability and confirms one current scope."""
import importlib
import json

import pytest
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import ok
from test_flow import create_item, enroll
from test_orders import add_assembly, current, group, new_order, plan, setup, version
from test_parts import allocate, line, plan as parts_plan, removal_body as allocation_removal_body
from test_progress import database_state
from test_production_process import change as process_change

ROOT = '/api/removals'


def preview(api, kind, record_id, action='remove'):
    return ok(api.get(f'{ROOT}/{kind}/{record_id}', params={'action': action}))


def body(record, **values):
    return {'expected_version': record['expected_version'], 'preview_token': record['preview_token'],
            'confirmation': record['confirmation'], 'reason': 'Correct a synthetic mistaken record while retaining its history', **values}


def change(api, kind, record_id, action='remove'):
    record = preview(api, kind, record_id, action)
    assert record['can_proceed'], record
    return ok(api.post(f'{ROOT}/{kind}/{record_id}/{action}', body(record)))


def stable_business_state(api):
    with api.session_factory() as session:
        rows = {}
        for table in api.application.Base.metadata.sorted_tables:
            if table.name in ('audit_events', 'record_removals'):
                continue
            values = [dict(row) for row in session.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
            if table.name == 'purchase_orders':
                for row in values:
                    row.pop('version')
                    row.pop('updated_at')
            rows[table.name] = values
    return json.dumps(rows, sort_keys=True, default=str)


def test_remove_and_restore_empty_po_with_draft_gpns_retains_original_identity(api):
    project_id = new_order(api)['order']['project_id']
    first, second = group(api, project_id, 'FIRST'), group(api, project_id, 'SECOND')
    before = stable_business_state(api)
    prior_version = version(api, project_id)
    record = preview(api, 'order', project_id)
    assert record['title'] == 'P.O. PO-100' and record['confirmation'] == 'PO-100'
    assert record['counts'] == {'orders': 1, 'gpns': 2, 'items': 0}
    assert record['expected_version'] == 0 and len(record['preview_token']) == 64
    removed = ok(api.post(f'{ROOT}/order/{project_id}/remove', body(record)))
    assert removed['removed'] and removed['affected_count'] == 3
    listed = ok(api.get(ROOT))['records']
    assert len(listed) == 1 and listed[0]['record_id'] == project_id
    assert listed[0]['counts'] == record['counts'] and listed[0]['actor'] == BADGES['admin']
    assert stable_business_state(api) == before
    assert version(api, project_id) == prior_version + 1
    restored = change(api, 'order', project_id, 'restore')
    assert not restored['removed'] and restored['affected_count'] == 3
    assert ok(api.get(ROOT))['records'] == []
    assert {g['id'] for g in current(api, project_id)['gpns']} == {first, second}
    assert version(api, project_id) == prior_version + 2
    assert stable_business_state(api) == before


def test_item_removal_preserves_work_inspection_and_qr_identity(api):
    item_id = api.item('REMOVE-LEGACY-PART', welds_required=1)['id']
    ok(api.post(f'/api/items/{item_id}/weld', {'count': 1, 'weld_ids': 'W01', 'notes': 'Retained synthetic completed weld'}, role='welder'))
    ok(api.post(f'/api/items/{item_id}/inspect', {'kind': 'Dimensional', 'result': 'Pass',
        'report': 'SYNTHETIC-REMOVAL-INSPECTION', 'measurements': 'Retain this actual recorded test observation'}, role='inspector'))
    before = stable_business_state(api)
    result = change(api, 'item', item_id)
    assert result['affected_count'] == 1
    assert stable_business_state(api) == before
    detail = ok(api.get('/api/items/' + item_id))
    assert detail['id'] == item_id and detail['welds_done'] == 1 and not detail['released']
    assert detail['removal']['removed']
    with api.session_factory() as session:
        assert session.get(api.application.Item, item_id) is not None
        assert session.scalars(select(api.application.Inspection).where(api.application.Inspection.item_id == item_id)).all()
        events = session.scalars(select(api.application.Audit).where(api.application.Audit.item_id == item_id)).all()
        assert [row.event for row in events].count('RECORD_REMOVED') == 1
    change(api, 'item', item_id, 'restore')
    assert stable_business_state(api) == before
    assert not ok(api.get('/api/items/' + item_id))['removal']['removed']


def test_branch_removal_preserves_spool_links_and_required_bom_quantities(api):
    project_id, gpn_id, _ = setup(api, count=1)
    spool_id = create_item(api, 'REMOVE-CHILD-SPOOL', kind='Spool', project=project_id)
    ok(plan(api, spool_id, project_id, 'ORDER-ASM-01'))
    component = create_item(api, 'REMOVE-CHILD-COMPONENT', project=project_id)
    configured = parts_plan(api, spool_id, [line(qty=2)])
    allocate(api, spool_id, configured['lines'][0]['id'], [component])
    before = stable_business_state(api)
    record = preview(api, 'gpn', gpn_id)
    assert record['counts'] == {'orders': 0, 'gpns': 1, 'items': 3}
    change(api, 'gpn', gpn_id)
    assert stable_business_state(api) == before
    states = importlib.import_module('removals')
    with api.session_factory() as session:
        assert all(states.item_is_removed(session, value) for value in ('ORDER-ASM-01', spool_id, component))
        assert session.get(api.application.OrderAssembly, 'ORDER-ASM-01').required_spools == 1
        assert session.get(api.application.SpoolPlan, spool_id).assembly_id == 'ORDER-ASM-01'
    change(api, 'gpn', gpn_id, 'restore')
    assert stable_business_state(api) == before
    restored = current(api, project_id)['assemblies'][0]
    assert restored['required_spools'] == restored['linked_spools'] == 1
    assert restored['ready_spools'] == 0
    assert ok(api.get('/api/parts/spools/' + spool_id))['totals']['required_qty'] == 2


def test_restoring_po_does_not_revive_an_earlier_independently_removed_branch(api):
    project_id, first, _ = setup(api)
    second = group(api, project_id, 'SECOND-GPN')
    add_assembly(api, project_id, second, item_id='SECOND-ASSEMBLY')
    change(api, 'gpn', first)
    record = preview(api, 'order', project_id)
    assert record['counts'] == {'orders': 1, 'gpns': 1, 'items': 1}
    change(api, 'order', project_id)
    blocked = preview(api, 'gpn', first, 'restore')
    assert not blocked['can_proceed'] and any('parent P.O.' in row for row in blocked['blockers'])
    before = database_state(api)
    response = api.post(f'{ROOT}/gpn/{first}/restore', body(blocked))
    assert response.status_code == 409 and database_state(api) == before
    change(api, 'order', project_id, 'restore')
    listed = ok(api.get(ROOT))['records']
    assert len(listed) == 1 and listed[0]['record_id'] == first
    assert [row['item_id'] for row in current(api, project_id)['assemblies']] == ['SECOND-ASSEMBLY']
    change(api, 'gpn', first, 'restore')
    assert len(current(api, project_id)['assemblies']) == 2


def test_last_mapped_assembly_item_removal_also_hides_its_gpn(api):
    project_id, gpn_id, _ = setup(api)
    record = preview(api, 'item', 'ORDER-ASM-01')
    assert record['counts'] == {'orders': 0, 'gpns': 1, 'items': 1}
    change(api, 'item', 'ORDER-ASM-01')
    assert current(api, project_id)['gpns'] == []
    assert current(api, project_id)['totals']['setup_needed_count'] == 0
    nested = preview(api, 'gpn', gpn_id, 'restore')
    assert not nested['can_proceed'] and 'Restore that entry' in nested['blockers'][0]
    change(api, 'item', 'ORDER-ASM-01', 'restore')
    assert current(api, project_id)['gpns'][0]['id'] == gpn_id


def test_one_of_multiple_physical_assemblies_keeps_shared_gpn_active(api):
    project_id, gpn_id, _ = setup(api)
    add_assembly(api, project_id, gpn_id, item_id='SIBLING-ASSEMBLY')
    assert preview(api, 'item', 'ORDER-ASM-01')['counts'] == {'orders': 0, 'gpns': 0, 'items': 1}
    change(api, 'item', 'ORDER-ASM-01')
    assert current(api, project_id)['gpns'][0]['id'] == gpn_id
    assert [row['item_id'] for row in current(api, project_id)['assemblies']] == ['SIBLING-ASSEMBLY']
    change(api, 'item', 'ORDER-ASM-01', 'restore')
    assert len(current(api, project_id)['assemblies']) == 2


@pytest.mark.parametrize('role,code', [(role, 403) for role in BADGES if role != 'admin'] + [(None, 401)])
def test_only_admin_can_list_preview_remove_or_restore(api, role, code):
    item_id = api.item('REMOVE-PERMISSIONS')['id']
    record = preview(api, 'item', item_id)
    before = database_state(api)
    for response in (api.get(ROOT, role=role), api.get(f'{ROOT}/item/{item_id}', role=role),
            api.post(f'{ROOT}/item/{item_id}/remove', body(record), role=role),
            api.post(f'{ROOT}/item/{item_id}/restore', body(record), role=role)):
        assert response.status_code == code, response.text
    assert database_state(api) == before


def test_wrong_confirmation_missing_reason_and_stale_state_have_no_side_effects(api):
    item_id = api.item('REMOVE-CONFIRM')['id']
    record = preview(api, 'item', item_id)
    for changes in ({'confirmation': 'WRONG'}, {'reason': 'x'}, {'reason': '    '},
                    {'expected_version': True}, {'expected_version': 3}, {'preview_token': '0' * 64}):
        before = database_state(api)
        response = api.post(f'{ROOT}/item/{item_id}/remove', body(record, **changes))
        assert response.status_code in (409, 422), response.text
        assert database_state(api) == before
    change(api, 'item', item_id)
    before = database_state(api)
    response = api.post(f'{ROOT}/item/{item_id}/remove', body(record))
    assert response.status_code == 409 and database_state(api) == before
    restored_preview = preview(api, 'item', item_id, 'restore')
    change(api, 'item', item_id, 'restore')
    before = database_state(api)
    response = api.post(f'{ROOT}/item/{item_id}/restore', body(restored_preview))
    assert response.status_code == 409 and database_state(api) == before


@pytest.mark.parametrize('change_kind', ['child', 'number', 'order'])
def test_scope_change_requires_fresh_confirmation(api, change_kind):
    project_id, _, _ = setup(api)
    record = preview(api, 'order', project_id)
    if change_kind == 'child':
        create_item(api, 'REMOVE-LATE-CHILD', project=project_id)
    elif change_kind == 'number':
        ok(api.patch('/api/items/ORDER-ASM-01/part-number', {'google_part_number': 'CORRECTED-NUMBER'}))
    else:
        ok(api.patch('/api/orders/' + project_id, {'expected_version': version(api, project_id),
            'purchase_order': 'PO-CORRECTED', 'notes': '', 'reason': 'Synthetic correction before removal'}))
    before = database_state(api)
    response = api.post(f'{ROOT}/order/{project_id}/remove', body(record))
    assert response.status_code == 409 and 'changed' in response.text
    assert database_state(api) == before


def test_linked_spool_must_be_unassigned_or_removed_with_parent(api):
    project_id, _, _ = setup(api, count=1)
    spool_id = create_item(api, 'REMOVE-LINKED-SPOOL', kind='Spool', project=project_id)
    ok(plan(api, spool_id, project_id, 'ORDER-ASM-01'))
    record = preview(api, 'item', spool_id)
    assert not record['can_proceed'] and any('linked to ORDER-ASM-01' in row for row in record['blockers'])
    before = database_state(api)
    response = api.post(f'{ROOT}/item/{spool_id}/remove', body(record))
    assert response.status_code == 409 and database_state(api) == before
    ok(plan(api, spool_id, project_id, None))
    change(api, 'item', spool_id)
    assembly = current(api, project_id)['assemblies'][0]
    assert assembly['required_spools'] == assembly['missing_spools'] == 1
    assert assembly['ready_spools'] == assembly['linked_spools'] == 0


def test_allocated_part_requires_guarded_unassignment_before_individual_removal(api):
    spool_id = create_item(api, 'REMOVE-ALLOC-SPOOL', kind='Spool')
    component = create_item(api, 'REMOVE-ALLOC-PART')
    configured = parts_plan(api, spool_id, [line(qty=1)])
    allocate(api, spool_id, configured['lines'][0]['id'], [component])
    assert not preview(api, 'item', component)['can_proceed']
    ok(api.post(f'/api/parts/spools/{spool_id}/allocations/{component}/remove', allocation_removal_body(api, spool_id)))
    change(api, 'item', component)
    summary = ok(api.get('/api/parts/spools/' + spool_id))['totals']
    assert summary['required_qty'] == summary['short_qty'] == 1
    assert summary['assigned_qty'] == 0


@pytest.mark.parametrize('paused', [False, True])
def test_open_manual_timers_block_removal_until_finished(api, paused):
    item_id = create_item(api, 'REMOVE-TIMER', kind='Spool')
    started = process_change(api, item_id, 'start', 0, role='admin', process_key='material_prep')
    if paused:
        started = process_change(api, item_id, 'pause', started['version'], role='admin', notes='Synthetic waiting interval')
    record = preview(api, 'item', item_id)
    assert not record['can_proceed'] and any('Finish timer' in row for row in record['blockers'])
    before = database_state(api)
    response = api.post(f'{ROOT}/item/{item_id}/remove', body(record))
    assert response.status_code == 409 and database_state(api) == before
    process_change(api, item_id, 'finish', started['version'], role='admin')
    change(api, 'item', item_id)


def test_numbered_route_timer_blocks_whole_po_without_claiming_completion(api):
    project_id, _, _ = setup(api)
    component = create_item(api, 'REMOVE-FLOW-COMPONENT', project=project_id)
    enroll(api, component, 'component')
    record = preview(api, 'order', project_id)
    assert not record['can_proceed'] and any('numbered-process timer' in row for row in record['blockers'])
    before = database_state(api)
    response = api.post(f'{ROOT}/order/{project_id}/remove', body(record))
    assert response.status_code == 409 and database_state(api) == before


def test_removed_identifiers_remain_reserved(api):
    project_id = new_order(api)['order']['project_id']
    change(api, 'order', project_id)
    before = database_state(api)
    response = api.post('/api/orders', {'expected_version': 0, 'purchase_order': 'PO-100', 'customer': 'Synthetic customer'})
    assert response.status_code == 409 and database_state(api) == before
    item_id = api.item('REMOVE-RESERVED-ID')['id']
    change(api, 'item', item_id)
    before = database_state(api)
    response = api.post('/api/items', {'id': item_id, 'location': 'Receiving', 'handler': BADGES['handler']})
    assert response.status_code == 409 and database_state(api) == before


def test_canonical_plan_membership_wins_over_stale_legacy_project_text(api):
    first = new_order(api)['order']['project_id']
    second = new_order(api, number='PO-SECOND')['order']['project_id']
    item_id = create_item(api, 'REMOVE-CANONICAL', kind='Spool', project=first)
    with api.session_factory() as session:
        session.get(api.application.Item, item_id).project = second
        session.commit()
    assert preview(api, 'order', second)['counts']['items'] == 0
    assert preview(api, 'order', first)['counts']['items'] == 1


def test_read_previews_and_removed_register_do_not_write(api):
    project_id, gpn_id, _ = setup(api)
    before = database_state(api)
    for kind, identifier in (('order', project_id), ('gpn', gpn_id), ('item', 'ORDER-ASM-01')):
        preview(api, kind, identifier)
        preview(api, kind, identifier, 'restore')
    ok(api.get(ROOT))
    assert database_state(api) == before
    assert api.get(f'{ROOT}/invalid/{project_id}').status_code == 422
    assert api.get(f'{ROOT}/order/NO-SUCH-PO').status_code == 404
