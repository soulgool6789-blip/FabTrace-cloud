"""Bounded upload intake, before multipart parsing; synthetic requests only."""
import asyncio
import io
import json

import pytest

import upload_limits
from test_spool_documents import setup, requirement_path, bom_csv, request_upload


PATH = '/api/spool-documents/requirements/OSPOOL-TEST/upload'


def run_request(monkeypatch, chunks, *, path=PATH, method='POST', headers=(), limit=1024,
                fail_app=False, disconnect=False):
    monkeypatch.setattr(upload_limits, 'MAX_REQUEST_BYTES', limit)
    monkeypatch.setattr(upload_limits, 'MEMORY_SPOOL_BYTES', 64)
    real_spool = upload_limits.tempfile.SpooledTemporaryFile
    created, writes, messages, received, entered = [], [], [], [], []

    def spool(*args, **kwargs):
        file = real_spool(*args, **kwargs)
        write = file.write

        def record(value):
            writes.append(len(value))
            return write(value)

        file.write = record
        created.append(file)
        return file

    monkeypatch.setattr(upload_limits.tempfile, 'SpooledTemporaryFile', spool)
    pending = [{'type': 'http.request', 'body': chunk,
                'more_body': index < len(chunks) - 1 or disconnect}
               for index, chunk in enumerate(chunks)]
    if disconnect:
        pending.append({'type': 'http.disconnect'})

    async def receive():
        assert pending, 'The middleware read beyond the completed request.'
        received.append(True)
        return pending.pop(0)

    async def send(message):
        messages.append(message)

    async def app(scope, receive, send):
        entered.append(True)
        if fail_app:
            raise RuntimeError('Synthetic downstream failure')
        body = bytearray()
        while True:
            message = await receive()
            body.extend(message.get('body', b''))
            if not message.get('more_body', False):
                break
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': bytes(body)})

    scope = {'type': 'http', 'method': method, 'path': path, 'headers': list(headers),
             'http_version': '1.1'}
    error = None
    try:
        asyncio.run(upload_limits.SpoolDocumentUploadLimit(app)(scope, receive, send))
    except RuntimeError as exc:
        error = exc
    return {'messages': messages, 'reads': len(received), 'entered': bool(entered),
            'files': created, 'written': sum(writes), 'error': error}


def assert_rejected(result):
    assert not result['entered'], 'Oversized body must not reach multipart parsing.'
    assert result['messages'][0]['status'] == 413
    assert json.loads(result['messages'][1]['body'])['detail'].startswith('Spool document upload is too large')
    assert all(file.closed for file in result['files'])


def test_declared_oversize_rejects_before_read_or_temporary_file(monkeypatch):
    result = run_request(monkeypatch, [b'not consumed'], headers=[(b'content-length', b'1025')])
    assert_rejected(result)
    assert result['reads'] == 0 and result['files'] == []


@pytest.mark.parametrize('headers', [[], [(b'transfer-encoding', b'chunked')], [(b'content-length', b'5')]])
def test_stream_limit_covers_missing_chunked_and_misleading_lengths(monkeypatch, headers):
    result = run_request(monkeypatch, [b'a' * 700, b'b' * 700, b'never consumed'], headers=headers)
    assert_rejected(result)
    assert result['reads'] == 2
    assert result['written'] == 700
    assert result['files'][0]._rolled, 'Accepted partial data must use the bounded disk spool.'


def test_accepted_body_is_replayed_exactly_and_spool_is_closed(monkeypatch):
    chunks = [b'a' * 200, b'b' * 300, b'c' * 524]
    result = run_request(monkeypatch, chunks, headers=[(b'content-length', b'1024')])
    assert result['entered'] and result['error'] is None
    assert result['messages'][0]['status'] == 200
    assert result['messages'][1]['body'] == b''.join(chunks)
    assert result['written'] == 1024 and result['files'][0].closed


@pytest.mark.parametrize(('path', 'method'), [
    ('/api/items', 'POST'), ('/api/spool-documents/files/sd_TEST', 'GET'),
    (PATH, 'GET'), ('/api/spool-documents/requirements/OSPOOL-TEST', 'POST'),
])
def test_unrelated_routes_and_methods_are_untouched(monkeypatch, path, method):
    result = run_request(monkeypatch, [b'a' * 2048], path=path, method=method)
    assert result['entered'] and result['messages'][0]['status'] == 200
    assert result['files'] == [] and result['written'] == 0


def test_disconnect_closes_partial_buffer_without_calling_parser(monkeypatch):
    result = run_request(monkeypatch, [b'a' * 700], disconnect=True)
    assert not result['entered'] and result['messages'] == []
    assert result['files'][0].closed


def test_downstream_error_still_closes_buffer(monkeypatch):
    result = run_request(monkeypatch, [b'a' * 700], fail_app=True)
    assert isinstance(result['error'], RuntimeError)
    assert str(result['error']) == 'Synthetic downstream failure'
    assert result['files'][0].closed


def test_authorized_real_csv_preview_and_upload_still_work(api, monkeypatch):
    monkeypatch.setattr(upload_limits, 'MAX_REQUEST_BYTES', 4096)
    path = requirement_path(setup(api))
    result = request_upload(api, path)
    assert result.status_code == 200, result.text
    assert result.json()['active']['bom']['bom']['line_count'] == 2


@pytest.mark.parametrize('suffix', ['preview', 'upload', 'isometric-preview', 'isometric-import'])
def test_unauthenticated_oversized_multipart_is_413_before_auth_or_parser(api, monkeypatch, suffix):
    monkeypatch.setattr(upload_limits, 'MAX_REQUEST_BYTES', 1024)
    path = requirement_path(setup(api)) + '/' + suffix
    response = api.request('POST', path, role=None, data={'kind': 'bom'},
        files=[('files', ('oversized.csv', b'x' * 2048, 'text/csv'))])
    assert response.status_code == 413, response.text
    assert response.json()['detail'].startswith('Spool document upload is too large')
    assert response.headers['x-content-type-options'] == 'nosniff'


@pytest.mark.parametrize('suffix', ['preview', 'isometric-preview', 'isometric-import'])
def test_actual_multipart_parser_is_never_called_for_oversized_chunked_body(api, monkeypatch, suffix):
    from starlette.formparsers import MultiPartParser

    path = requirement_path(setup(api)) + '/' + suffix
    monkeypatch.setattr(upload_limits, 'MAX_REQUEST_BYTES', 1024)
    calls = []

    async def unexpected_parse(self):
        calls.append(True)
        raise AssertionError('Oversized request reached multipart parser')

    monkeypatch.setattr(MultiPartParser, 'parse', unexpected_parse)
    response = api.request('POST', path, role=None,
        headers={'Content-Type': 'multipart/form-data; boundary=test-boundary'},
        content=iter([b'--test-boundary\r\n', b'x' * 2048]))
    assert response.status_code == 413, response.text
    assert calls == []
