# -*- coding: utf-8 -*-
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
from core.database_impl.contracts import DatabaseMixinHost
from core.models import SubtitleEntry

logger = logging.getLogger("SubtitleExtractor")


class DatabaseSearchStatsMixin(DatabaseMixinHost):

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
                    if not bool(self.fts_available):
                        logger.debug("FTS 비활성 상태라 literal LIKE로 fallback")
                    else:
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
