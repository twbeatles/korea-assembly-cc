from __future__ import annotations

import threading
from typing import Any

import pytest

from core.models import SubtitleEntry
from core.subtitle_pipeline import (
    PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD,
    PREVIEW_RESYNC_THRESHOLD,
)
from core.utils import compact_subtitle_text

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


def _build_preview_window() -> Any:
    win = MainWindow.__new__(MainWindow)
    win.subtitles = []
    win.subtitle_lock = threading.Lock()
    win._confirmed_compact = ""
    win._trailing_suffix = ""
    win._suffix_length = 50
    win._last_raw_text = ""
    win._preview_desync_count = 0
    win._preview_ambiguous_skip_count = 0
    win._last_good_raw_compact = ""
    win._preview_resync_threshold = PREVIEW_RESYNC_THRESHOLD
    win._preview_ambiguous_resync_threshold = PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD
    win._normalize_subtitle_text_for_option = lambda text: str(text or "")
    return win


def test_prepare_preview_raw_returns_none_for_empty_input():
    win = _build_preview_window()
    assert MainWindow._prepare_preview_raw(win, None) is None
    assert MainWindow._prepare_preview_raw(win, "   ") is None


def test_prepare_preview_raw_without_suffix_returns_full_normalized_text():
    win = _build_preview_window()
    prepared = MainWindow._prepare_preview_raw(win, "  첫 자막입니다  ")
    assert prepared == "첫 자막입니다"
    assert win._preview_desync_count == 0


def test_prepare_preview_raw_suffix_match_returns_full_raw_for_process_stage():
    win = _build_preview_window()
    base = "이전에 확정된 자막 텍스트입니다"
    win._trailing_suffix = compact_subtitle_text(base)
    raw = f"{base} 새로운 발언"
    prepared = MainWindow._prepare_preview_raw(win, raw)
    assert prepared == raw


def test_prepare_preview_raw_desync_below_threshold_returns_none():
    win = _build_preview_window()
    win._trailing_suffix = compact_subtitle_text("확정된 꼬리 텍스트")
    win._last_raw_text = "완전히 다른 이전 raw"
    soft_resync_calls: list[bool] = []
    win._soft_resync = lambda: soft_resync_calls.append(True)

    prepared = MainWindow._prepare_preview_raw(win, "전혀 다른 새 문장")

    assert prepared is None
    assert win._preview_desync_count == 1
    assert soft_resync_calls == []


def test_prepare_preview_raw_desync_at_threshold_triggers_soft_resync():
    win = _build_preview_window()
    win._trailing_suffix = compact_subtitle_text("확정된 꼬리 텍스트")
    win._preview_desync_count = PREVIEW_RESYNC_THRESHOLD - 1
    soft_resync_calls: list[bool] = []
    win._soft_resync = lambda: soft_resync_calls.append(True)

    prepared = MainWindow._prepare_preview_raw(win, "전혀 다른 새 문장")

    assert prepared == "전혀 다른 새 문장"
    assert soft_resync_calls == [True]
    assert win._preview_desync_count == 0


def test_prepare_preview_raw_ambiguous_suffix_skips_until_threshold():
    win = _build_preview_window()
    repeated = "감사합니다"
    filler = "가" * 260
    win._trailing_suffix = compact_subtitle_text(repeated)
    win._preview_ambiguous_skip_count = PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD - 1
    soft_resync_calls: list[bool] = []
    win._soft_resync = lambda: soft_resync_calls.append(True)

    raw = f"{repeated} {filler} {repeated} {filler} 추가 발언"
    prepared = MainWindow._prepare_preview_raw(win, raw)

    assert prepared == raw
    assert soft_resync_calls == [True]
    assert win._preview_ambiguous_skip_count == 0


def test_prepare_preview_raw_uses_stream_delta_fallback():
    win = _build_preview_window()
    win._trailing_suffix = compact_subtitle_text("다른꼬리텍스트")
    win._last_raw_text = "이전 확정 델타"
    prepared = MainWindow._prepare_preview_raw(win, "이전 확정 델타 추가")
    assert prepared == "추가"


def test_prepare_preview_raw_respects_auto_clean_newlines_option():
    win = _build_preview_window()
    win._normalize_subtitle_text_for_option = lambda text: " ".join(
        str(text or "").split()
    )
    prepared = MainWindow._prepare_preview_raw(win, "줄바꿈\n정리\n테스트")
    assert prepared == "줄바꿈 정리 테스트"