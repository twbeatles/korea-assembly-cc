"""
SQLite 데이터베이스 관리 모듈 (#26)

국회 의사중계 자막 추출기의 세션 데이터를 체계적으로 관리합니다.
"""

from collections.abc import Iterable
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from core.config import Config
from core.models import SubtitleEntry

logger = logging.getLogger("SubtitleExtractor")


class DatabaseManager:
    """자막 세션 데이터베이스 관리 클래스"""
    
    DEFAULT_DB_PATH = "subtitle_history.db"
    MAX_QUERY_LIMIT = 500
    STALE_CONNECTION_CLEANUP_INTERVAL = 2.0
    STALE_CONNECTION_CLEANUP_EVERY = 32
    
    def __init__(self, db_path: str | None = None):
        """데이터베이스 매니저 초기화
        
        Args:
            db_path: 데이터베이스 파일 경로 (기본: subtitle_history.db)
        """
        self.db_path = db_path or Config.DATABASE_PATH

        # 상위 폴더가 없으면 생성
        db_parent = Path(self.db_path).resolve().parent
        db_parent.mkdir(parents=True, exist_ok=True)
            
        self.lock = threading.RLock()
        self._thread_connections: dict[int, sqlite3.Connection] = {}
        self._stale_cleanup_calls = 0
        self._last_stale_cleanup_at = 0.0
        self._init_db()

    def close_all(self) -> None:
        """모든 데이터베이스 연결 종료"""
        with self.lock:
            for thread_id, conn in self._thread_connections.items():
                try:
                    conn.close()
                except Exception as e:
                    logger.error(f"DB 연결 종료 오류 (Thread {thread_id}): {e}")
            self._thread_connections.clear()
            logger.info("모든 DB 연결이 종료되었습니다.")

    def checkpoint(self, mode: str = "PASSIVE") -> bool:
        """WAL checkpoint를 수행한다."""
        checkpoint_mode = str(mode or "PASSIVE").strip().upper() or "PASSIVE"
        with self.lock:
            conn = self._get_connection()
            try:
                conn.execute(f"PRAGMA wal_checkpoint({checkpoint_mode})")
                return True
            except Exception as e:
                logger.debug("DB checkpoint 오류 (%s): %s", checkpoint_mode, e)
                return False

    @staticmethod
    def _sanitize_limit(limit: Any, default: int) -> int:
        """LIMIT 값을 안전한 범위로 정규화"""
        try:
            value = int(limit)
        except (TypeError, ValueError):
            return default
        if value <= 0:
            return default
        return min(value, DatabaseManager.MAX_QUERY_LIMIT)

    @staticmethod
    def _sanitize_offset(offset: Any) -> int:
        """OFFSET 값을 0 이상 정수로 정규화"""
        try:
            value = int(offset)
        except (TypeError, ValueError):
            return 0
        return max(0, value)

    @staticmethod
    def _sanitize_positive_id(value: Any) -> Optional[int]:
        """양수 ID만 허용하고, 그 외는 None 반환"""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _sanitize_query(query: Any) -> str:
        """검색어 문자열 정규화"""
        if query is None:
            return ""
        return str(query).strip()

    @staticmethod
    def _sanitize_duration(value: Any) -> int:
        """duration_seconds 정규화"""
        try:
            duration = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, duration)

    @staticmethod
    def _normalize_datetime_value(value: object) -> object:
        if isinstance(value, str) or value is None:
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    @staticmethod
    def _serialize_frame_path(value: object) -> str | None:
        if value in (None, "", ()):
            return None
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return None
            value = parsed
        if not isinstance(value, (list, tuple)):
            return None
        normalized: list[int] = []
        for item in value:
            try:
                normalized.append(int(item))
            except (TypeError, ValueError):
                continue
        if not normalized:
            return None
        return json.dumps(normalized, ensure_ascii=False)

    @staticmethod
    def _deserialize_frame_path(value: object) -> list[int] | None:
        if not value:
            return None
        if isinstance(value, list):
            normalized: list[int] = []
            for item in value:
                try:
                    normalized.append(int(item))
                except (TypeError, ValueError):
                    continue
            return normalized or None
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value)
        except Exception:
            return None
        if not isinstance(parsed, list):
            return None
        normalized: list[int] = []
        for item in parsed:
            try:
                normalized.append(int(item))
            except (TypeError, ValueError):
                continue
        return normalized or None

    @staticmethod
    def _escape_like_query(query: str) -> str:
        escaped = query.replace("\\", "\\\\")
        escaped = escaped.replace("%", "\\%")
        escaped = escaped.replace("_", "\\_")
        return escaped

    def _cleanup_stale_connections_locked(self, force: bool = False) -> None:
        """종료된 스레드의 캐시 연결을 정리한다. (lock 내부 전용)"""
        if not self._thread_connections:
            return
        self._stale_cleanup_calls += 1
        now = time.monotonic()
        if (
            not force
            and
            self._stale_cleanup_calls % self.STALE_CONNECTION_CLEANUP_EVERY != 0
            and now - self._last_stale_cleanup_at < self.STALE_CONNECTION_CLEANUP_INTERVAL
        ):
            return
        self._last_stale_cleanup_at = now
        alive_ids = {t.ident for t in threading.enumerate() if t.ident is not None}
        stale_ids = [tid for tid in self._thread_connections if tid not in alive_ids]
        for thread_id in stale_ids:
            conn = self._thread_connections.pop(thread_id, None)
            if conn is None:
                continue
            try:
                conn.close()
            except Exception as e:
                logger.debug(f"stale DB 연결 종료 오류 (Thread {thread_id}): {e}")
        if stale_ids:
            logger.debug("stale DB 연결 정리: %s개", len(stale_ids))

    @staticmethod
    def _iter_subtitle_rows(
        session_id: int,
        subtitles: object,
    ) -> Iterable[
        tuple[
            int,
            str,
            object,
            object,
            object,
            int,
            object,
            object,
            object,
            object,
            object,
            object,
            int,
        ]
    ]:
        if not isinstance(subtitles, Iterable) or isinstance(subtitles, (str, bytes, dict)):
            return ()

        def _generator() -> Iterable[
            tuple[
                int,
                str,
                object,
                object,
                object,
                int,
                object,
                object,
                object,
                object,
                object,
                object,
                int,
            ]
        ]:
            sequence = 0
            for item in subtitles:
                if isinstance(item, SubtitleEntry):
                    yield (
                        session_id,
                        item.text,
                        item.timestamp.isoformat(),
                        item.start_time.isoformat() if item.start_time else None,
                        item.end_time.isoformat() if item.end_time else None,
                        sequence,
                        item.entry_id,
                        item.source_selector,
                        DatabaseManager._serialize_frame_path(item.source_frame_path),
                        item.source_node_key,
                        item.speaker_color,
                        item.speaker_channel,
                        1 if item.speaker_changed else 0,
                    )
                    sequence += 1
                elif isinstance(item, dict):
                    yield (
                        session_id,
                        str(item.get("text", "")),
                        DatabaseManager._normalize_datetime_value(item.get("timestamp")),
                        DatabaseManager._normalize_datetime_value(item.get("start_time")),
                        DatabaseManager._normalize_datetime_value(item.get("end_time")),
                        sequence,
                        item.get("entry_id"),
                        item.get("source_selector"),
                        DatabaseManager._serialize_frame_path(item.get("source_frame_path")),
                        item.get("source_node_key"),
                        item.get("speaker_color"),
                        item.get("speaker_channel"),
                        1 if bool(item.get("speaker_changed", False)) else 0,
                    )
                    sequence += 1

        return _generator()
    
    def _get_connection(self) -> sqlite3.Connection:
        """스레드 안전한 연결 생성 및 캐싱"""
        thread_id = threading.get_ident()
        with self.lock:
            force_cleanup = thread_id not in self._thread_connections
            if not force_cleanup and len(self._thread_connections) > 1:
                alive_ids = {t.ident for t in threading.enumerate() if t.ident is not None}
                force_cleanup = any(
                    cached_thread_id not in alive_ids
                    for cached_thread_id in self._thread_connections
                )
            self._cleanup_stale_connections_locked(force=force_cleanup)
            if thread_id not in self._thread_connections:
                try:
                    conn = sqlite3.connect(
                        self.db_path, check_same_thread=False, timeout=10
                    )
                    conn.row_factory = sqlite3.Row
                    conn.execute("PRAGMA foreign_keys = ON")
                    conn.execute("PRAGMA journal_mode = WAL")
                    conn.execute("PRAGMA synchronous = NORMAL")
                    conn.execute("PRAGMA temp_store = MEMORY")
                    conn.execute("PRAGMA busy_timeout = 5000")
                    self._thread_connections[thread_id] = conn
                except Exception as e:
                    logger.error(f"DB 연결 생성 오류: {e}")
                    raise
            return self._thread_connections[thread_id]
    
    def _init_db(self) -> None:
        """데이터베이스 스키마 초기화"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # 세션 테이블
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        url TEXT,
                        committee_name TEXT,
                        total_subtitles INTEGER DEFAULT 0,
                        total_characters INTEGER DEFAULT 0,
                        duration_seconds INTEGER DEFAULT 0,
                        version TEXT,
                        notes TEXT,
                        lineage_id TEXT,
                        parent_session_id INTEGER NULL,
                        is_latest_in_lineage INTEGER DEFAULT 1
                    )
                """)
                self._ensure_session_table_columns(cursor)
                
                # 자막 테이블
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS subtitles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        timestamp DATETIME,
                        start_time DATETIME,
                        end_time DATETIME,
                        sequence INTEGER,
                        entry_id TEXT,
                        source_selector TEXT,
                        source_frame_path TEXT,
                        source_node_key TEXT,
                        speaker_color TEXT,
                        speaker_channel TEXT,
                        speaker_changed INTEGER DEFAULT 0,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    )
                """)
                self._ensure_subtitle_table_columns(cursor)
                
                # FTS5 가상 테이블 생성 (전체 텍스트 검색용)
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS subtitles_fts USING fts5(
                        text,
                        content='subtitles',
                        content_rowid='id'
                    )
                """)
                
                # 트리거: subtitles 삽입 시 fts 자동 업데이트
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS subtitles_ai AFTER INSERT ON subtitles BEGIN
                        INSERT INTO subtitles_fts(rowid, text) VALUES (new.id, new.text);
                    END;
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS subtitles_ad AFTER DELETE ON subtitles BEGIN
                        INSERT INTO subtitles_fts(subtitles_fts, rowid, text) VALUES('delete', old.id, old.text);
                    END;
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS subtitles_au AFTER UPDATE ON subtitles BEGIN
                        INSERT INTO subtitles_fts(subtitles_fts, rowid, text) VALUES('delete', old.id, old.text);
                        INSERT INTO subtitles_fts(rowid, text) VALUES (new.id, new.text);
                    END;
                """)
                
                # 인덱스 생성
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_subtitles_session 
                    ON subtitles(session_id)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_subtitles_session_sequence
                    ON subtitles(session_id, sequence)
                """)
                # FTS 사용으로 인해 일반 text 인덱스는 선택적이지만, 정확한 일치 검색 등을 위해 유지
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_subtitles_text 
                    ON subtitles(text)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_date 
                    ON sessions(created_at)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_committee 
                    ON sessions(committee_name)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_lineage_latest
                    ON sessions(lineage_id, is_latest_in_lineage, created_at DESC, id DESC)
                """)
                
                conn.commit()
                try:
                    conn.execute("PRAGMA optimize")
                except Exception as opt_error:
                    logger.debug(f"PRAGMA optimize 실행 오류: {opt_error}")
                logger.info(f"데이터베이스 초기화 완료: {self.db_path}")
            except Exception as e:
                logger.error(f"데이터베이스 초기화 오류: {e}")
                raise
            # 연결은 캐싱되므로 닫지 않음

    def _ensure_subtitle_table_columns(self, cursor: sqlite3.Cursor) -> None:
        column_rows = cursor.execute("PRAGMA table_info(subtitles)").fetchall()
        existing_columns = {str(row[1]) for row in column_rows}
        required_columns = {
            "entry_id": "TEXT",
            "source_selector": "TEXT",
            "source_frame_path": "TEXT",
            "source_node_key": "TEXT",
            "speaker_color": "TEXT",
            "speaker_channel": "TEXT",
            "speaker_changed": "INTEGER DEFAULT 0",
        }
        for column_name, sql_type in required_columns.items():
            if column_name in existing_columns:
                continue
            cursor.execute(f"ALTER TABLE subtitles ADD COLUMN {column_name} {sql_type}")

    def _ensure_session_table_columns(self, cursor: sqlite3.Cursor) -> None:
        column_rows = cursor.execute("PRAGMA table_info(sessions)").fetchall()
        existing_columns = {str(row[1]) for row in column_rows}
        required_columns = {
            "lineage_id": "TEXT",
            "parent_session_id": "INTEGER NULL",
            "is_latest_in_lineage": "INTEGER DEFAULT 1",
        }
        for column_name, sql_type in required_columns.items():
            if column_name in existing_columns:
                continue
            cursor.execute(f"ALTER TABLE sessions ADD COLUMN {column_name} {sql_type}")

        cursor.execute(
            """
            UPDATE sessions
            SET lineage_id = COALESCE(NULLIF(lineage_id, ''), 'legacy-' || id),
                parent_session_id = NULL,
                is_latest_in_lineage = COALESCE(is_latest_in_lineage, 1)
            WHERE lineage_id IS NULL
               OR lineage_id = ''
               OR is_latest_in_lineage IS NULL
            """
        )
    
    def save_session(self, session_data: object) -> int:
        """세션 저장
        
        Args:
            session_data: 세션 데이터
                - url: 소스 URL
                - committee_name: 위원회명
                - subtitles: 자막 리스트 [{"text": str, "timestamp": str, ...}, ...]
                - version: 앱 버전
                - duration_seconds: 녹화 시간 (초)
                - notes: 메모 (선택)
                
        Returns:
            int: 생성된 session_id
        """
        if not isinstance(session_data, dict):
            raise ValueError("session_data는 dict여야 합니다.")

        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                subtitles_raw = session_data.get("subtitles", [])
                subtitles = (
                    subtitles_raw
                    if isinstance(subtitles_raw, Iterable)
                    and not isinstance(subtitles_raw, (str, bytes, dict))
                    else ()
                )
                if not isinstance(subtitles, (list, tuple)):
                    subtitles = tuple(subtitles)

                total_subtitles = 0
                total_chars = 0
                for item in subtitles:
                    if isinstance(item, SubtitleEntry):
                        total_subtitles += 1
                        total_chars += item.char_count
                    elif isinstance(item, dict):
                        total_subtitles += 1
                        total_chars += len(str(item.get("text", "")))
                duration_seconds = self._sanitize_duration(
                    session_data.get("duration_seconds", 0)
                )
                lineage_id = str(session_data.get("lineage_id", "") or "").strip()
                if not lineage_id:
                    lineage_id = f"session-{uuid4().hex}"
                parent_session_id = self._sanitize_positive_id(
                    session_data.get("parent_session_id")
                )
                cursor.execute(
                    """
                    UPDATE sessions
                    SET is_latest_in_lineage = 0
                    WHERE lineage_id = ?
                    """,
                    (lineage_id,),
                )
                
                # 세션 삽입
                cursor.execute("""
                    INSERT INTO sessions 
                    (url, committee_name, total_subtitles, total_characters, 
                     duration_seconds, version, notes, lineage_id, parent_session_id, is_latest_in_lineage)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (
                    session_data.get("url", ""),
                    session_data.get("committee_name", ""),
                    total_subtitles,
                    total_chars,
                    duration_seconds,
                    session_data.get("version", ""),
                    session_data.get("notes", ""),
                    lineage_id,
                    parent_session_id,
                ))
                
                session_id = cursor.lastrowid
                if session_id is None:
                    raise RuntimeError("세션 저장 후 session_id를 확인할 수 없습니다.")
                
                # 자막 대량 삽입 (executemany 사용)
                # 딕셔너리 리스트를 튜플 리스트로 변환
                if total_subtitles:
                    cursor.executemany("""
                        INSERT INTO subtitles 
                        (
                            session_id,
                            text,
                            timestamp,
                            start_time,
                            end_time,
                            sequence,
                            entry_id,
                            source_selector,
                            source_frame_path,
                            source_node_key,
                            speaker_color,
                            speaker_channel,
                            speaker_changed
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, self._iter_subtitle_rows(session_id, subtitles))
                
                conn.commit()
                logger.info(f"세션 저장 완료: ID={session_id}, 자막={total_subtitles}개")
                return session_id
                
            except Exception as e:
                conn.rollback()
                logger.error(f"세션 저장 오류: {e}")
                raise
            # 연결은 캐싱되므로 닫지 않음
    
    def load_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """세션 로드
        
        Args:
            session_id: 세션 ID
            
        Returns:
            dict: 세션 데이터 또는 None
        """
        safe_session_id = self._sanitize_positive_id(session_id)
        if safe_session_id is None:
            return None

        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # 세션 조회
                cursor.execute("""
                    SELECT * FROM sessions WHERE id = ?
                """, (safe_session_id,))
                
                session_row = cursor.fetchone()
                if not session_row:
                    return None
                
                # 자막 조회
                cursor.execute("""
                    SELECT * FROM subtitles 
                    WHERE session_id = ? 
                    ORDER BY sequence
                """, (safe_session_id,))
                
                subtitle_rows = cursor.fetchall()
                
                return {
                    "id": session_row["id"],
                    "created_at": session_row["created_at"],
                    "url": session_row["url"],
                    "committee_name": session_row["committee_name"],
                    "total_subtitles": session_row["total_subtitles"],
                    "total_characters": session_row["total_characters"],
                    "duration_seconds": session_row["duration_seconds"],
                    "version": session_row["version"],
                    "notes": session_row["notes"],
                    "lineage_id": session_row["lineage_id"],
                    "parent_session_id": session_row["parent_session_id"],
                    "is_latest_in_lineage": int(session_row["is_latest_in_lineage"] or 0),
                    "subtitles": [
                        {
                            "text": row["text"],
                            "timestamp": row["timestamp"],
                            "start_time": row["start_time"],
                            "end_time": row["end_time"],
                            "entry_id": row["entry_id"],
                            "source_selector": row["source_selector"],
                            "source_frame_path": self._deserialize_frame_path(
                                row["source_frame_path"]
                            ),
                            "source_node_key": row["source_node_key"],
                            "speaker_color": row["speaker_color"],
                            "speaker_channel": row["speaker_channel"],
                            "speaker_changed": bool(row["speaker_changed"]),
                        }
                        for row in subtitle_rows
                    ]
                }
                
            except Exception as e:
                logger.exception("세션 로드 오류")
                return None
            # 연결은 캐싱되므로 닫지 않음
    
    def list_sessions(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """세션 목록 조회
        
        Args:
            limit: 최대 반환 개수
            offset: 시작 위치
            
        Returns:
            List[dict]: 세션 요약 리스트
        """
        safe_limit = self._sanitize_limit(limit, default=50)
        safe_offset = self._sanitize_offset(offset)

        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, created_at, url, committee_name, 
                           total_subtitles, total_characters, duration_seconds, notes,
                           lineage_id, parent_session_id, is_latest_in_lineage,
                           (
                               SELECT COUNT(*)
                               FROM sessions same_lineage
                               WHERE same_lineage.lineage_id = sessions.lineage_id
                           ) AS lineage_total,
                           (
                               SELECT COUNT(*)
                               FROM sessions newer
                               WHERE newer.lineage_id = sessions.lineage_id
                                 AND (
                                     newer.created_at > sessions.created_at
                                     OR (
                                         newer.created_at = sessions.created_at
                                         AND newer.id > sessions.id
                                     )
                                 )
                           ) AS newer_versions
                    FROM sessions 
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """, (safe_limit, safe_offset))
                
                return [dict(row) for row in cursor.fetchall()]
                
            except Exception as e:
                logger.exception("세션 목록 조회 오류")
                return []
            # 연결은 캐싱되므로 닫지 않음
    
    def search_subtitles(
        self,
        query: str,
        limit: int = 100,
        offset: int = 0,
        syntax: str = "literal",
    ) -> List[Dict[str, Any]]:
        """자막 텍스트 검색
        
        Args:
            query: 검색 키워드
            limit: 최대 반환 개수
            offset: 시작 위치
            
        Returns:
            List[dict]: 검색 결과 (세션 정보 포함)
        """
        safe_query = self._sanitize_query(query)
        if not safe_query:
            return []
        safe_limit = self._sanitize_limit(limit, default=100)
        safe_offset = self._sanitize_offset(offset)

        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()

                if str(syntax or "literal").strip().lower() == "fts":
                    try:
                        cursor.execute("""
                            SELECT s.id as subtitle_id, s.text, s.timestamp, s.sequence,
                                   sess.id as session_id, sess.created_at, sess.committee_name
                            FROM subtitles s
                            JOIN sessions sess ON s.session_id = sess.id
                            WHERE s.id IN (
                                SELECT rowid FROM subtitles_fts WHERE text MATCH ? ORDER BY rank
                            )
                            ORDER BY sess.created_at DESC, s.sequence
                            LIMIT ? OFFSET ?
                        """, (safe_query, safe_limit, safe_offset))
                        return [dict(row) for row in cursor.fetchall()]
                    except sqlite3.OperationalError as fts_error:
                        logger.debug(f"FTS 검색 실패, literal LIKE로 fallback: {fts_error}")

                like_query = f"%{self._escape_like_query(safe_query)}%"
                cursor.execute("""
                    SELECT s.id as subtitle_id, s.text, s.timestamp, s.sequence,
                           sess.id as session_id, sess.created_at, sess.committee_name
                    FROM subtitles s
                    JOIN sessions sess ON s.session_id = sess.id
                    WHERE s.text LIKE ? ESCAPE '\\'
                    ORDER BY sess.created_at DESC, s.sequence
                    LIMIT ? OFFSET ?
                """, (like_query, safe_limit, safe_offset))
                
                return [dict(row) for row in cursor.fetchall()]
                
            except Exception as e:
                logger.exception("자막 검색 오류")
                return []
            # 연결은 캐싱되므로 닫지 않음
    
    def delete_session(self, session_id: int) -> bool:
        """세션 삭제
        
        Args:
            session_id: 삭제할 세션 ID
            
        Returns:
            bool: 삭제 성공 여부
        """
        safe_session_id = self._sanitize_positive_id(session_id)
        if safe_session_id is None:
            return False

        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sessions WHERE id = ?", (safe_session_id,))
                conn.commit()
                
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"세션 삭제 완료: ID={safe_session_id}")
                return deleted
                
            except Exception as e:
                conn.rollback()
                logger.exception("세션 삭제 오류")
                return False
            # 연결은 캐싱되므로 닫지 않음
    
    def get_statistics(self) -> Dict[str, Union[int, float]]:
        """전체 통계 조회
        
        Returns:
            dict: 전체 통계 정보
        """
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_sessions,
                        SUM(total_subtitles) as total_subtitles,
                        SUM(total_characters) as total_characters,
                        SUM(duration_seconds) as total_duration
                    FROM sessions
                """)
                
                row = cursor.fetchone()
                return {
                    "total_sessions": row["total_sessions"] or 0,
                    "total_subtitles": row["total_subtitles"] or 0,
                    "total_characters": row["total_characters"] or 0,
                    "total_duration_hours": (row["total_duration"] or 0) / 3600
                }
                
            except Exception as e:
                logger.exception("통계 조회 오류")
                return {}
            # 연결은 캐싱되므로 닫지 않음
