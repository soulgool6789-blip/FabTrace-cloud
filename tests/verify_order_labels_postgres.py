"""Focused spool-label generation races on a LOCAL, disposable PostgreSQL schema.

Usage: python tests/verify_order_labels_postgres.py --dsn
  'postgresql+psycopg://nobody@/fabtrace_test_setup?host=/tmp/fabtrace-po-pg/socket&port=55433'

Reuses the full verifier's strict local test-database guard. Never uses an
inherited DATABASE_URL or caller-supplied search_path. Only a generated UUID
schema is written, and it is removed in finally, including on failed assertions.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import sys
from threading import Barrier, Event
import uuid

from sqlalchemy import create_engine, event, func, select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conftest import BADGES, TEST_PIN, TEST_SECRET, TestAPI
from test_order_setup import branch, create_setup
from test_progress import database_state
from tracking_helpers import ok
from verify_postgres import LIBPQ_ROUTING_ENV, is_loopback_host, local_test_url


def verify(dsn):
    url = local_test_url(dsn)
    if 'main' in sys.modules:
        raise RuntimeError('Use a fresh process; never reuse an application database')
    schema = 'fabtrace_labels_verify_' + uuid.uuid4().hex
    control = create_engine(url)
    app = api = None
    created = False
    settings = {
        'DATABASE_URL': url.update_query_dict({'options': '-csearch_path=' + schema}).render_as_string(hide_password=False),
        'JWT_SECRET': TEST_SECRET, 'COOKIE_SECURE': 'false',
        'PUBLIC_BASE_URL': 'https://fabtrace-label-tests.example',
        'BOOTSTRAP_BADGE': '', 'BOOTSTRAP_PIN': '',
    }
    previous = {key: os.environ.get(key) for key in (*settings, *LIBPQ_ROUTING_ENV)}
    try:
        for key in LIBPQ_ROUTING_ENV:
            os.environ.pop(key, None)
        os.environ.update(settings)
        with control.begin() as c:
            assert c.scalar(text('SELECT current_database()')) == url.database
            address = c.scalar(text('SELECT inet_server_addr()'))
            assert address is None or is_loopback_host(str(address))
            version = c.scalar(text('SHOW server_version'))
            c.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        app = importlib.import_module('main')
        with app.engine.connect() as c:
            assert c.scalar(text('SELECT current_schema()')) == schema
        app.Base.metadata.create_all(app.engine)
        with app.SessionLocal() as s:
            pin = app.password_hash.hash(TEST_PIN)
            s.add_all(app.Employee(badge=badge, name='QR race test ' + role,
                role=role, pin_hash=pin, active=True) for role, badge in BADGES.items())
            s.commit()
        with redirect_stdout(io.StringIO()):
            importlib.import_module('init_db').initialize()
        api = TestAPI(app, app.SessionLocal)
        orders = importlib.import_module('orders')

        setup = create_setup(api, number='QR-CONCURRENT-PO',
            assemblies=[branch('000-GPN-A', 3), branch('000-GPN-B', 2)])
        project = setup['order']['project_id']
        path = '/api/order-labels/' + project + '/generate'
        body = {'expected_version': 1, 'location': 'Synthetic assembly bay',
                'handler': BADGES['handler']}
        gate, connections = Barrier(2), set()

        def synchronize(c, cursor, statement, params, context, many):
            if 'pg_advisory_xact_lock' in statement and id(c) not in connections:
                connections.add(id(c))
                gate.wait(timeout=15)

        def request(method, target, payload, role='admin'):
            worker = TestAPI(app, app.SessionLocal)
            try:
                response = getattr(worker, method)(target, payload, role=role)
                return {'status': response.status_code, 'body': response.json()}
            finally:
                worker.client.close()

        event.listen(app.engine, 'before_cursor_execute', synchronize)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(request, 'post', path, body) for _ in range(2)]
                result = [future.result(timeout=30) for future in futures]
        finally:
            event.remove(app.engine, 'before_cursor_execute', synchronize)
        assert sorted(r['status'] for r in result) == [200, 409], result
        success = next(r['body'] for r in result if r['status'] == 200)
        assert success['created_count'] == 20 and len(set(success['created_ids'])) == 20
        assert success['created_assembly_count'] == 5 and success['created_spool_count'] == 15
        assert success['order']['version'] == 2
        with app.SessionLocal() as s:
            assert s.scalar(select(func.count()).select_from(app.Item)) == 20
            assert s.scalar(select(func.count()).select_from(orders.OrderAssembly)) == 5
            assert s.scalar(select(func.count()).select_from(app.Audit).where(
                app.Audit.event == 'ORDER_SPOOL_LABELS_GENERATED')) == 1
            counts = dict(s.execute(select(orders.OrderGpn.gpn, func.count(orders.OrderAssembly.item_id))
                .join(orders.OrderAssembly, orders.OrderAssembly.gpn_id == orders.OrderGpn.id)
                .group_by(orders.OrderGpn.gpn)).all())
            assert counts == {'000-GPN-A': 3, '000-GPN-B': 2}
            for table_name in ('flow_plans', 'flow_events', 'tracking_spool_plans',
                               'tracking_welds', 'inspections', 'tracking_process_events'):
                assert s.scalar(select(func.count()).select_from(app.Base.metadata.tables[table_name])) == 0

        before = database_state(api)
        noop = ok(api.post(path, {**body, 'expected_version': 2,
            'location': 'Ignored for an already complete order', 'handler': BADGES['welder']}))
        assert noop['created_count'] == 0 and noop['order']['version'] == 2
        assert database_state(api) == before
        unsafe, snapshots = [], []

        def observe(c, cursor, statement, params, context, many):
            sql = statement.lstrip().upper()
            if sql.startswith(('INSERT', 'UPDATE', 'DELETE')) or 'FOR UPDATE' in sql or 'PG_ADVISORY_XACT_LOCK' in sql:
                unsafe.append(statement)
            if 'FROM order_gpns' in statement:
                with c.connection.driver_connection.cursor() as probe:
                    probe.execute('SHOW transaction_read_only')
                    readonly = probe.fetchone()[0]
                    probe.execute('SHOW transaction_isolation')
                    snapshots.append((readonly, probe.fetchone()[0]))

        event.listen(app.engine, 'before_cursor_execute', observe)
        try:
            overview = ok(api.get('/api/order-labels/' + project))
            first = ok(api.get('/api/order-labels/' + project + '/labels'))
            second = ok(api.get('/api/order-labels/' + project + '/labels'))
        finally:
            event.remove(app.engine, 'before_cursor_execute', observe)
        assert first == second and len({r['qr_url'] for r in first['items']}) == 15
        assert all(row['kind'] == 'Spool' for row in first['items'])
        assert overview['totals']['remaining_quantity'] == 0
        assert not unsafe and snapshots and all(x == ('on', 'repeatable read') for x in snapshots)
        assert database_state(api) == before

        # Exercise the combined parent-and-spool transaction on a fresh PO.
        # Both callers see version 1, but only one may reserve its physical IDs.
        spool_setup = create_setup(api, number='QR-SPOOL-CONCURRENT-PO', assemblies=[
            branch('SPOOL-GPN-A', 3, [{'spool_number': 'SPOOL-A', 'quantity_per_assembly': 2}]),
            branch('SPOOL-GPN-B', 2, [{'spool_number': 'SPOOL-B', 'quantity_per_assembly': 1}]),
        ])
        spool_project = spool_setup['order']['project_id']
        spool_path = '/api/order-labels/' + spool_project + '/generate'
        spool_body = {**body, 'kind': 'Spool'}
        gate, connections = Barrier(2), set()
        event.listen(app.engine, 'before_cursor_execute', synchronize)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(request, 'post', spool_path, spool_body) for _ in range(2)]
                spool_results = [future.result(timeout=30) for future in futures]
        finally:
            event.remove(app.engine, 'before_cursor_execute', synchronize)
        assert sorted(r['status'] for r in spool_results) == [200, 409], spool_results
        spool_success = next(r['body'] for r in spool_results if r['status'] == 200)
        assert spool_success['created_count'] == 13
        assert spool_success['created_assembly_count'] == 5 and spool_success['created_spool_count'] == 8
        assert spool_success['order']['version'] == 2 and spool_success['totals']['remaining_quantity'] == 0
        with app.SessionLocal() as s:
            registrations = s.execute(select(app.OrderSpool, app.Item)
                .join(app.Item, app.Item.id == app.OrderSpool.item_id)
                .where(app.Item.project == spool_project)).all()
            assert len(registrations) == 8 and len({r.item_id for r, _ in registrations}) == 8
            child_counts = {}
            for registration, item in registrations:
                parent = s.get(app.Item, registration.assembly_id)
                assert item.kind == 'Spool' and parent.kind == 'Assembly' and parent.project == spool_project
                assert item.google_part_number == ('SPOOL-A' if parent.google_part_number == 'SPOOL-GPN-A' else 'SPOOL-B')
                child_counts[parent.id] = child_counts.get(parent.id, 0) + 1
            assert sorted(child_counts.values()) == [1, 1, 2, 2, 2]
            for table_name in ('flow_plans', 'flow_events', 'tracking_spool_plans',
                               'tracking_welds', 'inspections', 'tracking_process_events'):
                assert s.scalar(select(func.count()).select_from(app.Base.metadata.tables[table_name])) == 0
        spool_before = database_state(api)
        spool_noop = ok(api.post(spool_path, {**spool_body, 'expected_version': 2}))
        assert spool_noop['created_count'] == 0 and spool_noop['order']['version'] == 2
        assert database_state(api) == spool_before
        unsafe.clear()
        snapshots.clear()
        event.listen(app.engine, 'before_cursor_execute', observe)
        try:
            spool_first = ok(api.get('/api/order-labels/' + spool_project + '/labels?kind=Spool'))
            spool_second = ok(api.get('/api/order-labels/' + spool_project + '/labels?kind=Spool'))
            spool_overview = ok(api.get('/api/order-labels/' + spool_project + '?kind=Spool'))
        finally:
            event.remove(app.engine, 'before_cursor_execute', observe)
        assert spool_first == spool_second and spool_first['total'] == 8
        assert len({row['qr_url'] for row in spool_first['items']}) == 8
        assert all(row['assembly_id'] in child_counts for row in spool_first['items'])
        assert spool_overview['totals']['remaining_quantity'] == 0
        assert not unsafe and snapshots and all(x == ('on', 'repeatable read') for x in snapshots)
        assert database_state(api) == spool_before

        queued = {}
        for target_role, writer_role, expected_rejection in (
            ('handler', 'admin', 422), ('supervisor', 'supervisor', 401),
        ):
            order = create_setup(api, number='QR-QUEUED-' + target_role,
                assemblies=[branch('QUEUED-GPN', 2)])
            project_id = order['order']['project_id']
            badge = BADGES[target_role]
            account = next(row for row in ok(api.get('/api/admin/employees'))['employees'] if row['badge'] == badge)
            update = {'expected_version': account['version'], 'name': account['name'],
                'role': account['role'], 'active': False,
                'reason': 'Synthetic concurrent account deactivation'}
            generation = {'expected_version': 1, 'location': 'Synthetic receiving',
                'handler': BADGES['handler'] if target_role == 'handler' else BADGES['welder']}
            administrator_locked, writer_waiting = Event(), Event()
            control_state = {'connection': None, 'paused': False}

            def before_lock(c, cursor, statement, params, context, many):
                if 'pg_advisory_xact_lock' not in statement:
                    return
                if control_state['connection'] is None:
                    control_state['connection'] = id(c)
                elif id(c) != control_state['connection']:
                    writer_waiting.set()

            def after_lock(c, cursor, statement, params, context, many):
                if ('pg_advisory_xact_lock' in statement and id(c) == control_state['connection']
                        and not control_state['paused']):
                    control_state['paused'] = True
                    administrator_locked.set()
                    assert writer_waiting.wait(timeout=15), 'Queued generation did not reach the topology lock'

            event.listen(app.engine, 'before_cursor_execute', before_lock)
            event.listen(app.engine, 'after_cursor_execute', after_lock)
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    change = pool.submit(request, 'patch', '/api/admin/employees/' + badge, update)
                    assert administrator_locked.wait(timeout=15)
                    generation_future = pool.submit(request, 'post',
                        '/api/order-labels/' + project_id + '/generate', generation, writer_role)
                    change_result, generation_result = change.result(timeout=30), generation_future.result(timeout=30)
            finally:
                event.remove(app.engine, 'before_cursor_execute', before_lock)
                event.remove(app.engine, 'after_cursor_execute', after_lock)
            assert change_result['status'] == 200, change_result
            assert generation_result['status'] == expected_rejection, generation_result
            with app.SessionLocal() as s:
                assert s.scalar(select(func.count()).select_from(app.Item).where(app.Item.project == project_id)) == 0
                assert s.get(orders.PurchaseOrder, project_id).version == 1
            queued[target_role] = {'account_change_status': 200,
                'queued_generation_status': expected_rejection, 'created_assemblies': 0}

        return {'postgresql_version': version, 'generation_race': [200, 409],
            'created_assemblies': 5, 'created_spools': 15, 'gpn_quantities': counts, 'generated_order_events': 1,
            'spool_generation': {'race': [200, 409], 'created_assemblies': 5,
                'created_spools': 8, 'children_per_assembly': [1, 1, 2, 2, 2],
                'repeated_generation': 'no-op', 'read_only_stable_labels': True},
            'current_revision_repeat': 'no-op, unchanged data and IDs',
            'read_views': {'stable_ids': True, 'read_only': True, 'isolation': 'repeatable read',
                           'mutations': 0, 'write_locks': 0},
            'queued_account_changes': queued, 'production_evidence_created': False,
            'schema_cleanup': 'completed'}
    finally:
        if api is not None:
            api.client.close()
        if app is not None:
            app.engine.dispose()
        if created:
            with control.begin() as c:
                c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.dsn), indent=2))

