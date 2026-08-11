# -*- coding: utf-8 -*-
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from core.config import Config
from core.live_list import normalize_live_xcgcd, normalize_live_xcode


_ALLOWED_ASSEMBLY_HOST = "assembly.webcast.go.kr"
_PRESS_PLAYER_PATH = "/main/pressplayer.asp"
_PLAYER_PATH = "/main/player.asp"


def is_press_player_url(url: object) -> bool:
    """기자회견 중계 URL 여부 (pressplayer.asp). xcgcd/xcode 감지를 건너뛰어야 하는 URL."""
    try:
        parsed = urlsplit(str(url or "").strip())
        return (
            is_allowed_assembly_host(parsed.hostname)
            and parsed.path.lower().rstrip("/") == _PRESS_PLAYER_PATH.rstrip("/")
        )
    except Exception:
        return False


def is_allowed_assembly_host(host: object) -> bool:
    normalized_host = str(host or "").strip().lower().rstrip(".")
    return normalized_host == _ALLOWED_ASSEMBLY_HOST or normalized_host.endswith(
        f".{_ALLOWED_ASSEMBLY_HOST}"
    )


def validate_assembly_url(url: object) -> tuple[str | None, str | None]:
    normalized_url = str(url or "").strip()
    if len(normalized_url) > int(Config.MAX_URL_LENGTH):
        return None, "URL length exceeds the allowed limit."
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

    if parsed.username or parsed.password:
        return None, "URL user information is not allowed."
    try:
        port = parsed.port
    except ValueError:
        return None, "Invalid URL port."
    default_port = 443 if scheme == "https" else 80
    if port is not None and port != default_port:
        return None, "Non-standard ports are not allowed."

    path_lower = (parsed.path or "/").lower().rstrip("/") or "/"
    if path_lower not in {_PLAYER_PATH, _PRESS_PLAYER_PATH}:
        return None, "Unsupported assembly player path."
    if parsed.fragment:
        return None, "URL fragments are not allowed."

    normalized_query: list[tuple[str, str]] = []
    seen_live_keys: set[str] = set()
    for raw_name, raw_value in parse_qsl(parsed.query, keep_blank_values=True):
        name = str(raw_name).strip()
        lowered_name = name.lower()
        if lowered_name in ("xcode", "xcgcd"):
            if lowered_name in seen_live_keys:
                return None, f"Duplicate {lowered_name} parameter."
            seen_live_keys.add(lowered_name)
            value = (
                normalize_live_xcode(raw_value)
                if lowered_name == "xcode"
                else normalize_live_xcgcd(raw_value)
            )
            if not value:
                return None, f"Invalid {lowered_name} value."
            normalized_query.append((lowered_name, value))
        else:
            normalized_query.append((name, raw_value))

    host = str(parsed.hostname or "").lower().rstrip(".")
    return urlunsplit(
        (scheme, host, path_lower, urlencode(normalized_query, doseq=True), "")
    ), None


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
        if len(tag) > int(Config.MAX_HISTORY_TAG_LENGTH):
            dropped += 1
            continue
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
