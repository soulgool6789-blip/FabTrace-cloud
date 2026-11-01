"""Bounded read-only batches for the records a response already needs.

These maps exist only inside read_projection. They never authorize writes and
never outlive the request. Missing rows are explicit, so an empty relationship
does not cause a separate database trip for every helper and every spool.
"""
from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.orm import undefer

from read_projection import (PROJECTION_MISSING, prime_rows, projection_enabled,
                             projection_get, projection_put, read_get)


def _chunks(values):
    values = list(values)
    for start in range(0, len(values), 400):
        yield values[start:start + 400]


def _remember(s, model, key, row):
    projection_put(s, ('row', model), key, row)


def _group(rows, key):
    result = defaultdict(list)
    for row in rows:
        result[getattr(row, key)].append(row)
    return result


def _removals(s, kind, identifiers):
    from removals import RecordRemoval
    missing = [key for key in set(identifiers) if key and
               projection_get(s, 'removal_state', (kind, key)) is PROJECTION_MISSING]
    for batch in _chunks(missing):
        rows = {row.record_id: row for row in s.scalars(select(RecordRemoval).where(
            RecordRemoval.kind == kind, RecordRemoval.record_id.in_(batch))
            .execution_options(populate_existing=True))}
        for key in batch:
            projection_put(s, 'removal_state', (kind, key), rows.get(key))


def _document_sets(s, spool_ids, requirement_ids):
    from spool_documents import SpoolDocumentSet
    wanted = {('spools', key) for key in spool_ids} | {('requirements', key) for key in requirement_ids}
    missing = [key for key in wanted if projection_get(s, 'document_set', key) is PROJECTION_MISSING]
    for batch in _chunks(missing):
        rows = s.scalars(select(SpoolDocumentSet).where(or_(
            SpoolDocumentSet.spool_id.in_([key for kind, key in batch if kind == 'spools']),
            SpoolDocumentSet.requirement_id.in_([key for kind, key in batch if kind == 'requirements']))))
        found = {('requirements', row.requirement_id) if row.requirement_id else ('spools', row.spool_id): row
                 for row in rows}
        for key in batch:
            projection_put(s, 'document_set', key, found.get(key))
    return {row.id for key in wanted if (row := projection_get(s, 'document_set', key)) is not None}


def _document_rows(s, set_ids):
    from spool_documents import SpoolDocument
    missing = [key for key in set_ids if projection_get(s, 'document_rows', key) is PROJECTION_MISSING]
    for batch in _chunks(missing):
        ranked = select(SpoolDocument.id,
            func.row_number().over(partition_by=SpoolDocument.set_id,
                order_by=SpoolDocument.version.desc()).label('recent'),
            func.row_number().over(partition_by=(SpoolDocument.set_id, SpoolDocument.kind),
                order_by=SpoolDocument.version.desc()).label('kind_recent'))
        ranked = ranked.where(SpoolDocument.set_id.in_(batch)).subquery()
        rows = s.scalars(select(SpoolDocument).join(ranked, ranked.c.id == SpoolDocument.id)
            .where(or_(ranked.c.recent <= 100, ranked.c.kind_recent == 1))
            .order_by(SpoolDocument.version.desc()))
        grouped = _group(rows, 'set_id')
        for key in batch:
            candidates = grouped[key]
            # Match _documents exactly: newest 100 first, followed by any
            # otherwise missing BOM/isometric in that established kind order.
            selected = candidates[:100]
            for kind in ('bom', 'isometric'):
                if not any(row.kind == kind for row in selected):
                    older = next((row for row in candidates if row.kind == kind), None)
                    if older is not None:
                        selected.append(older)
            projection_put(s, 'document_rows', key, selected)


def _receiving(s, spool_ids):
    from spool_boms import SpoolBomMaterial, SpoolBomTrace
    from spool_receiving import SpoolArrivalInspection, SpoolMaterialInspection, SpoolMtrDocument
    missing = [key for key in spool_ids if projection_get(s, 'receiving_primed', key) is PROJECTION_MISSING]
    prime_rows(s, SpoolBomTrace, SpoolBomTrace.spool_id, missing)
    for batch in _chunks(missing):
        materials = _group(s.scalars(select(SpoolBomMaterial).where(SpoolBomMaterial.spool_id.in_(batch))), 'spool_id')
        latest = select(SpoolArrivalInspection.spool_id,
            func.max(SpoolArrivalInspection.version).label('version')).where(
            SpoolArrivalInspection.spool_id.in_(batch)).group_by(SpoolArrivalInspection.spool_id).subquery()
        arrivals = {row.spool_id: row for row in s.scalars(select(SpoolArrivalInspection).join(latest,
            (SpoolArrivalInspection.spool_id == latest.c.spool_id) &
            (SpoolArrivalInspection.version == latest.c.version)).options(undefer(SpoolArrivalInspection.basis)))}
        latest = select(SpoolMaterialInspection.spool_id, SpoolMaterialInspection.piece_key,
            func.max(SpoolMaterialInspection.version).label('version')).where(
            SpoolMaterialInspection.spool_id.in_(batch)).group_by(
            SpoolMaterialInspection.spool_id, SpoolMaterialInspection.piece_key).subquery()
        decisions = _group(s.scalars(select(SpoolMaterialInspection).join(latest,
            (SpoolMaterialInspection.spool_id == latest.c.spool_id) &
            (SpoolMaterialInspection.piece_key == latest.c.piece_key) &
            (SpoolMaterialInspection.version == latest.c.version))), 'spool_id')
        latest_id = select(SpoolMaterialInspection.spool_id,
            func.max(SpoolMaterialInspection.id).label('id')).where(
            SpoolMaterialInspection.spool_id.in_(batch)).group_by(SpoolMaterialInspection.spool_id).subquery()
        last_piece = {row.spool_id: row for row in s.scalars(select(SpoolMaterialInspection).join(
            latest_id, SpoolMaterialInspection.id == latest_id.c.id).options(undefer(SpoolMaterialInspection.basis)))}
        latest = select(SpoolMtrDocument.spool_id, SpoolMtrDocument.reference_key,
            func.max(SpoolMtrDocument.version).label('version')).where(
            SpoolMtrDocument.spool_id.in_(batch)).group_by(
            SpoolMtrDocument.spool_id, SpoolMtrDocument.reference_key).subquery()
        mtrs = _group(s.scalars(select(SpoolMtrDocument).join(latest,
            (SpoolMtrDocument.spool_id == latest.c.spool_id) &
            (SpoolMtrDocument.reference_key == latest.c.reference_key) &
            (SpoolMtrDocument.version == latest.c.version)).order_by(SpoolMtrDocument.reference_key)), 'spool_id')
        first = select(SpoolMtrDocument.id, func.row_number().over(partition_by=SpoolMtrDocument.spool_id,
            order_by=(SpoolMtrDocument.uploaded_at, SpoolMtrDocument.id)).label('position')).where(
            SpoolMtrDocument.spool_id.in_(batch)).subquery()
        first_mtr = {row.spool_id: row for row in s.scalars(select(SpoolMtrDocument).join(
            first, SpoolMtrDocument.id == first.c.id).where(first.c.position == 1))}
        for key in batch:
            projection_put(s, 'bom_materials', key, materials[key])
            projection_put(s, 'latest_arrival', key, arrivals.get(key))
            projection_put(s, 'current_material_inspections', key, {row.piece_key: row for row in decisions[key]})
            projection_put(s, 'latest_material_inspection', key, last_piece.get(key))
            projection_put(s, 'current_mtrs', key, mtrs[key])
            projection_put(s, 'first_mtr', key, first_mtr.get(key))
            projection_put(s, 'receiving_primed', key, True)


def _holds(s, identifiers):
    from main import Rework
    from tracking import TrackingHold
    from flow import FlowException
    missing = [key for key in identifiers if projection_get(s, 'physical_holds', key) is PROJECTION_MISSING]
    for batch in _chunks(missing):
        reworks = set(s.scalars(select(Rework.item_id).where(Rework.item_id.in_(batch),
            Rework.closed_at.is_(None)).distinct()))
        holds = _group(s.scalars(select(TrackingHold).where(TrackingHold.item_id.in_(batch),
            TrackingHold.closed_at.is_(None))), 'item_id')
        exceptions = _group(s.scalars(select(FlowException).where(FlowException.item_id.in_(batch),
            FlowException.closed_at.is_(None)).order_by(FlowException.id)), 'item_id')
        for key in batch:
            projection_put(s, 'physical_holds', key, {'rework': key in reworks, 'tracking': holds[key]})
            projection_put(s, 'flow_open_exceptions', key, exceptions[key])


def _components(s, spool_ids):
    from flow import ComponentLink
    missing = [key for key in spool_ids if projection_get(s, 'component_ids', key) is PROJECTION_MISSING]
    for batch in _chunks(missing):
        rows = _group(s.scalars(select(ComponentLink).where(ComponentLink.spool_id.in_(batch))
            .order_by(ComponentLink.component_id)), 'spool_id')
        for key in batch:
            projection_put(s, 'component_ids', key, [row.component_id for row in rows[key]])
            for row in rows[key]:
                _remember(s, ComponentLink, row.component_id, row)


def prime_projection(s, items):
    if not projection_enabled(s):
        return
    from main import Item
    from flow import ComponentLink, FlowPlan
    from tracking import Project, SpoolPlan
    from parts import PartAllocation, PartLine, SpoolPartsPlan
    from order_spools import OrderSpool, SpoolQrIdentity, effective_children_by_assembly
    from orders import OrderAssembly, OrderGpn, PurchaseOrder
    from order_setup import OrderSpoolRequirement

    requested = set()
    for item in items:
        key = item if isinstance(item, str) else item.id
        requested.add(key)
        if not isinstance(item, str):
            _remember(s, Item, key, item)
    initial = prime_rows(s, Item, Item.id, requested)
    # Only visible assemblies need all children. Following a spool's parent
    # for identity checks must not eagerly load every sibling in its P.O.
    expand = {key for key, row in initial.items() if row and row.kind == 'Assembly'}
    expanded, children = set(), {}
    while expand:
        next_expand = set()
        for batch in _chunks(expand - expanded):
            missing = [key for key in batch if projection_get(s, 'assembly_children', (key, True)) is PROJECTION_MISSING]
            found = effective_children_by_assembly(s, missing, include_removed=True)
            for key in batch:
                known = projection_get(s, 'assembly_children', (key, True))
                values = found.get(key, []) if known is PROJECTION_MISSING else known
                children[key] = values
                projection_put(s, 'assembly_children', (key, True), values)
                for item, plan in values:
                    _remember(s, Item, item.id, item)
                    _remember(s, SpoolPlan, item.id, plan)
                    requested.add(item.id)
                    if item.kind == 'Assembly':
                        next_expand.add(item.id)
        expanded |= expand
        expand = next_expand - expanded

    pending, seen = set(requested), set()
    while pending:
        batch_ids = pending - seen
        if not batch_ids:
            break
        prime_rows(s, Item, Item.id, batch_ids)
        models = ((SpoolPlan, SpoolPlan.item_id), (OrderSpool, OrderSpool.item_id),
            (FlowPlan, FlowPlan.item_id), (OrderAssembly, OrderAssembly.item_id),
            (ComponentLink, ComponentLink.component_id), (PartAllocation, PartAllocation.component_id),
            (SpoolPartsPlan, SpoolPartsPlan.spool_id), (SpoolQrIdentity, SpoolQrIdentity.item_id))
        for model, column in models:
            prime_rows(s, model, column, batch_ids)
        allocations = [read_get(s, PartAllocation, key) for key in batch_ids]
        prime_rows(s, PartLine, PartLine.id, [row.line_id for row in allocations if row])
        parents = set()
        for key in batch_ids:
            for model, field in ((SpoolPlan, 'assembly_id'), (OrderSpool, 'assembly_id'), (ComponentLink, 'spool_id')):
                row = read_get(s, model, key)
                if row and getattr(row, field):
                    parents.add(getattr(row, field))
            allocation = read_get(s, PartAllocation, key)
            line = read_get(s, PartLine, allocation.line_id) if allocation else None
            if line:
                parents.add(line.spool_id)
        seen |= batch_ids
        pending = parents - seen

    registrations = [read_get(s, OrderSpool, key) for key in seen]
    requirement_ids = {row.requirement_id for row in registrations if row}
    requirements = prime_rows(s, OrderSpoolRequirement, OrderSpoolRequirement.id, requirement_ids)
    mappings = [read_get(s, OrderAssembly, key) for key in seen]
    group_ids = {row.gpn_id for row in mappings if row} | {row.gpn_id for row in requirements.values() if row}
    groups = prime_rows(s, OrderGpn, OrderGpn.id, group_ids)
    project_ids = {row.project_id for row in groups.values() if row}
    for key in seen:
        item, plan = read_get(s, Item, key), read_get(s, SpoolPlan, key)
        project_ids.update(value for value in (item.project if item else None, plan.project_id if plan else None) if value)
    prime_rows(s, Project, Project.id, project_ids)
    prime_rows(s, PurchaseOrder, PurchaseOrder.project_id, project_ids)
    _removals(s, 'item', seen)
    _removals(s, 'gpn', group_ids)
    _removals(s, 'order', project_ids)
    for key, values in children.items():
        active = [(item, plan) for item, plan in values
                  if not ((state := projection_get(s, 'removal_state', ('item', item.id))) and state.removed)]
        projection_put(s, 'assembly_children', (key, False), active)
    physical = {key for key in seen if (item := read_get(s, Item, key)) and item.kind != 'Assembly'
                and (item.kind == 'Spool' or read_get(s, SpoolPlan, key) or read_get(s, OrderSpool, key))}
    _receiving(s, physical)
    _document_rows(s, _document_sets(s, physical, requirement_ids))
    _holds(s, seen)
    _components(s, physical)
