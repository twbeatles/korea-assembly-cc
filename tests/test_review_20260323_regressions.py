from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import ui.main_window_persistence as persistence_mod
from core.config import Config
from core.models import SubtitleEntry
from core.subtitle_pipeline import create_empty_capture_state
from ui.main_window_common import WorkerQueueMessage

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


class _SettingsStub:
    def __init__(self) -> None:
        self.saved: dict[str, str] = {}

    def setValue(self, key: str, value: str) -> None:
        self.saved[key] = value


class _DummyProcessor:
    def __init__(self) -> None:
        self.confirmed: list[str] = []

    def add_confirmed(self, text: str) -> None:
        self.confirmed.append(text)


class _TrackingLock:
    def __init__(self) -> None:
        self.held = False

    def __enter__(self):
        self.held = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.held = False
        return False


class _RealtimeFile:
    def __init__(self, lock: _TrackingLock) -> None:
        self.lock = lock
        self.lines: list[str] = []

    def write(self, line: str) -> None:
        assert self.lock.held is False
        self.lines.append(line)

    def flush(self) -> None:
        assert self.lock.held is False


class _FakePythonCom:
    def CoInitialize(self) -> None:
        return None

    def CoUninitialize(self) -> None:
        return None


class _FakeInsertText:
    def __init__(self) -> None:
        self.HSet = object()
        self.Text = ""


class _FakeFileOpenSave:
    def __init__(self) -> None:
        self.HSet = object()
        self.filename = ""
        self.Format = ""


class _FakeParameterSet:
    def __init__(self) -> None:
        self.HInsertText = _FakeInsertText()
        self.HFileOpenSave = _FakeFileOpenSave()


class _FakeHAction:
    def __init__(self, owner: "_FakeHwp") -> None:
        self.owner = owner

    def Run(self, _name: str) -> None:
        return None

    def GetDefault(self, _name: str, _hset: object) -> None:
        return None

    def Execute(self, name: str, _hset: object) -> None:
        if name == "InsertText":
            self.owner.buffer.append(self.owner.HParameterSet.HInsertText.Text)
        elif name == "FileSaveAs_S":
            target = Path(self.owner.HParameterSet.HFileOpenSave.filename)
            target.write_text("".join(self.owner.buffer), encoding="utf-8")


class _FakeHwp:
    def __init__(self) -> None:
        self.buffer: list[str] = []
        self.XHwpWindows = SimpleNamespace(Item=lambda _index: SimpleNamespace(Visible=False))
        self.HParameterSet = _FakeParameterSet()
        self.HAction = _FakeHAction(self)
        self.quit_called = False

    def RegisterModule(self, *_args) -> None:
        return None

    def Quit(self) -> None:
        self.quit_called = True


class _FakeDispatch:
    def __init__(self, hwp: _FakeHwp) -> None:
        self._hwp = hwp

    def Dispatch(self, _name: str) -> _FakeHwp:
        return self._hwp


def _build_window() -> MainWindow:
    win = MainWindow.__new__(MainWindow)
    win.subtitle_lock = threading.Lock()
    win.capture_state = create_empty_capture_state()
    win.subtitles = win.capture_state.entries
    win._cached_total_chars = 0
    win._cached_total_words = 0
    win.realtime_file = None
    win._realtime_error_count = 0
    win._check_keyword_alert = lambda _text: None
    win._update_count_label = lambda: None
    win._refresh_text = lambda force_full=False: None
    win._show_toast = lambda *_args, **_kwargs: None
    win._is_auto_clean_newlines_enabled = lambda: True
    win.subtitle_processor = _DummyProcessor()
    win.settings = _SettingsStub()
    return win


def test_subtitle_entry_generates_entry_id_for_new_and_loaded_entries():
    fresh = SubtitleEntry("새 자막")
    loaded = SubtitleEntry.from_dict(
        {
            "text": "로드된 자막",
            "timestamp": datetime(2026, 3, 23, 12, 0, 0).isoformat(),
        }
    )

    assert fresh.entry_id is not None
    assert loaded.entry_id is not None
    assert fresh.entry_id != loaded.entry_id


def test_unwrap_message_item_drops_stale_worker_run_messages():
    win = MainWindow.__new__(MainWindow)
    win._active_capture_run_id = 7

    assert MainWindow._unwrap_message_item(
        win,
        WorkerQueueMessage(6, "status", "stale"),
    ) is None
    assert MainWindow._unwrap_message_item(
        win,
        WorkerQueueMessage(7, "status", "live"),
    ) == ("status", "live")


def test_add_text_to_subtitles_writes_realtime_after_releasing_lock():
    win = _build_window()
    tracking_lock = _TrackingLock()
    win.subtitle_lock = tracking_lock
    realtime = _RealtimeFile(tracking_lock)
    win.realtime_file = realtime

    MainWindow._add_text_to_subtitles(win, "첫 문장")

    assert len(win.subtitles) == 1
    assert realtime.lines == [f"[{win.subtitles[0].timestamp.strftime('%H:%M:%S')}] 첫 문장\n"]


def test_finalize_subtitle_skips_text_already_materialized_in_capture_state():
    win = _build_window()
    win.capture_state.last_processed_raw = "이미 처리됨"

    MainWindow._finalize_subtitle(win, "이미 처리됨")

    assert win.subtitles == []
    assert win.subtitle_processor.confirmed == []


def test_alert_keyword_cache_persists_and_triggers_toast():
    win = _build_window()
    toasts: list[tuple[tuple[object, ...], dict[str, object]]] = []
    win._show_toast = lambda *args, **kwargs: toasts.append((args, kwargs))

    MainWindow._rebuild_alert_keyword_cache(win, ["법안", "통과"], update_settings=True)
    MainWindow._check_keyword_alert(win, "오늘 법안 통과 소식이 있습니다")

    assert win.settings.saved["alert_keywords"] == "법안, 통과"
    assert toasts
    assert "법안" in str(toasts[0][0][0])


def test_save_srt_and_vtt_keep_fallback_when_end_time_is_missing(tmp_path, monkeypatch):
    win = _build_window()
    entry = SubtitleEntry("마지막 문장", datetime(2026, 3, 23, 9, 0, 0))
    entry.start_time = None
    entry.end_time = None
    win._build_prepared_entries_snapshot = lambda: [entry]
    win._generate_smart_filename = lambda extension: f"out.{extension}"
    win._save_in_background = lambda save_func, path, *_args: save_func(path)

    srt_path = tmp_path / "output.srt"
    vtt_path = tmp_path / "output.vtt"
    saved_paths = iter([(str(srt_path), ""), (str(vtt_path), "")])
    monkeypatch.setattr(
        persistence_mod.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: next(saved_paths),
    )

    MainWindow._save_srt(win)
    MainWindow._save_vtt(win)

    assert "09:00:00,000 --> 09:00:03,000" in srt_path.read_text(encoding="utf-8")
    assert "09:00:00.000 --> 09:00:03.000" in vtt_path.read_text(encoding="utf-8")


def test_save_hwp_falls_back_to_rtf_when_pywin32_is_missing(monkeypatch):
    win = _build_window()
    win._build_prepared_entries_snapshot = lambda: [SubtitleEntry("첫 문장")]
    fallback_called: list[bool] = []
    win._save_rtf = lambda: fallback_called.append(True)

    monkeypatch.setattr(
        persistence_mod,
        "_import_optional_module",
        lambda name: (_ for _ in ()).throw(ImportError(name)),
    )
    monkeypatch.setattr(persistence_mod.QMessageBox, "warning", lambda *args, **kwargs: None)

    MainWindow._save_hwp(win)

    assert fallback_called == [True]


def test_save_hwp_success_path_runs_with_fake_com_objects(tmp_path, monkeypatch):
    win = _build_window()
    entry = SubtitleEntry("첫 문장", datetime(2026, 3, 23, 10, 0, 0))
    win._build_prepared_entries_snapshot = lambda: [entry]
    win._save_in_background = lambda save_func, path, *_args: save_func(path)

    target = tmp_path / "output.hwp"
    fake_hwp = _FakeHwp()
    fake_win32 = SimpleNamespace(dynamic=_FakeDispatch(fake_hwp))

    def fake_import(name: str):
        if name == "win32com.client":
            return fake_win32
        if name == "pythoncom":
            return _FakePythonCom()
        raise ImportError(name)

    monkeypatch.setattr(persistence_mod, "_import_optional_module", fake_import)
    monkeypatch.setattr(
        persistence_mod.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(target), ""),
    )

    MainWindow._save_hwp(win)

    assert target.exists()
    assert "국회 의사중계 자막" in target.read_text(encoding="utf-8")
    assert fake_hwp.quit_called is True


def test_config_removes_unverified_committee_entries():
    assert "정보위원회" not in Config.DEFAULT_COMMITTEE_PRESETS
    assert "정보위원회" not in Config.COMMITTEE_XCODE_MAP
    assert Config.SPECIAL_COMMITTEE_XCODES == {"IO": "국정감사/국정조사"}
