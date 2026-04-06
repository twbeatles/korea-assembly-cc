import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from core.models import SubtitleEntry

mw_mod = pytest.importorskip("ui.main_window")
dialogs_mod = pytest.importorskip("ui.dialogs")

MainWindow = mw_mod.MainWindow
QApplication = mw_mod.QApplication


def test_runtime_segment_flush_removes_prefix_only_after_done(tmp_path, monkeypatch):
    win = MainWindow.__new__(MainWindow)
    monkeypatch.setattr(mw_mod.Config, "RUNTIME_SEGMENT_FLUSH_THRESHOLD", 5)
    monkeypatch.setattr(mw_mod.Config, "RUNTIME_ACTIVE_TAIL_ENTRIES", 2)
    monkeypatch.setattr(
        mw_mod.utils,
        "atomic_write_json_stream",
        lambda *_args, **_kwargs: None,
    )

    win.is_running = True
    win._runtime_session_root = tmp_path
    win._runtime_manifest_path = tmp_path / "manifest.json"
    win._runtime_segment_manifest = []
    win._runtime_next_segment_index = 1
    win._runtime_archived_count = 0
    win._runtime_archived_chars = 0
    win._runtime_archived_words = 0
    win._runtime_segment_flush_in_progress = False
    win._runtime_search_revision = 0
    win._runtime_search_query = ""
    win._runtime_search_truncated = False
    win._cached_total_chars = 0
    win._cached_total_words = 0
    win.subtitle_lock = threading.Lock()
    win.subtitles = [SubtitleEntry(f"문장 {index}") for index in range(6)]
    win._build_session_save_context = lambda: ("https://assembly.example/live", "행안위", 0)
    win._is_background_shutdown_active = lambda: False
    emitted: list[tuple[str, dict]] = []
    win._emit_control_message = lambda msg_type, data: emitted.append((msg_type, data))
    win._start_background_thread = lambda target, _name: target() or True
    win._write_runtime_manifest = lambda: None
    win._write_runtime_tail_checkpoint = lambda *_args, **_kwargs: None
    win._update_count_label = lambda: None
    win._refresh_text = lambda **_kwargs: None
    win._show_toast = lambda *_args, **_kwargs: None

    assert MainWindow._maybe_schedule_runtime_segment_flush(win) is True
    assert len(win.subtitles) == 6
    assert emitted and emitted[0][0] == "runtime_segment_flush_done"

    MainWindow._handle_runtime_segment_flush_done(win, emitted[0][1])

    assert len(win.subtitles) == 2
    assert win._runtime_archived_count == 4
    assert len(win._runtime_segment_manifest) == 1


def test_session_save_done_preserves_runtime_archive_and_allows_followup_flush(
    tmp_path, monkeypatch
):
    win = MainWindow.__new__(MainWindow)
    monkeypatch.setattr(mw_mod.Config, "RUNTIME_SEGMENT_FLUSH_THRESHOLD", 5)
    monkeypatch.setattr(mw_mod.Config, "RUNTIME_ACTIVE_TAIL_ENTRIES", 2)
    monkeypatch.setattr(
        mw_mod.utils,
        "atomic_write_json_stream",
        lambda *_args, **_kwargs: None,
    )

    win._is_stopping = False
    win._session_dirty = True
    win._session_save_in_progress = True
    win.is_running = True
    win._runtime_session_root = tmp_path
    win._runtime_manifest_path = tmp_path / "manifest.json"
    win._runtime_segment_manifest = []
    win._runtime_next_segment_index = 1
    win._runtime_archived_count = 0
    win._runtime_archived_chars = 0
    win._runtime_archived_words = 0
    win._runtime_archive_token = "archive-current"
    win._runtime_archive_run_id = 17
    win._runtime_segment_flush_in_progress = False
    win._runtime_search_revision = 0
    win._runtime_search_query = ""
    win._runtime_search_truncated = False
    win._cached_total_chars = 0
    win._cached_total_words = 0
    win.subtitle_lock = threading.Lock()
    win.subtitles = [SubtitleEntry(f"문장 {index}") for index in range(6)]
    win._build_session_save_context = lambda: ("https://assembly.example/live", "행안위", 0)
    win._is_background_shutdown_active = lambda: False
    win._clear_session_dirty = lambda: setattr(win, "_session_dirty", False)
    recovery_cleared: list[bool] = []
    win._clear_recovery_state = lambda: recovery_cleared.append(True)
    emitted: list[tuple[str, dict]] = []
    win._emit_control_message = lambda msg_type, data: emitted.append((msg_type, data))
    win._start_background_thread = lambda target, _name: target() or True
    win._write_runtime_manifest = lambda: None
    win._write_runtime_tail_checkpoint = lambda *_args, **_kwargs: None
    win._schedule_ui_refresh = lambda **_kwargs: None
    win._set_status = lambda *_args, **_kwargs: None
    win._show_toast = lambda *_args, **_kwargs: None

    MainWindow._handle_message(win, "session_save_done", {"saved_count": 6})

    assert win._session_save_in_progress is False
    assert win._session_dirty is False
    assert recovery_cleared == [True]
    assert win._runtime_session_root == tmp_path
    assert win._runtime_manifest_path == tmp_path / "manifest.json"
    assert win._runtime_archive_token == "archive-current"
    assert win._runtime_archive_run_id == 17

    assert MainWindow._maybe_schedule_runtime_segment_flush(win) is True
    assert emitted and emitted[0][0] == "runtime_segment_flush_done"
    assert emitted[0][1]["archive_token"] == "archive-current"
    assert emitted[0][1]["run_id"] == 17

    MainWindow._handle_runtime_segment_flush_done(win, emitted[0][1])

    assert len(win.subtitles) == 2
    assert win._runtime_archived_count == 4
    assert len(win._runtime_segment_manifest) == 1


def test_runtime_segment_flush_done_ignores_stale_run_identity():
    win = MainWindow.__new__(MainWindow)
    win._runtime_archive_token = "archive-current"
    win._runtime_archive_run_id = 22
    win._runtime_segment_flush_in_progress = True
    win.subtitle_lock = threading.Lock()
    win.subtitles = [SubtitleEntry("현재 자막 1"), SubtitleEntry("현재 자막 2")]
    win._cached_total_chars = 10
    win._cached_total_words = 4
    win._runtime_archived_count = 7
    win._runtime_archived_chars = 70
    win._runtime_archived_words = 20
    win._runtime_segment_manifest = [{"path": "segment_000001.json", "entry_count": 7}]

    manifest_writes: list[bool] = []
    checkpoint_writes: list[bool] = []
    refresh_calls: list[bool] = []
    win._write_runtime_manifest = lambda: manifest_writes.append(True)
    win._write_runtime_tail_checkpoint = lambda *_args, **_kwargs: checkpoint_writes.append(
        True
    )
    win._schedule_ui_refresh = lambda **_kwargs: refresh_calls.append(True)

    MainWindow._handle_runtime_segment_flush_done(
        win,
        {
            "run_id": 99,
            "archive_token": "archive-current",
            "segment_index": 2,
            "path": "segment_000002.json",
            "entry_count": 1,
            "char_count": 3,
            "word_count": 1,
            "start_index": 7,
        },
    )

    assert [entry.text for entry in win.subtitles] == ["현재 자막 1", "현재 자막 2"]
    assert win._runtime_segment_flush_in_progress is True
    assert win._runtime_archived_count == 7
    assert manifest_writes == []
    assert checkpoint_writes == []
    assert refresh_calls == []


def test_runtime_segment_flush_failed_ignores_stale_archive_token():
    win = MainWindow.__new__(MainWindow)
    win._runtime_archive_token = "archive-current"
    win._runtime_archive_run_id = 22
    win._runtime_segment_flush_in_progress = True
    toasts: list[tuple[str, str, int]] = []
    win._show_toast = lambda message, level, duration: toasts.append(
        (str(message), str(level), int(duration))
    )

    MainWindow._handle_runtime_segment_flush_failed(
        win,
        {
            "run_id": 22,
            "archive_token": "archive-stale",
            "path": "segment_000002.json",
            "error": "stale flush error",
        },
    )

    assert win._runtime_segment_flush_in_progress is True
    assert toasts == []


def test_runtime_recovery_snapshot_worker_ignores_stale_archive_context(tmp_path):
    win = MainWindow.__new__(MainWindow)
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()

    win._auto_backup_lock = threading.Lock()
    win._runtime_session_root = runtime_root
    win._runtime_manifest_path = runtime_root / "manifest.json"
    win._runtime_segment_manifest = []
    win._runtime_archived_count = 0
    win._runtime_archived_chars = 0
    win._runtime_archived_words = 0
    win._runtime_tail_revision = 1
    win._runtime_tail_checkpoint_revision = 0
    win._runtime_archive_token = "archive-current"
    win._runtime_archive_run_id = 31
    win._build_session_save_context = lambda: ("https://assembly.example/live", "행안위", 0)
    win._is_background_shutdown_active = lambda: False

    worker_targets: list[Callable[[], None]] = []

    def fake_start_background_thread(target: Callable[[], None], _name: str) -> bool:
        worker_targets.append(target)
        return True

    win._start_background_thread = fake_start_background_thread
    recovery_records: list[tuple[tuple[object, ...], dict[str, object]]] = []
    win._record_recovery_snapshot = lambda *args, **kwargs: recovery_records.append(
        (args, kwargs)
    )

    assert MainWindow._start_runtime_recovery_snapshot_write(
        win,
        [SubtitleEntry("복구 자막")],
    )
    assert len(worker_targets) == 1

    win._runtime_archive_token = "archive-next"
    worker_targets[0]()

    assert recovery_records == []
    assert (runtime_root / "tail_checkpoint.json").exists() is False
    assert win._auto_backup_lock.acquire(blocking=False) is True
    win._auto_backup_lock.release()


def test_db_worker_serializes_async_and_sync_tasks():
    checkpoints: list[str] = []
    worker_names: list[str] = []
    control_messages: list[tuple[str, object]] = []

    win = MainWindow.__new__(MainWindow)
    win.db = SimpleNamespace(checkpoint=lambda mode="PASSIVE": checkpoints.append(mode) or True)
    win._show_toast = lambda *_args, **_kwargs: None
    win._set_status = lambda *_args, **_kwargs: None
    win._is_background_shutdown_active = lambda: False
    win._db_tasks_inflight = set()
    win._emit_control_message = lambda msg_type, data: control_messages.append((msg_type, data))

    assert MainWindow._run_db_task(
        win,
        "db_stats",
        worker=lambda: worker_names.append(threading.current_thread().name) or {"count": 1},
    )
    assert MainWindow._run_db_task(
        win,
        "db_search",
        worker=lambda: worker_names.append(threading.current_thread().name) or {"count": 2},
    )

    deadline = time.time() + 2.0
    while len(control_messages) < 2 and time.time() < deadline:
        time.sleep(0.01)

    assert len(control_messages) == 2

    sync_result = MainWindow._run_db_task_sync(
        win,
        "db_session_save",
        worker=lambda: worker_names.append(threading.current_thread().name) or 123,
        write_task=True,
    )

    assert sync_result == 123
    assert worker_names
    assert set(worker_names) == {"DBWorker"}
    assert checkpoints

    MainWindow._shutdown_db_worker(win, timeout=1.0)


def test_shutdown_diagnostic_includes_runtime_and_queue_metadata(tmp_path):
    win = MainWindow.__new__(MainWindow)
    win.message_queue = queue.Queue()
    win.message_queue.put_nowait(("status", "busy"))
    win._coalesced_control_messages = {"a": ("status", "x")}
    win._coalesced_worker_messages = {(1, "status"): "y"}
    win._overflow_passthrough_messages = [("finished", {})]
    win._detached_drivers_lock = threading.Lock()
    win._detached_drivers = [object()]
    win.driver = object()
    win.connection_status = "connected"
    win._session_dirty = True
    win._session_save_in_progress = False
    win._session_load_in_progress = False
    win._reflow_in_progress = False
    win.is_running = False
    win._runtime_session_root = tmp_path / "runtime"
    win._runtime_manifest_path = win._runtime_session_root / "manifest.json"
    win._runtime_segment_manifest = [{"path": "segment_000001.json", "entry_count": 10}]
    win._runtime_archived_count = 10
    win._active_background_threads = set()
    win._active_background_threads_lock = threading.Lock()
    win._db_worker_queue = queue.Queue()
    win._db_worker_thread = None
    win._db_worker_shutdown = False
    win._db_worker_current_task = ""

    payload = MainWindow._build_shutdown_diagnostic_payload(win)

    assert payload["db_worker"]["queue_size"] == 0
    assert payload["runtime_archive"]["archived_count"] == 10
    assert payload["message_queue"]["queue_size"] == 1
    assert payload["driver"]["detached_count"] == 1
    assert payload["session_state"]["dirty"] is True


def test_live_broadcast_dialog_mark_closing_aborts_active_reply():
    app = QApplication.instance() or QApplication([])

    class _FakeSignal:
        def disconnect(self):
            return None

    class _FakeReply:
        def __init__(self):
            self.finished = _FakeSignal()
            self.aborted = False
            self.deleted = False
            self.running = True

        def isRunning(self):
            return self.running

        def abort(self):
            self.aborted = True
            self.running = False

        def deleteLater(self):
            self.deleted = True

    _ = app
    dialog = dialogs_mod.LiveBroadcastDialog()
    fake_reply = _FakeReply()
    dialog._active_reply = fake_reply

    dialog._mark_closing()

    assert dialog._active_reply is None
    assert fake_reply.aborted is True
    assert fake_reply.deleted is True
