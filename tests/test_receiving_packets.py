"""Arrival decisions and exact MTR versions remain bound to issued packets."""
import hashlib
import io
import json
import zipfile

from tracking_helpers import ok
from receiving_helpers import accept_arrival, receiving_detail, record_arrival
from test_dossier import (make_project, physical_release, complete_packet, issue_item,
                          packet, signed, sign_source, document, entry, review)
from test_spool_receiving import upload_mtr, pdf


def test_issued_packet_retains_exact_arrival_decision_and_mtr_bytes_after_later_revision(api):
    item_id = make_project(api, 'ARRIVAL-PACKET')
    first = ok(upload_mtr(api, item_id, pdf(2)), 201)['mtr_documents']['current'][0]
    original = api.get(first['view_url']).content
    accepted = accept_arrival(api, item_id)['arrival']['latest']
    physical_release(api, item_id)
    current = complete_packet(api, item_id)
    assert current['status'] == 'ready_for_issue', current['blockers']
    signed(issue_item(api, item_id))
    issued = packet(api, item_id)['latest_issue']
    route = '/api/dossier/issues/' + str(issued['id'])
    historical = ok(api.get(route))
    downloaded = api.get(route + '/download')
    assert downloaded.status_code == 200, downloaded.text
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        saved = json.loads(archive.read('snapshot.json'))
        metadata = saved['mtr_documents'][0]
        assert metadata['document_id'] == first['id']
        assert metadata['spool_id'] == item_id
        assert saved['packet']['records']['arrival_qa'][0]['inspection'] == accepted
        assert saved['packet']['records']['arrival_qa'][0]['current_pass'] is True
        path = 'mtr-files/' + metadata['document_id'] + '_' + metadata['filename']
        assert archive.read(path) == original
        assert metadata['sha256'] == hashlib.sha256(original).hexdigest()
        assert path.encode() in archive.read('job-packet.html')
        assert json.loads(archive.read('manifest.json'))['mtr_documents'][0]['document_id'] == first['id']
    ok(api.post('/api/items/' + item_id + '/reopen'))
    newer = ok(upload_mtr(api, item_id, pdf(3), version=1), 201)['mtr_documents']['current'][0]
    assert newer['id'] != first['id']
    assert receiving_detail(api, item_id)['arrival']['status'] == 'needs_reinspection'
    assert packet(api, item_id)['latest_issue']['current'] is False
    assert ok(api.get(route)) == historical
    retained = api.get(route + '/download')
    assert retained.status_code == 200, retained.text
    with zipfile.ZipFile(io.BytesIO(retained.content)) as archive:
        assert archive.read(path) == original
        assert newer['id'] not in archive.read('snapshot.json').decode()


def test_new_arrival_fail_changes_current_packet_basis_without_rewriting_prior_signed_review(api):
    item_id = make_project(api, 'ARRIVAL-PACKET-FAIL')
    accept_arrival(api, item_id)
    signed(sign_source(api))
    supporting = document(api, item_id=item_id, code='SYNTHETIC-MATERIALS', section='02')
    signed(entry(api, item_id, 'materials', document_ids=[supporting['id']]))
    signed(review(api, item_id, 'materials'))
    prepared = packet(api, item_id)
    before = {row['code']: row for section in prepared['sections'] for row in section['checks']}
    material_review = before['materials']['latest_review']
    ok(record_arrival(api, item_id, result='Fail'), 201)
    current = packet(api, item_id)
    after = {row['code']: row for section in current['sections'] for row in section['checks']}
    assert after['materials']['latest_review'] == material_review
    assert after['materials']['status'] == 'stale'
    assert after['materials']['fingerprint'] != before['materials']['fingerprint']
    assert any('arrival' in value.lower() for value in current['blockers'])
    assert current['records']['arrival_qa'][0]['inspection']['result'] == 'Fail'
