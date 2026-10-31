"""Source binding, exact row extraction, and conservative ambiguity handling."""
import copy

from pypdf import PdfWriter
import io

from isometric_bom import extract_isometric_boms
from isometric_fixtures import DEFAULT_ROWS, make_isometric_pdf


def test_native_spools_bound_to_own_grid_and_assembly_hardware_excluded():
    content = make_isometric_pdf()
    result = extract_isometric_boms(content, 'unrelated-filename.pdf')
    assert result['status'] == 'ready'
    assert result['page_count'] == 3
    assert result['unreadable_pages'] == []
    candidates = result['candidates']
    assert [row['spool_number'] for row in candidates] == ['TEST-100-SPOOL-01', 'TEST-100-SPOOL-02']
    assert [row['source_pages'] for row in candidates] == [[2], [3]]
    assert all(row['drawing'] == 'TEST-100' and row['revision'] == 'A' for row in candidates)
    for candidate in candidates:
        assert candidate['quantity_basis'] == 'one_spool'
        assert [line['quantity'] for line in candidate['lines']] == [2, 1]
        assert [line['part_number'] for line in candidate['lines']] == ['000123', '000456']
        assert candidate['lines'][1]['length'] == '16 3/4"'
        assert all('U-BOLT' not in line['description'] for line in candidate['lines'])
        assert not candidate['review_required']
    assert any(row['page'] == 1 and 'Assembly BOM' in row['reason'] for row in result['excluded_pages'])
    assert extract_isometric_boms(content)['candidates'] == candidates


def test_top_header_and_arbitrary_identifiers_work_without_filename_inference():
    result = extract_isometric_boms(make_isometric_pdf(
        [{'number': 'PLANT9-CHWS-007-B', 'rows': DEFAULT_ROWS}], drawing='DWG-ALT-8',
        revision='B', include_assembly=False, header_at_top=True), '777.pdf')
    assert result['candidates'][0]['spool_number'] == 'PLANT9-CHWS-007-B'
    assert result['candidates'][0]['revision'] == 'B'
    assert result['candidates'][0]['lines'][1]['length'] == '16 3/4"'


def test_missing_quantity_stays_unresolved_for_review_instead_of_using_one():
    rows = copy.deepcopy(DEFAULT_ROWS)
    rows[0][1] = ''
    result = extract_isometric_boms(make_isometric_pdf(
        [{'number': 'TEST-100-SPOOL-01', 'rows': rows}], include_assembly=False))
    candidate = result['candidates'][0]
    assert candidate['lines'][1]['quantity'] is None
    assert candidate['review_required']
    assert any('quantity (blank)' in error for error in candidate['validation_errors'])
    assert any('Correction required' in warning for warning in candidate['warnings'])
    assert result['status'] == 'partial'


def test_missing_part_number_stays_blank_and_requires_review():
    rows = copy.deepcopy(DEFAULT_ROWS)
    rows[0][2] = ''
    candidate = extract_isometric_boms(make_isometric_pdf(
        [{'number': 'TEST-100-SPOOL-01', 'rows': rows}], include_assembly=False))['candidates'][0]
    assert candidate['lines'][1]['part_number'] == ''
    assert candidate['review_required']
    assert any('part-number' in warning for warning in candidate['warnings'])


def test_short_cut_preserved_and_flagged_without_material_or_size_inference():
    rows = copy.deepcopy(DEFAULT_ROWS)
    rows[0][4] = '9/16"'
    candidate = extract_isometric_boms(make_isometric_pdf(
        [{'number': 'TEST-100-SPOOL-01', 'rows': rows}], include_assembly=False))['candidates'][0]
    pipe = candidate['lines'][1]
    assert pipe['length'] == '9/16"' and pipe['quantity'] == 1
    assert pipe['size'] == ''
    assert 'before cutting' in pipe['notes']
    assert candidate['review_required']


def test_duplicate_spool_grids_are_not_summed_or_silently_deduplicated():
    result = extract_isometric_boms(make_isometric_pdf([
        {'number': 'TEST-100-SPOOL-01', 'rows': DEFAULT_ROWS},
        {'number': 'TEST-100-SPOOL-01', 'rows': DEFAULT_ROWS}], include_assembly=False))
    assert len(result['candidates']) == 2
    assert len({c['candidate_id'] for c in result['candidates']}) == 2
    assert all(c['review_required'] for c in result['candidates'])
    assert all(any('multiple BOM grids' in w for w in c['warnings']) for c in result['candidates'])


def test_unbound_table_is_not_assigned_from_filename_or_drawing_label():
    result = extract_isometric_boms(make_isometric_pdf(
        include_assembly=False, footer_override='MATERIAL LIST FOR ASSEMBLY'), 'TEST-100-SPOOL-01.pdf')
    assert result['candidates'] == []
    assert any('no unique quoted spool number' in w for w in result['warnings'])


def test_scans_and_blank_pages_never_fabricate_materials():
    result = extract_isometric_boms(make_isometric_pdf([], include_assembly=False, extra_blank_pages=1))
    assert result['status'] == 'needs_ocr'
    assert result['unreadable_pages'] == [1]
    assert result['candidates'] == []


def test_optional_local_ocr_contract_preserves_rows_and_requires_review():
    received = []

    def provider(content, page_number, width, height):
        received.append((page_number, width, height))
        return {'drawing': 'SCAN-88', 'revision': 'C', 'tables': [{
            'rows': [*copy.deepcopy(DEFAULT_ROWS),
                     ['ITEM', 'QTY', 'TAS PART #', 'DESCRIPTION', 'LENGTH', 'MATERIAL'],
                     ['"SCAN-88-SPOOL-2" QTY. SHOWN FOR ONE (1); ONE (1) REQ\'D', None, None, None, None, None]],
            'bbox': [610, 500, 1180, 714]}], 'warnings': []}

    result = extract_isometric_boms(make_isometric_pdf([], include_assembly=False, extra_blank_pages=1),
                                   ocr_page_provider=provider)
    assert received == [(1, 1200.0, 800.0)]
    candidate = result['candidates'][0]
    assert candidate['source_method'] == 'ocr'
    assert candidate['review_required']
    assert candidate['spool_number'] == 'SCAN-88-SPOOL-2'
    assert candidate['lines'][1]['part_number'] == '000456'


def test_page_cap_reports_later_pages_without_mutating_original_document():
    writer = PdfWriter()
    for _ in range(51):
        writer.add_blank_page(width=1200, height=800)
    output = io.BytesIO()
    writer.write(output)
    content = output.getvalue()
    result = extract_isometric_boms(content)
    assert result['page_count'] == 51
    assert 51 in result['unreadable_pages']
    assert any('first 50 pages' in warning for warning in result['warnings'])
    assert content == output.getvalue()


def test_invalid_pdf_is_reported_without_a_candidate():
    result = extract_isometric_boms(b'not a pdf')
    assert result['status'] == 'invalid_pdf' and result['candidates'] == []
