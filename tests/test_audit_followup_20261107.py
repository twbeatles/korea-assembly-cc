"""Regressions for the 2026-11-07 audit: preview gap ordering and owner lease reuse."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.process_wait import process_creation_marker
from core.recovery_candidates import discover_recovery_candidates
from core.runtime_archive_owner import is_archive_owner_alive, write_owner_file
from ui.main_window_common import MainWindowMessageQueue
from tests.test_audit_remediation_20261103 import qt_window  # noqa: F401

TEXTS = ["첫째 발언", "둘째 발언", "셋째 발언", "넷째 발언"]


def rows(*pairs: tuple[str, str]) -> dict:
    return {
        "raw": " ".join(text for _key, text in pairs),
        "rows": [
            {"nodeKey": key, "text": text, "speakerChannel": "primary", "unstableKey": False}
            for key, text in pairs
        ],
        "selector": "#viewSubtit .smi_word",
        "source_mode": "smi-window",
    }


def _pump(win, ticks: int = 10) -> None:
    """Run queue ticks until the backlog is empty (each tick has an 8ms budget)."""
    for _ in range(ticks):
        win._process_message_queue()
        if not win._has_pending_message_backlog():
            break


def _saturate_then_gap(win) -> int:
    """#1,#2 queued, #3 coalesced (full), UI consumes #1, then #4 queued after a gap."""
    run = win._activate_capture_run()
    win.message_queue = MainWindowMessageQueue(win, maxsize=2)
    win._emit_worker_message("preview", rows(("r1", TEXTS[0])), run_id=run)
    win._emit_worker_message("preview", rows(("r1", TEXTS[0]), ("r2", TEXTS[1])), run_id=run)
    win._emit_worker_message("preview", rows(("r2", TEXTS[1]), ("r3", TEXTS[2])), run_id=run)
    kind, data = win._unwrap_message_item(win.message_queue.get_nowait())
    win._handle_message(kind, data)
    win._emit_worker_message("preview", rows(("r3", TEXTS[2]), ("r4", TEXTS[3])), run_id=run)
    return run


def test_gap_preview_survives_worker_finished(qt_window):
    win, _app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    run = _saturate_then_gap(win)
    win._emit_worker_message("finished", {"success": True, "finalize_preview": True}, run_id=run)
    _pump(win)
    assert [entry.text for entry in win.subtitles] == TEXTS


def test_gap_preview_survives_user_stop(qt_window):
    win, _app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    _saturate_then_gap(win)
    win._stop()
    assert [entry.text for entry in win.subtitles] == TEXTS


def test_gap_preview_is_applied_in_order_during_capture(qt_window):
    win, _app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    run = _saturate_then_gap(win)
    _pump(win)
    assert [entry.text for entry in win.subtitles] == TEXTS
    assert win._get_capture_quality_payload()["preview_gaps"] == 1
    # The next in-order preview after replay is accepted normally (no new gap).
    win._emit_worker_message("preview", rows(("r4", TEXTS[3]), ("r5", "다섯째 발언")), run_id=run)
    _pump(win)
    assert [entry.text for entry in win.subtitles] == TEXTS + ["다섯째 발언"]
    assert win._get_capture_quality_payload()["preview_gaps"] == 1


def test_older_coalesced_snapshot_never_overrides_newer_state(qt_window):
    win, _app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    run = win._activate_capture_run()
    win._emit_worker_message("preview", rows(("r1", TEXTS[0])), run_id=run)
    win._emit_worker_message("preview", rows(("r1", TEXTS[0]), ("r2", TEXTS[1])), run_id=run)
    _pump(win)
    # A late coalesced snapshot with an older worker sequence must be ignored.
    with win._worker_message_lock:
        win._coalesced_worker_messages[(run, "preview")] = {
            **rows(("r1", "오래된 발언")), "full_snapshot": True, "worker_sequence": 1,
        }
    _pump(win)
    assert [entry.text for entry in win.subtitles] == TEXTS[:2]


def test_held_previews_are_dropped_with_retired_run(qt_window):
    win, _app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    run = win._activate_capture_run()
    win._hold_out_of_order_preview(run, 9, rows(("r9", "버려질 발언")))
    win._retire_capture_run(run)
    assert not win._has_held_previews()


def _write_crashed_archive(root: Path, *, pid: int, marker: str | None) -> Path:
    archive = root / "runtime_sessions" / "run_crashed"
    archive.mkdir(parents=True)
    (archive / "manifest.json").write_text(json.dumps({
        "format": "runtime_session_manifest_v1", "segments": [],
        "tail_checkpoint": "tail_checkpoint.json",
    }), encoding="utf-8")
    (archive / "tail_checkpoint.json").write_text(
        json.dumps({"entry_count": 1, "subtitles": [{"text": "x"}]}), encoding="utf-8"
    )
    owner: dict[str, object] = {"pid": pid, "token": "dead"}
    if marker is not None:
        owner["process_marker"] = marker
    (archive / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
    return archive


def test_reused_pid_owner_is_not_alive_with_injected_marker(tmp_path):
    archive = _write_crashed_archive(tmp_path, pid=4242, marker="win:111")
    assert not is_archive_owner_alive(
        archive, alive_impl=lambda _pid: True, marker_impl=lambda _pid: "win:222"
    )
    assert is_archive_owner_alive(
        archive, alive_impl=lambda _pid: True, marker_impl=lambda _pid: "win:111"
    )
    # Unreadable current marker keeps the conservative PID-only answer.
    assert is_archive_owner_alive(
        archive, alive_impl=lambda _pid: True, marker_impl=lambda _pid: None
    )


def test_legacy_owner_without_marker_keeps_pid_semantics(tmp_path):
    archive = _write_crashed_archive(tmp_path, pid=4242, marker=None)
    assert is_archive_owner_alive(archive, alive_impl=lambda _pid: True)
    assert not is_archive_owner_alive(archive, alive_impl=lambda _pid: False)


@pytest.mark.skipif(
    sys.platform != "win32" and not sys.platform.startswith("linux"),
    reason="process creation marker is implemented for Windows and Linux",
)
def test_crashed_archive_with_reused_real_pid_is_recoverable(tmp_path):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert process_creation_marker(other.pid)
        _write_crashed_archive(tmp_path, pid=other.pid, marker="stale-marker")
        candidates = discover_recovery_candidates(
            recovery_state_file=tmp_path / "missing.json",
            backup_dir=tmp_path / "backups",
            runtime_session_dir=tmp_path / "runtime_sessions",
        )
        assert len(candidates) == 1
    finally:
        other.kill()
        other.wait(timeout=10)


@pytest.mark.skipif(
    sys.platform != "win32" and not sys.platform.startswith("linux"),
    reason="process creation marker is implemented for Windows and Linux",
)
def test_live_owner_lease_written_by_this_process_stays_alive(tmp_path):
    archive = tmp_path / "run_live"
    write_owner_file(archive, pid=os.getpid(), token="live")
    payload = json.loads((archive / "owner.json").read_text(encoding="utf-8"))
    assert payload["process_marker"] == process_creation_marker(os.getpid())
    assert is_archive_owner_alive(archive)
