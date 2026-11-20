from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from core.recovery_candidates import discover_recovery_candidates
from core.recovery_candidates import inspect_recovery_candidate
from core.config import Config
import pytest
from ui.dialogs import RecoveryCandidateDialog
from PySide6.QtWidgets import QApplication


def _write_session(path, *, created: str, count: int) -> None:
    path.write_text(
        json.dumps(
            {
                "version": "test",
                "created": created,
                "url": "https://example.com/live",
                "subtitles": [{"text": str(index)} for index in range(count)],
            }
        ),
        encoding="utf-8",
    )


def test_discovery_deduplicates_pointer_and_backup_and_orders_newest(tmp_path) -> None:
    backup_dir = tmp_path / "backups"
    runtime_dir = backup_dir / "runtime_sessions"
    backup_dir.mkdir()
    runtime_dir.mkdir()
    older = datetime(2026, 8, 11, 9, 0, 0)
    newer = older + timedelta(hours=1)
    backup = backup_dir / "backup_1.json"
    _write_session(backup, created=older.isoformat(), count=2)
    session = tmp_path / "session.json"
    _write_session(session, created=newer.isoformat(), count=3)
    recovery_state = tmp_path / "recovery.json"
    recovery_state.write_text(
        json.dumps({"path": str(session), "snapshot_type": "session"}),
        encoding="utf-8",
    )

    candidates = discover_recovery_candidates(
        recovery_state_file=recovery_state,
        backup_dir=backup_dir,
        runtime_session_dir=runtime_dir,
    )

    assert [candidate.path for candidate in candidates] == [session.resolve(), backup.resolve()]
    assert candidates[0].entry_count == 3
    assert candidates[0].integrity == "valid"


def test_runtime_candidate_reports_missing_segment_warning(tmp_path) -> None:
    runtime_dir = tmp_path / "runtime"
    run_dir = runtime_dir / "run-1"
    run_dir.mkdir(parents=True)
    manifest = run_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "format": "runtime_session_manifest_v1",
                "created": "2026-08-11T10:00:00",
                "segments": [
                    {"path": "segment_000001.json", "entry_count": 5}
                ],
                "tail_checkpoint": "tail_checkpoint.json",
            }
        ),
        encoding="utf-8",
    )

    candidates = discover_recovery_candidates(
        recovery_state_file=tmp_path / "missing-pointer.json",
        backup_dir=tmp_path / "backups",
        runtime_session_dir=runtime_dir,
    )

    assert len(candidates) == 1
    assert candidates[0].snapshot_type == "runtime_manifest"
    assert candidates[0].integrity == "warning"
    assert any("segment" in warning for warning in candidates[0].warnings)


def test_corrupt_candidate_is_marked_invalid_not_raised(tmp_path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "backup_broken.json").write_text("{broken", encoding="utf-8")

    candidates = discover_recovery_candidates(
        recovery_state_file=tmp_path / "missing.json",
        backup_dir=backup_dir,
        runtime_session_dir=tmp_path / "runtime",
    )

    assert len(candidates) == 1
    assert candidates[0].integrity == "invalid"
    assert candidates[0].warnings


def test_recovery_dialog_selects_only_non_invalid_candidate(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    valid_path = tmp_path / "backup_valid.json"
    _write_session(valid_path, created="2026-08-11T10:00:00", count=1)
    broken_path = tmp_path / "backup_broken.json"
    broken_path.write_text("{broken", encoding="utf-8")
    candidates = discover_recovery_candidates(
        recovery_state_file=tmp_path / "missing.json",
        backup_dir=tmp_path,
        runtime_session_dir=tmp_path / "runtime",
    )
    dialog = RecoveryCandidateDialog(candidates)

    for index, candidate in enumerate(dialog.candidates):
        if candidate.integrity != "invalid":
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(index))
            break
    dialog.accept_selection()

    assert dialog.selected_candidate is not None
    assert dialog.selected_candidate.integrity != "invalid"
    dialog.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("resource", ["tail_checkpoint", "segment"])
@pytest.mark.parametrize("absolute", [False, True])
def test_recovery_inspection_rejects_resources_outside_archive(
    tmp_path, monkeypatch, resource, absolute
) -> None:
    from core import recovery_candidates

    root = tmp_path / "archive"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"entry_count": 25}', encoding="utf-8")
    name = str(outside) if absolute else "../outside.json"
    manifest = root / "manifest.json"
    payload = {"format": "runtime_session_manifest_v1", "segments": []}
    if resource == "segment":
        payload["segments"] = [{"path": name, "entry_count": 25}]
    else:
        payload["tail_checkpoint"] = name
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    reads = []
    original = recovery_candidates.read_limited_json_file

    def recorded_read(path, **kwargs):
        reads.append(path.resolve())
        return original(path, **kwargs)

    monkeypatch.setattr(recovery_candidates, "read_limited_json_file", recorded_read)
    candidate = inspect_recovery_candidate(manifest)
    assert candidate.integrity == "invalid"
    assert outside.resolve() not in reads


def test_recovery_pointer_respects_size_limit(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace
    from ui.main_window_impl.persistence_session_recovery import (
        MainWindowPersistenceSessionRecoveryMixin,
    )

    session = tmp_path / "session.json"
    session.write_text('{}', encoding="utf-8")
    pointer = tmp_path / "recovery.json"
    pointer.write_text(json.dumps({"path": str(session), "padding": "x" * 256}), encoding="utf-8")
    monkeypatch.setattr(Config, "RECOVERY_STATE_FILE", pointer)
    monkeypatch.setattr(Config, "URL_HISTORY_MAX_BYTES", 64)
    cleared = []
    host: Any = SimpleNamespace(_clear_recovery_state=lambda: cleared.append(True))
    assert MainWindowPersistenceSessionRecoveryMixin._load_recovery_state(host) is None
    assert cleared == [True]
