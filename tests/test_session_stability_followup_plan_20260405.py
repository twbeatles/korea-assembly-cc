import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace

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
