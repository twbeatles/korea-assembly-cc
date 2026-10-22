# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from core import utils
from core.models import CaptureSessionState, SubtitleEntry
from core.subtitle_pipeline_impl.history import (
    _append_confirmed_entry,
    _replace_tail_confirmed_entry,
    _resolve_merge_gap_seconds,
    _resolve_merge_max_chars,
    _normalize_runtime_text,
)
from core.subtitle_pipeline_impl.entry_policy import (
    is_speaker_boundary,
    should_merge_into_last_entry,
)
from core.subtitle_pipeline_impl.types import (
    LARGE_APPEND_MIN,
    PipelineResult,
    PipelineSourceMeta,
    _create_entry_id,
)


def _sanitize_committed_text(
    text: str,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    normalized_text = _normalize_runtime_text(text, settings)
    if not normalized_text:
        return ""
    if not utils.is_meaningful_subtitle_text(normalized_text):
        return ""
    return normalized_text

def _apply_source_meta(entry: SubtitleEntry, meta: Optional[PipelineSourceMeta]) -> None:
    if not meta:
        return
    if meta.source_entry_id:
        entry.entry_id = meta.source_entry_id
    if meta.selector:
        entry.source_selector = meta.selector
    if meta.frame_path:
        entry.source_frame_path = list(meta.frame_path)
    if meta.source_node_key:
        entry.source_node_key = meta.source_node_key
    if meta.speaker_color:
        entry.speaker_color = meta.speaker_color
    if meta.speaker_channel:
        entry.speaker_channel = meta.speaker_channel

def _join_stream_text(base: str, addition: str) -> str:
    left = str(base or "").rstrip()
    right = str(addition or "").lstrip()
    if not left:
        return right
    if not right:
        return left
    # Chrome joinStreamText 와 같은 문장부호 집합 (곡선 따옴표·말줄임표 포함)
    no_space_before = set(".,!?;:)]}%\"'”’…")
    no_space_after = set("([{<\"'“‘")
    if right[0] in no_space_before or left[-1] in no_space_after:
        return left + right
    return left + " " + right

def _update_state_metadata(
    state: CaptureSessionState,
    now: datetime,
    meta: Optional[PipelineSourceMeta] = None,
) -> None:
    state.last_observer_event_at = now.timestamp()
    if meta and meta.selector:
        state.current_selector = meta.selector
    if meta and meta.frame_path:
        state.current_frame_path = tuple(meta.frame_path)

def _find_entry_by_id(state: CaptureSessionState, entry_id: str) -> Optional[SubtitleEntry]:
    for entry in state.entries:
        if entry.entry_id == entry_id:
            return entry
    return None

def _append_or_merge_entry(
    state: CaptureSessionState,
    text: str,
    now: datetime,
    settings: Optional[dict[str, Any]] = None,
    meta: Optional[PipelineSourceMeta] = None,
) -> tuple[SubtitleEntry, bool, str]:
    last_entry = state.entries[-1] if state.entries else None
    merge_gap_seconds = _resolve_merge_gap_seconds(settings)
    merge_max_chars = _resolve_merge_max_chars(settings)

    if last_entry and should_merge_into_last_entry(
        last_entry,
        text,
        now,
        meta,
        merge_gap_seconds=merge_gap_seconds,
        merge_max_chars=merge_max_chars,
        after_reset=bool(state.last_committed_reset_at),
    ):
        previous_compact = last_entry.compact_text
        last_entry.update_text(_join_stream_text(last_entry.text, text))
        last_entry.end_time = now
        _apply_source_meta(last_entry, meta)
        return last_entry, False, previous_compact

    speaker_changed = bool(last_entry and is_speaker_boundary(last_entry, meta))
    entry = SubtitleEntry(
        text,
        now,
        entry_id=(meta.source_entry_id if meta and meta.source_entry_id else _create_entry_id()),
    )
    entry.start_time = now
    entry.end_time = now
    _apply_source_meta(entry, meta)
    if speaker_changed:
        entry.speaker_changed = True
    state.entries.append(entry)
    return entry, True, ""
