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


class MainWindowPersistenceSessionSaveMixin(MainWindowHost):
    """세션 스냅샷 저장 (SRP: JSON+DB 동기/비동기 저장)."""

    def _choose_session_snapshot_path(
            self,
            *,
            dialog_title: str = "세션 저장",
        ) -> str | None:
            filename = (
                f"{Config.SESSION_DIR}/세션_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
            )
            path, _ = QFileDialog.getSaveFileName(
                self,
                dialog_title,
                filename,
                "JSON (*.json)",
            )
            if not path:
                return None
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            return path

    def _start_async_session_snapshot_save(
            self,
            path: str,
            prepared_entries: list[SubtitleEntry],
            *,
            runtime_root: Path | None = None,
            runtime_manifest: list[dict[str, Any]] | None = None,
            on_success: Callable[[], None] | None = None,
            action_name: str = "",
        ) -> bool:
            if self._session_save_in_progress:
                self._show_toast("이미 세션 저장이 진행 중입니다.", "info")
                return False

            if on_success is not None:
                self._set_pending_deferred_action(action_name, on_success)

            snapshot_entries = [entry.clone() for entry in prepared_entries]
            snapshot_revision = self._get_session_revision()
            save_operation_id = uuid.uuid4().hex
            self._session_save_in_progress = True
            self._set_status("세션 저장 중...", "running")

            def background_save() -> None:
                try:
                    info = self._write_session_snapshot(
                        path,
                        snapshot_entries,
                        include_db=True,
                        runtime_root=runtime_root,
                        runtime_manifest=runtime_manifest,
                        save_operation_id=save_operation_id,
                    )
                    info["snapshot_revision"] = snapshot_revision
                    info["save_operation_id"] = save_operation_id
                    self._emit_control_message("session_save_done", info)
                except Exception as e:
                    logger.error(f"세션 저장 오류: {e}")
                    self._emit_control_message(
                        "session_save_failed",
                        {
                            "path": path,
                            "error": str(e),
                            "snapshot_revision": snapshot_revision,
                            "save_operation_id": save_operation_id,
                        },
                    )

            started = self._start_background_thread(background_save, "SessionSaveWorker")
            if started:
                self._show_toast(f"💾 세션 저장 시작: {Path(path).name}", "info", 1500)
                return True

            self._session_save_in_progress = False
            self._clear_pending_deferred_action()
            self._set_status("세션 저장 시작 거부 (종료 중)", "warning")
            self._show_toast("종료 중이라 세션 저장을 시작할 수 없습니다.", "warning")
            return False

    def _write_session_snapshot(
            self,
            path: str,
            prepared_entries: list[SubtitleEntry],
            *,
            include_db: bool = True,
            runtime_root: Path | None = None,
            runtime_manifest: list[dict[str, Any]] | None = None,
            save_operation_id: str | None = None,
        ) -> dict[str, Any]:
            """현재 세션 스냅샷을 JSON(+선택적 DB)으로 동기 저장한다."""
            snapshot_entries = [entry.clone() for entry in prepared_entries]
            current_url, committee_name, duration = self._build_session_save_context()
            created_at = datetime.now().isoformat()
            operation_id = str(save_operation_id or "").strip() or uuid.uuid4().hex
            capture_quality = self._get_capture_quality_payload()
            lineage_id = self._ensure_session_lineage_id()
            manifest_items = (
                runtime_manifest
                if runtime_manifest is not None
                else list(self.__dict__.get("_runtime_segment_manifest", []))
            )
            saved_count = sum(
                int(item.get("entry_count", 0) or 0)
                for item in manifest_items
            ) + len(snapshot_entries)
            utils.atomic_write_json_stream(
                path,
                head_items=[
                    ("version", Config.VERSION),
                    ("created", created_at),
                    ("url", current_url),
                    ("committee_name", committee_name),
                    ("lineage_id", lineage_id),
                    ("save_operation_id", operation_id),
                    ("capture_quality", capture_quality),
                ],
                sequence_key="subtitles",
                sequence_items=self._iter_full_session_serialized_items(
                    snapshot_entries,
                    runtime_root=runtime_root,
                    runtime_manifest=manifest_items,
                ),
                ensure_ascii=False,
            )
            self._record_recovery_snapshot(
                path,
                "session",
                created_at=created_at,
                url=current_url,
                committee_name=committee_name,
                lineage_id=lineage_id,
            )

            db_saved = False
            db_error = ""
            db_session_id = None
            if include_db:
                db = self.db
                if db is None or not bool(self.__dict__.get("db_available", False)):
                    db_error = self._get_db_degraded_message()
                else:
                    try:
                        db_data = {
                            "url": current_url,
                            "committee_name": committee_name,
                            "prepared_entries": snapshot_entries,
                            "runtime_root": runtime_root,
                            "runtime_manifest": [dict(item) for item in manifest_items],
                            "version": Config.VERSION,
                            "duration_seconds": duration,
                            "lineage_id": lineage_id,
                            "parent_session_id": self.__dict__.get("current_db_session_id"),
                            "save_operation_id": operation_id,
                            "capture_quality": capture_quality,
                        }
                        db_session_id = self._run_db_task_sync(
                            "db_session_save",
                            lambda data=dict(db_data): db.save_session(
                                {
                                    "url": data["url"],
                                    "committee_name": data["committee_name"],
                                    "subtitles": self._iter_full_session_entries(
                                        data["prepared_entries"],
                                        runtime_root=data["runtime_root"],
                                        runtime_manifest=data["runtime_manifest"],
                                    ),
                                    "version": data["version"],
                                    "duration_seconds": data["duration_seconds"],
                                    "lineage_id": data["lineage_id"],
                                    "parent_session_id": data["parent_session_id"],
                                    "save_operation_id": data["save_operation_id"],
                                    "capture_quality": data["capture_quality"],
                                }
                            ),
                            write_task=True,
                            timeout=None,
                        )
                        db_saved = True
                    except Exception as db_exc:
                        db_error = str(db_exc)

            return {
                "path": path,
                "saved_count": saved_count,
                "db_saved": db_saved,
                "db_error": db_error,
                "save_operation_id": operation_id,
                "db_session_id": db_session_id,
                "lineage_id": lineage_id,
                "url": current_url,
                "committee_name": committee_name,
                "created_at": created_at,
            }

    def _prompt_write_session_snapshot(
            self,
            prepared_entries: list[SubtitleEntry],
            *,
            dialog_title: str = "세션 저장",
        ) -> dict[str, Any] | None:
            """준비된 세션 스냅샷을 사용자 선택 경로에 동기 저장한다."""
            runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
            snapshot_revision = self._get_session_revision()
            if not prepared_entries and not runtime_manifest:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return None

            filename = (
                f"{Config.SESSION_DIR}/세션_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
            )
            path, _ = QFileDialog.getSaveFileName(
                self, dialog_title, filename, "JSON (*.json)"
            )
            if not path:
                return None

            try:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                try:
                    info = self._write_session_snapshot(
                        path,
                        prepared_entries,
                        include_db=True,
                        runtime_root=runtime_root,
                        runtime_manifest=runtime_manifest,
                    )
                except TypeError as exc:
                    err_text = str(exc)
                    if "runtime_root" not in err_text and "runtime_manifest" not in err_text:
                        raise
                    info = self._write_session_snapshot(
                        path,
                        prepared_entries,
                        include_db=True,
                    )
                try:
                    save_is_current = (
                        self._clear_session_dirty(saved_revision=snapshot_revision)
                        is not False
                    )
                except TypeError as exc:
                    if "saved_revision" not in str(exc):
                        raise
                    save_is_current = self._clear_session_dirty() is not False
                if save_is_current:
                    self._clear_recovery_state()
                self._apply_saved_session_db_identity(info)
                db_error = str(info.get("db_error", "") or "").strip()
                if db_error:
                    QMessageBox.warning(
                        self,
                        "DB 저장 경고",
                        "세션 JSON 저장은 완료되었지만 DB 저장은 실패했습니다.\n"
                        f"위치: {path}\n오류: {db_error}",
                    )
                return info
            except Exception as e:
                QMessageBox.critical(self, "오류", f"세션 저장 실패: {e}")
                return None
