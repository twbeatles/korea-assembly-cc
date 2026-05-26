# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Optional

from core import utils
from core.config import Config
from core.models import CaptureSessionState, SubtitleEntry
from core.subtitle_pipeline_impl.types import (
    RECENT_HISTORY_COMPACT_LENGTH,
    RECENT_HISTORY_ENTRIES,
    RECENT_RESYNC_ENTRIES,
    SUFFIX_LENGTH,
)


def _apply_confirmed_segments(
    state: CaptureSessionState,
    segments: list[str],
    settings: Optional[dict[str, Any]] = None,
) -> None:
    max_length = _resolve_confirmed_compact_max_length(settings)
    normalized_segments = [segment for segment in segments if segment]
    if max_length > 0 and normalized_segments:
        total_length = sum(len(segment) for segment in normalized_segments)
        trim = total_length - max_length
        while trim > 0 and normalized_segments:
            first = normalized_segments[0]
            if len(first) <= trim:
                trim -= len(first)
                normalized_segments.pop(0)
                continue
            normalized_segments[0] = first[trim:]
            trim = 0

    state.confirmed_segments = normalized_segments
    state.confirmed_compact = "".join(normalized_segments)
    state.trailing_suffix = state.confirmed_compact[-SUFFIX_LENGTH:]

def _append_confirmed_entry(
    state: CaptureSessionState,
    entry: SubtitleEntry,
    settings: Optional[dict[str, Any]] = None,
) -> None:
    compact = entry.compact_text
    if not compact:
        return
    segments = list(state.confirmed_segments)
    segments.append(compact)
    _apply_confirmed_segments(state, segments, settings)

def _replace_tail_confirmed_entry(
    state: CaptureSessionState,
    previous_compact: str,
    entry: SubtitleEntry,
    settings: Optional[dict[str, Any]] = None,
) -> bool:
    if not previous_compact or not state.confirmed_segments:
        return False
    if state.confirmed_segments[-1] != previous_compact:
        return False

    segments = list(state.confirmed_segments)
    next_compact = entry.compact_text
    if next_compact:
        segments[-1] = next_compact
    else:
        segments.pop()
    _apply_confirmed_segments(state, segments, settings)
    return True

def _confirmed_history_without_last_entry(
    state: CaptureSessionState,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    if not state.entries:
        return ""

    last_compact = state.entries[-1].compact_text
    if state.confirmed_segments and last_compact and state.confirmed_segments[-1] == last_compact:
        compact = "".join(state.confirmed_segments[:-1])
        max_length = _resolve_confirmed_compact_max_length(settings)
        return compact[-max_length:] if max_length > 0 else compact

    return build_confirmed_compact_history(
        state.entries[:-1],
        _resolve_confirmed_compact_max_length(settings),
    )

def build_confirmed_compact_history(
    entries: list[SubtitleEntry],
    max_length: int = Config.CONFIRMED_COMPACT_MAX_LEN,
) -> str:
    if not entries:
        return ""

    parts: list[str] = []
    current_length = 0
    for entry in reversed(entries):
        compact = entry.compact_text
        if not compact:
            continue
        parts.insert(0, compact)
        current_length += len(compact)
        if current_length >= max_length:
            break
    return "".join(parts)[-max_length:]

def _resolve_merge_max_chars(settings: Optional[dict[str, int]] = None) -> int:
    return int((settings or {}).get("merge_max_chars", Config.ENTRY_MERGE_MAX_CHARS))

def _resolve_merge_gap_seconds(settings: Optional[dict[str, int]] = None) -> int:
    return int((settings or {}).get("merge_gap_seconds", Config.ENTRY_MERGE_MAX_GAP))

def _resolve_confirmed_compact_max_length(settings: Optional[dict[str, int]] = None) -> int:
    return int((settings or {}).get("confirmed_compact_max_len", Config.CONFIRMED_COMPACT_MAX_LEN))

def _resolve_auto_clean_newlines(settings: Optional[dict[str, Any]] = None) -> bool:
    return bool(
        (settings or {}).get(
            "auto_clean_newlines",
            Config.AUTO_CLEAN_NEWLINES_DEFAULT,
        )
    )

def _normalize_runtime_text(
    text: str,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    if _resolve_auto_clean_newlines(settings):
        return utils.flatten_subtitle_text(text)
    return utils.clean_text_display(text)

def rebuild_confirmed_history(
    state: CaptureSessionState,
    settings: Optional[dict[str, Any]] = None,
) -> None:
    max_length = _resolve_confirmed_compact_max_length(settings)
    segments: list[str] = []
    current_length = 0
    for entry in reversed(state.entries):
        compact = entry.compact_text
        if not compact:
            continue
        segments.insert(0, compact)
        current_length += len(compact)
        if max_length > 0 and current_length >= max_length:
            break
    _apply_confirmed_segments(state, segments, settings)

def soft_resync_history(
    state: CaptureSessionState,
    settings: Optional[dict[str, Any]] = None,
) -> None:
    recent_entries = state.entries[-RECENT_RESYNC_ENTRIES:]
    segments = [entry.compact_text for entry in recent_entries if entry.compact_text]
    _apply_confirmed_segments(state, segments, settings)
    state.preview_desync_count = 0
    state.preview_ambiguous_skip_count = 0

def build_recent_compact_history(entries: list[SubtitleEntry]) -> str:
    recent_entries = entries[-RECENT_HISTORY_ENTRIES:]
    parts = [entry.compact_text for entry in recent_entries if entry.compact_text]
    return "".join(parts)[-RECENT_HISTORY_COMPACT_LENGTH:]
