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


def _facade_datetime():
    """퍼사드 late-binding: 테스트의 datetime monkeypatch를 존중한다."""
    from importlib import import_module

    return import_module("ui.main_window_impl.persistence_session").datetime


class MainWindowPersistenceSessionBackupMixin(MainWindowHost):
    """자동 백업 (SRP: 백업 쓰기/정리)."""

    def _start_backup_snapshot_write(
            self,
            prepared_entries: list[SubtitleEntry],
            *,
            worker_name: str = "AutoBackupWorker",
        ) -> bool:
            """복구 가능한 백업 JSON 쓰기를 백그라운드에서 시작한다."""
            if self.__dict__.get("_runtime_session_root") is not None:
                return self._start_runtime_recovery_snapshot_write(
                    prepared_entries,
                    worker_name=worker_name,
                )
            if not prepared_entries or self._is_background_shutdown_active():
                return False
            if not self._auto_backup_lock.acquire(blocking=False):
                return False

            try:
                backup_dir = Path(Config.BACKUP_DIR)
                backup_dir.mkdir(exist_ok=True)
                timestamp = _facade_datetime().now().strftime("%Y%m%d_%H%M%S_%f")
                backup_file = utils.next_available_path(
                    backup_dir / f"backup_{timestamp}.json"
                )
                source_url, committee_name, _duration = self._build_session_save_context()
                created_at = _facade_datetime().now().isoformat()
                lineage_id = self._ensure_session_lineage_id()
                capture_quality = self._get_capture_quality_payload()
                snapshot_entries = [entry.clone() for entry in prepared_entries]
            except Exception as e:
                try:
                    self._auto_backup_lock.release()
                except Exception:
                    pass
                logger.error(f"백업 준비 오류: {e}")
                return False

            def write_backup():
                try:
                    write_started_at = time.perf_counter()
                    utils.atomic_write_json_stream(
                        backup_file,
                        head_items=[
                            ("version", Config.VERSION),
                            ("created", created_at),
                            ("url", source_url),
                            ("committee_name", committee_name),
                            ("lineage_id", lineage_id),
                            ("capture_quality", capture_quality),
                        ],
                        sequence_key="subtitles",
                        sequence_items=utils.iter_serialized_subtitles(snapshot_entries),
                        ensure_ascii=False,
                    )
                    self._record_recovery_snapshot(
                        backup_file,
                        "backup",
                        created_at=created_at,
                        url=source_url,
                        committee_name=committee_name,
                        lineage_id=lineage_id,
                    )
                    self._cleanup_old_backups()
                    logger.info(
                        "백업 스냅샷 저장 완료: %s (%s개, %.1fms)",
                        backup_file,
                        len(snapshot_entries),
                        (time.perf_counter() - write_started_at) * 1000.0,
                    )
                except Exception as e:
                    logger.error(f"백업 스냅샷 저장 오류: {e}")
                finally:
                    try:
                        self._auto_backup_lock.release()
                    except Exception:
                        pass

            started = self._start_background_thread(write_backup, worker_name)
            if not started:
                try:
                    self._auto_backup_lock.release()
                except Exception:
                    pass
                return False
            return True

    def _schedule_initial_recovery_snapshot_if_needed(
            self,
            prepared_entries: list[SubtitleEntry] | None = None,
        ) -> bool:
            if not bool(self.__dict__.get("is_running", False)):
                return False
            if bool(self.__dict__.get("_initial_recovery_snapshot_done", False)):
                return False

            entries = (
                prepared_entries
                if prepared_entries is not None
                else self._build_persistent_entries_snapshot()
            )
            if not entries:
                return False
            if self._is_runtime_tail_checkpoint_current():
                self._initial_recovery_snapshot_done = True
                return True

            started = self._start_backup_snapshot_write(
                entries,
                worker_name="InitialRecoverySnapshotWorker",
            )
            if started:
                self._initial_recovery_snapshot_done = True
            return started

    def _auto_backup(self):
            """자동 백업 실행"""
            prepared_entries = self._build_persistent_entries_snapshot()
            if not prepared_entries:
                return
            if not self._start_backup_snapshot_write(
                prepared_entries,
                worker_name="AutoBackupWorker",
            ):
                logger.info("자동 백업 시작 생략")

    def _cleanup_old_backups(self):
            """오래된 백업 파일 정리"""
            try:
                backup_dir = Path(Config.BACKUP_DIR)
                backups = sorted(backup_dir.glob("backup_*.json"), reverse=True)

                # 최대 개수 초과분 삭제 (race-safe: 개별 unlink 실패는 다음 항목에 영향 없음)
                for old_backup in backups[Config.MAX_BACKUP_COUNT :]:
                    try:
                        old_backup.unlink(missing_ok=True)
                        logger.debug(f"오래된 백업 삭제: {old_backup}")
                    except Exception as item_err:
                        logger.warning(
                            "백업 항목 삭제 실패 (%s): %s",
                            old_backup,
                            item_err,
                        )
            except Exception as e:
                logger.warning(f"백업 정리 중 오류: {e}")
