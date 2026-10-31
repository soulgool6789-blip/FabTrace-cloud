"""Readable spool labels are durable aliases, never new traceability keys."""
import datetime as dt
import importlib
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import ok
from test_order_setup import branch, create_setup
from test_order_labels import generate, labels, public_qr_url
from test_progress import database_state
from test_removal_orders import change


NUMBER = '643-777-PCW-03-01'


def physical(api, item_id, number=NUMBER, kind='Spool'):
    return ok(api.post('/api/items', {'id': item_id, 'kind': kind,
        'google_part_number': number, 'location': 'Synthetic receiving',
        'handler': BADGES['handler']}), 201)


def registry():
    return importlib.import_module('order_spools')


def test_eighteen_spools_have_saved_numbered_labels_and_old_ids_still_open(api, monkeypatch):
    setup = create_setup(api, assemblies=[branch('643-777', 1, [
        {'spool_number': NUMBER, 'quantity_per_assembly': 18}])])
    project = setup['order']['project_id']
    generate(api, project)
    output = labels(api, project)['items']
    assert [row['qr_alias'] for row in output] == [f'{NUMBER}-[{n:03d}]' for n in range(1, 19)]
    assert all(row['display_code'] == row['qr_alias'] for row in output)
    assert len({row['id'] for row in output}) == len({row['qr_url'] for row in output}) == 18
    before = database_state(api)
    payloads = []
    original_qr = api.application.qrcode.make
    monkeypatch.setattr(api.application.qrcode, 'make', lambda value: (payloads.append(value), original_qr(value))[1])
    for row in output:
        assert row['id'].startswith('SPL-')
        assert parse_qs(urlparse(row['qr_url']).query) == {'spool': [row['qr_alias']]}
        detail = ok(api.get('/api/items/' + row['id']))
        assert detail['id'] == row['id'] and detail['display_code'] == row['qr_alias']
        resolved = ok(api.get('/api/spool-qr/resolve', params={'code': row['qr_alias']}))
        assert resolved['item_id'] == row['id'] and resolved['qr_alias'] == row['qr_alias']
        response = api.get('/api/items/' + row['id'] + '/qr.png')
        assert response.status_code == 200 and response.content.startswith(b'\x89PNG')
        assert payloads[-1] == row['qr_url']
    assert labels(api, project)['items'] == output
    assert generate(api, project)['created_count'] == 0
    assert database_state(api) == before
    assert api.get('/api/spool-qr/resolve', params={'code': output[0]['qr_alias']}, role=None).status_code == 401


def test_sequence_is_global_across_purchase_orders_and_never_recycles_removed_labels(api):
    first = create_setup(api, number='ALIAS-PO-1', assemblies=[branch('GPN-A', 1, [
        {'spool_number': NUMBER, 'quantity_per_assembly': 2}])])
    second = create_setup(api, number='ALIAS-PO-2', assemblies=[branch('GPN-B', 1, [
        {'spool_number': NUMBER.lower(), 'quantity_per_assembly': 1}])])
    one, two = first['order']['project_id'], second['order']['project_id']
    generate(api, one)
    original = labels(api, one)['items'][0]
    generate(api, two)
    assert labels(api, two)['items'][0]['qr_alias'] == NUMBER.lower() + '-[003]'
    change(api, 'item', original['id'])
    generate(api, one)
    remaining = labels(api, one)['items']
    assert [row['qr_alias'] for row in remaining] == [NUMBER + '-[002]', NUMBER + '-[004]']
    resolved = ok(api.get('/api/spool-qr/resolve', params={'code': original['qr_alias']}))
    assert resolved['item_id'] == original['id']
    assert ok(api.get('/api/items/' + original['id']))['removal']['removed']
    with api.session_factory() as s:
        assert [row.sequence for row in s.scalars(select(registry().SpoolQrIdentity)
            .order_by(registry().SpoolQrIdentity.sequence))] == [1, 2, 3, 4]


def test_all_future_create_bulk_and_legacy_plan_paths_allocate_once(api):
    first = physical(api, 'FUTURE-ONE')
    assert first['qr_alias'] == NUMBER + '-[001]'
    batch = ok(api.post('/api/items/bulk', {'rows': [{'kind': 'Spool',
        'google_part_number': NUMBER, 'location': 'Synthetic receiving',
        'handler': BADGES['handler'], 'quantity': 2}]}), 201)
    assert len(batch['items']) == 2
    assert [ok(api.get('/api/items/' + row['id']))['qr_alias'] for row in batch['items']] == [
        NUMBER + '-[002]', NUMBER + '-[003]']
    component = physical(api, 'LEGACY-PLANNED-PART', kind='Part')
    assert component['qr_alias'] is None
    ok(api.post('/api/tracking/projects', {'id': 'ALIAS-PROJECT', 'name': 'Synthetic project'}), 201)
    body = {'project_id': 'ALIAS-PROJECT', 'planned_welds': 1}
    ok(api.post('/api/tracking/spools/LEGACY-PLANNED-PART/plan', body))
    assert ok(api.get('/api/items/LEGACY-PLANNED-PART'))['qr_alias'] == NUMBER + '-[004]'
    ok(api.post('/api/tracking/spools/LEGACY-PLANNED-PART/plan', {**body, 'expected_version': 1}))
    with api.session_factory() as s:
        identities = s.scalars(select(registry().SpoolQrIdentity)).all()
        assert len(identities) == 4
        assert {row.source for row in identities} >= {'tracking_plan'}
    assembly = physical(api, 'ALIAS-ASSEMBLY', kind='Assembly')
    assert assembly['qr_alias'] is None and assembly['qr_url'] is None


def test_blank_legacy_number_keeps_old_url_until_number_is_entered_and_alias_number_is_pinned(api):
    blank = physical(api, 'NO-LEGACY-NUMBER', number='')
    assert blank['qr_alias'] is None and parse_qs(urlparse(blank['qr_url']).query) == {'item': [blank['id']]}
    filled = ok(api.patch('/api/items/' + blank['id'] + '/part-number', {'google_part_number': NUMBER}))
    assert filled['qr_alias'] == NUMBER + '-[001]'
    before = database_state(api)
    denied = api.patch('/api/items/' + blank['id'] + '/part-number', {'google_part_number': 'DIFFERENT-SPOOL'})
    assert denied.status_code == 409 and 'permanent QR' in denied.text
    assert database_state(api) == before
    recased = ok(api.patch('/api/items/' + blank['id'] + '/part-number', {'google_part_number': NUMBER.lower()}))
    assert recased['qr_alias'] == filled['qr_alias']


def test_backfill_is_deterministic_additive_idempotent_and_does_not_invent_numbers(api):
    tracking = importlib.import_module('tracking')
    ok(api.post('/api/tracking/projects', {'id': 'BACKFILL-PO', 'name': 'Synthetic legacy project'}), 201)
    at = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
    with api.session_factory() as s:
        rows = [
            ('LEGACY-Z', 'Spool', NUMBER, at + dt.timedelta(days=1)),
            ('LEGACY-B', 'Spool', NUMBER, at),
            ('LEGACY-A', 'Spool', NUMBER, at),
            ('LEGACY-TRACKED', 'Part', NUMBER, at + dt.timedelta(days=2)),
            ('LEGACY-BLANK', 'Spool', '', at),
            ('GENUINE-COMPONENT', 'Part', NUMBER, at),
            ('LEGACY-ASSEMBLY', 'Assembly', NUMBER, at),
        ]
        for item_id, kind, number, created in rows:
            s.add(api.application.Item(id=item_id, kind=kind, google_part_number=number,
                description='Retained description', project='BACKFILL-PO', location='Historical bay',
                handler=BADGES['handler'], created_at=created, updated_at=created))
        s.flush()
        s.add(tracking.SpoolPlan(item_id='LEGACY-TRACKED', project_id='BACKFILL-PO',
            planned_welds=1, created_by=BADGES['admin']))
        s.commit()
    change(api, 'item', 'LEGACY-B')
    with api.session_factory() as s:
        original_items = s.execute(select(api.application.Item.__table__)).all()
        result = registry().backfill_spool_qr_identities(s)
        assert result == {'created': 4, 'missing_spool_number': 1}
        s.commit()
        assert s.execute(select(api.application.Item.__table__)).all() == original_items
        assert {row.item_id: row.display_code for row in s.scalars(select(registry().SpoolQrIdentity))} == {
            'LEGACY-A': NUMBER + '-[001]', 'LEGACY-B': NUMBER + '-[002]',
            'LEGACY-Z': NUMBER + '-[003]', 'LEGACY-TRACKED': NUMBER + '-[004]'}
        events = s.scalars(select(api.application.Audit).where(
            api.application.Audit.event == 'SPOOL_QR_IDENTITY_ASSIGNED')).all()
        assert len(events) == 4 and all(row.actor == 'system:spool-qr-backfill' for row in events)
    before = database_state(api)
    with api.session_factory() as s:
        assert registry().backfill_spool_qr_identities(s) == {'created': 0, 'missing_spool_number': 1}
        s.commit()
    assert database_state(api) == before


def test_full_alias_lookup_escapes_url_and_does_not_guess_from_a_spool_number(api):
    number = '000-Spool / A&B #é [rev]'
    item = physical(api, 'ESCAPED-ALIAS', number=number)
    assert item['qr_alias'] == number + '-[001]'
    assert parse_qs(urlparse(item['qr_url']).query) == {'spool': [item['qr_alias']]}
    resolved = ok(api.get('/api/spool-qr/resolve', params={'code': item['qr_alias'].upper()}))
    assert resolved['item_id'] == item['id']
    for value in (number, number + '-[002]', 'ESCAPED-ALIAS', number + '-[001] / unrelated'):
        assert api.get('/api/spool-qr/resolve', params={'code': value}).status_code == 404


def test_alias_backfill_preserves_accepted_receipt_material_and_source_basis(api):
    from receiving_helpers import accept_arrival, receiving_detail
    # This is a legacy physical record predating readable labels.
    with api.session_factory() as s:
        s.add(api.application.Item(id='LEGACY-ACCEPTED', kind='Spool', google_part_number=NUMBER,
            description='Retained accepted spool', location='Synthetic receiving', handler=BADGES['handler']))
        s.commit()
    accept_arrival(api, 'LEGACY-ACCEPTED')
    before = receiving_detail(api, 'LEGACY-ACCEPTED')
    assert before['arrival']['can_proceed'] and before['context']['qr_alias'] is None
    with api.session_factory() as s:
        assert registry().backfill_spool_qr_identities(s)['created'] == 1
        s.commit()
    after = receiving_detail(api, 'LEGACY-ACCEPTED')
    assert after['context']['qr_alias'] == NUMBER + '-[001]'
    assert after['arrival']['basis_sha256'] == before['arrival']['basis_sha256']
    assert after['arrival']['latest'] == before['arrival']['latest']
    assert after['arrival']['history'] == before['arrival']['history']
    assert after['arrival']['can_proceed']
    assert after['traceability'] == before['traceability']
    assert after['source_status'] == before['source_status']


def test_failed_generation_rolls_back_allocated_aliases_and_audit(api, monkeypatch):
    setup = create_setup(api, assemblies=[branch('ROLLBACK-GPN', 1, [
        {'spool_number': NUMBER, 'quantity_per_assembly': 2}])])
    project = setup['order']['project_id']
    module = importlib.import_module('order_labels')
    before = database_state(api)
    with monkeypatch.context() as patch:
        def fail_event(*args, **kwargs):
            raise HTTPException(409, 'Synthetic failure after alias allocation')
        patch.setattr(module, '_event', fail_event)
        response = api.post('/api/order-labels/' + project + '/generate', {
            'expected_version': 1, 'location': 'Synthetic receiving', 'handler': BADGES['handler']})
        assert response.status_code == 409
    assert database_state(api) == before
    generate(api, project)
    assert [row['qr_alias'] for row in labels(api, project)['items']] == [NUMBER + '-[001]', NUMBER + '-[002]']


def test_sequences_expand_past_three_digits_without_renaming_prior_aliases(api):
    # Seed a legitimate retained high sequence without creating 999 work records.
    with api.session_factory() as s:
        item = api.application.Item(id='RETAINED-999', kind='Spool', google_part_number=NUMBER,
            description='', location='Legacy bay', handler=BADGES['handler'])
        s.add(item)
        s.flush()
        s.add(registry().SpoolQrIdentity(item_id=item.id, spool_number=NUMBER,
            normalized_number=NUMBER.casefold(), sequence=999, display_code=NUMBER+'-[999]',
            normalized_code=NUMBER.casefold()+'-[999]', created_by='system:legacy', source='retained_fixture'))
        s.commit()
    next_item = physical(api, 'NEXT-AFTER-999')
    assert next_item['qr_alias'] == NUMBER + '-[1000]'
    assert ok(api.get('/api/items/RETAINED-999'))['qr_alias'] == NUMBER + '-[999]'
