# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowPersistenceSessionMixin(MainWindowHost):

    def _record_recovery_snapshot(
            self,
            path: str | Path,
            snapshot_type: str,
            *,
            created_at: str,
            url: str = "",
            committee_name: str = "",
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

    def _prompt_session_recovery_if_available(self) -> None:
            if bool(self.__dict__.get("_startup_recovery_prompted", False)):
                return
            self._startup_recovery_prompted = True
            if self._session_load_in_progress or self.is_running:
                return

            recovery_state = self._load_recovery_state()
            if not recovery_state:
                return

            snapshot_path = str(recovery_state.get("path", "") or "")
            snapshot_type = str(recovery_state.get("snapshot_type", "") or "session")
            created_at = str(recovery_state.get("created_at", "") or "")
            if snapshot_type == "backup":
                description = "자동 백업"
            elif snapshot_type == "runtime_manifest":
                description = "런타임 세션 복구본"
            else:
                description = "세션 저장본"
            created_suffix = f"\n시각: {created_at}" if created_at else ""
            reply = QMessageBox.question(
                self,
                "세션 복구",
                "이전에 정상 종료되지 않은 것으로 보입니다.\n"
                f"최신 {description}을 복구하시겠습니까?\n"
                f"파일: {snapshot_path}{created_suffix}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._start_session_load_from_path(
                snapshot_path,
                mark_dirty=True,
                recovery=True,
            )

    def _write_session_snapshot(
            self,
            path: str,
            prepared_entries: list[SubtitleEntry],
            *,
            include_db: bool = True,
            runtime_root: Path | None = None,
            runtime_manifest: list[dict[str, Any]] | None = None,
        ) -> dict[str, Any]:
            """현재 세션 스냅샷을 JSON(+선택적 DB)으로 동기 저장한다."""
            current_url, committee_name, duration = self._build_session_save_context()
            created_at = datetime.now().isoformat()
            manifest_items = (
                runtime_manifest
                if runtime_manifest is not None
                else list(self.__dict__.get("_runtime_segment_manifest", []))
            )
            saved_count = sum(
                int(item.get("entry_count", 0) or 0)
                for item in manifest_items
            ) + len(prepared_entries)
            utils.atomic_write_json_stream(
                path,
                head_items=[
                    ("version", Config.VERSION),
                    ("created", created_at),
                    ("url", current_url),
                    ("committee_name", committee_name),
                ],
                sequence_key="subtitles",
                sequence_items=self._iter_full_session_serialized_items(
                    prepared_entries,
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
            )

            db_saved = False
            db_error = ""
            if include_db:
                db = self.db
                if db is not None:
                    try:
                        db_data = {
                            "url": current_url,
                            "committee_name": committee_name,
                            "prepared_entries": prepared_entries,
                            "runtime_root": runtime_root,
                            "runtime_manifest": [dict(item) for item in manifest_items],
                            "version": Config.VERSION,
                            "duration_seconds": duration,
                        }
                        self._run_db_task_sync(
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
                                }
                            ),
                            write_task=True,
                        )
                        db_saved = True
                    except Exception as db_exc:
                        db_error = str(db_exc)

            return {
                "path": path,
                "saved_count": saved_count,
                "db_saved": db_saved,
                "db_error": db_error,
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
            if not prepared_entries and not runtime_manifest:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return None

            filename = (
                f"{Config.SESSION_DIR}/세션_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
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
                self._clear_session_dirty()
                self._clear_recovery_state()
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

    def _confirm_dirty_session_action(self, action_name: str) -> bool:
            """dirty 세션이 있을 때 현재 작업을 보호하고 진행 여부를 반환한다."""
            if not self._has_dirty_session():
                return True

            prepared_entries = self._build_prepared_entries_snapshot()
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
                    return False
                if reply == QMessageBox.StandardButton.Save:
                    return (
                        self._prompt_write_session_snapshot(
                            prepared_entries,
                            dialog_title="세션 저장",
                        )
                        is not None
                    )
                return True

            reply = QMessageBox.question(
                self,
                f"{action_label} 확인",
                "저장되지 않은 변경이 있습니다.\n계속하시겠습니까?",
                QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            return reply != QMessageBox.StandardButton.Cancel

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
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = backup_dir / f"backup_{timestamp}.json"
                source_url, committee_name, _duration = self._build_session_save_context()
                created_at = datetime.now().isoformat()
                snapshot_entries = list(prepared_entries)
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
                else self._build_prepared_entries_snapshot()
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
            prepared_entries = self._build_prepared_entries_snapshot()
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

                # 최대 개수 초과분 삭제
                for old_backup in backups[Config.MAX_BACKUP_COUNT :]:
                    old_backup.unlink()
                    logger.debug(f"오래된 백업 삭제: {old_backup}")
            except Exception as e:
                logger.warning(f"백업 정리 중 오류: {e}")

    def _load_session(self):
            if self._is_runtime_mutation_blocked("세션 불러오기"):
                return
            if self._block_session_replacement_while_saving("세션 불러오기"):
                return
            if not self._confirm_dirty_session_action("세션 불러오기"):
                return

            path, _ = QFileDialog.getOpenFileName(
                self, "세션 불러오기", f"{Config.SESSION_DIR}/", "JSON (*.json)"
            )

            if not path:
                return
            self._start_session_load_from_path(path)

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
