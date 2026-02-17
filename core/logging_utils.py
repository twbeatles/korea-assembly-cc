# -*- coding: utf-8 -*-
"""
로깅 유틸리티
"""

import logging
from datetime import datetime
from pathlib import Path


def setup_logging():
    """로깅 시스템 초기화 - 파일 및 콘솔 출력"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / f"subtitle_{datetime.now().strftime('%Y%m%d')}.log"

    # 로거 설정
    logger = logging.getLogger("SubtitleExtractor")
    logger.setLevel(logging.DEBUG)

    # 이미 핸들러가 있으면 추가하지 않음
    if logger.handlers:
        return logger

    # 파일 핸들러 (DEBUG 레벨)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(funcName)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_format)

    # 콘솔 핸들러 (INFO 레벨)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_format)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


logger = setup_logging()
