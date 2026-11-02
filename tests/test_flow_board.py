"""The process board groups real spool copies without starting their routes."""
from sqlalchemy import event

from conftest import BADGES
from receiving_helpers import accept_arrival
from test_flow import enroll
from test_order_labels import generate, labels, public_qr_url
from test_progress import database_state
from test_removal_orders import change
from test_spool_status_presentation import NUMBER, seed
from tracking_helpers import ok
from station_helpers import move


def board(api, project='', **kwargs):
    return ok(api.get('/api/flow/board', params={'project_id': project}, **kwargs))


def create(api, identifier, project, *, kind='Spool', number=NUMBER):
    return ok(api.post('/api/items', {'id': identifier, 'kind': kind, 'project': project,
        'google_part_number': number, 'location': 'Receiving', 'handler': BADGES['handler'],
        'welds_required': 0}), 201)


def test_board_keeps_inventory_and_legacy_spools_once_with_exact_identity_and_no_writes(api):
    saved, project, _ = seed(api)
    generate(api, project)
    first, second = labels(api, project)['items']
    initial = board(api, project)
    assert [row['item_id'] for row in initial['items']] == [first['id'], second['id']]
    assert all(row['status'] == 'not_started' and row['current_step'] is None for row in initial['items'])
    assert initial['stage_counts']['inventory'] == 2
    assert ok(api.get('/api/flow/items', params={'project_id': project}))['items'] == []

    # Receipt acceptance leaves this actual copy in Inventory without a route;
    # the other copy has a real, independently recorded welding transfer.
    accept_arrival(api, first['id'])
    enroll(api, second['id'], 'spool', start_step=13)
    move(api, second['id'], 'welding')
    create(api, 'BOARD-NO-PLAN', project, number='BOARD-SP-10')
    create(api, 'BOARD-LEGACY', project, kind='Part', number='BOARD-SP-2')
    ok(api.post('/api/tracking/spools/BOARD-LEGACY/plan', {
        'project_id': project, 'planned_welds': 0, 'zero_weld_reason': 'Synthetic legacy physical spool'}))
    create(api, 'BOARD-COMPONENT', project, kind='Part')
    before = database_state(api)
    assert api.get('/api/flow/board', role=None).status_code == 401
    statements = []
    engine = api.session_factory.kw['bind']

    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement.upper().lstrip())

    event.listen(engine, 'before_cursor_execute', observe)
    try:
        result = board(api, project, role='welder')
        empty = board(api, 'MISSING-PROJECT')
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert not any(sql.startswith(('INSERT ', 'UPDATE ', 'DELETE ', 'LOCK '))
                   or 'FOR UPDATE' in sql or 'PG_ADVISORY' in sql for sql in statements)
    rows = {row['item_id']: row for row in result['items']}
    assert len(rows) == result['total'] == 4
    assert set(rows) == {first['id'], second['id'], 'BOARD-NO-PLAN', 'BOARD-LEGACY'}
    assert [row['item_id'] for row in result['items']] == [
        'BOARD-LEGACY', 'BOARD-NO-PLAN', first['id'], second['id']]
    assert rows[first['id']]['flow_stage']['key'] == 'inventory'
    assert rows[first['id']]['flow_stage']['color'] == 'black'
    assert rows[first['id']]['status'] == 'not_started'
    assert rows[second['id']]['flow_stage']['key'] == 'welding'
    assert rows[second['id']]['current_step'] == 13
    assert rows['BOARD-LEGACY']['item_kind'] == 'Part' and rows['BOARD-LEGACY']['route'] == 'spool'
    for copy in (first, second):
        row = rows[copy['id']]
        assert row['display_code'] == row['qr_alias'] == copy['qr_alias']
        assert row['spool_number'] == NUMBER and row['project_id'] == project
        assert row['assembly_id'] == copy['assembly_id']
        assert row['assembly_number'] == saved['assemblies'][0]['gpn']
        assert row['purchase_order'] == saved['order']['purchase_order']
    assert len(result['stage_catalog']) == len(result['stage_counts']) == 12
    assert sum(result['stage_counts'].values()) == result['total']
    assert result['stage_counts']['inventory'] == 3
    assert result['stage_counts']['qa_001'] == 0
    assert result['stage_counts']['welding'] == 1
    assert empty['items'] == [] and not any(empty['stage_counts'].values())
    assert database_state(api) == before


def test_board_excludes_removed_ancestors_and_keeps_unparented_physical_inventory(api):
    _, project, _ = seed(api)
    generate(api, project)
    copies = labels(api, project)['items']
    create(api, 'BOARD-UNPARENTED', project)
    assert board(api, project)['total'] == 3
    change(api, 'item', copies[0]['assembly_id'])
    before = database_state(api)
    assert [row['item_id'] for row in board(api, project)['items']] == ['BOARD-UNPARENTED']
    assert database_state(api) == before
    change(api, 'order', project)
    before = database_state(api)
    assert board(api)['total'] == board(api, project)['total'] == 0
    assert database_state(api) == before

