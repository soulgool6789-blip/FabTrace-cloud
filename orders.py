"""Purchase-order planning over the existing physical fabrication hierarchy.

Enrollment is explicit and additive. A purchase order owns one unchanged Project,
GPN groups organize its physical assemblies, and each assembly declares its child
spool count. These records never manufacture work, QA acceptance or a receipt.
"""
import datetime as dt
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from main import Audit, Base, Employee, Item, audit, auth, db, lock_item, permit, utcnow
from tracking import Project, SpoolPlan, new_id
from flow import FlowPlan, lock_topology
from permissions import has_capability

router = APIRouter(prefix='/api/orders', tags=['purchase orders'])


class PurchaseOrder(Base):
    __tablename__ = 'purchase_orders'
    __table_args__ = (UniqueConstraint('normalized_customer', 'normalized_number', name='uq_purchase_order_customer_number'),)
    project_id = Column(String(80), ForeignKey('tracking_projects.id'), primary_key=True)
    purchase_order = Column(String(200), nullable=False)
    normalized_number = Column(String(600), nullable=False)
    customer = Column(String(200), nullable=False, default='')
    normalized_customer = Column(String(600), nullable=False, default='')
    notes = Column(Text, nullable=False, default='')
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class OrderGpn(Base):
    __tablename__ = 'order_gpns'
    __table_args__ = (UniqueConstraint('project_id', 'normalized_gpn', name='uq_order_gpn_number'),)
    id = Column(String(60), primary_key=True)
    project_id = Column(String(80), ForeignKey('purchase_orders.project_id'), nullable=False, index=True)
    gpn = Column(String(160), nullable=False)
    normalized_gpn = Column(String(480), nullable=False)
    description = Column(String(500), nullable=False, default='')
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class OrderAssembly(Base):
    __tablename__ = 'order_assemblies'
    __table_args__ = (CheckConstraint('required_spools >= 1 AND required_spools <= 10000', name='ck_order_assembly_spool_count'),)
    item_id = Column(String(60), ForeignKey('items.id'), primary_key=True)
    gpn_id = Column(String(60), ForeignKey('order_gpns.id'), nullable=False, index=True)
    assembly_part_number = Column(String(160), nullable=False)
    required_spools = Column(Integer, nullable=False)
    notes = Column(Text, nullable=False, default='')
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    @field_validator('*', mode='before')
    @classmethod
    def valid_text(cls, value):
        if isinstance(value, str) and '\x00' in value:
            raise ValueError('Text cannot contain a null character')
        return value


class CreateOrderIn(Input):
    expected_version: int = Field(default=0, ge=0, le=0, strict=True)
    purchase_order: str = Field(min_length=2, max_length=200)
    customer: str = Field(default='', max_length=200)
    name: str = Field(default='', max_length=200)
    notes: str = Field(default='', max_length=3000)
    existing_project_id: str | None = Field(default=None, min_length=1, max_length=80)


class VersionIn(Input):
    expected_version: int = Field(ge=1, strict=True)


class EditOrderIn(VersionIn):
    purchase_order: str = Field(min_length=2, max_length=200)
    notes: str = Field(default='', max_length=3000)
    reason: str = Field(min_length=4, max_length=3000)


class CreateGpnIn(VersionIn):
    gpn: str = Field(min_length=1, max_length=160)
    description: str = Field(default='', max_length=500)


class EditGpnIn(CreateGpnIn):
    reason: str = Field(min_length=4, max_length=3000)


class AssemblyItemIn(Input):
    id: str = Field(min_length=3, max_length=60, pattern=r'^[A-Za-z0-9_-]+$')
    description: str = Field(min_length=2, max_length=300)
    google_part_number: str = Field(default='', max_length=160)
    drawing: str = Field(default='', max_length=160)
    location: str = Field(min_length=1, max_length=160)
    handler: str = Field(min_length=2, max_length=80)
    welds_required: int = Field(default=0, ge=0, le=10000, strict=True)


class AssemblyFields(VersionIn):
    assembly_part_number: str = Field(min_length=1, max_length=160)
    required_spools: int = Field(ge=1, le=10000, strict=True)
    notes: str = Field(default='', max_length=3000)


class CreateAssemblyIn(AssemblyFields):
    gpn_id: str = Field(min_length=1, max_length=60)
    item_id: str = Field(min_length=3, max_length=60, pattern=r'^[A-Za-z0-9_-]+$')
    create_item: AssemblyItemIn | None = None


class EditAssemblyIn(AssemblyFields):
    reason: str = Field(min_length=4, max_length=3000)


def _key(value):
    return ' '.join(value.split()).casefold()


def _row(obj, keys):
    result = {}
    for key in keys:
        value = getattr(obj, key)
        if isinstance(value, dt.datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=dt.timezone.utc)
            value = value.isoformat()
        result[key] = value
    return result


ORDER_FIELDS = 'project_id purchase_order customer notes version created_by created_at updated_at'.split()
GPN_FIELDS = 'id project_id gpn description created_by created_at updated_at'.split()
ASSEMBLY_FIELDS = 'item_id gpn_id assembly_part_number required_spools notes created_by created_at updated_at'.split()


def _order(s, project_id):
    row = s.get(PurchaseOrder, project_id)
    if row is None:
        raise HTTPException(404, 'Purchase order not found')
    return row


@contextmanager
def read_snapshot(s):
    """A single read-only database view for a PO tree and its derived counts."""
    bind = s.get_bind()
    engine = getattr(bind, 'engine', bind)
    with engine.connect() as raw:
        connection = raw.execution_options(isolation_level='REPEATABLE READ') if raw.dialect.name == 'postgresql' else raw
        with connection.begin():
            if connection.dialect.name == 'postgresql':
                connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            elif connection.dialect.name == 'sqlite':
                connection.exec_driver_sql('BEGIN')
            with Session(bind=connection, autoflush=False, expire_on_commit=False) as snapshot:
                yield snapshot


def _locked(s, project_id, expected_version, user):
    lock_topology(s)
    permit(user, 'admin', 'supervisor')
    row = s.scalar(select(PurchaseOrder).where(PurchaseOrder.project_id == project_id)
                   .with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, 'Purchase order not found')
    if row.version != expected_version:
        raise HTTPException(409, {'message': 'Purchase order changed; refresh and retry. No changes were saved.', 'current_version': row.version})
    return row


def _gpn(s, project_id, gpn_id):
    group = s.get(OrderGpn, gpn_id)
    if group is None or group.project_id != project_id:
        raise HTTPException(422, 'Choose a GPN belonging to this purchase order')
    return group


def _assembly(s, project_id, item_id):
    row = s.get(OrderAssembly, item_id)
    if row is None:
        raise HTTPException(404, 'Order assembly not found')
    _gpn(s, project_id, row.gpn_id)
    return row


def _commit(s):
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, 'A conflicting purchase order, GPN or assembly already exists. Refresh and retry; no changes were saved.') from None


def _flush(s):
    try:
        s.flush()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, 'A conflicting purchase order, GPN or assembly already exists. Refresh and retry; no changes were saved.') from None


def _event(s, order, user, action, *, before=None, after=None, reason='', item_id=None, first=False):
    if not first:
        order.version += 1
    order.updated_at = utcnow()
    audit(s, item_id, user.badge, 'ORDER_' + action, {
        'project_id': order.project_id, 'purchase_order': order.purchase_order,
        'version': order.version, 'reason': reason, 'before': before, 'after': after,
    })


def _linked(s, assembly_id):
    return s.execute(select(Item, SpoolPlan).join(SpoolPlan, SpoolPlan.item_id == Item.id)
                     .where(SpoolPlan.assembly_id == assembly_id).order_by(Item.id)).all()


def order_scope(s, item_id):
    """Lightweight context for flow forms; does not calculate progress or write."""
    mapping = s.get(OrderAssembly, item_id)
    if mapping is None:
        plan = s.get(SpoolPlan, item_id)
        mapping = s.get(OrderAssembly, plan.assembly_id) if plan and plan.assembly_id else None
    if mapping is None:
        return None
    group = s.get(OrderGpn, mapping.gpn_id)
    order = s.get(PurchaseOrder, group.project_id)
    return {'project_id': order.project_id, 'purchase_order': order.purchase_order,
            'gpn_id': group.id, 'gpn': group.gpn, 'assembly_id': mapping.item_id,
            'assembly_part_number': mapping.assembly_part_number, 'required_spools': mapping.required_spools}


def guard_flow_scope(s, item_id, expected_children):
    mapping = s.get(OrderAssembly, item_id)
    if mapping and expected_children != mapping.required_spools:
        raise HTTPException(409, f'This purchase-order assembly requires {mapping.required_spools} spools. The traveler must use that same declared count; adjust the order before starting the traveler.')


def guard_plan_scope(s, item, oldplan, values):
    """Apply order boundaries to the existing planner, including old UI clients."""
    old_parent_id = oldplan.assembly_id if oldplan else None
    new_parent_id = values.get('assembly_id')
    scope_keys = ('project_id', 'subproject_id', 'assembly_id', 'planned_welds', 'drawing_revision', 'zero_weld_reason')
    scope_changed = oldplan is None or any(
        key in values and getattr(oldplan, key) != values[key] for key in scope_keys)
    if scope_changed:
        for parent_id in sorted({value for value in (old_parent_id, new_parent_id) if value}):
            if s.get(OrderAssembly, parent_id) and lock_item(s, parent_id).released:
                raise HTTPException(409, 'Return the released purchase-order assembly to work before changing its child spool scope or links')
    managed = s.get(OrderAssembly, item.id)
    if managed:
        group = s.get(OrderGpn, managed.gpn_id)
        if values['project_id'] != group.project_id or values.get('assembly_id'):
            raise HTTPException(409, 'This assembly belongs to its purchase order and cannot be moved to another project or nested assembly')
    if oldplan and oldplan.assembly_id:
        prior = s.get(OrderAssembly, oldplan.assembly_id)
        if prior and values['project_id'] != s.get(OrderGpn, prior.gpn_id).project_id:
            raise HTTPException(409, 'A purchase-order spool cannot be moved to another project')
    parent_id = values.get('assembly_id')
    parent = s.get(OrderAssembly, parent_id) if parent_id else None
    if parent:
        group = s.get(OrderGpn, parent.gpn_id)
        if item.kind != 'Spool':
            raise HTTPException(422, 'Purchase-order assembly children must be registered as Spool items, not individual Parts or Assemblies')
        if values['project_id'] != group.project_id:
            raise HTTPException(409, 'Spool and purchase-order assembly must belong to the same project')
        other = len([child for child, _ in _linked(s, parent_id) if child.id != item.id])
        if other >= parent.required_spools:
            raise HTTPException(409, f'This assembly already has its {parent.required_spools} required spools')


def guard_dossier_purchase_order(s, project_id, purchase_order):
    order = s.get(PurchaseOrder, project_id)
    if order and _key(purchase_order) != order.normalized_number:
        raise HTTPException(409, 'The Job Packet purchase-order number must match the purchase order assigned to this project')


def _check_dossier(s, project_id, purchase_order):
    from dossier import DossierProject
    packet = s.get(DossierProject, project_id)
    if packet and _key(packet.purchase_order) != _key(purchase_order):
        raise HTTPException(409, 'The existing controlled Job Packet has a different PO number. Its purchase order cannot be silently replaced.')


def _validate_assembly_scope(s, order, item, required_spools):
    if item.kind != 'Assembly':
        raise HTTPException(422, 'Choose an Assembly item')
    plan = s.get(SpoolPlan, item.id)
    project_id = plan.project_id if plan else item.project
    if project_id != order.project_id:
        raise HTTPException(409, 'Assembly and purchase order must belong to the same project')
    if plan and plan.assembly_id:
        raise HTTPException(409, 'A purchase-order assembly cannot be nested inside another assembly')
    linked = _linked(s, item.id)
    if len(linked) > required_spools:
        raise HTTPException(409, 'Required spool count cannot be smaller than the existing linked spool count')
    if any(child.kind != 'Spool' or child_plan.project_id != order.project_id for child, child_plan in linked):
        raise HTTPException(409, 'Every existing child must be a Spool item planned in this purchase-order project')
    traveler = s.get(FlowPlan, item.id)
    if traveler and (traveler.route != 'assembly' or traveler.expected_children != required_spools):
        raise HTTPException(409, 'Required spool count must match the existing assembly traveler; the order does not rewrite established production scope')


def _assembly_detail(s, mapping, group, progress_rows):
    item = s.get(Item, mapping.item_id)
    plan = s.get(SpoolPlan, item.id)
    flow = s.get(FlowPlan, item.id)
    spools = []
    blockers = []
    for child, child_plan in _linked(s, item.id):
        child_flow = s.get(FlowPlan, child.id)
        row = progress_rows.get(child.id, {})
        errors = list(row.get('blockers', []))
        if child.kind != 'Spool' or child_plan.project_id != group.project_id:
            errors.append('Child identity or project does not match the purchase-order assembly')
        ready = bool(child.kind == 'Spool' and child_flow and child_flow.route == 'spool'
                     and child_flow.status == 'completed' and row.get('fabrication_finished') and not errors)
        spools.append({'item_id': child.id, 'description': child.description, 'google_part_number': child.google_part_number,
                       'project_id': child_plan.project_id, 'subproject_id': child_plan.subproject_id,
                       'flow_status': child_flow.status if child_flow else 'not_started',
                       'current_step': child_flow.current_step if child_flow else None,
                       'ready_for_assembly': ready, 'fabrication_finished': bool(row.get('fabrication_finished')),
                       'blocked': bool(errors), 'blockers': errors})
    linked, ready = len(spools), sum(row['ready_for_assembly'] for row in spools)
    if not plan:
        blockers.append('Assembly weld scope and drawing plan have not been set up')
    elif plan.project_id != group.project_id:
        blockers.append('Assembly project does not match the purchase order')
    if linked != mapping.required_spools:
        blockers.append(f'Spool identities incomplete: {linked} linked of {mapping.required_spools} required')
    if flow is None:
        blockers.append('Set up the purchase-order assembly traveler before ordinary final QA release')
    if flow and flow.expected_children != mapping.required_spools:
        blockers.append('Traveler count does not match the purchase-order requirement')
    return {**_row(mapping, ASSEMBLY_FIELDS), 'gpn': group.gpn,
            'description': item.description, 'google_part_number': item.google_part_number, 'drawing': item.drawing,
            'linked_spools': linked, 'missing_spools': max(0, mapping.required_spools - linked),
            'ready_spools': ready, 'not_ready_spools': linked - ready, 'planning_needed': plan is None,
            'flow_started': flow is not None, 'count_editable': flow is None and not item.released,
            'blockers': blockers, 'spools': spools}


def order_summary(s, order):
    project = s.get(Project, order.project_id)
    groups = s.scalars(select(OrderGpn).where(OrderGpn.project_id == order.project_id)).all()
    ids = [group.id for group in groups]
    mappings = s.scalars(select(OrderAssembly).where(OrderAssembly.gpn_id.in_(ids))).all() if ids else []
    linked = sum(len(_linked(s, row.item_id)) for row in mappings)
    required = sum(row.required_spools for row in mappings)
    return {**_row(order, ORDER_FIELDS), 'project_name': project.name,
            'gpn_count': len(groups), 'assembly_count': len(mappings), 'required_spools': required,
            'linked_spools': linked, 'missing_spools': sum(max(0, row.required_spools - len(_linked(s, row.item_id))) for row in mappings)}


def order_detail(s, project_id, user=None):
    """Read-only detail also used by the Excel snapshot; no enrollment on read."""
    from progress import project_rows
    order = _order(s, project_id)
    project = s.get(Project, project_id)
    groups = s.scalars(select(OrderGpn).where(OrderGpn.project_id == project_id).order_by(OrderGpn.gpn)).all()
    progress_rows = {row['id']: row for row in project_rows(s, project_id)}
    gpns, assemblies = [], []
    for group in groups:
        mappings = s.scalars(select(OrderAssembly).where(OrderAssembly.gpn_id == group.id).order_by(OrderAssembly.item_id)).all()
        children = [_assembly_detail(s, mapping, group, progress_rows) for mapping in mappings]
        gpns.append({**_row(group, GPN_FIELDS), 'assemblies': children, 'assembly_count': len(children),
                     **{key: sum(child[key] for child in children) for key in ('required_spools', 'linked_spools', 'missing_spools', 'ready_spools')}})
        assemblies.extend(children)
    assigned_ids = set(s.scalars(select(OrderAssembly.item_id)).all())
    available = []
    for item in s.scalars(select(Item).where(Item.kind == 'Assembly').order_by(Item.id)):
        if item.id in assigned_ids:
            continue
        plan = s.get(SpoolPlan, item.id)
        if (plan.project_id if plan else item.project) != project_id:
            continue
        available.append({'item_id': item.id, 'description': item.description, 'google_part_number': item.google_part_number,
                          'drawing': item.drawing, 'planned_welds': plan.planned_welds if plan else item.welds_required,
                          'planning_needed': plan is None})
    events = s.scalars(select(Audit).where(Audit.event.like('ORDER_%'), Audit.details['project_id'].as_string() == project_id)
                       .order_by(Audit.id.desc()).limit(100)).all()
    return {'order': {**_row(order, ORDER_FIELDS), 'project_name': project.name}, 'gpns': gpns, 'assemblies': assemblies,
            'totals': {'gpn_count': len(gpns), 'assembly_count': len(assemblies),
                       **{key: sum(row[key] for row in assemblies) for key in ('required_spools', 'linked_spools', 'missing_spools', 'ready_spools', 'not_ready_spools')}},
            'available_assemblies': available, 'permissions': {'can_manage': bool(user and has_capability(user, 'manage_production'))},
            'events': [_row(event, ('id', 'event', 'actor', 'at', 'details')) for event in events]}


@router.get('')
def list_orders(user: Employee = Depends(auth), s: Session = Depends(db)):
    role = user.role
    # Authentication has already borrowed a connection. Release it before
    # opening the snapshot, so concurrent readers cannot exhaust the pool
    # while each waits for a second connection. Keep only the plain role;
    # rollback expires the ORM employee and it must not be lazily reloaded.
    s.rollback()
    with read_snapshot(s) as snapshot:
        return _list_orders(snapshot, role)


def _list_orders(s, user):
    orders = s.scalars(select(PurchaseOrder).order_by(PurchaseOrder.purchase_order, PurchaseOrder.project_id)).all()
    assigned = {row.project_id for row in orders}
    return {'orders': [order_summary(s, row) for row in orders],
            'unassigned_projects': [_row(row, ('id', 'name', 'client')) for row in s.scalars(select(Project).order_by(Project.name)) if row.id not in assigned],
            'permissions': {'can_manage': has_capability(user, 'manage_production')}}


@router.post('', status_code=201)
def create_order(data: CreateOrderIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    lock_topology(s)
    permit(user, 'admin', 'supervisor')
    if data.existing_project_id:
        project = s.get(Project, data.existing_project_id)
        if not project:
            raise HTTPException(422, 'Existing project not found')
        if s.get(PurchaseOrder, project.id):
            raise HTTPException(409, 'This project already belongs to a purchase order')
        if len(data.notes) < 4:
            raise HTTPException(422, 'Record the PO reference and reason for attaching this existing project in the setup notes')
        if data.customer and _key(data.customer) != _key(project.client):
            raise HTTPException(409, 'The supplied customer must match the existing project customer; the project is not renamed or moved')
        customer = project.client
    else:
        customer = data.customer
        project = Project(id=new_id('PO'), name=data.name or ('PO ' + data.purchase_order)[:200],
                          client=customer, description=data.notes, created_by=user.badge)
        s.add(project)
        _flush(s)
    _check_dossier(s, project.id, data.purchase_order)
    duplicate = s.scalar(select(PurchaseOrder).where(PurchaseOrder.normalized_number == _key(data.purchase_order), PurchaseOrder.normalized_customer == _key(customer)))
    if duplicate:
        raise HTTPException(409, 'That PO number already exists for this customer')
    row = PurchaseOrder(project_id=project.id, purchase_order=data.purchase_order, normalized_number=_key(data.purchase_order),
                        customer=customer, normalized_customer=_key(customer), notes=data.notes, version=1, created_by=user.badge)
    s.add(row)
    _flush(s)
    _event(s, row, user, 'CREATED', after=_row(row, ORDER_FIELDS), reason=data.notes, first=True)
    _commit(s)
    return order_detail(s, project.id, user)


@router.get('/{project_id}')
def get_order(project_id: str, user: Employee = Depends(auth), s: Session = Depends(db)):
    role = user.role
    s.rollback()
    with read_snapshot(s) as snapshot:
        return order_detail(snapshot, project_id, role)


@router.patch('/{project_id}')
def edit_order(project_id: str, data: EditOrderIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    row = _locked(s, project_id, data.expected_version, user)
    _check_dossier(s, project_id, data.purchase_order)
    before = _row(row, ORDER_FIELDS)
    row.purchase_order, row.normalized_number, row.notes = data.purchase_order, _key(data.purchase_order), data.notes
    _event(s, row, user, 'UPDATED', before=before, after={'purchase_order': row.purchase_order, 'notes': row.notes}, reason=data.reason)
    _commit(s)
    return order_detail(s, project_id, user)


@router.post('/{project_id}/gpns', status_code=201)
def create_gpn(project_id: str, data: CreateGpnIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    row = _locked(s, project_id, data.expected_version, user)
    group = OrderGpn(id=new_id('OGPN'), project_id=project_id, gpn=data.gpn, normalized_gpn=_key(data.gpn),
                     description=data.description, created_by=user.badge)
    s.add(group)
    _flush(s)
    _event(s, row, user, 'GPN_CREATED', after=_row(group, GPN_FIELDS))
    _commit(s)
    return order_detail(s, project_id, user)


@router.patch('/{project_id}/gpns/{gpn_id}')
def edit_gpn(project_id: str, gpn_id: str, data: EditGpnIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    row = _locked(s, project_id, data.expected_version, user)
    group = _gpn(s, project_id, gpn_id)
    if data.gpn != group.gpn:
        for mapping in s.scalars(select(OrderAssembly).where(OrderAssembly.gpn_id == group.id)):
            item = lock_item(s, mapping.item_id)
            if item.released or s.get(FlowPlan, item.id):
                raise HTTPException(409, 'Correct the GPN before its assemblies enter a traveler or receive final release')
    before = _row(group, GPN_FIELDS)
    group.gpn, group.normalized_gpn, group.description = data.gpn, _key(data.gpn), data.description
    group.updated_at = utcnow()
    _event(s, row, user, 'GPN_UPDATED', before=before, after=_row(group, GPN_FIELDS), reason=data.reason)
    _commit(s)
    return order_detail(s, project_id, user)


@router.post('/{project_id}/assemblies', status_code=201)
def create_assembly(project_id: str, data: CreateAssemblyIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    from administration import employee_is_removed
    row = _locked(s, project_id, data.expected_version, user)
    group = _gpn(s, project_id, data.gpn_id)
    if s.get(OrderAssembly, data.item_id):
        raise HTTPException(409, 'This physical assembly already belongs to an order GPN')
    if data.create_item:
        if data.item_id != data.create_item.id:
            raise HTTPException(422, 'New item ID must match the assembly tracking ID')
        if s.get(Item, data.item_id):
            raise HTTPException(409, 'That item ID already exists; choose the existing-assembly option')
        employee = s.get(Employee, data.create_item.handler)
        if not employee or not employee.active or employee_is_removed(s, employee.badge):
            raise HTTPException(422, 'Choose an active employee handler badge')
        values = data.create_item.model_dump()
        item = Item(**values, kind='Assembly', project=project_id)
        s.add(item)
        _flush(s)
        audit(s, item.id, user.badge, 'ITEM_CREATED', {**values, 'kind': 'Assembly', 'project': project_id, 'source': 'purchase_order'})
    else:
        item = lock_item(s, data.item_id)
    _validate_assembly_scope(s, row, item, data.required_spools)
    mapping = OrderAssembly(item_id=item.id, gpn_id=group.id, assembly_part_number=data.assembly_part_number,
                            required_spools=data.required_spools, notes=data.notes, created_by=user.badge)
    s.add(mapping)
    _flush(s)
    _event(s, row, user, 'ASSEMBLY_CREATED', after=_row(mapping, ASSEMBLY_FIELDS), item_id=item.id)
    _commit(s)
    return order_detail(s, project_id, user)


@router.patch('/{project_id}/assemblies/{item_id}')
def edit_assembly(project_id: str, item_id: str, data: EditAssemblyIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    row = _locked(s, project_id, data.expected_version, user)
    mapping = _assembly(s, project_id, item_id)
    item = lock_item(s, item_id)
    if data.required_spools != mapping.required_spools or data.assembly_part_number != mapping.assembly_part_number:
        if item.released or s.get(FlowPlan, item.id):
            raise HTTPException(409, 'Set the required spool count and assembly part number before starting the assembly traveler. Existing production scope is preserved.')
    _validate_assembly_scope(s, row, item, data.required_spools)
    before = _row(mapping, ASSEMBLY_FIELDS)
    mapping.assembly_part_number, mapping.required_spools, mapping.notes = data.assembly_part_number, data.required_spools, data.notes
    mapping.updated_at = utcnow()
    _event(s, row, user, 'ASSEMBLY_UPDATED', before=before, after=_row(mapping, ASSEMBLY_FIELDS), reason=data.reason, item_id=item.id)
    _commit(s)
    return order_detail(s, project_id, user)
