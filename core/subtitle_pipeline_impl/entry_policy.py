# -*- coding: utf-8 -*-
"""entry 병합·keepalive 판정 순수 함수.

Chrome 확장(korea-assembly-cc-chrome) `src/core/subtitle-pipeline/entry-policy.ts` 와
같은 규칙이며 `parity/pipeline-vectors.json` 의 `shouldMerge` / `keepalive` 벡터로
양쪽을 함께 검증한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from core import utils
from core.config import Config
from core.models import SubtitleEntry
from core.subtitle_pipeline_impl.types import PipelineSourceMeta

_KNOWN_SPEAKER_CHANNELS = ("primary", "secondary")
FALLBACK_SOURCE_MODES = ("container", "fallback")


def is_fallback_source_mode(source_mode: str) -> bool:
    return str(source_mode or "") in FALLBACK_SOURCE_MODES


def is_speaker_boundary(
    last_entry: SubtitleEntry,
    meta: Optional[PipelineSourceMeta],
) -> bool:
    """양쪽 모두 알려진 channel 이 다르거나, 양쪽 색이 다르면 화자 경계다."""
    if not meta:
        return False
    channel_boundary = (
        meta.speaker_channel in _KNOWN_SPEAKER_CHANNELS
        and last_entry.speaker_channel in _KNOWN_SPEAKER_CHANNELS
        and meta.speaker_channel != last_entry.speaker_channel
    )
    color_boundary = bool(
        meta.speaker_color
        and last_entry.speaker_color
        and meta.speaker_color != last_entry.speaker_color
    )
    return channel_boundary or color_boundary


def should_merge_into_last_entry(
    last_entry: SubtitleEntry,
    text: str,
    now: datetime,
    meta: Optional[PipelineSourceMeta] = None,
    *,
    merge_gap_seconds: float = Config.ENTRY_MERGE_MAX_GAP,
    merge_max_chars: int = Config.ENTRY_MERGE_MAX_CHARS,
    after_reset: bool = False,
) -> bool:
    if after_reset or (meta and meta.force_new_entry):
        return False

    structured_boundary = bool(
        meta
        and meta.source_node_key
        and last_entry.source_node_key
        and last_entry.source_node_key != meta.source_node_key
    )
    is_fallback_meta = bool(meta and is_fallback_source_mode(meta.source_mode))
    # structured/화자 신호가 있는 entry 뒤에 container fallback 이 오면 이어 붙이지 않는다.
    fallback_boundary = is_fallback_meta and bool(
        last_entry.source_node_key
        or last_entry.speaker_color
        or last_entry.speaker_channel in _KNOWN_SPEAKER_CHANNELS
    )
    # structured node key 가 없는 fallback 은 더 짧은 merge gap 을 쓴다.
    is_fallback_path = is_fallback_meta or (
        not (meta and meta.source_node_key) and not last_entry.source_node_key
    )
    gap_seconds = (
        max(1.0, float(merge_gap_seconds) * float(Config.FALLBACK_MERGE_GAP_FACTOR))
        if is_fallback_path
        else float(merge_gap_seconds)
    )
    last_end_time = last_entry.end_time or last_entry.timestamp
    exceeds_merge_gap = (now - last_end_time).total_seconds() > gap_seconds

    return (
        not exceeds_merge_gap
        and not structured_boundary
        and not fallback_boundary
        and not is_speaker_boundary(last_entry, meta)
        and len(last_entry.text) + len(text) < int(merge_max_chars)
    )


def should_apply_keepalive(raw: str, last_entry_text: str) -> bool:
    """동일 raw 유지 중 마지막 entry 의 end_time 을 연장해도 되는지 판정한다.

    raw 가 비어 있으면 기존처럼 허용하고, raw 가 있으면 화면 텍스트가 마지막 entry 로
    끝날 때만 연장한다 (structured 미리보기는 최근 여러 row 를 이어 붙이므로 접미 비교).
    """
    last_compact = utils.compact_subtitle_text(last_entry_text)
    if not last_compact:
        return False
    raw_compact = utils.compact_subtitle_text(raw or "")
    if not raw_compact:
        return True
    return raw_compact == last_compact or raw_compact.endswith(last_compact)
