import threading

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
