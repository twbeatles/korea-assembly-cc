from __future__ import annotations

import queue
import threading

import pytest

from core.database_result import DatabaseOperationResult, unwrap_database_result
from ui.main_window import MainWindow
from ui.main_window_common import AppControlMessageQueue, MainWindowMessageQueue, WorkerQueueMessage


def test_emit_control_message_uses_app_control_queue_not_worker_queue():
    win = MainWindow.__new__(MainWindow)
    win.message_queue = MainWindowMessageQueue(win, maxsize=8)
    win.app_control_queue = AppControlMessageQueue(maxsize=8)

    MainWindow._emit_control_message(win, "session_save_done", {"saved_count": 1})

    assert win.message_queue.empty()
    msg_type, data = win.app_control_queue.get_nowait()
    assert msg_type == "session_save_done"
    assert data == {"saved_count": 1}


def test_clear_worker_queue_preserves_app_control_queue():
    win = MainWindow.__new__(MainWindow)
    win.message_queue = MainWindowMessageQueue(win, maxsize=8)
    win.app_control_queue = AppControlMessageQueue(maxsize=8)
    win._worker_message_lock = threading.Lock()
    win._coalesced_worker_messages = {}
    win._control_message_lock = threading.Lock()
    win._coalesced_control_messages = {}
    win._overflow_passthrough_lock = threading.Lock()
    win._overflow_passthrough_messages = []
    win._terminal_worker_message_lock = threading.Lock()
    win._terminal_worker_messages = []

    win.message_queue.put_nowait(WorkerQueueMessage(1, "preview", {"text": "x"}))
    win.app_control_queue.put_nowait(("session_load_done", {"path": "a.json"}))

    MainWindow._clear_message_queue(win)

    assert win.message_queue.empty()
    assert win.app_control_queue.qsize() == 1
    msg_type, _data = win.app_control_queue.get_nowait()
    assert msg_type == "session_load_done"


def test_shutdown_diagnostic_includes_control_queue_size():
    win = MainWindow.__new__(MainWindow)
    win.message_queue = MainWindowMessageQueue(win, maxsize=8)
    win.app_control_queue = AppControlMessageQueue(maxsize=8)
    win._coalesced_control_messages = {}
    win._coalesced_worker_messages = {}
    win._overflow_passthrough_messages = []
    win._detached_drivers_lock = threading.Lock()
    win._detached_drivers = []
    win._db_worker_thread = None
    win._db_worker_queue = queue.Queue()
    win._runtime_session_root = None
    win._runtime_manifest_path = None
    win._runtime_segment_manifest = []
    win._runtime_archived_count = 0
    win.driver = None

    win.app_control_queue.put_nowait(("toast", {"message": "hello"}))

    payload = MainWindow._build_shutdown_diagnostic_payload(win)
    message_queue = payload.get("message_queue")
    assert isinstance(message_queue, dict)
    assert message_queue.get("control_queue_size") == 1


def test_database_operation_result_helpers():
    ok = DatabaseOperationResult.success(["row"])
    assert ok.ok is True
    assert unwrap_database_result(ok) == ["row"]

    failed = DatabaseOperationResult.failure("boom", error_type="sqlite")
    assert failed.ok is False
    with pytest.raises(RuntimeError, match="boom"):
        unwrap_database_result(failed)


def test_handle_db_task_result_distinguishes_failed_result_from_empty_list():
    win = MainWindow.__new__(MainWindow)
    errors: list[tuple[str, str]] = []
    win._handle_db_task_error = lambda task_name, error, context=None: errors.append(
        (task_name, error)
    )
    win._db_tasks_inflight = {"db_search"}

    MainWindow._handle_db_task_result(
        win,
        "db_search",
        DatabaseOperationResult.failure("connection lost"),
        {"query": "테스트"},
    )

    assert errors == [("db_search", "connection lost")]