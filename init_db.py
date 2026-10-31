import os
from sqlalchemy import text
from sqlalchemy.orm import Session
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
    'spool_arrival_inspections',
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
    with engine.begin() as c:
        if c.dialect.name == 'postgresql':
            c.execute(text("SET LOCAL lock_timeout = '30s'"))
            c.execute(text('SELECT pg_advisory_xact_lock(647334246)'))
        Base.metadata.create_all(c)
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
    print('Schema ready: legacy records preserved; purchase orders, administration, weld, timing, process flow, transfers, audit readiness and Job Packet tables available')
if __name__=='__main__':initialize()


