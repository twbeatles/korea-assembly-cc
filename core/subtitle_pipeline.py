# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from core import utils
from core.config import Config
from core.models import CaptureSessionState, SpeakerChannel, SubtitleEntry


MIN_COMPACT_ANCHOR = 10
LARGE_APPEND_MIN = 200
RECENT_DUPLICATE_MIN_LENGTH = 8
RECENT_HISTORY_ENTRIES = 12
RECENT_HISTORY_COMPACT_LENGTH = 5000
RECENT_RESYNC_ENTRIES = 5
SUFFIX_LENGTH = 50
PREVIEW_RESYNC_THRESHOLD = 10
PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD = 6


@dataclass(slots=True)
class PipelineSourceMeta:
    selector: str = ""
    frame_path: tuple[int, ...] = ()
    source_node_key: str = ""
    source_entry_id: str = ""
    speaker_color: str = ""
    speaker_channel: SpeakerChannel = "unknown"
    force_new_entry: bool = False
    source_mode: str = ""


@dataclass(slots=True)
class LiveRowCommitMeta(PipelineSourceMeta):
    baseline_compact: Optional[str] = None


@dataclass(slots=True)
class PipelineResult:
    state: CaptureSessionState
    changed: bool
    appended_entry: Optional[SubtitleEntry] = None
    updated_entry: Optional[SubtitleEntry] = None
    reason: str = ""


@dataclass(slots=True)
class IncrementalExtractResult:
    text: str
    matched: bool
    duplicate: bool
    ambiguous: bool
    reason: str


def create_empty_capture_state() -> CaptureSessionState:
    return CaptureSessionState()


def _create_entry_id() -> str:
    return f"subtitle_{uuid4().hex}"


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


def _slice_from_compact_index(text: str, compact_index: int) -> str:
    return utils.clean_text_display(utils.slice_from_compact_index(text, compact_index))


def find_compact_suffix_prefix_overlap(
    history_compact: str,
    raw_compact: str,
    min_overlap: int = MIN_COMPACT_ANCHOR,
) -> int:
    max_overlap = min(len(history_compact), len(raw_compact))
    for length in range(max_overlap, min_overlap - 1, -1):
        if history_compact[-length:] == raw_compact[:length]:
            return length
    return 0


def extract_incremental_text_from_history(
    raw_text: str,
    history_compact: str,
    settings: Optional[dict[str, Any]] = None,
) -> IncrementalExtractResult:
    normalized_raw = _normalize_runtime_text(raw_text, settings)
    raw_compact = utils.compact_subtitle_text(normalized_raw)
    compact_history = utils.compact_subtitle_text(history_compact)

    if not raw_compact:
        return IncrementalExtractResult("", False, True, False, "empty")

    if not compact_history:
        return IncrementalExtractResult(normalized_raw, False, False, False, "no_history")

    if raw_compact == compact_history:
        return IncrementalExtractResult("", True, True, False, "identical_history")

    if (
        len(raw_compact) >= RECENT_DUPLICATE_MIN_LENGTH
        and raw_compact in compact_history
    ):
        return IncrementalExtractResult("", False, True, False, "contained_in_history")

    suffix = compact_history[-SUFFIX_LENGTH:]
    if suffix:
        first_pos = raw_compact.find(suffix)
        last_pos = raw_compact.rfind(suffix)
        if last_pos >= 0:
            compact_start = last_pos + len(suffix)
            text = _slice_from_compact_index(normalized_raw, compact_start)
            predicted_append = max(0, len(raw_compact) - compact_start)
            return IncrementalExtractResult(
                text,
                True,
                not bool(text),
                (
                    first_pos != last_pos
                    and predicted_append > max(LARGE_APPEND_MIN, len(raw_compact) // 3)
                ),
                "suffix" if text else "suffix_duplicate",
            )

    if len(compact_history) >= MIN_COMPACT_ANCHOR:
        history_pos = raw_compact.rfind(compact_history)
        if history_pos >= 0:
            compact_start = history_pos + len(compact_history)
            text = _slice_from_compact_index(normalized_raw, compact_start)
            return IncrementalExtractResult(
                text,
                True,
                not bool(text),
                False,
                "history" if text else "history_duplicate",
            )

    overlap = find_compact_suffix_prefix_overlap(compact_history, raw_compact)
    if overlap > 0:
        text = _slice_from_compact_index(normalized_raw, overlap)
        return IncrementalExtractResult(
            text,
            True,
            not bool(text),
            False,
            "overlap" if text else "overlap_duplicate",
        )

    return IncrementalExtractResult(normalized_raw, False, False, False, "full")


def extract_incremental_text_with_recent_history(
    raw_text: str,
    history_compact: str,
    recent_history_compact: str,
    settings: Optional[dict[str, Any]] = None,
) -> IncrementalExtractResult:
    recent_history = utils.compact_subtitle_text(recent_history_compact)
    full_history = utils.compact_subtitle_text(history_compact)

    if recent_history and recent_history != full_history:
        recent_result = extract_incremental_text_from_history(
            raw_text,
            recent_history,
            settings,
        )
        if recent_result.matched or recent_result.duplicate:
            return recent_result

    return extract_incremental_text_from_history(raw_text, full_history, settings)


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
