# -*- coding: utf-8 -*-
"""2026-10-22 Chrome 확장 수집 정합 2차 회귀 테스트 (상태 계층).

순수 함수 규칙은 `tests/test_parity_contract.py` 의 공유 벡터가 고정하고,
여기서는 MainWindow 파이프라인 상태 계층의 stable-only commit, fallback 안정 관측,
keepalive 재관측, placeholder 차단, keepalive 접미 규칙을 확인한다.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any

import pytest

from core import utils
from core.live_capture import create_empty_live_capture_ledger
from core.models import SubtitleEntry
from core.subtitle_pipeline import (
    PipelineSourceMeta,
    apply_keepalive,
    apply_preview,
    create_empty_capture_state,
)

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow

NOW = datetime(2026, 10, 22, 10, 0, 0)


class _FakeTimer:
    def __init__(self) -> None:
        self.active = False
        self.last_msec: int | None = None

    def start(self, msec: int) -> None:
        self.active = True
        self.last_msec = msec

    def stop(self) -> None:
        self.active = False

    def isActive(self) -> bool:
        return self.active


def _build_window() -> Any:
    win = MainWindow.__new__(MainWindow)
    win.is_running = True
    win.subtitle_lock = threading.Lock()
    win.capture_state = create_empty_capture_state()
    win.live_capture_ledger = create_empty_live_capture_ledger()
    win.subtitles = win.capture_state.entries
    win._pending_subtitle_reset_timer = _FakeTimer()
    win._pending_subtitle_reset_source = ""
    win._fallback_commit_timer = _FakeTimer()
    win._fallback_commit_candidate = None
    win._fallback_commit_token = 0
    win._ensure_capture_runtime_state = lambda: None
    win._normalize_subtitle_text_for_option = lambda text: str(text or "")
    win._current_capture_settings = lambda: {}
    win._apply_capture_pipeline_refresh = lambda **_kwargs: None
    win._mark_session_dirty = lambda: None
    win._invalidate_destructive_undo = lambda: None
    win._schedule_initial_recovery_snapshot_if_needed = lambda _entries: False
    win._build_prepared_entries_snapshot = lambda: list(win.capture_state.entries)
    win._set_preview_text = lambda _text: None
    return win


def _texts(win: Any) -> list[str]:
    return [entry.text for entry in win.capture_state.entries]


def _general_row_payload(*lines: str) -> dict[str, Any]:
    # 일반 자막 `p.smi_word` 는 stable class/id 가 없어 generated key(unstable)로 읽힌다.
    return {
        "raw": " ".join(lines),
        "rows": [
            {"nodeKey": f"row_gen{index}", "text": text, "unstableKey": True}
            for index, text in enumerate(lines)
        ],
        "selector": "#viewSubtit .smi_word",
        "source_mode": "smi-window",
    }


def test_unstable_rows_are_not_committed_until_fallback_is_stable() -> None:
    win = _build_window()
    payload = _general_row_payload("본회의를 개의하겠습니다")

    MainWindow._apply_structured_preview_payload(win, payload, now=NOW)
    assert _texts(win) == []
    assert win._fallback_commit_timer.isActive()
    assert win.live_capture_ledger.capture_mode == "fallback"

    MainWindow._apply_structured_preview_payload(
        win, payload, now=NOW + timedelta(milliseconds=150)
    )
    assert _texts(win) == ["본회의를 개의하겠습니다"]
    assert win._fallback_commit_candidate is None


def test_stable_rows_commit_immediately_and_clear_pending_fallback() -> None:
    win = _build_window()
    MainWindow._apply_structured_preview_payload(
        win, _general_row_payload("흔들리는 미리보기"), now=NOW
    )
    assert win._fallback_commit_candidate is not None

    MainWindow._apply_structured_preview_payload(
        win,
        {
            "raw": "위원장 발언입니다",
            "rows": [
                {
                    "nodeKey": "class:stxt7",
                    "text": "위원장 발언입니다",
                    "speakerColor": "rgb(35, 124, 147)",
                    "speakerChannel": "primary",
                    "unstableKey": False,
                }
            ],
            "selector": "#viewSubtit .smi_word",
            "source_mode": "smi-window",
        },
        now=NOW + timedelta(milliseconds=50),
    )
    assert _texts(win) == ["위원장 발언입니다"]
    assert win._fallback_commit_candidate is None


def test_fallback_candidate_commits_after_stable_window() -> None:
    win = _build_window()
    payload = {"raw": "새 발언입니다", "rows": [], "selector": "#viewSubtit", "source_mode": "container"}
    MainWindow._apply_structured_preview_payload(win, dict(payload), now=NOW)
    assert win._fallback_commit_timer.last_msec == 400

    MainWindow._commit_fallback_candidate(
        win, int(win._fallback_commit_candidate["token"]), NOW + timedelta(milliseconds=400)
    )
    assert _texts(win) == ["새 발언입니다"]


def test_keepalive_counts_as_fallback_reobservation() -> None:
    win = _build_window()
    MainWindow._apply_structured_preview_payload(
        win,
        {"raw": "같은 화면 텍스트", "rows": [], "selector": "#viewSubtit", "source_mode": "container"},
        now=NOW,
    )
    assert _texts(win) == []

    MainWindow._handle_keepalive(win, "같은 화면 텍스트")
    assert _texts(win) == ["같은 화면 텍스트"]


def test_loading_placeholder_is_never_committed() -> None:
    win = _build_window()
    payload = {"raw": "로딩중..", "rows": [], "selector": "#viewSubtit", "source_mode": "container"}
    MainWindow._apply_structured_preview_payload(win, dict(payload), now=NOW)
    MainWindow._apply_structured_preview_payload(
        win, dict(payload), now=NOW + timedelta(milliseconds=500)
    )
    assert _texts(win) == []


def test_year_text_is_kept_in_committed_entries() -> None:
    state = create_empty_capture_state()
    apply_preview(state, "2026년 예산안을 상정합니다", NOW, {})
    assert [entry.text for entry in state.entries] == ["2026년 예산안을 상정합니다"]
    assert utils.clean_text_display("2026년 예산") == "2026년 예산"


def test_speaker_boundary_marks_new_entry_as_speaker_changed() -> None:
    state = create_empty_capture_state()
    apply_preview(
        state,
        "첫 발언",
        NOW,
        {},
        meta=PipelineSourceMeta(speaker_color="rgb(35, 124, 147)", speaker_channel="primary"),
    )
    apply_preview(
        state,
        "두번째 화자 발언",
        NOW + timedelta(milliseconds=500),
        {},
        meta=PipelineSourceMeta(speaker_color="rgb(30, 30, 30)", speaker_channel="secondary"),
    )
    assert [entry.speaker_changed for entry in state.entries] == [False, True]


def test_keepalive_extends_when_structured_preview_ends_with_last_entry() -> None:
    state = create_empty_capture_state()
    entry = SubtitleEntry("마지막 줄입니다", NOW)
    entry.start_time = NOW
    entry.end_time = NOW
    state.entries.append(entry)

    later = NOW + timedelta(seconds=2)
    result = apply_keepalive(state, "앞줄 이전 발언 마지막 줄입니다", later)
    assert result.changed is True
    assert entry.end_time == later

    mismatch = apply_keepalive(state, "마지막 줄입니다 그리고 새 줄", later + timedelta(seconds=1))
    assert mismatch.changed is False
    assert entry.end_time == later
