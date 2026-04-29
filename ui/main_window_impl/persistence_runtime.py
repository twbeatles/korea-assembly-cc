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


class MainWindowPersistenceRuntimeMixin(MainWindowHost):

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

            prepared_entries = [entry.clone() for entry in self._build_prepared_entries_snapshot()]
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

    def _coerce_runtime_run_id(self, value: object) -> int | None:
            if value is None:
                return None
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    return None
                try:
                    return int(stripped)
                except ValueError:
                    return None
            try:
                return int(cast(Any, value))
            except Exception:
                return None

    def _build_session_save_context(self) -> tuple[str, str, int]:
            """세션/백업 저장에 사용할 메타데이터를 계산한다."""
            source_url = self._get_capture_source_url(fallback_to_current=True)
            committee_name = self._get_capture_source_committee(fallback_to_url=True)
            duration = int(time.time() - self.start_time) if self.start_time else 0
            return source_url, committee_name, duration

    def _has_runtime_archived_segments(self) -> bool:
            return bool(self.__dict__.get("_runtime_segment_manifest", [])) and int(
                self.__dict__.get("_runtime_archived_count", 0) or 0
            ) > 0

    def _is_runtime_archive_identity_current(
            self,
            run_id: object = None,
            archive_token: object = None,
        ) -> bool:
            expected_token = str(self.__dict__.get("_runtime_archive_token", "") or "")
            normalized_token = str(archive_token or "").strip()
            if not expected_token or not normalized_token or normalized_token != expected_token:
                return False
            current_run_id = self._coerce_runtime_run_id(
                self.__dict__.get("_runtime_archive_run_id")
            )
            candidate_run_id = self._coerce_runtime_run_id(run_id)
            if current_run_id is None or candidate_run_id is None:
                return False
            return current_run_id == candidate_run_id

    def _build_runtime_entries_fingerprint(
            self,
            entries: Iterable[SubtitleEntry],
        ) -> dict[str, Any]:
            entry_list = list(entries)
            digest = hashlib.sha256()
            for entry in entry_list:
                digest.update(
                    json.dumps(
                        entry.to_dict(),
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ).encode("utf-8")
                )
                digest.update(b"\n")
            first_entry = entry_list[0] if entry_list else None
            last_entry = entry_list[-1] if entry_list else None
            return {
                "entry_count": len(entry_list),
                "first_entry_id": str(first_entry.entry_id or "") if first_entry else "",
                "last_entry_id": str(last_entry.entry_id or "") if last_entry else "",
                "entries_digest": digest.hexdigest(),
            }

    def _payload_has_runtime_entries_fingerprint(
            self,
            payload: dict[str, Any],
        ) -> bool:
            return bool(
                payload.get("entries_digest")
                or payload.get("first_entry_id")
                or payload.get("last_entry_id")
            )

    def _runtime_entries_fingerprint_matches(
            self,
            entries: Iterable[SubtitleEntry],
            expected: dict[str, Any],
        ) -> bool:
            if not self._payload_has_runtime_entries_fingerprint(expected):
                return True
            current = self._build_runtime_entries_fingerprint(entries)
            return (
                int(current["entry_count"]) == int(expected.get("entry_count", 0) or 0)
                and current["first_entry_id"] == str(expected.get("first_entry_id") or "")
                and current["last_entry_id"] == str(expected.get("last_entry_id") or "")
                and current["entries_digest"] == str(expected.get("entries_digest") or "")
            )

    def _build_runtime_archive_snapshot(self) -> dict[str, Any] | None:
            runtime_root = self.__dict__.get("_runtime_session_root")
            manifest_path = self.__dict__.get("_runtime_manifest_path")
            if runtime_root is None or manifest_path is None:
                return None
            current_url, committee_name, _duration = self._build_session_save_context()
            lineage_id = self._ensure_session_lineage_id()
            return {
                "runtime_root": Path(runtime_root),
                "manifest_path": Path(manifest_path),
                "tail_checkpoint_name": "tail_checkpoint.json",
                "manifest_items": [
                    dict(item)
                    for item in list(self.__dict__.get("_runtime_segment_manifest", []))
                ],
                "archived_count": int(self.__dict__.get("_runtime_archived_count", 0) or 0),
                "archived_chars": int(self.__dict__.get("_runtime_archived_chars", 0) or 0),
                "archived_words": int(self.__dict__.get("_runtime_archived_words", 0) or 0),
                "tail_revision": int(self.__dict__.get("_runtime_tail_revision", 0) or 0),
                "archive_token": str(self.__dict__.get("_runtime_archive_token", "") or ""),
                "run_id": self.__dict__.get("_runtime_archive_run_id"),
                "url": current_url,
                "committee_name": committee_name,
                "lineage_id": lineage_id,
            }

    def _serialize_runtime_manifest_payload(
            self,
            *,
            current_url: str,
            committee_name: str,
            archived_count: int,
            archived_chars: int,
            archived_words: int,
            manifest_items: list[dict[str, Any]],
            tail_checkpoint_name: str = "tail_checkpoint.json",
            archive_token: str = "",
            run_id: int | None = None,
            lineage_id: str = "",
        ) -> dict[str, Any]:
            payload = {
                "format": "runtime_session_manifest_v1",
                "version": Config.VERSION,
                "created": datetime.now().isoformat(),
                "url": current_url,
                "committee_name": committee_name,
                "lineage_id": str(lineage_id or ""),
                "archived_count": int(archived_count),
                "archived_chars": int(archived_chars),
                "archived_words": int(archived_words),
                "tail_checkpoint": str(tail_checkpoint_name or "tail_checkpoint.json"),
                "segments": [dict(item) for item in manifest_items],
            }
            if archive_token:
                payload["archive_token"] = archive_token
            if run_id is not None:
                payload["run_id"] = int(run_id)
            return payload

    def _write_runtime_manifest_to_path(
            self,
            manifest_path: Path,
            *,
            current_url: str,
            committee_name: str,
            archived_count: int,
            archived_chars: int,
            archived_words: int,
            manifest_items: list[dict[str, Any]],
            tail_checkpoint_name: str = "tail_checkpoint.json",
            archive_token: str = "",
            run_id: int | None = None,
            lineage_id: str = "",
        ) -> None:
            utils.atomic_write_json(
                manifest_path,
                self._serialize_runtime_manifest_payload(
                    current_url=current_url,
                    committee_name=committee_name,
                    archived_count=archived_count,
                    archived_chars=archived_chars,
                    archived_words=archived_words,
                    manifest_items=manifest_items,
                    tail_checkpoint_name=tail_checkpoint_name,
                    archive_token=archive_token,
                    run_id=run_id,
                    lineage_id=lineage_id,
                ),
                ensure_ascii=False,
            )

    def _write_runtime_tail_checkpoint_to_path(
            self,
            checkpoint_path: Path,
            entries: list[SubtitleEntry],
            *,
            current_url: str,
            committee_name: str,
            archived_count: int,
            archived_chars: int,
            archived_words: int,
            archive_token: str = "",
            run_id: int | None = None,
            lineage_id: str = "",
        ) -> None:
            head_items: list[tuple[str, object]] = [
                ("format", "runtime_tail_checkpoint_v1"),
                ("version", Config.VERSION),
                ("created", datetime.now().isoformat()),
                ("url", current_url),
                ("committee_name", committee_name),
                ("lineage_id", str(lineage_id or "")),
                ("archived_count", int(archived_count)),
                ("archived_chars", int(archived_chars)),
                ("archived_words", int(archived_words)),
            ]
            if archive_token:
                head_items.append(("archive_token", archive_token))
            if run_id is not None:
                head_items.append(("run_id", int(run_id)))
            utils.atomic_write_json_stream(
                checkpoint_path,
                head_items=head_items,
                sequence_key="subtitles",
                sequence_items=utils.iter_serialized_subtitles(entries),
                ensure_ascii=False,
            )

    def _invalidate_runtime_segment_caches(self) -> None:
            self._runtime_segment_cache_key = ""
            self._runtime_segment_cache_entries = []
            self._runtime_segment_cache_keys = []
            self._runtime_segment_cache_entries_by_key = {}
            self._runtime_segment_search_text_cache = {}
            self._runtime_segment_locator_starts = []
            self._runtime_segment_locator_ends = []
            self._runtime_segment_locator_items = []
            self._runtime_render_window_cache_key = None
            self._runtime_render_window_cache_entries = []

    def _mark_runtime_tail_dirty(self) -> None:
            self._runtime_tail_revision = int(
                self.__dict__.get("_runtime_tail_revision", 0) or 0
            ) + 1
            self._runtime_render_window_cache_key = None
            self._runtime_render_window_cache_entries = []

    def _rebuild_runtime_segment_locator(self) -> None:
            manifest = list(self.__dict__.get("_runtime_segment_manifest", []))
            manifest.sort(key=lambda item: int(item.get("start_index", 0) or 0))
            starts: list[int] = []
            ends: list[int] = []
            normalized_items: list[dict[str, Any]] = []
            for item in manifest:
                start_index = int(item.get("start_index", 0) or 0)
                entry_count = int(item.get("entry_count", 0) or 0)
                end_index = int(item.get("end_index", start_index + entry_count) or (start_index + entry_count))
                normalized = dict(item)
                normalized["start_index"] = start_index
                normalized["entry_count"] = entry_count
                normalized["end_index"] = end_index
                starts.append(start_index)
                ends.append(end_index)
                normalized_items.append(normalized)
            self._runtime_segment_manifest = normalized_items
            self._runtime_segment_locator_starts = starts
            self._runtime_segment_locator_ends = ends
            self._runtime_segment_locator_items = normalized_items
            self._runtime_render_window_cache_key = None
            self._runtime_render_window_cache_entries = []

    def _iter_runtime_segments_for_window(
            self,
            start_index: int,
            end_index: int,
        ):
            starts = list(self.__dict__.get("_runtime_segment_locator_starts", []))
            items = list(self.__dict__.get("_runtime_segment_locator_items", []))
            if not starts or not items:
                self._rebuild_runtime_segment_locator()
                starts = list(self.__dict__.get("_runtime_segment_locator_starts", []))
                items = list(self.__dict__.get("_runtime_segment_locator_items", []))
            if not starts or not items:
                return

            start = max(0, int(start_index))
            end = max(start, int(end_index))
            pos = max(0, bisect.bisect_right(starts, start) - 1)
            while pos < len(items):
                item = items[pos]
                seg_start = int(item.get("start_index", 0) or 0)
                seg_end = int(item.get("end_index", seg_start + int(item.get("entry_count", 0) or 0)) or 0)
                if seg_end <= start:
                    pos += 1
                    continue
                if seg_start >= end:
                    break
                yield item
                pos += 1

    def _reset_runtime_session_archive_state(self, *, keep_root: bool = False) -> None:
            self._runtime_segment_manifest = []
            self._runtime_next_segment_index = 1
            self._runtime_archived_count = 0
            self._runtime_archived_chars = 0
            self._runtime_archived_words = 0
            self._runtime_archive_token = ""
            self._runtime_archive_run_id = None
            self._runtime_segment_flush_in_progress = False
            self._invalidate_runtime_segment_caches()
            self._cancel_runtime_search()
            self._runtime_search_revision = int(
                self.__dict__.get("_runtime_search_revision", 0) or 0
            ) + 1
            self._runtime_search_query = ""
            self._runtime_search_truncated = False
            self._runtime_search_in_progress = False
            self._runtime_tail_revision = 0
            self._runtime_tail_checkpoint_revision = -1
            if not keep_root:
                self._runtime_session_root = None
                self._runtime_manifest_path = None

    def _cleanup_runtime_session_archive(self, *, remove_files: bool = True) -> None:
            runtime_root = self.__dict__.get("_runtime_session_root")
            self._reset_runtime_session_archive_state(keep_root=False)
            if remove_files and runtime_root is not None:
                try:
                    shutil.rmtree(runtime_root, ignore_errors=True)
                except Exception:
                    logger.debug("runtime session archive 정리 실패: %s", runtime_root, exc_info=True)

    def _cleanup_orphan_runtime_archives(
            self,
            *,
            extra_preserved_dirs: Iterable[Path] | None = None,
        ) -> None:
            runtime_root = Path(Config.RUNTIME_SESSION_DIR)
            runtime_root.mkdir(parents=True, exist_ok=True)
            recovery_state = None
            try:
                recovery_state = self._load_recovery_state()
            except Exception:
                recovery_state = None

            preserved_dirs: set[Path] = set()
            if self._runtime_session_root is not None:
                preserved_dirs.add(self._runtime_session_root.resolve())
            for extra_dir in list(extra_preserved_dirs or []):
                try:
                    preserved_dirs.add(Path(extra_dir).resolve())
                except Exception:
                    continue
            if isinstance(recovery_state, dict):
                recovery_path = Path(str(recovery_state.get("path", "") or "")).resolve()
                for parent in [recovery_path, recovery_path.parent]:
                    try:
                        if parent.is_relative_to(runtime_root.resolve()):
                            if parent.is_dir():
                                preserved_dirs.add(parent)
                            elif parent.parent.is_dir():
                                preserved_dirs.add(parent.parent)
                    except Exception:
                        continue

            children = [child for child in runtime_root.iterdir() if child.is_dir()]
            children.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            keep_dirs = set(children[:3]) | preserved_dirs
            for child in children:
                if child in keep_dirs:
                    continue
                try:
                    shutil.rmtree(child, ignore_errors=True)
                except Exception:
                    logger.debug("orphan runtime archive 정리 실패: %s", child, exc_info=True)

    def _start_runtime_session_archive(self, run_id: int | None = None) -> None:
            previous_root = self.__dict__.get("_runtime_session_root")
            self._cleanup_runtime_session_archive(remove_files=False)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = f"{int(run_id)}" if run_id is not None else "manual"
            runtime_root = Path(Config.RUNTIME_SESSION_DIR) / f"run_{timestamp}_{suffix}"
            runtime_root.mkdir(parents=True, exist_ok=True)
            self._runtime_session_root = runtime_root
            self._runtime_manifest_path = runtime_root / "manifest.json"
            self._reset_runtime_session_archive_state(keep_root=True)
            self._runtime_archive_run_id = int(run_id) if run_id is not None else None
            self._runtime_archive_token = uuid4().hex
            self._write_runtime_manifest()
            preserved_dirs: set[Path] = set()
            if previous_root is not None:
                try:
                    preserved_dirs.add(Path(previous_root).resolve())
                except Exception:
                    pass
            self._cleanup_orphan_runtime_archives(extra_preserved_dirs=preserved_dirs)

    def _runtime_tail_checkpoint_path(self) -> Path | None:
            runtime_root = self.__dict__.get("_runtime_session_root")
            if runtime_root is None:
                return None
            return runtime_root / "tail_checkpoint.json"

    def _is_runtime_tail_checkpoint_current(self) -> bool:
            checkpoint_path = self._runtime_tail_checkpoint_path()
            if checkpoint_path is None or not checkpoint_path.exists():
                return False
            return int(self.__dict__.get("_runtime_tail_checkpoint_revision", -1) or -1) == int(
                self.__dict__.get("_runtime_tail_revision", 0) or 0
            )

    def _serialize_runtime_manifest(self) -> dict[str, Any]:
            current_url, committee_name, _duration = self._build_session_save_context()
            return self._serialize_runtime_manifest_payload(
                current_url=current_url,
                committee_name=committee_name,
                lineage_id=self._ensure_session_lineage_id(),
                archived_count=int(self._runtime_archived_count),
                archived_chars=int(self._runtime_archived_chars),
                archived_words=int(self._runtime_archived_words),
                manifest_items=[dict(item) for item in self._runtime_segment_manifest],
                tail_checkpoint_name="tail_checkpoint.json",
                archive_token=str(self.__dict__.get("_runtime_archive_token", "") or ""),
                run_id=self.__dict__.get("_runtime_archive_run_id"),
            )

    def _write_runtime_manifest(self) -> None:
            manifest_path = self._runtime_manifest_path
            if manifest_path is None:
                return
            current_url, committee_name, _duration = self._build_session_save_context()
            self._write_runtime_manifest_to_path(
                Path(manifest_path),
                current_url=current_url,
                committee_name=committee_name,
                archived_count=int(self._runtime_archived_count),
                archived_chars=int(self._runtime_archived_chars),
                archived_words=int(self._runtime_archived_words),
                manifest_items=[dict(item) for item in self._runtime_segment_manifest],
                tail_checkpoint_name="tail_checkpoint.json",
                archive_token=str(self.__dict__.get("_runtime_archive_token", "") or ""),
                run_id=self.__dict__.get("_runtime_archive_run_id"),
                lineage_id=self._ensure_session_lineage_id(),
            )

    def _write_runtime_tail_checkpoint(
            self,
            prepared_entries: list[SubtitleEntry] | None = None,
        ) -> Path | None:
            checkpoint_path = self._runtime_tail_checkpoint_path()
            if checkpoint_path is None:
                return None
            tail_revision = int(self.__dict__.get("_runtime_tail_revision", 0) or 0)
            current_url, committee_name, _duration = self._build_session_save_context()
            entries = prepared_entries if prepared_entries is not None else list(self.subtitles)
            self._write_runtime_tail_checkpoint_to_path(
                Path(checkpoint_path),
                list(entries),
                current_url=current_url,
                committee_name=committee_name,
                archived_count=int(self.__dict__.get("_runtime_archived_count", 0) or 0),
                archived_chars=int(self.__dict__.get("_runtime_archived_chars", 0) or 0),
                archived_words=int(self.__dict__.get("_runtime_archived_words", 0) or 0),
                archive_token=str(self.__dict__.get("_runtime_archive_token", "") or ""),
                run_id=self.__dict__.get("_runtime_archive_run_id"),
                lineage_id=self._ensure_session_lineage_id(),
            )
            self._runtime_tail_checkpoint_revision = tail_revision
            return checkpoint_path

    def _record_runtime_recovery_snapshot_from_context(
            self,
            prepared_entries: list[SubtitleEntry],
            *,
            context: dict[str, Any],
        ) -> bool:
            runtime_root = context.get("runtime_root")
            manifest_path = context.get("manifest_path")
            archive_token = str(context.get("archive_token", "") or "")
            run_id = context.get("run_id")
            if runtime_root is None or manifest_path is None:
                return False
            if archive_token and not self._is_runtime_archive_identity_current(run_id, archive_token):
                return False

            captured_archived_count = int(context.get("archived_count", 0) or 0)
            captured_tail_revision = int(context.get("tail_revision", 0) or 0)
            captured_manifest_items = [
                dict(item)
                for item in list(context.get("manifest_items", []))
                if isinstance(item, dict)
            ]
            current_archived_count = int(self.__dict__.get("_runtime_archived_count", 0) or 0)
            current_tail_revision = int(self.__dict__.get("_runtime_tail_revision", 0) or 0)
            if archive_token and (
                current_archived_count != captured_archived_count
                or current_tail_revision != captured_tail_revision
            ):
                return False

            runtime_root_path = Path(runtime_root)
            manifest_file_path = Path(manifest_path)
            checkpoint_path = runtime_root_path / str(
                context.get("tail_checkpoint_name", "tail_checkpoint.json")
                or "tail_checkpoint.json"
            )
            current_url = str(context.get("url", "") or "")
            committee_name = str(context.get("committee_name", "") or "")
            lineage_id = str(context.get("lineage_id", "") or "").strip()
            self._write_runtime_tail_checkpoint_to_path(
                checkpoint_path,
                list(prepared_entries),
                current_url=current_url,
                committee_name=committee_name,
                archived_count=captured_archived_count,
                archived_chars=int(context.get("archived_chars", 0) or 0),
                archived_words=int(context.get("archived_words", 0) or 0),
                archive_token=archive_token,
                run_id=(int(run_id) if run_id is not None else None),
                lineage_id=lineage_id,
            )
            self._write_runtime_manifest_to_path(
                manifest_file_path,
                current_url=current_url,
                committee_name=committee_name,
                archived_count=captured_archived_count,
                archived_chars=int(context.get("archived_chars", 0) or 0),
                archived_words=int(context.get("archived_words", 0) or 0),
                manifest_items=captured_manifest_items,
                tail_checkpoint_name=str(
                    context.get("tail_checkpoint_name", "tail_checkpoint.json")
                    or "tail_checkpoint.json"
                ),
                archive_token=archive_token,
                run_id=(int(run_id) if run_id is not None else None),
                lineage_id=lineage_id,
            )

            if archive_token and not self._is_runtime_archive_identity_current(run_id, archive_token):
                return False
            if archive_token and (
                int(self.__dict__.get("_runtime_archived_count", 0) or 0) != captured_archived_count
                or int(self.__dict__.get("_runtime_tail_revision", 0) or 0) != captured_tail_revision
            ):
                self._write_runtime_manifest()
                self._write_runtime_tail_checkpoint(list(self.subtitles))
                return False

            self._runtime_tail_checkpoint_revision = captured_tail_revision
            self._record_recovery_snapshot(
                manifest_file_path,
                "runtime_manifest",
                created_at=datetime.now().isoformat(),
                url=current_url,
                committee_name=committee_name,
                lineage_id=lineage_id,
            )
            return True

    def _record_runtime_recovery_snapshot(
            self,
            prepared_entries: list[SubtitleEntry] | None = None,
        ) -> bool:
            archive_context = self._build_runtime_archive_snapshot()
            if archive_context is None:
                return False
            entries = (
                list(prepared_entries)
                if prepared_entries is not None
                else list(self.subtitles)
            )
            return self._record_runtime_recovery_snapshot_from_context(
                entries,
                context=archive_context,
            )

    def _maybe_schedule_runtime_segment_flush(self) -> bool:
            if not bool(self.__dict__.get("is_running", False)):
                return False
            if self._runtime_session_root is None or self._runtime_manifest_path is None:
                return False
            if bool(self.__dict__.get("_runtime_segment_flush_in_progress", False)):
                return False
            if self._is_background_shutdown_active():
                return False

            threshold = max(
                int(Config.RUNTIME_ACTIVE_TAIL_ENTRIES),
                int(Config.RUNTIME_SEGMENT_FLUSH_THRESHOLD),
            )
            tail_keep = max(1, int(Config.RUNTIME_ACTIVE_TAIL_ENTRIES))
            with self.subtitle_lock:
                active_count = len(self.subtitles)
                if active_count <= threshold or active_count <= tail_keep:
                    return False
                flush_count = active_count - tail_keep
                flush_entries = [entry.clone() for entry in self.subtitles[:flush_count]]

            if not flush_entries:
                return False

            flush_fingerprint = self._build_runtime_entries_fingerprint(flush_entries)
            self._runtime_segment_flush_in_progress = True
            segment_index = int(self._runtime_next_segment_index)
            segment_path = self._runtime_session_root / f"segment_{segment_index:06d}.json"
            relative_path = segment_path.name
            start_index = int(self._runtime_archived_count)
            char_count = sum(entry.char_count for entry in flush_entries)
            word_count = sum(entry.word_count for entry in flush_entries)
            current_url, committee_name, _duration = self._build_session_save_context()
            created_at = datetime.now().isoformat()
            archive_token = str(self.__dict__.get("_runtime_archive_token", "") or "")
            run_id = self.__dict__.get("_runtime_archive_run_id")

            def write_segment() -> None:
                try:
                    head_items: list[tuple[str, object]] = [
                        ("format", "runtime_session_segment_v1"),
                        ("version", Config.VERSION),
                        ("created", created_at),
                        ("url", current_url),
                        ("committee_name", committee_name),
                        ("lineage_id", self._ensure_session_lineage_id()),
                        ("segment_index", segment_index),
                        ("start_index", start_index),
                        ("entry_count", flush_count),
                        ("first_entry_id", flush_fingerprint["first_entry_id"]),
                        ("last_entry_id", flush_fingerprint["last_entry_id"]),
                        ("entries_digest", flush_fingerprint["entries_digest"]),
                    ]
                    if archive_token:
                        head_items.append(("archive_token", archive_token))
                    if run_id is not None:
                        head_items.append(("run_id", int(run_id)))
                    utils.atomic_write_json_stream(
                        segment_path,
                        head_items=head_items,
                        sequence_key="subtitles",
                        sequence_items=utils.iter_serialized_subtitles(flush_entries),
                        ensure_ascii=False,
                    )
                    self._emit_control_message(
                        "runtime_segment_flush_done",
                        {
                            "run_id": run_id,
                            "archive_token": archive_token,
                            "segment_index": segment_index,
                            "path": relative_path,
                            "entry_count": flush_count,
                            "char_count": char_count,
                            "word_count": word_count,
                            "start_index": start_index,
                            "first_entry_id": flush_fingerprint["first_entry_id"],
                            "last_entry_id": flush_fingerprint["last_entry_id"],
                            "entries_digest": flush_fingerprint["entries_digest"],
                        },
                    )
                except Exception as e:
                    logger.error("runtime segment flush 실패: %s", e)
                    self._emit_control_message(
                        "runtime_segment_flush_failed",
                        {
                            "run_id": run_id,
                            "archive_token": archive_token,
                            "path": relative_path,
                            "error": str(e),
                        },
                    )

            started = self._start_background_thread(
                write_segment,
                f"RuntimeSegmentFlush-{segment_index:06d}",
            )
            if started:
                return True
            self._runtime_segment_flush_in_progress = False
            return False

    def _handle_runtime_segment_flush_done(self, payload: dict[str, Any]) -> None:
            payload_token = str(payload.get("archive_token", "") or "")
            payload_run_id = payload.get("run_id")
            if payload_token and not self._is_runtime_archive_identity_current(
                payload_run_id,
                payload_token,
            ):
                logger.info(
                    "stale runtime segment flush 무시: run_id=%s token=%s",
                    payload_run_id,
                    payload_token,
                )
                return
            flush_count = int(payload.get("entry_count", 0) or 0)
            char_count = int(payload.get("char_count", 0) or 0)
            word_count = int(payload.get("word_count", 0) or 0)
            segment_index = int(payload.get("segment_index", 0) or 0)
            relative_path = str(payload.get("path", "") or "").strip()
            start_index = int(payload.get("start_index", self._runtime_archived_count) or self._runtime_archived_count)
            self._runtime_segment_flush_in_progress = False
            if flush_count <= 0 or not relative_path:
                return

            fingerprint_mismatch = False
            with self.subtitle_lock:
                removable = min(flush_count, len(self.subtitles))
                current_prefix = list(self.subtitles[:removable])
                fingerprint_mismatch = removable != flush_count or not self._runtime_entries_fingerprint_matches(
                    current_prefix,
                    payload,
                )
                if fingerprint_mismatch:
                    removable = 0
                if removable > 0:
                    del self.subtitles[:removable]

            if fingerprint_mismatch:
                logger.warning(
                    "stale runtime segment flush fingerprint 불일치: segment=%s path=%s",
                    segment_index,
                    relative_path,
                )
                self._maybe_schedule_runtime_segment_flush()
                return

            self._cached_total_chars = max(0, int(self._cached_total_chars) - char_count)
            self._cached_total_words = max(0, int(self._cached_total_words) - word_count)
            self._runtime_archived_count += flush_count
            self._runtime_archived_chars += char_count
            self._runtime_archived_words += word_count
            self._runtime_segment_manifest.append(
                {
                    "segment_index": segment_index,
                    "path": relative_path,
                    "entry_count": flush_count,
                    "char_count": char_count,
                    "word_count": word_count,
                    "start_index": start_index,
                    "end_index": start_index + flush_count,
                    "first_entry_id": str(payload.get("first_entry_id") or ""),
                    "last_entry_id": str(payload.get("last_entry_id") or ""),
                    "entries_digest": str(payload.get("entries_digest") or ""),
                }
            )
            self._rebuild_runtime_segment_locator()
            self._runtime_next_segment_index = max(
                int(self._runtime_next_segment_index),
                segment_index + 1,
            )
            self._write_runtime_manifest()
            self._write_runtime_tail_checkpoint(list(self.subtitles))
            self._schedule_ui_refresh(count=True, render=True, force_full=True)
            self._maybe_schedule_runtime_segment_flush()

    def _handle_runtime_segment_flush_failed(self, payload: dict[str, Any]) -> None:
            payload_token = str(payload.get("archive_token", "") or "")
            payload_run_id = payload.get("run_id")
            if payload_token and not self._is_runtime_archive_identity_current(
                payload_run_id,
                payload_token,
            ):
                logger.info(
                    "stale runtime segment flush 실패 메시지 무시: run_id=%s token=%s",
                    payload_run_id,
                    payload_token,
                )
                return
            self._runtime_segment_flush_in_progress = False
            err = str(payload.get("error", "") or "알 수 없는 오류")
            logger.warning("runtime segment flush 실패: %s", err)
            self._show_toast(f"장시간 세션 세그먼트 저장 실패: {err}", "warning", 4000)

    def _start_runtime_recovery_snapshot_write(
            self,
            prepared_entries: list[SubtitleEntry],
            *,
            worker_name: str = "RuntimeRecoverySnapshotWorker",
        ) -> bool:
            if not prepared_entries or self._is_background_shutdown_active():
                return False
            if (
                self.__dict__.get("_runtime_session_root") is None
                or self.__dict__.get("_runtime_manifest_path") is None
            ):
                return False
            if self._is_runtime_tail_checkpoint_current():
                return False
            if not self._auto_backup_lock.acquire(blocking=False):
                return False

            snapshot_entries = list(prepared_entries)
            archive_context = self._build_runtime_archive_snapshot()
            if archive_context is None:
                try:
                    self._auto_backup_lock.release()
                except Exception:
                    pass
                return False

            def write_snapshot() -> None:
                try:
                    self._record_runtime_recovery_snapshot_from_context(
                        snapshot_entries,
                        context=archive_context,
                    )
                except Exception as e:
                    logger.error("runtime recovery snapshot 저장 오류: %s", e)
                finally:
                    try:
                        self._auto_backup_lock.release()
                    except Exception:
                        pass

            started = self._start_background_thread(write_snapshot, worker_name)
            if started:
                return True
            try:
                self._auto_backup_lock.release()
            except Exception:
                pass
            return False

    def _load_segment_file_entries(
            self,
            path: str | Path,
            *,
            source: str = "",
        ) -> list[SubtitleEntry]:
            segment_path = Path(path)
            cache_key = str(segment_path.resolve())
            cache_map = self.__dict__.get("_runtime_segment_cache_entries_by_key", {})
            if isinstance(cache_map, dict) and cache_key in cache_map:
                entries = cache_map[cache_key]
                cache_keys = list(self.__dict__.get("_runtime_segment_cache_keys", []))
                if cache_key in cache_keys:
                    cache_keys = [key for key in cache_keys if key != cache_key]
                cache_keys.append(cache_key)
                self._runtime_segment_cache_keys = cache_keys
                self._runtime_segment_cache_key = cache_key
                self._runtime_segment_cache_entries = entries
                return entries

            _data, entries, _skipped = self._read_runtime_entries_file(
                segment_path,
                source=source or cache_key,
            )
            self._cache_runtime_segment_entries(cache_key, entries)
            return entries

    def _cache_runtime_segment_entries(
            self,
            cache_key: str,
            entries: list[SubtitleEntry],
        ) -> None:
            cache_map = dict(self.__dict__.get("_runtime_segment_cache_entries_by_key", {}))
            cache_keys = [
                key
                for key in list(self.__dict__.get("_runtime_segment_cache_keys", []))
                if key != cache_key
            ]
            cache_map[cache_key] = entries
            cache_keys.append(cache_key)
            while len(cache_keys) > 3:
                evicted_key = cache_keys.pop(0)
                cache_map.pop(evicted_key, None)
                search_cache = dict(self.__dict__.get("_runtime_segment_search_text_cache", {}))
                if evicted_key in search_cache:
                    search_cache.pop(evicted_key, None)
                    self._runtime_segment_search_text_cache = search_cache
            self._runtime_segment_cache_keys = cache_keys
            self._runtime_segment_cache_entries_by_key = cache_map
            self._runtime_segment_cache_key = cache_key
            self._runtime_segment_cache_entries = entries

    def _read_runtime_entries_file(
            self,
            path: str | Path,
            *,
            source: str = "",
        ) -> tuple[dict[str, Any], list[SubtitleEntry], int]:
            file_path = Path(path)
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"지원하지 않는 JSON 구조: {file_path.name}")
            entries, skipped = self._deserialize_subtitles(
                data.get("subtitles", []),
                source=source or str(file_path),
            )
            return data, entries, skipped

    def _try_load_runtime_entries_file(
            self,
            path: str | Path,
            *,
            source: str = "",
            cache_result: bool = False,
        ) -> tuple[dict[str, Any] | None, list[SubtitleEntry], int, str | None]:
            file_path = Path(path)
            try:
                data, entries, skipped = self._read_runtime_entries_file(
                    file_path,
                    source=source or str(file_path),
                )
            except Exception as exc:
                return None, [], 0, f"{file_path.name} 로드 실패: {exc}"
            if cache_result:
                try:
                    self._cache_runtime_segment_entries(str(file_path.resolve()), entries)
                except Exception:
                    logger.debug("runtime segment cache 반영 실패: %s", file_path, exc_info=True)
            return data, entries, skipped, None

    def _build_salvaged_runtime_segments(self, runtime_root: Path) -> list[dict[str, Any]]:
            segment_paths = sorted(runtime_root.glob("segment_*.json"))
            return [
                {"path": segment_path.name}
                for segment_path in segment_paths
                if segment_path.is_file()
            ]

    def _resolve_runtime_relative_path(
            self,
            runtime_root: Path,
            relative_path: object,
            *,
            source: str,
        ) -> tuple[Path, str]:
            raw_path = str(relative_path or "").strip()
            if not raw_path:
                raise ValueError(f"{source} path가 비어 있습니다.")
            candidate = Path(raw_path)
            if candidate.is_absolute() or candidate.drive:
                raise ValueError(f"{source} path가 runtime root 밖을 가리킵니다: {raw_path}")
            runtime_root_resolved = runtime_root.resolve()
            resolved_path = (runtime_root / candidate).resolve()
            try:
                resolved_path.relative_to(runtime_root_resolved)
            except ValueError as exc:
                raise ValueError(
                    f"{source} path가 runtime root 밖을 가리킵니다: {raw_path}"
                ) from exc
            return resolved_path, raw_path

    def _load_runtime_segment_entries(
            self,
            segment_info: dict[str, Any],
            *,
            runtime_root: Path | None = None,
        ) -> list[SubtitleEntry]:
            runtime_root = (
                runtime_root
                if runtime_root is not None
                else self.__dict__.get("_runtime_session_root")
            )
            if runtime_root is None:
                return []
            relative_path = str(segment_info.get("path", "") or "").strip()
            if not relative_path:
                return []
            try:
                segment_path, relative_path = self._resolve_runtime_relative_path(
                    Path(runtime_root),
                    relative_path,
                    source="runtime segment",
                )
            except ValueError:
                logger.warning("runtime segment path 거부: %s", relative_path)
                return []
            if not segment_path.exists():
                return []
            return self._load_segment_file_entries(
                segment_path,
                source=f"runtime_segment:{relative_path}",
            )

    def _get_runtime_segment_search_texts(
            self,
            segment_info: dict[str, Any],
        ) -> list[str]:
            runtime_root = self.__dict__.get("_runtime_session_root")
            if runtime_root is None:
                return []
            relative_path = str(segment_info.get("path", "") or "").strip()
            if not relative_path:
                return []
            try:
                segment_path, _relative_path = self._resolve_runtime_relative_path(
                    Path(runtime_root),
                    relative_path,
                    source="runtime segment",
                )
            except ValueError:
                logger.warning("runtime segment search path 거부: %s", relative_path)
                return []
            cache_key = str(segment_path.resolve())
            search_cache = dict(self.__dict__.get("_runtime_segment_search_text_cache", {}))
            if cache_key in search_cache:
                return search_cache[cache_key]
            texts = [
                self._normalize_subtitle_text_for_option(entry.text).lower()
                for entry in self._load_runtime_segment_entries(segment_info)
            ]
            search_cache[cache_key] = texts
            self._runtime_segment_search_text_cache = search_cache
            return texts

    def _snapshot_runtime_stream_context(
            self,
        ) -> tuple[Path | None, list[dict[str, Any]]]:
            runtime_root = self.__dict__.get("_runtime_session_root")
            runtime_manifest = [
                dict(item)
                for item in list(self.__dict__.get("_runtime_segment_manifest", []))
            ]
            return runtime_root, runtime_manifest

    def _iter_full_session_entries(
            self,
            prepared_entries: list[SubtitleEntry] | None = None,
            *,
            runtime_root: Path | None = None,
            runtime_manifest: list[dict[str, Any]] | None = None,
        ):
            manifest_items = (
                runtime_manifest
                if runtime_manifest is not None
                else list(self.__dict__.get("_runtime_segment_manifest", []))
            )
            for segment_info in list(manifest_items):
                for entry in self._load_runtime_segment_entries(
                    segment_info,
                    runtime_root=runtime_root,
                ):
                    yield entry
            tail_entries = (
                prepared_entries
                if prepared_entries is not None
                else list(getattr(self, "subtitles", []))
            )
            for entry in tail_entries:
                yield entry

    def _iter_full_session_serialized_items(
            self,
            prepared_entries: list[SubtitleEntry] | None = None,
            *,
            runtime_root: Path | None = None,
            runtime_manifest: list[dict[str, Any]] | None = None,
        ):
            for entry in self._iter_full_session_entries(
                prepared_entries,
                runtime_root=runtime_root,
                runtime_manifest=runtime_manifest,
            ):
                yield entry.to_dict()

    def _iter_full_session_text_rows(
            self,
            prepared_entries: list[SubtitleEntry] | None = None,
            *,
            runtime_root: Path | None = None,
            runtime_manifest: list[dict[str, Any]] | None = None,
        ):
            for entry in self._iter_full_session_entries(
                prepared_entries,
                runtime_root=runtime_root,
                runtime_manifest=runtime_manifest,
            ):
                yield entry.timestamp, entry.text

    def _iter_full_session_timed_rows(
            self,
            prepared_entries: list[SubtitleEntry] | None = None,
            *,
            runtime_root: Path | None = None,
            runtime_manifest: list[dict[str, Any]] | None = None,
        ):
            for entry in self._iter_full_session_entries(
                prepared_entries,
                runtime_root=runtime_root,
                runtime_manifest=runtime_manifest,
            ):
                yield entry.start_time, entry.end_time, entry.timestamp, entry.text

    def _iter_display_session_rows(
            self,
            prepared_entries: list[SubtitleEntry] | None = None,
            *,
            runtime_root: Path | None = None,
            runtime_manifest: list[dict[str, Any]] | None = None,
        ):
            last_printed_ts = None
            for timestamp, text in self._iter_full_session_text_rows(
                prepared_entries,
                runtime_root=runtime_root,
                runtime_manifest=runtime_manifest,
            ):
                should_print_ts = False
                if last_printed_ts is None:
                    should_print_ts = True
                elif (timestamp - last_printed_ts).total_seconds() >= 60:
                    should_print_ts = True
                if should_print_ts:
                    last_printed_ts = timestamp
                yield timestamp, text, should_print_ts

    def _build_complete_session_entries_snapshot(
            self,
            prepared_entries: list[SubtitleEntry] | None = None,
            *,
            runtime_root: Path | None = None,
            runtime_manifest: list[dict[str, Any]] | None = None,
        ) -> list[SubtitleEntry]:
            return [
                entry.clone()
                for entry in self._iter_full_session_entries(
                    prepared_entries,
                    runtime_root=runtime_root,
                    runtime_manifest=runtime_manifest,
                )
            ]

    def _get_global_subtitle_count(self) -> int:
            subtitles = getattr(self, "subtitles", [])
            subtitle_lock = self.__dict__.get("subtitle_lock")
            if subtitle_lock is not None:
                with subtitle_lock:
                    active_count = len(subtitles)
            else:
                active_count = len(subtitles)
            return int(self.__dict__.get("_runtime_archived_count", 0) or 0) + active_count

    def _get_global_total_chars(self) -> int:
            return int(self.__dict__.get("_runtime_archived_chars", 0) or 0) + int(
                self.__dict__.get("_cached_total_chars", 0) or 0
            )

    def _get_global_total_words(self) -> int:
            return int(self.__dict__.get("_runtime_archived_words", 0) or 0) + int(
                self.__dict__.get("_cached_total_words", 0) or 0
            )

    def _read_global_entries_window(
            self,
            start_index: int,
            end_index: int,
            *,
            clone_entries: bool = True,
        ) -> list[SubtitleEntry]:
            start = max(0, int(start_index))
            end = max(start, int(end_index))
            if end <= start:
                return []

            archived_count = int(self.__dict__.get("_runtime_archived_count", 0) or 0)
            tail_revision = int(self.__dict__.get("_runtime_tail_revision", 0) or 0)
            cache_key = (start, end, archived_count, tail_revision)
            if not clone_entries and cache_key == self.__dict__.get("_runtime_render_window_cache_key"):
                return list(self.__dict__.get("_runtime_render_window_cache_entries", []))

            results: list[SubtitleEntry] = []
            if start < archived_count:
                for segment_info in self._iter_runtime_segments_for_window(start, end):
                    seg_start = int(segment_info.get("start_index", 0) or 0)
                    segment_entries = self._load_runtime_segment_entries(segment_info)
                    local_start = max(0, start - seg_start)
                    local_end = min(len(segment_entries), end - seg_start)
                    slice_entries = segment_entries[local_start:local_end]
                    if clone_entries:
                        results.extend(entry.clone() for entry in slice_entries)
                    else:
                        results.extend(slice_entries)

            if end > archived_count:
                local_start = max(0, start - archived_count)
                local_end = max(local_start, end - archived_count)
                subtitle_lock = self.__dict__.get("subtitle_lock")
                subtitles = getattr(self, "subtitles", [])
                if subtitle_lock is not None:
                    with subtitle_lock:
                        slice_entries = list(subtitles[local_start:local_end])
                else:
                    slice_entries = list(subtitles[local_start:local_end])
                if clone_entries:
                    results.extend(entry.clone() for entry in slice_entries)
                else:
                    results.extend(slice_entries)
            if not clone_entries:
                self._runtime_render_window_cache_key = cache_key
                self._runtime_render_window_cache_entries = list(results)
            return results

    def _get_global_entry_text(self, entry_index: int) -> str:
            entries = self._read_global_entries_window(
                entry_index,
                entry_index + 1,
                clone_entries=False,
            )
            if not entries:
                return ""
            return self._normalize_subtitle_text_for_option(entries[0].text)

    def _ensure_full_session_hydrated(self, reason: str = "") -> bool:
            completed = {"done": False}

            def mark_done() -> None:
                completed["done"] = True

            self._run_after_full_session_hydrated(reason, mark_done)
            return bool(completed["done"])

    def _load_runtime_manifest_payload(
            self,
            path: str | Path,
            *,
            allow_salvage: bool = False,
        ) -> dict[str, Any]:
            manifest_path = Path(path)
            runtime_root = manifest_path.parent
            all_entries: list[SubtitleEntry] = []
            skipped = 0
            skipped_files = 0
            warnings: list[str] = []
            manifest: dict[str, Any] = {}
            manifest_loaded = False

            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    loaded_manifest = json.load(f)
                if not isinstance(loaded_manifest, dict):
                    raise ValueError("지원하지 않는 runtime manifest 구조입니다.")
                if str(loaded_manifest.get("format", "") or "") != "runtime_session_manifest_v1":
                    raise ValueError("지원하지 않는 runtime manifest 형식입니다.")
                manifest = loaded_manifest
                manifest_loaded = True
            except Exception as exc:
                if not allow_salvage:
                    raise
                skipped_files += 1
                warnings.append(f"manifest 복구 전환: {exc}")

            def adopt_meta(raw_data: dict[str, Any] | None) -> None:
                nonlocal manifest
                if not isinstance(raw_data, dict):
                    return
                if not str(manifest.get("created", "") or "").strip():
                    manifest["created"] = str(raw_data.get("created", "") or "")
                if not str(manifest.get("url", "") or "").strip():
                    manifest["url"] = str(raw_data.get("url", "") or "")
                if not str(manifest.get("committee_name", "") or "").strip():
                    manifest["committee_name"] = str(raw_data.get("committee_name", "") or "")
                if not str(manifest.get("version", "") or "").strip():
                    manifest["version"] = str(raw_data.get("version", "") or "unknown")
                if not str(manifest.get("lineage_id", "") or "").strip():
                    manifest["lineage_id"] = str(raw_data.get("lineage_id", "") or "")

            segments = manifest.get("segments", [])
            if manifest_loaded and not isinstance(segments, list):
                if not allow_salvage:
                    raise ValueError("runtime manifest segments 구조가 올바르지 않습니다.")
                skipped_files += 1
                warnings.append("manifest segments 구조가 손상되어 sibling scan으로 대체합니다.")
                segments = self._build_salvaged_runtime_segments(runtime_root)
            elif not manifest_loaded:
                segments = self._build_salvaged_runtime_segments(runtime_root)

            for segment in segments if isinstance(segments, list) else []:
                relative_path = str(
                    getattr(segment, "get", lambda *_args, **_kwargs: "")("path", "") or ""
                )
                if not relative_path:
                    if allow_salvage:
                        skipped_files += 1
                        warnings.append("path가 없는 runtime segment를 건너뜁니다.")
                    continue
                try:
                    segment_path, safe_relative_path = self._resolve_runtime_relative_path(
                        runtime_root,
                        relative_path,
                        source="runtime segment",
                    )
                except ValueError as exc:
                    if not allow_salvage:
                        raise
                    skipped_files += 1
                    warnings.append(str(exc))
                    continue
                raw_data, segment_entries, segment_skipped, segment_error = (
                    self._try_load_runtime_entries_file(
                        segment_path,
                        source=f"runtime_manifest:{safe_relative_path}",
                        cache_result=True,
                    )
                )
                if segment_error:
                    if not allow_salvage:
                        raise ValueError(segment_error)
                    skipped_files += 1
                    warnings.append(segment_error)
                    continue
                adopt_meta(raw_data)
                skipped += segment_skipped
                all_entries.extend(entry.clone() for entry in segment_entries)

            checkpoint_relative = str(
                manifest.get("tail_checkpoint", "tail_checkpoint.json")
                or "tail_checkpoint.json"
            )
            checkpoint_path: Path | None = None
            try:
                checkpoint_path, safe_checkpoint_relative = self._resolve_runtime_relative_path(
                    runtime_root,
                    checkpoint_relative,
                    source="runtime tail checkpoint",
                )
            except ValueError as exc:
                if not allow_salvage:
                    raise
                skipped_files += 1
                warnings.append(str(exc))
                safe_checkpoint_relative = checkpoint_relative
            if checkpoint_path is not None and checkpoint_path.exists():
                checkpoint_data, tail_entries, tail_skipped, checkpoint_error = (
                    self._try_load_runtime_entries_file(
                        checkpoint_path,
                        source=f"runtime_tail:{checkpoint_path}",
                    )
                )
                if checkpoint_error:
                    if not allow_salvage:
                        raise ValueError(checkpoint_error)
                    skipped_files += 1
                    warnings.append(checkpoint_error)
                else:
                    adopt_meta(checkpoint_data)
                    skipped += tail_skipped
                    all_entries.extend(tail_entries)
            elif checkpoint_path is not None and allow_salvage:
                skipped_files += 1
                warnings.append(f"{safe_checkpoint_relative} 이(가) 없어 tail 복구를 건너뜁니다.")
            elif checkpoint_path is not None and manifest_loaded:
                raise ValueError(f"{safe_checkpoint_relative} 이(가) 없습니다.")

            if not all_entries:
                warning_text = " / ".join(warnings)
                if warning_text:
                    raise ValueError(f"복구 가능한 runtime 자막이 없습니다. ({warning_text})")
                raise ValueError("복구 가능한 runtime 자막이 없습니다.")

            payload = {
                "version": manifest.get("version", "unknown"),
                "created_at": manifest.get("created", ""),
                "url": manifest.get("url", ""),
                "committee_name": manifest.get("committee_name", ""),
                "lineage_id": manifest.get("lineage_id", ""),
                "subtitles": all_entries,
                "skipped": skipped,
                "runtime_manifest": True,
                "path": str(manifest_path),
            }
            if skipped_files > 0:
                payload["skipped_files"] = skipped_files
            if warnings:
                payload["recovery_warnings"] = warnings
            return payload
