# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from core import utils
from core.config import Config
from core.logging_utils import logger
from core.models import SubtitleEntry
from ui.main_window_impl.contracts import RuntimeHost


RuntimeBase = object


class MainWindowRuntimeDriverMixin(RuntimeBase):
    def _update_realtime_status_indicator(self) -> None:
        label = self.__dict__.get("realtime_status_label")
        if label is None:
            return

        status = str(self.__dict__.get("_realtime_save_status", "inactive") or "inactive")
        path = str(self.__dict__.get("_realtime_save_path", "") or "")
        if status == "active":
            label.setText("💾 실시간 저장 중")
            label.setToolTip(path or "실시간 저장이 정상 동작 중입니다.")
            label.setStyleSheet("color: #3fb950; background: transparent; border: none;")
            label.show()
            return
        if status == "failed":
            label.setText("⚠️ 실시간 저장 실패")
            label.setToolTip(path or "실시간 저장이 실패하여 현재 실행에서 중단되었습니다.")
            label.setStyleSheet("color: #d29922; background: transparent; border: none;")
            label.show()
            return
        if label.isVisible():
            label.hide()
        label.setText("")
        label.setToolTip("")

    def _set_realtime_save_status(self, status: str, *, path: str = "") -> None:
        normalized = str(status or "inactive").strip().lower() or "inactive"
        if normalized not in {"inactive", "active", "failed"}:
            normalized = "inactive"
        self._realtime_save_status = normalized
        self._realtime_save_path = str(path or "")
        self._realtime_save_active = normalized == "active"
        self._update_realtime_status_indicator()

    def _reset_realtime_save_run_state(self) -> None:
        self._realtime_error_count = 0
        self._set_realtime_save_status("inactive")

    def _close_realtime_save_file(self) -> None:
        realtime_file = self.__dict__.get("realtime_file")
        if realtime_file is None:
            return
        try:
            realtime_file.close()
        except Exception:
            pass
        self.realtime_file = None

    def _disable_realtime_save_for_run(
        self,
        *,
        message: str,
        toast_message: str = "",
        error: object | None = None,
    ) -> None:
        if error is not None:
            logger.error("실시간 저장 중단: %s", error)
        self._close_realtime_save_file()
        self._set_capture_source_metadata(
            self.__dict__.get("_capture_source_url", ""),
            self.__dict__.get("_capture_source_committee", ""),
            headless=bool(self.__dict__.get("_capture_source_headless", False)),
            realtime=False,
        )
        self._set_realtime_save_status(
            "failed",
            path=str(message or ""),
        )
        self._set_status("실시간 저장 실패 - 이번 실행에서는 중단됨", "warning")
        if toast_message:
            self._show_toast(toast_message, "warning", 4000)

    def _open_realtime_save_for_run(self) -> bool:
        self._reset_realtime_save_run_state()
        self.realtime_file = None
        if not bool(getattr(self.realtime_save_check, "isChecked", lambda: False)()):
            return False

        try:
            Path(Config.REALTIME_DIR).mkdir(exist_ok=True)
            filename = (
                f"{Config.REALTIME_DIR}/자막_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            )
            self.realtime_file = open(filename, "w", encoding="utf-8-sig")
            self._set_realtime_save_status("active", path=filename)
            return True
        except Exception as e:
            logger.error("실시간 저장 파일 생성 오류: %s", e)
            self.realtime_file = None
            self._disable_realtime_save_for_run(
                message=str(e),
                toast_message="실시간 저장 파일을 열지 못해 이번 실행에서는 실시간 저장을 중단합니다.",
            )
            return False

    def _block_session_replacement_while_saving(self, action_name: str) -> bool:
        if not bool(self.__dict__.get("_session_save_in_progress", False)):
            return False
        action_label = str(action_name or "작업").strip() or "작업"
        self._set_status("세션 저장 마무리 대기 중...", "warning")
        self._show_toast(
            f"세션 저장 완료 후 다시 시도하세요. ({action_label})",
            "warning",
            3000,
        )
        return True

    def _update_destructive_undo_action_state(self) -> None:
        action = self.__dict__.get("undo_destructive_action")
        if action is None:
            return
        has_snapshot = bool(self.__dict__.get("_destructive_undo_snapshot"))
        try:
            action.setEnabled((not bool(self.__dict__.get("is_running", False))) and has_snapshot)
        except Exception:
            return

    def _clear_destructive_undo_state(self) -> None:
        self._destructive_undo_snapshot = None
        self._update_destructive_undo_action_state()

    def _invalidate_destructive_undo(self) -> None:
        if bool(self.__dict__.get("_restoring_destructive_undo", False)):
            return
        self._clear_destructive_undo_state()

    def _store_destructive_undo_snapshot(self) -> bool:
        if bool(self.__dict__.get("_restoring_destructive_undo", False)):
            return False

        entries = [entry.clone() for entry in self._build_prepared_entries_snapshot()]
        self._destructive_undo_snapshot = {
            "subtitles": entries,
            "capture_source_url": str(self.__dict__.get("_capture_source_url", "") or ""),
            "capture_source_committee": str(self.__dict__.get("_capture_source_committee", "") or ""),
            "capture_source_headless": bool(self.__dict__.get("_capture_source_headless", False)),
            "capture_source_realtime": bool(self.__dict__.get("_capture_source_realtime", False)),
            "current_url": str(self.__dict__.get("current_url", "") or ""),
            "dirty": self._has_dirty_session(),
        }
        self._update_destructive_undo_action_state()
        return True

    def _notify_destructive_undo_available(self) -> None:
        self._update_destructive_undo_action_state()
        self._show_toast("되돌리기 가능 (Ctrl+Z)", "info", 2500)

    def _restore_last_destructive_change(self) -> bool:
        if self._is_runtime_mutation_blocked("되돌리기"):
            return False

        snapshot = self.__dict__.get("_destructive_undo_snapshot")
        if not isinstance(snapshot, dict):
            self._show_toast("되돌릴 변경이 없습니다.", "info", 2000)
            return False

        self._restoring_destructive_undo = True
        try:
            entries = [
                entry.clone()
                for entry in snapshot.get("subtitles", [])
                if isinstance(entry, SubtitleEntry)
            ]
            self._replace_subtitles_and_refresh(
                entries,
                keep_history_from_subtitles=bool(entries),
            )
            self._set_capture_source_metadata(
                str(snapshot.get("capture_source_url", "") or ""),
                str(snapshot.get("capture_source_committee", "") or ""),
                headless=bool(snapshot.get("capture_source_headless", False)),
                realtime=bool(snapshot.get("capture_source_realtime", False)),
            )
            restored_current_url = str(snapshot.get("current_url", "") or "")
            self.current_url = restored_current_url
            url_combo = self.__dict__.get("url_combo")
            if url_combo is not None:
                try:
                    url_combo.setCurrentText(restored_current_url)
                except Exception:
                    try:
                        url_combo.setEditText(restored_current_url)
                    except Exception:
                        pass
            if bool(snapshot.get("dirty", False)):
                self._mark_session_dirty()
            else:
                self._clear_session_dirty()
            self._show_toast("마지막 파괴적 변경을 되돌렸습니다.", "success", 2500)
            return True
        finally:
            self._restoring_destructive_undo = False
            self._clear_destructive_undo_state()

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
        self._update_destructive_undo_action_state()

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

    def _coerce_highlight_sequence(self, value: object) -> int:
        if value is None:
            return -1
        if isinstance(value, str) and not value.strip():
            return -1
        try:
            return int(value)
        except Exception:
            return -1

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
