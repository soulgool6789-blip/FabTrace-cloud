"""Small, synthetic vector isometrics for extraction/API/browser verification.

These are invented test drawings, not customer manufacturing drawings.
"""
import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


DEFAULT_ROWS = [
    ['2', '1', '000456', 'PIPE CARBON STEEL 4 IN SCH 40', '16 3/4"', 'A53B'],
    ['1', '2', '000123', 'FLANGE WELDNECK 4 IN CLASS 150', '', 'A105'],
]


def _pdf_string(value):
    return str(value).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def make_isometric_pdf(spools=None, *, drawing='TEST-100', revision='A',
                       include_assembly=True, extra_blank_pages=0,
                       header_at_top=False, footer_override=None, include_geometry=True):
    """Generate a PDF; spools=[{'number': '...', 'rows': [[6 cells], ...]}].

    Each table has item, quantity, TAS part number, description, length and
    material columns. Spool pages contain a lower-right grid and a distinct
    DWG/REV title block. Optional assembly page lists the child spool IDs.
    """
    if spools is None:
        spools = [{'number': 'TEST-100-SPOOL-01', 'rows': DEFAULT_ROWS},
                  {'number': 'TEST-100-SPOOL-02', 'rows': DEFAULT_ROWS}]
    writer = PdfWriter()
    pages = []
    if include_assembly:
        assembly_rows = [[str(len(spools) + 1), '2', '009999', 'ASSEMBLY MOUNTING U-BOLT', '', 'HDG']]
        assembly_rows += [[str(i + 1), '1', '', spool['number'], '', ''] for i, spool in enumerate(spools)]
        pages.append((drawing, assembly_rows))
    pages += [(spool['number'], spool.get('rows', DEFAULT_ROWS)) for spool in spools]
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    font_ref = writer._add_object(font)
    total_pages = len(pages) + extra_blank_pages
    for page_number, (number, rows) in enumerate(pages, 1):
        page = writer.add_blank_page(width=1200, height=800)
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): font_ref})})
        ops = ['0.5 w']

        def text(x, y, value, size=8):
            ops.append(f'BT /F1 {size} Tf 1 0 0 1 {x} {y} Tm ({_pdf_string(value)}) Tj ET')

        text(50, 740, 'SYNTHETIC ISOMETRIC TEST DRAWING', 14)
        text(55, 700, 'Invented pipe geometry and materials for testing only.', 10)
        if include_geometry:
            for offset in (0, 14):
                ops.append(f'145 {420 + offset} m 360 {544 + offset} l 540 {440 + offset} l S')
        headers = ['ITEM', 'QTY', 'TAS PART #', 'DESCRIPTION', 'LENGTH', 'MATERIAL']
        table_rows = [headers, *rows] if header_at_top else [*rows, headers]
        cols = [610, 646, 686, 752, 1040, 1114, 1180]
        row_height, bottom = 24, 110
        top = bottom + len(table_rows) * row_height
        for x in cols:
            ops.append(f'{x} {bottom} m {x} {top} l S')
        for row_index in range(len(table_rows) + 1):
            y = top - row_index * row_height
            ops.append(f'{cols[0]} {y} m {cols[-1]} {y} l S')
        for row_index, row in enumerate(table_rows):
            for column, value in enumerate(row):
                # Text only needs to fit this tiny verification fixture. Tests
                # needing wrapped descriptions may include an explicit newline.
                for line_index, line in enumerate(str(value).split('\n')):
                    text(cols[column] + 4, top - (row_index + 1) * row_height + 9 - line_index * 8, line, 7)
        ops.extend([f'{cols[0]} {bottom} m {cols[0]} {bottom - 24} l S',
                    f'{cols[-1]} {bottom} m {cols[-1]} {bottom - 24} l S',
                    f'{cols[0]} {bottom - 24} m {cols[-1]} {bottom - 24} l S'])
        footer = footer_override if footer_override is not None else f'"{number}" QTY. SHOWN FOR ONE (1); ONE (1) REQ\'D'
        text(cols[0] + 5, bottom - 15, footer, 8)
        text(930, 35, 'DWG. NO.', 7)
        text(1080, 35, 'SHEET', 7)
        text(1125, 35, 'OF', 7)
        text(1160, 35, 'REV.', 7)
        text(940, 19, drawing, 9)
        text(1090, 19, page_number, 9)
        text(1132, 19, total_pages, 9)
        text(1167, 19, revision, 9)
        stream = DecodedStreamObject()
        stream.set_data('\n'.join(ops).encode('latin-1'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    for _ in range(extra_blank_pages):
        writer.add_blank_page(width=1200, height=800)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def make_bom_pdf(*, spool_number='', rows=None, table_count=1, header_at_top=True,
                 commercial=False):
    """A standalone ruled material table, with no full-drawing title block."""
    rows = DEFAULT_ROWS if rows is None else rows
    writer = PdfWriter()
    height = 90 + table_count * (32 * (len(rows) + 1) + (32 if spool_number else 0) + 45)
    page = writer.add_blank_page(width=900, height=height)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    ops = ['0.8 w']
    def text(x, y, value, size=10):
        ops.append(f'BT /F1 {size} Tf 1 0 0 1 {x} {y} Tm ({_pdf_string(value)}) Tj ET')
    text(20, height - 25, 'INVOICE' if commercial else 'BILL OF MATERIAL', 15)
    columns = [20, 70, 120, 230, 650, 760, 880]
    headers = ['ITEM', 'QTY', 'PART NUMBER', 'DESCRIPTION', 'LENGTH', 'UNIT PRICE' if commercial else 'MATERIAL']
    top = height - 55
    for _ in range(table_count):
        table_rows = [headers, *rows] if header_at_top else [*rows, headers]
        bottom = top - len(table_rows) * 32
        for x in columns:
            ops.append(f'{x} {bottom} m {x} {top} l S')
        for index in range(len(table_rows) + 1):
            y = top - index * 32
            ops.append(f'{columns[0]} {y} m {columns[-1]} {y} l S')
        for index, row in enumerate(table_rows):
            for column, value in enumerate(row):
                text(columns[column] + 4, top - (index + 1) * 32 + 12, value, 9)
        if spool_number:
            ops.extend([f'{columns[0]} {bottom} m {columns[0]} {bottom - 32} l S',
                        f'{columns[-1]} {bottom} m {columns[-1]} {bottom - 32} l S',
                        f'{columns[0]} {bottom - 32} m {columns[-1]} {bottom - 32} l S'])
            text(columns[0] + 5, bottom - 21, f'"{spool_number}" QTY. SHOWN FOR ONE (1); ONE (1) REQ\'D', 10)
            bottom -= 32
        top = bottom - 45
    stream = DecodedStreamObject()
    stream.set_data('\n'.join(ops).encode('latin-1'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
