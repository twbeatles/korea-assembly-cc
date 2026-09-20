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


class MainWindowPersistenceSessionLoadMixin(MainWindowHost):
    """세션 불러오기 (SRP: 파일 로드/역직렬화)."""

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
            status_text = "세션 복구 중..." if recovery else "세션 불러오기 중..."
            self._set_status(status_text, "running")

            def background_load():
                try:
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
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

                    session_version = data.get("version", "unknown")
                    new_subtitles, skipped = self._deserialize_subtitles(
                        data.get("subtitles", []),
                        source=f"session:{path}",
                    )

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
                except Exception as e:
                    logger.error(f"세션 불러오기 오류: {e}")
                    self._emit_control_message(
                        "session_load_failed",
                        {"path": path, "error": str(e), "recovery": recovery},
                    )

            started = self._start_background_thread(background_load, "SessionLoadWorker")
            if not started:
                self._session_load_in_progress = False
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
            self, serialized_items, source: str = ""
        ) -> tuple[list[SubtitleEntry], int]:
            """직렬화된 자막 목록을 SubtitleEntry 리스트로 변환한다."""
            entries: list[SubtitleEntry] = []
            skipped = 0

            if serialized_items is None:
                return entries, skipped

            if not isinstance(serialized_items, (list, tuple)):
                logger.warning("자막 목록 타입 오류 (%s): %s", source, type(serialized_items))
                return entries, 1

            for item in serialized_items:
                try:
                    entries.append(SubtitleEntry.from_dict(item))
                except (ValueError, TypeError, KeyError) as e:
                    logger.warning("손상된 자막 항목 건너뜀 (%s): %s", source, e)
                    skipped += 1

            return entries, skipped
