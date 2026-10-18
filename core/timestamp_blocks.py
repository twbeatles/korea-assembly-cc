# -*- coding: utf-8 -*-
"""타임스탬프 블록 표시 규칙 (화면 렌더링 · 텍스트 계열 export 공통).

- 블록은 직전 블록 시작 시각으로부터 ``interval_seconds`` 이상 지난 엔트리에서 시작한다.
- ``merge_blocks``(자동 줄넘김 정리)가 켜지면 같은 블록 안의 엔트리 텍스트를
  한 문단으로 이어 붙이고, 블록마다 ``[HH:MM:SS]``를 한 번 표기한다.
- 저장된 ``SubtitleEntry`` 자체는 변경하지 않는다 (SRT/VTT/JSON/DB 타이밍 보존).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Iterator, NamedTuple

from core.config import Config
from core.text_utils import flatten_subtitle_text

_NO_SPACE_BEFORE = frozenset(".,!?;:)]}%\"'”’…")
_NO_SPACE_AFTER = frozenset("([{<\"'“‘")


def format_interval_label(seconds: int) -> str:
    seconds = int(seconds)
    if seconds % 60 == 0:
        return f"{seconds // 60}분"
    return f"{seconds}초"


def normalize_block_interval(value: object) -> int:
    """허용된 간격 값만 통과시키고 나머지는 기본값으로 되돌린다."""
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        return int(Config.TIMESTAMP_BLOCK_INTERVAL_DEFAULT)
    if seconds in Config.TIMESTAMP_BLOCK_INTERVAL_CHOICES:
        return seconds
    return int(Config.TIMESTAMP_BLOCK_INTERVAL_DEFAULT)


@dataclass(frozen=True, slots=True)
class DisplayLayout:
    """UI 스레드에서 스냅샷해 백그라운드 export로 넘기는 표시 옵션."""

    merge_blocks: bool = bool(Config.AUTO_CLEAN_NEWLINES_DEFAULT)
    interval_seconds: int = int(Config.TIMESTAMP_BLOCK_INTERVAL_DEFAULT)


class DisplayRow(NamedTuple):
    timestamp: datetime
    text: str
    print_timestamp: bool
    entry_count: int = 1


def starts_new_block(
    timestamp: datetime,
    block_start: datetime | None,
    interval_seconds: int,
) -> bool:
    if block_start is None:
        return True
    return (timestamp - block_start).total_seconds() >= interval_seconds


def block_join_separator(left: str, right: str) -> str:
    """두 조각을 이을 때 사이에 넣을 문자열 (문장부호 앞/여는 괄호 뒤는 공백 없음)."""
    if not left or not right:
        return ""
    if right[0] in _NO_SPACE_BEFORE or left[-1] in _NO_SPACE_AFTER:
        return ""
    return " "


def join_block_text(base: str, addition: str) -> str:
    left = str(base or "").rstrip()
    right = str(addition or "").lstrip()
    if not left:
        return right
    if not right:
        return left
    return left + block_join_separator(left, right) + right


def iter_display_rows(
    rows: Iterable[tuple[datetime, str]],
    layout: DisplayLayout | None = None,
) -> Iterator[DisplayRow]:
    """(timestamp, text) 스트림을 표시용 행으로 변환한다.

    merge 모드: 블록당 1행(텍스트 이어 붙임, 항상 타임스탬프 표기).
    일반 모드: 엔트리당 1행, 블록 시작 엔트리에만 타임스탬프 표기.
    """
    active = layout or DisplayLayout()
    interval = normalize_block_interval(active.interval_seconds)
    block_start: datetime | None = None

    if not active.merge_blocks:
        for timestamp, text in rows:
            if not str(text or "").strip():
                continue
            new_block = starts_new_block(timestamp, block_start, interval)
            if new_block:
                block_start = timestamp
            yield DisplayRow(timestamp, text, new_block, 1)
        return

    block_text = ""
    block_count = 0
    for timestamp, text in rows:
        piece = flatten_subtitle_text(str(text or ""))
        if not piece:
            continue
        if starts_new_block(timestamp, block_start, interval):
            if block_start is not None and block_text:
                yield DisplayRow(block_start, block_text, True, block_count)
            block_start = timestamp
            block_text = piece
            block_count = 1
            continue
        block_text = join_block_text(block_text, piece)
        block_count += 1
    if block_start is not None and block_text:
        yield DisplayRow(block_start, block_text, True, block_count)


def build_plain_text(
    rows: Iterable[tuple[datetime, str]],
    layout: DisplayLayout | None = None,
    *,
    with_timestamps: bool = False,
) -> str:
    lines: list[str] = []
    for row in iter_display_rows(rows, layout):
        text = row.text.strip()
        if not text:
            continue
        if with_timestamps and row.print_timestamp:
            lines.append(f"[{row.timestamp.strftime('%H:%M:%S')}] {text}")
        else:
            lines.append(text)
    return "\n".join(lines)
