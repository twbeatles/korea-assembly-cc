# -*- coding: utf-8 -*-

import uuid

from core.file_io import canonical_path_key
from core.recovery_candidates import (
    discover_recovery_candidates,
    inspect_recovery_candidate,
)
from ui.dialogs import RecoveryCandidateDialog
from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowPersistenceSessionDeferredMixin(MainWindowHost):
    """지연 액션·dirty 보호 (SRP: 저장 후 재개 흐름)."""

    def _clear_pending_deferred_action(self) -> None:
            self._pending_deferred_action = None
            self._pending_deferred_action_name = ""
            self._pending_deferred_action_after_save = False

    def _set_pending_deferred_action(
            self,
            action_name: str,
            callback: Callable[[], None],
        ) -> None:
            self._pending_deferred_action = callback
            self._pending_deferred_action_name = str(action_name or "").strip()
            self._pending_deferred_action_after_save = True

    def _resume_pending_deferred_action(self) -> bool:
            callback = self.__dict__.get("_pending_deferred_action")
            if not callable(callback):
                self._clear_pending_deferred_action()
                return False
            action_name = str(self.__dict__.get("_pending_deferred_action_name", "") or "")
            self._clear_pending_deferred_action()

            def run_callback() -> None:
                try:
                    callback()
                except Exception:
                    logger.exception("deferred action 재개 실패: %s", action_name or "unknown")
                    QMessageBox.critical(
                        self,
                        "오류",
                        f"저장 후 '{action_name or '작업'}' 재개 중 오류가 발생했습니다.",
                    )

            QTimer.singleShot(0, run_callback)
            return True

    def _run_after_dirty_session_action(
            self,
            action_name: str,
            callback: Callable[[], None],
        ) -> bool:
            confirm = getattr(self, "_confirm_dirty_session_action")
            try:
                return bool(confirm(action_name, on_continue=callback))
            except TypeError as exc:
                if "on_continue" not in str(exc):
                    raise
                confirmed = bool(confirm(action_name))
                if confirmed:
                    callback()
                return confirmed

    def _confirm_dirty_session_action(
            self,
            action_name: str,
            on_continue: Callable[[], None] | None = None,
        ) -> bool:
            """dirty 세션이 있을 때 현재 작업을 보호하고 진행 여부를 반환한다."""
            if not self._has_dirty_session():
                if callable(on_continue):
                    on_continue()
                return True

            prepared_entries = self._build_persistent_entries_snapshot()
            subtitle_count = len(prepared_entries)
            action_label = str(action_name or "작업").strip() or "작업"

            if subtitle_count > 0:
                reply = QMessageBox.question(
                    self,
                    f"{action_label} 확인",
                    f"저장하지 않은 세션 변경 {subtitle_count}개가 있습니다.\n\n"
                    f"{action_label} 전에 세션(JSON + DB)으로 저장하시겠습니까?",
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel,
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    self._clear_pending_deferred_action()
                    return False
                if reply == QMessageBox.StandardButton.Save:
                    if callable(on_continue):
                        runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
                        try:
                            path = self._choose_session_snapshot_path(dialog_title="세션 저장")
                        except Exception as e:
                            self._clear_pending_deferred_action()
                            QMessageBox.critical(self, "오류", f"세션 저장 경로 준비 실패: {e}")
                            return False
                        if not path:
                            self._clear_pending_deferred_action()
                            return False
                        return self._start_async_session_snapshot_save(
                            path,
                            prepared_entries,
                            runtime_root=runtime_root,
                            runtime_manifest=runtime_manifest,
                            on_success=on_continue,
                            action_name=action_label,
                        )
                    return (
                        self._prompt_write_session_snapshot(
                            prepared_entries,
                            dialog_title="세션 저장",
                        )
                        is not None
                    )
                if callable(on_continue):
                    on_continue()
                return True

            reply = QMessageBox.question(
                self,
                f"{action_label} 확인",
                "저장되지 않은 변경이 있습니다.\n계속하시겠습니까?",
                QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                self._clear_pending_deferred_action()
                return False
            if callable(on_continue):
                on_continue()
            return True
