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


class MainWindowRuntimeLifecycleDetachedMixin(RuntimeLifecycleBase):
    """분리 드라이버 (SRP: quit 타임아웃/분리 정리)."""

    def _force_quit_driver_with_timeout(
        self, driver, timeout: float = 2.0, source: str = "shutdown"
    ) -> bool:
        if not driver:
            return True

        done = threading.Event()
        error_holder: dict[str, Exception | None] = {"error": None}
        driver_id = hex(id(driver))

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
                "WebDriver 종료 타임아웃 (source=%s, timeout=%.1fs, driver=%s)",
                source,
                timeout,
                driver_id,
            )
            # 타임아웃 시 분리 목록에 남겨 이후 cleanup/진단이 추적 가능하게 한다.
            try:
                register = getattr(self, "_register_detached_driver", None)
                if callable(register):
                    register(driver)
            except Exception:
                logger.debug("timeout driver 등록 실패", exc_info=True)
            failures = list(self.__dict__.get("_driver_quit_failures", []) or [])
            failures.append(
                {
                    "source": str(source),
                    "timeout": float(timeout),
                    "driver_id": driver_id,
                    "reason": "timeout",
                    "at": datetime.now().isoformat(),
                }
            )
            self._driver_quit_failures = failures[-20:]
            return False

        if error_holder["error"] is not None:
            logger.debug(
                "WebDriver 종료 오류 (source=%s, driver=%s): %s",
                source,
                driver_id,
                error_holder["error"],
            )
            failures = list(self.__dict__.get("_driver_quit_failures", []) or [])
            failures.append(
                {
                    "source": str(source),
                    "timeout": float(timeout),
                    "driver_id": driver_id,
                    "reason": "error",
                    "error": str(error_holder["error"])[:300],
                    "at": datetime.now().isoformat(),
                }
            )
            self._driver_quit_failures = failures[-20:]
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
