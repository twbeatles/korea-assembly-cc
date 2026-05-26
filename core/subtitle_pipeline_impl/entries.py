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
    no_space_before = set(".,!?;:)]}%\"'")
    no_space_after = set("([{<\"'")
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

    if (
        last_entry
        and not state.last_committed_reset_at
        and not (meta and meta.force_new_entry)
    ):
        structured_boundary = bool(
            meta
            and meta.source_node_key
            and last_entry.source_node_key
            and last_entry.source_node_key != meta.source_node_key
        )
        speaker_color_boundary = bool(
            meta
            and meta.speaker_color
            and last_entry.speaker_color
            and meta.speaker_color != last_entry.speaker_color
        )
        known_meta_channel = bool(
            meta and meta.speaker_channel in ("primary", "secondary")
        )
        known_last_channel = last_entry.speaker_channel in ("primary", "secondary")
        speaker_channel_boundary = bool(
            meta
            and known_meta_channel
            and known_last_channel
            and meta.speaker_channel != last_entry.speaker_channel
        )
        fallback_boundary = bool(
            meta
            and meta.source_mode == "container"
            and (
                last_entry.source_node_key
                or last_entry.speaker_color
                or last_entry.speaker_channel in ("primary", "secondary")
            )
        )
        last_end_time = last_entry.end_time or last_entry.timestamp
        exceeds_merge_gap = (now - last_end_time).total_seconds() > merge_gap_seconds
        can_merge = (
            not exceeds_merge_gap
            and not structured_boundary
            and not speaker_color_boundary
            and not speaker_channel_boundary
            and not fallback_boundary
            and len(last_entry.text) + len(text) < merge_max_chars
        )
        if can_merge:
            previous_compact = last_entry.compact_text
            last_entry.update_text(_join_stream_text(last_entry.text, text))
            last_entry.end_time = now
            _apply_source_meta(last_entry, meta)
            return last_entry, False, previous_compact

    entry = SubtitleEntry(
        text,
        now,
        entry_id=(meta.source_entry_id if meta and meta.source_entry_id else _create_entry_id()),
    )
    entry.start_time = now
    entry.end_time = now
    _apply_source_meta(entry, meta)
    state.entries.append(entry)
    return entry, True, ""
