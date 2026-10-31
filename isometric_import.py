"""Reviewed, atomic spool BOM extraction and shared complete drawing imports.

Preview tokens retain the signed extraction result, so saving a reviewed table
does not repeat OCR or trust client-supplied source attribution. Exact order
requirements, never a number in another order, determine document inheritance.
"""
from collections import Counter
from contextlib import contextmanager
import copy
import datetime as dt
import hashlib
import io
import json
import re
import threading
from urllib.parse import quote
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from main import Employee, JWT_SECRET, audit, auth, db, jwt, lock_item, utcnow
from flow import lock_topology
from order_setup import OrderSpoolRequirement
from order_spools import OrderSpool
from orders import _key
from removals import item_not_removed
from isometric_bom import extract_isometric_boms
from spool_documents import (
    BOM_COLUMNS, MAX_LINES, MAX_SCOPE_BYTES, XLSX_MEDIA, SpoolDocument,
    SpoolDocumentFile, SpoolDocumentFileLink, SpoolDocumentSet, _bom_grid,
    _can_upload, _detail, _fail, _locked_reason, _metadata,
    _prepare, _safe_filename, _set_for, _stamp, _stored_file, _target, _text,
)


router = APIRouter()
TOKEN_AUDIENCE = 'fabtrace-isometric-import'
MAX_TARGETS = 200
MAX_PACKAGE_LINES = 10_000
# Starlette bounds each non-file multipart part at 1 MiB. Keep the complete
# signed token plus reviewed rows comfortably below that parser boundary.
MAX_REVIEW_BYTES = 900 * 1024
MAX_TOKEN_BYTES = 400 * 1024
_WORK_SLOT = threading.BoundedSemaphore(1)
EXCEL_COLUMNS = ['spool_number', *BOM_COLUMNS, 'drawing', 'revision', 'source_page']


@contextmanager
def _work_slot():
    # OCR is intentionally bounded to one request per worker on small hosts.
    # Acquire before reading files or rendering PDFs, and release on every error.
    if not _WORK_SLOT.acquire(blocking=False):
        _fail('Another drawing is being prepared. Please retry this review in a moment.', 429)
    try:
        yield
    finally:
        _WORK_SLOT.release()


def _json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _require_writer(user):
    if not _can_upload(user):
        _fail('Your position can view spool documents but cannot upload them.', 403)


def _saved_source(s, document_id, origin):
    document = s.get(SpoolDocument, document_id)
    if document is None or document.kind not in ('isometric', 'bom') or document.media_type != 'application/pdf':
        _fail('Choose a saved drawing or BOM PDF from this assembly or spool.', 404)
    doc_set = s.get(SpoolDocumentSet, document.set_id)
    source_scope = 'requirements' if doc_set.requirement_id else 'spools'
    source_identity = doc_set.requirement_id or doc_set.spool_id
    source_context, _, _ = _target(s, source_scope, source_identity)
    if origin['kind'] == 'requirement':
        allowed = (origin['gpn_id'] is not None and source_context['gpn_id'] == origin['gpn_id']
                   and source_context['project_id'] == origin['project_id']
                   and source_context['requirement_id'] is not None)
    else:
        allowed = ((source_scope == 'spools' and source_identity == origin['item_id'])
                   or (source_scope == 'requirements' and source_identity == origin['requirement_id']))
    if not allowed:
        _fail('This saved drawing belongs to a different purchase order, assembly or physical spool.', 409)
    content, owner_id = _stored_file(s, document)
    return {'kind': document.kind, 'filename': document.filename, 'media_type': document.media_type,
            'size_bytes': document.size_bytes, 'sha256': document.sha256,
            'selection_sha256': document.selection_sha256, 'page_count': document.page_count,
            'source_files': document.source_files, 'bom': None, 'content': content,
            'source_document_id': document.id, 'owner_document_id': owner_id,
            'source_scope': source_context}


def _source(s, origin, files, document_id):
    if bool(files) == bool(document_id):
        _fail('Choose either drawing files or one saved isometric for this review.')
    if document_id:
        return _saved_source(s, document_id, origin)
    prepared = _prepare(files, 'isometric', '', origin)
    return {**prepared, 'source_document_id': None, 'owner_document_id': None}


def _source_view(prepared, extraction=None, source_mode='auto'):
    document_id = prepared['source_document_id']
    classification = (extraction or {}).get('classification', 'unknown')
    document_kind = source_mode if source_mode in ('bom', 'isometric') else (
        classification if classification in ('bom', 'isometric') else None)
    return {'kind': 'saved' if document_id else 'upload', 'document_id': document_id,
            'filename': prepared['filename'], 'sha256': prepared['sha256'],
            'selection_sha256': prepared['selection_sha256'],
            'page_count': prepared['page_count'],
            'document_kind': document_kind, 'classification': classification,
            'classification_reason': (extraction or {}).get('classification_reason', ''),
            'source_mode': source_mode,
            'view_url': '/api/spool-documents/files/' + document_id if document_id else None}


def _target_view(s, scope, identity, user):
    context, item, requirement = _target(s, scope, identity)
    local = _set_for(s, scope, identity)
    inherited = (_set_for(s, 'requirements', requirement.id)
                 if scope == 'spools' and requirement is not None else None)
    active = {'bom': None, 'isometric': None}
    # A package may have many targets. Read only small current metadata here,
    # never every target's full historical material grids and provenance.
    for doc_set in (local, inherited):
        if doc_set is None:
            continue
        for kind in active:
            if active[kind] is None:
                revision = s.execute(select(SpoolDocument.revision).where(
                    SpoolDocument.set_id == doc_set.id, SpoolDocument.kind == kind)
                    .order_by(SpoolDocument.version.desc()).limit(1)).first()
                if revision is not None:
                    active[kind] = {'revision': revision[0], 'inherited': doc_set is inherited}
    locked = _locked_reason(s, scope, identity, item, requirement)
    return {'scope_kind': context['kind'], 'requirement_id': context['requirement_id'],
            'spool_id': context['item_id'], 'spool_number': context['spool_number'],
            'version': local.version if local else 0,
            'editable': _can_upload(user) and not locked, 'locked_reason': locked,
            'has_bom': active['bom'] is not None, 'has_isometric': active['isometric'] is not None,
            'bom_revision': active['bom']['revision'] if active['bom'] else '',
            'isometric_revision': active['isometric']['revision'] if active['isometric'] else '',
            'has_local_bom': bool(active['bom'] and not active['bom']['inherited']),
            'has_local_isometric': bool(active['isometric'] and not active['isometric']['inherited']),
            'context': context}


def _targets(s, scope, identity, origin, user):
    if scope == 'spools':
        return [_target_view(s, scope, identity, user)]
    requirements = list(s.scalars(select(OrderSpoolRequirement).where(
        OrderSpoolRequirement.gpn_id == origin['gpn_id'], OrderSpoolRequirement.active.is_(True))
        .order_by(OrderSpoolRequirement.spool_number, OrderSpoolRequirement.id).limit(MAX_TARGETS + 1)))
    if len(requirements) > MAX_TARGETS:
        _fail(f'An isometric review supports up to {MAX_TARGETS} spool requirements in one assembly.')
    targets = [_target_view(s, scope, requirement.id, user) for requirement in requirements]
    overrides = _override_counts(s, [requirement.id for requirement in requirements])
    for target in targets:
        target['physical_override_count'] = overrides.get(target['requirement_id'], 0)
    return targets


def _override_counts(s, requirement_ids):
    if not requirement_ids:
        return {}
    return dict(s.execute(select(OrderSpool.requirement_id, func.count())
        .join(SpoolDocumentSet, SpoolDocumentSet.spool_id == OrderSpool.item_id)
        .where(OrderSpool.requirement_id.in_(requirement_ids), SpoolDocumentSet.version > 0,
               item_not_removed(OrderSpool.item_id))
        .group_by(OrderSpool.requirement_id)).all())


def _override_warning(number, count):
    return (f'{number}: {count} individual spool document override(s) stay in effect. '
            'The shared setup documents remain accessible in each spool\'s History.')


def _extract(content, filename):
    # The native parser works without an OCR runtime. The bounded local OCR
    # provider, when installed, is loaded only by this review workflow.
    from isometric_ocr import LocalOCRProvider
    with LocalOCRProvider() as provider:
        return extract_isometric_boms(content, filename, ocr_page_provider=provider)


def _candidate_views(extraction, targets, scope):
    candidates = copy.deepcopy(extraction['candidates'])
    counts = Counter(_key(candidate['spool_number']) for candidate in candidates)
    for candidate in candidates:
        matches = [target for target in targets if candidate['spool_number']
                   and _key(target['spool_number']) == _key(candidate['spool_number'])]
        target = matches[0] if len(matches) == 1 else None
        candidate['assignment_basis'] = 'spool_number' if target else None
        eligible = [value for value in targets if value['editable']]
        if not candidate['spool_number'] and len(candidates) == 1 and len(eligible) == 1:
            target = eligible[0]
            candidate['assignment_basis'] = 'selected_scope'
            candidate['review_required'] = True
            candidate['warnings'].append('This standalone BOM has no printed spool identity. Confirm the selected spool and the one-spool quantity basis before saving.')
        candidate['matched_requirement_id'] = (target['requirement_id'] if target and scope == 'requirements' else None)
        candidate['matched_spool_id'] = target['spool_id'] if target and scope == 'spools' else None
        candidate['selected'] = bool(target and target['editable'] and counts[_key(candidate['spool_number'])] == 1)
        if not target:
            candidate['review_required'] = True
            candidate['warnings'].append('Choose the correct spool in this purchase order and assembly; no assignment was guessed.')
        elif counts[_key(candidate['spool_number'])] > 1:
            candidate['review_required'] = True
    return candidates


@router.post('/{scope}/{identity}/isometric-preview')
def preview_isometric(scope: str, identity: str, files: list[UploadFile] | None = File(None),
                      document_id: str = Form(''), source_mode: str = Form('auto'),
                      user: Employee = Depends(auth), s: Session = Depends(db)):
    _require_writer(user)
    if source_mode not in ('auto', 'bom', 'isometric'):
        _fail('Choose automatic detection, BOM source, or complete isometric.')
    with _work_slot():
        origin, _, _ = _target(s, scope, identity)
        prepared = _source(s, origin, files, document_id.strip())
        extraction = _extract(prepared['content'], prepared['filename'])
        if (len(extraction['candidates']) > MAX_TARGETS
                or sum(len(candidate['lines']) for candidate in extraction['candidates']) > MAX_PACKAGE_LINES):
            _fail('This drawing contains too many material lines for one review. Upload a smaller drawing set.')
        # Refresh target identities and permissions after potentially slow OCR.
        s.expire_all()
        _require_writer(user)
        current, _, _ = _target(s, scope, identity)
        if current != origin:
            _fail('The selected spool scope changed while the drawing was read. Reopen it and preview again.', 409)
        if prepared['source_document_id']:
            _saved_source(s, prepared['source_document_id'], current)
        targets = _targets(s, scope, identity, current, user)
        candidates = _candidate_views(extraction, targets, scope)
        warnings = list(extraction.get('warnings', []))
        warnings.extend(_override_warning(target['spool_number'], target['physical_override_count'])
                        for target in targets if target.get('physical_override_count'))
        source = _source_view(prepared, extraction, source_mode)
        claim = {'aud': TOKEN_AUDIENCE, 'sub': user.badge, 'iat': utcnow(),
                 'exp': utcnow() + dt.timedelta(minutes=30), 'jti': uuid.uuid4().hex,
                 'scope': scope, 'identity': identity, 'origin': current, 'source': source,
                 'targets': targets, 'extraction': extraction}
        token = jwt.encode(claim, JWT_SECRET, algorithm='HS256')
        if len(token) > MAX_TOKEN_BYTES:
            _fail('This drawing review is too large to save. Upload a smaller drawing set or the per-spool BOMs separately.', 413)
        # Include every candidate as an upper bound on the default selection;
        # unmatched tables can be assigned during review. Maximum reason and
        # revision lengths leave those ordinary edits enough payload space.
        estimated_review = {'preview_token': token, 'reviewed': True, 'revision': 'R' * 80,
            'reason': 'R' * 3000, 'mappings': [{'candidate_id': candidate['candidate_id'],
                'requirement_id' if scope == 'requirements' else 'spool_id': 'x' * 60,
                'expected_version': 999999999, 'lines': candidate['lines']}
                for candidate in candidates]}
        if len(json.dumps(estimated_review, ensure_ascii=False).encode()) > MAX_REVIEW_BYTES:
            _fail('This drawing review is too large to save. Upload a smaller drawing set or the per-spool BOMs separately.', 413)
        return {'kind': 'isometric', 'package': True, 'context': current, 'source': source,
                'preview_token': token, 'targets': targets, 'candidates': candidates,
                'status': extraction['status'], 'warnings': warnings,
                'warning_count': len(warnings) + sum(len(candidate.get('warnings', [])) for candidate in candidates),
                'unreadable_pages': extraction.get('unreadable_pages', []),
                'excluded_pages': extraction.get('excluded_pages', [])}


def _review(review, scope, identity, user):
    if len(review.encode()) > MAX_REVIEW_BYTES:
        _fail('This BOM review is too large to save. Select fewer spools or upload a smaller drawing set.', 413)
    try:
        value = json.loads(review)
    except (ValueError, TypeError, RecursionError):
        _fail('The reviewed drawing information is invalid. Preview the drawing again.')
    if not isinstance(value, dict) or value.get('reviewed') is not True:
        _fail('Review the selected spool assignments and material rows before saving.')
    token = value.get('preview_token')
    if not isinstance(token, str) or len(token) > MAX_TOKEN_BYTES:
        _fail('The drawing review token is invalid. Preview again.', 409)
    try:
        claim = jwt.decode(token, JWT_SECRET, algorithms=['HS256'], audience=TOKEN_AUDIENCE,
                           options={'require': ['exp', 'sub', 'aud', 'iat', 'jti']})
    except jwt.InvalidTokenError:
        _fail('This drawing review expired or changed. Preview again before saving.', 409)
    if claim.get('sub') != user.badge or claim.get('scope') != scope or claim.get('identity') != identity:
        _fail('This drawing review belongs to another spool or employee. Preview again.', 409)
    revision, reason = value.get('revision', ''), value.get('reason', '')
    if not isinstance(revision, str) or not isinstance(reason, str):
        _fail('Enter a valid revision and review reason.')
    revision, reason = revision.strip(), reason.strip()
    if len(revision) > 80 or any(ord(char) < 32 for char in revision):
        _fail('Use a document revision of at most 80 characters without control characters.')
    if not 4 <= len(reason) <= 3000:
        _fail('Enter a review or revision reason of 4–3,000 characters.')
    mappings = value.get('mappings')
    if not isinstance(mappings, list) or not 1 <= len(mappings) <= MAX_TARGETS:
        _fail('Select at least one corresponding spool and its reviewed BOM.')
    return claim, mappings, revision, reason


def _reviewed_bom(lines, candidate, context):
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        _fail(f'Each spool needs between 1 and {MAX_LINES} material lines.')
    rows, items = [EXCEL_COLUMNS], set()
    for index, line in enumerate(lines, 1):
        if not isinstance(line, dict):
            _fail(f'Material row {index} is invalid.')
        for field in BOM_COLUMNS:
            value = line.get(field, '')
            if value is not None and (not isinstance(value, (str, int, float)) or isinstance(value, bool)):
                _fail(f'Material row {index} has an invalid {field.replace("_", " ")}.')
        item = _text(line.get('item'), 160)
        if not item:
            _fail(f'Material row {index} needs its drawing item number.')
        item_key = str(int(item)) if item.isascii() and item.isdecimal() else _key(item)
        if item_key in items:
            _fail(f'Drawing item {item} appears more than once. Review and resolve duplicate material rows before saving.')
        items.add(item_key)
        # Drawing context is retained from the signed source, not reassigned by
        # editable cells. Per-spool fields below reflect the selected target.
        values = {**{field: line.get(field, '') for field in BOM_COLUMNS},
                  'spool_number': context['spool_number'], 'drawing': candidate.get('drawing', ''),
                  'revision': candidate.get('revision', ''),
                  'source_page': ', '.join(str(page) for page in candidate['source_pages'])}
        rows.append([values.get(field, '') for field in EXCEL_COLUMNS])
    bom = _bom_grid(rows, context['spool_number'], context['assembly_number'], 'BOM')
    bom['warnings'] = list(candidate.get('warnings', []))
    bom['source_pages'] = candidate['source_pages']
    return bom


def _material_values(lines):
    """Comparable reviewed fields; source blanks stay blank for provenance."""
    return [{field: (line.get(field) if field == 'quantity' else
                     _text(line.get(field), 2000 if field == 'notes' else 1000)
                     or ('EA' if field == 'unit' else ''))
             for field in BOM_COLUMNS} for line in lines]


def _write_text(cell, value):
    # Excel must treat all source text literally, including =, +, - and @.
    # Assigning strings with an '=' prefix normally creates an executable formula.
    cell.value = str(value or '')
    cell.data_type = 's'
    cell.number_format = '@'
    cell.alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)


def build_bom_excel(bom, context, *, source=None, revision='', provenance=None):
    """Generate one import-compatible, formula-free Excel BOM for one spool."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'BOM'
    sheet.sheet_view.showGridLines = False
    last_column = get_column_letter(len(EXCEL_COLUMNS))
    sheet.merge_cells(f'A1:{last_column}1')
    _write_text(sheet['A1'], 'FABTRACE  |  SPOOL BILL OF MATERIAL')
    sheet['A1'].font = Font(name='Aptos', size=17, bold=True, color='FFFFFF')
    sheet['A1'].fill = PatternFill('solid', fgColor='17304B')
    sheet.row_dimensions[1].height = 32
    meta = [('Spool', context.get('spool_number', '')), ('Purchase order', context.get('purchase_order', '')),
            ('Assembly', context.get('assembly_number', '')), ('Document revision', revision),
            ('Source drawing', (source or {}).get('filename', 'Uploaded BOM')),
            ('Source pages', ', '.join(str(page) for page in bom.get('source_pages', []))),
            ('Quantity basis', 'One spool; quantities are not multiplied by assembly or order quantity.')]
    for row_number, (label, value) in enumerate(meta, 3):
        _write_text(sheet.cell(row_number, 1), label)
        sheet.cell(row_number, 1).font = Font(name='Aptos', bold=True, color='17304B')
        sheet.merge_cells(start_row=row_number, start_column=2, end_row=row_number, end_column=len(EXCEL_COLUMNS))
        _write_text(sheet.cell(row_number, 2), value)
    start = 11
    for column, field in enumerate(EXCEL_COLUMNS, 1):
        _write_text(sheet.cell(start, column), field)
        sheet.cell(start, column).font = Font(name='Aptos', bold=True, color='FFFFFF')
        sheet.cell(start, column).fill = PatternFill('solid', fgColor='17304B')
    for row_number, line in enumerate(bom['lines'], start + 1):
        for column, field in enumerate(EXCEL_COLUMNS, 1):
            cell = sheet.cell(row_number, column)
            value = line.get(field, context.get('spool_number', '') if field == 'spool_number' else '')
            if field == 'quantity':
                cell.value = value
                cell.number_format = '0' if float(value).is_integer() else '0.########'
            else:
                _write_text(cell, value)
            cell.font = Font(name='Aptos', size=10)
            cell.alignment = Alignment(horizontal='center' if field in ('quantity', 'unit') else 'left',
                                       vertical='top', wrap_text=True)
        sheet.row_dimensions[row_number].height = 42
    table = Table(displayName='SpoolBOM', ref=f'A{start}:{last_column}{start + len(bom["lines"])}')
    table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2', showRowStripes=True)
    sheet.add_table(table)
    for column, width in zip('ABCDEFGHIJKLM', [30, 9, 12, 9, 18, 64, 14, 19, 20, 62, 23, 13, 15]):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = f'F{start + 1}'
    sheet.print_title_rows = f'1:{start}'
    sheet.print_options.horizontalCentered = True
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.print_area = f'A1:{last_column}{start + len(bom["lines"])}'
    notes = workbook.create_sheet('Source and review')
    notes.column_dimensions['A'].width = 28
    notes.column_dimensions['B'].width = 110
    details = [('Reference status', 'Reviewed drawing reference; not a material receipt, heat trace or QA acceptance.'),
               ('Spool', context.get('spool_number', '')),
               ('Source filename', (source or {}).get('filename', '')),
               ('Source SHA-256', (source or {}).get('sha256', '')),
               ('Reviewed by', (provenance or {}).get('reviewed_by', '')),
               ('Reviewed at', (provenance or {}).get('reviewed_at', '')),
               ('Source spool', (provenance or {}).get('source_spool_number', '')),
               ('Source pages', ', '.join(str(page) for page in bom.get('source_pages', []))),
               ('Review changes', 'Yes' if (provenance or {}).get('edited') else 'No'),
               *[('Drawing warning', value) for value in bom.get('warnings', [])]]
    for row_number, (label, value) in enumerate(details, 1):
        _write_text(notes.cell(row_number, 1), label)
        _write_text(notes.cell(row_number, 2), value)
        notes.cell(row_number, 1).font = Font(bold=True, color='17304B')
        notes.cell(row_number, 2).alignment = Alignment(horizontal='left', wrap_text=True, vertical='top')
        notes.row_dimensions[row_number].height = 32 if len(str(value)) > 100 else 22
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _append(s, doc_set, prepared, user, revision, reason, owner_id=None):
    doc_set.version += 1
    document = SpoolDocument(id='sd_' + uuid.uuid4().hex, set_id=doc_set.id,
        version=doc_set.version, revision=revision, reason=reason, uploaded_by=user.badge,
        **{field: prepared[field] for field in ('kind', 'filename', 'media_type', 'size_bytes',
             'sha256', 'selection_sha256', 'page_count', 'source_files', 'bom')})
    s.add(document)
    s.flush()
    if owner_id:
        s.add(SpoolDocumentFileLink(document_id=document.id, source_document_id=owner_id))
    else:
        s.add(SpoolDocumentFile(document_id=document.id, content=prepared['content']))
    return document


def _active_isometric(s, doc_set, context):
    inherited = (_set_for(s, 'requirements', context['requirement_id'])
                 if context['kind'] == 'spool' and context['requirement_id'] else None)
    for candidate_set in (doc_set, inherited):
        if candidate_set is None:
            continue
        document = s.scalar(select(SpoolDocument).where(SpoolDocument.set_id == candidate_set.id,
            SpoolDocument.kind == 'isometric').order_by(SpoolDocument.version.desc()).limit(1))
        if document is not None:
            return _metadata(document, candidate_set, inherited=candidate_set is inherited)
    return None


@router.post('/{scope}/{identity}/isometric-import')
def import_isometric(scope: str, identity: str, review: str = Form(...),
                     files: list[UploadFile] | None = File(None),
                     user: Employee = Depends(auth), s: Session = Depends(db)):
    _require_writer(user)
    with _work_slot():
        claim, mappings, revision, reason = _review(review, scope, identity, user)
        origin, _, _ = _target(s, scope, identity)
        if origin != claim['origin']:
            _fail('The selected assembly or spool changed after review. Preview again.', 409)
        prepared = _source(s, origin, files, claim['source'].get('document_id'))
        if _source_view(prepared, claim['extraction'], claim['source'].get('source_mode', 'auto')) != claim['source']:
            _fail('The drawing selection changed after preview. Preview these files again before saving.', 409)
        prepared['kind'] = claim['source'].get('document_kind')
        if prepared['kind'] not in ('bom', 'isometric'):
            _fail('The file contents were not identified. Choose BOM source or complete drawing and preview again.')
        candidates = {candidate['candidate_id']: candidate for candidate in claim['extraction']['candidates']}
        identity_field = 'requirement_id' if scope == 'requirements' else 'spool_id'
        targets = {target[identity_field]: target for target in claim['targets']}
        plans, seen_targets, seen_candidates, line_count = [], set(), set(), 0
        for mapping in mappings:
            if not isinstance(mapping, dict):
                _fail('A selected spool assignment is invalid.')
            target_id, candidate_id = mapping.get(identity_field), mapping.get('candidate_id')
            if not isinstance(target_id, str) or not isinstance(candidate_id, str):
                _fail('Select the corresponding spool for every material table.')
            if target_id not in targets or candidate_id not in candidates:
                _fail('A selected spool or material table is outside this drawing review.', 409)
            if target_id in seen_targets or candidate_id in seen_candidates:
                _fail('Choose each spool and source table once. Duplicate tables are not automatically combined.')
            seen_targets.add(target_id)
            seen_candidates.add(candidate_id)
            target, candidate = targets[target_id], candidates[candidate_id]
            version = mapping.get('expected_version')
            if type(version) is not int or version != target['version']:
                _fail('The saved spool version does not match its drawing preview. Refresh the review.', 409)
            bom = _reviewed_bom(mapping.get('lines'), candidate, target['context'])
            line_count += bom['line_count']
            if line_count > MAX_PACKAGE_LINES:
                _fail('This review contains too many material lines. Select fewer spools.')
            plans.append({'target_id': target_id, 'target': target, 'candidate': candidate, 'bom': bom})

        # One lock covers identity, release, removal, versions and all writes.
        # Nothing is committed until every selected spool has passed its checks.
        lock_topology(s)
        s.expire_all()
        _require_writer(user)
        current_origin, _, _ = _target(s, scope, identity)
        if current_origin != origin:
            _fail('The selected assembly or spool changed while the drawing was read. Preview again.', 409)
        if prepared['source_document_id']:
            current_source = _saved_source(s, prepared['source_document_id'], current_origin)
            if current_source['source_scope'] != prepared['source_scope']:
                _fail('The saved drawing scope changed. Preview again.', 409)
        for plan in plans:
            if scope == 'spools':
                lock_item(s, plan['target_id'])
            current = _target_view(s, scope, plan['target_id'], user)
            if current['context'] != plan['target']['context']:
                _fail('A selected spool changed its assembly or number. Refresh this drawing review.', 409)
            if not current['editable']:
                _fail(current['locked_reason'] or 'You cannot update documents for this spool.', 409)
            if current['version'] != plan['target']['version']:
                _fail('Documents for a selected spool changed after preview. Refresh the drawing review.', 409)

        package_id = 'sip_' + uuid.uuid4().hex
        reviewed_at = _stamp(utcnow())
        owner_id = prepared['owner_document_id']
        results, warnings = [], list(claim['extraction'].get('warnings', []))
        created_sources = 0
        overrides = _override_counts(s, [plan['target_id'] for plan in plans]) if scope == 'requirements' else {}
        for plan in plans:
            target_id, target, candidate, bom = plan['target_id'], plan['target'], plan['candidate'], plan['bom']
            context = target['context']
            if overrides.get(target_id):
                warnings.append(_override_warning(context['spool_number'], overrides[target_id]))
            doc_set = _set_for(s, scope, target_id)
            existing_query = select(SpoolDocument).where(
                SpoolDocument.set_id == doc_set.id, SpoolDocument.kind == prepared['kind']) if doc_set else None
            if existing_query is not None and prepared['kind'] == 'bom':
                existing_query = existing_query.where(SpoolDocument.media_type == 'application/pdf',
                                                      SpoolDocument.sha256 == prepared['sha256'])
            existing_source = s.scalar(existing_query.order_by(SpoolDocument.version.desc()).limit(1)) if existing_query is not None else None
            keep_source = bool(existing_source and existing_source.sha256 == prepared['sha256'])
            provenance = {'package_id': package_id, 'candidate_id': candidate['candidate_id'],
                'source_spool_number': candidate['spool_number'], 'source_pages': candidate['source_pages'],
                'source_sha256': prepared['sha256'], 'source_selection_sha256': prepared['selection_sha256'],
                'input_document_id': prepared['source_document_id'], 'source_filename': prepared['filename'],
                'source_document_kind': prepared['kind'],
                'source_classification': claim['source']['classification'],
                'source_mode': claim['source']['source_mode'],
                'source_method': candidate.get('source_method', 'native_pdf'),
                'extraction_version': candidate.get('extraction_version'),
                'original_lines': candidate['lines'], 'original_lines_sha256': _json_hash(candidate['lines']),
                'reviewed_lines_sha256': _json_hash(bom['lines']),
                'edited': _material_values(bom['lines']) != _material_values(candidate['lines']),
                'manually_assigned': _key(candidate['spool_number']) != _key(context['spool_number']),
                'reviewed_by': user.badge, 'reviewed_at': reviewed_at,
                'warnings': candidate.get('warnings', []),
                'source_validation_errors': candidate.get('validation_errors', [])}
            bom['provenance'] = provenance
            content = build_bom_excel(bom, context, source=claim['source'],
                                      revision=revision or candidate.get('revision', ''), provenance=provenance)
            size = len(content) + (0 if keep_source else prepared['size_bytes'])
            stored_size = (s.scalar(select(func.sum(SpoolDocument.size_bytes))
                .where(SpoolDocument.set_id == doc_set.id)) or 0) if doc_set else 0
            if stored_size + size > MAX_SCOPE_BYTES:
                _fail('A selected spool document history exceeds the 256 MiB limit. Contact an administrator.', 413)
            if doc_set is None:
                doc_set = SpoolDocumentSet(id='sds_' + uuid.uuid4().hex,
                    requirement_id=target_id if scope == 'requirements' else None,
                    spool_id=target_id if scope == 'spools' else None, scope_snapshot=context,
                    version=0, created_by=user.badge)
                s.add(doc_set)
                s.flush()
            if keep_source:
                source_document = existing_source
                _, existing_owner_id = _stored_file(s, source_document)
                if owner_id is None:
                    owner_id = existing_owner_id
            else:
                source_document = _append(s, doc_set, prepared, user,
                    revision or candidate.get('revision', ''), reason, owner_id=owner_id)
                created_sources += 1
                if owner_id is None:
                    owner_id = source_document.id
            provenance['source_document_id'] = source_document.id
            if prepared['kind'] == 'isometric':
                provenance['isometric_document_id'] = source_document.id
            digest = hashlib.sha256(content).hexdigest()
            bom_prepared = {'kind': 'bom', 'filename': _safe_filename(context['spool_number'] + '_BOM.xlsx'),
                'media_type': XLSX_MEDIA, 'size_bytes': len(content), 'sha256': digest,
                'selection_sha256': digest, 'page_count': None, 'content': content, 'bom': bom,
                'source_files': prepared['source_files']}
            document = _append(s, doc_set, bom_prepared, user, revision or candidate.get('revision', ''), reason)
            audit(s, context['item_id'], user.badge,
                'ISOMETRIC_SPOOL_BOM_IMPORTED' if prepared['kind'] == 'isometric' else 'BOM_SOURCE_IMPORTED', {
                'package_id': package_id, 'scope_kind': context['kind'], 'scope_id': target_id,
                'project_id': context['project_id'], 'gpn_id': context['gpn_id'],
                'spool_number': context['spool_number'], 'candidate_id': candidate['candidate_id'],
                'source_document_id': source_document.id, 'source_document_kind': prepared['kind'],
                'isometric_document_id': source_document.id if prepared['kind'] == 'isometric' else None,
                'bom_document_id': document.id,
                'source_sha256': prepared['sha256'], 'bom_sha256': digest,
                'source_pages': candidate['source_pages'], 'edited': provenance['edited'],
                'manually_assigned': provenance['manually_assigned'], 'reason': reason})
            warnings.extend(candidate.get('warnings', []))
            drawing = _active_isometric(s, doc_set, context)
            results.append({'requirement_id': context['requirement_id'], 'spool_id': context['item_id'],
                'spool_number': context['spool_number'], 'version': doc_set.version,
                'has_bom': True, 'has_isometric': drawing is not None,
                'saved_kinds': ['bom', 'isometric'] if prepared['kind'] == 'isometric' and not keep_source else ['bom'],
                'bom_document': _metadata(document, doc_set),
                'source_document': _metadata(source_document, doc_set),
                'isometric_document': drawing})
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            _fail('Spool documents changed while saving. Refresh this drawing review before retrying.', 409)
        detail = _detail(s, scope, identity, user)
        warnings = list(dict.fromkeys(warnings))
        detail['package_result'] = {'package_id': package_id, 'count': len(results),
            'source_document_kind': prepared['kind'], 'source_document_count': created_sources,
            'bom_count': len(results),
            'created_isometric_count': sum('isometric' in row['saved_kinds'] for row in results),
            'requirements': results if scope == 'requirements' else [],
            'spools': results if scope == 'spools' else [], 'warnings': warnings, 'warning_count': len(warnings)}
        return detail


@router.get('/files/{document_id}/bom.xlsx')
def download_bom_excel(document_id: str, user: Employee = Depends(auth), s: Session = Depends(db)):
    document = s.get(SpoolDocument, document_id)
    if document is None or document.kind != 'bom' or not document.bom or not document.bom.get('lines'):
        _fail('This document does not have a tabular BOM to download as Excel.', 404)
    doc_set = s.get(SpoolDocumentSet, document.set_id)
    _target(s, 'requirements' if doc_set.requirement_id else 'spools', doc_set.requirement_id or doc_set.spool_id)
    retained, _ = _stored_file(s, document)
    if document.media_type == XLSX_MEDIA and document.bom.get('provenance'):
        content = retained
    else:
        content = build_bom_excel(document.bom, doc_set.scope_snapshot,
            source={'filename': document.filename, 'sha256': document.sha256}, revision=document.revision)
    filename = _safe_filename(doc_set.scope_snapshot['spool_number'] + '_BOM.xlsx')
    fallback = re.sub(r'[^a-zA-Z0-9._ -]', '_', filename)
    return Response(content, media_type=XLSX_MEDIA, headers={
        'Content-Disposition': f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename)}',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "sandbox; default-src 'none'; frame-ancestors 'self'",
        'X-Frame-Options': 'SAMEORIGIN'})
