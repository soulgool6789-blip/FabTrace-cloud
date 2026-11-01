"""Request-local performance reuse preserves fresh, independent QA evidence."""
from contextlib import nullcontext
from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, update

from conftest import BADGES
from read_projection import read_cached, read_projection


def seed_tree(api, count=18):
    from main import Item
    from orders import OrderAssembly, OrderGpn, PurchaseOrder
    from tracking import Project, SpoolPlan, Subproject
    actor = BADGES['admin']
    identifiers = [f'READ-SPOOL-{index:03d}' for index in range(count)]
    with api.session_factory() as s:
        s.add(Project(id='READ-PO', name='Synthetic read-performance P.O.', created_by=actor))
        s.flush()
        s.add(PurchaseOrder(project_id='READ-PO', purchase_order='READ-PO',
            normalized_number='read-po', created_by=actor))
        s.add(Subproject(id='READ-SUB', project_id='READ-PO', name='Synthetic subproject', created_by=actor))
        s.flush()
        s.add(OrderGpn(id='READ-GPN', project_id='READ-PO', gpn='READ-ASSEMBLY',
            normalized_gpn='read-assembly', created_by=actor))
        s.add(Item(id='READ-ASSEMBLY', kind='Assembly', description='Synthetic assembly',
            project='READ-PO', location='Inventory', handler=actor))
        s.flush()
        s.add(OrderAssembly(item_id='READ-ASSEMBLY', gpn_id='READ-GPN',
            assembly_part_number='READ-ASSEMBLY', required_spools=count, created_by=actor))
        s.add(SpoolPlan(item_id='READ-ASSEMBLY', project_id='READ-PO', planned_welds=0,
            zero_weld_reason='Synthetic no-weld assembly', created_by=actor))
        for identifier in identifiers:
            s.add(Item(id=identifier, kind='Spool', description='Synthetic spool',
                project='READ-PO', google_part_number='643-777-PCW-03-01',
                location='Inventory', handler=actor))
        s.flush()
        for identifier in identifiers:
            s.add(SpoolPlan(item_id=identifier, project_id='READ-PO', subproject_id='READ-SUB',
                assembly_id='READ-ASSEMBLY', planned_welds=0,
                zero_weld_reason='Synthetic no-weld scope', created_by=actor))
        s.commit()
    return identifiers


def seed_accepted_materials(api, item_id):
    """Create isolated historical evidence using the real fingerprint builders."""
    from main import Item
    from spool_boms import (SpoolBomMaterial, SpoolBomTrace, _definition,
                            _piece_definitions, physical_bom_state)
    from spool_receiving import (CHECKS, SpoolArrivalInspection, SpoolMaterialInspection,
                                 _basis, _digest, _material_qa_bases)
    actor = BADGES['inspector']
    with api.session_factory() as s:
        definition = _definition('643-777-PCW-03-01')
        s.add(SpoolBomTrace(spool_id=item_id, catalog_id=definition['catalog_id'],
            spool_number=definition['spool_number'], definition=deepcopy(definition),
            source_sha256=definition['source_workbook']['sha256'],
            created_by=actor, updated_by=actor))
        s.flush()
        for piece in _piece_definitions(definition):
            s.add(SpoolBomMaterial(spool_id=item_id, piece_key=piece['piece_key'],
                heat_number='SYNTHETIC-HEAT', mtr_reference='SYNTHETIC-MTR', updated_by=actor))
        s.flush()
        state = physical_bom_state(s, item_id)
        for key, basis in _material_qa_bases(s, state).items():
            s.add(SpoolMaterialInspection(spool_id=item_id, piece_key=key, version=1,
                result='Pass', actor=actor, reference='SYNTHETIC-PIECE-QA',
                notes='Isolated historical test evidence', basis=basis, basis_sha256=_digest(basis)))
        s.flush()
        evidence, blockers = _basis(s, s.get(Item, item_id))
        assert not blockers
        s.add(SpoolArrivalInspection(spool_id=item_id, version=1, result='Pass', actor=actor,
            reference='SYNTHETIC-ARRIVAL', notes='Isolated historical test evidence',
            checks={row['key']: True for row in CHECKS}, basis=evidence, basis_sha256=_digest(evidence)))
        s.commit()


def read_with_count(api, function, enabled):
    engine = api.session_factory.kw['bind']
    statements = []

    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement.upper().lstrip())

    event.listen(engine, 'before_cursor_execute', observe)
    try:
        with api.session_factory() as s:
            with read_projection(s) if enabled else nullcontext():
                result = function(s)
            assert 'fabtrace_read_projection' not in s.info
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert not any(sql.startswith(('INSERT ', 'UPDATE ', 'DELETE ', 'LOCK '))
                   or 'FOR UPDATE' in sql or 'PG_ADVISORY' in sql for sql in statements)
    return result, len(statements)


@pytest.mark.parametrize('view', ['order', 'progress', 'board'])
def test_full_nested_payload_parity_and_substantial_query_reduction(api, monkeypatch, view):
    import orders
    import production_progress
    import spool_presentation
    seed_tree(api)
    fixed = api.application.utcnow()
    monkeypatch.setattr(production_progress, 'utcnow', lambda: fixed)
    function = {'order': lambda s: orders.order_detail(s, 'READ-PO', 'inspector'),
        'progress': lambda s: production_progress._tree(s, 'READ-PO'),
        'board': lambda s: spool_presentation.physical_spool_board(s, 'READ-PO')}[view]
    uncached, before = read_with_count(api, function, False)
    cached, after = read_with_count(api, function, True)
    assert cached == uncached, 'Every status, blocker, child, permission and identity must match'
    assert after < before * 0.45, (view, before, after)


def test_accepted_fingerprints_roles_history_and_mutable_payloads_are_independent(api):
    from main import Item
    from spool_boms import _spool_detail, physical_bom_state
    from spool_receiving import _physical_summary
    item_id = seed_tree(api, 1)[0]
    seed_accepted_materials(api, item_id)
    with api.session_factory() as s:
        expected = {role: _spool_detail(s, item_id, role) for role in ('inspector', 'handler')}
        item = s.get(Item, item_id)
        assert expected['inspector']['arrival']['can_proceed']
        with read_projection(s):
            for role in ('handler', 'inspector'):
                assert _spool_detail(s, item_id, role) == expected[role]
            assert _physical_summary(s, item, 'inspector')['permissions']['can_inspect']
            assert not _physical_summary(s, item, 'handler')['permissions']['can_inspect']
            assert not _physical_summary(s, item, 'inspector')['history']
            historical = _physical_summary(s, item, 'inspector', history=True)
            assert len(historical['history']) == 1
            historical['history'].clear()
            historical['blockers'].append('This caller must not poison sibling readers')
            assert len(_physical_summary(s, item, 'inspector', history=True)['history']) == 1
            assert not _physical_summary(s, item, 'inspector', history=True)['blockers']
            state = physical_bom_state(s, item_id)
            state['materials'][0]['heat_number'] = 'MUTATED-RESPONSE-ONLY'
            state['definition']['lines'].clear()
            assert physical_bom_state(s, item_id)['materials'][0]['heat_number'] == 'SYNTHETIC-HEAT'
            assert physical_bom_state(s, item_id)['definition']['lines']
            assert physical_bom_state(s, item_id)['item'] is item, 'Never deep-copy attached ORM identities'


def test_new_request_observes_material_changes_and_release_gate_rejects_stale_pass(api):
    from main import Item
    from spool_boms import SpoolBomMaterial
    from spool_receiving import receiving_summary, require_receiving_pass
    item_id = seed_tree(api, 1)[0]
    seed_accepted_materials(api, item_id)
    with api.session_factory() as s, read_projection(s):
        before = receiving_summary(s, s.get(Item, item_id), 'inspector')
        assert before['can_proceed']
    with api.session_factory() as writer:
        material = writer.scalar(select(SpoolBomMaterial).where(SpoolBomMaterial.spool_id == item_id))
        material.heat_number = 'CORRECTED-SYNTHETIC-HEAT'
        writer.commit()
    with api.session_factory() as s, read_projection(s):
        current = receiving_summary(s, s.get(Item, item_id), 'inspector')
        assert current['status'] == 'needs_reinspection' and not current['can_proceed']
        assert current['basis_sha256'] != before['basis_sha256']
    # Write-gate callers do not opt in. A prior fast GET cannot authorize work.
    with api.session_factory() as writer:
        assert 'fabtrace_read_projection' not in writer.info
        with pytest.raises(HTTPException) as error:
            require_receiving_pass(writer, writer.get(Item, item_id))
        assert error.value.status_code == 409


@pytest.mark.parametrize('mutation', ['dirty', 'flush', 'dml', 'commit', 'rollback'])
def test_mis_scoped_mutation_or_transaction_boundary_disables_reuse(api, mutation):
    from main import Item
    item_id = seed_tree(api, 1)[0]
    calls = []

    @read_cached(lambda s, identity: identity)
    def read_name(s, identity):
        calls.append(identity)
        return {'description': s.get(Item, identity).description}

    with api.session_factory() as s:
        with read_projection(s):
            assert read_name(s, item_id) == read_name(s, item_id)
            assert len(calls) == 1
            with read_projection(s):
                read_name(s, item_id)
            assert len(calls) == 1
            if mutation == 'dml':
                s.execute(update(Item).where(Item.id == item_id).values(description='Changed by synthetic DML'))
            elif mutation in ('dirty', 'flush', 'commit'):
                s.get(Item, item_id).description = 'Changed synthetic item'
                if mutation != 'dirty':
                    getattr(s, mutation)()
            else:
                s.rollback()
            result = read_name(s, item_id)
            assert len(calls) == 2
            if mutation == 'rollback':
                assert result['description'] == 'Synthetic spool'
            else:
                assert result['description'].startswith('Changed')
        assert 'fabtrace_read_projection' not in s.info
        read_name(s, item_id)
        assert len(calls) == 3


def test_removed_parent_is_fresh_in_next_scope_and_flow_detail_supplies_project_context(api):
    from main import Employee, Item
    from flow import ComponentLink, detail
    from removals import RecordRemoval, require_active_item
    item_id = seed_tree(api, 1)[0]
    actor = BADGES['admin']
    with api.session_factory() as s:
        s.add(Item(id='READ-PART', kind='Part', description='Synthetic component',
            project='', location='Inventory', handler=actor))
        s.flush()
        s.add(ComponentLink(component_id='READ-PART', spool_id=item_id, assigned_by=actor))
        s.commit()
        with read_projection(s):
            require_active_item(s, item_id)
            result = detail(s, s.get(Item, 'READ-PART'), s.get(Employee, actor))
            assert (result['project_id'], result['subproject_id']) == ('READ-PO', 'READ-SUB')
    with api.session_factory() as s:
        s.add(RecordRemoval(kind='item', record_id='READ-ASSEMBLY', removed=True, version=1,
            batch_id='READ-REMOVAL', root_kind='item', root_id='READ-ASSEMBLY',
            reason='Synthetic parent removed between reads', changed_by=actor))
        s.commit()
    with api.session_factory() as s, read_projection(s):
        with pytest.raises(HTTPException) as error:
            require_active_item(s, item_id)
        assert error.value.status_code == 409
