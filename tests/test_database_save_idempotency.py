from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from database import DatabaseManager


def test_save_session_reuses_id_for_same_operation_id(tmp_path) -> None:
    db_path = tmp_path / "sessions.db"
    db = DatabaseManager(str(db_path))
    payload = {
        "url": "https://example.com/live",
        "committee_name": "테스트위원회",
        "subtitles": [{"text": "첫 문장"}],
        "save_operation_id": "save-op-1",
    }
    try:
        first_id = db.save_session(payload)
        second_id = db.save_session({**payload, "subtitles": [{"text": "재시도 문장"}]})

        assert second_id == first_id
        assert len(db.list_sessions(limit=10)) == 1
        loaded = db.load_session(first_id)
        assert loaded is not None
        assert [row["text"] for row in loaded["subtitles"]] == ["첫 문장"]
    finally:
        db.close_all()


def test_existing_database_gets_save_operation_id_column(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                url TEXT,
                committee_name TEXT,
                total_subtitles INTEGER DEFAULT 0,
                total_characters INTEGER DEFAULT 0,
                duration_seconds INTEGER DEFAULT 0,
                version TEXT,
                notes TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO sessions (url, committee_name, notes) VALUES (?, ?, ?)",
            ("https://example.com/legacy", "기존위원회", "보존해야 하는 메모"),
        )

    db = DatabaseManager(str(db_path))
    try:
        with sqlite3.connect(db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(sessions)")}
        assert "save_operation_id" in columns
        assert "idx_sessions_save_operation_id" in indexes
        legacy = db.load_session(1)
        assert legacy is not None
        assert legacy["url"] == "https://example.com/legacy"
        assert legacy["committee_name"] == "기존위원회"
        assert legacy["notes"] == "보존해야 하는 메모"
        assert legacy["subtitles"] == []
        payload = {"save_operation_id": "after-migration", "subtitles": [{"text": "migratedtoken"}]}
        session_id = db.save_session(payload)
        assert db.save_session(payload) == session_id
        assert len(db.list_sessions()) == 2
        loaded = db.load_session(session_id)
        assert loaded is not None
        assert [row["text"] for row in loaded["subtitles"]] == ["migratedtoken"]
    finally:
        db.close_all()


@pytest.mark.parametrize("failure", ["iterator", "sqlite_trigger"])
def test_failed_batched_save_rolls_back_rows_index_and_lineage_then_retries(tmp_path, monkeypatch, failure):
    db_path = tmp_path / "sessions.db"
    db = DatabaseManager(str(db_path))
    monkeypatch.setattr(db, "INSERT_BATCH_SIZE", 2)
    try:
        parent_id = db.save_session({"subtitles": [{"text": "originaltoken"}], "lineage_id": "lineage"})
        if failure == "sqlite_trigger":
            with sqlite3.connect(db_path) as conn:
                conn.execute("""CREATE TRIGGER reject_bad_subtitle BEFORE INSERT ON subtitles
                    WHEN new.text = 'rejecttoken'
                    BEGIN SELECT RAISE(ABORT, 'injected insert failure'); END""")

        def interrupted_rows():
            yield {"text": "partialtoken first"}
            yield {"text": "partialtoken second"}
            # At least one real batch has reached SQLite, but other connections
            # must not see either it or a half-updated lineage.
            with sqlite3.connect(db_path) as observer:
                assert observer.execute("SELECT COUNT(*) FROM subtitles").fetchone()[0] == 1
                assert observer.execute("SELECT is_latest_in_lineage FROM sessions WHERE id=?", (parent_id,)).fetchone()[0] == 1
            if failure == "iterator":
                raise RuntimeError("injected iterator failure")
            yield {"text": "rejecttoken"}

        payload = {"lineage_id": "lineage", "parent_session_id": parent_id, "save_operation_id": "retry-op"}
        expected_error = RuntimeError if failure == "iterator" else sqlite3.IntegrityError
        with pytest.raises(expected_error, match="injected"):
            db.save_session({**payload, "subtitles": interrupted_rows()})

        assert [row["id"] for row in db.list_sessions()] == [parent_id]
        parent = db.load_session(parent_id)
        assert parent is not None and parent["is_latest_in_lineage"] == 1
        with sqlite3.connect(db_path) as observer:
            assert observer.execute("SELECT COUNT(*) FROM subtitles").fetchone()[0] == 1
            assert observer.execute("PRAGMA foreign_key_check").fetchall() == []
        if db.fts_available:
            assert db.search_subtitles("partialtoken", syntax="fts") == []
            assert len(db.search_subtitles("originaltoken", syntax="fts")) == 1

        # The operation ID must also have rolled back, allowing a genuine retry.
        retried_id = db.save_session({**payload, "subtitles": [{"text": "retrytoken"}]})
        loaded = db.load_session(retried_id)
        assert loaded is not None
        assert loaded["total_subtitles"] == 1
        assert loaded["total_characters"] == len("retrytoken")
        assert [row["text"] for row in loaded["subtitles"]] == ["retrytoken"]
        parent = db.load_session(parent_id)
        assert parent is not None and parent["is_latest_in_lineage"] == 0
    finally:
        db.close_all()


def test_concurrent_duplicate_save_is_exactly_once_and_survives_reopen(tmp_path):
    db_path = tmp_path / "sessions.db"
    db = DatabaseManager(str(db_path))
    barrier = threading.Barrier(3)
    payload = {"save_operation_id": "shared-operation", "subtitles": [{"text": "동시 저장"}]}

    def save():
        barrier.wait(timeout=5)
        return db.save_session(payload)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(save) for _ in range(2)]
            barrier.wait(timeout=5)
            ids = [future.result(timeout=10) for future in futures]
        assert ids[0] == ids[1]
        assert len(db.list_sessions()) == 1
    finally:
        db.close_all()

    reopened = DatabaseManager(str(db_path))
    try:
        assert reopened.save_session({**payload, "subtitles": [{"text": "must not overwrite"}]}) == ids[0]
        loaded = reopened.load_session(ids[0])
        assert loaded is not None
        assert [row["text"] for row in loaded["subtitles"]] == ["동시 저장"]
        with sqlite3.connect(db_path) as observer:
            assert observer.execute("SELECT COUNT(*) FROM subtitles").fetchone()[0] == 1
    finally:
        reopened.close_all()
