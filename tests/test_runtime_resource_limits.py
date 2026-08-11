from __future__ import annotations

import json

import pytest

from core.config import Config
from core.resource_budget import ResourceLimitExceeded
from ui.main_window import MainWindow


def _write_runtime_file(path, text: str, *, padding: int = 0) -> None:
    path.write_text(
        json.dumps(
            {
                "subtitles": [
                    {"text": text, "timestamp": "2026-08-11T10:00:00"}
                ],
                "padding": "x" * padding,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_manifest(root, segments: list[str]) -> None:
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "runtime_session_manifest_v1",
                "segments": [{"path": name} for name in segments],
                "tail_checkpoint": "tail_checkpoint.json",
            }
        ),
        encoding="utf-8",
    )


def _window() -> MainWindow:
    return MainWindow.__new__(MainWindow)


def test_runtime_manifest_rejects_oversized_referenced_segment(tmp_path, monkeypatch) -> None:
    _write_runtime_file(tmp_path / "segment_000001.json", "segment", padding=1000)
    _write_runtime_file(tmp_path / "tail_checkpoint.json", "tail")
    _write_manifest(tmp_path, ["segment_000001.json"])
    monkeypatch.setattr(Config, "SESSION_RESOURCE_PER_FILE_MAX_BYTES", 512)
    monkeypatch.setattr(Config, "SESSION_RESOURCE_TOTAL_MAX_BYTES", 4096)

    with pytest.raises(ResourceLimitExceeded) as exc_info:
        MainWindow._load_runtime_manifest_payload(
            _window(), tmp_path / "manifest.json", allow_salvage=False
        )

    assert exc_info.value.resource == "file_bytes"


def test_runtime_manifest_rejects_cumulative_segment_bytes(tmp_path, monkeypatch) -> None:
    _write_runtime_file(tmp_path / "segment_000001.json", "one", padding=300)
    _write_runtime_file(tmp_path / "segment_000002.json", "two", padding=300)
    _write_runtime_file(tmp_path / "tail_checkpoint.json", "tail")
    _write_manifest(tmp_path, ["segment_000001.json", "segment_000002.json"])
    manifest_size = (tmp_path / "manifest.json").stat().st_size
    first_size = (tmp_path / "segment_000001.json").stat().st_size
    monkeypatch.setattr(Config, "SESSION_RESOURCE_PER_FILE_MAX_BYTES", 4096)
    monkeypatch.setattr(
        Config,
        "SESSION_RESOURCE_TOTAL_MAX_BYTES",
        manifest_size + first_size + 1,
    )

    with pytest.raises(ResourceLimitExceeded) as exc_info:
        MainWindow._load_runtime_manifest_payload(
            _window(), tmp_path / "manifest.json", allow_salvage=False
        )

    assert exc_info.value.resource == "total_bytes"


def test_runtime_salvage_does_not_swallow_segment_count_limit(tmp_path, monkeypatch) -> None:
    (tmp_path / "manifest.json").write_text("{broken", encoding="utf-8")
    _write_runtime_file(tmp_path / "segment_000001.json", "one")
    _write_runtime_file(tmp_path / "segment_000002.json", "two")
    _write_runtime_file(tmp_path / "tail_checkpoint.json", "tail")
    monkeypatch.setattr(Config, "SESSION_RESOURCE_MAX_SEGMENTS", 1)

    with pytest.raises(ResourceLimitExceeded) as exc_info:
        MainWindow._load_runtime_manifest_payload(
            _window(), tmp_path / "manifest.json", allow_salvage=True
        )

    assert exc_info.value.resource == "segments"


def test_runtime_load_reports_resource_summary(tmp_path, monkeypatch) -> None:
    _write_runtime_file(tmp_path / "segment_000001.json", "segment")
    _write_runtime_file(tmp_path / "tail_checkpoint.json", "tail")
    _write_manifest(tmp_path, ["segment_000001.json"])
    monkeypatch.setattr(Config, "SESSION_RESOURCE_MAX_ENTRIES", 10)

    payload = MainWindow._load_runtime_manifest_payload(
        _window(), tmp_path / "manifest.json", allow_salvage=False
    )

    assert payload["resource_usage"]["segments"] == 1
    assert payload["resource_usage"]["entries"] == 2
    assert payload["resource_usage"]["total_bytes"] > 0
