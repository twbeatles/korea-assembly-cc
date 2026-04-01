# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

from typing import Any

from core import utils
from core.config import Config
from ui.main_window_impl.contracts import RuntimeHost


RuntimeBase = object


class MainWindowRuntimeDriverMixin(RuntimeBase):
    def _is_auto_clean_newlines_enabled(self) -> bool:
        checkbox = self.__dict__.get("auto_clean_newlines_check")
        if checkbox is not None:
            try:
                return bool(checkbox.isChecked())
            except Exception:
                pass
        return bool(
            self.__dict__.get(
                "auto_clean_newlines_enabled",
                Config.AUTO_CLEAN_NEWLINES_DEFAULT,
            )
        )

    def _is_runtime_mutation_blocked(self, action_name: str) -> bool:
        if not self.is_running:
            return False
        self._show_toast(
            f"추출 중에는 {action_name}을 할 수 없습니다. 먼저 중지하세요.",
            "warning",
            3000,
        )
        return True

    def _sync_runtime_action_state(self) -> None:
        controls = self.__dict__.get("_runtime_sensitive_controls", [])
        should_enable = not self.is_running
        for control in controls:
            if control is None:
                continue
            try:
                control.setEnabled(should_enable)
            except Exception:
                continue

    def _set_capture_source_metadata(
        self,
        url: str,
        committee_name: str = "",
        *,
        headless: bool = False,
        realtime: bool = False,
    ) -> None:
        self._capture_source_url = str(url or "").strip()
        self._capture_source_committee = str(committee_name or "").strip()
        self._capture_source_headless = bool(headless)
        self._capture_source_realtime = bool(realtime)

    def _get_capture_source_url(self, fallback_to_current: bool = True) -> str:
        source_url = str(self.__dict__.get("_capture_source_url", "") or "").strip()
        if source_url:
            return source_url
        if not fallback_to_current:
            return ""
        return self._get_current_url().strip()

    def _get_capture_source_committee(self, fallback_to_url: bool = True) -> str:
        committee_name = str(
            self.__dict__.get("_capture_source_committee", "") or ""
        ).strip()
        if committee_name:
            return committee_name
        if not fallback_to_url:
            return ""
        source_url = self._get_capture_source_url(fallback_to_current=True)
        return self._autodetect_tag(source_url) or ""

    def _mark_session_dirty(self) -> None:
        self._session_dirty = True

    def _clear_session_dirty(self) -> None:
        self._session_dirty = False

    def _has_dirty_session(self) -> bool:
        return bool(self.__dict__.get("_session_dirty", False))

    def _handle_escape_shortcut(self) -> None:
        search_frame = self.__dict__.get("search_frame")
        if search_frame is not None and search_frame.isVisible():
            self._hide_search()
            return
        if self.is_running:
            self._stop()

    def _normalize_subtitle_text_for_option(self, text: object) -> str:
        raw = "" if text is None else str(text)
        if self._is_auto_clean_newlines_enabled():
            return utils.flatten_subtitle_text(raw)
        return utils.clean_text_display(raw)

    def _toggle_auto_clean_newlines_option(self) -> None:
        enabled = self._is_auto_clean_newlines_enabled()
        self.auto_clean_newlines_enabled = enabled
        settings = self.__dict__.get("settings")
        if settings is not None:
            settings.setValue("auto_clean_newlines", enabled)

    def _next_capture_run_id(self) -> int:
        next_run_id = int(self.__dict__.get("_capture_run_sequence", 0)) + 1
        self._capture_run_sequence = next_run_id
        return next_run_id

    def _activate_capture_run(self) -> int:
        run_id = self._next_capture_run_id()
        self._active_capture_run_id = run_id
        return run_id

    def _ensure_active_capture_run(self) -> int:
        active_run_id = self.__dict__.get("_active_capture_run_id")
        if active_run_id is None:
            active_run_id = self._activate_capture_run()
        return int(active_run_id)

    def _retire_capture_run(self, run_id: int | None = None) -> None:
        target_run_id = (
            self.__dict__.get("_active_capture_run_id")
            if run_id is None
            else int(run_id)
        )
        if target_run_id is None:
            return
        if self.__dict__.get("_active_capture_run_id") == target_run_id:
            self._active_capture_run_id = None
        lock = self.__dict__.get("_worker_message_lock")
        if lock is None:
            return
        with lock:
            pending = getattr(self, "_coalesced_worker_messages", {})
            stale_keys = [
                key
                for key in pending.keys()
                if isinstance(key, tuple) and key[0] == target_run_id
            ]
            for key in stale_keys:
                pending.pop(key, None)

    def _is_active_capture_run(self, run_id: int | None) -> bool:
        return run_id is not None and self.__dict__.get("_active_capture_run_id") == int(run_id)

    def _set_current_driver(self, driver: Any | None) -> Any | None:
        lock = self.__dict__.get("_driver_lock")
        if lock is None:
            self.driver = driver
            return self.__dict__.get("driver")
        with lock:
            self.driver = driver
            return self.driver

    def _get_current_driver(self) -> Any | None:
        lock = self.__dict__.get("_driver_lock")
        if lock is None:
            return self.__dict__.get("driver")
        with lock:
            return self.driver

    def _take_current_driver(self) -> Any | None:
        lock = self.__dict__.get("_driver_lock")
        if lock is None:
            driver = self.__dict__.get("driver")
            self.driver = None
            return driver
        with lock:
            driver = self.driver
            self.driver = None
            return driver

    def _clear_current_driver_if(self, driver: Any | None) -> bool:
        if driver is None:
            return False
        lock = self.__dict__.get("_driver_lock")
        if lock is None:
            if self.__dict__.get("driver") is driver:
                self.driver = None
                return True
            return False
        with lock:
            if self.driver is driver:
                self.driver = None
                return True
        return False
