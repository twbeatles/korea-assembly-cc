# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

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
            self._cleanup_runtime_session_archive(remove_files=True)
            self._close_realtime_save_file()
            self._reset_realtime_save_run_state()
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
                    driver, timeout=Config.DRIVER_QUIT_TIMEOUT, source="stop_initial"
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
                    driver, timeout=Config.DRIVER_QUIT_TIMEOUT, source="stop_escalation"
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
            self._close_realtime_save_file()
            self._reset_realtime_save_run_state()
            self._initial_recovery_snapshot_done = False

            self._cleanup_detached_drivers_with_timeout(
                timeout=Config.DETACHED_DRIVER_QUIT_TIMEOUT
            )

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

    def _ensure_detached_driver_cleanup_state(self) -> None:
        state = getattr(self, "__dict__", {})
        if state.get("_detached_driver_cleanup_lock") is None:
            self._detached_driver_cleanup_lock = threading.Lock()
        if "_detached_driver_cleanup_in_progress" not in state:
            self._detached_driver_cleanup_in_progress = False

    def _register_detached_driver(self, driver) -> None:
        if not driver:
            return
        with self._detached_drivers_lock:
            if any(existing is driver for existing in self._detached_drivers):
                return
            self._detached_drivers.append(driver)

    def _schedule_detached_driver_cleanup(self, timeout: float | None = None) -> bool:
        self._ensure_detached_driver_cleanup_state()
        with self._detached_drivers_lock:
            has_detached = bool(self._detached_drivers)
        if not has_detached:
            return False

        with self._detached_driver_cleanup_lock:
            if self._detached_driver_cleanup_in_progress:
                return False
            self._detached_driver_cleanup_in_progress = True

        cleanup_timeout = max(
            0.0,
            float(
                timeout
                if timeout is not None
                else Config.DETACHED_DRIVER_QUIT_TIMEOUT
            ),
        )

        def cleanup_worker() -> None:
            try:
                self._cleanup_detached_drivers_with_timeout(timeout=cleanup_timeout)
            finally:
                with self._detached_driver_cleanup_lock:
                    self._detached_driver_cleanup_in_progress = False

        started = self._start_background_thread(
            cleanup_worker,
            "DetachedDriverCleanupWorker",
        )
        if started:
            return True

        with self._detached_driver_cleanup_lock:
            self._detached_driver_cleanup_in_progress = False
        return False

    def _wait_worker_shutdown(self, timeout: float) -> bool:
        if not self.worker or not self.worker.is_alive():
            return True
        self.worker.join(timeout=timeout)
        return not self.worker.is_alive()

    def _cleanup_detached_drivers_with_timeout(self, timeout: float = 2.0) -> None:
        with self._detached_drivers_lock:
            detached_drivers = list(self._detached_drivers)
            self._detached_drivers.clear()

        failed_drivers: list[object] = []
        for idx, drv in enumerate(detached_drivers, start=1):
            closed = self._force_quit_driver_with_timeout(
                drv,
                timeout=timeout,
                source=f"detached_{idx}",
            )
            if not closed:
                failed_drivers.append(drv)

        if failed_drivers:
            with self._detached_drivers_lock:
                for drv in failed_drivers:
                    if any(existing is drv for existing in self._detached_drivers):
                        continue
                    self._detached_drivers.append(drv)

    def _ensure_background_registry(self) -> None:
        state = getattr(self, "__dict__", {})
        if state.get("_active_background_threads") is None:
            self._active_background_threads = set()
        if state.get("_active_background_threads_lock") is None:
            self._active_background_threads_lock = threading.Lock()
        if "_background_shutdown_initiated" not in state:
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

    def _get_live_background_threads(self) -> list[threading.Thread]:
        self._ensure_background_registry()
        current_thread = threading.current_thread()
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
            return live_threads

    def _get_exit_wait_threads(self) -> list[threading.Thread]:
        threads = list(self._get_live_background_threads())
        current_thread = threading.current_thread()
        db_worker_thread = self.__dict__.get("_db_worker_thread")
        if (
            db_worker_thread is not None
            and db_worker_thread is not current_thread
            and db_worker_thread.is_alive()
            and bool(self.__dict__.get("_db_worker_shutdown", False))
        ):
            threads.append(db_worker_thread)
        return threads

    def _build_shutdown_diagnostic_payload(self) -> dict[str, object]:
        queue_size = 0
        try:
            queue_size = int(self.message_queue.qsize())
        except Exception:
            queue_size = 0

        with self._detached_drivers_lock:
            detached_count = len(self._detached_drivers)

        return {
            "generated_at": datetime.now().isoformat(),
            "background_threads": [
                {
                    "name": thread.name or "",
                    "alive": bool(thread.is_alive()),
                    "daemon": bool(thread.daemon),
                }
                for thread in self._get_live_background_threads()
            ],
            "db_worker": {
                "alive": bool(
                    self._db_worker_thread is not None
                    and self._db_worker_thread.is_alive()
                ),
                "shutdown_requested": bool(self.__dict__.get("_db_worker_shutdown", False)),
                "current_task": str(self.__dict__.get("_db_worker_current_task", "") or ""),
                "queue_size": int(self._db_worker_queue.qsize()),
            },
            "runtime_archive": {
                "root": str(self._runtime_session_root) if self._runtime_session_root else "",
                "manifest": str(self._runtime_manifest_path) if self._runtime_manifest_path else "",
                "segment_count": len(self._runtime_segment_manifest),
                "archived_count": int(self._runtime_archived_count),
            },
            "message_queue": {
                "queue_size": queue_size,
                "coalesced_control": len(self._coalesced_control_messages),
                "coalesced_worker": len(self._coalesced_worker_messages),
                "overflow_passthrough": len(self._overflow_passthrough_messages),
            },
            "driver": {
                "attached": bool(self.driver is not None),
                "detached_count": detached_count,
                "connection_status": str(self.__dict__.get("connection_status", "") or ""),
            },
            "session_state": {
                "dirty": bool(self.__dict__.get("_session_dirty", False)),
                "session_save_in_progress": bool(
                    self.__dict__.get("_session_save_in_progress", False)
                ),
                "session_load_in_progress": bool(
                    self.__dict__.get("_session_load_in_progress", False)
                ),
                "reflow_in_progress": bool(self.__dict__.get("_reflow_in_progress", False)),
                "is_running": bool(self.__dict__.get("is_running", False)),
            },
        }

    def _write_shutdown_diagnostic(self) -> str:
        logs_dir = Path(Config.LOG_DIR)
        logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = logs_dir / f"shutdown_diagnostic_{timestamp}.json"
        path.write_text(
            json.dumps(self._build_shutdown_diagnostic_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(path)

    def _force_exit_process(self, code: int = 1) -> None:
        os._exit(code)

    def _show_exit_wait_escalation(self) -> bool:
        main_window_mod = _main_window_public()
        box = main_window_mod.QMessageBox(self)
        box.setWindowTitle("종료 대기")
        box.setIcon(main_window_mod.QMessageBox.Icon.Warning)
        box.setText("종료 대기가 오래 걸리고 있습니다.")
        box.setInformativeText(
            "계속 기다리거나, 진단 파일을 저장하거나, 강제 종료할 수 있습니다."
        )
        box.addButton("계속 기다리기", main_window_mod.QMessageBox.ButtonRole.AcceptRole)
        diagnostic_btn = box.addButton(
            "진단 저장",
            main_window_mod.QMessageBox.ButtonRole.ActionRole,
        )
        force_btn = box.addButton(
            "강제 종료",
            main_window_mod.QMessageBox.ButtonRole.DestructiveRole,
        )
        box.exec()
        clicked = box.clickedButton()

        if clicked is diagnostic_btn:
            try:
                diagnostic_path = self._write_shutdown_diagnostic()
                self._show_toast(
                    f"종료 진단 저장: {Path(diagnostic_path).name}",
                    "info",
                    3000,
                )
            except Exception as e:
                logger.error("종료 진단 저장 실패: %s", e)
            return False

        if clicked is force_btn:
            try:
                self._write_shutdown_diagnostic()
            except Exception:
                logger.debug("강제 종료 전 진단 저장 실패", exc_info=True)
            self._force_exit_process(1)
            return True

        return False

    def _wait_for_background_threads_during_exit(self) -> None:
        warning_after = max(0.0, float(Config.SAVE_THREAD_SHUTDOWN_TIMEOUT))
        wait_started_at = time.monotonic()
        warning_emitted = False
        app = QApplication.instance()

        while True:
            live_threads = self._get_exit_wait_threads()
            if not live_threads:
                return

            if (
                not warning_emitted
                and warning_after > 0
                and time.monotonic() - wait_started_at >= warning_after
            ):
                warning_emitted = True
                live_thread_names = ", ".join(
                    sorted(
                        thread.name or f"thread-{idx}"
                        for idx, thread in enumerate(live_threads, start=1)
                    )
                )
                logger.warning(
                    "종료 대기 중 백그라운드 작업이 아직 남아 있습니다: %s개 (%s)",
                    len(live_threads),
                    live_thread_names or "unnamed",
                )
                try:
                    self._show_toast(
                        "백그라운드 작업이 끝날 때까지 종료를 기다립니다.",
                        "warning",
                        2500,
                    )
                except Exception:
                    logger.debug("종료 대기 toast 표시 실패", exc_info=True)

            escalation_after = max(0.0, float(Config.EXIT_ESCALATION_AFTER_SECONDS))
            escalation_repeat = max(0.0, float(Config.EXIT_ESCALATION_REPEAT_SECONDS))
            now = time.monotonic()
            should_escalate = (
                escalation_after > 0
                and now - wait_started_at >= escalation_after
                and (
                    not bool(self.__dict__.get("_exit_escalation_active", False))
                    or now - float(self.__dict__.get("_last_exit_escalation_at", 0.0))
                    >= escalation_repeat
                )
            )
            if should_escalate:
                self._exit_escalation_active = True
                self._last_exit_escalation_at = now
                if self._show_exit_wait_escalation():
                    return
                self._exit_escalation_active = False

            for thread in live_threads:
                thread.join(timeout=0.1)

            if app is not None:
                try:
                    app.processEvents()
                except Exception:
                    logger.debug("종료 대기 중 processEvents 실패", exc_info=True)
            try:
                self._process_message_queue()
            except Exception:
                logger.debug("종료 대기 중 큐 처리 실패", exc_info=True)

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

        if bool(self.__dict__.get("_session_save_in_progress", False)):
            try:
                self._set_status("세션 저장 마무리 대기 중...", "warning")
            except Exception:
                logger.debug("세션 저장 종료 대기 상태 텍스트 갱신 실패", exc_info=True)
            try:
                self._update_tray_status("🟡 세션 저장 마무리 중")
            except Exception:
                logger.debug("세션 저장 종료 대기 트레이 상태 갱신 실패", exc_info=True)
            self._wait_for_background_threads_during_exit()
            if bool(self.__dict__.get("_exit_escalation_active", False)) and self._get_exit_wait_threads():
                event.ignore()
                return
            try:
                self._process_message_queue()
            except Exception:
                logger.debug("세션 저장 종료 대기 후 큐 처리 실패", exc_info=True)

        proceed_now = {"ready": False}
        close_after_save = {"deferred": False}

        def continue_close() -> None:
            if close_after_save["deferred"]:
                QTimer.singleShot(0, self.close)
                return
            proceed_now["ready"] = True

        started_or_continued = self._run_after_dirty_session_action(
            "종료",
            continue_close,
        )
        close_after_save["deferred"] = started_or_continued and not proceed_now["ready"]
        if not started_or_continued:
            event.ignore()
            return
        if close_after_save["deferred"]:
            event.ignore()
            return

        self._begin_background_shutdown()
        self._begin_db_worker_shutdown()
        try:
            self._set_status("종료 대기 중...", "warning")
        except Exception:
            logger.debug("종료 대기 상태 텍스트 갱신 실패", exc_info=True)
        try:
            self._update_tray_status("🟡 종료 대기 중")
        except Exception:
            logger.debug("종료 대기 트레이 상태 갱신 실패", exc_info=True)
        self._wait_for_background_threads_during_exit()
        if bool(self.__dict__.get("_exit_escalation_active", False)) and self._get_exit_wait_threads():
            event.ignore()
            return
        self._exit_escalation_active = False
        self._cleanup_runtime_session_archive(remove_files=True)
        self._clear_recovery_state()

        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())

        self.queue_timer.stop()
        self.stats_timer.stop()
        self.backup_timer.stop()
        cleanup_timer = self.__dict__.get("detached_driver_cleanup_timer")
        if cleanup_timer is not None:
            try:
                cleanup_timer.stop()
            except Exception:
                logger.debug("분리된 드라이버 정리 타이머 중지 실패", exc_info=True)
        self._close_realtime_save_file()
        self._reset_realtime_save_run_state()
        self._initial_recovery_snapshot_done = False

        driver = self._take_current_driver()
        if driver:
            self._force_quit_driver_with_timeout(
                driver, timeout=Config.DRIVER_QUIT_TIMEOUT, source="close_event_idle"
            )
        self._cleanup_detached_drivers_with_timeout(timeout=Config.DETACHED_DRIVER_QUIT_TIMEOUT)

        db = self.db
        if db is not None:
            try:
                self._shutdown_db_worker(timeout=0.0)
                db.close_all()
            except Exception as e:
                logger.debug(f"DB 연결 종료 오류: {e}")

        logger.info("프로그램 종료")
        event.accept()
