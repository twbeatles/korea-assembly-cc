# -*- coding: utf-8 -*-

import bisect
import shutil

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowPersistenceRuntimeMixin(MainWindowHost):

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
            self._runtime_segment_flush_in_progress = False
            self._invalidate_runtime_segment_caches()
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
            self._reset_runtime_session_archive_state(keep_root=not remove_files)
            if remove_files and runtime_root is not None:
                try:
                    shutil.rmtree(runtime_root, ignore_errors=True)
                except Exception:
                    logger.debug("runtime session archive 정리 실패: %s", runtime_root, exc_info=True)

    def _cleanup_orphan_runtime_archives(self) -> None:
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
            self._cleanup_runtime_session_archive(remove_files=True)
            self._cleanup_orphan_runtime_archives()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = f"{int(run_id)}" if run_id is not None else "manual"
            runtime_root = Path(Config.RUNTIME_SESSION_DIR) / f"run_{timestamp}_{suffix}"
            runtime_root.mkdir(parents=True, exist_ok=True)
            self._runtime_session_root = runtime_root
            self._runtime_manifest_path = runtime_root / "manifest.json"
            self._reset_runtime_session_archive_state(keep_root=True)
            self._write_runtime_manifest()

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
            return {
                "format": "runtime_session_manifest_v1",
                "version": Config.VERSION,
                "created": datetime.now().isoformat(),
                "url": current_url,
                "committee_name": committee_name,
                "archived_count": int(self._runtime_archived_count),
                "archived_chars": int(self._runtime_archived_chars),
                "archived_words": int(self._runtime_archived_words),
                "tail_checkpoint": "tail_checkpoint.json",
                "segments": [dict(item) for item in self._runtime_segment_manifest],
            }

    def _write_runtime_manifest(self) -> None:
            manifest_path = self._runtime_manifest_path
            if manifest_path is None:
                return
            utils.atomic_write_json(
                manifest_path,
                self._serialize_runtime_manifest(),
                ensure_ascii=False,
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
            created_at = datetime.now().isoformat()
            entries = prepared_entries if prepared_entries is not None else list(self.subtitles)
            saved_count = int(self.__dict__.get("_runtime_archived_count", 0) or 0) + len(
                entries
            )
            utils.atomic_write_json_stream(
                checkpoint_path,
                head_items=[
                    ("format", "runtime_tail_checkpoint_v1"),
                    ("version", Config.VERSION),
                    ("created", created_at),
                    ("url", current_url),
                    ("committee_name", committee_name),
                    ("archived_count", int(self._runtime_archived_count)),
                    ("archived_chars", int(self._runtime_archived_chars)),
                    ("archived_words", int(self._runtime_archived_words)),
                ],
                sequence_key="subtitles",
                sequence_items=utils.iter_serialized_subtitles(entries),
                ensure_ascii=False,
            )
            self._runtime_tail_checkpoint_revision = tail_revision
            return checkpoint_path

    def _record_runtime_recovery_snapshot(
            self,
            prepared_entries: list[SubtitleEntry] | None = None,
        ) -> bool:
            manifest_path = self._runtime_manifest_path
            if manifest_path is None:
                return False
            self._write_runtime_tail_checkpoint(prepared_entries)
            self._write_runtime_manifest()
            current_url, committee_name, _duration = self._build_session_save_context()
            self._record_recovery_snapshot(
                manifest_path,
                "runtime_manifest",
                created_at=datetime.now().isoformat(),
                url=current_url,
                committee_name=committee_name,
            )
            return True

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

            self._runtime_segment_flush_in_progress = True
            segment_index = int(self._runtime_next_segment_index)
            segment_path = self._runtime_session_root / f"segment_{segment_index:06d}.json"
            relative_path = segment_path.name
            start_index = int(self._runtime_archived_count)
            char_count = sum(entry.char_count for entry in flush_entries)
            word_count = sum(entry.word_count for entry in flush_entries)
            current_url, committee_name, _duration = self._build_session_save_context()
            created_at = datetime.now().isoformat()

            def write_segment() -> None:
                try:
                    utils.atomic_write_json_stream(
                        segment_path,
                        head_items=[
                            ("format", "runtime_session_segment_v1"),
                            ("version", Config.VERSION),
                            ("created", created_at),
                            ("url", current_url),
                            ("committee_name", committee_name),
                            ("segment_index", segment_index),
                            ("start_index", start_index),
                            ("entry_count", flush_count),
                        ],
                        sequence_key="subtitles",
                        sequence_items=utils.iter_serialized_subtitles(flush_entries),
                        ensure_ascii=False,
                    )
                    self._emit_control_message(
                        "runtime_segment_flush_done",
                        {
                            "segment_index": segment_index,
                            "path": relative_path,
                            "entry_count": flush_count,
                            "char_count": char_count,
                            "word_count": word_count,
                            "start_index": start_index,
                        },
                    )
                except Exception as e:
                    logger.error("runtime segment flush 실패: %s", e)
                    self._emit_control_message(
                        "runtime_segment_flush_failed",
                        {"path": relative_path, "error": str(e)},
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
            flush_count = int(payload.get("entry_count", 0) or 0)
            char_count = int(payload.get("char_count", 0) or 0)
            word_count = int(payload.get("word_count", 0) or 0)
            segment_index = int(payload.get("segment_index", 0) or 0)
            relative_path = str(payload.get("path", "") or "").strip()
            start_index = int(payload.get("start_index", self._runtime_archived_count) or self._runtime_archived_count)
            self._runtime_segment_flush_in_progress = False
            if flush_count <= 0 or not relative_path:
                return

            with self.subtitle_lock:
                removable = min(flush_count, len(self.subtitles))
                if removable > 0:
                    del self.subtitles[:removable]

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

            def write_snapshot() -> None:
                try:
                    self._record_runtime_recovery_snapshot(snapshot_entries)
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

            with open(segment_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries, _skipped = self._deserialize_subtitles(
                data.get("subtitles", []),
                source=source or cache_key,
            )
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
            return entries

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
            segment_path = runtime_root / relative_path
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
            cache_key = str((runtime_root / relative_path).resolve())
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
            if not self._has_runtime_archived_segments():
                return False
            full_entries = self._build_complete_session_entries_snapshot()
            self._replace_subtitles_and_refresh(
                full_entries,
                keep_history_from_subtitles=bool(full_entries),
            )
            self._clear_recovery_state()
            self._cleanup_runtime_session_archive(remove_files=True)
            if reason:
                self._show_toast(
                    f"장시간 세션 전체를 메모리로 불러왔습니다. ({reason})",
                    "info",
                    3000,
                )
            return True

    def _load_runtime_manifest_payload(self, path: str | Path) -> dict[str, Any]:
            manifest_path = Path(path)
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            if str(manifest.get("format", "") or "") != "runtime_session_manifest_v1":
                raise ValueError("지원하지 않는 runtime manifest 형식입니다.")

            runtime_root = manifest_path.parent
            segments = manifest.get("segments", [])
            all_entries: list[SubtitleEntry] = []
            skipped = 0
            for segment in segments if isinstance(segments, list) else []:
                relative_path = str(getattr(segment, "get", lambda *_args, **_kwargs: "")("path", "") or "")
                if not relative_path:
                    continue
                segment_entries = self._load_segment_file_entries(
                    runtime_root / relative_path,
                    source=f"runtime_manifest:{relative_path}",
                )
                all_entries.extend(entry.clone() for entry in segment_entries)

            checkpoint_path = runtime_root / str(manifest.get("tail_checkpoint", "tail_checkpoint.json") or "tail_checkpoint.json")
            if checkpoint_path.exists():
                with open(checkpoint_path, "r", encoding="utf-8") as f:
                    checkpoint_data = json.load(f)
                tail_entries, tail_skipped = self._deserialize_subtitles(
                    checkpoint_data.get("subtitles", []),
                    source=f"runtime_tail:{checkpoint_path}",
                )
                skipped += tail_skipped
                all_entries.extend(tail_entries)

            return {
                "version": manifest.get("version", "unknown"),
                "created_at": manifest.get("created", ""),
                "url": manifest.get("url", ""),
                "committee_name": manifest.get("committee_name", ""),
                "subtitles": all_entries,
                "skipped": skipped,
                "runtime_manifest": True,
                "path": str(manifest_path),
            }
