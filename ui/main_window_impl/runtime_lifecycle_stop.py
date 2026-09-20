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


class MainWindowRuntimeLifecycleStopMixin(RuntimeLifecycleBase):
    """추출 중지 (SRP: 중지 확정/정리)."""

    def _stop(self, for_app_exit: bool = False):
        if not self.is_running:
            return

        try:
            self.is_running = False
            self.stop_event.set()
            self._set_status("중지 중...", "warning")
            self._is_stopping = True
            preserve_driver = (not for_app_exit) and bool(
                self.__dict__.get("keep_browser_on_stop", False)
            )
            self._preserve_driver_on_worker_stop = preserve_driver
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

            force_driver_quit = not preserve_driver

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
            self._preserve_driver_on_worker_stop = False
