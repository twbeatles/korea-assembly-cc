from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.models import SubtitleEntry

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


def _build_runtime_archive_window() -> Any:
    win = MainWindow.__new__(MainWindow)
    win._runtime_segment_manifest = []
    win._runtime_archived_count = 0
    return win


def test_has_runtime_archived_segments_requires_positive_archived_count(tmp_path):
    win = _build_runtime_archive_window()
    win._runtime_segment_manifest = [{"path": "segment_0001.json", "start_index": 0}]
    win._runtime_archived_count = 0
    assert MainWindow._has_runtime_archived_segments(win) is False

    win._runtime_archived_count = 3
    assert MainWindow._has_runtime_archived_segments(win) is True


def test_build_salvaged_runtime_segments_collects_sibling_segment_files(tmp_path):
    win = _build_runtime_archive_window()
    runtime_root = tmp_path / "run-1"
    runtime_root.mkdir()
    (runtime_root / "segment_0001.json").write_text("{}", encoding="utf-8")
    (runtime_root / "segment_0002.json").write_text("{}", encoding="utf-8")
    (runtime_root / "manifest.json").write_text("{broken", encoding="utf-8")
    (runtime_root / "tail_checkpoint.json").write_text("{}", encoding="utf-8")

    segments = MainWindow._build_salvaged_runtime_segments(win, runtime_root)

    assert segments == [
        {"path": "segment_0001.json"},
        {"path": "segment_0002.json"},
    ]


def test_runtime_entries_fingerprint_mismatch_detected():
    win = _build_runtime_archive_window()
    entries = [
        SubtitleEntry("첫 문장", entry_id="e-1"),
        SubtitleEntry("둘 문장", entry_id="e-2"),
    ]
    expected = MainWindow._build_runtime_entries_fingerprint(win, entries)
    expected["entries_digest"] = "deadbeef"

    error = MainWindow._runtime_entries_integrity_error(
        win,
        entries,
        expected,
        source="segment",
    )

    assert error is not None
    assert "무결성 불일치" in error


def test_runtime_manifest_salvage_reads_valid_segment_despite_broken_manifest(tmp_path, monkeypatch):
    win = _build_runtime_archive_window()
    runtime_root = tmp_path / "run-2"
    runtime_root.mkdir()
    segment_path = runtime_root / "segment_0001.json"
    entries = [SubtitleEntry("salvage 대상", entry_id="seg-1")]
    fingerprint = MainWindow._build_runtime_entries_fingerprint(win, entries)
    segment_path.write_text(
        json.dumps(
            {
                "subtitles": [entry.to_dict() for entry in entries],
                **fingerprint,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (runtime_root / "manifest.json").write_text("{broken", encoding="utf-8")

    monkeypatch.setattr(
        mw_mod.utils,
        "atomic_write_json",
        lambda *_args, **_kwargs: None,
    )
    win._runtime_session_root = runtime_root
    win._load_segment_file_entries = MainWindow._load_segment_file_entries.__get__(
        win, MainWindow
    )

    salvaged = MainWindow._build_salvaged_runtime_segments(win, runtime_root)
    loaded = MainWindow._load_runtime_segment_entries(win, salvaged[0], runtime_root=runtime_root)

    assert len(salvaged) == 1
    assert len(loaded) == 1
    assert loaded[0].text == "salvage 대상"