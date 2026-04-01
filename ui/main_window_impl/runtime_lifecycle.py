# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import threading
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QSystemTrayIcon

from core.config import Config
from core.live_capture import create_empty_live_capture_ledger
from core.logging_utils import logger
from core.subtitle_pipeline import create_empty_capture_state, finalize_session
from ui.main_window_impl.contracts import RuntimeHost


def _main_window_public():
    return import_module("ui.main_window")


RuntimeLifecycleBase = object


class MainWindowRuntimeLifecycleMixin(RuntimeLifecycleBase):
    def _start(self):
        main_window_mod = _main_window_public()
        if self.is_running:
            return

        url = self._get_current_url().strip()
        selector = self.selector_combo.currentText().strip()

        if not url or not selector:
            main_window_mod.QMessageBox.warning(self, "오류", "URL과 선택자를 입력하세요.")
            return

        if not url.startswith(("http://", "https://")):
            main_window_mod.QMessageBox.warning(self, "오류", "올바른 URL을 입력하세요.")
            return

        try:
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
            self._set_capture_source_metadata(
                url,
                committee_name,
                headless=self.headless_check.isChecked(),
                realtime=self.realtime_save_check.isChecked(),
            )
            run_id = self._activate_capture_run()

            self._clear_message_queue()

            self.realtime_file = None
            if self.realtime_save_check.isChecked():
                try:
                    Path(Config.REALTIME_DIR).mkdir(exist_ok=True)
                    filename = (
                        f"{Config.REALTIME_DIR}/자막_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    )
                    self.realtime_file = open(filename, "w", encoding="utf-8-sig")
                    self._set_status(f"실시간 저장: {filename}", "success")
                except Exception as e:
                    logger.error(f"실시간 저장 파일 생성 오류: {e}")

            self.is_running = True
            self.stop_event.clear()
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.url_combo.setEnabled(False)
            self.selector_combo.setEnabled(False)
            self.progress.show()
            self._sync_runtime_action_state()

            self._set_status("Chrome 브라우저 시작 중...", "running")
            self._update_tray_status("🟢 추출 중")

            headless = self.headless_check.isChecked()
            self.worker = threading.Thread(
                target=self._extraction_worker,
                args=(url, selector, headless, run_id),
                daemon=True,
            )
            self.worker.start()

            self.stats_timer.start(Config.STATS_UPDATE_INTERVAL)
            self.backup_timer.start(Config.AUTO_BACKUP_INTERVAL)

            if self.top_header_container.isVisible():
                self._toggle_top_header()

        except Exception as e:
            logger.exception(f"시작 오류: {e}")
            self._retire_capture_run()
            if self.realtime_file:
                try:
                    self.realtime_file.close()
                except Exception as close_err:
                    logger.debug(f"실시간 저장 파일 닫기 오류: {close_err}")
                self.realtime_file = None
            self._reset_ui()
            main_window_mod.QMessageBox.critical(self, "오류", f"시작 중 오류 발생: {e}")

    def _stop(self, for_app_exit: bool = False):
        if not self.is_running:
            return

        try:
            self.is_running = False
            self.stop_event.set()
            self._set_status("중지 중...", "warning")
            self._is_stopping = True
            self._cancel_scheduled_subtitle_reset()

            self._drain_pending_previews(requeue_others=True)
            self._materialize_pending_preview()
            finalize_session(
                self.capture_state,
                datetime.now(),
                self._current_capture_settings(),
            )
            self._sync_capture_state_entries(force_refresh=False)
            self._finalize_pending_subtitle()

            force_driver_quit = for_app_exit or (not Config.KEEP_BROWSER_ON_STOP)

            if force_driver_quit:
                driver = self._take_current_driver()
            else:
                driver = None
            if driver:
                self._force_quit_driver_with_timeout(
                    driver, timeout=2.0, source="stop_initial"
                )

            worker_stopped = self._wait_worker_shutdown(
                timeout=Config.THREAD_STOP_TIMEOUT
            )

            if not worker_stopped and not force_driver_quit:
                logger.warning("워커 스레드 종료 지연 감지 - 드라이버 강제 종료 후 재대기")
                driver = self._take_current_driver()
            else:
                driver = None
            if driver:
                self._force_quit_driver_with_timeout(
                    driver, timeout=2.0, source="stop_escalation"
                )
                worker_stopped = self._wait_worker_shutdown(timeout=1.0)

            retire_after_finalize = False
            if not worker_stopped:
                logger.warning("워커 스레드가 시간 내에 종료되지 않음(종료 계속 진행)")
                retire_after_finalize = True

            self._drain_pending_previews(requeue_others=True)
            self._materialize_pending_preview()
            finalize_session(
                self.capture_state,
                datetime.now(),
                self._current_capture_settings(),
            )
            self._sync_capture_state_entries(force_refresh=False)
            self._finalize_pending_subtitle()
            self._clear_preview()

            if self.realtime_file:
                try:
                    self.realtime_file.close()
                except Exception as e:
                    logger.debug(f"파일 닫기 오류: {e}")
                self.realtime_file = None

            self._cleanup_detached_drivers_with_timeout(timeout=2.0)

            if retire_after_finalize:
                self._retire_capture_run()
            self._clear_message_queue()
            self.worker = None
            self._retire_capture_run()
            self._reset_ui()
            self._set_status("중지됨", "warning")
            self._update_tray_status("⚪ 대기 중")
        except Exception as e:
            logger.error(f"중지 중 오류 발생: {e}")
            self._reset_ui()
        finally:
            self._is_stopping = False

    def _force_quit_driver_with_timeout(
        self, driver, timeout: float = 2.0, source: str = "shutdown"
    ) -> bool:
        if not driver:
            return True

        done = threading.Event()
        error_holder: dict[str, Exception | None] = {"error": None}

        def _quit_driver():
            try:
                driver.quit()
            except Exception as e:
                error_holder["error"] = e
            finally:
                done.set()

        threading.Thread(
            target=_quit_driver,
            daemon=True,
            name=f"DriverQuitThread-{source}",
        ).start()

        if not done.wait(timeout=timeout):
            logger.warning(
                "WebDriver 종료 타임아웃 (source=%s, timeout=%.1fs)",
                source,
                timeout,
            )
            return False

        if error_holder["error"] is not None:
            logger.debug(
                "WebDriver 종료 오류 (source=%s): %s",
                source,
                error_holder["error"],
            )
            return False

        return True

    def _wait_worker_shutdown(self, timeout: float) -> bool:
        if not self.worker or not self.worker.is_alive():
            return True
        self.worker.join(timeout=timeout)
        return not self.worker.is_alive()

    def _cleanup_detached_drivers_with_timeout(self, timeout: float = 2.0) -> None:
        with self._detached_drivers_lock:
            detached_drivers = list(self._detached_drivers)
            self._detached_drivers.clear()

        for idx, drv in enumerate(detached_drivers, start=1):
            self._force_quit_driver_with_timeout(
                drv,
                timeout=timeout,
                source=f"detached_{idx}",
            )

    def _ensure_background_registry(self) -> None:
        if not hasattr(self, "_active_background_threads") or self._active_background_threads is None:
            self._active_background_threads = set()
        if (
            not hasattr(self, "_active_background_threads_lock")
            or self._active_background_threads_lock is None
        ):
            self._active_background_threads_lock = threading.Lock()
        if not hasattr(self, "_background_shutdown_initiated"):
            self._background_shutdown_initiated = False

    def _begin_background_shutdown(self) -> None:
        self._ensure_background_registry()
        with self._active_background_threads_lock:
            self._background_shutdown_initiated = True

    def _is_background_shutdown_active(self) -> bool:
        self._ensure_background_registry()
        with self._active_background_threads_lock:
            return bool(self._background_shutdown_initiated)

    def _unregister_background_thread(self, thread: threading.Thread | None) -> None:
        self._ensure_background_registry()
        if thread is None:
            return
        with self._active_background_threads_lock:
            self._active_background_threads.discard(thread)

    def _start_background_thread(self, target, name: str) -> bool:
        self._ensure_background_registry()
        with self._active_background_threads_lock:
            if self._background_shutdown_initiated:
                logger.info("종료 단계에서 백그라운드 작업 시작 거부: %s", name)
                return False

            def runner():
                try:
                    target()
                finally:
                    self._unregister_background_thread(threading.current_thread())

            worker_thread = threading.Thread(target=runner, daemon=False, name=name)
            self._active_background_threads.add(worker_thread)

        try:
            worker_thread.start()
        except Exception as e:
            self._unregister_background_thread(worker_thread)
            logger.error("백그라운드 작업 시작 실패 (%s): %s", name, e)
            return False
        return True

    def _wait_active_background_threads(self, timeout: float) -> None:
        self._ensure_background_registry()
        deadline = time.time() + max(0.0, float(timeout))
        current_thread = threading.current_thread()

        while True:
            with self._active_background_threads_lock:
                live_threads = [
                    t
                    for t in self._active_background_threads
                    if t is not None and t is not current_thread and t.is_alive()
                ]
                if not live_threads:
                    self._active_background_threads = {
                        t for t in self._active_background_threads if t.is_alive()
                    }
                    return

            remaining = deadline - time.time()
            if remaining <= 0:
                logger.warning("백그라운드 작업 종료 대기 타임아웃: %s개", len(live_threads))
                return

            for thread in live_threads:
                thread.join(timeout=min(0.2, remaining))

    def _wait_active_save_threads(self, timeout: float) -> None:
        self._wait_active_background_threads(timeout=timeout)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        main_window_mod = _main_window_public()
        if a0 is None:
            return
        event = a0
        if self.minimize_to_tray and self.tray_icon.isVisible():
            self.hide()
            self.tray_icon.showMessage(
                Config.APP_NAME,
                "프로그램이 트레이로 최소화되었습니다.\n트레이 아이콘을 더블클릭하여 다시 열 수 있습니다.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
            event.ignore()
            return

        if self.is_running:
            reply = main_window_mod.QMessageBox.question(
                self,
                "종료",
                "추출 중입니다. 종료하시겠습니까?",
                main_window_mod.QMessageBox.StandardButton.Yes
                | main_window_mod.QMessageBox.StandardButton.No,
            )
            if reply == main_window_mod.QMessageBox.StandardButton.No:
                event.ignore()
                return
            self._stop(for_app_exit=True)

        subtitles_snapshot = self._build_prepared_entries_snapshot()
        subtitle_count = len(subtitles_snapshot)

        if self._has_dirty_session():
            if subtitle_count > 0:
                reply = main_window_mod.QMessageBox.question(
                    self,
                    "종료 확인",
                    f"저장하지 않은 세션 변경 {subtitle_count}개가 있습니다.\n\n"
                    "세션(JSON + DB)으로 저장하시겠습니까?",
                    main_window_mod.QMessageBox.StandardButton.Save
                    | main_window_mod.QMessageBox.StandardButton.Discard
                    | main_window_mod.QMessageBox.StandardButton.Cancel,
                )
                if reply == main_window_mod.QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                if reply == main_window_mod.QMessageBox.StandardButton.Save:
                    filename = (
                        f"{Config.SESSION_DIR}/세션_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    )
                    path, _ = main_window_mod.QFileDialog.getSaveFileName(
                        self, "세션 저장", filename, "JSON (*.json)"
                    )
                    if not path:
                        event.ignore()
                        return
                    try:
                        Path(path).parent.mkdir(parents=True, exist_ok=True)
                        info = self._write_session_snapshot(
                            path,
                            subtitles_snapshot,
                            include_db=True,
                        )
                        self._clear_session_dirty()
                        db_error = str(info.get("db_error", "") or "").strip()
                        if db_error:
                            main_window_mod.QMessageBox.warning(
                                self,
                                "DB 저장 경고",
                                "세션 JSON 저장은 완료되었지만 DB 저장은 실패했습니다.\n"
                                f"위치: {path}\n오류: {db_error}",
                            )
                    except Exception as e:
                        main_window_mod.QMessageBox.critical(self, "오류", f"세션 저장 실패: {e}")
                        event.ignore()
                        return
            else:
                reply = main_window_mod.QMessageBox.question(
                    self,
                    "종료 확인",
                    "저장되지 않은 변경이 있습니다.\n종료하시겠습니까?",
                    main_window_mod.QMessageBox.StandardButton.Discard
                    | main_window_mod.QMessageBox.StandardButton.Cancel,
                )
                if reply == main_window_mod.QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return

        self._begin_background_shutdown()
        self._wait_active_background_threads(timeout=Config.SAVE_THREAD_SHUTDOWN_TIMEOUT)
        self._clear_recovery_state()

        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())

        self.queue_timer.stop()
        self.stats_timer.stop()
        self.backup_timer.stop()

        if self.realtime_file:
            try:
                self.realtime_file.close()
            except Exception as e:
                logger.debug(f"파일 닫기 오류: {e}")
            self.realtime_file = None

        driver = self._take_current_driver()
        if driver:
            self._force_quit_driver_with_timeout(
                driver, timeout=2.0, source="close_event_idle"
            )
        self._cleanup_detached_drivers_with_timeout(timeout=2.0)

        db = self.db
        if db is not None:
            try:
                db.close_all()
            except Exception as e:
                logger.debug(f"DB 연결 종료 오류: {e}")

        logger.info("프로그램 종료")
        event.accept()
