from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import Config
from core.live_list import build_live_list_url, parse_live_list_payload


def _normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


def _preset_xcodes() -> set[str]:
    codes: set[str] = set()
    for url in Config.DEFAULT_COMMITTEE_PRESETS.values():
        marker = "xcode="
        if marker not in str(url):
            continue
        code = str(url).split(marker, 1)[1].split("&", 1)[0]
        normalized = _normalize_code(code)
        if normalized:
            codes.add(normalized)
    return codes


def _config_xcodes() -> set[str]:
    codes = {
        _normalize_code(value)
        for value in Config.COMMITTEE_XCODE_MAP.values()
        if value is not None and _normalize_code(value)
    }
    codes.update(_preset_xcodes())
    return codes


def build_drift_report(timeout: float = 10.0) -> dict[str, object]:
    request = Request(build_live_list_url(), headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = parse_live_list_payload(response.read())

    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError(
            f"live_list schema/network failure: "
            f"{payload.get('error_type', 'unknown') if isinstance(payload, dict) else 'unknown'} "
            f"{payload.get('error', '') if isinstance(payload, dict) else ''}"
        )

    rows = payload.get("result") or []
    if not isinstance(rows, list):
        raise RuntimeError("live_list result is not a list")

    api_codes = sorted(
        {
            _normalize_code(row.get("xcode"))
            for row in rows
            if isinstance(row, dict) and _normalize_code(row.get("xcode"))
        }
    )
    config_codes = sorted(_config_xcodes())
    missing_in_config = sorted(set(api_codes) - set(config_codes))
    config_not_in_api = sorted(set(config_codes) - set(api_codes))
    return {
        "ok": True,
        "row_count": len(rows),
        "dropped_rows": int(payload.get("dropped_rows", 0) or 0),
        "api_codes": api_codes,
        "config_codes": config_codes,
        "missing_in_config": missing_in_config,
        "config_not_in_api": config_not_in_api,
        "drift": bool(missing_in_config or config_not_in_api),
    }


def main() -> int:
    try:
        report = build_drift_report()
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
