"""Bounded scan workers and raster-cell transcription without guessed values."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import isometric_ocr
from isometric_bom import _parse_table
from isometric_ocr import LocalOCRProvider, _tables_from_tokens
from isometric_fixtures import make_isometric_pdf


def raster_grid_tokens(*, missing_quantity=False, footer=True):
    import cv2
    import numpy as np
    image = np.full((500, 700, 3), 255, dtype=np.uint8)
    xs = [100, 140, 180, 260, 500, 570, 650]
    for x in xs:
        cv2.line(image, (x, 320), (x, 410), (0, 0, 0), 1)
    for y in [320, 350, 380, 410, 440]:
        cv2.line(image, (100, y), (650, y), (0, 0, 0), 1)
    cv2.line(image, (100, 410), (100, 440), (0, 0, 0), 1)
    cv2.line(image, (650, 410), (650, 440), (0, 0, 0), 1)
    headers = ['ITEM', 'QTY', 'TAS PART #', 'DESCRIPTION', 'LENGTH', 'MATERIAL']
    rows = [['2', '' if missing_quantity else '1', '000456', 'PIPE CARBON STEEL', '163/4"', 'A53B'],
            ['1', '2', '000123', 'WELDNECK FLANGE', '', 'A105']]
    tokens = []
    for row_number, row in enumerate([*rows, headers]):
        center_y = 335 + row_number * 30
        for column, text in enumerate(row):
            if not text:
                continue
            center_x = (xs[column] + xs[column + 1]) / 2
            half_width = min((xs[column + 1] - xs[column]) / 2 - 3, max(5, len(text) * 2))
            tokens.append({'text': text, 'score': .99,
                           'bbox': [center_x - half_width, center_y - 7, center_x + half_width, center_y + 7]})
    if footer:
        tokens.append({'text': '"TEST-200-SPOOL-01" QTY. SHOWN FOR ONE (1); ONE (1) REQ\'D',
                       'score': .99, 'bbox': [110, 418, 640, 433]})
    return image, tokens


def test_module_import_does_not_load_ocr_models_or_numeric_runtimes():
    script = ('import sys; import isometric_ocr; '
              'assert not any(name in sys.modules for name in '
              '["rapidocr", "onnxruntime", "numpy", "cv2", "pypdfium2"])')
    subprocess.run([sys.executable, '-c', script], check=True,
                   cwd=str(Path(isometric_ocr.__file__).parent))


def test_measured_session_options_reduce_graph_memory_without_relaxing_watchdog():
    import onnxruntime as ort
    options = isometric_ocr._onnx_session_options()
    assert options.graph_optimization_level == ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
    assert not options.enable_cpu_mem_arena
    assert options.enable_mem_pattern
    assert options.intra_op_num_threads == options.inter_op_num_threads == 1
    assert isometric_ocr.MIN_WORKER_BUDGET_KIB == 288 * 1024
    assert isometric_ocr.MAX_WORKER_RSS_KIB == 350 * 1024
    assert isometric_ocr.MAX_SERVICE_RSS_KIB == 512 * 1024
    assert isometric_ocr.MEMORY_RESERVE_KIB == 64 * 1024


def test_grid_geometry_preserves_missing_quantity_and_flags_collapsed_fraction():
    image, tokens = raster_grid_tokens(missing_quantity=True)
    page = _tables_from_tokens(image, tokens)
    assert len(page['tables']) == 1
    candidate, error = _parse_table(page['tables'][0], 1, 'TEST-200', 'A', 'ocr')
    assert error is None
    assert candidate['spool_number'] == 'TEST-200-SPOOL-01'
    assert len(candidate['lines']) == 2
    pipe = candidate['lines'][1]
    assert pipe['quantity'] is None
    assert pipe['part_number'] == '000456'
    assert pipe['length'] == '163/4"'
    assert any('quantity (blank)' in error for error in candidate['validation_errors'])
    assert 'lost a space' in pipe['notes']
    assert any('lost a space' in warning for warning in candidate['warnings'])
    assert candidate['review_required']


def test_raster_table_without_unique_spool_footer_produces_no_candidate():
    image, tokens = raster_grid_tokens(footer=False)
    result = _tables_from_tokens(image, tokens)
    assert result['tables'] == []
    assert any('spool-number footer' in warning for warning in result['warnings'])


def test_whole_page_crop_mode_preserves_unlabeled_table_and_top_header():
    image, tokens = raster_grid_tokens(footer=False)
    # Flip only the table's row positions to put the same observed heading at
    # the top; text values and column geometry stay literal source evidence.
    image = image[310:420, 90:660].copy()
    adjusted = []
    for token in tokens:
        x0, y0, x1, y1 = token['bbox']
        center = (y0 + y1) / 2
        shift = -60 if center > 380 else 30
        adjusted.append({**token, 'bbox': [x0 - 90, y0 + shift - 310, x1 - 90, y1 + shift - 310]})
    result = _tables_from_tokens(image, adjusted, allow_standalone=True)
    assert len(result['tables']) == 1
    candidate, error = _parse_table(result['tables'][0], 1, '', '', 'ocr')
    assert error is None and candidate['spool_number'] == ''
    assert len(candidate['lines']) == 2
    assert [row['part_number'] for row in candidate['lines']] == ['000123', '000456']
    assert candidate['review_required']


def test_item_header_ocr_box_crossing_left_rule_keeps_observed_grid_cells():
    image, tokens = raster_grid_tokens()
    item_header = next(token for token in tokens if token['text'] == 'ITEM')
    item_header['bbox'][0] = 98  # Real OCR may overlap the printed rule at x=100.
    result = _tables_from_tokens(image, tokens, allow_standalone=True)
    assert len(result['tables']) == 1
    candidate, error = _parse_table(result['tables'][0], 1, '', '', 'ocr')
    assert error is None
    assert [(row['item'], row['quantity'], row['part_number']) for row in candidate['lines']] == [
        ('1', 2, '000123'), ('2', 1, '000456')]


def test_thumbnail_geometry_distinguishes_pipe_view_from_bom_only_template(tmp_path):
    path = tmp_path / 'drawing.pdf'
    table_boxes = [[610, 570, 1180, 714]]
    path.write_bytes(make_isometric_pdf([{'number': 'TEST-100-SPOOL-01'}], include_assembly=False))
    assert isometric_ocr._scan_geometry(path, 1, table_boxes)
    path.write_bytes(make_isometric_pdf([{'number': 'TEST-100-SPOOL-01'}],
        include_assembly=False, include_geometry=False))
    assert not isometric_ocr._scan_geometry(path, 1, table_boxes)


def test_page_fallback_restores_detector_after_cell_recognition_changes_engine_mode():
    import numpy as np
    image = np.full((40, 40, 3), 255, dtype=np.uint8)
    image[12:22, 17:20] = 0
    class StatefulEngine:
        detection = True
        def __call__(self, image, **kwargs):
            self.detection = kwargs.get('use_det', self.detection)
            if not self.detection:
                return SimpleNamespace(txts=['1'], scores=[.99])
            return SimpleNamespace(boxes=None)
    engine = StatefulEngine()
    assert isometric_ocr._recognize_cell(engine, image, (0, 0, 40, 40))[0] == '1'
    assert not engine.detection
    result = isometric_ocr._read_scan(engine, (image, 40, 40, 1, 0, 0), allow_standalone=True)
    assert engine.detection
    assert result['tables'] == []


def test_page_budget_and_busy_gate_do_not_start_a_worker(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('OCR worker must not start')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    with LocalOCRProvider(max_pages=0) as provider:
        result = provider(b'input', 1, 100, 100)
        assert 'limited to 0' in result['warnings'][0]
    isometric_ocr._WORKER_GATE.acquire()
    try:
        with LocalOCRProvider() as provider:
            result = provider(b'input', 1, 100, 100)
            assert 'Another drawing scan' in result['warnings'][0]
    finally:
        isometric_ocr._WORKER_GATE.release()


def test_timeout_kills_child_releases_gate_and_removes_temporary_source(monkeypatch):
    class Child:
        pid = 123456789
        returncode = None

        def __init__(self, args, **kwargs):
            self.input_path = Path(args[-2])
            assert self.input_path.read_bytes() == b'private drawing bytes'

        def communicate(self, timeout=None):
            if self.returncode is None:
                time.sleep(.02)
                raise subprocess.TimeoutExpired('ocr-worker', timeout)
            return b'', b''

        def kill(self):
            self.returncode = -9

        def poll(self):
            return self.returncode

    children = []
    def start(args, **kwargs):
        child = Child(args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(subprocess, 'Popen', start)
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: object())
    monkeypatch.setattr(isometric_ocr, '_resident_kib', lambda pid: 64 * 1024 if pid == os.getpid() else 0)
    with LocalOCRProvider(page_timeout=.1) as provider:
        result = provider(b'private drawing bytes', 1, 100, 100)
        assert 'time limit' in result['warnings'][0]
        assert children[0].returncode == -9
        input_path = children[0].input_path
        assert input_path.is_file()
    assert not input_path.exists()
    assert isometric_ocr._WORKER_GATE.acquire(blocking=False)
    isometric_ocr._WORKER_GATE.release()


def test_memory_limit_kills_worker_without_returning_partial_rows(monkeypatch):
    class Child:
        pid = 123456789
        returncode = None
        def __init__(self, *args, **kwargs): pass
        def communicate(self, timeout=None):
            if self.returncode is None:
                raise subprocess.TimeoutExpired('ocr-worker', timeout)
            return b'', b''
        def kill(self): self.returncode = -9
        def poll(self): return self.returncode
    monkeypatch.setattr(subprocess, 'Popen', Child)
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: object())
    monkeypatch.setattr(isometric_ocr, '_resident_kib', lambda pid: 64 * 1024 if pid == os.getpid() else isometric_ocr.MAX_WORKER_RSS_KIB + 1)
    with LocalOCRProvider() as provider:
        result = provider(b'drawing', 1, 100, 100)
    assert result['tables'] == []
    assert 'memory limit' in result['warnings'][0]


def test_large_parent_upload_reduces_ocr_budget_before_starting_child(monkeypatch):
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: object())
    monkeypatch.setattr(isometric_ocr, '_resident_kib', lambda pid: 200 * 1024)
    def forbidden(*args, **kwargs):
        raise AssertionError('Large parent leaves too little safe OCR memory')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    with LocalOCRProvider() as provider:
        result = provider(b'large upload', 1, 100, 100)
    assert result['tables'] == []
    assert 'Not enough memory' in result['warnings'][0]


def test_image_encoder_shares_ocr_gate_and_checks_input_and_parent_memory(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('An image converter must not start without resources')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    isometric_ocr._WORKER_GATE.acquire()
    try:
        with pytest.raises(isometric_ocr.ImageNormalizationError) as failure:
            isometric_ocr.normalize_image_pdf(b'private image')
        assert failure.value.status_code == 429
    finally:
        isometric_ocr._WORKER_GATE.release()
    monkeypatch.setattr(isometric_ocr, 'MAX_IMAGE_INPUT_BYTES', 5)
    with pytest.raises(isometric_ocr.ImageNormalizationError) as failure:
        isometric_ocr.normalize_image_pdf(b'oversized')
    assert failure.value.status_code == 413
    monkeypatch.setattr(isometric_ocr, '_resident_kib', lambda pid: 420 * 1024)
    with pytest.raises(isometric_ocr.ImageNormalizationError) as failure:
        isometric_ocr.normalize_image_pdf(b'scan')
    assert failure.value.status_code == 413 and 'memory' in str(failure.value)
    assert isometric_ocr._WORKER_GATE.acquire(blocking=False)
    isometric_ocr._WORKER_GATE.release()


@pytest.mark.parametrize('failure_mode', ['timeout', 'memory', 'oversize', 'worker_failure', 'launch_failure'])
def test_image_encoder_failure_kills_child_releases_shared_gate_and_removes_files(monkeypatch, failure_mode):
    paths, children = [], []
    class Child:
        pid = 123456789
        returncode = None
        def communicate(self, timeout=None):
            if self.returncode is not None:
                return b'', b''
            if failure_mode in ('timeout', 'memory'):
                time.sleep(.02)
                raise subprocess.TimeoutExpired('image-pdf', timeout)
            if failure_mode == 'worker_failure':
                self.returncode = 1
                return b'', b''
            paths[1].write_bytes(b'12345678901')
            self.returncode = 0
            return b'{"ok":true}', b''
        def kill(self): self.returncode = -9
        def poll(self): return self.returncode
    def start(args, **kwargs):
        assert args[-3] == '--image-pdf'
        paths.extend([Path(args[-2]), Path(args[-1])])
        assert paths[0].read_bytes() == b'private image'
        if failure_mode == 'launch_failure':
            raise OSError('Synthetic process failure')
        child = Child()
        children.append(child)
        return child
    monkeypatch.setattr(subprocess, 'Popen', start)
    monkeypatch.setattr(isometric_ocr, 'MAX_IMAGE_SECONDS', .04)
    monkeypatch.setattr(isometric_ocr, 'MAX_IMAGE_PDF_BYTES', 10)
    monkeypatch.setattr(isometric_ocr, '_resident_kib', lambda pid:
        64 * 1024 if pid == os.getpid() else isometric_ocr.MAX_WORKER_RSS_KIB + 1 if failure_mode == 'memory' else 0)
    with pytest.raises(isometric_ocr.ImageNormalizationError) as failure:
        isometric_ocr.normalize_image_pdf(b'private image')
    assert failure.value.status_code == (413 if failure_mode in ('memory', 'oversize') else 415)
    assert paths and not paths[0].parent.exists()
    if failure_mode in ('timeout', 'memory'):
        assert children[0].returncode == -9
    assert isometric_ocr._WORKER_GATE.acquire(blocking=False)
    isometric_ocr._WORKER_GATE.release()


def test_image_worker_bounds_pixels_and_pdf_output_before_expensive_or_oversize_work(monkeypatch, tmp_path):
    import socket
    from PIL import Image
    monkeypatch.setattr(socket, 'create_connection', socket.create_connection)
    monkeypatch.setattr(socket.socket, 'connect', socket.socket.connect)
    source = tmp_path / 'scan.png'
    with Image.new('RGB', (8, 8), 'white') as image:
        image.save(source, 'PNG')
    monkeypatch.setattr(isometric_ocr, 'MAX_IMAGE_PIXELS', 60)
    with pytest.raises(isometric_ocr.ImageNormalizationError) as failure:
        isometric_ocr._image_pdf_worker(source, tmp_path / 'page.pdf')
    assert failure.value.status_code == 400
    monkeypatch.setattr(isometric_ocr, 'MAX_IMAGE_PIXELS', 64)
    monkeypatch.setattr(isometric_ocr, 'MAX_IMAGE_PDF_BYTES', 20)
    with pytest.raises(isometric_ocr.ImageNormalizationError) as failure:
        isometric_ocr._image_pdf_worker(source, tmp_path / 'page.pdf')
    assert failure.value.status_code == 413
    assert (tmp_path / 'page.pdf').stat().st_size <= 20
