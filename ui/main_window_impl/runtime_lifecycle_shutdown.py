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


def _facade_qapplication():
    """퍼사드 late-binding: 테스트의 QApplication monkeypatch를 존중한다."""
    from importlib import import_module

    return import_module("ui.main_window_impl.runtime_lifecycle").QApplication


class MainWindowRuntimeLifecycleShutdownMixin(RuntimeLifecycleBase):
    """종료 진단·대기·closeEvent (SRP: 종료 흐름)."""

    def _build_shutdown_diagnostic_payload(self) -> dict[str, object]:
        queue_size = 0
        control_queue_size = 0
        try:
            queue_size = int(self.message_queue.qsize())
        except Exception:
            queue_size = 0
        try:
            control_queue = self.__dict__.get("app_control_queue")
            if control_queue is not None:
                control_queue_size = int(control_queue.qsize())
        except Exception:
            control_queue_size = 0

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
                "control_queue_size": control_queue_size,
                "coalesced_control": len(self._coalesced_control_messages),
                "coalesced_worker": len(self._coalesced_worker_messages),
                "overflow_passthrough": len(self._overflow_passthrough_messages),
            },
            "driver": {
                "attached": bool(self.driver is not None),
                "detached_count": detached_count,
                "connection_status": str(self.__dict__.get("connection_status", "") or ""),
                "quit_failures": list(self.__dict__.get("_driver_quit_failures", []) or []),
            },
            "worker": (
                lambda _worker: {
                    "name": str(getattr(_worker, "name", "") or "") if _worker else "",
                    "alive": bool(
                        _worker is not None and bool(getattr(_worker, "is_alive", lambda: False)())
                    ),
                    "ident": int(getattr(_worker, "ident", 0) or 0) if _worker else 0,
                }
            )(self.__dict__.get("worker")),
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
                "exit_in_progress": bool(self.__dict__.get("_exit_in_progress", False)),
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
            db = self.__dict__.get("db")
            if db is not None:
                try:
                    db.checkpoint("PASSIVE")
                except Exception:
                    logger.debug("강제 종료 전 DB checkpoint 실패", exc_info=True)
            self._force_exit_process(1)
            return True

        return False

    def _wait_for_background_threads_during_exit(self) -> None:
        warning_after = max(0.0, float(Config.SAVE_THREAD_SHUTDOWN_TIMEOUT))
        wait_started_at = time.monotonic()
        warning_emitted = False
        app = _facade_qapplication().instance()

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
        if bool(self.__dict__.get("_force_quit_for_update", False)):
            self.minimize_to_tray = False
        if self.minimize_to_tray and self.tray_icon.isVisible():
            if self.is_running:
                # 추출 중에는 사용자 의도를 한 번 더 확인 (백그라운드 캡처 지속 vs 실제 종료)
                reply = main_window_mod.QMessageBox.question(
                    self,
                    "트레이 최소화 또는 종료",
                    "추출 중입니다.\n"
                    "[Yes] 트레이로 최소화하고 백그라운드에서 계속 캡처\n"
                    "[No] 추출을 중지하고 프로그램을 종료\n"
                    "[Cancel] 작업 유지",
                    main_window_mod.QMessageBox.StandardButton.Yes
                    | main_window_mod.QMessageBox.StandardButton.No
                    | main_window_mod.QMessageBox.StandardButton.Cancel,
                )
                if reply == main_window_mod.QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                if reply == main_window_mod.QMessageBox.StandardButton.Yes:
                    self.hide()
                    self.tray_icon.showMessage(
                        Config.APP_NAME,
                        "추출 중 상태로 트레이에 최소화되었습니다.\n"
                        "트레이 아이콘을 더블클릭하면 다시 열 수 있습니다.",
                        QSystemTrayIcon.MessageIcon.Information,
                        2500,
                    )
                    event.ignore()
                    return
                # No → 추출 중지 후 종료 흐름 진행
                self._stop(for_app_exit=True)
            else:
                self.hide()
                self.tray_icon.showMessage(
                    Config.APP_NAME,
                    "프로그램이 트레이로 최소화되었습니다.\n트레이 아이콘을 더블클릭하여 다시 열 수 있습니다.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000,
                )
                event.ignore()
                return
        elif self.is_running:
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

        self._save_setting_value(
            "geometry",
            self.saveGeometry(),
            context="창 위치 설정 저장",
        )
        self._save_setting_value(
            "windowState",
            self.saveState(),
            context="창 상태 설정 저장",
        )

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
                self._shutdown_db_worker(
                    timeout=max(0.0, float(Config.SAVE_THREAD_SHUTDOWN_TIMEOUT))
                )
                try:
                    db.checkpoint("TRUNCATE")
                except Exception:
                    logger.debug("종료 단계 DB checkpoint 실패", exc_info=True)
                db.close_all()
            except Exception as e:
                logger.debug(f"DB 연결 종료 오류: {e}")

        logger.info("프로그램 종료")
        event.accept()
