"""One-time, idempotent schema upgrade for EXISTING PostgreSQL deployments.
Run after backing up database: python migrate_google_part_numbers.py
New deployments should use python init_db.py instead.
"""
from sqlalchemy import text
from main import engine
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE items ADD COLUMN IF NOT EXISTS google_part_number VARCHAR(160) NOT NULL DEFAULT ''"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_items_google_part_number ON items (google_part_number)"))
print('Google part number schema migration complete.')
