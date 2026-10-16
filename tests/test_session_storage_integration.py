"""Real pipeline -> archive/tail -> JSON, SQLite worker, recovery and exports.

Only user input and UI notifications are substituted. Serialization, filesystem,
database transactions, worker threads and export formatting run unchanged.
"""
from __future__ import annotations

import json
import queue
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any, cast

import pytest

from core import file_io
from core.config import Config
from core.models import CaptureQualityState, SubtitleEntry
from core.subtitle_pipeline import LiveRowCommitMeta, commit_live_row, create_empty_capture_state
from database import DatabaseManager
from ui.main_window import MainWindow
from ui.main_window_impl import persistence_exports_text


@pytest.fixture
def stored_session(tmp_path, monkeypatch):
    win = cast(Any, MainWindow.__new__(MainWindow))
    win.db = DatabaseManager(str(tmp_path / "sessions.db"))
    win.db_available = True
    win.subtitle_lock = threading.Lock()
    win.capture_state = create_empty_capture_state()
    win._capture_quality = CaptureQualityState(preview_gaps=2, reconnects=1)
    win._session_lineage_id = "integration-lineage"
    win._session_save_in_progress = False
    win._build_session_save_context = lambda: ("https://assembly.webcast.go.kr/live", "테스트위원회", 10)
    win._show_toast = lambda *_args, **_kwargs: None
    win._set_status = lambda *_args, **_kwargs: None
    messages: queue.Queue = queue.Queue()
    win._emit_control_message = lambda kind, payload: messages.put((kind, payload))
    recovery = tmp_path / "recovery.json"
    monkeypatch.setattr(Config, "RECOVERY_STATE_FILE", str(recovery))
    now = datetime(2026, 10, 16, 9, 0, 0)

    first = commit_live_row(win.capture_state, "예산안을 심사합니다", "예산안을 심사합니다", now,
        meta=LiveRowCommitMeta(source_node_key="top::row1", selector="#viewSubtit .smi_word", speaker_channel="primary"))
    assert first.appended_entry is not None
    commit_live_row(win.capture_state, "예산안을 심사하겠습니다", "예산안을 심사하겠습니다", now + timedelta(seconds=1),
        meta=LiveRowCommitMeta(source_node_key="top::row1", source_entry_id=first.appended_entry.entry_id or "", selector="#viewSubtit .smi_word", speaker_channel="primary"))
    commit_live_row(win.capture_state, "다음 안건을 상정합니다", "다음 안건을 상정합니다", now + timedelta(seconds=5),
        meta=LiveRowCommitMeta(source_node_key="top::row2", selector="#viewSubtit .smi_word", speaker_channel="secondary", frame_path=(0,)))
    entries = [entry.clone() for entry in win.capture_state.entries]
    assert [entry.text for entry in entries] == ["예산안을 심사하겠습니다", "다음 안건을 상정합니다"]
    # Model a long-running capture: the first row is on disk, only the tail is in memory.
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    segment = runtime_root / "segment_0001.json"
    file_io.atomic_write_json(segment, {"subtitles": [entries[0].to_dict()], **win._build_runtime_entries_fingerprint(entries[:1])})
    win._runtime_session_root = runtime_root
    win._runtime_segment_manifest = [{"path": segment.name, "entry_count": 1, "start_index": 0}]
    tail = [entries[1].clone()]
    win.subtitles = tail
    # UI snapshot preparation is covered separately; the storage readers remain real.
    win._build_prepared_entries_snapshot = lambda: tail
    try:
        yield win, entries, tail, messages, recovery
    finally:
        win._wait_active_background_threads(timeout=5)
        assert win._get_live_background_threads() == [], "save worker leaked"
        win._shutdown_db_worker(timeout=5)
        assert win.__dict__.get("_db_worker_thread") is None, "DB worker leaked"
        win.db.close_all()


def test_archive_and_tail_round_trip_through_json_db_worker_and_recovery(stored_session, tmp_path):
    win, expected, tail, _messages, recovery = stored_session
    target = tmp_path / "session.json"
    info = win._write_session_snapshot(str(target), tail, save_operation_id="round-trip")
    assert info["db_saved"] is True and info["db_error"] == ""
    assert info["saved_count"] == 2
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["subtitles"] == [entry.to_dict() for entry in expected]
    pointer = json.loads(recovery.read_text(encoding="utf-8"))
    assert pointer["path"] == str(target.resolve())
    assert win._load_recovery_state() == pointer
    loaded = win.db.load_session(info["db_session_id"])
    assert loaded is not None
    restored = [SubtitleEntry.from_dict(row).to_dict() for row in loaded["subtitles"]]
    assert restored == payload["subtitles"]
    for field in ("lineage_id", "save_operation_id", "capture_quality", "url", "committee_name"):
        assert loaded[field] == payload[field]
    assert loaded["total_subtitles"] == 2
    assert loaded["total_characters"] == sum(len(entry.text) for entry in expected)
    assert win._db_worker_thread.is_alive()


@pytest.mark.parametrize("extension", ["srt", "vtt"])
def test_archive_and_tail_export_complete_cues_in_real_background_worker(stored_session, tmp_path, monkeypatch, extension):
    win, expected, _tail, messages, _recovery = stored_session
    target = tmp_path / f"captions.{extension}"
    win._generate_smart_filename = lambda ext: f"captions.{ext}"
    monkeypatch.setattr(persistence_exports_text.QFileDialog, "getSaveFileName", lambda *_args: (str(target), ""))
    getattr(win, f"_save_{extension}")()
    kind, result = messages.get(timeout=10)
    assert kind == "toast" and result["toast_type"] == "success", result
    win._wait_active_background_threads(timeout=5)
    assert win._file_save_in_progress == set()
    text = target.read_text(encoding="utf-8")
    separator = "," if extension == "srt" else "."
    expected_text = (
        f"1\n00:00:00{separator}000 --> 00:00:01{separator}000\n{expected[0].text}\n\n"
        f"2\n00:00:05{separator}000 --> 00:00:08{separator}000\n{expected[1].text}\n\n"
    )
    assert text == ("WEBVTT\n\n" if extension == "vtt" else "") + expected_text


def test_db_failure_preserves_complete_json_recovery_and_can_retry(stored_session, tmp_path):
    win, expected, tail, _messages, recovery = stored_session
    with sqlite3.connect(win.db.db_path) as conn:
        conn.execute("""CREATE TRIGGER reject_save BEFORE INSERT ON sessions
            BEGIN SELECT RAISE(ABORT, 'injected DB unavailable'); END""")
    target = tmp_path / "session.json"
    info = win._write_session_snapshot(str(target), tail, save_operation_id="retry")
    assert info["db_saved"] is False and "injected DB unavailable" in info["db_error"]
    assert info["db_session_id"] is None
    assert json.loads(target.read_text(encoding="utf-8"))["subtitles"] == [entry.to_dict() for entry in expected]
    assert json.loads(recovery.read_text(encoding="utf-8"))["path"] == str(target.resolve())
    assert win.db.list_sessions() == []
    with sqlite3.connect(win.db.db_path) as conn:
        conn.execute("DROP TRIGGER reject_save")
    retried = win._write_session_snapshot(str(target), tail, save_operation_id="retry")
    assert retried["db_saved"] is True
    assert len(win.db.list_sessions()) == 1


def test_corrupt_archive_cannot_replace_existing_snapshot_or_recovery(stored_session, tmp_path):
    win, _expected, tail, _messages, recovery = stored_session
    target = tmp_path / "session.json"
    win._write_session_snapshot(str(target), tail)
    originals = target.read_bytes(), recovery.read_bytes()
    # Simulate disk corruption after a restart: no process-local cache may hide it.
    win._runtime_segment_cache_entries_by_key = {}
    (win._runtime_session_root / "segment_0001.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        win._write_session_snapshot(str(target), tail)
    assert (target.read_bytes(), recovery.read_bytes()) == originals
    assert len(win.db.list_sessions()) == 1
    assert list(tmp_path.glob(".session.json.*.tmp")) == []


def test_async_save_freezes_entries_while_capture_changes(stored_session, tmp_path):
    win, expected, tail, messages, _recovery = stored_session
    entered = threading.Event()
    release = threading.Event()
    context = win._build_session_save_context

    def paused_context():
        entered.set()
        assert release.wait(timeout=5), "test failed to release save worker"
        return context()

    win._build_session_save_context = paused_context
    win._mark_session_dirty()
    target = tmp_path / "async.json"
    try:
        assert win._start_async_session_snapshot_save(str(target), tail) is True
        assert entered.wait(timeout=5)
        tail[0].update_text("저장 도중 새롭게 수집된 문장")
        win._mark_session_dirty()
    finally:
        release.set()
    kind, info = messages.get(timeout=10)
    assert kind == "session_save_done", info
    assert info["snapshot_revision"] == 1
    assert win._clear_session_dirty(saved_revision=info["snapshot_revision"]) is False
    assert win._session_dirty is True
    assert json.loads(target.read_text(encoding="utf-8"))["subtitles"] == [entry.to_dict() for entry in expected]
    loaded = win.db.load_session(info["db_session_id"])
    assert loaded is not None
    assert [row["text"] for row in loaded["subtitles"]] == [entry.text for entry in expected]
