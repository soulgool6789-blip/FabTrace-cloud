"""Versioned Kelvion Job Packets, attachments, QA release and recorded handover.

Project enrollment is explicit. Read projections never create business records.
Every mutation is serialized with the existing topology lock, project version and
physical item locks. Immutable issue snapshots retain their exact document IDs.
"""
import datetime as dt
import hashlib
import html
import io
import json
import re
import tempfile
import zipfile
from collections import defaultdict
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, JSON,
                        LargeBinary, String, Text, UniqueConstraint, func, select)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, deferred
from starlette.background import BackgroundTask

from main import Base, Employee, Item, Inspection, Rework, audit, auth, db, utcnow
from permissions import has_capability, require_capability, user_permissions
from tracking import (Project, SpoolPlan, Weld, WeldRequirement, RequirementEvidence,
                      RequirementReview, WeldWork, WeldRepair, TrackingHold,
                      tracking_release_errors, spool_dict)
from flow import FlowPlan, FlowEvent, FlowException, ComponentLink, lock_topology
from quality import QualityWorkspace, QualityEvidence, QualityAction, workspace_detail
from dossier_templates import VERSION, SOURCE_NOTE, SECTIONS, CHECKS, CHECK_BY_CODE, SOURCE_REFERENCES

router = APIRouter(prefix='/api/dossier', tags=['dossier'])
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PROJECT_FILE_BYTES = 256 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 12 * 1024 * 1024
MEDIA = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg',
         '.jpeg': 'image/jpeg', '.txt': 'text/plain', '.csv': 'text/csv',
         '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
         '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


class DossierProject(Base):
    __tablename__ = 'dossier_projects'
    project_id = Column(String(80), ForeignKey('tracking_projects.id'), primary_key=True)
    manufacturer_name = Column(String(240), nullable=False)
    manufacturer_contact = Column(Text, nullable=False)
    purchase_order = Column(String(200), nullable=False)
    work_order = Column(String(200), nullable=False, default='')
    advisements = Column(Text, nullable=False, default='')
    source_reference = Column(String(1000), nullable=False)
    expected_packets = Column(Integer, nullable=False)
    shipping_gate = Column(Boolean, nullable=False, default=True)
    customer_approval_required = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=False, default='')
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DossierEntry(Base):
    __tablename__ = 'dossier_entries'
    __table_args__ = (UniqueConstraint('item_id', 'code', name='uq_dossier_item_check'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(80), ForeignKey('dossier_projects.project_id'), nullable=False, index=True)
    item_id = Column(String(60), ForeignKey('items.id'), nullable=False, index=True)
    code = Column(String(80), nullable=False)
    applicability = Column(String(30), nullable=False, default='required')
    reference = Column(String(1000), nullable=False, default='')
    notes = Column(Text, nullable=False, default='')
    document_ids = Column(JSON, nullable=False, default=list)
    values = Column(JSON, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)
    updated_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DossierDocument(Base):
    __tablename__ = 'dossier_documents'
    __table_args__ = (UniqueConstraint('project_id', 'scope_key', 'code', 'revision', name='uq_dossier_document_revision'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(80), ForeignKey('dossier_projects.project_id'), nullable=False, index=True)
    item_id = Column(String(60), ForeignKey('items.id'), index=True)
    scope_key = Column(String(60), nullable=False, default='')
    code = Column(String(100), nullable=False)
    title = Column(String(240), nullable=False)
    revision = Column(String(80), nullable=False)
    section = Column(String(2), nullable=False)
    reference = Column(String(1000), nullable=False, default='')
    filename = Column(String(180), nullable=False)
    media_type = Column(String(160), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DossierFile(Base):
    __tablename__ = 'dossier_files'
    document_id = Column(Integer, ForeignKey('dossier_documents.id'), primary_key=True)
    content = deferred(Column(LargeBinary, nullable=False))


class DossierReview(Base):
    __tablename__ = 'dossier_reviews'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(80), ForeignKey('dossier_projects.project_id'), nullable=False, index=True)
    item_id = Column(String(60), ForeignKey('items.id'), index=True)
    code = Column(String(80), nullable=False)
    decision = Column(String(30), nullable=False)
    reference = Column(String(1000), nullable=False)
    notes = Column(Text, nullable=False)
    fingerprint = Column(String(64), nullable=False)
    snapshot = Column(JSON, nullable=False)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DossierIssue(Base):
    __tablename__ = 'dossier_issues'
    __table_args__ = (UniqueConstraint('project_id', 'scope_key', 'revision', name='uq_dossier_issue_revision'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(80), ForeignKey('dossier_projects.project_id'), nullable=False, index=True)
    item_id = Column(String(60), ForeignKey('items.id'), index=True)
    scope_key = Column(String(60), nullable=False, default='')
    kind = Column(String(20), nullable=False)
    revision = Column(Integer, nullable=False)
    fingerprint = Column(String(64), nullable=False)
    sha256 = Column(String(64), nullable=False)
    snapshot = deferred(Column(JSON, nullable=False))
    print_html = deferred(Column(Text, nullable=False))
    print_sha256 = Column(String(64), nullable=False)
    reference = Column(String(1000), nullable=False)
    notes = Column(Text, nullable=False)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DossierHandover(Base):
    __tablename__ = 'dossier_handovers'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(80), ForeignKey('dossier_projects.project_id'), nullable=False, index=True)
    issue_id = Column(Integer, ForeignKey('dossier_issues.id'), nullable=False, index=True)
    channel = Column(String(20), nullable=False)
    event = Column(String(20), nullable=False)
    dispatch_id = Column(Integer, ForeignKey('dossier_handovers.id'), unique=True)
    recipient = Column(String(240), nullable=False)
    organization = Column(String(240), nullable=False)
    reference = Column(String(1000), nullable=False)
    notes = Column(Text, nullable=False, default='')
    occurred_on = Column(String(10), nullable=False)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DossierEvent(Base):
    __tablename__ = 'dossier_events'
    __table_args__ = (UniqueConstraint('project_id', 'sequence', name='uq_dossier_project_sequence'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(80), ForeignKey('dossier_projects.project_id'), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event = Column(String(80), nullable=False)
    item_id = Column(String(60), ForeignKey('items.id'))
    details = Column(JSON, nullable=False)
    actor = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Versioned(Input):
    expected_version: int = Field(ge=0, strict=True)

class ConfigIn(Versioned):
    manufacturer_name: str = Field(min_length=2, max_length=240)
    manufacturer_contact: str = Field(min_length=4, max_length=5000)
    purchase_order: str = Field(min_length=2, max_length=200)
    work_order: str = Field(default='', max_length=200)
    advisements: str = Field(default='', max_length=10000)
    source_reference: str = Field(min_length=3, max_length=1000)
    expected_packets: int = Field(ge=1, le=100000, strict=True)
    shipping_gate: bool = Field(default=True, strict=True)
    customer_approval_required: bool = Field(default=False, strict=True)
    notes: str = Field(default='', max_length=10000)

class EntryIn(Versioned):
    applicability: Literal['required', 'not_applicable'] = 'required'
    reference: str = Field(default='', max_length=1000)
    notes: str = Field(default='', max_length=10000)
    document_ids: list[Annotated[int, Field(ge=1, strict=True)]] = Field(default_factory=list, max_length=200)
    values: dict = Field(default_factory=dict)

    @field_validator('values')
    @classmethod
    def bounded_values(cls, value):
        if len(value) > 30 or any(not isinstance(k, str) or not isinstance(v, str) or len(k)>80 or len(v)>5000 for k,v in value.items()):
            raise ValueError('Record at most 30 named text fields, each at most 5,000 characters')
        return {k:v.strip() for k,v in value.items()}

class SignedIn(Versioned):
    reference: str = Field(min_length=3, max_length=1000)
    notes: str = Field(min_length=4, max_length=10000)

class ReviewIn(SignedIn):
    decision: Literal['accepted', 'not_applicable', 'rejected']

class HandoverIn(SignedIn):
    issue_id: int = Field(ge=1, strict=True)
    channel: Literal['digital', 'physical']
    recipient: str = Field(min_length=2, max_length=240)
    organization: str = Field(min_length=2, max_length=240)
    occurred_on: str = Field(min_length=10, max_length=10)

class ReceiptIn(SignedIn):
    recipient: str = Field(min_length=2, max_length=240)
    occurred_on: str = Field(min_length=10, max_length=10)


def _fmt(value):
    if isinstance(value, dt.datetime):
        return (value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)).isoformat()
    return value

def row_dict(row, exclude=()):
    return {c.name: _fmt(getattr(row, c.name)) for c in row.__table__.columns if c.name not in exclude and c.name!='print_html'}

def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()

def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()

def _error(message, status=409):
    raise HTTPException(status, message)

def _project(s, project_id):
    obj = s.get(Project, project_id)
    if not obj:
        _error('Project not found', 404)
    return obj

def _config(s, project_id):
    obj = s.get(DossierProject, project_id)
    if not obj:
        _error('Configure Job Packets for this project first')
    return obj

def _locked(s, project_id, expected):
    lock_topology(s)
    _project(s, project_id)
    from removals import require_active_project
    require_active_project(s, project_id)
    cfg = s.scalar(select(DossierProject).where(DossierProject.project_id == project_id).with_for_update().execution_options(populate_existing=True))
    version = cfg.version if cfg else 0
    if version != expected:
        _error({'message': 'Job Packet project changed; refresh and review the latest records.', 'current_version': version})
    return cfg

def _item(s, item_id):
    item, plan = s.get(Item, item_id), s.get(SpoolPlan, item_id)
    if not item:
        _error('Item not found', 404)
    if not plan:
        _error('Set up the spool or assembly project/weld plan first')
    return item, plan

def _lock_items(s, project_id):
    ids = list(s.scalars(select(SpoolPlan.item_id).where(SpoolPlan.project_id == project_id)))
    ids += list(s.scalars(select(Item.id).where(Item.project == project_id)))
    if ids:
        ids += list(s.scalars(select(ComponentLink.component_id).where(ComponentLink.spool_id.in_(ids))))
        list(s.scalars(select(Item).where(Item.id.in_(sorted(set(ids)))).order_by(Item.id).with_for_update().execution_options(populate_existing=True)))

def _bump(s, cfg, user, event, details, item_id=None, first=False):
    if not first:
        cfg.version += 1
    cfg.updated_at = utcnow()
    s.add(DossierEvent(project_id=cfg.project_id, sequence=cfg.version, event=event,
        item_id=item_id, details=details, actor=user.badge))
    audit(s, item_id, user.badge, 'DOSSIER_'+event.upper(), {'project_id': cfg.project_id, **details})

def _commit(s):
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        _error('Conflicting Job Packet update or duplicate revision; refresh before retrying')

def _permissions(user):
    scope = user_permissions(user)
    return {'manage': has_capability(user, 'dossier_manage'),
            'write': bool(scope['dossier_check_codes'] or scope['dossier_upload_sections']),
            'review': has_capability(user, 'dossier_review'),
            'editable_check_codes': scope['dossier_check_codes'],
            'upload_sections': scope['dossier_upload_sections'],
            'can_handover': has_capability(user, 'dossier_handover')}

def _source_basis(cfg):
    return {key: getattr(cfg, key) for key in ('project_id','manufacturer_name','manufacturer_contact',
        'purchase_order','work_order','source_reference','shipping_gate','customer_approval_required')} | {'template_version': VERSION}

def _latest_review(s, project_id, item_id, code):
    return s.scalar(select(DossierReview).where(DossierReview.project_id == project_id,
        DossierReview.item_id == item_id, DossierReview.code == code).order_by(DossierReview.id.desc()))

def _source_view(s, cfg):
    review = _latest_review(s, cfg.project_id, None, 'source')
    current = bool(review and review.decision == 'accepted' and review.fingerprint == _digest(_source_basis(cfg)))
    return {'status': 'confirmed' if current else 'needs_confirmation', 'review': row_dict(review, ('snapshot',)) if review else None}

def _documents(s, project_id):
    rows = list(s.scalars(select(DossierDocument).where(DossierDocument.project_id == project_id).order_by(DossierDocument.id)))
    latest = {(r.scope_key, r.code): r.id for r in rows}
    return [{**row_dict(r), 'current': latest[(r.scope_key, r.code)] == r.id} for r in rows]


def _material_trace_scope(s, item, seen=None):
    """Saved material facts for this spool or its active physical descendants.

    Merely having an approved reference BOM adds no packet basis. A physical
    trace record must have been saved; reads never create it. Registered child
    spools without a weld plan can still retain supplier material facts.
    """
    from spool_boms import spool_bom_scope_basis
    return spool_bom_scope_basis(s, item.id, seen) if item else []


def _material_trace_rows(bases):
    return [{'spool_id': basis['spool_id'], 'spool_number': basis['spool_number'], **piece}
            for basis in bases for piece in basis['materials']]


def _spool_document_scope(s, item):
    """Exact uploaded references; no upload is treated as a QA approval."""
    from spool_documents import spool_document_scope_basis
    return spool_document_scope_basis(s, item.id) if item else []


def _arrival_scope(s, item):
    from spool_receiving import receiving_scope_basis
    return receiving_scope_basis(s, item.id) if item else []


def _mtr_document_scope(s, item):
    from spool_receiving import spool_mtr_scope_metadata
    return [{key: value for key, value in row.items() if key not in ('view_url', 'download_url')}
            for row in spool_mtr_scope_metadata(s, item.id)] if item else []


def _physical_structure(s,item,plan,seen=None):
    """Relevant child construction proof, without releases, logistics or coating."""
    seen=set(seen or ())
    if item.id in seen:
        return {'item_id':item.id,'error':'Circular physical hierarchy'}
    seen.add(item.id)
    links=list(s.scalars(select(ComponentLink).where(ComponentLink.spool_id==item.id).order_by(ComponentLink.component_id)))
    ids=[item.id]+[r.component_id for r in links]
    children=[]
    for child_plan in s.scalars(select(SpoolPlan).where(SpoolPlan.assembly_id==item.id).order_by(SpoolPlan.item_id)):
        child=s.get(Item,child_plan.item_id)
        children.append({'item_id':child_plan.item_id,'physical_basis':_physical_structure(s,child,child_plan,seen)})
    from parts import parts_basis
    parts = parts_basis(s, item.id)
    material_trace = _material_trace_scope(s, item)
    spool_documents = _spool_document_scope(s, item)
    arrival = _arrival_scope(s, item)
    mtrs = _mtr_document_scope(s, item)
    return _structural({'tracking':spool_dict(s,item),'component_links':[row_dict(x) for x in links],
        **({'parts': {'basis': parts}} if parts else {}),
        **({'material_trace': material_trace} if material_trace else {}),
        **({'spool_documents': spool_documents} if spool_documents else {}),
        **({'arrival_qa': arrival} if arrival else {}),
        **({'mtr_documents': mtrs} if mtrs else {}),
        'child_spools':children,'reworks':[row_dict(x) for x in s.scalars(select(Rework).where(Rework.item_id.in_(ids)).order_by(Rework.id))],
        'flow_events':[row_dict(x) for x in s.scalars(select(FlowEvent).where(FlowEvent.item_id.in_(ids)).order_by(FlowEvent.id))]})

def _actual_records(s, item, plan, user):
    from administration import release_summary
    tracking = spool_dict(s, item)
    # Operational handoffs and timers are included as records but kept out of
    # review fingerprints so routine logistics does not invalidate QA proof.
    tracking.pop('history', None)
    ids = [item.id]
    components = list(s.scalars(select(ComponentLink).where(ComponentLink.spool_id == item.id).order_by(ComponentLink.component_id)))
    ids += [x.component_id for x in components]
    child_plans = list(s.scalars(select(SpoolPlan).where(SpoolPlan.assembly_id == item.id).order_by(SpoolPlan.item_id)))
    children = [row_dict(p) for p in child_plans]
    for cp in child_plans:
        child = s.get(Item, cp.item_id)
        children[child_plans.index(cp)].update(released=bool(child and child.released), description=child.description if child else '',
            release_mode=release_summary(s,child)['mode'] if child else 'not_released',
            physical_basis=_physical_structure(s,child,cp,{item.id}) if child else {'error':'Missing child item'})
    inspections = [row_dict(x) for x in s.scalars(select(Inspection).where(Inspection.item_id.in_(ids)).order_by(Inspection.id))]
    reworks = [row_dict(x) for x in s.scalars(select(Rework).where(Rework.item_id.in_(ids)).order_by(Rework.id))]
    flow_events = [row_dict(x) for x in s.scalars(select(FlowEvent).where(FlowEvent.item_id.in_(ids)).order_by(FlowEvent.id))]
    exceptions = [row_dict(x) for x in s.scalars(select(FlowException).where(FlowException.item_id.in_(ids)).order_by(FlowException.id))]
    fp = s.get(FlowPlan, item.id)
    quality = []
    for ws in s.scalars(select(QualityWorkspace).where(QualityWorkspace.project_id == plan.project_id).order_by(QualityWorkspace.id)):
        detail = workspace_detail(s, ws, user)
        linked = [e for e in detail['evidence'] if e['item_id'] in ids or e['weld_id'] in {w['id'] for w in tracking['welds']}]
        requirement_ids = {e['requirement_id'] for e in linked}
        if not linked:
            continue
        quality.append({'workspace': {k:detail['workspace'][k] for k in ('id','project_id','name','customer','purchase_order')}, 'evidence': linked,
            'requirements': [r for r in detail['requirements'] if r['id'] in requirement_ids],
            'actions': [a for a in detail['actions'] if a['requirement_id'] in requirement_ids]})
    from parts import parts_basis, parts_snapshot
    parts = parts_basis(s, item.id)
    snapshot = parts_snapshot(s, item.id) if parts else None
    part_records = None
    if snapshot:
        part_records = {'basis': parts, 'totals': snapshot['totals'], 'blockers': snapshot['blockers'],
            'lines': [{**{key:value for key,value in line.items() if key != 'components'},
                       'components': [{key:value for key,value in component.items() if key != 'can_remove'}
                                      for component in line['components']]} for line in snapshot['lines']]}
    material_trace = _material_trace_scope(s, item)
    spool_documents = _spool_document_scope(s, item)
    arrival = _arrival_scope(s, item)
    mtrs = _mtr_document_scope(s, item)
    return {'tracking': tracking, 'inspections': inspections, 'reworks': reworks,
        **({'parts': part_records} if part_records else {}),
        **({'spool_documents': spool_documents} if spool_documents else {}),
        **({'arrival_qa': arrival} if arrival else {}),
        **({'mtr_documents': mtrs} if mtrs else {}),
        **({'material_trace': material_trace,
            'material_trace_records': _material_trace_rows(material_trace)} if material_trace else {}),
        'component_links': [row_dict(x) for x in components], 'child_spools': children,
        'flow': row_dict(fp) if fp else None, 'flow_events': flow_events,
        'flow_exceptions': exceptions, 'quality_records': quality}

def _fabrication_event(event):
    data = event.get('data') or {}
    if data.get('testing_protocol') == 'CLM-TEST-v1' and event['action'] == 'advance':
        # The phased protocol records QA acceptance twice at numeric Step18.
        # Successful reviews and custody/report actions do not fabricate the
        # item and must not stale the very test proof that they approved.
        # Recorded corrective work does change the physical evidence basis.
        return data.get('testing_action') == 'correct'
    # Preserve the established legacy basis exactly. A QA failure still
    # invalidates prior proof, including for the new testing protocol.
    return ((event['action'] == 'advance' and event['step'] in (1, 7, 18)) or
            (event['action'] in ('fail', 'reopen') and
             (data.get('return_step', event['step']) or 0) <= 19))


def _structural(records):
    tr = records['tracking']
    welds = []
    for w in tr['welds']:
        welds.append({k: w[k] for k in ('id','number','version','cycle','component_a','heat_a','mtr_a',
            'component_b','heat_b','mtr_b','wps','wps_revision','required_operations','completed_at','work','repairs')})
    physical_events = [e for e in records['flow_events'] if _fabrication_event(e)]
    return {'item_id':tr['item']['id'], 'drawing':tr['item']['drawing'],
        **({'parts': records['parts']['basis']} if records.get('parts') else {}),
        **({'material_trace': records['material_trace']} if records.get('material_trace') else {}),
        **({'spool_documents': records['spool_documents']} if records.get('spool_documents') else {}),
        **({'arrival_qa': records['arrival_qa']} if records.get('arrival_qa') else {}),
        **({'mtr_documents': records['mtr_documents']} if records.get('mtr_documents') else {}),
        'plan':{k:tr['plan'][k] for k in ('project_id','subproject_id','assembly_id','planned_welds','drawing_revision','zero_weld_reason')},
        'welds':welds, 'components':records['component_links'],
        'children':[{'item_id':x['item_id'],'physical_basis':x.get('physical_basis')} for x in records['child_spools']],
        'reworks':records['reworks'], 'physical_events':physical_events}

def _requirements(records):
    tr = records['tracking']
    return tr['requirements'] + [r for w in tr['welds'] for r in w['requirements']]

def _check_basis(cfg, item, spec, entry, records, documents):
    code = spec['code']
    data = {'code':code, 'applicability':entry.applicability if entry else 'required',
        'reference':entry.reference if entry else '', 'notes':entry.notes if entry else '',
        'document_ids':entry.document_ids if entry else [], 'values':entry.values if entry else {},
        'entry_version':entry.version if entry else 0}
    docs_by_id={d['id']:d for d in documents}
    data['documents']=[docs_by_id.get(i) for i in data['document_ids']]
    # Technical proof follows the PO/source, not unrelated contact edits, gate
    # switches or a later source-review identity. Full packet currentness still
    # binds the complete project configuration and the signed source review.
    data['source'] = {k:getattr(cfg,k) for k in ('project_id','purchase_order','work_order','source_reference')}
    data['source']['template_version']=VERSION
    if code=='contact':
        data['actual']={'name':cfg.manufacturer_name,'contact':cfg.manufacturer_contact}
    elif code=='purchase_order':
        data['actual']={'po':cfg.purchase_order,'work_order':cfg.work_order}
    elif code=='advisements':
        data['actual']=cfg.advisements
    elif code=='contents':
        data['actual']={'item_id':item.id,'sections':SECTIONS,'version':VERSION}
    elif code=='drawings':
        data['actual']={'drawing':item.drawing,'revision':records['tracking']['plan']['drawing_revision']}
        drawings=[d for d in records.get('spool_documents',[]) if d['kind']=='isometric']
        if drawings:data['actual']['spool_documents']=drawings
    elif code in ('pressure','torque','customer_hold','procedures','materials','weld_log','brazing_bonding'):
        data['actual']=_structural(records)
    elif code in ('visual','nde'):
        data['actual']={'structure':_structural(records),'requirements':[r for r in _requirements(records)
            if (r['code']=='VT' if code=='visual' else (r['code']=='NDE_PLAN' or 'NDE' in r['code'].upper()))]}
    elif code=='dimensions':
        data['actual']={'structure':_structural(records),'status':item.dimensional,'at':_fmt(item.dimension_at),
            'latest_work':_fmt(item.last_work_at),'inspections':records['inspections']}
    elif code=='nonconformance':
        data['actual']={'holds':records['tracking']['holds'],'reworks':records['reworks'],
            'repairs':[w['repairs'] for w in records['tracking']['welds']],
            'exceptions':records['flow_exceptions'],'quality':records['quality_records']}
    elif code in ('surface','coating'):
        data['actual']={'structure':_structural(records),'coating_events':[e for e in records['flow_events'] if e['step'] in (20,21,22) and e['action'] in ('advance','fail')],
            'latest_work':_fmt(item.last_work_at)}
    elif code=='release':
        data['actual']={'released':item.released,'at':_fmt(item.released_at),'by':item.released_by,
            'requirements':_requirements(records),'dimensional':item.dimensional,'dimension_at':_fmt(item.dimension_at),
            'holds':records['tracking']['holds'],'reworks':records['reworks']}
        release_control=records['tracking']['item'].get('release_control',{})
        if release_control.get('active_override'):
            # Keep ordinary historical fingerprints byte-for-byte equivalent.
            # Only a real administrative exception adds a new release basis.
            data['actual']['administrative_override']=release_control['override']
    else:
        data['actual']=_structural(records)
    return data

def _entry_errors(cfg, item, spec, entry, basis, records):
    errors=[]
    if not entry:
        return ['Record this checklist item and its evidence or applicability basis']
    allowed_na=spec['allow_na'] and not (spec['code']=='customer_shipping' and cfg.customer_approval_required)
    if spec['code'] in ('weld_log','visual','procedures') and records['tracking']['welds']:
        allowed_na=False
    if spec['code']=='materials' and records.get('material_trace_records'):
        allowed_na=False
    if entry.applicability=='not_applicable':
        if not allowed_na: errors.append('This checklist item cannot be marked not applicable for the current scope')
        if len(entry.reference)<3 or len(entry.notes)<8:errors.append('Document the source/authorization reference and a meaningful non-applicability reason')
        return errors
    if len(entry.reference)<3 or len(entry.notes)<4:
        errors.append('Record an identifiable evidence reference and actual findings/verification notes')
    if spec['kind']=='file' and not entry.document_ids:
        errors.append('Attach and select the actual controlled supporting file(s) for this item')
    for d in basis['documents']:
        if not d:errors.append('A selected supporting document is missing')
        elif not d['current']:errors.append(f"Document {d['code']} revision {d['revision']} is superseded; select the current revision")
    for f in spec['fields']:
        value=entry.values.get(f['name'])
        if f['required'] and (not isinstance(value,str) or not value.strip()):errors.append(f"Record {f['label']}")
        if value and f.get('options') and value not in f['options']:errors.append(f"Invalid {f['label']}")
    if 'result' in entry.values and entry.values['result']!='pass':
        errors.append('The actual examination/test result must pass before acceptance')
    code=spec['code'];tr=records['tracking']
    if code=='drawings' and (not (item.drawing or '').strip() or not tr['plan']['drawing_revision'].strip()):
        errors.append('Record both the actual manufacturing drawing ID and its separate revision in the item/spool plan')
    if code=='materials':
        for piece in records.get('material_trace_records', []):
            label = f"{piece['spool_id']}, BOM item {piece['item']} piece {piece['piece_number']}"
            if not str(piece.get('heat_number') or '').strip():
                errors.append(label + ': material heat number is missing')
            if not str(piece.get('mtr_reference') or '').strip():
                errors.append(label + ': MTR reference is missing')
        for w in tr['welds']:
            if any(not w.get(k) for k in ('component_a','component_b','heat_a','heat_b','mtr_a','mtr_b')):errors.append(f"{w['number']}: both-side material/heat/MTR traceability is incomplete")
    if code in ('weld_log','visual'):
        if len(tr['welds']) != tr['plan']['planned_welds']:errors.append('Define the full planned joint scope first')
        for w in tr['welds']:
            if not w['production_complete']:errors.append(f"{w['number']}: current-cycle work is incomplete")
            if code=='visual' and not any(r['code']=='VT' and r['satisfied'] and r['status']=='accepted' for r in w['requirements']):
                errors.append(f"{w['number']}: current accepted visual examination is required for every weld")
        if not tr['welds'] and not tr['plan']['zero_weld_reason']:errors.append('Explain the zero-weld scope')
    if code=='dimensions':
        if item.dimensional!='Pass' or not item.dimension_at or (item.last_work_at and _fmt(item.dimension_at)<=_fmt(item.last_work_at)):
            errors.append('Record current passing dimensional measurements after the latest work')
    if code=='nonconformance':
        if item.on_hold or any(not h['closed_at'] for h in tr['holds']):errors.append('Resolve open quality holds')
        if any(not r['closed_at'] for r in records['reworks']):errors.append('Resolve open item/component rework')
        if any(not e['closed_at'] for e in records['flow_exceptions']):errors.append('Resolve open process exceptions')
        if any(a['status']!='closed' or a.get('closure_stale') for q in records['quality_records'] for a in q['actions']):errors.append('Resolve linked audit corrective actions and their effectiveness basis')
    if code=='release':
        if not item.released:errors.append('Final QA release has not been recorded')
        elif records['tracking']['item'].get('release_control',{}).get('active_override'):
            errors.append('Administrative release does not establish the final QA release required by this checklist')
    return list(dict.fromkeys(errors))

def _check_view(cfg, item, spec, entry, review, records, documents):
    basis=_check_basis(cfg,item,spec,entry,records,documents)
    blockers=_entry_errors(cfg,item,spec,entry,basis,records)
    status='missing' if entry is None else 'in_progress'
    if review:
        if review.decision=='rejected':status='rejected'
        elif review.fingerprint!=_digest(basis):status='stale'
        elif not blockers:status=review.decision
    if status not in ('accepted','not_applicable') and not blockers:
        blockers=['A current signed QA checklist review is required']
    return {**spec,**{k:basis[k] for k in ('applicability','reference','notes','document_ids','values')},
        'status':status,'blockers':blockers,'latest_review':row_dict(review,('snapshot',)) if review else None,
        'fingerprint':_digest(basis)},basis

def _latest_issue(s, project_id, item_id):
    return s.scalar(select(DossierIssue).where(DossierIssue.project_id==project_id,
        DossierIssue.item_id==item_id).order_by(DossierIssue.revision.desc()))

def _packet(s,item,user,_seen=None,_cache=None):
    _seen=set(_seen or ())
    _cache={} if _cache is None else _cache
    if item.id in _cache:
        return _cache[item.id]
    if item.id in _seen:
        _error('Circular spool/assembly relationship must be corrected before packet review')
    _seen.add(item.id)
    item,plan=_item(s,item.id)
    cfg=_config(s,plan.project_id)
    records=_actual_records(s,item,plan,user)
    documents=_documents(s,cfg.project_id)
    available=[d for d in documents if d['item_id'] in (None,item.id)]
    entries={e.code:e for e in s.scalars(select(DossierEntry).where(DossierEntry.item_id==item.id,DossierEntry.project_id==cfg.project_id))}
    reviews={r.code:r for r in s.scalars(select(DossierReview).where(DossierReview.item_id==item.id,DossierReview.project_id==cfg.project_id).order_by(DossierReview.id))}
    checks=[];basis={}
    for spec in CHECKS:
        view,one=_check_view(cfg,item,spec,entries.get(spec['code']),reviews.get(spec['code']),records,available)
        checks.append(view);basis[spec['code']]=one
    source=_source_view(s,cfg)
    blockers=[]
    if source['status']!='confirmed':blockers.append('Confirm the original customer source and project/PO applicability')
    for row in checks:
        if row['status'] not in ('accepted','not_applicable'):
            blockers.extend(f"{row['title']}: {x}" for x in row['blockers'])
    release_errors=tracking_release_errors(s,item)
    release_control=records['tracking']['item']['release_control']
    if release_control['active_override']:
        release_errors.append('Administrative release requires ordinary QA release before a QA-issued Job Packet')
    if not item.released:blockers.append('Item final QA release is required before packet issuance')
    blockers.extend(release_errors)
    child_basis=[]
    for child in records['child_spools']:
        if not child['released']:blockers.append('Child spool '+child['item_id']+' is not released')
        if child['project_id']!=cfg.project_id:
            blockers.append('Child spool '+child['item_id']+' belongs to a different project')
            continue
        if child['item_id'] in _seen:
            blockers.append('Circular spool/assembly relationship: '+child['item_id'])
            continue
        child_item=s.get(Item,child['item_id'])
        child_packet=_packet(s,child_item,user,_seen,_cache)
        child_issue=_latest_issue(s,cfg.project_id,child_item.id)
        current=bool(child_issue and child_issue.fingerprint==child_packet['fingerprint'] and not child_packet['blockers'])
        if not current:blockers.append('Child spool '+child_item.id+' needs a current QA-issued Job Packet')
        child_basis.append({'item_id':child_item.id,'fingerprint':child_packet['fingerprint'],
            'issue_id':child_issue.id if child_issue else None,'sha256':child_issue.sha256 if child_issue else None,
            'current':current})
    issue_basis={'template':VERSION,'config':_source_basis(cfg),'advisements':cfg.advisements,
        'source_review':source['review']['id'] if source['status']=='confirmed' else None,
        'checks':[{k:c[k] for k in ('code','status','fingerprint')}|{'review_id':(c['latest_review'] or {}).get('id')} for c in checks],
        'release':{'released':item.released,'released_at':_fmt(item.released_at),'released_by':item.released_by},
        'release_errors':release_errors,'structural':_structural(records),'child_packets':child_basis}
    if release_control['active_override']:
        issue_basis['release']['administrative_override']=release_control['override']
    accepted=sum(c['status'] in ('accepted','not_applicable') for c in checks)
    packet={'project':row_dict(_project(s,cfg.project_id)), 'config':row_dict(cfg),'version':cfg.version,
        'item':{**row_dict(item),'release_control':release_control}, 'sections':[{**section,'checks':[c for c in checks if c['section']==section['code']]} for section in SECTIONS],
        'records':records,'documents':available,'blockers':list(dict.fromkeys(blockers)),
        'status':'ready_for_issue' if not blockers else ('stale' if any(c['status']=='stale' for c in checks) else 'in_progress'),
        'percent':round(100*accepted/len(checks),1),'permissions':_permissions(user),
        'source_status':source['status'],'source_review':source['review'],
        'child_packets':child_basis,'fingerprint':_digest(issue_basis),'basis':basis}
    _cache[item.id]=packet
    return packet

def item_detail(s,item,user):
    packet=_packet(s,item,user)
    from removals import item_is_removed, removal_summary
    active=not item_is_removed(s,item.id)
    packet['removal']=removal_summary(s,'item',item.id)
    packet['can_mutate']=active
    if not active:
        packet['permissions']={key:[] if isinstance(value,list) else False for key,value in packet['permissions'].items()}
    rows=list(s.scalars(select(DossierIssue).where(DossierIssue.item_id==item.id).order_by(DossierIssue.revision.desc())))
    packet['issues']=[{**row_dict(r,('snapshot',)),'current':r.fingerprint==packet['fingerprint'] and not packet['blockers']} for r in rows]
    packet['latest_issue']=packet['issues'][0] if packet['issues'] else None
    if packet['latest_issue'] and packet['latest_issue']['current']:packet['status']='issued'
    elif packet['latest_issue']:packet['status']='stale'
    packet.pop('basis',None)
    return packet


def _project_state(s,project_id,user):
    """Physical scope plus latest immutable item issues; no writes or row locks."""
    from progress import project_rows
    cfg=_config(s,project_id)
    rows=project_rows(s,project_id)
    plans=list(s.scalars(select(SpoolPlan).where(SpoolPlan.project_id==project_id).order_by(SpoolPlan.item_id)))
    packets=[];cache={};blockers=[]
    if len(plans)!=cfg.expected_packets:
        blockers.append(f'Declared packet scope is {cfg.expected_packets}; {len(plans)} spool/assembly plans are registered')
    if not plans:blockers.append('Register the actual spool/assembly scope before project issue')
    for row in rows:
        if row['kind']=='unplanned':
            blockers.append(row['id']+': unresolved project part; set up its spool plan or component route')
        elif not row['fabrication_finished']:
            blockers.append(row['id']+': current fabrication/preparation is not finished')
    for plan in plans:
        item=s.get(Item,plan.item_id)
        packet=_packet(s,item,user,_cache=cache)
        issue=_latest_issue(s,project_id,item.id)
        current=bool(issue and issue.fingerprint==packet['fingerprint'] and not packet['blockers'])
        if not current:blockers.append(item.id+': issue a complete current QA-reviewed Job Packet')
        packets.append({'item_id':item.id,'description':item.description,'kind':item.kind,
            'status':'issued' if current else 'stale' if issue else packet['status'],
            'percent':packet['percent'],'blockers':packet['blockers'],
            'latest_issue':{**row_dict(issue,('snapshot',)),'current':current} if issue else None,
            'fingerprint':packet['fingerprint']})
    basis={'template_version':VERSION,'source':_source_basis(cfg),'expected_packets':cfg.expected_packets,
        'scope':[{'item_id':r['id'],'kind':r['kind'],'parent_id':r['parent_id'],
            'fabrication_finished':r['fabrication_finished'],'blockers':r['blockers']} for r in rows],
        'packets':[{'item_id':p['item_id'],'fingerprint':p['fingerprint'],
            'issue_id':p['latest_issue']['id'] if p['latest_issue'] else None,
            'sha256':p['latest_issue']['sha256'] if p['latest_issue'] else None,
            'current':bool(p['latest_issue'] and p['latest_issue']['current'])} for p in packets]}
    return packets,rows,list(dict.fromkeys(blockers)),_digest(basis),basis


def project_detail(s,project_id,user):
    project=_project(s,project_id)
    from removals import item_is_removed, project_is_removed, removal_summary
    active=not project_is_removed(s,project_id)
    cfg=s.get(DossierProject,project_id)
    if cfg:
        items,scope,blockers,fingerprint,_=_project_state(s,project_id,user)
        documents=_documents(s,project_id)
        source=_source_view(s,cfg)
    else:
        items=[{'item_id':p.item_id,'description':s.get(Item,p.item_id).description,
            'kind':s.get(Item,p.item_id).kind,'status':'not_configured','percent':0,
            'blockers':['Configure project Job Packets first'],'latest_issue':None}
            for p in s.scalars(select(SpoolPlan).where(SpoolPlan.project_id==project_id).order_by(SpoolPlan.item_id))]
        scope=[];documents=[];blockers=['Configure project Job Packets first'];fingerprint=None
        source={'status':'needs_confirmation','review':None}
    issues=[{**row_dict(r,('snapshot',)),'current':bool(cfg and r.fingerprint==fingerprint and not blockers)}
        for r in s.scalars(select(DossierIssue).where(DossierIssue.project_id==project_id,
            DossierIssue.kind=='project').order_by(DossierIssue.revision.desc()))]
    handovers=[row_dict(r) for r in s.scalars(select(DossierHandover).where(DossierHandover.project_id==project_id).order_by(DossierHandover.id))]
    latest=issues[0] if issues else None
    transfer_status={}
    for channel in ('digital','physical'):
        dispatches=[h for h in handovers if h['channel']==channel and h['event']=='dispatch'
            and latest and h['issue_id']==latest['id']]
        latest_dispatch=dispatches[-1] if dispatches else None
        receipt=next((h for h in handovers if latest_dispatch and h['dispatch_id']==latest_dispatch['id']),None)
        transfer_status[channel]={'status':'received' if receipt else 'dispatched' if latest_dispatch else 'not_dispatched',
            'dispatch':latest_dispatch,'receipt':receipt}
    permissions=_permissions(user)
    # Removal is an operational restriction, not a change to retained work or
    # the signed evidence basis. Add display blockers only after calculating
    # the original fingerprint and immutable issue's currentness above.
    completion_blockers=list(blockers)
    if not active:
        completion_blockers.append('This P.O. is removed. Restore it before issuing or handing over its Job Packet.')
    else:
        scope_ids={row['id'] for row in scope} | {row['item_id'] for row in items}
        removed_ids=sorted(item_id for item_id in scope_ids if item_is_removed(s,item_id))
        if removed_ids:
            completion_blockers.append('Removed records remain in the declared Job Packet scope: '
                + ', '.join(removed_ids) + '. Restore them before issuing or handing over this project packet.')
    if not active:
        permissions={key:[] if isinstance(value,list) else False for key,value in permissions.items()}
    for item in items:
        item['removal']=removal_summary(s,'item',item['item_id'])
    return {'project':row_dict(project),'configured':bool(cfg),'config':row_dict(cfg) if cfg else None,
        'removal':removal_summary(s,'order',project_id),'can_mutate':active,
        'version':cfg.version if cfg else 0,'documents':documents,'items':items,'scope':scope,
        'issues':issues,'latest_project_issue':latest,'latest_issue':latest,
        'handovers':handovers,'transfer_status':transfer_status,
        'events':[row_dict(r) for r in s.scalars(select(DossierEvent).where(DossierEvent.project_id==project_id).order_by(DossierEvent.sequence.desc()))],
        'permissions':permissions,'source_status':source['status'],'source_review':source['review'],
        'completion_blockers':completion_blockers,'fingerprint':fingerprint,
        'summary':{'items':len(items),'approved_packets':sum(bool(p['latest_issue'] and p['latest_issue']['current']) for p in items),
            'stale_packets':sum(bool(p['latest_issue'] and not p['latest_issue']['current']) for p in items),
            'checklist_percent':round(sum(p['percent'] for p in items)/len(items),1) if items else 0}}


@router.get('/catalog')
def catalog(user:Employee=Depends(auth)):
    return {'version':VERSION,'source_note':SOURCE_NOTE,'source_references':SOURCE_REFERENCES,
        'sections':SECTIONS,'checks':CHECKS,'limits':{'max_file_bytes':MAX_FILE_BYTES,
        'max_project_file_bytes':MAX_PROJECT_FILE_BYTES,'allowed_extensions':list(MEDIA)}}


@router.get('/projects')
def projects(user:Employee=Depends(auth),s:Session=Depends(db)):
    from removals import project_not_removed
    result=[]
    for p in s.scalars(select(Project).where(project_not_removed(Project.id)).order_by(Project.name,Project.id)):
        detail=project_detail(s,p.id,user)
        result.append({**row_dict(p),**{k:detail[k] for k in ('configured','config','summary','latest_project_issue','transfer_status')}})
    return {'projects':result}


@router.get('/projects/{project_id}')
def get_project(project_id:str,user:Employee=Depends(auth),s:Session=Depends(db)):
    return project_detail(s,project_id,user)


@router.put('/projects/{project_id}/config')
def configure_project(project_id:str,data:ConfigIn,user:Employee=Depends(auth),s:Session=Depends(db)):
    require_capability(user,'dossier_manage')
    cfg=_locked(s,project_id,data.expected_version)
    from orders import guard_dossier_purchase_order
    guard_dossier_purchase_order(s,project_id,data.purchase_order)
    _lock_items(s,project_id)
    if cfg and (cfg.shipping_gate!=data.shipping_gate or cfg.customer_approval_required!=data.customer_approval_required):
        require_capability(user,'dossier_review')
    if not cfg and not data.shipping_gate:
        require_capability(user,'dossier_review')
    values=data.model_dump(exclude={'expected_version'})
    before=row_dict(cfg) if cfg else None
    first=cfg is None
    if first:
        cfg=DossierProject(project_id=project_id,created_by=user.badge,**values)
        s.add(cfg);s.flush()
    else:
        for key,value in values.items():setattr(cfg,key,value)
    _bump(s,cfg,user,'configured',{'before':before,'after':values},first=first)
    _commit(s)
    return project_detail(s,project_id,user)


@router.post('/projects/{project_id}/source-review')
def review_source(project_id:str,data:SignedIn,user:Employee=Depends(auth),s:Session=Depends(db)):
    require_capability(user,'dossier_review')
    cfg=_locked(s,project_id,data.expected_version) or _config(s,project_id)
    _lock_items(s,project_id)
    basis=_source_basis(cfg)
    review=DossierReview(project_id=project_id,code='source',decision='accepted',reference=data.reference,
        notes=data.notes,fingerprint=_digest(basis),snapshot=basis,actor=user.badge)
    s.add(review);s.flush()
    _bump(s,cfg,user,'source_reviewed',{'review_id':review.id,'reference':data.reference,'fingerprint':review.fingerprint})
    _commit(s)
    return project_detail(s,project_id,user)


@router.get('/items/{item_id}')
def get_item(item_id:str,user:Employee=Depends(auth),s:Session=Depends(db)):
    item,_=_item(s,item_id)
    return item_detail(s,item,user)


def _editable_item(s,item_id,expected):
    lock_topology(s)
    item,plan=_item(s,item_id)
    from removals import require_active_item
    require_active_item(s,item_id)
    cfg=_locked(s,plan.project_id,expected) or _config(s,plan.project_id)
    _lock_items(s,plan.project_id)
    return item,plan,cfg


@router.put('/items/{item_id}/checks/{code}')
def save_check(item_id:str,code:str,data:EntryIn,user:Employee=Depends(auth),s:Session=Depends(db)):
    if code not in CHECK_BY_CODE:_error('Unknown Job Packet checklist item',404)
    if code not in user_permissions(user)['dossier_check_codes']:
        _error('Your job position cannot edit this Job Packet checklist item',403)
    item,plan,cfg=_editable_item(s,item_id,data.expected_version)
    if set(data.values)-{f['name'] for f in CHECK_BY_CODE[code]['fields']}:
        _error('Use the named evidence fields in the checklist catalog',422)
    documents={d['id']:d for d in _documents(s,cfg.project_id) if d['item_id'] in (None,item_id)}
    if any(identifier not in documents for identifier in data.document_ids):
        _error('Every selected document must belong to this project and this item or the shared project scope',422)
    entry=s.scalar(select(DossierEntry).where(DossierEntry.item_id==item_id,DossierEntry.code==code))
    before=row_dict(entry) if entry else None
    values=data.model_dump(exclude={'expected_version'})
    values['document_ids']=sorted(set(values['document_ids']))
    if entry:
        entry.project_id=cfg.project_id
        for key,value in values.items():setattr(entry,key,value)
        entry.version+=1;entry.updated_by=user.badge;entry.updated_at=utcnow()
    else:
        entry=DossierEntry(project_id=cfg.project_id,item_id=item_id,code=code,updated_by=user.badge,**values)
        s.add(entry)
    s.flush()
    _bump(s,cfg,user,'check_saved',{'code':code,'before':before,'after':row_dict(entry)},item_id)
    _commit(s)
    return item_detail(s,item,user)


@router.post('/items/{item_id}/checks/{code}/review')
def review_check(item_id:str,code:str,data:ReviewIn,user:Employee=Depends(auth),s:Session=Depends(db)):
    require_capability(user,'dossier_review')
    if code not in CHECK_BY_CODE:_error('Unknown Job Packet checklist item',404)
    item,plan,cfg=_editable_item(s,item_id,data.expected_version)
    entry=s.scalar(select(DossierEntry).where(DossierEntry.item_id==item_id,DossierEntry.code==code,
        DossierEntry.project_id==cfg.project_id))
    records=_actual_records(s,item,plan,user)
    documents=[d for d in _documents(s,cfg.project_id) if d['item_id'] in (None,item_id)]
    spec=CHECK_BY_CODE[code];basis=_check_basis(cfg,item,spec,entry,records,documents)
    if data.decision!='rejected':
        errors=_entry_errors(cfg,item,spec,entry,basis,records)
        if _source_view(s,cfg)['status']!='confirmed':errors.insert(0,'Confirm the original project/PO sources first')
        expected='not_applicable' if entry and entry.applicability=='not_applicable' else 'accepted'
        if data.decision!=expected:errors.append('The review decision must match the saved applicability')
        if errors:_error({'message':'The current checklist evidence cannot be accepted','blockers':errors})
    review=DossierReview(project_id=cfg.project_id,item_id=item_id,code=code,decision=data.decision,
        reference=data.reference,notes=data.notes,fingerprint=_digest(basis),snapshot=basis,actor=user.badge)
    s.add(review);s.flush()
    _bump(s,cfg,user,'check_reviewed',{'code':code,'review_id':review.id,'decision':data.decision,
        'fingerprint':review.fingerprint,'reference':data.reference},item_id)
    _commit(s)
    return item_detail(s,item,user)


def _safe_filename(value):
    value=(value or '').replace('\\','/').rsplit('/',1)[-1]
    value=re.sub(r'[^A-Za-z0-9._-]+','_',value).lstrip('._')
    if not value or '.' not in value:_error('A named file with an allowed extension is required',422)
    stem,extension=value.rsplit('.',1)
    return stem[:150]+'.'+extension.lower()


def _validate_file(filename,declared,content):
    extension='.'+filename.rsplit('.',1)[-1]
    if extension not in MEDIA:_error('Unsupported file type; use PDF, PNG, JPEG, TXT, CSV, XLSX or DOCX',415)
    if declared and declared.split(';',1)[0].lower() not in (MEDIA[extension],'application/octet-stream'):
        _error('The uploaded media type does not match the filename',415)
    if not content:_error('An empty file cannot be supporting evidence',422)
    valid=True
    if extension=='.pdf':valid=content.startswith(b'%PDF-')
    elif extension=='.png':valid=content.startswith(b'\x89PNG\r\n\x1a\n')
    elif extension in ('.jpg','.jpeg'):valid=content.startswith(b'\xff\xd8\xff')
    elif extension in ('.txt','.csv'):
        try:
            decoded=content.decode('utf-8-sig')
            valid='\x00' not in decoded
        except UnicodeDecodeError:valid=False
    elif extension in ('.docx','.xlsx'):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                names=z.namelist()
                valid=('[Content_Types].xml' in names and
                    ('word/document.xml' if extension=='.docx' else 'xl/workbook.xml') in names and
                    len(names)<=3000 and sum(i.file_size for i in z.infolist())<=64*1024*1024 and
                    not any(i.flag_bits&1 for i in z.infolist()) and
                    not any(n.startswith(('/','\\')) or '..' in n.split('/') or 'vbaproject' in n.lower() for n in names))
        except (zipfile.BadZipFile,ValueError):valid=False
    if not valid:_error('The actual file content does not match its allowed document format',415)
    return MEDIA[extension]


@router.post('/projects/{project_id}/documents',status_code=201)
def upload_document(project_id:str,expected_version:str=Form(...,min_length=1,max_length=18),
        code:str=Form(...,min_length=1,max_length=100),title:str=Form(...,min_length=2,max_length=240),
        revision:str=Form(...,min_length=1,max_length=80),section:str=Form(...,min_length=2,max_length=2),
        item_id:str=Form(default='',max_length=60),reference:str=Form(default='',max_length=1000),
        file:UploadFile=File(...),user:Employee=Depends(auth),s:Session=Depends(db)):
    if not re.fullmatch(r'0|[1-9][0-9]*',expected_version):_error('expected_version must be a nonnegative integer',422)
    code,title,revision,section,item_id,reference=(x.strip() for x in (code,title,revision,section,item_id,reference))
    if not code or len(title)<2 or not revision or any(ord(c)<32 for c in code+title+revision+reference):
        _error('Use nonblank document identifiers, title and revision without control characters',422)
    if section not in {r['code'] for r in SECTIONS}:_error('Select a valid CLM dossier section',422)
    if section not in user_permissions(user)['dossier_upload_sections']:
        _error('Your job position cannot upload records to this Job Packet section',403)
    cfg=_locked(s,project_id,int(expected_version)) or _config(s,project_id)
    _lock_items(s,project_id)
    if item_id:
        item,plan=_item(s,item_id)
        if plan.project_id!=project_id:_error('The document item must belong to this project',422)
        from removals import require_active_item
        require_active_item(s,item_id)
    prior_sections=set(s.scalars(select(DossierDocument.section).where(
        DossierDocument.project_id==project_id,DossierDocument.scope_key==item_id,
        DossierDocument.code==code)))
    if prior_sections-set(user_permissions(user)['dossier_upload_sections']):
        _error('Your job position cannot revise this document by moving it from another department section',403)
    if s.scalar(select(DossierDocument.id).where(DossierDocument.project_id==project_id,
            DossierDocument.scope_key==item_id,DossierDocument.code==code,DossierDocument.revision==revision)):
        _error('This document revision already exists. Upload a new controlled revision; existing bytes cannot be replaced')
    filename=_safe_filename(file.filename)
    try:
        content=file.file.read(MAX_FILE_BYTES+1)
    finally:
        file.file.close()
    if len(content)>MAX_FILE_BYTES:_error('A supporting file must not exceed 8 MiB',413)
    media_type=_validate_file(filename,file.content_type,content)
    stored=s.scalar(select(func.coalesce(func.sum(DossierDocument.size_bytes),0)).where(DossierDocument.project_id==project_id))
    if stored+len(content)>MAX_PROJECT_FILE_BYTES:_error('The project document revision storage limit is 256 MiB',413)
    document=DossierDocument(project_id=project_id,item_id=item_id or None,scope_key=item_id,
        code=code,title=title,revision=revision,section=section,reference=reference,
        filename=filename,media_type=media_type,size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest(),actor=user.badge)
    s.add(document);s.flush()
    s.add(DossierFile(document_id=document.id,content=content))
    _bump(s,cfg,user,'document_uploaded',{'document':row_dict(document)},item_id or None)
    _commit(s)
    return project_detail(s,project_id,user)


@router.get('/documents/{document_id}/download')
def download_document(document_id:int,user:Employee=Depends(auth),s:Session=Depends(db)):
    document=s.get(DossierDocument,document_id)
    if not document:_error('Supporting document not found',404)
    stored=s.get(DossierFile,document_id)
    if not stored:_error('Stored supporting file is missing',409)
    content=stored.content
    if len(content)!=document.size_bytes or hashlib.sha256(content).hexdigest()!=document.sha256:
        _error('Stored document integrity verification failed; contact QA before use',409)
    return Response(content,media_type=document.media_type,headers={
        'Content-Disposition':'attachment; filename="'+document.filename+'"','X-Content-Type-Options':'nosniff',
        'Cache-Control':'private, no-store','X-Content-SHA256':document.sha256})


def _selected_documents(packet):
    selected={identifier for section in packet['sections'] for check in section['checks'] for identifier in check['document_ids']}
    return [d for d in packet['documents'] if d['id'] in selected]


def _unique_spool_documents(documents):
    """Freeze exact file identities and their physical spool associations."""
    rows={(d['spool_id'],d['document_id']):d for d in documents}
    return [rows[key] for key in sorted(rows)]


def _external_references(packet):
    return [{'scope':packet['item']['id'],'check':c['code'],'reference':c['reference'],
        'embedded_document_ids':c['document_ids'],'source':c['source']}
        for section in packet['sections'] for c in section['checks'] if c['reference']]


def _issued_header(project_id,item_id,revision,data,user,at):
    return {'project_id':project_id,'item_id':item_id,'revision':revision,'reference':data.reference,
        'notes':data.notes,'actor':user.badge,'at':_fmt(at)}


def _save_issue(s,cfg,item_id,kind,fingerprint,snapshot,data,user,at):
    if len(_canonical(snapshot))>MAX_SNAPSHOT_BYTES:
        _error('The generated record snapshot exceeds 12 MiB; split the project into reviewed scopes before issue',413)
    snapshot_hash=_digest(snapshot)
    printable=_render_item(snapshot) if kind=='item' else _render_project(snapshot,snapshot_hash)
    issue=DossierIssue(project_id=cfg.project_id,item_id=item_id,scope_key=item_id or '',kind=kind,
        revision=snapshot['issued']['revision'],fingerprint=fingerprint,sha256=snapshot_hash,snapshot=snapshot,
        print_html=printable,print_sha256=hashlib.sha256(printable.encode('utf-8')).hexdigest(),
        reference=data.reference,notes=data.notes,actor=user.badge,at=at)
    s.add(issue);s.flush()
    _bump(s,cfg,user,'packet_issued' if kind=='item' else 'project_issued',
        {'issue_id':issue.id,'revision':issue.revision,'fingerprint':fingerprint,'sha256':issue.sha256,
        'reference':data.reference},item_id)
    return issue


@router.post('/items/{item_id}/issue',status_code=201)
def issue_item(item_id:str,data:SignedIn,user:Employee=Depends(auth),s:Session=Depends(db)):
    require_capability(user,'dossier_review')
    item,plan,cfg=_editable_item(s,item_id,data.expected_version)
    packet=_packet(s,item,user)
    if packet['blockers']:_error({'message':'The Job Packet is incomplete or its physical release is not current','blockers':packet['blockers']})
    latest=_latest_issue(s,cfg.project_id,item_id)
    if latest and latest.fingerprint==packet['fingerprint']:_error('This exact current packet has already been issued; download its retained revision')
    revision=(latest.revision+1) if latest else 1
    packet.pop('basis',None)
    packet['documents']=_selected_documents(packet)
    children=[_get_issue(s,c['issue_id']) for c in packet['child_packets']]
    documents={d['id']:d for d in packet['documents']}
    spool_documents=list(packet['records'].get('spool_documents',[]))
    mtr_documents=list(packet['records'].get('mtr_documents',[]))
    references=_external_references(packet)
    for child in children:
        documents.update({d['id']:d for d in child.snapshot['documents']})
        spool_documents.extend(child.snapshot.get('spool_documents',[]))
        mtr_documents.extend(child.snapshot.get('mtr_documents',[]))
        references.extend(child.snapshot['external_references'])
    at=utcnow()
    snapshot={'format':VERSION,'kind':'item','issued':_issued_header(cfg.project_id,item_id,revision,data,user,at),
        'source_note':SOURCE_NOTE,'source_references':SOURCE_REFERENCES,'packet':packet,
        'child_issues':[row_dict(child,('snapshot',)) for child in children],
        'documents':sorted(documents.values(),key=lambda d:d['id']),'external_references':references}
    if spool_documents:snapshot['spool_documents']=_unique_spool_documents(spool_documents)
    if mtr_documents:snapshot['mtr_documents']=_unique_spool_documents(mtr_documents)
    _save_issue(s,cfg,item_id,'item',packet['fingerprint'],snapshot,data,user,at)
    _commit(s)
    return item_detail(s,item,user)


@router.post('/projects/{project_id}/issue',status_code=201)
def issue_project(project_id:str,data:SignedIn,user:Employee=Depends(auth),s:Session=Depends(db)):
    require_capability(user,'dossier_review')
    cfg=_locked(s,project_id,data.expected_version) or _config(s,project_id)
    _lock_items(s,project_id)
    packets,scope,blockers,fingerprint,basis=_project_state(s,project_id,user)
    from removals import require_active_item
    for row in scope:
        require_active_item(s,row['id'])
    if blockers:_error({'message':'Every declared project part and packet must be complete and current','blockers':blockers})
    latest=_latest_issue(s,project_id,None)
    if latest and latest.fingerprint==fingerprint:_error('This exact current project package has already been issued')
    revision=(latest.revision+1) if latest else 1
    issues=[s.get(DossierIssue,p['latest_issue']['id']) for p in packets]
    documents={d['id']:d for issue in issues for d in issue.snapshot['documents']}
    spool_documents=_unique_spool_documents([d for issue in issues for d in issue.snapshot.get('spool_documents',[])])
    mtr_documents=_unique_spool_documents([d for issue in issues for d in issue.snapshot.get('mtr_documents',[])])
    at=utcnow()
    snapshot={'format':VERSION,'kind':'project','issued':_issued_header(project_id,None,revision,data,user,at),
        'source_note':SOURCE_NOTE,'source_references':SOURCE_REFERENCES,
        'project':row_dict(_project(s,project_id)),'config':row_dict(cfg),'scope':scope,'basis':basis,
        'item_issues':[row_dict(issue,('snapshot',)) for issue in issues],
        'documents':sorted(documents.values(),key=lambda d:d['id']),
        'external_references':[r for issue in issues for r in issue.snapshot['external_references']]}
    if spool_documents:snapshot['spool_documents']=spool_documents
    if mtr_documents:snapshot['mtr_documents']=mtr_documents
    _save_issue(s,cfg,None,'project',fingerprint,snapshot,data,user,at)
    _commit(s)
    return project_detail(s,project_id,user)


def _get_issue(s,issue_id):
    issue=s.get(DossierIssue,issue_id)
    if not issue:_error('Issued Job Packet revision not found',404)
    if _digest(issue.snapshot)!=issue.sha256:_error('Issued snapshot integrity verification failed; contact QA before use')
    return issue


@router.get('/issues/{issue_id}')
def get_issue(issue_id:int,user:Employee=Depends(auth),s:Session=Depends(db)):
    issue=_get_issue(s,issue_id)
    # Historical retrieval is exact; current validity is shown by the item/project views.
    return {'issue':row_dict(issue,('snapshot',)),'snapshot':issue.snapshot}


def _date(value,earliest=None):
    try:day=dt.date.fromisoformat(value)
    except ValueError:_error('Record a real calendar date in YYYY-MM-DD format',422)
    if day.isoformat()!=value or day>utcnow().date():_error('Record the actual date; a future dispatch or receipt cannot be claimed',422)
    if earliest and day<earliest:_error('The event date cannot precede issue or the recorded dispatch',422)
    return value


@router.post('/projects/{project_id}/handovers',status_code=201)
def record_handover(project_id:str,data:HandoverIn,user:Employee=Depends(auth),s:Session=Depends(db)):
    require_capability(user,'dossier_handover')
    cfg=_locked(s,project_id,data.expected_version) or _config(s,project_id)
    _lock_items(s,project_id)
    issue=_get_issue(s,data.issue_id)
    if issue.project_id!=project_id or issue.kind!='project':_error('Select a project package issued for this project',422)
    _,scope,blockers,fingerprint,_=_project_state(s,project_id,user)
    from removals import require_active_item
    for row in scope:
        require_active_item(s,row['id'])
    if blockers or issue.fingerprint!=fingerprint:_error('Only a current complete issued project package can be dispatched')
    _date(data.occurred_on,dt.datetime.fromisoformat(_fmt(issue.at)).date())
    row=DossierHandover(project_id=project_id,event='dispatch',actor=user.badge,
        **data.model_dump(exclude={'expected_version'}))
    s.add(row);s.flush()
    _bump(s,cfg,user,'handover_dispatched',{'handover':row_dict(row)})
    _commit(s)
    return project_detail(s,project_id,user)


def _receipt(s,project_id,handover_id,data,user):
    require_capability(user,'dossier_handover')
    cfg=_locked(s,project_id,data.expected_version) or _config(s,project_id)
    original=s.get(DossierHandover,handover_id)
    if not original or original.project_id!=project_id:_error('Dispatch record not found',404)
    if original.event!='dispatch':_error('Receipt must identify an actual dispatch record',422)
    if s.scalar(select(DossierHandover.id).where(DossierHandover.dispatch_id==handover_id)):
        _error('This dispatch already has a recorded receipt')
    _date(data.occurred_on,dt.date.fromisoformat(original.occurred_on))
    row=DossierHandover(project_id=project_id,issue_id=original.issue_id,channel=original.channel,
        event='receipt',dispatch_id=original.id,organization=original.organization,actor=user.badge,
        **data.model_dump(exclude={'expected_version'}))
    s.add(row);s.flush()
    _bump(s,cfg,user,'handover_received',{'handover':row_dict(row)})
    _commit(s)
    return project_detail(s,project_id,user)


@router.post('/projects/{project_id}/handovers/{handover_id}/receipt',status_code=201)
def record_receipt(project_id:str,handover_id:int,data:ReceiptIn,user:Employee=Depends(auth),s:Session=Depends(db)):
    return _receipt(s,project_id,handover_id,data,user)


@router.post('/handovers/{handover_id}/receipt',status_code=201)
def receipt_alias(handover_id:int,data:ReceiptIn,user:Employee=Depends(auth),s:Session=Depends(db)):
    original=s.get(DossierHandover,handover_id)
    if not original:_error('Dispatch record not found',404)
    return _receipt(s,original.project_id,handover_id,data,user)


def dossier_gate_errors(s,item,phase='shipment',*,for_update=False):
    """Opt-in Job Packet gates; the mutation caller owns the topology lock.

    Pre-coating uses only source, pressure and written customer hold decisions.
    Shipment uses current issued item and child spool packets. GET callers never
    request locks and this function does not create history or change records.
    """
    from types import SimpleNamespace
    if phase not in ('pre_coating','shipment'):raise ValueError('Unknown Job Packet gate phase')
    plan=s.get(SpoolPlan,item.id)
    if not plan:return []
    query=select(DossierProject).where(DossierProject.project_id==plan.project_id)
    if for_update:query=query.with_for_update().execution_options(populate_existing=True)
    cfg=s.scalar(query)
    if not cfg or not cfg.shipping_gate:return []
    if for_update:_lock_items(s,cfg.project_id)
    user=SimpleNamespace(role='inspector')
    ids=[item.id];seen=set();errors=[]
    if _source_view(s,cfg)['status']!='confirmed':errors.append('Job Packet: confirm the original source and current project/PO applicability')
    while ids:
        item_id=ids.pop(0)
        if item_id in seen:
            errors.append('Job Packet: circular child spool/assembly scope')
            continue
        seen.add(item_id)
        physical=s.get(Item,item_id);physical_plan=s.get(SpoolPlan,item_id)
        if not physical or not physical_plan or physical_plan.project_id!=cfg.project_id:
            errors.append('Job Packet: child '+item_id+' is missing or belongs to another project')
            continue
        ids.extend(s.scalars(select(SpoolPlan.item_id).where(SpoolPlan.assembly_id==item_id).order_by(SpoolPlan.item_id)))
        if phase=='pre_coating':
            records=_actual_records(s,physical,physical_plan,user)
            documents=[d for d in _documents(s,cfg.project_id) if d['item_id'] in (None,item_id)]
            for code in ('pressure','customer_hold'):
                entry=s.scalar(select(DossierEntry).where(DossierEntry.item_id==item_id,
                    DossierEntry.project_id==cfg.project_id,DossierEntry.code==code))
                review=_latest_review(s,cfg.project_id,item_id,code)
                view,_=_check_view(cfg,physical,CHECK_BY_CODE[code],entry,review,records,documents)
                if view['status'] not in ('accepted','not_applicable'):
                    errors.append('Job Packet '+item_id+' · '+view['title']+': '+('; '.join(view['blockers']) or 'Current signed QA acceptance is required'))
        else:
            packet=_packet(s,physical,user)
            issued=_latest_issue(s,cfg.project_id,item_id)
            if packet['blockers']:
                errors.extend('Job Packet '+item_id+': '+message for message in packet['blockers'])
            if not issued or issued.fingerprint!=packet['fingerprint'] or packet['blockers']:
                errors.append('Job Packet '+item_id+': current complete QA-issued revision required before Ready to Ship')
    return list(dict.fromkeys(errors))


def _escape(value):
    return html.escape('' if value is None else str(value),quote=True)


def _table(rows,columns=None):
    if not rows:return '<p class="muted">No recorded rows in this scope.</p>'
    columns=columns or list(dict.fromkeys(k for row in rows for k in row))
    def value(v):
        return _escape(json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(dict,list)) else v)
    return '<div class="table"><table><thead><tr>'+''.join('<th>'+_escape(k.replace('_',' '))+'</th>' for k in columns)+'</tr></thead><tbody>'+''.join(
        '<tr>'+''.join('<td>'+value(row.get(k))+'</td>' for k in columns)+'</tr>' for row in rows)+'</tbody></table></div>'


def _page(title,body):
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+_escape(title)+'''</title><style>
    :root{font-family:Arial,Helvetica,sans-serif;color:#162d38;font-size:14px}body{margin:0;background:#edf2f3}main{max-width:1100px;margin:24px auto;background:white;padding:36px}
    h1{font-size:28px}h2{margin-top:30px;border-bottom:2px solid #178078;padding-bottom:8px}h3{font-size:17px;margin-bottom:7px}p,li{line-height:1.55}small,.muted{color:#536872}
    .banner{background:#e3f3ef;border-left:5px solid #14796e;padding:14px}.draft{background:#fff1d7;border-color:#b8640a}.section{page-break-inside:avoid}
    table{width:100%;border-collapse:collapse;margin:14px 0;font-size:11px}th,td{text-align:left;vertical-align:top;padding:7px;border:1px solid #cad5d8;overflow-wrap:anywhere}th{background:#e9eff1}
    pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:10px;background:#f4f7f8;padding:12px}a{color:#08675f}.signatures{display:grid;grid-template-columns:1fr 1fr;gap:30px}.line{border-bottom:1px solid #52656b;height:35px}
    @media print{body{background:white}main{margin:0;padding:0;max-width:none}h2{break-after:avoid}tr{break-inside:avoid}thead{display:table-header-group}.table{overflow:visible}a{color:inherit}details{display:block}.print-hide{display:none}@page{size:A4;margin:15mm}
    </style></head><body><main>'''+body+'</main></body></html>'


def _render_item(snapshot,draft=False):
    packet=snapshot['packet'];item=packet['item'];issued=snapshot.get('issued',{})
    title='CLM Fabrication — Spool Quality Dossier'
    body='<p class="muted">Kelvion Job Packet · '+_escape(VERSION)+'</p><h1>'+title+'</h1>'
    if draft:
        body+='<div class="banner draft"><strong>DRAFT — NOT ISSUED</strong><p>This live preview is incomplete until all applicable evidence, QA decisions and physical releases are current.</p></div>'
    else:
        body+='<div class="banner"><strong>Retained issued revision '+_escape(issued['revision'])+'</strong><p>Issued by '+_escape(issued['actor'])+' at '+_escape(issued['at'])+'. Historical contents are fixed. Check FabTrace for current validity before use. A download does not record dispatch or receipt.</p></div>'
    body+=_table([{'project_id':packet['project']['id'],'project':packet['project']['name'],'item_id':item['id'],
        'description':item['description'],'drawing':item['drawing'],'revision':packet['records']['tracking']['plan']['drawing_revision'],
        'purchase_order':packet['config']['purchase_order'],'work_order':packet['config']['work_order']}])
    release_control=item.get('release_control',{})
    if release_control.get('active_override'):
        override=release_control['override']
        body+='<div class="banner draft"><strong>ADMINISTRATIVE RELEASE — QA RELEASE NOT VERIFIED</strong><p>'+_escape(override['reason'])+'</p><p>Recorded by '+_escape(override['actor'])+' at '+_escape(override['at'])+'. Existing inspection, hold and work records retain their actual status.</p></div>'
    body+='<p>'+_escape(snapshot['source_note'])+'</p><p><strong>Manufacturer:</strong> '+_escape(packet['config']['manufacturer_name'])+' · '+_escape(packet['config']['manufacturer_contact'])+'</p>'
    body+='<p><strong>Advisements:</strong> '+_escape(packet['config']['advisements'] or 'See reviewed applicability and records below.')+'</p>'
    body+='<h2>Table of contents</h2><ol>'+''.join('<li><a href="#section-'+s['code']+'">'+_escape(s['code']+' · '+s['title'])+'</a></li>' for s in packet['sections'])+'</ol>'
    if draft and packet['blockers']:
        body+='<h2>Outstanding records and decisions</h2><ul>'+''.join('<li>'+_escape(b)+'</li>' for b in packet['blockers'])+'</ul>'
    for section in packet['sections']:
        body+='<section id="section-'+section['code']+'"><h2>'+_escape(section['code']+' · '+section['title'])+'</h2>'
        for check in section['checks']:
            review=check['latest_review'] or {}
            body+='<div class="section"><h3>'+_escape(check['title'])+'</h3><p><strong>'+_escape(check['status'].replace('_',' ').upper())+'</strong> · '+_escape(check['source'])+'</p>'
            body+='<p><strong>Evidence reference:</strong> '+_escape(check['reference'])+'<br><strong>Recorded findings:</strong> '+_escape(check['notes'])+'</p>'
            if check['values']:body+=_table([check['values']])
            if review:body+='<p><strong>QA decision:</strong> '+_escape(review['decision'])+' · '+_escape(review['actor'])+' · '+_escape(review['at'])+' · '+_escape(review['reference'])+'<br>'+_escape(review['notes'])+'</p>'
            linked=[d for d in snapshot['documents'] if d['id'] in check['document_ids']]
            if linked:body+=_table(linked,['id','code','title','revision','filename','sha256'])
            body+='</div>'
        body+='</section>'
    records=packet['records'];tr=records['tracking']
    body+='<h2>Actual generated fabrication records</h2>'
    if records.get('arrival_qa'):
        body+='<h3>Physical spool arrival QA</h3>'
        body+=_table(records['arrival_qa'],['spool_id','current_pass','basis_sha256','inspection'])
        body+='<p>Arrival decisions identify the exact physical spool and reviewed BOM, heat and MTR basis. A later material or document change requires a fresh QA decision.</p>'
    if records.get('mtr_documents'):
        body+='<h3>Retained material test reports</h3>'
        body+=_table(records['mtr_documents'],['spool_id','reference','filename','revision','version','sha256'])
        body+='<ul>'
        for document in {d['document_id']:d for d in records['mtr_documents']}.values():
            link=('/api/spool-boms/mtr-files/'+str(document['document_id']) if draft else
                  'mtr-files/'+str(document['document_id'])+'_'+document['filename'])
            body+='<li><a href="'+_escape(quote(link,safe='/'))+'">'+_escape(document['filename'])+'</a></li>'
        body+='</ul>'
    if records.get('spool_documents'):
        body+='<h3>Uploaded spool bills of material and isometric drawings</h3>'
        body+=_table(records['spool_documents'],['spool_id','kind','filename','revision','page_count','sha256'])
        body+='<p>These files retain the references uploaded for each spool. Uploading a file does not record engineering or QA acceptance. The complete files are included with the digital packet.</p><ul>'
        for document in {d['document_id']:d for d in records['spool_documents']}.values():
            link=('/api/spool-documents/files/'+str(document['document_id']) if draft else
                  'spool-files/'+str(document['document_id'])+'_'+document['filename'])
            body+='<li><a href="'+_escape(quote(link,safe='/'))+'">'+_escape(document['filename'])+'</a></li>'
        body+='</ul>'
    if records.get('material_trace_records'):
        body+='<h3>Material heat and MTR register</h3>'
        for trace in records['material_trace']:
            body+='<h4>Physical spool '+_escape(trace['spool_id'])+' · '+_escape(trace['spool_number'])+'</h4>'
            body+=_table(trace['materials'], ['item','piece_number','tas_ln_number','description','material','length_display'])
            body+=_table(trace['materials'], ['item','piece_number','supplier','supplier_piece_id','heat_number','mtr_reference','mtr_url','notes'])
        body+='<p>Each row identifies one physical material piece on its own spool. MTR references and links identify supporting records; actual files are listed separately in the attachment register.</p>'
    body+='<h3>Weld register</h3>'+_table(tr['welds'],['number','component_a','heat_a','mtr_a','component_b','heat_b','mtr_b','wps','wps_revision','cycle','completed_by','completed_at','production_complete','qa_accepted'])
    body+='<h3>Weld operations and individual requirements</h3>'
    body+=_table([{'weld':w['number'],**work} for w in tr['welds'] for work in w['work']],['weld','cycle','operation','actor','at','notes'])
    body+=_table([{'weld':w['number'],**r} for w in tr['welds'] for r in w['requirements']],['weld','code','label','cycle','status','satisfied','evidence','reviews'])
    body+='<h3>Inspections and actual measurements</h3>'+_table(records['inspections'],['item_id','kind','result','report','measurements','inspector','at'])
    body+='<h3>Rework and process exceptions</h3>'+_table(records['reworks'])+_table(records['flow_exceptions'])
    body+='<h3>Process traveler records retained at issue</h3>'+_table(records['flow_events'],['item_id','sequence','step','action','reference','notes','actor','at','data'])
    body+='<h3>Child spools and component links</h3>'+_table(records['child_spools'],['item_id','project_id','description','drawing_revision','released','release_mode'])+_table(records['component_links'])
    if records.get('parts'):
        body+='<h3>Required spool parts and quantities retained at issue</h3>'+_table(records['parts']['lines'],
            ['id','part_number','description','required_qty','assigned_qty','received_qty','prepared_qty','short_qty','remaining_qty'])
        body+='<p>Each allocated physical Part ID counts once. Receipt and preparation use actual recorded component steps; unrecorded baseline history is not inferred.</p>'
        body+=_table([{'line_id':line['id'], **component} for line in records['parts']['lines'] for component in line['components']],
            ['line_id','id','google_part_number','received','prepared','flow_status','current_step','handler','location','blockers'])
    if snapshot.get('child_issues'):
        body+='<h3>Exact child packet revisions included with this assembly</h3>'+_table(snapshot['child_issues'],['id','item_id','revision','sha256','actor','at'])+'<ul>'
        for child in snapshot['child_issues']:
            base='/api/dossier/issues/'+str(child['id'])
            body+='<li>'+_escape(child['item_id'])+' revision '+_escape(child['revision'])+': <a href="'+base+'/print" target="_blank" rel="noopener">Print exact retained child packet</a> · <a href="'+base+'/download">Download exact child packet</a></li>'
        body+='</ul>'
    body+='<h2>Attachment register</h2>'+_table(snapshot['documents'],['id','scope_key','code','title','revision','filename','size_bytes','sha256'])
    body+='<h2>References and full retained structured records</h2><p>Only the files in the attachment register are embedded in the digital ZIP. Source citations, report identifiers and external references are not fetched or embedded automatically. Review the selected actual files for engineering acceptance criteria.</p>'
    body+=_table(snapshot['source_references'],['document','revision','location'])
    body+='<pre>'+_escape(json.dumps(records,ensure_ascii=False,sort_keys=True,indent=2))+'</pre>'
    return _page(title+' '+item['id'],body)


def _render_project(snapshot,sha256):
    p=snapshot['project'];issued=snapshot['issued']
    body='<p class="muted">CLM Fabrication · Kelvion Job Packet</p><h1>Project package and physical handover sheet</h1>'
    body+='<div class="banner"><strong>Retained project revision '+_escape(issued['revision'])+'</strong><p>Issued by '+_escape(issued['actor'])+' at '+_escape(issued['at'])+'. This sheet identifies a specific retained revision. Downloading or printing it does not record dispatch or receipt.</p></div>'
    body+=_table([{'project_id':p['id'],'project':p['name'],'purchase_order':snapshot['config']['purchase_order'],
        'work_order':snapshot['config']['work_order'],'reference':issued['reference'],'snapshot_sha256':sha256}])
    body+='<p>'+_escape(issued['notes'])+'</p><h2>Included item packet revisions</h2>'
    body+=_table(snapshot['item_issues'],['id','item_id','revision','actor','at','reference','sha256'])
    body+='<p>For a complete paper set, print this cover, each exact item revision below, and its original supporting appendices from the file register. These links open the retained revisions, not a changing live preview.</p><ul>'
    for item_issue in snapshot['item_issues']:
        base='/api/dossier/issues/'+str(item_issue['id'])
        local='items/'+str(item_issue['id'])+'-revision-'+str(item_issue['revision'])+'/job-packet.html'
        body+='<li>'+_escape(item_issue['item_id'])+' · revision '+_escape(item_issue['revision'])+': <a href="'+base+'/print" target="_blank" rel="noopener">Print exact item packet (signed-in FabTrace)</a> · <a href="'+base+'/download">Download exact item ZIP</a> · <a href="'+local+'">Open included HTML after extracting the project ZIP</a></li>'
    body+='</ul>'
    body+='<h2>Declared physical project scope at issue</h2>'+_table(snapshot['scope'],['id','description','kind','parent_id','fabrication_finished','status'])
    body+='<h2>Controlled file register</h2>'+_table(snapshot['documents'],['id','scope_key','code','title','revision','filename','sha256'])
    if snapshot.get('spool_documents'):
        body+='<h3>Spool BOM and isometric reference files</h3>'+_table(snapshot['spool_documents'],['spool_id','kind','filename','revision','page_count','sha256'])
    if snapshot.get('mtr_documents'):
        body+='<h3>Physical spool material test reports</h3>'+_table(snapshot['mtr_documents'],['spool_id','reference','filename','revision','version','sha256'])
    body+='<h2>Actual physical handover — complete at transfer</h2><p>Record the completed transfer in FabTrace against this issued revision. Keep signed paper or the receipt reference with the project records. Leave fields blank until the event occurs.</p><div class="signatures">'
    for label in ('Dispatched by / date','Received by / date','Recipient and organization','Transfer / signed receipt reference'):
        body+='<div><p>'+label+'</p><div class="line"></div></div>'
    body+='</div><h2>Digital transfer</h2><p>The ZIP contains this manifest, exact retained item packets, generated fabrication records, and selected supporting files. Share it through the approved company channel and then record the actual dispatch and, separately, confirmed receipt. Files represented only by external references are not embedded.</p>'
    body+='<h2>Source cross references</h2>'+_table(snapshot['source_references'])
    return _page('Project Job Packet '+p['id'],body)


@router.get('/items/{item_id}/preview')
def preview_item(item_id:str,user:Employee=Depends(auth),s:Session=Depends(db)):
    item,_=_item(s,item_id)
    packet=_packet(s,item,user);packet.pop('basis',None)
    snapshot={'packet':packet,'documents':_selected_documents(packet),'source_note':SOURCE_NOTE,'source_references':SOURCE_REFERENCES}
    if packet['records'].get('spool_documents'):snapshot['spool_documents']=packet['records']['spool_documents']
    if packet['records'].get('mtr_documents'):snapshot['mtr_documents']=packet['records']['mtr_documents']
    return HTMLResponse(_render_item(snapshot,True),headers={'Cache-Control':'private, no-store',
        'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"})


@router.get('/issues/{issue_id}/print')
def print_issue(issue_id:int,user:Employee=Depends(auth),s:Session=Depends(db)):
    issue=_get_issue(s,issue_id)
    content=_retained_html(issue)
    return HTMLResponse(content,headers={'Cache-Control':'private, no-store',
        'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"})


def _zip_add(archive,name,content):
    entry=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
    entry.compress_type=zipfile.ZIP_DEFLATED
    entry.external_attr=0o100600<<16
    archive.writestr(entry,content)


def _zip_stream(file):
    try:
        while True:
            chunk=file.read(64*1024)
            if not chunk:break
            yield chunk
    finally:file.close()


def _retained_html(issue):
    content=issue.print_html
    if hashlib.sha256(content.encode('utf-8')).hexdigest()!=issue.print_sha256:
        _error('Retained printable packet integrity verification failed; contact QA before use')
    return content


def _related_issues(s,issue):
    pending=list(issue.snapshot.get('item_issues',[]))+list(issue.snapshot.get('child_issues',[]))
    retained={}
    while pending:
        metadata=pending.pop(0)
        if metadata['id'] in retained:continue
        if metadata['id']==issue.id:_error('A retained package contains a circular issue reference')
        child=_get_issue(s,metadata['id'])
        if child.sha256!=metadata['sha256'] or child.project_id!=issue.project_id:
            _error('Retained child packet identity/integrity verification failed')
        retained[child.id]=child
        pending.extend(child.snapshot.get('child_issues',[]))
    return [retained[key] for key in sorted(retained)]


@router.get('/issues/{issue_id}/download')
def download_issue(issue_id:int,user:Employee=Depends(auth),s:Session=Depends(db)):
    issue=_get_issue(s,issue_id);snapshot=issue.snapshot
    output=tempfile.SpooledTemporaryFile(max_size=8*1024*1024,mode='w+b')
    try:
        related=_related_issues(s,issue)
        manifest={'format':snapshot['format'],'issue':row_dict(issue,('snapshot',)),
            'snapshot_sha256':issue.sha256,'external_references':snapshot['external_references'],
            'documents':snapshot['documents'],'related_issues':[row_dict(r,('snapshot',)) for r in related],
            'note':'Exact retained revision. Only listed documents are embedded; references are not retrieved. Download is not dispatch or receipt.'}
        if snapshot.get('spool_documents'):manifest['spool_documents']=snapshot['spool_documents']
        if snapshot.get('mtr_documents'):manifest['mtr_documents']=snapshot['mtr_documents']
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=True) as archive:
            _zip_add(archive,'manifest.json',_canonical(manifest))
            _zip_add(archive,'snapshot.json',_canonical(snapshot))
            if issue.kind=='item':
                _zip_add(archive,'job-packet.html',_retained_html(issue).encode('utf-8'))
                _zip_add(archive,'generated-records.json',_canonical(snapshot['packet']['records']))
            else:
                _zip_add(archive,'project-handover.html',_retained_html(issue).encode('utf-8'))
            for retained in related:
                prefix='items/'+str(retained.id)+'-revision-'+str(retained.revision)+'/'
                _zip_add(archive,prefix+'snapshot.json',_canonical(retained.snapshot))
                _zip_add(archive,prefix+'job-packet.html',_retained_html(retained).encode('utf-8'))
                _zip_add(archive,prefix+'generated-records.json',_canonical(retained.snapshot['packet']['records']))
            for document in snapshot['documents']:
                stored=s.get(DossierFile,document['id'])
                if not stored:_error('A retained supporting file is missing; contact QA before use')
                content=stored.content
                if len(content)!=document['size_bytes'] or hashlib.sha256(content).hexdigest()!=document['sha256']:
                    _error('Retained supporting file integrity verification failed; contact QA before use')
                _zip_add(archive,'files/'+str(document['id'])+'_'+document['filename'],content)
                s.expire(stored,['content'])
            # Resolve immutable IDs frozen at issue, never the current upload.
            # Preserve the matching paths in each included child's HTML too.
            packet_scopes=[('',snapshot)]+[
                ('items/'+str(r.id)+'-revision-'+str(r.revision)+'/',r.snapshot) for r in related]
            from spool_documents import spool_document_retained_file
            from spool_receiving import spool_mtr_retained_file
            for prefix,retained_snapshot in packet_scopes:
                for document in {d['document_id']:d for d in retained_snapshot.get('spool_documents',[])}.values():
                    stored=spool_document_retained_file(s,document['document_id'])
                    content=stored['content']
                    if (hashlib.sha256(content).hexdigest()!=document['sha256'] or
                            stored['filename']!=document['filename'] or stored['media_type']!=document['media_type']):
                        _error('Retained spool document integrity verification failed; contact QA before use')
                    _zip_add(archive,prefix+'spool-files/'+str(document['document_id'])+'_'+document['filename'],content)
                for document in {d['document_id']:d for d in retained_snapshot.get('mtr_documents',[])}.values():
                    stored=spool_mtr_retained_file(s,document['document_id'])
                    content=stored['content']
                    if (len(content)!=document['size_bytes'] or
                            hashlib.sha256(content).hexdigest()!=document['sha256'] or
                            stored['filename']!=document['filename'] or stored['media_type']!=document['media_type']):
                        _error('Retained spool MTR integrity verification failed; contact QA before use')
                    _zip_add(archive,prefix+'mtr-files/'+str(document['document_id'])+'_'+document['filename'],content)
        output.seek(0)
    except Exception:
        output.close()
        raise
    filename='FabTrace-'+issue.kind+'-packet-'+str(issue.id)+'-revision-'+str(issue.revision)+'.zip'
    return StreamingResponse(_zip_stream(output),media_type='application/zip',headers={
        'Content-Disposition':'attachment; filename="'+filename+'"','Cache-Control':'private, no-store',
        'X-Content-Type-Options':'nosniff','X-Snapshot-SHA256':issue.sha256},background=BackgroundTask(output.close))

