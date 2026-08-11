from __future__ import annotations

import json
from datetime import datetime, timedelta

from core.recovery_candidates import discover_recovery_candidates
from ui.dialogs import RecoveryCandidateDialog
from PyQt6.QtWidgets import QApplication


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
