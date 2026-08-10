# -*- coding: utf-8 -*-
"""내보내기(HWP/HWPX/SRT/VTT/DOCX) 견고성 회귀."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zipfile import ZipFile

import pytest

import ui.main_window_persistence as persistence_mod
from core.export_text import (
    format_srt_timestamp,
    normalize_hwp_insert_text,
    resolve_cue_time_range,
    sanitize_document_text,
    sanitize_subtitle_cue_text,
    strip_illegal_xml_chars,
)
from core.models import SubtitleEntry
from core.subtitle_pipeline import create_empty_capture_state

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


def _build_window() -> Any:
    win = MainWindow.__new__(MainWindow)
    win.subtitle_lock = threading.Lock()
    win.capture_state = create_empty_capture_state()
    win.subtitles = win.capture_state.entries
    win._cached_total_chars = 0
    win._cached_total_words = 0
    win.realtime_file = None
    win._show_toast = lambda *_a, **_k: None
    win._generate_smart_filename = lambda extension: f"out.{extension}"
    win._save_in_background = lambda save_func, path, *_a: save_func(path)
    win._snapshot_runtime_stream_context = lambda: (None, [])
    return win


def test_strip_illegal_xml_chars_removes_null_and_controls() -> None:
    assert strip_illegal_xml_chars("a\x00b\x08c") == "abc"
    assert "\t" in strip_illegal_xml_chars("a\tb")  # tab 허용


def test_sanitize_subtitle_cue_text_collapses_blank_lines() -> None:
    raw = "첫 줄\n\n\n둘째 줄\x00"
    assert sanitize_subtitle_cue_text(raw) == "첫 줄\n둘째 줄"


def test_resolve_cue_time_range_fixes_equal_and_reversed_end() -> None:
    ts = datetime(2026, 3, 23, 9, 0, 0)
    start = ts
    equal_end = ts
    reversed_end = ts - timedelta(seconds=1)
    ok_end = ts + timedelta(seconds=2)

    s1, e1 = resolve_cue_time_range(start, equal_end, ts)
    assert e1 > s1
    assert (e1 - s1).total_seconds() == 3

    s2, e2 = resolve_cue_time_range(start, reversed_end, ts)
    assert e2 > s2

    s3, e3 = resolve_cue_time_range(start, ok_end, ts)
    assert s3 == start and e3 == ok_end

    s4, e4 = resolve_cue_time_range(None, None, ts)
    assert s4 == ts
    assert (e4 - s4).total_seconds() == 3


def test_normalize_hwp_insert_text_uses_crlf() -> None:
    assert normalize_hwp_insert_text("a\nb\rc") == "a\r\nb\r\nc"
    assert "\x00" not in normalize_hwp_insert_text("x\x00y")


def test_save_srt_and_vtt_fix_invalid_end_and_blank_lines(tmp_path, monkeypatch):
    win = _build_window()
    entry = SubtitleEntry("첫 줄\n\n\n둘째 줄", datetime(2026, 3, 23, 9, 0, 0))
    entry.start_time = datetime(2026, 3, 23, 9, 0, 0)
    entry.end_time = datetime(2026, 3, 23, 9, 0, 0)  # equal → fallback
    win._build_prepared_entries_snapshot = lambda: [entry]

    srt_path = tmp_path / "out.srt"
    vtt_path = tmp_path / "out.vtt"
    paths = iter([(str(srt_path), ""), (str(vtt_path), "")])
    monkeypatch.setattr(
        persistence_mod.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: next(paths),
    )

    MainWindow._save_srt(win)
    MainWindow._save_vtt(win)

    srt = srt_path.read_text(encoding="utf-8")
    vtt = vtt_path.read_text(encoding="utf-8")

    assert "09:00:00,000 --> 09:00:03,000" in srt
    assert "09:00:00.000 --> 09:00:03.000" in vtt
    assert "첫 줄\n둘째 줄" in srt
    assert "\n\n\n" not in srt.split("-->", 1)[1]
    # 큐 본문에 빈 줄이 큐 경계를 만들지 않음 (번호 1개만)
    assert srt.count("\n\n") >= 1
    assert srt.strip().startswith("1\n")


def test_save_hwpx_strips_control_chars(tmp_path, monkeypatch):
    win = _build_window()
    entries = [
        SubtitleEntry("깨짐\x00문자", datetime(2026, 3, 23, 10, 0, 0)),
        SubtitleEntry("정상 문장", datetime(2026, 3, 23, 10, 1, 0)),
    ]
    win._build_prepared_entries_snapshot = lambda: entries
    target = tmp_path / "out.hwpx"
    monkeypatch.setattr(
        persistence_mod.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(target), ""),
    )

    MainWindow._save_hwpx(win)

    with ZipFile(target) as archive:
        section = archive.read("Contents/section0.xml").decode("utf-8")
        preview = archive.read("Preview/PrvText.txt").decode("utf-8")

    assert "\x00" not in section
    assert "깨짐문자" in section or ("깨짐" in preview and "문자" in preview)
    assert "정상 문장" in preview


def test_save_hwp_uses_smart_filename_and_multiline(tmp_path, monkeypatch):
    win = _build_window()
    entry = SubtitleEntry("첫 줄\n둘째 줄", datetime(2026, 3, 23, 10, 0, 0))
    win._build_prepared_entries_snapshot = lambda: [entry]
    names: list[str] = []

    def capture_filename(*args, **kwargs):
        # getSaveFileName(self, title, filename, filter)
        if len(args) >= 3:
            names.append(str(args[2]))
        elif "caption" in kwargs:
            names.append(str(kwargs.get("directory", "")))
        default_name = args[2] if len(args) >= 3 else "out.hwp"
        target = tmp_path / Path(default_name).name
        return str(target), ""

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
            self.get_default_insert = 0

        def Run(self, _name: str) -> None:
            return None

        def GetDefault(self, name: str, _hset: object) -> None:
            if name == "InsertText":
                self.get_default_insert += 1

        def Execute(self, name: str, _hset: object) -> None:
            if name == "InsertText":
                self.owner.buffer.append(self.owner.HParameterSet.HInsertText.Text)
            elif name == "FileSaveAs_S":
                Path(self.owner.HParameterSet.HFileOpenSave.filename).write_text(
                    "".join(self.owner.buffer), encoding="utf-8"
                )

    class _FakeHwp:
        def __init__(self) -> None:
            self.buffer: list[str] = []
            self.XHwpWindows = SimpleNamespace(
                Item=lambda _i: SimpleNamespace(Visible=False)
            )
            self.HParameterSet = _FakeParameterSet()
            self.HAction = _FakeHAction(self)
            self.quit_called = False

        def RegisterModule(self, *_a) -> None:
            return None

        def Quit(self) -> None:
            self.quit_called = True

    fake_hwp = _FakeHwp()
    fake_win32 = SimpleNamespace(dynamic=SimpleNamespace(Dispatch=lambda _n: fake_hwp))

    def fake_import(name: str):
        if name == "win32com.client":
            return fake_win32
        if name == "pythoncom":
            return SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
        raise ImportError(name)

    monkeypatch.setattr(persistence_mod, "_import_optional_module", fake_import)
    monkeypatch.setattr(
        persistence_mod.QFileDialog, "getSaveFileName", capture_filename
    )

    MainWindow._save_hwp(win)

    assert names and names[0].endswith(".hwp")
    assert "out.hwp" in names[0] or names[0].endswith("out.hwp")
    body = "".join(fake_hwp.buffer)
    assert "첫 줄\r\n둘째 줄" in body
    # 제목/생성일시/본문/통계 등 InsertText 마다 GetDefault
    assert fake_hwp.HAction.get_default_insert >= 3
    assert fake_hwp.quit_called is True


def test_format_srt_timestamp_padding() -> None:
    value = datetime(2026, 1, 1, 1, 2, 3, 45000)
    assert format_srt_timestamp(value) == "01:02:03,045"


def test_sanitize_document_text_keeps_korean() -> None:
    assert sanitize_document_text("한글\x00 테스트") == "한글 테스트"
