"""Additional audit: search, document output, presets, merge and stale reflow."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core import file_io
from core.config import Config
from core.models import SubtitleEntry
from core.resource_budget import ResourceLimitExceeded
from tests.test_audit_remediation_20261103 import qt_window
from ui.main_window_impl import persistence_exports_documents as documents
from ui.main_window_impl import persistence_tools
from ui.main_window_impl.ui import history_presets

NOW = datetime(2026, 11, 3, 12)
URL = "https://assembly.webcast.go.kr/main/player.asp?xcode=10"


def test_archived_search_keeps_first_entry_index_and_selects_text(qt_window, tmp_path):
    win, app = qt_window
    archived = SubtitleEntry("첫 자막 검색어", NOW)
    segment = tmp_path / "segment.json"
    fingerprint = win._build_runtime_entries_fingerprint([archived])
    file_io.atomic_write_json(segment, {"subtitles": [archived.to_dict()], **fingerprint})
    win._runtime_session_root = tmp_path
    win._runtime_segment_manifest = [{"path": segment.name, "start_index": 0, **fingerprint}]
    win._runtime_archived_count = 1
    win._rebuild_runtime_segment_locator()
    win.subtitles.append(SubtitleEntry("다른 자막", NOW))
    win.search_input.setText("검색어")
    win._do_search()
    win._wait_active_background_threads(timeout=5)
    win._process_message_queue()
    app.processEvents()
    assert len(win.search_matches) == 1
    assert win.search_matches[0].entry_index == 0
    assert win.subtitle_text.textCursor().selectedText() == "검색어"


def test_search_selection_uses_qt_utf16_offsets_after_emoji(qt_window):
    win, app = qt_window
    win._replace_subtitles_and_refresh([SubtitleEntry("😀 검색어 끝", NOW)])
    win.search_input.setText("검색어")
    win._do_search()
    app.processEvents()
    assert win.subtitle_text.textCursor().selectedText() == "검색어"


@pytest.mark.parametrize("mode", ["false", "partial", "insert_false", "success"])
def test_hwp_failure_preserves_existing_file_and_reports_failure(qt_window, tmp_path, monkeypatch, mode):
    win, _app = qt_window
    win._replace_subtitles_and_refresh([SubtitleEntry("내보낼 자막", NOW)])
    target = tmp_path / "기존 파일.hwp"
    target.write_bytes(b"original-document")
    failures = []
    win._handle_hwp_save_failure = lambda error: failures.append(error)
    win.stop_event.set()  # Fail fast in the retry wait; no capture is running.
    handles = []
    class FakeHwp:
        def __init__(self):
            self.HParameterSet = SimpleNamespace(
                HInsertText=SimpleNamespace(HSet=None, Text=""),
                HFileOpenSave=SimpleNamespace(HSet=None, filename="", Format=""),
            )
            self.HAction = SimpleNamespace(GetDefault=lambda *args: None,
                Run=lambda *args: True, Execute=self.execute)
            self.XHwpWindows = SimpleNamespace(Item=lambda _index: SimpleNamespace(Visible=False))
            self.quit_called = False
        def RegisterModule(self, *args):
            pass
        def Quit(self):
            self.quit_called = True
        def execute(self, action, _settings):
            if action == "InsertText":
                return mode != "insert_false"
            if action == "FileSaveAs_S":
                destination = Path(self.HParameterSet.HFileOpenSave.filename)
                handles.append(destination)
                if mode == "partial":
                    destination.write_bytes(b"truncated")
                    raise OSError("COM save interrupted")
                if mode == "success":
                    destination.write_bytes(b"new-document")
                    return True
                return False
            return True
    hwp = FakeHwp()
    def optional(name):
        if name == "win32com.client":
            return SimpleNamespace(dynamic=SimpleNamespace(Dispatch=lambda _name: hwp))
        if name == "pythoncom":
            return SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
        raise ImportError(name)
    win._import_optional_module = optional
    monkeypatch.setattr(documents.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    win._save_hwp()
    win._wait_active_background_threads(timeout=5)
    win._process_message_queue()
    if mode == "success":
        assert target.read_bytes() == b"new-document" and not failures
        assert handles[0] != target and handles[0].parent == target.parent
    else:
        assert target.read_bytes() == b"original-document"
        assert failures
        assert not any("HWP 저장 완료" in str(args) for args in win.audit_notices)
    assert hwp.quit_called
    assert not list(tmp_path.glob(".기존 파일.*.hwp"))


def test_preset_save_failure_rolls_back_memory_and_never_announces_success(qt_window, monkeypatch):
    win, _app = qt_window
    win.custom_presets = {"기존": URL}
    win._save_committee_presets()
    original = Path(Config.PRESET_FILE).read_bytes()
    responses = iter([("새 프리셋", True), (URL, True)])
    monkeypatch.setattr(history_presets._ui_public().QInputDialog, "getText", lambda *args, **kwargs: next(responses))
    def denied(*args, **kwargs):
        raise PermissionError("read-only preset file")
    monkeypatch.setattr(history_presets._ui_public().utils, "atomic_write_json", denied)
    win._add_custom_preset()
    assert win.custom_presets == {"기존": URL}
    assert Path(Config.PRESET_FILE).read_bytes() == original
    assert not any("추가됨" in str(args) for args in win.audit_notices)


@pytest.mark.parametrize("operation", ["rename", "delete", "import"])
def test_all_preset_mutations_preserve_committed_state_on_io_failure(qt_window, tmp_path, monkeypatch, operation):
    win, _app = qt_window
    ui = history_presets._ui_public()
    win.custom_presets = {"기존": URL}
    win._save_committee_presets()
    original_file = Path(Config.PRESET_FILE).read_bytes()
    original_committee = dict(win.committee_presets)
    original_custom = dict(win.custom_presets)
    def denied(*args, **kwargs):
        raise PermissionError("preset write denied")
    monkeypatch.setattr(ui.utils, "atomic_write_json", denied)
    if operation == "import":
        source = tmp_path / "import.json"
        file_io.atomic_write_json(source, {"custom": {"가져온 프리셋": URL}, "committee": {"내 위원회": URL}})
        monkeypatch.setattr(ui.QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
        win._import_presets()
    else:
        choices = iter([("수정" if operation == "rename" else "삭제", True), ("기존", True)])
        inputs = iter([("새 이름", True), (URL, True)])
        monkeypatch.setattr(ui.QInputDialog, "getItem", lambda *args, **kwargs: next(choices))
        monkeypatch.setattr(ui.QInputDialog, "getText", lambda *args, **kwargs: next(inputs))
        monkeypatch.setattr(ui.QMessageBox, "question", lambda *args: ui.QMessageBox.StandardButton.Yes)
        win._manage_presets()
    assert win.custom_presets == original_custom and win.committee_presets == original_committee
    assert Path(Config.PRESET_FILE).read_bytes() == original_file
    assert not any(args[1] == "success" for args in win.audit_notices if len(args) > 1)


def test_renaming_preset_cannot_silently_overwrite_another(qt_window, monkeypatch):
    win, _app = qt_window
    win.custom_presets = {"A": URL, "B": URL.replace("10", "20")}
    original = dict(win.custom_presets)
    choices = iter([("수정", True), ("A", True)])
    inputs = iter([("B", True), (URL, True)])
    ui = history_presets._ui_public()
    monkeypatch.setattr(ui.QInputDialog, "getItem", lambda *args, **kwargs: next(choices))
    monkeypatch.setattr(ui.QInputDialog, "getText", lambda *args, **kwargs: next(inputs))
    monkeypatch.setattr(ui.QMessageBox, "question", lambda *args: ui.QMessageBox.StandardButton.No)
    win._manage_presets()
    assert win.custom_presets == original


def test_reflow_cannot_replace_newer_edits(qt_window, monkeypatch):
    win, _app = qt_window
    win._replace_subtitles_and_refresh([SubtitleEntry("기존. 문장.", NOW)])
    win._mark_session_dirty()
    pending = []
    win._start_background_thread = lambda worker, name: pending.append(worker) or True
    monkeypatch.setattr(persistence_tools.QMessageBox, "question", lambda *args: persistence_tools.QMessageBox.StandardButton.Yes)
    win._clean_newlines()
    assert len(pending) == 1
    win._replace_subtitles_and_refresh([SubtitleEntry("새롭게 편집한 내용", NOW)])
    win._mark_session_dirty()
    current = win.subtitles[0].entry_id
    pending[0]()
    win._process_message_queue()
    assert [entry.text for entry in win.subtitles] == ["새롭게 편집한 내용"]
    assert win.subtitles[0].entry_id == current
    assert not win._reflow_in_progress


def test_reflow_result_is_rejected_after_clean_session_replacement(qt_window, monkeypatch):
    win, _app = qt_window
    win._replace_subtitles_and_refresh([SubtitleEntry("이전 세션.", NOW)])
    pending = []
    win._start_background_thread = lambda worker, name: pending.append(worker) or True
    monkeypatch.setattr(persistence_tools.QMessageBox, "question", lambda *args: persistence_tools.QMessageBox.StandardButton.Yes)
    win._clean_newlines()
    revision = win._get_session_revision()
    win._replace_subtitles_and_refresh([SubtitleEntry("다른 clean 세션", NOW)])
    win._reset_session_revision(dirty=False)
    assert win._get_session_revision() == revision
    pending[0]()
    win._process_message_queue()
    assert [entry.text for entry in win.subtitles] == ["다른 clean 세션"]


def test_merge_applies_cumulative_entry_budget(qt_window, tmp_path, monkeypatch):
    win, _app = qt_window
    files = []
    for index in range(2):
        path = tmp_path / f"{index}.json"
        file_io.atomic_write_json(path, {"subtitles": [SubtitleEntry(f"자막{index}", NOW).to_dict()]})
        files.append(str(path))
    monkeypatch.setattr(Config, "SESSION_RESOURCE_MAX_ENTRIES", 1)
    with pytest.raises(ResourceLimitExceeded):
        win._merge_sessions(files, remove_duplicates=False)


def test_merge_accepts_runtime_manifest_and_rejects_cumulative_bytes(qt_window, tmp_path, monkeypatch):
    win, _app = qt_window
    root = tmp_path / "runtime"
    root.mkdir()
    entry = SubtitleEntry("runtime 자막", NOW)
    fingerprint = win._build_runtime_entries_fingerprint([entry])
    file_io.atomic_write_json(root / "segment.json", {"subtitles": [entry.to_dict()], **fingerprint})
    file_io.atomic_write_json(root / "tail_checkpoint.json", {"subtitles": [], **win._build_runtime_entries_fingerprint([])})
    manifest = root / "manifest.json"
    file_io.atomic_write_json(manifest, {"format": "runtime_session_manifest_v1",
        "segments": [{"path": "segment.json", **fingerprint}]})
    merged = win._merge_sessions([str(manifest)], strict=True)
    assert [item.text for item in merged] == [entry.text]
    monkeypatch.setattr(Config, "SESSION_RESOURCE_TOTAL_MAX_BYTES", manifest.stat().st_size + 1)
    with pytest.raises(ResourceLimitExceeded):
        win._merge_sessions([str(manifest)], strict=True)


def test_merge_dialog_rejects_partial_result_and_preserves_session(qt_window, tmp_path, monkeypatch):
    from ui.main_window_impl import database_dialogs_stats_merge as dialogs
    from PySide6.QtWidgets import QPushButton
    win, _app = qt_window
    win._replace_subtitles_and_refresh([SubtitleEntry("현재 세션", NOW)])
    win._clear_session_dirty()
    valid, broken = tmp_path / "valid.json", tmp_path / "broken.json"
    file_io.atomic_write_json(valid, {"subtitles": [SubtitleEntry("병합 입력", NOW).to_dict()]})
    broken.write_text("{broken", encoding="utf-8")
    errors = []
    monkeypatch.setattr(dialogs.QFileDialog, "getOpenFileNames", lambda *args: ([str(valid), str(broken)], ""))
    monkeypatch.setattr(dialogs.QMessageBox, "question", lambda *args: dialogs.QMessageBox.StandardButton.No)
    monkeypatch.setattr(dialogs.QMessageBox, "warning", lambda *args: errors.append(args))
    def execute(dialog):
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        buttons["➕ 파일 추가"].click()
        buttons["병합 실행"].click()
        return 0
    monkeypatch.setattr(dialogs.QDialog, "exec", execute)
    win._show_merge_dialog()
    assert [entry.text for entry in win.subtitles] == ["현재 세션"]
    assert errors
