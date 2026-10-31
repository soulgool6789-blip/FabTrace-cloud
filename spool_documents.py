"""User-selected spool reference documents, with immutable uploaded revisions.

An uploaded BOM is a reference, not a material receipt or QA approval. Documents
belong to an exact order spool requirement or an exact physical spool. A physical
spool inherits only its registered requirement's documents; uploads never match
or attach themselves by a part number elsewhere in the system.
"""
from datetime import timezone
from decimal import Decimal, InvalidOperation
import csv
import hashlib
import io
import json
import re
import unicodedata
from urllib.parse import quote
import uuid
import warnings
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from openpyxl import load_workbook
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter
from sqlalchemy import (CheckConstraint, Column, DateTime, ForeignKey, Integer,
                        JSON, LargeBinary, String, Text, UniqueConstraint, func, select)
from sqlalchemy.orm import Session, deferred
from sqlalchemy.exc import IntegrityError

from main import Base, Employee, Item, audit, auth, db, lock_item, utcnow
from flow import lock_topology
from orders import OrderAssembly, OrderGpn, PurchaseOrder, _key, read_snapshot
from order_setup import OrderSpoolRequirement
from order_spools import OrderSpool, effective_children, effective_parent_id, guard_registered_spool
from permissions import has_capability
from removals import (item_not_removed, require_active_gpn, require_active_item,
                      require_active_project)


router = APIRouter(prefix='/api/spool-documents', tags=['spool document uploads'])
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024
MAX_SCOPE_BYTES = 256 * 1024 * 1024
MAX_FILES = 40
MAX_PAGES = 200
MAX_LINES = 500
MAX_IMAGE_PIXELS = 20_000_000
BOM_COLUMNS = ['item', 'quantity', 'unit', 'part_number', 'description', 'size',
               'material', 'length', 'notes']
XLSX_MEDIA = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class SpoolDocumentSet(Base):
    __tablename__ = 'spool_document_sets'
    __table_args__ = (CheckConstraint(
        '(requirement_id IS NOT NULL AND spool_id IS NULL) OR '
        '(requirement_id IS NULL AND spool_id IS NOT NULL)', name='ck_spool_document_exact_scope'),)
    id = Column(String(60), primary_key=True)
    requirement_id = Column(String(60), ForeignKey('order_spool_requirements.id'), unique=True)
    spool_id = Column(String(60), ForeignKey('items.id'), unique=True)
    scope_snapshot = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=0)
    created_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class SpoolDocument(Base):
    __tablename__ = 'spool_documents'
    __table_args__ = (
        UniqueConstraint('set_id', 'version', name='uq_spool_document_set_version'),
        CheckConstraint("kind IN ('bom', 'isometric')", name='ck_spool_document_kind'),
    )
    id = Column(String(60), primary_key=True)
    set_id = Column(String(60), ForeignKey('spool_document_sets.id'), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    version = Column(Integer, nullable=False)
    filename = Column(String(200), nullable=False)
    media_type = Column(String(160), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    selection_sha256 = Column(String(64), nullable=False)
    page_count = Column(Integer)
    revision = Column(String(80), nullable=False, default='')
    uploaded_by = Column(String(80), ForeignKey('employees.badge'), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    reason = Column(Text, nullable=False)
    source_files = Column(JSON, nullable=False)
    bom = Column(JSON)


class SpoolDocumentFile(Base):
    __tablename__ = 'spool_document_files'
    document_id = Column(String(60), ForeignKey('spool_documents.id'), primary_key=True)
    content = deferred(Column(LargeBinary, nullable=False))


def _fail(message, status=422):
    raise HTTPException(status, message)


def _stamp(value):
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat() if value is not None else None


def _can_upload(user):
    return any(has_capability(user, capability) for capability in
               ('manage_production', 'allocate_parts', 'inspect'))


def _safe_filename(value):
    value = unicodedata.normalize('NFKC', str(value or 'document'))
    value = value.replace('\\', '/').split('/')[-1]
    value = re.sub(r'[\x00-\x1f\x7f"<>:|?*]', '_', value).strip(' .')
    if not value:
        value = 'document'
    if len(value) > 180:
        stem, dot, extension = value.rpartition('.')
        value = stem[:160] + dot + extension[:18] if dot else value[:180]
    return value


def _set_for(s, scope, identity):
    column = SpoolDocumentSet.requirement_id if scope == 'requirements' else SpoolDocumentSet.spool_id
    return s.scalar(select(SpoolDocumentSet).where(column == identity))


def guard_document_spool_identity(s, item, values=None):
    """Keep uploaded files attached to the physical identity selected at upload."""
    doc_set = _set_for(s, 'spools', item.id)
    if doc_set is None:
        return
    saved = doc_set.scope_snapshot
    project_id = values.get('project_id') if values is not None else item.project
    assembly_id = values.get('assembly_id') if values is not None else effective_parent_id(s, item.id)
    if (item.kind != 'Spool' or _key(item.google_part_number or '') != _key(saved['spool_number'] or '')
            or (project_id or '') != (saved['project_id'] or '')
            or (assembly_id or '') != (saved['assembly_id'] or '')):
        _fail('This physical spool has uploaded BOM or drawing documents. Retain its saved spool number, '
              'purchase order and assembly so those documents cannot move to a different production identity.', 409)


def guard_document_requirement_identity(s, group, *, gpn=None, spool_numbers=None):
    """Retain the assembly/spool identities selected for setup document uploads.

    Call before mutating the group's number or reconciling its requirement list.
    Counts and weld declarations can change under the existing planning rules;
    a document-backed requirement cannot silently become a different assembly
    or disappear when a setup edit creates/replaces another spool number.
    """
    backed = list(s.scalars(select(OrderSpoolRequirement)
        .join(SpoolDocumentSet, SpoolDocumentSet.requirement_id == OrderSpoolRequirement.id)
        .where(OrderSpoolRequirement.gpn_id == group.id, SpoolDocumentSet.version > 0)))
    if not backed:
        return
    if gpn is not None and _key(gpn) != _key(group.gpn):
        _fail('This assembly has uploaded spool BOM or drawing documents. Retain its saved assembly number '
              'so the uploaded files and revision history stay associated with the correct assembly and spools. '
              'Quantities and weld counts can still be edited before physical registration.', 409)
    if spool_numbers is not None:
        incoming = {_key(number) for number in spool_numbers}
        if any(line.active and line.normalized_number not in incoming for line in backed):
            _fail('A spool in this setup has uploaded BOM or drawing documents. Retain its saved spool number '
                  'and setup row so its files and revision history remain accessible. Quantities and weld counts '
                  'can still be edited before physical registration.', 409)


def _target(s, scope, identity):
    if scope not in ('requirements', 'spools'):
        _fail('Choose an order spool requirement or a physical spool.', 404)
    group = None
    if scope == 'requirements':
        requirement = s.get(OrderSpoolRequirement, identity)
        if requirement is None or not requirement.active:
            _fail('Active spool requirement not found.', 404)
        group = s.get(OrderGpn, requirement.gpn_id)
        if group is None:
            _fail('Assembly number not found.', 404)
        require_active_gpn(s, group.id)
        require_active_project(s, group.project_id)
        project_id, assembly_id, spool_number = group.project_id, None, requirement.spool_number
        item, registration = None, None
    else:
        item = s.get(Item, identity)
        if item is None or item.kind != 'Spool':
            _fail('Physical spool not found.', 404)
        require_active_item(s, item.id)
        guard_registered_spool(s, item)
        guard_document_spool_identity(s, item)
        project_id, assembly_id, spool_number = item.project, effective_parent_id(s, item.id), item.google_part_number
        if project_id:
            require_active_project(s, project_id)
        registration = s.get(OrderSpool, item.id)
        requirement = s.get(OrderSpoolRequirement, registration.requirement_id) if registration else None
        mapping = s.get(OrderAssembly, assembly_id) if assembly_id else None
        group = s.get(OrderGpn, mapping.gpn_id) if mapping else None
        if assembly_id:
            require_active_item(s, assembly_id)
        if group:
            require_active_gpn(s, group.id)
    order = s.get(PurchaseOrder, project_id) if project_id else None
    context = {'kind': 'requirement' if scope == 'requirements' else 'spool',
               'requirement_id': requirement.id if requirement else None,
               'item_id': item.id if item else None, 'spool_number': spool_number,
               'assembly_id': assembly_id, 'assembly_number': group.gpn if group else None,
               'gpn_id': group.id if group else None, 'project_id': project_id,
               'purchase_order': order.purchase_order if order else None}
    return context, item, requirement


def _locked_reason(s, scope, identity, item, requirement):
    if scope == 'spools':
        if item.released:
            return 'This spool is released. Return it to work before uploading a new document revision.'
        parent_id = effective_parent_id(s, item.id)
        parent = s.get(Item, parent_id) if parent_id else None
        if parent and parent.released:
            return 'The parent assembly is released. Return it to work before changing spool documents.'
        return ''
    # A requirement update becomes the effective drawing/BOM on its registered
    # children. Do not silently change a released physical production basis.
    child = s.scalar(select(Item.id).join(OrderSpool, OrderSpool.item_id == Item.id)
        .where(OrderSpool.requirement_id == requirement.id, Item.released.is_(True), item_not_removed(Item.id)).limit(1))
    parent = s.scalar(select(Item.id).join(OrderAssembly, OrderAssembly.item_id == Item.id)
        .where(OrderAssembly.gpn_id == requirement.gpn_id, Item.released.is_(True), item_not_removed(Item.id)).limit(1))
    if child or parent:
        return ('A physical spool or assembly in this setup is released. Return it to work before '
                'revising shared setup documents, or upload to an unreleased individual spool.')
    return ''


def _metadata(document, doc_set, inherited=False, include_bom=True):
    bom = document.bom
    if bom and not include_bom:
        bom = {key: value for key, value in bom.items() if key != 'lines'}
    return {'id': document.id, 'kind': document.kind, 'version': document.version,
            'filename': document.filename, 'media_type': document.media_type,
            'size_bytes': document.size_bytes, 'sha256': document.sha256,
            'page_count': document.page_count, 'revision': document.revision,
            'uploaded_by': document.uploaded_by, 'uploaded_at': _stamp(document.uploaded_at),
            'reason': document.reason, 'scope_kind': 'requirement' if doc_set.requirement_id else 'spool',
            'scope_id': doc_set.requirement_id or doc_set.spool_id, 'inherited': inherited,
            'view_url': '/api/spool-documents/files/' + document.id,
            'download_url': '/api/spool-documents/files/' + document.id + '?download=1',
            'source_files': document.source_files, 'bom': bom}


def _documents(s, doc_set, inherited=False):
    if doc_set is None:
        return []
    rows = list(s.scalars(
        select(SpoolDocument).where(SpoolDocument.set_id == doc_set.id)
        .order_by(SpoolDocument.version.desc()).limit(100)))
    # A rarely revised BOM may precede 100 newer drawing revisions. Retain its
    # effective identity without loading an unbounded history into every read.
    for kind in ('bom', 'isometric'):
        if not any(row.kind == kind for row in rows):
            older = s.scalar(select(SpoolDocument).where(SpoolDocument.set_id == doc_set.id,
                SpoolDocument.kind == kind).order_by(SpoolDocument.version.desc()).limit(1))
            if older:
                rows.append(older)
    return [(_metadata(row, doc_set, inherited), row) for row in rows]


def _effective(s, scope, identity, requirement=None):
    local = _set_for(s, scope, identity)
    inherited = (_set_for(s, 'requirements', requirement.id)
                 if scope == 'spools' and requirement is not None else None)
    local_documents = _documents(s, local)
    inherited_documents = _documents(s, inherited, True)
    active = {'bom': None, 'isometric': None}
    rows = {}
    for metadata, row in local_documents + inherited_documents:
        if active[row.kind] is None:
            active[row.kind] = metadata
            rows[row.kind] = row
    return local, inherited, active, rows, local_documents, inherited_documents


def _detail(s, scope, identity, user):
    context, item, requirement = _target(s, scope, identity)
    local, inherited, active, _, local_documents, inherited_documents = _effective(s, scope, identity, requirement)
    locked = _locked_reason(s, scope, identity, item, requirement)
    history = []
    for metadata, row in (local_documents + inherited_documents)[:100]:
        history.append({**metadata, 'bom': ({key: value for key, value in row.bom.items() if key != 'lines'}
                                          if row.bom else None)})
    return {'context': context, 'version': local.version if local else 0,
            'editable': _can_upload(user) and not locked, 'locked_reason': locked,
            'active': active, 'history': history,
            'inherited_from': ({'requirement_id': requirement.id, 'spool_number': requirement.spool_number}
                               if inherited else None),
            'permissions': {'can_upload': _can_upload(user)},
            'limits': {'max_file_bytes': MAX_FILE_BYTES, 'max_total_bytes': MAX_TOTAL_BYTES,
                       'max_files': MAX_FILES, 'max_pages': MAX_PAGES, 'max_bom_lines': MAX_LINES}}


ALIASES = {
    'item': ('item', 'itemno', 'itemnumber', 'line', 'lineno', 'lineitem', 'position', 'pos'),
    'quantity': ('quantity', 'qty', 'quant', 'quantityperspool', 'qtyperspool'),
    'unit': ('unit', 'units', 'uom', 'unitofmeasure'),
    'part_number': ('partnumber', 'partno', 'part', 'taslnnumber', 'tasln', 'taslnno', 'lnnumber', 'taspn', 'materialcode'),
    'description': ('description', 'materialdescription', 'itemdescription', 'componentdescription'),
    'size': ('size', 'nominalsize', 'nps', 'diameter'),
    'material': ('material', 'materialspec', 'specification', 'grade'),
    'length': ('length', 'lengthdisplay', 'lengthinches', 'cutlength'),
    'notes': ('notes', 'note', 'remarks'),
    'spool_number': ('spoolnumber', 'spoolno', 'spool', 'spoolid'),
    'drawing': ('drawing', 'drawingnumber', 'drawingno'),
    'revision': ('revision', 'rev', 'drawingrevision'),
    'source_page': ('sourcepage', 'sourcepages', 'sourcesheet', 'sheet', 'page'),
    'assembly_number': ('assemblynumber', 'assembly', 'gpn', 'googlepartnumber'),
}
HEADER_MAP = {alias: field for field, aliases in ALIASES.items() for alias in aliases}


def _header(value):
    normalized = re.sub('[^a-z0-9]', '', str(value or '').lower())
    return HEADER_MAP.get(normalized)


def _text(value, maximum=1000):
    text = '' if value is None else str(value).strip()
    if len(text) > maximum:
        _fail(f'A BOM value exceeds {maximum:,} characters. Shorten that cell and upload again.')
    if any(ord(character) < 32 and character not in '\r\n\t' for character in text):
        _fail('BOM cells must contain readable text.')
    return text


def _bom_grid(rows, spool_number, assembly_number, sheet=''):
    header_index, fields = None, None
    for index, row in enumerate(rows[:30]):
        mapped = [_header(value) for value in row]
        if 'quantity' in mapped and 'description' in mapped:
            used = [field for field in mapped if field]
            if len(used) != len(set(used)):
                _fail('The BOM contains duplicate recognized column headings.')
            header_index, fields = index, mapped
            break
    if fields is None:
        _fail('The BOM needs Quantity and Description columns. Download the BOM template for the supported headings.')
    lines, source_spools, skipped = [], set(), 0
    for index, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(value is not None and str(value).strip() for value in row):
            continue
        values = {field: row[column] if column < len(row) else None
                  for column, field in enumerate(fields) if field}
        if 'spool_number' in values:
            number = _text(values['spool_number'], 160)
            if not number:
                _fail(f'BOM row {index} needs its Spool number; a spool-number column cannot contain unassigned lines.')
            source_spools.add(number)
            if _key(number) != _key(spool_number or ''):
                skipped += 1
                continue
        if values.get('assembly_number') and assembly_number and _key(str(values['assembly_number'])) != _key(assembly_number):
            _fail(f'BOM row {index} belongs to a different assembly number. Choose the corresponding spool in that assembly.')
        try:
            quantity = Decimal(str(values.get('quantity', '')).strip())
            if not quantity.is_finite() or quantity <= 0 or quantity > 100_000_000:
                raise InvalidOperation
        except (InvalidOperation, ValueError, TypeError):
            _fail(f'BOM row {index} needs a positive numeric Quantity.')
        description = _text(values.get('description'))
        if not description:
            _fail(f'BOM row {index} needs a Description.')
        line = {key: _text(values.get(key), 2000 if key == 'notes' else 1000) for key in BOM_COLUMNS if key != 'quantity'}
        line['item'] = line['item'] or str(len(lines) + 1)
        line['quantity'] = int(quantity) if quantity == quantity.to_integral_value() else float(quantity)
        line['unit'] = line['unit'] or 'EA'
        for key in ('spool_number', 'drawing', 'revision', 'source_page', 'assembly_number'):
            if key in values:
                line[key] = _text(values[key])
        lines.append(line)
        if len(lines) > MAX_LINES:
            _fail(f'A spool BOM can contain at most {MAX_LINES} material lines.')
    if not lines:
        _fail('No material lines match the selected spool number.' if source_spools else 'The BOM contains no material lines.')
    return {'columns': BOM_COLUMNS, 'lines': lines, 'line_count': len(lines),
            'quantity_basis': 'one_spool', 'sheet': sheet, 'source_spools': sorted(source_spools),
            'warnings': ([f'{skipped} row(s) for other spool numbers were excluded from this spool preview.'] if skipped else [])}


def _xlsx_rows(content, sheet):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if (len(entries) > 2000 or sum(entry.file_size for entry in entries) > 64 * 1024 * 1024
                    or any(entry.flag_bits & 1 or entry.filename.startswith('/')
                           or '..' in entry.filename.split('/') for entry in entries)
                    or any('vbaproject' in entry.filename.lower() or 'externallink' in entry.filename.lower() for entry in entries)):
                _fail('The workbook contains unsupported or excessively large content.')
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
        try:
            names = workbook.sheetnames
            if sheet and sheet not in names:
                _fail('The selected worksheet does not exist in this workbook.')
            candidates = []
            for worksheet in workbook.worksheets:
                sample = list(worksheet.iter_rows(min_row=1, max_row=min(30, worksheet.max_row or 30),
                                                 max_col=min(worksheet.max_column or 30, 40), values_only=True))
                if any('quantity' in [_header(value) for value in row] and
                       'description' in [_header(value) for value in row] for row in sample):
                    candidates.append(worksheet.title)
            if not sheet:
                if len(candidates) != 1:
                    return None, candidates or names, ''
                sheet = candidates[0]
            worksheet = workbook[sheet]
            if (worksheet.max_row or 0) > 10000 or (worksheet.max_column or 0) > 100:
                _fail('Choose a compact per-spool BOM worksheet (up to 10,000 source rows and 100 columns).')
            rows = []
            for row in worksheet.iter_rows(max_row=min(worksheet.max_row or 10000, 10000), max_col=min(worksheet.max_column or 40, 100)):
                if any(cell.data_type == 'f' for cell in row):
                    _fail('BOM worksheets must contain saved values, not formulas. Save a values-only copy before upload.')
                values = []
                for cell in row:
                    value = cell.value
                    if (isinstance(value, int) and not isinstance(value, bool) and value >= 0
                            and re.fullmatch('0{2,}', cell.number_format or '')):
                        value = str(value).zfill(len(cell.number_format))
                    values.append(value)
                rows.append(values)
            return rows, candidates or names, sheet
        finally:
            workbook.close()
    except HTTPException:
        raise
    except Exception:
        _fail('The Excel file could not be read. Upload a valid .xlsx workbook or CSV.', 415)


def _strip_pdf_actions(value, seen=None):
    """Keep complete page graphics while removing interactive PDF actions."""
    seen = set() if seen is None else seen
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if hasattr(current, 'get_object'):
            current = current.get_object()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        if depth > 100 or len(seen) > 200_000:
            _fail('The PDF contains an excessively complex object structure. Export a flattened PDF and upload it again.', 415)
        if isinstance(current, dict):
            for key in ('/A', '/AA', '/OpenAction', '/JS', '/JavaScript', '/Launch', '/EmbeddedFiles',
                        '/RichMediaContent', '/RichMediaSettings', '/XFA'):
                current.pop(key, None)
            pending.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend((child, depth + 1) for child in current)


def _pdf_pages(content, extension):
    try:
        if extension == '.pdf':
            if not content.startswith(b'%PDF-'):
                _fail('The uploaded PDF does not contain a valid PDF document.', 415)
            reader = PdfReader(io.BytesIO(content), strict=False)
            if reader.is_encrypted:
                _fail('Password-protected PDFs cannot be used. Upload an unlocked copy.')
            count = len(reader.pages)
            if not 1 <= count <= MAX_PAGES:
                _fail(f'A document must contain between 1 and {MAX_PAGES} pages.')
            return reader
        if extension not in ('.png', '.jpg', '.jpeg'):
            _fail('Isometric scans must be PDF, PNG or JPEG files.', 415)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as picture:
                if picture.format not in ('PNG', 'JPEG'):
                    _fail('The actual scan format must be PNG or JPEG.', 415)
                if picture.width * picture.height > MAX_IMAGE_PIXELS:
                    _fail('A scan is too large. Use an image of at most 20 megapixels.')
                picture.load()
                converted = ImageOps.exif_transpose(picture).convert('RGB')
                output = io.BytesIO()
                converted.save(output, format='PDF', resolution=150.0)
                converted.close()
                return PdfReader(io.BytesIO(output.getvalue()))
    except HTTPException:
        raise
    except Exception:
        _fail('A drawing page could not be read. Upload a valid unlocked PDF, PNG or JPEG.', 415)


def _read_files(files):
    if not 1 <= len(files) <= MAX_FILES:
        _fail(f'Select between 1 and {MAX_FILES} files.')
    sources, total = [], 0
    for uploaded in files:
        content = uploaded.file.read(MAX_FILE_BYTES + 1)
        if not content:
            _fail('Empty files cannot be uploaded.')
        if len(content) > MAX_FILE_BYTES:
            _fail('Each file must be 20 MiB or smaller.', 413)
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            _fail('The selected files exceed the 40 MiB total upload limit.', 413)
        filename = _safe_filename(uploaded.filename)
        sources.append({'filename': filename, 'content': content,
                        'size_bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
    return sources


def _prepare(files, kind, sheet, context):
    if kind not in ('bom', 'isometric'):
        _fail('Choose Bill of material or Isometric drawings.')
    sources = _read_files(files)
    if kind == 'bom' and len(sources) != 1:
        _fail('Upload one BOM file at a time. Combine scanned BOM pages into one PDF first.')
    selection = hashlib.sha256(json.dumps({'kind': kind, 'sheet': sheet, 'files': [
        {key: value for key, value in source.items() if key != 'content'} for source in sources]},
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    first = sources[0]
    filename = first['filename']
    extension = '.' + filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    content, bom, page_count, sheets = first['content'], None, None, []
    sheet_required = False
    if kind == 'bom' and extension in ('.xlsx', '.csv', '.tsv'):
        if extension == '.xlsx':
            rows, sheets, selected_sheet = _xlsx_rows(content, sheet)
            sheet_required = rows is None
            media_type = XLSX_MEDIA
        else:
            try:
                decoded = content.decode('utf-8-sig')
                if '\x00' in decoded:
                    raise ValueError
                rows = list(csv.reader(io.StringIO(decoded), delimiter='\t' if extension == '.tsv' else ','))
                if len(rows) > 10000 or any(len(row) > 100 for row in rows):
                    _fail('Choose a compact per-spool BOM file (up to 10,000 source rows and 100 columns).')
            except (UnicodeError, ValueError, csv.Error):
                _fail('The BOM must be a UTF-8 CSV/TSV file or an Excel .xlsx workbook.', 415)
            selected_sheet, media_type = '', 'text/tab-separated-values' if extension == '.tsv' else 'text/csv'
        if not sheet_required:
            bom = _bom_grid(rows, context['spool_number'], context['assembly_number'], selected_sheet)
    else:
        writer = PdfWriter()
        try:
            for source in sources:
                source_extension = '.' + source['filename'].rsplit('.', 1)[-1].lower()
                reader = _pdf_pages(source['content'], source_extension)
                if len(writer.pages) + len(reader.pages) > MAX_PAGES:
                    _fail(f'The combined document exceeds {MAX_PAGES} pages.')
                seen = set()
                for page in reader.pages:
                    _strip_pdf_actions(page, seen)
                    writer.add_page(page)
            output = io.BytesIO()
            writer.write(output)
            content, page_count = output.getvalue(), len(writer.pages)
        except HTTPException:
            raise
        except Exception:
            _fail('The drawing pages could not be combined into a viewable PDF. Export a fresh PDF or scan and try again.', 415)
        finally:
            writer.close()
        filename = (_safe_filename(context['spool_number'] or context['item_id'] or 'spool') +
                    ('-isometric.pdf' if kind == 'isometric' else '-bom.pdf'))
        if len(sources) == 1 and extension == '.pdf':
            filename = first['filename']
        media_type = 'application/pdf'
    if len(content) > MAX_TOTAL_BYTES:
        _fail('The combined document exceeds the 40 MiB upload limit.', 413)
    return {'kind': kind, 'filename': filename, 'media_type': media_type,
            'size_bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
            'selection_sha256': selection, 'page_count': page_count,
            'source_files': [{key: value for key, value in source.items() if key != 'content'} for source in sources],
            'bom': bom, 'sheets': sheets, 'sheet_required': sheet_required, 'content': content}


@router.get('/template.csv')
def bom_template(user: Employee = Depends(auth)):
    columns = ['spool_number', *BOM_COLUMNS, 'drawing', 'revision', 'source_page']
    output = io.StringIO(newline='')
    csv.writer(output).writerow(columns)
    return Response(output.getvalue().encode('utf-8-sig'), media_type='text/csv', headers={
        'Content-Disposition': 'attachment; filename="FabTrace_Spool_BOM_Template.csv"',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/files/{document_id}')
def document_file(document_id: str, download: bool = False, user: Employee = Depends(auth), s: Session = Depends(db)):
    document = s.get(SpoolDocument, document_id)
    if document is None:
        _fail('Spool document not found.', 404)
    doc_set = s.get(SpoolDocumentSet, document.set_id)
    _target(s, 'requirements' if doc_set.requirement_id else 'spools', doc_set.requirement_id or doc_set.spool_id)
    stored = s.get(SpoolDocumentFile, document.id)
    content = stored.content if stored else None
    if content is None or len(content) != document.size_bytes or hashlib.sha256(content).hexdigest() != document.sha256:
        _fail('The saved document could not be verified. Contact an administrator.', 503)
    disposition = 'attachment' if download or document.media_type != 'application/pdf' else 'inline'
    fallback = re.sub(r'[^a-zA-Z0-9._ -]', '_', document.filename)
    # Native PDF viewers create browser-owned plugin/frame content. CSP sandbox
    # blocks embedded PDFs in WebKit, while default-src 'none' can also block
    # viewer resources. Keep same-origin embedding protection without applying
    # HTML execution restrictions to a validated, action-sanitized PDF response.
    # This response-only change also fixes previously uploaded revisions.
    policy = ("frame-ancestors 'self'" if document.media_type == 'application/pdf'
              else "sandbox; default-src 'none'; frame-ancestors 'self'")
    return Response(content, media_type=document.media_type, headers={
        'Content-Disposition': f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{quote(document.filename)}',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': policy,
        'X-Frame-Options': 'SAMEORIGIN'})


@router.get('/{scope}/{identity}')
def document_detail(scope: str, identity: str, user: Employee = Depends(auth), s: Session = Depends(db)):
    role = user.role
    s.rollback()
    with read_snapshot(s) as snapshot:
        return _detail(snapshot, scope, identity, role)


@router.post('/{scope}/{identity}/preview')
def preview_documents(scope: str, identity: str, kind: str = Form(...),
                      files: list[UploadFile] = File(...), sheet: str = Form(''),
                      user: Employee = Depends(auth), s: Session = Depends(db)):
    if not _can_upload(user):
        _fail('Your position can view spool documents but cannot upload them.', 403)
    context, item, requirement = _target(s, scope, identity)
    locked = _locked_reason(s, scope, identity, item, requirement)
    if locked:
        _fail(locked, 409)
    prepared = _prepare(files, kind, sheet.strip(), context)
    return {key: value for key, value in prepared.items() if key != 'content'}


@router.post('/{scope}/{identity}/upload')
def upload_documents(scope: str, identity: str, kind: str = Form(...),
                     files: list[UploadFile] = File(...), expected_version: int = Form(...),
                     expected_sha256: str = Form(...), revision: str = Form(''),
                     reason: str = Form(...), sheet: str = Form(''),
                     user: Employee = Depends(auth), s: Session = Depends(db)):
    if not _can_upload(user):
        _fail('Your position can view spool documents but cannot upload them.', 403)
    revision, reason, sheet = revision.strip(), reason.strip(), sheet.strip()
    if not 4 <= len(reason) <= 3000:
        _fail('Enter an upload or revision reason of 4–3,000 characters.')
    if len(revision) > 80 or len(sheet) > 200 or expected_version < 0:
        _fail('The document revision, worksheet or saved version is invalid.')
    if any(ord(character) < 32 for character in revision):
        _fail('Use a document revision without control characters.')
    # Parse without holding the topology lock, then re-check scope and version
    # under the same lock used by release, removal and production writers.
    initial_context, _, _ = _target(s, scope, identity)
    prepared = _prepare(files, kind, sheet, initial_context)
    if prepared['sheet_required']:
        _fail('Choose the worksheet containing the selected spool BOM, then preview it again.')
    if prepared['selection_sha256'] != expected_sha256:
        _fail('The file selection changed after preview. Preview these files again before saving.', 409)
    lock_topology(s)
    s.expire_all()
    if not _can_upload(user):
        _fail('Your position can view spool documents but cannot upload them.', 403)
    if scope == 'spools':
        lock_item(s, identity)
    context, item, requirement = _target(s, scope, identity)
    if context != initial_context:
        _fail('The selected spool scope changed while these files were being read. Reopen the spool and preview again.', 409)
    locked = _locked_reason(s, scope, identity, item, requirement)
    if locked:
        _fail(locked, 409)
    doc_set = _set_for(s, scope, identity)
    if expected_version != (doc_set.version if doc_set else 0):
        _fail('Spool documents have changed. Reload the saved documents before uploading this revision.', 409)
    if doc_set:
        stored_size = s.scalar(select(func.sum(SpoolDocument.size_bytes)).where(SpoolDocument.set_id == doc_set.id)) or 0
        if stored_size + prepared['size_bytes'] > MAX_SCOPE_BYTES:
            _fail('This spool document history exceeds the 256 MiB limit. Contact an administrator.', 413)
    else:
        doc_set = SpoolDocumentSet(id='sds_' + uuid.uuid4().hex,
            requirement_id=identity if scope == 'requirements' else None,
            spool_id=identity if scope == 'spools' else None, scope_snapshot=context,
            version=0, created_by=user.badge)
        s.add(doc_set)
        s.flush()
    doc_set.version += 1
    document = SpoolDocument(id='sd_' + uuid.uuid4().hex, set_id=doc_set.id, kind=kind,
        version=doc_set.version, filename=prepared['filename'], media_type=prepared['media_type'],
        size_bytes=prepared['size_bytes'], sha256=prepared['sha256'],
        selection_sha256=prepared['selection_sha256'], page_count=prepared['page_count'],
        revision=revision, reason=reason, uploaded_by=user.badge,
        source_files=prepared['source_files'], bom=prepared['bom'])
    s.add(document)
    s.flush()
    s.add(SpoolDocumentFile(document_id=document.id, content=prepared['content']))
    audit(s, item.id if item else None, user.badge, 'SPOOL_DOCUMENT_UPLOADED', {
        'document_id': document.id, 'kind': kind, 'scope_kind': context['kind'],
        'scope_id': identity, 'project_id': context['project_id'],
        'spool_number': context['spool_number'], 'version': doc_set.version,
        'sha256': document.sha256, 'revision': revision, 'reason': reason})
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        _fail('Spool documents changed while this upload was saving. Reload the saved documents before retrying.', 409)
    return _detail(s, scope, identity, user)


def _physical_documents(s, item_id):
    item = s.get(Item, item_id)
    if item is None:
        return []
    if item.kind == 'Assembly':
        result = []
        for child, _ in effective_children(s, item.id, include_removed=False):
            if child.kind == 'Spool':
                result.extend(_physical_documents(s, child.id))
        return result
    if item.kind != 'Spool':
        return []
    registration = s.get(OrderSpool, item.id)
    requirement = s.get(OrderSpoolRequirement, registration.requirement_id) if registration else None
    _, _, active, rows, _, _ = _effective(s, 'spools', item.id, requirement)
    return [(item.id, active[kind], rows[kind]) for kind in ('bom', 'isometric') if active[kind]]


def spool_document_scope_basis(s, item_id):
    """Exact effective uploaded versions for quality and Job Packet fingerprints."""
    keys = ('kind', 'scope_kind', 'scope_id', 'version', 'sha256', 'revision',
            'filename', 'page_count', 'media_type', 'size_bytes')
    return sorted([{'spool_id': spool_id, 'document_id': metadata['id'],
                    **{key: metadata[key] for key in keys}}
                   for spool_id, metadata, _ in _physical_documents(s, item_id)],
                  key=lambda value: (value['spool_id'], value['kind'], value['document_id']))


def spool_document_packet_files(s, item_id):
    """Current active document bytes; issued packets must retain exact IDs."""
    result = []
    for spool_id, metadata, document in _physical_documents(s, item_id):
        result.append({'spool_id': spool_id, **spool_document_retained_file(s, document.id)})
    return result


def spool_document_retained_file(s, document_id):
    """Read a frozen issue's exact immutable document, even after scope removal.

    This internal helper deliberately does not resolve today's effective file or
    apply current active-scope guards. Its caller must authorize the issued
    packet and supply only document IDs retained in that packet's snapshot.
    """
    document = s.get(SpoolDocument, document_id)
    stored = s.get(SpoolDocumentFile, document_id) if document else None
    content = stored.content if stored else None
    if content is None or len(content) != document.size_bytes or hashlib.sha256(content).hexdigest() != document.sha256:
        _fail('A retained spool document could not be verified for the Job Packet.', 503)
    return {'document_id': document.id, 'kind': document.kind, 'filename': document.filename,
            'media_type': document.media_type, 'sha256': document.sha256,
            'size_bytes': document.size_bytes, 'content': content}
