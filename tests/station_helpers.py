"""Record an actual isolated station move through the authenticated API."""
from tracking_helpers import ok


def move(api, item_id, location_id, *, role='handler', status='queued'):
    current = ok(api.get('/api/transfers/items/' + item_id))
    return ok(api.post('/api/items/' + item_id + '/transfer', {
        'sender_badge': current['handler'], 'handler': current['handler'],
        'location_id': location_id, 'operational_status': status,
        'expected_transfer_version': current['version'], 'expected_handler': current['handler'],
        'scan_method': 'employee_qr', 'notes': 'Synthetic recorded physical station transfer'}, role=role))
