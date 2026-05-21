from __future__ import annotations

from typing import cast

from core.config import Config
import scripts.check_live_list_drift as drift_mod


def _config_rows(*, name_override: dict[str, str] | None = None) -> list[dict[str, str]]:
    overrides = name_override or {}
    seen_codes: set[str] = set()
    rows: list[dict[str, str]] = []
    for name, code in Config.COMMITTEE_XCODE_MAP.items():
        normalized_code = str(code).strip().upper()
        if not normalized_code or normalized_code in seen_codes:
            continue
        seen_codes.add(normalized_code)
        rows.append(
            {
                "xstat": "1",
                "xcgcd": f"LIVE{normalized_code}",
                "xcode": normalized_code,
                "xname": overrides.get(str(name), str(name)),
                "xdesc": "",
                "time": "",
            }
        )
    return rows


def test_drift_report_keeps_code_drift_compatibility_and_adds_name_fields():
    report = drift_mod._build_drift_report_from_payload(
        {"ok": True, "result": _config_rows(), "dropped_rows": 0}
    )

    assert report["drift"] is False
    assert report["name_drift"] is False
    assert report["name_mismatch"] == []
    api_code_to_names = cast(dict[str, list[str]], report["api_code_to_names"])
    config_name_to_code = cast(dict[str, str], report["config_name_to_code"])
    config_alias_to_code = cast(dict[str, str], report["config_alias_to_code"])
    assert api_code_to_names["10"] == ["본회의"]
    assert config_name_to_code["본회의"] == "10"
    assert config_alias_to_code["법사위"] == "25"


def test_drift_report_detects_name_mismatch_without_changing_code_drift():
    report = drift_mod._build_drift_report_from_payload(
        {
            "ok": True,
            "result": _config_rows(name_override={"본회의": "전혀다른채널"}),
            "dropped_rows": 0,
        }
    )

    assert report["drift"] is False
    assert report["name_drift"] is True
    name_mismatch = cast(list[dict[str, object]], report["name_mismatch"])
    assert any(
        item["code"] == "10" and item["config_name"] == "본회의"
        for item in name_mismatch
    )


def test_drift_report_detects_code_set_drift():
    rows = _config_rows()
    rows.append(
        {
            "xstat": "1",
            "xcgcd": "LIVEZZ",
            "xcode": "ZZ",
            "xname": "신규채널",
            "xdesc": "",
            "time": "",
        }
    )

    report = drift_mod._build_drift_report_from_payload(
        {"ok": True, "result": rows, "dropped_rows": 0}
    )

    assert report["drift"] is True
    assert report["missing_in_config"] == ["ZZ"]


def test_drift_report_main_strict_flags_return_nonzero(monkeypatch):
    monkeypatch.setattr(
        drift_mod,
        "build_drift_report",
        lambda: {"ok": True, "drift": True, "name_drift": False},
    )

    assert drift_mod.main(["--fail-on-drift"]) == 2

    monkeypatch.setattr(
        drift_mod,
        "build_drift_report",
        lambda: {"ok": True, "drift": False, "name_drift": True},
    )

    assert drift_mod.main(["--fail-on-name-drift"]) == 3
