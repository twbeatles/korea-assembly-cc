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


class MainWindowRuntimeSegmentsMixin(MainWindowHost):

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

            snapshot_entries = [entry.clone() for entry in prepared_entries]
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
