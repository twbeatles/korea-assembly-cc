# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from core import utils
from core.models import CaptureSessionState, SubtitleEntry
from core.subtitle_pipeline_impl.entries import (
    _append_or_merge_entry,
    _apply_source_meta,
    _find_entry_by_id,
    _join_stream_text,
    _sanitize_committed_text,
    _update_state_metadata,
)
from core.subtitle_pipeline_impl.history import (
    _append_confirmed_entry,
    _apply_confirmed_segments,
    _confirmed_history_without_last_entry,
    _normalize_runtime_text,
    _replace_tail_confirmed_entry,
    _resolve_auto_clean_newlines,
    _resolve_confirmed_compact_max_length,
    _resolve_merge_gap_seconds,
    _resolve_merge_max_chars,
    build_confirmed_compact_history,
    build_recent_compact_history,
    rebuild_confirmed_history,
    soft_resync_history,
)
from core.subtitle_pipeline_impl.incremental import (
    _slice_from_compact_index,
    extract_incremental_text_from_history,
    extract_incremental_text_with_recent_history,
    find_compact_suffix_prefix_overlap,
)
from core.subtitle_pipeline_impl.types import (
    LARGE_APPEND_MIN,
    MIN_COMPACT_ANCHOR,
    PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD,
    PREVIEW_RESYNC_THRESHOLD,
    RECENT_DUPLICATE_MIN_LENGTH,
    RECENT_HISTORY_COMPACT_LENGTH,
    RECENT_HISTORY_ENTRIES,
    RECENT_RESYNC_ENTRIES,
    SUFFIX_LENGTH,
    IncrementalExtractResult,
    LiveRowCommitMeta,
    PipelineResult,
    PipelineSourceMeta,
    create_empty_capture_state,
    _create_entry_id,
)

PipelineSourceMeta.__module__ = __name__
LiveRowCommitMeta.__module__ = __name__
PipelineResult.__module__ = __name__
IncrementalExtractResult.__module__ = __name__

def apply_preview(
    state: CaptureSessionState,
    raw: str,
    now: datetime,
    settings: Optional[dict[str, Any]] = None,
    meta: Optional[PipelineSourceMeta] = None,
) -> PipelineResult:
    _update_state_metadata(state, now, meta)
    normalized_raw = _normalize_runtime_text(raw, settings)
    preview_changed = state.preview_text != normalized_raw
    state.preview_text = normalized_raw
    state.last_observed_raw = normalized_raw

    extraction = extract_incremental_text_with_recent_history(
        normalized_raw,
        state.confirmed_compact,
        build_recent_compact_history(state.entries),
        settings,
    )

    if not extraction.matched and state.confirmed_compact:
        state.preview_desync_count += 1
    else:
        state.preview_desync_count = 0

    if extraction.ambiguous:
        state.preview_ambiguous_skip_count += 1
    else:
        state.preview_ambiguous_skip_count = 0

    if state.entries and (
        state.preview_desync_count >= PREVIEW_RESYNC_THRESHOLD
        or state.preview_ambiguous_skip_count >= PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD
    ):
        soft_resync_history(state, settings)
        extraction = extract_incremental_text_with_recent_history(
            normalized_raw,
            state.confirmed_compact,
            build_recent_compact_history(state.entries),
            settings,
        )

    if extraction.duplicate or not extraction.text:
        return PipelineResult(state, preview_changed, reason=f"preview_{extraction.reason}")

    candidate_text = _sanitize_committed_text(extraction.text, settings)
    if not candidate_text:
        return PipelineResult(state, preview_changed, reason="preview_filtered")

    entry, appended_new, previous_compact = _append_or_merge_entry(
        state,
        candidate_text,
        now,
        settings,
        meta,
    )
    state.last_processed_raw = normalized_raw
    state.last_committed_reset_at = None
    state.preview_desync_count = 0
    state.preview_ambiguous_skip_count = 0
    if appended_new:
        _append_confirmed_entry(state, entry, settings)
    elif not _replace_tail_confirmed_entry(state, previous_compact, entry, settings):
        rebuild_confirmed_history(state, settings)
    return PipelineResult(
        state,
        True,
        appended_entry=entry if appended_new else None,
        updated_entry=entry,
        reason=f"preview_{extraction.reason}",
    )

def commit_live_row(
    state: CaptureSessionState,
    row_text: str,
    preview_text: str,
    now: datetime,
    settings: Optional[dict[str, Any]] = None,
    meta: Optional[LiveRowCommitMeta] = None,
) -> PipelineResult:
    _update_state_metadata(state, now, meta)
    normalized_preview = _normalize_runtime_text(
        preview_text,
        settings,
    ) or _normalize_runtime_text(row_text, settings)
    preview_changed = state.preview_text != normalized_preview
    baseline_compact = (
        meta.baseline_compact if meta and meta.baseline_compact is not None else state.confirmed_compact
    ) or ""
    recent_baseline = utils.compact_subtitle_text(baseline_compact)[-RECENT_HISTORY_COMPACT_LENGTH:]

    state.preview_text = normalized_preview
    state.last_observed_raw = normalized_preview

    extraction = extract_incremental_text_with_recent_history(
        row_text,
        baseline_compact,
        recent_baseline,
        settings,
    )
    candidate_text = _sanitize_committed_text(extraction.text, settings)
    if not candidate_text:
        return PipelineResult(
            state,
            preview_changed,
            reason="row_duplicate" if extraction.duplicate else "row_filtered",
        )

    if meta and meta.source_entry_id:
        entry = _find_entry_by_id(state, meta.source_entry_id)
        if not entry:
            return PipelineResult(state, preview_changed, reason="row_entry_missing")
        before_text = entry.text
        previous_compact = entry.compact_text
        entry.update_text(candidate_text)
        entry.end_time = now
        _apply_source_meta(entry, meta)
        state.last_processed_raw = _normalize_runtime_text(row_text, settings)
        state.last_committed_reset_at = None
        if (
            state.entries
            and entry is state.entries[-1]
            and _replace_tail_confirmed_entry(state, previous_compact, entry, settings)
        ):
            pass
        else:
            rebuild_confirmed_history(state, settings)
        changed = preview_changed or before_text != entry.text
        return PipelineResult(
            state,
            changed,
            updated_entry=entry,
            reason="row_update",
        )

    entry, appended_new, previous_compact = _append_or_merge_entry(
        state,
        candidate_text,
        now,
        settings,
        meta=PipelineSourceMeta(
            selector=meta.selector if meta else "",
            frame_path=meta.frame_path if meta else (),
            source_node_key=meta.source_node_key if meta else "",
            source_entry_id="",
            speaker_color=meta.speaker_color if meta else "",
            speaker_channel=meta.speaker_channel if meta else "unknown",
            force_new_entry=True,
            source_mode=meta.source_mode if meta else "",
        ),
    )
    state.last_processed_raw = _normalize_runtime_text(row_text, settings)
    state.last_committed_reset_at = None
    if appended_new:
        _append_confirmed_entry(state, entry, settings)
    elif not _replace_tail_confirmed_entry(state, previous_compact, entry, settings):
        rebuild_confirmed_history(state, settings)
    return PipelineResult(
        state,
        True,
        appended_entry=entry if appended_new else None,
        updated_entry=entry,
        reason="row_append",
    )

def apply_structured_entry(
    state: CaptureSessionState,
    text: str,
    preview_text: str,
    now: datetime,
    settings: Optional[dict[str, Any]] = None,
    meta: Optional[PipelineSourceMeta] = None,
) -> PipelineResult:
    last_entry = state.entries[-1] if state.entries else None
    if (
        meta
        and meta.source_node_key
        and last_entry
        and last_entry.source_node_key == meta.source_node_key
        and not meta.force_new_entry
    ):
        baseline_compact = _confirmed_history_without_last_entry(state, settings)
        return commit_live_row(
            state,
            text,
            preview_text,
            now,
            settings,
        meta=LiveRowCommitMeta(
            selector=meta.selector,
            frame_path=meta.frame_path,
            source_node_key=meta.source_node_key,
            source_entry_id=last_entry.entry_id or "",
            speaker_color=meta.speaker_color,
            speaker_channel=meta.speaker_channel,
            source_mode=meta.source_mode,
            baseline_compact=baseline_compact,
        ),
    )

    return commit_live_row(
        state,
        text,
        preview_text,
        now,
        settings,
        meta=LiveRowCommitMeta(
            selector=meta.selector if meta else "",
            frame_path=meta.frame_path if meta else (),
            source_node_key=meta.source_node_key if meta else "",
            speaker_color=meta.speaker_color if meta else "",
            speaker_channel=meta.speaker_channel if meta else "unknown",
            source_mode=meta.source_mode if meta else "",
            baseline_compact=state.confirmed_compact,
        ),
    )

def apply_keepalive(
    state: CaptureSessionState,
    raw: str,
    now: datetime,
) -> PipelineResult:
    state.last_observer_event_at = now.timestamp()
    last_entry = state.entries[-1] if state.entries else None
    if not last_entry:
        return PipelineResult(state, False, reason="no_entries")

    raw_compact = utils.compact_subtitle_text(raw)
    if raw_compact and raw_compact != last_entry.compact_text:
        return PipelineResult(state, False, reason="raw_mismatch")

    last_entry.end_time = now
    state.last_keepalive_at = now.timestamp()
    return PipelineResult(state, True, updated_entry=last_entry, reason="keepalive")

def apply_reset(
    state: CaptureSessionState,
    now: datetime,
    settings: Optional[dict[str, Any]] = None,
) -> PipelineResult:
    state.preview_text = ""
    _apply_confirmed_segments(state, [], settings)
    state.last_observed_raw = ""
    state.last_processed_raw = ""
    state.preview_desync_count = 0
    state.preview_ambiguous_skip_count = 0
    state.last_committed_reset_at = now.timestamp()
    state.last_observer_event_at = now.timestamp()
    return PipelineResult(state, True, reason="reset")

def finalize_session(
    state: CaptureSessionState,
    now: datetime,
    settings: Optional[dict[str, Any]] = None,
) -> PipelineResult:
    del settings
    state.preview_text = ""
    state.last_committed_reset_at = None
    state.last_observer_event_at = now.timestamp()
    last_entry = state.entries[-1] if state.entries else None
    if last_entry:
        last_entry.end_time = now
    return PipelineResult(state, True, updated_entry=last_entry, reason="finalized")

def flush_pending_previews(
    state: CaptureSessionState,
    now: datetime,
    settings: Optional[dict[str, Any]] = None,
) -> CaptureSessionState:
    prepared_state = state.snapshot_clone(clone_last_entry=bool(state.preview_text))
    normalized_preview = _normalize_runtime_text(prepared_state.preview_text, settings)
    if not normalized_preview:
        return prepared_state
    apply_preview(
        prepared_state,
        normalized_preview,
        now,
        settings,
        meta=PipelineSourceMeta(
            selector=prepared_state.current_selector,
            frame_path=prepared_state.current_frame_path,
        ),
    )
    return prepared_state


__all__ = [
    "MIN_COMPACT_ANCHOR",
    "LARGE_APPEND_MIN",
    "RECENT_DUPLICATE_MIN_LENGTH",
    "RECENT_HISTORY_ENTRIES",
    "RECENT_HISTORY_COMPACT_LENGTH",
    "RECENT_RESYNC_ENTRIES",
    "SUFFIX_LENGTH",
    "PREVIEW_RESYNC_THRESHOLD",
    "PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD",
    "PipelineSourceMeta",
    "LiveRowCommitMeta",
    "PipelineResult",
    "IncrementalExtractResult",
    "create_empty_capture_state",
    "build_confirmed_compact_history",
    "rebuild_confirmed_history",
    "soft_resync_history",
    "build_recent_compact_history",
    "find_compact_suffix_prefix_overlap",
    "extract_incremental_text_from_history",
    "extract_incremental_text_with_recent_history",
    "apply_preview",
    "commit_live_row",
    "apply_structured_entry",
    "apply_keepalive",
    "apply_reset",
    "finalize_session",
    "flush_pending_previews",
]
