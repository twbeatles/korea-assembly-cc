import threading
import sqlite3
from pathlib import Path

from core.config import Config
from core.models import SubtitleEntry
from database import DatabaseManager


def test_database_input_guards_and_subtitle_sanitizing(tmp_path):
    db_path = tmp_path / "subtitle_history.db"
    db = DatabaseManager(str(db_path))
    try:
        assert db.load_session(0) is None
        assert db.delete_session(-1) is False
        assert db.search_subtitles("   ") == []
        assert DatabaseManager._sanitize_limit(-1, default=50) == 50
        assert DatabaseManager._sanitize_limit(999999, default=50) == 500
        assert DatabaseManager._sanitize_offset(-4) == 0
        assert DatabaseManager._sanitize_positive_id("abc") is None
        assert DatabaseManager._sanitize_duration("-3") == 0

        try:
            db.save_session("invalid")
            assert False, "dict가 아닌 session_data는 ValueError가 발생해야 함"
        except ValueError:
            pass

        session_id = db.save_session(
            {
                "url": "https://example.com/live",
                "committee_name": "테스트위원회",
                "subtitles": [
                    {"text": "정상 자막", "timestamp": "2026-02-12T10:00:00"},
                    "잘못된 타입",
                    None,
                ],
                "duration_seconds": "-3",
                "version": "test",
            }
        )
        assert session_id > 0

        loaded = db.load_session(session_id)
        assert loaded is not None
        assert loaded["total_subtitles"] == 1
        assert len(loaded["subtitles"]) == 1

        listed = db.list_sessions(limit=-50, offset=-10)
        assert len(listed) >= 1

        results = db.search_subtitles("정상", limit=-100)
        assert any("정상" in row["text"] for row in results)
    finally:
        db.close_all()


def test_database_cleans_stale_thread_connections(tmp_path):
    db_path = tmp_path / "subtitle_history.db"
    db = DatabaseManager(str(db_path))
    worker_id_holder = {}

    try:
        def worker():
            db.list_sessions(limit=10)
            worker_id_holder["id"] = threading.get_ident()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        # main thread 접근으로 stale 연결 정리 트리거
        db.list_sessions(limit=10)

        alive_ids = {th.ident for th in threading.enumerate() if th.ident is not None}
        assert all(tid in alive_ids for tid in db._thread_connections.keys())

        worker_id = worker_id_holder.get("id")
        if worker_id and worker_id != threading.get_ident():
            assert worker_id not in db._thread_connections
    finally:
        db.close_all()


def test_database_default_path_uses_config(monkeypatch, tmp_path):
    expected = tmp_path / "default_history.db"
    monkeypatch.setattr(Config, "DATABASE_PATH", str(expected), raising=False)

    db = DatabaseManager()
    try:
        assert Path(db.db_path).resolve() == expected.resolve()
    finally:
        db.close_all()


def test_database_save_session_accepts_subtitle_entry_objects(tmp_path):
    db_path = tmp_path / "subtitle_history.db"
    db = DatabaseManager(str(db_path))
    try:
        subtitles = [
            SubtitleEntry("첫 문장"),
            SubtitleEntry("둘째 문장"),
        ]
        session_id = db.save_session(
            {
                "url": "https://example.com/live",
                "committee_name": "테스트위원회",
                "subtitles": subtitles,
                "duration_seconds": 12,
                "version": "test",
            }
        )

        loaded = db.load_session(session_id)
        assert loaded is not None
        assert loaded["total_subtitles"] == 2
        assert loaded["total_characters"] == len("첫 문장") + len("둘째 문장")
        assert [row["text"] for row in loaded["subtitles"]] == ["첫 문장", "둘째 문장"]
    finally:
        db.close_all()


def test_database_save_load_preserves_lossless_subtitle_metadata(tmp_path):
    db_path = tmp_path / "subtitle_history.db"
    db = DatabaseManager(str(db_path))
    try:
        entry = SubtitleEntry(
            "메타데이터 보존 문장",
            entry_id="entry-lossless",
            source_selector="#subtitle",
            source_frame_path=[1, 3],
            source_node_key="row-lossless",
            speaker_color="#abc123",
            speaker_channel="secondary",
            speaker_changed=True,
        )
        entry.start_time = entry.timestamp
        entry.end_time = entry.timestamp

        session_id = db.save_session(
            {
                "url": "https://example.com/live",
                "committee_name": "테스트위원회",
                "subtitles": [entry],
                "duration_seconds": 7,
                "version": "test",
            }
        )

        loaded = db.load_session(session_id)
        assert loaded is not None
        restored = SubtitleEntry.from_dict(loaded["subtitles"][0])
        assert restored.to_dict() == entry.to_dict()
    finally:
        db.close_all()


def test_database_migrates_existing_subtitles_table_to_lossless_schema(tmp_path):
    db_path = tmp_path / "legacy_subtitle_history.db"
    conn = sqlite3.connect(db_path)
    try:
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
            """
            CREATE TABLE subtitles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                timestamp DATETIME,
                start_time DATETIME,
                end_time DATETIME,
                sequence INTEGER
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    db = DatabaseManager(str(db_path))
    try:
        with sqlite3.connect(db_path) as migrated:
            columns = {
                row[1]
                for row in migrated.execute("PRAGMA table_info(subtitles)").fetchall()
            }
        assert {
            "entry_id",
            "source_selector",
            "source_frame_path",
            "source_node_key",
            "speaker_color",
            "speaker_channel",
            "speaker_changed",
        }.issubset(columns)
    finally:
        db.close_all()


def test_database_search_defaults_to_literal_substring_matching(tmp_path):
    db_path = tmp_path / "subtitle_history.db"
    db = DatabaseManager(str(db_path))
    try:
        session_id = db.save_session(
            {
                "url": "https://example.com/live",
                "committee_name": "테스트위원회",
                "subtitles": [
                    SubtitleEntry("alpha beta literal"),
                    SubtitleEntry("alpha OR beta literal"),
                    SubtitleEntry("alpha -beta"),
                    SubtitleEntry("alpha:beta"),
                    SubtitleEntry('quote "value"'),
                    SubtitleEntry("100% coverage"),
                    SubtitleEntry("under_score"),
                ],
                "duration_seconds": 20,
                "version": "test",
            }
        )
        assert session_id > 0

        assert [row["text"] for row in db.search_subtitles("alpha beta")] == [
            "alpha beta literal"
        ]
        assert [row["text"] for row in db.search_subtitles("alpha -beta")] == [
            "alpha -beta"
        ]
        assert [row["text"] for row in db.search_subtitles("alpha:beta")] == [
            "alpha:beta"
        ]
        assert [row["text"] for row in db.search_subtitles('"value"')] == [
            'quote "value"'
        ]
        assert [row["text"] for row in db.search_subtitles("100%")] == [
            "100% coverage"
        ]
        assert [row["text"] for row in db.search_subtitles("under_score")] == [
            "under_score"
        ]
    finally:
        db.close_all()
