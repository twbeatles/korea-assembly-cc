# -*- coding: utf-8 -*-
"""코어 알고리즘 단위 테스트

MainWindow의 실제 메서드를 직접 호출해 rfind 추출/소프트 리셋을 검증한다.
"""

import threading

import pytest

from core.models import SubtitleEntry
from core.utils import compact_subtitle_text

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


def _build_minimal_window():
    win = MainWindow.__new__(MainWindow)
    win.subtitles = []
    win.subtitle_lock = threading.Lock()
    win._confirmed_compact = ""
    win._trailing_suffix = ""
    win._suffix_length = 50
    return win


def test_rfind_prevents_over_extraction():
    win = _build_minimal_window()
    win._trailing_suffix = compact_subtitle_text("위원장 감사합니다")

    raw = "기존 텍스트 위원장 감사합니다 중간 텍스트 위원장 감사합니다 새로운 발언"
    raw_compact = compact_subtitle_text(raw)
    result = MainWindow._extract_new_part(win, raw, raw_compact)

    result_compact = compact_subtitle_text(result)
    assert "새로운발언" in result_compact
    assert "중간텍스트" not in result_compact


def test_rfind_no_new_content():
    win = _build_minimal_window()
    win._trailing_suffix = compact_subtitle_text("마지막 텍스트입니다")

    raw = "이전 내용 마지막 텍스트입니다"
    raw_compact = compact_subtitle_text(raw)
    result = MainWindow._extract_new_part(win, raw, raw_compact)

    assert result == ""


def test_rfind_suffix_not_found():
    win = _build_minimal_window()
    win._trailing_suffix = "전혀다른텍스트"

    raw = "완전히 새로운 문장입니다"
    raw_compact = compact_subtitle_text(raw)
    result = MainWindow._extract_new_part(win, raw, raw_compact)

    assert result == raw


def test_rfind_empty_suffix():
    win = _build_minimal_window()
    win._trailing_suffix = ""

    raw = "첫 번째 자막"
    raw_compact = compact_subtitle_text(raw)
    result = MainWindow._extract_new_part(win, raw, raw_compact)

    assert result == raw


def test_soft_resync_preserves_recent():
    win = _build_minimal_window()
    win.subtitles = [
        SubtitleEntry("첫 번째 자막입니다"),
        SubtitleEntry("두 번째 자막 텍스트가 길게 이어집니다"),
        SubtitleEntry("세 번째 자막은 더 길어서 충분한 텍스트를 제공합니다"),
    ]

    MainWindow._soft_resync(win)

    assert win._trailing_suffix != ""
    assert win._confirmed_compact != ""

    third_compact = compact_subtitle_text("세 번째 자막은 더 길어서 충분한 텍스트를 제공합니다")
    assert third_compact in win._confirmed_compact


def test_soft_resync_fallback_empty():
    win = _build_minimal_window()
    win.subtitles = []
    win._confirmed_compact = "stale"
    win._trailing_suffix = "stale"

    MainWindow._soft_resync(win)

    assert win._confirmed_compact == ""
    assert win._trailing_suffix == ""


def test_soft_resync_prevents_duplicate():
    win = _build_minimal_window()
    recent_text = "이전에 확정된 자막입니다 충분히 긴 텍스트를 포함하여 suffix가 제대로 만들어지도록 합니다"
    win.subtitles = [SubtitleEntry(recent_text)]

    MainWindow._soft_resync(win)

    raw_compact = compact_subtitle_text(recent_text)
    result = MainWindow._extract_new_part(win, recent_text, raw_compact)

    assert result == "" or compact_subtitle_text(result) == ""
