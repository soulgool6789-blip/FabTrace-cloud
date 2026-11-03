import os
from contextlib import contextmanager
from sqlalchemy import MetaData, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable
from main import Base,engine,Employee,password_hash

# These are history records, not the editable current-state rows. The API only
# inserts them; PostgreSQL also prevents routine UPDATE/DELETE outside the API.
HISTORY_TABLES = (
    'audit_events',
    'tracking_requirement_evidence',
    'tracking_requirement_reviews',
    'tracking_weld_work',
    'tracking_weld_repairs',
    'tracking_requirement_templates',
    'tracking_process_events',
    'flow_events',
    'spool_parts_events',
    'spool_bom_events',
    'spool_qr_identities',
    'spool_arrival_inspections',
    'spool_material_inspections',
    'spool_mtr_documents',
    'spool_mtr_files',
    'spool_documents',
    'spool_document_files',
    'spool_document_file_links',
    'quality_documents',
    'quality_evidence',
    'quality_reviews',
    'quality_events',
    'dossier_documents',
    'dossier_files',
    'dossier_reviews',
    'dossier_issues',
    'dossier_handovers',
    'dossier_events',
)


def _legacy_gpn_uniqueness(c):
    schema = inspect(c)
    if not schema.has_table('order_gpns'):
        return False
    return any(set(row['column_names']) == {'project_id', 'normalized_gpn'}
               for row in schema.get_unique_constraints('order_gpns'))


@contextmanager
def _schema_transaction():
    """Keep SQLite table replacement atomic and restore its connection setting.

    SQLite cannot drop a table-level UNIQUE constraint in place. Its documented
    rebuild requires foreign keys disabled before BEGIN, followed by an exact
    foreign-key check before commit. Other connections keep their own settings.
    PostgreSQL uses the existing single transaction and advisory locks below.
    """
    with engine.connect() as c:
        rebuild = c.dialect.name == 'sqlite' and _legacy_gpn_uniqueness(c)
        original_foreign_keys = c.exec_driver_sql('PRAGMA foreign_keys').scalar() if rebuild else None
        if c.in_transaction():
            c.commit()
        if rebuild:
            c.exec_driver_sql('PRAGMA foreign_keys=OFF')
            if c.exec_driver_sql('PRAGMA foreign_keys').scalar():
                raise RuntimeError('Could not prepare the SQLite assembly-number migration safely')
            c.commit()
        try:
            with c.begin():
                if c.dialect.name == 'sqlite':
                    # Explicit BEGIN also makes SQLite DDL roll back if a
                    # later initialization or integrity check fails.
                    c.exec_driver_sql('BEGIN IMMEDIATE')
                yield c
                if rebuild and c.exec_driver_sql('PRAGMA foreign_key_check').first() is not None:
                    raise RuntimeError('Assembly-number migration found invalid foreign keys; no changes were committed')
        finally:
            if rebuild:
                if c.in_transaction():
                    c.rollback()
                c.exec_driver_sql('PRAGMA foreign_keys=' + ('ON' if original_foreign_keys else 'OFF'))
                c.commit()


def _rebuild_sqlite_order_gpns(c):
    from orders import OrderGpn
    table = OrderGpn.__table__
    columns = [column.name for column in table.columns]
    if {column['name'] for column in inspect(c).get_columns(table.name)} != set(columns):
        raise RuntimeError('Unexpected order_gpns columns; refusing to discard data during migration')
    artifacts = c.execute(text("SELECT name, sql FROM sqlite_master WHERE tbl_name='order_gpns' "
                               "AND type IN ('index','trigger') AND sql IS NOT NULL")).all()
    # Resolve the replacement table's two foreign keys without creating or
    # altering their targets. Indexes are installed only after the old table
    # has been replaced, avoiding collisions with the original index names.
    metadata = MetaData()
    for target in ('purchase_orders', 'employees'):
        Base.metadata.tables[target].to_metadata(metadata)
    replacement = table.to_metadata(metadata, name='order_gpns_assembly_number_v1')
    c.execute(CreateTable(replacement))
    c.execute(replacement.insert().from_select(columns, select(*(table.c[name] for name in columns))))
    c.exec_driver_sql('DROP TABLE order_gpns')
    c.exec_driver_sql('ALTER TABLE order_gpns_assembly_number_v1 RENAME TO order_gpns')
    replaced_names = {index.name for index in table.indexes} | {'uq_order_gpn_number'}
    for name, sql in artifacts:
        if name not in replaced_names:
            c.exec_driver_sql(sql)


def _migrate_gpn_labels_v1(c):
    """Add current GPN metadata without modifying any retained identity."""
    columns = {column['name'] for column in inspect(c).get_columns('order_gpns')}
    if 'gpn_label' not in columns:
        c.execute(text('ALTER TABLE order_gpns ADD COLUMN gpn_label VARCHAR(160)'))


def _migrate_assembly_numbers_v1(c):
    """Add separate, initially unknown assembly numbers; retain every identity.

    Named assemblies are unique within one PO. GPNs may repeat across named
    assemblies; legacy/unknown-number entries retain their old GPN uniqueness.
    No GPN, physical mapping, document, QR alias or QA record is rewritten.
    """
    from orders import OrderGpn
    columns = {column['name'] for column in inspect(c).get_columns('order_gpns')}
    if 'assembly_number' not in columns:
        c.execute(text("ALTER TABLE order_gpns ADD COLUMN assembly_number VARCHAR(160) NOT NULL DEFAULT ''"))
    if 'normalized_assembly_number' not in columns:
        c.execute(text('ALTER TABLE order_gpns ADD COLUMN normalized_assembly_number VARCHAR(480)'))
    legacy = _legacy_gpn_uniqueness(c)
    if c.dialect.name == 'sqlite' and legacy:
        _rebuild_sqlite_order_gpns(c)
    elif c.dialect.name not in ('sqlite', 'postgresql'):
        raise RuntimeError('The assembly-number migration supports PostgreSQL and SQLite')
    # Install replacement uniqueness before dropping the PostgreSQL legacy
    # constraint, so the table never loses its intended uniqueness guarantees.
    for index in sorted(OrderGpn.__table__.indexes, key=lambda value: value.name):
        index.create(c, checkfirst=True)
    if c.dialect.name == 'postgresql' and legacy:
        c.execute(text('ALTER TABLE order_gpns DROP CONSTRAINT uq_order_gpn_number'))


def initialize():
    """Add missing tables without rewriting legacy items or inventing welds.

    Render runs this before starting a new version. Keep PostgreSQL DDL,
    history protection and first-account bootstrap in one transaction, with a
    transaction lock so overlapping deploys cannot initialize concurrently.
    Explicit PO weld counts live in an additive requirement table; absent
    legacy declarations remain absent until a user supplies a count.
    create_all is intentionally additive; future column changes need an
    explicit versioned migration rather than an assumption that it alters DDL.
    """
    badge=os.environ.get('BOOTSTRAP_BADGE','')
    pin=os.environ.get('BOOTSTRAP_PIN','')
    with _schema_transaction() as c:
        if c.dialect.name == 'postgresql':
            c.execute(text("SET LOCAL lock_timeout = '30s'"))
            c.execute(text('SELECT pg_advisory_xact_lock(647334246)'))
            # Runtime spool writers acquire topology before touching history.
            # Keep the same lock order before installing history triggers and
            # allocating permanent identities/material pieces during migration.
            from flow import TOPOLOGY_LOCK
            c.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': TOPOLOGY_LOCK})
        Base.metadata.create_all(c)
        # The legacy SQLite rebuild uses the complete current model schema.
        _migrate_gpn_labels_v1(c)
        _migrate_assembly_numbers_v1(c)
        from removal_migrations import migrate_removal_kinds
        migrate_removal_kinds(c)
        if c.dialect.name == 'postgresql':
            c.execute(text('''CREATE OR REPLACE FUNCTION fabtrace_no_audit_mutation()
                RETURNS trigger AS $$ BEGIN
                RAISE EXCEPTION 'Audit or traceability history modification forbidden';
                END; $$ LANGUAGE plpgsql'''))
            for table in HISTORY_TABLES:
                # Names come only from the fixed allowlist above.
                c.execute(text(f'DROP TRIGGER IF EXISTS audit_immutable ON {table}'))
                c.execute(text(f'CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON {table} '
                               'FOR EACH ROW EXECUTE FUNCTION fabtrace_no_audit_mutation()'))
        with Session(bind=c) as s:
            if s.query(Employee).count()==0:
                if not badge or len(pin)<12:
                    raise RuntimeError('Set BOOTSTRAP_BADGE and BOOTSTRAP_PIN (12+ characters) before first initialization')
                s.add(Employee(badge=badge,name='Bootstrap administrator',role='admin',pin_hash=password_hash.hash(pin)))
                s.flush()
                print('Created bootstrap administrator')
            else:
                print('Employee accounts already exist; bootstrap skipped')
            from gpn_label_corrections import apply_confirmed_gpn_label_corrections
            label_corrections=apply_confirmed_gpn_label_corrections(s)
            from orders import backfill_gpn_records
            gpn_records=backfill_gpn_records(s)
            from order_spools import backfill_spool_qr_identities
            assigned=backfill_spool_qr_identities(s)
            from spool_boms import backfill_material_piece_records
            material_records=backfill_material_piece_records(s)
            s.flush()
            print(f'Confirmed GPN labels ready: {label_corrections}')
            print(f'Separate GPN records ready: {gpn_records}')
            print(f"Spool QR labels ready: {assigned['created']} permanent labels added; {assigned['missing_spool_number']} records still need a spool number")
            print(f'Individual material records ready: {material_records}')
    print('Schema ready: legacy records preserved; purchase orders, administration, weld, timing, process flow, transfers, audit readiness and Job Packet tables available')
if __name__=='__main__':initialize()



