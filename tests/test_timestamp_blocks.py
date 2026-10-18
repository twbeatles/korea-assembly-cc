# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta

from core.config import Config
from core.hwpx_export import build_hwpx_lines
from core.models import SubtitleEntry
from core.timestamp_blocks import (
    DisplayLayout,
    build_plain_text,
    format_interval_label,
    iter_display_rows,
    join_block_text,
    normalize_block_interval,
)
from ui.main_window import MainWindow

BASE = datetime(2026, 10, 18, 14, 0, 0)


def _rows(*items: tuple[int, str]) -> list[tuple[datetime, str]]:
    return [(BASE + timedelta(seconds=offset), text) for offset, text in items]


def test_merge_mode_joins_entries_within_timestamp_block() -> None:
    rows = _rows((0, "위원장님,"), (3, "질의하겠습니다."), (20, "예산안에\n대해"), (61, "답변드리겠습니다."))
    result = list(iter_display_rows(rows, DisplayLayout(merge_blocks=True, interval_seconds=60)))

    assert [(row.text, row.entry_count) for row in result] == [
        ("위원장님, 질의하겠습니다. 예산안에 대해", 3),
        ("답변드리겠습니다.", 1),
    ]
    assert all(row.print_timestamp for row in result)
    assert result[0].timestamp == BASE
    assert result[1].timestamp == BASE + timedelta(seconds=61)


def test_merge_mode_respects_interval_and_punctuation_join() -> None:
    rows = _rows((0, "첫 문장"), (25, "."), (31, "다음"))

    thirty = list(iter_display_rows(rows, DisplayLayout(True, 30)))
    two_min = list(iter_display_rows(rows, DisplayLayout(True, 120)))

    assert [row.text for row in thirty] == ["첫 문장.", "다음"]
    assert [row.text for row in two_min] == ["첫 문장. 다음"]
    assert join_block_text("(", "괄호") == "(괄호"


def test_normal_mode_keeps_entry_rows_and_prints_ts_per_block() -> None:
    rows = _rows((0, "a"), (10, "b"), (30, "c"), (31, "  "))
    result = list(iter_display_rows(rows, DisplayLayout(False, 30)))

    assert [(row.text, row.print_timestamp) for row in result] == [
        ("a", True),
        ("b", False),
        ("c", True),
    ]


def test_interval_normalization_and_labels() -> None:
    assert normalize_block_interval("120") == 120
    assert normalize_block_interval(7) == Config.TIMESTAMP_BLOCK_INTERVAL_DEFAULT
    assert normalize_block_interval(None) == Config.TIMESTAMP_BLOCK_INTERVAL_DEFAULT
    assert format_interval_label(30) == "30초"
    assert format_interval_label(300) == "5분"


def test_build_plain_text_with_timestamps() -> None:
    rows = _rows((0, "가"), (5, "나"), (70, "다"))
    text = build_plain_text(rows, DisplayLayout(True, 60), with_timestamps=True)
    assert text == "[14:00:00] 가 나\n[14:01:10] 다"


def test_hwpx_lines_merge_layout_counts_entries() -> None:
    rows = _rows((0, "가"), (5, "나"), (70, "다"))
    lines = build_hwpx_lines(rows, BASE, layout=DisplayLayout(True, 60))

    assert "[14:00:00] 가 나" in lines
    assert "[14:01:10] 다" in lines
    assert lines[-1] == "총 3문장, 4자"


def _render_window(merge: bool, interval: int = 60, show_ts: bool = True):
    from PySide6.QtGui import QTextCharFormat
    from PySide6.QtWidgets import QApplication, QTextEdit

    if QApplication.instance() is None:
        QApplication([])
    win = MainWindow.__new__(MainWindow)
    win.subtitle_text = QTextEdit()
    win._keyword_pattern = None
    win._keywords_lower_set = set()
    win._normal_fmt = QTextCharFormat()
    win._timestamp_fmt = QTextCharFormat()
    win._highlight_fmt = QTextCharFormat()
    win.search_matches = []
    win.search_idx = 0
    win._search_focus_entry_index = None
    win._last_rendered_count = 0
    win._last_rendered_last_text = ""
    win._last_render_offset = 0
    win._last_render_show_ts = None
    win._last_render_chunk_specs = []
    win._rendered_entry_text_spans = {}
    win._last_printed_ts = None
    win._user_scrolled_up = False
    win.auto_clean_newlines_enabled = merge
    win.timestamp_block_interval = interval

    from PySide6.QtGui import QAction

    timestamp_action = QAction()
    timestamp_action.setCheckable(True)
    timestamp_action.setChecked(show_ts)
    win.timestamp_action = timestamp_action
    win.subtitles = [
        SubtitleEntry("위원장님,", BASE),
        SubtitleEntry("질의하겠습니다.", BASE + timedelta(seconds=4)),
        SubtitleEntry("예산안에 대해", BASE + timedelta(seconds=30)),
        SubtitleEntry("답변드리겠습니다.", BASE + timedelta(seconds=75)),
    ]
    return win


def test_render_merges_entries_into_timestamp_paragraphs() -> None:
    win = _render_window(merge=True)
    MainWindow._render_subtitles(win)

    assert win.subtitle_text.toPlainText() == (
        "[14:00:00] 위원장님, 질의하겠습니다. 예산안에 대해\n"
        "[14:01:15] 답변드리겠습니다."
    )
    # 엔트리별 span 은 유지되어 검색/포커스가 계속 동작한다.
    start, end = win._rendered_entry_text_spans[1]
    assert win.subtitle_text.toPlainText()[start:end] == "질의하겠습니다."


def test_render_merge_without_timestamps_keeps_paragraph_boundaries() -> None:
    win = _render_window(merge=True, show_ts=False)
    MainWindow._render_subtitles(win)

    assert win.subtitle_text.toPlainText() == (
        "위원장님, 질의하겠습니다. 예산안에 대해\n답변드리겠습니다."
    )


def test_render_incremental_append_and_layout_change_rerender() -> None:
    win = _render_window(merge=True)
    MainWindow._render_subtitles(win)

    win.subtitles.append(SubtitleEntry("이상입니다.", BASE + timedelta(seconds=80)))
    MainWindow._render_subtitles(win)
    assert win.subtitle_text.toPlainText().endswith(
        "[14:01:15] 답변드리겠습니다. 이상입니다."
    )

    win.auto_clean_newlines_enabled = False
    MainWindow._render_subtitles(win)
    assert win.subtitle_text.toPlainText() == (
        "[14:00:00] 위원장님,\n질의하겠습니다.\n예산안에 대해\n"
        "[14:01:15] 답변드리겠습니다.\n이상입니다."
    )


def test_display_layout_snapshot_reads_window_options() -> None:
    win = MainWindow.__new__(MainWindow)
    win.auto_clean_newlines_enabled = False
    win.timestamp_block_interval = 300
    layout = MainWindow._get_display_layout(win)
    assert layout == DisplayLayout(merge_blocks=False, interval_seconds=300)
