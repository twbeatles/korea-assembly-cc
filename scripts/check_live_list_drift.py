from __future__ import annotations

import argparse
import json
import re
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


def _normalize_label(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", str(value or "")).lower()


def _extract_xcode_from_url(url: object) -> str:
    marker = "xcode="
    text = str(url or "")
    if marker not in text:
        return ""
    return _normalize_code(text.split(marker, 1)[1].split("&", 1)[0])


def _preset_xcodes() -> set[str]:
    codes: set[str] = set()
    for url in Config.DEFAULT_COMMITTEE_PRESETS.values():
        normalized = _extract_xcode_from_url(url)
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


def _config_name_to_code() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for name, code in Config.COMMITTEE_XCODE_MAP.items():
        normalized = _normalize_code(code)
        if normalized:
            mapping[str(name)] = normalized
    for name, url in Config.DEFAULT_COMMITTEE_PRESETS.items():
        normalized = _extract_xcode_from_url(url)
        if normalized:
            mapping.setdefault(str(name), normalized)
    return dict(sorted(mapping.items(), key=lambda item: (item[1], item[0])))


def _config_alias_to_code(config_name_to_code: dict[str, str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for alias, canonical in Config.COMMITTEE_ABBREVIATIONS.items():
        code = config_name_to_code.get(str(canonical))
        if code:
            aliases[str(alias)] = code
    return dict(sorted(aliases.items(), key=lambda item: (item[1], item[0])))



def _code_to_unique_field_values(
    rows: list[object],
    field: str,
    *,
    skip_default_name: bool = False,
) -> dict[str, list[str]]:
    values: dict[str, set[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = _normalize_code(row.get("xcode"))
        value = str(row.get(field, "") or "").strip()
        if not code or not value:
            continue
        if skip_default_name and value == "이름 없음":
            continue
        values.setdefault(code, set()).add(value)
    return {code: sorted(items) for code, items in sorted(values.items())}


def _labels_match(expected_labels: list[str], api_texts: list[str]) -> bool:
    expected = [
        _normalize_label(label)
        for label in expected_labels
        if len(_normalize_label(label)) >= 2
    ]
    actual = [
        _normalize_label(text)
        for text in api_texts
        if len(_normalize_label(text)) >= 2
    ]
    for expected_label in expected:
        for actual_text in actual:
            if expected_label in actual_text or actual_text in expected_label:
                return True
    return False


def _build_name_mismatch(
    *,
    config_name_to_code: dict[str, str],
    config_alias_to_code: dict[str, str],
    api_code_to_names: dict[str, list[str]],
    api_code_to_descriptions: dict[str, list[str]],
) -> list[dict[str, object]]:
    aliases_by_code: dict[str, list[str]] = {}
    for alias, code in config_alias_to_code.items():
        aliases_by_code.setdefault(code, []).append(alias)

    mismatches: list[dict[str, object]] = []
    for config_name, code in config_name_to_code.items():
        api_names = api_code_to_names.get(code, [])
        api_descriptions = api_code_to_descriptions.get(code, [])
        api_texts = [*api_names, *api_descriptions]
        if not api_texts:
            continue
        labels = [config_name, *aliases_by_code.get(code, [])]
        if _labels_match(labels, api_texts):
            continue
        mismatches.append(
            {
                "code": code,
                "config_name": config_name,
                "config_aliases": sorted(aliases_by_code.get(code, [])),
                "api_names": api_names,
                "api_descriptions": api_descriptions,
            }
        )
    return mismatches


def _build_drift_report_from_payload(payload: dict[str, object]) -> dict[str, object]:
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
    api_code_to_names = _code_to_unique_field_values(
        rows,
        "xname",
        skip_default_name=True,
    )
    api_code_to_descriptions = _code_to_unique_field_values(rows, "xdesc")
    config_name_to_code = _config_name_to_code()
    config_alias_to_code = _config_alias_to_code(config_name_to_code)
    name_mismatch = _build_name_mismatch(
        config_name_to_code=config_name_to_code,
        config_alias_to_code=config_alias_to_code,
        api_code_to_names=api_code_to_names,
        api_code_to_descriptions=api_code_to_descriptions,
    )
    return {
        "ok": True,
        "row_count": len(rows),
        "dropped_rows": int(payload.get("dropped_rows", 0) or 0),
        "api_codes": api_codes,
        "config_codes": config_codes,
        "missing_in_config": missing_in_config,
        "config_not_in_api": config_not_in_api,
        "api_code_to_names": api_code_to_names,
        "api_code_to_descriptions": api_code_to_descriptions,
        "config_name_to_code": config_name_to_code,
        "config_alias_to_code": config_alias_to_code,
        "name_mismatch": name_mismatch,
        "name_drift": bool(name_mismatch),
        "drift": bool(missing_in_config or config_not_in_api),
    }


def build_drift_report(timeout: float = 10.0) -> dict[str, object]:
    request = Request(build_live_list_url(), headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = parse_live_list_payload(response.read())
    return _build_drift_report_from_payload(payload)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="국회 live_list drift report")
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="xcode 집합 drift가 있으면 non-zero로 종료합니다.",
    )
    parser.add_argument(
        "--fail-on-name-drift",
        action="store_true",
        help="xcode 명칭 drift가 있으면 non-zero로 종료합니다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
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
    if bool(report.get("drift")) and args.fail_on_drift:
        return 2
    if bool(report.get("name_drift")) and args.fail_on_name_drift:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
