# -*- coding: utf-8 -*-
"""
로깅 유틸리티
"""

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from core.config import Config


def _ensure_console_handler(logger: logging.Logger) -> None:
    if any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger.handlers
    ):
        return
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
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
    file_handler.setLevel(logging.DEBUG)
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
