"""Check QA-001 bulk atomicity and races in a disposable LOCAL PostgreSQL schema.

Requires an explicit loopback/socket DSN for a fabtrace_test_* database. No
operational host, inherited database, or production credentials are accepted.
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
from threading import Barrier
import uuid

from sqlalchemy import create_engine, event, func, select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conftest import BADGES, TEST_PIN, TEST_SECRET, TestAPI
from receiving_helpers import receiving_detail, save_receiving_materials, upload_receiving_bom
from test_material_piece_qa import decide, edit_piece
from test_spool_receiving import create_spool
from tracking_helpers import ok
from verify_postgres import LIBPQ_ROUTING_ENV, is_loopback_host, local_test_url


def payload(detail):
    return {
        'expected_trace_version': detail['traceability']['version'],
        'expected_bom_sha256': detail['source_status']['expected_bom_sha256'],
        'reference': 'PG-PASS-ALL-001',
        'notes': 'Synthetic inspection of every listed physical piece and its evidence.',
        'pieces': [{'piece_key': piece['piece_key'],
                    'expected_version': piece['qa001']['version'],
                    'basis_sha256': piece['qa001']['basis_sha256']}
                   for piece in detail['traceability']['materials']],
    }


def verify(dsn):
    url = local_test_url(dsn)
    if 'main' in sys.modules:
        raise RuntimeError('Start in a fresh process with no inherited application connection.')
    schema = 'fabtrace_bulk_qa_verify_' + uuid.uuid4().hex
    settings = {
        'DATABASE_URL': url.update_query_dict({'options': '-csearch_path=' + schema}).render_as_string(hide_password=False),
        'JWT_SECRET': TEST_SECRET, 'COOKIE_SECURE': 'false',
        'PUBLIC_BASE_URL': 'https://fabtrace-bulk-tests.example',
        'BOOTSTRAP_BADGE': '', 'BOOTSTRAP_PIN': '',
    }
    previous = {key: os.environ.get(key) for key in (*settings, *LIBPQ_ROUTING_ENV)}
    app = api = control = None
    created = False
    checks = []
    try:
        for key in LIBPQ_ROUTING_ENV:
            os.environ.pop(key, None)
        os.environ.update(settings)
        control = create_engine(url)
        with control.begin() as connection:
            assert connection.scalar(text('SELECT current_database()')) == url.database
            address = connection.scalar(text('SELECT inet_server_addr()'))
            assert address is None or is_loopback_host(address)
            version = connection.scalar(text('SHOW server_version'))
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        app = importlib.import_module('main')
        app.Base.metadata.create_all(app.engine)
        with app.SessionLocal() as session:
            pin = app.password_hash.hash(TEST_PIN)
            session.add_all(app.Employee(badge=badge, name='Synthetic ' + role,
                role=role, active=True, pin_hash=pin) for role, badge in BADGES.items())
            session.commit()
        with redirect_stdout(io.StringIO()):
            importlib.import_module('init_db').initialize()
        api = TestAPI(app, app.SessionLocal)
        from spool_receiving import SpoolMaterialInspection

        def count_decisions(item_id):
            with app.SessionLocal() as session:
                return session.scalar(select(func.count()).select_from(SpoolMaterialInspection)
                    .where(SpoolMaterialInspection.spool_id == item_id))

        def count_audit(item_id):
            with app.SessionLocal() as session:
                return session.scalar(select(func.count()).select_from(app.Audit)
                    .where(app.Audit.item_id == item_id))

        def fresh(item_id):
            create_spool(api, item_id, 'PG-BULK-SPOOL')
            upload_receiving_bom(api, item_id, quantity=3)
            save_receiving_materials(api, item_id)
            return receiving_detail(api, item_id)

        first, sibling, rollback = 'PG-BULK-FIRST', 'PG-BULK-SIBLING', 'PG-BULK-ROLLBACK'
        fresh(first)
        sibling_before = fresh(sibling)
        blocked = edit_piece(api, first, 2, mtr_reference='')
        path = f'/api/spool-boms/spools/{first}/materials/qa-001/pass-all'
        before = count_audit(first)
        response = api.post(path, payload(blocked), role='inspector')
        assert response.status_code == 409, response.text
        assert count_decisions(first) == 0 and count_audit(first) == before
        checks.append('One incomplete piece rejects the complete batch with no inspection or audit writes.')

        current = save_receiving_materials(api, first)
        reread = receiving_detail(api, first)
        for saved, fetched in zip(current['traceability']['materials'], reread['traceability']['materials']):
            assert saved['qa001']['basis_sha256'] == fetched['qa001']['basis_sha256'], {
                'message': 'The material PUT must return the same usable QA basis as an immediate GET.',
                'piece_key': saved['piece_key'],
                'differences': {key: [saved[key], fetched[key]] for key in saved
                                if key != 'qa001' and saved[key] != fetched[key]},
            }
        body = payload(current)
        gate, connections = Barrier(2), set()

        def synchronize(connection, cursor, statement, params, context, many):
            if 'pg_advisory_xact_lock' in statement and id(connection) not in connections:
                connections.add(id(connection))
                gate.wait(timeout=15)

        def request():
            worker = TestAPI(app, app.SessionLocal)
            try:
                result = worker.post(path, body, role='inspector')
                return result.status_code, result.json()
            finally:
                worker.client.close()

        event.listen(app.engine, 'before_cursor_execute', synchronize)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(request) for _ in range(2)]
                responses = [future.result(timeout=40) for future in futures]
        finally:
            event.remove(app.engine, 'before_cursor_execute', synchronize)
        assert sorted(status for status, _ in responses) == [200, 409], responses
        detail = receiving_detail(api, first)
        assert count_decisions(first) == 3
        assert all(piece['qa001']['version'] == 1 and piece['qa001']['can_proceed']
                   for piece in detail['traceability']['materials'])
        assert not detail['arrival']['can_proceed']
        with app.SessionLocal() as session:
            events = list(session.scalars(select(SpoolMaterialInspection)
                .where(SpoolMaterialInspection.spool_id == first)))
            assert len({row.at for row in events}) == 1
            assert all(row.actor == BADGES['inspector'] for row in events)
        assert receiving_detail(api, sibling) == sibling_before
        checks.append('Concurrent PASS ALL requests yield one success and one conflict, exactly three separate decisions at one time, and no sibling or arrival approval.')
        response = api.post(path, payload(detail), role='inspector')
        assert response.status_code == 200, response.text
        assert count_decisions(first) == 3
        checks.append('A fresh request preserves already-current Pass decisions without duplicate history.')

        rollback_detail = fresh(rollback)
        before = count_audit(rollback)
        injected = {'fired': False}

        def fail_after_insert(connection, cursor, statement, params, context, many):
            if not injected['fired'] and 'INSERT INTO spool_material_inspections' in statement:
                injected['fired'] = True
                raise RuntimeError('Synthetic failure after bulk inspection INSERT, before commit.')

        event.listen(app.engine, 'after_cursor_execute', fail_after_insert)
        try:
            try:
                response = api.post(f'/api/spool-boms/spools/{rollback}/materials/qa-001/pass-all',
                    payload(rollback_detail), role='inspector')
                assert response.status_code >= 500, response.text
            except Exception:
                if not injected['fired']:
                    raise
        finally:
            event.remove(app.engine, 'after_cursor_execute', fail_after_insert)
        assert injected['fired']
        assert count_decisions(rollback) == 0 and count_audit(rollback) == before
        assert receiving_detail(api, rollback) == rollback_detail
        checks.append('A forced failure after SQL INSERT rolls back every piece decision and audit entry.')

        original = rollback_detail['traceability']['materials'][0]
        ok(decide(api, rollback, original, 'Fail'), 201)
        fields = ('piece_key', 'supplier', 'supplier_piece_id', 'heat_number', 'mtr_reference', 'mtr_url', 'notes')
        materials = [{key: piece[key] for key in fields} for piece in rollback_detail['traceability']['materials']]
        materials[0]['heat_number'] = 'SHOULD-NOT-BE-SAVED'
        before = count_audit(rollback)
        response = api.put(f'/api/spool-boms/spools/{rollback}/traceability', {
            'expected_version': rollback_detail['traceability']['version'],
            'expected_bom_sha256': rollback_detail['source_status']['expected_bom_sha256'],
            'reason': 'Synthetic guarded save after another inspector recorded Fail.',
            'materials': materials,
            'qa001_guard': {'piece_key': original['piece_key'],
                'expected_version': original['qa001']['version'],
                'basis_sha256': original['qa001']['basis_sha256']},
        }, role='inspector')
        assert response.status_code == 409, response.text
        after = receiving_detail(api, rollback)
        assert after['traceability']['materials'][0]['heat_number'] == original['heat_number']
        assert after['traceability']['materials'][0]['qa001']['status'] == 'failed'
        assert count_audit(rollback) == before
        checks.append('The combined material-save guard rejects an unseen concurrent Fail without changing material values.')
        return {'status': 'passed', 'postgresql': version, 'groups': len(checks), 'checks': checks}
    finally:
        if api is not None:
            api.client.close()
        if app is not None:
            app.engine.dispose()
        if control is not None:
            if created:
                with control.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            control.dispose()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn', required=True)
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.dsn), indent=2))
