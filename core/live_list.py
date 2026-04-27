from __future__ import annotations

import json
import time


LIVE_LIST_API_URL = "https://assembly.webcast.go.kr/main/service/live_list.asp"


def build_live_list_url(now_ts: int | None = None) -> str:
    token = int(time.time()) if now_ts is None else int(now_ts)
    return f"{LIVE_LIST_API_URL}?vv={token}"


def normalize_live_list_row(item: object) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    xcgcd = str(item.get("xcgcd", "") or "").strip()
    xcode = str(item.get("xcode", "") or "").strip()
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
        and bool(str(item.get("xcgcd", "")).strip())
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
    target_norm = str(target_xcode or "").strip().upper()
    current_norm = str(current_xcgcd or "").strip()

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

    if len(live_rows) == 1:
        return {"ok": True, "row": live_rows[0], "reason": "single_live"}
    if len(live_rows) > 1:
        return {
            "ok": False,
            "reason": "ambiguous_live",
            "candidate_count": len(live_rows),
        }
    return {"ok": False, "reason": "no_live", "candidate_count": 0}


def apply_live_broadcast_to_url(original_url: str, row: dict[str, str]) -> str:
    url = str(original_url or "").strip().rstrip("&")
    for name, value in (
        ("xcgcd", str(row.get("xcgcd", "")).strip()),
        ("xcode", str(row.get("xcode", "")).strip()),
    ):
        if not value:
            continue
        marker = f"{name}="
        if marker in url:
            import re

            pattern = re.compile(r"([?&])" + re.escape(name) + r"=[^&]*")
            url = pattern.sub(lambda match: f"{match.group(1)}{name}={value}", url, count=1)
            continue
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{name}={value}"
    return url


def summarize_live_selection_issue(
    reason: str,
    *,
    target_xcode: str | None = None,
    candidate_count: int = 0,
) -> str:
    normalized_reason = str(reason or "").strip()
    xcode = str(target_xcode or "").strip()
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
    if normalized_reason == "xcode_not_live" and xcode:
        return f"xcode={xcode} 위원회의 진행 중인 생중계를 찾지 못했습니다."
    if normalized_reason == "no_live":
        return "진행 중인 생중계를 찾지 못했습니다."
    return "생중계 자동 선택을 진행하지 않았습니다."
