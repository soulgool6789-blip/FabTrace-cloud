"""Read-only, per-spool summaries of the two fabrication QA reviews.

Only a recorded traveler inspection decision supplies a PASS or FAIL. A later
return invalidates completion without erasing that historical decision. These
summaries never authorize work or replace the live inspection/release gates.
"""

import datetime as dt


QA_STEPS = (11, 15)
RETURN_STEPS = {11: 10, 15: 14}
INVALIDATING_ACTIONS = ('fail', 'rework_return', 'reopen', 'admin_return_to_work')


def _timestamp(value):
    if not value:
        return None
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


def _decision(event):
    data = event.get('data') or {}
    return {
        'event_id': event.get('id'), 'sequence': event.get('sequence'),
        'result': 'PASS' if event['action'] == 'advance' else 'FAIL',
        'actor': event.get('actor'), 'at': event.get('at'),
        'reference': event.get('reference', ''), 'notes': event.get('notes', ''),
        'resolution': data.get('resolution', ''),
        'title': (data.get('step_definition') or {}).get('title'),
    }


def _defects(number, definitions, events, exceptions):
    target = RETURN_STEPS[number]
    rows = []
    for exception in exceptions:
        if exception.get('step') != number or exception.get('closed_at'):
            continue
        failed = next((event for event in events if event.get('action') == 'fail'
                       and (event.get('data') or {}).get('exception_id') == exception['id']), None)
        completion = None
        for event in events:
            data = event.get('data') or {}
            if (event.get('action') != 'advance' or event.get('step') != target
                    or exception['id'] not in data.get('reworked_exception_ids', ())):
                continue
            if failed is not None and event['sequence'] <= failed['sequence']:
                continue
            if _timestamp(event.get('at')) < _timestamp(exception.get('opened_at')):
                continue
            description = data.get('resolution', '')
            if isinstance(description, str) and len(description.strip()) >= 4:
                completion = {
                    'event_id': event.get('id'), 'step': target, 'actor': event.get('actor'),
                    'at': event.get('at'), 'description': description,
                    'reference': event.get('reference', ''),
                }
        rows.append({
            'id': exception['id'], 'step': number, 'display_step': number,
            'return_step': target, 'return_display_step': target,
            'reason': exception.get('reason', ''), 'reference': exception.get('reference', ''),
            'opened_by': exception.get('opened_by'), 'opened_at': exception.get('opened_at'),
            'responsible_roles': list(definitions[target]['roles']), 'testing': False,
            'needs_completion': completion is None, 'completion': completion,
        })
    return rows


def spool_review_rows(plan, definitions, events=(), exceptions=(), *, removed=False):
    """Project already-loaded records, retaining their real event order.

    ``plan`` is None for a spool without a traveler. ``definitions`` contains the
    saved-catalog definitions for production steps 10/14 and QA steps 11/15.
    ``events`` are that spool's immutable events ordered by sequence. No item-level
    release, baseline, elapsed work, or another spool's approval supplies a result.
    """
    result = []
    for number in QA_STEPS:
        definition = definitions[number]
        status = 'not_recorded' if plan and number < plan['baseline_step'] else 'pending'
        latest = credited = None
        invalidated = False
        for event in events:
            action, data = event.get('action'), event.get('data') or {}
            if action in INVALIDATING_ACTIONS:
                target = data.get('return_step', event.get('step'))
                if isinstance(target, int) and target <= number:
                    invalidated = invalidated or credited is not None
                    credited = None
                    status = 'pending'
            if event.get('step') != number or data.get('phase_only'):
                continue
            if action in ('advance', 'fail'):
                latest = _decision(event)
                if action == 'advance':
                    credited, invalidated, status = latest, False, 'completed'
                else:
                    credited, status = None, 'rework'
        defects = _defects(number, definitions, events, exceptions)
        needs_reinspection = bool(defects or invalidated or latest and latest['result'] == 'FAIL')
        is_current = bool(plan and plan['status'] == 'active'
                          and plan.get('current_step') == number and not removed)
        if needs_reinspection:
            status = 'rework'
        if is_current:
            status = 'current'
        result.append({
            **definition, 'checks': [dict(check) for check in definition['checks']],
            'qa': True, 'review_key': definition['qa_code'],
            'status': status, 'is_current': is_current,
            'completed_at': credited['at'] if credited and not needs_reinspection else None,
            'last_actor': credited['actor'] if credited and not needs_reinspection else None,
            'latest_review': latest, 'needs_reinspection': needs_reinspection,
            'defects': defects, 'return_step': RETURN_STEPS[number],
            'return_title': definitions[RETURN_STEPS[number]]['title'],
        })
    return result
