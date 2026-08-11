from __future__ import annotations

import json

from core.models import CaptureQualityState, SubtitleEntry
from database import DatabaseManager
from ui.main_window import MainWindow


def test_capture_quality_mapping_round_trip_and_sanitizing() -> None:
    state = CaptureQualityState.from_mapping(
        {
            "queue_drops": 2,
            "preview_gaps": "3",
            "reconnects": -1,
            "unknown": 999,
        }
    )

    assert state.to_dict() == {
        "queue_drops": 2,
        "preview_gaps": 3,
        "reconnects": 0,
        "desync_resets": 0,
        "salvage_skipped_files": 0,
    }


def test_capture_quality_is_persisted_in_json_snapshot(tmp_path) -> None:
    win = MainWindow.__new__(MainWindow)
    win._capture_quality = CaptureQualityState(queue_drops=2, preview_gaps=1)
    win._runtime_segment_manifest = []
    win._build_session_save_context = lambda: ("https://example.com", "test", 0)
    win._ensure_session_lineage_id = lambda: "lineage"
    win._record_recovery_snapshot = lambda *_args, **_kwargs: None
    win._iter_full_session_serialized_items = (
        lambda entries, **_kwargs: (entry.to_dict() for entry in entries)
    )
    output = tmp_path / "session.json"

    MainWindow._write_session_snapshot(
        win,
        str(output),
        [SubtitleEntry("문장")],
        include_db=False,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["capture_quality"]["queue_drops"] == 2
    assert payload["capture_quality"]["preview_gaps"] == 1


def test_capture_quality_is_persisted_in_database(tmp_path) -> None:
    db = DatabaseManager(str(tmp_path / "sessions.db"))
    try:
        session_id = db.save_session(
            {
                "subtitles": [],
                "capture_quality": {"reconnects": 4, "desync_resets": 2},
            }
        )
        loaded = db.load_session(session_id)
        assert loaded is not None
        assert loaded["capture_quality"]["reconnects"] == 4
        assert loaded["capture_quality"]["desync_resets"] == 2
    finally:
        db.close_all()


def test_queue_drop_updates_capture_quality_counter() -> None:
    win = MainWindow.__new__(MainWindow)
    win._show_toast = lambda *_args, **_kwargs: None
    win._set_status = lambda *_args, **_kwargs: None

    MainWindow._record_overflow_drop(win, 3, reason="test")

    assert MainWindow._get_capture_quality_payload(win)["queue_drops"] == 3
