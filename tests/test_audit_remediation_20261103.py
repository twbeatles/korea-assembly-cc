"""Audit fixes exercised through real Qt, core pipeline, files and DB boundaries."""
from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PySide6.QtWidgets import QApplication

from core import file_io
from core.config import Config
from core.models import SubtitleEntry
from core.resource_budget import ResourceLimitExceeded
from core.update_installer import UpdateApplyError, apply_staged_update
from core.update_installer import recover_update_backup, write_update_recovery_launcher
from ui.main_window import MainWindow
from ui.main_window_common import WorkerQueueMessage
from ui.main_window_impl import capture_browser

NOW = datetime(2026, 11, 3, 10)


@pytest.fixture
def qt_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    for field, relative in {
        "STORAGE_DIR": ".", "SESSION_DIR": "sessions", "BACKUP_DIR": "backups",
        "REALTIME_DIR": "realtime", "RUNTIME_SESSION_DIR": "backups/runtime",
        "DATABASE_PATH": "test.db", "RECOVERY_STATE_FILE": "recovery.json",
        "PRESET_FILE": "presets.json", "URL_HISTORY_FILE": "history.json",
        "SETTINGS_INI_PATH": "settings.ini", "LOG_DIR": "logs",
    }.items():
        monkeypatch.setattr(Config, field, str(tmp_path / relative))
    monkeypatch.setattr(MainWindow, "_setup_tray", lambda self: None)
    monkeypatch.setattr(MainWindow, "_prompt_session_recovery_if_available", lambda self: None)
    monkeypatch.setattr(MainWindow, "_notify_pending_update_result", lambda self: None)
    win = cast(Any, MainWindow)()
    notices: list[tuple] = []
    win._show_toast = lambda *args, **_kwargs: notices.append(args)
    win.audit_notices = notices
    try:
        yield win, app
    finally:
        win.is_running = False
        win._begin_background_shutdown()
        win._wait_active_background_threads(timeout=5)
        win._clear_session_dirty()
        win.close()
        win.deleteLater()
        app.processEvents()


def payload(text: str, key: str = "row1", *, unstable: bool = False) -> dict:
    return {"raw": text, "rows": [{"nodeKey": key, "text": text,
            "speakerChannel": "primary", "unstableKey": unstable}],
            "selector": "#viewSubtit .smi_word", "source_mode": "smi-window"}


def wait_load(win, app):
    deadline = time.monotonic() + 5
    while win._session_load_in_progress and time.monotonic() < deadline:
        app.processEvents()
        win._process_message_queue()
        time.sleep(0.005)
    assert not win._session_load_in_progress


@pytest.mark.parametrize("unstable", [False, True])
def test_real_dict_commit_writes_realtime_and_alerts_once(qt_window, tmp_path, unstable):
    win, app = qt_window
    win.is_running = True
    win._rebuild_alert_keyword_cache(["예산"], update_settings=False)
    target = tmp_path / "실시간 기록.txt"
    win.realtime_file = target.open("w", encoding="utf-8")
    event = payload("예산안을 심사합니다", unstable=unstable)
    win._handle_message("preview", event)
    if unstable:
        # Exercise the actual QTimer connection and Qt event loop.
        deadline = time.monotonic() + 2
        while not win.subtitles and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
    assert [entry.text for entry in win.subtitles] == [event["raw"]]
    assert target.read_text(encoding="utf-8").count(event["raw"]) == 1
    win._handle_message("preview", event)
    win._handle_message("keepalive", event["raw"])
    assert target.read_text(encoding="utf-8").count(event["raw"]) == 1
    assert sum("키워드 감지" in str(args) for args in win.audit_notices) == 1


def test_row_extension_and_correction_have_explicit_realtime_records(qt_window, tmp_path):
    win, _app = qt_window
    win.is_running = True
    win._rebuild_alert_keyword_cache(["예산", "의결"], update_settings=False)
    path = tmp_path / "realtime.txt"
    win.realtime_file = path.open("w", encoding="utf-8")
    win._apply_structured_preview_payload(payload("예산안"), now=NOW)
    win._apply_structured_preview_payload(payload("예산안을 심사합니다"), now=NOW + timedelta(seconds=1))
    win._apply_structured_preview_payload(payload("예산안을 의결합니다"), now=NOW + timedelta(seconds=2))
    text = path.read_text(encoding="utf-8")
    assert "+ 을 심사합니다" in text
    assert f"[정정 {win.subtitles[0].entry_id}] 예산안을 의결합니다" in text
    assert sum("키워드 감지" in str(args) for args in win.audit_notices) == 2
    assert len(win.subtitles) == 1


def test_distinct_stable_rows_preserve_identical_utterances_and_speaker(qt_window):
    win, _app = qt_window
    first = payload("네", "row1")
    second = payload("네", "row2")
    second["rows"][0]["speakerChannel"] = "secondary"
    win._apply_structured_preview_payload(first, now=NOW)
    win._apply_structured_preview_payload(second, now=NOW + timedelta(seconds=1))
    win._apply_structured_preview_payload(second, now=NOW + timedelta(seconds=2))
    assert [entry.text for entry in win.subtitles] == ["네", "네"]
    assert [entry.speaker_channel for entry in win.subtitles] == ["primary", "secondary"]
    assert len({entry.entry_id for entry in win.subtitles}) == 2


def test_recovery_can_restore_when_normal_executable_is_missing(tmp_path):
    target, backup = tmp_path / "app.exe", tmp_path / "app.bak"
    backup.write_bytes(b"original")
    assert recover_update_backup(target, backup)
    assert target.read_bytes() == b"original"
    backup.write_bytes(b"other")
    assert not recover_update_backup(target, backup)
    assert target.read_bytes() == b"original" and backup.read_bytes() == b"other"
    with pytest.raises(ValueError):
        recover_update_backup(target, tmp_path / "outside" / "backup.bak")


def test_recovery_launcher_handles_unicode_and_batch_metacharacters(tmp_path):
    root = tmp_path / "한글 공백 %name% & !"
    root.mkdir()
    helper = root / "helper.exe"
    launcher = write_update_recovery_launcher(helper, target=root / "app.exe",
        backup=root / "app.bak", result_file=root / "result.json")
    text = launcher.read_text(encoding="utf-8")
    assert "DisableDelayedExpansion" in text and "chcp 65001" in text
    assert '"--recover-update"' in text and "%%name%%" in text
    assert str(helper).replace("%", "%%") in text


def test_recovery_cli_restores_before_gui_startup(tmp_path):
    from tests.test_config_paths import _load_entrypoint_module
    entrypoint = _load_entrypoint_module()
    target, backup, result = (tmp_path / name for name in ("app.exe", "app.bak", "result.json"))
    backup.write_bytes(b"old")
    assert entrypoint.main(["--recover-update", "--update-target", str(target),
        "--update-backup", str(backup), "--update-result-file", str(result),
        "--update-no-relaunch"]) == 0
    assert target.read_bytes() == b"old"
    assert json.loads(result.read_text(encoding="utf-8"))["status"] == "rolled_back"


@pytest.mark.parametrize("action", ["srt", "hydrate"])
def test_missing_archive_preserves_export_and_current_session(qt_window, tmp_path, monkeypatch, action):
    from ui.main_window_impl import persistence_exports_text, persistence_runtime_hydration
    win, _app = qt_window
    win._apply_structured_preview_payload(payload("기존 tail"), now=NOW)
    original_ids = [entry.entry_id for entry in win.subtitles]
    win._runtime_session_root = tmp_path
    win._runtime_segment_manifest = [{"path": "missing.json", "entry_count": 1}]
    win._runtime_archived_count = 1
    if action == "srt":
        output = tmp_path / "existing.srt"
        output.write_bytes(b"original")
        monkeypatch.setattr(persistence_exports_text.QFileDialog, "getSaveFileName", lambda *args: (str(output), ""))
        win._save_srt()
        win._wait_active_background_threads(timeout=5)
        win._process_message_queue()
        assert output.read_bytes() == b"original"
        assert any("저장 실패" in str(args) for args in win.audit_notices)
    else:
        errors = []
        monkeypatch.setattr(persistence_runtime_hydration.QMessageBox, "critical", lambda *args: errors.append(args))
        resumed = []
        win._run_after_full_session_hydrated("편집", lambda: resumed.append(True))
        win._wait_active_background_threads(timeout=5)
        win._process_message_queue()
        assert errors and not resumed and not win._hydrate_in_progress
    assert [entry.entry_id for entry in win.subtitles] == original_ids


def test_real_commit_write_failure_disables_realtime(qt_window):
    win, _app = qt_window
    class DeniedFile:
        def write(self, _line):
            raise PermissionError("test sharing lock")
        def close(self):
            pass
    win.realtime_file = DeniedFile()
    win._realtime_save_active = True
    win._apply_structured_preview_payload(payload("정상 수집 자막"), now=NOW)
    assert len(win.subtitles) == 1
    assert not win._realtime_save_active
    assert win.realtime_file is None


@pytest.mark.parametrize("fault", ["missing", "text", "count", "skipped", "path"])
@pytest.mark.parametrize("cached", [False, True])
def test_runtime_fault_cannot_replace_snapshot(qt_window, tmp_path, fault, cached):
    win, _app = qt_window
    root = tmp_path / "archive"
    root.mkdir()
    entry = SubtitleEntry("보관된 자막", NOW)
    fingerprint = win._build_runtime_entries_fingerprint([entry])
    segment = root / "segment_000001.json"
    data = {"subtitles": [entry.to_dict()], **fingerprint}
    file_io.atomic_write_json(segment, data)
    manifest = {"path": segment.name, **fingerprint}
    win._runtime_session_root = root
    win._runtime_segment_manifest = [manifest]
    if cached:
        assert win._load_runtime_segment_entries(manifest)[0].text == entry.text
    if fault == "missing":
        segment.unlink()
    elif fault == "path":
        manifest["path"] = "../outside.json"
    else:
        if fault == "text":
            data["subtitles"][0]["text"] = "변조된 자막"
        elif fault == "count":
            data["entry_count"] = 2
        else:
            data["subtitles"].append({"text": "timestamp 없음"})
        file_io.atomic_write_json(segment, data)
    output = tmp_path / "기존 세션.json"
    output.write_bytes(b"original")
    with pytest.raises(cast(Any, (ValueError, FileNotFoundError))):
        win._write_session_snapshot(str(output), [SubtitleEntry("tail", NOW)], include_db=False)
    assert output.read_bytes() == b"original"
    assert not list(tmp_path.glob(".기존 세션.json.*.tmp"))


def test_json_entry_limit_and_late_cancel_preserve_current_session(qt_window, tmp_path, monkeypatch):
    win, app = qt_window
    win._apply_structured_preview_payload(payload("기존 내용"), now=NOW)
    current = win.subtitles[0].entry_id
    path = tmp_path / "session.json"
    file_io.atomic_write_json(path, {"version": Config.VERSION, "subtitles": [
        SubtitleEntry("첫 자막", NOW).to_dict(), SubtitleEntry("둘째 자막", NOW).to_dict()]})
    monkeypatch.setattr(Config, "SESSION_RESOURCE_MAX_ENTRIES", 1)
    errors = []
    from ui.main_window_impl import pipeline_messages
    monkeypatch.setattr(pipeline_messages._pipeline_public().QMessageBox, "critical", lambda *args: errors.append(args))
    assert win._start_session_load_from_path(str(path))
    wait_load(win, app)
    assert errors and win.subtitles[0].entry_id == current
    monkeypatch.setattr(Config, "SESSION_RESOURCE_MAX_ENTRIES", 2)
    # Cancel after the worker has queued done but before the GUI consumes it.
    win.queue_timer.stop()
    assert win._start_session_load_from_path(str(path))
    win._wait_active_background_threads(timeout=5)
    win._session_load_cancel_event.set()
    wait_load(win, app)
    assert win.subtitles[0].entry_id == current
    assert win._session_load_progress_dialog is None
    assert win._start_session_load_from_path(str(path))
    wait_load(win, app)
    assert [entry.text for entry in win.subtitles] == ["첫 자막", "둘째 자막"]


def test_bounded_json_read_checks_cancellation_between_chunks(tmp_path):
    path = tmp_path / "large.json"
    file_io.atomic_write_json(path, {"padding": "x" * (2 * 1024 * 1024)})
    cancel = threading.Event()
    progress = []
    def observed(current, total):
        progress.append((current, total))
        cancel.set()
    with pytest.raises(ResourceLimitExceeded, match="취소"):
        file_io.read_limited_json_file(path, max_bytes=4 * 1024 * 1024,
                                      cancel_check=cancel.is_set, progress=observed)
    assert len(progress) == 1


@pytest.mark.requires_subprocess
def test_offline_browser_worker_json_db_export_and_reload(qt_window, tmp_path, monkeypatch):
    from tests.test_support.browser_dom import BrowserDom
    from ui.main_window_impl import persistence_exports_text
    win, app = qt_window
    browser = BrowserDom()
    original_probe = win._read_subtitle_probe_by_selectors
    reads = []
    target_text = "예산안을 의결합니다"
    try:
        browser.load('<div id="viewSubtit"><p class="smi_word stxt1">예산안을 심사합니다</p></div>')
        win._open_initial_capture_driver_session = lambda *args: (
            browser, "https://assembly.webcast.go.kr/main/player.asp?xcode=10",
            ["#viewSubtit .smi_word"], "#viewSubtit .smi_word", False, (),
        )
        win._inject_mutation_observer = lambda *args: (False, ())
        win._dispose_driver = lambda *args, **kwargs: None
        def probe(*args, **kwargs):
            result = original_probe(*args, **kwargs)
            reads.append(result)
            if len(reads) == 1:
                browser.execute_script("document.querySelector('p').textContent=arguments[0]; return true;", target_text)
            else:
                win.stop_event.set()
            return result
        win._read_subtitle_probe_by_selectors = probe
        win.is_running = True
        run = win._activate_capture_run()
        win._extraction_worker("https://assembly.webcast.go.kr/main/player.asp?xcode=10",
                               "#viewSubtit .smi_word", True, run_id=run)
        win._process_message_queue()
        assert len(reads) == 2
        assert [entry.text for entry in win.subtitles] == [target_text]
        saved = tmp_path / "session.json"
        info = win._write_session_snapshot(str(saved), win._build_persistent_entries_snapshot())
        assert info["db_saved"]
        serialized = json.loads(saved.read_text(encoding="utf-8"))["subtitles"]
        loaded = win.db.load_session(info["db_session_id"])
        assert [SubtitleEntry.from_dict(row).to_dict() for row in loaded["subtitles"]] == serialized
        srt = tmp_path / "captions.srt"
        monkeypatch.setattr(persistence_exports_text.QFileDialog, "getSaveFileName", lambda *args: (str(srt), ""))
        win._save_srt()
        win._wait_active_background_threads(timeout=5)
        assert target_text in srt.read_text(encoding="utf-8")
        win.is_running = False
        assert win._start_session_load_from_path(str(saved))
        wait_load(win, app)
        assert [entry.to_dict() for entry in win.subtitles] == serialized
    finally:
        browser.close()


@pytest.mark.parametrize("smoke_ok", [False, True])
def test_staged_cleanup_cannot_bypass_smoke_or_rollback(tmp_path, monkeypatch, smoke_ok):
    target, staged, backup = (tmp_path / name for name in ("app.exe", "staged.exe", "app.bak"))
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    unlink = Path.unlink
    def deny_staged(path, *args, **kwargs):
        if path == staged:
            raise PermissionError("test sharing lock")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", deny_staged)
    calls = []
    def smoke(path):
        calls.append(path.read_bytes())
        return smoke_ok
    args: dict[str, Any] = dict(target=target, staged=staged, backup=backup,
                expected_size=3, expected_sha256=hashlib.sha256(b"new").hexdigest(), smoke_runner=smoke)
    if smoke_ok:
        apply_staged_update(**args)
    else:
        with pytest.raises(UpdateApplyError, match="rolled back"):
            apply_staged_update(**args)
    assert calls == [b"new"]
    assert target.read_bytes() == (b"new" if smoke_ok else b"old")


@pytest.mark.parametrize("change", ["key", "speaker", "frame", "selector", "spacing", "same"])
@pytest.mark.parametrize("observer", [False, True])
def test_worker_observes_structure_even_when_compact_text_is_unchanged(monkeypatch, change, observer):
    win = cast(Any, MainWindow.__new__(MainWindow))
    win.message_queue = queue.Queue()
    class Stop:
        count = 0
        def is_set(self):
            return self.count >= 2
        def wait(self, timeout=None):
            self.count += 1
            return self.is_set()
    clock = iter(range(100, 200))
    monkeypatch.setattr(capture_browser, "time", SimpleNamespace(time=lambda: next(clock)))
    win.stop_event = Stop()
    win.auto_reconnect_enabled = False
    win._build_chrome_options = lambda _headless: None
    win._open_initial_capture_driver_session = lambda *args: (object(), "url", [".row"], ".row", observer, ())
    win._check_driver_health = lambda _driver: (1, "ok")
    win._collect_observer_changes = lambda *args: ["text changed"]
    win._inject_mutation_observer = lambda *args: (observer, ())
    win._normalize_subtitle_text_for_option = lambda text: str(text or "")
    win._dispose_driver = lambda *args, **kwargs: None
    probes: list[dict[str, Any]] = [dict(text="네 네", found=True, matched_selector=".row", frame_path=[],
                   rows=[dict(nodeKey="row1", text="네 네", speakerChannel="primary")]) for _ in range(2)]
    if change == "key": probes[1]["rows"][0]["nodeKey"] = "row2"
    if change == "speaker": probes[1]["rows"][0]["speakerChannel"] = "secondary"
    if change == "frame": probes[1]["frame_path"] = [0]
    if change == "selector": probes[1]["matched_selector"] = ".other"
    if change == "spacing":
        probes[1]["text"] = "네네"
        probes[1]["rows"][0]["text"] = "네네"
    iterator = iter(probes)
    win._read_subtitle_probe_by_selectors = lambda *args, **kwargs: next(iterator)
    win._extraction_worker("url", ".row", False, run_id=1)
    events = [(item.msg_type, item.payload) if isinstance(item, WorkerQueueMessage) else item
              for item in win.message_queue.queue]
    previews = [p for kind, p in events if kind == "preview"]
    assert len(previews) == (1 if change == "same" else 2)
    assert any(kind == "finished" and p["success"] for kind, p in events)
