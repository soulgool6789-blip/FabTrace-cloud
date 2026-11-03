"""Extend reversible removal to separate GPN and saved spool-entry records.

Existing removal batches, versions and reasons are copied exactly. No purchase
order, production record, linked file or audit history is rewritten.
"""
import re

from sqlalchemy import MetaData, inspect, select, text
from sqlalchemy.schema import CreateTable


def migrate_removal_kinds(connection):
    """Run within initialization's existing transaction and topology lock."""
    from main import Base
    from removals import KINDS, RecordRemoval

    schema = inspect(connection)
    table = RecordRemoval.__table__
    if not schema.has_table(table.name):
        return False
    expected = {'ck_record_removal_kind': 'kind',
                'ck_record_removal_root_kind': 'root_kind'}
    checks = {row['name']: row['sqltext'] for row in schema.get_check_constraints(table.name)}
    if not all(name in checks for name in expected):
        raise RuntimeError('Unexpected removal constraints; refusing to replace unrecognized schema')
    if all(set(KINDS).issubset(set(re.findall(r"'([^']+)'", checks[name])))
           for name in expected):
        return False
    dialect = connection.dialect.name
    if dialect == 'postgresql':
        allowed = ','.join("'" + kind + "'" for kind in KINDS)
        for name, column in expected.items():
            # Names and allowed values come only from this fixed schema.
            connection.execute(text(f'ALTER TABLE record_removals DROP CONSTRAINT {name}'))
            connection.execute(text(f'ALTER TABLE record_removals ADD CONSTRAINT {name} '
                                    f'CHECK ({column} IN ({allowed}))'))
    elif dialect == 'sqlite':
        columns = [column.name for column in table.columns]
        if {row['name'] for row in schema.get_columns(table.name)} != set(columns):
            raise RuntimeError('Unexpected removal columns; refusing to discard data during migration')
        # No application table references these mutable state rows. Refuse an
        # unknown inbound dependency rather than disabling foreign-key checks.
        if any(key.get('referred_table') == table.name
               for name in schema.get_table_names() if name != table.name
               for key in schema.get_foreign_keys(name)):
            raise RuntimeError('Unexpected foreign key to removal state; migration requires review')
        artifacts = connection.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE tbl_name='record_removals' "
            "AND type IN ('index','trigger') AND sql IS NOT NULL")).all()
        metadata = MetaData()
        Base.metadata.tables['employees'].to_metadata(metadata)
        replacement = table.to_metadata(metadata, name='record_removals_po_edit_v1')
        connection.execute(CreateTable(replacement))
        connection.execute(replacement.insert().from_select(
            columns, select(*(table.c[column] for column in columns))))
        connection.exec_driver_sql('DROP TABLE record_removals')
        connection.exec_driver_sql('ALTER TABLE record_removals_po_edit_v1 RENAME TO record_removals')
        managed = {index.name for index in table.indexes}
        for name, sql in artifacts:
            if name not in managed:
                connection.exec_driver_sql(sql)
        for index in sorted(table.indexes, key=lambda row: row.name):
            index.create(connection, checkfirst=True)
        if connection.exec_driver_sql('PRAGMA foreign_key_check').first() is not None:
            raise RuntimeError('Removal migration found invalid foreign keys; no changes were committed')
    else:
        raise RuntimeError('Removal-kind migration supports PostgreSQL and SQLite')
    return True
