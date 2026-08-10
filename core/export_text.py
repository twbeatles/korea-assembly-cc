# -*- coding: utf-8 -*-
"""내보내기 공통 텍스트·타임코드 정규화.

SRT/VTT 큐 경계, HWPX XML 1.0, 문서 본문 제어문자를 형식별로 안전하게 만든다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

# XML 1.0 허용 문자: #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD]
# (상위 플레인은 Python str 에서 대부분 유효; 여기선 제어문자·비문자 위주 제거)
_ILLEGAL_XML_CHARS_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\uFFFE\uFFFF]"
)
# SRT/VTT 큐 본문에서 큐 경계를 깨는 연속 빈 줄
_BLANK_LINE_RUN_RE = re.compile(r"\n{2,}")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")

DEFAULT_CUE_FALLBACK_SECONDS = 3.0


def strip_illegal_xml_chars(text: object) -> str:
    """XML 1.0에서 금지된 제어문자·비문자를 제거한다."""
    value = str(text or "")
    if not value:
        return ""
    return _ILLEGAL_XML_CHARS_RE.sub("", value)


def sanitize_document_text(text: object) -> str:
    """DOCX/HWP/HWPX/TXT 본문용: 제어문자·zero-width 제거, 개행 정규화는 호출측."""
    value = strip_illegal_xml_chars(text)
    if not value:
        return ""
    return _ZERO_WIDTH_RE.sub("", value)


def sanitize_subtitle_cue_text(text: object) -> str:
    """SRT/VTT 큐 본문: 제어문자 제거 + 내부 빈 줄 붕괴 + 양끝 공백 정리."""
    value = sanitize_document_text(text)
    if not value:
        return ""
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    # 큐 내부 빈 줄은 파서가 다음 큐로 오인하므로 단일 개행으로 축소
    collapsed = _BLANK_LINE_RUN_RE.sub("\n", normalized)
    # 각 줄 끝 공백 정리 (내용 손실 없이)
    lines = [line.rstrip() for line in collapsed.split("\n")]
    return "\n".join(lines).strip()


def resolve_cue_time_range(
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    timestamp: datetime,
    *,
    fallback_seconds: float = DEFAULT_CUE_FALLBACK_SECONDS,
) -> Tuple[datetime, datetime]:
    """SRT/VTT용 유효한 (start, end)를 만든다.

    - start/end 가 모두 있고 end > start 이면 그대로 사용
    - 그 외에는 timestamp(또는 start) 기준으로 fallback 길이 적용
    """
    if fallback_seconds <= 0:
        fallback_seconds = DEFAULT_CUE_FALLBACK_SECONDS

    base = start_time if isinstance(start_time, datetime) else timestamp
    if not isinstance(base, datetime):
        base = datetime.now()

    if (
        isinstance(start_time, datetime)
        and isinstance(end_time, datetime)
        and end_time > start_time
    ):
        return start_time, end_time

    end = base + timedelta(seconds=fallback_seconds)
    return base, end


def format_srt_timestamp(value: datetime) -> str:
    return (
        f"{value.strftime('%H:%M:%S')},"
        f"{value.microsecond // 1000:03d}"
    )


def format_vtt_timestamp(value: datetime) -> str:
    return (
        f"{value.strftime('%H:%M:%S')}."
        f"{value.microsecond // 1000:03d}"
    )


def normalize_hwp_insert_text(text: object) -> str:
    """HWP InsertText용: 개행을 \\r\\n 으로 통일하고 제어문자를 제거한다."""
    value = sanitize_document_text(text)
    if not value:
        return ""
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
