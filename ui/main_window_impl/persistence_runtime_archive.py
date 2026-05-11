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


class MainWindowRuntimeArchiveMixin(MainWindowHost):

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
