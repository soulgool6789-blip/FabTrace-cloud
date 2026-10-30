"""Removed orders/items stay traceable and cannot re-enter work via older APIs."""
import json

from conftest import BADGES
from tracking_helpers import add_weld, ok
from test_combined_assemblies import combined
from test_dossier import (configure, config_body, issued_fixture, packet, project as packet_project,
                          upload, entry, issue_project)
from test_flow import create_item
from test_orders import new_order, plan as spool_plan
from test_parts import (allocate, allocation_body, detail as parts_detail, line,
                        plan as parts_plan, plan_body, removal_body)
from test_progress import database_state
from test_quality import (workspace, create_requirement, create_evidence, mutate,
                          review as quality_review, requirement_body)
from test_transfers import transfer_body


def change(api, kind, record_id, action='remove'):
    root = f'/api/removals/{kind}/{record_id}'
    preview = ok(api.get(root, params={'action': action}))
    assert preview['can_proceed'], preview['blockers']
    return ok(api.post(root + '/' + action, {
        'expected_version': preview['expected_version'], 'preview_token': preview['preview_token'],
        'confirmation': preview['confirmation'], 'reason': 'Synthetic confirmed removal integration decision',
    }))


def scope(api):
    project_id = new_order(api, number='REMOVE-INTEGRATION-PO')['order']['project_id']
    record = combined(api, project_id)
    assembly_id, gpn_id = record['selected_assembly_id'], record['selected_gpn_id']
    ok(spool_plan(api, assembly_id, project_id))
    spool_id = create_item(api, 'REMOVE-SPOOL', kind='Spool', planned=1, project=project_id)
    ok(spool_plan(api, spool_id, project_id, assembly_id=assembly_id, planned=1))
    weld = add_weld(api, spool_id)
    component_id = create_item(api, 'REMOVE-COMPONENT', project=project_id)
    bom = parts_plan(api, spool_id, [line(2)])
    allocate(api, spool_id, bom['lines'][0]['id'], [component_id])
    return project_id, gpn_id, assembly_id, spool_id, component_id, weld


def no_change(api, response, before):
    assert response.status_code == 409, response.text
    assert 'removed' in response.text.lower(), response.text
    assert database_state(api) == before


def test_order_removal_hides_active_lists_and_keeps_history_scope_and_quantities(api):
    project_id, _, assembly_id, spool_id, component_id, _ = scope(api)
    configure(api, project_id, purchase_order='REMOVE-INTEGRATION-PO', expected_packets=2)
    before_packet = packet(api, spool_id)
    before_project_packet = packet_project(api, project_id)
    before_parts = parts_detail(api, spool_id)
    before = json.loads(database_state(api))
    change(api, 'order', project_id)
    after = json.loads(database_state(api))
    for table, rows in before.items():
        if table not in ('record_removals', 'audit_events', 'purchase_orders'):
            assert after[table] == rows, table
    stable = database_state(api)
    assert ok(api.get('/api/items'))['items'] == []
    assert ok(api.get('/api/admin/items'))['items'] == []
    assert ok(api.get('/api/admin/overview'))['counts']['items'] == 0
    assert ok(api.get('/api/tracking/projects')) == []
    assert ok(api.get('/api/tracking/overview'))['spools'] == []
    assert ok(api.get('/api/flow/items'))['items'] == []
    assert ok(api.get('/api/parts/spools'))['items'] == []
    assert ok(api.get('/api/progress/projects'))['projects'] == []
    assert ok(api.get('/api/dossier/projects'))['projects'] == []
    for item_id in (assembly_id, spool_id, component_id):
        item = ok(api.get('/api/items/' + item_id, role='welder'))
        assert item['removal']['removed'] and not item['permissions']['can_mutate']
        assert not any(item['permissions'].values())
        assert not item['transfer']['can_transfer']
        assert ok(api.get('/api/flow/items/' + item_id))['allowed_actions'] == []
        assert ok(api.get('/api/admin/items/' + item_id))['allowed_actions'] == []
    historical = parts_detail(api, spool_id)
    assert historical['totals'] == before_parts['totals']
    assert not historical['editable'] and not historical['permissions']['can_allocate']
    assert historical['candidates'] == []
    assert historical['lines'][0]['components'][0]['can_remove'] is False
    after_packet = packet(api, spool_id)
    assert after_packet['fingerprint'] == before_packet['fingerprint']
    assert packet_project(api, project_id)['fingerprint'] == before_project_packet['fingerprint']
    assert after_packet['removal']['removed'] and not after_packet['can_mutate']
    assert after_packet['permissions']['editable_check_codes'] == []
    tracked = ok(api.get('/api/tracking/spools/' + spool_id))
    assert not tracked['can_mutate'] and tracked['welds'][0]['allowed_operations'] == []
    assert not any(tracked['welds'][0]['requirements'][0]['permissions'].values())
    assert database_state(api) == stable
    change(api, 'order', project_id, 'restore')
    assert len(ok(api.get('/api/items'))['items']) == 3
    assert parts_detail(api, spool_id)['totals'] == before_parts['totals']
    assert packet(api, spool_id)['fingerprint'] == before_packet['fingerprint']


def test_removed_order_cannot_be_changed_through_legacy_operational_routes(api):
    project_id, _, _, spool_id, component_id, weld = scope(api)
    configure(api, project_id, purchase_order='REMOVE-INTEGRATION-PO', expected_packets=2)
    requirement = weld['requirements'][0]
    parts = parts_detail(api, spool_id)
    part_body = plan_body(api, spool_id, [line(2, id=parts['lines'][0]['id'])])
    unassign_body = removal_body(api, spool_id)
    custody_body = transfer_body(api, spool_id)
    admin = ok(api.get('/api/admin/items/' + spool_id))
    admin_body = {'expected_version': admin['version'], 'reason': 'Synthetic blocked old administrator form',
                  'reference': 'TEST-REMOVED-FORM'}
    change(api, 'order', project_id)
    before = database_state(api)
    requests = [
        ('POST', f'/api/items/{spool_id}/scan', None),
        ('PATCH', f'/api/items/{spool_id}/part-number', {'google_part_number': 'BLOCKED'}),
        ('POST', f'/api/items/{spool_id}/weld', {'count': 1, 'weld_ids': 'W01'}),
        ('POST', f'/api/items/{spool_id}/inspect', {'kind': 'Dimensional', 'result': 'Pass',
            'report': 'TEST-REPORT', 'measurements': 'Synthetic old inspection form'}),
        ('POST', f'/api/items/{spool_id}/release', {'reference': 'TEST-QA-OLD-FORM'}),
        ('POST', f'/api/items/{spool_id}/reopen', None),
        ('POST', f'/api/items/{spool_id}/transfer', custody_body),
        ('POST', f'/api/admin/items/{spool_id}/release', admin_body),
        ('POST', f'/api/admin/items/{spool_id}/custody', {**admin_body,
            'handler': BADGES['handler'], 'location_id': 'welding', 'operational_status': 'queued'}),
        ('POST', f'/api/tracking/welds/{weld["id"]}/work', {'operation': 'root', 'notes': 'Old work form'}),
        ('POST', f'/api/tracking/requirements/{requirement["id"]}/evidence', {
            'expected_version': requirement['version'], 'reference': 'TEST-OLD-EVIDENCE', 'result': 'pass'}),
        ('POST', f'/api/flow/items/{spool_id}/start', {'route': 'spool', 'expected_children': 2}),
        ('POST', f'/api/tracking/spools/{spool_id}/process', {
            'action': 'start', 'process_key': 'fit_up', 'expected_version': 0}),
        ('PUT', f'/api/parts/spools/{spool_id}/plan', part_body),
        ('POST', f'/api/parts/spools/{spool_id}/allocations/{component_id}/remove', unassign_body),
    ]
    for method, path, body in requests:
        no_change(api, api.request(method, path, json=body), before)
    no_change(api, entry(api, spool_id, 'advisements', project_id=project_id), before)
    no_change(api, upload(api, project_id=project_id, item_id=spool_id), before)


def test_new_items_bulk_subprojects_and_plans_cannot_join_removed_po(api):
    project_id = new_order(api, number='REMOVED-EMPTY-PO')['order']['project_id']
    other = create_item(api, 'ACTIVE-OTHER-SPOOL', kind='Spool')
    item_body = {'id': 'BLOCKED-NEW-PART', 'kind': 'Part', 'project': project_id,
                 'location': 'Receiving', 'handler': BADGES['handler'], 'google_part_number': '0001'}
    change(api, 'order', project_id)
    before = database_state(api)
    no_change(api, api.post('/api/items', item_body), before)
    no_change(api, api.post('/api/items/bulk', {'rows': [{**item_body, 'quantity': 1}]}), before)
    no_change(api, api.post('/api/tracking/subprojects', {
        'id': 'BLOCKED-SUB', 'project_id': project_id, 'name': 'Synthetic old project selection'}), before)
    no_change(api, spool_plan(api, other, project_id), before)


def test_removed_assembly_cannot_accept_a_new_spool_from_active_same_po(api):
    project_id = new_order(api, number='ACTIVE-PARENT-PO')['order']['project_id']
    created = combined(api, project_id)
    assembly_id = created['selected_assembly_id']
    child = create_item(api, 'UNLINKED-ACTIVE-SPOOL', kind='Spool', project=project_id)
    change(api, 'item', assembly_id)
    before = database_state(api)
    no_change(api, spool_plan(api, child, project_id, assembly_id=assembly_id), before)
    assert ok(api.get('/api/items/' + child))['can_mutate']


def test_removed_component_is_absent_from_candidates_and_cannot_be_allocated(api):
    project_id = new_order(api, number='ACTIVE-BOM-PO')['order']['project_id']
    spool_id = create_item(api, 'ACTIVE-BOM-SPOOL', kind='Spool', project=project_id)
    component_id = create_item(api, 'REMOVED-LOOSE-PART', project=project_id)
    bom = parts_plan(api, spool_id, [line()])
    body = allocation_body(api, spool_id, bom['lines'][0]['id'], [component_id])
    change(api, 'item', component_id)
    before = database_state(api)
    assert parts_detail(api, spool_id)['candidates'] == []
    no_change(api, api.post(f'/api/parts/spools/{spool_id}/allocations', body), before)
    assert parts_detail(api, spool_id)['totals']['required_qty'] == 1
    assert parts_detail(api, spool_id)['totals']['assigned_qty'] == 0


def test_project_audit_freezes_and_global_audit_cannot_add_or_review_removed_item_evidence(api):
    project_id = new_order(api, number='QUALITY-REMOVE-PO')['order']['project_id']
    item_id = create_item(api, 'AUDIT-REMOVED-SPOOL', kind='Spool', project=project_id)
    scoped = workspace(api, project_id=project_id)['workspace']['id']
    global_id = workspace(api)['workspace']['id']
    req = create_requirement(api, global_id)
    evidence_id = create_evidence(api, global_id, req, item_id=item_id)
    change(api, 'order', project_id)
    before = database_state(api)
    assert {row['id'] for row in ok(api.get('/api/quality/workspaces'))['workspaces']} == {global_id}
    historical = ok(api.get(f'/api/quality/workspaces/{scoped}'))
    assert historical['removal']['removed'] and not historical['can_mutate']
    assert not any(historical['permissions'].values())
    no_change(api, mutate(api, scoped, 'requirements', requirement_body()), before)
    no_change(api, quality_review(api, global_id, 'evidence', evidence_id, 'accepted'), before)
    no_change(api, mutate(api, global_id, 'evidence', {
        'requirement_id': req, 'type': 'other', 'title': 'Blocked evidence', 'reference': 'TEST-OLD-FORM',
        'occurred_on': '2026-01-15', 'item_id': item_id,
        'data': {'scope': 'Removed physical record', 'result': 'pass'},
    }), before)


def test_removal_retains_issued_packet_fingerprints_print_and_download_bytes(api):
    item_id = 'REMOVED-ISSUED-SPOOL'
    issue = issued_fixture(api, item_id)
    path = f'/api/dossier/issues/{issue["id"]}'
    snapshot, printed, archive = ok(api.get(path)), api.get(path + '/print').content, api.get(path + '/download').content
    live_before = packet(api, item_id)
    change(api, 'item', item_id)
    before = database_state(api)
    assert ok(api.get(path)) == snapshot
    assert api.get(path + '/print').content == printed
    assert api.get(path + '/download').content == archive
    assert packet(api, item_id)['fingerprint'] == live_before['fingerprint']
    assert packet(api, item_id)['latest_issue']['current'] == live_before['latest_issue']['current']
    assert database_state(api) == before
    change(api, 'item', item_id, 'restore')
    assert packet(api, item_id)['fingerprint'] == live_before['fingerprint']


def test_removed_member_shows_project_issue_and_handover_blocker_without_changing_evidence_basis(api):
    project_id = 'REMOVE-DOSSIER-ACTIVE-PO'
    item_id = 'REMOVED-PACKET-MEMBER'
    issued_fixture(api, item_id, project_id=project_id)
    new_order(api, number='TEST-PO-JOB-PACKET', customer='', existing_project_id=project_id,
              notes='Synthetic confirmed enrollment of the existing completed packet project')
    assert issue_project(api, project_id).status_code == 201
    before = packet_project(api, project_id)
    assert before['completion_blockers'] == [] and before['permissions']['can_handover']
    issue_id = before['latest_issue']['id']
    retained = ok(api.get(f'/api/dossier/issues/{issue_id}'))
    change(api, 'item', item_id)
    after = packet_project(api, project_id)
    assert after['can_mutate'] and not (after['removal'] or {}).get('removed')
    assert any(item_id in text and 'Removed records' in text for text in after['completion_blockers'])
    # Existing dispatch receipts remain recordable on this active P.O.; the
    # display blocker is used for new issue/dispatch controls only.
    assert after['permissions']['can_handover']
    assert after['fingerprint'] == before['fingerprint']
    assert after['latest_issue'] == before['latest_issue']
    assert ok(api.get(f'/api/dossier/issues/{issue_id}')) == retained
    change(api, 'item', item_id, 'restore')
    restored = packet_project(api, project_id)
    assert restored['completion_blockers'] == [] and restored['permissions']['can_handover']
    assert restored['fingerprint'] == before['fingerprint']
