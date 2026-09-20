# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from core.config import Config
from core.live_capture import create_empty_live_capture_ledger
from core.logging_utils import logger
from core.subtitle_pipeline import create_empty_capture_state, finalize_session
from core.selector_policy import validate_subtitle_selector
from core.url_policy import validate_assembly_url
from ui.main_window_impl.contracts import RuntimeHost

from ui.main_window_impl.runtime_lifecycle_common import (
    RuntimeLifecycleBase,
    _main_window_public,
)


class MainWindowRuntimeLifecycleExtractionMixin(RuntimeLifecycleBase):
    """추출 시작 (SRP: 시작 검증/런 기동)."""

    def _current_session_entry_count_for_start(self) -> int:
        """시작 전 교체될 현재 세션 자막 수(아카이브 포함)."""
        getter = getattr(self, "_get_global_subtitle_count", None)
        if callable(getter):
            try:
                return max(0, int(cast(Any, getter())))
            except Exception:
                pass
        subtitles = getattr(self, "subtitles", None) or []
        try:
            active = len(subtitles)
        except Exception:
            active = 0
        archived = int(self.__dict__.get("_runtime_archived_count", 0) or 0)
        return max(0, active + archived)

    def _confirm_replace_session_for_start(self, subtitle_count: int) -> bool:
        """clean 세션이지만 자막이 있을 때 시작 교체 확인."""
        main_window_mod = _main_window_public()
        reply = main_window_mod.QMessageBox.question(
            self,
            "추출 시작 확인",
            f"현재 {subtitle_count}개의 자막이 있습니다.\n"
            "새 추출을 시작하면 현재 자막이 화면에서 사라집니다.\n"
            "계속하시겠습니까?",
            main_window_mod.QMessageBox.StandardButton.Yes
            | main_window_mod.QMessageBox.StandardButton.No,
            main_window_mod.QMessageBox.StandardButton.No,
        )
        return reply == main_window_mod.QMessageBox.StandardButton.Yes

    def _start(self):
        main_window_mod = _main_window_public()
        if self.is_running:
            return
        if bool(self.__dict__.get("_exit_in_progress", False)) or (
            callable(getattr(self, "_is_background_shutdown_active", None))
            and self._is_background_shutdown_active()
        ):
            self._set_status("종료 중...", "warning")
            self._show_toast("종료 중에는 추출을 시작할 수 없습니다.", "warning", 2500)
            return
        if bool(self.__dict__.get("_session_save_in_progress", False)):
            self._set_status("세션 저장 마무리 대기 중...", "warning")
            self._show_toast("세션 저장 완료 후 추출을 시작하세요.", "warning", 3000)
            return
        if bool(self.__dict__.get("_session_load_in_progress", False)):
            self._set_status("세션 불러오기 마무리 대기 중...", "warning")
            self._show_toast("세션 불러오기 완료 후 추출을 시작하세요.", "warning", 3000)
            return

        url = self._get_current_url().strip()
        selector = self.selector_combo.currentText().strip()

        if not url or not selector:
            main_window_mod.QMessageBox.warning(self, "오류", "URL과 선택자를 입력하세요.")
            return

        normalized_selector, selector_error = validate_subtitle_selector(selector)
        if normalized_selector is None:
            main_window_mod.QMessageBox.warning(
                self,
                "오류",
                selector_error or "올바른 CSS 선택자를 입력하세요.",
            )
            return
        selector = normalized_selector

        normalized_url, url_error = validate_assembly_url(url)
        if normalized_url is None:
            warning_message = (
                url_error or "올바른 국회 의사중계 URL을 입력하세요."
            ).replace("프리셋 URL", "URL")
            main_window_mod.QMessageBox.warning(
                self,
                "오류",
                warning_message,
            )
            return
        url = normalized_url

        def continue_start() -> None:
            self._begin_extraction_run(url, selector)

        # dirty 세션: 종료/불러오기와 동일한 저장·버리기·취소 흐름
        if bool(self._has_dirty_session()):
            self._run_after_dirty_session_action("추출 시작", continue_start)
            return

        # clean 이지만 자막이 남아 있으면 교체 확인 (미저장 데이터 손실 방지와 동일 UX)
        existing_count = self._current_session_entry_count_for_start()
        if existing_count > 0 and not self._confirm_replace_session_for_start(
            existing_count
        ):
            return

        continue_start()

    def _begin_extraction_run(self, url: str, selector: str) -> None:
        """검증된 URL/selector로 추출 worker를 기동한다 (세션 교체 포함)."""
        main_window_mod = _main_window_public()
        if self.is_running:
            return
        if bool(self.__dict__.get("_session_save_in_progress", False)):
            self._set_status("세션 저장 마무리 대기 중...", "warning")
            self._show_toast("세션 저장 완료 후 추출을 시작하세요.", "warning", 3000)
            return
        if bool(self.__dict__.get("_session_load_in_progress", False)):
            self._set_status("세션 불러오기 마무리 대기 중...", "warning")
            self._show_toast("세션 불러오기 완료 후 추출을 시작하세요.", "warning", 3000)
            return

        try:
            retained_driver = self._take_current_driver()
            if retained_driver:
                self._force_quit_driver_with_timeout(
                    retained_driver,
                    timeout=Config.DRIVER_QUIT_TIMEOUT,
                    source="start_replacing_preserved",
                )

            self._add_to_history(url)
            self.current_url = url
            committee_name = self.url_history.get(url, "") or self._autodetect_tag(url)

            self.subtitle_text.clear()
            self.capture_state = create_empty_capture_state()
            self._bind_subtitles_to_capture_state()
            self.live_capture_ledger = create_empty_live_capture_ledger()
            self._cancel_scheduled_subtitle_reset()
            self._cached_total_chars = 0
            self._cached_total_words = 0
            self._last_rendered_count = 0
            self._last_rendered_last_text = ""
            self._last_render_offset = 0
            self._last_render_show_ts = None
            self._last_render_chunk_specs = []
            self._last_printed_ts = None
            self._rendered_entry_text_spans = {}
            self.search_matches = []
            self.search_idx = 0
            search_count = self.__dict__.get("search_count")
            if search_count is not None:
                search_count.setText("")
            self._cancel_runtime_search()
            self._runtime_search_revision += 1
            self._runtime_search_in_progress = False
            self._runtime_search_query = ""
            self._runtime_search_truncated = False
            self._search_focus_entry_index = None
            self._pending_search_focus_query = ""
            self._update_count_label()

            self.last_subtitle = ""
            self.last_update_time = 0
            self._last_raw_text = ""
            self._last_processed_raw = ""
            self._stream_start_time = None
            self._confirmed_compact = ""
            self._trailing_suffix = ""
            self._preview_desync_count = 0
            self._preview_ambiguous_skip_count = 0
            self._last_good_raw_compact = ""
            self._is_stopping = False
            self._clear_preview()
            self.start_time = time.time()
            self._clear_session_dirty()
            self._clear_session_db_identity()
            self._clear_destructive_undo_state()
            self._initial_recovery_snapshot_done = False
            self._set_capture_source_metadata(
                url,
                committee_name,
                headless=self.headless_check.isChecked(),
                realtime=False,
            )
            run_id = self._activate_capture_run()
            self._start_runtime_session_archive(run_id)

            self._clear_message_queue()
            realtime_active = self._open_realtime_save_for_run()
            self._set_capture_source_metadata(
                url,
                committee_name,
                headless=self.headless_check.isChecked(),
                realtime=realtime_active,
            )

            self.is_running = True
            self.stop_event.clear()
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.url_combo.setEnabled(False)
            self.selector_combo.setEnabled(False)
            self.progress.show()
            self._sync_runtime_action_state()

            status_text = "Chrome 브라우저 시작 중..."
            status_level = "running"
            if self.realtime_save_check.isChecked() and not realtime_active:
                status_text = "Chrome 브라우저 시작 중... (실시간 저장 중단)"
                status_level = "warning"
            self._set_status(status_text, status_level)
            self._update_tray_status("🟢 추출 중")

            headless = self.headless_check.isChecked()
            self.worker = threading.Thread(
                target=self._extraction_worker,
                args=(url, selector, headless, run_id),
                daemon=False,
                name="ExtractionWorker",
            )
            self.worker.start()

            self.stats_timer.start(Config.STATS_UPDATE_INTERVAL)
            self.backup_timer.start(Config.AUTO_BACKUP_INTERVAL)

            if self.top_header_container.isVisible():
                self._toggle_top_header()

        except Exception as e:
            logger.exception(f"시작 오류: {e}")
            self._retire_capture_run()
            self._cleanup_runtime_session_archive(remove_files=True)
            self._close_realtime_save_file()
            self._reset_realtime_save_run_state()
            self._reset_ui()
            main_window_mod.QMessageBox.critical(self, "오류", f"시작 중 오류 발생: {e}")
