"""Evidence-based audit readiness without manufacturing compliance claims.

Workspaces are explicitly created; draft templates never become actual records.
Document revisions, evidence, reviews and events are append-only. Verification
binds to a deterministic snapshot and becomes stale when its basis changes.
All mutations lock the existing production topology before a workspace row.
"""

import datetime as dt
import hashlib
import json
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Session

from main import Base, Employee, Item, Rework, audit, auth, db, utcnow
from tracking import Project, SpoolPlan, Weld, WeldRequirement, TrackingHold
from permissions import has_capability, require_capability
from quality_templates import TEMPLATE_VERSION, SOURCE_NOTE, SOURCE_DOCUMENTS, TEMPLATES, EVIDENCE_TYPES

router = APIRouter(prefix='/api/quality', tags=['quality'])
EVIDENCE_KINDS = {row['value']: row for row in EVIDENCE_TYPES}


class QualityWorkspace(Base):
    __tablename__ = 'quality_workspaces'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    customer = Column(String(160), nullable=False)
    project_id = Column(String(80), ForeignKey('tracking_projects.id'), index=True)
    purchase_order = Column(String(200), nullable=False, default='')
    audit_date = Column(String(10))
    owner_badge = Column(String(80), ForeignKey('employees.badge'))
    template_version = Column(String(80), nullable=False, default='')
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class QualityRequirement(Base):
    __tablename__ = 'quality_requirements'
    __table_args__ = (UniqueConstraint('workspace_id', 'item_number', name='uq_quality_requirement_number'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey('quality_workspaces.id'), nullable=False, index=True)
    item_number = Column(String(40), nullable=False)
    title = Column(String(240), nullable=False)
    requirement_text = Column(Text, nullable=False)
    response_text = Column(Text, nullable=False, default='')
    source_document = Column(String(500), nullable=False, default='')
    source_revision = Column(String(160), nullable=False, default='')
    source_section = Column(String(300), nullable=False, default='')
    source_reference = Column(String(1000), nullable=False, default='')
    supporting_documents = Column(Text, nullable=False, default='')
    required_evidence = Column(Text, nullable=False, default='')
    gaps = Column(Text, nullable=False, default='')
    priority = Column(String(20), nullable=False, default='high')
    owner_badge = Column(String(80), ForeignKey('employees.badge'))
    due_date = Column(String(10))
    applicability = Column(String(30), nullable=False, default='applicable')
    applicability_reason = Column(Text, nullable=False, default='')
    required_evidence_types = Column(JSON, nullable=False, default=list)
    document_ids = Column(JSON, nullable=False, default=list)
    requires_closed_action = Column(Boolean, nullable=False, default=False)
    requires_approved_document = Column(Boolean, nullable=False, default=False)
    gate = Column(String(30), nullable=False, default='none')
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class QualityDocument(Base):
    __tablename__ = 'quality_documents'
    __table_args__ = (UniqueConstraint('workspace_id', 'code', 'revision', name='uq_quality_document_revision'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey('quality_workspaces.id'), nullable=False, index=True)
    code = Column(String(100), nullable=False)
    title = Column(String(240), nullable=False)
    revision = Column(String(80), nullable=False)
    reference = Column(String(1000), nullable=False)
    effective_date = Column(String(10))
    requires_training = Column(Boolean, nullable=False, default=False)
    required_badges = Column(JSON, nullable=False, default=list)
    notes = Column(Text, nullable=False, default='')
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class QualityEvidence(Base):
    __tablename__ = 'quality_evidence'
    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey('quality_workspaces.id'), nullable=False, index=True)
    requirement_id = Column(Integer, ForeignKey('quality_requirements.id'), nullable=False, index=True)
    type = Column(String(40), nullable=False)
    title = Column(String(240), nullable=False)
    reference = Column(String(1000), nullable=False)
    occurred_on = Column(String(10), nullable=False)
    notes = Column(Text, nullable=False, default='')
    document_id = Column(Integer, ForeignKey('quality_documents.id'))
    related_evidence_id = Column(Integer, ForeignKey('quality_evidence.id'))
    item_id = Column(String(60), ForeignKey('items.id'))
    weld_id = Column(String(60), ForeignKey('tracking_welds.id'))
    participants = Column(JSON, nullable=False, default=list)
    performed_by = Column(String(200), nullable=False, default='')
    data = Column(JSON, nullable=False, default=dict)
    production_snapshot = Column(JSON, nullable=False, default=dict)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class QualityAction(Base):
    __tablename__ = 'quality_actions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey('quality_workspaces.id'), nullable=False, index=True)
    requirement_id = Column(Integer, ForeignKey('quality_requirements.id'), nullable=False, index=True)
    title = Column(String(240), nullable=False)
    owner_badge = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    due_date = Column(String(10), nullable=False)
    problem = Column(Text, nullable=False)
    containment = Column(Text, nullable=False, default='')
    root_cause = Column(Text, nullable=False, default='')
    correction = Column(Text, nullable=False, default='')
    corrective_action = Column(Text, nullable=False, default='')
    status = Column(String(30), nullable=False, default='open')
    closure_evidence_ids = Column(JSON, nullable=False, default=list)
    effectiveness_evidence_id = Column(Integer, ForeignKey('quality_evidence.id'))
    customer_approval_required = Column(Boolean, nullable=False, default=False)
    customer_approval_evidence_id = Column(Integer, ForeignKey('quality_evidence.id'))
    version = Column(Integer, nullable=False, default=1)
    closed_by = Column(String(80), ForeignKey('employees.badge'))
    closed_at = Column(DateTime(timezone=True))
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class QualityReview(Base):
    __tablename__ = 'quality_reviews'
    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey('quality_workspaces.id'), nullable=False, index=True)
    target_type = Column(String(30), nullable=False)
    target_id = Column(Integer, nullable=False)
    decision = Column(String(30), nullable=False)
    reference = Column(String(1000), nullable=False)
    notes = Column(Text, nullable=False)
    fingerprint = Column(String(64), nullable=False)
    snapshot = Column(JSON, nullable=False)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class QualityEvent(Base):
    __tablename__ = 'quality_events'
    __table_args__ = (UniqueConstraint('workspace_id', 'sequence', name='uq_quality_event_sequence'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey('quality_workspaces.id'), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event = Column(String(80), nullable=False)
    target_type = Column(String(30), nullable=False)
    target_id = Column(Integer, nullable=False)
    details = Column(JSON, nullable=False)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Versioned(Input):
    expected_version: int = Field(ge=1)


class WorkspaceFields(Input):
    name: str = Field(min_length=2, max_length=200)
    customer: str = Field(default='Kelvion', min_length=2, max_length=160)
    project_id: str | None = Field(default=None, max_length=80)
    purchase_order: str = Field(default='', max_length=200)
    audit_date: dt.date | None = None
    owner_badge: str | None = Field(default=None, max_length=80)


class WorkspaceIn(WorkspaceFields):
    template: Literal['kelvion', 'blank'] = 'kelvion'


class WorkspaceUpdate(WorkspaceFields, Versioned):
    pass


class RequirementIn(Versioned):
    item_number: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=2, max_length=240)
    requirement_text: str = Field(min_length=4, max_length=20000)
    response_text: str = Field(default='', max_length=20000)
    source_document: str = Field(default='', max_length=500)
    source_revision: str = Field(default='', max_length=160)
    source_section: str = Field(default='', max_length=300)
    source_reference: str = Field(default='', max_length=1000)
    supporting_documents: str = Field(default='', max_length=10000)
    required_evidence: str = Field(default='', max_length=10000)
    gaps: str = Field(default='', max_length=10000)
    priority: Literal['normal', 'high', 'critical'] = 'high'
    owner_badge: str | None = Field(default=None, max_length=80)
    due_date: dt.date | None = None
    applicability: Literal['applicable', 'conditional', 'not_applicable'] = 'applicable'
    applicability_reason: str = Field(default='', max_length=5000)
    required_evidence_types: list[str] = Field(default_factory=list, max_length=30)
    document_ids: list[int] = Field(default_factory=list, max_length=100)
    requires_closed_action: bool = False
    requires_approved_document: bool = False
    gate: Literal['none', 'pre_coating', 'shipment'] = 'none'


class DocumentIn(Versioned):
    code: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=2, max_length=240)
    revision: str = Field(min_length=1, max_length=80)
    reference: str = Field(min_length=2, max_length=1000)
    effective_date: dt.date
    requires_training: bool = False
    required_badges: list[str] = Field(default_factory=list, max_length=1000)
    notes: str = Field(default='', max_length=10000)


class EvidenceIn(Versioned):
    requirement_id: int = Field(ge=1)
    type: str = Field(min_length=2, max_length=40)
    title: str = Field(min_length=2, max_length=240)
    reference: str = Field(min_length=2, max_length=1000)
    occurred_on: dt.date
    notes: str = Field(default='', max_length=10000)
    document_id: int | None = Field(default=None, ge=1)
    related_evidence_id: int | None = Field(default=None, ge=1)
    item_id: str | None = Field(default=None, max_length=60)
    weld_id: str | None = Field(default=None, max_length=60)
    participants: list[str] = Field(default_factory=list, max_length=1000)
    performed_by: str = Field(default='', max_length=200)
    data: dict = Field(default_factory=dict)


class ActionIn(Versioned):
    requirement_id: int = Field(ge=1)
    title: str = Field(min_length=2, max_length=240)
    owner_badge: str = Field(min_length=1, max_length=80)
    due_date: dt.date
    problem: str = Field(min_length=4, max_length=10000)
    containment: str = Field(default='', max_length=10000)
    root_cause: str = Field(default='', max_length=10000)
    correction: str = Field(default='', max_length=10000)
    corrective_action: str = Field(default='', max_length=10000)
    status: Literal['open', 'implemented'] = 'open'
    closure_evidence_ids: list[int] = Field(default_factory=list, max_length=100)
    effectiveness_evidence_id: int | None = Field(default=None, ge=1)
    customer_approval_required: bool = False
    customer_approval_evidence_id: int | None = Field(default=None, ge=1)


class ReviewIn(Versioned):
    target_type: Literal['source', 'requirement', 'document', 'evidence', 'action']
    target_id: int = Field(ge=1)
    decision: str = Field(min_length=2, max_length=30)
    reference: str = Field(min_length=2, max_length=1000)
    notes: str = Field(min_length=4, max_length=10000)


def _fmt(value):
    if isinstance(value, dt.datetime):
        return (value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def row_dict(row):
    return {col.name: _fmt(getattr(row, col.name)) for col in row.__table__.columns}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _values(data, *exclude):
    return {k: _fmt(v) for k, v in data.model_dump(exclude={'expected_version', *exclude}).items()}


def _error(message, status=409):
    raise HTTPException(status, message)


def _one(s, model, identifier, workspace_id):
    obj = s.get(model, identifier)
    if not obj or obj.workspace_id != workspace_id:
        _error('Record not found in this audit workspace', 404)
    return obj


def _badge(s, badge, required=False):
    if not badge and not required:
        return
    employee = s.get(Employee, badge) if badge else None
    if not employee or not employee.active:
        _error('An active employee badge is required: ' + str(badge or '(missing)'), 422)


def _badges(s, badges, required=False):
    if not isinstance(badges, list) or any(not isinstance(x, str) or not x.strip() or len(x) > 80 for x in badges):
        _error('Employee badges must be a list of nonempty badge IDs', 422)
    if len(badges) > 1000 or len(set(badges)) != len(badges):
        _error('Employee badge lists must contain at most 1,000 distinct employees', 422)
    if required and not badges:
        _error('Identify the employees who require or completed this training', 422)
    for badge in badges:
        _badge(s, badge, True)


def _workspace(s, workspace_id, expected=None):
    if expected is not None:
        from flow import lock_topology
        lock_topology(s)
    query = select(QualityWorkspace).where(QualityWorkspace.id == workspace_id)
    if expected is not None:
        query = query.with_for_update().execution_options(populate_existing=True)
    workspace = s.scalar(query)
    if not workspace:
        _error('Audit workspace not found', 404)
    if expected is not None and workspace.project_id:
        from removals import require_active_project
        require_active_project(s, workspace.project_id)
    if expected is not None and workspace.version != expected:
        _error('This audit workspace changed. Refresh before saving your changes.')
    return workspace


def _event(s, workspace, actor, event, target_type, target_id, details, *, initial=False):
    if not initial:
        workspace.version += 1
    workspace.updated_at = utcnow()
    entry = QualityEvent(workspace_id=workspace.id, sequence=workspace.version,
                         event=event, target_type=target_type, target_id=target_id,
                         details=details, actor=actor, at=workspace.updated_at)
    s.add(entry)
    audit(s, None, actor, 'QUALITY_' + event, {'workspace_id': workspace.id,
          'sequence': workspace.version, 'target_type': target_type, 'target_id': target_id,
          'details': details})


def _check_scope(s, values):
    from removals import require_active_project
    if values.get('project_id'):
        require_active_project(s, values['project_id'])
    if values.get('project_id') and not s.get(Project, values['project_id']):
        _error('Tracking project not found', 422)
    _badge(s, values.get('owner_badge'))


def _physical(s, item_id, weld_id, cache=None):
    """Only quality-changing state: a routine handoff must not stale test reports."""
    if not item_id and not weld_id:
        return {}
    if cache is not None:
        item = cache['items'].get(item_id)
        weld = cache['welds'].get(weld_id) if weld_id else None
        component_link = cache['component_links'].get(item_id)
        plan = cache['plans'].get(item_id) or (cache['plans'].get(component_link.spool_id) if component_link else None)
        holds = cache['holds'].get(item_id, [])
        reworks = cache['reworks'].get(item_id, [])
        requirements = cache['weld_requirements'].get(item_id, [])
    else:
        from flow import ComponentLink
        weld = s.get(Weld, weld_id) if weld_id else None
        if weld and not item_id:
            item_id = weld.item_id
        item = s.get(Item, item_id) if item_id else None
        component_link = s.get(ComponentLink, item_id) if item_id else None
        plan = s.get(SpoolPlan, item_id) if item_id else None
        if not plan and component_link:
            plan = s.get(SpoolPlan, component_link.spool_id)
        holds = list(s.scalars(select(TrackingHold).where(TrackingHold.item_id == item_id, TrackingHold.closed_at.is_(None)).order_by(TrackingHold.id))) if item else []
        reworks = list(s.scalars(select(Rework).where(Rework.item_id == item_id, Rework.closed_at.is_(None)).order_by(Rework.id))) if item else []
        requirements = list(s.scalars(select(WeldRequirement).where(WeldRequirement.item_id == item_id).order_by(WeldRequirement.id))) if item else []
    snapshot = {'item_id': item_id, 'weld_id': weld_id, 'project_id': plan.project_id if plan else None,
                'component_spool_id': component_link.spool_id if component_link else None,
                'drawing_revision': plan.drawing_revision if plan else None,
                'item': {key: _fmt(getattr(item, key)) for key in ('drawing', 'last_work_at', 'dimension_at', 'weld_at', 'reinspection_due', 'on_hold')} if item else None,
                'weld': {key: _fmt(getattr(weld, key)) for key in ('id', 'item_id', 'version', 'cycle', 'completed_at')} if weld else None,
                'open_holds': [h.id for h in holds], 'open_reworks': [r.id for r in reworks],
                'weld_requirements': [{key: getattr(r, key) for key in ('id', 'weld_id', 'version', 'cycle', 'status')} for r in requirements]}
    return snapshot


def _context(s, workspace, as_of=None):
    """Load one workspace once; per-requirement projection performs no queries."""
    ctx = {'workspace': workspace, 'as_of': as_of or utcnow(), 'latest': {}, 'doc_cache': {}, 'ev_cache': {}, 'req_cache': {}}
    for key, model in [('requirements', QualityRequirement), ('documents', QualityDocument),
                       ('evidence', QualityEvidence), ('actions', QualityAction),
                       ('reviews', QualityReview), ('events', QualityEvent)]:
        rows = list(s.scalars(select(model).where(model.workspace_id == workspace.id).order_by(model.id)))
        ctx[key] = rows
        ctx[key + '_by_id'] = {r.id: r for r in rows}
    for review in ctx['reviews']:
        ctx['latest'][(review.target_type, review.target_id)] = review
    item_ids = {r.item_id for r in ctx['evidence'] if r.item_id}
    weld_ids = {r.weld_id for r in ctx['evidence'] if r.weld_id}
    physical = {'items': {}, 'plans': {}, 'welds': {}, 'component_links': {}, 'holds': defaultdict(list), 'reworks': defaultdict(list), 'weld_requirements': defaultdict(list)}
    if weld_ids:
        physical['welds'] = {r.id: r for r in s.scalars(select(Weld).where(Weld.id.in_(weld_ids)))}
    if item_ids:
        from flow import ComponentLink
        physical['items'] = {r.id: r for r in s.scalars(select(Item).where(Item.id.in_(item_ids)))}
        physical['component_links'] = {r.component_id: r for r in s.scalars(select(ComponentLink).where(ComponentLink.component_id.in_(item_ids)))}
        plan_ids = item_ids | {r.spool_id for r in physical['component_links'].values()}
        physical['plans'] = {r.item_id: r for r in s.scalars(select(SpoolPlan).where(SpoolPlan.item_id.in_(plan_ids)))}
        for key, model, query in [('holds', TrackingHold, select(TrackingHold).where(TrackingHold.item_id.in_(item_ids), TrackingHold.closed_at.is_(None)).order_by(TrackingHold.id)),
                                  ('reworks', Rework, select(Rework).where(Rework.item_id.in_(item_ids), Rework.closed_at.is_(None)).order_by(Rework.id)),
                                  ('weld_requirements', WeldRequirement, select(WeldRequirement).where(WeldRequirement.item_id.in_(item_ids)).order_by(WeldRequirement.id))]:
            for obj in s.scalars(query):
                physical[key][obj.item_id].append(obj)
    ctx['physical'] = physical
    return ctx


def _latest(ctx, kind, identifier):
    return ctx['latest'].get((kind, identifier))


def _review_dict(review):
    return row_dict(review) if review else None


def _evidence_basis(ctx, evidence):
    document = ctx['documents_by_id'].get(evidence.document_id) if evidence.document_id else None
    alert = ctx['evidence_by_id'].get(evidence.related_evidence_id) if evidence.type == 'training' and evidence.related_evidence_id else None
    return {'record': row_dict(evidence), 'current_production': _physical(None, evidence.item_id, evidence.weld_id, ctx['physical']),
            'document': _document_basis(ctx, document) if document else None,
            # Training can refer only to an older Quality Alert, never another
            # training entry. The alert projection therefore cannot recurse.
            'quality_alert': _evidence_view(ctx, alert) if alert else None}


def _evidence_view(ctx, evidence):
    if evidence.id in ctx['ev_cache']:
        return ctx['ev_cache'][evidence.id]
    review = _latest(ctx, 'evidence', evidence.id)
    basis = _evidence_basis(ctx, evidence)
    stale = bool(evidence.production_snapshot != basis['current_production'])
    status = 'submitted'
    if review and review.decision == 'rejected':
        status = 'rejected'
    elif review and review.decision == 'accepted' and review.fingerprint == _digest(basis) and not stale:
        status = 'accepted'
    result = {**row_dict(evidence), 'status': status, 'stale': stale,
              'latest_review': _review_dict(review)}
    ctx['ev_cache'][evidence.id] = result
    return result


def _basic_document_status(ctx, document):
    review = _latest(ctx, 'document', document.id)
    return ('approved' if review and review.decision == 'approved' else
            'superseded' if review and review.decision == 'superseded' else 'draft')


def _document_basis(ctx, document):
    """Document validity without training coverage (avoids a dependency loop)."""
    status = _basic_document_status(ctx, document)
    today = ctx['as_of'].date().isoformat()
    if status == 'approved':
        for newer in ctx['documents']:
            if newer.code != document.code or newer.id <= document.id or not newer.effective_date or newer.effective_date > today:
                continue
            approved = any(r.target_type == 'document' and r.target_id == newer.id and r.decision == 'approved' for r in ctx['reviews'])
            latest = _latest(ctx, 'document', newer.id)
            cancelled_before_effective = bool(latest and latest.decision == 'superseded'
                 and _fmt(latest.at)[:10] < newer.effective_date)
            if approved and not cancelled_before_effective:
                status = 'superseded'
                break
    return {**row_dict(document), 'status': status,
            'effective': bool(document.effective_date and document.effective_date <= today),
            'latest_review': _review_dict(_latest(ctx, 'document', document.id))}


def _document_view(ctx, document):
    if document.id in ctx['doc_cache']:
        return ctx['doc_cache'][document.id]
    basis = _document_basis(ctx, document)
    trained = set()
    for evidence in ctx['evidence']:
        if evidence.type == 'training' and evidence.document_id == document.id and _evidence_view(ctx, evidence)['status'] == 'accepted':
            trained.update(evidence.participants)
    training_gaps = sorted(set(document.required_badges) - trained) if document.requires_training else []
    result = {**basis, 'training_gaps': training_gaps}
    ctx['doc_cache'][document.id] = result
    return result


def _source_basis(requirement, workspace):
    return {**{key: getattr(requirement, key) for key in ('requirement_text', 'source_document', 'source_revision',
                'source_section', 'source_reference', 'applicability', 'applicability_reason')},
            'workspace_scope': {key: getattr(workspace, key) for key in ('project_id', 'customer', 'purchase_order')}}


def _source_status(ctx, requirement):
    review = _latest(ctx, 'source', requirement.id)
    return 'confirmed' if review and review.decision == 'confirmed' and review.fingerprint == _digest(_source_basis(requirement, ctx['workspace'])) else 'unconfirmed'


def _accepted(ctx, identifier, requirement_id=None, kind=None):
    evidence = ctx['evidence_by_id'].get(identifier)
    return bool(evidence and (requirement_id is None or evidence.requirement_id == requirement_id)
                and (kind is None or evidence.type == kind) and _evidence_view(ctx, evidence)['status'] == 'accepted')


def _action_closure_errors(ctx, action):
    errors = []
    if action.status not in ('implemented', 'closed'):
        errors.append('Corrective action must be implemented before closure.')
    for key in ('containment', 'root_cause', 'correction', 'corrective_action'):
        if not getattr(action, key).strip():
            errors.append('Record ' + key.replace('_', ' ') + ' before closure.')
    if not action.closure_evidence_ids or any(not _accepted(ctx, identifier, action.requirement_id)
                                            for identifier in action.closure_evidence_ids):
        errors.append('Accepted implementation/closure evidence for this requirement is required.')
    if not _accepted(ctx, action.effectiveness_evidence_id, action.requirement_id, 'effectiveness'):
        errors.append('Accepted effectiveness verification for this requirement is required.')
    elif action.closure_evidence_ids:
        effectiveness = ctx['evidence_by_id'][action.effectiveness_evidence_id]
        implementation_dates = [ctx['evidence_by_id'][identifier].occurred_on for identifier in action.closure_evidence_ids
                                if identifier in ctx['evidence_by_id']]
        if implementation_dates and effectiveness.occurred_on < max(implementation_dates):
            errors.append('Effectiveness verification cannot precede the latest implementation/closure evidence.')
    if action.customer_approval_required and not _accepted(ctx, action.customer_approval_evidence_id,
                                                         action.requirement_id, 'customer_approval'):
        errors.append('Accepted written customer approval for this requirement is required.')
    return errors


def _action_view(ctx, action):
    result = row_dict(action)
    errors = _action_closure_errors(ctx, action) if action.status == 'closed' else []
    result['closure_stale'] = bool(errors)
    result['closure_blockers'] = errors
    result['overdue'] = action.status != 'closed' and action.due_date < ctx['as_of'].date().isoformat()
    return result


def _requirement_basis(ctx, requirement):
    evidence = [r for r in ctx['evidence'] if r.requirement_id == requirement.id]
    document_ids = set(requirement.document_ids)
    related_training = [r for r in ctx['evidence'] if r.type == 'training' and
                        (r.document_id in document_ids or r.related_evidence_id in {e.id for e in evidence})]
    relevant_evidence = {r.id: r for r in evidence + related_training}
    return {'requirement': row_dict(requirement), 'workspace_scope': {'project_id': ctx['workspace'].project_id,
                'customer': ctx['workspace'].customer, 'purchase_order': ctx['workspace'].purchase_order},
            'source_review': _review_dict(_latest(ctx, 'source', requirement.id)),
            'documents': [_document_view(ctx, ctx['documents_by_id'][identifier]) for identifier in sorted(document_ids) if identifier in ctx['documents_by_id']],
            'evidence': [_evidence_view(ctx, r) for r in sorted(relevant_evidence.values(), key=lambda row: row.id)],
            'actions': [_action_view(ctx, r) for r in ctx['actions'] if r.requirement_id == requirement.id]}


def _requirement_view(ctx, requirement):
    if requirement.id in ctx['req_cache']:
        return ctx['req_cache'][requirement.id]
    basis = _requirement_basis(ctx, requirement)
    source_status = _source_status(ctx, requirement)
    errors = []
    if source_status != 'confirmed':
        errors.append('Confirm the actual source, revision, section and project applicability.')
    if requirement.applicability == 'conditional':
        errors.append('Resolve conditional applicability for this project.')
    if requirement.applicability == 'not_applicable' and not requirement.applicability_reason.strip():
        errors.append('Record the reason this requirement is not applicable.')
    actions = [r for r in ctx['actions'] if r.requirement_id == requirement.id]
    for action in actions:
        if action.status != 'closed':
            errors.append(f'Corrective action {action.id} remains {action.status}: {action.title}.')
        elif _action_closure_errors(ctx, action):
            errors.append(f'Corrective action {action.id} closure evidence is no longer current.')
    if requirement.applicability != 'not_applicable':
        if requirement.gaps.strip():
            errors.append('Resolve the recorded gaps and update the gap statement before verification.')
        if not requirement.response_text.strip() or requirement.response_text.upper().startswith('DRAFT'):
            errors.append('Finalize the CLM response after checking implementation; it is still blank or marked DRAFT.')
        accepted = [r for r in ctx['evidence'] if r.requirement_id == requirement.id and _evidence_view(ctx, r)['status'] == 'accepted']
        accepted_types = {r.type for r in accepted}
        newest_by_type = {r.type: r for r in ctx['evidence'] if r.requirement_id == requirement.id}
        for kind in requirement.required_evidence_types:
            if kind not in accepted_types:
                errors.append('Provide accepted actual evidence: ' + EVIDENCE_KINDS.get(kind, {'label': kind})['label'] + '.')
            elif kind in newest_by_type and _evidence_view(ctx, newest_by_type[kind])['status'] != 'accepted':
                errors.append('The latest ' + EVIDENCE_KINDS[kind]['label'] + ' record is not accepted; review or replace it before verification.')
        for identifier in requirement.document_ids:
            document = ctx['documents_by_id'].get(identifier)
            if not document:
                errors.append(f'Linked document {identifier} is missing from this workspace.')
                continue
            doc = _document_view(ctx, document)
            if doc['status'] != 'approved' or not doc['effective']:
                errors.append(f'Document {document.code} Rev {document.revision} is not the current effective approved revision.')
            if doc['training_gaps']:
                errors.append(f'Document {document.code} Rev {document.revision} lacks accepted training for: ' + ', '.join(doc['training_gaps']) + '.')
        if not requirement.document_ids and not accepted:
            errors.append('Link an approved supporting document or accepted actual evidence; draft narrative alone is insufficient.')
        if requirement.requires_approved_document and not any(
                d['status'] == 'approved' and d['effective'] for d in basis['documents']):
            errors.append('This requirement requires at least one linked current approved supporting document.')
        for evidence in accepted:
            if evidence.type == 'quality_alert' and evidence.data.get('training_required'):
                trained = {badge for training in ctx['evidence'] if training.type == 'training'
                           and training.related_evidence_id == evidence.id and _evidence_view(ctx, training)['status'] == 'accepted'
                           for badge in training.participants}
                missing = sorted(set(evidence.data.get('required_participants', [])) - trained)
                if missing:
                    errors.append(f'Quality Alert {evidence.id} lacks accepted training for: ' + ', '.join(missing) + '.')
        if requirement.requires_closed_action and not any(a.status == 'closed' and not _action_closure_errors(ctx, a) for a in actions):
            errors.append('Demonstrate at least one completed and verified corrective action.')
    latest = _latest(ctx, 'requirement', requirement.id)
    current_review = latest and latest.fingerprint == _digest(basis)
    desired = 'not_applicable' if requirement.applicability == 'not_applicable' else 'verified'
    if current_review and latest.decision == desired and not errors:
        status = desired
    elif errors:
        activity = bool(accepted if requirement.applicability != 'not_applicable' else False) or bool(requirement.document_ids) or bool(actions) or latest is not None
        status = 'needs_attention' if activity else 'draft'
    else:
        status = 'ready_for_review'
    if latest and latest.decision in ('verified', 'not_applicable') and not current_review:
        errors.append('Previous verification is stale because the requirement or supporting basis changed; review again.')
        if status == 'ready_for_review':
            status = 'in_progress'
    result = {**row_dict(requirement), 'status': status, 'blockers': errors, 'source_status': source_status,
              'latest_review': _review_dict(latest), 'overdue': bool(requirement.due_date and requirement.due_date < ctx['as_of'].date().isoformat() and status not in ('verified', 'not_applicable'))}
    ctx['req_cache'][requirement.id] = result
    return result


def workspace_detail(s, workspace, user, as_of=None):
    from removals import project_is_removed, removal_summary
    active = not (workspace.project_id and project_is_removed(s, workspace.project_id))
    ctx = _context(s, workspace, as_of=as_of)
    requirements = [_requirement_view(ctx, row) for row in ctx['requirements']]
    actions = [_action_view(ctx, row) for row in ctx['actions']]
    metrics = {'total': len(requirements), 'verified': sum(r['status'] == 'verified' for r in requirements),
               'not_applicable': sum(r['status'] == 'not_applicable' for r in requirements),
               'needs_attention': sum(r['status'] not in ('verified', 'not_applicable') for r in requirements),
               'ready_for_review': sum(r['status'] == 'ready_for_review' for r in requirements),
               'priority_open': sum(r['priority'] == 'critical' and r['status'] not in ('verified', 'not_applicable') for r in requirements),
               'open_actions': sum(r['status'] != 'closed' or r['closure_stale'] for r in actions),
               'overdue_actions': sum(r['overdue'] for r in actions)}
    return {'workspace': row_dict(workspace), 'requirements': requirements,
            'removal': removal_summary(s, 'order', workspace.project_id) if workspace.project_id else None,
            'can_mutate': active,
            'documents': [_document_view(ctx, row) for row in ctx['documents']],
            'evidence': [_evidence_view(ctx, row) for row in ctx['evidence']], 'actions': actions,
            'reviews': [row_dict(row) for row in ctx['reviews']], 'events': [row_dict(row) for row in ctx['events']],
            'metrics': metrics, 'permissions': {'manage': active and has_capability(user, 'manage_production'),
                    'write': active and has_capability(user, 'quality_write'), 'review': active and has_capability(user, 'quality_review')}}


def _finish(s, workspace, user):
    s.commit()
    return workspace_detail(s, workspace, user)


@router.get('/catalog')
def catalog(user: Employee = Depends(auth)):
    return {'template_version': TEMPLATE_VERSION, 'source_note': SOURCE_NOTE,
            'source_documents': SOURCE_DOCUMENTS, 'templates': TEMPLATES, 'evidence_types': EVIDENCE_TYPES}


@router.get('/workspaces')
def list_workspaces(user: Employee = Depends(auth), s: Session = Depends(db)):
    from removals import project_not_removed
    result = []
    for workspace in s.scalars(select(QualityWorkspace).where(project_not_removed(QualityWorkspace.project_id)).order_by(QualityWorkspace.id.desc())):
        detail = workspace_detail(s, workspace, user)
        result.append({**detail['workspace'], 'metrics': detail['metrics']})
    return {'workspaces': result}


@router.post('/workspaces', status_code=201)
def create_workspace(data: WorkspaceIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    require_capability(user, 'manage_production')
    from flow import lock_topology
    lock_topology(s)
    values = _values(data, 'template')
    _check_scope(s, values)
    workspace = QualityWorkspace(**values, template_version=TEMPLATE_VERSION if data.template == 'kelvion' else '', created_by=user.badge)
    s.add(workspace)
    s.flush()
    if data.template == 'kelvion':
        for draft in TEMPLATES:
            s.add(QualityRequirement(workspace_id=workspace.id, **draft, created_by=user.badge))
    s.flush()
    _event(s, workspace, user.badge, 'WORKSPACE_CREATED', 'workspace', workspace.id,
           {'workspace': row_dict(workspace), 'template': data.template, 'source_note': SOURCE_NOTE,
            'draft_requirements': len(TEMPLATES) if data.template == 'kelvion' else 0}, initial=True)
    return _finish(s, workspace, user)


@router.get('/workspaces/{workspace_id}')
def get_workspace(workspace_id: int, user: Employee = Depends(auth), s: Session = Depends(db)):
    return workspace_detail(s, _workspace(s, workspace_id), user)


@router.put('/workspaces/{workspace_id}')
def update_workspace(workspace_id: int, data: WorkspaceUpdate, user: Employee = Depends(auth), s: Session = Depends(db)):
    require_capability(user, 'manage_production')
    workspace = _workspace(s, workspace_id, data.expected_version)
    values = _values(data)
    _check_scope(s, values)
    if values['project_id'] != workspace.project_id:
        has_dependencies = s.scalar(select(QualityEvidence.id).where(QualityEvidence.workspace_id == workspace_id).limit(1)) or s.scalar(select(QualityRequirement.id).where(QualityRequirement.workspace_id == workspace_id, QualityRequirement.gate != 'none').limit(1))
        if has_dependencies:
            _error('Project scope is fixed after evidence or production gates are recorded. Create a separate workspace for another project.')
    before = row_dict(workspace)
    for key, value in values.items():
        setattr(workspace, key, value)
    _event(s, workspace, user.badge, 'WORKSPACE_UPDATED', 'workspace', workspace.id, {'before': before, 'after': row_dict(workspace)})
    return _finish(s, workspace, user)


def _requirement_values(s, workspace, data, user, old=None):
    values = _values(data)
    _badge(s, data.owner_badge)
    if len(set(data.required_evidence_types)) != len(data.required_evidence_types) or any(k not in EVIDENCE_KINDS for k in data.required_evidence_types):
        _error('Select distinct supported evidence types', 422)
    if len(set(data.document_ids)) != len(data.document_ids):
        _error('Link each document revision only once', 422)
    for identifier in data.document_ids:
        _one(s, QualityDocument, identifier, workspace.id)
    if data.applicability in ('conditional', 'not_applicable') and not data.applicability_reason:
        # Seeded draft conditional rows intentionally have no rationale yet;
        # editing them requires an explicit explanation of the unresolved scope.
        _error('Record the applicability reason or unresolved condition', 422)
    if data.gate != 'none' and not workspace.project_id:
        _error('Production gates require a specific tracking project', 422)
    if data.gate != (old.gate if old else 'none'):
        require_capability(user, 'quality_review')
    duplicate = s.scalar(select(QualityRequirement.id).where(QualityRequirement.workspace_id == workspace.id,
                      QualityRequirement.item_number == data.item_number,
                      QualityRequirement.id != (old.id if old else -1)))
    if duplicate:
        _error('That audit item number already exists in this workspace')
    return values


@router.post('/workspaces/{workspace_id}/requirements', status_code=201)
def create_requirement(workspace_id: int, data: RequirementIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    require_capability(user, 'quality_write')
    workspace = _workspace(s, workspace_id, data.expected_version)
    values = _requirement_values(s, workspace, data, user)
    requirement = QualityRequirement(workspace_id=workspace_id, **values, created_by=user.badge)
    s.add(requirement)
    s.flush()
    _event(s, workspace, user.badge, 'REQUIREMENT_CREATED', 'requirement', requirement.id, {'after': row_dict(requirement)})
    return _finish(s, workspace, user)


@router.put('/workspaces/{workspace_id}/requirements/{requirement_id}')
def update_requirement(workspace_id: int, requirement_id: int, data: RequirementIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    require_capability(user, 'quality_write')
    workspace = _workspace(s, workspace_id, data.expected_version)
    requirement = _one(s, QualityRequirement, requirement_id, workspace_id)
    values = _requirement_values(s, workspace, data, user, requirement)
    before = row_dict(requirement)
    for key, value in values.items():
        setattr(requirement, key, value)
    requirement.version += 1
    requirement.updated_at = utcnow()
    _event(s, workspace, user.badge, 'REQUIREMENT_UPDATED', 'requirement', requirement.id, {'before': before, 'after': row_dict(requirement)})
    return _finish(s, workspace, user)


@router.post('/workspaces/{workspace_id}/documents', status_code=201)
def create_document(workspace_id: int, data: DocumentIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    require_capability(user, 'quality_write')
    workspace = _workspace(s, workspace_id, data.expected_version)
    _badges(s, data.required_badges, data.requires_training)
    if data.required_badges and not data.requires_training:
        _error('Enable required training when employee training requirements are listed', 422)
    values = _values(data)
    values['code'] = data.code.upper()
    if s.scalar(select(QualityDocument.id).where(QualityDocument.workspace_id == workspace_id,
                  QualityDocument.code == values['code'], QualityDocument.revision == data.revision)):
        _error('This document code and revision already exists; create a distinct new revision')
    document = QualityDocument(workspace_id=workspace_id, **values, created_by=user.badge)
    s.add(document)
    s.flush()
    _event(s, workspace, user.badge, 'DOCUMENT_REGISTERED', 'document', document.id, {'document': row_dict(document)})
    return _finish(s, workspace, user)


def _evidence_payload(s, workspace, data):
    if data.type not in EVIDENCE_KINDS:
        _error('Unsupported evidence type', 422)
    if data.occurred_on > utcnow().date():
        _error('The actual activity date cannot be in the future; record planned dates in an audit schedule', 422)
    _one(s, QualityRequirement, data.requirement_id, workspace.id)
    if data.document_id:
        _one(s, QualityDocument, data.document_id, workspace.id)
    related = _one(s, QualityEvidence, data.related_evidence_id, workspace.id) if data.related_evidence_id else None
    _badges(s, data.participants)
    spec = EVIDENCE_KINDS[data.type]
    allowed = {field['name'] for field in spec['fields']}
    if set(data.data) - allowed:
        _error('Unsupported detail fields for this evidence type: ' + ', '.join(sorted(set(data.data) - allowed)), 422)
    payload = dict(data.data)
    if len(json.dumps(payload, ensure_ascii=False)) > 50000:
        _error('Evidence details exceed the 50,000-character limit', 422)
    for field in spec['fields']:
        name, value = field['name'], payload.get(field['name'])
        if name == 'required_participants':
            if isinstance(value, str):
                value = [part.strip() for part in value.replace(',', '\n').splitlines() if part.strip()]
                payload[name] = value
            if value is None:
                payload[name] = []
            _badges(s, payload[name], bool(payload.get('training_required')))
            continue
        if field['type'] == 'checkbox':
            if type(value) is not bool:
                _error('Record an explicit yes/no value for ' + field['label'], 422)
        elif field['required'] and (not isinstance(value, str) or len(value.strip()) < 2):
            _error('Record ' + field['label'], 422)
        elif value is not None:
            if not isinstance(value, str) or len(value) > 10000:
                _error('Invalid or excessively long detail: ' + field['label'], 422)
            payload[name] = value.strip()
            if field.get('options') and value not in field['options']:
                _error('Select a supported value for ' + field['label'], 422)
            if field['type'] == 'date':
                try:
                    parsed = dt.date.fromisoformat(value)
                except (ValueError, TypeError):
                    _error('Use an ISO calendar date for ' + field['label'], 422)
                payload[name] = parsed.isoformat()
                if data.type == 'audit_schedule' and parsed < data.occurred_on:
                    _error('The planned audit cannot precede the schedule issue/approval date', 422)
    if data.type == 'training':
        _badges(s, data.participants, True)
        _badge(s, data.performed_by, True)
        if not data.document_id and not related:
            _error('Training must reference an exact document revision or issued Quality Alert', 422)
        if related and related.type != 'quality_alert':
            _error('Training related evidence must be an issued Quality Alert', 422)
        if related and data.occurred_on.isoformat() < related.occurred_on:
            _error('Training cannot predate the related Quality Alert', 422)
    elif related and data.related_evidence_id == getattr(data, 'id', None):
        _error('Evidence cannot reference itself', 422)
    return payload


def _lock_physical_records(s, workspace_id):
    """Tracking writes also use Item locks; serialize a signed physical basis.

    Call only during writes/gate checks after the shared topology lock. Read
    projections and Excel snapshots deliberately do not take row locks.
    """
    identifiers = list(s.scalars(select(QualityEvidence.item_id).where(
        QualityEvidence.workspace_id == workspace_id, QualityEvidence.item_id.is_not(None)).distinct()))
    if identifiers:
        list(s.scalars(select(Item).where(Item.id.in_(identifiers)).order_by(Item.id)
             .with_for_update().execution_options(populate_existing=True)))


@router.post('/workspaces/{workspace_id}/evidence', status_code=201)
def create_evidence(workspace_id: int, data: EvidenceIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    require_capability(user, 'quality_write')
    workspace = _workspace(s, workspace_id, data.expected_version)
    payload = _evidence_payload(s, workspace, data)
    values = _values(data)
    values['data'] = payload
    weld = s.get(Weld, data.weld_id) if data.weld_id else None
    if data.weld_id and not weld:
        _error('Individual weld record not found', 422)
    if weld:
        if data.item_id and weld.item_id != data.item_id:
            _error('The weld does not belong to the selected item', 422)
        values['item_id'] = weld.item_id
    if values['item_id']:
        item = s.scalar(select(Item).where(Item.id == values['item_id']).with_for_update().execution_options(populate_existing=True))
        if not item:
            _error('Physical item not found', 422)
        from removals import require_active_item
        require_active_item(s, item.id)
    values['production_snapshot'] = _physical(s, values['item_id'], data.weld_id)
    # A component inherits project scope only through its authoritative physical
    # spool assignment. Free-text Item.project never grants project membership.
    if values['item_id'] and workspace.project_id and values['production_snapshot']['project_id'] != workspace.project_id:
        _error('The physical item is not tracked or assigned to a spool in this workspace project', 422)
    evidence = QualityEvidence(workspace_id=workspace_id, **values, created_by=user.badge)
    s.add(evidence)
    s.flush()
    _event(s, workspace, user.badge, 'EVIDENCE_RECORDED', 'evidence', evidence.id, {'evidence': row_dict(evidence)})
    return _finish(s, workspace, user)


def _action_values(s, workspace, data, old=None):
    _one(s, QualityRequirement, data.requirement_id, workspace.id)
    _badge(s, data.owner_badge, True)
    if old and old.requirement_id != data.requirement_id:
        _error('An existing action cannot be moved to another requirement')
    if len(set(data.closure_evidence_ids)) != len(data.closure_evidence_ids):
        _error('Link each closure record only once', 422)
    ids = data.closure_evidence_ids + [identifier for identifier in
            (data.effectiveness_evidence_id, data.customer_approval_evidence_id) if identifier]
    for identifier in ids:
        evidence = _one(s, QualityEvidence, identifier, workspace.id)
        if evidence.requirement_id != data.requirement_id:
            _error('Corrective-action evidence must belong to this requirement', 422)
    if old and old.status == 'closed':
        _error('A reviewer must reopen this corrective action before it can be edited')
    return _values(data)


@router.post('/workspaces/{workspace_id}/actions', status_code=201)
def create_action(workspace_id: int, data: ActionIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    require_capability(user, 'quality_write')
    workspace = _workspace(s, workspace_id, data.expected_version)
    values = _action_values(s, workspace, data)
    action = QualityAction(workspace_id=workspace_id, **values, created_by=user.badge)
    s.add(action)
    s.flush()
    _event(s, workspace, user.badge, 'ACTION_CREATED', 'action', action.id, {'after': row_dict(action)})
    return _finish(s, workspace, user)


@router.put('/workspaces/{workspace_id}/actions/{action_id}')
def update_action(workspace_id: int, action_id: int, data: ActionIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    require_capability(user, 'quality_write')
    workspace = _workspace(s, workspace_id, data.expected_version)
    action = _one(s, QualityAction, action_id, workspace_id)
    values = _action_values(s, workspace, data, action)
    before = row_dict(action)
    for key, value in values.items():
        setattr(action, key, value)
    action.version += 1
    action.updated_at = utcnow()
    _event(s, workspace, user.badge, 'ACTION_UPDATED', 'action', action.id, {'before': before, 'after': row_dict(action)})
    return _finish(s, workspace, user)


DECISIONS = {'source': {'confirmed', 'unconfirmed'},
             'requirement': {'verified', 'not_applicable', 'needs_work'},
             'document': {'approved', 'superseded'},
             'evidence': {'accepted', 'rejected'},
             'action': {'closed', 'reopened'}}


def _review_basis(s, workspace, data, user):
    if data.decision not in DECISIONS[data.target_type]:
        _error('Unsupported decision for this review type', 422)
    _lock_physical_records(s, workspace.id)
    ctx = _context(s, workspace)
    if data.target_type in ('source', 'requirement'):
        requirement = _one(s, QualityRequirement, data.target_id, workspace.id)
        if data.target_type == 'source':
            basis = _source_basis(requirement, workspace)
            if data.decision == 'confirmed':
                if any(not basis[key].strip() for key in ('source_document', 'source_revision', 'source_section', 'source_reference')):
                    _error('Source confirmation requires the actual document, revision, section/clause and retrievable reference')
                if requirement.applicability == 'conditional':
                    _error('Resolve conditional applicability before confirming the source')
            return basis
        basis = _requirement_basis(ctx, requirement)
        view = _requirement_view(ctx, requirement)
        # A stale-verification notice is informational: a fresh review can
        # replace it after the underlying requirements are actually satisfied.
        blockers = [message for message in view['blockers'] if not message.startswith('Previous verification is stale')]
        if data.decision == 'verified':
            if requirement.applicability != 'applicable':
                _error('Only an explicitly applicable requirement can be verified')
            if blockers:
                _error('Cannot verify: ' + ' '.join(blockers))
        elif data.decision == 'not_applicable':
            if requirement.applicability != 'not_applicable' or len(requirement.applicability_reason.strip()) < 4:
                _error('Record a meaningful not-applicable rationale before review')
            if blockers:
                _error('Cannot approve not applicable: ' + ' '.join(blockers))
        return basis
    if data.target_type == 'document':
        document = _one(s, QualityDocument, data.target_id, workspace.id)
        if data.decision == 'approved' and not document.effective_date:
            _error('An effective date is required before document approval')
        return row_dict(document)
    if data.target_type == 'evidence':
        evidence = _one(s, QualityEvidence, data.target_id, workspace.id)
        if evidence.item_id:
            from removals import require_active_item
            require_active_item(s, evidence.item_id)
        basis = _evidence_basis(ctx, evidence)
        if data.decision == 'accepted':
            if evidence.production_snapshot != basis['current_production']:
                _error('The linked production record changed after this evidence was recorded. Submit a current record and review it.')
            if evidence.type in ('inspection', 'effectiveness') and evidence.data.get('result') != 'pass':
                _error('A failed or unassessed inspection/effectiveness result cannot be accepted as satisfactory evidence')
            if evidence.document_id and (not basis['document'] or basis['document']['status'] != 'approved' or not basis['document']['effective']):
                _error('Evidence linked to a document requires its current effective approved revision before acceptance')
            if evidence.type == 'training' and evidence.related_evidence_id:
                if not _accepted(ctx, evidence.related_evidence_id, kind='quality_alert'):
                    _error('Accept the actual issued Quality Alert before accepting its training record')
            # Employee deactivation after recording does not erase historical
            # training. The named identities were validated on submission.
        return basis
    action = _one(s, QualityAction, data.target_id, workspace.id)
    if data.decision == 'closed':
        if action.status == 'closed':
            _error('Corrective action is already closed; reopen before changing the closure')
        errors = _action_closure_errors(ctx, action)
        if errors:
            _error('Cannot close corrective action: ' + ' '.join(errors))
        action.status = 'closed'
        action.closed_by = user.badge
        action.closed_at = utcnow()
    else:
        if action.status != 'closed':
            _error('Only a closed corrective action can be reopened')
        action.status = 'open'
        action.closed_by = None
        action.closed_at = None
    action.version += 1
    action.updated_at = utcnow()
    evidence_ids = set(action.closure_evidence_ids + [x for x in (action.effectiveness_evidence_id, action.customer_approval_evidence_id) if x])
    return {'action': row_dict(action), 'evidence': [_evidence_view(ctx, ctx['evidence_by_id'][identifier]) for identifier in sorted(evidence_ids)]}


@router.post('/workspaces/{workspace_id}/reviews', status_code=201)
def create_review(workspace_id: int, data: ReviewIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    require_capability(user, 'quality_review')
    workspace = _workspace(s, workspace_id, data.expected_version)
    basis = _review_basis(s, workspace, data, user)
    review = QualityReview(workspace_id=workspace_id, target_type=data.target_type, target_id=data.target_id,
                           decision=data.decision, reference=data.reference, notes=data.notes,
                           fingerprint=_digest(basis), snapshot=basis, actor=user.badge)
    s.add(review)
    s.flush()
    _event(s, workspace, user.badge, 'REVIEW_RECORDED', data.target_type, data.target_id, {'review': row_dict(review)})
    return _finish(s, workspace, user)


def production_gate_errors(s, item, gate, as_of=None, *, for_update=False):
    """Opt-in project gates; caller already owns the flow topology/item locks.

    No project enrollment or no configured gate means legacy behavior remains
    unchanged. The shared topology lock serializes changes against gate checks.
    A gate is satisfied only by current signed verification or approved NA.
    """
    if gate not in ('pre_coating', 'shipment'):
        raise ValueError('Unknown quality production gate')
    plan = s.get(SpoolPlan, item.id)
    if not plan:
        return []
    workspace_ids = select(QualityRequirement.workspace_id).where(QualityRequirement.gate == gate)
    query = select(QualityWorkspace).where(QualityWorkspace.project_id == plan.project_id,
            QualityWorkspace.id.in_(workspace_ids)).order_by(QualityWorkspace.id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    workspaces = list(s.scalars(query))
    errors = []
    for workspace in workspaces:
        if for_update:
            _lock_physical_records(s, workspace.id)
        ctx = _context(s, workspace, as_of=as_of)
        for requirement in ctx['requirements']:
            if requirement.gate != gate:
                continue
            view = _requirement_view(ctx, requirement)
            if view['status'] not in ('verified', 'not_applicable'):
                explanation = '; '.join(view['blockers'][:3]) or 'Signed requirement verification is required.'
                errors.append(f'{workspace.name} · {requirement.item_number}: {requirement.title} — {explanation}')
    return errors
