from __future__ import annotations

import threading
from typing import Any, cast

from core.config import Config
from ui.main_window import MainWindow
from ui.main_window_common import MainWindowMessageQueue, WorkerQueueMessage
from ui.main_window_impl.pipeline_queue import PRIORITY_OVERFLOW_WORKER_TYPES


def _build_queue_window() -> MainWindow:
    win = MainWindow.__new__(MainWindow)
    win.message_queue = MainWindowMessageQueue(win, maxsize=1)
    win._worker_message_lock = threading.Lock()
    win._coalesced_worker_messages = {}
    win._active_capture_run_id = 7
    win._overflow_passthrough_lock = threading.Lock()
    win._overflow_passthrough_messages = []
    win._overflow_drop_total = 0
    win._worker_message_coalesce_total = 0
    win._queue_backpressure_notice_at = {}
    win._is_stopping = False
    win._set_status = lambda *_args, **_kwargs: None
    win._show_toast = lambda *_args, **_kwargs: None
    return win


def test_preview_messages_use_overflow_instead_of_coalescing():
    win = _build_queue_window()
    win.message_queue.put_nowait("occupied")

    for index in range(5):
        MainWindow._emit_worker_message(
            win,
            "preview",
            {"raw": f"line-{index}"},
            run_id=7,
        )

    assert win._coalesced_worker_messages == {}
    assert len(win._overflow_passthrough_messages) == 5
    assert all(
        isinstance(item, WorkerQueueMessage) and item.msg_type == "preview"
        for item in win._overflow_passthrough_messages
    )


def test_overflow_trim_prefers_dropping_low_priority_messages():
    win = _build_queue_window()
    win._overflow_passthrough_messages = [
        WorkerQueueMessage(7, "preview", {"raw": f"p{i}"}) for i in range(130)
    ] + [
        WorkerQueueMessage(7, "subtitle_reset", {"source": "trusted"}),
    ]

    dropped = MainWindow._trim_overflow_passthrough_messages(
        win, win._overflow_passthrough_messages
    )

    assert dropped == 3
    assert len(win._overflow_passthrough_messages) == int(Config.OVERFLOW_PASSTHROUGH_MAX)
    assert any(
        isinstance(item, WorkerQueueMessage) and item.msg_type == "subtitle_reset"
        for item in win._overflow_passthrough_messages
    )


def test_overflow_drop_records_total_and_notice():
    win = _build_queue_window()
    statuses: list[str] = []
    cast(Any, win)._set_status = lambda message, *_args, **_kwargs: statuses.append(
        str(message)
    )

    MainWindow._record_overflow_drop(win, 2, reason="test")

    assert win._overflow_drop_total == 2
    assert statuses
    assert "드롭" in statuses[0]


def test_stopping_phase_drains_more_than_default_preview_limit():
    win = MainWindow.__new__(MainWindow)
    win._is_stopping = True
    assert MainWindow._resolve_preview_drain_limit(win, None) is None
    win._is_stopping = False
    assert MainWindow._resolve_preview_drain_limit(win, None) == Config.PREVIEW_DRAIN_MAX_ITEMS


def test_reconnected_handler_soft_resyncs_when_entries_exist():
    win = MainWindow.__new__(MainWindow)
    cast(Any, win).capture_state = type("State", (), {"entries": [object()]})()
    win._preview_desync_count = 4
    win._preview_ambiguous_skip_count = 2
    soft_resync_calls: list[bool] = []
    win._soft_resync = lambda: soft_resync_calls.append(True)

    MainWindow._on_capture_reconnected(win, {"attempt": 2})

    assert win._preview_desync_count == 0
    assert win._preview_ambiguous_skip_count == 0
    assert soft_resync_calls == [True]


def test_priority_overflow_types_include_reset_and_segments():
    assert "subtitle_reset" in PRIORITY_OVERFLOW_WORKER_TYPES
    assert "subtitle_segments" in PRIORITY_OVERFLOW_WORKER_TYPES


def test_overflow_preview_burst_preserves_terminal_priority_messages():
    win = _build_queue_window()
    win._overflow_passthrough_messages = [
        WorkerQueueMessage(7, "preview", {"raw": f"p{i}"}) for i in range(129)
    ] + [
        WorkerQueueMessage(7, "subtitle_reset", {"source": "burst"}),
        WorkerQueueMessage(7, "subtitle_segments", [{"raw": "segment"}]),
    ]

    dropped = MainWindow._trim_overflow_passthrough_messages(
        win, win._overflow_passthrough_messages
    )

    assert dropped == 3
    assert len(win._overflow_passthrough_messages) == int(Config.OVERFLOW_PASSTHROUGH_MAX)
    message_types = {
        item.msg_type
        for item in win._overflow_passthrough_messages
        if isinstance(item, WorkerQueueMessage)
    }
    assert "subtitle_reset" in message_types
    assert "subtitle_segments" in message_types


def test_preview_overflow_items_remain_draggable_after_burst():
    win = _build_queue_window()
    win.message_queue.put_nowait("occupied")
    for index in range(5):
        MainWindow._emit_worker_message(
            win,
            "preview",
            {"raw": f"burst-{index}"},
            run_id=7,
        )
    assert len(win._overflow_passthrough_messages) == 5