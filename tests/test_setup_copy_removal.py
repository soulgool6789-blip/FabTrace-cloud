"""Only untouched generated copies can leave an active assembly individually."""
import importlib
import json

import pytest
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import ok
from test_order_setup import branch, create_setup
from test_order_labels import generate, labels, public_qr_url
from test_orders import plan as edit_plan
from test_progress import database_state
from test_removal_orders import change
from test_spool_documents import request_upload
from test_transfers import transfer


def setup_copy(api, count=2, *, with_bom=False):
    saved = create_setup(api, assemblies=[branch('COPY-GPN', 1, [{
        'spool_number': 'COPY-SPOOL', 'quantity_per_assembly': 1,
        'welds_per_spool': count}])])
    project = saved['order']['project_id']
    if with_bom:
        line = saved['assemblies'][0]['spools'][0]
        source = (b'Spool number,Item,Qty,Unit,Part number,Description,Heat No.,MTR Reference,Traceability Scope\n'
                  b'COPY-SPOOL,1,1,EA,000123,Pipe,000HEAT,000MTR,all copies\n')
        ok(request_upload(api, '/api/spool-documents/requirements/' + line['id'],
            files=[('Initial.csv', source, 'text/csv')]))
    generate(api, project)
    copy = labels(api, project)['items'][0]
    return saved, copy


def preview(api, item_id, action='remove'):
    return ok(api.get('/api/removals/item/' + item_id, params={'action': action}))


def body(review):
    return {key: review[key] for key in ('expected_version', 'preview_token', 'confirmation')} | {
        'reason': 'Correct an untouched synthetic generated setup copy'}


def facts(api, item_id):
    module = importlib.import_module('removal_planning')
    with api.session_factory() as session:
        return module.generated_copy_removal_facts(session, item_id)


def retained_rows(api):
    rows = json.loads(database_state(api))
    return {name: values for name, values in rows.items()
            if name not in ('audit_events', 'record_removals', 'purchase_orders')}


def assert_blocked(api, item_id):
    reviewed = preview(api, item_id)
    assert not reviewed['can_proceed'], reviewed
    before = database_state(api)
    response = api.post('/api/removals/item/' + item_id + '/remove', body(reviewed))
    assert response.status_code == 409, response.text
    assert database_state(api) == before


@pytest.mark.parametrize('weld_count', [0, 2])
def test_initial_copy_removal_retains_exact_plan_bom_qa_and_demand(api, weld_count):
    saved, copy = setup_copy(api, weld_count, with_bom=True)
    project, item_id = saved['order']['project_id'], copy['id']
    tracking = importlib.import_module('tracking')
    material = importlib.import_module('spool_boms')
    with api.session_factory() as session:
        assert session.get(api.application.Item, item_id).reinspection_due
        assert session.get(tracking.SpoolPlan, item_id).planned_welds == weld_count
        assert len(list(session.scalars(select(tracking.Weld).where(tracking.Weld.item_id == item_id)))) == weld_count
        pieces = list(session.scalars(select(material.SpoolBomMaterial).where(material.SpoolBomMaterial.spool_id == item_id)))
        assert [(row.heat_number, row.mtr_reference) for row in pieces] == [('000HEAT', '000MTR')]
    before = database_state(api)
    first = facts(api, item_id)
    assert first['eligible'], first
    assert first == facts(api, item_id), 'Eligibility facts must be stable between read-only previews'
    json.dumps(first)
    assert preview(api, item_id)['can_proceed']
    assert database_state(api) == before
    retained = retained_rows(api)

    change(api, 'item', item_id)
    assert retained_rows(api) == retained
    assert labels(api, project)['items'] == []
    order = ok(api.get('/api/orders/' + project))
    assert order['assemblies'][0]['required_spools'] == 1
    assert order['assemblies'][0]['missing_spools'] == 1
    assert ok(api.get('/api/order-setup/' + project))['totals']['total_spools'] == 1

    change(api, 'item', item_id, 'restore')
    assert retained_rows(api) == retained
    assert labels(api, project)['items'][0]['id'] == item_id
    assert labels(api, project)['items'][0]['display_code'] == copy['display_code']
    assert facts(api, item_id)['eligible'], 'Remove/restore audit history must not fabricate production'


def test_replacement_gets_new_identity_and_original_restore_obeys_capacity(api):
    saved, original = setup_copy(api)
    project = saved['order']['project_id']
    change(api, 'item', original['id'])
    result = generate(api, project)
    assert result['created_spool_count'] == 1 and result['created_assembly_count'] == 0
    replacement = labels(api, project)['items'][0]
    assert replacement['id'] != original['id']
    assert replacement['display_code'] != original['display_code']
    assert replacement['assembly_id'] == original['assembly_id']
    reviewed = preview(api, original['id'], 'restore')
    assert not reviewed['can_proceed']
    before = database_state(api)
    response = api.post('/api/removals/item/' + original['id'] + '/restore', body(reviewed))
    assert response.status_code == 409 and database_state(api) == before
    change(api, 'item', replacement['id'])
    change(api, 'item', original['id'], 'restore')
    assert labels(api, project)['items'][0]['id'] == original['id']


@pytest.mark.parametrize('scope', ['copy', 'parent'])
def test_recorded_handoff_on_copy_or_parent_blocks_the_narrow_exception(api, scope):
    _, copy = setup_copy(api)
    transfer(api, copy['id'] if scope == 'copy' else copy['assembly_id'])
    assert not facts(api, copy['id'])['eligible']
    assert_blocked(api, copy['id'])


def test_parent_change_invalidates_a_previous_copy_removal_preview(api):
    _, copy = setup_copy(api)
    old_facts, reviewed = facts(api, copy['id']), preview(api, copy['id'])
    assert reviewed['can_proceed']
    transfer(api, copy['assembly_id'])
    assert facts(api, copy['id'])['fingerprint'] != old_facts['fingerprint']
    before = database_state(api)
    result = api.post('/api/removals/item/' + copy['id'] + '/remove', body(reviewed))
    assert result.status_code == 409 and database_state(api) == before


@pytest.mark.parametrize('scope', ['copy', 'parent'])
def test_retained_inspection_without_a_new_item_audit_blocks_removal(api, scope):
    _, copy = setup_copy(api)
    with api.session_factory() as session:
        session.add(api.application.Inspection(item_id=copy['id'] if scope == 'copy' else copy['assembly_id'],
            kind='Dimensional', result='Fail', inspector=BADGES['inspector'],
            report='SYNTHETIC-RETAINED-QA', measurements='Historical failed inspection remains authoritative'))
        session.commit()
    assert_blocked(api, copy['id'])


@pytest.mark.parametrize('activity', ['work', 'review', 'requirement_cycle', 'weld_edit', 'closed_process'])
def test_work_or_qa_history_cannot_be_hidden_behind_incomplete_placeholders(api, activity):
    _, copy = setup_copy(api)
    tracking = importlib.import_module('tracking')
    production = importlib.import_module('production')
    with api.session_factory() as session:
        weld = session.scalar(select(tracking.Weld).where(tracking.Weld.item_id == copy['id']))
        requirement = session.scalar(select(tracking.WeldRequirement).where(
            tracking.WeldRequirement.weld_id == weld.id))
        if activity == 'work':
            session.add(tracking.WeldWork(weld_id=weld.id, cycle=1, operation='root',
                notes='Retained synthetic work', actor=BADGES['welder']))
        elif activity == 'review':
            session.add(tracking.RequirementReview(requirement_id=requirement.id, cycle=1,
                decision='rejected', notes='Retained failed review', actor=BADGES['inspector']))
        elif activity == 'requirement_cycle':
            requirement.cycle = 2
        elif activity == 'weld_edit':
            weld.wps = 'MANUALLY-SPECIFIED-WPS'
        else:
            session.add(production.SpoolProcessEvent(item_id=copy['id'], sequence=1,
                event='finish', process_key='welding', process_name='Welding',
                actor=BADGES['welder'], notes='Retained closed work interval'))
        session.commit()
    assert_blocked(api, copy['id'])


def test_edited_generated_plan_keeps_the_existing_linked_work_blocker(api):
    saved, copy = setup_copy(api)
    ok(edit_plan(api, copy['id'], saved['order']['project_id'], copy['assembly_id'], planned=2))
    assert_blocked(api, copy['id'])


def test_manual_material_change_blocks_copy_removal_without_losing_source_lot(api):
    _, copy = setup_copy(api, with_bom=True)
    module = importlib.import_module('spool_boms')
    with api.session_factory() as session:
        piece = session.scalar(select(module.SpoolBomMaterial).where(module.SpoolBomMaterial.spool_id == copy['id']))
        piece.heat_number = 'MANUALLY-CORRECTED-HEAT'
        session.commit()
    assert_blocked(api, copy['id'])


@pytest.mark.parametrize('scope', ['copy', 'parent', 'weld'])
def test_separate_quality_workspace_evidence_blocks_even_without_item_audit(api, scope):
    saved, copy = setup_copy(api)
    quality = importlib.import_module('quality')
    tracking = importlib.import_module('tracking')
    with api.session_factory() as session:
        workspace = quality.QualityWorkspace(name='Synthetic linked QA', customer='',
            project_id=saved['order']['project_id'], created_by=BADGES['admin'])
        session.add(workspace)
        session.flush()
        requirement = quality.QualityRequirement(workspace_id=workspace.id, item_number='1',
            title='Synthetic QA obligation', requirement_text='Retain the linked actual record',
            created_by=BADGES['admin'])
        session.add(requirement)
        session.flush()
        weld = session.scalar(select(tracking.Weld).where(tracking.Weld.item_id == copy['id']))
        session.add(quality.QualityEvidence(workspace_id=workspace.id, requirement_id=requirement.id,
            type='other', title='Linked retained evidence', reference='QA-EVIDENCE', occurred_on='2026-01-15',
            item_id=None if scope == 'weld' else copy['id'] if scope == 'copy' else copy['assembly_id'],
            weld_id=weld.id if scope == 'weld' else None, created_by=BADGES['inspector']))
        session.commit()
    assert_blocked(api, copy['id'])


def test_shared_project_packet_review_blocks_untouched_copy_exception(api):
    saved, copy = setup_copy(api)
    dossier = importlib.import_module('dossier')
    with api.session_factory() as session:
        session.add(dossier.DossierProject(project_id=saved['order']['project_id'],
            manufacturer_name='Synthetic', manufacturer_contact='Synthetic QA',
            purchase_order=saved['order']['purchase_order'], source_reference='SYNTHETIC-REFERENCE',
            expected_packets=1, created_by=BADGES['admin']))
        session.flush()
        session.add(dossier.DossierReview(project_id=saved['order']['project_id'], item_id=None,
            code='purchase_order', decision='accepted', reference='SYNTHETIC-REVIEW',
            notes='A saved project review must not be bypassed', fingerprint='f' * 64,
            snapshot={}, actor=BADGES['inspector']))
        session.commit()
    assert_blocked(api, copy['id'])
