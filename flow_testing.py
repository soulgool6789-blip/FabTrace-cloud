"""Explicit assembly testing phases without renumbering the historical traveler.

This row is only the current cursor. Signed decisions, reports, custody moves,
failures and corrections remain append-only FlowEvent records.
"""

import datetime as dt
import hashlib
import json
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import (CheckConstraint, Column, DateTime, ForeignKey, Integer,
                        JSON, String, Text, select)

from main import Base, Employee, utcnow
from permissions import role_id
from read_projection import PROJECTION_MISSING, projection_get, read_cached, read_get


PROTOCOL = 'CLM-TEST-v1'
TEST_ROLES = {'ndt': 'ndt', 'pressure': 'pressure_testing_technician'}
WORK_PHASES = {'ndt': 'ndt', 'pressure_test': 'pressure'}
QA_PHASES = {'ndt_qa': 'ndt', 'pressure_qa': 'pressure'}
CORRECTION_PHASES = {'ndt_rework': 'ndt', 'pressure_rework': 'pressure'}
FLOOR_PHASES = {'floor_before_pressure', 'floor_before_paint'}
ACTIVE_PHASES = {'decision', *WORK_PHASES, *QA_PHASES, *CORRECTION_PHASES, *FLOOR_PHASES}
PHASE_STEP = {**{key: 17 for key in ('decision', *WORK_PHASES, *CORRECTION_PHASES)},
              **{key: 18 for key in QA_PHASES}, **{key: 19 for key in FLOOR_PHASES}}


class FlowTestingState(Base):
    __tablename__ = 'flow_testing_states'
    __table_args__ = (
        CheckConstraint('cycle >= 1 AND attempt >= 1', name='ck_flow_testing_attempt'),
        CheckConstraint("decision IS NULL OR decision IN ('YES','NO')", name='ck_flow_testing_decision'),
        CheckConstraint("report_result IS NULL OR report_result IN ('PASS','FAIL')", name='ck_flow_testing_report'),
        CheckConstraint("qa_result IS NULL OR qa_result IN ('PASS','FAIL')", name='ck_flow_testing_qa'),
    )
    item_id = Column(String(60), ForeignKey('items.id'), primary_key=True)
    protocol = Column(String(30), nullable=False, default=PROTOCOL)
    cycle = Column(Integer, nullable=False, default=1)
    phase = Column(String(40), nullable=False, default='decision')
    decision = Column(String(3))
    decision_by = Column(String(80), ForeignKey('employees.badge'))
    decision_at = Column(DateTime(timezone=True))
    test_kind = Column(String(20))
    attempt = Column(Integer, nullable=False, default=1)
    test_started_by = Column(String(80), ForeignKey('employees.badge'))
    test_started_at = Column(DateTime(timezone=True))
    report_result = Column(String(4))
    report_reference = Column(String(500), nullable=False, default='')
    report_notes = Column(Text, nullable=False, default='')
    reported_by = Column(String(80), ForeignKey('employees.badge'))
    reported_at = Column(DateTime(timezone=True))
    report_event_id = Column(Integer, ForeignKey('flow_events.id'))
    report_basis = Column(String(64), nullable=False, default='')
    ndt_basis = Column(String(64), nullable=False, default='')
    ndt_report_event_id = Column(Integer, ForeignKey('flow_events.id'))
    ndt_review_event_id = Column(Integer, ForeignKey('flow_events.id'))
    qa_result = Column(String(4))
    qa_reference = Column(String(500), nullable=False, default='')
    reviewed_by = Column(String(80), ForeignKey('employees.badge'))
    reviewed_at = Column(DateTime(timezone=True))
    origin_snapshot = Column(JSON, nullable=False, default=dict)
    pending_exception_ids = Column(JSON, nullable=False, default=list)
    pending_exception_kinds = Column(JSON, nullable=False, default=dict)
    correction = Column(JSON, nullable=False, default=dict)
    phase_entered_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


def _stamp(value):
    if value is None:
        return None
    return (value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None
            else value.astimezone(dt.timezone.utc)).isoformat()


@read_cached(lambda s, plan: plan.item_id)
def _eligible_pending(s, plan):
    """Only untouched Step17 work adopts the new protocol automatically."""
    if plan.route != 'assembly' or plan.status != 'active' or plan.current_step != 17:
        return False
    from flow import VERSION, catalog_version
    # Current-catalog returns to testing always begin an explicit new
    # decision. A late controlled baseline cannot reopen the old combined QA.
    if catalog_version(plan) == VERSION:
        return True
    if plan.baseline_step > 17:
        return False
    cached = projection_get(s, 'testing_legacy_work', plan.item_id)
    if cached is not PROJECTION_MISSING:
        return not cached
    from flow import FlowEvent
    return not s.scalar(select(FlowEvent.id).where(
        FlowEvent.item_id == plan.item_id,
        ((FlowEvent.action == 'advance') & (FlowEvent.step >= 17)) |
        ((FlowEvent.action == 'fail') & (FlowEvent.step >= 18))).limit(1))


def testing_state(s, plan, *, create=False, at=None):
    if plan is None or plan.route != 'assembly':
        return None
    state = read_get(s, FlowTestingState, plan.item_id)
    if state is not None:
        return state
    if not _eligible_pending(s, plan):
        return None
    values = dict(item_id=plan.item_id, protocol=PROTOCOL, cycle=1, phase='decision',
        decision=None, decision_by=None, decision_at=None, test_kind=None, attempt=1,
        test_started_by=None, test_started_at=None, report_result=None,
        report_reference='', report_notes='', reported_by=None, reported_at=None,
        report_event_id=None, report_basis='', ndt_basis='', ndt_report_event_id=None,
        ndt_review_event_id=None, qa_result=None, qa_reference='', reviewed_by=None,
        reviewed_at=None, origin_snapshot={}, pending_exception_ids=[], pending_exception_kinds={}, correction={},
        phase_entered_at=plan.step_entered_at, created_at=at or plan.started_at,
        updated_at=at or plan.updated_at)
    if not create:
        return SimpleNamespace(**values)
    state = FlowTestingState(**values)
    s.add(state)
    s.flush()
    return state


def action_for(state):
    if state.phase == 'decision':
        return 'decision'
    if state.phase in WORK_PHASES:
        return 'complete' if state.test_started_at else 'start'
    if state.phase in QA_PHASES:
        return 'review'
    if state.phase in CORRECTION_PHASES:
        return 'correct'
    if state.phase in FLOOR_PHASES:
        return 'handoff'
    return None


def _label(kind):
    return 'NDT' if kind == 'ndt' else 'Pressure Test'


def _qa_position(kind, version):
    from flow import VERSION
    pressure = kind == 'pressure' and version == VERSION
    return {'qa_code': 'QA-005' if pressure else 'QA-004',
            'display_qa_code': 'QA/QC-005' if pressure else 'QA/QC-004',
            'qa_stage': 'qa_pressure_results' if pressure else 'qa_test_results'}


def test_qa_position(plan, kind):
    from flow import catalog_version
    return _qa_position(kind, catalog_version(plan))


def phase_definition(state, base):
    if state is None or state.phase not in ACTIVE_PHASES or PHASE_STEP[state.phase] != base['number']:
        return base
    action, phase = action_for(state), state.phase
    kind = WORK_PHASES.get(phase) or QA_PHASES.get(phase) or CORRECTION_PHASES.get(phase)
    qa_position = _qa_position(kind, base.get('catalog_version'))
    definition = {**base, 'roles': [], 'qa': False, 'return_steps': [],
        'qa_code': None, 'display_qa_code': None, 'qa_stage': None,
        'requires_scan': True, 'requires_reference': False, 'requires_handoff': False,
        'requires_location': False, 'requires_child_scans': phase == 'decision',
        'requires_resolution': action == 'correct', 'testing_phase': phase,
        'testing_action': action, 'testing_protocol': PROTOCOL,
        'handoff_target_role': None, 'handoff_location_id': None}
    if action == 'decision':
        title = 'Determine if Spool need to be sent to Testing'
        checks = ['Verify the assembly ID and every required released child spool',
                  'Scan each child spool barcode',
                  'Determine testing requirements against the approved scope']
        roles = ['admin', 'supervisor', 'handler']
    elif action == 'start':
        title = _label(kind) + ': Receive for Testing'
        checks = ['Verify the item and the required testing position',
                  'Record the actual custody handoff into testing']
        roles = ['admin', TEST_ROLES[kind]]
        definition.update(requires_handoff=True, requires_location=True,
            handoff_target_role=TEST_ROLES[kind], handoff_location_id='testing')
    elif action == 'complete':
        title = _label(kind) + ': Record Results and Send to QA/QC'
        checks = ['Complete the test against the approved requirements',
                  'Record the actual test result and controlled report reference',
                  'Record the actual custody handoff to QA/QC']
        roles = ['admin', TEST_ROLES[kind]]
        definition.update(requires_reference=True, requires_handoff=True,
            requires_location=True, handoff_target_role='inspector',
            handoff_location_id=qa_position['qa_stage'])
    elif action == 'review':
        title = qa_position['display_qa_code'] + ' - ' + (
            'NDT Results' if kind == 'ndt' else 'Verify Pressure Testing')
        checks = ['Review the current test attempt and its controlled report',
                  'Verify current passing dimensions and applicable weld / test acceptance',
                  'Record an explicit QA/QC PASS or FAIL']
        roles = ['admin', 'inspector']
        definition.update(qa=True, requires_reference=True, **qa_position,
                          flow_stage_key=qa_position['qa_stage'])
    elif action == 'correct':
        title = _label(kind) + ': Mandatory Rework'
        checks = ['Complete and record the correction required by the failed QA review',
                  'Confirm the item is ready for a new test attempt']
        roles = ['admin', TEST_ROLES[kind]]
        definition.update(requires_reference=True)
    else:
        title = 'Return to Floor After ' + ('NDT' if phase == 'floor_before_pressure' else 'Pressure Test')
        checks = ['Verify the passing test approval for this attempt',
                  'Record the actual custody handoff back to the floor']
        roles = ['admin', 'supervisor', 'handler']
        definition.update(requires_handoff=True, requires_location=True,
            handoff_target_role='handler', handoff_location_id='floor')
    if action != 'decision':
        title += f' (cycle {state.cycle}, attempt {state.attempt})'
    definition.update(title=title, roles=roles,
        checks=[{'id': f'testing_{phase}_{action}_{index}', 'label': label}
                for index, label in enumerate(checks, 1)])
    return definition


def report_snapshot(state):
    if not state.reported_at:
        return None
    return {'test_kind': state.test_kind, 'attempt': state.attempt, 'cycle': state.cycle,
        'result': state.report_result, 'reference': state.report_reference,
        'notes': state.report_notes, 'actor': state.reported_by,
        'at': _stamp(state.reported_at), 'event_id': state.report_event_id,
        'basis_sha256': state.report_basis}


def summary(s, plan):
    state = testing_state(s, plan)
    if state is None:
        return None
    active = plan.status == 'active' and PHASE_STEP.get(state.phase) == plan.current_step
    action = action_for(state) if active else None
    return {'protocol': state.protocol, 'cycle': state.cycle, 'phase': state.phase,
        'decision': state.decision, 'decision_by': state.decision_by,
        'decision_at': _stamp(state.decision_at), 'test_kind': state.test_kind,
        'attempt': state.attempt, 'action': action, 'active': active,
        'requires_decision': action == 'decision',
        'requires_result': action in ('complete', 'review'),
        'requires_child_scans': action == 'decision',
        'phase_entered_at': _stamp(state.phase_entered_at),
        'test_started_by': state.test_started_by, 'test_started_at': _stamp(state.test_started_at),
        'report': report_snapshot(state),
        'ndt_acceptance': {'basis_sha256': state.ndt_basis,
            'report_event_id': state.ndt_report_event_id,
            'review_event_id': state.ndt_review_event_id} if state.ndt_basis else None,
        'qa': {'result': state.qa_result, 'reference': state.qa_reference,
               'actor': state.reviewed_by, 'at': _stamp(state.reviewed_at)} if state.reviewed_at else None,
        'return_to': dict(state.origin_snapshot or {}) or None,
        'rework_required': state.phase in CORRECTION_PHASES,
        'pending_exception_ids': list(state.pending_exception_ids or []),
        'review_exception_ids': [identifier for identifier in state.pending_exception_ids or []
            if (state.pending_exception_kinds or {}).get(str(identifier)) == state.test_kind],
        'correction': dict(state.correction or {}) or None}


def is_active(s, plan):
    state = testing_state(s, plan)
    return (state is not None and state.phase in ACTIVE_PHASES and plan.status == 'active'
            and plan.current_step == PHASE_STEP[state.phase])


def assembly_editable(s, plan):
    state = testing_state(s, plan)
    return state is None or state.phase == 'decision' and state.decision is None and state.cycle == 1


def fabrication_editable(s, plan):
    """Existing repair operations may run during mandatory correction only."""
    state = testing_state(s, plan)
    return state is None or state.phase == 'decision' or state.phase in CORRECTION_PHASES


def can_control_flow_timer(s, plan, user):
    """None means the established legacy clock permission still applies."""
    state = testing_state(s, plan)
    if state is None or not is_active(s, plan):
        return None
    from flow import step_definition
    return role_id(user) in phase_definition(state, step_definition(plan, plan.current_step))['roles']


def validate_context(state, data):
    if (data.testing_phase != state.phase or data.testing_attempt != state.attempt or
            data.testing_action != action_for(state)):
        raise HTTPException(409, 'The testing phase or attempt changed. Refresh the traveler and review the current action; no changes were saved.')


def event_context(state, *, action=None):
    return {'testing_protocol': state.protocol, 'testing_phase': state.phase,
        'testing_action': action or action_for(state), 'test_kind': state.test_kind,
        'testing_attempt': state.attempt, 'testing_cycle': state.cycle}


def change_phase(state, plan, phase, at):
    state.phase = phase
    state.phase_entered_at = at
    state.updated_at = at
    plan.current_step = PHASE_STEP.get(phase, 20)
    plan.step_entered_at = at


def clear_attempt(state, kind, *, next_attempt=1):
    state.test_kind = kind
    state.attempt = next_attempt
    state.test_started_by = None
    state.test_started_at = None
    state.report_result = None
    state.report_reference = ''
    state.report_notes = ''
    state.reported_by = None
    state.reported_at = None
    state.report_event_id = None
    state.report_basis = ''
    state.qa_result = None
    state.qa_reference = ''
    state.reviewed_by = None
    state.reviewed_at = None


def restart_cycle(s, plan, at):
    state = read_get(s, FlowTestingState, plan.item_id)
    state.cycle += 1
    # A route that required testing cannot lose that obligation on rework.
    state.decision = 'YES' if state.decision == 'YES' else None
    state.decision_by, state.decision_at = None, None
    clear_attempt(state, None)
    state.origin_snapshot = {}
    state.ndt_basis = ''
    state.ndt_report_event_id = None
    state.ndt_review_event_id = None
    # Corrected test failures remain open until the fresh matching QA result.
    # A full-route return must not erase or close those exceptions.
    state.correction = {}
    change_phase(state, plan, 'decision', at)
    return state


def restart_after_final_qa(s, plan, failed_step, target, at):
    state = read_get(s, FlowTestingState, plan.item_id)
    if state is not None and failed_step == 22 and target == 17:
        restart_cycle(s, plan, at)


def validate_handoff(s, item, plan, state, selected, user):
    """Both the role and actual custodian are checked, never inferred."""
    action = action_for(state)
    if action == 'start':
        required = TEST_ROLES[state.test_kind]
        if selected.receiver.role not in (required, 'admin'):
            raise HTTPException(422, 'The receiving employee must hold the required testing position')
        if user.role != 'admin' and selected.receiver.badge != user.badge:
            raise HTTPException(403, 'Receive the item using your own testing employee badge')
        if selected.location_id != 'testing':
            raise HTTPException(422, 'Record the handoff into the Testing station before starting the test')
    elif action == 'complete':
        if user.role != 'admin' and item.handler != user.badge:
            raise HTTPException(403, 'The recorded testing custodian must submit their own test report')
        if item.handler != state.test_started_by:
            raise HTTPException(409, 'Testing custody changed after this attempt started. Restore the recorded testing custodian before submitting its report.')
        if selected.receiver.role not in ('inspector', 'admin'):
            raise HTTPException(422, 'Send the test report and item to an employee in the QA/QC position')
        qa_position = test_qa_position(plan, state.test_kind)
        if selected.location_id != qa_position['qa_stage']:
            raise HTTPException(422, 'The recorded test handoff must go to ' + qa_position['display_qa_code'])
    elif action == 'handoff':
        if selected.location_id != 'floor':
            raise HTTPException(422, 'Record the required handoff back to the Floor station')
        if selected.receiver.role not in ('handler', 'supervisor', 'admin'):
            raise HTTPException(422, 'The floor handoff requires a material coordinator or shop foreman')


def validate_return(state, data):
    origin = state.origin_snapshot or {}
    if not origin.get('sender_badge') or not origin.get('location_id'):
        raise HTTPException(409, 'The original testing sender and station were not recorded; this return cannot be inferred')
    if data.receiver_badge != origin['sender_badge'] or data.location_id != origin['location_id']:
        raise HTTPException(422, 'Return this failed test to the exact recorded testing employee and station')


def pending_exceptions(s, state, *, test_kind=None):
    from flow import FlowException
    ids = list(state.pending_exception_ids or [])
    rows = list(s.scalars(select(FlowException).where(FlowException.id.in_(ids)))) if ids else []
    kinds = state.pending_exception_kinds or {}
    if (len(rows) != len(ids) or set(kinds) != {str(identifier) for identifier in ids} or
            any(row.item_id != state.item_id or row.step != 18 or row.closed_at is not None for row in rows)):
        raise HTTPException(409, 'The testing correction record changed; review its open QA exceptions')
    by_id = {row.id: row for row in rows}
    return [by_id[identifier] for identifier in ids
            if test_kind is None or kinds[str(identifier)] == test_kind]


@read_cached(lambda s, item, plan: (item.id, plan.expected_children))
def _physical_report_payload(s, item, plan):
    """Bind a test to construction/source scope, excluding routing and QA acts."""
    from dossier import _physical_structure
    from flow import _spool_ids
    from main import Item
    from tracking import SpoolPlan, WeldRequirement
    identifiers = [item.id, *_spool_ids(s, item.id)]
    structures = []
    for identifier in identifiers:
        physical = s.get(Item, identifier)
        scope = s.get(SpoolPlan, identifier)
        if physical is None or scope is None:
            raise HTTPException(409, 'The tested physical scope is incomplete; review its child spools')
        structures.append(_physical_structure(s, physical, scope))
    requirements = [{key: getattr(row, key) for key in (
        'id', 'item_id', 'weld_id', 'code', 'label', 'stage', 'owner_role',
        'check_kind', 'allow_na', 'evidence_required', 'source', 'template_id')}
        for row in s.scalars(select(WeldRequirement).where(
            WeldRequirement.item_id.in_(identifiers)).order_by(WeldRequirement.id))]
    return {'protocol': PROTOCOL, 'expected_children': plan.expected_children,
            'physical_scope': structures, 'requirements': requirements}


def _hash_payload(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, default=str).encode()).hexdigest()


@read_cached(lambda s, item, plan: (item.id, plan.expected_children))
def physical_report_basis(s, item, plan):
    return _hash_payload(_physical_report_payload(s, item, plan))


def _without_pressure_correction_events(value):
    if isinstance(value, list):
        return [_without_pressure_correction_events(row) for row in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, child in value.items():
        if key == 'physical_events':
            # A pressure-test setup correction does not automatically claim
            # that NDT-covered construction changed. Actual weld work/repair,
            # components, heat/MTR, BOM and source revisions remain below.
            child = [event for event in child if not (
                event.get('data', {}).get('testing_protocol') == PROTOCOL and
                event.get('data', {}).get('test_kind') == 'pressure' and
                (event.get('action') == 'fail' or event.get('data', {}).get('testing_action') == 'correct'))]
        result[key] = _without_pressure_correction_events(child)
    return result


@read_cached(lambda s, item, plan: (item.id, plan.expected_children))
def ndt_construction_basis(s, item, plan):
    return _hash_payload(_without_pressure_correction_events(_physical_report_payload(s, item, plan)))


def ndt_prerequisite_errors(s, item, plan):
    state = testing_state(s, plan)
    if state is None or not state.ndt_basis:
        return []
    if state.phase not in ('floor_before_pressure', 'pressure_test', 'pressure_qa', 'floor_before_paint', 'complete'):
        return []
    if state.ndt_basis != ndt_construction_basis(s, item, plan):
        return ['The construction or source scope changed after NDT approval. Complete any pending QA failure and correction, then Return to testing for a fresh NDT and pressure-test cycle.']
    return []


def accepted_report_errors(s, item, plan):
    state = testing_state(s, plan)
    if state is None or state.decision != 'YES' or state.phase != 'complete':
        return []
    if (state.test_kind != 'pressure' or state.qa_result != 'PASS' or
            not state.report_basis or state.report_basis != physical_report_basis(s, item, plan)):
        return ['The physical scope or source records changed after testing approval. Return to testing for a fresh required test cycle before coating or final release.']
    return ndt_prerequisite_errors(s, item, plan)


def _review_position(s, item, plan, state):
    from transfers import ItemTransferState
    transfer = s.get(ItemTransferState, item.id)
    employee = s.get(Employee, item.handler)
    qa_position = test_qa_position(plan, state.test_kind)
    if (transfer is None or transfer.location_id != qa_position['qa_stage'] or
            employee is None or not employee.active or employee.role not in ('inspector', 'admin')):
        raise HTTPException(409, 'Record the item custody at ' + qa_position['display_qa_code'] + ' before reviewing the test result')


def _validate_report(state):
    if (state.report_result not in ('PASS', 'FAIL') or not state.reported_at or
            not state.report_event_id or len(state.report_reference) < 2 or not state.reported_by):
        raise HTTPException(409, 'A signed test result and report for this exact test attempt are required before QA review')


def _completed_corrections(s, state, *, for_restart=False):
    from flow import FlowEvent
    rows = pending_exceptions(s, state, test_kind=None if for_restart else state.test_kind)
    if not rows:
        return rows
    events = list(s.scalars(select(FlowEvent).where(FlowEvent.item_id == state.item_id)
                          .order_by(FlowEvent.sequence)))
    report_event = next((event for event in events if event.id == state.report_event_id), None)
    for exception in rows:
        kind = state.pending_exception_kinds[str(exception.id)]
        failed = next((event for event in events if event.action == 'fail' and
            event.data.get('exception_id') == exception.id and
            event.data.get('testing_protocol') == PROTOCOL and
            event.data.get('test_kind') == kind and
            isinstance(event.data.get('testing_cycle'), int) and
            (event.data['testing_cycle'] < state.cycle or
             event.data['testing_cycle'] == state.cycle and
             (for_restart or event.data.get('testing_attempt', state.attempt) < state.attempt))), None)
        corrected = next((event for event in events if event.action == 'advance' and
            event.data.get('testing_protocol') == PROTOCOL and event.data.get('testing_action') == 'correct' and
            (event.data.get('correction') or {}).get('exception_id') == exception.id and
            event.data.get('test_kind') == kind and failed is not None and
            event.data.get('testing_cycle') == failed.data.get('testing_cycle') and
            event.data.get('testing_attempt') == failed.data.get('testing_attempt') and
            failed.sequence < event.sequence and
            (for_restart or report_event is not None and event.sequence < report_event.sequence)), None)
        if failed is None or corrected is None:
            raise HTTPException(409, 'Complete the recorded correction for each failed test attempt before passing reinspection')
    return rows


def restart_allowed(s, item, plan):
    state = testing_state(s, plan)
    if state is None or plan.status != 'active' or item.released:
        return False
    after_testing = state.phase in ('complete', 'not_required') and plan.current_step in (20, 21)
    during_testing = state.phase in ('ndt', 'floor_before_pressure', 'pressure_test', 'floor_before_paint') and is_active(s, plan)
    if not (after_testing or during_testing):
        return False
    if state.pending_exception_ids:
        if any(kind not in TEST_ROLES for kind in state.pending_exception_kinds.values()):
            return False
        try:
            _completed_corrections(s, state, for_restart=True)
        except HTTPException:
            return False
    return True


def advance_testing(s, item, plan, data, user):
    from flow import (_commit, _event, _fresh_dimensions_after_work, _step_errors,
                      _sync, _utc, _verify_form, current_step_definition, detail)
    from transfers import ItemTransferState, record_transfer
    now = _utc(utcnow())
    state = testing_state(s, plan, create=True, at=now)
    validate_context(state, data)
    action, original_phase, original_step = action_for(state), state.phase, plan.current_step
    definition = current_step_definition(s, plan)
    context = event_context(state)
    if action == 'decision':
        if data.testing_decision not in ('YES', 'NO'):
            raise HTTPException(422, 'Choose YES or NO for whether testing is required; no choice is assumed')
        if state.decision == 'YES' and data.testing_decision != 'YES':
            raise HTTPException(409, 'This testing route already requires testing and cannot be changed to NO during correction')
    elif data.testing_decision is not None:
        raise HTTPException(422, 'A testing decision is accepted only at the initial decision phase')
    if action in ('complete', 'review'):
        if data.test_result not in ('PASS', 'FAIL'):
            raise HTTPException(422, 'Record an explicit PASS or FAIL for this test attempt')
        if action == 'review' and data.test_result != 'PASS':
            raise HTTPException(422, 'Use the failed test review action and record its mandatory return and rework')
    elif data.test_result is not None:
        raise HTTPException(422, 'A test result is accepted only when reporting or reviewing the current test attempt')
    selected, _ = _verify_form(s, item, plan, data)
    errors = _step_errors(s, item, plan, quality_for_update=True)
    if errors:
        raise HTTPException(409, {'flow_blockers': errors})
    if selected is not None:
        validate_handoff(s, item, plan, state, selected, user)
    extra, closed = {}, []
    if action == 'decision':
        state.decision = data.testing_decision
        state.decision_by, state.decision_at = user.badge, now
        extra['testing_decision'] = state.decision
        if state.decision == 'NO':
            change_phase(state, plan, 'not_required', now)
            extra['not_required_steps'] = [18, 19]
        else:
            clear_attempt(state, 'ndt')
            change_phase(state, plan, 'ndt', now)
    elif action == 'start':
        state.test_started_by = selected.receiver.badge
        state.test_started_at = now
        state.phase_entered_at = now
        plan.step_entered_at = now
    elif action == 'complete':
        transfer = s.get(ItemTransferState, item.id)
        if transfer is None or not transfer.location_id or transfer.location_id in ('qa_test_results', 'qa_pressure_results'):
            raise HTTPException(409, 'The testing station must be recorded before sending this attempt to QA/QC')
        state.origin_snapshot = {'sender_badge': selected.sender.badge,
            'sender_name': selected.sender.name, 'location_id': transfer.location_id,
            'location_label': item.location}
        state.report_result, state.report_reference, state.report_notes = data.test_result, data.reference, data.notes
        state.reported_by, state.reported_at = user.badge, now
        state.report_basis = physical_report_basis(s, item, plan)
        extra.update(test_result=data.test_result, report=report_snapshot(state),
                     return_to=dict(state.origin_snapshot))
        change_phase(state, plan, 'ndt_qa' if state.test_kind == 'ndt' else 'pressure_qa', now)
    elif action == 'review':
        _validate_report(state)
        _review_position(s, item, plan, state)
        if not state.report_basis or state.report_basis != physical_report_basis(s, item, plan):
            raise HTTPException(409, 'The physical scope or source records changed after this test report. Record FAIL, complete the required correction, and submit a fresh test attempt before QA PASS.')
        if state.report_result != 'PASS':
            raise HTTPException(409, 'A failed test report requires a FAIL disposition and mandatory correction; it cannot receive QA PASS')
        closed = _completed_corrections(s, state)
        if closed and len(data.resolution) < 4:
            raise HTTPException(422, 'Record the QA reinspection resolution for the corrected test attempts')
        for exception in closed:
            exception.closed_by, exception.closed_at, exception.resolution = user.badge, now, data.resolution
        closed_ids = {row.id for row in closed}
        state.pending_exception_ids = [identifier for identifier in state.pending_exception_ids if identifier not in closed_ids]
        state.pending_exception_kinds = {key: value for key, value in state.pending_exception_kinds.items()
                                         if int(key) not in closed_ids}
        state.qa_result, state.qa_reference = 'PASS', data.reference
        state.reviewed_by, state.reviewed_at = user.badge, now
        if state.test_kind == 'ndt':
            state.ndt_basis = ndt_construction_basis(s, item, plan)
            state.ndt_report_event_id = state.report_event_id
            extra['ndt_accepted_basis'] = {'basis_sha256': state.ndt_basis,
                                         'report_event_id': state.ndt_report_event_id}
        extra.update(test_result='PASS', report=report_snapshot(state),
            closed_exception_ids=[row.id for row in closed], resolution=data.resolution,
            remaining_exception_ids=list(state.pending_exception_ids),
            remaining_exception_kinds=dict(state.pending_exception_kinds))
        change_phase(state, plan, 'floor_before_pressure' if state.test_kind == 'ndt' else 'floor_before_paint', now)
    elif action == 'correct':
        origin = state.origin_snapshot or {}
        transfer = s.get(ItemTransferState, item.id)
        if item.handler != origin.get('sender_badge') or transfer is None or transfer.location_id != origin.get('location_id'):
            raise HTTPException(409, 'Complete correction at the recorded return station with the original testing custodian')
        if user.role != 'admin' and user.badge != origin.get('sender_badge'):
            raise HTTPException(403, 'The recorded testing employee must complete this correction')
        pending = pending_exceptions(s, state, test_kind=state.test_kind)
        if not pending:
            raise HTTPException(409, 'No failed test attempt is available for correction')
        correction = {'exception_id': pending[-1].id, 'attempt': state.attempt,
            'test_kind': state.test_kind, 'reference': data.reference,
            'resolution': data.resolution, 'actor': user.badge, 'at': _stamp(now)}
        state.correction = correction
        extra['correction'] = correction
        _fresh_dimensions_after_work(item, now)
        kind, next_attempt = state.test_kind, state.attempt + 1
        clear_attempt(state, kind, next_attempt=next_attempt)
        change_phase(state, plan, 'ndt' if kind == 'ndt' else 'pressure_test', now)
    elif action == 'handoff':
        if state.qa_result != 'PASS':
            raise HTTPException(409, 'QA PASS is required before the test can return to the floor')
        extra['qa'] = {'result': state.qa_result, 'reference': state.qa_reference,
                       'actor': state.reviewed_by, 'at': _stamp(state.reviewed_at)}
        if original_phase == 'floor_before_pressure':
            clear_attempt(state, 'pressure')
            state.origin_snapshot = {}
            state.correction = {}
            change_phase(state, plan, 'pressure_test', now)
        else:
            change_phase(state, plan, 'complete', now)
    if selected is not None:
        extra['handoff'] = record_transfer(s, item, selected, user, now,
            notes=data.notes, scan_method='flow_item_verification',
            scanned_item_id=data.scanned_item_id, flow_step=original_step)
    state.updated_at = now
    phase_only = not ((action == 'decision' and state.decision == 'NO') or
        (action == 'complete' and context['test_kind'] == 'pressure') or
        (action == 'review' and context['test_kind'] == 'pressure') or
        original_phase == 'floor_before_paint')
    event = _event(s, item, plan, user.badge, 'advance', original_step, now,
        data.reference, data.notes, {**context, **extra,
            'confirmations': data.confirmations, 'scanned_item_id': data.scanned_item_id,
            'scanned_child_ids': data.scanned_child_ids,
            'phase_only': phase_only, 'next_step': plan.current_step, 'next_phase': state.phase},
        step_definition=definition)
    if action == 'complete':
        state.report_event_id = event.id
    elif action == 'review' and context['test_kind'] == 'ndt':
        state.ndt_review_event_id = event.id
    _sync(s, item, user.badge, plan.current_step, now, definition['title'] + ' recorded')
    _commit(s)
    return detail(s, item, user)


def fail_testing(s, item, plan, data, user):
    from flow import (FlowException, _commit, _event, _sync, _utc,
                      current_step_definition, detail)
    from transfers import record_transfer, validate_transfer
    state = testing_state(s, plan)
    validate_context(state, data)
    if state.phase not in QA_PHASES or data.test_result != 'FAIL':
        raise HTTPException(422, 'Record an explicit FAIL at the current testing QA review')
    if data.return_step is not None:
        raise HTTPException(422, 'The test return destination is fixed by the recorded sending employee and station')
    if data.scanned_item_id != item.id:
        raise HTTPException(422, 'Scan or enter the exact item ID before recording a failed test return')
    _validate_report(state)
    _review_position(s, item, plan, state)
    validate_return(state, data)
    selected = validate_transfer(s, item, sender_badge=data.sender_badge,
        receiver_badge=data.receiver_badge, location_id=data.location_id,
        operational_status=data.operational_status,
        expected_transfer_version=data.expected_transfer_version, allow_no_change=True)
    now = _utc(utcnow())
    definition, context = current_step_definition(s, plan), event_context(state)
    row = FlowException(item_id=item.id, step=18, return_step=17,
        reason=data.reason, reference=data.reference, opened_by=user.badge, opened_at=now)
    s.add(row)
    s.flush()
    state.pending_exception_ids = [*state.pending_exception_ids, row.id]
    state.pending_exception_kinds = {**state.pending_exception_kinds, str(row.id): state.test_kind}
    state.qa_result, state.qa_reference = 'FAIL', data.reference
    state.reviewed_by, state.reviewed_at = user.badge, now
    item.dimensional, item.dimension_at, item.reinspection_due = 'Not started', None, True
    handoff = record_transfer(s, item, selected, user, now, notes=data.reason,
        scan_method='flow_item_verification', scanned_item_id=data.scanned_item_id, flow_step=18)
    change_phase(state, plan, 'ndt_rework' if state.test_kind == 'ndt' else 'pressure_rework', now)
    _event(s, item, plan, user.badge, 'fail', 18, now, data.reference, data.reason,
        {**context, 'test_result': 'FAIL', 'report': report_snapshot(state),
            'exception_id': row.id, 'return_step': 17,
            'return_to': dict(state.origin_snapshot), 'handoff': handoff,
            'next_step': 17, 'next_phase': state.phase}, step_definition=definition)
    _sync(s, item, user.badge, 17, now, 'Failed test returned for mandatory correction')
    _commit(s)
    return detail(s, item, user)


def project_step_states(states, state):
    """Decorate existing numbered-step projections without fabricating passes."""
    if state is None:
        return states
    if isinstance(states, dict):
        rows = project_step_states([{'number': number, 'state': value}
                                    for number, value in states.items()], state)
        return {row['number']: row['state'] for row in rows}
    rows = [dict(row) for row in states]
    for row in rows:
        number = row.get('number', row.get('step'))
        status_key = 'status' if 'status' in row else 'state'
        if number == 17:
            row['title'] = 'Determine if Spool need to be sent to Testing'
        if state.decision == 'NO' and number in (18, 19):
            row.update({status_key: 'not_required', 'completed_at': None,
                        'last_actor': None, 'not_required_reason': 'Testing decision recorded as NO'})
        elif number in (17, 18, 19) and state.phase in ACTIVE_PHASES:
            # NDT completion cannot credit the later pressure-test cycle.
            if PHASE_STEP[state.phase] == number:
                row[status_key] = 'current'
            elif (state.phase not in ('pressure_qa', 'floor_before_paint') or
                  state.phase == 'pressure_qa' and number == 19):
                row.update({status_key: 'pending', 'completed_at': None, 'last_actor': None})
    return rows


