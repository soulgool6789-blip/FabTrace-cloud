"""Current traveler responsibilities remain a read-only, position-aware view."""

from copy import deepcopy
import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from conftest import BADGES
from employee_work import work_projection
from test_flow import PROJECT, create_item, enroll
from test_progress import database_state
from tracking_helpers import ok


def projection(flow, *, role='handler', badge=None, handler=None, step=10,
               route='spool', status='active', phase=None, started=False,
               testing=None, legacy=False, active=True):
    plan = SimpleNamespace(route=route, status=status, current_step=step,
                           catalog_version=None if legacy else flow.VERSION)
    current = flow.step_definition(plan, step) if step is not None else None
    if phase:
        from flow_testing import phase_definition
        current = phase_definition(SimpleNamespace(phase=phase, cycle=2, attempt=3,
            test_started_at='recorded' if started else None), current)
    user = SimpleNamespace(role=role, badge=badge or BADGES[role])
    item = SimpleNamespace(handler=handler or BADGES['handler'])
    before = deepcopy(current)
    result = work_projection(item, plan, user, current,
        display_step=flow.chart_step_number(step, flow.catalog_version(plan), phase),
        testing=testing, handoff_roles=flow.HANDOFF, active=active)
    assert current == before, 'A work projection must not change saved/catalog checklist meanings'
    return result


def test_current_spool_and_component_roles_do_not_turn_custody_into_assignment(application):
    flow = importlib.import_module('flow')
    for role in ('fitup_welder', 'welder', 'admin'):
        work = projection(flow, role=role)
        assert work['pending'] and work['for_position'] and work['can_record']
        assert not work['in_custody'] and work['required_employee_badge'] is None
        assert work['current_checks'] == flow.STEP_BY_NUMBER[10]['checks']
    custodian = projection(flow, role='handler')
    assert custodian['in_custody'] and not custodian['for_position'] and not custodian['can_record']
    assert not projection(flow, role='process_welder')['for_position']
    assert projection(flow, role='process_welder', step=14)['for_position']
    assert not projection(flow, role='fitup_welder', step=14)['for_position']
    prep = projection(flow, role='finisher', route='component', step=7)
    assert prep['for_position'] and prep['title'] == 'Prep Components'
    assert not projection(flow, role='handler', route='component', step=7)['for_position']


@pytest.mark.parametrize('phase,role,display', [
    ('ndt', 'ndt', 18), ('pressure_test', 'pressure_testing_technician', 21),
])
def test_actual_testing_phase_and_exact_report_employee(application, phase, role, display):
    flow = importlib.import_module('flow')
    values = dict(route='assembly', step=17, phase=phase, role=role, handler=BADGES[role])
    receive = projection(flow, **values)
    assert receive['for_position'] and receive['can_record']
    assert receive['display_step'] == display and receive['required_employee_badge'] is None
    testing = {'test_started_by': BADGES[role]}
    owner = projection(flow, **values, started=True, testing=testing)
    coworker = projection(flow, **values, started=True, testing=testing, badge='OTHER-TESTER')
    assert owner['required_employee_badge'] == BADGES[role] and owner['can_record']
    assert coworker['for_position'] and not coworker['can_record'] and not coworker['in_custody']
    assert BADGES[role] in coworker['restriction']
    assert any('PASS or FAIL' in requirement for requirement in owner['requirements'])
    wrong_custody = projection(flow, **{**values, 'handler': BADGES['handler']}, started=True, testing=testing)
    assert not wrong_custody['can_record'] and 'custody' in wrong_custody['restriction']
    override = projection(flow, **{**values, 'role': 'admin'}, started=True, testing=testing)
    assert override['can_record'] and override['required_employee_badge'] == BADGES[role]


def test_corrections_and_qa_use_their_real_position_and_recorded_actor(application):
    flow = importlib.import_module('flow')
    testing = {'test_started_by': BADGES['ndt'],
               'return_to': {'sender_badge': BADGES['pressure_testing_technician']}}
    values = dict(route='assembly', step=17, phase='pressure_rework', role='pressure_testing_technician',
                  handler=BADGES['pressure_testing_technician'], testing=testing)
    own = projection(flow, **values)
    assert own['required_employee_badge'] == BADGES['pressure_testing_technician']
    assert own['can_record'] and any('corrective work' in row for row in own['requirements'])
    assert not projection(flow, **values, badge='OTHER-PRESSURE-TESTER')['can_record']
    assert not projection(flow, **{**values, 'testing': {}})['can_record']
    qa = projection(flow, route='assembly', step=18, phase='pressure_qa', role='inspector')
    assert qa['can_record'] and qa['required_employee_badge'] is None
    assert qa['display_step'] == 22 and 'QA/QC-005' in qa['title']
    assert not projection(flow, route='assembly', step=18, phase='pressure_qa', role='pressure_testing_technician')['for_position']


def test_legacy_numbers_no_testing_completed_routes_and_delivery_receipts(application):
    flow = importlib.import_module('flow')
    legacy = projection(flow, route='assembly', step=22, legacy=True, role='inspector')
    current = projection(flow, route='assembly', step=22, role='inspector')
    assert legacy['display_step'] == 22 and 'QA/QC-005' in legacy['title']
    assert current['display_step'] == 26 and 'QA/QC-006' in current['title']
    after_no = projection(flow, route='assembly', step=20, role='ndt', testing={'phase':'not_required','decision':'NO'})
    assert after_no['pending'] and not after_no['for_position']
    assert not any('PASS or FAIL' in row for row in after_no['requirements'])
    for status, route in (('completed','spool'), ('completed','component'), ('delivered','assembly')):
        finished = projection(flow, route=route, step=None, status=status)
        assert not finished['pending'] and not finished['can_record']
        assert finished['current_checks'] == finished['requirements'] == []
        assert finished['responsible_roles'] == [] and finished['title'] == ''
    for role in ('handler','supervisor','admin'):
        receipt = projection(flow, route='assembly', step=None, status='shipped', role=role)
        assert receipt['pending'] and receipt['for_position'] and receipt['can_record']
        assert receipt['display_step'] is None and receipt['current_checks'] == []
        assert any('recipient' in row for row in receipt['requirements'])
    assert not projection(flow, route='assembly', step=None, status='shipped', role='painter')['can_record']
    assert not projection(flow, role='fitup_welder', active=False)['pending']
    assert work_projection(SimpleNamespace(handler='A'), None, None) is None


def test_list_and_detail_are_personalized_once_without_writing_or_creating_testing(api):
    flow = importlib.import_module('flow')
    tracking = importlib.import_module('tracking')
    orders = importlib.import_module('orders')
    component = create_item(api, 'WORK-COMPONENT')
    spool = create_item(api, 'WORK-SPOOL', kind='Spool')
    assembly = create_item(api, 'WORK-ASSEMBLY', kind='Assembly')
    # Explicit local fixture relationships; the reads below must never create
    # a relationship, testing state, task assignment, or completion event.
    with api.session_factory() as session:
        session.get(tracking.SpoolPlan, spool).assembly_id = assembly
        session.add(flow.ComponentLink(component_id=component, spool_id=spool, assigned_by=BADGES['admin']))
        session.add(orders.PurchaseOrder(project_id=PROJECT, purchase_order='PO-WORK-17',
            normalized_number='PO-WORK-17', created_by=BADGES['admin']))
        session.flush()
        session.add(orders.OrderGpn(id='WORK-GROUP', project_id=PROJECT, gpn='GPN-KEEP-SEPARATE',
            normalized_gpn='GPN-KEEP-SEPARATE', assembly_number='ASSEMBLY-SHOP-42',
            normalized_assembly_number='ASSEMBLY-SHOP-42', created_by=BADGES['admin']))
        session.flush()
        session.add(orders.OrderAssembly(item_id=assembly, gpn_id='WORK-GROUP',
            assembly_part_number='GPN-KEEP-SEPARATE', required_spools=1, created_by=BADGES['admin']))
        session.commit()
    enroll(api, component, 'component', start_step=7)
    enroll(api, spool, 'spool', start_step=10, expected_children=1)
    enroll(api, assembly, 'assembly', expected_children=1)
    with api.session_factory() as session:
        assert session.get(flow.FlowTestingState, assembly) is None
    before = database_state(api)
    statements = []
    engine = api.session_factory.kw['bind']
    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement.upper().lstrip())
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        assert api.get('/api/flow/items', role=None).status_code == 401
        first = ok(api.get('/api/flow/items', role='fitup_welder'))['items']
        second = ok(api.get('/api/flow/items', role='handler'))['items']
        prep = ok(api.get('/api/flow/items', role='finisher'))['items']
        record = ok(api.get('/api/flow/items/' + assembly, role='handler'))
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert not any(sql.startswith(('INSERT ', 'UPDATE ', 'DELETE ', 'LOCK '))
        or 'FOR UPDATE' in sql or 'PG_ADVISORY' in sql for sql in statements)
    rows = {row['item_id']: row for row in first}
    assert len(rows) == len(first) == 3
    assert {row['item_id'] for row in first if row['work']['for_position']} == {spool}
    assert {row['item_id'] for row in second if row['work']['for_position']} == {assembly}
    assert {row['item_id'] for row in prep if row['work']['for_position']} == {component}
    assert rows[component]['parent_item_id'] == spool and rows[spool]['parent_item_id'] == assembly
    assert all(row['purchase_order'] == 'PO-WORK-17' for row in first)
    assert all(row['assembly_number'] == 'ASSEMBLY-SHOP-42' for row in first)
    assert rows[assembly]['kind'] == 'Assembly' and rows[component]['kind'] == 'Part'
    assert record['work'] == next(row['work'] for row in second if row['item_id'] == assembly)
    assert record['item']['assembly_number'] == 'ASSEMBLY-SHOP-42'
    assert len(record['spools']) == 1 and record['spools'][0]['work'] is None
    assert record['work']['title'] == record['flow']['current']['title']
    assert record['work']['current_checks'] == record['flow']['current']['checks']
    assert database_state(api) == before


def test_testing_list_and_detail_use_the_signed_in_employee_and_do_not_change_evidence(api):
    flow = importlib.import_module('flow')
    assembly = create_item(api, 'WORK-TESTING-ASSEMBLY', kind='Assembly')
    enroll(api, assembly, 'assembly', expected_children=1)
    with api.session_factory() as session:
        original = session.get(api.application.Employee, BADGES['ndt'])
        session.add(api.application.Employee(badge='WORK-NDT-COWORKER', name='Other local tester',
            role='ndt', active=True, pin_hash=original.pin_hash))
        session.get(api.application.Item, assembly).handler = BADGES['ndt']
        session.add(flow.FlowTestingState(item_id=assembly, phase='ndt', decision='YES', test_kind='ndt',
            test_started_by=BADGES['ndt'], test_started_at=api.application.utcnow()))
        session.commit()
    before = database_state(api)
    for role, allowed in (('ndt', True), ('WORK-NDT-COWORKER', False), ('admin', True), ('inspector', False)):
        row = ok(api.get('/api/flow/items', role=role))['items'][0]
        record = ok(api.get('/api/flow/items/' + assembly, role=role))
        assert row['work'] == record['work']
        assert row['work']['required_employee_badge'] == BADGES['ndt']
        assert row['work']['can_record'] is allowed
        assert row['work']['display_step'] == 18
        assert row['work']['current_checks'] == record['flow']['current']['checks']
    assert database_state(api) == before
