"""Live spool-number labels keep each physical copy and evidence scope intact."""
import importlib

from tracking_helpers import ok
from test_flow import enroll
from test_order_labels import generate, labels, public_qr_url
from test_order_setup import branch, create_setup, detail
from test_production_progress import flatten
from test_progress import database_state


NUMBER = '643-777-PCW-03-01'


def seed(api):
    setup = create_setup(api, assemblies=[branch('643-777-PCW-03', 1, [
        {'spool_number': NUMBER, 'quantity_per_assembly': 2, 'welds_per_spool': 0}])])
    return setup, setup['order']['project_id'], setup['assemblies'][0]['spools'][0]['id']


def indexed(rows, key='item_id'):
    return {row[key]: row for row in rows}


def test_actual_spool_number_and_copy_status_agree_across_live_views(api):
    _, project, _ = seed(api)
    generate(api, project)
    copies = labels(api, project)['items']
    first, second = copies
    enroll(api, first['id'], 'spool', start_step=13)
    before = database_state(api)

    expected = {first['id']: 'welding', second['id']: 'qa_001'}
    views = [
        indexed(ok(api.get('/api/items'))['items'], 'id'),
        indexed(labels(api, project)['items'], 'id'),
        indexed(ok(api.get('/api/parts/spools', params={'project_id': project}))['items']),
        indexed(ok(api.get('/api/tracking/overview', params={'project_id': project}))['spools']),
        indexed(ok(api.get('/api/progress/projects/' + project))['items'], 'id'),
        flatten(ok(api.get('/api/progress/orders', params={'project_id': project}))),
        indexed([spool for assembly in ok(api.get('/api/orders/' + project))['assemblies']
                 for spool in assembly['spools']]),
    ]
    for copy in copies:
        item_id = copy['id']
        assert copy['qr_alias'] != item_id and NUMBER in copy['qr_alias']
        for view in views:
            row = view[item_id]
            assert row['spool_number'] == row['google_part_number'] == NUMBER
            assert row['display_code'] == row['qr_alias'] == copy['qr_alias']
            assert row['flow_stage']['key'] == expected[item_id]
            assert row['route'] == 'spool'
        for path in ('/api/items/', '/api/flow/items/', '/api/parts/spools/', '/api/tracking/spools/'):
            response = ok(api.get(path + item_id))
            row = response if path == '/api/items/' else response['item']
            assert row['spool_number'] == NUMBER
            assert row['display_code'] == copy['qr_alias']
            assert row['flow_stage']['key'] == expected[item_id]
        documents = ok(api.get('/api/spool-documents/spools/' + item_id))
        assert documents['context']['item_id'] == item_id
        assert documents['context']['spool_number'] == NUMBER
        assert documents['context']['display_code'] == copy['qr_alias']
        assert documents['flow_stage']['key'] == expected[item_id]

    board = indexed(ok(api.get('/api/flow/items', params={'project_id': project}))['items'])
    assert board[first['id']]['display_code'] == first['qr_alias']
    assert board[first['id']]['flow_stage']['key'] == 'welding'
    exceptions = ok(api.get('/api/tracking/exceptions', params={'project_id': project}))['exceptions']
    assert {row['item_id'] for row in exceptions}.issuperset(expected)
    for row in exceptions:
        if row['item_id'] in expected:
            assert row['route'] == 'spool' and row['spool_number'] == NUMBER
            assert row['flow_stage']['key'] == expected[row['item_id']]
        else:
            assert row['route'] == 'assembly' and row['spool_number'] == ''
    assert database_state(api) == before


def test_requirement_common_stage_becomes_mixed_without_changing_evidence_payloads(api):
    saved, project, requirement = seed(api)
    unregistered = saved['assemblies'][0]['spools'][0]
    assert unregistered['flow_stage_state'] == 'not_registered'
    assert unregistered['flow_stage'] is None and unregistered['physical_spools'] == []
    generate(api, project)
    common = detail(api, project)['assemblies'][0]['spools'][0]
    assert common['flow_stage_state'] == 'common' and common['physical_spools_total'] == 2
    assert common['flow_stage']['key'] == 'qa_001'
    assert common['flow_stage']['source_item_id'] is None
    copies = common['physical_spools']
    assert len({row['display_code'] for row in copies}) == 2
    enroll(api, copies[0]['item_id'], 'spool', start_step=13)
    before = database_state(api)

    setup = detail(api, project)['assemblies'][0]['spools'][0]
    documents = ok(api.get('/api/spool-documents/requirements/' + requirement))
    order = ok(api.get('/api/orders/' + project))['gpns'][0]['quantity_plan']['spools'][0]
    for view in (setup, documents, order):
        assert view['flow_stage_state'] == 'mixed' and view['flow_stage'] is None
        assert view['physical_spools_total'] == 2
        assert {row['flow_stage']['key'] for row in view['physical_spools']} == {'welding', 'qa_001'}
        assert {row['spool_number'] for row in view['physical_spools']} == {NUMBER}
        assert {row['item_id'] for row in view['physical_spools']} == {row['item_id'] for row in copies}

    tracking = importlib.import_module('tracking')
    progress = importlib.import_module('progress')
    setup_models = importlib.import_module('order_setup')
    document_models = importlib.import_module('spool_documents')
    with api.session_factory() as session:
        item = session.get(api.application.Item, copies[0]['item_id'])
        retained = tracking.spool_dict(session, item)
        assert 'flow_stage' not in retained['item'] and 'display_code' not in retained['item']
        context, _, _ = document_models._target(session, 'spools', item.id)
        assert 'display_code' not in context and 'flow_stage' not in context
        assert all('flow_stage' not in row and 'display_code' not in row
                   for row in progress.project_rows(session, project))
        plan = setup_models.requirements_by_gpn(session, [saved['assemblies'][0]['gpn_id']])
        assert all('flow_stage' not in row and 'physical_spools' not in row
                   for group in plan.values() for row in group['spools'])
    assert database_state(api) == before
