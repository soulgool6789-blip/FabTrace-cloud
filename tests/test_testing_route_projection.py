"""Testing routes keep progress, timers and read projections truthful."""
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from conftest import BADGES
from test_flow import create_item, enroll
from tracking_helpers import ok


def recorded(step, *, phase_only=False, **data):
    return SimpleNamespace(action='advance', step=step,
                           data={'testing_protocol': 'CLM-TEST-v1', 'phase_only': phase_only, **data})


def test_no_testing_excludes_only_the_saved_optional_steps(application):
    from production_progress import COUNT_KEYS, _steps, _stages
    from progress import _recorded_steps
    plan = SimpleNamespace(route='assembly', catalog_version='CLM-25-v1', baseline_step=17, current_step=20, status='active')
    testing = SimpleNamespace(decision='NO', phase='not_required')
    steps = _steps('assembly', plan, [recorded(17)], testing)
    states = {row['number']: row['state'] for row in steps}
    assert states == {17: 'completed', 18: 'not_required', 19: 'not_required',
                      20: 'current', 21: 'pending', 22: 'pending', 23: 'pending', 24: 'pending', 25: 'pending'}
    assert _recorded_steps(plan, [recorded(17)], testing) == (1, 7, 0)
    fabrication = [row for row in steps if row['fabrication'] and row['state'] != 'not_required']
    assert len(fabrication) == 4
    summary = {key: 0 for key in COUNT_KEYS}
    summary['items'] = 1
    stages = {row['key']: row for row in _stages({'A': {'steps': steps}}, ['A'], summary)}
    for key in ('qa_test_results', 'qa_pressure_results'):
        assert stages[key]['state'] == 'not_required'
        assert stages[key]['completed'] == stages[key]['total'] == 0
        assert stages[key]['not_required'] == 1 and stages[key]['percent'] is None
    assert stages['floor']['state'] == 'pending' and stages['floor']['total'] == 1
    assert stages['floor']['not_required'] == 1, 'Only testing Floor19 is skipped; shipment Floor23 remains due'
    assert stages['paint']['state'] == 'current' and stages['qa_final']['state'] == 'pending'


@pytest.mark.parametrize('phase,current,terminal,expected', [
    ('ndt', 17, [], ['current', 'pending', 'pending']),
    ('ndt_qa', 18, [], ['pending', 'current', 'pending']),
    ('floor_before_pressure', 19, [], ['pending', 'pending', 'current']),
    ('pressure_test', 17, [], ['current', 'pending', 'pending']),
    ('pressure_qa', 18, [17], ['completed', 'current', 'pending']),
    ('floor_before_paint', 19, [17, 18], ['completed', 'completed', 'current']),
    ('complete', 20, [17, 18, 19], ['completed', 'completed', 'completed']),
    ('ndt_rework', 17, [], ['current', 'pending', 'pending']),
    ('pressure_rework', 17, [], ['current', 'pending', 'pending']),
])
def test_shared_steps_require_pressure_completion_after_ndt(application, phase, current, terminal, expected):
    from production_progress import _steps
    plan = SimpleNamespace(route='assembly', catalog_version='CLM-25-v1', baseline_step=17, current_step=current, status='active')
    testing = SimpleNamespace(decision='YES', phase=phase)
    events = [recorded(number, phase_only=True) for number in (17, 17, 18, 19)]
    events.extend(recorded(number) for number in terminal)
    steps = _steps('assembly', plan, events, testing)
    assert [row['state'] for row in steps[:3]] == expected


def test_legacy_numbered_history_retains_its_test_title(application):
    from flow import LEGACY_STEP_17
    from production_progress import _steps
    from progress import _recorded_steps
    plan = SimpleNamespace(route='assembly', baseline_step=17, current_step=20, status='active')
    events = [SimpleNamespace(action='advance', step=n, data={}) for n in (17, 18, 19)]
    steps = _steps('assembly', plan, events)
    assert steps[0]['title'] == LEGACY_STEP_17['title']
    assert [row['state'] for row in steps[:3]] == ['completed'] * 3
    assert _recorded_steps(plan, events) == (3, 8, 0)


def test_administrative_override_retains_pending_tests_without_two_current_steps(application):
    from production_progress import _steps
    plan = SimpleNamespace(route='assembly', catalog_version='CLM-25-v1', baseline_step=17, current_step=23, status='active')
    testing = SimpleNamespace(decision='YES', phase='ndt')
    steps = _steps('assembly', plan, [recorded(17, phase_only=True)], testing)
    assert [row['number'] for row in steps if row['state'] == 'current'] == [23]
    assert all(row['state'] == 'pending' for row in steps if row['number'] in (17, 18, 19))


@pytest.mark.parametrize('legacy_version', [None, 'CLM-24-v6'])
def test_historical_shipping_numbers_and_denominators_stay_frozen(application, legacy_version):
    from production_progress import _steps
    from progress import _recorded_steps
    old = SimpleNamespace(route='assembly', catalog_version=legacy_version,
        baseline_step=17, current_step=23, status='active')
    new = SimpleNamespace(route='assembly', catalog_version='CLM-25-v1',
        baseline_step=17, current_step=23, status='active')
    events = [SimpleNamespace(action='advance', step=n, data={}) for n in range(17, 23)]
    historical, current = _steps('assembly', old, events), _steps('assembly', new, events)
    assert len(historical) == 8 and len(current) == 9
    assert historical[-2]['number'] == 23 and historical[-2]['title'] == 'Release to Ready to Ship'
    assert historical[-1]['number'] == 24 and historical[-1]['title'] == 'Ship to Customer'
    assert current[-3]['number'] == 23 and current[-3]['title'] == 'Return to Floor'
    assert current[-2]['number'] == 24 and current[-2]['title'] == 'Release to Ready to Ship'
    assert current[-1]['number'] == 25 and current[-1]['title'] == 'Ship to Customer'
    assert historical[5]['title'].startswith('QA/QC-005')
    assert current[5]['title'].startswith('QA/QC-006')
    assert _recorded_steps(old, events) == (6, 8, 0)
    assert _recorded_steps(new, events) == (6, 9, 0)
    assert all(not row['fabrication'] for row in current[-3:])


def test_distinct_review_stations_require_their_own_saved_pass(application):
    from production_progress import COUNT_KEYS, _steps, _stages
    plan = SimpleNamespace(route='assembly', catalog_version='CLM-25-v1',
        baseline_step=17, current_step=18, status='active')
    testing = SimpleNamespace(decision='YES', phase='pressure_qa')
    events = [recorded(17, phase_only=True, testing_action='decision', testing_decision='YES'),
        recorded(18, phase_only=True, testing_action='review', test_kind='ndt', test_result='PASS'),
        recorded(17, testing_action='complete', test_kind='pressure', test_result='PASS')]
    steps = _steps('assembly', plan, events, testing)
    assert len([row for row in steps if row['number'] == 18]) == 1
    summary = {key: 0 for key in COUNT_KEYS}
    summary['items'] = 1
    stages = {row['key']: row for row in _stages({'A': {'steps': steps}}, ['A'], summary)}
    assert stages['qa_test_results']['state'] == 'completed'
    assert stages['qa_pressure_results']['state'] == 'current'
    assert stages['qa_test_results']['total'] == stages['qa_pressure_results']['total'] == 1
    assert sum(row['fabrication'] for row in steps) == 6
    # A later pressure failure retains the completed NDT review, while the
    # matching pressure review reopens. A full restart reopens both reviews.
    failure = SimpleNamespace(action='fail', step=18, data={'testing_protocol':'CLM-TEST-v1',
        'testing_action':'review', 'test_kind':'pressure', 'test_result':'FAIL', 'return_step':17})
    plan.current_step, testing.phase = 17, 'pressure_rework'
    after = _steps('assembly', plan, [*events, failure], testing)[1]['stage_states']
    assert after == {'qa_test_results':'completed', 'qa_pressure_results':'pending'}
    restart = SimpleNamespace(action='reopen', step=17, data={'testing_protocol':'CLM-TEST-v1',
        'testing_action':'restart', 'return_step':17})
    after = _steps('assembly', plan, [*events, failure, restart], testing)[1]['stage_states']
    assert set(after.values()) == {'pending'}


def test_numeric_review_alone_never_claims_two_phase_acceptances(application):
    from production_progress import _steps
    plan = SimpleNamespace(route='assembly', catalog_version='CLM-25-v1',
        baseline_step=17, current_step=20, status='active')
    steps = _steps('assembly', plan, [recorded(18)], SimpleNamespace(decision='YES', phase='complete'))
    assert steps[1]['state'] == 'completed'
    assert set(steps[1]['stage_states'].values()) == {'pending'}


def test_legacy_recorded_station_remains_in_catalog_without_a_traveler(application):
    from production_progress import COUNT_KEYS, _steps, _stages
    steps = _steps('assembly', None, [])
    nodes = {'A': {'steps':steps, 'flow_stage':{'key':'qa_004'}}}
    summary = {key: 0 for key in COUNT_KEYS}
    summary['items'] = 1
    stages = {row['key']:row for row in _stages(nodes, nodes, summary)}
    assert stages['qa_004']['label'] == 'QA/QC-005'
    assert stages['qa_pressure_results']['label'] == 'QA/QC-005'
    assert stages['qa_final']['label'] == 'QA/QC-006'
    assert stages['qa_004']['state'] == 'not_applicable'
    assert stages['qa_final']['state'] == 'pending'


@pytest.mark.parametrize('station', ['qa_pressure_results', 'qa_final'])
def test_current_recorded_station_remains_visible_on_a_retained_legacy_route(application, station):
    from production_progress import COUNT_KEYS, _steps, _stages
    plan = SimpleNamespace(route='assembly', catalog_version=None,
        baseline_step=17, current_step=22, status='active')
    steps = _steps('assembly', plan, [])
    nodes = {'A': {'steps':steps, 'catalog_version':'CLM-24-v6', 'flow_stage':{'key':station}}}
    summary = {key: 0 for key in COUNT_KEYS}
    summary['items'] = 1
    stages = {row['key']:row for row in _stages(nodes, nodes, summary)}
    assert station in stages
    assert stages[station]['state'] == 'not_applicable', 'A physical move does not create new route obligations or QA passes'
    assert stages['qa_004']['state'] == 'current'
    assert len(steps) == 8 and steps[-1]['number'] == 24


def test_phase_timer_permissions_and_resume_keep_the_actual_testing_role(api):
    from flow import FlowPlan, current_step_definition
    from flow_testing import FlowTestingState
    from main import Item
    from production import sync_flow_process
    item_id = create_item(api, 'TEST-TIMER-PHASE', kind='Assembly')
    enroll(api, item_id, 'assembly', expected_children=1)
    with api.session_factory() as s:
        plan = s.get(FlowPlan, item_id)
        s.add(FlowTestingState(item_id=item_id, decision='YES', phase='ndt',
            test_kind='ndt', attempt=2, decision_by=BADGES['handler'], decision_at=api.application.utcnow()))
        s.flush()
        sync_flow_process(s, s.get(Item, item_id), BADGES['ndt'],
                          current_step_definition(s, plan), api.application.utcnow())
        s.commit()
    path = f'/api/tracking/spools/{item_id}/process'
    snapshot = ok(api.get(path, role='ndt'))
    assert snapshot['permissions']['allowed_actions'] == ['pause']
    assert 'NDT' in snapshot['current']['process_name']
    for role in ('handler', 'inspector', 'pressure_testing_technician'):
        assert ok(api.get(path, role=role))['permissions']['allowed_actions'] == []
        assert api.post(path, {'action': 'pause', 'expected_version': snapshot['version'], 'notes': 'Test pause reason'}, role=role).status_code == 403
    paused = ok(api.post(path, {'action': 'pause', 'expected_version': snapshot['version'], 'notes': 'Test pause reason'}, role='ndt'), 201)
    resumed = ok(api.post(path, {'action': 'resume', 'expected_version': paused['version']}, role='ndt'), 201)
    assert resumed['current']['process_name'] == snapshot['current']['process_name']


def test_testing_eligibility_is_batched_and_never_writes_on_read(api):
    from flow import FlowPlan
    from flow_testing import testing_state
    from read_projection import prime_projection, read_get, read_projection
    from test_progress import database_state
    ids = [create_item(api, f'TEST-BATCH-TESTING-{n}', kind='Assembly') for n in range(3)]
    for item_id in ids:
        enroll(api, item_id, 'assembly', expected_children=1)
    before = database_state(api)
    statements = []
    with api.session_factory() as s, read_projection(s):
        prime_projection(s, ids)
        engine = s.get_bind()
        def observe(connection, cursor, statement, parameters, context, many):
            statements.append(statement)
        event.listen(engine, 'before_cursor_execute', observe)
        try:
            for item_id in ids:
                assert testing_state(s, read_get(s, FlowPlan, item_id)).phase == 'decision'
        finally:
            event.remove(engine, 'before_cursor_execute', observe)
    assert statements == []
    assert database_state(api) == before


def test_additive_initialization_preserves_history_without_inventing_decisions(api, monkeypatch):
    import importlib
    from flow_testing import FlowTestingState
    from sqlalchemy import inspect, select
    from test_flow import detail
    item_id = create_item(api, 'TEST-ADDITIVE-TESTING', kind='Assembly')
    before = enroll(api, item_id, 'assembly', expected_children=1)
    engine = api.session_factory.kw['bind']
    with engine.begin() as connection:
        FlowTestingState.__table__.drop(connection)
    assert 'flow_testing_states' not in inspect(engine).get_table_names()
    initializer = importlib.import_module('init_db')
    monkeypatch.setattr(initializer, 'engine', engine)
    initializer.initialize()
    initializer.initialize()
    assert 'flow_testing_states' in inspect(engine).get_table_names()
    with api.session_factory() as s:
        assert s.scalars(select(FlowTestingState)).all() == []
    after = detail(api, item_id)
    assert after['events'] == before['events']
    assert after['flow']['version'] == before['flow']['version']
    assert after['flow']['testing']['decision'] is None
    health = ok(api.get('/healthz', role=None))
    assert health['status'] == 'ok' and health['version'] == api.application.APP_VERSION
