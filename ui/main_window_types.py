from __future__ import annotations

import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Pattern, TextIO

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtGui import QAction, QTextCharFormat
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QSplitter,
    QSystemTrayIcon,
    QTextEdit,
)

from core.live_capture import LiveCaptureLedger
from core.models import CaptureSessionState, SubtitleEntry
from core.subtitle_processor import SubtitleProcessor
from ui.main_window_common import SearchMatch, WorkerQueueMessage
from ui.widgets import CollapsibleGroupBox, ToastWidget

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QMainWindow
    from ui.main_window_common import DatabaseProtocol

    class MainWindowHost(QMainWindow):
        settings: QSettings
        font_size: int
        minimize_to_tray: bool
        message_queue: queue.Queue[Any]
        worker: threading.Thread | None
        driver: Any | None
        _driver_lock: Any
        is_running: bool
        stop_event: threading.Event
        subtitle_lock: Any
        _auto_backup_lock: Any
        start_time: float | None
        last_subtitle: str
        _last_raw_text: str
        _last_processed_raw: str
        _stream_start_time: float | None
        subtitles: list[SubtitleEntry]
        subtitle_processor: SubtitleProcessor
        keywords: list[str]
        alert_keywords: list[str]
        _alert_keywords_cache: list[tuple[str, str]]
        last_update_time: float | int
        _highlight_fmt: QTextCharFormat
        _normal_fmt: QTextCharFormat
        _timestamp_fmt: QTextCharFormat
        _keyword_pattern: Pattern[str] | None
        _keywords_lower_set: set[str]
        _cached_total_chars: int
        _cached_total_words: int
        _user_scrolled_up: bool
        _last_printed_ts: datetime | None
        _last_rendered_count: int
        _last_rendered_last_text: str
        _last_render_offset: int
        _last_render_show_ts: bool | None
        _last_render_chunk_specs: list[tuple[str, str, str]]
        _rendered_entry_text_spans: dict[int, tuple[int, int]]
        active_toasts: list[ToastWidget]
        realtime_file: TextIO | None
        _realtime_save_status: str
        _realtime_save_path: str
        _realtime_save_active: bool
        capture_state: CaptureSessionState
        live_capture_ledger: LiveCaptureLedger
        _pending_subtitle_reset_source: str
        _pending_subtitle_reset_timer: QTimer | Any
        auto_reconnect_enabled: bool
        reconnect_attempts: int
        connection_status: str
        last_ping_time: float | int
        ping_latency: int
        current_url: str
        _capture_source_url: str
        _capture_source_committee: str
        _capture_source_headless: bool
        _capture_source_realtime: bool
        _session_dirty: bool
        is_dark_theme: bool
        _db_history_dialog_state: dict[str, Any] | None
        _db_search_dialog_state: dict[str, Any] | None
        _active_background_threads: set[threading.Thread]
        _active_background_threads_lock: Any
        _background_shutdown_initiated: bool
        _is_stopping: bool
        _capture_run_sequence: int
        _active_capture_run_id: int | None
        _worker_message_lock: Any
        _coalesced_worker_messages: dict[tuple[int, str], Any]
        _control_message_lock: Any
        _coalesced_control_messages: dict[object, tuple[str, Any]]
        db: DatabaseProtocol | None
        _db_tasks_inflight: set[str]
        _detached_drivers: list[Any]
        _detached_drivers_lock: Any
        _detached_driver_cleanup_lock: Any
        _detached_driver_cleanup_in_progress: bool
        _preview_resync_threshold: int
        _preview_ambiguous_resync_threshold: int
        _suffix_length: int
        _confirmed_compact: str
        _trailing_suffix: str
        _preview_desync_count: int
        _preview_ambiguous_skip_count: int
        _last_good_raw_compact: str
        _last_status_message: str
        _session_save_in_progress: bool
        _session_load_in_progress: bool
        _reflow_in_progress: bool
        _initial_recovery_snapshot_done: bool
        _destructive_undo_snapshot: dict[str, Any] | None
        _restoring_destructive_undo: bool
        _startup_recovery_prompted: bool
        _realtime_error_count: int
        _last_subtitle_frame_path: tuple[int, ...]
        url_history: dict[str, str]
        committee_presets: dict[str, str]
        custom_presets: dict[str, str]
        _runtime_sensitive_controls: list[QAction | QPushButton | QCheckBox]
        _search_focus_entry_index: int | None
        _pending_search_focus_query: str
        url_combo: QComboBox
        selector_combo: QComboBox
        keyword_input: QLineEdit
        search_input: QLineEdit
        subtitle_text: QTextEdit
        preview_frame: QFrame
        preview_label: QLabel
        status_label: QLabel
        realtime_status_label: QLabel
        count_label: QLabel
        connection_indicator: QLabel
        stat_time: QLabel
        stat_chars: QLabel
        stat_words: QLabel
        stat_sents: QLabel
        stat_cpm: QLabel
        search_count: QLabel
        search_frame: QFrame
        main_splitter: QSplitter
        progress: QProgressBar
        auto_scroll_check: QCheckBox
        auto_clean_newlines_check: QCheckBox
        headless_check: QCheckBox
        realtime_save_check: QCheckBox
        start_btn: QPushButton
        stop_btn: QPushButton
        live_btn: QPushButton
        preset_btn: QPushButton
        tag_btn: QPushButton
        theme_toggle_btn: QPushButton
        toggle_stats_btn: QPushButton
        toggle_header_btn: QPushButton
        scroll_to_bottom_btn: QPushButton
        clean_btn: QPushButton
        clear_btn: QPushButton
        timestamp_action: QAction
        theme_action: QAction
        tray_action: QAction
        tray_status_action: QAction
        load_session_action: QAction
        edit_subtitle_action: QAction
        delete_subtitle_action: QAction
        clear_action: QAction
        undo_destructive_action: QAction
        merge_action: QAction
        clean_newlines_action: QAction
        tray_icon: QSystemTrayIcon
        preset_menu: QMenu
        top_header_container: Any
        settings_group: CollapsibleGroupBox
        stats_group: QGroupBox
        backup_timer: QTimer
        stats_timer: QTimer
        queue_timer: QTimer
        detached_driver_cleanup_timer: QTimer
        search_matches: list[SearchMatch]
        search_idx: int

        def _show_toast(
            self,
            message: str,
            toast_type: str = "info",
            duration: int = 3000,
        ) -> None: ...

        def _set_status(self, text: str, status_type: str = "info") -> None: ...
        def _update_count_label(self) -> None: ...
        def _update_connection_status(
            self, status: str, latency: int | None = None
        ) -> None: ...
        def _update_tray_status(self, status: str) -> None: ...
        def _get_current_url(self) -> str: ...
        def _autodetect_tag(self, url: str) -> str: ...
        def _add_to_history(self, url: str, tag: str = "") -> None: ...
        def _activate_capture_run(self) -> int: ...
        def _append_text_to_subtitles_shared(
            self,
            text: str,
            *,
            now: datetime | None = None,
            force_new_entry: bool = False,
            refresh: bool = True,
            check_alert: bool = True,
        ) -> dict[str, Any]: ...
        def _build_prepared_entries_snapshot(self) -> list[SubtitleEntry]: ...
        def _build_preview_payload_from_probe(
            self, probe_result: dict[str, Any]
        ) -> dict[str, Any]: ...
        def _check_keyword_alert(self, text: str) -> None: ...
        def _clear_destructive_undo_state(self) -> None: ...
        def _clear_current_driver_if(self, driver: Any | None) -> bool: ...
        def _clean_newlines(self) -> None: ...
        def _clear_preview(self) -> None: ...
        def _clear_subtitles(self) -> None: ...
        def _close_realtime_save_file(self) -> None: ...
        def _coerce_highlight_sequence(self, value: object) -> int: ...
        def _clear_text(self) -> None: ...
        def _copy_to_clipboard(self) -> None: ...
        def _delete_subtitle(self) -> None: ...
        def _deserialize_subtitles(
            self,
            serialized_items: object,
            source: str = "",
        ) -> tuple[list[SubtitleEntry], int]: ...
        def _complete_loaded_session(self, payload: dict[str, Any]) -> bool: ...
        def _do_search(self) -> None: ...
        def _edit_subtitle(self) -> None: ...
        def _ensure_active_capture_run(self) -> int: ...
        def _export_stats(self) -> None: ...
        def _finalize_subtitle(self, text: str) -> None: ...
        def _get_current_driver(self) -> Any | None: ...
        def _handle_db_task_error(
            self, task_name: str, error: str, context: dict[str, Any] | None = None
        ) -> None: ...
        def _handle_db_task_result(
            self, task_name: str, result: Any, context: dict[str, Any] | None = None
        ) -> None: ...
        def _handle_hwp_save_failure(self, error: object) -> None: ...
        def _hide_search(self) -> None: ...
        def _is_background_shutdown_active(self) -> bool: ...
        def _join_stream_text(self, base: str, addition: str) -> str: ...
        def _is_active_capture_run(self, run_id: int | None) -> bool: ...
        def _is_auto_clean_newlines_enabled(self) -> bool: ...
        def _is_runtime_mutation_blocked(self, action_name: str) -> bool: ...
        def _invalidate_destructive_undo(self) -> None: ...
        def _load_session(self) -> None: ...
        def _notify_destructive_undo_available(self) -> None: ...
        def _open_realtime_save_for_run(self) -> bool: ...
        def _prompt_write_session_snapshot(
            self,
            prepared_entries: list[SubtitleEntry],
            *,
            dialog_title: str = ...,
        ) -> dict[str, Any] | None: ...
        def _confirm_dirty_session_action(self, action_name: str) -> bool: ...
        def _block_session_replacement_while_saving(self, action_name: str) -> bool: ...
        def _start_session_load_from_path(
            self,
            path: str,
            *,
            mark_dirty: bool = False,
            recovery: bool = False,
        ) -> bool: ...
        def _schedule_initial_recovery_snapshot_if_needed(
            self,
            prepared_entries: list[SubtitleEntry] | None = None,
        ) -> bool: ...
        def _start_db_session_load(
            self,
            session_id: int | str | None,
            *,
            task_name: str,
            action_name: str,
            loading_text: str,
            busy_message: str,
            source_tag: str,
            set_busy: Callable[[bool, str], None] | None = None,
            dialog: object | None = None,
            highlight_sequence: int = -1,
            highlight_query: str = "",
        ) -> bool: ...
        def _start_backup_snapshot_write(
            self,
            prepared_entries: list[SubtitleEntry],
            *,
            worker_name: str = ...,
        ) -> bool: ...
        def _emit_control_message(self, msg_type: str, data: Any) -> None: ...
        def _load_recovery_state(self) -> dict[str, Any] | None: ...
        def _clear_recovery_state(self) -> None: ...
        def _prompt_session_recovery_if_available(self) -> None: ...
        def _merge_sessions(
            self,
            file_paths: list[Path | str],
            remove_duplicates: bool = True,
            sort_by_time: bool = True,
            existing_subtitles: list[SubtitleEntry] | None = None,
            dedupe_mode: str = "legacy_bucket",
        ) -> list[SubtitleEntry]: ...
        def _nav_search(self, delta: int) -> None: ...
        def _on_scroll_changed(self) -> None: ...
        def _perform_keyword_cache_update(self) -> None: ...
        def _rebuild_stats_cache(self) -> None: ...
        def _refresh_text(self, force_full: bool = False) -> None: ...
        def _refresh_text_full(self, *_args: object) -> None: ...
        def _replace_subtitles_and_refresh(
            self,
            new_subtitles: list[SubtitleEntry],
            keep_history_from_subtitles: bool | None = None,
        ) -> None: ...
        def _normalize_subtitle_text_for_option(self, text: object) -> str: ...
        def _reset_ui(self) -> None: ...
        def _retire_capture_run(self, run_id: int | None = None) -> None: ...
        def _save_docx(self) -> None: ...
        def _save_hwpx(self) -> None: ...
        def _save_hwp(self) -> None: ...
        def _set_current_driver(self, driver: Any | None) -> Any | None: ...
        def _toggle_auto_clean_newlines_option(self) -> None: ...
        def _save_rtf(self) -> None: ...
        def _save_session(self) -> None: ...
        def _handle_escape_shortcut(self) -> None: ...
        def _save_srt(self) -> None: ...
        def _save_txt(self) -> None: ...
        def _save_vtt(self) -> None: ...
        def _scroll_to_bottom(self) -> None: ...
        def _schedule_detached_driver_cleanup(
            self, timeout: float | None = None
        ) -> bool: ...
        def _register_detached_driver(self, driver: Any) -> None: ...
        def _take_current_driver(self) -> Any | None: ...
        def _set_alert_keywords(self) -> None: ...
        def _set_keywords(self) -> None: ...
        def _set_preview_text(self, text: str) -> None: ...
        def _show_db_history(self) -> None: ...
        def _show_db_search(self) -> None: ...
        def _show_db_stats(self) -> None: ...
        def _show_live_dialog(self) -> None: ...
        def _show_merge_dialog(self) -> None: ...
        def _show_search(self) -> None: ...
        def _mark_session_dirty(self) -> None: ...
        def _clear_session_dirty(self) -> None: ...
        def _has_dirty_session(self) -> bool: ...
        def _start(self) -> None: ...
        def _start_background_thread(self, target: Any, name: str) -> bool: ...
        def _stop(self, for_app_exit: bool = False) -> None: ...
        def _wait_for_background_threads_during_exit(self) -> None: ...
        def _toggle_stats_panel(self) -> None: ...
        def _toggle_theme(self) -> None: ...
        def _toggle_theme_from_button(self) -> None: ...
        def _sync_runtime_action_state(self) -> None: ...
        def _update_keyword_cache(self) -> None: ...
        def _get_capture_source_url(self, fallback_to_current: bool = True) -> str: ...
        def _get_capture_source_committee(
            self, fallback_to_url: bool = True
        ) -> str: ...
        def _set_capture_source_metadata(
            self,
            url: str,
            committee_name: str = "",
            *,
            headless: bool = False,
            realtime: bool = False,
        ) -> None: ...
        def _set_realtime_save_status(self, status: str, *, path: str = "") -> None: ...
        def _reset_realtime_save_run_state(self) -> None: ...
        def _restore_last_destructive_change(self) -> bool: ...
        def _store_destructive_undo_snapshot(self) -> bool: ...
        def _update_destructive_undo_action_state(self) -> None: ...
        def _update_realtime_status_indicator(self) -> None: ...

else:
    class MainWindowHost:
        """Runtime-light base class for type-checking-only main window contracts."""

        pass
