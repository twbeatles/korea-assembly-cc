"""
SQLite 데이터베이스 관리 모듈 (#26)

국회 의사중계 자막 추출기의 세션 데이터를 체계적으로 관리합니다.
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any, Union
import json
import threading
import logging

logger = logging.getLogger("SubtitleExtractor")


class DatabaseManager:
    """자막 세션 데이터베이스 관리 클래스"""
    
    DEFAULT_DB_PATH = "subtitle_history.db"
    
    def __init__(self, db_path: str = None):
        """데이터베이스 매니저 초기화
        
        Args:
            db_path: 데이터베이스 파일 경로 (기본: subtitle_history.db)
        """
        if db_path is None:
            # 실행 파일 위치 기준 경로 설정
            base_dir = Path.cwd()
            self.db_path = str(base_dir / self.DEFAULT_DB_PATH)
        else:
            self.db_path = db_path
            
        self.lock = threading.RLock()
        self._thread_connections = {}  # 스레드별 연결 캐시 (thread_id -> connection)
        self._init_db()

    def close_all(self):
        """모든 데이터베이스 연결 종료"""
        with self.lock:
            for thread_id, conn in self._thread_connections.items():
                try:
                    conn.close()
                except Exception as e:
                    logger.error(f"DB 연결 종료 오류 (Thread {thread_id}): {e}")
            self._thread_connections.clear()
            logger.info("모든 DB 연결이 종료되었습니다.")
    
    def _get_connection(self) -> sqlite3.Connection:
        """스레드 안전한 연결 생성 및 캐싱"""
        thread_id = threading.get_ident()
        with self.lock:
            if thread_id not in self._thread_connections:
                try:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    conn.row_factory = sqlite3.Row
                    conn.execute("PRAGMA foreign_keys = ON")
                    conn.execute("PRAGMA journal_mode = WAL")  # 성능 향상을 위해 WAL 모드 사용 권장
                    self._thread_connections[thread_id] = conn
                except Exception as e:
                    logger.error(f"DB 연결 생성 오류: {e}")
                    raise
            return self._thread_connections[thread_id]
    
    def _init_db(self):
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
                        notes TEXT
                    )
                """)
                
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
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    )
                """)
                
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
                
                conn.commit()
                logger.info(f"데이터베이스 초기화 완료: {self.db_path}")
            except Exception as e:
                logger.error(f"데이터베이스 초기화 오류: {e}")
                raise
            # 연결은 캐싱되므로 닫지 않음
    
    def save_session(self, session_data: dict) -> int:
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
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                subtitles = session_data.get("subtitles", [])
                total_chars = sum(len(s.get("text", "")) for s in subtitles)
                
                # 세션 삽입
                cursor.execute("""
                    INSERT INTO sessions 
                    (url, committee_name, total_subtitles, total_characters, 
                     duration_seconds, version, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_data.get("url", ""),
                    session_data.get("committee_name", ""),
                    len(subtitles),
                    total_chars,
                    session_data.get("duration_seconds", 0),
                    session_data.get("version", ""),
                    session_data.get("notes", "")
                ))
                
                session_id = cursor.lastrowid
                
                # 자막 대량 삽입 (executemany 사용)
                # 딕셔너리 리스트를 튜플 리스트로 변환
                subtitle_data = [
                    (
                        session_id,
                        s.get("text", ""),
                        s.get("timestamp"),
                        s.get("start_time"),
                        s.get("end_time"),
                        i
                    )
                    for i, s in enumerate(subtitles)
                ]
                
                if subtitle_data:
                    cursor.executemany("""
                        INSERT INTO subtitles 
                        (session_id, text, timestamp, start_time, end_time, sequence)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, subtitle_data)
                
                conn.commit()
                logger.info(f"세션 저장 완료: ID={session_id}, 자막={len(subtitles)}개")
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
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # 세션 조회
                cursor.execute("""
                    SELECT * FROM sessions WHERE id = ?
                """, (session_id,))
                
                session_row = cursor.fetchone()
                if not session_row:
                    return None
                
                # 자막 조회
                cursor.execute("""
                    SELECT * FROM subtitles 
                    WHERE session_id = ? 
                    ORDER BY sequence
                """, (session_id,))
                
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
                    "subtitles": [
                        {
                            "text": row["text"],
                            "timestamp": row["timestamp"],
                            "start_time": row["start_time"],
                            "end_time": row["end_time"]
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
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, created_at, url, committee_name, 
                           total_subtitles, total_characters, duration_seconds, notes
                    FROM sessions 
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
                
                return [dict(row) for row in cursor.fetchall()]
                
            except Exception as e:
                logger.exception("세션 목록 조회 오류")
                return []
            # 연결은 캐싱되므로 닫지 않음
    
    def search_subtitles(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        """자막 텍스트 검색
        
        Args:
            query: 검색 키워드
            limit: 최대 반환 개수
            
        Returns:
            List[dict]: 검색 결과 (세션 정보 포함)
        """
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # FTS 검색 시도 (MATCH 연산자)
                try:
                    cursor.execute("""
                        SELECT s.id as subtitle_id, s.text, s.timestamp, s.sequence,
                               sess.id as session_id, sess.created_at, sess.committee_name
                        FROM subtitles s
                        JOIN sessions sess ON s.session_id = sess.id
                        WHERE s.id IN (SELECT rowid FROM subtitles_fts WHERE text MATCH ? ORDER BY rank)
                        ORDER BY sess.created_at DESC, s.sequence
                        LIMIT ?
                    """, (query, limit))
                    results = [dict(row) for row in cursor.fetchall()]
                    
                    # FTS 검색 결과가 있으면 반환
                    if results:
                        return results
                        
                except sqlite3.OperationalError as fts_error:
                    # FTS 검색 실패 시 LIKE으로 Fallback (#6)
                    logger.debug(f"FTS 검색 실패, LIKE로 Fallback: {fts_error}")
                
                # Fallback: LIKE 검색 (특수문자, 따옴표 등 처리)
                like_query = f"%{query}%"
                cursor.execute("""
                    SELECT s.id as subtitle_id, s.text, s.timestamp, s.sequence,
                           sess.id as session_id, sess.created_at, sess.committee_name
                    FROM subtitles s
                    JOIN sessions sess ON s.session_id = sess.id
                    WHERE s.text LIKE ?
                    ORDER BY sess.created_at DESC, s.sequence
                    LIMIT ?
                """, (like_query, limit))
                
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
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                conn.commit()
                
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"세션 삭제 완료: ID={session_id}")
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
