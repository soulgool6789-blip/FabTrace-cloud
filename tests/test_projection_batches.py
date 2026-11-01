"""Bounded batches preserve complete evidence and only live for one read."""
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select

from conftest import BADGES
from test_read_projection import seed_accepted_materials, seed_tree
from read_projection import (PROJECTION_MISSING, prime_projection, projection_get,
                             read_get, read_projection)


def capture(api, reader, prime):
    statements = []
    engine = api.session_factory.kw['bind']
    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        with api.session_factory() as s, read_projection(s):
            if prime:
                prime_projection(s, prime)
            result = reader(s)
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert not any(sql.lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE '))
                   or 'FOR UPDATE' in sql.upper() for sql in statements)
    assert not any('spool_document_files' in sql or 'spool_mtr_files' in sql for sql in statements)
    return result, statements


def test_batched_receiving_preserves_accepted_evidence_roles_history_and_next_request(api):
    from main import Item
    from spool_boms import SpoolBomMaterial, _spool_detail
    from spool_receiving import _physical_summary, receiving_summary, require_receiving_pass
    identifiers = seed_tree(api, 2)
    for item_id in identifiers:
        seed_accepted_materials(api, item_id)

    def complete(s):
        return {item_id: {role: {'detail': _spool_detail(s, item_id, role),
            'arrival_history': _physical_summary(s, read_get(s, Item, item_id), role, history=True)}
            for role in ('handler', 'inspector')} for item_id in identifiers}
    before, _ = capture(api, complete, [])
    after, _ = capture(api, complete, identifiers)
    assert before == after
    assert all(after[key]['inspector']['detail']['arrival']['can_proceed'] for key in identifiers)
    with api.session_factory() as writer:
        row = writer.scalar(select(SpoolBomMaterial).where(SpoolBomMaterial.spool_id == identifiers[0]))
        row.heat_number = 'CHANGED-AFTER-FAST-READ'
        writer.commit()
    with api.session_factory() as s, read_projection(s):
        prime_projection(s, identifiers)
        current = receiving_summary(s, read_get(s, Item, identifiers[0]), 'inspector')
        assert current['status'] == 'needs_reinspection' and not current['can_proceed']
        assert current['basis_sha256'] != before[identifiers[0]]['inspector']['detail']['arrival']['basis_sha256']
        assert receiving_summary(s, read_get(s, Item, identifiers[1]), 'inspector')['can_proceed']
    with api.session_factory() as writer, pytest.raises(HTTPException) as error:
        require_receiving_pass(writer, writer.get(Item, identifiers[0]))
    assert error.value.status_code == 409


def test_single_spool_batch_is_bounded_and_negative_rows_do_not_repeat_queries(api):
    from main import Item
    from flow import FlowPlan
    identifiers = seed_tree(api, 5)
    with api.session_factory() as s, read_projection(s):
        prime_projection(s, identifiers[:1])
        assert projection_get(s, ('row', Item), 'READ-ASSEMBLY') is not PROJECTION_MISSING
        assert projection_get(s, ('row', Item), identifiers[1]) is PROJECTION_MISSING
        assert projection_get(s, ('row', FlowPlan), identifiers[0]) is None
        engine = s.get_bind()
        statements = []
        def observe(connection, cursor, statement, parameters, context, many):
            statements.append(statement)
        event.listen(engine, 'before_cursor_execute', observe)
        try:
            assert read_get(s, FlowPlan, identifiers[0]) is None
            assert read_get(s, FlowPlan, identifiers[0]) is None
            prime_projection(s, identifiers[:1])
        finally:
            event.remove(engine, 'before_cursor_execute', observe)
        assert not statements


def test_document_history_fallback_and_mtr_revision_groups_match_without_binary_reads(api):
    from spool_documents import SpoolDocument, SpoolDocumentSet, _documents, _set_for
    from spool_receiving import SpoolMtrDocument, _current_mtrs
    identifiers = seed_tree(api, 2)
    actor = BADGES['admin']
    now = api.application.utcnow()
    with api.session_factory() as s:
        for index, item_id in enumerate(identifiers):
            set_id = 'BATCH-SET-' + str(index)
            s.add(SpoolDocumentSet(id=set_id, spool_id=item_id, scope_snapshot={}, version=104, created_by=actor))
            s.flush()
            for version in range(1, 105 if index == 0 else 4):
                s.add(SpoolDocument(id=f'BATCH-DOC-{index}-{version}', set_id=set_id,
                    kind='bom' if version == 1 else 'isometric', version=version,
                    filename='synthetic.pdf', media_type='application/pdf', size_bytes=10,
                    sha256='a' * 64, selection_sha256='b' * 64, uploaded_by=actor,
                    reason='Synthetic history', source_files=[]))
            for ref in ('REF-A', 'REF-B'):
                for version in (1, 2):
                    s.add(SpoolMtrDocument(id=f'BATCH-MTR-{index}-{ref}-{version}',
                        spool_id=item_id, reference=ref, reference_key=ref.lower(), version=version,
                        filename='synthetic.pdf', media_type='application/pdf', size_bytes=10,
                        sha256='c' * 64, selection_sha256='d' * 64, page_count=1, source_files=[],
                        scope_snapshot={}, uploaded_by=actor, uploaded_at=now + timedelta(seconds=version),
                        reason='Synthetic revision'))
        s.commit()

    def metadata(s):
        return {key: {'docs': [row[0] for row in _documents(s, _set_for(s, 'spools', key))],
            'mtrs': [(row.id, row.reference_key, row.version) for row in _current_mtrs(s, key)]}
            for key in identifiers}
    before, _ = capture(api, metadata, [])
    after, _ = capture(api, metadata, identifiers)
    assert before == after
    assert len(after[identifiers[0]]['docs']) == 101
    assert after[identifiers[0]]['docs'][-1]['kind'] == 'bom'
    assert all(version == 2 for value in after.values() for _, _, version in value['mtrs'])


def test_removed_and_foreign_children_remain_visible_to_assembly_guards(api):
    from main import Item
    from tracking import Project, SpoolPlan
    from removals import RecordRemoval
    from order_spools import effective_children
    from spool_receiving import receiving_summary
    identifiers = seed_tree(api, 3)
    actor = BADGES['admin']
    with api.session_factory() as s:
        s.add(Project(id='FOREIGN-PROJECT', name='Foreign scope', created_by=actor))
        s.flush()
        s.get(SpoolPlan, identifiers[0]).project_id = 'FOREIGN-PROJECT'
        s.add(RecordRemoval(kind='item', record_id=identifiers[1], removed=True, version=1,
            batch_id='BATCH-REMOVE', root_kind='item', root_id=identifiers[1], reason='Synthetic removal', changed_by=actor))
        s.commit()
    def payload(s):
        parent = read_get(s, Item, 'READ-ASSEMBLY')
        return {'summary': receiving_summary(s, parent, 'inspector'),
            'all': [item.id for item, _ in effective_children(s, parent.id, include_removed=True)],
            'active': [item.id for item, _ in effective_children(s, parent.id, include_removed=False)]}
    before, _ = capture(api, payload, [])
    after, _ = capture(api, payload, ['READ-ASSEMBLY'])
    assert after == before
    assert identifiers[0] in after['active'] and identifiers[1] not in after['active']
    assert identifiers[1] in after['all']


def test_eighteen_spool_batches_remove_most_remaining_database_roundtrips(api):
    from main import Item
    from spool_receiving import receiving_summary
    identifiers = seed_tree(api, 18)
    def summaries(s):
        return [receiving_summary(s, read_get(s, Item, key), 'inspector') for key in identifiers]
    before, queries_before = capture(api, summaries, [])
    after, queries_after = capture(api, summaries, identifiers)
    assert before == after
    assert len(queries_after) < len(queries_before) * 0.25


def test_removal_batch_refreshes_retained_identity_across_read_scopes(api):
    from sqlalchemy import update
    from removals import RecordRemoval, item_is_removed
    identifier = seed_tree(api, 1)[0]
    with api.session_factory() as s:
        retained = RecordRemoval(kind='item', record_id=identifier, removed=False, version=1,
            batch_id='RESTORED', root_kind='item', root_id=identifier,
            reason='Synthetic restored record', changed_by=BADGES['admin'])
        s.add(retained)
        s.commit()
        with read_projection(s):
            prime_projection(s, [identifier])
            assert not item_is_removed(s, identifier)
        s.commit()
        with api.session_factory() as writer:
            writer.execute(update(RecordRemoval).where(RecordRemoval.kind == 'item',
                RecordRemoval.record_id == identifier).values(removed=True, version=2))
            writer.commit()
        assert not retained.removed, 'The retained ORM identity has not been refreshed yet'
        with read_projection(s):
            prime_projection(s, [identifier])
            assert item_is_removed(s, identifier)
            assert retained.removed and retained.version == 2
