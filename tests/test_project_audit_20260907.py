# -*- coding: utf-8 -*-
"""PROJECT_AUDIT 2026-09-07 후속 회귀."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from core.config import Config
from core.models import SubtitleEntry


def test_wait_for_process_exit_uses_injected_wait_impl() -> None:
    from core.process_wait import wait_for_process_exit

    calls: list[tuple[str, int, float]] = []

    def fake_wait(pid: int, timeout: float) -> bool:
        calls.append(("wait", pid, timeout))
        return True

    wait_for_process_exit(987654, timeout=1.0, wait_impl=fake_wait)
    assert calls == [("wait", 987654, 1.0)]


def test_wait_for_process_exit_access_denied_is_not_exit() -> None:
    from core.process_wait import ProcessWaitError, wait_for_process_exit

    def denied(_pid: int, _timeout: float) -> bool:
        raise PermissionError("OpenProcess SYNCHRONIZE denied")

    with pytest.raises(ProcessWaitError):
        wait_for_process_exit(123, timeout=0.1, wait_impl=denied)


def test_is_process_alive_uses_probe_impl() -> None:
    from core.process_wait import is_process_alive

    assert is_process_alive(1, probe_impl=lambda _pid: False) is False
    assert is_process_alive(1, probe_impl=lambda _pid: True) is True


def test_apply_update_script_does_not_call_os_kill() -> None:
    source = Path("scripts/apply_update.py").read_text(encoding="utf-8")
    assert "os.kill" not in source


def test_wait_for_parent_does_not_call_os_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    import os as os_mod

    import scripts.apply_update as apply_mod

    kill_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        os_mod,
        "kill",
        lambda pid, sig: kill_calls.append((int(pid), int(sig))),
    )
    apply_mod._wait_for_parent(42, timeout=0.01, wait_impl=lambda _pid, _timeout: True)
    assert kill_calls == []


def test_parent_wait_timeout_does_not_apply_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.apply_update as apply_mod

    applied: list[object] = []
    monkeypatch.setattr(
        apply_mod,
        "_wait_for_parent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("timed out")),
    )
    monkeypatch.setattr(
        apply_mod,
        "apply_staged_update",
        lambda **_kwargs: applied.append(True),
    )
    target = tmp_path / "app.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "app.exe.bak"
    result_file = tmp_path / "result.json"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    exit_code = apply_mod.main(
        [
            "--target",
            str(target),
            "--staged",
            str(staged),
            "--backup",
            str(backup),
            "--parent-pid",
            "1234",
            "--expected-sha256",
            "0" * 64,
            "--expected-size",
            "3",
            "--result-file",
            str(result_file),
        ]
    )
    assert exit_code == 1
    assert applied == []
    assert target.read_bytes() == b"old"
    assert '"status": "failed"' in result_file.read_text(encoding="utf-8")


class _FakeCloseEvent:
    def __init__(self) -> None:
        self.accepted = False
        self.ignored = False

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


class _VisibleTray:
    def isVisible(self) -> bool:
        return True

    def showMessage(self, *_args: object, **_kwargs: object) -> None:
        return None


def _update_ready_payload(tmp_path: Path) -> dict[str, object]:
    staged = tmp_path / "staged.exe"
    staged.write_bytes(b"new")
    return {
        "staged": str(staged),
        "target": str(tmp_path / "app.exe"),
        "backup": str(tmp_path / "app.exe.bak"),
        "sha256": "a" * 64,
        "size": 3,
        "result_file": str(tmp_path / "result.json"),
        "version": "99.0.0",
        "interactive": True,
    }


def test_update_install_dirty_cancel_does_not_launch_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ui.main_window_impl.ui.help as help_mod

    mw_mod = pytest.importorskip("ui.main_window")
    MainWindow = mw_mod.MainWindow
    launched: list[object] = []
    win = MainWindow.__new__(MainWindow)
    win._is_runtime_mutation_blocked = lambda *_a, **_k: False
    win._set_update_state = lambda *_a, **_k: None
    win._set_status = lambda *_a, **_k: None
    win._discard_staged_update = lambda *_a, **_k: None
    win._handle_update_failure = lambda *_a, **_k: None
    win._run_after_dirty_session_action = lambda *_a, **_k: False
    monkeypatch.setattr(
        help_mod.QMessageBox,
        "question",
        lambda *_a, **_k: help_mod.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        help_mod,
        "launch_update_helper",
        lambda **_k: launched.append(True),
    )
    monkeypatch.setattr(help_mod.QApplication, "quit", lambda: launched.append("quit"))

    MainWindow._handle_update_install_ready(win, _update_ready_payload(tmp_path))
    assert launched == []


def test_force_quit_for_update_skips_tray_minimize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mw_mod = pytest.importorskip("ui.main_window")
    MainWindow = mw_mod.MainWindow
    win = MainWindow.__new__(MainWindow)
    win.minimize_to_tray = True
    win.tray_icon = _VisibleTray()
    win.is_running = False
    win._force_quit_for_update = True
    win._session_save_in_progress = False
    win._exit_escalation_active = False
    captured: dict[str, object] = {}
    win._confirm_dirty_session_action = lambda _action, on_continue=None: (
        captured.setdefault("dirty", True) or True
    ) and (on_continue() or True) if callable(on_continue) else True
    win._begin_background_shutdown = lambda: captured.setdefault("shutdown", True)
    win._begin_db_worker_shutdown = lambda: None
    win._wait_for_background_threads_during_exit = lambda: None
    win._cleanup_runtime_session_archive = lambda **_k: None
    win._clear_recovery_state = lambda: None
    win._set_status = lambda *_a, **_k: None
    win._update_tray_status = lambda *_a, **_k: None
    win._save_setting_value = lambda *_a, **_k: True
    win.saveGeometry = lambda: b"g"
    win.saveState = lambda: b"s"
    win.queue_timer = type("T", (), {"stop": lambda self: None})()
    win.stats_timer = type("T", (), {"stop": lambda self: None})()
    win.backup_timer = type("T", (), {"stop": lambda self: None})()
    win._close_realtime_save_file = lambda: None
    win._reset_realtime_save_run_state = lambda: None
    win._take_current_driver = lambda: None
    win._cleanup_detached_drivers_with_timeout = lambda timeout=0.0: None
    win.db = None
    hidden: list[bool] = []
    win.hide = lambda: hidden.append(True)

    event = _FakeCloseEvent()
    MainWindow.closeEvent(win, event)
    assert hidden == []
    assert event.ignored is False
    assert event.accepted is True


def _write_runtime_entries_file(
    path: Path,
    *,
    format_name: str,
    subtitles: list[SubtitleEntry],
    extra: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {
        "format": format_name,
        "version": Config.VERSION,
        "created": "2026-09-07T12:00:00",
        "url": "https://assembly.example/runtime",
        "committee_name": "행정안전위원회",
        "subtitles": [item.to_dict() for item in subtitles],
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _runtime_loader_window() -> Any:
    mw_mod = pytest.importorskip("ui.main_window")
    win = mw_mod.MainWindow.__new__(mw_mod.MainWindow)
    win._runtime_segment_cache_entries_by_key = {}
    win._runtime_segment_cache_keys = []
    win._runtime_segment_search_text_cache = {}
    return win


def test_mismatched_manifest_and_tail_does_not_duplicate_without_warning(
    tmp_path: Path,
) -> None:
    mw_mod = pytest.importorskip("ui.main_window")
    MainWindow = mw_mod.MainWindow
    runtime_root = tmp_path / "runtime_mismatch"
    runtime_root.mkdir()
    entry_a = SubtitleEntry("발언 A", entry_id="id-A")
    entry_b = SubtitleEntry("발언 B", entry_id="id-B")
    _write_runtime_entries_file(
        runtime_root / "segment_000001.json",
        format_name="runtime_session_segment_v1",
        subtitles=[entry_a],
        extra={"entry_count": 1, "first_entry_id": "id-A", "last_entry_id": "id-A"},
    )
    _write_runtime_entries_file(
        runtime_root / "tail_checkpoint.json",
        format_name="runtime_tail_checkpoint_v1",
        subtitles=[entry_a, entry_b],
        extra={"archived_count": 0, "entry_count": 2, "first_entry_id": "id-A", "last_entry_id": "id-B"},
    )
    fingerprint = MainWindow._build_runtime_entries_fingerprint(
        _runtime_loader_window(), [entry_a]
    )
    tail_fp = MainWindow._build_runtime_entries_fingerprint(
        _runtime_loader_window(), [entry_a, entry_b]
    )
    (runtime_root / "segment_000001.json").write_text(
        json.dumps(
            {
                **json.loads((runtime_root / "segment_000001.json").read_text(encoding="utf-8")),
                **fingerprint,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (runtime_root / "tail_checkpoint.json").write_text(
        json.dumps(
            {
                **json.loads((runtime_root / "tail_checkpoint.json").read_text(encoding="utf-8")),
                **tail_fp,
                "archived_count": 0,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest_path = runtime_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format": "runtime_session_manifest_v1",
                "version": Config.VERSION,
                "created": "2026-09-07T12:00:00",
                "url": "https://assembly.example/runtime",
                "committee_name": "행정안전위원회",
                "archived_count": 1,
                "tail_checkpoint": "tail_checkpoint.json",
                "segments": [
                    {
                        "path": "segment_000001.json",
                        "entry_count": 1,
                        "first_entry_id": "id-A",
                        "last_entry_id": "id-A",
                        "entries_digest": fingerprint["entries_digest"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = MainWindow._load_runtime_manifest_payload(
        _runtime_loader_window(),
        manifest_path,
        allow_salvage=True,
    )
    ids = [str(entry.entry_id) for entry in payload["subtitles"]]
    assert ids != ["id-A", "id-A", "id-B"]
    assert ids == ["id-A", "id-B"]
    assert payload.get("recovery_warnings")


def test_same_text_different_entry_ids_are_kept(tmp_path: Path) -> None:
    mw_mod = pytest.importorskip("ui.main_window")
    MainWindow = mw_mod.MainWindow
    runtime_root = tmp_path / "runtime_repeat"
    runtime_root.mkdir()
    first = SubtitleEntry("같은 문장", entry_id="id-1")
    second = SubtitleEntry("같은 문장", entry_id="id-2")
    _write_runtime_entries_file(
        runtime_root / "tail_checkpoint.json",
        format_name="runtime_tail_checkpoint_v1",
        subtitles=[first, second],
        extra={"archived_count": 0},
    )
    manifest_path = runtime_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format": "runtime_session_manifest_v1",
                "version": Config.VERSION,
                "created": "2026-09-07T12:00:00",
                "archived_count": 0,
                "tail_checkpoint": "tail_checkpoint.json",
                "segments": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    payload = MainWindow._load_runtime_manifest_payload(
        _runtime_loader_window(),
        manifest_path,
        allow_salvage=True,
    )
    ids = [str(entry.entry_id) for entry in payload["subtitles"]]
    assert ids == ["id-1", "id-2"]
    assert [entry.text for entry in payload["subtitles"]] == ["같은 문장", "같은 문장"]


def test_segment_flush_commits_generation_tail_before_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    mw_mod = pytest.importorskip("ui.main_window")
    MainWindow = mw_mod.MainWindow
    win = MainWindow.__new__(MainWindow)
    win._runtime_session_root = tmp_path
    win._runtime_manifest_path = tmp_path / "manifest.json"
    win._runtime_segment_manifest = []
    win._runtime_next_segment_index = 1
    win._runtime_archived_count = 0
    win._runtime_archived_chars = 0
    win._runtime_archived_words = 0
    win._runtime_checkpoint_generation = 0
    win._runtime_archive_token = "token-a"
    win._runtime_archive_run_id = 1
    win._cached_total_chars = 10
    win._cached_total_words = 2
    win.subtitle_lock = threading.Lock()
    flushed = SubtitleEntry("세그먼트 A", entry_id="id-A")
    remaining = SubtitleEntry("tail B", entry_id="id-B")
    win.subtitles = [flushed, remaining]
    win._build_session_save_context = lambda: ("https://example/live", "행안위", 0)
    win._get_capture_quality_payload = lambda: {}
    win._ensure_session_lineage_id = lambda: "lineage"
    win._schedule_ui_refresh = lambda **_k: None
    win._maybe_schedule_runtime_segment_flush = lambda: False
    win._rebuild_runtime_segment_locator = lambda: None
    fingerprint = MainWindow._build_runtime_entries_fingerprint(win, [flushed])
    MainWindow._handle_runtime_segment_flush_done(
        win,
        {
            "archive_token": "token-a",
            "run_id": 1,
            "entry_count": 1,
            "char_count": 5,
            "word_count": 1,
            "segment_index": 1,
            "path": "segment_000001.json",
            "start_index": 0,
            **fingerprint,
        },
    )
    assert win._runtime_checkpoint_generation == 1
    tail_name = "tail_checkpoint_000001.json"
    assert (tmp_path / tail_name).is_file()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tail_checkpoint"] == tail_name
    assert manifest["checkpoint_generation"] == 1
    tail = json.loads((tmp_path / tail_name).read_text(encoding="utf-8"))
    assert tail["checkpoint_generation"] == 1
    assert [item["text"] for item in tail["subtitles"]] == ["tail B"]


def test_archive_owner_missing_file_is_not_alive(tmp_path: Path) -> None:
    from core.runtime_archive_owner import is_archive_owner_alive

    archive = tmp_path / "run_missing"
    archive.mkdir()
    assert is_archive_owner_alive(archive) is False


def test_archive_owner_live_pid_is_alive(tmp_path: Path) -> None:
    from core.runtime_archive_owner import is_archive_owner_alive, write_owner_file

    archive = tmp_path / "run_live"
    archive.mkdir()
    write_owner_file(archive, pid=1234, token="abc", run_id=1)
    assert is_archive_owner_alive(archive, alive_impl=lambda _pid: True) is True
    assert is_archive_owner_alive(archive, alive_impl=lambda _pid: False) is False


def test_start_runtime_archive_uses_unique_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mw_mod = pytest.importorskip("ui.main_window")
    MainWindow = mw_mod.MainWindow
    monkeypatch.setattr(Config, "RUNTIME_SESSION_DIR", str(tmp_path))

    class _FrozenDateTime:
        @staticmethod
        def now():
            from datetime import datetime as real_datetime

            return real_datetime(2026, 9, 7, 12, 0, 0)

    def _build() -> Any:
        win = MainWindow.__new__(MainWindow)
        win._runtime_session_root = None
        win._runtime_manifest_path = None
        win._load_recovery_state = lambda: None
        win._build_session_save_context = lambda: ("https://example/live", "행안위", 0)
        win._get_capture_quality_payload = lambda: {}
        win._ensure_session_lineage_id = lambda: "lineage"
        win._cancel_runtime_search = lambda: None
        win._invalidate_runtime_segment_caches = lambda: None
        return win

    monkeypatch.setattr(
        "ui.main_window_impl.persistence_runtime_archive.datetime",
        _FrozenDateTime,
    )
    first = _build()
    second = _build()
    MainWindow._start_runtime_session_archive(first, 1)
    MainWindow._start_runtime_session_archive(second, 1)
    assert first._runtime_session_root != second._runtime_session_root
    assert Path(first._runtime_session_root).is_dir()
    assert Path(second._runtime_session_root).is_dir()
    assert (Path(first._runtime_session_root) / "owner.json").is_file()
    assert (Path(second._runtime_session_root) / "owner.json").is_file()


def test_cleanup_orphan_skips_live_owner_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.runtime_archive_owner import write_owner_file

    mw_mod = pytest.importorskip("ui.main_window")
    MainWindow = mw_mod.MainWindow
    root = tmp_path / "runtime_sessions"
    root.mkdir()
    live = root / "run_live"
    dead = root / "run_dead"
    live.mkdir()
    dead.mkdir()
    write_owner_file(live, pid=111, token="live", run_id=1)
    write_owner_file(dead, pid=222, token="dead", run_id=2)
    old = time.time() - (10 * 86400)
    os.utime(live, (old, old))
    os.utime(dead, (old, old))
    monkeypatch.setattr(Config, "RUNTIME_SESSION_DIR", str(root))
    monkeypatch.setattr(Config, "RUNTIME_ARCHIVE_KEEP_RECENT", 1)
    monkeypatch.setattr(Config, "RUNTIME_ARCHIVE_MAX_AGE_DAYS", 7)
    monkeypatch.setattr(
        "ui.main_window_impl.persistence_runtime_archive.is_archive_owner_alive",
        lambda path, **_k: Path(path).name == "run_live",
    )
    win = MainWindow.__new__(MainWindow)
    win._runtime_session_root = None
    win._load_recovery_state = lambda: None
    MainWindow._cleanup_orphan_runtime_archives(win)
    assert live.exists()
    assert not dead.exists()


def test_realtime_save_uses_exclusive_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mw_mod = pytest.importorskip("ui.main_window")
    MainWindow = mw_mod.MainWindow
    monkeypatch.setattr(Config, "REALTIME_DIR", str(tmp_path))
    existing = tmp_path / "자막_20260907_120000.txt"
    existing.write_text("old", encoding="utf-8-sig")

    class _FrozenDateTime:
        @staticmethod
        def now():
            from datetime import datetime as real_datetime

            return real_datetime(2026, 9, 7, 12, 0, 0)

    monkeypatch.setattr("ui.main_window_impl.runtime_driver.datetime", _FrozenDateTime)
    win = MainWindow.__new__(MainWindow)
    win._reset_realtime_save_run_state = lambda: None
    win.realtime_save_check = type("C", (), {"isChecked": lambda self: True})()
    paths: list[str] = []
    win._set_realtime_save_status = lambda status, path="": paths.append(str(path))
    assert MainWindow._open_realtime_save_for_run(win) is True
    assert win.realtime_file is not None
    opened = Path(paths[0])
    assert opened != existing
    assert opened.exists()
    win.realtime_file.close()


def test_apply_staged_update_retries_cross_volume_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    from core.update_installer import apply_staged_update

    target = tmp_path / "app.exe"
    staged = tmp_path / "staging" / "staged.exe"
    backup = tmp_path / "app.exe.bak"
    staged.parent.mkdir()
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    original_replace = os.replace
    calls: list[tuple[str, str]] = []

    def fake_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        calls.append((str(src), str(dst)))
        if len(calls) == 1:
            err = OSError("cross-device")
            err.errno = errno.EXDEV
            err.winerror = 17
            raise err
        return original_replace(src, dst)

    monkeypatch.setattr("core.update_installer.os.replace", fake_replace)
    apply_staged_update(
        target=target,
        staged=staged,
        backup=backup,
        smoke_runner=lambda path: path.read_bytes() == b"new",
    )
    assert target.read_bytes() == b"new"
    assert backup.read_bytes() == b"old"
    assert any(Path(src).parent == target.parent for src, _dst in calls[1:])


def test_no_broadcast_alert_raises_without_selector_wait() -> None:
    from ui.main_window_common import NoBroadcastError

    mw_mod = pytest.importorskip("ui.main_window")
    MainWindow = mw_mod.MainWindow
    win = MainWindow.__new__(MainWindow)

    class _Alert:
        text = "잘못된 요청입니다."

        def dismiss(self) -> None:
            return None

    class _SwitchTo:
        alert = _Alert()

    class _Driver:
        current_url = "https://assembly.webcast.go.kr/main/"
        switch_to = _SwitchTo()

    with pytest.raises(NoBroadcastError, match="현재 중계가 없습니다"):
        MainWindow._raise_if_no_broadcast_landing(
            win,
            _Driver(),
            "https://assembly.webcast.go.kr/main/player.asp?xcode=10",
        )


def test_initial_capture_retries_recoverable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from ui.main_window_common import RecoverableWebDriverError

    mw_mod = pytest.importorskip("ui.main_window")
    MainWindow = mw_mod.MainWindow
    win = MainWindow.__new__(MainWindow)
    attempts: list[int] = []

    def fake_open(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise RecoverableWebDriverError("net fail")
        return ("driver", "url", ["sel"], "sel", True, ())

    win._open_capture_driver_session = fake_open
    win._get_reconnect_delay = lambda _attempt: 0.0
    win.message_queue = type("Q", (), {"put": lambda self, item: None})()
    win.stop_event = type("E", (), {"wait": lambda self, timeout=0.0: False})()
    monkeypatch.setattr(Config, "MAX_RECONNECT_ATTEMPTS", 5)
    result = MainWindow._open_initial_capture_driver_session(
        win, object(), "https://example", ".smi_word"
    )
    assert attempts == [1, 2]
    assert result[0] == "driver"


def test_committee_canonical_name_uses_site_title() -> None:
    assert "기후에너지환경노동위원회" in Config.DEFAULT_COMMITTEE_PRESETS
    assert Config.COMMITTEE_XCODE_MAP["기후에너지환경노동위원회"] == 62
    assert Config.COMMITTEE_ABBREVIATIONS["기후노동위"] == "기후에너지환경노동위원회"
    assert Config.COMMITTEE_ABBREVIATIONS["기후환경노동위원회"] == "기후에너지환경노동위원회"
    assert Config.COMMITTEE_ABBREVIATIONS["환노위"] == "기후에너지환경노동위원회"


def test_session_snapshot_header_includes_save_operation_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mw_mod = pytest.importorskip("ui.main_window")
    MainWindow = mw_mod.MainWindow
    win = MainWindow.__new__(MainWindow)
    path = tmp_path / "session.json"
    win._build_session_save_context = lambda: ("https://example", "행안위", 1)
    win._get_capture_quality_payload = lambda: {"queue_drops": 2}
    win._ensure_session_lineage_id = lambda: "lin"
    win._iter_full_session_serialized_items = (
        lambda entries, **_k: [entry.to_dict() for entry in entries]
    )
    win._record_recovery_snapshot = lambda *_a, **_k: None
    win.db = None
    win.db_available = False
    win._get_db_degraded_message = lambda: ""
    MainWindow._write_session_snapshot(
        win,
        str(path),
        [SubtitleEntry("저장")],
        include_db=False,
        save_operation_id="op-123",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["save_operation_id"] == "op-123"
    assert payload["capture_quality"]["queue_drops"] == 2
