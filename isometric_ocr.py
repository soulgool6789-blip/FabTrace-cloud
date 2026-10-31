"""Bounded, offline OCR for scanned isometric BOM grids.

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
MIN_WORKER_BUDGET_KIB = 320 * 1024
MAX_RENDER_PIXELS = 4_000_000
MAX_WORKER_OUTPUT = 2 * 1024 * 1024
_WORKER_GATE = threading.BoundedSemaphore(1)


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
            lock = os.open('/tmp/fabtrace-isometric-ocr.lock', flags, 0o600)
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
    texts = list(output.txts or [])
    scores = list(output.scores or [])
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
                       scale=1.0, crop_left=0.0, crop_top=0.0):
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
    header_items = [t for t in tokens if _key(t['text']) == 'ITEM' and _center(t)[1] > height * .20]
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
        left_options = [x for x in xs if x < item_header['bbox'][0]]
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
        if row_height < 8 or row_height > height * .10:
            continue
        boundaries = [header_top]
        for y in reversed([y for y in above if y < header_top]):
            if boundaries[-1] - y > row_height * 3:
                break
            boundaries.append(y)
        boundaries = sorted(boundaries)
        if len(boundaries) < 2 or len(boundaries) > 501:
            warnings.append('The scanned BOM material rows could not be bounded reliably.')
            continue
        footer_options = [t for t in tokens if header_bottom <= _center(t)[1] <= header_bottom + row_height * 2.2
                          and 'QTY' in _key(t['text']) and 'SHOWNFOR' in _key(t['text'])]
        if len(footer_options) != 1:
            warnings.append('The scanned BOM has no unique readable spool-number footer.')
            continue
        footer = footer_options[0]
        headers = []
        for x0, x1 in zip(xs, xs[1:]):
            headers.append(_join_tokens([t for t in header_tokens if x0 < _center(t)[0] < x1]))
        header_keys = {_key(value) for value in headers}
        if not {'ITEM', 'DESCRIPTION'} <= header_keys or not header_keys.intersection({'QTY', 'QUANTITY'}):
            warnings.append('The scanned BOM column headings could not be read unambiguously.')
            continue
        table_warnings = []
        if footer['score'] < .98:
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
        rows.append([footer['text'], *([None] * (len(headers) - 1))])
        tables.append({'rows': rows, 'bbox': [crop_left + left / scale, crop_top + boundaries[0] / scale,
                                              crop_left + right / scale, crop_top + (header_bottom + row_height) / scale],
                       'warnings': list(dict.fromkeys(table_warnings))})
        tables[-1]['row_notes'] = row_notes
    drawing, revision, metadata_warnings = _metadata(tokens, image, engine)
    warnings.extend(metadata_warnings)
    return {'tables': tables, 'drawing': drawing, 'revision': revision,
            'warnings': list(dict.fromkeys(warnings))}


def _worker(input_path, page_number):
    # All imports below intentionally live in the short-lived subprocess.
    import cv2
    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr import RapidOCR
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
    pdf = pdfium.PdfDocument(str(input_path))
    try:
        if not 1 <= page_number <= len(pdf):
            return _empty('The requested scan page does not exist.')
        page = pdf[page_number - 1]
        try:
            width, height = page.get_size()
            crop_left, crop_top = width * .45, height * .30
            crop_width, crop_height = width - crop_left, height - crop_top
            if crop_width <= 0 or crop_height <= 0:
                return _empty('The scan page has invalid dimensions.')
            scale = min(1.6, 2200 / max(crop_width, crop_height),
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
    engine = RapidOCR(params={
        'Det.model_path': str(det), 'Rec.model_path': str(rec),
        'EngineConfig.onnxruntime.intra_op_num_threads': 1,
        'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        'EngineConfig.onnxruntime.enable_cpu_mem_arena': False,
        'Global.log_level': 'error', 'Global.max_side_len': 2200,
        'Det.limit_side_len': 960, 'Det.limit_type': 'max',
        'Rec.rec_batch_num': 1, 'Global.use_cls': False})
    output = engine(image)
    if output.boxes is None:
        return _empty('No readable text was found in the lower-right scan area.')
    tokens = []
    for box, text, score in zip(output.boxes, output.txts, output.scores):
        tokens.append({'text': str(text), 'score': float(score),
                       'bbox': [float(box[:, 0].min()), float(box[:, 1].min()),
                                float(box[:, 0].max()), float(box[:, 1].max())]})
    return _tables_from_tokens(image, tokens, engine, page_width=width, page_height=height,
                              scale=scale, crop_left=crop_left, crop_top=crop_top)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--worker':
        raise SystemExit(2)
    try:
        # Keep third-party progress/log text out of the structured protocol.
        with contextlib.redirect_stdout(sys.stderr):
            result = _worker(Path(sys.argv[2]), int(sys.argv[3]))
    except Exception as exc:
        result = _empty(f'Local OCR could not read this page ({type(exc).__name__}).')
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
