from __future__ import annotations

import sqlite3

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

    db = DatabaseManager(str(db_path))
    try:
        with sqlite3.connect(db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(sessions)")}
        assert "save_operation_id" in columns
        assert "idx_sessions_save_operation_id" in indexes
    finally:
        db.close_all()
