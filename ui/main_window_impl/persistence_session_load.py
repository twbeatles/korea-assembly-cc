# -*- coding: utf-8 -*-

import uuid

from core.file_io import canonical_path_key, read_limited_json_file
from core.resource_budget import ResourceBudget, ResourceBudgetLimits, ResourceLimitExceeded
from PySide6 import QtWidgets
from core.recovery_candidates import (
    discover_recovery_candidates,
    inspect_recovery_candidate,
)
from ui.dialogs import RecoveryCandidateDialog
from ui.main_window_common import *
from ui.main_window_types import MainWindowHost

QProgressDialog = cast(Any, getattr(QtWidgets, "QProgressDialog"))


class MainWindowPersistenceSessionLoadMixin(MainWindowHost):
    """세션 불러오기 (SRP: 파일 로드/역직렬화)."""

    def _finish_session_load(self) -> bool:
            event = self.__dict__.get("_session_load_cancel_event")
            cancelled = bool(event is not None and event.is_set())
            self._session_load_in_progress = False
            dialog = self.__dict__.get("_session_load_progress_dialog")
            self._session_load_progress_dialog = None
            if dialog is not None:
                dialog.close()
                dialog.deleteLater()
            return cancelled

    def _handle_session_load_progress(self, payload: dict[str, Any]) -> None:
            if not self.__dict__.get("_session_load_in_progress", False):
                return
            dialog = self.__dict__.get("_session_load_progress_dialog")
            if dialog is not None:
                dialog.setLabelText(str(payload.get("phase", "세션 불러오는 중...")))
                dialog.setValue(min(99, int(payload.get("percent", 0))))

    def _start_session_load_from_path(
            self,
            path: str,
            *,
            mark_dirty: bool = False,
            recovery: bool = False,
        ) -> bool:
            if self._is_background_shutdown_active():
                self._show_toast("종료 중이라 세션 불러오기를 시작할 수 없습니다.", "warning")
                return False
            if self._block_session_replacement_while_saving(
                "세션 복구" if recovery else "세션 불러오기"
            ):
                return False
            if self._session_load_in_progress:
                self._show_toast("이미 세션 불러오기가 진행 중입니다.", "info")
                return False
            try:
                session_path = Path(path)
                max_bytes = int(getattr(Config, "SESSION_LOAD_MAX_BYTES", 0) or 0)
                if max_bytes > 0:
                    file_size = session_path.stat().st_size
                    if file_size > max_bytes:
                        limit_mb = max_bytes / (1024 * 1024)
                        actual_mb = file_size / (1024 * 1024)
                        QMessageBox.warning(
                            self,
                            "세션 파일 크기 초과",
                            (
                                "세션 파일이 너무 커서 불러오기를 중단했습니다.\n"
                                f"파일 크기: {actual_mb:.1f} MB\n"
                                f"허용 크기: {limit_mb:.1f} MB"
                            ),
                        )
                        self._set_status(
                            "세션 파일이 너무 커서 불러오기를 중단했습니다.",
                            "warning",
                        )
                        return False
            except OSError as exc:
                QMessageBox.warning(
                    self,
                    "세션 파일 확인 실패",
                    f"세션 파일을 확인할 수 없습니다.\n{exc}",
                )
                self._set_status("세션 파일 확인 실패", "warning")
                return False

            self._session_load_in_progress = True
            cancel_event = threading.Event()
            self._session_load_cancel_event = cancel_event
            if self.__dict__.get("_session_load_progress_enabled", False):
                dialog = QProgressDialog("세션 파일을 읽는 중...", "취소", 0, 100, self)
                dialog.setWindowModality(Qt.WindowModality.WindowModal)
                dialog.setAutoClose(False)
                dialog.setAutoReset(False)
                dialog.canceled.connect(cancel_event.set)
                dialog.setMinimumDuration(0)
                self._session_load_progress_dialog = dialog
                dialog.show()
            status_text = "세션 복구 중..." if recovery else "세션 불러오기 중..."
            self._set_status(status_text, "running")

            def background_load():
                try:
                    budget = ResourceBudget(
                        ResourceBudgetLimits(
                            per_file_bytes=min(int(Config.SESSION_LOAD_MAX_BYTES), int(Config.SESSION_RESOURCE_PER_FILE_MAX_BYTES)),
                            total_bytes=int(Config.SESSION_RESOURCE_TOTAL_MAX_BYTES),
                            max_entries=int(Config.SESSION_RESOURCE_MAX_ENTRIES),
                            max_segments=int(Config.SESSION_RESOURCE_MAX_SEGMENTS),
                        ),
                        cancel_check=cancel_event.is_set,
                    )
                    try:
                        data = read_limited_json_file(
                            path, max_bytes=budget.limits.per_file_bytes, label="세션 JSON",
                            cancel_check=cancel_event.is_set,
                            progress=lambda current, total: self._emit_control_message(
                                "session_load_progress", {"percent": min(50, current * 50 // total), "phase": "세션 파일을 읽는 중..."}
                            ),
                        )
                        if not isinstance(data, dict):
                            raise ValueError("세션 JSON은 object여야 합니다.")
                    except json.JSONDecodeError as json_err:
                        if recovery:
                            try:
                                payload = self._load_runtime_manifest_payload(
                                    path,
                                    allow_salvage=True,
                                )
                                payload["mark_dirty"] = mark_dirty
                                payload["recovery"] = recovery
                                self._emit_control_message("session_load_done", payload)
                                return
                            except Exception:
                                logger.debug(
                                    "손상된 recovery snapshot salvage 실패: %s",
                                    path,
                                    exc_info=True,
                                )
                        self._emit_control_message(
                            "session_load_json_error",
                            {"path": path, "error": str(json_err), "recovery": recovery},
                        )
                        return

                    if str(data.get("format", "") or "") == "runtime_session_manifest_v1":
                        payload = self._load_runtime_manifest_payload(
                            path,
                            allow_salvage=recovery,
                        )
                        payload["mark_dirty"] = mark_dirty
                        payload["recovery"] = recovery
                        self._emit_control_message("session_load_done", payload)
                        return

                    budget.consume_file(Path(path).stat().st_size, label="세션 JSON")
                    raw_entries = data.get("subtitles", [])
                    if isinstance(raw_entries, (list, tuple)):
                        budget.consume_entries(len(raw_entries))
                    session_version = data.get("version", "unknown")
                    new_subtitles, skipped = self._deserialize_subtitles(
                        raw_entries,
                        source=f"session:{path}",
                        cancel_check=cancel_event.is_set,
                        progress=lambda current, total: self._emit_control_message(
                            "session_load_progress", {"percent": 50 + current * 50 // max(1, total), "phase": f"자막 불러오는 중... {current:,}/{total:,}"}
                        ),
                    )
                    budget.check_cancelled()

                    self._emit_control_message(
                        "session_load_done",
                        {
                            "path": path,
                            "version": session_version,
                            "created_at": data.get("created", ""),
                            "url": data.get("url", ""),
                            "committee_name": data.get("committee_name", ""),
                            "lineage_id": data.get("lineage_id", ""),
                            "capture_quality": data.get("capture_quality", {}),
                            "subtitles": new_subtitles,
                            "skipped": skipped,
                            "mark_dirty": mark_dirty,
                            "recovery": recovery,
                        },
                    )
                except ResourceLimitExceeded as e:
                    self._emit_control_message(
                        "session_load_cancelled" if e.resource == "cancelled" else "session_load_failed",
                        {"path": path, "error": str(e), "recovery": recovery},
                    )
                except Exception as e:
                    logger.error(f"세션 불러오기 오류: {e}")
                    self._emit_control_message(
                        "session_load_failed",
                        {"path": path, "error": str(e), "recovery": recovery},
                    )

            started = self._start_background_thread(background_load, "SessionLoadWorker")
            if not started:
                self._finish_session_load()
                self._set_status("세션 불러오기 시작 거부 (종료 중)", "warning")
                self._show_toast("종료 중이라 세션 불러오기를 시작할 수 없습니다.", "warning")
                return False

            message = (
                f"📂 복구 시작: {Path(path).name}"
                if recovery
                else f"📂 세션 불러오기 시작: {Path(path).name}"
            )
            self._show_toast(message, "info", 1500)
            return True

    def _load_session(self):
            if self._is_runtime_mutation_blocked("세션 불러오기"):
                return
            if self._block_session_replacement_while_saving("세션 불러오기"):
                return

            def continue_load() -> None:
                path, _ = QFileDialog.getOpenFileName(
                    self, "세션 불러오기", f"{Config.SESSION_DIR}/", "JSON (*.json)"
                )

                if not path:
                    return
                self._start_session_load_from_path(path)

            self._run_after_dirty_session_action("세션 불러오기", continue_load)

    def _deserialize_subtitles(
            self, serialized_items, source: str = "", *,
            cancel_check: Callable[[], bool] | None = None,
            progress: Callable[[int, int], None] | None = None,
        ) -> tuple[list[SubtitleEntry], int]:
            """직렬화된 자막 목록을 SubtitleEntry 리스트로 변환한다."""
            entries: list[SubtitleEntry] = []
            skipped = 0

            if serialized_items is None:
                return entries, skipped

            if not isinstance(serialized_items, (list, tuple)):
                logger.warning("자막 목록 타입 오류 (%s): %s", source, type(serialized_items))
                return entries, 1

            for index, item in enumerate(serialized_items):
                if cancel_check is not None and cancel_check():
                    raise ResourceLimitExceeded("cancelled", limit=None, observed=None, label="세션 불러오기")
                try:
                    entries.append(SubtitleEntry.from_dict(item))
                except (ValueError, TypeError, KeyError) as e:
                    logger.warning("손상된 자막 항목 건너뜀 (%s): %s", source, e)
                    skipped += 1
                if progress is not None and (index % 500 == 0 or index + 1 == len(serialized_items)):
                    progress(index + 1, len(serialized_items))

            return entries, skipped
