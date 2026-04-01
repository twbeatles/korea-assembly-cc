from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import ui.main_window_persistence as persistence_mod
import ui.main_window_pipeline as pipeline_mod
from core.config import Config
from core.models import SubtitleEntry

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


class _FakeEvent:
    def __init__(self) -> None:
        self.accepted = False
        self.ignored = False

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


class _FakeTrayIcon:
    def isVisible(self) -> bool:
        return False


class _FakeTimer:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _FakeSettings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value


class _ImmediateQueue:
    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def put(self, item: tuple[str, object]) -> None:
        msg_type, payload = item
        MainWindow._handle_message(self.owner, msg_type, payload)


class _FakeRun:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.breaks: list[object] = []

    def add_break(self, break_type: object) -> None:
        self.breaks.append(break_type)


class _FakeParagraph:
    def __init__(self) -> None:
        self.runs: list[_FakeRun] = []

    def add_run(self, text: str = "") -> _FakeRun:
        run = _FakeRun(text)
        self.runs.append(run)
        return run


def _build_persistence_window() -> Any:
    win = MainWindow.__new__(MainWindow)
    win.db = None
    win.start_time = None
    win._capture_source_url = "https://assembly.example/live"
    win._capture_source_committee = "행정안전위원회"
    win._get_current_url = lambda: "https://assembly.example/ui"
    win._autodetect_tag = lambda _url: "행정안전위원회"
    return win


def _build_loaded_session_window() -> Any:
    win = MainWindow.__new__(MainWindow)
    win.subtitles = []
    win.url_combo = SimpleNamespace(setCurrentText=lambda _text: None)
    win._capture_source_headless = False
    win._capture_source_realtime = False
    win._set_capture_source_metadata = lambda *args, **kwargs: None
    win._replace_subtitles_and_refresh = lambda subtitles, **_kwargs: setattr(
        win, "subtitles", list(subtitles)
    )
    win._add_to_history = lambda *_args, **_kwargs: None
    win.current_url = ""
    win._focus_loaded_session_result = lambda *_args, **_kwargs: None
    win._set_status = lambda *_args, **_kwargs: None
    win._show_toast = lambda *_args, **_kwargs: None
    win._session_dirty = False
    return win


def test_write_session_snapshot_records_recovery_state(tmp_path, monkeypatch):
    win = _build_persistence_window()
    recovery_file = tmp_path / "recovery.json"
    monkeypatch.setattr(Config, "RECOVERY_STATE_FILE", str(recovery_file), raising=False)

    session_file = tmp_path / "session.json"
    info = MainWindow._write_session_snapshot(
        win,
        str(session_file),
        [SubtitleEntry("복구 대상 자막")],
        include_db=False,
    )

    assert info["path"] == str(session_file)
    recovery_state = json.loads(recovery_file.read_text(encoding="utf-8"))
    assert recovery_state["path"] == str(session_file.resolve())
    assert recovery_state["snapshot_type"] == "session"
    assert recovery_state["url"] == "https://assembly.example/live"
    assert recovery_state["committee_name"] == "행정안전위원회"


def test_prompt_session_recovery_starts_mark_dirty_load(tmp_path, monkeypatch):
    session_file = tmp_path / "recover.json"
    session_file.write_text(
        json.dumps(
            {
                "version": Config.VERSION,
                "created": "2026-04-01T09:00:00",
                "url": "https://assembly.example/recover",
                "committee_name": "운영위",
                "subtitles": [{"text": "복구 자막", "timestamp": "2026-04-01T09:00:00"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    recovery_file = tmp_path / "recovery.json"
    recovery_file.write_text(
        json.dumps(
            {
                "path": str(session_file.resolve()),
                "snapshot_type": "backup",
                "created_at": "2026-04-01T09:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Config, "RECOVERY_STATE_FILE", str(recovery_file), raising=False)
    monkeypatch.setattr(
        persistence_mod.QMessageBox,
        "question",
        lambda *_args, **_kwargs: persistence_mod.QMessageBox.StandardButton.Yes,
    )

    started: list[tuple[str, bool, bool]] = []
    win = MainWindow.__new__(MainWindow)
    win._startup_recovery_prompted = False
    win._session_load_in_progress = False
    win.is_running = False
    win._start_session_load_from_path = lambda path, **kwargs: started.append(
        (path, kwargs.get("mark_dirty", False), kwargs.get("recovery", False))
    ) or True

    MainWindow._prompt_session_recovery_if_available(win)

    assert started == [(str(session_file.resolve()), True, True)]


def test_complete_loaded_recovery_marks_session_dirty():
    win = _build_loaded_session_window()
    payload = {
        "version": Config.VERSION,
        "subtitles": [SubtitleEntry("복구된 자막")],
        "mark_dirty": True,
        "recovery": True,
    }

    assert MainWindow._complete_loaded_session(win, payload) is True
    assert win._session_dirty is True


def test_close_event_exit_save_uses_json_and_db_and_clears_recovery(monkeypatch, tmp_path):
    win = MainWindow.__new__(MainWindow)
    win.minimize_to_tray = False
    win.tray_icon = _FakeTrayIcon()
    win.is_running = False
    win._has_dirty_session = lambda: True
    win._build_prepared_entries_snapshot = lambda: [SubtitleEntry("종료 전 자막")]
    win._clear_session_dirty = lambda: None
    captured: dict[str, object] = {}
    win._write_session_snapshot = lambda path, entries, include_db=True: captured.update(
        {"path": path, "count": len(entries), "include_db": include_db}
    ) or {"db_error": "db failed"}
    win._begin_background_shutdown = lambda: captured.setdefault("shutdown", True)
    win._wait_active_background_threads = lambda timeout: captured.setdefault(
        "wait_timeout", timeout
    )
    win._clear_recovery_state = lambda: captured.setdefault("recovery_cleared", True)
    win.settings = _FakeSettings()
    win.saveGeometry = lambda: b"geometry"
    win.saveState = lambda: b"state"
    win.queue_timer = _FakeTimer()
    win.stats_timer = _FakeTimer()
    win.backup_timer = _FakeTimer()
    win.realtime_file = None
    win._take_current_driver = lambda: None
    win._cleanup_detached_drivers_with_timeout = lambda timeout=0.0: captured.setdefault(
        "driver_cleanup_timeout", timeout
    )
    win.db = None

    warnings: list[str] = []
    monkeypatch.setattr(
        mw_mod.QMessageBox,
        "question",
        lambda *_args, **_kwargs: mw_mod.QMessageBox.StandardButton.Save,
    )
    monkeypatch.setattr(
        mw_mod.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(tmp_path / "closing-session.json"), "JSON (*.json)"),
    )
    monkeypatch.setattr(
        mw_mod.QMessageBox,
        "warning",
        lambda *_args, **kwargs: warnings.append(str(kwargs.get("text") or _args[2])),
    )

    event = _FakeEvent()
    MainWindow.closeEvent(win, event)

    assert captured["include_db"] is True
    assert captured["recovery_cleared"] is True
    assert event.accepted is True
    assert warnings and "DB 저장은 실패" in warnings[0]


def test_clean_newlines_uses_prepared_snapshot_and_applies_result(monkeypatch):
    prepared_entry = SubtitleEntry("정리 전 준비 스냅샷")
    current_entry = SubtitleEntry("현재 화면 자막")
    replaced: list[list[SubtitleEntry]] = []
    captured_inputs: list[list[SubtitleEntry]] = []
    dirty_marks: list[bool] = []

    win = MainWindow.__new__(MainWindow)
    win.is_running = False
    win._is_runtime_mutation_blocked = lambda _action: False
    win._is_background_shutdown_active = lambda: False
    win._reflow_in_progress = False
    win._is_stopping = False
    win.subtitles = [current_entry]
    win._build_prepared_entries_snapshot = lambda: [prepared_entry]
    win._replace_subtitles_and_refresh = lambda subtitles: replaced.append(list(subtitles))
    win._mark_session_dirty = lambda: dirty_marks.append(True)
    win._set_status = lambda *_args, **_kwargs: None
    win._show_toast = lambda *_args, **_kwargs: None
    win.message_queue = _ImmediateQueue(win)
    win._start_background_thread = lambda target, _name: target() or True

    monkeypatch.setattr(
        persistence_mod.QMessageBox,
        "question",
        lambda *_args, **_kwargs: persistence_mod.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        persistence_mod.utils,
        "reflow_subtitles",
        lambda entries: captured_inputs.append(list(entries)) or [SubtitleEntry("정리 완료")],
    )

    MainWindow._clean_newlines(win)

    assert captured_inputs == [[prepared_entry]]
    assert [entry.text for entry in replaced[0]] == ["정리 완료"]
    assert dirty_marks == [True]
    assert win._reflow_in_progress is False


def test_add_docx_multiline_text_inserts_line_break_runs():
    win = MainWindow.__new__(MainWindow)
    paragraph = _FakeParagraph()
    break_types = SimpleNamespace(LINE="LINE")

    MainWindow._add_docx_multiline_text(win, paragraph, "첫째 줄\n둘째 줄", break_types)

    assert [run.text for run in paragraph.runs] == ["첫째 줄", "", "둘째 줄"]
    assert paragraph.runs[1].breaks == ["LINE"]
