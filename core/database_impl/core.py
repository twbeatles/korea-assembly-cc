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


class DatabaseCoreMixin:

    DEFAULT_DB_PATH = "subtitle_history.db"
    MAX_QUERY_LIMIT = 500
    INSERT_BATCH_SIZE = 500
    ALLOWED_CHECKPOINT_MODES = frozenset({"PASSIVE", "FULL", "RESTART", "TRUNCATE"})
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
        self.db_available = False
        self.fts_available = False
        self.degraded_reason = ""
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
        if checkpoint_mode not in self.ALLOWED_CHECKPOINT_MODES:
            raise ValueError(f"지원하지 않는 WAL checkpoint mode: {checkpoint_mode}")
        with self.lock:
            conn = self._get_connection()
            try:
                conn.execute(f"PRAGMA wal_checkpoint({checkpoint_mode})")
                return True
            except Exception as e:
                logger.debug("DB checkpoint 오류 (%s): %s", checkpoint_mode, e)
                return False

    @classmethod
    def _sanitize_limit(cls, limit: Any, default: int) -> int:
        """LIMIT 값을 안전한 범위로 정규화"""
        try:
            value = int(limit)
        except (TypeError, ValueError):
            return default
        if value <= 0:
            return default
        return min(value, cls.MAX_QUERY_LIMIT)

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
                        DatabaseCoreMixin._serialize_frame_path(item.source_frame_path),
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
                        DatabaseCoreMixin._normalize_datetime_value(item.get("timestamp")),
                        DatabaseCoreMixin._normalize_datetime_value(item.get("start_time")),
                        DatabaseCoreMixin._normalize_datetime_value(item.get("end_time")),
                        sequence,
                        item.get("entry_id"),
                        item.get("source_selector"),
                        DatabaseCoreMixin._serialize_frame_path(item.get("source_frame_path")),
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
