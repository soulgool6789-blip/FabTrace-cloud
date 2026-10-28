"""Append-only spool process timing, independent of weld/QA acceptance.

The recorded intervals are calendar time in a process, not employee labor
hours. A spool has one current visit; moving closes it and opens the next at
the same instant. Explicit pauses distinguish waiting time without removing
that time from the total dwell. No timestamps are inferred for older work.
"""

import datetime as dt
from collections.abc import Mapping
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from main import Base, Employee, Item, audit, auth, db, lock_item, permit, require_unreleased, utcnow
from tracking import ROLES, _require_plan


router = APIRouter(prefix='/api/tracking', tags=['production timing'])
UTC = dt.timezone.utc
PROCESS_CATALOG = (
    {'key': 'material_prep', 'label': 'Material preparation'},
    {'key': 'cutting_beveling', 'label': 'Cutting & beveling'},
    {'key': 'fit_up', 'label': 'Fit-up'},
    {'key': 'welding', 'label': 'Welding'},
    {'key': 'nde', 'label': 'NDE / testing'},
    {'key': 'pwht', 'label': 'PWHT'},
    {'key': 'dimensional', 'label': 'Dimensional inspection'},
    {'key': 'coating', 'label': 'Coating / painting'},
    {'key': 'final_qa', 'label': 'Final QA'},
    {'key': 'dispatch', 'label': 'Ready for dispatch'},
)
PROCESS_NAMES = {row['key']: row['label'] for row in PROCESS_CATALOG}
EVENT_KEYS = 'id item_id sequence event process_key process_name actor at notes'.split()


class SpoolProcessEvent(Base):
    __tablename__ = 'tracking_process_events'
    __table_args__ = (
        UniqueConstraint('item_id', 'sequence', name='uq_tracking_process_sequence'),
        CheckConstraint('sequence > 0', name='ck_tracking_process_sequence_positive'),
        CheckConstraint("event IN ('start', 'move', 'pause', 'resume', 'finish', 'release')", name='ck_tracking_process_event'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(60), ForeignKey('items.id'), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event = Column(String(20), nullable=False)
    process_key = Column(String(50), nullable=False)
    process_name = Column(String(80), nullable=False)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    notes = Column(Text, nullable=False, default='')


class ProcessIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    action: Literal['start', 'move', 'pause', 'resume', 'finish']
    expected_version: int = Field(ge=0, strict=True)
    process_key: str | None = Field(default=None, min_length=1, max_length=50)
    process_name: str | None = Field(default=None, min_length=2, max_length=80)
    notes: str = Field(default='', max_length=2000)

    @field_validator('process_key', 'process_name', 'notes')
    @classmethod
    def reject_null_character(cls, value):
        if value is not None and '\x00' in value:
            raise ValueError('Text cannot contain a null character')
        return value

    @model_validator(mode='after')
    def validate_action_fields(self):
        if self.action in ('start', 'move'):
            if self.process_key not in (*PROCESS_NAMES, 'custom'):
                raise ValueError('Choose a listed production process or a custom process')
            if self.process_key == 'custom':
                if self.process_name is None:
                    raise ValueError('A custom process needs a name')
                self.process_name = ' '.join(self.process_name.split())
                if len(self.process_name) < 2:
                    raise ValueError('A custom process name needs at least two characters')
            elif self.process_name is not None:
                raise ValueError('Listed production processes use their existing name')
        elif self.process_key is not None or self.process_name is not None:
            raise ValueError('Only start or move selects a production process')
        if self.action == 'pause' and len(self.notes) < 3:
            raise ValueError('Record a pause reason of at least three characters')
        return self


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _value(row, key):
    return row[key] if isinstance(row, Mapping) else getattr(row, key)


def _process_identity(key, name):
    # Names of catalog processes may change in a later release; their stable
    # key continues to identify one total. Custom spelling/case is normalized.
    return (key, ' '.join(name.split()).casefold() if key == 'custom' else '')


def _group_key(key, name):
    identity = _process_identity(key, name)
    return key + ':' + identity[1] if key == 'custom' else key


def _event_dict(row):
    result = {key: _value(row, key) for key in EVENT_KEYS}
    result['at'] = _utc(result['at']).isoformat()
    return result


def summarize_process_events(item_id, events, as_of):
    """Pure projection used by the API and a consistent-snapshot Excel export.

    Datetimes from SQLite have no timezone; they represent the same stored UTC
    instants. Durations use integer microseconds internally so pause segments
    and visit totals add up without accumulated rounding. A read during a
    backwards clock adjustment never makes recorded time decrease below the
    latest event. Mutations reject a clock earlier than the previous event.
    """
    rows = sorted(events, key=lambda row: _value(row, 'sequence'))
    as_of = _utc(as_of)
    if rows:
        as_of = max(as_of, _utc(_value(rows[-1], 'at')))
    visits = []
    current = None
    last_at = None

    def accrue(visit, at):
        microseconds = max(0, (at - visit['_cursor']) // dt.timedelta(microseconds=1))
        visit['_paused_us' if visit['status'] == 'paused' else '_active_us'] += microseconds
        visit['_cursor'] = max(visit['_cursor'], at)

    def close(visit, row, at):
        visit['ended_at'] = at.isoformat()
        visit['ended_by'] = _value(row, 'actor')
        visit['status'] = 'finished'
        visit['end_reason'] = _value(row, 'event')

    for row in rows:
        at = _utc(_value(row, 'at'))
        # Preserve a nonnegative projection even if unsupported direct writes
        # introduced an out-of-order clock. API writes prevent this situation.
        if last_at is not None:
            at = max(at, last_at)
        last_at = at
        event = _value(row, 'event')
        if current is not None:
            accrue(current, at)
        if event in ('start', 'move'):
            if current is not None:
                close(current, row, at)
            current = {
                'id': _value(row, 'sequence'),
                'process_key': _value(row, 'process_key'),
                'process_name': _value(row, 'process_name'),
                'group_key': _group_key(_value(row, 'process_key'), _value(row, 'process_name')),
                'started_at': at.isoformat(), 'ended_at': None,
                'started_by': _value(row, 'actor'), 'ended_by': None,
                'status': 'running', 'end_reason': None,
                '_active_us': 0, '_paused_us': 0, '_cursor': at,
            }
            visits.append(current)
        elif current is not None:
            if event == 'pause':
                current['status'] = 'paused'
            elif event == 'resume':
                current['status'] = 'running'
            elif event in ('finish', 'release'):
                close(current, row, at)
                current = None

    if current is not None:
        accrue(current, as_of)

    total_active = 0
    total_paused = 0
    grouped = {}
    public_visits = []
    for visit in visits:
        active, paused = visit['_active_us'], visit['_paused_us']
        public_visits.append({
            **{key: value for key, value in visit.items() if not key.startswith('_')},
            'elapsed_seconds': (active + paused) / 1_000_000,
            'active_seconds': active / 1_000_000,
            'paused_seconds': paused / 1_000_000,
        })
        identity = _process_identity(visit['process_key'], visit['process_name'])
        group = grouped.setdefault(identity, {
            'process_key': visit['process_key'], 'process_name': visit['process_name'],
            'group_key': visit['group_key'],
            'visits': 0, '_active_us': 0, '_paused_us': 0,
        })
        group['visits'] += 1
        group['_active_us'] += active
        group['_paused_us'] += paused
        total_active += active
        total_paused += paused
    by_process = [{
        'process_key': row['process_key'], 'process_name': row['process_name'],
        'group_key': row['group_key'],
        'visits': row['visits'],
        'elapsed_seconds': (row['_active_us'] + row['_paused_us']) / 1_000_000,
        'active_seconds': row['_active_us'] / 1_000_000,
        'paused_seconds': row['_paused_us'] / 1_000_000,
    } for row in grouped.values()]
    return {
        'item_id': item_id, 'version': _value(rows[-1], 'sequence') if rows else 0,
        'as_of': as_of.isoformat(),
        'status': current['status'] if current is not None else ('finished' if rows else 'not_started'),
        'current': public_visits[-1] if current is not None else None,
        'totals': {
            'visits': len(public_visits),
            'elapsed_seconds': (total_active + total_paused) / 1_000_000,
            'active_seconds': total_active / 1_000_000,
            'paused_seconds': total_paused / 1_000_000,
        },
        'by_process': by_process, 'visits': public_visits,
        'events': [_event_dict(row) for row in rows],
    }


def process_snapshot(s, item_id, as_of=None, events=None):
    if events is None:
        events = s.scalars(select(SpoolProcessEvent).where(
            SpoolProcessEvent.item_id == item_id).order_by(SpoolProcessEvent.sequence)).all()
    snapshot = summarize_process_events(item_id, events, as_of if as_of is not None else utcnow())
    if s is not None:
        from flow import FlowPlan
        flow = s.get(FlowPlan, item_id)
        snapshot.update(flow_managed=flow is not None,
                        flow_step=flow.current_step if flow else None,
                        flow_status=flow.status if flow else None)
    return snapshot


def compact_process_summary(snapshot):
    return {key: snapshot.get(key) for key in ('item_id', 'version', 'as_of', 'status', 'current', 'totals',
                                              'flow_managed', 'flow_step', 'flow_status')}


def _append_event(s, item, actor, event, process_key, process_name, notes, at, version):
    row = SpoolProcessEvent(item_id=item.id, sequence=version + 1, event=event,
        process_key=process_key, process_name=process_name, actor=actor, at=at, notes=notes)
    s.add(row)
    s.flush()
    item.updated_at = at
    audit(s, item.id, actor, 'TRACKING_PROCESS_EVENT', {
        'process_event_id': row.id, 'sequence': row.sequence, 'event': event, 'action': event,
        'process_key': process_key, 'process_name': process_name, 'notes': notes,
        'at': at.isoformat(),
    })
    return row


def _check_clock(snapshot, at):
    if snapshot['events'] and at < dt.datetime.fromisoformat(snapshot['events'][-1]['at']):
        raise HTTPException(409, 'Server clock precedes the latest recorded process event; retry when time has caught up. No changes were saved.')


def finish_on_release(s, item, actor, at):
    """Close an open visit in the same locked transaction as final release."""
    at = _utc(at)
    snapshot = process_snapshot(s, item.id, as_of=at)
    current = snapshot['current']
    if current is None:
        return
    _check_clock(snapshot, at)
    _append_event(s, item, actor, 'release', current['process_key'], current['process_name'],
        'Process timing closed automatically by final release.', at, snapshot['version'])


def sync_flow_process(s, item, actor, step, at, notes=''):
    """Use the existing process clock for each numbered traveler step.

    Caller holds the topology and Item locks and owns the transaction. A return
    to the same numbered step is a new visit, preserving the earlier attempt.
    Quality release may already have closed a clock; the next custody/shipping
    step can then start without reopening the accepted fabrication record.
    """
    at = _utc(at)
    snapshot = process_snapshot(s, item.id, as_of=at)
    _check_clock(snapshot, at)
    current = snapshot['current']
    if step is None:
        if current is not None:
            _append_event(s, item, actor, 'finish', current['process_key'], current['process_name'],
                          notes or 'Numbered process route completed.', at, snapshot['version'])
        return
    key = f"clm_{step['number']:02d}"
    name = f"{step['number']}. {step['title']}"
    _append_event(s, item, actor, 'move' if current else 'start', key, name,
                  notes or 'Entered numbered process step.', at, snapshot['version'])


def _timing_flow(s, item):
    from flow import FlowPlan
    flow = s.get(FlowPlan, item.id)
    if flow is None:
        _require_plan(s, item)
    return flow


@router.get('/processes')
def get_processes(u: Employee = Depends(auth)):
    return list(PROCESS_CATALOG)


@router.get('/spools/{item_id}/process')
def get_process(item_id: str, u: Employee = Depends(auth), s: Session = Depends(db)):
    item = s.get(Item, item_id)
    if item is None:
        raise HTTPException(404, 'Item not found')
    _timing_flow(s, item)
    return process_snapshot(s, item_id)


@router.post('/spools/{item_id}/process', status_code=201)
def record_process(item_id: str, data: ProcessIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    permit(u, *ROLES)
    from flow import lock_topology
    lock_topology(s)
    item = lock_item(s, item_id)
    flow = _timing_flow(s, item)
    if flow is not None:
        if data.action not in ('pause', 'resume') or flow.status != 'active':
            raise HTTPException(409, 'Use Process flow to advance this numbered traveler. Its timer only supports pause and resume here.')
        if item.released and flow.current_step not in (16, 23, 24):
            require_unreleased(item)
    else:
        require_unreleased(item)
    at = _utc(utcnow())
    snapshot = process_snapshot(s, item_id, as_of=at)
    if data.expected_version != snapshot['version']:
        raise HTTPException(409, 'Process timing changed since you opened it; refresh and retry. No changes were saved.')
    _check_clock(snapshot, at)
    current = snapshot['current']
    if data.action == 'start' and current is not None:
        raise HTTPException(409, 'A process is already open; move it to the next process or finish it first')
    if data.action != 'start' and current is None:
        raise HTTPException(409, 'No process is currently open; start a process first')
    if data.action == 'pause' and snapshot['status'] != 'running':
        raise HTTPException(409, 'The current process is already paused')
    if data.action == 'resume' and snapshot['status'] != 'paused':
        raise HTTPException(409, 'The current process is not paused')
    if data.action in ('start', 'move'):
        key = data.process_key
        name = data.process_name if key == 'custom' else PROCESS_NAMES[key]
        if current and _process_identity(key, name) == _process_identity(current['process_key'], current['process_name']):
            raise HTTPException(409, 'This spool is already in that process; finish the current visit before starting another visit to the same process')
    else:
        key, name = current['process_key'], current['process_name']
    try:
        _append_event(s, item, u.badge, data.action, key, name, data.notes, at, snapshot['version'])
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, 'Another process update was saved first; refresh and retry. No changes were saved.') from None
    return process_snapshot(s, item_id)
