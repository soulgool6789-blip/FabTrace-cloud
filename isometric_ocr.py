"""Bounded, offline image conversion and OCR for scanned spool documents.

Importing this module loads only the standard library. Each requested scan page
is rendered and recognized in an isolated child process that exits afterwards;
native-PDF requests do not load the OCR models into the application process.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time


MAX_OCR_PAGES = 8
MAX_PAGE_SECONDS = 20
MAX_TOTAL_SECONDS = 50
MAX_WORKER_RSS_KIB = 350 * 1024
MAX_SERVICE_RSS_KIB = 512 * 1024
MEMORY_RESERVE_KIB = 64 * 1024
# Real 777/712 and repeated image API probes peak at 276.51 MiB with EXTENDED
# optimization. Admit only with at least 288 MiB, retaining an 11.49 MiB margin
# in addition to the separate service reserve and the live RSS watchdog.
MIN_WORKER_BUDGET_KIB = 288 * 1024
MAX_RENDER_PIXELS = 4_000_000
MAX_WORKER_OUTPUT = 2 * 1024 * 1024
MAX_IMAGE_INPUT_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PDF_BYTES = 40 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_SECONDS = 20
MIN_IMAGE_BUDGET_KIB = 64 * 1024
_WORKER_GATE = threading.BoundedSemaphore(1)
_WORKER_LOCK_PATH = '/tmp/fabtrace-isometric-ocr.lock'


class ImageNormalizationError(ValueError):
    def __init__(self, message, status_code=415):
        super().__init__(message)
        self.status_code = status_code


def normalize_image_pdf(content):
    """Encode one camera image without retaining pixel arenas in the web app.

    The same host/process gate excludes an OCR child while an image is being
    encoded. Both paths keep the actual service headroom and RSS watchdog;
    the converted page is still parsed and sanitized by the document importer.
    """
    if not content:
        raise ImageNormalizationError('Empty image files cannot be uploaded.')
    if len(content) > MAX_IMAGE_INPUT_BYTES:
        raise ImageNormalizationError('Each image must be 20 MiB or smaller.', 413)
    if not _WORKER_GATE.acquire(blocking=False):
        raise ImageNormalizationError('Another drawing scan is being prepared. Please retry in a moment.', 429)
    lock = process = None
    try:
        import fcntl
        flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
        lock = os.open(_WORKER_LOCK_PATH, flags, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ImageNormalizationError('Another drawing scan is being prepared. Please retry in a moment.', 429)
        if _worker_budget_kib() < MIN_IMAGE_BUDGET_KIB:
            raise ImageNormalizationError('Not enough memory is available to prepare this image now. Please retry or upload a PDF.', 413)
        with tempfile.TemporaryDirectory(prefix='fabtrace-image-pdf-') as directory:
            source = Path(directory) / 'source-image'
            output_path = Path(directory) / 'page.pdf'
            source.write_bytes(content)
            env = os.environ.copy()
            env.update({'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
                        'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1'})
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                '--image-pdf', str(source), str(output_path)], stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=env)
            deadline = time.monotonic() + MAX_IMAGE_SECONDS
            while True:
                try:
                    message, _ = process.communicate(timeout=min(.15, max(.01, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    if _resident_kib(process.pid) > _worker_budget_kib():
                        process.kill()
                        process.communicate()
                        raise ImageNormalizationError('This image exceeds the available conversion memory. Upload a smaller scan or PDF.', 413)
                    if output_path.exists() and output_path.stat().st_size > MAX_IMAGE_PDF_BYTES:
                        process.kill()
                        process.communicate()
                        raise ImageNormalizationError('The converted image exceeds the 40 MiB document limit.', 413)
                    if time.monotonic() >= deadline:
                        process.kill()
                        process.communicate()
                        raise ImageNormalizationError('Preparing this image exceeded the time limit. Upload a smaller scan or PDF.')
            if process.returncode != 0 or len(message) > 4096:
                raise ImageNormalizationError('This image could not be prepared safely. Upload a valid PNG, JPEG or PDF.')
            try:
                status = json.loads(message)
            except (ValueError, UnicodeError):
                raise ImageNormalizationError('The image converter returned an unreadable result. Please retry with a valid scan.')
            if not isinstance(status, dict) or not status.get('ok'):
                detail = status.get('error', '') if isinstance(status, dict) else ''
                code = status.get('status_code', 415) if isinstance(status, dict) else 415
                raise ImageNormalizationError(detail or 'A drawing page could not be read. Upload a valid PNG or JPEG.',
                    code if code in (400, 413, 415) else 415)
            if not output_path.is_file() or not 0 < output_path.stat().st_size <= MAX_IMAGE_PDF_BYTES:
                raise ImageNormalizationError('The converted image exceeds the 40 MiB document limit.', 413)
            return output_path.read_bytes()
    except ImageNormalizationError:
        raise
    except Exception:
        raise ImageNormalizationError('The image converter could not prepare this scan. Please retry with a valid PNG, JPEG or PDF.')
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
        if lock is not None:
            os.close(lock)
        _WORKER_GATE.release()


def _empty(message):
    return {'tables': [], 'drawing': '', 'revision': '', 'warnings': [message]}


class LocalOCRProvider:
    """Context-managed callback for ``extract_isometric_boms``.

    ``with LocalOCRProvider() as provider: extract_isometric_boms(...,
    ocr_page_provider=provider)`` keeps temporary input bytes private and deletes
    them when extraction finishes. No upload, remote model, or external API is
    used. Budget failures return explicit unreadable-page warnings.
    """
    def __init__(self, *, max_pages=MAX_OCR_PAGES, page_timeout=MAX_PAGE_SECONDS,
                 total_timeout=MAX_TOTAL_SECONDS):
        self.max_pages = min(MAX_OCR_PAGES, max(0, int(max_pages)))
        self.page_timeout = min(MAX_PAGE_SECONDS, max(.1, float(page_timeout)))
        self.total_timeout = min(MAX_TOTAL_SECONDS, max(.1, float(total_timeout)))
        self.pages_used = 0
        self.started = None
        self._temporary = None
        self._source_hash = None
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
        self._closed = True

    def __call__(self, pdf_bytes, page_number, width, height):
        if self._closed:
            return _empty('The local OCR session has closed; preview the drawing again.')
        if self.pages_used >= self.max_pages:
            return _empty(f'Local OCR is limited to {self.max_pages} scanned pages per preview. All drawing pages remain available.')
        if self.started is None:
            self.started = time.monotonic()
        remaining = self.total_timeout - (time.monotonic() - self.started)
        if remaining <= .1:
            return _empty('The local OCR time budget was reached. All drawing pages are retained; review the remaining BOMs separately.')
        if not _WORKER_GATE.acquire(blocking=False):
            return _empty('Another drawing scan is being read. Try the preview again when it finishes.')
        lock = None
        process = None
        try:
            # The process gate also covers deployments with multiple application
            # workers sharing this host. Never queue a second 300 MB OCR process.
            import fcntl
            flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
            lock = os.open(_WORKER_LOCK_PATH, flags, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return _empty('Another drawing scan is being read. Try the preview again when it finishes.')
            if importlib.util.find_spec('rapidocr') is None or importlib.util.find_spec('onnxruntime') is None:
                return _empty('Local OCR is unavailable on this server. Upload a text PDF or the reviewed spool BOM separately.')
            if _worker_budget_kib() < MIN_WORKER_BUDGET_KIB:
                return _empty('Not enough memory is available to read this scan now. All drawing pages remain available; upload a text PDF or review the BOM separately.')
            if self._temporary is None:
                self._temporary = tempfile.TemporaryDirectory(prefix='fabtrace-isometric-ocr-')
            source_hash = hashlib.sha256(pdf_bytes).hexdigest()
            input_path = Path(self._temporary.name) / 'drawing.pdf'
            if self._source_hash != source_hash:
                input_path.write_bytes(pdf_bytes)
                self._source_hash = source_hash
            self.pages_used += 1
            timeout = min(self.page_timeout, remaining)
            env = os.environ.copy()
            env.update({'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
                        'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1'})
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), '--worker',
                 str(input_path), str(int(page_number))],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            deadline = time.monotonic() + timeout
            while True:
                try:
                    output, error = process.communicate(timeout=min(.15, max(.01, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    rss = _resident_kib(process.pid)
                    if rss > _worker_budget_kib():
                        process.kill()
                        process.communicate()
                        return _empty('The scan exceeded the local OCR memory limit. Upload a clearer cropped drawing or a reviewed BOM.')
                    if time.monotonic() >= deadline:
                        process.kill()
                        process.communicate()
                        return _empty('Reading this scan exceeded the local OCR time limit. All drawing pages were retained.')
            if process.returncode != 0 or len(output) > MAX_WORKER_OUTPUT:
                return _empty('Local OCR could not read this scan within its resource limits. Upload a clearer drawing or a reviewed BOM.')
            try:
                result = json.loads(output)
            except (ValueError, UnicodeError):
                return _empty('Local OCR returned an unreadable result. No material values were guessed.')
            return result if isinstance(result, dict) and isinstance(result.get('tables'), list) else _empty('Local OCR did not identify a complete spool BOM.')
        except Exception as exc:
            return _empty(f'Local OCR could not read this page ({type(exc).__name__}). No material values were guessed.')
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()
            if lock is not None:
                os.close(lock)
            _WORKER_GATE.release()


def _resident_kib(pid):
    try:
        status = Path(f'/proc/{int(pid)}/status').read_text()
        match = re.search(r'^VmRSS:\s+(\d+)\s+kB', status, re.M)
        return int(match.group(1)) if match else 0
    except OSError:
        return 0


def _worker_budget_kib():
    parent_rss = _resident_kib(os.getpid())
    if not parent_rss:
        try:
            import resource
            parent_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except (ImportError, ValueError):
            return 0
    return max(0, min(MAX_WORKER_RSS_KIB,
                      MAX_SERVICE_RSS_KIB - parent_rss - MEMORY_RESERVE_KIB))


def _image_pdf_worker(input_path, output_path):
    """Pillow-only child; complete raster dimensions and camera orientation stay intact."""
    import socket
    import warnings
    from PIL import Image, ImageOps

    def no_network(*_args, **_kwargs):
        raise RuntimeError('This image converter is offline.')

    socket.create_connection = no_network
    socket.socket.connect = no_network
    if not 0 < input_path.stat().st_size <= MAX_IMAGE_INPUT_BYTES:
        raise ImageNormalizationError('Each image must be 20 MiB or smaller.', 413)

    class LimitedOutput:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def write(self, data):
            if self.stream.tell() + len(data) > MAX_IMAGE_PDF_BYTES:
                raise ImageNormalizationError('The converted image exceeds the 40 MiB document limit.', 413)
            return self.stream.write(data)

    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        # Pillow's ImageFile context manager closes only the file handle.
        # closing() also destroys the native pixel core on every exit.
        with contextlib.closing(Image.open(input_path)) as picture:
            if picture.format not in ('PNG', 'JPEG'):
                raise ImageNormalizationError('The actual scan format must be PNG or JPEG.')
            if picture.width * picture.height > MAX_IMAGE_PIXELS:
                raise ImageNormalizationError('A scan is too large. Use an image of at most 20 megapixels.', 400)
            picture.load()
            ImageOps.exif_transpose(picture, in_place=True)
            converted = picture if picture.mode == 'RGB' else picture.convert('RGB')
            try:
                with output_path.open('w+b') as output:
                    # Keep the same full-resolution page and JPEG settings as
                    # the parent encoder; thin one-digit quantities stay legible.
                    converted.save(LimitedOutput(output), format='PDF', resolution=150.0,
                                   quality=95, subsampling=0)
            finally:
                if converted is not picture:
                    converted.close()


def _key(value):
    return re.sub(r'[^A-Z0-9]', '', str(value).upper())


def _center(token):
    x0, y0, x1, y1 = token['bbox']
    return (x0 + x1) / 2, (y0 + y1) / 2


def _groups(indices, distance=3):
    groups = []
    for value in indices:
        if groups and value - groups[-1][-1] <= distance:
            groups[-1].append(int(value))
        else:
            groups.append([int(value)])
    return [round(sum(group) / len(group)) for group in groups]


def _join_tokens(tokens):
    # Adjacent OCR lines retain their reading order; no characters or fractions
    # are repaired. All OCR output remains a reviewable transcription.
    return ' '.join(str(t['text']).strip() for t in sorted(tokens, key=lambda t: (round(t['bbox'][1] / 8), t['bbox'][0]))).strip()


def _recognize_cell(engine, image, bbox):
    """Retry an actually inked cell when full-page detection missed its text."""
    import cv2
    import numpy as np
    x0, y0, x1, y1 = [int(round(value)) for value in bbox]
    x0, y0 = max(0, x0 + 3), max(0, y0 + 3)
    x1, y1 = min(image.shape[1], x1 - 3), min(image.shape[0], y1 - 3)
    if x1 <= x0 or y1 <= y0:
        return '', 0.0
    cell = image[y0:y1, x0:x1]
    gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY) if cell.ndim == 3 else cell
    # Empty table cells must stay blank; the recognizer must not hallucinate a
    # numeral from a border or from an all-white input.
    mask = gray < 170
    if int(mask.sum()) < 10 or not mask.any(axis=0).sum() >= 3 or not mask.any(axis=1).sum() >= 4:
        return '', 0.0
    cell = cv2.copyMakeBorder(cell, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    output = engine(cell, use_det=False, use_cls=False, use_rec=True)
    texts = list(getattr(output, 'txts', None) or [])
    scores = list(getattr(output, 'scores', None) or [])
    if len(texts) != 1:
        return '', 0.0
    return str(texts[0]).strip(), float(scores[0]) if scores else 0.0


def _metadata(tokens, image, engine):
    drawing = revision = ''
    warnings = []
    height, width = image.shape[:2]
    bottom = [t for t in tokens if _center(t)[1] > height * .83]
    labels = [t for t in bottom if _key(t['text']) in {'DWGNO', 'DRAWINGNO', 'DWG', 'DRAWING'}]
    if labels:
        label = max(labels, key=lambda t: t['bbox'][0])
        next_labels = [t for t in bottom if t['bbox'][0] > label['bbox'][2] and _key(t['text']) in {'SHEET', 'REV', 'REVISION'}]
        right = min((t['bbox'][0] for t in next_labels), default=width)
        matches = [t for t in bottom if label['bbox'][0] <= _center(t)[0] < right
                   and _center(t)[1] >= _center(label)[1]
                   and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*[-_/][A-Za-z0-9._/-]+', t['text'])]
        if len(matches) == 1:
            drawing = matches[0]['text']
            if matches[0]['score'] < .98:
                warnings.append('The drawing number has uncertain OCR text; verify the title block.')
    labels = [t for t in bottom if _key(t['text']) in {'REV', 'REVISION'}]
    if labels:
        label = max(labels, key=lambda t: t['bbox'][0])
        matches = [t for t in bottom if t['bbox'][0] > label['bbox'][2]
                   and abs(_center(t)[1] - _center(label)[1]) < 50
                   and re.fullmatch(r'[A-Za-z0-9]{1,12}', t['text'])]
        if len(matches) == 1:
            revision = matches[0]['text']
        elif not matches and engine is not None:
            y0 = max(0, label['bbox'][1] - 8)
            y1 = min(height, label['bbox'][3] + 28)
            value, score = _recognize_cell(engine, image, (label['bbox'][2] + 2, y0, width - 10, y1))
            if re.fullmatch(r'[A-Za-z0-9]{1,12}', value) and score >= .90:
                revision = value
                warnings.append('Revision was read from a separate OCR crop; verify it against the title block.')
    return drawing, revision, warnings


def _tables_from_tokens(image, tokens, engine=None, *, page_width=None, page_height=None,
                       scale=1.0, crop_left=0.0, crop_top=0.0, allow_standalone=False):
    """Recover ruled cells from raster lines, then place observed OCR boxes.

    Grid geometry supplies only boundaries; item numbers, quantities and part
    identifiers always come from recognized source text, never row positions.
    """
    import cv2
    import numpy as np

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    _, binary = cv2.threshold(gray, 195, 255, cv2.THRESH_BINARY_INV)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(24, height // 45))))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                 cv2.getStructuringElement(cv2.MORPH_RECT, (max(45, width // 25), 1)))
    header_items = [t for t in tokens if _key(t['text']) == 'ITEM'
                    and (allow_standalone or _center(t)[1] > height * .20)]
    tables = []
    warnings = []
    for item_header in header_items[:6]:
        header_y = _center(item_header)[1]
        token_height = max(10, item_header['bbox'][3] - item_header['bbox'][1])
        header_tokens = [t for t in tokens if abs(_center(t)[1] - header_y) < token_height * .65]
        if not any(_key(t['text']) in {'QTY', 'QUANTITY'} for t in header_tokens) or not any(_key(t['text']) == 'DESCRIPTION' for t in header_tokens):
            continue
        band_start, band_end = max(0, int(header_y - token_height)), min(height, int(header_y + token_height))
        crossed = np.count_nonzero(vertical[band_start:band_end], axis=0)
        xs = _groups(np.flatnonzero(crossed >= max(12, (band_end - band_start) * .65)))
        # Discard page borders left of the ITEM cell; keep exactly the lines
        # enclosing this observed header row, rather than evenly spacing columns.
        # OCR boxes can extend a few pixels across a printed rule, particularly
        # on a cropped BOM. The observed text center still identifies its
        # enclosing cell, just as it does for every material/header value below.
        left_options = [x for x in xs if x < _center(item_header)[0]]
        if not left_options:
            warnings.append('The scanned BOM has no clear left table border.')
            continue
        left = max(left_options)
        xs = [x for x in xs if x >= left]
        if not 5 <= len(xs) <= 16:
            warnings.append('The scanned BOM column boundaries could not be separated reliably.')
            continue
        right = xs[-1]
        row_coverage = np.count_nonzero(horizontal[:, left:right + 1], axis=1)
        ys = _groups(np.flatnonzero(row_coverage >= (right - left) * .78))
        above = [y for y in ys if y < header_y]
        below = [y for y in ys if y > header_y]
        if not above or not below:
            warnings.append('The scanned BOM header is not enclosed by readable row lines.')
            continue
        header_top, header_bottom = max(above), min(below)
        row_height = header_bottom - header_top
        if row_height < 8 or row_height > height * (.40 if allow_standalone else .10):
            continue
        def connected_boundaries(start, values):
            found = [start]
            for y in values:
                if abs(found[-1] - y) > row_height * 3:
                    break
                middle = int((found[-1] + y) / 2)
                internal_lines = sum(bool(np.any(vertical[max(0, middle - 2):middle + 3,
                    max(0, x - 2):x + 3])) for x in xs[1:-1])
                if internal_lines < max(1, len(xs[1:-1]) * .65):
                    break
                found.append(y)
            return sorted(found)
        before_rows = connected_boundaries(header_top, reversed([y for y in above if y < header_top]))
        after_rows = connected_boundaries(header_bottom, [y for y in below if y > header_bottom])
        if len(before_rows) > 1 and len(after_rows) > 1:
            warnings.append('The scanned table has material rows on both sides of its header; review its boundaries manually.')
            continue
        boundaries = before_rows if len(before_rows) > 1 else after_rows
        if len(boundaries) < 2 or len(boundaries) > 501:
            warnings.append('The scanned BOM material rows could not be bounded reliably.')
            continue
        table_bottom = max(header_bottom, boundaries[-1])
        footer_options = [t for t in tokens if table_bottom <= _center(t)[1] <= table_bottom + row_height * 2.2
                          and 'QTY' in _key(t['text']) and 'SHOWNFOR' in _key(t['text'])]
        if len(footer_options) > 1 or (not footer_options and not allow_standalone):
            warnings.append('The scanned BOM has no unique readable spool-number footer.')
            continue
        footer = footer_options[0] if footer_options else None
        headers = []
        for x0, x1 in zip(xs, xs[1:]):
            headers.append(_join_tokens([t for t in header_tokens if x0 < _center(t)[0] < x1]))
        header_keys = {_key(value) for value in headers}
        if not {'ITEM', 'DESCRIPTION'} <= header_keys or not header_keys.intersection({'QTY', 'QUANTITY'}):
            warnings.append('The scanned BOM column headings could not be read unambiguously.')
            continue
        table_warnings = []
        if footer and footer['score'] < .98:
            table_warnings.append('The spool footer contains uncertain OCR text; verify the complete spool number.')
        rows = []
        row_notes = {}
        for row_number, (y0, y1) in enumerate(zip(boundaries, boundaries[1:]), 1):
            row = []
            notes = []
            for column, (x0, x1) in enumerate(zip(xs, xs[1:])):
                cell_tokens = [t for t in tokens if x0 < _center(t)[0] < x1 and y0 < _center(t)[1] < y1]
                text = _join_tokens(cell_tokens)
                score = min((t['score'] for t in cell_tokens), default=0.0)
                label = headers[column] or f'column {column + 1}'
                if not text and engine is not None and _key(label) in {'ITEM', 'QTY', 'QUANTITY', 'TASPART', 'TASLN', 'PARTNUMBER'}:
                    text, score = _recognize_cell(engine, image, (x0, y0, x1, y1))
                    if text:
                        table_warnings.append(f'Source row {row_number}, {label}: text "{text}" was recovered from a separate OCR crop; verify it.')
                if text and score < .95:
                    table_warnings.append(f'Source row {row_number}, {label}: uncertain OCR text "{text}"; compare it with the drawing.')
                    notes.append(f'OCR read {label} as {text}; compare this uncertain text with the drawing.')
                if text and _key(label) in {'LENGTH', 'CUTLENGTH', 'LENGTHIN', 'LENGTHMM'}:
                    fraction = re.fullmatch(r'(\d+)\s*/\s*(\d+)\s*(?:["\u2033]|in(?:ches)?\.?)?', text, re.I)
                    if fraction and int(fraction.group(1)) >= max(1, int(fraction.group(2))):
                        message = (f'OCR length {text} may have lost a space between whole inches and the fraction. '
                                   'Correct or confirm the exact cut length against the drawing.')
                        table_warnings.append(f'Source row {row_number}, {label}: {message}')
                        notes.append(message)
                    elif not re.search(r'["\u2033]|\b(?:in|inch|inches|mm|cm|ft)\b', text, re.I):
                        message = f'OCR length {text} has no readable unit mark. Verify its units against the drawing.'
                        table_warnings.append(f'Source row {row_number}, {label}: {message}')
                        notes.append(message)
                # Merged detections crossing a cell boundary can silently put a
                # quantity inside a part number. Surface that evidence explicitly.
                if any(t['bbox'][0] < x0 - 4 or t['bbox'][2] > x1 + 4 for t in cell_tokens):
                    table_warnings.append(f'Source row {row_number}, {label}: OCR text crosses a column line; verify this cell.')
                row.append(text)
            rows.append(row)
            if notes:
                row_notes[str(row_number)] = notes
        rows.append(headers)
        if footer:
            rows.append([footer['text'], *([None] * (len(headers) - 1))])
        tables.append({'rows': rows, 'bbox': [crop_left + left / scale, crop_top + min(boundaries[0], header_top) / scale,
                                              crop_left + right / scale, crop_top + (table_bottom + (row_height if footer else 0)) / scale],
                       'warnings': list(dict.fromkeys(table_warnings))})
        tables[-1]['row_notes'] = row_notes
    drawing, revision, metadata_warnings = _metadata(tokens, image, engine)
    warnings.extend(metadata_warnings)
    title_keys = {_key(token['text']) for token in tokens if _center(token)[1] > height * .83}
    title_evidence = (any(key.startswith(('DWG', 'DRAWING')) for key in title_keys)
                      and any(key.startswith(('SHEET', 'REV')) for key in title_keys))
    return {'tables': tables, 'drawing': drawing, 'revision': revision,
            'title_block_evidence': title_evidence, 'warnings': list(dict.fromkeys(warnings))}


def _render_scan(input_path, page_number, *, full_page=False):
    """Render a bounded region; standalone tables require the entire page."""
    import cv2
    import numpy as np
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(input_path))
    try:
        if not 1 <= page_number <= len(pdf):
            return _empty('The requested scan page does not exist.')
        page = pdf[page_number - 1]
        try:
            width, height = page.get_size()
            crop_left, crop_top = (0, 0) if full_page else (width * .45, height * .30)
            crop_width, crop_height = width - crop_left, height - crop_top
            if crop_width <= 0 or crop_height <= 0:
                return _empty('The scan page has invalid dimensions.')
            scale = min(2.25, 2200 / max(crop_width, crop_height),
                        math.sqrt(MAX_RENDER_PIXELS / (crop_width * crop_height)))
            bitmap = page.render(scale=scale, crop=(crop_left, 0, 0, crop_top))
            try:
                image = cv2.cvtColor(np.asarray(bitmap.to_pil().convert('RGB')), cv2.COLOR_RGB2BGR)
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        pdf.close()
    return image, width, height, scale, crop_left, crop_top


def _read_scan(engine, rendered, *, allow_standalone=False):
    if not isinstance(rendered, tuple):
        return rendered
    image, width, height, scale, crop_left, crop_top = rendered
    # Cell retries use recognition-only mode, which RapidOCR retains between
    # calls. Explicitly re-enable detection for the whole-page fallback.
    output = engine(image, use_det=True, use_cls=False, use_rec=True)
    if getattr(output, 'boxes', None) is None:
        return _empty('No readable text was found in the scanned page area.')
    tokens = []
    for box, text, score in zip(output.boxes, output.txts, output.scores):
        tokens.append({'text': str(text), 'score': float(score),
                       'bbox': [float(box[:, 0].min()), float(box[:, 1].min()),
                                float(box[:, 0].max()), float(box[:, 1].max())]})
    return _tables_from_tokens(image, tokens, engine, page_width=width, page_height=height,
                              scale=scale, crop_left=crop_left, crop_top=crop_top,
                              allow_standalone=allow_standalone)


def _scan_geometry(input_path, page_number, table_boxes):
    """Look for long oblique view lines outside the observed material tables.

    A small full-page thumbnail keeps this test cheap. It is evidence of a
    drawing view, never a source for material quantities or identifiers.
    """
    import cv2
    import numpy as np
    import pypdfium2 as pdfium
    try:
        with pdfium.PdfDocument(str(input_path)) as pdf:
            page = pdf[page_number - 1]
            try:
                width, height = page.get_size()
                scale = min(1.0, 1000 / max(width, height))
                bitmap = page.render(scale=scale)
                try:
                    gray = np.asarray(bitmap.to_pil().convert('L')).copy()
                finally:
                    bitmap.close()
            finally:
                page.close()
        for box in table_boxes:
            if box and len(box) == 4:
                x0, top, x1, bottom = [int(value * scale) for value in box]
                gray[max(0, top - 5):bottom + 6, max(0, x0 - 5):x1 + 6] = 255
        height, width = gray.shape
        view = gray[int(height * .08):int(height * .74), int(width * .05):int(width * .96)]
        edges = cv2.Canny(view, 35, 100)
        minimum = min(width, height)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=max(20, int(minimum * .05)),
            minLineLength=max(25, int(minimum * .08)), maxLineGap=max(2, int(minimum * .012)))
        count, total = 0, 0.0
        for x0, y0, x1, y1 in (lines.reshape(-1, 4)[:1000] if lines is not None else []):
            dx, dy = abs(int(x1) - int(x0)), abs(int(y1) - int(y0))
            if dx > minimum * .025 and dy > minimum * .025:
                count += 1
                total += math.hypot(dx, dy)
                if count >= 2 and total >= minimum * .16:
                    return True
    except Exception:
        # Uncertain layout must remain a BOM source, not replace an isometric.
        return False
    return False


def _onnx_session_options():
    # Import only in the child. EXTENDED avoids the additional retained graph
    # allocations measured with ALL without changing model inputs or outputs.
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
    options.enable_cpu_mem_arena = False
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.log_severity_level = 4
    return options


def _local_engine(det, rec):
    from rapidocr import RapidOCR
    import onnxruntime as ort
    from omegaconf import flag_override
    class LocalEngine(RapidOCR):
        def _supply_session(self, section, path):
            if self.cfg[section].get('session') is None:
                with flag_override(self.cfg, 'allow_objects', True):
                    self.cfg[section].session = ort.InferenceSession(str(path),
                        sess_options=_onnx_session_options(), providers=['CPUExecutionProvider'])

        def _load_det_model(self):
            self._supply_session('Det', det)
            return super()._load_det_model()

        def _load_rec_model(self):
            self._supply_session('Rec', rec)
            return super()._load_rec_model()

    engine = LocalEngine(params={
        'Det.model_path': str(det), 'Rec.model_path': str(rec),
        'EngineConfig.onnxruntime.intra_op_num_threads': 1,
        'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        'EngineConfig.onnxruntime.enable_cpu_mem_arena': False,
        'Global.log_level': 'error', 'Global.max_side_len': 2200,
        'Det.limit_side_len': 960, 'Det.limit_type': 'max',
        'Rec.rec_batch_num': 1, 'Global.use_cls': False})
    # RapidOCR explicitly supports a supplied InferenceSession. Its models are
    # loaded lazily; preserve that timing. Preloading recognition before the
    # first detector pass retains substantially more working memory. These
    # pinned-version load hooks only supply the supported local session object.
    return engine


def _worker(input_path, page_number):
    # All heavy imports below intentionally live in the short-lived subprocess.
    import rapidocr
    import socket

    def no_network(*_args, **_kwargs):
        raise RuntimeError('This OCR worker is offline.')

    socket.create_connection = no_network
    socket.socket.connect = no_network
    model_dir = Path(rapidocr.__file__).resolve().parent / 'models'
    det = model_dir / 'PP-OCRv6_det_small.onnx'
    rec = model_dir / 'PP-OCRv6_rec_small.onnx'
    if not det.is_file() or not rec.is_file():
        return _empty('Bundled local OCR models are unavailable; no models or drawings were sent to an external service.')
    engine = _local_engine(det, rec)
    strict = _read_scan(engine, _render_scan(input_path, page_number))
    if strict.get('tables'):
        strict['drawing_geometry'] = _scan_geometry(input_path, page_number,
            [table.get('bbox') for table in strict['tables']])
        if strict.get('drawing_geometry') or strict.get('drawing'):
            return strict
    # Keep one bounded worker/time budget. The fallback reuses the same local
    # models and reads the full image only when the full-sheet layout was not
    # identified, so a BOM crop never loses its left columns or top rows.
    whole = _read_scan(engine, _render_scan(input_path, page_number, full_page=True), allow_standalone=True)
    result = whole if whole.get('tables') else strict if strict.get('tables') else whole
    result['drawing_geometry'] = bool((result.get('drawing') or result.get('title_block_evidence') or result.get('tables')) and
        _scan_geometry(input_path, page_number, [table.get('bbox') for table in result.get('tables', [])]))
    return result


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] not in ('--worker', '--image-pdf'):
        raise SystemExit(2)
    try:
        # Keep third-party progress/log text out of the structured protocol.
        with contextlib.redirect_stdout(sys.stderr):
            if sys.argv[1] == '--image-pdf':
                _image_pdf_worker(Path(sys.argv[2]), Path(sys.argv[3]))
                result = {'ok': True}
            else:
                result = _worker(Path(sys.argv[2]), int(sys.argv[3]))
    except ImageNormalizationError as exc:
        result = {'ok': False, 'error': str(exc), 'status_code': exc.status_code}
    except Exception as exc:
        result = ({'ok': False, 'error': 'A drawing page could not be read. Upload a valid PNG or JPEG.', 'status_code': 415}
                  if sys.argv[1] == '--image-pdf' else
                  _empty(f'Local OCR could not read this page ({type(exc).__name__}).'))
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
