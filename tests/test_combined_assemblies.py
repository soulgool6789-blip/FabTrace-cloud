"""One-step GPN/assembly registration uses real identities and atomic scope."""

import importlib

import pytest
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import ok
from test_admin import release as admin_release
from test_flow import create_item, detail as flow_detail, enroll
from test_orders import ROOT, add_assembly, current, group, new_order, plan, reject, version
from test_progress import database_state


def create_body(api, project_id, **values):
    return {'expected_version': version(api, project_id), 'gpn': '00001234',
            'assembly_number': '000-TEST-ASSEMBLY',
            'required_spools': 2, 'notes': 'Approved synthetic assembly requirement',
            'create_item': {'location': 'Receiving', 'handler': BADGES['handler'],
                            'drawing': 'TEST-ISO-REV-A'}, **values}


def combined(api, project_id, **values):
    return ok(api.post(f'{ROOT}/{project_id}/gpn-assemblies', create_body(api, project_id, **values)), 201)


def edit_body(api, project_id, **values):
    return {'expected_version': version(api, project_id), 'gpn': '00001234',
            'required_spools': 2, 'notes': 'Reviewed synthetic scope',
            'reason': 'Confirmed current assembly identity and approved scope', **values}


def test_combined_creation_is_one_atomic_revision_with_generated_physical_id(api):
    project_id = new_order(api)['order']['project_id']
    detail = combined(api, project_id)
    item_id = detail['selected_assembly_id']
    assert item_id.startswith('ASM-') and len(item_id) <= 60
    assert detail['order']['version'] == 2
    assert len(detail['gpns']) == len(detail['assemblies']) == 1
    gpn, assembly = detail['gpns'][0], detail['assemblies'][0]
    assert gpn['id'] == assembly['gpn_id'] == detail['selected_gpn_id']
    assert gpn['gpn'] == assembly['assembly_part_number'] == assembly['google_part_number'] == '00001234'
    assert assembly['item_id'] == item_id and assembly['description'] == ''
    assert assembly['number_editable'] and assembly['combined_number_matches'] and assembly['planning_needed']
    assert detail['totals']['combined_count'] == 1 and detail['totals']['setup_needed_count'] == 0
    assert detail['totals']['required_spools'] == detail['totals']['missing_spools'] == 2
    assert detail['totals']['ready_spools'] == detail['totals']['linked_spools'] == 0
    item = ok(api.get('/api/items/' + item_id))
    assert item['kind'] == 'Assembly' and not item['released'] and item['description'] == ''
    assert item['handler'] == BADGES['handler'] and item['drawing'] == 'TEST-ISO-REV-A'
    assert ok(api.get('/api/tracking/spools/' + item_id))['plan'] is None
    assert flow_detail(api, item_id)['flow'] is None
    assert {event['event'] for event in detail['events']} == {'ORDER_CREATED', 'ORDER_GPN_ASSEMBLY_CREATED'}
    event = detail['events'][0]
    assert event['details']['after']['physical_item_created'] is True


def test_custom_qr_id_and_supervisor_creation_are_supported(api):
    project_id = new_order(api)['order']['project_id']
    body = create_body(api, project_id)
    body['create_item']['id'] = 'CUSTOM-ASM-001'
    detail = ok(api.post(f'{ROOT}/{project_id}/gpn-assemblies', body, role='supervisor'), 201)
    assert detail['selected_assembly_id'] == 'CUSTOM-ASM-001'


@pytest.mark.parametrize('explicit_group', [False, True])
def test_finish_existing_empty_gpn_retains_its_identity_and_description(api, explicit_group):
    project_id = new_order(api)['order']['project_id']
    gpn_id = group(api, project_id, number='DRAFT-GPN')
    detail = current(api, project_id)
    before_group = detail['gpns'][0]
    assert detail['totals']['combined_count'] == detail['totals']['setup_needed_count'] == 1
    register = ok(api.get(ROOT))['orders'][0]
    assert register['combined_count'] == register['setup_needed_count'] == 1
    payload = {'gpn': ' draft-gpn ', 'assembly_number': before_group['assembly_number']}
    if explicit_group:
        payload['gpn_id'] = gpn_id
    detail = combined(api, project_id, **payload)
    assert detail['selected_gpn_id'] == gpn_id
    assert len(detail['gpns']) == 1 and detail['gpns'][0]['gpn'] == 'DRAFT-GPN'
    for key in ('id', 'description', 'created_by', 'created_at', 'updated_at'):
        assert detail['gpns'][0][key] == before_group[key]
    assert detail['assemblies'][0]['assembly_part_number'] == 'DRAFT-GPN'
    assert detail['totals']['combined_count'] == 1 and detail['totals']['setup_needed_count'] == 0


def test_duplicate_number_or_stale_form_creates_no_second_physical_record(api):
    project_id = new_order(api)['order']['project_id']
    body = create_body(api, project_id)
    detail = ok(api.post(f'{ROOT}/{project_id}/gpn-assemblies', body), 201)
    before = database_state(api)
    reject(api, api.post(f'{ROOT}/{project_id}/gpn-assemblies', body), before, (409,))
    body.update(expected_version=detail['order']['version'], gpn='  00001234  ')
    reject(api, api.post(f'{ROOT}/{project_id}/gpn-assemblies', body), before, (409,))
    assert len(current(api, project_id)['assemblies']) == 1


@pytest.mark.parametrize('problem', ['missing_handler', 'inactive_handler', 'existing_item_id'])
def test_failed_new_registration_rolls_back_new_gpn_item_and_audit(api, problem):
    project_id = new_order(api)['order']['project_id']
    body = create_body(api, project_id)
    if problem == 'missing_handler':
        body['create_item']['handler'] = 'NO-SUCH-HANDLER'
    elif problem == 'inactive_handler':
        with api.session_factory() as session:
            session.get(api.application.Employee, BADGES['handler']).active = False
            session.commit()
    else:
        api.item('EXISTING-ID')
        body['create_item']['id'] = 'EXISTING-ID'
    before = database_state(api)
    reject(api, api.post(f'{ROOT}/{project_id}/gpn-assemblies', body), before)
    assert current(api, project_id)['gpns'] == []


@pytest.mark.parametrize('mode', ['neither', 'both', 'invalid_count', 'foreign_group', 'mismatched_group'])
def test_combined_creation_rejects_ambiguous_or_foreign_scope(api, mode):
    project_id = new_order(api)['order']['project_id']
    body = create_body(api, project_id)
    if mode == 'neither':
        del body['create_item']
    elif mode == 'both':
        body['item_id'] = 'SOME-EXISTING-ASSEMBLY'
    elif mode == 'invalid_count':
        body['required_spools'] = True
    elif mode == 'foreign_group':
        other = new_order(api, number='PO-FOREIGN')['order']['project_id']
        body['gpn_id'] = group(api, other)
    else:
        body['gpn_id'] = group(api, project_id, number='DIFFERENT-GPN')
        body['expected_version'] = version(api, project_id)
    before = database_state(api)
    reject(api, api.post(f'{ROOT}/{project_id}/gpn-assemblies', body), before)


@pytest.mark.parametrize('role,code', [('welder', 403), ('inspector', 403), (None, 401)])
def test_new_create_and_edit_require_management_authority(api, role, code):
    project_id = new_order(api)['order']['project_id']
    body = create_body(api, project_id)
    before = database_state(api)
    reject(api, api.post(f'{ROOT}/{project_id}/gpn-assemblies', body, role=role), before, (code,))
    created = combined(api, project_id)
    item_id = created['selected_assembly_id']
    before = database_state(api)
    reject(api, api.patch(f'{ROOT}/{project_id}/gpn-assemblies/{item_id}',
                         edit_body(api, project_id, gpn='UNAUTHORIZED'), role=role), before, (code,))


def test_existing_physical_assembly_attachment_preserves_item_and_history(api):
    project_id = new_order(api)['order']['project_id']
    create_item(api, 'LEGACY-PHYSICAL-ASM', kind='Assembly', project=project_id)
    ok(api.patch('/api/items/LEGACY-PHYSICAL-ASM/part-number', {'google_part_number': 'LEGACY-PHYSICAL-NUMBER'}))
    with api.session_factory() as session:
        item = session.get(api.application.Item, 'LEGACY-PHYSICAL-ASM')
        prior_item = {column.name: getattr(item, column.name) for column in item.__table__.columns}
        prior_audits = [(a.id, a.details) for a in session.scalars(select(api.application.Audit).order_by(api.application.Audit.id))]
    detail = combined(api, project_id, item_id='LEGACY-PHYSICAL-ASM', create_item=None)
    assert detail['selected_assembly_id'] == 'LEGACY-PHYSICAL-ASM'
    assert detail['assemblies'][0]['google_part_number'] == 'LEGACY-PHYSICAL-NUMBER'
    with api.session_factory() as session:
        item = session.get(api.application.Item, 'LEGACY-PHYSICAL-ASM')
        assert {column.name: getattr(item, column.name) for column in item.__table__.columns} == prior_item
        for audit_id, details in prior_audits:
            assert session.get(api.application.Audit, audit_id).details == details
    assert detail['events'][0]['details']['after']['physical_item_created'] is False


def test_controlled_renumber_updates_combined_identity_and_part_number_together(api):
    project_id = new_order(api)['order']['project_id']
    created = combined(api, project_id)
    item_id, gpn_id = created['selected_assembly_id'], created['selected_gpn_id']
    changed = ok(api.patch(f'{ROOT}/{project_id}/gpn-assemblies/{item_id}',
                           edit_body(api, project_id, gpn='00005678', required_spools=3)))
    row = changed['assemblies'][0]
    assert row['item_id'] == item_id and row['gpn_id'] == gpn_id
    assert row['gpn'] == row['assembly_part_number'] == row['google_part_number'] == '00005678'
    assert row['required_spools'] == 3 and row['combined_number_matches']
    event = changed['events'][0]
    assert event['event'] == 'ORDER_GPN_ASSEMBLY_UPDATED'
    assert event['details']['before']['physical_part_number'] == '00001234'
    assert event['details']['after']['physical_part_number'] == '00005678'
    assert event['details']['reason'] == edit_body(api, project_id)['reason']
    before = database_state(api)
    stale = edit_body(api, project_id, gpn='STALE')
    stale['expected_version'] = created['order']['version']
    reject(api, api.patch(f'{ROOT}/{project_id}/gpn-assemblies/{item_id}', stale), before, (409,))


def test_legacy_differing_part_number_and_gpn_description_are_not_silently_rewritten(api):
    project_id = new_order(api)['order']['project_id']
    gpn_id = group(api, project_id, number='00001234')
    original = add_assembly(api, project_id, gpn_id)
    row = original['assemblies'][0]
    assert not row['combined_number_matches'] and row['number_editable']
    changed = ok(api.patch(f'{ROOT}/{project_id}/gpn-assemblies/{row["item_id"]}', edit_body(api, project_id, required_spools=3)))
    assert changed['assemblies'][0]['assembly_part_number'] == 'ASM-DESIGN-01'
    assert changed['assemblies'][0]['google_part_number'] == 'PHYSICAL-PART-GPN'
    assert changed['gpns'][0]['description'] == original['gpns'][0]['description']
    changed = ok(api.patch(f'{ROOT}/{project_id}/gpn-assemblies/{row["item_id"]}',
                           edit_body(api, project_id, gpn='CONFIRMED-GPN', required_spools=3)))
    assert changed['assemblies'][0]['assembly_part_number'] == 'CONFIRMED-GPN'
    assert changed['assemblies'][0]['google_part_number'] == 'PHYSICAL-PART-GPN'
    assert changed['gpns'][0]['description'] == original['gpns'][0]['description']


def test_existing_multi_assembly_group_is_visible_but_cannot_be_renumbered_from_one_item(api):
    project_id = new_order(api)['order']['project_id']
    gpn_id = group(api, project_id, number='00001234')
    add_assembly(api, project_id, gpn_id, item_id='MULTI-ASM-01')
    add_assembly(api, project_id, gpn_id, item_id='MULTI-ASM-02')
    group(api, project_id, number='EMPTY-GPN')
    detail = current(api, project_id)
    assert detail['totals']['combined_count'] == 3 and detail['totals']['setup_needed_count'] == 1
    assert not any(a['number_editable'] for a in detail['assemblies'])
    register = ok(api.get(ROOT))['orders'][0]
    assert register['combined_count'] == 3 and register['setup_needed_count'] == 1
    before = database_state(api)
    reject(api, api.patch(f'{ROOT}/{project_id}/gpn-assemblies/MULTI-ASM-01',
                         edit_body(api, project_id, gpn='BAD-RENUMBER')), before, (409,))


@pytest.mark.parametrize('control', ['traveler', 'released', 'linked_count', 'duplicate_assembly_number'])
def test_combined_edits_preserve_scope_release_and_number_boundaries(api, control):
    project_id = new_order(api)['order']['project_id']
    created = combined(api, project_id)
    item_id = created['selected_assembly_id']
    body = edit_body(api, project_id, gpn='UPDATED-GPN', required_spools=3)
    if control == 'traveler':
        ok(plan(api, item_id, project_id))
        enroll(api, item_id, 'assembly', expected_children=2)
    elif control == 'released':
        admin_release(api, item_id)
    elif control == 'linked_count':
        ok(plan(api, item_id, project_id))
        for child in ('LINKED-SPOOL-01', 'LINKED-SPOOL-02'):
            create_item(api, child, kind='Spool', project=project_id)
            ok(plan(api, child, project_id, item_id))
        body['required_spools'] = 1
    else:
        group(api, project_id, number='UPDATED-GPN')
        body['expected_version'] = version(api, project_id)
        body['assembly_number'] = 'ASM-UPDATED-GPN'
    before = database_state(api)
    reject(api, api.patch(f'{ROOT}/{project_id}/gpn-assemblies/{item_id}', body), before, (409,))
    if control in ('traveler', 'released'):
        assert not current(api, project_id)['assemblies'][0]['number_editable']
        # Notes are still correctable without redefining established physical scope.
        changed = ok(api.patch(f'{ROOT}/{project_id}/gpn-assemblies/{item_id}', edit_body(api, project_id)))
        assert changed['assemblies'][0]['gpn'] == '00001234'


