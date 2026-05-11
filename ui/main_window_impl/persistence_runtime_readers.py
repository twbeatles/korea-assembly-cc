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


class MainWindowRuntimeReadersMixin(MainWindowHost):

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
