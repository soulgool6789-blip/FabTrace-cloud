"""Bound spool-document request bodies before FastAPI parses multipart files.

File-size checks inside an endpoint happen after the multipart parser has
already received its files. Only the new document upload/preview endpoints use
this middleware. Accepted bodies are replayed unchanged from a bounded spool;
rejected bodies never reach the parser or any endpoint mutation.
"""
import re
import tempfile

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


# The endpoint permits 40 MiB of files. The extra 2 MiB covers multipart field,
# filename and boundary overhead; it is not additional allowed file content.
MAX_REQUEST_BYTES = 42 * 1024 * 1024
MEMORY_SPOOL_BYTES = 1024 * 1024
REPLAY_CHUNK_BYTES = 64 * 1024
_UPLOAD_PATH = re.compile(
    r'^/api/(?:spool-documents/[^/]+/[^/]+/(?:preview|upload|isometric-preview|isometric-import)'
    r'|spool-boms/spools/[^/]+/(?:mtr-preview|mtr-documents))/?$')


class SpoolDocumentUploadLimit:
    def __init__(self, app: ASGIApp):
        self.app = app

    @staticmethod
    async def reject(scope: Scope, receive: Receive, send: Send):
        headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
        # An early rejection leaves unread bytes on an HTTP/1 connection.
        # Closing it prevents a client from continuing that oversized upload.
        if scope.get('http_version') in ('1.0', '1.1'):
            headers['Connection'] = 'close'
        response = JSONResponse(status_code=413, headers=headers, content={
            'detail': 'Spool document upload is too large. Select files totaling no more than 40 MiB.'})
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if (scope['type'] != 'http' or scope.get('method') != 'POST'
                or not _UPLOAD_PATH.fullmatch(scope.get('path', ''))):
            await self.app(scope, receive, send)
            return

        limit = MAX_REQUEST_BYTES
        for name, value in scope.get('headers', []):
            if name.lower() != b'content-length':
                continue
            try:
                declared_length = int(value)
            except (ValueError, TypeError):
                # The server handles malformed framing. Actual bytes are still
                # counted below; a missing or misleading length cannot bypass it.
                continue
            if declared_length > limit:
                await self.reject(scope, receive, send)
                return

        # At most 1 MiB remains in memory; larger accepted bodies use a temporary
        # file that is closed on success, rejection, disconnect or application
        # error. Disk reads/writes run outside the event loop. The parser is not
        # invoked until the complete body has passed the total byte limit.
        with tempfile.SpooledTemporaryFile(max_size=MEMORY_SPOOL_BYTES, mode='w+b') as buffered:
            total = 0
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                if message['type'] != 'http.request':
                    continue
                chunk = message.get('body', b'')
                total += len(chunk)
                if total > limit:
                    await self.reject(scope, receive, send)
                    return
                if chunk:
                    await run_in_threadpool(buffered.write, chunk)
                if not message.get('more_body', False):
                    break

            await run_in_threadpool(buffered.seek, 0)
            remaining, complete = total, False

            async def replay():
                nonlocal remaining, complete
                if complete:
                    return await receive()
                chunk = await run_in_threadpool(buffered.read, min(REPLAY_CHUNK_BYTES, remaining))
                remaining -= len(chunk)
                complete = remaining == 0
                return {'type': 'http.request', 'body': chunk, 'more_body': not complete}

            await self.app(scope, replay, send)
