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


class DatabaseSessionMixin(DatabaseMixinHost):

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
                    0,
                    0,
                    duration_seconds,
                    session_data.get("version", ""),
                    session_data.get("notes", ""),
                    lineage_id,
                    parent_session_id,
                ))

                session_id = cursor.lastrowid
                if session_id is None:
                    raise RuntimeError("세션 저장 후 session_id를 확인할 수 없습니다.")

                total_subtitles = 0
                total_chars = 0
                batch: list[tuple[Any, ...]] = []

                def flush_batch() -> None:
                    if not batch:
                        return
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
                    """, batch)
                    batch.clear()

                for row in self._iter_subtitle_rows(session_id, subtitles):
                    total_subtitles += 1
                    total_chars += len(str(row[1] or ""))
                    batch.append(row)
                    if len(batch) >= self.INSERT_BATCH_SIZE:
                        flush_batch()
                flush_batch()

                cursor.execute(
                    """
                    UPDATE sessions
                    SET total_subtitles = ?, total_characters = ?
                    WHERE id = ?
                    """,
                    (total_subtitles, total_chars, session_id),
                )

                conn.commit()
                logger.info(f"세션 저장 완료: ID={session_id}, 자막={total_subtitles}개")
                return session_id

            except Exception as e:
                conn.rollback()
                logger.error(f"세션 저장 오류: {e}")
                raise

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

            except Exception:
                logger.exception("세션 로드 오류")
                raise

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
                    ORDER BY created_at DESC, id DESC
                    LIMIT ? OFFSET ?
                """, (safe_limit, safe_offset))

                return [dict(row) for row in cursor.fetchall()]

            except Exception:
                logger.exception("세션 목록 조회 오류")
                raise

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
                cursor.execute(
                    """
                    SELECT lineage_id, is_latest_in_lineage
                    FROM sessions
                    WHERE id = ?
                    """,
                    (safe_session_id,),
                )
                session_row = cursor.fetchone()
                if not session_row:
                    return False

                lineage_id = str(session_row["lineage_id"] or "").strip()
                was_latest = bool(session_row["is_latest_in_lineage"] or 0)
                cursor.execute("DELETE FROM sessions WHERE id = ?", (safe_session_id,))
                deleted = cursor.rowcount > 0
                if deleted and lineage_id and was_latest:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM sessions
                        WHERE lineage_id = ?
                          AND is_latest_in_lineage = 1
                        LIMIT 1
                        """,
                        (lineage_id,),
                    )
                    has_latest = cursor.fetchone() is not None
                    if not has_latest:
                        cursor.execute(
                            """
                            UPDATE sessions
                            SET is_latest_in_lineage = 1
                            WHERE id = (
                                SELECT id
                                FROM sessions
                                WHERE lineage_id = ?
                                ORDER BY created_at DESC, id DESC
                                LIMIT 1
                            )
                            """,
                            (lineage_id,),
                        )

                conn.commit()
                if deleted:
                    logger.info(f"세션 삭제 완료: ID={safe_session_id}")
                return deleted

            except Exception:
                conn.rollback()
                logger.exception("세션 삭제 오류")
                raise
