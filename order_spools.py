"""Physical PO spool identities and explicitly declared weld counts.

Registration fixes the saved spool requirement and exact physical assembly.
Declared counts initialize empty individual welds with pending QA requirements;
production travelers, collection events and acceptance are never inferred.
Legacy children retain their identity and existing plans and work.
"""
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import (CheckConstraint, Column, DateTime, ForeignKey, Integer,
                        String, UniqueConstraint, and_, exists, func, or_, select, text)
from read_projection import read_cached

from main import Base, Item, audit, utcnow
from tracking import SpoolPlan


WELD_GENERATION_LIMIT = 2000
SPOOL_INITIALIZATION_LIMIT = 500


class OrderSpool(Base):
    __tablename__ = 'order_spools'
    item_id = Column(String(60), ForeignKey('items.id'), primary_key=True)
    assembly_id = Column(String(60), ForeignKey('order_assemblies.item_id'), nullable=False, index=True)
    requirement_id = Column(String(60), ForeignKey('order_spool_requirements.id'), nullable=False, index=True)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class SpoolQrIdentity(Base):
    """Permanent human-readable label; Item.id remains the traceability key.

    Numbering is global per normalized spool number, including removed items.
    These rows are append-only history and must never be recycled or reranked.
    """
    __tablename__ = 'spool_qr_identities'
    __table_args__ = (
        UniqueConstraint('normalized_number', 'sequence', name='uq_spool_qr_number_sequence'),
        CheckConstraint('sequence > 0', name='ck_spool_qr_sequence_positive'),
    )
    item_id = Column(String(60), ForeignKey('items.id'), primary_key=True)
    spool_number = Column(String(160), nullable=False)
    normalized_number = Column(String(480), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    display_code = Column(String(180), nullable=False, unique=True)
    normalized_code = Column(String(540), nullable=False, unique=True)
    # Like Audit.actor, migration provenance does not fabricate an employee.
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    source = Column(String(80), nullable=False)


def _qr_number(value):
    return ' '.join((value or '').split())


def _qr_key(value):
    return _qr_number(value).casefold()


def _lock_qr_allocation(s):
    """Use the same transaction lock and ordering as every physical writer."""
    transaction = s.get_transaction()
    if transaction is not None and s.info.get('spool_qr_lock_transaction') is transaction:
        return
    if s.get_bind().dialect.name == 'postgresql':
        from flow import TOPOLOGY_LOCK
        with s.no_autoflush:
            s.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': TOPOLOGY_LOCK})
    # This is a lock marker only, not a cache of mutable identity/receipt data.
    s.info['spool_qr_lock_transaction'] = s.get_transaction()


def spool_qr_identity(s, item_id):
    """Read a stored identity without allocating or changing inventory."""
    return s.get(SpoolQrIdentity, item_id)


def resolve_spool_qr_identity(s, code):
    """Resolve a complete alias; do not guess a spool from its base number."""
    normalized = _qr_key(code)
    if not normalized or len(normalized) > 540:
        return None
    return s.scalar(select(SpoolQrIdentity).where(
        SpoolQrIdentity.normalized_code == normalized))


def guard_spool_qr_number(s, item):
    identity = spool_qr_identity(s, item.id)
    if identity and _qr_key(item.google_part_number) != identity.normalized_number:
        raise HTTPException(409, 'This physical spool has a permanent QR identity. '
            'Its spool number cannot be changed after the label is assigned.')


def ensure_spool_qr_identity(s, item, actor, source='item_create'):
    """Allocate once in the caller's transaction; never commit or rename Item.

    An actual spool number is required. Legacy blank numbers keep their old
    ID/QR until a real number is entered; components and assemblies stay as-is.
    """
    _lock_qr_allocation(s)
    prior = spool_qr_identity(s, item.id)
    if prior is not None:
        return prior
    if item.kind == 'Assembly':
        return None
    if item.kind != 'Spool' and not (s.get(SpoolPlan, item.id) or s.get(OrderSpool, item.id)):
        return None
    number = _qr_number(item.google_part_number)
    if not number:
        return None
    normalized = _qr_key(number)
    last = s.scalar(select(func.max(SpoolQrIdentity.sequence)).where(
        SpoolQrIdentity.normalized_number == normalized)) or 0
    sequence = last + 1
    if sequence > 2147483647:
        raise HTTPException(409, 'The spool QR sequence is exhausted; no identity was created.')
    code = f'{number}-[{sequence:03d}]'
    identity = SpoolQrIdentity(item_id=item.id, spool_number=number,
        normalized_number=normalized, sequence=sequence, display_code=code,
        normalized_code=_qr_key(code), created_by=actor, source=source)
    s.add(identity)
    audit(s, item.id, actor, 'SPOOL_QR_IDENTITY_ASSIGNED', {
        'item_id': item.id, 'spool_number': number, 'sequence': sequence,
        'display_code': code, 'source': source, 'legacy_item_id': item.id})
    s.flush()
    return identity


def backfill_spool_qr_identities(s, actor='system:spool-qr-backfill'):
    """Deterministically append aliases to legacy physical records, in batches.

    Include removed identities so their sequence numbers remain reserved.
    Re-running initialization never alters existing rows, labels or item data.
    """
    _lock_qr_allocation(s)
    physical = or_(Item.kind == 'Spool', and_(Item.kind != 'Assembly', or_(
        exists().where(SpoolPlan.item_id == Item.id),
        exists().where(OrderSpool.item_id == Item.id))))
    missing = ~exists().where(SpoolQrIdentity.item_id == Item.id)
    created, missing_number, cursor = 0, 0, None
    while True:
        query = select(Item).where(physical, missing)
        if cursor is not None:
            at, item_id = cursor
            query = query.where(or_(Item.created_at > at,
                and_(Item.created_at == at, Item.id > item_id)))
        rows = s.scalars(query.order_by(Item.created_at, Item.id).limit(500)).all()
        if not rows:
            break
        for item in rows:
            if ensure_spool_qr_identity(s, item, actor, source='startup_backfill') is None:
                missing_number += 1
            else:
                created += 1
        cursor = (rows[-1].created_at, rows[-1].id)
    return {'created': created, 'missing_spool_number': missing_number}


@read_cached(lambda s, item_id: item_id)
def registered_spool(s, item_id):
    return s.get(OrderSpool, item_id)


@read_cached(lambda s, item_id: item_id)
def effective_parent_id(s, item_id):
    registration = registered_spool(s, item_id)
    if registration:
        return registration.assembly_id
    plan = s.get(SpoolPlan, item_id)
    return plan.assembly_id if plan else None


def effective_children_by_assembly(s, assembly_ids, *, include_removed=True):
    """Read the union once; a registered child with a plan appears only once.

    Kept removal history is included by default, matching the existing planning
    and removal relationship readers. Active label/count callers opt out.
    """
    ids = set(assembly_ids)
    children = defaultdict(dict)
    if not ids:
        return {}
    query = (select(Item, SpoolPlan, OrderSpool)
        .outerjoin(SpoolPlan, SpoolPlan.item_id == Item.id)
        .outerjoin(OrderSpool, OrderSpool.item_id == Item.id)
        .where(or_(SpoolPlan.assembly_id.in_(ids), OrderSpool.assembly_id.in_(ids)))
        .order_by(Item.id))
    if not include_removed:
        from removals import item_not_removed
        query = query.where(item_not_removed(Item.id))
    for item, plan, registration in s.execute(query):
        parents = {value for value in (
            plan.assembly_id if plan else None,
            registration.assembly_id if registration else None,
        ) if value in ids}
        for parent_id in parents:
            children[parent_id][item.id] = (item, plan)
    return {parent_id: list(rows.values()) for parent_id, rows in children.items()}


@read_cached(lambda s, assembly_id, *, include_removed=True: (assembly_id, include_removed))
def effective_children(s, assembly_id, *, include_removed=True):
    return effective_children_by_assembly(s, [assembly_id],
        include_removed=include_removed).get(assembly_id, [])


def effective_child_ids(s, assembly_id, *, include_removed=True):
    return [item.id for item, _ in effective_children(s, assembly_id,
        include_removed=include_removed)]


def pending_declared_spools(s, project_id, plans):
    """Validate all selected retained scope before selecting a bounded batch."""
    from orders import OrderAssembly, _key
    from removals import item_not_removed
    from tracking import validate_order_weld_scope
    parents = s.execute(select(OrderAssembly, Item)
        .join(Item, Item.id == OrderAssembly.item_id)
        .where(OrderAssembly.gpn_id.in_(plans), item_not_removed(Item.id))
        .order_by(OrderAssembly.gpn_id, Item.created_at, Item.id)).all()
    children = effective_children_by_assembly(s, [mapping.item_id for mapping, _ in parents],
                                              include_removed=False)
    pending = []
    for mapping, parent in parents:
        requirements = {_key(line['spool_number']): line for line in plans[mapping.gpn_id]['spools']}
        for item, plan in children.get(parent.id, []):
            line = requirements.get(_key(item.google_part_number or ''))
            if line is None or line['welds_per_spool'] is None:
                continue
            guard_registered_spool(s, item)
            if item.kind != 'Spool' or item.project != project_id:
                raise HTTPException(409, f'Spool {item.id} has conflicting purchase-order scope. Review the existing record before declaring welds.')
            if validate_order_weld_scope(s, item, project_id, parent.id, line['welds_per_spool']):
                if parent.released:
                    raise HTTPException(409, 'Return the released purchase-order assembly to work before declaring missing child weld records.')
                pending.append((item, parent.id, line))
    return pending


def initialize_declared_spools(s, project_id, pending, actor, *, weld_limit=None):
    """Initialize a batch, leaving further declared spools for generation."""
    from tracking import initialize_order_weld_scope
    if weld_limit is None:
        weld_limit = WELD_GENERATION_LIMIT
    initialized, welds = [], 0
    for item, parent_id, line in pending:
        count = line['welds_per_spool']
        if len(initialized) >= SPOOL_INITIALIZATION_LIMIT or welds + count > weld_limit:
            break
        welds += initialize_order_weld_scope(s, item, project_id, parent_id, count, actor)
        initialized.append(item.id)
    return initialized, welds


def guard_registered_spool(s, item, values=None):
    """Keep generated identity, PO and intended parent fixed in every writer."""
    registration = registered_spool(s, item.id)
    if registration is None:
        return
    from orders import OrderAssembly, OrderGpn, _key
    from order_setup import OrderSpoolRequirement
    from removals import require_active_item, require_active_gpn
    mapping = s.get(OrderAssembly, registration.assembly_id)
    requirement = s.get(OrderSpoolRequirement, registration.requirement_id)
    if mapping is None or requirement is None or requirement.gpn_id != mapping.gpn_id or not requirement.active:
        raise HTTPException(409, 'This registered spool does not match an active requirement in its purchase-order assembly.')
    group = s.get(OrderGpn, mapping.gpn_id)
    require_active_gpn(s, mapping.gpn_id)
    require_active_item(s, mapping.item_id)
    if item.kind != 'Spool' or _key(item.google_part_number or '') != requirement.normalized_number:
        raise HTTPException(409, 'The registered physical spool part number must match its saved purchase-order spool requirement.')
    if item.project != group.project_id:
        raise HTTPException(409, 'This registered spool must remain in its purchase-order project.')
    plan = s.get(SpoolPlan, item.id)
    if plan and (plan.project_id != group.project_id or plan.assembly_id != registration.assembly_id):
        raise HTTPException(409, 'This registered spool has conflicting weld-plan scope. Correct the retained scope before changing its work.')
    if values is not None and (values.get('project_id') != group.project_id or
                               values.get('assembly_id') != registration.assembly_id):
        raise HTTPException(409, 'This registered spool must retain its exact purchase-order assembly and project when declaring its weld plan.')

