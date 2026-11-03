"""Real PostgreSQL races for record removal, restoration and queued writers."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import event, select

from conftest import BADGES, TestAPI
from tracking_helpers import ok
from test_orders import new_order, current
from test_progress import database_state
from test_transfers import transfer_body


def verify_record_removals(application, api):
    from orders import PurchaseOrder, OrderGpn, OrderAssembly
    from removals import RecordRemoval

    def body(kind, identifier, action='remove'):
        preview = ok(api.get(f'/api/removals/{kind}/{identifier}', params={'action': action}))
        assert preview['can_proceed'], preview
        return {key: preview[key] for key in ('expected_version', 'preview_token', 'confirmation')} | {
            'reason': 'Synthetic local PostgreSQL removal concurrency gate'}

    def race(calls):
        barrier, seen = Barrier(2), set()

        def synchronize(connection, cursor, statement, parameters, context, many):
            if 'pg_advisory_xact_lock' in statement and id(connection) not in seen:
                seen.add(id(connection))
                barrier.wait(timeout=15)

        def submit(call):
            worker = TestAPI(application, application.SessionLocal)
            try:
                method, path, payload = call
                response = worker.request(method, path, json=payload)
                return {'status': response.status_code, 'body': response.json()}
            finally:
                worker.client.close()

        event.listen(application.engine, 'before_cursor_execute', synchronize)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [future.result(timeout=40) for future in [pool.submit(submit, call) for call in calls]]
        finally:
            event.remove(application.engine, 'before_cursor_execute', synchronize)
        assert sum(r['status'] in (200, 201) for r in results) == 1, results
        assert sum(r['status'] == 409 for r in results) == 1, results
        return sorted(r['status'] for r in results)

    order = new_order(api, number='PG-REMOVE-DUPLICATE')
    project = order['order']['project_id']
    before_reads = database_state(api)
    payload = body('order', project)
    ok(api.get('/api/removals'))
    assert database_state(api) == before_reads
    duplicate_remove = race([('POST', f'/api/removals/order/{project}/remove', payload)] * 2)
    with application.SessionLocal() as session:
        state = session.get(RecordRemoval, ('order', project))
        assert state.removed and state.version == 1
        assert session.get(PurchaseOrder, project).version == 2
    payload = body('order', project, 'restore')
    duplicate_restore = race([('POST', f'/api/removals/order/{project}/restore', payload)] * 2)
    with application.SessionLocal() as session:
        state = session.get(RecordRemoval, ('order', project))
        assert not state.removed and state.version == 2
        assert session.get(PurchaseOrder, project).version == 3

    order = new_order(api, number='PG-REMOVE-VS-CREATE')
    project = order['order']['project_id']
    payload = body('order', project)
    create = {'expected_version': 1, 'gpn': 'PG-REMOVE-CHILD', 'required_spools': 1,
        'assembly_number': 'PG-REMOVE-CHILD-ASSEMBLY',
        'create_item': {'id': 'PG-REMOVE-CHILD-ASM', 'location': 'Synthetic receiving', 'handler': BADGES['handler']}}
    create_vs_remove = race([
        ('POST', f'/api/removals/order/{project}/remove', payload),
        ('POST', f'/api/orders/{project}/gpn-assemblies', create),
    ])
    with application.SessionLocal() as session:
        state = session.get(RecordRemoval, ('order', project))
        physical = session.get(application.Item, 'PG-REMOVE-CHILD-ASM')
        groups = session.scalars(select(OrderGpn).where(OrderGpn.project_id == project)).all()
        if state and state.removed:
            assert physical is None and not groups
        else:
            assert physical and len(groups) == 1 and session.get(OrderAssembly, physical.id)

    item = 'PG-REMOVE-VS-TRANSFER'
    api.item(item, welds_required=0, kind='Part')
    payload = body('item', item)
    transfer = transfer_body(api, item, handler=BADGES['handler'])
    transfer_vs_remove = race([
        ('POST', f'/api/removals/item/{item}/remove', payload),
        ('POST', f'/api/items/{item}/transfer', transfer),
    ])
    with application.SessionLocal() as session:
        state = session.get(RecordRemoval, ('item', item))
        physical = session.get(application.Item, item)
        if state and state.removed:
            assert physical.handler == BADGES['welder']
        else:
            assert physical.handler == BADGES['handler']
        assert physical.welds_done == 0 and not physical.released

    return {'duplicate_remove': duplicate_remove, 'duplicate_restore': duplicate_restore,
            'assembly_creation_vs_remove': create_vs_remove, 'transfer_vs_remove': transfer_vs_remove,
            'preview_and_register_readonly': True, 'identities_and_requirements_retained': True}

