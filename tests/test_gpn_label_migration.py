"""Exact, additive business-label correction in disposable test databases."""
import hashlib
import importlib
import json

import pytest
from sqlalchemy import inspect, text

from fixture_accounts import BADGES


TARGET_PROJECT = 'PO-1F80E4618276345B54CEBFFA'
TARGET_GROUP = 'OGPN-90D187E3E996EDE04EB841E8'
RAW_GPN = '1193403643-777'
BUSINESS_GPN = '1193403'
ASSEMBLY_NUMBER = '643-777'
OTHER_PROJECT = 'MIGRATION-OTHER-PO'
OTHER_GROUP = 'MIGRATION-OTHER-GPN'
LOOKALIKE_GROUP = 'MIGRATION-LOOKALIKE-GPN'
MIGRATION_ACTOR = 'system:init-db:gpn-label-v1'


def _engine(api):
    return api.session_factory.kw['bind']


def _rows(api):
    """Compare stored values, including retained JSON and document bytes."""
    with _engine(api).connect() as connection:
        return {
            table.name: [dict(row) for row in connection.exec_driver_sql(
                'SELECT * FROM "' + table.name + '" ORDER BY ' +
                ', '.join('"' + column.name + '"' for column in table.primary_key.columns)
            ).mappings()]
            for table in api.application.Base.metadata.sorted_tables
        }


def _seed(api, *, target=True):
    """Synthetic physical records use the migration's exact observed anchor."""
    from flow import FlowEvent
    from order_setup import OrderAssemblyRequirement, OrderSpoolRequirement
    from order_spools import OrderSpool, SpoolQrIdentity
    from orders import OrderAssembly, OrderGpn, PurchaseOrder, _key
    from spool_boms import SpoolBomEvent, SpoolBomMaterial, SpoolBomTrace
    from spool_documents import SpoolDocument, SpoolDocumentFile, SpoolDocumentSet
    from spool_receiving import SpoolArrivalInspection, SpoolMaterialInspection
    from tracking import Project, SpoolPlan

    app, actor = api.application, BADGES['admin']
    with api.session_factory.begin() as session:
        projects = [(OTHER_PROJECT, '1168019')]
        if target:
            projects.append((TARGET_PROJECT, 'Kelvion-01'))
        for identity, number in projects:
            session.add(Project(id=identity, name='Synthetic migration ' + number,
                                created_by=actor))
        session.flush()
        for identity, number in projects:
            session.add(PurchaseOrder(project_id=identity, purchase_order=number,
                normalized_number=_key(number), customer='', normalized_customer='',
                version=13 if identity == TARGET_PROJECT else 7, created_by=actor))
        session.flush()
        for identity, project, gpn in (
            (OTHER_GROUP, OTHER_PROJECT, BUSINESS_GPN),
            (LOOKALIKE_GROUP, OTHER_PROJECT, RAW_GPN),
        ):
            session.add(OrderGpn(id=identity, project_id=project, gpn=gpn,
                normalized_gpn=_key(gpn), gpn_label=None, assembly_number='',
                normalized_assembly_number=None, created_by=actor))
        if not target:
            return
        session.add(OrderGpn(id=TARGET_GROUP, project_id=TARGET_PROJECT, gpn=RAW_GPN,
            normalized_gpn=_key(RAW_GPN), gpn_label=None, assembly_number='',
            normalized_assembly_number=None, created_by=actor))
        session.flush()
        session.add(OrderAssemblyRequirement(gpn_id=TARGET_GROUP,
            assembly_quantity=18, created_by=actor))
        for letter in ('A', 'B'):
            number = 'MIGRATION-SPOOL-' + letter
            session.add(OrderSpoolRequirement(id='MIGRATION-REQ-' + letter,
                gpn_id=TARGET_GROUP, spool_number=number, normalized_number=_key(number),
                quantity_per_assembly=1, created_by=actor))
        for index in range(1, 19):
            parent = f'MIGRATION-ASM-{index:03d}'
            for identity, kind in [(parent, 'Assembly')] + [
                (f'MIGRATION-SPL-{index:03d}-{letter}', 'Spool') for letter in ('A', 'B')
            ]:
                session.add(app.Item(id=identity, kind=kind, description='Synthetic retained item',
                    project='Kelvion-01', google_part_number=RAW_GPN,
                    location='Synthetic bay', handler=actor))
        session.flush()
        for index in range(1, 19):
            parent = f'MIGRATION-ASM-{index:03d}'
            session.add(OrderAssembly(item_id=parent, gpn_id=TARGET_GROUP,
                assembly_part_number=RAW_GPN, required_spools=2, created_by=actor))
            session.add(SpoolPlan(item_id=parent, project_id=TARGET_PROJECT,
                planned_welds=0, zero_weld_reason='Synthetic declared zero-weld scope',
                created_by=actor))
        session.flush()
        for index in range(1, 19):
            parent = f'MIGRATION-ASM-{index:03d}'
            for letter in ('A', 'B'):
                identity = f'MIGRATION-SPL-{index:03d}-{letter}'
                number = 'MIGRATION-SPOOL-' + letter
                display = f'{number}-[{index:03d}]'
                session.add(OrderSpool(item_id=identity, assembly_id=parent,
                    requirement_id='MIGRATION-REQ-' + letter, created_by=actor))
                session.add(SpoolPlan(item_id=identity, project_id=TARGET_PROJECT,
                    assembly_id=parent, planned_welds=0,
                    zero_weld_reason='Synthetic declared zero-weld scope', created_by=actor))
                session.add(SpoolQrIdentity(item_id=identity, spool_number=number,
                    normalized_number=_key(number), sequence=index, display_code=display,
                    normalized_code=_key(display), created_by=actor, source='test-fixture'))
        session.flush()
        spool = 'MIGRATION-SPL-001-A'
        basis = {'gpn_id': TARGET_GROUP, 'gpn': RAW_GPN,
                 'assembly_part_number': RAW_GPN, 'historical_note': 'Preserve exact evidence'}
        fingerprint = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
        session.add(SpoolBomTrace(spool_id=spool, catalog_id='synthetic-retained-source',
            spool_number='MIGRATION-SPOOL-A', source_sha256=fingerprint,
            definition={'lines': [], 'original_scope': basis}, version=1,
            created_by=actor, updated_by=actor))
        session.flush()
        session.add(SpoolBomMaterial(spool_id=spool, piece_key='retained-piece',
            heat_number='SYNTHETIC-HEAT', mtr_reference='SYNTHETIC-MTR', updated_by=actor))
        session.add(SpoolBomEvent(spool_id=spool, version=1, actor=actor,
            reason='Synthetic retained material history', changes=basis))
        session.add(SpoolMaterialInspection(spool_id=spool, piece_key='retained-piece',
            version=1, result='Pass', actor=BADGES['inspector'], reference='SYNTHETIC-QA',
            notes='Synthetic retained inspection', basis_sha256=fingerprint, basis=basis))
        session.add(SpoolArrivalInspection(spool_id=spool, version=1, result='Pass',
            actor=BADGES['inspector'], reference='SYNTHETIC-ARRIVAL',
            notes='Synthetic retained arrival', checks={'identity': True},
            basis_sha256=fingerprint, basis=basis))
        session.add(FlowEvent(item_id=spool, sequence=1, action='SYNTHETIC_HISTORY',
            step=15, actor=BADGES['inspector'], data=basis))
        session.add(SpoolDocumentSet(id='MIGRATION-DOC-SET', spool_id=spool,
            scope_snapshot=basis, version=1, created_by=actor))
        session.flush()
        content = b'Synthetic retained document bytes; never a production upload.'
        document_hash = hashlib.sha256(content).hexdigest()
        session.add(SpoolDocument(id='MIGRATION-DOC', set_id='MIGRATION-DOC-SET',
            kind='isometric', version=1, filename='synthetic-retained.txt',
            media_type='text/plain', size_bytes=len(content), sha256=document_hash,
            selection_sha256=document_hash, uploaded_by=actor,
            reason='Synthetic retained reference', source_files=[]))
        session.flush()
        session.add(SpoolDocumentFile(document_id='MIGRATION-DOC', content=content))
        session.add(app.Audit(item_id=spool, actor=actor,
            event='SYNTHETIC_RETAINED_HISTORY', details=basis))


def _apply(api):
    from gpn_label_corrections import apply_confirmed_gpn_label_corrections
    with api.session_factory.begin() as session:
        return apply_confirmed_gpn_label_corrections(session)


def test_exact_label_correction_preserves_physical_identity_other_orders_and_history(api):
    _seed(api)
    before = _rows(api)
    assert _apply(api) == {'applied': 1, 'already_applied': 0, 'not_applicable': 0}
    after = _rows(api)
    assert len(after['order_assemblies']) == 18
    assert len(after['order_spools']) == 36
    expected = {name: rows for name, rows in before.items()
                if name not in ('order_gpns', 'purchase_orders', 'audit_events')}
    assert {name: after[name] for name in expected} == expected
    old_groups = {row['id']: row for row in before['order_gpns']}
    new_groups = {row['id']: row for row in after['order_gpns']}
    assert new_groups[OTHER_GROUP] == old_groups[OTHER_GROUP]
    assert new_groups[LOOKALIKE_GROUP] == old_groups[LOOKALIKE_GROUP]
    changed = new_groups[TARGET_GROUP]
    assert changed['gpn_label'] == BUSINESS_GPN
    assert changed['assembly_number'] == ASSEMBLY_NUMBER
    assert changed['normalized_assembly_number'] == ASSEMBLY_NUMBER.casefold()
    for key, value in old_groups[TARGET_GROUP].items():
        if key not in ('gpn_label', 'assembly_number', 'normalized_assembly_number', 'updated_at'):
            assert changed[key] == value, key
    old_orders = {row['project_id']: row for row in before['purchase_orders']}
    new_orders = {row['project_id']: row for row in after['purchase_orders']}
    assert new_orders[OTHER_PROJECT] == old_orders[OTHER_PROJECT]
    assert new_orders[TARGET_PROJECT]['version'] == 14
    for key, value in old_orders[TARGET_PROJECT].items():
        if key not in ('version', 'updated_at'):
            assert new_orders[TARGET_PROJECT][key] == value, key
    assert after['audit_events'][:-1] == before['audit_events']
    assert len(after['audit_events']) == len(before['audit_events']) + 1
    event = after['audit_events'][-1]
    assert event['actor'] == MIGRATION_ACTOR
    evidence = json.dumps(event['details'], sort_keys=True, default=str)
    for value in (TARGET_GROUP, TARGET_PROJECT, RAW_GPN, BUSINESS_GPN, ASSEMBLY_NUMBER):
        assert value in evidence
    assert _apply(api) == {'applied': 0, 'already_applied': 1, 'not_applicable': 0}
    assert _rows(api) == after, 'Repeat startup must not increment the PO or append another event'


def test_absent_exact_target_is_a_noop_even_with_matching_gpn_elsewhere(api):
    _seed(api, target=False)
    before = _rows(api)
    assert _apply(api) == {'applied': 0, 'already_applied': 0, 'not_applicable': 1}
    assert _rows(api) == before


def test_already_matching_label_gets_one_verification_marker_without_order_change(api):
    from orders import OrderGpn, _key
    _seed(api)
    with api.session_factory.begin() as session:
        group = session.get(OrderGpn, TARGET_GROUP)
        group.gpn_label, group.assembly_number = BUSINESS_GPN, ASSEMBLY_NUMBER
        group.normalized_assembly_number = _key(ASSEMBLY_NUMBER)
    before = _rows(api)
    assert _apply(api) == {'applied': 0, 'already_applied': 1, 'not_applicable': 0}
    after = _rows(api)
    assert {key: rows for key, rows in after.items() if key != 'audit_events'} == {
        key: rows for key, rows in before.items() if key != 'audit_events'}
    assert after['audit_events'][:-1] == before['audit_events']
    assert len(after['audit_events']) == len(before['audit_events']) + 1
    assert after['audit_events'][-1]['actor'] == MIGRATION_ACTOR
    details = after['audit_events'][-1]['details']
    if isinstance(details, str):
        details = json.loads(details)
    assert details['outcome'] == 'already_correct'
    assert details['version_before'] == details['version'] == 13
    assert _apply(api) == {'applied': 0, 'already_applied': 1, 'not_applicable': 0}
    assert _rows(api) == after


def test_marker_preserves_a_later_legitimate_business_label_edit(api):
    from orders import OrderGpn, PurchaseOrder, _key
    _seed(api)
    _apply(api)
    with api.session_factory.begin() as session:
        group = session.get(OrderGpn, TARGET_GROUP)
        group.gpn_label, group.assembly_number = 'LATER-CONFIRMED-GPN', 'LATER-CONFIRMED-ASSEMBLY'
        group.normalized_assembly_number = _key(group.assembly_number)
        session.get(PurchaseOrder, TARGET_PROJECT).version += 1
    before = _rows(api)
    assert _apply(api) == {'applied': 0, 'already_applied': 1, 'not_applicable': 0}
    assert _rows(api) == before


@pytest.mark.parametrize('field,value', [
    ('gpn', 'UNEXPECTED-RAW-GPN'),
    ('normalized_gpn', 'unexpected-normalized-key'),
    ('project_id', OTHER_PROJECT),
    ('gpn_label', 'EXISTING-DIFFERENT-LABEL'),
    ('assembly_number', 'EXISTING-DIFFERENT-ASSEMBLY'),
])
def test_unexpected_target_identity_or_existing_labels_abort_without_changes(api, field, value):
    from orders import OrderGpn, _key
    _seed(api)
    with api.session_factory.begin() as session:
        if field == 'project_id':
            # Avoid an unrelated uniqueness violation before exercising the helper.
            session.delete(session.get(OrderGpn, LOOKALIKE_GROUP))
            session.flush()
        group = session.get(OrderGpn, TARGET_GROUP)
        setattr(group, field, value)
        if field == 'gpn':
            group.normalized_gpn = _key(value)
        elif field == 'assembly_number':
            group.normalized_assembly_number = _key(value)
    before = _rows(api)
    with pytest.raises(RuntimeError):
        _apply(api)
    assert _rows(api) == before


def test_existing_same_po_assembly_number_conflict_is_not_overwritten(api):
    from fastapi import HTTPException
    from orders import OrderGpn, _key
    _seed(api)
    with api.session_factory.begin() as session:
        session.add(OrderGpn(id='MIGRATION-NAMED-CONFLICT', project_id=TARGET_PROJECT,
            gpn='SYNTHETIC-DIFFERENT-GPN', normalized_gpn=_key('SYNTHETIC-DIFFERENT-GPN'),
            assembly_number=ASSEMBLY_NUMBER, normalized_assembly_number=_key(ASSEMBLY_NUMBER),
            created_by=BADGES['admin']))
    before = _rows(api)
    with pytest.raises(HTTPException) as error:
        _apply(api)
    assert error.value.status_code == 409
    assert _rows(api) == before


@pytest.mark.parametrize('kind,identity', [('order', TARGET_PROJECT), ('gpn', TARGET_GROUP)])
def test_removed_target_scope_is_not_corrected(api, kind, identity):
    from removals import RecordRemoval
    _seed(api)
    with api.session_factory.begin() as session:
        session.add(RecordRemoval(kind=kind, record_id=identity, removed=True,
            version=1, batch_id='MIGRATION-SYNTHETIC-REMOVAL', root_kind=kind,
            root_id=identity, reason='Synthetic retained removal', changed_by=BADGES['admin']))
    before = _rows(api)
    with pytest.raises(RuntimeError, match='removed'):
        _apply(api)
    assert _rows(api) == before


def test_label_correction_obeys_callers_transaction_and_rolls_back_its_audit(api):
    from gpn_label_corrections import apply_confirmed_gpn_label_corrections
    _seed(api)
    before = _rows(api)
    with pytest.raises(RuntimeError, match='Synthetic subsequent initialization failure'):
        with api.session_factory.begin() as session:
            apply_confirmed_gpn_label_corrections(session)
            session.flush()
            raise RuntimeError('Synthetic subsequent initialization failure')
    assert _rows(api) == before


@pytest.mark.parametrize('older_assembly_schema', [False, True])
def test_startup_adds_nullable_label_before_optional_assembly_rebuild_and_is_idempotent(
        api, monkeypatch, older_assembly_schema):
    _seed(api, target=False)
    before = _rows(api)
    initializer = importlib.import_module('init_db')
    if older_assembly_schema:
        from test_assembly_identity_migration import legacy_schema
        engine = legacy_schema(api)
    else:
        engine = _engine(api)
        with engine.begin() as connection:
            connection.exec_driver_sql('ALTER TABLE order_gpns DROP COLUMN gpn_label')
    monkeypatch.setattr(initializer, 'engine', engine)
    initializer.initialize()
    with engine.connect() as connection:
        columns = {column['name']: column for column in inspect(connection).get_columns('order_gpns')}
        assert columns['gpn_label']['nullable'] is True
        assert connection.scalar(text('SELECT count(*) FROM order_gpns WHERE gpn_label IS NOT NULL')) == 0
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
    after = _rows(api)
    # The new independent GPN hierarchy adds only its own master/link rows.
    # All pre-existing identities, source bytes, history and QA stay unchanged.
    added_tables = {'order_google_part_numbers', 'order_assembly_gpn_links'}
    assert {name: rows for name, rows in after.items() if name not in added_tables} == {
        name: rows for name, rows in before.items() if name not in added_tables}
    assert len(after['order_google_part_numbers']) == 2
    assert {row['assembly_definition_id'] for row in after['order_assembly_gpn_links']} == {
        OTHER_GROUP, LOOKALIKE_GROUP}
    initializer.initialize()
    assert _rows(api) == after


def test_startup_conflict_rolls_back_nullable_ddl_and_all_records(api, monkeypatch):
    from orders import OrderGpn, _key
    _seed(api)
    with api.session_factory.begin() as session:
        group = session.get(OrderGpn, TARGET_GROUP)
        group.assembly_number = 'EXISTING-APPROVED-ASSEMBLY'
        group.normalized_assembly_number = _key(group.assembly_number)
    engine = _engine(api)
    with engine.begin() as connection:
        connection.exec_driver_sql('ALTER TABLE order_gpns DROP COLUMN gpn_label')
    before = _rows(api)
    with engine.connect() as connection:
        schema_before = connection.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE tbl_name='order_gpns' ORDER BY name")).all()
    initializer = importlib.import_module('init_db')
    monkeypatch.setattr(initializer, 'engine', engine)
    with pytest.raises(RuntimeError):
        initializer.initialize()
    with engine.connect() as connection:
        assert 'gpn_label' not in {column['name'] for column in inspect(connection).get_columns('order_gpns')}
        assert connection.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE tbl_name='order_gpns' ORDER BY name")).all() == schema_before
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
    assert _rows(api) == before

