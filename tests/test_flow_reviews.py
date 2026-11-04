"""Per-spool QA002/003 evidence is readable without creating approvals or work."""

from copy import deepcopy
import datetime as dt
import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from conftest import BADGES
from flow_reviews import spool_review_rows


BASE = dt.datetime(2026, 10, 1, 9, tzinfo=dt.timezone.utc)


@pytest.fixture
def flow(application):
    return importlib.import_module('flow')


def definitions(flow, version=None):
    plan = SimpleNamespace(catalog_version=version or flow.VERSION)
    return {number: flow.step_definition(plan, number) for number in (10, 11, 14, 15)}


def plan(current_step=15, *, status='active', baseline_step=9):
    return {'status': status, 'current_step': current_step, 'baseline_step': baseline_step}


def decision(sequence, step, action='advance', *, actor=BADGES['inspector'], data=None, at=None):
    return {'id': sequence, 'sequence': sequence, 'step': step, 'action': action,
            'actor': actor, 'at': (at or BASE + dt.timedelta(minutes=sequence)).isoformat(),
            'reference': f'REVIEW-{step}-{sequence}', 'notes': f'Recorded observation {sequence}',
            'data': data or {}}


def finding(number=15, identifier=7, *, opened_at=None):
    return {'id': identifier, 'step': number, 'return_step': {11: 10, 15: 14}[number],
            'reason': 'Weld profile requires correction', 'reference': f'FAIL-{identifier}',
            'opened_by': BADGES['inspector'],
            'opened_at': (opened_at or BASE + dt.timedelta(minutes=2)).isoformat(),
            'closed_at': None}


@pytest.mark.parametrize('version', ['CLM-25-v1', 'CLM-24-v6'])
def test_saved_catalog_tasks_and_independent_signed_decisions(flow, version):
    saved = definitions(flow, version)
    original = deepcopy(saved)
    events = [decision(1, 11), decision(2, 14, actor=BADGES['process_welder'])]
    first, last = spool_review_rows(plan(), saved, events)
    assert saved == original
    assert first['checks'] == saved[11]['checks']
    assert last['checks'] == saved[15]['checks']
    assert [first['review_key'], last['review_key']] == ['QA-002', 'QA-003']
    assert first['qa'] and last['qa']
    assert first['catalog_version'] == last['catalog_version'] == version
    assert first['status'] == 'completed' and not first['needs_reinspection']
    assert first['completed_at'] == events[0]['at']
    assert first['latest_review']['result'] == 'PASS'
    assert first['latest_review']['actor'] == BADGES['inspector']
    assert first['latest_review']['reference'] == 'REVIEW-11-1'
    assert last['status'] == 'current' and last['is_current']
    assert last['latest_review'] is None


@pytest.mark.parametrize('state,events,expected', [
    (None, [], ['pending', 'pending']),
    (plan(16, baseline_step=16), [], ['not_recorded', 'not_recorded']),
    (plan(None, status='completed'), [decision(1, 15, 'admin_release')], ['pending', 'pending']),
    (plan(None, status='completed'), [decision(1, 15, data={'phase_only': True})], ['pending', 'pending']),
])
def test_unstarted_baseline_and_administrative_release_never_invent_pass(flow, state, events, expected):
    rows = spool_review_rows(state, definitions(flow), events)
    assert [row['status'] for row in rows] == expected
    assert all(row['latest_review'] is None and row['completed_at'] is None for row in rows)
    assert all(not row['needs_reinspection'] for row in rows)


@pytest.mark.parametrize('action', ['reopen', 'rework_return', 'admin_return_to_work'])
def test_explicit_return_preserves_history_but_requires_fresh_review(flow, action):
    events = [decision(1, 11), decision(2, 15),
              decision(3, 14, action, data={'return_step': 14})]
    first, last = spool_review_rows(plan(14), definitions(flow), events)
    assert first['status'] == 'completed' and not first['needs_reinspection']
    assert last['status'] == 'rework' and last['needs_reinspection']
    assert last['latest_review']['result'] == 'PASS'
    assert last['latest_review']['reference'] == 'REVIEW-15-2'
    assert last['completed_at'] is None and last['last_actor'] is None
    # A return to fit-up invalidates both downstream reviews, not their history.
    events.append(decision(4, 10, action, data={'return_step': 10}))
    rows = spool_review_rows(plan(10), definitions(flow), events)
    assert all(row['needs_reinspection'] and row['status'] == 'rework' for row in rows)
    assert all(row['latest_review']['result'] == 'PASS' for row in rows)


def test_failure_correction_and_reinspection_keep_their_own_signed_evidence(flow):
    failed = decision(2, 15, 'fail', data={'exception_id': 7, 'return_step': 14})
    corrected = decision(3, 14, actor=BADGES['process_welder'],
        data={'reworked_exception_ids': [7], 'resolution': 'Repaired the weld profile to the approved WPS'})
    events = [decision(1, 11), failed, corrected]
    first, last = spool_review_rows(plan(15), definitions(flow), events, [finding()])
    assert first['status'] == 'completed'
    assert last['is_current'] and last['status'] == 'current' and last['needs_reinspection']
    assert last['latest_review']['result'] == 'FAIL'
    assert last['latest_review']['actor'] == BADGES['inspector']
    assert last['latest_review']['at'] == failed['at']
    defect = last['defects'][0]
    assert defect['reason'] == finding()['reason']
    assert defect['reference'] == 'FAIL-7' and defect['opened_by'] == BADGES['inspector']
    assert not defect['needs_completion']
    assert defect['completion']['actor'] == BADGES['process_welder']
    assert defect['completion']['reference'] == corrected['reference']
    assert defect['completion']['description'] == corrected['data']['resolution']
    events.append(decision(4, 15, data={'closed_exception_ids': [7], 'resolution': 'Fresh QA inspection passed'}))
    closed = {**finding(), 'closed_at': events[-1]['at']}
    passed = spool_review_rows(plan(16), definitions(flow), events, [closed])[1]
    assert passed['status'] == 'completed' and not passed['needs_reinspection']
    assert passed['latest_review']['result'] == 'PASS' and passed['latest_review']['event_id'] == 4
    assert passed['defects'] == []


@pytest.mark.parametrize('correction', [
    decision(1, 14, data={'reworked_exception_ids': [7], 'resolution': 'Old correction'}),
    decision(3, 14, data={'reworked_exception_ids': [8], 'resolution': 'Unrelated correction'}),
    decision(3, 10, data={'reworked_exception_ids': [7], 'resolution': 'Wrong production step'}),
    decision(3, 14, data={'reworked_exception_ids': [7], 'resolution': 'yes'}),
    decision(3, 14, data={'reworked_exception_ids': [7], 'resolution': 'Old timestamp'}, at=BASE),
])
def test_only_linked_correction_after_failure_completes_the_required_work(flow, correction):
    failed = decision(2, 15, 'fail', data={'exception_id': 7, 'return_step': 14})
    events = sorted([failed, correction], key=lambda row: row['sequence'])
    row = spool_review_rows(plan(14), definitions(flow), events, [finding()])[1]
    assert row['needs_reinspection'] and row['status'] == 'rework'
    assert row['defects'][0]['needs_completion'] and row['defects'][0]['completion'] is None


def test_removed_spool_is_not_a_current_inspection_task(flow):
    row = spool_review_rows(plan(11), definitions(flow), removed=True)[0]
    assert row['status'] == 'pending' and not row['is_current']


def seed_family(api, flow, *, count=3, with_reviews=True):
    """Seed explicit local historical fixtures; no production records are used."""
    tracking = importlib.import_module('tracking')
    identities = importlib.import_module('order_spools')
    spool_ids = [f'QA-SPOOL-{index}' for index in range(count)]
    with api.session_factory() as session:
        session.add(tracking.Project(id='QA-PRJ', name='Local QA projection test', created_by=BADGES['admin']))
        session.add_all(api.application.Item(id=key, description='Local review fixture ' + key,
            kind=kind, project='QA-PRJ', google_part_number='SPOOL-NUMBER' if kind == 'Spool' else '',
            location='Local fabrication bay', handler=BADGES['handler'], welds_required=0)
            for key, kind in [('QA-ASSEMBLY', 'Assembly'), ('QA-COMPONENT', 'Part')]
                + [(key, 'Spool') for key in spool_ids])
        session.flush()
        session.add_all(tracking.SpoolPlan(item_id=key, project_id='QA-PRJ', assembly_id='QA-ASSEMBLY',
            planned_welds=0, zero_weld_reason='Local fixture without configured welds', created_by=BADGES['admin'])
            for key in spool_ids)
        session.add_all(identities.SpoolQrIdentity(item_id=key, spool_number='SPOOL-NUMBER',
            normalized_number='spool-number', sequence=index + 1, display_code=f'SPOOL-NUMBER-{index + 1}',
            normalized_code=f'spool-number-{index + 1}', created_by=BADGES['admin'], source='local-test')
            for index, key in enumerate(spool_ids))
        session.add(flow.ComponentLink(component_id='QA-COMPONENT', spool_id=spool_ids[0], assigned_by=BADGES['admin']))
        if with_reviews:
            for index, key in enumerate(spool_ids[:2]):
                session.add(flow.FlowPlan(item_id=key, catalog_version=flow.VERSION if index == 0 else None,
                    route='spool', current_step=16 if index == 0 else 15, status='active',
                    baseline_step=9, started_by=BADGES['admin']))
                values = [decision(1, 11), decision(2, 15)]
                if index:
                    exception = flow.FlowException(item_id=key, step=15, return_step=14,
                        reason='Weld profile requires correction', reference='FAIL-SECOND-SPOOL',
                        opened_by=BADGES['inspector'], opened_at=BASE + dt.timedelta(minutes=2))
                    session.add(exception)
                    session.flush()
                    values = [decision(1, 11), decision(2, 15, 'fail',
                        data={'exception_id': exception.id, 'return_step': 14}),
                        decision(3, 14, actor=BADGES['process_welder'], data={
                            'reworked_exception_ids': [exception.id], 'resolution': 'Corrected weld profile'})]
                for value in values:
                    payload = {key: value[key] for key in ('sequence', 'step', 'action', 'actor', 'reference', 'notes', 'data')}
                    payload['at'] = dt.datetime.fromisoformat(value['at'])
                    payload['reference'] = key + ':' + payload['reference']
                    session.add(flow.FlowEvent(item_id=key, **payload))
                # Normal later welding/work timestamps must not erase fit-up QA.
                session.get(api.application.Item, key).last_work_at = BASE + dt.timedelta(hours=1)
        session.commit()
    return spool_ids


def get_detail(api, item_id, *, role='inspector'):
    response = api.get('/api/flow/items/' + item_id, role=role)
    assert response.status_code == 200, response.text
    return response.json()


def test_assembly_and_component_expose_only_their_actual_spool_reviews_read_only(api, flow):
    spool_ids = seed_family(api, flow)
    statements = []
    engine = api.session_factory.kw['bind']

    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement.upper().lstrip())

    event.listen(engine, 'before_cursor_execute', observe)
    try:
        assembly = get_detail(api, 'QA-ASSEMBLY', role='handler')
        selected = get_detail(api, spool_ids[1])
        component = get_detail(api, 'QA-COMPONENT')
        not_started = get_detail(api, spool_ids[2])
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert not any(sql.startswith(('INSERT ', 'UPDATE ', 'DELETE ', 'LOCK '))
                   or 'FOR UPDATE' in sql or 'PG_ADVISORY' in sql for sql in statements)
    assert assembly['flow'] is None and assembly['qa_reviews'] == []
    groups = {row['item_id']: row for row in assembly['spool_reviews']}
    assert set(groups) == set(spool_ids)
    first, second, third = [groups[key] for key in spool_ids]
    assert first['spool_number'] == second['spool_number'] == 'SPOOL-NUMBER'
    assert first['qr_alias'] != second['qr_alias']
    assert first['catalog_version'] == flow.VERSION and second['catalog_version'] == flow.LEGACY_VERSION
    assert all(row['status'] == 'completed' for row in first['reviews'])
    assert first['reviews'][1]['latest_review']['reference'].startswith(spool_ids[0] + ':')
    assert second['reviews'][0]['status'] == 'completed'
    assert second['reviews'][1]['status'] == 'current' and second['reviews'][1]['needs_reinspection']
    assert second['reviews'][1]['latest_review']['result'] == 'FAIL'
    assert second['reviews'][1]['latest_review']['reference'].startswith(spool_ids[1] + ':')
    assert second['reviews'][1]['defects'][0]['completion']['actor'] == BADGES['process_welder']
    assert selected['qa_reviews'] == second['reviews']
    assert selected['spool_reviews'] == []
    assert [row['item_id'] for row in component['spool_reviews']] == [spool_ids[0]]
    assert component['spool_reviews'][0]['reviews'] == first['reviews']
    assert not third['has_flow'] and third['route_status'] == 'not_started'
    assert not_started['flow'] is None and not_started['qa_reviews'] == third['reviews']
    assert all(row['latest_review'] is None and row['status'] == 'pending' for row in third['reviews'])
    with api.session_factory() as session:
        assert session.get(flow.FlowPlan, 'QA-ASSEMBLY') is None
        assert session.get(flow.FlowPlan, spool_ids[2]) is None
        assert session.get(flow.FlowTestingState, 'QA-ASSEMBLY') is None


def test_review_batch_query_count_does_not_grow_per_spool_or_flush_pending_writes(api, flow):
    spool_ids = seed_family(api, flow, count=12, with_reviews=False)
    engine = api.session_factory.kw['bind']
    statements = []

    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement.upper().lstrip())

    with api.session_factory() as session:
        item = session.get(api.application.Item, spool_ids[0])
        original = item.description
        item.description = 'Uncommitted change must not be flushed by this read'
        event.listen(engine, 'before_cursor_execute', observe)
        try:
            one = flow.spool_review_records(session, spool_ids[:1])
            one_count = len(statements)
            statements.clear()
            many = flow.spool_review_records(session, spool_ids + spool_ids[:1])
            many_count = len(statements)
            assert flow.spool_review_records(session, []) == {}
        finally:
            event.remove(engine, 'before_cursor_execute', observe)
        assert one_count == many_count == 3
        assert all(sql.startswith('SELECT ') for sql in statements)
        assert len(one) == 1 and len(many) == len(spool_ids)
        assert item in session.dirty
        session.rollback()
        assert session.get(api.application.Item, spool_ids[0]).description == original
        assert list(session.scalars(select(flow.FlowPlan))) == []
