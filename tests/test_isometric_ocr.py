"""Bounded scan workers and raster-cell transcription without guessed values."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

import isometric_ocr
from isometric_bom import _parse_table
from isometric_ocr import LocalOCRProvider, _tables_from_tokens


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
