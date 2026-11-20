"""Real Qt regressions for save, final commit, terminal ordering and recovery."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog

from core.config import Config
from core.file_io import atomic_write_json
from core.models import SubtitleEntry
from core.recovery_candidates import discover_recovery_candidates
from core.resource_budget import ResourceLimitExceeded
from ui.main_window_common import MainWindowMessageQueue
from ui.main_window_impl import persistence_session_save
from ui.main_window_impl.persistence_session_recovery import MainWindowPersistenceSessionRecoveryMixin
from tests.test_audit_remediation_20261103 import qt_window, payload, NOW

def test_terminal_overflow_preserves_pending_previews(qt_window):
    win, app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    run = win._activate_capture_run()
    win.message_queue = MainWindowMessageQueue(win, maxsize=1)
    win._emit_worker_message('preview', payload('마지막 발언입니다', 'row1'), run_id=run)
    win._emit_worker_message('finished', {'success': True, 'finalize_preview': True}, run_id=run)
    win._process_message_queue()
    assert [entry.text for entry in win.subtitles] == ['마지막 발언입니다']


def test_finished_preserves_coalesced_latest_preview(qt_window):
    win, app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    run = win._activate_capture_run()
    win.message_queue = MainWindowMessageQueue(win, maxsize=1)
    win._emit_worker_message('preview', payload('처음 발언입니다', 'row1'), run_id=run)
    win._emit_worker_message('preview', payload('최종 발언입니다', 'row2'), run_id=run)
    # Consume one queued preview, leaving room for finished; the latest preview is coalesced.
    item = win.message_queue.get_nowait()
    kind, data = win._unwrap_message_item(item)
    win._handle_message(kind, data)
    win._emit_worker_message('finished', {'success': True, 'finalize_preview': True}, run_id=run)
    win._process_message_queue()
    assert [entry.text for entry in win.subtitles] == ['처음 발언입니다', '최종 발언입니다']


def test_terminal_overflow_at_production_capacity(qt_window):
    win, app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    run = win._activate_capture_run()
    from core.config import Config
    assert win.message_queue._queue.maxsize == Config.MESSAGE_QUEUE_MAX_SIZE == 500
    for i in range(499):
        win._emit_worker_message('status', str(i), run_id=run)
    win._emit_worker_message('preview', payload('끝 발언', 'row-last'), run_id=run)
    win._emit_worker_message('finished', {'success': True, 'finalize_preview': True}, run_id=run)
    for _ in range(20):
        win._process_message_queue()
    assert [e.text for e in win.subtitles] == ['끝 발언']


def test_final_fallback_is_written_and_alerted(qt_window, tmp_path):
    win, app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    win._rebuild_alert_keyword_cache(['예산'], update_settings=False)
    target = tmp_path / 'realtime.txt'
    win.realtime_file = target.open('w', encoding='utf-8')
    win._handle_message('preview', payload('예산안을 의결합니다', unstable=True))
    assert not win.subtitles
    win._handle_message('finished', {'success': True, 'finalize_preview': True})
    assert [entry.text for entry in win.subtitles] == ['예산안을 의결합니다']
    assert '예산안을 의결합니다' in target.read_text(encoding='utf-8')
    assert any('키워드 감지' in str(args) for args in win.audit_notices)


def test_final_fallback_marks_dirty_and_records_alert(qt_window, tmp_path):
    win, app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    win._rebuild_alert_keyword_cache(['예산'], update_settings=False)
    win._handle_message('preview', payload('예산안을 의결합니다', unstable=True))
    before = win._get_session_revision()
    win._handle_message('finished', {'success': True, 'finalize_preview': True})
    observed = {'texts': [e.text for e in win.subtitles], 'dirty': win._has_dirty_session(), 'revision_delta': win._get_session_revision() - before, 'keyword_notices': sum('키워드 감지' in str(args) for args in win.audit_notices)}
    assert observed['dirty'] and observed['revision_delta'] > 0 and observed['keyword_notices'] == 1


@pytest.mark.parametrize("archive_flush", [False, True])
def test_capture_during_real_modal_save_keeps_dirty(qt_window, tmp_path, monkeypatch, archive_flush):
    win, app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    if archive_flush:
        monkeypatch.setattr(Config, "RUNTIME_ACTIVE_TAIL_ENTRIES", 1)
        monkeypatch.setattr(Config, "RUNTIME_SEGMENT_FLUSH_THRESHOLD", 1)
        win._start_runtime_session_archive(run_id=win._activate_capture_run())
    win._apply_structured_preview_payload(payload('첫 발언', 'row1'), now=NOW)
    target = tmp_path / 'snapshot.json'
    def modal_save(*args, **kwargs):
        dialog = QFileDialog(win, 'Audit Save')
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.selectFile(str(target))
        def capture_then_accept():
            win._apply_structured_preview_payload(payload('새 발언', 'row2'), now=NOW + timedelta(seconds=1))
            if archive_flush:
                win._wait_active_background_threads(timeout=5)
                win._process_message_queue()
                assert win._runtime_archived_count == 1
            dialog.accept()
        QTimer.singleShot(0, capture_then_accept)
        assert dialog.exec() == QFileDialog.DialogCode.Accepted
        return str(target), 'JSON (*.json)'
    monkeypatch.setattr(persistence_session_save.QFileDialog, 'getSaveFileName', modal_save)
    win._save_session()
    win._wait_active_background_threads(timeout=5)
    win._process_message_queue()
    saved = json.loads(target.read_text(encoding='utf-8'))
    actual = {'memory': [e.text for e in win._iter_full_session_entries(win._build_persistent_entries_snapshot())], 'saved': [e['text'] for e in saved['subtitles']], 'dirty': win._has_dirty_session()}
    assert actual['saved'] == actual['memory'] == ['첫 발언', '새 발언']
    assert not actual['dirty']
    stored = win.db.load_session(win.current_db_session_id)
    assert [e['text'] for e in stored['subtitles']] == actual['saved']


def wait_scan(win, app):
    deadline = time.monotonic() + 5
    while win._recovery_scan_in_progress and time.monotonic() < deadline:
        app.processEvents()
        win._process_message_queue()
        time.sleep(0.005)
    assert not win._recovery_scan_in_progress


def test_manual_recovery_discovers_without_pointer_and_startup_stays_quiet(qt_window):
    win, app = qt_window
    backup = Path(Config.BACKUP_DIR) / "backup_20261105.json"
    atomic_write_json(backup, {"version": Config.VERSION, "subtitles": [SubtitleEntry("복구할 자막").to_dict()]})
    assert not Path(Config.RECOVERY_STATE_FILE).exists()
    shown = []
    win._present_recovery_candidates = lambda candidates, state, **kwargs: shown.extend(candidates)
    MainWindowPersistenceSessionRecoveryMixin._prompt_session_recovery_if_available(win)
    assert not shown and not win.__dict__.get("_recovery_scan_in_progress")
    win._recover_session()
    wait_scan(win, app)
    assert [candidate.path for candidate in shown] == [backup.resolve()]


def test_recovery_scan_late_cancel_keeps_current_session(qt_window):
    win, app = qt_window
    win._apply_structured_preview_payload(payload("현재 내용"), now=NOW)
    shown = []
    win._present_recovery_candidates = lambda *args, **kwargs: shown.append(True)
    assert win._start_recovery_scan(manual=True)
    win._wait_active_background_threads(timeout=5)
    win._recovery_scan_cancel.set()
    win._process_message_queue()
    assert not shown and not win._recovery_scan_in_progress
    assert [entry.text for entry in win.subtitles] == ["현재 내용"]


@pytest.mark.parametrize("resource", ["candidates", "total_bytes", "cancelled", "paths"])
def test_recovery_scan_has_global_budgets_and_cancellation(tmp_path, resource):
    for index in range(3):
        atomic_write_json(tmp_path / f"backup_{index}.json", {"subtitles": []})
    options: dict[str, Any] = {}
    if resource == "candidates":
        options["max_candidates"] = 2
    elif resource == "total_bytes":
        options["max_total_bytes"] = 1
    elif resource == "paths":
        (tmp_path / "runtime" / "empty").mkdir(parents=True)
        options["max_paths"] = 1
    else:
        options["cancel_check"] = lambda: True
    with pytest.raises(ResourceLimitExceeded) as raised:
        discover_recovery_candidates(recovery_state_file=tmp_path / "missing.json",
            backup_dir=tmp_path, runtime_session_dir=tmp_path / "runtime", **options)
    assert isinstance(raised.value, ResourceLimitExceeded)
    assert raised.value.resource == resource


def test_save_worker_uses_detached_metadata_and_preserves_newer_revision(qt_window, tmp_path):
    win, app = qt_window
    win._set_capture_source_metadata("https://assembly.webcast.go.kr/main/player.asp?xcode=10", "본회의")
    win._apply_structured_preview_payload(payload("저장할 내용"), now=NOW)
    win._wait_active_background_threads(timeout=5)
    queued = []
    win._start_background_thread = lambda worker, name: queued.append(worker) or True
    path = tmp_path / "snapshot.json"
    lineage = win._ensure_session_lineage_id()
    revision = win._get_session_revision()
    assert win._start_async_session_snapshot_save(str(path), win._build_persistent_entries_snapshot())
    win._set_capture_source_metadata("https://assembly.webcast.go.kr/main/player.asp?xcode=20", "다른 위원회")
    win.subtitles[0].update_text("나중 수정")
    win._mark_session_dirty()
    win.current_session_lineage_id = "new-lineage"
    queued[0]()
    win._process_message_queue()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["committee_name"] == "본회의" and saved["lineage_id"] == lineage
    assert saved["snapshot_revision"] == revision
    assert [item["text"] for item in saved["subtitles"]] == ["저장할 내용"]
    assert win._has_dirty_session()


@pytest.mark.parametrize("terminal", ["finished", "stop"])
def test_final_fallback_is_committed_once_and_retains_recovery(qt_window, tmp_path, terminal):
    win, app = qt_window
    win.queue_timer.stop()
    win.is_running = True
    win._activate_capture_run()
    win._rebuild_alert_keyword_cache(["예산"], update_settings=False)
    target = tmp_path / "final.txt"
    win.realtime_file = target.open("w", encoding="utf-8")
    win._handle_message("preview", payload("예산을 의결합니다", unstable=True))
    if terminal == "stop":
        win._stop()
        win._stop()
    else:
        win._handle_message("finished", {"success": True})
        win._handle_message("finished", {"success": True})
    win._wait_active_background_threads(timeout=5)
    assert [entry.text for entry in win.subtitles] == ["예산을 의결합니다"]
    assert target.read_text(encoding="utf-8").count("예산을 의결합니다") == 1
    assert win._has_dirty_session() and win._runtime_tail_revision > 0
    assert Path(Config.RECOVERY_STATE_FILE).exists()
    assert sum("키워드 감지" in str(args) for args in win.audit_notices) == 1


def test_late_preview_from_finished_run_cannot_modify_new_capture(qt_window):
    win, app = qt_window
    win.is_running = True
    old = win._activate_capture_run()
    win._emit_worker_message("preview", payload("첫 발언"), run_id=old)
    win._emit_worker_message("finished", {"success": True}, run_id=old)
    win._process_message_queue()
    win._replace_subtitles_and_refresh([])
    win.is_running = True
    new = win._activate_capture_run()
    win._emit_worker_message("preview", payload("늦은 이전 발언"), run_id=old)
    win._emit_worker_message("preview", payload("새 수집 발언"), run_id=new)
    win._process_message_queue()
    assert [entry.text for entry in win.subtitles] == ["새 수집 발언"]


@pytest.mark.skipif(not os.environ.get("KACC_SOAK_SECONDS"), reason="KACC_SOAK_SECONDS로 명시적 soak 실행")
def test_offline_capture_soak(qt_window, tmp_path, monkeypatch):
    """Opt-in queue/thread/archive/save/reload soak, independent of live TV."""
    win, app = qt_window
    duration = float(os.environ["KACC_SOAK_SECONDS"])
    assert 0 < duration <= 86400
    monkeypatch.setattr(Config, "RUNTIME_ACTIVE_TAIL_ENTRIES", 50)
    monkeypatch.setattr(Config, "RUNTIME_SEGMENT_FLUSH_THRESHOLD", 100)
    win.is_running = True
    run = win._activate_capture_run()
    win._start_runtime_session_archive(run_id=run)
    deadline = time.monotonic() + duration
    count = 0
    peak_active = 0
    while time.monotonic() < deadline:
        def produce(start=count):
            for index in range(start, start + 5):
                win._emit_worker_message("preview", payload(f"예산 검토 발언 {index} 처리", f"row-{index}"), run_id=run)
        producer = threading.Thread(target=produce)
        producer.start()
        while producer.is_alive():
            app.processEvents()
            win._process_message_queue()
            producer.join(0.001)
        count += 5
        win._process_message_queue()
        win._wait_active_background_threads(timeout=5)
        win._process_message_queue()
        peak_active = max(peak_active, len(win.subtitles))
        assert win._get_global_subtitle_count() == count
        time.sleep(0.01)
    win._emit_worker_message("finished", {"success": True}, run_id=run)
    win._process_message_queue()
    win._wait_active_background_threads(timeout=5)
    win._process_message_queue()
    path = tmp_path / "soak-session.json"
    info = win._write_session_snapshot(str(path), win._build_persistent_entries_snapshot())
    assert info["saved_count"] == count and info["db_saved"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [row["text"] for row in saved["subtitles"]] == [f"예산 검토 발언 {index} 처리" for index in range(count)]
    stored = win.db.load_session(info["db_session_id"])
    assert len(stored["subtitles"]) == count
    assert peak_active <= 105
    assert win._start_session_load_from_path(str(path))
    from tests.test_audit_remediation_20261103 import wait_load
    wait_load(win, app)
    assert len(win.subtitles) == count
