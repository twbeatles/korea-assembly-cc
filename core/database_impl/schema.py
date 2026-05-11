# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false

from collections.abc import Iterable
import json
import logging
import re
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


class DatabaseSchemaMixin:

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
                self.db_available = True
                self.degraded_reason = ""
                self._init_fts_objects(conn)
                try:
                    conn.execute("PRAGMA optimize")
                except Exception as opt_error:
                    logger.debug(f"PRAGMA optimize 실행 오류: {opt_error}")
                logger.info(f"데이터베이스 초기화 완료: {self.db_path}")
            except Exception as e:
                self.db_available = False
                self.fts_available = False
                self.degraded_reason = str(e)
                logger.error(f"데이터베이스 초기화 오류: {e}")
                raise

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
