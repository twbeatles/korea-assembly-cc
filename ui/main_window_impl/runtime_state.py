# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any, Callable, cast

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QTextCharFormat

from core.config import Config
from core.live_capture import create_empty_live_capture_ledger
from core.logging_utils import logger
from core.models import CaptureSessionState, SubtitleEntry
from core.subtitle_pipeline import (
    PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD,
    PREVIEW_RESYNC_THRESHOLD,
    SUFFIX_LENGTH,
    create_empty_capture_state,
)
from core.subtitle_processor import SubtitleProcessor
from ui.main_window_common import (
    DB_AVAILABLE,
    DatabaseManagerClass,
    DatabaseProtocol,
    MainWindowMessageQueue,
    ToastWidget,
)
from ui.main_window_impl.contracts import RuntimeHost


RuntimeStateBase = object


class MainWindowRuntimeStateMixin(RuntimeStateBase):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{Config.APP_NAME} v{Config.VERSION}")
        self.setWindowIcon(QIcon(Config.get_resource_path("assets/icon.ico")))
        self.setMinimumSize(1100, 750)
        self.resize(1200, 800)

        if Config.SETTINGS_INI_PATH:
            self.settings = QSettings(
                Config.SETTINGS_INI_PATH,
                QSettings.Format.IniFormat,
            )
        else:
            self.settings = QSettings("AssemblySubtitle", "Extractor")
        self.is_dark_theme = self.settings.value("dark_theme", True, type=bool)
        self.font_size = self.settings.value(
            "font_size", Config.DEFAULT_FONT_SIZE, type=int
        )
        self.minimize_to_tray = self.settings.value(
            "minimize_to_tray", False, type=bool
        )
        self.auto_clean_newlines_enabled = self.settings.value(
            "auto_clean_newlines",
            Config.AUTO_CLEAN_NEWLINES_DEFAULT,
            type=bool,
        )

        self.message_queue: Any = MainWindowMessageQueue(self, maxsize=500)

        self.worker = None
        self.driver = None
        self._driver_lock = threading.Lock()
        self.is_running = False
        self.stop_event = threading.Event()
        self.subtitle_lock = threading.Lock()
        self._auto_backup_lock = threading.Lock()
        self.start_time = None
        self.last_subtitle = ""
        self._last_raw_text = ""
        self._last_processed_raw = ""
        self._stream_start_time = None

        self._confirmed_compact = ""
        self._trailing_suffix = ""
        self._suffix_length = SUFFIX_LENGTH
        self._preview_desync_count = 0
        self._preview_ambiguous_skip_count = 0
        self._last_good_raw_compact = ""
        self._preview_resync_threshold = PREVIEW_RESYNC_THRESHOLD
        self._preview_ambiguous_resync_threshold = PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD

        self.subtitle_processor = SubtitleProcessor()

        saved_keywords = self.settings.value("highlight_keywords", "")
        if not saved_keywords:
            legacy_keywords = self.settings.value("keywords", "", type=str)
            if legacy_keywords:
                saved_keywords = legacy_keywords
                self.settings.setValue("highlight_keywords", legacy_keywords)
                self.settings.remove("keywords")
        self.keywords = (
            [k.strip() for k in saved_keywords.split(",") if k.strip()]
            if saved_keywords
            else []
        )
        saved_alert = self.settings.value("alert_keywords", "")
        self.alert_keywords = (
            [k.strip() for k in saved_alert.split(",") if k.strip()]
            if saved_alert
            else []
        )
        self._alert_keywords_cache = []
        self._rebuild_alert_keyword_cache(self.alert_keywords, update_settings=False)
        self.last_update_time = 0

        self._highlight_fmt = QTextCharFormat()
        self._highlight_fmt.setBackground(QColor("#ffd700"))
        self._highlight_fmt.setForeground(QColor("#000000"))
        self._highlight_fmt.setFontWeight(QFont.Weight.Bold)
        self._normal_fmt = QTextCharFormat()
        self._timestamp_fmt = QTextCharFormat()
        self._timestamp_fmt.setForeground(QColor("#888888"))

        self._keyword_pattern = None
        self._keywords_lower_set = set()
        self._rebuild_keyword_cache(self.keywords, update_settings=False, refresh=False)

        self._cached_total_chars = 0
        self._cached_total_words = 0

        self._last_rendered_count = 0
        self._last_rendered_last_text = ""
        self._last_render_offset = 0
        self._last_render_show_ts = None
        self._last_render_chunk_specs: list[tuple[str, str, str]] = []
        self._rendered_entry_text_spans: dict[int, tuple[int, int]] = {}
        self._pending_ui_refresh_flags = 0
        self._pending_ui_refresh_force_full = False
        self._ui_refresh_scheduled = False
        self._use_async_ui_refresh = True
        self._pending_status_text = ""
        self._pending_status_type = "info"
        self._pending_search_count_index: int | None = None
        self._queue_drain_scheduled = False
        self._use_async_queue_drain = True
        self._runtime_sensitive_controls: list[Any] = []
        self._search_focus_entry_index: int | None = None
        self._pending_search_focus_query = ""

        self.active_toasts: list[ToastWidget] = []

        self.realtime_file = None
        self._realtime_error_count = 0
        self._realtime_save_status = "inactive"
        self._realtime_save_path = ""
        self._realtime_save_active = False
        self._runtime_session_root: Path | None = None
        self._runtime_manifest_path: Path | None = None
        self._runtime_archive_token = ""
        self._runtime_archive_run_id: int | None = None
        self._runtime_segment_manifest: list[dict[str, Any]] = []
        self._runtime_next_segment_index = 1
        self._runtime_archived_count = 0
        self._runtime_archived_chars = 0
        self._runtime_archived_words = 0
        self._runtime_segment_flush_in_progress = False
        self._runtime_segment_cache_key = ""
        self._runtime_segment_cache_entries: list[SubtitleEntry] = []
        self._runtime_segment_cache_keys: list[str] = []
        self._runtime_segment_cache_entries_by_key: dict[str, list[SubtitleEntry]] = {}
        self._runtime_segment_locator_starts: list[int] = []
        self._runtime_segment_locator_ends: list[int] = []
        self._runtime_segment_locator_items: list[dict[str, Any]] = []
        self._runtime_render_window_cache_key: tuple[int, int, int, int] | None = None
        self._runtime_render_window_cache_entries: list[SubtitleEntry] = []
        self._runtime_segment_search_text_cache: dict[str, list[str]] = {}
        self._runtime_search_in_progress = False
        self._runtime_search_revision = 0
        self._runtime_search_query = ""
        self._runtime_search_truncated = False
        self._runtime_search_requested_query = ""
        self._runtime_tail_revision = 0
        self._runtime_tail_checkpoint_revision = -1
        self._db_history_request_token = 0
        self._db_search_request_token = 0
        self._overflow_passthrough_messages: list[Any] = []
        self._overflow_passthrough_lock = threading.Lock()
        self._db_worker_thread: threading.Thread | None = None
        self._db_worker_queue: queue.Queue[Any] = queue.Queue()
        self._db_worker_lock = threading.Lock()
        self._db_worker_shutdown = False
        self._db_worker_current_task = ""
        self._last_exit_escalation_at = 0.0
        self._exit_escalation_active = False

        self.capture_state: CaptureSessionState = create_empty_capture_state()
        self.subtitles: list[SubtitleEntry] = self.capture_state.entries
        self.live_capture_ledger = create_empty_live_capture_ledger()
        self._pending_subtitle_reset_source = ""
        self._pending_subtitle_reset_timer = QTimer(self)
        self._pending_subtitle_reset_timer.setSingleShot(True)
        self._pending_subtitle_reset_timer.timeout.connect(
            self._commit_scheduled_subtitle_reset
        )
        self._runtime_search_debounce_timer = QTimer(self)
        self._runtime_search_debounce_timer.setSingleShot(True)
        self._runtime_search_debounce_timer.timeout.connect(
            self._run_scheduled_search
        )
        self._detached_drivers: list[Any] = []
        self._detached_drivers_lock = threading.Lock()
        self._last_subtitle_frame_path = ()

        self.connection_status = "disconnected"
        self.last_ping_time = 0
        self.ping_latency = 0

        self.reconnect_attempts = 0
        self.auto_reconnect_enabled = self.settings.value(
            "auto_reconnect", True, type=bool
        )
        self.current_url = ""
        self._capture_source_url = ""
        self._capture_source_committee = ""
        self._capture_source_headless = False
        self._capture_source_realtime = False
        self._session_dirty = False
        self.current_session_lineage_id = ""
        self.current_db_session_id: int | None = None

        self._user_scrolled_up = False
        self._is_stopping = False
        self._capture_run_sequence = 0
        self._active_capture_run_id: int | None = None
        self._worker_message_lock = threading.Lock()
        self._coalesced_worker_messages: dict[tuple[int, str], Any] = {}
        self._control_message_lock = threading.Lock()
        self._coalesced_control_messages: dict[object, tuple[str, Any]] = {}
        self._last_status_message = ""
        self._session_save_in_progress = False
        self._pending_deferred_action: Callable[[], None] | None = None
        self._pending_deferred_action_name = ""
        self._pending_deferred_action_after_save = False
        self._session_load_in_progress = False
        self._reflow_in_progress = False
        self._hydrate_in_progress = False
        self._hydrate_cancel_event = threading.Event()
        self._hydrate_progress_dialog = None
        self._pending_hydration_action: Callable[[], None] | None = None
        self._pending_hydration_action_name = ""
        self._initial_recovery_snapshot_done = False
        self._destructive_undo_snapshot: dict[str, Any] | None = None
        self._restoring_destructive_undo = False
        self._startup_recovery_prompted = False
        self._db_history_dialog_state: dict[str, Any] | None = None
        self._db_search_dialog_state: dict[str, Any] | None = None
        self._active_background_threads: set[threading.Thread] = set()
        self._active_background_threads_lock = threading.Lock()
        self._background_shutdown_initiated = False
        self._detached_driver_cleanup_lock = threading.Lock()
        self._detached_driver_cleanup_in_progress = False

        self.url_history = self._load_url_history()

        self._create_menu()
        self._create_ui()
        self._apply_theme()
        self._setup_shortcuts()
        self._sync_runtime_action_state()

        self.queue_timer = QTimer(self)
        self.queue_timer.timeout.connect(self._process_message_queue)
        self.queue_timer.start(Config.QUEUE_PROCESS_INTERVAL)

        self.detached_driver_cleanup_timer = QTimer(self)
        self.detached_driver_cleanup_timer.timeout.connect(
            lambda: self._schedule_detached_driver_cleanup()
        )
        self.detached_driver_cleanup_timer.start(Config.DETACHED_DRIVER_CLEANUP_INTERVAL)

        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self._update_stats)

        self.backup_timer = QTimer(self)
        self.backup_timer.timeout.connect(self._auto_backup)

        Path(Config.SESSION_DIR).mkdir(parents=True, exist_ok=True)
        Path(Config.REALTIME_DIR).mkdir(parents=True, exist_ok=True)
        Path(Config.BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        Path(Config.RUNTIME_SESSION_DIR).mkdir(parents=True, exist_ok=True)

        self.db: DatabaseProtocol | None = None
        self._db_tasks_inflight: set[str] = set()
        if DB_AVAILABLE and DatabaseManagerClass is not None:
            try:
                db_factory = cast(Callable[[str], DatabaseProtocol], DatabaseManagerClass)
                self.db = db_factory(Config.DATABASE_PATH)
            except Exception as e:
                logger.error(f"데이터베이스 초기화 실패: {e}")

        try:
            self._cleanup_orphan_runtime_archives()
        except Exception:
            logger.debug("runtime archive 정리 실패", exc_info=True)

        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)

        self._setup_tray()
        QTimer.singleShot(0, self._prompt_session_recovery_if_available)
