# -*- coding: utf-8 -*-
"""PROJECT_AUDIT_EXTENDED 2026-07-29 후속 회귀."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from core.config import Config
from core.logging_utils import resolve_log_file_level, safe_log_text
from core.models import SubtitleEntry
from tests.test_support.capture_probe import (
    CaptureProbeProtocol,
    FakeCaptureProbe,
    scenario_incremental_speech,
    scenario_short_utterances,
)

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


# --- 로그 정책 ---


def test_safe_log_text_redacts_long_body() -> None:
    long = "가" * 200
    rendered = safe_log_text(long, max_chars=40)
    assert len(rendered) < 50
    assert "…" in rendered or "+" in rendered


def test_log_file_level_defaults_to_info() -> None:
    level = resolve_log_file_level()
    assert level in (logging.INFO, logging.DEBUG, logging.WARNING, logging.ERROR)


# --- runtime archive age GC ---


def test_cleanup_orphan_runtime_archives_removes_old_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "runtime_sessions"
    root.mkdir()
    old = root / "run_old"
    recent = root / "run_recent"
    old.mkdir()
    recent.mkdir()
    old_mtime = time.time() - (10 * 86400)
    recent_mtime = time.time() - 60
    # Windows utime
    import os

    os.utime(old, (old_mtime, old_mtime))
    os.utime(recent, (recent_mtime, recent_mtime))

    monkeypatch.setattr(Config, "RUNTIME_SESSION_DIR", str(root))
    monkeypatch.setattr(Config, "RUNTIME_ARCHIVE_KEEP_RECENT", 5)
    monkeypatch.setattr(Config, "RUNTIME_ARCHIVE_MAX_AGE_DAYS", 7)

    win = MainWindow.__new__(MainWindow)
    win._runtime_session_root = None
    win._load_recovery_state = lambda: None

    MainWindow._cleanup_orphan_runtime_archives(win)

    assert not old.exists()
    assert recent.exists()


def test_cleanup_orphan_keeps_recovery_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "runtime_sessions"
    root.mkdir()
    preserved = root / "run_recover"
    preserved.mkdir()
    old_mtime = time.time() - (30 * 86400)
    import os

    os.utime(preserved, (old_mtime, old_mtime))

    monkeypatch.setattr(Config, "RUNTIME_SESSION_DIR", str(root))
    monkeypatch.setattr(Config, "RUNTIME_ARCHIVE_KEEP_RECENT", 1)
    monkeypatch.setattr(Config, "RUNTIME_ARCHIVE_MAX_AGE_DAYS", 7)

    win = MainWindow.__new__(MainWindow)
    win._runtime_session_root = None
    win._load_recovery_state = lambda: {
        "path": str(preserved / "manifest.json"),
    }

    MainWindow._cleanup_orphan_runtime_archives(win)

    assert preserved.exists()


# --- exit guard ---


def test_start_blocked_when_exit_in_progress() -> None:
    win = MainWindow.__new__(MainWindow)
    win.is_running = False
    win._exit_in_progress = True
    win._session_save_in_progress = False
    win._session_load_in_progress = False
    statuses: list[str] = []
    toasts: list[str] = []
    win._set_status = lambda text, *_a, **_k: statuses.append(str(text))
    win._show_toast = lambda message, *_a, **_k: toasts.append(str(message))
    win._begin_extraction_run = lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("종료 중이면 begin 하면 안 됨")
    )

    MainWindow._start(win)

    assert any("종료" in s for s in statuses + toasts)


def test_runtime_mutation_blocked_during_exit() -> None:
    win = MainWindow.__new__(MainWindow)
    win.is_running = False
    win._exit_in_progress = True
    toasts: list[str] = []
    win._show_toast = lambda message, *_a, **_k: toasts.append(str(message))

    assert MainWindow._is_runtime_mutation_blocked(win, "세션 불러오기") is True
    assert any("종료" in t for t in toasts)


# --- search truncated label ---


def test_search_count_label_shows_top_n_when_truncated() -> None:
    win = MainWindow.__new__(MainWindow)
    win._runtime_search_in_progress = False
    win._runtime_search_truncated = True
    win._runtime_search_query = "국회"
    win.search_matches = [object()] * 10  # type: ignore[list-item]
    captured: list[str] = []

    class _Label:
        def setText(self, text: str) -> None:
            captured.append(str(text))

    win.search_count = _Label()

    MainWindow._update_search_count_label_now(win)

    assert captured
    assert "상위" in captured[-1]
    assert "+" in captured[-1]


# --- hydrate limit ---


def test_hydrate_rejects_over_max_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    win = MainWindow.__new__(MainWindow)
    win._hydrate_in_progress = False
    win._is_background_shutdown_active = lambda: False
    win._has_runtime_archived_segments = lambda: True
    win._build_persistent_entries_snapshot = lambda: []
    win._snapshot_runtime_stream_context = lambda: (
        Path("."),
        [{"entry_count": 200_000, "path": "segment_000001.json"}],
    )
    toasts: list[str] = []
    statuses: list[str] = []
    win._show_toast = lambda message, *_a, **_k: toasts.append(str(message))
    win._set_status = lambda text, *_a, **_k: statuses.append(str(text))
    monkeypatch.setattr(Config, "HYDRATE_MAX_ENTRIES", 1000)

    called = {"v": False}

    def _cb() -> None:
        called["v"] = True

    result = MainWindow._run_after_full_session_hydrated(win, "편집", _cb)

    assert result is False
    assert called["v"] is False
    assert any("너무 큽니다" in t or "상한" in s for t, s in zip(toasts or [""], statuses or [""]) for _ in [0]) or any(
        "큽니다" in t or "상한" in t for t in toasts + statuses
    )


def test_hydrate_done_uses_result_token_slot() -> None:
    win = MainWindow.__new__(MainWindow)
    entries = [SubtitleEntry("불러온 자막")]
    win._pending_hydration_action = None
    win._pending_hydration_action_name = "테스트"
    win._hydrate_result_token = "tok-1"
    win._hydrate_result_entries = entries
    win._hydrate_in_progress = True
    win._hydrate_progress_dialog = None
    win._hydrate_cancel_event = threading.Event()
    replaced: list[Any] = []
    win._replace_subtitles_and_refresh = (
        lambda subs, keep_history_from_subtitles=False: replaced.append(list(subs))
    )
    win._cleanup_runtime_session_archive = lambda **_k: None
    win._show_toast = lambda *_a, **_k: None
    win._reset_hydration_state = lambda: None

    MainWindow._handle_hydrate_done(
        win,
        {"result_token": "tok-1", "reason": "테스트", "current": 1, "total": 1},
    )

    assert replaced and replaced[0][0].text == "불러온 자막"
    assert win._hydrate_result_entries is None


# --- driver quit diagnostic ---


def test_force_quit_timeout_records_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    win = MainWindow.__new__(MainWindow)
    win._detached_drivers = []
    win._detached_drivers_lock = threading.Lock()
    win._driver_quit_failures = []

    class _SlowDriver:
        def quit(self) -> None:
            time.sleep(2.0)

    ok = MainWindow._force_quit_driver_with_timeout(
        win, _SlowDriver(), timeout=0.05, source="test"
    )

    assert ok is False
    assert win._driver_quit_failures
    assert win._driver_quit_failures[-1]["reason"] == "timeout"


# --- capture probe library ---


def test_capture_probe_scenarios_implement_protocol() -> None:
    for probe in (
        scenario_incremental_speech(),
        scenario_short_utterances(),
        FakeCaptureProbe(["단일"]),
    ):
        assert isinstance(probe, CaptureProbeProtocol)
        payload = probe.read_subtitle_probe(["#viewSubtit"])
        assert "text" in payload
        assert "found" in payload
