# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from core.models import SubtitleEntry

_TIMESTAMP_PATTERN = re.compile(r"\[(\d{2}:\d{2}:\d{2})\]")
_SENTENCE_SPLIT_PATTERN = re.compile(r"([.?!])\s+")
_MERGE_ENDERS = (".", "?", "!")


def _clone_entry(
    entry: SubtitleEntry,
    *,
    text: str | None = None,
    timestamp: datetime | None = None,
    preserve_entry_id: bool = True,
) -> SubtitleEntry:
    if preserve_entry_id and text is None and timestamp is None:
        return entry.clone()

    cloned = SubtitleEntry(
        text if text is not None else entry.text,
        timestamp or entry.timestamp,
        entry_id=entry.entry_id if preserve_entry_id else None,
        source_selector=entry.source_selector,
        source_frame_path=entry.source_frame_path,
        source_node_key=entry.source_node_key,
        speaker_color=entry.speaker_color,
        speaker_channel=entry.speaker_channel,
        speaker_changed=entry.speaker_changed,
    )
    cloned.start_time = entry.start_time
    cloned.end_time = entry.end_time
    return cloned


def _metadata_signature(entry: SubtitleEntry) -> tuple[object, ...]:
    frame_path = tuple(entry.source_frame_path or ())
    return (
        entry.source_selector,
        frame_path,
        entry.source_node_key,
        entry.speaker_color,
        entry.speaker_channel,
        entry.speaker_changed,
    )


def _split_embedded_timestamps(
    entry: SubtitleEntry,
) -> list[tuple[SubtitleEntry, bool]]:
    text = entry.text
    matches = list(_TIMESTAMP_PATTERN.finditer(text))
    if not matches:
        return [(entry.clone(), False)]

    base_date = entry.timestamp.date()
    current_timestamp = entry.timestamp
    chunks: list[tuple[str, datetime]] = []
    last_pos = 0

    for match in matches:
        pre_text = text[last_pos:match.start()].strip()
        if pre_text:
            chunks.append((pre_text, current_timestamp))

        try:
            parsed_time = datetime.strptime(match.group(1), "%H:%M:%S").time()
            current_timestamp = datetime.combine(base_date, parsed_time)
        except ValueError:
            pass
        last_pos = match.end()

    remaining_text = text[last_pos:].strip()
    if remaining_text:
        chunks.append((remaining_text, current_timestamp))

    if not chunks:
        return []

    pieces: list[tuple[SubtitleEntry, bool]] = []
    for index, (chunk_text, chunk_timestamp) in enumerate(chunks):
        piece = _clone_entry(
            entry,
            text=chunk_text,
            timestamp=chunk_timestamp,
            preserve_entry_id=False,
        )
        if index == 0 and chunk_timestamp == entry.timestamp:
            piece.start_time = entry.start_time
        else:
            piece.start_time = chunk_timestamp
        if index < len(chunks) - 1:
            piece.end_time = chunks[index + 1][1]
        else:
            piece.end_time = entry.end_time
        pieces.append((piece, index > 0))
    return pieces


def _split_sentences(buffer_text: str) -> list[str]:
    fragments = _SENTENCE_SPLIT_PATTERN.split(buffer_text.strip())
    if len(fragments) <= 1:
        return [buffer_text.strip()] if buffer_text.strip() else []

    sentences: list[str] = []
    current = ""
    for fragment in fragments:
        if fragment in (".", "?", "!"):
            current += fragment
            if current.strip():
                sentences.append(current.strip())
            current = ""
            continue
        if current:
            if current.strip():
                sentences.append(current.strip())
        current = fragment
    if current.strip():
        sentences.append(current.strip())
    return sentences


def _split_entry_by_sentences(
    entry: SubtitleEntry,
    boundary_before: bool = False,
) -> list[tuple[SubtitleEntry, bool]]:
    sentences = _split_sentences(entry.text)
    if not sentences:
        return []
    if len(sentences) == 1 and sentences[0] == entry.text.strip():
        return [(entry.clone(), boundary_before)]

    pieces: list[tuple[SubtitleEntry, bool]] = []
    for index, sentence in enumerate(sentences):
        piece = _clone_entry(
            entry,
            text=sentence,
            timestamp=entry.timestamp,
            preserve_entry_id=False,
        )
        piece.start_time = entry.start_time if index == 0 else None
        piece.end_time = entry.end_time if index == len(sentences) - 1 else None
        pieces.append((piece, boundary_before if index == 0 else False))
    return pieces


def _expand_entries(subtitles: Iterable[SubtitleEntry]) -> list[tuple[SubtitleEntry, bool]]:
    expanded: list[tuple[SubtitleEntry, bool]] = []
    for entry in subtitles:
        timestamp_split = _split_embedded_timestamps(entry)
        for piece, boundary_before in timestamp_split:
            expanded.extend(_split_entry_by_sentences(piece, boundary_before))
    return expanded


def _can_merge_entries(current: SubtitleEntry, next_entry: SubtitleEntry) -> bool:
    if _metadata_signature(current) != _metadata_signature(next_entry):
        return False
    time_diff = (next_entry.timestamp - current.timestamp).total_seconds()
    return time_diff <= 10


def reflow_subtitles(subtitles: list[SubtitleEntry]) -> list[SubtitleEntry]:
    """
    자막 리스트를 메타데이터 손실 없이 재정렬(Reflow)합니다.

    기능:
    1. 텍스트 내 포함된 타임스탬프([HH:MM:SS])를 감지하여 새로운 자막 엔트리로 분리합니다.
    2. 문장 부호(. ? !) 기준으로 문장을 분리합니다.
    3. 문장 부호로 끝나지 않는 짧은 라인들을 메타데이터가 같은 경우에만 병합합니다.
    """
    if not subtitles:
        return []

    expanded_entries = _expand_entries(subtitles)
    if not expanded_entries:
        return []

    result_entries: list[SubtitleEntry] = []
    current_buffer = expanded_entries[0][0].clone()

    for next_entry, next_has_hard_boundary in expanded_entries[1:]:
        buffer_text = current_buffer.text.strip()
        if (
            buffer_text.endswith(_MERGE_ENDERS)
            or next_has_hard_boundary
            or not _can_merge_entries(
            current_buffer, next_entry
            )
        ):
            result_entries.append(current_buffer)
            current_buffer = next_entry.clone()
            continue

        merged_text = f"{buffer_text} {next_entry.text.strip()}".strip()
        current_buffer.update_text(merged_text)
        current_buffer.end_time = next_entry.end_time

    if current_buffer.text.strip():
        result_entries.append(current_buffer)

    return result_entries
