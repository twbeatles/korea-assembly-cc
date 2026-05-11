# -*- coding: utf-8 -*-

import hashlib
import bisect
import shutil
from typing import Any, Iterable, cast
from uuid import uuid4

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt, QTimer

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost

QProgressDialog = cast(Any, getattr(QtWidgets, "QProgressDialog"))


class MainWindowRuntimeHydrationMixin(MainWindowHost):

    def _reset_hydration_state(self) -> None:
            dialog = self.__dict__.get("_hydrate_progress_dialog")
            self._hydrate_in_progress = False
            self._hydrate_progress_dialog = None
            self._hydrate_cancel_event.clear()
            self._pending_hydration_action = None
            self._pending_hydration_action_name = ""
            if dialog is not None:
                try:
                    dialog.close()
                except Exception:
                    logger.debug("hydrate progress dialog close 실패", exc_info=True)
                try:
                    dialog.deleteLater()
                except Exception:
                    logger.debug("hydrate progress dialog delete 실패", exc_info=True)

    def _handle_hydrate_progress(self, payload: dict[str, object]) -> None:
            dialog = self.__dict__.get("_hydrate_progress_dialog")
            if dialog is None:
                return
            current_raw = payload.get("current", 0)
            total_raw = payload.get("total", 1)
            try:
                current = int(cast(Any, current_raw if current_raw is not None else 0))
            except Exception:
                current = 0
            try:
                total = int(cast(Any, total_raw if total_raw is not None else 1))
            except Exception:
                total = 1
            total = max(1, total)
            reason = str(payload.get("reason", "") or "")
            label = "장시간 세션 전체를 불러오는 중입니다..."
            if reason:
                label += f"\n작업: {reason}"
            try:
                dialog.setLabelText(label)
                dialog.setMaximum(total)
                dialog.setValue(min(current, total))
            except Exception:
                logger.debug("hydrate progress 업데이트 실패", exc_info=True)

    def _handle_hydrate_done(self, payload: dict[str, object]) -> None:
            action = self.__dict__.get("_pending_hydration_action")
            action_name = str(self.__dict__.get("_pending_hydration_action_name", "") or "")
            subtitles = payload.get("subtitles", [])
            if not isinstance(subtitles, list):
                subtitles = []
            self._reset_hydration_state()
            self._replace_subtitles_and_refresh(
                subtitles,
                keep_history_from_subtitles=bool(subtitles),
            )
            self._cleanup_runtime_session_archive(remove_files=False)
            if action_name:
                self._show_toast(
                    f"장시간 세션 전체를 메모리로 불러왔습니다. ({action_name})",
                    "info",
                    3000,
                )
            if callable(action):
                QTimer.singleShot(0, action)

    def _handle_hydrate_failed(self, payload: dict[str, object]) -> None:
            error = str(payload.get("error", "세션 hydrate 실패") or "세션 hydrate 실패")
            self._reset_hydration_state()
            self._set_status(f"세션 hydrate 실패: {error}", "error")
            QMessageBox.critical(self, "오류", f"장시간 세션 hydrate 실패: {error}")

    def _handle_hydrate_cancelled(self, payload: dict[str, object]) -> None:
            reason = str(payload.get("reason", "") or "")
            self._reset_hydration_state()
            message = "세션 전체 불러오기를 취소했습니다."
            if reason:
                message += f" ({reason})"
            self._set_status(message, "warning")
            self._show_toast(message, "warning", 2500)

    def _run_after_full_session_hydrated(
            self,
            reason: str,
            callback: Callable[[], None],
        ) -> bool:
            if not self._has_runtime_archived_segments():
                callback()
                return True
            if self._hydrate_in_progress:
                self._show_toast("이미 장시간 세션을 불러오는 중입니다.", "info")
                return False
            if self._is_background_shutdown_active():
                self._show_toast("종료 중이라 세션 전체 불러오기를 시작할 수 없습니다.", "warning")
                return False

            prepared_entries = self._build_persistent_entries_snapshot()
            runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
            total_entries = sum(
                int(item.get("entry_count", 0) or 0)
                for item in runtime_manifest
            ) + len(prepared_entries)
            total_entries = max(1, total_entries)

            self._hydrate_in_progress = True
            self._hydrate_cancel_event.clear()
            self._pending_hydration_action = callback
            self._pending_hydration_action_name = str(reason or "").strip()

            dialog = QProgressDialog(
                "장시간 세션 전체를 불러오는 중입니다...",
                "취소",
                0,
                total_entries,
                self,
            )
            dialog.setWindowTitle("세션 불러오기")
            dialog.setWindowModality(Qt.WindowModality.WindowModal)
            dialog.setMinimumDuration(0)
            dialog.setAutoClose(False)
            dialog.setAutoReset(False)
            dialog.canceled.connect(self._hydrate_cancel_event.set)
            dialog.show()
            self._hydrate_progress_dialog = dialog

            def hydrate_worker() -> None:
                try:
                    full_entries: list[SubtitleEntry] = []
                    completed = 0
                    for segment_info in runtime_manifest:
                        if self._hydrate_cancel_event.is_set():
                            self._emit_control_message("hydrate_cancelled", {"reason": reason})
                            return
                        segment_entries = self._load_runtime_segment_entries(
                            segment_info,
                            runtime_root=runtime_root,
                        )
                        full_entries.extend(entry.clone() for entry in segment_entries)
                        completed += len(segment_entries)
                        self._emit_control_message(
                            "hydrate_progress",
                            {
                                "reason": reason,
                                "current": completed,
                                "total": total_entries,
                            },
                        )
                    for entry in prepared_entries:
                        if self._hydrate_cancel_event.is_set():
                            self._emit_control_message("hydrate_cancelled", {"reason": reason})
                            return
                        full_entries.append(entry.clone())
                        completed += 1
                        if completed == total_entries or completed % 50 == 0:
                            self._emit_control_message(
                                "hydrate_progress",
                                {
                                    "reason": reason,
                                    "current": completed,
                                    "total": total_entries,
                                },
                            )
                    self._emit_control_message(
                        "hydrate_done",
                        {
                            "reason": reason,
                            "subtitles": full_entries,
                            "current": total_entries,
                            "total": total_entries,
                        },
                    )
                except Exception as exc:
                    logger.exception("세션 hydrate 실패")
                    self._emit_control_message(
                        "hydrate_failed",
                        {"reason": reason, "error": str(exc)},
                    )

            started = self._start_background_thread(hydrate_worker, "SessionHydrateWorker")
            if started:
                return False

            self._reset_hydration_state()
            self._show_toast("종료 중이라 세션 전체 불러오기를 시작할 수 없습니다.", "warning")
            return False

    def _ensure_full_session_hydrated(self, reason: str = "") -> bool:
            completed = {"done": False}

            def mark_done() -> None:
                completed["done"] = True

            self._run_after_full_session_hydrated(reason, mark_done)
            return bool(completed["done"])
