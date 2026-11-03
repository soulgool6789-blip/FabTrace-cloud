"""Testing routes keep progress, timers and read projections truthful."""
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from conftest import BADGES
from test_flow import create_item, enroll
from tracking_helpers import ok


def recorded(step, *, phase_only=False):
    return SimpleNamespace(action='advance', step=step,
                           data={'testing_protocol': 'CLM-TEST-v1', 'phase_only': phase_only})


def test_no_testing_excludes_only_the_saved_optional_steps(application):
    from production_progress import COUNT_KEYS, _steps, _stages
    from progress import _recorded_steps
    plan = SimpleNamespace(route='assembly', baseline_step=17, current_step=20, status='active')
    testing = SimpleNamespace(decision='NO', phase='not_required')
    steps = _steps('assembly', plan, [recorded(17)], testing)
    states = {row['number']: row['state'] for row in steps}
    assert states == {17: 'completed', 18: 'not_required', 19: 'not_required',
                      20: 'current', 21: 'pending', 22: 'pending', 23: 'pending', 24: 'pending'}
    assert _recorded_steps(plan, [recorded(17)], testing) == (1, 6, 0)
    fabrication = [row for row in steps if row['fabrication'] and row['state'] != 'not_required']
    assert len(fabrication) == 4
    summary = {key: 0 for key in COUNT_KEYS}
    summary['items'] = 1
    stages = {row['key']: row for row in _stages({'A': {'steps': steps}}, ['A'], summary)}
    for key in ('qa_test_results', 'floor'):
        assert stages[key]['state'] == 'not_required'
        assert stages[key]['completed'] == stages[key]['total'] == 0
        assert stages[key]['not_required'] == 1 and stages[key]['percent'] is None
    assert stages['paint']['state'] == 'current' and stages['qa_004']['state'] == 'pending'


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
    plan = SimpleNamespace(route='assembly', baseline_step=17, current_step=current, status='active')
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
    plan = SimpleNamespace(route='assembly', baseline_step=17, current_step=23, status='active')
    testing = SimpleNamespace(decision='YES', phase='ndt')
    steps = _steps('assembly', plan, [recorded(17, phase_only=True)], testing)
    assert [row['number'] for row in steps if row['state'] == 'current'] == [23]
    assert all(row['state'] == 'pending' for row in steps if row['number'] in (17, 18, 19))


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
