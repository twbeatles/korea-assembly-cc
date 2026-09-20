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


class MainWindowRuntimeLifecycleBackgroundMixin(RuntimeLifecycleBase):
    """백그라운드 레지스트리 (SRP: 스레드 등록/대기)."""

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
        self._exit_in_progress = True
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
