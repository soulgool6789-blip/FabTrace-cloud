"""Purchase-order scoped BOM downloads using the application's XLSX writer.

These are editable offline snapshots/templates. Downloading never changes a
quantity, creates an inventory identity, or certifies completed fabrication.
"""
import tempfile
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from main import Employee, Item, auth, db, utcnow
from tracking import SpoolPlan
from flow import FlowPlan
from parts import parts_snapshot
from orders import order_detail
from exports import (ExporterIdentity, TEMP_MEMORY_BYTES, WorkbookWriter,
                     XLSX_MEDIA_TYPE, _stream_file, _utc)


router = APIRouter(prefix='/api/orders', tags=['purchase order bills of materials'])
SUMMARY_COLUMNS = (
    'PO number', 'GPN / Assembly number', 'Assembly ID',
    'Required spools', 'Linked spools', 'Missing spools', 'Ready spools',
    'Linked spools not ready', 'Planning status', 'Notes', 'Blockers',
)
BOM_COLUMNS = (
    'PO number', 'GPN / Assembly number', 'Assembly ID', 'Spool ID',
    'Spool part number', 'Material part number', 'Material description',
    'Required quantity', 'Assigned quantity', 'Received quantity', 'Prepared quantity',
    'Remaining quantity', 'Unit', 'BOM reference', 'Assigned component IDs',
    'Line notes', 'Planning status',
)
TEMPLATE_COLUMNS = (
    'PO number', 'GPN / Assembly number', 'Assembly ID', 'Spool ID',
    'Spool part number', 'Material part number', 'Material description',
    'Required quantity', 'Unit', 'BOM reference', 'Line notes',
)
SPOOL_COLUMNS = (
    'PO number', 'GPN / Assembly number', 'Assembly ID', 'Spool ID',
    'Spool part number', 'Planning status', 'BOM reference',
    'BOM version', 'Required pieces', 'Assigned pieces', 'Received pieces',
    'Prepared pieces', 'Remaining pieces', 'Process status', 'Current step',
    'Ready for assembly', 'Blockers',
)


def _join(values):
    return '\n'.join(str(value) for value in values if value)


def _selection(detail, gpn_id, assembly_id):
    """Reject foreign filters instead of silently returning another scope."""
    gpns = detail['gpns']
    if gpn_id is not None:
        gpns = [row for row in gpns if row['id'] == gpn_id]
        if not gpns:
            raise HTTPException(404, 'GPN not found in this purchase order')
    allowed = {row['id'] for row in gpns}
    assemblies = [row for row in detail['assemblies'] if row['gpn_id'] in allowed]
    if assembly_id is not None:
        assemblies = [row for row in assemblies if row['item_id'] == assembly_id]
        if not assemblies:
            raise HTTPException(404, 'Assembly not found in this purchase order and GPN selection')
    return gpns, assemblies


def _context(order, assembly=None, spool=None, gpn=None):
    assembly, spool = assembly or {}, spool or {}
    number = assembly.get('gpn', gpn or '')
    retained = assembly.get('assembly_part_number', '')
    return {
        'PO number': order['purchase_order'],
        'GPN / Assembly number': number,
        'Assembly ID': assembly.get('item_id', ''),
        'Retained assembly part number': retained if retained and retained != number else '',
        'Spool ID': spool.get('item_id', ''),
        'Spool part number': spool.get('google_part_number') or '',
    }


def _identity_columns(headers, include_retained):
    """Keep new combined numbers simple while retaining distinct old metadata."""
    if include_retained:
        return headers[:3] + ('Retained assembly part number',) + headers[3:]
    return headers


def _write(writer, name, headers, rows, *, json_columns=()):
    writer.write_rows(name, 'derived:purchase_order_bom', headers,
        (([row.get(header) for header in headers], str(index))
         for index, row in enumerate(rows, 1)), len(rows),
        json_columns=json_columns, group='report')


def _snapshot_rows(session, detail, gpn_id=None, assembly_id=None, *, template=False):
    order = detail['order']
    gpns, assemblies = _selection(detail, gpn_id, assembly_id)
    summary, bom, register = [], [], []
    seen_spools = set()

    def spool_rows(spool, assembly=None, unmapped=False):
        spool_id = spool['item_id']
        if spool_id in seen_spools:
            raise RuntimeError('A physical spool appeared more than once in the selected order scope')
        seen_spools.add(spool_id)
        context = _context(order, assembly, spool)
        snapshot = parts_snapshot(session, spool_id)
        has_lines = bool(snapshot and snapshot['lines'])
        status = 'Planned' if has_lines else 'BOM not planned'
        if unmapped:
            status = 'Not assigned to a PO assembly; ' + status.lower()
        totals = snapshot['totals'] if snapshot else {}
        blockers = list(spool.get('blockers') or [])
        if snapshot:
            blockers += snapshot['blockers']
        else:
            blockers.append('Create the required parts list for this spool')
        register.append({**context,
            'Planning status': status, 'BOM reference': snapshot['reference'] if snapshot else '',
            'BOM version': snapshot['version'] if snapshot else None,
            'Required pieces': totals.get('required_qty'), 'Assigned pieces': totals.get('assigned_qty'),
            'Received pieces': totals.get('received_qty'), 'Prepared pieces': totals.get('prepared_qty'),
            'Remaining pieces': totals.get('remaining_qty'), 'Process status': spool.get('flow_status', 'not_started'),
            'Current step': spool.get('current_step'), 'Ready for assembly': spool.get('ready_for_assembly'),
            'Blockers': _join(dict.fromkeys(blockers))})
        if template:
            bom.append({**context, 'Unit': 'piece', 'BOM reference': snapshot['reference'] if snapshot else ''})
        elif has_lines:
            for line in snapshot['lines']:
                bom.append({**context, 'Material part number': line['part_number'],
                    'Material description': line['description'], 'Required quantity': line['required_qty'],
                    'Assigned quantity': line['assigned_qty'], 'Received quantity': line['received_qty'],
                    'Prepared quantity': line['prepared_qty'], 'Remaining quantity': line['remaining_qty'],
                    'Unit': 'piece', 'BOM reference': snapshot['reference'],
                    'Assigned component IDs': _join(component['id'] for component in line['components']),
                    'Line notes': line['notes'], 'Planning status': status})
        else:
            bom.append({**context, 'Unit': 'piece', 'Planning status': status})

    for assembly in assemblies:
        context = _context(order, assembly)
        summary.append({**context,
            'Required spools': assembly['required_spools'], 'Linked spools': assembly['linked_spools'],
            'Missing spools': assembly['missing_spools'], 'Ready spools': assembly['ready_spools'],
            'Linked spools not ready': assembly['not_ready_spools'],
            'Planning status': 'Assembly production plan needed' if assembly['planning_needed'] else 'Planned',
            'Notes': assembly['notes'], 'Blockers': _join(assembly['blockers'])})
        if not assembly['spools']:
            status = 'No physical spools linked; material quantities not yet planned'
            bom.append({**context, 'Unit': 'piece', 'Planning status': status})
            register.append({**context, 'Planning status': status, 'Blockers': _join(assembly['blockers'])})
        for spool in assembly['spools']:
            spool_rows(spool, assembly)

    for gpn in gpns:
        if assembly_id is not None or any(row['gpn_id'] == gpn['id'] for row in assemblies):
            continue
        context = _context(order, gpn=gpn['gpn'])
        status = 'Finish GPN / Assembly setup; no physical assembly or spools registered'
        summary.append({**context, 'Planning status': status})
        bom.append({**context, 'Unit': 'piece', 'Planning status': status})
        register.append({**context, 'Planning status': status})

    # A newly attached legacy project can contain valid spools that are not yet
    # assigned to an order assembly. Keep them visible in an unfiltered PO export.
    # Filters must never leak an unassigned or different-GPN material list.
    if gpn_id is None and assembly_id is None:
        unassigned_parent_ids = set()
        for plan, item in session.execute(select(SpoolPlan, Item).join(Item, Item.id == SpoolPlan.item_id)
                .where(SpoolPlan.project_id == order['project_id'], Item.kind != 'Assembly')
                .order_by(SpoolPlan.item_id)):
            if item.id in seen_spools:
                continue
            flow = session.get(FlowPlan, item.id)
            parent = session.get(Item, plan.assembly_id) if plan.assembly_id else None
            if parent:
                unassigned_parent_ids.add(parent.id)
            context_assembly = {'item_id': parent.id, 'gpn': '', 'assembly_part_number': ''} if parent else None
            spool_rows({'item_id': item.id, 'google_part_number': item.google_part_number,
                'flow_status': flow.status if flow else 'not_started',
                'current_step': flow.current_step if flow else None,
                'blockers': ['Assign this spool to a mapped PO/GPN assembly']}, context_assembly, unmapped=True)
        for assembly in detail.get('available_assemblies', []):
            context = _context(order, {'item_id': assembly['item_id']})
            status = 'Assembly not assigned to a PO/GPN; required spool count not declared'
            summary.append({**context,
                'Planning status': status,
                'Blockers': 'Assign the assembly to a GPN and declare its required spool count'})
            if assembly['item_id'] not in unassigned_parent_ids:
                bom.append({**context, 'Unit': 'piece', 'Planning status': status})
                register.append({**context, 'Planning status': status})

    if not bom:
        # A template is useful before individual spools exist. Its blank quantity
        # means undeclared, never zero, one, or the assembly's required spool count.
        for gpn in gpns or [{}]:
            context = _context(order, gpn=gpn.get('gpn', ''))
            bom.append({**context, 'Unit': 'piece', 'Planning status': 'No physical spools planned'})
    return summary, bom, register


def build_order_bom(bind, exporter, project_id, *, gpn_id=None, assembly_id=None,
                    template=False, created_at=None):
    """Return a rewound temporary XLSX produced from one read-only snapshot."""
    created_at = created_at or utcnow()
    engine = bind.engine if isinstance(bind, Connection) else bind
    output = tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES, mode='w+b')
    try:
        with tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES, mode='w+b') as overflow:
            with engine.connect() as raw:
                kind = raw.dialect.name
                connection = raw.execution_options(isolation_level='REPEATABLE READ') if kind == 'postgresql' else raw
                with connection.begin():
                    if kind == 'postgresql':
                        connection.execute(text('SET TRANSACTION READ ONLY'))
                    elif kind == 'sqlite':
                        connection.exec_driver_sql('BEGIN')
                    else:
                        raise RuntimeError('Consistent BOM export supports PostgreSQL and SQLite')
                    with Session(bind=connection, autoflush=False, expire_on_commit=False,
                                 join_transaction_mode='rollback_only') as session:
                        detail = order_detail(session, project_id)
                        summary, bom, register = _snapshot_rows(session, detail, gpn_id, assembly_id, template=template)
                    retained_numbers = any(row.get('Retained assembly part number') for row in summary)
                    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED,
                                         compresslevel=6, allowZip64=True) as archive:
                        writer = WorkbookWriter(archive, overflow)
                        writer.next_sheet_id = 1
                        _write(writer, 'Assembly summary', _identity_columns(SUMMARY_COLUMNS, retained_numbers), summary)
                        _write(writer, 'BOM template' if template else 'Bill of materials',
                               _identity_columns(TEMPLATE_COLUMNS if template else BOM_COLUMNS, retained_numbers), bom)
                        _write(writer, 'Spool register', _identity_columns(SPOOL_COLUMNS, retained_numbers), register)
                        info = [
                            ('Document', 'Editable BOM planning template' if template else 'Purchase order bill of materials snapshot'),
                            ('PO number', detail['order']['purchase_order']),
                            ('Customer', detail['order']['customer']),
                            ('Project ID', project_id),
                            ('Project name', detail['order']['project_name']),
                            ('Order revision', detail['order']['version']),
                            ('GPN / Assembly filter', gpn_id or 'All GPN / Assemblies'),
                            ('Physical assembly filter', assembly_id or 'All physical assemblies'),
                            ('Exported at', _utc(created_at)),
                            ('Exported by', exporter.name),
                            ('Quantity unit', 'Whole physical pieces per unique spool. Material quantities are not multiplied by the required spool count.'),
                            ('Assembly counts', 'Required spools are declared scope; linked spools count unique existing identities. Missing spools have no invented material quantities.'),
                            ('Number identity', 'GPN / Assembly number is the combined business number. Assembly ID remains the unique physical QR identity.'),
                            ('Progress', 'Received and prepared counts come from current recorded component processes. A BOM quantity or assignment does not prove receipt, preparation or QA release.'),
                            ('Blank quantities', 'A blank quantity means not planned or not known. It does not mean zero required pieces.'),
                            ('Excel editing', 'This workbook is editable offline. Editing or saving it does not change FabTrace; enter approved quantities using Spool parts. Excel import is not provided by this download.'),
                            ('Template use', 'Add one line per material requirement and unique physical spool. Copy context cells when adding rows; enter material part number, description, whole-piece quantity and approved BOM reference. Leave unregistered spool identities blank until assigned.'),
                            ('Control', 'Planning/export only. This workbook is not a QA-issued Job Packet or authorization to pass a quality hold point.'),
                        ]
                        if retained_numbers:
                            info.append(('Retained numbers', 'Retained assembly part number preserves a distinct earlier number only where it differs from the GPN / Assembly number. The export does not rename or modify any record.'))
                        _write(writer, 'Export info', ('Entry', 'Value'), [{'Entry': key, 'Value': value} for key, value in info])
                        writer.write_overflow()
                        writer.finish(created_at)
        output.seek(0)
        return output
    except BaseException:
        output.close()
        raise


def _download(project_id, gpn_id, assembly_id, template, user, session):
    created_at = utcnow()
    exporter = ExporterIdentity(badge=user.badge, name=user.name, role=user.role)
    bind = session.get_bind()
    session.rollback()  # Release the authentication connection before the snapshot.
    file = build_order_bom(bind, exporter, project_id, gpn_id=gpn_id,
        assembly_id=assembly_id, template=template, created_at=created_at)
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    # No user-controlled PO, GPN or description enters a response header.
    filename = ('fabtrace-bom-template-' if template else 'fabtrace-bom-') + created_at.strftime('%Y%m%dT%H%M%SZ') + '.xlsx'
    return StreamingResponse(_stream_file(file), media_type=XLSX_MEDIA_TYPE,
        headers={'Content-Disposition': f'attachment; filename="{filename}"',
                 'Content-Length': str(size), 'Cache-Control': 'private, no-store'},
        background=BackgroundTask(file.close))


@router.get('/{project_id}/bom.xlsx')
def export_bom(project_id: str, gpn_id: str | None = Query(default=None, min_length=1, max_length=60),
               assembly_id: str | None = Query(default=None, min_length=1, max_length=60),
               u: Employee = Depends(auth), s: Session = Depends(db)):
    return _download(project_id, gpn_id, assembly_id, False, u, s)


@router.get('/{project_id}/bom-template.xlsx')
def export_bom_template(project_id: str, gpn_id: str | None = Query(default=None, min_length=1, max_length=60),
                        assembly_id: str | None = Query(default=None, min_length=1, max_length=60),
                        u: Employee = Depends(auth), s: Session = Depends(db)):
    return _download(project_id, gpn_id, assembly_id, True, u, s)
