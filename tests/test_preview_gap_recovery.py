from __future__ import annotations

import queue

from ui.main_window import MainWindow
from ui.main_window_common import WorkerQueueMessage


def _window() -> MainWindow:
    win = MainWindow.__new__(MainWindow)
    win.message_queue = queue.Queue()
    win._worker_message_lock = __import__("threading").Lock()
    win._coalesced_worker_messages = {}
    win._active_capture_run_id = 7
    win._is_active_capture_run = lambda run_id: run_id == 7
    return win


def test_preview_messages_receive_monotonic_sequence_per_run() -> None:
    win = _window()

    win._emit_worker_message("preview", {"raw": "one"}, run_id=7)
    win._emit_worker_message("preview", {"raw": "two"}, run_id=7)

    first = win.message_queue.get_nowait()
    second = win.message_queue.get_nowait()
    assert first.sequence == 1
    assert second.sequence == 2


def test_preview_duplicate_is_ignored_and_gap_requests_full_snapshot() -> None:
    win = _window()

    assert win._unwrap_message_item(
        WorkerQueueMessage(7, "preview", {"raw": "one"}, sequence=1)
    ) is not None
    assert win._unwrap_message_item(
        WorkerQueueMessage(7, "preview", {"raw": "duplicate"}, sequence=1)
    ) is None
    assert win._unwrap_message_item(
        WorkerQueueMessage(7, "preview", {"raw": "gap"}, sequence=3)
    ) is None
    assert win.__dict__["_preview_resync_requested_runs"] == {7}


def test_next_preview_after_gap_is_tagged_as_full_snapshot_and_accepted() -> None:
    win = _window()
    win._preview_sequence_by_run = {7: 3}
    win._preview_last_received_sequence_by_run = {7: 1}
    win._preview_resync_requested_runs = {7}
    win._preview_awaiting_full_snapshot_runs = {7}

    win._emit_worker_message("preview", {"raw": "current DOM"}, run_id=7)
    message = win.message_queue.get_nowait()
    decoded = win._unwrap_message_item(message)

    assert message.sequence == 4
    assert decoded is not None
    assert decoded[1]["full_snapshot"] is True
    assert win.__dict__["_preview_awaiting_full_snapshot_runs"] == set()


def test_legacy_sequence_less_worker_message_remains_compatible() -> None:
    win = _window()
    assert win._unwrap_message_item(
        WorkerQueueMessage(7, "preview", {"raw": "legacy"})
    ) == ("preview", {"raw": "legacy"})


def test_queue_overflow_coalesced_preview_is_a_full_snapshot() -> None:
    win = _window()
    win.message_queue = queue.Queue(maxsize=1)
    win.message_queue.put_nowait(("status", "busy"))
    win._set_status = lambda *_args, **_kwargs: None
    win._show_toast = lambda *_args, **_kwargs: None

    win._emit_worker_message("preview", {"raw": "latest DOM"}, run_id=7)

    pending = win._pop_coalesced_worker_messages(max_items=1)
    assert pending[0][0] == "preview"
    assert pending[0][1]["full_snapshot"] is True
    assert pending[0][1]["worker_sequence"] == 1
