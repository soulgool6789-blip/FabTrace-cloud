"""Physical material trace follows the spool into signed packet and export proof.

Only disposable SQLite records and synthetic supplier details are used here.
The approved BOM defines pieces; it does not prove receiving or welding.
"""

import importlib
import io
import json
import zipfile

from conftest import BADGES
from tracking_helpers import ok
from test_dossier import (
    ROOT as DOSSIER, check, checks, complete_packet, configure, document, entry,
    issue_item, make_project, packet, physical_release, review, sign_source, signed,
)
from test_exports import download
from test_flow import PROJECT, create_item
from test_order_labels import generate, labels, public_qr_url
from test_progress import database_state
from test_spool_reference_bom import APPROVED_SHA256, ROOT, SPOOL_A, setup


FIELDS = ('supplier', 'supplier_piece_id', 'heat_number', 'mtr_reference', 'mtr_url', 'notes')


def reference_spool(api, item_id='BOM-PACKET-SPOOL'):
    make_project(api, item_id)
    ok(api.patch(f'/api/items/{item_id}/part-number', {'google_part_number': SPOOL_A}))
    return item_id


def trace(api, item_id):
    return ok(api.get(f'{ROOT}/spools/{item_id}'))['traceability']


def save_materials(api, item_id, *, edits=None, reason='Synthetic supplier register entered'):
    current = trace(api, item_id)
    rows = []
    for piece in current['materials']:
        key = piece['piece_key']
        values = {field: piece[field] for field in FIELDS}
        if not current['configured']:
            values.update(supplier='Synthetic steel supplier', supplier_piece_id='PIECE-' + key,
                          heat_number='HEAT-' + key, mtr_reference='MTR-' + key)
        values.update((edits or {}).get(key, {}))
        rows.append({'piece_key': key, **values})
    return ok(api.put(f'{ROOT}/spools/{item_id}/traceability', {
        'expected_version': current['version'], 'reason': reason, 'materials': rows,
    }, role='supervisor'))['traceability']


def materials_evidence(api, item_id, *, project_id=PROJECT):
    signed(sign_source(api, project_id))
    uploaded = document(api, project_id=project_id, item_id=item_id,
                        code='SYNTHETIC-MTR-' + item_id, section='02')
    signed(entry(api, item_id, 'materials', project_id=project_id,
                 document_ids=[uploaded['id']]))
    return uploaded


def test_unsaved_reference_bom_does_not_change_legacy_packet_fingerprints(api):
    item_id = reference_spool(api)
    before = packet(api, item_id)
    state = database_state(api)
    assert not trace(api, item_id)['configured']
    after = packet(api, item_id)
    assert after['fingerprint'] == before['fingerprint']
    assert checks(after) == checks(before)
    assert 'material_trace' not in after['records']
    assert 'material_trace_records' not in after['records']
    structural = importlib.import_module('dossier')._structural(after['records'])
    assert 'material_trace' not in structural
    assert database_state(api) == state


def test_materials_review_requires_every_piece_heat_reference_and_real_attachment(api):
    item_id = reference_spool(api)
    save_materials(api, item_id, edits={'1-1': {
        'heat_number': '', 'mtr_reference': '', 'mtr_url': 'https://example.invalid/mtr/first-flange',
    }})
    signed(entry(api, item_id, 'materials'))
    assert any('actual controlled supporting file' in message
               for message in check(api, item_id, 'materials')['blockers'])
    materials_evidence(api, item_id)
    row = check(api, item_id, 'materials')
    assert item_id + ', BOM item 1 piece 1: material heat number is missing' in row['blockers']
    assert item_id + ', BOM item 1 piece 1: MTR reference is missing' in row['blockers']
    assert review(api, item_id, 'materials').status_code == 409
    save_materials(api, item_id, edits={'1-1': {
        'heat_number': 'HEAT-FLANGE-ONE', 'mtr_reference': 'MTR-FLANGE-ONE', 'mtr_url': '',
    }}, reason='Synthetic missing fields supplied from the material record')
    signed(review(api, item_id, 'materials'))
    assert check(api, item_id, 'materials')['status'] == 'accepted'
    records = packet(api, item_id)['records']
    assert records['tracking']['welds'] == []
    assert records['flow_events'] == []
    assert records['component_links'] == []


def test_heat_correction_stales_signed_material_proof_without_changing_the_review_or_other_copy(api):
    item_id = reference_spool(api)
    other_id = 'BOM-PACKET-OTHER-COPY'
    create_item(api, other_id, kind='Spool', project=PROJECT)
    ok(api.patch(f'/api/items/{other_id}/part-number', {'google_part_number': SPOOL_A}))
    save_materials(api, item_id)
    materials_evidence(api, item_id)
    signed(review(api, item_id, 'materials'))
    before = check(api, item_id, 'materials')
    other_before = packet(api, other_id)
    dossier = importlib.import_module('dossier')
    with api.session_factory() as session:
        historical_snapshot = session.get(dossier.DossierReview, before['latest_review']['id']).snapshot
    save_materials(api, item_id, edits={'1-2': {'heat_number': 'HEAT-SECOND-FLANGE-CORRECTED'}},
                   reason='Correct the second flange heat from its synthetic MTR')
    after = check(api, item_id, 'materials')
    assert after['status'] == 'stale'
    assert after['fingerprint'] != before['fingerprint']
    assert after['latest_review'] == before['latest_review']
    pieces = {row['piece_key']: row for row in packet(api, item_id)['records']['material_trace_records']}
    assert pieces['1-1']['heat_number'] == 'HEAT-1-1'
    assert pieces['1-2']['heat_number'] == 'HEAT-SECOND-FLANGE-CORRECTED'
    assert {piece['spool_id'] for piece in pieces.values()} == {item_id}
    with api.session_factory() as session:
        assert session.get(dossier.DossierReview, before['latest_review']['id']).snapshot == historical_snapshot
    assert packet(api, other_id)['fingerprint'] == other_before['fingerprint']
    assert not trace(api, other_id)['configured']


def test_parent_packet_includes_active_registered_spool_materials_even_before_child_weld_plan(api):
    saved = setup(api, quantity=1, welds=None)
    project_id = saved['order']['project_id']
    generate(api, project_id)
    physical = labels(api, project_id)['items']
    first, second = physical[:2]
    parent_id = first['assembly_id']
    assert second['assembly_id'] == parent_id
    ok(api.post(f'/api/tracking/spools/{parent_id}/plan', {
        'project_id': project_id, 'planned_welds': 0,
        'zero_weld_reason': 'Synthetic assembly scope has no assembly-level welds',
    }))
    configure(api, project_id, purchase_order=saved['order']['purchase_order'])
    before = packet(api, parent_id)
    save_materials(api, first['id'])
    one = packet(api, parent_id)
    assert len(one['records']['material_trace_records']) == 3
    assert {piece['spool_id'] for piece in one['records']['material_trace_records']} == {first['id']}
    assert one['records']['child_spools'] == [], 'No child plan may be fabricated by a material read or save'
    assert one['fingerprint'] != before['fingerprint']
    save_materials(api, second['id'], edits={'1-1': {'heat_number': 'SECOND-COPY-FLANGE-ONE'}})
    two = packet(api, parent_id)
    assert len(two['records']['material_trace_records']) == 6
    assert {piece['spool_id'] for piece in two['records']['material_trace_records']} == {first['id'], second['id']}
    assert two['fingerprint'] != one['fingerprint']
    first_heat = next(piece['heat_number'] for piece in two['records']['material_trace_records']
                      if piece['spool_id'] == first['id'] and piece['piece_key'] == '1-1')
    assert first_heat == 'HEAT-1-1'


def test_issued_packet_and_zip_retain_each_physical_piece_and_exact_source_workbook(api):
    item_id = reference_spool(api)
    save_materials(api, item_id, edits={'1-1': {
        'supplier': 'Synthetic <steel> & flanges', 'mtr_url': 'https://example.invalid/mtr/flange-one',
    }})
    physical_release(api, item_id)
    ready = complete_packet(api, item_id)
    assert ready['status'] == 'ready_for_issue', ready['blockers']
    signed(issue_item(api, item_id))
    issued = packet(api, item_id)['latest_issue']
    printed = api.get(f"{DOSSIER}/issues/{issued['id']}/print")
    assert printed.status_code == 200
    assert 'Material heat and MTR register' in printed.text
    assert 'Synthetic &lt;steel&gt; &amp; flanges' in printed.text
    assert 'HEAT-1-1' in printed.text and 'HEAT-1-2' in printed.text
    assert 'actual files are listed separately' in printed.text
    archived = api.get(f"{DOSSIER}/issues/{issued['id']}/download")
    assert archived.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archived.content)) as archive:
        records = json.loads(archive.read('generated-records.json'))
        assert len(records['material_trace_records']) == 3
        assert {row['spool_id'] for row in records['material_trace_records']} == {item_id}
        assert records['material_trace'][0]['source_sha256'] == APPROVED_SHA256
        assert records['material_trace'][0]['version'] == 1
        assert {row['heat_number'] for row in records['material_trace_records']} == {
            'HEAT-2-1', 'HEAT-1-1', 'HEAT-1-2'}
        assert not any(name.endswith('flange-one') for name in archive.namelist())


def test_database_excel_retains_material_definition_current_pieces_and_correction_history(api):
    item_id = reference_spool(api)
    save_materials(api, item_id)
    save_materials(api, item_id, edits={'1-2': {'heat_number': 'CORRECTED-SECOND-FLANGE'}},
                   reason='Synthetic trace correction remains in the export history')
    _, workbook = download(api)
    configs = workbook.records('Spool BOM trace configs')
    assert len(configs) == 1
    assert configs[0]['spool_id'].value == item_id
    assert configs[0]['source_sha256'].value == APPROVED_SHA256
    assert configs[0]['version'].value == 2
    assert json.loads(configs[0]['definition'].value)['spool_number'] == SPOOL_A
    pieces = {row['piece_key'].value: row for row in workbook.records('Spool BOM material pieces')}
    assert set(pieces) == {'2-1', '1-1', '1-2'}
    assert pieces['1-2']['heat_number'].value == 'CORRECTED-SECOND-FLANGE'
    assert pieces['1-1']['heat_number'].value == 'HEAT-1-1'
    history = workbook.records('Spool BOM trace events')
    assert [row['version'].value for row in history] == [1, 2]
    correction = json.loads(history[1]['changes'].value)
    assert correction[0]['piece_key'] == '1-2'
    assert correction[0]['before']['heat_number'] == 'HEAT-1-2'
    assert correction[0]['after']['heat_number'] == 'CORRECTED-SECOND-FLANGE'
    assert history[1]['actor'].value == BADGES['supervisor']
