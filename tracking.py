"""Project, spool and individual-weld tracking.

Enrollment is explicit: existing Items keep their legacy workflow until a
SpoolPlan is created.  All changes to an enrolled spool take its existing Item
row lock first.  Requirements, submitted evidence and review decisions are
different records; neither uploading a reference nor finishing welding grants
QA acceptance.  These tables add to, rather than migrate, legacy production
records.
"""

import datetime as dt
import secrets
from contextlib import contextmanager
from functools import wraps
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint, select, text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from read_projection import (PROJECTION_MISSING, prime_projection, prime_rows,
    projection_enabled, projection_get, projection_put, read_get, read_projection, read_cached)

from main import (
    Audit, Base, Employee, Item, Rework, asdict, audit, auth, db, lock_item,
    permit, require_unreleased, utcnow,
)


router = APIRouter(prefix='/api/tracking', tags=['tracking'])
from permissions import (Role, ROLE_IDS, WELD_OPERATIONS, can_record_weld_operation,
    can_submit_requirement_evidence, has_capability)
ROLES = ROLE_IDS
ACCEPTED = ('accepted', 'not_applicable')


def new_id(prefix):
    return prefix + '-' + secrets.token_hex(12).upper()


class Project(Base):
    __tablename__ = 'tracking_projects'
    id = Column(String(80), primary_key=True)
    name = Column(String(200), nullable=False)
    client = Column(String(200), nullable=False, default='')
    description = Column(Text, nullable=False, default='')
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Subproject(Base):
    __tablename__ = 'tracking_subprojects'
    id = Column(String(80), primary_key=True)
    project_id = Column(String(80), ForeignKey('tracking_projects.id'), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default='')
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class SpoolPlan(Base):
    __tablename__ = 'tracking_spool_plans'
    item_id = Column(String(60), ForeignKey('items.id'), primary_key=True)
    project_id = Column(String(80), ForeignKey('tracking_projects.id'), nullable=False, index=True)
    subproject_id = Column(String(80), ForeignKey('tracking_subprojects.id'), index=True)
    assembly_id = Column(String(60), ForeignKey('items.id'), index=True)
    planned_welds = Column(Integer, nullable=False)
    drawing_revision = Column(String(80), nullable=False, default='')
    due_date = Column(String(10))
    notes = Column(Text, nullable=False, default='')
    zero_weld_reason = Column(Text, nullable=False, default='')
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class RequirementTemplate(Base):
    __tablename__ = 'tracking_requirement_templates'
    __table_args__ = (UniqueConstraint('code', 'revision', name='uq_tracking_template_revision'),)
    id = Column(String(60), primary_key=True)
    code = Column(String(80), nullable=False)
    name = Column(String(200), nullable=False)
    revision = Column(Integer, nullable=False)
    source = Column(Text, nullable=False, default='')
    requirements = Column(JSON, nullable=False)
    required_operations = Column(JSON, nullable=False)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Weld(Base):
    __tablename__ = 'tracking_welds'
    __table_args__ = (UniqueConstraint('item_id', 'number', name='uq_tracking_spool_weld_number'),)
    id = Column(String(60), primary_key=True)
    item_id = Column(String(60), ForeignKey('items.id'), nullable=False, index=True)
    number = Column(String(80), nullable=False)
    description = Column(String(500), nullable=False, default='')
    joint_type = Column(String(80), nullable=False, default='')
    size = Column(String(80), nullable=False, default='')
    wall_thickness = Column(String(80), nullable=False, default='')
    drawing_revision = Column(String(80), nullable=False, default='')
    component_a = Column(String(160), nullable=False, default='')
    heat_a = Column(String(160), nullable=False, default='')
    mtr_a = Column(String(300), nullable=False, default='')
    component_b = Column(String(160), nullable=False, default='')
    heat_b = Column(String(160), nullable=False, default='')
    mtr_b = Column(String(300), nullable=False, default='')
    wps = Column(String(160), nullable=False, default='')
    wps_revision = Column(String(80), nullable=False, default='')
    template_id = Column(String(60), ForeignKey('tracking_requirement_templates.id'))
    required_operations = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    cycle = Column(Integer, nullable=False, default=1)
    completed_at = Column(DateTime(timezone=True))
    completed_by = Column(String(80), ForeignKey('employees.badge'))
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class WeldRequirement(Base):
    __tablename__ = 'tracking_requirements'
    __table_args__ = (UniqueConstraint('item_id', 'weld_id', 'code', name='uq_tracking_weld_requirement'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(60), ForeignKey('items.id'), nullable=False, index=True)
    weld_id = Column(String(60), ForeignKey('tracking_welds.id'), index=True)
    code = Column(String(80), nullable=False)
    label = Column(String(240), nullable=False)
    stage = Column(String(30), nullable=False)
    allow_na = Column(Boolean, nullable=False, default=False)
    evidence_required = Column(Boolean, nullable=False, default=True)
    source = Column(Text, nullable=False, default='')
    owner_role = Column(String(30), nullable=False, default='inspector')
    check_kind = Column(String(30), nullable=False, default='none')
    status = Column(String(30), nullable=False, default='pending')
    version = Column(Integer, nullable=False, default=1)
    cycle = Column(Integer, nullable=False, default=1)
    template_id = Column(String(60), ForeignKey('tracking_requirement_templates.id'))
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class RequirementEvidence(Base):
    __tablename__ = 'tracking_requirement_evidence'
    id = Column(Integer, primary_key=True, autoincrement=True)
    requirement_id = Column(Integer, ForeignKey('tracking_requirements.id'), nullable=False, index=True)
    cycle = Column(Integer, nullable=False)
    reference = Column(String(500), nullable=False)
    notes = Column(Text, nullable=False, default='')
    result = Column(String(20), nullable=False, default='recorded')
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class RequirementReview(Base):
    __tablename__ = 'tracking_requirement_reviews'
    id = Column(Integer, primary_key=True, autoincrement=True)
    requirement_id = Column(Integer, ForeignKey('tracking_requirements.id'), nullable=False, index=True)
    evidence_id = Column(Integer, ForeignKey('tracking_requirement_evidence.id'))
    cycle = Column(Integer, nullable=False)
    decision = Column(String(30), nullable=False)
    notes = Column(Text, nullable=False)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class WeldWork(Base):
    __tablename__ = 'tracking_weld_work'
    __table_args__ = (UniqueConstraint('weld_id', 'cycle', 'operation', name='uq_tracking_work_cycle_operation'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    weld_id = Column(String(60), ForeignKey('tracking_welds.id'), nullable=False, index=True)
    cycle = Column(Integer, nullable=False)
    operation = Column(String(30), nullable=False)
    notes = Column(Text, nullable=False, default='')
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class WeldRepair(Base):
    __tablename__ = 'tracking_weld_repairs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    weld_id = Column(String(60), ForeignKey('tracking_welds.id'), nullable=False, index=True)
    cycle = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    opened_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class TrackingHold(Base):
    __tablename__ = 'tracking_holds'
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(60), ForeignKey('items.id'), nullable=False, index=True)
    weld_id = Column(String(60), ForeignKey('tracking_welds.id'), index=True)
    reason = Column(Text, nullable=False)
    opened_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    closed_by = Column(String(80), ForeignKey('employees.badge'))
    closed_at = Column(DateTime(timezone=True))
    close_notes = Column(Text)


class InputModel(BaseModel):
    # Reject accidental reviewer/actor fields rather than silently ignoring
    # an attempt to impersonate another employee.
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class ProjectIn(InputModel):
    id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=2, max_length=200)
    client: str = Field(default='', max_length=200)
    description: str = Field(default='', max_length=5000)


class SubprojectIn(InputModel):
    id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    project_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default='', max_length=5000)


class PlanIn(InputModel):
    project_id: str = Field(min_length=1, max_length=80)
    subproject_id: str | None = Field(default=None, max_length=80)
    assembly_id: str | None = Field(default=None, max_length=60)
    planned_welds: int = Field(ge=0, le=10000)
    drawing_revision: str = Field(default='', max_length=80)
    due_date: dt.date | None = None
    notes: str = Field(default='', max_length=5000)
    zero_weld_reason: str = Field(default='', max_length=2000)
    expected_version: int | None = Field(default=None, ge=1)


Stage = Literal['before_welding', 'after_welding', 'release']
Check = Literal['none', 'materials', 'procedure', 'welding_complete']
Operation = Literal['root', 'fill_cap']


class RequirementIn(InputModel):
    code: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    label: str = Field(min_length=2, max_length=240)
    stage: Stage = 'release'
    source: str = Field(default='', max_length=3000)
    owner_role: Role = 'inspector'
    allow_na: bool = False
    evidence_required: bool = True
    check: Check = 'none'

    @model_validator(mode='after')
    def avoid_circular_work_gate(self):
        if self.stage == 'before_welding' and self.check == 'welding_complete':
            raise ValueError('A before-welding prerequisite cannot require welding to be complete')
        return self


def check_operations(operations):
    if not operations or len(operations) != len(set(operations)):
        raise ValueError('Choose at least one distinct required welding operation')
    return operations


class TemplateIn(InputModel):
    code: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=2, max_length=200)
    revision: int = Field(ge=1, le=100000)
    source: str = Field(default='', max_length=3000)
    required_operations: list[Operation] = Field(default_factory=lambda: ['root', 'fill_cap'], max_length=2)
    requirements: list[RequirementIn] = Field(min_length=1, max_length=100)

    @field_validator('required_operations')
    @classmethod
    def operations_valid(cls, value):
        return check_operations(value)


class WeldIn(InputModel):
    number: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    description: str = Field(default='', max_length=500)
    joint_type: str = Field(default='', max_length=80)
    size: str = Field(default='', max_length=80)
    wall_thickness: str = Field(default='', max_length=80)
    drawing_revision: str = Field(default='', max_length=80)
    component_a: str = Field(default='', max_length=160)
    heat_a: str = Field(default='', max_length=160)
    mtr_a: str = Field(default='', max_length=300)
    component_b: str = Field(default='', max_length=160)
    heat_b: str = Field(default='', max_length=160)
    mtr_b: str = Field(default='', max_length=300)
    wps: str = Field(default='', max_length=160)
    wps_revision: str = Field(default='', max_length=80)
    template_id: str | None = Field(default=None, max_length=60)
    required_operations: list[Operation] | None = Field(default=None, max_length=2)

    @field_validator('required_operations')
    @classmethod
    def operations_valid(cls, value):
        return check_operations(value) if value is not None else None


class WeldUpdate(InputModel):
    expected_version: int = Field(ge=1)
    description: str | None = Field(default=None, max_length=500)
    joint_type: str | None = Field(default=None, max_length=80)
    size: str | None = Field(default=None, max_length=80)
    wall_thickness: str | None = Field(default=None, max_length=80)
    drawing_revision: str | None = Field(default=None, max_length=80)
    component_a: str | None = Field(default=None, max_length=160)
    heat_a: str | None = Field(default=None, max_length=160)
    mtr_a: str | None = Field(default=None, max_length=300)
    component_b: str | None = Field(default=None, max_length=160)
    heat_b: str | None = Field(default=None, max_length=160)
    mtr_b: str | None = Field(default=None, max_length=300)
    wps: str | None = Field(default=None, max_length=160)
    wps_revision: str | None = Field(default=None, max_length=80)
    required_operations: list[Operation] | None = Field(default=None, max_length=2)
    change_reason: str = Field(default='Controlled weld record correction', min_length=4, max_length=3000)

    @field_validator('required_operations')
    @classmethod
    def operations_valid(cls, value):
        return check_operations(value) if value is not None else None


class WorkIn(InputModel):
    operation: Literal['fitup', 'root', 'fill_cap', 'complete']
    notes: str = Field(default='', max_length=3000)


class EvidenceIn(InputModel):
    expected_version: int = Field(ge=1)
    reference: str = Field(min_length=2, max_length=500)
    notes: str = Field(default='', max_length=5000)
    result: Literal['recorded', 'pass', 'fail'] = 'recorded'


class ReviewIn(InputModel):
    expected_version: int = Field(ge=1)
    decision: Literal['accepted', 'rejected', 'not_applicable']
    notes: str = Field(min_length=4, max_length=5000)


class ReasonIn(InputModel):
    reason: str = Field(min_length=4, max_length=5000)


class HoldIn(ReasonIn):
    weld_id: str | None = Field(default=None, max_length=60)


class CloseHoldIn(InputModel):
    notes: str = Field(min_length=4, max_length=5000)


DEFAULT_REQUIREMENTS = [
    {'code': 'MATERIALS', 'label': 'Both-side component identity (heat/MTR required after fabrication)',
     'stage': 'before_welding', 'check': 'materials'},
    {'code': 'PROCEDURE', 'label': 'WPS and welder qualification applicability verified',
     'stage': 'before_welding', 'check': 'procedure'},
    {'code': 'FIT_UP', 'label': 'Fit-up verified and approved',
     'stage': 'before_welding', 'check': 'none'},
    {'code': 'VT', 'label': 'Visual examination reviewed',
     'stage': 'after_welding', 'check': 'welding_complete'},
    {'code': 'NDE_PLAN', 'label': 'Applicable NDE plan / required extent confirmed',
     'stage': 'release', 'check': 'welding_complete', 'allow_na': True},
    {'code': 'FINAL_QA', 'label': 'Individual weld QA release',
     'stage': 'release', 'check': 'welding_complete'},
]
BASELINE_SOURCE = 'FabTrace starter checklist: QA must verify applicability against the approved project requirements. No code or NDE percentage is inferred.'

PLAN_KEYS = 'item_id project_id subproject_id assembly_id planned_welds drawing_revision due_date notes zero_weld_reason version created_by created_at updated_at'.split()
WELD_KEYS = 'id item_id number description joint_type size wall_thickness drawing_revision component_a heat_a mtr_a component_b heat_b mtr_b wps wps_revision template_id required_operations version cycle completed_at completed_by created_by created_at updated_at'.split()
REQUIREMENT_KEYS = 'id item_id weld_id code label stage allow_na evidence_required source owner_role status version cycle template_id created_by created_at updated_at'.split()
HOLD_KEYS = 'id item_id weld_id reason opened_by opened_at closed_by closed_at close_notes'.split()


def _commit(s):
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, 'Duplicate or conflicting tracking record; refresh and retry. No changes were saved.')


def _require_plan(s, item):
    plan = read_get(s, SpoolPlan, item.id)
    if not plan:
        raise HTTPException(409, 'Enroll this item with a project and spool plan first')
    return plan


def is_tracked(s, item):
    item_id = item if isinstance(item, str) else item.id
    return read_get(s, SpoolPlan, item_id) is not None


_TRACKING_SNAPSHOT_NAMESPACE = 'tracking.read_snapshot'


def prime_tracking_read_snapshots(s, item_ids):
    """Load selected-spool histories together without changing QA calculations.

    Every entry, including an empty history, belongs to the current clean read
    projection. A mutation or transaction boundary invalidates it through that
    scope. Writers do not enter this path and retain their flush-and-read gate.
    """
    if not projection_enabled(s):
        return
    missing = [item_id for item_id in dict.fromkeys(item_ids)
               if projection_get(s, _TRACKING_SNAPSHOT_NAMESPACE, item_id) is PROJECTION_MISSING]
    from production import prime_process_read_events, process_snapshot
    for offset in range(0, len(missing), 400):
        batch = missing[offset:offset + 400]
        plans = prime_rows(s, SpoolPlan, SpoolPlan.item_id, batch)
        prime_rows(s, Project, Project.id, (plan.project_id for plan in plans.values() if plan))
        prime_rows(s, Subproject, Subproject.id,
                   (plan.subproject_id for plan in plans.values() if plan and plan.subproject_id))
        snapshots = {item_id: {
            'item_id': item_id, 'welds': [], 'requirements': [], 'holds': [],
            'evidence': {}, 'reviews': {}, 'work': {}, 'repairs': {},
            'open_rework': False,
        } for item_id in batch}
        for row in s.scalars(select(Weld).where(Weld.item_id.in_(batch)).order_by(Weld.number)):
            snapshots[row.item_id]['welds'].append(row)
            projection_put(s, ('row', Weld), row.id, row)
        for row in s.scalars(select(WeldRequirement).where(
                WeldRequirement.item_id.in_(batch)).order_by(WeldRequirement.id)):
            snapshots[row.item_id]['requirements'].append(row)
        for row in s.scalars(select(TrackingHold).where(
                TrackingHold.item_id.in_(batch)).order_by(TrackingHold.id.desc())):
            snapshots[row.item_id]['holds'].append(row)
        for model, key in ((RequirementEvidence, 'evidence'), (RequirementReview, 'reviews')):
            for row, item_id in s.execute(select(model, WeldRequirement.item_id).join(
                    WeldRequirement, WeldRequirement.id == model.requirement_id).where(
                    WeldRequirement.item_id.in_(batch)).order_by(model.id.desc())):
                snapshots[item_id][key].setdefault(row.requirement_id, []).append(row)
        for model, key in ((WeldWork, 'work'), (WeldRepair, 'repairs')):
            for row, item_id in s.execute(select(model, Weld.item_id).join(
                    Weld, Weld.id == model.weld_id).where(
                    Weld.item_id.in_(batch)).order_by(model.id.desc())):
                snapshots[item_id][key].setdefault(row.weld_id, []).append(row)
        for item_id in s.scalars(select(Rework.item_id).where(
                Rework.item_id.in_(batch), Rework.closed_at.is_(None)).distinct()):
            snapshots[item_id]['open_rework'] = True
        prime_process_read_events(s, batch)
        for item_id, snapshot in snapshots.items():
            snapshot['production_process'] = process_snapshot(s, item_id)
            projection_put(s, _TRACKING_SNAPSHOT_NAMESPACE, item_id, snapshot)


@contextmanager
def _read_snapshot(s, item_id):
    """Bounded per-spool preloads used only during a single read calculation.

    Never retain this cache across a mutation. Nested summary/detail helpers
    share the same snapshot, avoiding per-requirement SQL on large weld lists.
    Release callers already hold the owning Item lock.
    """
    previous = s.info.get('tracking_read_snapshot')
    previous_projection = s.info.get('tracking_read_snapshot_projection', False)
    if previous and previous['item_id'] == item_id and (
            not previous_projection or projection_enabled(s)):
        yield previous
        return
    # Imported lazily because the process extension shares these tracking
    # definitions. One event preload serves both summary and detail output.
    from production import process_snapshot
    s.flush()
    snapshot = projection_get(s, _TRACKING_SNAPSHOT_NAMESPACE, item_id)
    if snapshot is PROJECTION_MISSING:
        welds = s.scalars(select(Weld).where(Weld.item_id == item_id).order_by(Weld.number)).all()
        requirements = s.scalars(select(WeldRequirement).where(
            WeldRequirement.item_id == item_id).order_by(WeldRequirement.id)).all()
        holds = s.scalars(select(TrackingHold).where(
            TrackingHold.item_id == item_id).order_by(TrackingHold.id.desc())).all()
        evidence = s.scalars(select(RequirementEvidence).join(WeldRequirement,
            WeldRequirement.id == RequirementEvidence.requirement_id).where(
            WeldRequirement.item_id == item_id).order_by(RequirementEvidence.id.desc())).all()
        reviews = s.scalars(select(RequirementReview).join(WeldRequirement,
            WeldRequirement.id == RequirementReview.requirement_id).where(
            WeldRequirement.item_id == item_id).order_by(RequirementReview.id.desc())).all()
        work = s.scalars(select(WeldWork).join(Weld, Weld.id == WeldWork.weld_id).where(
            Weld.item_id == item_id).order_by(WeldWork.id.desc())).all()
        repairs = s.scalars(select(WeldRepair).join(Weld, Weld.id == WeldRepair.weld_id).where(
            Weld.item_id == item_id).order_by(WeldRepair.id.desc())).all()
        def group(rows, attr):
            grouped = {}
            for row in rows:
                grouped.setdefault(getattr(row, attr), []).append(row)
            return grouped
        snapshot = {
            'item_id': item_id, 'welds': welds, 'requirements': requirements, 'holds': holds,
            'evidence': group(evidence, 'requirement_id'), 'reviews': group(reviews, 'requirement_id'),
            'work': group(work, 'weld_id'), 'repairs': group(repairs, 'weld_id'),
            'production_process': process_snapshot(s, item_id),
            'open_rework': bool(s.scalar(select(Rework.id).where(
                Rework.item_id == item_id, Rework.closed_at.is_(None)).limit(1))),
        }
        projection_put(s, _TRACKING_SNAPSHOT_NAMESPACE, item_id, snapshot)
    s.info['tracking_read_snapshot'] = snapshot
    s.info['tracking_read_snapshot_projection'] = projection_enabled(s)
    try:
        yield snapshot
    finally:
        if previous is None:
            s.info.pop('tracking_read_snapshot', None)
            s.info.pop('tracking_read_snapshot_projection', None)
        else:
            s.info['tracking_read_snapshot'] = previous
            s.info['tracking_read_snapshot_projection'] = previous_projection


def _snapshot_response(function):
    @wraps(function)
    def wrapped(s, row, *args, **kwargs):
        item_id = row.id if isinstance(row, Item) else row.item_id
        with _read_snapshot(s, item_id):
            return function(s, row, *args, **kwargs)
    return wrapped


def _snapshot(s, item_id):
    if s.info.get('tracking_read_snapshot_projection') and not projection_enabled(s):
        return None
    value = s.info.get('tracking_read_snapshot')
    return value if value and value['item_id'] == item_id else None


def _arrival_errors(s, item):
    """Read arrival evidence once per scoped response, never across a write."""
    from spool_receiving import receiving_errors
    snapshot = _snapshot(s, item.id)
    if snapshot is None:
        return receiving_errors(s, item)
    if 'receiving_errors' not in snapshot:
        snapshot['receiving_errors'] = receiving_errors(s, item)
    return list(snapshot['receiving_errors'])


def _welds(s, item_id):
    snapshot = _snapshot(s, item_id)
    if snapshot:
        return snapshot['welds']
    return s.scalars(select(Weld).where(Weld.item_id == item_id).order_by(Weld.number)).all()


def _requirements(s, item_id, weld_id=None, all_scopes=False):
    snapshot = _snapshot(s, item_id)
    if snapshot:
        return [r for r in snapshot['requirements'] if all_scopes or r.weld_id == weld_id]
    q = select(WeldRequirement).where(WeldRequirement.item_id == item_id)
    if not all_scopes:
        q = q.where(WeldRequirement.weld_id == weld_id)
    return s.scalars(q.order_by(WeldRequirement.id)).all()


def _holds(s, item_id, weld_id=None, all_scopes=False):
    snapshot = _snapshot(s, item_id)
    if snapshot:
        return [r for r in snapshot['holds'] if all_scopes or r.weld_id == weld_id]
    q = select(TrackingHold).where(TrackingHold.item_id == item_id)
    if not all_scopes:
        q = q.where(TrackingHold.weld_id == weld_id)
    return s.scalars(q.order_by(TrackingHold.id.desc())).all()


def _version(row, expected):
    if expected != row.version:
        raise HTTPException(409, {'message': 'Record changed; refresh before continuing', 'current_version': row.version})


def _lock_weld(s, weld_id):
    initial = s.get(Weld, weld_id)
    if not initial:
        raise HTTPException(404, 'Weld not found')
    item = lock_item(s, initial.item_id)
    require_unreleased(item)
    weld = s.scalar(select(Weld).where(Weld.id == weld_id).execution_options(populate_existing=True))
    _require_plan(s, item)
    return item, weld


def _lock_requirement(s, requirement_id):
    initial = s.get(WeldRequirement, requirement_id)
    if not initial:
        raise HTTPException(404, 'Requirement not found')
    item = lock_item(s, initial.item_id)
    require_unreleased(item)
    req = s.scalar(select(WeldRequirement).where(WeldRequirement.id == requirement_id).execution_options(populate_existing=True))
    _require_plan(s, item)
    return item, req


def _invalidate_spool(item, physical=False):
    item.updated_at = utcnow()
    item.reinspection_due = True
    item.weld = 'Not started'
    item.weld_at = None
    if physical:
        item.last_work_at = utcnow()
        item.dimensional = 'Not started'
        item.dimension_at = None


def _reset_requirements(s, item, rows, actor, reason):
    """Start a new verification cycle without deleting earlier evidence."""
    changes = []
    for req in rows:
        changes.append({'requirement_id': req.id, 'previous_status': req.status,
                        'previous_cycle': req.cycle, 'previous_version': req.version})
        req.status = 'pending'
        req.cycle += 1
        req.version += 1
        req.updated_at = utcnow()
    if changes:
        audit(s, item.id, actor, 'TRACKING_REQUIREMENTS_REOPENED', {'reason': reason, 'requirements': changes})


def _invalidate_final_qa(s, item, weld_id, actor, reason, except_id=None):
    if not weld_id:
        return
    rows = [r for r in _requirements(s, item.id, weld_id)
            if r.code == 'FINAL_QA' and r.id != except_id and r.status in ACCEPTED]
    _reset_requirements(s, item, rows, actor, reason)


def reopen_tracked(s, item, actor, reason):
    """Called with Item locked by legacy reopen/rework endpoints.

    Administrative or dimensional rework invalidates verification but does not
    invent a need to weld again. Actual weld repairs use a new Weld.cycle.
    """
    if not is_tracked(s, item):
        return
    _reset_requirements(s, item, _requirements(s, item.id, all_scopes=True), actor, reason)
    _invalidate_spool(item)
    _sync_legacy_counts(s, item)


def _current_work(s, weld):
    snapshot = _snapshot(s, weld.item_id)
    if snapshot:
        return [r for r in snapshot['work'].get(weld.id, []) if r.cycle == weld.cycle]
    return s.scalars(select(WeldWork).where(WeldWork.weld_id == weld.id,
        WeldWork.cycle == weld.cycle).order_by(WeldWork.id)).all()


def _production_complete(s, weld):
    if weld.completed_at is None:
        return False
    operations = {w.operation for w in _current_work(s, weld)}
    return 'complete' in operations and set(weld.required_operations or []).issubset(operations) and bool(weld.required_operations)


def _material_errors(weld, *, include_traceability=True):
    names = [('component_a', 'Component A piece / lot identity'),
             ('component_b', 'Component B piece / lot identity')]
    if include_traceability:
        names += [('heat_a', 'Component A heat'), ('heat_b', 'Component B heat'),
                  ('mtr_a', 'Component A MTR reference'), ('mtr_b', 'Component B MTR reference')]
    return [label + ' missing' for key, label in names if not (getattr(weld, key) or '').strip()]


def _weld_heat_errors(weld):
    return [label + ' is required after fabrication, before post-weld QA/testing/release'
            for key, label in (('heat_a', 'Component A heat number'), ('heat_b', 'Component B heat number'),
                               ('mtr_a', 'Component A MTR reference'), ('mtr_b', 'Component B MTR reference'))
            if not (getattr(weld, key) or '').strip()]


def _physical_heat_errors(s, item):
    """Reuse physical-piece reads only within the existing one-calculation snapshot."""
    from spool_boms import spool_heat_errors
    snapshot = _snapshot(s, item.id)
    if snapshot is None:
        return spool_heat_errors(s, item)
    if 'physical_heat_errors' not in snapshot:
        snapshot['physical_heat_errors'] = spool_heat_errors(s, item)
    return list(snapshot['physical_heat_errors'])


@read_cached(lambda s, item, include_children=True: (item.id, include_children))
def post_fabrication_heat_errors(s, item, *, include_children=True):
    """Independent heat/MTR deadline; custom/NA requirements cannot waive it.

    Fabrication work and completion do not call this acceptance gate. Assemblies
    include their own welds and the exact active physical descendant scope.
    The original helper name is retained for existing acceptance/timer callers.
    """
    from order_spools import effective_children
    from spool_boms import spool_heat_errors
    errors = (_physical_heat_errors(s, item) if include_children
              else spool_heat_errors(s, item, include_children=False))
    pending, seen = [item], set()
    while pending:
        current = pending.pop()
        if current.id in seen:
            continue
        seen.add(current.id)
        if read_get(s, SpoolPlan, current.id) is not None:
            for weld in _welds(s, current.id):
                errors.extend(f'{current.id}, {weld.number}: {message}' for message in _weld_heat_errors(weld))
        if include_children and current.kind == 'Assembly':
            pending.extend(child for child, _ in effective_children(s, current.id, include_removed=False))
    return list(dict.fromkeys(errors))


def _requirement_heat_errors(s, req, weld=None):
    if req.stage not in ('after_welding', 'release') and req.code != 'FINAL_QA':
        return []
    if weld is None and req.weld_id:
        weld = read_get(s, Weld, req.weld_id)
    item = read_get(s, Item, req.item_id)
    if weld is not None:
        return _weld_heat_errors(weld) + _physical_heat_errors(s, item)
    return post_fabrication_heat_errors(s, item)


def _check_errors(s, req, weld=None):
    if weld is None and req.weld_id:
        weld = read_get(s, Weld, req.weld_id)
    errors = _requirement_heat_errors(s, req, weld)
    if req.check_kind == 'none':
        return errors
    if req.check_kind in ('materials', 'procedure') and weld is None:
        return errors + ['This check requires an individual weld record']
    if req.check_kind == 'materials':
        errors.extend(_material_errors(weld, include_traceability=req.stage != 'before_welding'))
    elif req.check_kind == 'procedure':
        errors.extend(label + ' missing' for key, label in [('wps', 'WPS identifier'), ('wps_revision', 'WPS revision')]
                      if not (getattr(weld, key) or '').strip())
    elif req.check_kind == 'welding_complete':
        if weld is not None:
            if not _production_complete(s, weld):
                errors.append('Configured welding operations are not complete')
        else:
            plan = read_get(s, SpoolPlan, req.item_id)
            welds = _welds(s, req.item_id)
            if not plan or len(welds) != plan.planned_welds or any(not _production_complete(s, w) for w in welds):
                errors.append('Spool weld scope or configured welding operations are incomplete')
    return list(dict.fromkeys(errors))


def _latest_evidence(s, req):
    snapshot = _snapshot(s, req.item_id)
    if snapshot:
        return next((r for r in snapshot['evidence'].get(req.id, []) if r.cycle == req.cycle), None)
    return s.scalar(select(RequirementEvidence).where(
        RequirementEvidence.requirement_id == req.id,
        RequirementEvidence.cycle == req.cycle).order_by(RequirementEvidence.id.desc()).limit(1))


def _latest_review(s, req):
    snapshot = _snapshot(s, req.item_id)
    if snapshot:
        return next((r for r in snapshot['reviews'].get(req.id, []) if r.cycle == req.cycle), None)
    return s.scalar(select(RequirementReview).where(
        RequirementReview.requirement_id == req.id,
        RequirementReview.cycle == req.cycle).order_by(RequirementReview.id.desc()).limit(1))


def _requirement_satisfied(s, req, weld=None):
    if req.status == 'not_applicable':
        review = _latest_review(s, req)
        return bool(req.allow_na and review and review.decision == 'not_applicable' and review.notes.strip()
                    and not _requirement_heat_errors(s, req, weld))
    if req.status != 'accepted' or _check_errors(s, req, weld):
        return False
    latest = _latest_evidence(s, req)
    if req.evidence_required and latest is None:
        return False
    if latest and latest.result == 'fail':
        return False
    review = _latest_review(s, req)
    # A signed decision must identify the same immutable evidence revision.
    return bool(review and review.decision == 'accepted' and
                review.evidence_id == (latest.id if latest else None))


def _weld_blockers(s, weld, include_production=True, *, requirement_stages=None):
    errors = _weld_heat_errors(weld)
    if include_production and not _production_complete(s, weld):
        errors.append('Welding operations incomplete')
    rows = _requirements(s, weld.item_id, weld.id)
    if not rows:
        errors.append('No approved weld requirement scope defined')
    for req in rows:
        if requirement_stages is not None and req.stage not in requirement_stages:
            continue
        if not _requirement_satisfied(s, req, weld):
            details = _check_errors(s, req, weld)
            errors.append(req.label + ': ' + (', '.join(details) if details else req.status.replace('_', ' ')))
    for hold in _holds(s, weld.item_id, weld.id):
        if hold.closed_at is None:
            errors.append('Hold: ' + hold.reason)
    return errors


def _qa_accepted(s, weld):
    return not _weld_blockers(s, weld)


def _after(left, right):
    # SQLite test fixtures return naive datetimes; PostgreSQL returns aware.
    if left is None:
        return False
    if right is None:
        return True
    normalize = lambda value: value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value
    return normalize(left) > normalize(right)


def _assembly_errors(s, item_id, project_id, assembly_id):
    from order_spools import effective_children, effective_parent_id
    errors = []
    seen = {item_id}
    parent_id = assembly_id
    while parent_id:
        if parent_id in seen:
            errors.append('Assembly links cannot form a cycle')
            break
        seen.add(parent_id)
        parent = read_get(s, Item, parent_id)
        if not parent or parent.kind != 'Assembly':
            errors.append('Assembly link must identify an existing Assembly item')
            break
        parent_plan = read_get(s, SpoolPlan, parent_id)
        if parent_plan and parent_plan.project_id != project_id:
            errors.append('Linked assembly belongs to a different project')
            break
        parent_id = effective_parent_id(s, parent_id)
    children = effective_children(s, item_id)
    if any((plan.project_id if plan else child.project) != project_id for child, plan in children):
        errors.append('Assembly has child spools in another project; reassign those links before moving the assembly')
    return errors


@_snapshot_response
def tracking_release_errors(s, item, *, requirement_stages=None):
    """Authoritative release gate for explicitly enrolled spools.

    Legacy aggregate Weld inspections cannot satisfy individual requirements.
    Dimensional inspection and legacy rework still apply at the spool level.
    A pre-final checkpoint may select explicit requirement stages. The default
    final-release gate always checks every stage, including final obligations.
    """
    plan = read_get(s, SpoolPlan, item.id)
    if not plan:
        return ['Item is not enrolled in weld tracking']
    errors = _arrival_errors(s, item) + post_fabrication_heat_errors(s, item)
    project = read_get(s, Project, plan.project_id)
    if not project:
        errors.append('Project assignment missing')
    if plan.subproject_id:
        sub = read_get(s, Subproject, plan.subproject_id)
        if not sub or sub.project_id != plan.project_id:
            errors.append('Subproject does not belong to assigned project')
    errors.extend(_assembly_errors(s, item.id, plan.project_id, plan.assembly_id))
    welds = _welds(s, item.id)
    if len(welds) != plan.planned_welds:
        errors.append(f'Weld scope incomplete: {len(welds)} defined of {plan.planned_welds} planned')
    if plan.planned_welds == 0 and not plan.zero_weld_reason.strip():
        errors.append('Zero-weld scope requires an approved scope reason')
    for weld in welds:
        errors.extend(f'{weld.number}: {message}' for message in _weld_blockers(
            s, weld, requirement_stages=requirement_stages))
    for req in _requirements(s, item.id):
        if requirement_stages is not None and req.stage not in requirement_stages:
            continue
        if not _requirement_satisfied(s, req):
            details = _check_errors(s, req)
            errors.append('Spool ' + req.label + ': ' + (', '.join(details) if details else req.status.replace('_', ' ')))
    if item.on_hold:
        errors.append('Item is on hold')
    for hold in _holds(s, item.id):
        if hold.closed_at is None:
            errors.append('Spool hold: ' + hold.reason)
    if item.dimensional != 'Pass':
        errors.append('Spool dimensional inspection must pass')
    if item.dimension_at is None:
        errors.append('Spool dimensional inspection timestamp missing')
    elif not _after(item.dimension_at, item.last_work_at):
        errors.append('Spool dimensional inspection predates latest work')
    if _snapshot(s, item.id)['open_rework']:
        errors.append('Open spool rework exists')
    from parts import parts_blockers
    errors.extend(parts_blockers(s, item.id))
    return errors


def _sync_legacy_counts(s, item):
    plan = s.get(SpoolPlan, item.id)
    if plan:
        item.welds_required = plan.planned_welds
        item.welds_done = sum(_production_complete(s, w) for w in _welds(s, item.id))


@_snapshot_response
def tracking_summary(s, item):
    from production import compact_process_summary
    from administration import release_summary
    plan = read_get(s, SpoolPlan, item.id)
    if not plan:
        return None
    welds = _welds(s, item.id)
    project = read_get(s, Project, plan.project_id)
    sub = read_get(s, Subproject, plan.subproject_id) if plan.subproject_id else None
    blockers = tracking_release_errors(s, item)
    from parts import parts_summary
    parts = parts_summary(s, item.id)
    release_control = release_summary(s, item)
    if release_control['active_override']:
        blockers.append('Administrative release is recorded; ordinary QA release has not been verified')
    return {
        'item_id': item.id, 'description': item.description,
        'drawing': item.drawing, 'drawing_revision': plan.drawing_revision,
        'project_id': plan.project_id, 'project_name': project.name if project else '',
        'subproject_id': plan.subproject_id, 'subproject_name': sub.name if sub else '',
        'assembly_id': plan.assembly_id, 'planned_welds': plan.planned_welds,
        'welds_defined': len(welds), 'production_complete': sum(_production_complete(s, w) for w in welds),
        'qa_accepted': sum(_qa_accepted(s, w) for w in welds),
        'ready_to_release': not blockers, 'released': bool(item.released),
        'release_control': release_control,
        'blockers': blockers, 'due_date': plan.due_date,
        'production_process': compact_process_summary(_snapshot(s, item.id)['production_process']),
        **({'parts': parts} if parts else {}),
    }


@_snapshot_response
def requirement_dict(s, req, user=None):
    out = asdict(req, REQUIREMENT_KEYS)
    if user is not None:
        from removals import item_is_removed
        active = not item_is_removed(s, req.item_id)
        out['permissions'] = {'can_submit_evidence': active and can_submit_requirement_evidence(user, req),
                              'can_review': active and has_capability(user, 'quality_review'), 'can_mutate': active}
    out['check'] = req.check_kind
    out['satisfied'] = _requirement_satisfied(s, req)
    out['check_errors'] = _check_errors(s, req)
    snapshot = _snapshot(s, req.item_id)
    out['evidence'] = [asdict(row, 'id requirement_id cycle reference notes result actor at'.split())
        for row in snapshot['evidence'].get(req.id, [])]
    out['reviews'] = [asdict(row, 'id requirement_id evidence_id cycle decision notes actor at'.split())
        for row in snapshot['reviews'].get(req.id, [])]
    return out


@_snapshot_response
def weld_dict(s, weld, user=None):
    out = asdict(weld, WELD_KEYS)
    arrival_blockers = _arrival_errors(s, read_get(s, Item, weld.item_id))
    if user is not None:
        from removals import item_is_removed, removal_summary
        active = not item_is_removed(s, weld.item_id)
        out['allowed_operations'] = list(WELD_OPERATIONS.get(user.role, ())) if active and not arrival_blockers else []
        out['removal'] = removal_summary(s, 'item', weld.item_id)
        out['can_mutate'] = active
    out['production_complete'] = _production_complete(s, weld)
    out['qa_accepted'] = _qa_accepted(s, weld)
    out['blockers'] = list(dict.fromkeys(_weld_blockers(s, weld) + arrival_blockers))
    out['requirements'] = [requirement_dict(s, r, user) for r in _requirements(s, weld.item_id, weld.id)]
    snapshot = _snapshot(s, weld.item_id)
    out['work'] = [asdict(row, 'id weld_id cycle operation notes actor at'.split())
                   for row in snapshot['work'].get(weld.id, [])]
    out['repairs'] = [asdict(row, 'id weld_id cycle reason opened_by opened_at'.split())
                      for row in snapshot['repairs'].get(weld.id, [])]
    out['holds'] = [asdict(row, HOLD_KEYS) for row in _holds(s, weld.item_id, weld.id)]
    return out


def template_dict(row):
    return asdict(row, 'id code name revision source requirements required_operations created_by created_at'.split())


@_snapshot_response
def spool_dict(s, item, user=None):
    plan = read_get(s, SpoolPlan, item.id)
    from parts import parts_summary
    from administration import release_summary
    from production import with_process_permissions
    from removals import item_is_removed, removal_summary
    from order_spools import registered_spool
    from spool_receiving import receiving_summary
    registration = registered_spool(s, item.id)
    parts = parts_summary(s, item.id)
    arrival = receiving_summary(s, item, user)
    # Dossier evidence calls this reader without a user. Live labels and colors
    # belong only to UI responses, never to the retained evidence fingerprint.
    from spool_presentation import item_presentation
    display = item_presentation(s, item, receiving=arrival) if user is not None else {}
    return {
        **({'removal': removal_summary(s, 'item', item.id), 'can_mutate': not item_is_removed(s, item.id)} if user is not None else {}),
        **({'parts': parts} if parts else {}),
        'item': {**asdict(item, 'id description kind project drawing location handler welds_required welds_done dimensional weld dimension_at last_work_at reinspection_due on_hold released released_at released_by'.split()),
                 **display, 'release_control': release_summary(s, item), 'receiving': arrival},
        'plan': asdict(plan, PLAN_KEYS) if plan else None,
        'registered_assembly_id': registration.assembly_id if registration else None,
        'summary': tracking_summary(s, item),
        'production_process': with_process_permissions(s, item.id, _snapshot(s, item.id)['production_process'], user),
        'welds': [weld_dict(s, row, user) for row in _welds(s, item.id)],
        'requirements': [requirement_dict(s, row, user) for row in _requirements(s, item.id)],
        'holds': [asdict(row, HOLD_KEYS) for row in _holds(s, item.id, all_scopes=True)],
        'history': [asdict(row, 'id item_id actor event details at'.split()) for row in s.scalars(
            select(Audit).where(Audit.item_id == item.id).order_by(Audit.id.desc()).limit(100)).all()],
    }


def _add_requirement(s, item, weld, definition, actor, template_id=None):
    data = definition.model_dump() if isinstance(definition, RequirementIn) else RequirementIn(**definition).model_dump()
    check = data.pop('check')
    req = WeldRequirement(item_id=item.id, weld_id=weld.id if weld else None,
        check_kind=check, created_by=actor, template_id=template_id, **data)
    s.add(req)
    return req


def _default_definitions(template=None):
    """Baseline controls remain present; profiles add project-specific checks.

    A template can give a baseline check a project source/label, but cannot
    silently remove its minimum evidence/review or weaken its stage/check.
    """
    result = {row['code']: RequirementIn(source=BASELINE_SOURCE, **row).model_dump()
              for row in DEFAULT_REQUIREMENTS}
    if template:
        for spec in template.requirements:
            current = result.get(spec['code'])
            if current:
                for key in ('label', 'source', 'owner_role'):
                    if spec.get(key):
                        current[key] = spec[key]
            else:
                result[spec['code']] = dict(spec)
    return list(result.values())


def validate_order_weld_scope(s, item, project_id, assembly_id, weld_count):
    """Validate an explicit PO count without altering retained production."""
    plan = s.get(SpoolPlan, item.id)
    if plan:
        if (plan.project_id != project_id or plan.assembly_id != assembly_id or
                plan.planned_welds != weld_count):
            raise HTTPException(409, f'Spool {item.id} already has a different weld plan. '
                'Review its existing weld scope before declaring the purchase-order weld count; no existing work was changed.')
        return False
    if (item.released or item.welds_done or item.last_work_at or
            item.dimensional != 'Not started' or item.weld != 'Not started' or
            s.scalar(select(Weld.id).where(Weld.item_id == item.id).limit(1))):
        raise HTTPException(409, f'Spool {item.id} already has production or inspection history without an individual weld plan. '
            'Review that retained history before declaring its weld count; no existing work was changed.')
    return True


def initialize_order_weld_scope(s, item, project_id, assembly_id, weld_count, actor):
    """Create empty numbered weld scope inside the caller's locked transaction.

    Existing plans and every production/QA record are retained. A declared
    count is planning evidence only; no operation, traveler or acceptance is
    inferred, and each weld receives the normal pending quality requirements.
    """
    from orders import _flush
    from order_spools import ensure_spool_qr_identity
    if not validate_order_weld_scope(s, item, project_id, assembly_id, weld_count):
        return 0
    values = {'project_id': project_id, 'assembly_id': assembly_id,
        'planned_welds': weld_count, 'drawing_revision': '', 'notes': '',
        'zero_weld_reason': 'Zero welds explicitly declared in purchase-order spool setup.' if weld_count == 0 else ''}
    s.add(SpoolPlan(item_id=item.id, created_by=actor, **values))
    welds = [Weld(id=new_id('WLD'), item_id=item.id, number=f'W{number:02d}',
                  required_operations=['root', 'fill_cap'], created_by=actor)
             for number in range(1, weld_count + 1)]
    s.add_all(welds)
    _flush(s)
    ensure_spool_qr_identity(s, item, actor, source='purchase_order_weld_count')
    from spool_boms import ensure_material_piece_records
    ensure_material_piece_records(s, item, actor,
        'Initialize physical material pieces while declaring the saved spool weld count.')
    definitions = _default_definitions()
    for weld in welds:
        for definition in definitions:
            _add_requirement(s, item, weld, definition, actor)
        audit(s, item.id, actor, 'TRACKING_WELD_CREATED', {
            'weld_id': weld.id, 'number': weld.number,
            'required_operations': weld.required_operations, 'source': 'purchase_order_weld_count'})
    item.welds_required = weld_count
    item.reinspection_due = True
    item.updated_at = utcnow()
    audit(s, item.id, actor, 'TRACKING_PLAN_SAVED', {
        'before': None, 'after': values, 'source': 'purchase_order_weld_count'})
    _flush(s)
    return len(welds)


@router.get('/projects')
def get_projects(u: Employee = Depends(auth), s: Session = Depends(db)):
    from removals import project_not_removed
    return [asdict(row, 'id name client description created_by created_at'.split())
            for row in s.scalars(select(Project).where(project_not_removed(Project.id)).order_by(Project.name)).all()]


@router.post('/projects', status_code=201)
def create_project(data: ProjectIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    permit(u, 'supervisor', 'admin')
    if s.get(Project, data.id):
        raise HTTPException(409, 'Project ID already exists')
    row = Project(**data.model_dump(), created_by=u.badge)
    s.add(row)
    audit(s, None, u.badge, 'TRACKING_PROJECT_CREATED', data.model_dump())
    _commit(s)
    return asdict(row, 'id name client description created_by created_at'.split())


@router.get('/subprojects')
def get_subprojects(project_id: str = '', u: Employee = Depends(auth), s: Session = Depends(db)):
    from removals import project_not_removed
    q = select(Subproject).where(project_not_removed(Subproject.project_id))
    if project_id:
        q = q.where(Subproject.project_id == project_id)
    return [asdict(row, 'id project_id name description created_by created_at'.split())
            for row in s.scalars(q.order_by(Subproject.name)).all()]


@router.post('/subprojects', status_code=201)
def create_subproject(data: SubprojectIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    from removals import require_active_project
    lock_topology(s)
    permit(u, 'supervisor', 'admin')
    if not s.get(Project, data.project_id):
        raise HTTPException(422, 'Project not found')
    require_active_project(s, data.project_id)
    if s.get(Subproject, data.id):
        raise HTTPException(409, 'Subproject ID already exists')
    row = Subproject(**data.model_dump(), created_by=u.badge)
    s.add(row)
    audit(s, None, u.badge, 'TRACKING_SUBPROJECT_CREATED', data.model_dump())
    _commit(s)
    return asdict(row, 'id project_id name description created_by created_at'.split())


@router.get('/templates')
def get_templates(u: Employee = Depends(auth), s: Session = Depends(db)):
    return [template_dict(row) for row in s.scalars(select(RequirementTemplate).order_by(
        RequirementTemplate.name, RequirementTemplate.revision.desc())).all()]


@router.post('/templates', status_code=201)
def create_template(data: TemplateIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    permit(u, 'supervisor', 'admin')
    codes = [r.code for r in data.requirements]
    if len(codes) != len(set(codes)):
        raise HTTPException(422, 'Requirement codes must be unique within a template')
    prior = s.scalar(select(RequirementTemplate).where(RequirementTemplate.code == data.code).order_by(
        RequirementTemplate.revision.desc()).limit(1))
    if prior and data.revision <= prior.revision:
        raise HTTPException(409, 'Create a higher immutable template revision; existing revisions cannot be overwritten')
    row = RequirementTemplate(id=new_id('TPL'), **data.model_dump(), created_by=u.badge)
    s.add(row)
    audit(s, None, u.badge, 'TRACKING_TEMPLATE_CREATED', {'id': row.id, **data.model_dump()})
    _commit(s)
    return template_dict(row)


@router.get('/spools/{item_id}')
def get_spool(item_id: str, u: Employee = Depends(auth), s: Session = Depends(db)):
    with read_projection(s):
        item = read_get(s, Item, item_id)
        if not item:
            raise HTTPException(404, 'Item not found')
        return spool_dict(s, item, u)


@router.post('/spools/{item_id}/plan')
def save_plan(item_id: str, data: PlanIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    from removals import require_active_item, require_active_project
    lock_topology(s)
    permit(u, 'supervisor', 'admin')
    # Serialize topology before Item locks. The same boundary revalidates
    # account permissions for production and review writers queued behind edits.
    item = lock_item(s, item_id)
    require_unreleased(item)
    if not s.get(Project, data.project_id):
        raise HTTPException(422, 'Project not found')
    require_active_project(s, data.project_id)
    if data.assembly_id:
        require_active_item(s, data.assembly_id)
    if data.subproject_id:
        sub = s.get(Subproject, data.subproject_id)
        if not sub or sub.project_id != data.project_id:
            raise HTTPException(422, 'Subproject must belong to the selected project')
    hierarchy_errors = _assembly_errors(s, item.id, data.project_id, data.assembly_id)
    if hierarchy_errors:
        raise HTTPException(422, {'hierarchy_errors': hierarchy_errors})
    count = len(_welds(s, item.id))
    if data.planned_welds < count:
        raise HTTPException(409, f'Scope cannot contain fewer than the {count} existing weld records')
    if data.planned_welds == 0 and len(data.zero_weld_reason.strip()) < 4:
        raise HTTPException(422, 'A zero-weld plan needs a controlled scope reason')
    values = data.model_dump(exclude={'expected_version'})
    values['due_date'] = data.due_date.isoformat() if data.due_date else None
    plan = s.get(SpoolPlan, item.id)
    before = asdict(plan, PLAN_KEYS) if plan else None
    from flow import guard_plan_change
    guard_plan_change(s, item, plan, values)
    from orders import guard_plan_scope
    guard_plan_scope(s, item, plan, values)
    from order_setup import guard_declared_weld_count
    guard_declared_weld_count(s, item, values.get('assembly_id'), values['planned_welds'])
    from parts import guard_plan_project
    guard_plan_project(s, item, values)
    from spool_documents import guard_document_spool_identity
    guard_document_spool_identity(s, item, values)
    if plan:
        _version(plan, data.expected_version)
        changed_scope = any(getattr(plan, key) != values[key] for key in (
            'project_id', 'subproject_id', 'assembly_id', 'planned_welds', 'drawing_revision', 'zero_weld_reason'))
        for key, value in values.items():
            setattr(plan, key, value)
        plan.version += 1
        plan.updated_at = utcnow()
        if changed_scope:
            reopen_tracked(s, item, u.badge, 'Spool plan scope or drawing changed')
            _invalidate_spool(item, physical=True)
    else:
        plan = SpoolPlan(item_id=item.id, created_by=u.badge, **values)
        s.add(plan)
        s.flush()
        _invalidate_spool(item, physical=True)
    item.project = data.project_id
    from order_spools import ensure_spool_qr_identity
    ensure_spool_qr_identity(s, item, u.badge, source='tracking_plan')
    from spool_boms import ensure_material_piece_records
    ensure_material_piece_records(s, item, u.badge,
        'Initialize physical material pieces from the uploaded spool BOM after weld-plan setup.')
    _sync_legacy_counts(s, item)
    audit(s, item.id, u.badge, 'TRACKING_PLAN_SAVED', {'before': before, 'after': values})
    _commit(s)
    return spool_dict(s, item, u)


@router.post('/spools/{item_id}/welds', status_code=201)
def create_weld(item_id: str, data: WeldIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    permit(u, 'supervisor', 'admin')
    item = lock_item(s, item_id)
    require_unreleased(item)
    plan = _require_plan(s, item)
    if len(_welds(s, item.id)) >= plan.planned_welds:
        raise HTTPException(409, 'All planned welds are defined; update the controlled spool plan before adding another weld')
    if s.scalar(select(Weld.id).where(Weld.item_id == item.id, Weld.number == data.number)):
        raise HTTPException(409, 'Weld number already exists on this spool')
    template = s.get(RequirementTemplate, data.template_id) if data.template_id else None
    if data.template_id and not template:
        raise HTTPException(422, 'Requirement template not found')
    values = data.model_dump()
    values['required_operations'] = data.required_operations or (template.required_operations if template else ['root', 'fill_cap'])
    weld = Weld(id=new_id('WLD'), item_id=item.id, created_by=u.badge, **values)
    s.add(weld)
    s.flush()
    for definition in _default_definitions(template):
        _add_requirement(s, item, weld, definition, u.badge, template.id if template else None)
    _reset_requirements(s, item, _requirements(s, item.id), u.badge, 'Weld added to spool scope')
    _invalidate_spool(item, physical=True)
    _sync_legacy_counts(s, item)
    audit(s, item.id, u.badge, 'TRACKING_WELD_CREATED', {'weld_id': weld.id, **values})
    _commit(s)
    return weld_dict(s, weld, u)


@router.get('/welds/{weld_id}')
def get_weld(weld_id: str, u: Employee = Depends(auth), s: Session = Depends(db)):
    with read_projection(s):
        weld = read_get(s, Weld, weld_id)
        if not weld:
            raise HTTPException(404, 'Weld not found')
        return weld_dict(s, weld, u)


@router.patch('/welds/{weld_id}')
def update_weld(weld_id: str, data: WeldUpdate, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    permit(u, 'supervisor', 'admin')
    item, weld = _lock_weld(s, weld_id)
    _version(weld, data.expected_version)
    updates = data.model_dump(exclude={'expected_version', 'change_reason'}, exclude_unset=True)
    if any(value is None for value in updates.values()):
        raise HTTPException(422, 'Use an empty string to clear metadata; required operations cannot be empty')
    changes = {key: {'before': getattr(weld, key), 'after': value}
               for key, value in updates.items() if getattr(weld, key) != value}
    if not changes:
        raise HTTPException(409, 'No weld metadata changed')
    for key, change in changes.items():
        setattr(weld, key, change['after'])
    if 'required_operations' in changes:
        # A new scope of physical operations needs a new completion event;
        # retain old operations and their history in an explicit repair cycle.
        weld.cycle += 1
        weld.completed_at = None
        weld.completed_by = None
        s.add(WeldRepair(weld_id=weld.id, cycle=weld.cycle,
            reason='Required welding operations changed: ' + data.change_reason, opened_by=u.badge))
    weld.version += 1
    weld.updated_at = utcnow()
    affected = _requirements(s, item.id, weld.id) + _requirements(s, item.id)
    _reset_requirements(s, item, affected, u.badge, data.change_reason)
    _invalidate_spool(item, physical=True)
    _sync_legacy_counts(s, item)
    audit(s, item.id, u.badge, 'TRACKING_WELD_UPDATED', {'weld_id': weld.id, 'reason': data.change_reason, 'changes': changes})
    _commit(s)
    return weld_dict(s, weld, u)


@router.post('/welds/{weld_id}/work')
def record_work(weld_id: str, data: WorkIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    if not can_record_weld_operation(u, data.operation):
        raise HTTPException(403, 'Your assigned position cannot record this welding operation.')
    from flow import guard_weld_operation
    item, weld = _lock_weld(s, weld_id)
    guard_weld_operation(s, item, data.operation)
    holds = [h for h in _holds(s, item.id, all_scopes=True)
             if h.closed_at is None and h.weld_id in (None, weld.id)]
    if item.on_hold or holds:
        raise HTTPException(409, {'work_blockers': ['Item is on hold'] if item.on_hold else ['Hold: ' + h.reason for h in holds]})
    existing = {row.operation for row in _current_work(s, weld)}
    if weld.completed_at is not None:
        raise HTTPException(409, 'This weld cycle is complete; open a repair before recording additional physical work')
    if data.operation in existing:
        raise HTTPException(409, 'This operation is already recorded for the current weld cycle')
    if data.operation != 'fitup':
        prerequisites = [r for r in _requirements(s, item.id, weld.id) if r.stage == 'before_welding']
        prerequisites += [r for r in _requirements(s, item.id) if r.stage == 'before_welding']
        blockers = [r.label + ': ' + (', '.join(_check_errors(s, r, weld if r.weld_id else None)) or r.status.replace('_', ' '))
                    for r in prerequisites if not _requirement_satisfied(s, r, weld if r.weld_id else None)]
        if not prerequisites:
            blockers.append('Before-welding requirements have not been defined')
        if blockers:
            raise HTTPException(409, {'work_blockers': blockers})
        if data.operation in ('root', 'fill_cap') and data.operation not in weld.required_operations:
            raise HTTPException(409, 'This operation is not in the controlled weld work plan')
        if data.operation == 'fill_cap' and 'root' in weld.required_operations and 'root' not in existing:
            raise HTTPException(409, 'Record the required root operation before fill/cap')
        if data.operation == 'complete':
            missing = [op for op in weld.required_operations if op not in existing]
            if missing:
                raise HTTPException(409, {'work_blockers': ['Required operation not recorded: ' + op for op in missing]})
    now = utcnow()
    s.add(WeldWork(weld_id=weld.id, cycle=weld.cycle, operation=data.operation,
                  notes=data.notes, actor=u.badge, at=now))
    if data.operation == 'complete':
        weld.completed_at = now
        weld.completed_by = u.badge
    weld.version += 1
    weld.updated_at = now
    # New physical work invalidates existing post-work and spool approvals.
    post = [r for r in _requirements(s, item.id, weld.id)
            if (r.stage != 'before_welding' or (data.operation == 'fitup' and r.code == 'FIT_UP'))
            and (r.status != 'pending' or _latest_evidence(s, r) is not None)]
    spool_post = [r for r in _requirements(s, item.id)
                  if r.stage != 'before_welding' and (r.status != 'pending' or _latest_evidence(s, r) is not None)]
    _reset_requirements(s, item, post + spool_post, u.badge, 'Additional physical work recorded')
    _invalidate_spool(item, physical=True)
    s.flush()
    _sync_legacy_counts(s, item)
    audit(s, item.id, u.badge, 'TRACKING_WELD_WORK', {'weld_id': weld.id, 'cycle': weld.cycle, **data.model_dump()})
    _commit(s)
    return weld_dict(s, weld, u)


def _new_requirement(item_id, weld_id, data, u, s):
    permit(u, 'supervisor', 'admin')
    if weld_id:
        item, weld = _lock_weld(s, weld_id)
    else:
        item = lock_item(s, item_id)
        require_unreleased(item)
        _require_plan(s, item)
        weld = None
    if not weld and data.check in ('materials', 'procedure'):
        raise HTTPException(422, 'Material and procedure checks must belong to an individual weld')
    if any(r.code == data.code for r in _requirements(s, item.id, weld.id if weld else None)):
        raise HTTPException(409, 'Requirement code already exists for this scope')
    req = _add_requirement(s, item, weld, data, u.badge)
    _invalidate_final_qa(s, item, weld.id if weld else None, u.badge, 'Additional requirement added')
    _invalidate_spool(item)
    audit(s, item.id, u.badge, 'TRACKING_REQUIREMENT_ADDED', {'weld_id': weld.id if weld else None, **data.model_dump()})
    _commit(s)
    return requirement_dict(s, req, u)


@router.post('/spools/{item_id}/requirements', status_code=201)
def add_spool_requirement(item_id: str, data: RequirementIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    return _new_requirement(item_id, None, data, u, s)


@router.post('/welds/{weld_id}/requirements', status_code=201)
def add_weld_requirement(weld_id: str, data: RequirementIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    return _new_requirement(None, weld_id, data, u, s)


@router.post('/requirements/{requirement_id}/evidence', status_code=201)
def submit_evidence(requirement_id: int, data: EvidenceIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    permit(u, *ROLES)
    item, req = _lock_requirement(s, requirement_id)
    if not can_submit_requirement_evidence(u, req):
        raise HTTPException(403, 'This requirement is assigned to a different position. Ask a supervisor or QA/QC to review its assignment.')
    _version(req, data.expected_version)
    previous = req.status
    evidence = RequirementEvidence(requirement_id=req.id, cycle=req.cycle,
        reference=data.reference, notes=data.notes, result=data.result, actor=u.badge)
    s.add(evidence)
    req.status = 'rejected' if data.result == 'fail' else 'submitted'
    req.version += 1
    req.updated_at = utcnow()
    _invalidate_final_qa(s, item, req.weld_id, u.badge, 'Requirement evidence changed', except_id=req.id)
    _invalidate_spool(item)
    s.flush()
    audit(s, item.id, u.badge, 'TRACKING_EVIDENCE_SUBMITTED', {
        'requirement_id': req.id, 'weld_id': req.weld_id, 'evidence_id': evidence.id,
        'cycle': req.cycle, 'previous_status': previous,
        'reference': data.reference, 'notes': data.notes, 'result': data.result})
    _commit(s)
    return requirement_dict(s, req, u)


@router.post('/requirements/{requirement_id}/review')
def review_requirement(requirement_id: int, data: ReviewIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    permit(u, 'inspector', 'admin')
    item, req = _lock_requirement(s, requirement_id)
    _version(req, data.expected_version)
    evidence = _latest_evidence(s, req)
    weld = s.get(Weld, req.weld_id) if req.weld_id else None
    if data.decision == 'not_applicable':
        if not req.allow_na:
            raise HTTPException(409, 'This required control cannot be marked not applicable')
        if evidence and evidence.result == 'fail':
            raise HTTPException(409, 'A failing result cannot be dismissed as not applicable; resolve its corrective disposition first')
        heat_errors = _requirement_heat_errors(s, req, weld)
        if heat_errors:
            raise HTTPException(409, {'requirement_blockers': heat_errors})
    elif data.decision == 'accepted':
        blockers = _check_errors(s, req, weld)
        if req.evidence_required and evidence is None:
            blockers.append('Current-cycle evidence reference required before acceptance')
        if evidence and evidence.result == 'fail':
            blockers.append('Latest evidence reports failure; record the corrective disposition and new evidence')
        if req.stage in ('after_welding', 'release') and weld and not _production_complete(s, weld):
            blockers.append('Welding must be complete before post-weld acceptance')
        if req.code == 'FINAL_QA' and weld:
            blockers += [r.label + ' is not accepted' for r in _requirements(s, item.id, weld.id)
                         if r.id != req.id and not _requirement_satisfied(s, r, weld)]
            blockers += ['Hold: ' + h.reason for h in _holds(s, item.id, all_scopes=True)
                         if h.closed_at is None and h.weld_id in (None, weld.id)]
            if item.on_hold:
                blockers.append('Item is on hold')
        if blockers:
            raise HTTPException(409, {'requirement_blockers': list(dict.fromkeys(blockers))})
    previous = req.status
    s.add(RequirementReview(requirement_id=req.id, evidence_id=evidence.id if evidence else None,
        cycle=req.cycle, decision=data.decision, notes=data.notes, actor=u.badge))
    req.status = data.decision
    req.version += 1
    req.updated_at = utcnow()
    if data.decision == 'rejected':
        _invalidate_final_qa(s, item, req.weld_id, u.badge, 'Requirement rejected', except_id=req.id)
    _invalidate_spool(item)
    audit(s, item.id, u.badge, 'TRACKING_REQUIREMENT_REVIEWED', {
        'requirement_id': req.id, 'weld_id': req.weld_id, 'cycle': req.cycle,
        'evidence_id': evidence.id if evidence else None, 'previous_status': previous,
        'decision': data.decision, 'notes': data.notes})
    s.flush()
    # Only derived acceptance can update the legacy display. It is never read
    # back as proof of individual weld acceptance.
    welds = _welds(s, item.id)
    if welds and all(_qa_accepted(s, w) for w in welds):
        item.weld = 'Pass'
        item.weld_at = utcnow()
    if not tracking_release_errors(s, item):
        item.reinspection_due = False
    _commit(s)
    return requirement_dict(s, req, u)


@router.post('/welds/{weld_id}/repairs', status_code=201)
def open_weld_repair(weld_id: str, data: ReasonIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    permit(u, 'inspector', 'supervisor', 'admin')
    item, weld = _lock_weld(s, weld_id)
    previous_cycle = weld.cycle
    weld.cycle += 1
    weld.version += 1
    weld.completed_at = None
    weld.completed_by = None
    weld.updated_at = utcnow()
    s.add(WeldRepair(weld_id=weld.id, cycle=weld.cycle, reason=data.reason, opened_by=u.badge))
    _reset_requirements(s, item, _requirements(s, item.id, weld.id) + _requirements(s, item.id), u.badge, data.reason)
    _invalidate_spool(item, physical=True)
    _sync_legacy_counts(s, item)
    audit(s, item.id, u.badge, 'TRACKING_WELD_REPAIR_OPENED', {
        'weld_id': weld.id, 'previous_cycle': previous_cycle, 'cycle': weld.cycle, 'reason': data.reason})
    _commit(s)
    return weld_dict(s, weld, u)


@router.post('/spools/{item_id}/holds', status_code=201)
def open_hold(item_id: str, data: HoldIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    permit(u, 'inspector', 'supervisor', 'admin')
    item = lock_item(s, item_id)
    require_unreleased(item)
    _require_plan(s, item)
    if data.weld_id:
        weld = s.get(Weld, data.weld_id)
        if not weld or weld.item_id != item.id:
            raise HTTPException(422, 'Hold weld must belong to this spool')
    hold = TrackingHold(item_id=item.id, weld_id=data.weld_id, reason=data.reason, opened_by=u.badge)
    s.add(hold)
    if data.weld_id:
        _invalidate_final_qa(s, item, data.weld_id, u.badge, 'Weld hold opened')
    else:
        for weld in _welds(s, item.id):
            _invalidate_final_qa(s, item, weld.id, u.badge, 'Spool hold opened')
    _invalidate_spool(item)
    s.flush()
    audit(s, item.id, u.badge, 'TRACKING_HOLD_OPENED', {'hold_id': hold.id, **data.model_dump()})
    _commit(s)
    return asdict(hold, HOLD_KEYS)


@router.post('/holds/{hold_id}/close')
def close_hold(hold_id: int, data: CloseHoldIn, u: Employee = Depends(auth), s: Session = Depends(db)):
    from flow import lock_topology
    lock_topology(s)
    permit(u, 'inspector', 'admin')
    initial = s.get(TrackingHold, hold_id)
    if not initial:
        raise HTTPException(404, 'Hold not found')
    item = lock_item(s, initial.item_id)
    require_unreleased(item)
    hold = s.scalar(select(TrackingHold).where(TrackingHold.id == hold_id).execution_options(populate_existing=True))
    if hold.closed_at:
        raise HTTPException(409, 'Hold already closed')
    hold.closed_at = utcnow()
    hold.closed_by = u.badge
    hold.close_notes = data.notes
    item.updated_at = utcnow()
    audit(s, item.id, u.badge, 'TRACKING_HOLD_CLOSED', {'hold_id': hold.id, 'weld_id': hold.weld_id, 'notes': data.notes})
    _commit(s)
    return asdict(hold, HOLD_KEYS)


def _filtered_items(s, project_id='', subproject_id=''):
    from removals import item_not_removed, project_not_removed
    q = select(Item).join(SpoolPlan, SpoolPlan.item_id == Item.id).where(
        item_not_removed(), project_not_removed(SpoolPlan.project_id))
    if project_id:
        q = q.where(SpoolPlan.project_id == project_id)
    if subproject_id:
        q = q.where(SpoolPlan.subproject_id == subproject_id)
    return s.scalars(q.order_by(SpoolPlan.due_date, Item.id)).all()


@router.get('/overview')
def overview(project_id: str = '', subproject_id: str = '', u: Employee = Depends(auth), s: Session = Depends(db)):
    with read_projection(s):
        rows = _filtered_items(s, project_id, subproject_id)
        prime_projection(s, rows)
        prime_tracking_read_snapshots(s, (item.id for item in rows))
        from spool_presentation import item_presentations
        displays = item_presentations(s, rows)
        spools = [{**tracking_summary(s, item), **displays[item.id]} for item in rows]
        return {
            'projects': get_projects(u, s),
            'subprojects': get_subprojects('', u, s),
            'templates': get_templates(u, s),
            'spools': spools,
            'metrics': {
                'spools': len(spools),
                'welds_planned': sum(r['planned_welds'] for r in spools),
                'welds_defined': sum(r['welds_defined'] for r in spools),
                'production_complete': sum(r['production_complete'] for r in spools),
                'qa_accepted': sum(r['qa_accepted'] for r in spools),
                'ready_to_release': sum(r['ready_to_release'] and not r['released'] for r in spools),
                'released': sum(r['released'] for r in spools),
            },
        }


@_snapshot_response
def _item_exceptions(s, item):
    result = []
    welds = _welds(s, item.id)
    weld_by_id = {w.id: w for w in welds}
    plan = read_get(s, SpoolPlan, item.id)
    base = {'item_id': item.id, 'weld_id': None, 'weld_number': None, 'requirement_id': None}
    if len(welds) != plan.planned_welds:
        result.append({**base, 'type': 'scope', 'label': f'{len(welds)} of {plan.planned_welds} welds defined', 'status': 'pending', 'owner_role': 'supervisor'})
    for req in _requirements(s, item.id, all_scopes=True):
        weld = weld_by_id.get(req.weld_id)
        if not _requirement_satisfied(s, req, weld):
            result.append({**base, 'weld_id': req.weld_id, 'weld_number': weld.number if weld else None,
                'requirement_id': req.id, 'type': 'requirement', 'label': req.label,
                'status': req.status, 'owner_role': req.owner_role})
    for weld in welds:
        if not _production_complete(s, weld):
            result.append({**base, 'weld_id': weld.id, 'weld_number': weld.number, 'type': 'work',
                'label': 'Configured welding operations incomplete', 'status': 'pending', 'owner_role': 'welder'})
    for hold in _holds(s, item.id, all_scopes=True):
        if hold.closed_at is None:
            weld = weld_by_id.get(hold.weld_id)
            result.append({**base, 'weld_id': hold.weld_id, 'weld_number': weld.number if weld else None,
                'type': 'hold', 'label': hold.reason, 'status': 'hold', 'owner_role': 'inspector', 'hold_id': hold.id})
    if item.on_hold:
        result.append({**base, 'type': 'hold', 'label': 'Item is on hold', 'status': 'hold', 'owner_role': 'inspector'})
    if item.dimensional != 'Pass' or not _after(item.dimension_at, item.last_work_at):
        result.append({**base, 'type': 'dimensional', 'label': 'Spool dimensional inspection required', 'status': 'pending', 'owner_role': 'inspector'})
    if _snapshot(s, item.id)['open_rework']:
        result.append({**base, 'type': 'rework', 'label': 'Open spool rework exists', 'status': 'hold', 'owner_role': 'supervisor'})
    return result


@router.get('/exceptions')
def exceptions(project_id: str = '', subproject_id: str = '', u: Employee = Depends(auth), s: Session = Depends(db)):
    with read_projection(s):
        result = []
        rows = _filtered_items(s, project_id, subproject_id)
        prime_projection(s, rows)
        prime_tracking_read_snapshots(s, (item.id for item in rows))
        from spool_presentation import item_presentations
        displays = item_presentations(s, rows)
        for item in rows:
            result.extend({**row, **displays[item.id]} for row in _item_exceptions(s, item))
        return {'exceptions': result}


