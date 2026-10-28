import os
from sqlalchemy import text
from main import Base,engine,SessionLocal,Employee,password_hash

def initialize():
    Base.metadata.create_all(engine)
    # Database-level protection against routine audit edits/deletion.
    with engine.begin() as c:
        c.execute(text('''CREATE OR REPLACE FUNCTION fabtrace_no_audit_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'Audit event modification forbidden'; END; $$ LANGUAGE plpgsql'''))
        c.execute(text('DROP TRIGGER IF EXISTS audit_immutable ON audit_events'))
        c.execute(text('CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION fabtrace_no_audit_mutation()'))
    badge=os.environ.get('BOOTSTRAP_BADGE','')
    pin=os.environ.get('BOOTSTRAP_PIN','')
    with SessionLocal() as s:
        if s.query(Employee).count()==0:
            if not badge or len(pin)<12:raise RuntimeError('Set BOOTSTRAP_BADGE and BOOTSTRAP_PIN (12+ characters) before first initialization')
            s.add(Employee(badge=badge,name='Bootstrap administrator',role='admin',pin_hash=password_hash.hash(pin)))
            s.commit()
            print('Created bootstrap administrator:',badge)
        else: print('Employee accounts already exist; bootstrap skipped')
if __name__=='__main__':initialize()
