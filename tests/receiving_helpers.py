"""Explicit synthetic receiving records for tests; never infer a QA Pass."""
import csv
import io

from tracking_helpers import ok


CHECKS = {key: True for key in ('identity', 'bom', 'heat_numbers', 'mtrs', 'condition')}


def receiving_detail(api, item_id):
    return ok(api.get('/api/spool-boms/spools/' + item_id))


def upload_receiving_bom(api, item_id, *, quantity=1, unit='EA', part='000123', description='Synthetic pipe', version=None):
    detail = receiving_detail(api, item_id)
    spool_number = detail['context']['spool_number']
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow((['spool_number'] if spool_number else []) + ['item', 'quantity', 'unit', 'part_number', 'description', 'material', 'length'])
    writer.writerow(([spool_number] if spool_number else []) + ['1', quantity, unit, part, description, 'A53B', '9/16 in'])
    path = '/api/spool-documents/spools/' + item_id
    files = [('files', ('synthetic-bom.csv', output.getvalue().encode(), 'text/csv'))]
    preview = ok(api.request('POST', path + '/preview', data={'kind': 'bom'}, files=files))
    if version is None:
        version = ok(api.get(path))['version']
    return ok(api.request('POST', path + '/upload', files=files, data={'kind': 'bom',
        'expected_version': version, 'expected_sha256': preview['selection_sha256'],
        'reason': 'Upload synthetic per-spool material basis'}))


def save_receiving_materials(api, item_id, *, heat='HEAT-LOCAL-1', reference='MTR-LOCAL-1', role='handler'):
    detail = receiving_detail(api, item_id)
    fields = ('piece_key', 'supplier', 'supplier_piece_id', 'heat_number', 'mtr_reference', 'mtr_url', 'notes')
    rows = [{key: row.get(key, '') for key in fields} for row in detail['traceability']['materials']]
    for row in rows:
        row.update(heat_number=heat, mtr_reference=reference)
    return ok(api.put('/api/spool-boms/spools/' + item_id + '/traceability', {
        'expected_version': detail['traceability']['version'],
        'expected_bom_sha256': detail['source_status']['expected_bom_sha256'],
        'reason': 'Record synthetic physical material identity', 'materials': rows}, role=role))


def record_arrival(api, item_id, *, result='Pass', role='inspector', notes='Synthetic arrival inspected against current evidence'):
    detail = receiving_detail(api, item_id)
    return api.post('/api/spool-boms/spools/' + item_id + '/arrival-inspections', {
        'expected_version': detail['arrival']['version'], 'basis_sha256': detail['arrival']['basis_sha256'],
        'result': result, 'reference': 'LOCAL-RECEIPT-01', 'notes': notes,
        'checks': {check['key']: result == 'Pass' for check in detail['arrival']['checks_catalog']}}, role=role)


def approve_materials(api, item_id):
    """Use the real per-piece QA endpoint; never infer acceptance from fields."""
    detail = receiving_detail(api, item_id)
    for piece in detail['traceability']['materials']:
        qa = piece['qa001']
        if qa['can_proceed']:
            continue
        detail = ok(api.post(qa['history_url'], {
            'expected_version': qa['version'], 'basis_sha256': qa['basis_sha256'],
            'result': 'Pass', 'reference': 'LOCAL-PIECE-QA-001',
            'notes': 'Synthetic incoming dimensions and material evidence checked for this piece'},
            role='inspector'), 201)
    return detail


def adopt_current_bom(api, item_id):
    detail = receiving_detail(api, item_id)
    return ok(api.post('/api/spool-boms/spools/' + item_id + '/adopt-bom', {
        'expected_version': detail['traceability']['version'],
        'expected_bom_sha256': detail['source_status']['expected_bom_sha256'],
        'reason': 'Explicitly adopt the revised synthetic physical material basis'}))


def accept_arrival(api, item_id):
    """Create real synthetic BOM/heat/MTR evidence and use the QA endpoint."""
    detail = receiving_detail(api, item_id)
    if detail['arrival']['can_proceed']:
        return detail
    if not detail['bom_available']:
        upload_receiving_bom(api, item_id)
    detail = receiving_detail(api, item_id)
    if not detail['traceability']['complete']:
        save_receiving_materials(api, item_id)
    approve_materials(api, item_id)
    return ok(record_arrival(api, item_id), 201)


def ensure_scope_arrival(api, item_id):
    """Explicitly prepare acceptance for a happy-path physical test scope."""
    item = ok(api.get('/api/items/' + item_id))
    summary = item['receiving']
    if not summary['required'] or summary['can_proceed']:
        return item
    if item['kind'] == 'Assembly':
        for child in summary.get('children', []):
            accept_arrival(api, child['spool_id'])
    else:
        accept_arrival(api, item_id)
    return ok(api.get('/api/items/' + item_id))
