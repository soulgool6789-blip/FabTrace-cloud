"""Purchase-order planning over the existing physical fabrication hierarchy.

Enrollment is explicit and additive. A purchase order owns one unchanged Project,
GPN groups organize its physical assemblies, and each assembly declares its child
spool count. These records never manufacture work, QA acceptance or a receipt.
"""
import datetime as dt
from collections import defaultdict
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from read_projection import prime_projection, read_get, read_projection

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
    __table_args__ = (
        Index('uq_order_named_assembly_number', 'project_id', 'normalized_assembly_number', unique=True,
              postgresql_where=text('normalized_assembly_number IS NOT NULL'),
              sqlite_where=text('normalized_assembly_number IS NOT NULL')),
        Index('uq_order_legacy_gpn_number', 'project_id', 'normalized_gpn', unique=True,
              postgresql_where=text('normalized_assembly_number IS NULL'),
              sqlite_where=text('normalized_assembly_number IS NULL')),
    )
    id = Column(String(60), primary_key=True)
    project_id = Column(String(80), ForeignKey('purchase_orders.project_id'), nullable=False, index=True)
    gpn = Column(String(160), nullable=False)
    normalized_gpn = Column(String(480), nullable=False)
    # Keep the recorded GPN as the physical/document identity basis. Current
    # business labels may be corrected without rewriting that retained basis.
    gpn_label = Column(String(160), nullable=True)
    # Historical unnamed definitions remain readable. New and edited assembly
    # records require an explicitly supplied number, never a GPN or Item ID.
    assembly_number = Column(String(160), nullable=False, default='', server_default='')
    normalized_assembly_number = Column(String(480), nullable=True)
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


class GooglePartNumber(Base):
    """One editable business GPN record per purchase order.

    ``OrderGpn`` remains the retained assembly-setup identity used by existing
    documents, QR labels and spool requirements. A separate link gives that
    assembly setup a parent here without rewriting any historical key.
    """
    __tablename__ = 'order_google_part_numbers'
    __table_args__ = (UniqueConstraint('project_id', 'normalized_gpn',
                                     name='uq_order_google_part_number'),)
    id = Column(String(60), primary_key=True)
    project_id = Column(String(80), ForeignKey('purchase_orders.project_id'), nullable=False, index=True)
    gpn = Column(String(160), nullable=False)
    normalized_gpn = Column(String(480), nullable=False)
    description = Column(String(500), nullable=False, default='')
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class AssemblyGpnLink(Base):
    """Explicit relationship from an assembly definition to its GPN record."""
    __tablename__ = 'order_assembly_gpn_links'
    assembly_definition_id = Column(String(60), ForeignKey('order_gpns.id'), primary_key=True)
    gpn_record_id = Column(String(60), ForeignKey('order_google_part_numbers.id'), nullable=False, index=True)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    @field_validator('*', mode='before')
    @classmethod
    def valid_text(cls, value):
        if isinstance(value, str) and '\x00' in value:
            raise ValueError('Text cannot contain a null character')
        return value

    @field_validator('assembly_number', check_fields=False)
    @classmethod
    def provided_assembly_number_is_not_null(cls, value):
        if value is None:
            raise ValueError('Assembly Number cannot be null. Omit it only to retain a saved Assembly Number.')
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
    assembly_number: str = Field(min_length=1, max_length=160)
    description: str = Field(default='', max_length=500)


class EditGpnIn(CreateGpnIn):
    assembly_number: str | None = Field(default=None, min_length=1, max_length=160)
    reason: str = Field(min_length=4, max_length=3000)


class CreateGpnRecordIn(VersionIn):
    gpn: str = Field(min_length=1, max_length=160)
    description: str = Field(default='', max_length=500)


class EditGpnRecordIn(CreateGpnRecordIn):
    reason: str = Field(min_length=4, max_length=3000)


class AssemblyItemIn(Input):
    id: str = Field(min_length=3, max_length=60, pattern=r'^[A-Za-z0-9_-]+$')
    description: str = Field(default='', max_length=300)
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
    # This retained exact-definition endpoint may reuse its saved number.
    # A supplied number must be nonblank and match that selected definition.
    assembly_number: str | None = Field(default=None, min_length=1, max_length=160)
    item_id: str = Field(min_length=3, max_length=60, pattern=r'^[A-Za-z0-9_-]+$')
    create_item: AssemblyItemIn | None = None


class EditAssemblyIn(AssemblyFields):
    reason: str = Field(min_length=4, max_length=3000)


class CombinedAssemblyItemIn(Input):
    id: str | None = Field(default=None, min_length=3, max_length=60, pattern=r'^[A-Za-z0-9_-]+$')
    location: str = Field(min_length=1, max_length=160)
    handler: str = Field(min_length=2, max_length=80)
    drawing: str = Field(default='', max_length=160)


class CombinedAssemblyFields(VersionIn):
    gpn: str = Field(min_length=1, max_length=160)
    assembly_number: str = Field(min_length=1, max_length=160)
    required_spools: int = Field(ge=1, le=10000, strict=True)
    notes: str = Field(default='', max_length=3000)


class CreateCombinedAssemblyIn(CombinedAssemblyFields):
    gpn_id: str | None = Field(default=None, min_length=1, max_length=60)
    item_id: str | None = Field(default=None, min_length=3, max_length=60, pattern=r'^[A-Za-z0-9_-]+$')
    create_item: CombinedAssemblyItemIn | None = None

    @model_validator(mode='after')
    def one_physical_record_mode(self):
        if (self.create_item is not None) == (self.item_id is not None):
            raise ValueError('Choose either a new assembly record or one existing physical assembly ID')
        return self


class EditCombinedAssemblyIn(CombinedAssemblyFields):
    assembly_number: str | None = Field(default=None, min_length=1, max_length=160)
    reason: str = Field(min_length=4, max_length=3000)


def _key(value):
    return ' '.join(value.split()).casefold()


def _require_assembly_number(value):
    """Reject unnamed writes without changing retained historical records."""
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(409, 'Assembly Number is required. Use Edit assembly in P.O. setup '
            'to record it before changing this assembly or creating physical copies.')
    return value


def business_gpn(group):
    """Current business label; the original GPN remains the identity basis."""
    return group.gpn_label or group.gpn


def sync_gpn_record(s, group, *, allow_removed=False):
    """Persist an explicit parent after an authorized assembly write only."""
    label = business_gpn(group)
    record = s.scalar(select(GooglePartNumber).where(
        GooglePartNumber.project_id == group.project_id,
        GooglePartNumber.normalized_gpn == _key(label)))
    if record is None:
        record = GooglePartNumber(id=new_id('GPN'), project_id=group.project_id,
            gpn=label, normalized_gpn=_key(label), description='',
            created_by=group.created_by, created_at=group.created_at or utcnow())
        s.add(record)
        _flush(s)
    elif not allow_removed:
        from removals import require_active_gpn_record
        require_active_gpn_record(s, record.id)
    link = s.get(AssemblyGpnLink, group.id)
    if link is None:
        s.add(AssemblyGpnLink(assembly_definition_id=group.id, gpn_record_id=record.id))
    elif link.gpn_record_id != record.id:
        link.gpn_record_id = record.id
    _flush(s)
    return record


def backfill_gpn_records(s):
    """Add missing GPN parents once, preserving every existing assembly ID.

    Called during initialization after confirmed current-label corrections.
    Existing links are never moved by a later startup. No physical record,
    source document or production evidence is updated.
    """
    known = set(s.scalars(select(AssemblyGpnLink.assembly_definition_id)))
    groups = s.scalars(select(OrderGpn).order_by(OrderGpn.project_id, OrderGpn.id)).all()
    count = 0
    for group in groups:
        if group.id not in known:
            sync_gpn_record(s, group, allow_removed=True)
            count += 1
    return count


def gpn_record_rows(s, project_id, assembly_rows, *, include_removed=False):
    """Read-only canonical GPNs and their separate assembly definitions."""
    from removals import gpn_record_not_removed, removal_summaries
    identifiers = [row.get('gpn_id', row.get('id')) for row in assembly_rows]
    links = dict(s.execute(select(AssemblyGpnLink.assembly_definition_id,
        AssemblyGpnLink.gpn_record_id).where(
            AssemblyGpnLink.assembly_definition_id.in_(identifiers))).all()) if identifiers else {}
    by_record = defaultdict(list)
    for row in assembly_rows:
        identity = row.get('gpn_id', row.get('id'))
        row['assembly_definition_id'] = identity
        row['gpn_record_id'] = links.get(identity)
        if row['gpn_record_id']:
            by_record[row['gpn_record_id']].append(row)
    query = select(GooglePartNumber).where(GooglePartNumber.project_id == project_id)
    if not include_removed:
        query = query.where(gpn_record_not_removed(GooglePartNumber.id))
    records = s.scalars(query.order_by(GooglePartNumber.gpn, GooglePartNumber.id)).all()
    states = removal_summaries(s, 'gpn_record', [record.id for record in records])
    return [{**_row(record, ('id', 'project_id', 'gpn', 'description', 'created_by', 'created_at', 'updated_at')),
             'removal': states[record.id],
             'assembly_definition_ids': [row['assembly_definition_id'] for row in by_record[record.id]],
             'assembly_count': len(by_record[record.id])} for record in records]


def create_gpn_record_value(s, order, data, user):
    existing = s.scalar(select(GooglePartNumber.id).where(
            GooglePartNumber.project_id == order.project_id,
            GooglePartNumber.normalized_gpn == _key(data.gpn)))
    if existing:
        from removals import gpn_record_is_removed
        if gpn_record_is_removed(s, existing):
            raise HTTPException(409, 'That GPN is in Removed records. Restore its existing record to retain its identity and linked history.')
        raise HTTPException(409, 'This GPN already has its own record in this P.O. Add another assembly under that GPN.')
    record = GooglePartNumber(id=new_id('GPN'), project_id=order.project_id,
        gpn=data.gpn, normalized_gpn=_key(data.gpn), description=data.description,
        created_by=user.badge)
    s.add(record)
    _flush(s)
    _event(s, order, user, 'GPN_RECORD_CREATED', after={
        'gpn_record_id': record.id, 'gpn': record.gpn, 'description': record.description})
    return record


def edit_gpn_record_value(s, order, record_id, data, user):
    from removals import require_active_gpn_record, gpn_record_is_removed
    record = s.get(GooglePartNumber, record_id)
    if record is None or record.project_id != order.project_id:
        raise HTTPException(404, 'GPN record not found in this P.O.')
    require_active_gpn_record(s, record.id)
    duplicate = s.scalar(select(GooglePartNumber.id).where(
        GooglePartNumber.project_id == order.project_id,
        GooglePartNumber.normalized_gpn == _key(data.gpn), GooglePartNumber.id != record.id))
    if duplicate:
        if gpn_record_is_removed(s, duplicate):
            raise HTTPException(409, 'That GPN is in Removed records. Restore its existing record to retain its identity and linked history.')
        raise HTTPException(409, 'That GPN already has a separate record. Choose its existing record; records are not silently merged.')
    groups = s.scalars(select(OrderGpn).join(AssemblyGpnLink,
        AssemblyGpnLink.assembly_definition_id == OrderGpn.id).where(
            AssemblyGpnLink.gpn_record_id == record.id)).all()
    before = {'gpn_record_id': record.id, 'gpn': record.gpn,
              'description': record.description,
              'assembly_definition_ids': [group.id for group in groups]}
    record.gpn, record.normalized_gpn = data.gpn, _key(data.gpn)
    record.description, record.updated_at = data.description, utcnow()
    # Current business labels may change; the retained GPN/document basis,
    # permanent physical IDs, BOMs, QR aliases and QA fingerprints stay intact.
    for group in groups:
        group.gpn_label, group.updated_at = data.gpn, utcnow()
    _event(s, order, user, 'GPN_RECORD_UPDATED', before=before,
        after={**before, 'gpn': record.gpn, 'description': record.description}, reason=data.reason)
    return record


def _assembly_number_key(value):
    return _key(value) or None


def _group_number_conflict(s, project_id, gpn, assembly_number, *, excluding=None):
    query = select(OrderGpn).where(OrderGpn.project_id == project_id)
    number = _assembly_number_key(assembly_number)
    if number is not None:
        query = query.where(OrderGpn.normalized_assembly_number == number)
    else:
        query = query.where(OrderGpn.normalized_assembly_number.is_(None),
                            OrderGpn.normalized_gpn == _key(gpn))
    if excluding is not None:
        query = query.where(OrderGpn.id != excluding)
    return s.scalar(query)


def _guard_group_number(s, project_id, gpn, assembly_number, *, excluding=None):
    _require_assembly_number(assembly_number)
    duplicate = _group_number_conflict(s, project_id, gpn, assembly_number, excluding=excluding)
    if duplicate is not None:
        from removals import gpn_is_removed
        label = 'Assembly Number'
        if gpn_is_removed(s, duplicate.id):
            raise HTTPException(409, f'That {label} is in Removed records. Restore its existing entry to retain its identity.')
        raise HTTPException(409, f'That {label} already exists in this P.O. Open its existing setup.')


def _set_assembly_number(group, value):
    group.assembly_number = value
    group.normalized_assembly_number = _assembly_number_key(value)


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
GPN_FIELDS = 'id project_id gpn gpn_label assembly_number description created_by created_at updated_at'.split()
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
                with read_projection(snapshot):
                    yield snapshot


def _locked(s, project_id, expected_version, user):
    from removals import require_active_project
    lock_topology(s)
    permit(user, 'admin', 'supervisor')
    require_active_project(s, project_id)
    row = s.scalar(select(PurchaseOrder).where(PurchaseOrder.project_id == project_id)
                   .with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, 'Purchase order not found')
    if row.version != expected_version:
        raise HTTPException(409, {'message': 'Purchase order changed; refresh and retry. No changes were saved.', 'current_version': row.version})
    return row


def _gpn(s, project_id, gpn_id):
    from removals import require_active_gpn
    group = s.get(OrderGpn, gpn_id)
    if group is None or group.project_id != project_id:
        raise HTTPException(422, 'Choose a GPN belonging to this purchase order')
    require_active_gpn(s, gpn_id)
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


def _linked(s, assembly_id, *, include_removed=True):
    from order_spools import effective_children
    return effective_children(s, assembly_id, include_removed=include_removed)


def order_scope(s, item_id):
    """Lightweight context for flow forms; does not calculate progress or write."""
    mapping = s.get(OrderAssembly, item_id)
    if mapping is None:
        from order_spools import effective_parent_id
        parent_id = effective_parent_id(s, item_id)
        mapping = s.get(OrderAssembly, parent_id) if parent_id else None
    if mapping is None:
        return None
    group = s.get(OrderGpn, mapping.gpn_id)
    order = s.get(PurchaseOrder, group.project_id)
    from removals import removal_summary
    return {'project_id': order.project_id, 'purchase_order': order.purchase_order,
            'gpn_id': group.id, 'gpn': group.gpn, 'assembly_id': mapping.item_id,
            'assembly_part_number': mapping.assembly_part_number, 'required_spools': mapping.required_spools,
            'removal': removal_summary(s, 'order', order.project_id)}


def guard_flow_scope(s, item_id, expected_children):
    mapping = s.get(OrderAssembly, item_id)
    if mapping and expected_children != mapping.required_spools:
        raise HTTPException(409, f'This purchase-order assembly requires {mapping.required_spools} spools. The traveler must use that same declared count; adjust the order before starting the traveler.')


def guard_plan_scope(s, item, oldplan, values):
    """Apply order boundaries to the existing planner, including old UI clients."""
    from removals import require_active_item, require_active_project, require_active_gpn
    require_active_item(s, item.id)
    require_active_project(s, values['project_id'])
    from order_spools import guard_registered_spool
    guard_registered_spool(s, item, values)
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
        require_active_gpn(s, group.id)
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
        require_active_gpn(s, group.id)
        if item.kind != 'Spool':
            raise HTTPException(422, 'Purchase-order assembly children must be registered as Spool items, not individual Parts or Assemblies')
        if values['project_id'] != group.project_id:
            raise HTTPException(409, 'Spool and purchase-order assembly must belong to the same project')
        other = len([child for child, _ in _linked(s, parent_id, include_removed=False) if child.id != item.id])
        if other >= parent.required_spools:
            raise HTTPException(409, f'This assembly already has its {parent.required_spools} required spools')
        from order_setup import guard_spool_requirement
        guard_spool_requirement(s, item, parent_id)


def guard_dossier_purchase_order(s, project_id, purchase_order):
    from removals import require_active_project
    require_active_project(s, project_id)
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
    linked = _linked(s, item.id, include_removed=False)
    if len(linked) > required_spools:
        raise HTTPException(409, 'Required spool count cannot be smaller than the existing linked spool count')
    if any(child.kind != 'Spool' or (child_plan.project_id if child_plan else child.project) != order.project_id
           for child, child_plan in linked):
        raise HTTPException(409, 'Every existing child must be a Spool item registered in this purchase-order project')
    traveler = s.get(FlowPlan, item.id)
    if traveler and (traveler.route != 'assembly' or traveler.expected_children != required_spools):
        raise HTTPException(409, 'Required spool count must match the existing assembly traveler; the order does not rewrite established production scope')


def _assembly_detail(s, mapping, group, progress_rows, *, presentation=False, presentations=None):
    from removals import removal_summary
    from spool_boms import item_bom_summary
    item = read_get(s, Item, mapping.item_id)
    item_removal = removal_summary(s, 'item', item.id)
    plan = read_get(s, SpoolPlan, item.id)
    flow = read_get(s, FlowPlan, item.id)
    spools = []
    blockers = []
    linked_rows = _linked(s, item.id, include_removed=bool(item_removal and item_removal['removed']))
    from spool_presentation import item_presentations
    displays = (presentations if presentations is not None else
                item_presentations(s, [child for child, _ in linked_rows])) if presentation else {}
    for child, child_plan in linked_rows:
        child_removal = removal_summary(s, 'item', child.id)
        child_flow = read_get(s, FlowPlan, child.id)
        row = progress_rows.get(child.id, {})
        errors = list(row.get('blockers', []))
        child_project = child_plan.project_id if child_plan else child.project
        if child.kind != 'Spool' or child_project != group.project_id:
            errors.append('Child identity or project does not match the purchase-order assembly')
        if child_plan is None:
            errors.append('Spool weld scope and drawing plan have not been set up')
        if child_flow is None:
            errors.append('Set up the purchase-order spool traveler before ordinary final QA release')
        errors = list(dict.fromkeys(errors))
        ready = bool(child.kind == 'Spool' and child_plan and child_flow and child_flow.route == 'spool'
                     and child_flow.status == 'completed' and row.get('fabrication_finished') and not errors)
        spools.append({'item_id': child.id, 'description': child.description, 'google_part_number': child.google_part_number,
                       **displays.get(child.id, {}),
                       'bom': item_bom_summary(child, s) if not (child_removal and child_removal['removed']) else None,
                       'removal': child_removal,
                       'project_id': child_project, 'subproject_id': child_plan.subproject_id if child_plan else None,
                       'planning_needed': child_plan is None, 'weld_plan_exists': child_plan is not None,
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
    return {**_row(mapping, ASSEMBLY_FIELDS), 'gpn': group.gpn, 'gpn_label': business_gpn(group),
            'assembly_number': group.assembly_number,
            'removal': item_removal,
            'description': item.description, 'google_part_number': item.google_part_number, 'drawing': item.drawing,
            'linked_spools': linked, 'missing_spools': max(0, mapping.required_spools - linked),
            'ready_spools': ready, 'not_ready_spools': linked - ready, 'planning_needed': plan is None,
            'flow_started': flow is not None, 'count_editable': flow is None and not item.released,
            'blockers': blockers, 'spools': spools}


def order_summary(s, order):
    from removals import gpn_not_removed, gpn_record_not_removed, item_not_removed, removal_summary
    project = s.get(Project, order.project_id)
    groups = s.scalars(select(OrderGpn).where(OrderGpn.project_id == order.project_id, gpn_not_removed(OrderGpn.id))).all()
    ids = [group.id for group in groups]
    mappings = s.scalars(select(OrderAssembly).where(OrderAssembly.gpn_id.in_(ids), item_not_removed(OrderAssembly.item_id))).all() if ids else []
    prime_projection(s, [row.item_id for row in mappings])
    linked_counts = {row.item_id: len(_linked(s, row.item_id, include_removed=False)) for row in mappings}
    linked = sum(linked_counts.values())
    required = sum(row.required_spools for row in mappings)
    setup_needed = len(groups) - len({row.gpn_id for row in mappings})
    canonical_count = s.scalar(select(func.count()).select_from(GooglePartNumber)
        .where(GooglePartNumber.project_id == order.project_id,
               gpn_record_not_removed(GooglePartNumber.id)))
    return {**_row(order, ORDER_FIELDS), 'project_name': project.name,
            'removal': removal_summary(s, 'order', order.project_id),
            'gpn_count': canonical_count or len({_key(business_gpn(group)) for group in groups}),
            'assembly_definition_count': len(groups), 'assembly_count': len(mappings),
            'combined_count': len(mappings) + setup_needed, 'setup_needed_count': setup_needed, 'required_spools': required,
            'linked_spools': linked, 'missing_spools': sum(max(0, row.required_spools - linked_counts[row.item_id]) for row in mappings)}


def order_detail(s, project_id, user=None):
    """Read-only detail also used by the Excel snapshot; no enrollment on read."""
    from progress import project_rows
    from removals import gpn_not_removed, item_not_removed, removal_summary
    from order_setup import requirements_by_gpn
    order = _order(s, project_id)
    removal = removal_summary(s, 'order', project_id)
    removed = bool(removal and removal['removed'])
    project = s.get(Project, project_id)
    group_query = select(OrderGpn).where(OrderGpn.project_id == project_id)
    if not removed:
        group_query = group_query.where(gpn_not_removed(OrderGpn.id))
    groups = s.scalars(group_query.order_by(OrderGpn.gpn)).all()
    quantity_plans = requirements_by_gpn(s, [group.id for group in groups])
    if user is not None:
        from spool_presentation import requirement_presentations
        displays = requirement_presentations(s, [line['id'] for plan in quantity_plans.values()
            for line in plan['spools']])
        quantity_plans = {identifier: {**plan, 'spools': [
            {**line, **displays.get(line['id'], {})} for line in plan['spools']]}
            for identifier, plan in quantity_plans.items()}
    progress_rows = {row['id']: row for row in project_rows(s, project_id)}
    group_ids = [group.id for group in groups]
    mapping_query = select(OrderAssembly).where(OrderAssembly.gpn_id.in_(group_ids))
    if not removed:
        mapping_query = mapping_query.where(item_not_removed(OrderAssembly.item_id))
    by_group = defaultdict(list)
    for mapping in s.scalars(mapping_query.order_by(OrderAssembly.item_id)) if group_ids else ():
        by_group[mapping.gpn_id].append(mapping)
    physical_counts = dict(s.execute(select(OrderAssembly.gpn_id, func.count())
        .where(OrderAssembly.gpn_id.in_(group_ids)).group_by(OrderAssembly.gpn_id)).all()) if group_ids else {}
    # All assembly rows share the same live physical-copy display calculation.
    # Computing station history per assembly creates another N+1 on large P.O.s.
    assembly_presentations = None
    if user is not None:
        from spool_presentation import item_presentations
        visible_children = {}
        for mappings in by_group.values():
            for mapping in mappings:
                state = removal_summary(s, 'item', mapping.item_id)
                for child, _ in _linked(s, mapping.item_id, include_removed=bool(state and state['removed'])):
                    visible_children[child.id] = child
        assembly_presentations = item_presentations(s, visible_children.values())
    gpns, assemblies = [], []
    for group in groups:
        mappings = by_group[group.id]
        children = [_assembly_detail(s, mapping, group, progress_rows,
                                    presentation=user is not None,
                                    presentations=assembly_presentations) for mapping in mappings]
        # A removed physical instance still owns its retained identity. Do not
        # offer a shared-number correction that would rewrite its history.
        physical_count = physical_counts.get(group.id, 0)
        group_removal = removal_summary(s, 'gpn', group.id)
        assembly_number_editable = not removed and not (group_removal and group_removal['removed'])
        for child in children:
            child['count_editable'] = child['count_editable'] and not removed and group.id not in quantity_plans
            child['number_editable'] = child['count_editable'] and physical_count == 1
            child['combined_number_matches'] = _key(child['assembly_part_number']) == group.normalized_gpn
            child['assembly_number_editable'] = assembly_number_editable
        gpns.append({**_row(group, GPN_FIELDS), 'gpn_label': business_gpn(group),
                     'assemblies': children, 'assembly_count': len(children),
                     'quantity_plan': quantity_plans.get(group.id),
                     'removal': group_removal, 'assembly_number_editable': assembly_number_editable,
                     **{key: sum(child[key] for child in children) for key in ('required_spools', 'linked_spools', 'missing_spools', 'ready_spools')}})
        assemblies.extend(children)
    available = []
    available_query = (select(Item, SpoolPlan)
        .outerjoin(SpoolPlan, SpoolPlan.item_id == Item.id)
        .outerjoin(OrderAssembly, OrderAssembly.item_id == Item.id)
        .where(Item.kind == 'Assembly', item_not_removed(Item.id), OrderAssembly.item_id.is_(None),
               or_(SpoolPlan.project_id == project_id,
                   and_(SpoolPlan.item_id.is_(None), Item.project == project_id)))
        .order_by(Item.id))
    for item, plan in s.execute(available_query) if not removed else ():
        available.append({'item_id': item.id, 'description': item.description, 'google_part_number': item.google_part_number,
                          'drawing': item.drawing, 'planned_welds': plan.planned_welds if plan else item.welds_required,
                          'planning_needed': plan is None})
    events = s.scalars(select(Audit).where(Audit.event.like('ORDER_%'), Audit.details['project_id'].as_string() == project_id)
                       .order_by(Audit.id.desc()).limit(100)).all()
    canonical_gpns = gpn_record_rows(s, project_id, gpns, include_removed=removed)
    parent_ids = {group['id']: group['gpn_record_id'] for group in gpns}
    for assembly in assemblies:
        assembly['assembly_definition_id'] = assembly['gpn_id']
        assembly['gpn_record_id'] = parent_ids.get(assembly['gpn_id'])
    return {'order': {**_row(order, ORDER_FIELDS), 'project_name': project.name, 'removal': removal}, 'gpns': gpns, 'assemblies': assemblies,
            'gpn_records': canonical_gpns,
            'totals': {'gpn_count': len(canonical_gpns) or len({_key(group['gpn_label']) for group in gpns}), 'assembly_count': len(assemblies),
                       'combined_count': len(assemblies) + sum(not g['assemblies'] for g in gpns),
                       'setup_needed_count': sum(not g['assemblies'] for g in gpns),
                       **{key: sum(row[key] for row in assemblies) for key in ('required_spools', 'linked_spools', 'missing_spools', 'ready_spools', 'not_ready_spools')}},
            'available_assemblies': [] if removed else available,
            'permissions': {'can_manage': bool(not removed and user and has_capability(user, 'manage_production')),
                            'can_remove': getattr(user, 'role', user) == 'admin' and not removed},
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
    from removals import project_not_removed
    orders = s.scalars(select(PurchaseOrder).where(project_not_removed(PurchaseOrder.project_id))
                       .order_by(PurchaseOrder.purchase_order, PurchaseOrder.project_id)).all()
    assigned = set(s.scalars(select(PurchaseOrder.project_id)))
    return {'orders': [order_summary(s, row) for row in orders],
            'unassigned_projects': [_row(row, ('id', 'name', 'client')) for row in s.scalars(select(Project)
                .where(project_not_removed(Project.id)).order_by(Project.name)) if row.id not in assigned],
            'permissions': {'can_manage': has_capability(user, 'manage_production'),
                            'can_remove': getattr(user, 'role', user) == 'admin'}}


@router.post('', status_code=201)
def create_order(data: CreateOrderIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    from removals import require_active_project, project_is_removed
    lock_topology(s)
    permit(user, 'admin', 'supervisor')
    if data.existing_project_id:
        require_active_project(s, data.existing_project_id)
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
        if project_is_removed(s, duplicate.project_id):
            raise HTTPException(409, 'That PO is in Removed records. Restore it to use the same PO number; its history and identity are retained.')
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
    _guard_group_number(s, project_id, data.gpn, data.assembly_number)
    group = OrderGpn(id=new_id('OGPN'), project_id=project_id, gpn=data.gpn, normalized_gpn=_key(data.gpn),
                     description=data.description, created_by=user.badge)
    _set_assembly_number(group, data.assembly_number)
    s.add(group)
    _flush(s)
    sync_gpn_record(s, group)
    _event(s, row, user, 'GPN_CREATED', after=_row(group, GPN_FIELDS))
    _commit(s)
    return order_detail(s, project_id, user)


@router.patch('/{project_id}/gpns/{gpn_id}')
def edit_gpn(project_id: str, gpn_id: str, data: EditGpnIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    row = _locked(s, project_id, data.expected_version, user)
    group = _gpn(s, project_id, gpn_id)
    assembly_number = _require_assembly_number(
        group.assembly_number if data.assembly_number is None else data.assembly_number)
    from spool_documents import guard_document_requirement_identity
    guard_document_requirement_identity(s, group, gpn=data.gpn)
    if data.gpn != group.gpn:
        from order_setup import OrderAssemblyRequirement
        if s.get(OrderAssemblyRequirement, group.id):
            raise HTTPException(409, 'Correct this Google part number from P.O. setup before registering its physical assemblies')
        for mapping in s.scalars(select(OrderAssembly).where(OrderAssembly.gpn_id == group.id)):
            item = lock_item(s, mapping.item_id)
            if item.released or s.get(FlowPlan, item.id):
                raise HTTPException(409, 'Correct the GPN before its assemblies enter a traveler or receive final release')
    before = _row(group, GPN_FIELDS)
    _guard_group_number(s, project_id, data.gpn, assembly_number, excluding=group.id)
    group.gpn, group.normalized_gpn, group.description = data.gpn, _key(data.gpn), data.description
    _set_assembly_number(group, assembly_number)
    group.updated_at = utcnow()
    sync_gpn_record(s, group)
    _event(s, row, user, 'GPN_UPDATED', before=before, after=_row(group, GPN_FIELDS), reason=data.reason)
    _commit(s)
    return order_detail(s, project_id, user)


@router.post('/{project_id}/gpn-records', status_code=201)
def create_gpn_record(project_id: str, data: CreateGpnRecordIn,
                      user: Employee = Depends(auth), s: Session = Depends(db)):
    order = _locked(s, project_id, data.expected_version, user)
    record = create_gpn_record_value(s, order, data, user)
    _commit(s)
    return {**order_detail(s, project_id, user), 'saved_gpn_record_id': record.id}


@router.patch('/{project_id}/gpn-records/{gpn_record_id}')
def edit_gpn_record(project_id: str, gpn_record_id: str, data: EditGpnRecordIn,
                    user: Employee = Depends(auth), s: Session = Depends(db)):
    order = _locked(s, project_id, data.expected_version, user)
    record = edit_gpn_record_value(s, order, gpn_record_id, data, user)
    _commit(s)
    return {**order_detail(s, project_id, user), 'saved_gpn_record_id': record.id}


@router.post('/{project_id}/assemblies', status_code=201)
def create_assembly(project_id: str, data: CreateAssemblyIn, user: Employee = Depends(auth), s: Session = Depends(db)):
    from administration import employee_is_removed
    from order_setup import guard_assembly_registration, OrderAssemblyRequirement
    row = _locked(s, project_id, data.expected_version, user)
    group = _gpn(s, project_id, data.gpn_id)
    _require_assembly_number(group.assembly_number)
    if data.assembly_number is not None and data.assembly_number != group.assembly_number:
        raise HTTPException(409, 'The Assembly Number must match the selected setup. '
            'Edit its Assembly Number separately before registration.')
    guard_assembly_registration(s, group, data.required_spools, item_id=data.item_id)
    if s.get(OrderAssemblyRequirement, group.id) and _key(data.assembly_part_number) != group.normalized_gpn:
        raise HTTPException(409, 'The assembly part number must match the planned Google part number / assembly number')
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
    if s.get(OrderAssemblyRequirement, group.id) and _key(item.google_part_number) != group.normalized_gpn:
        raise HTTPException(409, 'The physical assembly Google part number must match the planned assembly number')
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
    from order_setup import guard_assembly_registration, OrderAssemblyRequirement
    row = _locked(s, project_id, data.expected_version, user)
    mapping = _assembly(s, project_id, item_id)
    group = _gpn(s, project_id, mapping.gpn_id)
    _require_assembly_number(group.assembly_number)
    guard_assembly_registration(s, group, data.required_spools, item_id=item_id)
    if s.get(OrderAssemblyRequirement, group.id) and _key(data.assembly_part_number) != group.normalized_gpn:
        raise HTTPException(409, 'The assembly part number must match the planned Google part number / assembly number')
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


def _selected_assembly_detail(s, project_id, user, gpn_id, item_id):
    return {**order_detail(s, project_id, user),
            'selected_gpn_id': gpn_id, 'selected_assembly_id': item_id}


@router.post('/{project_id}/gpn-assemblies', status_code=201)
def create_combined_assembly(project_id: str, data: CreateCombinedAssemblyIn,
                             user: Employee = Depends(auth), s: Session = Depends(db)):
    """Create the GPN and its physical assembly as one versioned transaction."""
    from administration import employee_is_removed
    from order_setup import guard_assembly_registration, OrderAssemblyRequirement
    from removals import require_active_gpn
    order = _locked(s, project_id, data.expected_version, user)
    if data.gpn_id:
        group = _gpn(s, project_id, data.gpn_id)
        _require_assembly_number(group.assembly_number)
        if group.normalized_gpn != _key(data.gpn):
            raise HTTPException(409, 'The GPN must match the existing entry being completed')
        if data.assembly_number != group.assembly_number:
            raise HTTPException(409, 'The Assembly Number must match the selected setup. Edit its Assembly Number separately before registration.')
    else:
        group = _group_number_conflict(s, project_id, data.gpn, data.assembly_number)
        if group:
            _require_assembly_number(group.assembly_number)
            require_active_gpn(s, group.id)
            if group.normalized_gpn != _key(data.gpn):
                raise HTTPException(409, 'That Assembly Number already has a different GPN. Open its existing setup.')
    previous_group = _row(group, GPN_FIELDS) if group else None
    if group and not s.get(OrderAssemblyRequirement, group.id) and s.scalar(select(OrderAssembly.item_id).where(OrderAssembly.gpn_id == group.id).limit(1)):
        raise HTTPException(409, 'That GPN / assembly already exists in this P.O. Open its existing spool list instead of creating a duplicate.')
    if group is None:
        _guard_group_number(s, project_id, data.gpn, data.assembly_number)
        group = OrderGpn(id=new_id('OGPN'), project_id=project_id, gpn=data.gpn,
                         normalized_gpn=_key(data.gpn), description='', created_by=user.badge)
        _set_assembly_number(group, data.assembly_number)
        s.add(group)
        _flush(s)

    sync_gpn_record(s, group)

    if data.create_item is not None:
        new_item_id = data.create_item.id or new_id('ASM')
        if s.get(Item, new_item_id):
            raise HTTPException(409, 'That physical item ID already exists; select the existing assembly option or another QR ID')
        employee = s.get(Employee, data.create_item.handler)
        if not employee or not employee.active or employee_is_removed(s, employee.badge):
            raise HTTPException(422, 'Choose an active employee handler badge')
        values = {'id': new_item_id, 'description': '', 'google_part_number': group.gpn,
                  'drawing': data.create_item.drawing, 'location': data.create_item.location,
                  'handler': data.create_item.handler, 'welds_required': 0,
                  'kind': 'Assembly', 'project': project_id}
        item = Item(**values)
        s.add(item)
        _flush(s)
        audit(s, item.id, user.badge, 'ITEM_CREATED', {**values, 'source': 'combined_gpn_assembly'})
    else:
        item = lock_item(s, data.item_id)
    if s.get(OrderAssembly, item.id):
        raise HTTPException(409, 'This physical assembly already belongs to a GPN / assembly entry')
    if s.get(OrderAssemblyRequirement, group.id) and _key(item.google_part_number) != group.normalized_gpn:
        raise HTTPException(409, 'The physical assembly Google part number must match the planned assembly number')
    guard_assembly_registration(s, group, data.required_spools, item_id=item.id)
    _validate_assembly_scope(s, order, item, data.required_spools)
    mapping = OrderAssembly(item_id=item.id, gpn_id=group.id, assembly_part_number=group.gpn,
                            required_spools=data.required_spools, notes=data.notes, created_by=user.badge)
    s.add(mapping)
    _flush(s)
    _event(s, order, user, 'GPN_ASSEMBLY_CREATED',
           before={'gpn': previous_group, 'assembly': None},
           after={'gpn': _row(group, GPN_FIELDS), 'assembly': _row(mapping, ASSEMBLY_FIELDS),
                  'physical_item_created': data.create_item is not None}, item_id=item.id)
    _commit(s)
    return _selected_assembly_detail(s, project_id, user, group.id, item.id)


@router.patch('/{project_id}/gpn-assemblies/{item_id}')
def edit_combined_assembly(project_id: str, item_id: str, data: EditCombinedAssemblyIn,
                           user: Employee = Depends(auth), s: Session = Depends(db)):
    """Edit independent assembly metadata while retaining physical GPN guards."""
    from order_setup import guard_assembly_registration, OrderAssemblyRequirement
    order = _locked(s, project_id, data.expected_version, user)
    mapping = _assembly(s, project_id, item_id)
    group = _gpn(s, project_id, mapping.gpn_id)
    assembly_number = _require_assembly_number(
        group.assembly_number if data.assembly_number is None else data.assembly_number)
    from spool_documents import guard_document_requirement_identity
    guard_document_requirement_identity(s, group, gpn=data.gpn)
    item = lock_item(s, item_id)
    number_changed = data.gpn != group.gpn
    guard_assembly_registration(s, group, data.required_spools, item_id=item_id)
    if number_changed and s.get(OrderAssemblyRequirement, group.id):
        raise HTTPException(409, 'This planned assembly number is locked by registered physical records; its P.O. setup and identities are preserved')
    if number_changed or data.required_spools != mapping.required_spools:
        if item.released or s.get(FlowPlan, item.id):
            raise HTTPException(409, 'Correct the GPN / assembly number and required spool count before starting its traveler or releasing the assembly')
    if number_changed:
        if s.scalar(select(OrderAssembly.item_id).where(OrderAssembly.gpn_id == group.id,
                                                        OrderAssembly.item_id != item.id).limit(1)):
            raise HTTPException(409, 'This existing GPN is shared by multiple physical assemblies. Its number cannot be changed from one assembly record.')
    _guard_group_number(s, project_id, data.gpn, assembly_number, excluding=group.id)
    _validate_assembly_scope(s, order, item, data.required_spools)
    before = {'gpn': _row(group, GPN_FIELDS), 'assembly': _row(mapping, ASSEMBLY_FIELDS),
              'physical_part_number': item.google_part_number}
    if number_changed:
        old_key = group.normalized_gpn
        group.gpn, group.normalized_gpn = data.gpn, _key(data.gpn)
        group.updated_at = utcnow()
        mapping.assembly_part_number = data.gpn
        if not item.google_part_number or _key(item.google_part_number) == old_key:
            item.google_part_number = data.gpn
    if assembly_number != group.assembly_number:
        _set_assembly_number(group, assembly_number)
        group.updated_at = utcnow()
    mapping.required_spools, mapping.notes = data.required_spools, data.notes
    mapping.updated_at = utcnow()
    sync_gpn_record(s, group)
    _event(s, order, user, 'GPN_ASSEMBLY_UPDATED', before=before,
           after={'gpn': _row(group, GPN_FIELDS), 'assembly': _row(mapping, ASSEMBLY_FIELDS),
                  'physical_part_number': item.google_part_number},
           reason=data.reason, item_id=item.id)
    _commit(s)
    return _selected_assembly_detail(s, project_id, user, group.id, item.id)

