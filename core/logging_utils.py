# -*- coding: utf-8 -*-
"""
로깅 유틸리티

정책 (PROJECT_AUDIT_EXTENDED):
- 파일/콘솔 기본 레벨은 Config.LOG_* (기본 INFO)
- 환경변수 SUBTITLE_LOG_LEVEL 로 상향 가능 (DEBUG|INFO|WARNING|ERROR)
- 자막 전문·민감 장문은 safe_log_text() 로 축약 권장
"""

from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from core.config import Config


def _parse_level(name: object, default: int = logging.INFO) -> int:
    raw = str(name or "").strip().upper()
    if not raw:
        return default
    return int(getattr(logging, raw, default))


def resolve_log_file_level() -> int:
    env = os.environ.get("SUBTITLE_LOG_LEVEL", "").strip()
    if env:
        return _parse_level(env, logging.INFO)
    return _parse_level(getattr(Config, "LOG_FILE_LEVEL", "INFO"), logging.INFO)


def resolve_log_console_level() -> int:
    env = os.environ.get("SUBTITLE_LOG_LEVEL", "").strip()
    if env:
        return _parse_level(env, logging.INFO)
    return _parse_level(getattr(Config, "LOG_CONSOLE_LEVEL", "INFO"), logging.INFO)


def safe_log_text(text: object, *, max_chars: int | None = None) -> str:
    """로그용 텍스트 축약. 자막 전문 기록 방지를 위한 헬퍼."""
    value = str(text or "")
    if not bool(getattr(Config, "LOG_REDACT_LONG_TEXT", True)):
        return value
    limit = max_chars
    if limit is None:
        try:
            limit = int(getattr(Config, "LOG_REDACT_MAX_CHARS", 80) or 80)
        except Exception:
            limit = 80
    limit = max(8, int(limit))
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}…(+{len(value) - limit + 1})"


def _ensure_console_handler(logger: logging.Logger) -> None:
    if any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger.handlers
    ):
        return
    console_handler = logging.StreamHandler()
    console_handler.setLevel(resolve_log_console_level())
    console_format = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)


def _ensure_file_handler(logger: logging.Logger) -> None:
    if any(isinstance(handler, TimedRotatingFileHandler) for handler in logger.handlers):
        return
    log_dir = Path(Config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "subtitle.log"
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=max(1, int(getattr(Config, "LOG_RETENTION_DAYS", 14) or 14)),
        encoding="utf-8",
    )
    file_handler.setLevel(resolve_log_file_level())
    file_handler.suffix = "%Y%m%d"
    file_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(funcName)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)


def setup_logging():
    """로깅 시스템 초기화 - 파일 및 콘솔 출력"""
    logger = logging.getLogger("SubtitleExtractor")
    # 로거 자체는 DEBUG까지 받고 핸들러가 필터한다
    logger.setLevel(logging.DEBUG)

    _ensure_console_handler(logger)
    try:
        _ensure_file_handler(logger)
    except Exception as exc:
        logger.warning("파일 로그 핸들러 초기화 실패: %s", exc)
    return logger


def ensure_file_logging() -> logging.Logger:
    """startup preflight 이후 파일 핸들러를 보장한다."""
    logger = logging.getLogger("SubtitleExtractor")
    logger.setLevel(logging.DEBUG)
    _ensure_console_handler(logger)
    _ensure_file_handler(logger)
    return logger


logger = setup_logging()
