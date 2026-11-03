"""Catalog binding is additive and leaves old traveler cursors unmodified."""
import importlib
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect, text


def test_nullable_catalog_migration_preserves_rows_and_historical_step_meanings(application):
    initializer = importlib.import_module('init_db')
    flow = importlib.import_module('flow')
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE flow_plans (item_id TEXT PRIMARY KEY, current_step INTEGER, status TEXT)'))
            connection.execute(text("INSERT INTO flow_plans VALUES ('OLD-READY',23,'active'),('OLD-SHIP',24,'active'),('OLD-DONE',NULL,'shipped')"))
            connection.execute(text('CREATE TABLE flow_events (id INTEGER PRIMARY KEY, data TEXT)'))
            connection.execute(text("INSERT INTO flow_events VALUES (1,'retained step 23 shipping evidence')"))
            before = connection.execute(text('SELECT item_id,current_step,status FROM flow_plans ORDER BY item_id')).all()
            history = connection.execute(text('SELECT * FROM flow_events')).all()
            initializer._migrate_flow_catalog_v1(connection)
            initializer._migrate_flow_catalog_v1(connection)
            columns = {row['name']: row for row in inspect(connection).get_columns('flow_plans')}
            assert columns['catalog_version']['nullable']
            assert columns['catalog_version']['default'] is None
            assert connection.execute(text('SELECT item_id,current_step,status FROM flow_plans ORDER BY item_id')).all() == before
            assert connection.scalar(text('SELECT count(*) FROM flow_plans WHERE catalog_version IS NOT NULL')) == 0
            assert connection.execute(text('SELECT * FROM flow_events')).all() == history
        old = SimpleNamespace(route='assembly', catalog_version=None)
        assert flow.catalog_version(old) == 'CLM-24-v6'
        assert flow.ready_to_ship_step(old) == 23 and flow.shipment_step(old) == 24
        assert 'Ready to Ship' in flow.step_definition(old, 23)['title']
        assert 'Ship to Customer' in flow.step_definition(old, 24)['title']
        current = SimpleNamespace(route='assembly', catalog_version='CLM-25-v1')
        assert flow.step_definition(current, 23)['title'] == 'Return to Floor'
        assert flow.ready_to_ship_step(current) == 24 and flow.shipment_step(current) == 25
    finally:
        engine.dispose()
