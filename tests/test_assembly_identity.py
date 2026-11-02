"""Independent assembly metadata preserves physical and inspection identities."""
import json

import pytest
from sqlalchemy import select

from conftest import BADGES
from receiving_helpers import accept_arrival, receiving_detail
from test_order_labels import generate, labels, public_qr_url
from test_order_setup import ROOT, branch, create_setup, detail, edit_body
from test_orders import current
from test_progress import database_state
from test_removal_orders import change
from tracking_helpers import ok


def named_branch(number, gpn='000-GPN-A', quantity=1):
    return {**branch(gpn, quantity, [{'spool_number': '000-SPOOL-01',
        'quantity_per_assembly': 1, 'welds_per_spool': 0}]), 'assembly_number': number}


def identity_path(saved, index=0):
    return f'{ROOT}/{saved["order"]["project_id"]}/assemblies/{saved["assemblies"][index]["gpn_id"]}/identity'


def identity_body(saved, number):
    return {'expected_version': saved['order']['version'], 'assembly_number': number,
            'reason': 'Record the separately verified assembly number'}


def test_setup_keeps_unknown_assembly_number_and_supports_repeated_gpn_for_named_assemblies(api):
    saved = create_setup(api, assemblies=[branch('0000456', 1)])
    legacy = saved['assemblies'][0]
    assert legacy['gpn'] == '0000456' and legacy['assembly_number'] == ''
    assert saved['saved_gpn_ids'] == [legacy['gpn_id']]
    project = saved['order']['project_id']
    for number in ('000-ASM-A', '000-ASM-B'):
        saved = ok(api.post(f'{ROOT}/{project}/assemblies', {
            **named_branch(number, '0000456'), 'expected_version': saved['order']['version']}), 201)
        selected = next(row for row in saved['assemblies'] if row['assembly_number'] == number)
        assert saved['saved_gpn_ids'] == [selected['gpn_id']]
    assert {row['assembly_number'] for row in saved['assemblies']} == {'', '000-ASM-A', '000-ASM-B'}
    assert len({row['gpn_id'] for row in saved['assemblies']}) == 3
    assert all(row['gpn'] == '0000456' for row in saved['assemblies'])
    from orders import OrderGpn
    with api.session_factory() as session:
        rows = list(session.scalars(select(OrderGpn)))
        assert {row.normalized_assembly_number for row in rows} == {None, '000-asm-a', '000-asm-b'}
        assert all(row.normalized_gpn == '0000456' for row in rows)
        assert session.execute(select(api.application.Item)).all() == []


def test_number_uniqueness_is_per_order_and_removed_entries_keep_their_identity(api):
    saved = create_setup(api, assemblies=[named_branch(' AS  001 ', 'GPN-A'), named_branch('', 'GPN-B')])
    project = saved['order']['project_id']
    before = database_state(api)
    for values in (named_branch('as 001', 'DIFFERENT-GPN'), named_branch('', ' gpn-b ')):
        response = api.post(f'{ROOT}/{project}/assemblies', {**values, 'expected_version': saved['order']['version']})
        assert response.status_code == 409 and database_state(api) == before
    response = api.post(ROOT, {'purchase_order': 'DUPLICATE-NAMED',
        'assemblies': [named_branch('A', 'FIRST'), named_branch(' a ', 'SECOND')]})
    assert response.status_code == 422 and database_state(api) == before
    other = create_setup(api, number='OTHER-PO', assemblies=[named_branch('AS 001', 'GPN-A')])
    assert other['assemblies'][0]['assembly_number'] == 'AS 001'
    removed = next(row for row in saved['assemblies'] if row['assembly_number'])
    change(api, 'gpn', removed['gpn_id'])
    saved = detail(api, project)
    before = database_state(api)
    response = api.post(f'{ROOT}/{project}/assemblies', {
        **named_branch('AS 001', 'THIRD-GPN'), 'expected_version': saved['order']['version']})
    assert response.status_code == 409 and 'Removed records' in response.text
    assert database_state(api) == before


def test_assembly_metadata_can_be_corrected_after_real_qa_without_changing_any_production_evidence(api):
    saved = create_setup(api, assemblies=[named_branch('')])
    project = saved['order']['project_id']
    generate(api, project)
    spool = labels(api, project)['items'][0]
    accepted = accept_arrival(api, spool['id'])
    saved = detail(api, project)
    assert not saved['assemblies'][0]['editable'] and saved['assemblies'][0]['assembly_number_editable']
    before = json.loads(database_state(api))
    changed = ok(api.patch(identity_path(saved), identity_body(saved, 'VERIFIED-ASSEMBLY-001'), role='supervisor'))
    assert changed['saved_gpn_ids'] == [saved['assemblies'][0]['gpn_id']]
    assert changed['order']['version'] == saved['order']['version'] + 1
    assert changed['assemblies'][0]['gpn'] == saved['assemblies'][0]['gpn']
    assert changed['assemblies'][0]['assembly_number'] == 'VERIFIED-ASSEMBLY-001'
    after = json.loads(database_state(api))
    for table in set(before) - {'order_gpns', 'purchase_orders', 'audit_events'}:
        assert after[table] == before[table], table
    assert len(after['audit_events']) == len(before['audit_events']) + 1
    audit = after['audit_events'][-1]
    assert audit['event'] == 'ORDER_SETUP_ASSEMBLY_IDENTITY_UPDATED'
    assert audit['details']['before']['assembly_number'] == ''
    assert audit['details']['after']['assembly_number'] == 'VERIFIED-ASSEMBLY-001'
    receipt = receiving_detail(api, spool['id'])
    assert receipt['arrival']['can_proceed']
    assert receipt['arrival']['latest'] == accepted['arrival']['latest']
    assert receipt['arrival']['basis_sha256'] == accepted['arrival']['basis_sha256']
    assert [row['qa001']['latest'] for row in receipt['traceability']['materials']] == [
        row['qa001']['latest'] for row in accepted['traceability']['materials']]
    physical = current(api, project)
    assert physical['gpns'][0]['assembly_number'] == physical['assemblies'][0]['assembly_number'] == 'VERIFIED-ASSEMBLY-001'
    assert physical['assemblies'][0]['assembly_part_number'] == saved['assemblies'][0]['gpn']
    assert labels(api, project)['items'][0]['id'] == spool['id']
    before_rejection = database_state(api)
    response = api.patch(f'{ROOT}/{project}/assemblies/{saved["assemblies"][0]["gpn_id"]}',
        edit_body(changed, gpn='UNAPPROVED-GPN-CHANGE'))
    assert response.status_code == 409 and database_state(api) == before_rejection


@pytest.mark.parametrize('role', [None, 'handler', 'inspector'])
def test_assembly_number_edit_requires_existing_management_permission(api, role):
    saved = create_setup(api)
    before = database_state(api)
    response = api.patch(identity_path(saved), identity_body(saved, 'ASM-A'), role=role)
    assert response.status_code == (401 if role is None else 403)
    assert database_state(api) == before


def test_identity_edits_reject_stale_foreign_duplicate_and_invalid_requests_without_writes(api):
    saved = create_setup(api, assemblies=[named_branch('A'), named_branch('B', 'SECOND')])
    other = create_setup(api, number='FOREIGN', assemblies=[named_branch('C')])
    updated = ok(api.patch(identity_path(saved), identity_body(saved, 'A-CORRECTED')))
    before = database_state(api)
    assert api.patch(identity_path(saved), identity_body(saved, 'STALE')).status_code == 409
    assert api.patch(identity_path(updated), identity_body(updated, 'B')).status_code == 409
    foreign = f'{ROOT}/{updated["order"]["project_id"]}/assemblies/{other["assemblies"][0]["gpn_id"]}/identity'
    assert api.patch(foreign, identity_body(updated, 'FOREIGN')).status_code == 422
    for body in ({**identity_body(updated, 'A'), 'gpn': 'NOT-ALLOWED'},
                 {**identity_body(updated, 'A'), 'reason': ''}, identity_body(updated, 'X' * 161),
                 identity_body(updated, 'NULL\x00NUMBER')):
        assert api.patch(identity_path(updated), body).status_code == 422
    assert database_state(api) == before


def test_omitted_assembly_number_preserves_metadata_and_full_edit_keeps_fields_independent(api):
    saved = create_setup(api, assemblies=[named_branch('KNOWN-ASSEMBLY')])
    path = f'{ROOT}/{saved["order"]["project_id"]}/assemblies/{saved["assemblies"][0]["gpn_id"]}'
    changed = ok(api.patch(path, edit_body(saved, gpn='SEPARATELY-CORRECTED-GPN')))
    assert changed['assemblies'][0]['assembly_number'] == 'KNOWN-ASSEMBLY'
    assert changed['assemblies'][0]['gpn'] == 'SEPARATELY-CORRECTED-GPN'
    assert changed['saved_gpn_ids'] == saved['saved_gpn_ids']
    cleared = ok(api.patch(identity_path(changed), identity_body(changed, '')))
    assert cleared['assemblies'][0]['assembly_number'] == ''
    assert cleared['assemblies'][0]['gpn'] == 'SEPARATELY-CORRECTED-GPN'


def test_combined_registration_resolves_repeated_gpn_by_exact_group_and_edits_only_metadata(api):
    saved = create_setup(api, assemblies=[named_branch('ASSEMBLY-A'), named_branch('ASSEMBLY-B')])
    project = saved['order']['project_id']
    body = {'expected_version': saved['order']['version'], 'gpn': '000-GPN-A', 'required_spools': 1,
            'create_item': {'id': 'INDEPENDENT-ASSEMBLY-01', 'location': 'Receiving', 'handler': BADGES['handler']}}
    before = database_state(api)
    ambiguous = api.post(f'/api/orders/{project}/gpn-assemblies', body)
    assert ambiguous.status_code == 409 and 'more than one assembly setup' in ambiguous.text
    assert database_state(api) == before
    selected = saved['assemblies'][0]
    physical = ok(api.post(f'/api/orders/{project}/gpn-assemblies', {
        **body, 'gpn_id': selected['gpn_id'], 'assembly_number': selected['assembly_number']}), 201)
    record = physical['assemblies'][0]
    assert record['assembly_number'] == selected['assembly_number'] and record['assembly_number_editable']
    edit = {'expected_version': physical['order']['version'], 'gpn': selected['gpn'],
        'assembly_number': 'ASSEMBLY-CORRECTED', 'required_spools': 1,
        'reason': 'Correct independent assembly metadata after registration'}
    changed = ok(api.patch(f'/api/orders/{project}/gpn-assemblies/{record["item_id"]}', edit))
    assert changed['assemblies'][0]['assembly_number'] == 'ASSEMBLY-CORRECTED'
    assert changed['assemblies'][0]['assembly_part_number'] == record['assembly_part_number']
    assert changed['assemblies'][0]['google_part_number'] == record['google_part_number']
    del edit['assembly_number']
    edit['expected_version'] = changed['order']['version']
    again = ok(api.patch(f'/api/orders/{project}/gpn-assemblies/{record["item_id"]}', edit))
    assert again['assemblies'][0]['assembly_number'] == 'ASSEMBLY-CORRECTED'

