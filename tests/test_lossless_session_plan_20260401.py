from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import ui.main_window_persistence as persistence_mod
import ui.main_window_pipeline as pipeline_mod
import ui.main_window_impl.runtime_lifecycle as runtime_lifecycle_mod
from core.config import Config
from core.models import SubtitleEntry
from ui.main_window_common import MainWindowMessageQueue

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

    def put_nowait(self, item: tuple[str, object]) -> None:
        self.put(item)


class _CloneTrackingEntry(SubtitleEntry):
    __slots__ = ("clone_calls",)

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.clone_calls = 0

    def clone(self) -> SubtitleEntry:
        self.clone_calls += 1
        return super().clone()


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


def test_confirm_dirty_session_action_save_uses_json_and_db_snapshot(monkeypatch, tmp_path):
    win = MainWindow.__new__(MainWindow)
    win._session_dirty = True
    win._build_prepared_entries_snapshot = lambda: [SubtitleEntry("저장 전 자막")]
    captured: dict[str, object] = {}
    win._write_session_snapshot = lambda path, entries, include_db=True: captured.update(
        {"path": path, "count": len(entries), "include_db": include_db}
    ) or {"db_error": ""}
    win._clear_session_dirty = lambda: setattr(win, "_session_dirty", False)
    win._clear_recovery_state = lambda: captured.setdefault("recovery_cleared", True)

    monkeypatch.setattr(
        persistence_mod.QMessageBox,
        "question",
        lambda *_args, **_kwargs: persistence_mod.QMessageBox.StandardButton.Save,
    )
    monkeypatch.setattr(
        persistence_mod.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(tmp_path / "confirm-save.json"), "JSON (*.json)"),
    )

    assert MainWindow._confirm_dirty_session_action(win, "세션 불러오기") is True
    assert captured["include_db"] is True
    assert captured["count"] == 1
    assert captured["recovery_cleared"] is True
    assert win._session_dirty is False


def test_prompt_session_recovery_no_keeps_recovery_state_file(tmp_path, monkeypatch):
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
    original_state = {
        "path": str(session_file.resolve()),
        "snapshot_type": "runtime_manifest",
        "created_at": "2026-04-01T09:00:00",
    }
    recovery_file.write_text(
        json.dumps(original_state, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(Config, "RECOVERY_STATE_FILE", str(recovery_file), raising=False)
    monkeypatch.setattr(
        persistence_mod.QMessageBox,
        "question",
        lambda *_args, **_kwargs: persistence_mod.QMessageBox.StandardButton.No,
    )

    started: list[str] = []
    win = MainWindow.__new__(MainWindow)
    win._startup_recovery_prompted = False
    win._session_load_in_progress = False
    win.is_running = False
    win._start_session_load_from_path = lambda path, **_kwargs: started.append(path) or True

    MainWindow._prompt_session_recovery_if_available(win)

    assert started == []
    assert recovery_file.exists() is True
    assert json.loads(recovery_file.read_text(encoding="utf-8")) == original_state


def test_complete_loaded_recovery_keeps_recovery_state_pointer():
    win = _build_loaded_session_window()
    recovery_cleared: list[bool] = []
    win._clear_recovery_state = lambda: recovery_cleared.append(True)

    payload = {
        "version": Config.VERSION,
        "subtitles": [SubtitleEntry("복구된 자막")],
        "mark_dirty": True,
        "recovery": True,
    }

    assert MainWindow._complete_loaded_session(win, payload) is True
    assert win._session_dirty is True
    assert recovery_cleared == []


def test_load_session_stops_when_dirty_confirmation_is_cancelled(monkeypatch):
    win = MainWindow.__new__(MainWindow)
    win.is_running = False
    win._is_runtime_mutation_blocked = lambda _action: False
    win._confirm_dirty_session_action = lambda _action: False

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("dirty confirmation이 취소되면 파일 선택기로 넘어가면 안 됩니다.")

    monkeypatch.setattr(persistence_mod.QFileDialog, "getOpenFileName", _unexpected)

    MainWindow._load_session(win)


def test_close_event_uses_dirty_confirmation_and_waits_for_background_shutdown():
    win = MainWindow.__new__(MainWindow)
    win.minimize_to_tray = False
    win.tray_icon = _FakeTrayIcon()
    win.is_running = False
    win._session_save_in_progress = False
    captured: dict[str, object] = {}
    win._confirm_dirty_session_action = (
        lambda action: captured.setdefault("dirty_action", action) or True
    )
    win._begin_background_shutdown = lambda: captured.setdefault("shutdown", True)
    win._wait_for_background_threads_during_exit = lambda: captured.setdefault("waited", True)
    win._clear_recovery_state = lambda: captured.setdefault("recovery_cleared", True)
    win._set_status = lambda text, level="info": captured.setdefault("status", (text, level))
    win._update_tray_status = lambda text: captured.setdefault("tray_status", text)
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

    event = _FakeEvent()
    MainWindow.closeEvent(win, event)

    assert captured["dirty_action"] == "종료"
    assert captured["waited"] is True
    assert captured["recovery_cleared"] is True
    assert event.accepted is True


def test_close_event_waits_for_session_save_completion_before_dirty_confirmation():
    win = MainWindow.__new__(MainWindow)
    win.minimize_to_tray = False
    win.tray_icon = _FakeTrayIcon()
    win.is_running = False
    win._session_save_in_progress = True
    order: list[str] = []

    def wait_for_background() -> None:
        order.append("wait")
        win._session_save_in_progress = False

    win._wait_for_background_threads_during_exit = wait_for_background
    win._process_message_queue = lambda: order.append("process")
    win._confirm_dirty_session_action = lambda _action: order.append("dirty") or True
    win._begin_background_shutdown = lambda: order.append("shutdown")
    win._clear_recovery_state = lambda: order.append("recovery")
    win._set_status = lambda *_args, **_kwargs: None
    win._update_tray_status = lambda *_args, **_kwargs: None
    win.settings = _FakeSettings()
    win.saveGeometry = lambda: b"geometry"
    win.saveState = lambda: b"state"
    win.queue_timer = _FakeTimer()
    win.stats_timer = _FakeTimer()
    win.backup_timer = _FakeTimer()
    win.realtime_file = None
    win._take_current_driver = lambda: None
    win._cleanup_detached_drivers_with_timeout = lambda timeout=0.0: None
    win.db = None

    event = _FakeEvent()
    MainWindow.closeEvent(win, event)

    assert order[:3] == ["wait", "process", "dirty"]
    assert event.accepted is True


def test_wait_for_background_threads_during_exit_blocks_until_complete(monkeypatch):
    win = MainWindow.__new__(MainWindow)
    win._show_toast = lambda *_args, **_kwargs: None
    process_calls: list[bool] = []
    win._process_message_queue = lambda: process_calls.append(True)
    win._active_background_threads_lock = threading.Lock()
    completed: list[bool] = []

    def _background_work() -> None:
        time.sleep(0.15)
        completed.append(True)

    worker = threading.Thread(target=_background_work, daemon=False, name="BackgroundWaitTest")
    worker.start()
    win._active_background_threads = {worker}

    class _FakeApp:
        def processEvents(self) -> None:
            return None

    monkeypatch.setattr(
        runtime_lifecycle_mod,
        "QApplication",
        SimpleNamespace(instance=lambda: _FakeApp()),
    )

    started_at = time.perf_counter()
    MainWindow._wait_for_background_threads_during_exit(win)
    elapsed = time.perf_counter() - started_at

    assert completed == [True]
    assert elapsed >= 0.12
    assert not worker.is_alive()
    assert process_calls


def test_process_message_queue_drains_overflowed_control_messages():
    win = MainWindow.__new__(MainWindow)
    win.message_queue = MainWindowMessageQueue(win, maxsize=1)
    win._worker_message_lock = threading.Lock()
    win._coalesced_worker_messages = {}
    win._control_message_lock = threading.Lock()
    win._coalesced_control_messages = {}
    win._active_capture_run_id = None
    win._is_stopping = False
    win._last_status_message = ""
    win._session_save_in_progress = True
    status_updates: list[tuple[str, str]] = []
    toasts: list[str] = []
    dirty_cleared: list[bool] = []

    win._clear_session_dirty = lambda: dirty_cleared.append(True)
    win._set_status = lambda text, level="info": status_updates.append((text, level))
    win._show_toast = lambda message, *_args, **_kwargs: toasts.append(str(message))

    win.message_queue.put_nowait("occupied")
    MainWindow._emit_control_message(win, "session_save_done", {"saved_count": 3})

    assert win._coalesced_control_messages

    MainWindow._process_message_queue(win)

    assert win._session_save_in_progress is False
    assert dirty_cleared == [True]
    assert status_updates == [("세션 저장 완료 (3개)", "success")]
    assert toasts == ["세션 저장 완료!"]


def test_schedule_initial_recovery_snapshot_runs_only_once():
    win = MainWindow.__new__(MainWindow)
    win.is_running = True
    win._initial_recovery_snapshot_done = False

    calls: list[tuple[list[str], str]] = []
    win._start_backup_snapshot_write = (
        lambda entries, worker_name="AutoBackupWorker": calls.append(
            ([entry.text for entry in entries], worker_name)
        )
        or True
    )

    entries = [SubtitleEntry("첫 자막")]

    assert MainWindow._schedule_initial_recovery_snapshot_if_needed(win, entries) is True
    assert MainWindow._schedule_initial_recovery_snapshot_if_needed(win, entries) is False
    assert calls == [(["첫 자막"], "InitialRecoverySnapshotWorker")]


def test_start_backup_snapshot_write_freezes_prepared_entries_before_worker_runs(
    tmp_path, monkeypatch
):
    entry = _CloneTrackingEntry("첫 자막")
    written: dict[str, object] = {}
    pending_worker: dict[str, Any] = {}

    win = MainWindow.__new__(MainWindow)
    win._auto_backup_lock = threading.Lock()
    win._is_background_shutdown_active = lambda: False
    win._build_session_save_context = (
        lambda: ("https://assembly.example/live", "행정안전위원회", 0)
    )
    win._record_recovery_snapshot = lambda *_args, **_kwargs: None
    win._cleanup_old_backups = lambda: None
    win._start_background_thread = (
        lambda target, _name: pending_worker.update(target=target) or True
    )

    monkeypatch.setattr(persistence_mod.Config, "BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(
        persistence_mod.utils,
        "atomic_write_json_stream",
        lambda path, **kwargs: written.update(
            path=str(path),
            subtitles=list(kwargs.get("sequence_items", [])),
        ),
    )

    assert MainWindow._start_backup_snapshot_write(win, [entry]) is True
    entry.update_text("변경된 자막")
    pending_worker["target"]()

    assert entry.clone_calls == 1
    assert str(written.get("path", "")).endswith(".json")
    subtitles = written.get("subtitles")
    assert isinstance(subtitles, list)
    assert isinstance(subtitles[0], dict)
    assert subtitles[0]["text"] == "첫 자막"


class _AlwaysFullQueue:
    def put_nowait(self, _item: object) -> None:
        raise queue.Full

    def put(self, _item: object, *args: object, **kwargs: object) -> None:
        raise queue.Full


def test_terminal_worker_messages_use_priority_passthrough_when_queue_is_full():
    win = MainWindow.__new__(MainWindow)
    win.message_queue = _AlwaysFullQueue()
    win._active_capture_run_id = 7
    win._is_active_capture_run = lambda run_id: run_id == 7
    handled: list[tuple[str, object]] = []

    MainWindow._emit_worker_message(win, "finished", {"success": True}, run_id=7)

    assert win.__dict__.get("_terminal_worker_messages")
    processed = MainWindow._drain_terminal_worker_messages(
        win,
        max_items=10,
        handler=lambda msg_type, data: handled.append((msg_type, data)),
    )

    assert processed == 1
    assert handled == [("finished", {"success": True})]


def test_nonterminal_worker_message_overflows_without_raising_when_queue_stays_full():
    win = MainWindow.__new__(MainWindow)
    win.message_queue = _AlwaysFullQueue()
    win._active_capture_run_id = 7
    win._is_active_capture_run = lambda run_id: run_id == 7

    MainWindow._emit_worker_message(win, "subtitle_reset", {"source": "test"}, run_id=7)

    assert win.__dict__.get("_overflow_passthrough_messages")


def test_start_db_session_load_respects_dirty_confirmation():
    win = MainWindow.__new__(MainWindow)
    win.db = object()
    win._show_toast = lambda *_args, **_kwargs: None
    win._confirm_dirty_session_action = lambda _action: False
    win._run_db_task = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("dirty confirmation이 거부되면 DB 로드를 시작하면 안 됩니다.")
    )

    assert (
        MainWindow._start_db_session_load(
            win,
            1,
            task_name="db_history_load_selected",
            action_name="세션 불러오기",
            loading_text="DB 세션 불러오는 중...",
            busy_message="세션을 불러오는 중입니다...",
            source_tag="db_session",
        )
        is False
    )


def test_load_session_is_blocked_while_session_save_is_in_progress(monkeypatch):
    win = MainWindow.__new__(MainWindow)
    win.is_running = False
    win._session_save_in_progress = True
    statuses: list[tuple[str, str]] = []
    toasts: list[str] = []
    win._is_runtime_mutation_blocked = lambda _action: False
    win._set_status = lambda text, level="info": statuses.append((text, level))
    win._show_toast = lambda message, *_args, **_kwargs: toasts.append(str(message))

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("저장 중이면 파일 선택기로 넘어가면 안 됩니다.")

    monkeypatch.setattr(persistence_mod.QFileDialog, "getOpenFileName", _unexpected)

    MainWindow._load_session(win)

    assert statuses == [("세션 저장 마무리 대기 중...", "warning")]
    assert toasts == ["세션 저장 완료 후 다시 시도하세요. (세션 불러오기)"]


def test_start_db_session_load_is_blocked_while_session_save_is_in_progress():
    win = MainWindow.__new__(MainWindow)
    win.db = object()
    win._session_save_in_progress = True
    statuses: list[tuple[str, str]] = []
    toasts: list[str] = []
    win._set_status = lambda text, level="info": statuses.append((text, level))
    win._show_toast = lambda message, *_args, **_kwargs: toasts.append(str(message))
    win._confirm_dirty_session_action = lambda _action: True

    assert (
        MainWindow._start_db_session_load(
            win,
            1,
            task_name="db_history_load_selected",
            action_name="세션 불러오기",
            loading_text="DB 세션 불러오는 중...",
            busy_message="세션을 불러오는 중입니다...",
            source_tag="db_session",
        )
        is False
    )
    assert statuses == [("세션 저장 마무리 대기 중...", "warning")]
    assert toasts == ["세션 저장 완료 후 다시 시도하세요. (세션 불러오기)"]


def test_start_db_session_load_enqueues_highlight_payload_and_busy_state():
    class _FakeDb:
        def load_session(self, _session_id: int) -> dict[str, object]:
            return {
                "version": Config.VERSION,
                "created_at": "2026-04-01T09:00:00",
                "url": "https://assembly.example/db",
                "committee_name": "행정안전위원회",
                "subtitles": [{"text": "DB 자막", "timestamp": "2026-04-01T09:00:00"}],
            }

    win = MainWindow.__new__(MainWindow)
    win.db = _FakeDb()
    win._show_toast = lambda *_args, **_kwargs: None
    win._confirm_dirty_session_action = lambda _action: True
    win._deserialize_subtitles = lambda _items, source="": ([SubtitleEntry("DB 자막")], 0)

    captured: dict[str, Any] = {}
    busy_calls: list[tuple[bool, str]] = []

    def fake_run_db_task(task_name: str, worker, context=None, loading_text: str = "") -> bool:
        captured["task_name"] = task_name
        captured["context"] = dict(context or {})
        captured["loading_text"] = loading_text
        captured["payload"] = worker()
        return True

    win._run_db_task = fake_run_db_task

    started = MainWindow._start_db_session_load(
        win,
        7,
        task_name="db_search_load_selected",
        action_name="검색 결과 이동",
        loading_text="DB 검색 결과 세션 불러오는 중...",
        busy_message="검색 결과 세션을 불러오는 중입니다...",
        source_tag="db_search_session",
        set_busy=lambda busy, message: busy_calls.append((busy, message)),
        dialog="dialog-ref",
        highlight_sequence=3,
        highlight_query="예산",
    )

    assert started is True
    assert captured["task_name"] == "db_search_load_selected"
    assert captured["loading_text"] == "DB 검색 결과 세션 불러오는 중..."
    assert captured["context"] == {
        "session_id": 7,
        "dialog": "dialog-ref",
        "highlight": True,
        "query": "예산",
    }
    assert captured["payload"]["highlight_sequence"] == 3
    assert captured["payload"]["highlight_query"] == "예산"
    assert busy_calls == [(True, "검색 결과 세션을 불러오는 중입니다...")]


def _write_runtime_entries_file(
    path: Path,
    *,
    format_name: str,
    subtitles: list[object],
    extra: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {
        "format": format_name,
        "version": Config.VERSION,
        "created": "2026-04-06T09:00:00",
        "url": "https://assembly.example/runtime",
        "committee_name": "행정안전위원회",
        "subtitles": [
            item.to_dict() if isinstance(item, SubtitleEntry) else item for item in subtitles
        ],
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _build_runtime_manifest_loader_window() -> Any:
    win = MainWindow.__new__(MainWindow)
    win._runtime_segment_cache_entries_by_key = {}
    win._runtime_segment_cache_keys = []
    win._runtime_segment_search_text_cache = {}
    return win


def test_load_runtime_manifest_payload_salvages_missing_segment_file(tmp_path):
    runtime_root = tmp_path / "runtime_missing"
    runtime_root.mkdir()
    _write_runtime_entries_file(
        runtime_root / "segment_000001.json",
        format_name="runtime_session_segment_v1",
        subtitles=[SubtitleEntry("첫 세그먼트")],
    )
    _write_runtime_entries_file(
        runtime_root / "tail_checkpoint.json",
        format_name="runtime_tail_checkpoint_v1",
        subtitles=[SubtitleEntry("tail 자막")],
    )
    manifest_path = runtime_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format": "runtime_session_manifest_v1",
                "version": Config.VERSION,
                "created": "2026-04-06T09:00:00",
                "url": "https://assembly.example/runtime",
                "committee_name": "행정안전위원회",
                "tail_checkpoint": "tail_checkpoint.json",
                "segments": [
                    {"path": "segment_000001.json"},
                    {"path": "segment_000002.json"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = MainWindow._load_runtime_manifest_payload(
        _build_runtime_manifest_loader_window(),
        manifest_path,
        allow_salvage=True,
    )

    assert [entry.text for entry in payload["subtitles"]] == ["첫 세그먼트", "tail 자막"]
    assert payload["skipped_files"] == 1
    assert any("segment_000002.json" in item for item in payload["recovery_warnings"])


def test_load_runtime_manifest_payload_salvages_corrupt_segment_file(tmp_path):
    runtime_root = tmp_path / "runtime_corrupt_segment"
    runtime_root.mkdir()
    _write_runtime_entries_file(
        runtime_root / "segment_000001.json",
        format_name="runtime_session_segment_v1",
        subtitles=[SubtitleEntry("정상 세그먼트")],
    )
    (runtime_root / "segment_000002.json").write_text("{broken", encoding="utf-8")
    _write_runtime_entries_file(
        runtime_root / "tail_checkpoint.json",
        format_name="runtime_tail_checkpoint_v1",
        subtitles=[SubtitleEntry("tail 자막")],
    )
    manifest_path = runtime_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format": "runtime_session_manifest_v1",
                "version": Config.VERSION,
                "created": "2026-04-06T09:00:00",
                "url": "https://assembly.example/runtime",
                "committee_name": "행정안전위원회",
                "tail_checkpoint": "tail_checkpoint.json",
                "segments": [
                    {"path": "segment_000001.json"},
                    {"path": "segment_000002.json"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = MainWindow._load_runtime_manifest_payload(
        _build_runtime_manifest_loader_window(),
        manifest_path,
        allow_salvage=True,
    )

    assert [entry.text for entry in payload["subtitles"]] == ["정상 세그먼트", "tail 자막"]
    assert payload["skipped_files"] == 1
    assert any("segment_000002.json" in item for item in payload["recovery_warnings"])


def test_load_runtime_manifest_payload_salvages_corrupt_tail_checkpoint(tmp_path):
    runtime_root = tmp_path / "runtime_corrupt_tail"
    runtime_root.mkdir()
    _write_runtime_entries_file(
        runtime_root / "segment_000001.json",
        format_name="runtime_session_segment_v1",
        subtitles=[SubtitleEntry("세그먼트 자막")],
    )
    (runtime_root / "tail_checkpoint.json").write_text("{broken", encoding="utf-8")
    manifest_path = runtime_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format": "runtime_session_manifest_v1",
                "version": Config.VERSION,
                "created": "2026-04-06T09:00:00",
                "url": "https://assembly.example/runtime",
                "committee_name": "행정안전위원회",
                "tail_checkpoint": "tail_checkpoint.json",
                "segments": [{"path": "segment_000001.json"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = MainWindow._load_runtime_manifest_payload(
        _build_runtime_manifest_loader_window(),
        manifest_path,
        allow_salvage=True,
    )

    assert [entry.text for entry in payload["subtitles"]] == ["세그먼트 자막"]
    assert payload["skipped_files"] == 1
    assert any("tail_checkpoint.json" in item for item in payload["recovery_warnings"])


def test_load_runtime_manifest_payload_salvages_from_sibling_files_when_manifest_is_corrupt(
    tmp_path,
):
    runtime_root = tmp_path / "runtime_manifest_salvage"
    runtime_root.mkdir()
    _write_runtime_entries_file(
        runtime_root / "segment_000001.json",
        format_name="runtime_session_segment_v1",
        subtitles=[SubtitleEntry("세그먼트 자막")],
    )
    _write_runtime_entries_file(
        runtime_root / "tail_checkpoint.json",
        format_name="runtime_tail_checkpoint_v1",
        subtitles=[SubtitleEntry("tail 자막")],
    )
    manifest_path = runtime_root / "manifest.json"
    manifest_path.write_text("{broken", encoding="utf-8")

    payload = MainWindow._load_runtime_manifest_payload(
        _build_runtime_manifest_loader_window(),
        manifest_path,
        allow_salvage=True,
    )

    assert [entry.text for entry in payload["subtitles"]] == ["세그먼트 자막", "tail 자막"]
    assert payload["skipped_files"] == 1
    assert any("manifest 복구 전환" in item for item in payload["recovery_warnings"])


def test_load_runtime_manifest_payload_rejects_traversal_segment_path(tmp_path):
    runtime_root = tmp_path / "runtime_traversal_segment"
    runtime_root.mkdir()
    _write_runtime_entries_file(
        runtime_root / "tail_checkpoint.json",
        format_name="runtime_tail_checkpoint_v1",
        subtitles=[SubtitleEntry("tail 자막")],
    )
    manifest_path = runtime_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format": "runtime_session_manifest_v1",
                "version": Config.VERSION,
                "tail_checkpoint": "tail_checkpoint.json",
                "segments": [{"path": "../outside.json"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="runtime root 밖"):
        MainWindow._load_runtime_manifest_payload(
            _build_runtime_manifest_loader_window(),
            manifest_path,
            allow_salvage=False,
        )


def test_load_runtime_manifest_payload_salvages_invalid_manifest_paths(tmp_path):
    runtime_root = tmp_path / "runtime_salvage_invalid_paths"
    runtime_root.mkdir()
    outside_tail = tmp_path / "outside_tail.json"
    _write_runtime_entries_file(
        runtime_root / "segment_000001.json",
        format_name="runtime_session_segment_v1",
        subtitles=[SubtitleEntry("정상 세그먼트")],
    )
    _write_runtime_entries_file(
        outside_tail,
        format_name="runtime_tail_checkpoint_v1",
        subtitles=[SubtitleEntry("외부 tail")],
    )
    manifest_path = runtime_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format": "runtime_session_manifest_v1",
                "version": Config.VERSION,
                "tail_checkpoint": str(outside_tail.resolve()),
                "segments": [
                    {"path": "segment_000001.json"},
                    {"path": "../outside_segment.json"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = MainWindow._load_runtime_manifest_payload(
        _build_runtime_manifest_loader_window(),
        manifest_path,
        allow_salvage=True,
    )

    assert [entry.text for entry in payload["subtitles"]] == ["정상 세그먼트"]
    assert payload["skipped_files"] == 2
    assert all("runtime root 밖" in item for item in payload["recovery_warnings"])


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

    assert captured_inputs[0][0] is not prepared_entry
    assert captured_inputs[0][0].text == "정리 전 준비 스냅샷"
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


def test_save_rtf_writes_ascii_safe_unicode_and_preserves_line_breaks(tmp_path, monkeypatch):
    target = tmp_path / "unicode-test.rtf"
    entry = SubtitleEntry("한글🙂\n둘째 줄")

    win = MainWindow.__new__(MainWindow)
    win._build_prepared_entries_snapshot = lambda: [entry]
    win._generate_smart_filename = lambda _ext: "unicode-test.rtf"
    win._save_in_background = lambda save_func, path, *_args: save_func(path)

    monkeypatch.setattr(
        persistence_mod.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(target), "RTF 문서 (*.rtf)"),
    )

    MainWindow._save_rtf(win)

    raw = target.read_bytes().decode("ascii")
    expected_text = MainWindow._rtf_encode(win, entry.text)

    assert raw.isascii()
    assert expected_text in raw
    assert "\\line " in raw
