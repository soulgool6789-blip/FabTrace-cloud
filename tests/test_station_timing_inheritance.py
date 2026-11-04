"""Shared parent moves remain in a completed child's historical station visits."""
import datetime as dt

import pytest

from conftest import BADGES
from test_order_labels import generate, labels, public_qr_url
from test_spool_status_presentation import seed


def test_completed_child_retains_past_parent_visits_after_its_own_later_move(api):
    from flow import FlowPlan
    from flow_stations import station_positions
    from order_spools import OrderSpool

    _, project, _ = seed(api)
    generate(api, project)
    child = labels(api, project)['items'][0]
    item_id, parent_id = child['id'], child['assembly_id']
    at = lambda hour: dt.datetime(2026, 11, 3, hour, tzinfo=dt.timezone.utc)

    def movement(s, identifier, hour, previous, location):
        s.add(api.application.Audit(item_id=identifier, actor=BADGES['handler'], event='TRANSFER', at=at(hour),
            details={'location_changed': True, 'from': {'location_id': previous},
                'to': {'location_id': location, 'location': location, 'handler': BADGES['handler']}}))

    with api.session_factory() as s:
        s.get(OrderSpool, item_id).created_at = at(0)
        s.add(FlowPlan(item_id=item_id, route='spool', status='completed', current_step=None,
            baseline_step=9, started_by=BADGES['admin'], started_at=at(0), updated_at=at(2), completed_at=at(2)))
        movement(s, item_id, 1, 'inventory', 'floor')
        movement(s, parent_id, 3, 'floor', 'testing')
        movement(s, item_id, 4, 'testing', 'welding')
        s.commit()
        item = s.get(api.application.Item, item_id)
        own_current = station_positions(s, [item])[item_id]
        assert own_current['key'] == 'welding'
        assert [row['stage_key'] for row in own_current['station_visits']] == ['floor', 'testing', 'welding']
        assert own_current['station_visits'][1]['inherited']
        assert own_current['station_visits'][1]['source_item_id'] == parent_id
        assert own_current['station_visits'][1]['departed_at'] == at(4).isoformat()
        movement(s, parent_id, 5, 'testing', 'blast_paint')
        s.commit()
        parent_current = station_positions(s, [item])[item_id]
        assert parent_current['key'] == 'paint'
        assert [row['stage_key'] for row in parent_current['station_visits']] == ['floor', 'testing', 'welding', 'paint']


@pytest.mark.parametrize('return_action', ['reopen', 'fail', 'rework_return', 'admin_return_to_work'])
def test_parent_visits_follow_each_completion_interval_and_exclude_open_rework(api, return_action):
    from flow import FlowEvent, FlowPlan
    from flow_stations import station_positions
    from order_spools import OrderSpool

    _, project, _ = seed(api)
    generate(api, project)
    child = labels(api, project)['items'][0]
    item_id, parent_id = child['id'], child['assembly_id']
    at = lambda hour: dt.datetime(2026, 11, 3, hour, tzinfo=dt.timezone.utc)

    def movement(s, identifier, hour, previous, location):
        s.add(api.application.Audit(item_id=identifier, actor=BADGES['handler'], event='TRANSFER', at=at(hour),
            details={'location_changed': True, 'from': {'location_id': previous},
                'to': {'location_id': location, 'location': location, 'handler': BADGES['handler']}}))

    with api.session_factory() as s:
        s.get(OrderSpool, item_id).created_at = at(0)
        plan = FlowPlan(item_id=item_id, route='spool', status='active', current_step=14,
            baseline_step=9, started_by=BADGES['admin'], started_at=at(0), updated_at=at(4))
        s.add(plan)
        s.add(FlowEvent(item_id=item_id, sequence=1, action='advance', step=16,
            actor=BADGES['handler'], at=at(2), data={}))
        s.add(FlowEvent(item_id=item_id, sequence=2, action=return_action, step=14,
            actor=BADGES['admin'], at=at(4), data={'return_step': 14}))
        movement(s, item_id, 1, 'inventory', 'floor')
        movement(s, parent_id, 3, 'floor', 'testing')
        movement(s, item_id, 5, 'testing', 'welding')
        movement(s, parent_id, 6, 'testing', 'blast_paint')
        s.commit()
        item = s.get(api.application.Item, item_id)
        in_rework = station_positions(s, [item])[item_id]
        assert in_rework['key'] == 'welding'
        assert [row['stage_key'] for row in in_rework['station_visits']] == ['floor', 'testing', 'welding']
        assert in_rework['station_visits'][1]['inherited']
        assert all(row['stage_key'] != 'paint' for row in in_rework['station_visits'])

        movement(s, item_id, 7, 'welding', 'floor')
        s.add(FlowEvent(item_id=item_id, sequence=3, action='advance', step=16,
            actor=BADGES['handler'], at=at(8), data={}))
        plan.status, plan.current_step = 'completed', None
        plan.updated_at = plan.completed_at = at(8)
        movement(s, parent_id, 9, 'blast_paint', 'qa_004')
        s.commit()
        completed_again = station_positions(s, [item])[item_id]
        assert completed_again['key'] == 'qa_004'
        assert [row['stage_key'] for row in completed_again['station_visits']] == [
            'floor', 'testing', 'welding', 'floor', 'qa_004']
        assert [(row['stage_key'], row['entered_at']) for row in completed_again['station_visits'] if row['inherited']] == [
            ('testing', at(3).isoformat()), ('qa_004', at(9).isoformat())]


def test_same_station_parent_handoff_preserves_clock_and_keeps_source_segments():
    from station_timing import station_visit_history

    at = lambda hour: dt.datetime(2026, 11, 3, hour, tzinfo=dt.timezone.utc)
    result = station_visit_history([
        {'at': at(1), 'event_id': 1, 'stage_key': 'floor', 'source_item_id': 'CHILD',
         'inherited': False, 'evidence_source': 'transfer'},
        {'at': at(3), 'event_id': 2, 'stage_key': 'floor', 'source_item_id': 'PARENT',
         'inherited': True, 'evidence_source': 'transfer'},
        {'at': at(4), 'event_id': 3, 'stage_key': 'floor', 'source_item_id': 'PARENT',
         'inherited': True, 'evidence_source': 'transfer'},
    ])
    assert result['station_entered_at'] == at(1).isoformat()
    assert len(result['station_visits']) == 2
    own, inherited = result['station_visits']
    assert own['source_item_id'] == 'CHILD' and not own['inherited']
    assert inherited['source_item_id'] == 'PARENT' and inherited['inherited']
    assert own['departed_at'] == inherited['entered_at'] == at(3).isoformat()
    assert inherited['departed_at'] is None
