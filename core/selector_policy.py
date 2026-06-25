# -*- coding: utf-8 -*-
from __future__ import annotations

import re

from core.config import Config

_SELECTOR_SAFE_PATTERN = re.compile(r"^[#.\w\[\]=\"':,\s>-]+$")
_SELECTOR_MAX_LEN = 300


def validate_subtitle_selector(selector: object) -> tuple[str | None, str | None]:
    """자막 CSS 선택자 기본 검증 (Selenium InvalidSelectorException 예방)."""
    normalized = str(selector or "").strip()
    if not normalized:
        return None, "CSS 선택자를 입력하세요."
    if len(normalized) > _SELECTOR_MAX_LEN:
        return None, f"CSS 선택자는 {_SELECTOR_MAX_LEN}자 이하여야 합니다."
    if normalized in Config.DEFAULT_SELECTORS:
        return normalized, None
    if not _SELECTOR_SAFE_PATTERN.fullmatch(normalized):
        return None, "허용되지 않는 문자가 포함된 CSS 선택자입니다."
    return normalized, None