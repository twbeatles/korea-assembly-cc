# -*- coding: utf-8 -*-

import json
import os
import queue
import re
import threading
import time
from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QComboBox,
    QCheckBox,
    QApplication,
    QFrame,
    QProgressBar,
    QMessageBox,
    QFileDialog,
    QGroupBox,
    QGridLayout,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QSplitter,
    QMenu,
    QMenuBar,
    QInputDialog,
    QSystemTrayIcon,
    QAbstractItemView,
    QTreeWidget,
    QTreeWidgetItem,
    QToolBar,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QSettings
from PyQt6.QtGui import (
    QCloseEvent,
    QFont,
    QColor,
    QTextCursor,
    QTextCharFormat,
    QAction,
    QShortcut,
    QKeySequence,
    QIcon,
)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    WebDriverException,
    NoSuchElementException,
    StaleElementReferenceException,
)
from selenium.webdriver.chrome.options import Options

from core.config import Config
from core.live_capture import (
    clear_live_capture_ledger,
    create_empty_live_capture_ledger,
    get_live_row,
    mark_live_row_committed,
    normalize_capture_event,
    reconcile_live_capture,
    set_live_row_baseline,
)
from core.logging_utils import logger
from core.models import CaptureSessionState, ObservedSubtitleRow, SubtitleEntry
from core.subtitle_pipeline import (
    LiveRowCommitMeta,
    PipelineSourceMeta,
    apply_keepalive,
    apply_preview,
    apply_reset,
    commit_live_row,
    create_empty_capture_state,
    finalize_session,
    flush_pending_previews,
    rebuild_confirmed_history,
)
from ui.dialogs import LiveBroadcastDialog
from ui.themes import DARK_THEME, LIGHT_THEME
from ui.widgets import CollapsibleGroupBox, ToastWidget
from core import utils
from core.subtitle_processor import SubtitleProcessor


class _TimerSignalShim:
    def __init__(self) -> None:
        self._callback = None

    def connect(self, callback) -> None:
        self._callback = callback


class _ResetTimerShim:
    def __init__(self) -> None:
        self.timeout = _TimerSignalShim()
        self._active = False

    def setSingleShot(self, _single_shot: bool) -> None:
        return None

    def start(self, _msec: int) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def isActive(self) -> bool:
        return self._active


class DatabaseProtocol(Protocol):
    def save_session(self, session_data: object) -> int: ...
    def load_session(self, session_id: int) -> dict[str, Any] | None: ...
    def delete_session(self, session_id: int) -> bool: ...
    def search_subtitles(self, query: str, limit: Any = ...) -> list[dict[str, Any]]: ...
    def get_statistics(self) -> dict[str, Any]: ...
    def list_sessions(
        self, limit: Any = ..., offset: Any = ...
    ) -> list[dict[str, Any]]: ...
    def close_all(self) -> None: ...


DatabaseManagerClass: type[DatabaseProtocol] | None
try:
    from database import DatabaseManager as DatabaseManagerClass

    DB_AVAILABLE = True
except ImportError:
    DatabaseManagerClass = None
    DB_AVAILABLE = False
    logger.warning(
        "database.py 모듈을 찾을 수 없습니다. 데이터베이스 기능은 비활성화됩니다."
    )


class RecoverableWebDriverError(RuntimeError):
    """웹드라이버 재연결로 복구 가능한 오류"""


def _import_optional_module(module_name: str) -> Any:
    """Keep optional dependency imports dynamic so baseline Pylance checks stay stable."""
    return cast(Any, import_module(module_name))


