# -*- coding: utf-8 -*-

import json
import threading
import uuid
from typing import Any, cast

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from core.file_io import canonical_path_key, read_limited_json_file
from core.recovery_candidates import (
    RecoveryCandidate,
    discover_recovery_candidates,
    inspect_recovery_candidate,
)
from ui.dialogs import RecoveryCandidateDialog
from ui.main_window_common import (
    Config,
    Path,
    QDialog,
    QMessageBox,
    datetime,
    logger,
    utils,
)
from ui.main_window_types import MainWindowHost

QProgressDialog = cast(Any, getattr(QtWidgets, "QProgressDialog"))


class MainWindowPersistenceSessionRecoveryMixin(MainWindowHost):
    """복구 포인터 (SRP: recovery state 기록/제안)."""

    def _record_recovery_snapshot(
            self,
            path: str | Path,
            snapshot_type: str,
            *,
            created_at: str,
            url: str = "",
            committee_name: str = "",
            lineage_id: str = "",
        ) -> None:
            utils.atomic_write_json(
                Config.RECOVERY_STATE_FILE,
                {
                    "path": str(Path(path).resolve()),
                    "snapshot_type": str(snapshot_type or "session"),
                    "created_at": str(created_at or ""),
                    "saved_at": datetime.now().isoformat(),
                    "url": str(url or ""),
                    "committee_name": str(committee_name or ""),
                    "lineage_id": str(lineage_id or ""),
                },
                ensure_ascii=False,
            )

    def _clear_recovery_state(self) -> None:
            try:
                Path(Config.RECOVERY_STATE_FILE).unlink(missing_ok=True)
            except Exception as e:
                logger.debug(f"recovery state 정리 오류: {e}")

    def _load_recovery_state(self) -> dict[str, Any] | None:
            recovery_path = Path(Config.RECOVERY_STATE_FILE)
            if not recovery_path.exists():
                return None
            try:
                data = read_limited_json_file(
                    recovery_path,
                    max_bytes=int(Config.URL_HISTORY_MAX_BYTES),
                    label="recovery pointer",
                )
            except Exception as e:
                logger.warning(f"recovery state 파싱 오류: {e}")
                self._clear_recovery_state()
                return None
            if not isinstance(data, dict):
                self._clear_recovery_state()
                return None
            snapshot_path = str(data.get("path", "") or "").strip()
            if not snapshot_path or not Path(snapshot_path).exists():
                self._clear_recovery_state()
                return None
            return data

    def _prompt_session_recovery_if_available(self) -> None:
            if bool(self.__dict__.get("_startup_recovery_prompted", False)):
                return
            self._startup_recovery_prompted = True
            if self._session_load_in_progress or self.is_running:
                return

            had_pointer = Path(Config.RECOVERY_STATE_FILE).exists()
            recovery_state = self._load_recovery_state()
            if not recovery_state:
                if had_pointer:
                    self._show_toast(
                        "복구 포인터를 읽을 수 없습니다. 파일 메뉴의 '백업에서 세션 복구'를 사용하세요.",
                        "warning", 5000,
                    )
                return
            self._start_recovery_scan(recovery_state=recovery_state)

    def _recover_session(self) -> None:
            """Explicit recovery also works after a missing/corrupt pointer."""
            if self._is_runtime_mutation_blocked("세션 복구"):
                return
            if self._session_load_in_progress or self._block_session_replacement_while_saving("세션 복구"):
                return
            self._start_recovery_scan(manual=True)

    def _start_recovery_scan(
            self, *, recovery_state: dict[str, Any] | None = None,
            manual: bool = False,
        ) -> bool:
            if self.__dict__.get("_recovery_scan_in_progress", False):
                self._show_toast("복구 후보를 검색하고 있습니다.", "info")
                return False
            if self._is_background_shutdown_active():
                return False
            token = uuid.uuid4().hex
            cancelled = threading.Event()
            dialog = QProgressDialog("복구 후보 검색 중...", "취소", 0, 0, self)
            dialog.setWindowModality(Qt.WindowModality.WindowModal)
            dialog.canceled.connect(cancelled.set)
            self._recovery_scan_token = token
            self._recovery_scan_in_progress = True
            self._recovery_scan_cancel = cancelled
            self._recovery_scan_dialog = dialog
            paths = dict(recovery_state_file=Config.RECOVERY_STATE_FILE,
                         backup_dir=Config.BACKUP_DIR,
                         runtime_session_dir=Config.RUNTIME_SESSION_DIR)
            def worker() -> None:
                result: dict[str, Any] = {"token": token, "manual": manual,
                                          "state": dict(recovery_state or {})}
                try:
                    result["candidates"] = discover_recovery_candidates(
                        recovery_state_file=paths["recovery_state_file"],
                        backup_dir=paths["backup_dir"],
                        runtime_session_dir=paths["runtime_session_dir"],
                        cancel_check=lambda: cancelled.is_set() or self._is_background_shutdown_active(),
                        progress=lambda count: self._emit_control_message(
                            "recovery_scan_progress", {"token": token, "count": count}),
                    )
                except Exception as exc:
                    result["error"] = str(exc)
                self._emit_control_message("recovery_scan_done", result)
            if not self._start_background_thread(worker, "RecoveryScanWorker"):
                self._recovery_scan_in_progress = False
                self._recovery_scan_token = None
                self._recovery_scan_dialog = None
                dialog.close()
                dialog.deleteLater()
                return False
            dialog.show()
            return True

    def _handle_recovery_scan_progress(self, payload: dict[str, Any]) -> None:
            if payload.get("token") != self.__dict__.get("_recovery_scan_token"):
                return
            dialog = self.__dict__.get("_recovery_scan_dialog")
            if dialog is not None:
                dialog.setLabelText(f"복구 후보 {payload.get('count', 0)}개 확인 중...")

    def _handle_recovery_scan_done(self, payload: dict[str, Any]) -> None:
            if not self.__dict__.get("_recovery_scan_in_progress", False) or (
                payload.get("token") != self.__dict__.get("_recovery_scan_token")
            ):
                return
            self._recovery_scan_in_progress = False
            self._recovery_scan_token = None
            cancelled = self.__dict__.get("_recovery_scan_cancel")
            was_cancelled = cancelled is not None and cancelled.is_set()
            dialog = self.__dict__.get("_recovery_scan_dialog")
            self._recovery_scan_dialog = None
            if dialog is not None:
                dialog.close()
                dialog.deleteLater()
            if was_cancelled or self._is_background_shutdown_active():
                return
            if payload.get("error"):
                self._show_toast(f"복구 후보 검색 실패: {payload['error']}", "warning", 5000)
                return
            if self.is_running or self._session_load_in_progress:
                return
            self._present_recovery_candidates(
                payload.get("candidates", []), payload.get("state", {}),
                manual=bool(payload.get("manual", False)),
            )

    def _present_recovery_candidates(
            self, candidates: list[RecoveryCandidate], recovery_state: dict[str, Any],
            *, manual: bool = False,
        ) -> None:
            usable_candidates = [
                candidate for candidate in candidates if candidate.integrity != "invalid"
            ]
            if len(usable_candidates) > 1:
                dialog = RecoveryCandidateDialog(candidates, self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                selected = dialog.selected_candidate
                if selected is None:
                    return
                recovery_state = {
                    "path": str(selected.path),
                    "snapshot_type": selected.snapshot_type,
                    "created_at": selected.created_at,
                }
            elif len(usable_candidates) == 1:
                selected = usable_candidates[0]
                recovery_state = {
                    **recovery_state,
                    "path": str(selected.path),
                    "snapshot_type": selected.snapshot_type,
                    "created_at": selected.created_at,
                }
            elif candidates:
                self._report_user_visible_warning(
                    "사용 가능한 세션 복구본이 없습니다.",
                    toast=False,
                )
                return
            else:
                self._show_toast("사용 가능한 세션 복구본이 없습니다.", "info")
                return

            snapshot_path = str(recovery_state.get("path", "") or "")
            snapshot_type = str(recovery_state.get("snapshot_type", "") or "session")
            created_at = str(recovery_state.get("created_at", "") or "")
            if snapshot_type == "backup":
                description = "자동 백업"
                detail = (
                    "\n\n5분 자동 백업 JSON입니다. "
                    "장시간 추출 중에는 segment/tail 기반 런타임 복구 포인터가 "
                    "우선 기록될 수 있습니다."
                )
                priority_hint = (
                    "\n\n우선순위: 장시간 추출이었다면 런타임 복구본이 더 최신일 수 있습니다. "
                    "복구 후 자막 수·시각을 확인하세요."
                )
            elif snapshot_type == "runtime_manifest":
                description = "런타임 세션 복구본"
                detail = (
                    "\n\n장시간 추출 세션은 manifest + segment/tail 구조로 저장됩니다. "
                    "복구 후 전체 자막을 불러오는 데 시간이 걸릴 수 있습니다."
                )
                priority_hint = (
                    "\n\n우선순위: 장시간 추출 복구에는 이 런타임 복구본이 일반적으로 "
                    "5분 자동 백업보다 최신입니다."
                )
            else:
                description = "세션 저장본"
                detail = ""
                priority_hint = ""
            created_suffix = f"\n시각: {created_at}" if created_at else ""
            reply = QMessageBox.question(
                self,
                "세션 복구",
                ("백업에서 세션을 복구합니다.\n" if manual else "이전에 정상 종료되지 않은 것으로 보입니다.\n") +
                f"최신 {description}을 복구하시겠습니까?\n"
                f"파일: {snapshot_path}{created_suffix}{detail}{priority_hint}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            def load() -> None:
                self._start_session_load_from_path(
                    snapshot_path, mark_dirty=True, recovery=True,
                )
            if self.is_running or self._session_load_in_progress or self._is_background_shutdown_active():
                return
            self._run_after_dirty_session_action("세션 복구", load)
