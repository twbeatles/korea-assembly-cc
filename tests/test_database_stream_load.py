from __future__ import annotations

import pytest

from core.config import Config
from core.models import SubtitleEntry
from core.resource_budget import ResourceLimitExceeded
from database import DatabaseManager
from ui.main_window import MainWindow


def _save_rows(db: DatabaseManager, count: int) -> int:
    return db.save_session(
        {
            "url": "https://example.com/live",
            "committee_name": "테스트",
            "subtitles": [
                {"text": f"문장 {index}", "timestamp": "2026-08-11T10:00:00"}
                for index in range(count)
            ],
        }
    )


def test_session_metadata_is_loaded_without_subtitle_materialization(tmp_path) -> None:
    db = DatabaseManager(str(tmp_path / "sessions.db"))
    try:
        session_id = _save_rows(db, 3)

        metadata = db.get_session_metadata(session_id)

        assert metadata is not None
        assert metadata["id"] == session_id
        assert metadata["total_subtitles"] == 3
        assert "subtitles" not in metadata
    finally:
        db.close_all()


def test_session_subtitles_are_streamed_in_fetchmany_batches(tmp_path, monkeypatch) -> None:
    db = DatabaseManager(str(tmp_path / "sessions.db"))
    try:
        session_id = _save_rows(db, 5)
        fetch_sizes: list[int] = []
        original_get_connection = db._get_connection

        class CursorProxy:
            def __init__(self, cursor):
                self._cursor = cursor

            def execute(self, *args, **kwargs):
                self._cursor.execute(*args, **kwargs)
                return self

            def fetchmany(self, size):
                fetch_sizes.append(size)
                return self._cursor.fetchmany(size)

            def fetchall(self):
                raise AssertionError("subtitle streaming must not call fetchall")

            def __getattr__(self, name):
                return getattr(self._cursor, name)

        class ConnectionProxy:
            def __init__(self, connection):
                self._connection = connection

            def cursor(self):
                return CursorProxy(self._connection.cursor())

        monkeypatch.setattr(
            db,
            "_get_connection",
            lambda: ConnectionProxy(original_get_connection()),
        )

        rows = list(db.iter_session_subtitles(session_id, batch_size=2))

        assert [row["text"] for row in rows] == [f"문장 {index}" for index in range(5)]
        assert fetch_sizes == [2, 2, 2, 2]
    finally:
        db.close_all()


def test_session_subtitle_stream_validates_batch_size(tmp_path) -> None:
    db = DatabaseManager(str(tmp_path / "sessions.db"))
    try:
        session_id = _save_rows(db, 1)
        with pytest.raises(ValueError, match="batch_size"):
            list(db.iter_session_subtitles(session_id, batch_size=0))
    finally:
        db.close_all()


def test_db_dialog_load_builds_payload_from_streaming_api(monkeypatch) -> None:
    class StreamingDb:
        def get_session_metadata(self, session_id: int):
            return {
                "id": session_id,
                "version": "test",
                "total_subtitles": 2,
                "url": "https://example.com/live",
            }

        def iter_session_subtitles(self, session_id: int, *, batch_size: int = 500):
            assert session_id == 7
            assert batch_size == 500
            yield {"text": "one"}
            yield {"text": "two"}

        def load_session(self, _session_id: int):
            raise AssertionError("streaming-capable DB must not use load_session")

    win = MainWindow.__new__(MainWindow)
    win.db = StreamingDb()
    win._show_toast = lambda *_args, **_kwargs: None
    win._confirm_dirty_session_action = lambda _action: True
    win._deserialize_subtitles = lambda items, source="": (
        [SubtitleEntry(item["text"]) for item in items],
        0,
    )
    win._emit_control_message = lambda *_args, **_kwargs: None
    captured = {}
    win._run_db_task = lambda _task, worker, **_kwargs: captured.update(
        payload=worker()
    ) or True

    assert MainWindow._start_db_session_load(
        win,
        7,
        task_name="db_history_load_selected",
        action_name="load",
        loading_text="loading",
        busy_message="busy",
        source_tag="db",
    )

    assert [entry.text for entry in captured["payload"]["subtitles"]] == ["one", "two"]


def test_db_dialog_load_rejects_declared_entry_over_limit(monkeypatch) -> None:
    class OversizedDb:
        def get_session_metadata(self, session_id: int):
            return {"id": session_id, "total_subtitles": 2}

        def iter_session_subtitles(self, session_id: int, *, batch_size: int = 500):
            yield {"text": "must not be reached"}

    monkeypatch.setattr(Config, "SESSION_RESOURCE_MAX_ENTRIES", 1)
    win = MainWindow.__new__(MainWindow)
    win.db = OversizedDb()
    win._show_toast = lambda *_args, **_kwargs: None
    win._confirm_dirty_session_action = lambda _action: True
    win._run_db_task = lambda _task, worker, **_kwargs: worker()

    with pytest.raises(ResourceLimitExceeded):
        MainWindow._start_db_session_load(
            win,
            7,
            task_name="db_history_load_selected",
            action_name="load",
            loading_text="loading",
            busy_message="busy",
            source_tag="db",
        )


def test_db_dialog_stream_load_can_be_cancelled_before_session_swap() -> None:
    class StreamingDb:
        def get_session_metadata(self, session_id: int):
            return {"id": session_id, "total_subtitles": 1}

        def iter_session_subtitles(self, session_id: int, *, batch_size: int = 500):
            yield {"text": "one"}

    win = MainWindow.__new__(MainWindow)
    win.db = StreamingDb()
    win._show_toast = lambda *_args, **_kwargs: None
    win._confirm_dirty_session_action = lambda _action: True

    def cancel_then_run(_task, worker, **_kwargs):
        MainWindow._cancel_db_session_load(win)
        return worker()

    win._run_db_task = cancel_then_run

    with pytest.raises(ResourceLimitExceeded) as exc_info:
        MainWindow._start_db_session_load(
            win,
            7,
            task_name="db_history_load_selected",
            action_name="load",
            loading_text="loading",
            busy_message="busy",
            source_tag="db",
        )

    assert exc_info.value.resource == "cancelled"
