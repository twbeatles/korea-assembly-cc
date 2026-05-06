from __future__ import annotations

from datetime import datetime, timedelta
import threading
from typing import Any

import pytest

from core.live_capture import create_empty_live_capture_ledger
from core.models import SubtitleEntry
from core.subtitle_pipeline import (
    PipelineSourceMeta,
    apply_preview,
    create_empty_capture_state,
)

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


class _FakeResetTimer:
    def __init__(self) -> None:
        self.active = False

    def start(self, _msec: int) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    def isActive(self) -> bool:
        return self.active


def _build_pipeline_window() -> Any:
    win = MainWindow.__new__(MainWindow)
    win.is_running = True
    win.subtitle_lock = threading.Lock()
    win.capture_state = create_empty_capture_state()
    win.live_capture_ledger = create_empty_live_capture_ledger()
    win.subtitles = win.capture_state.entries
    win._pending_subtitle_reset_timer = _FakeResetTimer()
    win._pending_subtitle_reset_source = ""
    win._ensure_capture_runtime_state = lambda: None
    win._normalize_subtitle_text_for_option = lambda text: str(text or "")
    win._current_capture_settings = lambda: {}
    win._sync_capture_state_entries = lambda force_refresh=False: None
    win._apply_capture_pipeline_refresh = lambda **_kwargs: None
    win._mark_session_dirty = lambda: None
    win._invalidate_destructive_undo = lambda: None
    win._schedule_initial_recovery_snapshot_if_needed = lambda _entries: False
    win._build_prepared_entries_snapshot = lambda: list(win.capture_state.entries)
    return win


def test_persistent_entries_snapshot_clones_prepared_entries():
    win = _build_pipeline_window()
    entry = SubtitleEntry("저장 전", datetime(2026, 5, 6, 9, 0, 0))
    win.capture_state.entries.append(entry)

    snapshot = MainWindow._build_persistent_entries_snapshot(win)
    entry.update_text("저장 후")

    assert snapshot[0] is not entry
    assert snapshot[0].text == "저장 전"


def test_pending_subtitle_reset_commits_before_structured_preview():
    win = _build_pipeline_window()
    now = datetime(2026, 4, 29, 9, 0, 0)
    previous = SubtitleEntry(
        "이전 발언",
        now - timedelta(seconds=1),
        source_node_key="row_previous",
        speaker_color="rgb(35, 124, 147)",
        speaker_channel="primary",
    )
    previous.start_time = previous.timestamp
    previous.end_time = previous.timestamp
    win.capture_state.entries.append(previous)
    win._pending_subtitle_reset_source = "observer_cleared"
    win._pending_subtitle_reset_timer.start(1000)

    changed = MainWindow._apply_structured_preview_payload(
        win,
        {
            "raw": "새 발언",
            "rows": [],
            "selector": "#viewSubtit",
            "source_mode": "container",
        },
        now=now,
    )

    assert changed is True
    assert win._pending_subtitle_reset_timer.isActive() is False
    assert [entry.text for entry in win.capture_state.entries] == ["이전 발언", "새 발언"]


def test_container_fallback_preview_does_not_merge_after_structured_entry():
    state = create_empty_capture_state()
    now = datetime(2026, 4, 29, 9, 0, 0)

    apply_preview(
        state,
        "기존 발언",
        now,
        {},
        meta=PipelineSourceMeta(
            source_node_key="row_previous",
            speaker_color="rgb(35, 124, 147)",
            speaker_channel="primary",
        ),
    )
    apply_preview(
        state,
        "fallback 새 발언",
        now + timedelta(seconds=1),
        {},
        meta=PipelineSourceMeta(source_mode="container"),
    )

    assert [entry.text for entry in state.entries] == ["기존 발언", "fallback 새 발언"]


def test_speaker_metadata_mismatch_blocks_merge():
    state = create_empty_capture_state()
    now = datetime(2026, 4, 29, 9, 0, 0)

    apply_preview(
        state,
        "첫 발언",
        now,
        {},
        meta=PipelineSourceMeta(
            speaker_color="rgb(35, 124, 147)",
            speaker_channel="primary",
        ),
    )
    apply_preview(
        state,
        "다른 발언",
        now + timedelta(seconds=1),
        {},
        meta=PipelineSourceMeta(
            speaker_color="rgb(30, 30, 30)",
            speaker_channel="secondary",
        ),
    )

    assert [entry.text for entry in state.entries] == ["첫 발언", "다른 발언"]


def test_observer_reset_classifier_trusts_only_subtitle_row_or_legacy_reset():
    win = MainWindow.__new__(MainWindow)

    legacy = MainWindow._coerce_observer_reset_event(win, "__SUBTITLE_CLEARED__")
    row_reset = MainWindow._coerce_observer_reset_event(
        win,
        {"kind": "reset", "selector": "#viewSubtit .smi_word", "previousLength": 4},
    )
    broad_reset = MainWindow._coerce_observer_reset_event(
        win,
        {"kind": "reset", "selector": "#viewSubtit", "previousLength": 4},
    )

    assert legacy is not None
    assert row_reset is not None
    assert broad_reset is not None
    assert MainWindow._is_trusted_observer_reset_event(win, legacy) is True
    assert MainWindow._is_trusted_observer_reset_event(win, row_reset) is True
    assert MainWindow._is_trusted_observer_reset_event(win, broad_reset) is False
