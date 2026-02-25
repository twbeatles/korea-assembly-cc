import logging
from pathlib import Path

from core.config import Config
from core.logging_utils import logger


def test_logger_file_handler_uses_config_log_dir():
    log_dir = Path(Config.LOG_DIR).resolve()
    file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
    assert file_handlers, "파일 핸들러가 최소 1개 있어야 합니다."

    for handler in file_handlers:
        log_path = Path(handler.baseFilename).resolve()
        assert log_path.parent == log_dir
