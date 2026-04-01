# -*- coding: utf-8 -*-

import json
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
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
    PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD,
    PREVIEW_RESYNC_THRESHOLD,
    PipelineSourceMeta,
    SUFFIX_LENGTH,
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
    def search_subtitles(
        self,
        query: str,
        limit: Any = ...,
        offset: Any = ...,
        syntax: str = ...,
    ) -> list[dict[str, Any]]: ...
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


@dataclass(slots=True)
class WorkerQueueMessage:
    """Run-scoped worker message envelope used to drop stale capture runs."""

    run_id: int
    msg_type: str
    payload: Any


@dataclass(slots=True)
class SearchMatch:
    """Rendered-search match anchored to a subtitle entry."""

    entry_index: int
    char_start: int
    char_length: int


@dataclass(slots=True)
class SubtitleDialogItem:
    """Searchable subtitle row model used by edit/delete dialogs."""

    source_index: int
    timestamp_text: str
    text: str
    normalized_text: str
    display_text: str
    search_blob: str


def build_subtitle_dialog_items(
    entries: list[SubtitleEntry],
    normalize_text: Callable[[object], str],
    preview_limit: int = 80,
) -> list[SubtitleDialogItem]:
    items: list[SubtitleDialogItem] = []
    for index, entry in enumerate(entries):
        timestamp = getattr(entry, "timestamp", None)
        timestamp_text = (
            timestamp.strftime("%H:%M:%S") if isinstance(timestamp, datetime) else ""
        )
        raw_text = str(getattr(entry, "text", "") or "")
        normalized_text = str(normalize_text(raw_text) or "").strip()
        preview_text = normalized_text.replace("\n", " ")
        if len(preview_text) > preview_limit:
            preview_text = preview_text[:preview_limit] + "..."
        display_text = (
            f"[{timestamp_text}] {preview_text}" if timestamp_text else preview_text
        )
        search_blob = f"{timestamp_text} {normalized_text}".strip().lower()
        items.append(
            SubtitleDialogItem(
                source_index=index,
                timestamp_text=timestamp_text,
                text=raw_text,
                normalized_text=normalized_text,
                display_text=display_text,
                search_blob=search_blob,
            )
        )
    return items


def filter_subtitle_dialog_items(
    items: list[SubtitleDialogItem],
    query: str,
) -> list[SubtitleDialogItem]:
    needle = str(query or "").strip().lower()
    if not needle:
        return list(items)
    return [item for item in items if needle in item.search_blob]


class MainWindowMessageQueue:
    """Queue wrapper that automatically envelopes worker-thread messages."""

    def __init__(self, owner: Any, maxsize: int = 0) -> None:
        self._owner = owner
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=maxsize)
        self._worker_local = threading.local()

    def set_worker_run_id(self, run_id: int | None) -> None:
        self._worker_local.run_id = run_id

    def clear_worker_run_id(self) -> None:
        self._worker_local.run_id = None

    def _get_worker_run_id(self) -> int | None:
        run_id = getattr(self._worker_local, "run_id", None)
        return int(run_id) if run_id is not None else None

    def put(self, item: object, block: bool = True, timeout: float | None = None) -> None:
        run_id = self._get_worker_run_id()
        if run_id is not None and isinstance(item, tuple) and len(item) == 2:
            msg_type, data = item
            self._owner._emit_worker_message(str(msg_type), data, run_id=run_id)
            return
        if timeout is None:
            self._queue.put(item, block=block)
            return
        self._queue.put(item, block=block, timeout=timeout)

    def put_nowait(self, item: object) -> None:
        self.put(item, block=False)

    def get(self, block: bool = True, timeout: float | None = None) -> Any:
        if timeout is None:
            return self._queue.get(block=block)
        return self._queue.get(block=block, timeout=timeout)

    def get_nowait(self) -> Any:
        return self._queue.get_nowait()

    def empty(self) -> bool:
        return self._queue.empty()

    def qsize(self) -> int:
        return self._queue.qsize()


def _import_optional_module(module_name: str) -> Any:
    """Keep optional dependency imports dynamic so baseline Pylance checks stay stable."""
    return cast(Any, import_module(module_name))


