# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Optional

from core import utils
from core.subtitle_pipeline_impl.history import (
    _normalize_runtime_text,
    build_recent_compact_history,
)
from core.subtitle_pipeline_impl.types import (
    IncrementalExtractResult,
    LARGE_APPEND_MIN,
    MIN_COMPACT_ANCHOR,
    RECENT_DUPLICATE_MIN_LENGTH,
    SUFFIX_LENGTH,
)


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
