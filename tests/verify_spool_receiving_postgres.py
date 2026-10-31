"""Verify additive arrival history and races in a disposable LOCAL PostgreSQL schema.

Run with --dsn postgresql+psycopg://nobody@/fabtrace_test_receiving?host=/tmp/fabtrace-pg/socket&port=55432
The strict local-only guard rejects operational databases. The generated schema
is removed in finally; inherited database and libpq routing settings are ignored.
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

from sqlalchemy import create_engine, delete, event, func, inspect, select, text, update
from sqlalchemy.exc import DBAPIError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conftest import BADGES, TEST_SECRET, TestAPI
from receiving_helpers import (CHECKS, approve_materials, receiving_detail, record_arrival,
                               save_receiving_materials, upload_receiving_bom)
from test_spool_receiving import create_spool, upload_mtr, pdf
from tracking_helpers import ok
from verify_postgres import (LIBPQ_ROUTING_ENV, is_loopback_host, local_test_url,
                             seed_legacy, snapshot_legacy)


NEW_TABLES = {'spool_material_inspections', 'spool_qr_identities'}


def verify(dsn):
    url = local_test_url(dsn)
    if 'main' in sys.modules:
        raise RuntimeError('Use a fresh process with no inherited application connection')
    schema = 'fabtrace_receiving_verify_' + uuid.uuid4().hex
    control = create_engine(url)
    app = api = None
    created = False
    settings = {'DATABASE_URL': url.update_query_dict({'options': '-csearch_path=' + schema}).render_as_string(hide_password=False),
        'JWT_SECRET': TEST_SECRET, 'COOKIE_SECURE': 'false',
        'PUBLIC_BASE_URL': 'https://fabtrace-receiving-tests.example',
        'BOOTSTRAP_BADGE': '', 'BOOTSTRAP_PIN': ''}
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
        seed_legacy(app)
        # Simulate the preceding release with a retained uploaded BOM but no
        # physical material rows, QA-001 table, or readable QR identities.
        app.Base.metadata.create_all(app.engine, tables=[table for name, table in
            app.Base.metadata.tables.items() if name not in NEW_TABLES])
        from fastapi import UploadFile
        from spool_documents import SpoolDocumentSet, SpoolDocument, SpoolDocumentFile, _prepare
        context = {'kind': 'spool', 'requirement_id': None, 'item_id': 'PG-OLD-BOM',
            'spool_number': 'PG-OLD-SPOOL', 'assembly_id': None, 'assembly_number': None,
            'gpn_id': None, 'project_id': '', 'purchase_order': None}
        prepared = _prepare([UploadFile(filename='old-bom.csv', file=io.BytesIO(
            b'item,quantity,unit,part_number,description\n1,2,EA,000123,Retained synthetic material\n'))], 'bom', '', context)
        with app.SessionLocal() as s:
            s.add(app.Item(id='PG-OLD-BOM', kind='Spool', description='Retain uploaded BOM scope',
                google_part_number='PG-OLD-SPOOL', location='Synthetic receiving', handler=BADGES['handler']))
            s.flush()
            s.add(SpoolDocumentSet(id='PG-OLD-DOCSET', spool_id='PG-OLD-BOM', scope_snapshot=context,
                version=1, created_by=BADGES['handler']))
            s.flush()
            s.add(SpoolDocument(id='PG-OLD-DOC', set_id='PG-OLD-DOCSET', kind='bom', version=1,
                uploaded_by=BADGES['handler'], reason='Retained upload predates piece persistence', revision='',
                **{key: prepared[key] for key in ('filename', 'media_type', 'size_bytes', 'sha256',
                    'selection_sha256', 'page_count', 'source_files', 'bom')}))
            s.flush()
            s.add(SpoolDocumentFile(document_id='PG-OLD-DOC', content=prepared['content']))
            s.commit()
        old_tables = set(inspect(app.engine).get_table_names())
        old_columns = {name: [column['name'] for column in inspect(app.engine).get_columns(name)]
                       for name in old_tables}
        with app.engine.connect() as c:
            old_rows = {name: list(c.execute(select(app.Base.metadata.tables[name])).mappings()) for name in old_tables}
        initializer = importlib.import_module('init_db')
        with redirect_stdout(io.StringIO()):
            initializer.initialize()
        with app.engine.connect() as c:
            after_first = {name: list(c.execute(select(table)).mappings()) for name, table in app.Base.metadata.tables.items()}
        with redirect_stdout(io.StringIO()):
            initializer.initialize()
        assert set(inspect(app.engine).get_table_names()) - old_tables == NEW_TABLES
        assert all([column['name'] for column in inspect(app.engine).get_columns(name)] == columns
                   for name, columns in old_columns.items())
        with app.engine.connect() as c:
            for name, rows in old_rows.items():
                table = app.Base.metadata.tables[name]
                for row in rows:
                    retained = c.execute(select(table).where(*[key == row[key.name] for key in table.primary_key.columns])).mappings().one()
                    assert dict(retained) == dict(row), (name, row)
            for name, rows in after_first.items():
                assert list(c.execute(select(app.Base.metadata.tables[name])).mappings()) == rows, name
            assert c.scalar(select(func.count()).select_from(app.Base.metadata.tables['spool_material_inspections'])) == 0
            material_table = app.Base.metadata.tables['spool_bom_materials']
            seeded = list(c.execute(select(material_table).where(material_table.c.spool_id == 'PG-OLD-BOM')).mappings())
            assert len(seeded) == 2 and all(not row['heat_number'] and not row['mtr_reference'] for row in seeded)
            system_actor = c.execute(select(app.Employee.__table__).where(
                app.Employee.badge == 'system:material-piece-backfill')).mappings().one()
            assert system_actor['active'] is False and system_actor['role'] == 'misc'
            triggers = c.execute(text("SELECT event_object_table FROM information_schema.triggers "
                "WHERE trigger_schema=:schema AND trigger_name='audit_immutable'"), {'schema': schema}).scalars().all()
            assert NEW_TABLES <= set(triggers)
        api = TestAPI(app, app.SessionLocal)
        item_id = create_spool(api, 'PG-RECEIVING-FIRST')
        other_id = create_spool(api, 'PG-RECEIVING-SECOND')
        upload_receiving_bom(api, item_id, quantity=2)
        save_receiving_materials(api, item_id)
        original_mtr = ok(upload_mtr(api, item_id), 201)['mtr_documents']['current'][0]
        original_bytes = api.get(original_mtr['view_url']).content

        def request(method, path, body, role='inspector'):
            worker = TestAPI(app, app.SessionLocal)
            try:
                response = getattr(worker, method)(path, body, role=role)
                return {'status': response.status_code, 'body': response.json()}
            finally:
                worker.client.close()

        gate, connections = Barrier(2), set()

        def synchronize(c, cursor, statement, params, context, many):
            if 'pg_advisory_xact_lock' in statement and id(c) not in connections:
                connections.add(id(c))
                gate.wait(timeout=15)

        piece = receiving_detail(api, item_id)['traceability']['materials'][0]
        piece_path = piece['qa001']['history_url']
        piece_payload = {'expected_version': piece['qa001']['version'], 'basis_sha256': piece['qa001']['basis_sha256'],
            'result': 'Pass', 'reference': 'PG-QA-001', 'notes': 'Synthetic incoming dimensional piece evidence checked'}
        event.listen(app.engine, 'before_cursor_execute', synchronize)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                piece_decisions = [future.result(timeout=30) for future in
                    [pool.submit(request, 'post', piece_path, piece_payload) for _ in range(2)]]
        finally:
            event.remove(app.engine, 'before_cursor_execute', synchronize)
        assert sorted(row['status'] for row in piece_decisions) == [201, 409], piece_decisions
        approve_materials(api, item_id)
        arrival = receiving_detail(api, item_id)['arrival']
        payload = {'expected_version': arrival['version'], 'basis_sha256': arrival['basis_sha256'],
            'result': 'Pass', 'reference': 'PG-ARRIVAL-1',
            'notes': 'Synthetic PostgreSQL arrival evidence checked', 'checks': CHECKS}
        gate, connections = Barrier(2), set()
        path = f'/api/spool-boms/spools/{item_id}/arrival-inspections'
        event.listen(app.engine, 'before_cursor_execute', synchronize)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(request, 'post', path, payload) for _ in range(2)]
                decisions = [future.result(timeout=30) for future in futures]
        finally:
            event.remove(app.engine, 'before_cursor_execute', synchronize)
        assert sorted(result['status'] for result in decisions) == [201, 409], decisions
        current = receiving_detail(api, item_id)
        assert current['arrival']['version'] == 1 and current['arrival']['can_proceed']
        assert receiving_detail(api, other_id)['arrival']['status'] == 'pending'

        # Force a material edit to commit while a QA decision is queued. The
        # queued decision must inspect the refreshed basis after acquiring the lock.
        piece = current['traceability']['materials'][0]
        piece_payload.update(expected_version=piece['qa001']['version'], basis_sha256=piece['qa001']['basis_sha256'])
        fields = ('piece_key', 'supplier', 'supplier_piece_id', 'heat_number', 'mtr_reference', 'mtr_url', 'notes')
        material = {'expected_version': current['traceability']['version'],
            'expected_bom_sha256': current['source_status']['expected_bom_sha256'],
            'reason': 'Synthetic corrected heat received while QA queued',
            'materials': [{key: row[key] for key in fields} for row in current['traceability']['materials']]}
        for row in material['materials']:
            row['heat_number'] = 'PG-CORRECTED-HEAT'
        locked, queued = Event(), Event()
        writer = {'connection': None, 'paused': False}

        def before_lock(c, cursor, statement, params, context, many):
            if 'pg_advisory_xact_lock' in statement:
                if writer['connection'] is None:
                    writer['connection'] = id(c)
                elif id(c) != writer['connection']:
                    queued.set()

        def after_lock(c, cursor, statement, params, context, many):
            if ('pg_advisory_xact_lock' in statement and id(c) == writer['connection'] and not writer['paused']):
                writer['paused'] = True
                locked.set()
                assert queued.wait(15), 'QA writer never queued behind the material edit'

        event.listen(app.engine, 'before_cursor_execute', before_lock)
        event.listen(app.engine, 'after_cursor_execute', after_lock)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                change = pool.submit(request, 'put', f'/api/spool-boms/spools/{item_id}/traceability', material, 'handler')
                assert locked.wait(15)
                stale_qa = pool.submit(request, 'post', piece_path, piece_payload)
                changed, rejected = change.result(timeout=30), stale_qa.result(timeout=30)
        finally:
            event.remove(app.engine, 'before_cursor_execute', before_lock)
            event.remove(app.engine, 'after_cursor_execute', after_lock)
        assert changed['status'] == 200 and rejected['status'] == 409, (changed, rejected)
        current = receiving_detail(api, item_id)
        assert current['arrival']['version'] == 1 and current['arrival']['status'] == 'needs_reinspection'
        assert {row['heat_number'] for row in current['traceability']['materials']} == {'PG-CORRECTED-HEAT'}
        approve_materials(api, item_id)
        assert ok(record_arrival(api, item_id), 201)['arrival']['can_proceed']
        replaced = ok(upload_mtr(api, item_id, pdf(3), version=1), 201)
        assert replaced['arrival']['status'] == 'needs_reinspection'
        assert api.get(original_mtr['view_url']).content == original_bytes

        protected = sorted(NEW_TABLES | {'spool_bom_events', 'spool_arrival_inspections',
                                        'spool_mtr_documents', 'spool_mtr_files'})
        for name in protected:
            table = app.Base.metadata.tables[name]
            keys = list(table.primary_key.columns)
            with app.engine.connect() as c:
                row = c.execute(select(*keys).limit(1)).first()
                assert row is not None
                where = [key == value for key, value in zip(keys, row)]
            for statement in (update(table).where(*where).values({keys[0].name: row[0]}), delete(table).where(*where)):
                try:
                    with app.engine.begin() as c:
                        c.execute(statement)
                except DBAPIError as error:
                    assert getattr(error.orig, 'sqlstate', None) == 'P0001'
                    assert 'history modification forbidden' in str(error.orig)
                else:
                    raise AssertionError(f'{name} permitted immutable history mutation')
        assert api.get('/healthz', role=None).status_code == 200
        return {'postgresql_version': version, 'new_tables': sorted(NEW_TABLES),
            'old_columns_unchanged': True, 'legacy_records_unchanged': True,
            'uploaded_bom_blank_piece_backfill': 2, 'disabled_system_actor_only': True,
            'initializer_idempotent': True, 'concurrent_decisions': [201, 409],
            'concurrent_piece_decisions': [201, 409],
            'material_edit_then_queued_qa': [200, 409], 'old_mtr_bytes_retained': True,
            'independent_same_number_spools': True, 'immutable_update_and_delete': protected,
            'health': 'ok', 'schema_cleanup': 'completed'}
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
    print(json.dumps(verify(parser.parse_args().dsn), indent=2))
