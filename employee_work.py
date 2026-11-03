"""Read-only responsibilities derived from an item's actual current traveler.

Position eligibility and recorded custody are separate facts. This projection
does not assign work, accept evidence, initialize a traveler, or replace any
production, testing, inspection, or transfer validation.
"""


def _requirements(current, testing):
    requirements = []
    if current.get('checks'):
        requirements.append('Confirm every checklist entry for this step.')
    if current.get('requires_scan'):
        requirements.append('Scan or enter the exact current item ID.')
    if current.get('requires_child_scans', current.get('number') == 17):
        requirements.append('Scan or enter each linked child spool exactly once.')
    if current.get('requires_reference'):
        requirements.append('Record the required document or report reference.')
    if current.get('requires_handoff'):
        requirements.append('Scan both employee badges; the sending badge must match the current custodian.')
        requirements.append('Select the recorded handoff work status.')
    if current.get('requires_location'):
        requirements.append('Record the required destination location.')
    if current.get('number') == 5:
        requirements.append('Verify the selected target spool against the recorded component assignment.')
    if current.get('is_shipment'):
        requirements.append('Record the carrier, shipment reference and destination.')
    action = current.get('testing_action')
    if action == 'decision':
        requirements.append('Select YES or NO for whether testing is required.')
    elif action == 'start':
        requirements.append('The testing employee must receive the item using their own badge, unless an administrator records the handoff.')
    elif action in ('complete', 'review'):
        requirements.append('Record an explicit PASS or FAIL for this test attempt.')
    if action == 'review' and current.get('display_qa_code'):
        requirements.append('Verify the recorded item custody at ' + current['display_qa_code'] + '.')
    if current.get('requires_resolution'):
        requirements.append('Record the completed corrective work before starting a fresh test attempt.')
    elif action == 'review' and testing and testing.get('review_exception_ids'):
        requirements.append('Record the corrective disposition for the open exception before passing reinspection.')
    return requirements


def work_projection(item, plan, user, current=None, *, display_step=None,
                    testing=None, handoff_roles=(), active=True):
    """Describe current role/actor eligibility, independently of release gates.

All arguments are existing records or response values. No database access or
mutable state belongs here. Administrators retain the existing testing-actor
override; a same-position coworker does not inherit another tester's report
or mandatory correction.
"""
    if user is None:
        return None
    current_step = bool(plan and plan.status == 'active' and current)
    receipt = bool(plan and plan.route == 'assembly' and plan.status == 'shipped')
    pending = bool(active and (current_step or receipt))
    roles = list(current.get('roles', ())) if current_step else list(handoff_roles) if receipt else []
    for_position = user.role in roles
    action = current.get('testing_action') if current_step else None
    required_employee = None
    if action == 'complete':
        required_employee = (testing or {}).get('test_started_by')
    elif action == 'correct':
        required_employee = ((testing or {}).get('return_to') or {}).get('sender_badge')

    restriction = ''
    if not active:
        restriction = 'This record has been removed and cannot receive production work.'
    elif not pending:
        restriction = 'There is no current production step or delivery receipt to record.'
    elif not for_position:
        restriction = 'Your job position does not record this action.'
    elif action in ('complete', 'correct') and user.role != 'admin':
        if not required_employee:
            restriction = 'The recorded testing employee could not be verified. Refresh the traveler.'
        elif user.badge != required_employee:
            restriction = ('The recorded testing employee (' + required_employee + ') must '
                           + ('submit this test report.' if action == 'complete' else 'record this correction.'))
        elif item.handler != required_employee:
            restriction = 'Restore custody to the recorded testing employee before recording this action.'

    return {
        'pending': pending,
        'for_position': for_position,
        'in_custody': item.handler == user.badge,
        'custodian_badge': item.handler,
        'responsible_roles': roles,
        'required_employee_badge': required_employee,
        'can_record': bool(pending and for_position and not restriction),
        'restriction': restriction,
        'title': current['title'] if current_step else 'Record delivery confirmation' if receipt else '',
        'display_step': display_step if current_step else None,
        'current_checks': [{'id': row['id'], 'label': row['label']}
                           for row in current.get('checks', ())] if current_step else [],
        'requirements': _requirements(current, testing) if current_step else
            ['Record the delivery receipt reference.', 'Record the recipient.'] if receipt else [],
    }
