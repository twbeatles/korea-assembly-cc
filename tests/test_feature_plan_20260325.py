from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from typing import Any

import pytest
from PyQt6 import QtGui
from PyQt6.QtGui import QTextCharFormat, QTextCursor

import ui.main_window_database as database_mod
import ui.main_window_persistence as persistence_mod
import ui.main_window_pipeline as pipeline_mod
import ui.main_window_ui as ui_mod
import ui.main_window_view as view_mod
from core.config import Config
from core.models import SubtitleEntry
from core.subtitle_pipeline import create_empty_capture_state

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _UrlComboStub:
    def __init__(self) -> None:
        self.current_text = ""

    def setCurrentText(self, text: str) -> None:
        self.current_text = text


class _AcceptingDialog:
    def __init__(self) -> None:
        self.accepted = False

    def accept(self) -> None:
        self.accepted = True


class _FakeAction:
    def __init__(self, checked: bool = False) -> None:
        self._checked = checked

    def setCheckable(self, _checkable: bool) -> None:
        return None

    def setChecked(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _FakeCheckBox:
    def __init__(self, checked: bool = False) -> None:
        self._checked = checked

    def setChecked(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _FakeFrame:
    def __init__(self) -> None:
        self._visible = False

    def show(self) -> None:
        self._visible = True

    def hide(self) -> None:
        self._visible = False

    def isVisible(self) -> bool:
        return self._visible


class _FakeLabel:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def setText(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class _FakeLineEdit:
    def __init__(self) -> None:
        self._text = ""

    def setText(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def setFocus(self) -> None:
        return None

    def selectAll(self) -> None:
        return None


class _FakeScrollBar:
    def __init__(self) -> None:
        self._value = 0
        self._maximum = 0

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        self._value = value

    def maximum(self) -> int:
        return self._maximum

    def blockSignals(self, _blocked: bool) -> None:
        return None


class _FakeTextEdit:
    def __init__(self) -> None:
        self._document: Any = QtGui.QTextDocument()
        self._cursor = QTextCursor(self._document)
        self._scrollbar = _FakeScrollBar()

    def verticalScrollBar(self) -> _FakeScrollBar:
        return self._scrollbar

    def textCursor(self) -> QTextCursor:
        return QTextCursor(self._cursor)

    def setTextCursor(self, cursor: QTextCursor) -> None:
        self._cursor = QTextCursor(cursor)

    def document(self) -> Any:
        return self._document

    def clear(self) -> None:
        self._document.clear()
        self._cursor = QTextCursor(self._document)

    def ensureCursorVisible(self) -> None:
        return None

    def moveCursor(self, operation: QTextCursor.MoveOperation) -> None:
        cursor = QTextCursor(self._cursor)
        cursor.movePosition(operation)
        self._cursor = cursor


class _CloneCountingEntry(SubtitleEntry):
    clone_calls = 0

    def clone(self) -> SubtitleEntry:
        type(self).clone_calls += 1
        return super().clone()


def _build_runtime_window() -> tuple[Any, list[str]]:
    win = MainWindow.__new__(MainWindow)
    entries = [SubtitleEntry("기존 자막", datetime(2026, 3, 25, 9, 0, 0))]
    win.subtitle_lock = threading.Lock()
    win.subtitles = entries
    win.capture_state = create_empty_capture_state()
    win.capture_state.entries = entries
    win.is_running = True
    win._session_load_in_progress = False
    win._is_background_shutdown_active = lambda: False

    toasts: list[str] = []
    win._show_toast = lambda message, *_args, **_kwargs: toasts.append(str(message))
    return win, toasts


def _build_session_window() -> tuple[Any, list[tuple[str, str]], list[tuple[int, str]]]:
    win = MainWindow.__new__(MainWindow)
    win.subtitles = []
    win.url_combo = _UrlComboStub()
    win.search_matches = []
    win.search_idx = 0
    win._search_focus_entry_index = None
    win._pending_search_focus_query = ""

    history: list[tuple[str, str]] = []
    focus_calls: list[tuple[int, str]] = []

    def replace(
        new_subtitles: list[SubtitleEntry],
        keep_history_from_subtitles: bool | None = None,
    ) -> None:
        win.subtitles = list(new_subtitles)

    win._replace_subtitles_and_refresh = replace
    win._add_to_history = lambda url, committee="": history.append((url, committee))
    win._focus_loaded_session_result = (
        lambda entry_index, query="": focus_calls.append((entry_index, query))
    )
    win._set_status = lambda *_args, **_kwargs: None
    win._show_toast = lambda *_args, **_kwargs: None
    return win, history, focus_calls


def _build_search_window() -> Any:
    win = MainWindow.__new__(MainWindow)
    win.subtitle_lock = threading.Lock()
    win.subtitles = []
    win._keyword_pattern = None
    win._keywords_lower_set = set()
    win._normal_fmt = QTextCharFormat()
    win._timestamp_fmt = QTextCharFormat()
    win._highlight_fmt = QTextCharFormat()
    win.subtitle_text = _FakeTextEdit()
    win.search_frame = _FakeFrame()
    win.search_input = _FakeLineEdit()
    win.search_count = _FakeLabel("")
    win.search_matches = []
    win.search_idx = 0
    win._search_focus_entry_index = None
    win._pending_search_focus_query = ""
    win._show_toast = lambda *_args, **_kwargs: None
    win._is_auto_clean_newlines_enabled = lambda: True
    win._last_rendered_count = 0
    win._last_rendered_last_text = ""
    win._last_render_offset = 0
    win._last_render_show_ts = None
    win._last_render_chunk_specs = []
    win._rendered_entry_text_spans = {}
    win._last_printed_ts = None
    win._user_scrolled_up = False

    timestamp_action = _FakeAction()
    timestamp_action.setCheckable(True)
    timestamp_action.setChecked(False)
    win.timestamp_action = timestamp_action

    auto_scroll_check = _FakeCheckBox()
    auto_scroll_check.setChecked(False)
    win.auto_scroll_check = auto_scroll_check
    return win


def test_runtime_mutation_guards_preserve_subtitles_and_capture_state(monkeypatch):
    win, toasts = _build_runtime_window()
    original_entries = win.subtitles

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("guarded action should not reach dialog/file picker")

    monkeypatch.setattr(
        persistence_mod.QFileDialog,
        "getOpenFileName",
        _unexpected,
    )
    monkeypatch.setattr(persistence_mod.QMessageBox, "question", _unexpected)
    monkeypatch.setattr(view_mod.QMessageBox, "question", _unexpected)
    monkeypatch.setattr(database_mod, "QDialog", _unexpected)

    MainWindow._load_session(win)
    MainWindow._clean_newlines(win)
    MainWindow._clear_subtitles(win)
    MainWindow._clear_text(win)
    MainWindow._edit_subtitle(win)
    MainWindow._delete_subtitle(win)
    MainWindow._show_merge_dialog(win)

    assert win.subtitles is original_entries
    assert win.capture_state.entries is original_entries
    assert len(toasts) == 7
    assert all("먼저 중지하세요" in message for message in toasts)


def test_search_spans_full_subtitle_list_and_restores_tail_render():
    win = _build_search_window()
    start = datetime(2026, 3, 25, 9, 0, 0)
    target_index = 40

    win.subtitles = [
        SubtitleEntry(
            "검색 대상 키워드가 있는 문장"
            if index == target_index
            else f"일반 문장 {index}",
            start + timedelta(seconds=index),
        )
        for index in range(Config.MAX_RENDER_ENTRIES + 120)
    ]

    win.search_frame.show()
    win.search_input.setText("키워드")
    MainWindow._do_search(win)

    assert len(win.search_matches) == 1
    assert win.search_matches[0].entry_index == target_index
    assert win._last_render_offset == 0
    assert target_index in win._rendered_entry_text_spans
    assert win.search_count.text() == "1/1"
    assert win.subtitle_text.textCursor().selectedText() == "키워드"

    MainWindow._hide_search(win)

    assert win.search_count.text() == ""
    assert win._last_render_offset == len(win.subtitles) - Config.MAX_RENDER_ENTRIES
    assert target_index not in win._rendered_entry_text_spans


def test_render_subtitles_clones_only_visible_window(monkeypatch):
    win = _build_search_window()
    start = datetime(2026, 3, 25, 9, 0, 0)
    _CloneCountingEntry.clone_calls = 0

    monkeypatch.setattr(mw_mod.Config, "MAX_RENDER_ENTRIES", 10)

    win.subtitles = [
        _CloneCountingEntry(f"문장 {index}", start + timedelta(seconds=index))
        for index in range(100)
    ]

    MainWindow._render_subtitles(win)

    assert _CloneCountingEntry.clone_calls == 10
    assert win._last_render_offset == 90


def test_complete_loaded_session_cancels_on_version_mismatch(monkeypatch):
    win, history, focus_calls = _build_session_window()
    payload = {
        "version": "0.0.0",
        "url": "https://assembly.example/session",
        "committee_name": "행정안전위원회",
        "subtitles": [SubtitleEntry("로드 자막", datetime(2026, 3, 25, 10, 0, 0))],
    }

    monkeypatch.setattr(
        pipeline_mod.QMessageBox,
        "question",
        lambda *_args, **_kwargs: pipeline_mod.QMessageBox.StandardButton.No,
    )

    assert MainWindow._complete_loaded_session(win, payload) is False
    assert payload["_cancelled"] is True
    assert win.subtitles == []
    assert history == []
    assert focus_calls == []


def test_complete_loaded_session_restores_url_and_focuses_sequence(monkeypatch):
    win, history, focus_calls = _build_session_window()
    loaded_entries = [
        SubtitleEntry("첫 문장", datetime(2026, 3, 25, 10, 0, 0)),
        SubtitleEntry("특정 검색어가 있는 둘째 문장", datetime(2026, 3, 25, 10, 0, 1)),
    ]
    payload = {
        "version": "0.0.0",
        "url": "https://assembly.example/session",
        "committee_name": "행정안전위원회",
        "created_at": "2026-03-25T10:00:00",
        "subtitles": loaded_entries,
        "skipped": 1,
        "highlight_sequence": 1,
        "highlight_query": "검색어",
    }

    monkeypatch.setattr(
        pipeline_mod.QMessageBox,
        "question",
        lambda *_args, **_kwargs: pipeline_mod.QMessageBox.StandardButton.Yes,
    )

    assert MainWindow._complete_loaded_session(win, payload) is True
    assert [entry.text for entry in win.subtitles] == [entry.text for entry in loaded_entries]
    assert win.url_combo.current_text == "https://assembly.example/session"
    assert history == [("https://assembly.example/session", "행정안전위원회")]
    assert focus_calls == [(1, "검색어")]


def test_complete_loaded_session_preserves_highlight_sequence_zero(monkeypatch):
    win, history, focus_calls = _build_session_window()
    payload = {
        "version": Config.VERSION,
        "url": "https://assembly.example/session",
        "committee_name": "행정안전위원회",
        "subtitles": [SubtitleEntry("첫 문장", datetime(2026, 3, 25, 10, 0, 0))],
        "highlight_sequence": 0,
        "highlight_query": "첫",
    }

    assert MainWindow._complete_loaded_session(win, payload) is True
    assert history == [("https://assembly.example/session", "행정안전위원회")]
    assert focus_calls == [(0, "첫")]


def _assert_db_load_task_result_uses_common_handler(
    task_name: str,
    context: dict[str, Any] | None,
) -> None:
    win = MainWindow.__new__(MainWindow)
    handled_payloads: list[dict[str, Any]] = []
    busy_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    history_dialog = _AcceptingDialog()

    win._complete_loaded_session = (
        lambda payload: handled_payloads.append(payload) or True
    )
    win._set_db_history_dialog_busy = (
        lambda *args, **kwargs: busy_calls.append((args, kwargs))
    )
    win._db_history_dialog_state = {"dialog": history_dialog}

    result_payload = {"subtitles": []}
    MainWindow._handle_db_task_result(win, task_name, result_payload, context)

    assert handled_payloads == [result_payload]
    if task_name == "db_history_load_selected":
        assert busy_calls == [((False,), {})]
        assert history_dialog.accepted is True
    else:
        assert context is not None and context["dialog"].accepted is True


def test_db_history_load_task_result_uses_common_loaded_session_handler():
    _assert_db_load_task_result_uses_common_handler(
        "db_history_load_selected",
        None,
    )


def test_db_search_load_task_result_uses_common_loaded_session_handler():
    _assert_db_load_task_result_uses_common_handler(
        "db_search_load_selected",
        {"dialog": _AcceptingDialog()},
    )


def test_preset_export_import_round_trip_preserves_committee_and_custom(
    tmp_path, monkeypatch
):
    export_path = tmp_path / "presets.json"

    source = MainWindow.__new__(MainWindow)
    source.committee_presets = {"행정안전위원회": "https://example.com/committee"}
    source.custom_presets = {"내 프리셋": "https://example.com/custom"}
    source._show_toast = lambda *_args, **_kwargs: None

    monkeypatch.setattr(
        ui_mod.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(export_path), ""),
    )
    MainWindow._export_presets(source)

    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["committee"] == source.committee_presets
    assert exported["custom"] == source.custom_presets

    target = MainWindow.__new__(MainWindow)
    target.committee_presets = {"행정안전위원회": "https://old.example.com"}
    target.custom_presets = {"내 프리셋": "https://old.example.com/custom"}
    target._show_toast = lambda *_args, **_kwargs: None
    target._save_committee_presets = lambda: None
    target._build_preset_menu = lambda: None

    monkeypatch.setattr(
        ui_mod.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(export_path), ""),
    )
    MainWindow._import_presets(target)

    assert target.committee_presets == source.committee_presets
    assert target.custom_presets == source.custom_presets


def test_export_stats_overwrites_existing_report_atomically(tmp_path, monkeypatch):
    target = tmp_path / "stats.txt"
    current_entries = [
        SubtitleEntry("예전전용토큰", datetime(2026, 3, 25, 11, 0, 0)),
    ]

    win = MainWindow.__new__(MainWindow)
    win.subtitle_lock = threading.Lock()
    win.subtitles = list(current_entries)
    win.keywords = ["문장"]
    win._build_prepared_entries_snapshot = lambda: list(current_entries)
    win._save_in_background = lambda save_func, path, *_args: save_func(path)

    monkeypatch.setattr(
        persistence_mod.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(target), ""),
    )

    MainWindow._export_stats(win)
    first_raw = target.read_text(encoding="utf-8")
    assert "총 문장 수: 1개" in first_raw
    assert "예전전용토큰" in first_raw

    current_entries = [
        SubtitleEntry("매우 긴 새 문장입니다", datetime(2026, 3, 25, 12, 0, 0)),
        SubtitleEntry("둘째 문장", datetime(2026, 3, 25, 12, 0, 1)),
    ]
    win.subtitles = list(current_entries)

    MainWindow._export_stats(win)
    second_raw = target.read_text(encoding="utf-8")

    assert "총 문장 수: 2개" in second_raw
    assert "매우 긴 새 문장입니다" in second_raw
    assert "예전전용토큰" not in second_raw
