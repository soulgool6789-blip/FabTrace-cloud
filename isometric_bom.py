"""Read per-spool BOMs from complete isometrics and standalone ruled tables.

The parser binds a grid to its own spool footer and never chooses a production
record. It preserves source quantities and cut lengths; ambiguous grids are
reported instead of repaired or assigned by a filename. Pages without readable
text can use an optional local OCR provider with the same table contract.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import io
import math
import re
from typing import Callable

import pdfplumber


MAX_EXTRACTION_PAGES = 50
MAX_TABLE_LINES = 500
MAX_PAGE_CHARACTERS = 60_000
MAX_PAGE_EDGES = 12_000
MAX_TABLES_PER_PAGE = 50
EXTRACTION_VERSION = 2

# No drawing IDs, spool prefixes, part numbers, or row values are hardcoded.
_FOOTER = re.compile(
    r'["\u201c\u201d]([^"\u201c\u201d\r\n]{1,120})["\u201c\u201d]\s*'
    r'QTY\.?\s*SHOWN\s*FOR\s*(?:ONE\s*\(\s*1\s*\)|1\b)', re.I)
_HEADERS = {
    'item': {'ITEM', 'ITEMNO', 'ITEMNUMBER', 'POS', 'POSITION', 'MARK'},
    'quantity': {'QTY', 'QUANTITY', 'QUANTITYEA', 'QTYEA'},
    'part_number': {'TASLN', 'TASPART', 'TASPARTNO', 'TASPARTNUMBER',
                    'TASLNNUMBER', 'PART', 'PARTNO', 'PARTNUMBER', 'MATERIALCODE'},
    'description': {'DESCRIPTION', 'MATERIALDESCRIPTION', 'PARTDESCRIPTION'},
    'length': {'LENGTH', 'CUTLENGTH', 'LENGTHIN', 'LENGTHMM'},
    'material': {'MATERIAL', 'MATERIALSPEC', 'MATERIALSPECIFICATION'},
    'unit': {'UNIT', 'UNITS', 'UOM'},
    'size': {'SIZE', 'NPS', 'NOMINALSIZE'},
}


def _text(value) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _key(value) -> str:
    return re.sub(r'[^A-Z0-9]', '', _text(value).upper())


def _identity(value) -> str:
    return _text(value).casefold()


def _header(row):
    mapping = {}
    for column, value in enumerate(row):
        key = _key(value)
        for name, aliases in _HEADERS.items():
            if key in aliases:
                if name in mapping:
                    return None
                mapping[name] = column
    return mapping if {'item', 'quantity', 'description'} <= mapping.keys() else None


def _value(row, mapping, name):
    column = mapping.get(name)
    return _text(row[column]) if column is not None and column < len(row) else ''


def _quantity(value):
    raw = _text(value)
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', raw):
        return None
    try:
        quantity = Decimal(raw.replace(',', ''))
        if not quantity.is_finite() or not 0 < quantity <= 1_000_000:
            return None
        return int(quantity) if quantity == quantity.to_integral_value() else float(quantity)
    except (InvalidOperation, OverflowError, ValueError):
        return None


def _short_pipe_cut(description, length):
    """Flag a printed sub-inch pipe cut without changing its source value."""
    if not re.match(r'^PIPE\b', description, re.I):
        return False
    match = re.fullmatch(r'\s*(?:(\d+)\s+)?(\d+)\s*/\s*(\d+)\s*(?:["\u2033]|in(?:ches)?\.?)\s*', length, re.I)
    if not match:
        return False
    whole, numerator, denominator = match.groups()
    return not int(whole or 0) and 0 < int(numerator) < int(denominator)


def _title_block(page):
    """Bind drawing/revision to labels in the page's bottom-right title block."""
    words = page.crop((page.width * .5, page.height * .91,
                       page.width, page.height)).extract_words(x_tolerance=2, y_tolerance=2)
    drawing = revision = ''
    drawing_labels = [w for w in words if _key(w['text']) in {'DWG', 'DRAWING'}]
    if drawing_labels:
        label = max(drawing_labels, key=lambda w: w['x0'])
        same_row = [w for w in words if abs(w['top'] - label['top']) < 6]
        next_labels = [w for w in same_row if w['x0'] > label['x1']
                       and _key(w['text']) in {'SHEET', 'REV', 'REVISION'}]
        right = min((w['x0'] for w in next_labels), default=page.width)
        values = [w for w in words if label['x0'] <= w['x0'] < right
                  and w['top'] > label['top'] + 1
                  and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*[-_/][A-Za-z0-9._/-]+', w['text'])]
        if len(values) == 1:
            drawing = _text(values[0]['text'])
    revision_labels = [w for w in words if _key(w['text']) in {'REV', 'REVISION'}]
    if revision_labels:
        label = max(revision_labels, key=lambda w: w['x0'])
        values = [w for w in words if w['x0'] >= label['x0']
                  and w['top'] > label['top'] + 1
                  and re.fullmatch(r'[A-Za-z0-9]{1,12}', w['text'])]
        unique = {_text(w['text']) for w in values}
        if len(unique) == 1:
            revision = unique.pop()
    return drawing, revision


def _native_page(page):
    """Use vector grid edges; text inside a drawing view is never a BOM row."""
    # Preserve the bounded engineering-sheet region: CAD page borders and view
    # geometry can otherwise connect many cells into one enormous false table.
    drawing, revision = _title_block(page)
    crop = page.crop((page.width * .45, page.height * .30,
                      page.width, page.height * .94))
    focused = []
    if len(crop.edges) <= MAX_PAGE_EDGES:
        tables = crop.find_tables()
        if len(tables) <= MAX_TABLES_PER_PAGE:
            focused = [{'rows': table.extract(x_tolerance=2, y_tolerance=2),
                         'bbox': list(table.bbox)} for table in tables]
    labeled = any(any(_header(row) for row in table['rows']) and
                  any(_FOOTER.search(' '.join(_text(cell) for cell in row)) for row in table['rows'])
                  for table in focused)
    if drawing and labeled:
        return {'tables': focused, 'drawing': drawing, 'revision': revision,
                'drawing_geometry': _native_geometry(page, [table['bbox'] for table in focused
                    if any(_header(row) for row in table['rows'])]), 'warnings': []}
    # A standalone BOM can occupy the full page or have a header at its top.
    # Only use this fallback when the complete isometric layout was not found.
    if len(page.edges) > MAX_PAGE_EDGES:
        return {'tables': focused if labeled else [], 'drawing': drawing, 'revision': revision,
                'drawing_geometry': _native_geometry(page) if drawing else False,
                'warnings': ['The rest of this page has too many grid edges to extract safely.']}
    tables = page.find_tables()
    if len(tables) > MAX_TABLES_PER_PAGE:
        return {'tables': [], 'warnings': ['The lower-right drawing area has too many tables to identify a spool BOM safely.']}
    return {'tables': [{'rows': table.extract(x_tolerance=2, y_tolerance=2),
                         'bbox': list(table.bbox)} for table in tables],
            'drawing': drawing, 'revision': revision,
            'drawing_geometry': _native_geometry(page) if drawing else False, 'warnings': []}


def _native_geometry(page, table_boxes=()):
    """Require long oblique drawing edges away from material and title tables.

    Borders, letters and a lower-right BOM on an otherwise empty drawing
    template do not establish that the uploaded page contains an isometric.
    """
    minimum = min(float(page.width), float(page.height))
    count, length = 0, 0.0
    for edge in page.edges[:MAX_PAGE_EDGES]:
        dx, dy = edge.get('x1', 0) - edge.get('x0', 0), edge.get('bottom', 0) - edge.get('top', 0)
        middle_x = (edge.get('x0', 0) + edge.get('x1', 0)) / 2
        middle_y = (edge.get('top', 0) + edge.get('bottom', 0)) / 2
        if any(box[0] <= middle_x <= box[2] and box[1] <= middle_y <= box[3] for box in table_boxes):
            continue
        if (dx > minimum * .025 and dy > minimum * .025 and page.width * .05 < middle_x < page.width * .96
                and page.height * .08 < middle_y < page.height * .74):
            count += 1
            length += math.hypot(dx, dy)
            if count >= 2 and length >= minimum * .16:
                return True
    return False


def _has_scanned_bom_area(page):
    """A scan may have a small native title or OCR layer around a raster BOM."""
    # Keep the original focused-area check for hybrid CAD PDFs whose title and
    # geometry are native but whose relatively small lower-right BOM is raster.
    for x0, top, x1, bottom in ((page.width * .45, page.height * .30, page.width, page.height * .94),
                                (0, 0, page.width, page.height)):
        area = (x1 - x0) * (bottom - top)
        covered = sum(max(0, min(x1, image['x1']) - max(x0, image['x0'])) * max(
            0, min(bottom, image['bottom']) - max(top, image['top'])) for image in page.images)
        if covered > area * .20:
            return True
    return False


def _parse_table(table, page_number, drawing, revision, source_method):
    rows = table.get('rows') or []
    if len(rows) > MAX_TABLE_LINES + 10:
        return None, f'A BOM grid exceeds the automatic extraction limit of {MAX_TABLE_LINES} material rows.'
    headers = [(i, _header(row)) for i, row in enumerate(rows)]
    headers = [(i, mapping) for i, mapping in headers if mapping]
    if not headers:
        return None, None
    if len(headers) != 1:
        return None, 'Multiple BOM headers share one grid; the spool rows could not be separated.'
    header_index, mapping = headers[0]
    footers = []
    for index, row in enumerate(rows):
        text = ' '.join(_text(value) for value in row if value is not None)
        for match in _FOOTER.finditer(text):
            footers.append((index, _text(match.group(1))))
    if len(footers) > 1:
        return None, ('A BOM grid contains multiple spool-number footers; no spool assignment was guessed.')
    footer_index, spool_number = footers[0] if footers else (len(rows), '')
    if spool_number and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/ -]{0,119}', spool_number):
        return None, 'The BOM footer has an unsupported or unreadable spool number.'
    if not footers:
        # Generic invoices and arbitrary prose must not become spool material
        # records. An unlabeled table needs material-oriented headings in
        # addition to Item, Quantity and Description, with no commercial header.
        header_keys = {_key(value) for value in rows[header_index]}
        commercial = {'PRICE', 'UNITPRICE', 'AMOUNT', 'EXTENDEDPRICE', 'TOTALPRICE', 'TOTALCOST', 'INVOICE'}
        if not {'part_number', 'material', 'length', 'size'}.intersection(mapping) or header_keys.intersection(commercial):
            return None, 'This unlabeled table is not an unambiguous material BOM; no spool assignment was guessed.'
        if any(re.search(r'\b(?:MATERIAL\s+LIST|BILL\s+OF\s+MATERIALS?)\s+FOR\s+(?:AN?\s+)?ASSEMBLY\b',
                         ' '.join(_text(value) for value in row), re.I) for row in rows):
            return None, 'This is labeled as an assembly material list, without a unique per-spool footer; no spool assignment was guessed.'
    def material_row(row):
        return any(_value(row, mapping, field) for field in
                   ('description', 'quantity', 'part_number', 'length', 'material', 'size'))
    before = [row for row in rows[:header_index] if material_row(row)]
    after = [row for row in rows[header_index + 1:footer_index] if material_row(row)]
    if before and after:
        return None, 'Material rows appear on both sides of one header; the BOM boundary needs manual review.'
    source_rows = before or after
    if not source_rows or len(source_rows) > MAX_TABLE_LINES:
        return None, f'Spool {spool_number} has no readable BOM rows or exceeds {MAX_TABLE_LINES} rows.'
    warnings = [_text(warning) for warning in table.get('warnings', [])]
    errors = []
    lines = []
    deleted_items = []
    seen_items = set()
    if not footers:
        warnings.append('No spool number or per-one quantity footer is printed on this BOM. Choose the correct spool and confirm that these quantities are for one spool.')
    if not drawing:
        warnings.append('Drawing number could not be read from the title block. Verify it against the full drawing.')
    if not revision:
        warnings.append('Drawing revision could not be read from the title block. Verify the revision against the full drawing.')
    if 'part_number' not in mapping:
        warnings.append('The BOM grid has no recognized part-number column. Verify all part numbers.')
    for position, row in enumerate(source_rows, 1):
        item = _value(row, mapping, 'item')
        description = _value(row, mapping, 'description')
        quantity_text = _value(row, mapping, 'quantity')
        part_number = _value(row, mapping, 'part_number')
        if description.upper() in {'DELETE', 'DELETED', 'OMIT', 'OMITTED'} and not quantity_text:
            deleted_items.append(item or f'row {position}')
            continue
        quantity = _quantity(quantity_text)
        if not item or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,39}', item):
            errors.append(f'Row {position} has a missing or unreadable item number.')
        elif item in seen_items:
            errors.append(f'Item {item} occurs more than once in this BOM grid.')
        seen_items.add(item)
        if quantity is None:
            errors.append(f'Item {item or position} has a missing or invalid quantity ({quantity_text or "blank"}).')
        if not description:
            errors.append(f'Item {item or position} has no readable description.')
        notes = [_text(note) for note in table.get('row_notes', {}).get(str(position), [])]
        if not part_number:
            notes.append('Part-number field is blank or unreadable in the source. Verify before using this BOM.')
            warnings.append(f'Item {item or position}: part-number field is blank or unreadable.')
        if quantity is not None and not isinstance(quantity, int):
            warnings.append(f'Item {item or position}: quantity {quantity_text} is fractional; verify its unit and basis.')
        length = _value(row, mapping, 'length')
        if _short_pipe_cut(description, length):
            message = f'The drawing lists a short pipe cut of {length}. Verify it with the drawing owner before cutting.'
            notes.append(message)
            warnings.append(f'Item {item}: {message}')
        lines.append({'item': item, 'quantity': quantity, 'unit': _value(row, mapping, 'unit') or 'EA',
                      'part_number': part_number, 'description': description,
                      'size': _value(row, mapping, 'size'), 'material': _value(row, mapping, 'material'),
                      'length': length, 'notes': ' '.join(notes), 'drawing': drawing,
                      'revision': revision, 'source_page': page_number})
    if not lines:
        return None, f'Spool {spool_number} has no material rows after source-deleted items are excluded.'
    if errors:
        warnings.extend('Correction required: ' + error for error in errors)
    if deleted_items:
        warnings.append('Source-deleted items excluded: ' + ', '.join(deleted_items) + '.')
    numeric_items = [int(line['item']) for line in lines if line['item'].isdigit()]
    if len(numeric_items) == len(lines):
        numeric_deleted = {int(item) for item in deleted_items if item.isdigit()}
        # A numeric mark may be a large identifier; do not allocate a range
        # controlled by that untrusted value or assume it is a row count.
        expected = set(range(1, max(numeric_items) + 1)) if max(numeric_items) <= MAX_TABLE_LINES * 4 else set()
        missing = sorted(expected - set(numeric_items) - numeric_deleted)
        if missing:
            warnings.append('Item sequence has missing numbers: ' + ', '.join(map(str, missing[:20])) +
                            '. Verify that all source rows are visible.')
        lines.sort(key=lambda line: int(line['item']))
    if source_method == 'ocr':
        warnings.append('Read from a scan using local OCR. Review every item, quantity, part number and cut length against the drawing.')
    return {'spool_number': spool_number, 'drawing': drawing, 'revision': revision,
            'source_pages': [page_number], 'quantity_basis': 'one_spool', 'lines': lines,
            'line_count': len(lines), 'warnings': warnings, 'review_required': bool(warnings),
            'source_method': source_method, 'table_bbox': table.get('bbox'),
            'deleted_items': deleted_items, 'validation_errors': errors,
            'has_spool_footer': bool(footers), 'quantity_basis_verified': bool(footers)}, None


def _record_kind(record, page_width, page_height, drawing_geometry=False):
    """Only positive full-sheet evidence permits replacing a saved drawing.

    A crop can retain a valid spool footer but still is only a material table.
    Require separate drawing geometry plus a small, labeled lower-right grid.
    A title value may be unreadable in a scan and remains explicitly blank.
    Everything else recognized as a BOM remains a BOM source conservatively.
    """
    bbox = record.get('table_bbox')
    if (not drawing_geometry or not record.get('has_spool_footer')
            or not bbox or len(bbox) != 4):
        return 'bom'
    x0, top, x1, bottom = bbox
    area = max(0, x1 - x0) * max(0, bottom - top)
    if (page_width > 0 and page_height > 0 and x0 >= page_width * .38
            and top >= page_height * .12 and bottom <= page_height * .97
            and area < page_width * page_height * .40):
        return 'isometric'
    return 'bom'


def _is_assembly(record, footer_ids):
    number = _identity(record['spool_number'])
    # Assembly BOMs contain complete child-spool IDs, normally without a TAS
    # component number. This uses observed document identities, not ID patterns.
    if any(_identity(line['description']) in footer_ids - {number}
           for line in record['lines']):
        return 'Assembly BOM containing child spools; assembly mounting hardware is not a spool BOM.'
    if record['drawing'] and number == _identity(record['drawing']):
        return ('BOM footer matches the assembly/drawing number; it does not identify a distinct spool. '
                'This table was excluded from automatic spool assignment.')
    return ''


def extract_isometric_boms(pdf_bytes: bytes, filename: str = '', *,
                           ocr_page_provider: Callable | None = None) -> dict:
    """Return independent, reviewable spool BOM candidates from complete PDF bytes.

    ``ocr_page_provider(pdf_bytes, page_number, width, height)`` may return a
    dictionary containing ``tables=[{rows: [[...]], bbox: [x0, top, x1, bottom]}]``,
    ``drawing``, ``revision``, and ``warnings``. OCR tables must retain the header
    and quoted per-one spool footer. Coordinates use PDF points with a top-left
    origin. The provider must be local/bounded; this module makes no network calls.

    Full document bytes are never changed. Source page numbers are 1-based PDF
    page numbers, so the app can link each candidate back to the retained file.
    """
    result = {'status': 'no_bom', 'page_count': 0, 'candidates': [], 'warnings': [],
              'unreadable_pages': [], 'excluded_pages': [],
              'extraction_version': EXTRACTION_VERSION, 'classification': 'unknown',
              'classification_reason': 'No recognizable spool material table was found.',
              'drawing_pages': []}
    source_hash = hashlib.sha256(pdf_bytes).hexdigest()
    records = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            result['page_count'] = len(pdf.pages)
            if len(pdf.pages) > MAX_EXTRACTION_PAGES:
                result['warnings'].append(
                    f'Automatic BOM extraction is limited to the first {MAX_EXTRACTION_PAGES} pages. '
                    f'All {len(pdf.pages)} drawing pages are retained; later pages need separate BOM review.')
                result['unreadable_pages'].extend(range(MAX_EXTRACTION_PAGES + 1, len(pdf.pages) + 1))
            for index, page in enumerate(pdf.pages[:MAX_EXTRACTION_PAGES], 1):
                try:
                    character_count = len(page.chars)
                    if character_count > MAX_PAGE_CHARACTERS:
                        result['unreadable_pages'].append(index)
                        result['warnings'].append(f'Page {index}: too much drawing text to extract safely.')
                        continue
                    method = 'native_pdf'
                    if character_count < 20:
                        if ocr_page_provider is None:
                            result['unreadable_pages'].append(index)
                            result['warnings'].append(
                                f'Page {index}: no readable PDF text. Keep the drawing and supply a text PDF or upload the reviewed BOM separately.')
                            continue
                        method = 'ocr'
                        page_data = ocr_page_provider(pdf_bytes, index, float(page.width), float(page.height)) or {}
                    else:
                        page_data = _native_page(page)
                        native_bom = any(any(_header(row) for row in table.get('rows', []))
                                         for table in page_data.get('tables', []))
                        if not native_bom and _has_scanned_bom_area(page):
                            if ocr_page_provider is None:
                                result['unreadable_pages'].append(index)
                                result['warnings'].append(f'Page {index}: the lower-right BOM area is scanned and has no readable native table.')
                                continue
                            method = 'ocr'
                            page_data = ocr_page_provider(pdf_bytes, index, float(page.width), float(page.height)) or {}
                    for warning in page_data.get('warnings', []):
                        result['warnings'].append(f'Page {index}: {_text(warning)}')
                    if page_data.get('drawing_geometry') and (page_data.get('drawing') or page_data.get('title_block_evidence')):
                        result['drawing_pages'].append(index)
                    tables = page_data.get('tables') or []
                    if len(tables) > MAX_TABLES_PER_PAGE:
                        result['unreadable_pages'].append(index)
                        result['warnings'].append(f'Page {index}: too many OCR tables to extract safely.')
                        continue
                    found_bom = False
                    for table_index, table in enumerate(tables):
                        record, error = _parse_table(table, index, _text(page_data.get('drawing')),
                                                     _text(page_data.get('revision')), method)
                        if error:
                            found_bom = True
                            result['warnings'].append(f'Page {index}: {error}')
                            result['excluded_pages'].append({'page': index, 'reason': error})
                        if record:
                            found_bom = True
                            record['document_kind'] = _record_kind(record, float(page.width), float(page.height),
                                                                  bool(page_data.get('drawing_geometry')))
                            key = f'{source_hash}:{index}:{table_index}:{record["spool_number"]}'
                            record['candidate_id'] = 'ibom_' + hashlib.sha256(key.encode()).hexdigest()[:24]
                            records.append(record)
                    if not found_bom:
                        if method == 'ocr':
                            result['unreadable_pages'].append(index)
                            result['warnings'].append(f'Page {index}: OCR did not identify a complete, uniquely labeled spool BOM.')
                        result['excluded_pages'].append({'page': index, 'reason': 'No recognized per-spool BOM grid on this drawing page.'})
                except Exception as exc:
                    # A malformed or unsupported page cannot silently remove the
                    # remaining pages from a full drawing or fabricate BOM data.
                    result['unreadable_pages'].append(index)
                    result['warnings'].append(f'Page {index}: BOM extraction could not read this page ({type(exc).__name__}).')
                finally:
                    page.close()
    except Exception as exc:
        result['status'] = 'invalid_pdf'
        result['warnings'].append(f'The PDF could not be read for BOM extraction ({type(exc).__name__}).')
        return result
    footer_ids = {_identity(record['spool_number']) for record in records}
    if result['drawing_pages'] or any(record['document_kind'] == 'isometric' for record in records):
        result['classification'] = 'isometric'
        result['classification_reason'] = 'Drawing views and their title or labeled spool BOM were recognized in the complete uploaded page set.'
    for record in records:
        reason = _is_assembly(record, footer_ids)
        if reason:
            result['excluded_pages'].append({'page': record['source_pages'][0], 'reason': reason})
            continue
        result['candidates'].append(record)
    if result['classification'] == 'unknown' and result['candidates']:
        result['classification'] = 'bom'
        result['classification_reason'] = 'A material BOM table was recognized without enough evidence of a complete isometric sheet.'
    # Repeated spool IDs may be duplicate pages, alternatives, or continuation
    # pages. Do not sum them or choose one revision without an explicit review.
    identities = {}
    for candidate in result['candidates']:
        if candidate['spool_number']:
            identities.setdefault(_identity(candidate['spool_number']), []).append(candidate)
    for group in identities.values():
        if len(group) > 1:
            pages = ', '.join(str(candidate['source_pages'][0]) for candidate in group)
            for candidate in group:
                candidate['warnings'].append(f'This spool number appears in multiple BOM grids on pages {pages}. Select the intended source; rows were not combined.')
                candidate['review_required'] = True
    result['unreadable_pages'] = sorted(set(result['unreadable_pages']))
    if result['candidates']:
        result['status'] = 'partial' if (result['warnings'] or result['unreadable_pages'] or
                                        any(c['validation_errors'] for c in result['candidates'])) else 'ready'
    elif result['unreadable_pages']:
        result['status'] = 'needs_ocr'
    return result
