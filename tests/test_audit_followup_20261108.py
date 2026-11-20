"""Regressions for the 2026-11-08 audit: stream ordering of reset/reconnected vs previews."""
from __future__ import annotations

import pytest

from core.config import Config
from ui.main_window_common import MainWindowMessageQueue, WorkerQueueMessage
from tests.test_audit_followup_20261107 import rows
from tests.test_audit_remediation_20261103 import qt_window  # noqa: F401

T = ["첫째 발언", "둘째 발언", "셋째 발언", "넷째 발언", "다섯째 발언"]
RESET = {"source": "observer", "selector": ".smi_word"}


def _texts(win) -> list[str]:
    return [entry.text for entry in win.subtitles]


def _pump(win, ticks: int = 10) -> None:
    """Run queue ticks like the 100ms timer + follow-up drains (each tick has an 8ms budget)."""
    for _ in range(ticks):
        win._process_message_queue()
        if not win._has_pending_message_backlog():
            break


def _consume_one(win) -> None:
    decoded = win._unwrap_message_item(win.message_queue.get_nowait())
    assert decoded is not None
    win._handle_message(*decoded)


def _saturate_then_reset(win) -> int:
    """#1 consumed, #2 consumed, #3 coalesced, #4 queued after a gap, reset queued."""
    run = win._activate_capture_run()
    win.message_queue = MainWindowMessageQueue(win, maxsize=2)
    emit = win._emit_worker_message
    emit("preview", rows(("r1", T[0])), run_id=run)
    emit("preview", rows(("r1", T[0]), ("r2", T[1])), run_id=run)
    emit("preview", rows(("r2", T[1]), ("r3", T[2])), run_id=run)  # coalesced
    _consume_one(win)
    emit("preview", rows(("r3", T[2]), ("r4", T[3])), run_id=run)
    _consume_one(win)
    emit("subtitle_reset", RESET, run_id=run)
    return run


@pytest.fixture
def running(qt_window):
    win, _app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    return win


def test_reset_does_not_overtake_held_previews_during_capture(running):
    win = running
    run = _saturate_then_reset(win)
    _pump(win)
    win._emit_worker_message("preview", rows(("n1", T[4])), run_id=run)
    _pump(win)
    assert _texts(win) == T


def test_reset_does_not_overtake_held_previews_at_finished_barrier(running):
    win = running
    run = _saturate_then_reset(win)
    win._emit_worker_message(
        "finished", {"success": True, "finalize_preview": True}, run_id=run
    )
    _pump(win)
    assert _texts(win) == T[:4]


def test_user_stop_after_saturated_reset_keeps_every_utterance_once(running):
    win = running
    _saturate_then_reset(win)
    win._stop()
    assert _texts(win) == T[:4]


def test_reset_in_overflow_waits_for_older_queued_previews(running, monkeypatch):
    monkeypatch.setattr(Config, "WORKER_MESSAGE_PUT_TIMEOUT", 0.01)
    win = running
    run = win._activate_capture_run()
    win.message_queue = MainWindowMessageQueue(win, maxsize=2)
    emit = win._emit_worker_message
    emit("preview", rows(("r1", T[0])), run_id=run)
    _pump(win)
    emit("preview", rows(("r1", T[0]), ("r2", T[1])), run_id=run)
    emit("preview", rows(("r2", T[1]), ("r3", T[2])), run_id=run)
    emit("subtitle_reset", RESET, run_id=run)  # queue full -> overflow passthrough
    assert len(win._overflow_passthrough_messages) == 1
    _pump(win)
    emit("preview", rows(("n1", T[3])), run_id=run)
    _pump(win)
    assert _texts(win) == T[:4]


def test_unsaturated_reset_order_is_unchanged(running):
    win = running
    run = win._activate_capture_run()
    emit = win._emit_worker_message
    emit("preview", rows(("r1", T[0])), run_id=run)
    emit("preview", rows(("r1", T[0]), ("r2", T[1])), run_id=run)
    emit("preview", rows(("r2", T[1]), ("r3", T[2])), run_id=run)
    emit("preview", rows(("r3", T[2]), ("r4", T[3])), run_id=run)
    emit("subtitle_reset", RESET, run_id=run)
    _pump(win)
    emit("preview", rows(("n1", T[4])), run_id=run)
    _pump(win)
    assert _texts(win) == T
    assert win._get_capture_quality_payload()["preview_gaps"] == 0


def test_reset_shares_the_preview_sequence(running):
    win = running
    run = win._activate_capture_run()
    win._emit_worker_message("preview", rows(("r1", T[0])), run_id=run)
    win._emit_worker_message("subtitle_reset", RESET, run_id=run)
    win._emit_worker_message("keepalive", T[0], run_id=run)
    win._emit_worker_message("preview", rows(("n1", T[1])), run_id=run)
    items = [win.message_queue.get_nowait() for _ in range(4)]
    assert [(item.msg_type, item.sequence) for item in items] == [
        ("preview", 1),
        ("subtitle_reset", 2),
        ("keepalive", None),
        ("preview", 3),
    ]


def test_coalesced_reconnected_is_replayed_in_sequence_with_previews(running):
    win = running
    run = win._activate_capture_run()
    win.message_queue = MainWindowMessageQueue(win, maxsize=2)
    calls: list[tuple[str, list[str]]] = []
    win._on_capture_reconnected = lambda _data: calls.append(("reconnected", _texts(win)))
    emit = win._emit_worker_message
    emit("preview", rows(("r1", T[0])), run_id=run)
    emit("preview", rows(("r1", T[0]), ("r2", T[1])), run_id=run)
    # Queue full: the pre-reconnect preview (#3) and reconnected (#4) are coalesced,
    # then a post-reconnect preview (#5) overwrites the coalesced preview slot.
    emit("preview", rows(("r2", T[1]), ("r3", T[2])), run_id=run)
    emit("reconnected", {"attempt": 1, "url": "https://assembly.webcast.go.kr/"}, run_id=run)
    emit("preview", rows(("r3", T[2]), ("r4", T[3])), run_id=run)
    with win._worker_message_lock:
        pending = dict(win._coalesced_worker_messages)
    assert pending[(run, "reconnected")]["worker_sequence"] == 4
    assert pending[(run, "preview")]["worker_sequence"] == 5
    _pump(win)
    # reconnected (#4) ran after every older preview and before the newer #5.
    assert calls == [("reconnected", T[:2])]
    assert T[3] in _texts(win)


def test_full_snapshot_waits_for_older_stashed_reset(running):
    win = running
    run = win._activate_capture_run()
    win._preview_last_received_sequence_by_run = {run: 1}
    win._stash_overflow_passthrough_item(
        WorkerQueueMessage(run, "subtitle_reset", RESET, sequence=2)
    )
    snapshot = WorkerQueueMessage(
        run, "preview", {**rows(("n1", T[1])), "full_snapshot": True}, sequence=3
    )
    assert win._unwrap_message_item(snapshot) is None
    assert win._has_held_previews(run)


def test_full_snapshot_without_stash_is_accepted_after_gap(running):
    win = running
    run = win._activate_capture_run()
    win._preview_last_received_sequence_by_run = {run: 1}
    snapshot = WorkerQueueMessage(
        run, "preview", {**rows(("n1", T[1])), "full_snapshot": True}, sequence=4
    )
    assert win._unwrap_message_item(snapshot) is not None
    assert win._preview_last_received_sequence_by_run[run] == 4


def test_budget_limited_drain_does_not_replay_held_ahead_of_queue(running):
    win = running
    run = win._activate_capture_run()
    emit = win._emit_worker_message
    emit("preview", rows(("r1", T[0])), run_id=run)
    emit("preview", rows(("r1", T[0]), ("r2", T[1])), run_id=run)
    win._hold_out_of_order_preview(run, 9, rows(("r9", "나중 발언")))
    win._drain_pending_previews(max_items=1)
    assert "나중 발언" not in _texts(win)
    assert win._has_held_previews(run)


def test_requeued_stream_message_is_not_dropped_as_duplicate(running):
    win = running
    run = win._activate_capture_run()
    item = WorkerQueueMessage(run, "reconnected", {"attempt": 1}, sequence=1)
    assert win._unwrap_message_item(item) is not None
    requeued = win._as_requeueable(item)
    assert isinstance(requeued, WorkerQueueMessage) and requeued.sequence is None
    assert win._unwrap_message_item(requeued) == ("reconnected", {"attempt": 1})


def test_held_trim_is_counted_and_announced(running, monkeypatch):
    monkeypatch.setattr(Config, "PREVIEW_HELD_MAX", 2)
    win = running
    toasts: list[str] = []
    win._show_toast = lambda message, *_a, **_k: toasts.append(str(message))
    run = win._activate_capture_run()
    for sequence in (5, 6, 7):
        win._hold_out_of_order_preview(run, sequence, rows((f"r{sequence}", "x")))
    assert win._get_capture_quality_payload()["queue_drops"] == 1
    assert toasts


def test_capture_summary_reports_drops_of_this_run_only(running):
    win = running
    win._capture_quality = None
    win._increment_capture_quality("queue_drops", 3)  # from an earlier run/session
    win._capture_run_queue_drops_baseline = 3
    assert "드롭" not in win._build_capture_summary_text()
    win._increment_capture_quality("queue_drops", 2)
    assert "메시지 2건 드롭" in win._build_capture_summary_text()
