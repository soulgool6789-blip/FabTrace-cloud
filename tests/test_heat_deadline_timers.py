"""The heat deadline also controls later numbered process timers."""
import pytest

from test_flow import (
    ROOT as FLOW, advance, completed_spool, create_item,
    detail as flow_detail, enroll, link_spool,
)
from test_heat_deadline import blocked, fill_weld_heats, finish_weld, receive
from tracking_helpers import accept_weld, add_weld, ok, ready_to_weld, weld as weld_detail


@pytest.mark.parametrize('route,step', [('spool', 15), ('assembly', 17)])
def test_qa003_preparation_and_assembly_fabrication_timers_can_resume_without_heat(api, route, step):
    item_id = create_item(api, 'HEAT-EARLY-TIMER', kind='Spool' if route == 'spool' else 'Assembly',
                          planned=0 if route == 'spool' else 1)
    if route == 'spool':
        receive(api, item_id)
    else:
        add_weld(api, item_id, heat_a='', heat_b='')
    enroll(api, item_id, route, start_step=step, expected_children=0 if route == 'spool' else 1)
    path = f'/api/tracking/spools/{item_id}/process'
    running = ok(api.get(path))
    paused = ok(api.post(path, {'action': 'pause', 'expected_version': running['version'],
                                'notes': 'Pause before the next controlled review'}), 201)
    assert 'resume' in paused['permissions']['allowed_actions']
    resumed = ok(api.post(path, {'action': 'resume', 'expected_version': paused['version']}), 201)
    assert resumed['status'] == 'running'
    assert resumed['current']['process_key'] == f'clm_{step:02d}'


def test_later_clm_resume_and_corrective_sync_need_heat_without_blocking_the_fail_route(api):
    assembly = create_item(api, 'HEAT-LATER-TIMER', kind='Assembly', planned=1)
    child = completed_spool(api, 'HEAT-LATER-TIMER-CHILD')
    record = add_weld(api, assembly)
    enroll(api, assembly, 'assembly', expected_children=1)
    link_spool(api, assembly, child)
    ready_to_weld(api, assembly, record['id'])
    finish_weld(api, record['id'])
    accept_weld(api, assembly, record['id'])
    assert advance(api, assembly)['flow']['current_step'] == 18

    current = weld_detail(api, assembly, record['id'])
    work = current['work']
    ok(api.patch(f"/api/tracking/welds/{record['id']}", {
        'expected_version': current['version'], 'heat_a': '',
        'change_reason': 'Retained heat entry needs correction before further testing',
    }, role='supervisor'))
    path = f'/api/tracking/spools/{assembly}/process'
    running = ok(api.get(path))
    paused = ok(api.post(path, {'action': 'pause', 'expected_version': running['version'],
                                'notes': 'Pause testing while the heat entry is corrected'}), 201)
    assert paused['heat_blockers'] and not paused['receiving_blockers']
    assert 'resume' not in paused['permissions']['allowed_actions']
    blocked(api, path, {'action': 'resume', 'expected_version': paused['version']})

    # A valid QA failure/return is recorded, but does not start work without heat.
    flow = flow_detail(api, assembly)['flow']
    failed = ok(api.post(f'{FLOW}/items/{assembly}/fail', {
        'expected_version': flow['version'], 'return_step': 18,
        'reference': 'TEST-HEAT-CORRECTION', 'reason': 'Repeat test review after correcting heat evidence',
    }, role='inspector'))
    assert failed['flow']['current_step'] == 18
    stopped = ok(api.get(path))
    assert stopped['current'] is None and stopped['status'] == 'finished'
    assert stopped['events'][-1]['event'] == 'finish'
    assert 'resume' not in stopped['permissions']['allowed_actions']
    blocked(api, path, {'action': 'resume', 'expected_version': stopped['version']})

    updated = fill_weld_heats(api, assembly, record['id'])
    assert updated['work'] == work and updated['production_complete']
    assert not updated['qa_accepted'], 'Heat correction does not manufacture fresh QA acceptance'
    allowed = ok(api.get(path))
    assert 'resume' in allowed['permissions']['allowed_actions']
    resumed = ok(api.post(path, {'action': 'resume', 'expected_version': allowed['version']}), 201)
    assert resumed['status'] == 'running'
    assert resumed['current']['process_key'] == 'clm_18'
