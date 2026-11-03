"""The startup schema migration retains legacy rows, FKs and acceptance evidence."""
import importlib

import pytest
from sqlalchemy import inspect, text

from receiving_helpers import accept_arrival, receiving_detail
from test_assembly_identity import legacy_unnamed, named_branch
from test_order_labels import generate, labels, public_qr_url
from test_order_setup import ROOT, create_setup, detail
from test_progress import database_state
from tracking_helpers import ok


def legacy_schema(api):
    """Restore the exact pre-feature parent schema in this disposable test DB."""
    engine = api.session_factory.kw['bind']
    with engine.connect() as connection:
        original = connection.exec_driver_sql('PRAGMA foreign_keys').scalar()
        connection.commit()
        connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
        connection.commit()
        try:
            with connection.begin():
                connection.exec_driver_sql('BEGIN IMMEDIATE')
                connection.exec_driver_sql('''CREATE TABLE order_gpns_legacy (
                    id VARCHAR(60) PRIMARY KEY, project_id VARCHAR(80) NOT NULL REFERENCES purchase_orders(project_id),
                    gpn VARCHAR(160) NOT NULL, normalized_gpn VARCHAR(480) NOT NULL,
                    description VARCHAR(500) NOT NULL, created_by VARCHAR(80) NOT NULL REFERENCES employees(badge),
                    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                    CONSTRAINT uq_order_gpn_number UNIQUE (project_id, normalized_gpn))''')
                connection.exec_driver_sql('''INSERT INTO order_gpns_legacy
                    SELECT id, project_id, gpn, normalized_gpn, description, created_by, created_at, updated_at FROM order_gpns''')
                connection.exec_driver_sql('DROP TABLE order_gpns')
                connection.exec_driver_sql('ALTER TABLE order_gpns_legacy RENAME TO order_gpns')
                connection.exec_driver_sql('CREATE INDEX ix_order_gpns_project_id ON order_gpns (project_id)')
                connection.exec_driver_sql('CREATE INDEX order_gpns_extra_description ON order_gpns (description)')
                connection.exec_driver_sql("CREATE TRIGGER order_gpns_extra_guard BEFORE DELETE ON order_gpns BEGIN SELECT RAISE(ABORT, 'retain group'); END")
        finally:
            connection.exec_driver_sql('PRAGMA foreign_keys=' + ('ON' if original else 'OFF'))
            connection.commit()
    return engine


def test_startup_migrates_existing_sqlite_idempotently_without_inventing_assembly_numbers_or_changing_history(api, monkeypatch):
    saved = create_setup(api, assemblies=[named_branch('MIGRATION-ASM')])
    project = saved['order']['project_id']
    generate(api, project)
    spool = labels(api, project)['items'][0]
    accepted = accept_arrival(api, spool['id'])
    saved = legacy_unnamed(api, saved)
    before = database_state(api)
    initializer = importlib.import_module('init_db')
    engine = legacy_schema(api)
    monkeypatch.setattr(initializer, 'engine', engine)
    initializer.initialize()
    assert database_state(api) == before
    initializer.initialize()
    assert database_state(api) == before
    current = detail(api, project)
    assert current['assemblies'][0]['assembly_number'] == ''
    assert current['assemblies'][0]['gpn'] == saved['assemblies'][0]['gpn']
    receipt = receiving_detail(api, spool['id'])
    assert receipt['arrival']['can_proceed'] and receipt['arrival']['latest'] == accepted['arrival']['latest']
    with engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        schema = inspect(connection)
        assert not any(set(row['column_names']) == {'project_id', 'normalized_gpn'}
                       for row in schema.get_unique_constraints('order_gpns'))
        names = {row['name'] for row in schema.get_indexes('order_gpns')}
        assert {'uq_order_named_assembly_number', 'uq_order_legacy_gpn_number', 'order_gpns_extra_description'} <= names
        assert connection.scalar(text("SELECT COUNT(*) FROM sqlite_master WHERE name='order_gpns_extra_guard' AND type='trigger'")) == 1
    added = ok(api.post(f'{ROOT}/{project}/assemblies', {
        **named_branch('ACTUAL-ASM-A'), 'expected_version': current['order']['version']}), 201)
    added = ok(api.post(f'{ROOT}/{project}/assemblies', {
        **named_branch('ACTUAL-ASM-B'), 'expected_version': added['order']['version']}), 201)
    assert len(added['assemblies']) == 3
    before = database_state(api)
    for number in ('ACTUAL-ASM-A', ''):
        response = api.post(f'{ROOT}/{project}/assemblies', {
            **named_branch(number), 'expected_version': added['order']['version']})
        assert response.status_code == (409 if number else 422) and database_state(api) == before


def test_failed_startup_rolls_back_sqlite_schema_replacement_and_restores_fk_enforcement(api, monkeypatch):
    import spool_boms

    create_setup(api, assemblies=[named_branch('MIGRATION-ROLLBACK-ASM')])
    engine = legacy_schema(api)
    initializer = importlib.import_module('init_db')
    monkeypatch.setattr(initializer, 'engine', engine)
    with engine.connect() as connection:
        schema_before = connection.execute(text("SELECT name, sql FROM sqlite_master WHERE tbl_name='order_gpns' ORDER BY name")).all()
        rows_before = connection.execute(text('SELECT * FROM order_gpns')).all()
        children_before = connection.execute(text('SELECT * FROM order_spool_requirements')).all()

    def fail_after_migration(*args):
        raise RuntimeError('Synthetic post-migration initialization failure')

    monkeypatch.setattr(spool_boms, 'backfill_material_piece_records', fail_after_migration)
    with pytest.raises(RuntimeError, match='Synthetic post-migration'):
        initializer.initialize()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name, sql FROM sqlite_master WHERE tbl_name='order_gpns' ORDER BY name")).all() == schema_before
        assert connection.execute(text('SELECT * FROM order_gpns')).all() == rows_before
        assert connection.execute(text('SELECT * FROM order_spool_requirements')).all() == children_before
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1


