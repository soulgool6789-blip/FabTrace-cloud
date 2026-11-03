"""Read-only proof that one generated spool is still an untouched setup copy.

This is a narrow exception to the normal linked-work removal blocker. It never
changes a requirement, physical relationship, document, weld or QA record.
Unknown provenance or activity keeps the existing blocker in force. Callers
must evaluate these facts again under the normal topology lock before writing.
"""
import datetime as dt
import hashlib
import json

from sqlalchemy import or_, select


def _json_value(value):
    if isinstance(value, dt.datetime):
        return (value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None
                else value.astimezone(dt.timezone.utc)).isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _values(row):
    return _json_value({column.name: getattr(row, column.name)
                        for column in row.__table__.columns}) if row is not None else None


def generated_copy_removal_facts(s, item_id):
    """Return stable JSON-safe eligibility and a current evidence fingerprint.

    ``eligible`` only relaxes individual removal of a registered child whose
    SpoolPlan was automatically initialized from its PO weld declaration. The
    parent remains outside the removal scope, but its state enters this digest
    so a parent-only change invalidates an earlier removal preview. Deliberate
    remove/restore audit entries do not turn untouched planning into work.
    """
    from main import Base, Item, Audit
    from orders import OrderAssembly, OrderGpn
    from order_setup import OrderSpoolRequirement, OrderSpoolWeldRequirement
    from order_spools import OrderSpool, SpoolQrIdentity
    from tracking import (SpoolPlan, Weld, WeldRequirement, RequirementIn,
                          _default_definitions)
    from spool_boms import (SpoolBomTrace, SpoolBomMaterial, SpoolBomEvent,
                           MATERIAL_FIELDS, _piece_definitions, _import_material_values)

    basis = {'schema': 'generated-copy-removal-v1', 'item_id': item_id}
    parent_id = None
    evidence_counts = {}

    def finish(eligible, reason):
        serial = json.dumps(_json_value(basis), sort_keys=True, separators=(',', ':'),
                            ensure_ascii=False)
        return {'eligible': eligible, 'reason': reason, 'item_id': item_id,
                'parent_id': parent_id, 'evidence_counts': evidence_counts,
                'fingerprint': hashlib.sha256(serial.encode('utf-8')).hexdigest()}

    item = s.get(Item, item_id)
    registration = s.get(OrderSpool, item_id)
    plan = s.get(SpoolPlan, item_id)
    basis.update(item=_values(item), registration=_values(registration), plan=_values(plan))
    if item is None or item.kind != 'Spool' or registration is None or plan is None:
        return finish(False, 'This is not a generated spool copy with an initial PO weld plan.')

    parent_id = registration.assembly_id
    parent = s.get(Item, parent_id)
    mapping = s.get(OrderAssembly, parent_id)
    line = s.get(OrderSpoolRequirement, registration.requirement_id)
    declaration = s.get(OrderSpoolWeldRequirement, registration.requirement_id)
    group = s.get(OrderGpn, mapping.gpn_id) if mapping else None
    qr = s.get(SpoolQrIdentity, item_id)
    basis.update(parent=_values(parent), mapping=_values(mapping), requirement=_values(line),
                 declaration=_values(declaration), group=_values(group), qr=_values(qr))
    if (parent is None or parent.kind != 'Assembly' or mapping is None or group is None
            or line is None or not line.active or declaration is None
            or line.gpn_id != mapping.gpn_id or plan.assembly_id != parent_id
            or plan.project_id != group.project_id or item.project != group.project_id
            or parent.project != group.project_id or item.google_part_number != line.spool_number
            or plan.planned_welds != declaration.welds_per_spool
            or item.welds_required != plan.planned_welds
            or qr is None or qr.spool_number != line.spool_number):
        return finish(False, 'The generated copy no longer matches its exact saved PO scope.')

    identities = (item_id, parent_id)
    audit_rows = list(s.scalars(select(Audit).where(Audit.item_id.in_(identities)).order_by(Audit.id)))
    basis['audit'] = [_values(row) for row in audit_rows]
    own_audit = [row for row in audit_rows if row.item_id == item_id]
    parent_audit = [row for row in audit_rows if row.item_id == parent_id]
    creations = [row for row in own_audit if row.event == 'ITEM_CREATED']
    plans = [row for row in own_audit if row.event == 'TRACKING_PLAN_SAVED']
    if (len(creations) != 1 or creations[0].details.get('source') != 'purchase_order_labels'
            or creations[0].details.get('assembly_id') != parent_id
            or creations[0].details.get('requirement_id') != line.id
            or len(plans) != 1 or plans[0].details.get('source') != 'purchase_order_weld_count'
            or plans[0].details.get('before') is not None):
        return finish(False, 'Only the original automatically generated PO plan is eligible.')
    creation = creations[0].details
    if any(getattr(item, name) != creation.get(name) for name in (
            'id', 'kind', 'project', 'google_part_number', 'description', 'drawing', 'handler', 'location')):
        return finish(False, 'The physical copy has been changed since setup.')
    initial_plan = plans[0].details.get('after') or {}
    if (plan.version != 1 or plan.subproject_id is not None or plan.due_date is not None
            or any(getattr(plan, key) != initial_plan.get(key) for key in (
                'project_id', 'assembly_id', 'planned_welds', 'drawing_revision', 'notes', 'zero_weld_reason'))
            or plan.drawing_revision or plan.notes
            or plan.zero_weld_reason != ('Zero welds explicitly declared in purchase-order spool setup.'
                                        if plan.planned_welds == 0 else '')):
        return finish(False, 'The initial generated weld plan has been edited.')

    def has_item_activity(row):
        return (row.welds_done or row.last_work_at or row.dimension_at or row.weld_at
                or row.dimensional != 'Not started' or row.weld != 'Not started'
                or row.on_hold or row.released or row.released_at or row.released_by)

    if has_item_activity(item) or has_item_activity(parent) or parent.welds_required or parent.reinspection_due:
        return finish(False, 'The spool or its parent assembly has production, hold or QA state.')

    own_allowed = {'ITEM_CREATED', 'SPOOL_QR_IDENTITY_ASSIGNED', 'TRACKING_PLAN_SAVED',
                   'TRACKING_WELD_CREATED', 'SPOOL_MATERIAL_PIECES_INITIALIZED',
                   'RECORD_REMOVED', 'RECORD_RESTORED'}
    parent_allowed = {'ITEM_CREATED', 'RECORD_REMOVED', 'RECORD_RESTORED'}
    if (any(row.event not in own_allowed for row in own_audit)
            or any(row.event not in parent_allowed for row in parent_audit)):
        return finish(False, 'The spool or its parent has recorded activity beyond initial setup.')

    welds = list(s.scalars(select(Weld).where(Weld.item_id.in_(identities)).order_by(Weld.id)))
    requirements = list(s.scalars(select(WeldRequirement).where(
        WeldRequirement.item_id.in_(identities)).order_by(WeldRequirement.id)))
    basis['welds'], basis['requirements'] = [_values(row) for row in welds], [_values(row) for row in requirements]
    weld_ids = [row.id for row in welds]
    requirement_ids = [row.id for row in requirements]

    # Existence of these rows is activity even if current status was later
    # reset. Query persisted links directly, including quality records whose
    # audit entries have no item_id. Never load original file bytes here.
    def evidence(table_name, predicate):
        table = Base.metadata.tables[table_name]
        columns = list(table.primary_key.columns)
        rows = list(s.execute(select(*columns).where(predicate(table)).order_by(*columns)))
        basis[table_name] = [list(row) for row in rows]
        evidence_counts[table_name] = len(rows)

    for table_name, column in (
            ('flow_plans', 'item_id'), ('flow_events', 'item_id'), ('flow_exceptions', 'item_id'),
            ('tracking_process_events', 'item_id'), ('inspections', 'item_id'), ('reworks', 'item_id'),
            ('tracking_holds', 'item_id'), ('item_transfer_states', 'item_id'),
            ('spool_arrival_inspections', 'spool_id'), ('spool_material_inspections', 'spool_id'),
            ('spool_mtr_documents', 'spool_id'), ('spool_parts_plans', 'spool_id'),
            ('spool_parts_events', 'spool_id'), ('dossier_entries', 'item_id')):
        evidence(table_name, lambda table, column=column: table.c[column].in_(identities))
    for table_name in ('tracking_weld_work', 'tracking_weld_repairs'):
        evidence(table_name, lambda table: table.c.weld_id.in_(weld_ids))
    for table_name in ('tracking_requirement_evidence', 'tracking_requirement_reviews'):
        evidence(table_name, lambda table: table.c.requirement_id.in_(requirement_ids))
    evidence('tracking_spool_plans', lambda table: or_(table.c.item_id == parent_id,
                                                      table.c.assembly_id == item_id))
    evidence('order_spools', lambda table: table.c.assembly_id == item_id)
    evidence('flow_component_links', lambda table: or_(table.c.component_id.in_(identities),
                                                       table.c.spool_id.in_(identities)))
    part_lines = Base.metadata.tables['spool_part_lines']
    evidence('spool_part_allocations', lambda table: or_(table.c.component_id.in_(identities),
        table.c.line_id.in_(select(part_lines.c.id).where(part_lines.c.spool_id.in_(identities)))))
    evidence('quality_evidence', lambda table: or_(table.c.item_id.in_(identities),
                                                   table.c.weld_id.in_(weld_ids)))
    for table_name in ('dossier_reviews', 'dossier_issues', 'dossier_documents'):
        evidence(table_name, lambda table: (table.c.project_id == group.project_id) &
                 (table.c.item_id.is_(None) | table.c.item_id.in_(identities)))
    evidence('spool_document_sets', lambda table: table.c.spool_id.in_(identities))
    if any(evidence_counts.values()):
        return finish(False, 'The spool or its parent has linked production, material, QA or packet activity.')

    created_welds = [row for row in own_audit if row.event == 'TRACKING_WELD_CREATED']
    if (len(welds) != plan.planned_welds or any(row.item_id != item_id for row in welds)
            or {row.number for row in welds} != {f'W{number:02d}' for number in range(1, plan.planned_welds + 1)}
            or len(created_welds) != len(welds)
            or {row.details.get('weld_id') for row in created_welds} != set(weld_ids)
            or any(row.details.get('source') != 'purchase_order_weld_count' for row in created_welds)):
        return finish(False, 'The numbered weld placeholders differ from the generated scope.')
    blank_weld_fields = ('description', 'joint_type', 'size', 'wall_thickness', 'drawing_revision',
                         'component_a', 'heat_a', 'mtr_a', 'component_b', 'heat_b', 'mtr_b',
                         'wps', 'wps_revision', 'template_id', 'completed_at', 'completed_by')
    if any(row.version != 1 or row.cycle != 1 or row.required_operations != ['root', 'fill_cap']
           or any(getattr(row, name) for name in blank_weld_fields) for row in welds):
        return finish(False, 'A generated weld has been changed or has production state.')
    definitions = {}
    for definition in _default_definitions():
        values = RequirementIn(**definition).model_dump()
        values['check_kind'] = values.pop('check')
        definitions[values['code']] = values
    by_weld = {}
    for requirement in requirements:
        by_weld.setdefault(requirement.weld_id, []).append(requirement)
        expected = definitions.get(requirement.code)
        if (requirement.item_id != item_id or requirement.weld_id not in weld_ids or expected is None
                or requirement.version != 1 or requirement.cycle != 1 or requirement.status != 'pending'
                or requirement.template_id is not None
                or any(getattr(requirement, key) != value for key, value in expected.items())):
            return finish(False, 'The pending QA placeholders differ from the initial generated requirements.')
    if any({row.code for row in by_weld.get(weld_id, [])} != set(definitions)
           or len(by_weld.get(weld_id, [])) != len(definitions) for weld_id in weld_ids):
        return finish(False, 'The initial generated QA requirement set is incomplete.')

    # Automatic source seeding can legitimately contain heat/MTR values.
    # Verify they remain exactly the initial imported values, not manual edits.
    trace = s.get(SpoolBomTrace, item_id)
    materials = list(s.scalars(select(SpoolBomMaterial).where(
        SpoolBomMaterial.spool_id == item_id).order_by(SpoolBomMaterial.piece_key)))
    material_events = list(s.scalars(select(SpoolBomEvent).where(
        SpoolBomEvent.spool_id == item_id).order_by(SpoolBomEvent.version)))
    basis.update(material_trace=_values(trace), materials=[_values(row) for row in materials],
                 material_events=[_values(row) for row in material_events])
    if trace is None:
        if materials or material_events:
            return finish(False, 'The physical material scope has unverified history.')
    else:
        pieces = {piece['piece_key']: _import_material_values(piece)
                  for piece in _piece_definitions(trace.definition)}
        if (trace.version != 1 or len(material_events) != 1 or material_events[0].version != 1
                or len(material_events[0].changes) != 1
                or material_events[0].changes[0].get('type') != 'pieces_initialized'
                or material_events[0].changes[0].get('after_definition') != trace.definition
                or {row.piece_key for row in materials} != set(pieces)
                or any(any(getattr(row, key) != pieces[row.piece_key][key] for key in MATERIAL_FIELDS)
                       for row in materials)):
            return finish(False, 'The physical material register has changed since initial source seeding.')
    return finish(True, 'Only automatically generated planning placeholders are recorded; saved demand and history are retained.')
