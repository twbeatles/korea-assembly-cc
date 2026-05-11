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
from core.models import SubtitleEntry

logger = logging.getLogger("SubtitleExtractor")


class DatabaseFtsMixin:

    def _init_fts_objects(self, conn: sqlite3.Connection) -> None:
        cursor = conn.cursor()
        try:
            fts_existed = self._fts_table_exists(cursor)
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS subtitles_fts USING fts5(
                    text,
                    content='subtitles',
                    content_rowid='id'
                )
            """)
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
            if (not fts_existed) or self._fts_rebuild_required(cursor):
                self._rebuild_fts_index(cursor)
            conn.commit()
            self.fts_available = True
            self.degraded_reason = ""
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            self.fts_available = False
            self.degraded_reason = f"FTS5 초기화 실패: {exc}"
            logger.warning("%s", self.degraded_reason)

    def _fts_table_exists(self, cursor: sqlite3.Cursor) -> bool:
        row = cursor.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'subtitles_fts'
            LIMIT 1
            """
        ).fetchone()
        return row is not None

    def _fts_rebuild_required(self, cursor: sqlite3.Cursor) -> bool:
        try:
            subtitle_count_row = cursor.execute("SELECT COUNT(*) FROM subtitles").fetchone()
            fts_count_row = cursor.execute("SELECT COUNT(*) FROM subtitles_fts").fetchone()
            subtitle_count = int(subtitle_count_row[0] if subtitle_count_row else 0)
            fts_count = int(fts_count_row[0] if fts_count_row else 0)
            if subtitle_count != fts_count:
                return True
            return self._fts_sample_index_missing(cursor)
        except Exception as exc:
            logger.debug("FTS 상태 확인 실패, rebuild 수행: %s", exc)
            return True

    def _rebuild_fts_index(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("INSERT INTO subtitles_fts(subtitles_fts) VALUES ('rebuild')")

    @staticmethod
    def _build_fts_probe_query(text: object) -> str:
        for token in re.findall(r"[0-9A-Za-z가-힣_]+", str(text or "")):
            normalized = token.strip("_")
            if normalized:
                return '"' + normalized.replace('"', '""') + '"'
        return ""

    def _fts_sample_index_missing(self, cursor: sqlite3.Cursor) -> bool:
        rows = cursor.execute(
            """
            SELECT id, text
            FROM subtitles
            WHERE text IS NOT NULL AND text != ''
            ORDER BY id DESC
            LIMIT 20
            """
        ).fetchall()
        for row_id, text in rows:
            query = self._build_fts_probe_query(text)
            if not query:
                continue
            hit = cursor.execute(
                """
                SELECT 1
                FROM subtitles_fts
                WHERE rowid = ? AND subtitles_fts MATCH ?
                LIMIT 1
                """,
                (row_id, query),
            ).fetchone()
            if hit is None:
                return True
        return False
