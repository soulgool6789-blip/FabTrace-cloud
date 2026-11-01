"""Selected-spool batches preserve the complete live QA/history projection."""
from contextlib import nullcontext
import datetime as dt

import pytest
from sqlalchemy import event, select, update

from conftest import BADGES
from test_read_projection import seed_accepted_materials, seed_tree


NOW = dt.datetime(2026, 1, 2, 12, tzinfo=dt.timezone.utc)


def seed_histories(api, count=8):
    from flow import FlowPlan
    from main import Item, Rework
    from production import SpoolProcessEvent
    from tracking import (RequirementEvidence, RequirementReview, SpoolPlan,
        TrackingHold, Weld, WeldRepair, WeldRequirement, WeldWork)
    identifiers = seed_tree(api, count)
    actor = BADGES['inspector']
    with api.session_factory() as s:
        for index, item_id in enumerate(identifiers[:-2]):
            item = s.get(Item, item_id)
            item.dimensional = 'Pass'
            item.last_work_at = NOW - dt.timedelta(hours=3)
            item.dimension_at = NOW - dt.timedelta(hours=2)
            s.get(SpoolPlan, item_id).planned_welds = 2
            for number in range(2):
                weld_id = f'{item_id}-W{number}'
                weld = Weld(id=weld_id, item_id=item_id, number=f'W{number}',
                    component_a='Piece A', heat_a='HEAT-A', mtr_a='MTR-A',
                    component_b='Piece B', heat_b='HEAT-B', mtr_b='MTR-B',
                    wps='WPS-01', wps_revision='C', cycle=2,
                    required_operations=['root', 'fill_cap'], created_by=actor,
                    completed_at=NOW - dt.timedelta(hours=3) if index != 2 else None)
                s.add(weld)
                s.flush()
                for cycle in (1, 2):
                    operations = ('root',) if index == 2 and cycle == 2 else ('root', 'fill_cap', 'complete')
                    s.add_all(WeldWork(weld_id=weld_id, cycle=cycle, operation=operation,
                        actor=BADGES['welder'], at=NOW - dt.timedelta(hours=4)) for operation in operations)
                s.add(WeldRepair(weld_id=weld_id, cycle=2, reason='Retained repair history',
                    opened_by=actor, opened_at=NOW - dt.timedelta(hours=6)))
                for ordinal, check in enumerate(('materials', 'procedure', 'none', 'welding_complete', 'none', 'none')):
                    req = WeldRequirement(item_id=item_id, weld_id=weld_id,
                        code=f'REQ-{ordinal}', label=f'Requirement {ordinal}', stage='release',
                        check_kind=check, status='not_applicable' if ordinal == 4 else 'accepted',
                        allow_na=ordinal == 4, evidence_required=True, cycle=2, created_by=actor)
                    s.add(req)
                    s.flush()
                    for cycle in (1, 2):
                        evidence = RequirementEvidence(requirement_id=req.id, cycle=cycle,
                            reference=f'REPORT-{cycle}', actor=actor, at=NOW - dt.timedelta(hours=3),
                            result='fail' if index != 0 and ordinal == 5 and cycle == 2 else 'pass')
                        s.add(evidence)
                        s.flush()
                        s.add(RequirementReview(requirement_id=req.id, evidence_id=evidence.id,
                            cycle=cycle, decision='not_applicable' if ordinal == 4 else 'accepted',
                            notes='Recorded scope decision', actor=actor, at=NOW - dt.timedelta(hours=2)))
                    if index != 0 and ordinal == 2:
                        # The stored accepted flag is deliberately stale. A
                        # later immutable evidence revision must block it.
                        s.add(RequirementEvidence(requirement_id=req.id, cycle=2,
                            reference='REPLACED-AFTER-REVIEW', result='pass', actor=actor, at=NOW))
            s.add(TrackingHold(item_id=item_id, weld_id=f'{item_id}-W0',
                reason='Retained weld hold', opened_by=actor,
                closed_at=None if index == 1 else NOW - dt.timedelta(hours=1)))
            s.add(TrackingHold(item_id=item_id, reason='Retained spool hold', opened_by=actor,
                closed_at=None if index == 2 else NOW - dt.timedelta(hours=1)))
            s.add(Rework(item_id=item_id, kind='Weld', reason='Retained spool rework',
                assigned=actor, closed_at=None if index == 1 else NOW - dt.timedelta(hours=1)))
            events = [('start', 'cutting_beveling', 'Cutting & beveling', 8),
                      ('move', 'welding', 'Welding', 6), ('pause', 'welding', 'Welding', 4)]
            if index % 2 == 0:
                events.append(('resume', 'welding', 'Welding', 3))
            for sequence, (action, key, name, hours) in enumerate(events, 1):
                s.add(SpoolProcessEvent(item_id=item_id, sequence=sequence, event=action,
                    process_key=key, process_name=name, actor=actor,
                    at=NOW - dt.timedelta(hours=hours), notes='Retained timing history'))
            if index == 1:
                s.add(FlowPlan(item_id=item_id, route='spool', current_step=6,
                    baseline_step=6, started_by=BADGES['admin']))
        s.commit()
    if count > 2:
        seed_accepted_materials(api, identifiers[0])
    return identifiers


def observe_read(api, function):
    statements = []
    engine = api.session_factory.kw['bind']

    def observe(connection, cursor, statement, parameters, context, many):
        statements.append((statement.upper().lstrip(), parameters))

    event.listen(engine, 'before_cursor_execute', observe)
    try:
        with api.session_factory() as s:
            result = function(s)
            assert 'fabtrace_read_projection' not in s.info
            assert 'tracking_read_snapshot' not in s.info
            assert 'tracking_read_snapshot_projection' not in s.info
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert not any(sql.startswith(('INSERT ', 'UPDATE ', 'DELETE ', 'LOCK '))
        or 'FOR UPDATE' in sql for sql, _ in statements)
    return result, statements


@pytest.mark.parametrize('view', ['details', 'overview', 'exceptions'])
def test_full_history_permissions_and_qa_payload_match_with_fewer_queries(api, monkeypatch, view):
    import flow
    import production
    import tracking
    from main import Employee, Item
    from read_projection import prime_projection, read_projection
    identifiers = seed_histories(api)
    monkeypatch.setattr(production, 'utcnow', lambda: NOW)
    monkeypatch.setattr(flow, 'utcnow', lambda: NOW)

    def read(s, enabled):
        users = [s.get(Employee, BADGES[role]) for role in ('inspector', 'handler')]
        if view == 'details':
            rows = [s.get(Item, item_id) for item_id in identifiers]
            with read_projection(s) if enabled else nullcontext():
                if enabled:
                    prime_projection(s, rows)
                    tracking.prime_tracking_read_snapshots(s, identifiers)
                return [[tracking.spool_dict(s, item, user) for item in rows] for user in users]
        with monkeypatch.context() as patch:
            if not enabled:
                patch.setattr(tracking, 'read_projection', lambda s: nullcontext(s))
            return getattr(tracking, view)('READ-PO', '', users[0], s)

    expected, before = observe_read(api, lambda s: read(s, False))
    actual, after = observe_read(api, lambda s: read(s, True))
    assert actual == expected, 'All histories, blockers, per-revision decisions and role permissions must match'
    assert len(after) < len(before) * 0.45, (view, len(before), len(after))
    if view == 'details':
        assert actual[0][0]['summary']['ready_to_release']
        assert actual[0][0]['summary']['qa_accepted'] == 2
        assert actual[0][1]['summary']['qa_accepted'] == 0
        assert actual[0][-1]['welds'] == []
        assert actual[0][-1]['production_process']['version'] == 0
        assert actual[0][0]['welds'][0]['requirements'][0]['permissions']['can_review']
        assert not actual[1][0]['welds'][0]['requirements'][0]['permissions']['can_review']


def test_new_request_sees_replaced_evidence_and_previously_empty_histories(api, monkeypatch):
    import production
    import tracking
    from main import Employee, Item
    from production import SpoolProcessEvent
    from read_projection import read_projection
    from tracking import RequirementEvidence, TrackingHold, WeldRequirement
    identifiers = seed_histories(api, 3)
    populated, empty = identifiers[0], identifiers[-1]
    monkeypatch.setattr(production, 'utcnow', lambda: NOW)
    with api.session_factory() as s, read_projection(s):
        tracking.prime_tracking_read_snapshots(s, identifiers)
        user = s.get(Employee, BADGES['inspector'])
        before = tracking.spool_dict(s, s.get(Item, populated), user)
        empty_before = tracking.spool_dict(s, s.get(Item, empty), user)
        assert before['summary']['ready_to_release']
        assert empty_before['holds'] == [] and empty_before['production_process']['version'] == 0
    with api.session_factory() as writer:
        req = writer.scalar(select(WeldRequirement).where(
            WeldRequirement.item_id == populated, WeldRequirement.code == 'REQ-2'))
        writer.add(RequirementEvidence(requirement_id=req.id, cycle=req.cycle,
            reference='NEW-FAILED-REVISION', result='fail', actor=BADGES['inspector']))
        writer.add(TrackingHold(item_id=empty, reason='New hold after empty read', opened_by=BADGES['inspector']))
        writer.add(SpoolProcessEvent(item_id=empty, sequence=1, event='start',
            process_key='welding', process_name='Welding', actor=BADGES['welder'], at=NOW))
        writer.commit()
    with api.session_factory() as s, read_projection(s):
        tracking.prime_tracking_read_snapshots(s, identifiers)
        user = s.get(Employee, BADGES['inspector'])
        current = tracking.spool_dict(s, s.get(Item, populated), user)
        empty_current = tracking.spool_dict(s, s.get(Item, empty), user)
        assert not current['summary']['ready_to_release']
        assert current['summary']['qa_accepted'] == 1
        assert empty_current['holds'][0]['reason'] == 'New hold after empty read'
        assert empty_current['production_process']['version'] == 1
    # Write gates never reuse a previous read projection's accepted status.
    with api.session_factory() as writer:
        assert 'fabtrace_read_projection' not in writer.info
        blockers = tracking.tracking_release_errors(writer, writer.get(Item, populated))
        assert any('Requirement 2' in blocker for blocker in blockers)


@pytest.mark.parametrize('mutation', ['dirty', 'flush', 'dml', 'commit', 'rollback'])
def test_mutations_invalidate_batch_even_inside_an_active_snapshot(api, mutation):
    import tracking
    from main import Rework
    from read_projection import projection_enabled, read_projection
    item_id = seed_tree(api, 1)[0]
    with api.session_factory() as s:
        row = Rework(item_id=item_id, kind='Weld', reason='Initially closed',
            assigned=BADGES['inspector'], closed_at=NOW)
        s.add(row)
        s.commit()
        with read_projection(s):
            tracking.prime_tracking_read_snapshots(s, [item_id])
            with tracking._read_snapshot(s, item_id) as original:
                assert not original['open_rework']
                if mutation == 'dml':
                    s.execute(update(Rework).where(Rework.id == row.id).values(closed_at=None))
                elif mutation == 'rollback':
                    s.rollback()
                else:
                    row.closed_at = None
                    if mutation != 'dirty':
                        getattr(s, mutation)()
                assert not projection_enabled(s)
                with tracking._read_snapshot(s, item_id) as current:
                    assert current['open_rework'] == (mutation != 'rollback')
            assert 'tracking_read_snapshot' not in s.info
        assert 'fabtrace_read_projection' not in s.info


def test_empty_histories_are_retained_and_batches_are_bounded(api):
    import tracking
    from read_projection import read_projection
    identifiers = seed_tree(api, 405)

    def read(s):
        with read_projection(s):
            tracking.prime_tracking_read_snapshots(s, identifiers)
            tracking.prime_tracking_read_snapshots(s, identifiers)
            for item_id in identifiers:
                with tracking._read_snapshot(s, item_id) as snapshot:
                    assert not snapshot['welds'] and not snapshot['requirements']
                    assert not snapshot['evidence'] and not snapshot['reviews']
                    assert not snapshot['holds'] and not snapshot['open_rework']
                    assert snapshot['production_process']['version'] == 0
    _, statements = observe_read(api, read)
    assert len(statements) <= 26, len(statements)
    assert all(len(parameters) <= 400 for _, parameters in statements)


def test_response_container_edits_do_not_modify_sibling_tracking_snapshots(api):
    import tracking
    from read_projection import read_projection
    item_id = seed_histories(api, 3)[0]
    with api.session_factory() as s, read_projection(s):
        tracking.prime_tracking_read_snapshots(s, [item_id])
        with tracking._read_snapshot(s, item_id) as first:
            requirement_id = first['requirements'][0].id
            first['holds'].clear()
            first['evidence'][requirement_id].clear()
            first['production_process']['events'].clear()
        with tracking._read_snapshot(s, item_id) as second:
            assert second['holds']
            assert second['evidence'][requirement_id]
            assert second['production_process']['events']
