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
                data = json.loads(recovery_path.read_text(encoding="utf-8"))
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

            recovery_state = self._load_recovery_state()
            if not recovery_state:
                return

            candidates = []
            if Path(Config.RECOVERY_STATE_FILE).is_file():
                candidates = discover_recovery_candidates(
                    recovery_state_file=Config.RECOVERY_STATE_FILE,
                    backup_dir=Config.BACKUP_DIR,
                    runtime_session_dir=Config.RUNTIME_SESSION_DIR,
                )
            pointer_path = str(recovery_state.get("path", "") or "").strip()
            candidate_keys = {canonical_path_key(item.path) for item in candidates}
            if pointer_path and canonical_path_key(pointer_path) not in candidate_keys:
                candidates.append(
                    inspect_recovery_candidate(
                        pointer_path,
                        snapshot_type=str(
                            recovery_state.get("snapshot_type", "session") or "session"
                        ),
                    )
                )
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
                "이전에 정상 종료되지 않은 것으로 보입니다.\n"
                f"최신 {description}을 복구하시겠습니까?\n"
                f"파일: {snapshot_path}{created_suffix}{detail}{priority_hint}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._start_session_load_from_path(
                snapshot_path,
                mark_dirty=True,
                recovery=True,
            )
