"""P.O. drill-down reports recorded work, physical finish and missing scope.

All fixtures are isolated SQLite records. These reads may neither repair old
scope nor supply missing traveler, QA, custody or quantity evidence.
"""
import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from conftest import BADGES
from tracking_helpers import ok
from test_admin import release as admin_release
from test_flow import (
    PROJECT, advance, assign_component, create_item, detail as flow_detail,
    enroll, inspect_dimensions,
)
from test_orders import add_assembly, group, new_order, plan as weld_plan, setup
from test_parts import allocate, line, plan as parts_plan
from test_progress import database_state
from test_quality import assembly_at_step
from test_removal_orders import change


ROOT = '/api/progress/orders'


def report(api, project_id='', **values):
    return ok(api.get(ROOT, params={'project_id': project_id}, **values))


def flatten(result):
    rows = []

    def visit(node):
        rows.append(node)
        for child in node['children']:
            visit(child)

    for order in result['orders']:
        for gpn in order['gpns']:
            for assembly in gpn['assemblies']:
                visit(assembly)
        for node in order['unassigned']:
            visit(node)
    assert len(rows) == len({row['id'] for row in rows}), 'Physical identities must not repeat'
    return {row['id']: row for row in rows}


def node(api, item_id, project_id=''):
    return flatten(report(api, project_id))[item_id]


def enroll_project_as_order(api, project_id=PROJECT, number='FLOW-PO'):
    return new_order(api, number=number, customer='', existing_project_id=project_id,
                     notes='Existing synthetic project enrolled for progress coverage')


def test_all_roles_read_one_or_all_pos_with_independent_choices_and_no_writes(api):
    first = new_order(api, number='PO-A')['order']['project_id']
    second = new_order(api, number='PO-B')['order']['project_id']
    create_item(api, 'NOT-ENROLLED')
    before = database_state(api)
    assert api.get(ROOT, role=None).status_code == 401
    assert api.get(ROOT, params={'project_id': 'UNKNOWN'}).status_code == 404
    assert api.get(ROOT, params={'project_id': PROJECT}).status_code == 404
    assert api.get(ROOT, params={'project_id': 'a' * 81}).status_code == 422
    for role in BADGES:
        all_orders = report(api, role=role)
        assert [order['project_id'] for order in all_orders['orders']] == [first, second]
        selected = report(api, second, role=role)
        assert selected['selected_project_id'] == second
        assert [order['project_id'] for order in selected['orders']] == [second]
        assert {choice['project_id'] for choice in selected['choices']} == {first, second}
        assert selected['summary']['purchase_orders'] == 1
    assert database_state(api) == before


def test_flow_catalog_matches_requested_stage_order_and_colors(api):
    result = report(api)
    assert [(stage['label'], stage['color']) for stage in result['stage_catalog']] == [
        ('Inventory', 'black'), ('QA/QC-001', 'black'), ('Prep/Fabrication', 'red'),
        ('QA/QC-002', 'red'), ('Floor', 'yellow'), ('Process Welder', 'blue'),
        ('QA/QC-003', 'blue'), ('Testing', 'orange'), ('QA/QC-004', 'orange'),
        ('Paint', 'pink'), ('QA/QC-005', 'pink'), ('Ready To Ship', 'green')]
    assert sorted(number for stage in result['stage_catalog'] for number in stage['steps']) == list(range(1, 25))
    assert result['stage_catalog'] == ok(api.get('/api/flow/catalog'))['stage_catalog']


def test_empty_po_and_draft_gpn_have_unknown_scope_and_no_completion(api):
    project = new_order(api)['order']['project_id']
    empty = report(api, project)
    assert empty['summary']['items'] == 0
    assert empty['summary']['percent'] is None
    assert not empty['summary']['scope_complete'] and not empty['summary']['complete']
    assert {stage['state'] for stage in empty['stages']} == {'scope_unknown'}
    group_id = group(api, project)
    result = report(api, project)
    gpn = result['orders'][0]['gpns'][0]
    assert gpn['id'] == group_id and gpn['setup_needed']
    assert gpn['assemblies'] == [] and gpn['summary']['percent'] is None
    assert gpn['summary']['undeclared_scope'] > 0 and gpn['warnings']
    assert {stage['state'] for stage in gpn['stages']} == {'scope_unknown'}
    assert result['summary']['finished'] == 0


def test_tree_counts_each_identity_once_and_keeps_missing_spools_and_bom_pieces(api):
    project, gpn_id, _ = setup(api, count=2)
    ok(weld_plan(api, 'ORDER-ASM-01', project))
    spool = create_item(api, 'TREE-SPOOL', kind='Spool', project=project)
    ok(weld_plan(api, spool, project, assembly_id='ORDER-ASM-01'))
    part = create_item(api, 'TREE-PART', project=project)
    unassigned = create_item(api, 'TREE-UNASSIGNED', project=project)
    parts = parts_plan(api, spool, [line(qty=3)])
    allocate(api, spool, parts['lines'][0]['id'], [part])
    result = report(api, project)
    rows = flatten(result)
    order = result['orders'][0]
    gpn = order['gpns'][0]
    assembly = gpn['assemblies'][0]
    assert gpn['id'] == gpn_id and not gpn['setup_needed']
    assert assembly['id'] == 'ORDER-ASM-01'
    assert [child['id'] for child in assembly['children']] == [spool]
    assert [child['id'] for child in rows[spool]['children']] == [part]
    assert [item['id'] for item in order['unassigned']] == [unassigned]
    assert order['summary']['items'] == 4
    assert order['summary']['total_steps'] == 6 + 8 + 8 + 8
    assert assembly['summary']['items'] == 3 and assembly['summary']['total_steps'] == 22
    assert gpn['summary']['total_steps'] == 22
    assert rows[part]['summary']['total_steps'] == rows[part]['progress']['total'] == 8
    assert order['summary']['missing_spools'] == 1
    assert order['summary']['missing_parts'] == 2
    assert rows[spool]['parts']['required_qty'] == 3
    assert rows[spool]['parts']['assigned_qty'] == 1
    assert not order['summary']['scope_complete'] and not order['summary']['complete']
    assert assembly['required_spools'] == 2 and assembly['linked_spools'] == 1
    stages = {stage['key']: stage for stage in assembly['stages']}
    assert stages['inventory']['total'] == 1 and stages['inventory']['missing_records'] == 2
    assert stages['qa_001']['total'] == 3 and stages['qa_001']['missing_records'] == 2
    assert stages['preparation']['total'] == 5 and stages['preparation']['missing_records'] == 3
    assert stages['qa_002']['total'] == 1 and stages['qa_002']['missing_records'] == 1
    assert stages['floor']['total'] == 4 and stages['floor']['missing_records'] == 3
    assert stages['testing']['total'] == stages['qa_test_results']['total'] == 1
    assert stages['qa_test_results']['label'] == 'QA/QC-004'
    assert stages['paint']['total'] == 2 and stages['qa_004']['total'] == 1
    assert stages['qa_004']['label'] == 'QA/QC-005'
    assert stages['ready_to_ship']['total'] == 2 and stages['ready_to_ship']['separate']
    assert rows[spool]['blockers'] and not rows[spool]['on_hold']
    assert all(not row['route_started'] for row in rows.values())
    assert rows[part]['location'] == 'Receiving'
    assert rows[part]['handler'] == BADGES['handler'] and rows[part]['handler_name']
    assert next(s for s in rows[part]['stages'] if s['key'] == 'paint')['state'] == 'not_applicable'


def test_shared_legacy_gpn_keeps_distinct_assembly_ids_without_double_counting(api):
    project, gpn_id, _ = setup(api, count=1)
    add_assembly(api, project, gpn_id, item_id='SECOND-ASSEMBLY', count=3)
    result = report(api, project)
    gpn = result['orders'][0]['gpns'][0]
    assert {row['id'] for row in gpn['assemblies']} == {'ORDER-ASM-01', 'SECOND-ASSEMBLY'}
    assert len(flatten(result)) == 2
    assert gpn['summary']['items'] == 2 and gpn['summary']['total_steps'] == 12
    assert result['summary']['total_steps'] == 12 and result['summary']['missing_spools'] == 4


def test_missing_spools_leave_their_unknown_material_stages_visible(api):
    project, _, _ = setup(api, count=2)
    ok(weld_plan(api, 'ORDER-ASM-01', project))
    row = node(api, 'ORDER-ASM-01')
    assert row['summary']['undeclared_scope'] == 0
    assert row['summary']['missing_spools'] == 2
    stages = {stage['key']: stage for stage in row['stages']}
    assert stages['inventory']['state'] == stages['qa_001']['state'] == 'scope_unknown'
    assert stages['inventory']['percent'] is None
    assert stages['preparation']['state'] == 'pending' and stages['preparation']['missing_records'] == 2
    assert stages['qa_002']['state'] == 'pending' and stages['qa_002']['missing_records'] == 2


@pytest.mark.parametrize('incomplete', [
    {'missing_spools': 1}, {'missing_parts': 2}, {'undeclared_scope': 1}, {'wip': 1, 'on_hold': 1},
])
def test_registered_100_percent_is_never_complete_with_missing_scope_or_unfinished_work(api, incomplete):
    module = importlib.import_module('production_progress')
    counts = {key: 0 for key in module.COUNT_KEYS}
    counts.update(items=1, assemblies=1, finished=1, completed_steps=6, total_steps=6, **incomplete)
    result = module._finish_summary(counts)
    assert result['recorded_percent'] == result['percent'] == 100
    assert not result['complete']
    if not incomplete.get('wip'):
        assert not result['scope_complete']


def test_late_baseline_remains_unrecorded_and_qa_finish_is_distinct_from_handoff(api):
    project = new_order(api)['order']['project_id']
    spool = create_item(api, 'BASELINE-SPOOL', kind='Spool', project=project)
    assert next(s for s in node(api, spool)['stages'] if s['key'] == 'inventory')['state'] == 'scope_unknown'
    enroll(api, spool, 'spool', start_step=14)
    before = node(api, spool, project)
    assert before['progress'] == {'completed': 0, 'total': 8, 'not_recorded': 5, 'percent': 0}
    assert [step['state'] for step in before['steps']] == ['not_recorded'] * 5 + ['current', 'pending', 'pending']
    assert not before['fabrication_finished'] and not before['on_hold']
    advance(api, spool)
    inspect_dimensions(api, spool)
    advance(api, spool, role='inspector')
    after_qa = node(api, spool, project)
    assert after_qa['fabrication_finished'] and after_qa['current_step'] == 16
    assert after_qa['progress']['percent'] == 25
    assert after_qa['steps'][-1]['state'] == 'current'
    advance(api, spool)
    after = node(api, spool, project)
    assert after['progress']['percent'] == 37.5 and after['progress']['not_recorded'] == 5
    assert after['flow_status'] == 'completed' and after['fabrication_finished']
    assert after['parts']['legacy_scope'] and after['parts']['required_qty'] == 0
    assert after['summary']['scope_complete']
    assert next(s for s in after['stages'] if s['key'] == 'inventory')['state'] == 'not_applicable'


def test_assembly_finish_stops_at_22_shipping_and_delivery_are_separate(api):
    ok(api.post('/api/tracking/projects', {'id': PROJECT, 'name': 'Local shipping progress fixture'}), 201)
    enroll_project_as_order(api)
    assembly = assembly_at_step(api, 23)
    before = report(api, PROJECT)
    row = flatten(before)[assembly]
    assert row['fabrication_finished'] and row['progress']['percent'] == 100, row['blockers']
    assert row['progress']['total'] == 6 and row['progress']['completed'] == 6
    assert row['flow_stage']['key'] == 'floor'
    assert row['flow_stage']['color'] == 'yellow'
    children = row['children']
    assert children and all(child['flow_stage']['key'] == 'floor' for child in children)
    assert all(child['flow_stage']['source_item_id'] == assembly and child['flow_stage']['inherited'] for child in children)
    assert all(child['progress']['total'] == 8 for child in children)
    assert len(row['steps']) == 8
    shipping = next(stage for stage in row['stages'] if stage['key'] == 'ready_to_ship')
    assert shipping['current'] == 1 and shipping['completed'] == 0
    assert before['summary']['total_steps'] == 14
    advance(api, assembly, location_id='ready_to_ship')
    advance(api, assembly)
    shipped = report(api, PROJECT)
    assert flatten(shipped)[assembly]['flow_stage']['key'] == 'ready_to_ship'
    assert shipped['summary']['completed_steps'] == before['summary']['completed_steps']
    assert shipped['summary']['recorded_percent'] == before['summary']['recorded_percent']
    assert shipped['summary']['shipped'] == 1 and shipped['summary']['delivered'] == 0
    current = flow_detail(api, assembly)
    ok(api.post(f'/api/flow/items/{assembly}/deliver', {
        'expected_version': current['flow']['version'],
        'receipt_reference': 'SYNTHETIC-PROOF-OF-DELIVERY', 'recipient': 'Synthetic customer receiver',
        'notes': 'Fixture customer receipt',
    }))
    delivered = report(api, PROJECT)
    assert delivered['summary']['delivered'] == 1
    assert delivered['summary']['completed_steps'] == before['summary']['completed_steps']


def test_quality_failure_resets_downstream_steps_and_marks_actual_exception(api):
    assembly = assembly_at_step(api, 22)
    enroll_project_as_order(api)
    assert node(api, assembly)['progress']['completed'] == 5
    current = flow_detail(api, assembly)
    ok(api.post(f'/api/flow/items/{assembly}/fail', {
        'expected_version': current['flow']['version'], 'return_step': 18,
        'reason': 'Synthetic final inspection defect requires assembly rework',
        'reference': 'TREE-NCR-001',
    }, role='inspector'))
    row = node(api, assembly)
    assert row['progress']['completed'] == 1 and row['progress']['percent'] == 16.7
    assert row['current_step'] == 18 and row['steps'][1]['state'] == 'current'
    assert row['flow_stage']['key'] == 'floor' and row['flow_stage']['color'] == 'yellow'
    assert row['flow_stage']['blocked']
    assert all(child['flow_stage']['color'] != 'green' for child in row['children'])
    assert all(step['state'] == 'pending' for step in row['steps'][2:])
    assert row['on_hold'] and row['hold_reasons'] and not row['fabrication_finished']
    assert report(api)['summary']['on_hold'] >= 1


def test_shipping_document_gate_reports_blocker_without_relocating_the_recorded_station(api, monkeypatch):
    from test_quality import workspace, create_requirement
    ok(api.post('/api/tracking/projects', {'id': PROJECT, 'name': 'Local shipping color fixture'}), 201)
    enroll_project_as_order(api)
    assembly = assembly_at_step(api, 23)
    before = node(api, assembly)
    assert before['flow_stage']['key'] == 'floor'
    quality = workspace(api, project_id=PROJECT)['workspace']['id']
    create_requirement(api, quality, gate='shipment')
    module = importlib.import_module('production_progress')
    original, checked = module.flow_stage_for_item, []

    def counted(session, item, **kwargs):
        checked.append(item.id)
        return original(session, item, **kwargs)

    monkeypatch.setattr(module, 'flow_stage_for_item', counted)
    current = node(api, assembly)
    assert checked == [assembly], 'Only the candidate shipping assembly needs extra gate reads'
    assert current['flow_stage']['key'] == 'floor' and current['flow_stage']['blocked']
    assert flow_detail(api, assembly)['flow_stage'] == current['flow_stage']
    assert all(child['flow_stage']['color'] != 'green' for child in current['children'])
    assert current['progress'] == before['progress']


@pytest.mark.parametrize('action', ['fail', 'reopen', 'admin_return_to_work'])
def test_each_return_event_resets_completed_steps_without_resetting_earlier_work(api, action):
    module = importlib.import_module('production_progress')
    flow = SimpleNamespace(baseline_step=9, current_step=14, status='active')
    events = [SimpleNamespace(action='advance', step=step, data={}) for step in range(9, 17)]
    events.append(SimpleNamespace(action=action, step=15, data={'return_step': 14}))
    states = {step['number']: step['state'] for step in module._steps('spool', flow, events)}
    assert [states[step] for step in range(9, 14)] == ['completed'] * 5
    assert states[14] == 'current' and states[15] == states[16] == 'pending'


def test_admin_release_and_numeric_position_do_not_supply_work_evidence(api):
    project = new_order(api)['order']['project_id']
    spool = create_item(api, 'ADMIN-POSITION', kind='Spool', project=project)
    enroll(api, spool, 'spool')
    flow_module = importlib.import_module('flow')
    with api.session_factory() as session:
        session.get(flow_module.FlowPlan, spool).current_step = 16
        session.commit()
    before = node(api, spool)
    assert before['progress']['completed'] == 0
    assert [step['state'] for step in before['steps']] == ['pending'] * 7 + ['current']
    admin_release(api, spool)
    after = node(api, spool)
    assert after['administrative_release']
    assert after['progress']['completed'] == 0 and not after['fabrication_finished']
    assert after['flow_stage']['key'] != 'ready_to_ship' and after['flow_stage']['color'] != 'green'


def test_legacy_part_with_structured_spool_plan_uses_its_actual_scope(api):
    project = new_order(api)['order']['project_id']
    item = create_item(api, 'LEGACY-PART-SPOOL', kind='Part', project=project)
    ok(weld_plan(api, item, project))
    row = node(api, item)
    assert row['item_kind'] == 'Part' and row['route'] == 'spool'
    assert row['progress']['total'] == 8
    assert [step['number'] for step in row['steps']] == list(range(9, 17))
    assert row['summary']['spools'] == 1 and row['summary']['parts'] == 0
    assert not row['route_started'] and not row['fabrication_finished']


def test_scope_uses_canonical_plan_and_component_parent_over_stale_item_labels(api):
    first = new_order(api, number='SCOPE-A')['order']['project_id']
    second = new_order(api, number='SCOPE-B')['order']['project_id']
    spool = create_item(api, 'SCOPE-SPOOL', kind='Spool', project=first)
    part = create_item(api, 'SCOPE-PART', project=first)
    other = create_item(api, 'SCOPE-OTHER', project=second)
    # Model legacy labels before receipt approval. Once MTR/arrival evidence
    # exists its purchase-order identity is protected by the receiving guard.
    enroll(api, part, 'component', start_step=5)
    assign_component(api, part, spool)
    with api.session_factory() as session:
        session.get(api.application.Item, spool).project = second
        session.get(api.application.Item, part).project = second
        session.commit()
    assert set(flatten(report(api, first))) == {spool, part}
    assert set(flatten(report(api, second))) == {other}
    all_orders = report(api)
    assert set(flatten(all_orders)) == {spool, part, other}
    assert all_orders['summary']['items'] == 3


def test_removed_branches_and_orders_stay_out_of_operational_totals(api):
    project, gpn_id, _ = setup(api, count=2)
    create_item(api, 'REMOVED-SPOOL', kind='Spool', project=project)
    ok(weld_plan(api, 'REMOVED-SPOOL', project, assembly_id='ORDER-ASM-01'))
    assert report(api)['summary']['items'] == 2
    change(api, 'gpn', gpn_id)
    removed = report(api, project)
    assert removed['orders'][0]['gpns'] == [] and flatten(removed) == {}
    assert removed['summary']['items'] == 0 and removed['summary']['missing_spools'] == 0
    change(api, 'gpn', gpn_id, 'restore')
    assert len(flatten(report(api, project))) == 2
    change(api, 'order', project)
    assert report(api)['orders'] == report(api)['choices'] == []
    assert api.get(ROOT, params={'project_id': project}).status_code == 404


def test_read_is_pure_calls_physical_projection_once_and_preserves_historical_progress(api, monkeypatch):
    first, _, _ = setup(api)
    second = new_order(api, number='SECOND-PO')['order']['project_id']
    create_item(api, 'READ-ONLY-SPOOL', kind='Spool', project=second)
    before = database_state(api)
    old = ok(api.get(f'/api/progress/projects/{first}'))
    module = importlib.import_module('production_progress')
    original, calls, statements = module.project_rows, [], []

    def counted(session, project_id=None):
        calls.append(project_id)
        return original(session, project_id)

    def inspect_sql(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    monkeypatch.setattr(module, 'project_rows', counted)
    engine = api.session_factory.kw['bind']
    event.listen(engine, 'before_cursor_execute', inspect_sql)
    try:
        assert report(api)['summary']['purchase_orders'] == 2
        assert calls == [None]
    finally:
        event.remove(engine, 'before_cursor_execute', inspect_sql)
    assert not any('FOR UPDATE' in statement.upper() for statement in statements)
    assert not any(statement.lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ', 'CREATE ', 'ALTER ')) for statement in statements)
    assert database_state(api) == before
    after = ok(api.get(f'/api/progress/projects/{first}'))
    assert after['items'] == old['items'] and after['counts'] == old['counts']

