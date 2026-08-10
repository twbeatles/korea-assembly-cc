# -*- coding: utf-8 -*-
"""probe JS multi-speaker 분할 규칙의 순수 Python 미러.

브라우저 execute_script 안의 collectMultiSpeakerSegments 와 동일 의미론을
단위 테스트로 고정한다. JS 수정 시 이 모듈·테스트를 함께 갱신한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class SpeakerSpanInput:
    """DOM span 한 개에 해당하는 테스트/미러 입력."""

    text: str
    speaker_color: str
    span_id: str = ""
    index: int = 0


@dataclass(frozen=True, slots=True)
class SpeakerSegment:
    text: str
    speaker_color: str
    key_suffix: str


def _compact(text: str) -> str:
    return "".join(str(text or "").split())


def collect_multi_speaker_segments(
    spans: Sequence[SpeakerSpanInput],
) -> list[SpeakerSegment]:
    """서로 다른 화자색 span 이 2개 이상일 때만 분할 결과를 반환한다.

    - 동일 색·단일 span → [] (노드 단위 1 row 유지)
    - 빈 텍스트 span 제외
    - key_suffix = span_id 또는 span{index}
    """
    segments: list[SpeakerSegment] = []
    for span in spans:
        text = " ".join(str(span.text or "").split()).strip()
        if not _compact(text):
            continue
        suffix = str(span.span_id or "").strip() or f"span{span.index}"
        segments.append(
            SpeakerSegment(
                text=text,
                speaker_color=str(span.speaker_color or "").strip(),
                key_suffix=suffix,
            )
        )
    if len(segments) <= 1:
        return []
    colors = {item.speaker_color for item in segments}
    if len(colors) <= 1:
        return []
    return segments


def build_split_node_keys(base_node_key: str, segments: Sequence[SpeakerSegment]) -> list[str]:
    return [f"{base_node_key}#{seg.key_suffix}" for seg in segments]
