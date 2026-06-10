from __future__ import annotations

import json
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


LIVE_LIST_API_URL = "https://assembly.webcast.go.kr/main/service/live_list.asp"
_LIVE_XCODE_PATTERN = re.compile(r"^[A-Za-z0-9]{1,10}$")
_LIVE_XCGCD_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def build_live_list_url(now_ts: int | None = None) -> str:
    token = int(time.time()) if now_ts is None else int(now_ts)
    return f"{LIVE_LIST_API_URL}?vv={token}"


def _normalize_live_token(value: object, pattern: re.Pattern[str]) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if not pattern.fullmatch(normalized):
        return ""
    return normalized


def normalize_live_xcode(value: object) -> str:
    return _normalize_live_token(value, _LIVE_XCODE_PATTERN)


def normalize_live_xcgcd(value: object) -> str:
    return _normalize_live_token(value, _LIVE_XCGCD_PATTERN)


def set_live_query_param(original_url: str, name: str, value: object) -> str:
    url = str(original_url or "").strip().rstrip("&")
    normalized_name = str(name or "").strip().lower()
    if normalized_name == "xcode":
        normalized_value = normalize_live_xcode(value)
    elif normalized_name == "xcgcd":
        normalized_value = normalize_live_xcgcd(value)
    else:
        return url
    if not normalized_value:
        return url

    parsed = urlsplit(url)
    query_pairs = [
        (key, current_value)
        for key, current_value in parse_qsl(parsed.query, keep_blank_values=True)
        if str(key).lower() != normalized_name
    ]
    query_pairs.append((normalized_name, normalized_value))
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query_pairs, doseq=True),
            parsed.fragment,
        )
    )


def normalize_live_list_row(item: object) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    raw_xcgcd = str(item.get("xcgcd", "") or "").strip()
    raw_xcode = str(item.get("xcode", "") or "").strip()
    xcgcd = normalize_live_xcgcd(raw_xcgcd)
    xcode = normalize_live_xcode(raw_xcode)
    if raw_xcgcd and not xcgcd:
        return None
    if raw_xcode and not xcode:
        return None
    xname = str(item.get("xname", "이름 없음") or "이름 없음").strip() or "이름 없음"
    xdesc = str(item.get("xdesc", "") or "").strip()
    if not any((xcgcd, xcode, xname and xname != "이름 없음", xdesc)):
        return None
    return {
        "xstat": str(item.get("xstat", "") or "").strip(),
        "xcgcd": xcgcd,
        "xcode": xcode,
        "xname": xname,
        "xdesc": xdesc,
        "time": str(item.get("time", "") or "").strip(),
    }


def make_live_list_error_payload(
    error_type: str,
    error: str,
    *,
    dropped_rows: int = 0,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": False,
        "error": str(error or "알 수 없는 오류"),
        "error_type": str(error_type or "unknown"),
    }
    if dropped_rows > 0:
        payload["dropped_rows"] = int(dropped_rows)
    return payload


def parse_live_list_payload(payload: bytes) -> dict[str, object]:
    try:
        decoded = payload.decode("utf-8", errors="replace")
        data = json.loads(decoded)
    except Exception as exc:
        return make_live_list_error_payload("invalid_json", str(exc))

    if not isinstance(data, dict):
        return make_live_list_error_payload(
            "invalid_schema",
            "응답 루트가 객체(dict)가 아닙니다.",
        )

    rows = data.get("xlist")
    if not isinstance(rows, list):
        return make_live_list_error_payload(
            "invalid_schema",
            "응답의 xlist가 목록(list)이 아닙니다.",
        )

    valid_rows: list[dict[str, str]] = []
    dropped_rows = 0
    for item in rows:
        normalized = normalize_live_list_row(item)
        if normalized is None:
            dropped_rows += 1
            continue
        valid_rows.append(normalized)

    if not valid_rows and rows:
        return make_live_list_error_payload(
            "invalid_schema",
            f"유효한 방송 항목이 없습니다. (손상 항목 {dropped_rows}개)",
            dropped_rows=dropped_rows,
        )

    return {
        "ok": True,
        "result": valid_rows,
        "dropped_rows": dropped_rows,
        "error_type": "none",
    }


def is_live_broadcast_row(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    return (
        str(item.get("xstat", "")).strip() == "1"
        and bool(normalize_live_xcgcd(item.get("xcgcd", "")))
    )


def select_live_broadcast_row(
    rows: list[dict[str, str]] | object,
    *,
    target_xcode: str | None = None,
    current_xcgcd: str | None = None,
) -> dict[str, object]:
    normalized_rows: list[dict[str, str]] = []
    if isinstance(rows, list):
        for item in rows:
            normalized = normalize_live_list_row(item)
            if normalized is not None:
                normalized_rows.append(normalized)
    live_rows = [item for item in normalized_rows if is_live_broadcast_row(item)]
    target_norm = normalize_live_xcode(target_xcode).upper()
    current_norm = normalize_live_xcgcd(current_xcgcd)

    if current_norm and not target_norm:
        for row in live_rows:
            if str(row.get("xcgcd", "")).strip() == current_norm:
                return {"ok": True, "row": row, "reason": "current_xcgcd"}

    if target_norm:
        matches = [
            row
            for row in live_rows
            if str(row.get("xcode", "")).strip().upper() == target_norm
        ]
        if len(matches) == 1:
            return {"ok": True, "row": matches[0], "reason": "target_xcode"}
        if len(matches) > 1:
            return {
                "ok": False,
                "reason": "ambiguous_xcode",
                "candidate_count": len(matches),
            }
        return {"ok": False, "reason": "xcode_not_live", "candidate_count": 0}

    if live_rows:
        return {
            "ok": False,
            "reason": "target_xcode_required",
            "candidate_count": len(live_rows),
        }
    return {"ok": False, "reason": "no_live", "candidate_count": 0}


def apply_live_broadcast_to_url(original_url: str, row: dict[str, str]) -> str:
    url = str(original_url or "").strip().rstrip("&")
    for name, value in (
        ("xcgcd", normalize_live_xcgcd(row.get("xcgcd", ""))),
        ("xcode", normalize_live_xcode(row.get("xcode", ""))),
    ):
        if not value:
            continue
        url = set_live_query_param(url, name, value)
    return url


def summarize_live_selection_issue(
    reason: str,
    *,
    target_xcode: str | None = None,
    candidate_count: int = 0,
    error_type: str = "",
    error: str = "",
) -> str:
    normalized_reason = str(reason or "").strip()
    xcode = str(target_xcode or "").strip()
    if normalized_reason == "live_list_error":
        normalized_error_type = str(error_type or "unknown").strip() or "unknown"
        normalized_error = str(error or "알 수 없는 오류").strip() or "알 수 없는 오류"
        return f"live_list 조회 실패({normalized_error_type}): {normalized_error}"
    if normalized_reason == "ambiguous_xcode" and xcode:
        return (
            f"xcode={xcode}에 해당하는 생중계 후보가 {candidate_count}개여서 "
            "자동 선택을 생략했습니다. 생중계 목록에서 직접 선택하세요."
        )
    if normalized_reason == "ambiguous_live":
        return (
            f"진행 중인 생중계 후보가 {candidate_count}개여서 자동 선택을 생략했습니다. "
            "생중계 목록에서 직접 선택하세요."
        )
    if normalized_reason == "target_xcode_required":
        return (
            f"진행 중인 생중계 후보가 {candidate_count}개 있지만 xcode 대상이 없어 "
            "자동 선택을 생략했습니다. 위원회 프리셋 또는 생중계 목록에서 직접 선택하세요."
        )
    if normalized_reason == "xcode_not_live" and xcode:
        return f"xcode={xcode} 위원회의 진행 중인 생중계를 찾지 못했습니다."
    if normalized_reason == "no_live":
        return "진행 중인 생중계를 찾지 못했습니다."
    return "생중계 자동 선택을 진행하지 않았습니다."
