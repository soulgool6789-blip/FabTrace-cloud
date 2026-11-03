"""Station durations retain visits and never infer entry from mutable state."""
import datetime as dt
import importlib

from sqlalchemy import select

from station_helpers import move
from test_order_labels import generate, labels, public_qr_url
from test_progress import database_state
from test_spool_status_presentation import seed
from tracking_helpers import ok


def movement(hour, key, event_id, **extra):
    return {'at': dt.datetime(2026, 11, 3, hour, tzinfo=dt.timezone.utc),
            'stage_key': key, 'event_id': event_id, 'source_item_id': 'SPOOL-1',
            'evidence_source': 'transfer', 'actor': 'QA-1', **extra}


def test_repeated_visits_same_station_handoffs_and_unknown_movements():
    from station_timing import station_visit_history
    result = station_visit_history([movement(1, 'floor', 1), movement(2, 'floor', 2),
        movement(3, 'welding', 3), movement(4, 'floor', 4), movement(5, None, 5),
        movement(6, 'floor', 6)])
    visits = result['station_visits']
    assert [(v['stage_key'], v['visit']) for v in visits] == [('floor', 1), ('welding', 1), ('floor', 2), ('floor', 3)]
    assert visits[0]['entered_at'].endswith('01:00:00+00:00')
    assert visits[0]['departed_at'].endswith('03:00:00+00:00')
    assert visits[2]['departed_at'].endswith('05:00:00+00:00')
    assert result['station_entered_at'] == visits[-1]['entered_at']
    assert visits[-1]['departed_at'] is None


def test_mutable_state_timestamp_and_absent_movement_never_become_entry():
    from station_timing import station_visit_history
    assert station_visit_history([])['station_entered_at'] is None
    state = station_visit_history([movement(1, 'welding', None, evidence_source='recorded_state')])
    assert state['station_timing_status'] == 'entry_not_recorded'
    assert state['station_visits'] == []
    unknown = station_visit_history([movement(1, 'floor', 1), movement(2, None, 2)])
    assert unknown['station_entered_at'] is None
    assert unknown['station_timing_status'] == 'station_unmapped'


def test_api_refresh_and_same_station_transfer_preserve_entry(api, public_qr_url):
    _, project, _ = seed(api)
    generate(api, project)
    item_id = labels(api, project)['items'][0]['id']
    initial = ok(api.get('/api/items/' + item_id))['flow_stage']
    assert initial['station_entered_at'] is None
    first = move(api, item_id, 'floor')['flow_stage']
    assert first['station_entered_at'] and len(first['station_visits']) == 1
    second = move(api, item_id, 'floor', status='in_progress')['flow_stage']
    assert second['station_entered_at'] == first['station_entered_at']
    assert len(second['station_visits']) == 1
    move(api, item_id, 'welding')
    returned = move(api, item_id, 'floor')['flow_stage']
    assert [v['stage_key'] for v in returned['station_visits']] == ['floor', 'welding', 'floor']
    assert returned['station_visits'][-1]['visit'] == 2
    before = database_state(api)
    for _ in range(2):
        assert ok(api.get('/api/items/' + item_id))['flow_stage'] == returned
        ok(api.get('/api/progress/orders', params={'project_id': project}))
    assert database_state(api) == before
