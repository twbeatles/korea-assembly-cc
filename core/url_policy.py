# -*- coding: utf-8 -*-
from __future__ import annotations

from urllib.parse import urlsplit


_ALLOWED_ASSEMBLY_HOST = "assembly.webcast.go.kr"


def is_allowed_assembly_host(host: object) -> bool:
    normalized_host = str(host or "").strip().lower().rstrip(".")
    return normalized_host == _ALLOWED_ASSEMBLY_HOST or normalized_host.endswith(
        f".{_ALLOWED_ASSEMBLY_HOST}"
    )


def validate_assembly_url(url: object) -> tuple[str | None, str | None]:
    normalized_url = str(url or "").strip()
    if not normalized_url:
        return None, "프리셋 URL을 입력하세요."

    try:
        parsed = urlsplit(normalized_url)
    except Exception:
        return None, "올바른 프리셋 URL을 입력하세요."

    scheme = str(parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return None, "프리셋 URL은 http:// 또는 https://만 허용됩니다."

    if not is_allowed_assembly_host(parsed.hostname):
        return None, "프리셋 URL은 assembly.webcast.go.kr 계열만 허용됩니다."

    return normalized_url, None


def sanitize_url_history(data: object, max_items: int) -> tuple[dict[str, str], int]:
    if isinstance(data, dict):
        raw_items = list(data.items())
    elif isinstance(data, list):
        raw_items = [(item, "") for item in data]
    else:
        return {}, 1 if data not in ({}, [], None) else 0

    sanitized: dict[str, str] = {}
    dropped = 0
    for raw_url, raw_tag in raw_items:
        normalized_url, _error = validate_assembly_url(raw_url)
        if normalized_url is None:
            dropped += 1
            continue
        tag = raw_tag.strip() if isinstance(raw_tag, str) else ""
        if normalized_url in sanitized:
            sanitized.pop(normalized_url, None)
        sanitized[normalized_url] = tag

    try:
        limit = int(max_items)
    except (TypeError, ValueError):
        limit = 0
    if limit > 0 and len(sanitized) > limit:
        overflow = len(sanitized) - limit
        kept_items = list(sanitized.items())[-limit:]
        sanitized = dict(kept_items)
        dropped += overflow

    return sanitized, dropped
