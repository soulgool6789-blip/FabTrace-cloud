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
                       header_at_top=False, footer_override=None):
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
        text(55, 700, 'Drawing geometry is intentionally omitted. These materials are test data.', 10)
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
