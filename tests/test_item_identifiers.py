"""Physical records can be registered by identity without item descriptions."""

import pytest

from conftest import BADGES


@pytest.mark.parametrize('kind', ('Part', 'Spool', 'Assembly'))
def test_physical_registration_uses_ids_without_requiring_a_description(api, kind):
    item_id = 'NO-DESCRIPTION-' + kind.upper()
    body = {'id': item_id, 'google_part_number': '00001234', 'kind': kind,
            'location': 'Receiving', 'handler': BADGES['handler'], 'welds_required': 0}
    response = api.post('/api/items', body)
    assert response.status_code == 201, response.text
    saved = api.get('/api/items/' + item_id).json()
    assert saved['id'] == item_id and saved['google_part_number'] == '00001234'
    assert saved['description'] == ''
    assert not saved['released']
    with api.session_factory() as session:
        item = session.get(api.application.Item, item_id)
        assert item.description == ''  # No invented title or duplicated identifier.


def test_bulk_registration_accepts_new_identifier_only_and_legacy_rows_together(api):
    common = {'kind': 'Part', 'location': 'Receiving', 'handler': BADGES['handler']}
    response = api.post('/api/items/bulk', {'rows': [
        {**common, 'google_part_number': '00004567', 'quantity': 2},
        {**common, 'id': 'BLANK-DESCRIPTION', 'google_part_number': '00008901', 'description': ''},
        {**common, 'id': 'LEGACY-DESCRIPTION', 'google_part_number': 'OLD-PN',
         'description': 'Retained description supplied by an older client'},
    ]})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['created_count'] == 4
    assert len({row['id'] for row in result['items']}) == 4
    generated = [row for row in result['items'] if row['google_part_number'] == '00004567']
    assert len(generated) == 2 and all(row['description'] == '' for row in generated)
    assert api.get('/api/items/BLANK-DESCRIPTION').json()['description'] == ''
    assert api.get('/api/items/LEGACY-DESCRIPTION').json()['description'] == (
        'Retained description supplied by an older client')

