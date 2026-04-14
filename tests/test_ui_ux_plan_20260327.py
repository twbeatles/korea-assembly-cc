from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

import pytest

from core.config import Config
from core.live_capture import create_empty_live_capture_ledger
from core.models import SubtitleEntry
from core.subtitle_pipeline import create_empty_capture_state
import ui.main_window_capture as capture_mod
import ui.main_window_impl.runtime_state as runtime_state_mod
import ui.main_window_ui as ui_mod
from ui.main_window_common import (
    SubtitleDialogItem,
    build_subtitle_dialog_items,
    filter_subtitle_dialog_items,
)

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


class _FakeSignal:
    def connect(self, _callback) -> None:
        return None


class _FakeFrame:
    def __init__(self, visible: bool = False) -> None:
        self._visible = visible

    def isVisible(self) -> bool:
        return self._visible

    def hide(self) -> None:
        self._visible = False


class _FakeCombo:
    def __init__(self) -> None:
        self.current_text = ""
        self.edit_text = ""
        self.current_index = -1

    def setCurrentText(self, text: str) -> None:
        self.current_text = text

    def findData(self, _value: str) -> int:
        return -1

    def setCurrentIndex(self, index: int) -> None:
        self.current_index = index

    def setEditText(self, text: str) -> None:
        self.edit_text = text


class _FakeLabel:
    def __init__(self) -> None:
        self.value = ""

    def setText(self, text: str) -> None:
        self.value = text

    def text(self) -> str:
        return self.value


class _FakeButton:
    def __init__(self) -> None:
        self.enabled = True

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class _FakeListWidget:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.enabled = True
        self.current_row = -1

    def addItem(self, text: str) -> None:
        self.items.append(text)

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def count(self) -> int:
        return len(self.items)

    def currentRow(self) -> int:
        return self.current_row

    def setCurrentRow(self, row: int) -> None:
        self.current_row = row


class _FakeLiveDialog:
    next_broadcast: dict[str, Any] | None = None
    next_result = True

    def __init__(self, _parent=None) -> None:
        self.finished = _FakeSignal()
        self.selected_broadcast = self.__class__.next_broadcast

    def deleteLater(self) -> None:
        return None

    def exec(self) -> bool:
        return bool(self.__class__.next_result)


def _build_session_window() -> tuple[Any, list[tuple[str, str]]]:
    win = MainWindow.__new__(MainWindow)
    win.subtitle_lock = threading.Lock()
    win.subtitles = []
    win.url_combo = _FakeCombo()
    win._capture_source_url = ""
    win._capture_source_committee = ""
    win._capture_source_headless = False
    win._capture_source_realtime = False
    win._session_dirty = True

    history: list[tuple[str, str]] = []

    def replace(
        new_subtitles: list[SubtitleEntry],
        keep_history_from_subtitles: bool | None = None,
    ) -> None:
        win.subtitles = list(new_subtitles)

    win._replace_subtitles_and_refresh = replace
    win._add_to_history = lambda url, committee="": history.append((url, committee))
    win._focus_loaded_session_result = lambda *_args, **_kwargs: None
    win._set_status = lambda *_args, **_kwargs: None
    win._show_toast = lambda *_args, **_kwargs: None
    return win, history


def test_add_to_history_moves_existing_url_to_mru_and_preserves_tag():
    win = MainWindow.__new__(MainWindow)
    win.url_history = {
        "https://example.com/first": "첫번째",
        "https://example.com/second": "두번째",
    }
    win.committee_presets = {}
    win._save_url_history = lambda: None
    win._refresh_url_combo = lambda: None

    MainWindow._add_to_history(win, "https://example.com/first")

    assert list(win.url_history.items()) == [
        ("https://example.com/second", "두번째"),
        ("https://example.com/first", "첫번째"),
    ]


def test_build_session_save_context_prefers_capture_snapshot_and_falls_back():
    win = MainWindow.__new__(MainWindow)
    win.start_time = time.time() - 12
    win._capture_source_url = "https://capture.example/live"
    win._capture_source_committee = "운영위"
    win._get_current_url = lambda: "https://ui.example/current"
    win._autodetect_tag = lambda _url: "행안위"

    url, committee, duration = MainWindow._build_session_save_context(win)

    assert url == "https://capture.example/live"
    assert committee == "운영위"
    assert duration >= 11

    win._capture_source_url = ""
    win._capture_source_committee = ""

    fallback_url, fallback_committee, _fallback_duration = (
        MainWindow._build_session_save_context(win)
    )

    assert fallback_url == "https://ui.example/current"
    assert fallback_committee == "행안위"


def test_resolve_live_url_from_list_uses_only_live_rows():
    win = MainWindow.__new__(MainWindow)
    win._fetch_live_list = lambda: [
        {"xcode": "AB", "xcgcd": "ENDED001", "xstat": "2"},
        {"xcode": "AB", "xcgcd": "LIVE001", "xstat": "1"},
    ]

    resolved = MainWindow._resolve_live_url_from_list(
        win,
        "https://assembly.webcast.go.kr/main/player.asp?xcode=AB",
        "AB",
    )

    assert "xcgcd=LIVE001" in resolved
    assert "ENDED001" not in resolved


def test_resolve_live_url_from_list_keeps_original_url_when_live_candidates_are_ambiguous():
    win = MainWindow.__new__(MainWindow)
    win._fetch_live_list = lambda: {
        "ok": True,
        "result": [
            {"xcode": "AB", "xcgcd": "LIVE001", "xstat": "1"},
            {"xcode": "CD", "xcgcd": "LIVE002", "xstat": "1"},
        ],
    }
    original_url = "https://assembly.webcast.go.kr/main/player.asp"

    resolved = MainWindow._resolve_live_url_from_list(win, original_url, None)

    assert resolved == original_url


def test_show_live_dialog_prompts_before_applying_non_live_selection(monkeypatch):
    win = MainWindow.__new__(MainWindow)
    win.url_combo = _FakeCombo()
    win._is_runtime_mutation_blocked = lambda _action_name: False
    win._show_toast = lambda *_args, **_kwargs: None

    history: list[tuple[str, str]] = []
    win._add_to_history = lambda url, committee="": history.append((url, committee))

    _FakeLiveDialog.next_broadcast = {
        "xcode": "AB",
        "xcgcd": "ENDED001",
        "xstat": "2",
        "xname": "종료된 방송",
    }

    prompted: list[str] = []

    def fake_question(*_args, **_kwargs):
        prompted.append("asked")
        return capture_mod.QMessageBox.StandardButton.No

    monkeypatch.setattr(capture_mod, "LiveBroadcastDialog", _FakeLiveDialog)
    monkeypatch.setattr(capture_mod.QMessageBox, "question", fake_question)

    MainWindow._show_live_dialog(win)

    assert prompted == ["asked"]
    assert history == []
    assert win.url_combo.edit_text == ""


def test_handle_escape_shortcut_closes_search_before_stopping():
    win = MainWindow.__new__(MainWindow)
    win.search_frame = _FakeFrame(True)
    win.is_running = True

    calls: list[str] = []
    win._hide_search = lambda: calls.append("hide")
    win._stop = lambda *args, **kwargs: calls.append("stop")

    MainWindow._handle_escape_shortcut(win)

    assert calls == ["hide"]

    win.search_frame = _FakeFrame(False)
    MainWindow._handle_escape_shortcut(win)

    assert calls == ["hide", "stop"]


def test_build_and_filter_subtitle_dialog_items_keep_original_indexes():
    entries = [
        SubtitleEntry("첫 줄\n자막", datetime(2026, 3, 27, 10, 0, 0)),
        SubtitleEntry("둘째 발언", datetime(2026, 3, 27, 10, 1, 5)),
    ]

    items = build_subtitle_dialog_items(
        entries,
        lambda text: str(text).replace("\n", " ").strip(),
    )
    filtered_by_text = filter_subtitle_dialog_items(items, "발언")
    filtered_by_time = filter_subtitle_dialog_items(items, "10:00:00")

    assert [item.source_index for item in items] == [0, 1]
    assert items[0].display_text.startswith("[10:00:00] 첫 줄 자막")
    assert [item.source_index for item in filtered_by_text] == [1]
    assert [item.source_index for item in filtered_by_time] == [0]


def test_complete_loaded_session_sets_capture_source_and_clears_dirty():
    win, history = _build_session_window()
    payload = {
        "version": Config.VERSION,
        "url": "https://assembly.webcast.go.kr/main/player.asp?xcode=AB&xcgcd=LIVE001",
        "committee_name": "행안위",
        "subtitles": [SubtitleEntry("불러온 자막", datetime(2026, 3, 27, 9, 0, 0))],
        "skipped": 0,
    }

    loaded = MainWindow._complete_loaded_session(win, payload)

    assert loaded is True
    assert len(win.subtitles) == 1
    assert win.url_combo.current_text == payload["url"]
    assert history == [(payload["url"], "행안위")]
    assert MainWindow._get_capture_source_url(win) == payload["url"]
    assert MainWindow._get_capture_source_committee(win) == "행안위"
    assert MainWindow._has_dirty_session(win) is False


def test_session_save_done_clears_dirty_and_reports_db_warning():
    win = MainWindow.__new__(MainWindow)
    win._is_stopping = False
    win._session_dirty = True
    win._session_save_in_progress = True

    statuses: list[tuple[str, str]] = []
    toasts: list[tuple[Any, ...]] = []
    recovery_cleared: list[bool] = []
    win._set_status = lambda message, level: statuses.append((message, level))
    win._show_toast = lambda *args, **_kwargs: toasts.append(args)
    win._clear_recovery_state = lambda: recovery_cleared.append(True)

    MainWindow._handle_message(
        win,
        "session_save_done",
        {"saved_count": 3, "db_saved": False, "db_error": "db fail"},
    )

    assert MainWindow._has_dirty_session(win) is False
    assert win._session_save_in_progress is False
    assert recovery_cleared == [True]
    assert statuses == [("세션 저장 완료 (3개)", "success")]
    assert toasts == [("세션 저장 완료 (DB 저장은 실패)", "warning", 3500)]


def test_complete_loaded_session_clears_stale_current_url_when_payload_url_blank():
    win, history = _build_session_window()
    win.current_url = "https://assembly.example/old"
    win.url_combo.current_text = "https://assembly.example/old"
    payload = {
        "version": Config.VERSION,
        "url": "",
        "committee_name": "행안위",
        "subtitles": [SubtitleEntry("불러온 자막", datetime(2026, 3, 27, 9, 0, 0))],
        "skipped": 0,
    }

    loaded = MainWindow._complete_loaded_session(win, payload)

    assert loaded is True
    assert history == []
    assert win.current_url == ""
    assert win.url_combo.current_text == ""
    assert MainWindow._get_capture_source_url(win, fallback_to_current=False) == ""


def test_structured_preview_payload_marks_dirty_only_when_commit_occurs():
    def _build_window() -> Any:
        win = MainWindow.__new__(MainWindow)
        win.capture_state = create_empty_capture_state()
        win.live_capture_ledger = create_empty_live_capture_ledger()
        win._ensure_capture_runtime_state = lambda: None
        win._normalize_subtitle_text_for_option = lambda text: str(text or "")
        win._cancel_scheduled_subtitle_reset = lambda: None
        win._current_capture_settings = lambda: {}
        win._apply_capture_pipeline_refresh = lambda **_kwargs: None
        return win

    win = _build_window()
    dirty_marks: list[bool] = []
    win._mark_session_dirty = lambda: dirty_marks.append(True)

    changed = MainWindow._apply_structured_preview_payload(
        win,
        {
            "raw": "첫 문장",
            "rows": [{"nodeKey": "row_1", "text": "첫 문장"}],
            "selector": "#viewSubtit .smi_word",
        },
    )

    assert changed is True
    assert dirty_marks == [True]
    assert [entry.text for entry in win.capture_state.entries] == ["첫 문장"]

    win = _build_window()
    dirty_marks = []
    win._mark_session_dirty = lambda: dirty_marks.append(True)

    changed = MainWindow._apply_structured_preview_payload(
        win,
        {
            "raw": "",
            "rows": [],
            "selector": "#viewSubtit .smi_word",
        },
    )

    assert changed is False
    assert dirty_marks == []
    assert win.capture_state.entries == []


def test_structured_preview_payload_schedules_initial_recovery_only_on_commit():
    def _build_window() -> Any:
        win = MainWindow.__new__(MainWindow)
        win.capture_state = create_empty_capture_state()
        win.live_capture_ledger = create_empty_live_capture_ledger()
        win._ensure_capture_runtime_state = lambda: None
        win._normalize_subtitle_text_for_option = lambda text: str(text or "")
        win._cancel_scheduled_subtitle_reset = lambda: None
        win._current_capture_settings = lambda: {}
        win._apply_capture_pipeline_refresh = lambda **_kwargs: None
        win._mark_session_dirty = lambda: None
        win._invalidate_destructive_undo = lambda: None
        return win

    win = _build_window()
    scheduled: list[list[str]] = []
    win._schedule_initial_recovery_snapshot_if_needed = (
        lambda entries: scheduled.append([entry.text for entry in entries]) or True
    )

    MainWindow._apply_structured_preview_payload(
        win,
        {
            "raw": "첫 문장",
            "rows": [{"nodeKey": "row_1", "text": "첫 문장"}],
            "selector": "#viewSubtit .smi_word",
        },
    )

    assert scheduled == [["첫 문장"]]

    win = _build_window()
    scheduled = []
    win._schedule_initial_recovery_snapshot_if_needed = (
        lambda entries: scheduled.append([entry.text for entry in entries]) or True
    )

    MainWindow._apply_structured_preview_payload(
        win,
        {
            "raw": "",
            "rows": [],
            "selector": "#viewSubtit .smi_word",
        },
    )

    assert scheduled == []


def test_restore_last_destructive_change_restores_entries_metadata_and_dirty():
    win = MainWindow.__new__(MainWindow)
    win.is_running = False
    win._session_dirty = False
    win._capture_source_url = "https://assembly.example/original"
    win._capture_source_committee = "행정안전위원회"
    win._capture_source_headless = True
    win._capture_source_realtime = False
    win.current_url = "https://assembly.example/original"
    win.url_combo = _FakeCombo()
    win._build_prepared_entries_snapshot = lambda: [SubtitleEntry("원래 자막")]
    win._show_toast = lambda *_args, **_kwargs: None
    win._mark_session_dirty = lambda: setattr(win, "_session_dirty", True)
    win._clear_session_dirty = lambda: setattr(win, "_session_dirty", False)
    win._set_capture_source_metadata = lambda url, committee, headless=False, realtime=False: (
        setattr(win, "_capture_source_url", url),
        setattr(win, "_capture_source_committee", committee),
        setattr(win, "_capture_source_headless", headless),
        setattr(win, "_capture_source_realtime", realtime),
    )

    def replace(
        new_subtitles: list[SubtitleEntry],
        keep_history_from_subtitles: bool | None = None,
    ) -> None:
        win.subtitles = list(new_subtitles)

    win._replace_subtitles_and_refresh = replace

    assert MainWindow._store_destructive_undo_snapshot(win) is True

    win.subtitles = [SubtitleEntry("변경된 자막")]
    win._capture_source_url = "https://assembly.example/changed"
    win._capture_source_committee = "예산결산특별위원회"
    win._capture_source_headless = False
    win._capture_source_realtime = True
    win.current_url = "https://assembly.example/changed"
    win._session_dirty = True

    assert MainWindow._restore_last_destructive_change(win) is True
    assert [entry.text for entry in win.subtitles] == ["원래 자막"]
    assert win._capture_source_url == "https://assembly.example/original"
    assert win._capture_source_committee == "행정안전위원회"
    assert win._capture_source_headless is True
    assert win._capture_source_realtime is False
    assert win.current_url == "https://assembly.example/original"
    assert win.url_combo.current_text == "https://assembly.example/original"
    assert win._session_dirty is False
    assert win._destructive_undo_snapshot is None


def test_keepalive_and_reset_messages_do_not_mark_dirty():
    win = MainWindow.__new__(MainWindow)
    win._is_stopping = False
    dirty_marks: list[bool] = []
    keepalive_calls: list[str] = []
    reset_calls: list[str] = []
    win._mark_session_dirty = lambda: dirty_marks.append(True)
    win._handle_keepalive = lambda raw: keepalive_calls.append(raw)
    win._schedule_deferred_subtitle_reset = lambda source: reset_calls.append(source)

    MainWindow._handle_message(win, "keepalive", "동일 자막")
    MainWindow._handle_message(win, "subtitle_reset", "observer_cleared")

    assert dirty_marks == []
    assert keepalive_calls == ["동일 자막"]
    assert reset_calls == ["observer_cleared"]


def test_append_db_history_sessions_updates_loaded_state():
    win = MainWindow.__new__(MainWindow)
    loaded_label = _FakeLabel()
    more_btn = _FakeButton()
    list_widget = _FakeListWidget()
    sessions: list[dict[str, Any]] = []
    win._db_history_dialog_state = {
        "sessions": sessions,
        "list_widget": list_widget,
        "loaded_label": loaded_label,
        "more_btn": more_btn,
        "page_size": Config.DB_HISTORY_PAGE_SIZE,
        "offset": 0,
        "has_more": True,
        "loading": True,
    }

    MainWindow._append_db_history_sessions(
        win,
        [
            {
                "id": 1,
                "created_at": "2026-03-27T09:00:00",
                "committee_name": "운영위",
                "total_subtitles": 10,
                "total_characters": 123,
            }
        ],
    )

    assert sessions[0]["id"] == 1
    assert loaded_label.text() == "현재 1개 로드됨"
    assert list_widget.count() == 1
    assert win._db_history_dialog_state["offset"] == 1
    assert win._db_history_dialog_state["has_more"] is False
    assert more_btn.enabled is False
    assert win._db_history_dialog_state["loading"] is False


def test_format_db_history_item_includes_lineage_badges():
    win = MainWindow.__new__(MainWindow)

    latest = MainWindow._format_db_history_item(
        win,
        {
            "created_at": "2026-03-27T09:00:00",
            "committee_name": "운영위",
            "total_subtitles": 10,
            "total_characters": 123,
            "is_latest_in_lineage": 1,
            "lineage_total": 2,
            "newer_versions": 0,
        },
    )
    previous = MainWindow._format_db_history_item(
        win,
        {
            "created_at": "2026-03-26T09:00:00",
            "committee_name": "운영위",
            "total_subtitles": 8,
            "total_characters": 100,
            "is_latest_in_lineage": 0,
            "lineage_total": 2,
            "newer_versions": 1,
        },
    )

    assert latest.startswith("[최신]")
    assert previous.startswith("[이전 저장본 1/1]")


def test_append_db_search_results_updates_loaded_state():
    win = MainWindow.__new__(MainWindow)
    loaded_label = _FakeLabel()
    more_btn = _FakeButton()
    list_widget = _FakeListWidget()
    results: list[dict[str, Any]] = []
    win._db_search_dialog_state = {
        "results": results,
        "list_widget": list_widget,
        "loaded_label": loaded_label,
        "more_btn": more_btn,
        "page_size": Config.DB_SEARCH_PAGE_SIZE,
        "offset": 0,
        "has_more": True,
        "loading": True,
    }

    MainWindow._append_db_search_results(
        win,
        [
            {
                "session_id": 1,
                "created_at": "2026-03-27T09:00:00",
                "committee_name": "행안위",
                "text": "검색된 자막입니다",
            }
        ],
    )

    assert results[0]["session_id"] == 1
    assert loaded_label.text() == "현재 1개 로드됨"
    assert list_widget.count() == 1
    assert win._db_search_dialog_state["offset"] == 1
    assert win._db_search_dialog_state["has_more"] is False
    assert more_btn.enabled is False
    assert win._db_search_dialog_state["loading"] is False


def test_initialize_database_state_marks_runtime_degraded_when_db_init_fails(monkeypatch):
    class _BrokenDatabase:
        def __init__(self, _db_path: str):
            raise RuntimeError("db boom")

    win = MainWindow.__new__(MainWindow)
    win._sync_runtime_action_state = lambda: None

    monkeypatch.setattr(runtime_state_mod, "DB_AVAILABLE", True)
    monkeypatch.setattr(runtime_state_mod, "DatabaseManagerClass", _BrokenDatabase)

    MainWindow._initialize_database_state(win)

    assert win.db is None
    assert win.db_available is False
    assert win.fts_available is False
    assert "db boom" in win.db_degraded_reason


def test_load_url_history_reports_user_visible_warning(monkeypatch):
    win = MainWindow.__new__(MainWindow)
    reported: list[tuple[str, dict[str, Any]]] = []
    win._report_user_visible_warning = (
        lambda message, **kwargs: reported.append((message, kwargs))
    )

    monkeypatch.setattr(ui_mod.Path, "exists", lambda self: True)
    monkeypatch.setattr(
        "builtins.open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("history boom")),
    )

    result = MainWindow._load_url_history(win)

    assert result == {}
    assert reported
    assert "URL 히스토리 로드 실패" in reported[0][0]
    assert reported[0][1]["toast"] is False


def test_save_committee_presets_reports_user_visible_warning(monkeypatch):
    win = MainWindow.__new__(MainWindow)
    win.committee_presets = {"행정안전위원회": "https://example.com"}
    win.custom_presets = {}
    reported: list[tuple[str, dict[str, Any]]] = []
    win._report_user_visible_warning = (
        lambda message, **kwargs: reported.append((message, kwargs))
    )

    monkeypatch.setattr(
        ui_mod.utils,
        "atomic_write_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("preset boom")),
    )

    MainWindow._save_committee_presets(win)

    assert reported
    assert "프리셋 저장 실패" in reported[0][0]
