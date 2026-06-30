from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

import pytest

from core.models import SubtitleEntry
from core.subtitle_pipeline import create_empty_capture_state

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


def _build_reconnect_window() -> Any:
    win = MainWindow.__new__(MainWindow)
    win.subtitle_lock = threading.Lock()
    win.subtitles = []
    win.capture_state = create_empty_capture_state()
    win.capture_state.entries = win.subtitles
    win._confirmed_compact = ""
    win._trailing_suffix = ""
    win._suffix_length = 50
    win._last_raw_text = ""
    win._last_processed_raw = ""
    win._preview_desync_count = 0
    win._preview_ambiguous_skip_count = 0
    win._last_good_raw_compact = ""
    win._preview_resync_threshold = 10
    win._preview_ambiguous_resync_threshold = 6
    win._normalize_subtitle_text_for_option = lambda text: str(text or "")
    win._mark_session_dirty = lambda: None
    win._invalidate_destructive_undo = lambda: None
    win._schedule_initial_recovery_snapshot_if_needed = lambda _entries: False
    win._schedule_ui_refresh = lambda **_kwargs: None
    win._check_keyword_alert = lambda _text: None
    win._mark_runtime_tail_dirty = lambda: None
    win._maybe_schedule_runtime_segment_flush = lambda: None
    win._write_realtime_line = lambda _line: None
    win._should_merge_entry = lambda _last, _new, _now: False
    win._cached_total_chars = 0
    win._cached_total_words = 0
    return win


def test_reconnected_resync_prevents_duplicate_append_for_same_probe_text():
    win = _build_reconnect_window()
    now = datetime(2026, 6, 30, 12, 0, 0)
    text = "재연결 이전에 확정된 발언 텍스트입니다 충분히 길게 작성합니다"
    entry = SubtitleEntry(text, now)
    entry.start_time = now
    entry.end_time = now
    win.subtitles.append(entry)
    win.capture_state.entries = win.subtitles

    MainWindow._soft_resync(win)
    MainWindow._on_capture_reconnected(win, {"attempt": 1})

    prepared = MainWindow._prepare_preview_raw(win, text)
    assert prepared is None

    before_count = len(win.subtitles)
    if prepared:
        MainWindow._process_raw_text(win, prepared)
    assert len(win.subtitles) == before_count == 1


def test_reconnected_allows_delta_after_resync_when_probe_grows():
    win = _build_reconnect_window()
    now = datetime(2026, 6, 30, 12, 0, 0)
    base = "재연결 이전에 확정된 발언 텍스트입니다 충분히 길게 작성합니다"
    entry = SubtitleEntry(base, now)
    entry.start_time = now
    entry.end_time = now
    win.subtitles.append(entry)
    win.capture_state.entries = win.subtitles

    MainWindow._soft_resync(win)
    MainWindow._on_capture_reconnected(win, {"attempt": 1})

    grown = f"{base} 이어지는 추가 발언"
    prepared = MainWindow._prepare_preview_raw(win, grown)
    assert prepared is not None

    MainWindow._process_raw_text(win, prepared)
    assert len(win.subtitles) == 2
    assert win.subtitles[-1].text.endswith("이어지는 추가 발언")