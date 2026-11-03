"""Reviewed BOM source facts are assigned only to their physical piece/copy."""
import csv
import io

from openpyxl import Workbook, load_workbook

from receiving_helpers import adopt_current_bom
from test_order_labels import generate, labels, public_qr_url
from test_progress import database_state
from test_spool_documents import ROOT, NUMBER, requirement_path, request_upload, setup
from test_spool_receiving import create_spool
from tracking_helpers import ok


HEADINGS = ['Spool number', 'Item', 'Qty', 'Description', 'Unit', 'Heat No.',
            'MTR Reference', 'Supplier Piece ID', 'Traceability Scope',
            'Physical Spool ID', 'Spool Label', 'MTR Link']


def source(rows, number=NUMBER):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(HEADINGS)
    for row in rows:
        writer.writerow([number, row.get('item', '1'), row.get('qty', 1),
            row.get('description', 'Weldneck flange'), 'EA', row.get('heat', ''),
            row.get('mtr', ''), row.get('piece', ''), row.get('scope', ''),
            row.get('spool_id', ''), row.get('label', ''), row.get('url', '')])
    return out.getvalue().encode('utf-8')


def upload(api, path, rows, **kwargs):
    return request_upload(api, path, files=[('Trace-BOM.csv', source(rows), 'text/csv')], **kwargs)


def material_detail(api, item_id):
    return ok(api.get('/api/spool-boms/spools/' + item_id))


def test_import_assigns_distinct_heat_mtr_to_each_duplicate_material_piece(api):
    spool_id = create_spool(api, 'IMPORTED-TRACE', NUMBER)
    before = database_state(api)
    rows = [{'heat': '000123', 'mtr': 'MTR-001', 'piece': 'P-001'},
            {'heat': '000456', 'mtr': '=literal-reference', 'piece': 'P-002'}]
    preview = ok(api.request('POST', ROOT + '/spools/' + spool_id + '/preview',
        data={'kind': 'bom'}, files=[('files', ('Trace.csv', source(rows), 'text/csv'))]))
    assert preview['bom']['lines'][0]['heat_number'] == '000123'
    assert preview['bom']['lines'][1]['mtr_reference'] == '=literal-reference'
    assert database_state(api) == before
    saved = ok(upload(api, ROOT + '/spools/' + spool_id, rows))
    detail = material_detail(api, spool_id)
    materials = detail['traceability']['materials']
    assert [(row['heat_number'], row['mtr_reference'], row['supplier_piece_id']) for row in materials] == [
        ('000123', 'MTR-001', 'P-001'), ('000456', '=literal-reference', 'P-002')]
    assert len({row['piece_key'] for row in materials}) == 2
    assert all(row['persisted'] and row['qa001']['status'] == 'pending' for row in materials)
    assert detail['arrival']['status'] == 'pending'
    assert detail['mtr_documents']['current'] == []
    workbook = load_workbook(io.BytesIO(api.get(saved['active']['bom']['excel_url']).content), data_only=False)
    sheet = workbook['BOM']
    headings = {cell.value: cell.column for cell in sheet[11]}
    assert sheet.cell(12, headings['heat_number']).value == '000123'
    mtr = sheet.cell(13, headings['mtr_reference'])
    assert mtr.value == '=literal-reference' and mtr.data_type == 's'
    workbook.close()


def test_quantity_heat_assignment_requires_explicit_whole_line_scope(api):
    spool_id = create_spool(api, 'QUANTITY-TRACE', NUMBER)
    path = ROOT + '/spools/' + spool_id
    before = database_state(api)
    invalid = upload(api, path, [{'qty': 2, 'heat': 'H-1', 'mtr': 'M-1'}])
    assert invalid.status_code == 422 and 'every piece' in invalid.text
    assert database_state(api) == before
    ok(upload(api, path, [{'qty': 2, 'heat': 'H-1', 'mtr': 'M-1', 'scope': 'all pieces'}]))
    rows = material_detail(api, spool_id)['traceability']['materials']
    assert len(rows) == 2 and len({row['piece_key'] for row in rows}) == 2
    assert all(row['heat_number'] == 'H-1' and row['mtr_reference'] == 'M-1' for row in rows)


def test_missing_material_values_stay_missing(api):
    spool_id = create_spool(api, 'MISSING-TRACE', NUMBER)
    ok(upload(api, ROOT + '/spools/' + spool_id, [{'heat': 'H-ONLY'}, {'item': '2', 'mtr': 'M-ONLY'}]))
    rows = material_detail(api, spool_id)['traceability']['materials']
    assert [(row['heat_number'], row['mtr_reference']) for row in rows] == [('H-ONLY', ''), ('', 'M-ONLY')]


def test_shared_requirement_does_not_fan_out_physical_lot_facts(api):
    saved = setup(api, number='SHARED-TRACE', quantity=2)
    ok(upload(api, requirement_path(saved), [{'heat': 'H-UNASSIGNED', 'mtr': 'M-UNASSIGNED'}]))
    generate(api, saved['order']['project_id'])
    children = labels(api, saved['order']['project_id'])['items']
    assert len(children) == 2
    for child in children:
        detail = material_detail(api, child['id'])
        assert detail['trace_import_warnings']
        assert all(not row['heat_number'] and not row['mtr_reference'] for row in detail['traceability']['materials'])


def test_explicit_all_copies_source_assigns_only_its_requirement_members(api):
    saved = setup(api, number='ALL-COPIES-TRACE', quantity=2)
    foreign = setup(api, number='OTHER-COPIES-TRACE', quantity=1)
    ok(upload(api, requirement_path(saved), [{'heat': 'H-SHARED', 'mtr': 'M-SHARED', 'scope': 'all copies'}]))
    generate(api, saved['order']['project_id'])
    generate(api, foreign['order']['project_id'])
    for child in labels(api, saved['order']['project_id'])['items']:
        row = material_detail(api, child['id'])['traceability']['materials'][0]
        assert (row['heat_number'], row['mtr_reference']) == ('H-SHARED', 'M-SHARED')
    for child in labels(api, foreign['order']['project_id'])['items']:
        assert material_detail(api, child['id'])['traceability']['materials'] == []


def test_shared_rows_target_exact_physical_copy_by_label(api):
    saved = setup(api, number='EXACT-COPY-TRACE', quantity=2)
    generate(api, saved['order']['project_id'])
    first, second = labels(api, saved['order']['project_id'])['items']
    ok(upload(api, requirement_path(saved), [
        {'heat': 'H-A', 'mtr': 'M-A', 'piece': 'P-A', 'label': first['display_code']},
        {'heat': 'H-B', 'mtr': 'M-B', 'piece': 'P-B', 'label': second['display_code']}]))
    for child, heat, line in ((first, 'H-A', 1), (second, 'H-B', 2)):
        rows = material_detail(api, child['id'])['traceability']['materials']
        assert len(rows) == 1 and rows[0]['heat_number'] == heat
        assert rows[0]['source_line_number'] == line


def test_requirement_rejects_foreign_copy_and_unregistered_label(api):
    saved = setup(api, number='OWN-COPY', quantity=1)
    other = setup(api, number='FOREIGN-COPY', quantity=1)
    generate(api, other['order']['project_id'])
    foreign = labels(api, other['order']['project_id'])['items'][0]
    before = database_state(api)
    for target in ({'spool_id': foreign['id']}, {'label': foreign['display_code']},
                   {'label': NUMBER + '-[999]'}):
        result = upload(api, requirement_path(saved), [{'heat': 'H-X', 'mtr': 'M-X', **target}])
        assert result.status_code == 422
        assert database_state(api) == before


def test_revision_does_not_overwrite_pin_and_adoption_retains_previous_facts(api):
    spool_id = create_spool(api, 'REVISION-TRACE', NUMBER)
    path = ROOT + '/spools/' + spool_id
    ok(upload(api, path, [{'heat': 'H-ORIGINAL', 'mtr': 'M-ORIGINAL'}]))
    original = material_detail(api, spool_id)
    ok(upload(api, path, [{'heat': 'H-NEW', 'mtr': 'M-NEW'}], version=1))
    pinned = material_detail(api, spool_id)
    assert pinned['source_status']['changed']
    assert pinned['traceability']['materials'][0]['heat_number'] == 'H-ORIGINAL'
    adopt_current_bom(api, spool_id)
    adopted = material_detail(api, spool_id)
    assert adopted['traceability']['materials'][0]['heat_number'] == 'H-NEW'
    history = ok(api.get('/api/spool-boms/spools/' + spool_id + '/history/' + str(adopted['traceability']['version'])))
    assert history['changes'][0]['before_materials'][0]['heat_number'] == 'H-ORIGINAL'
    assert original['traceability']['materials'][0]['piece_key'] != adopted['traceability']['materials'][0]['piece_key']


def test_duplicate_piece_ids_and_unsafe_mtr_links_are_rejected_atomically(api):
    spool_id = create_spool(api, 'INVALID-TRACE', NUMBER)
    path = ROOT + '/spools/' + spool_id
    before = database_state(api)
    for rows in ([{'piece': 'P-1'}, {'piece': 'P-1'}],
                 [{'piece': 'P-1', 'qty': 2, 'scope': 'all_pieces'}],
                 [{'heat': 'H-1', 'url': 'javascript:alert(1)'}],
                 [{'spool_id': 'OTHER-SPOOL', 'heat': 'H-1'}]):
        assert upload(api, path, rows).status_code == 422
        assert database_state(api) == before


def test_excel_numeric_heat_format_preserves_leading_zeroes(api):
    spool_id = create_spool(api, 'XLSX-TRACE', NUMBER)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(['Quantity', 'Description', 'Heat Number', 'MTR No'])
    sheet.append([1, 'Pipe', 123, '000007'])
    sheet['C2'].number_format = '000000'
    output = io.BytesIO()
    workbook.save(output)
    ok(request_upload(api, ROOT + '/spools/' + spool_id,
        files=[('Trace.xlsx', output.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')]))
    row = material_detail(api, spool_id)['traceability']['materials'][0]
    assert row['heat_number'] == '000123' and row['mtr_reference'] == '000007'
