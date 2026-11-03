"""Read-only station visits from retained physical movement evidence.

Station dwell includes waiting and holds. It is not employee labor time or a
numbered traveler step timer. Missing entry evidence remains unknown.
"""
import datetime as dt

from flow_stages import STAGE_BY_KEY


def _utc(value):
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


def station_visit_history(movements):
    """Group consecutive known station moves without resetting custody handoffs.

    An unmapped physical movement ends the known visit. A later return starts
    another visit, even if the display retained the previous station color.
    Current-state updated_at cannot prove when a historical station was entered.
    """
    visits, current, counts = [], None, {}
    continuous_key, continuous_entered_at = None, None
    status = 'entry_not_recorded'
    for movement in sorted(movements, key=lambda row: (_utc(row['at']), row.get('event_id') or 0)):
        at = _utc(movement['at']).isoformat()
        key = movement.get('stage_key')
        uncertain = not key or movement.get('evidence_source') == 'recorded_state'
        same = (not uncertain and current is not None
                and current['stage_key'] == key
                and current['source_item_id'] == movement['source_item_id']
                and current['inherited'] == bool(movement.get('inherited')))
        if same:
            continue
        if current is not None:
            current['departed_at'] = at
            current['exit_event_id'] = movement.get('event_id')
            current['departed_by'] = movement.get('actor')
            current = None
        if uncertain:
            status = 'station_unmapped' if not key else 'entry_not_recorded'
            continuous_key, continuous_entered_at = None, None
            continue
        if key != continuous_key:
            counts[key] = counts.get(key, 0) + 1
            continuous_key, continuous_entered_at = key, at
        # Movement projection supplies a saved checkpoint label only when its
        # recorded definition agrees with this semantic station key. Do not
        # relabel old final QA as the newer pressure or final checkpoint.
        saved_label = movement.get('stage_label')
        label = saved_label if isinstance(saved_label, str) and saved_label.strip() else STAGE_BY_KEY[key]['label']
        current = {'stage_key': key, 'label': label,
            'visit': counts[key], 'entered_at': at, 'departed_at': None,
            'entry_event_id': movement.get('event_id'), 'exit_event_id': None,
            'entered_by': movement.get('actor'), 'departed_by': None,
            'handler_badge': movement.get('handler_badge'),
            'source_item_id': movement['source_item_id'],
            'inherited': bool(movement.get('inherited')),
            'entry_notes': movement.get('notes', '')}
        visits.append(current)
        status = 'recorded'
    return {'station_visits': visits,
            'station_entered_at': continuous_entered_at if current else None,
            'station_timing_status': status}
