from __future__ import annotations

from core.committee_catalog import (
    build_committee_catalog,
    canonical_committee_name,
    normalize_committee_label,
)
from core.config import Config
from core.live_list import apply_live_broadcast_to_url, select_live_broadcast_row


def test_normalize_committee_label_strips_separators():
    assert normalize_committee_label("청문회/공청회") == "청문회공청회"
    assert normalize_committee_label(" 기후노동위 ") == "기후노동위"


def test_catalog_maps_current_and_legacy_hearing_xcodes_to_same_identity():
    catalog = build_committee_catalog()

    assert catalog.identity_for_xcode("97") == "청문회/공청회"
    assert catalog.identity_for_xcode("99") == "청문회/공청회"
    assert catalog.identity_for_name("청문회") == "청문회/공청회"
    assert catalog.identity_for_name("청문회/공청회") == "청문회/공청회"


def test_catalog_maps_climate_committee_aliases_to_official_name():
    catalog = build_committee_catalog()

    assert catalog.identity_for_xcode("62") == "기후에너지환경노동위원회"
    assert catalog.identity_for_name("기후노동위") == "기후에너지환경노동위원회"
    assert catalog.identity_for_name("환노위") == "기후에너지환경노동위원회"
    assert catalog.identity_for_name("기후환경노동위원회") == "기후에너지환경노동위원회"
    assert canonical_committee_name("기후환경노동위원회") == "기후에너지환경노동위원회"


def test_config_uses_live_list_hearing_and_climate_names():
    assert Config.COMMITTEE_XCODE_MAP["청문회/공청회"] == 97
    assert Config.DEFAULT_COMMITTEE_PRESETS["청문회/공청회"].endswith("xcode=97")
    assert Config.COMMITTEE_XCODE_MAP["기후에너지환경노동위원회"] == 62
    assert "기후환경노동위원회" not in Config.COMMITTEE_XCODE_MAP
    assert Config.COMMITTEE_ABBREVIATIONS["기후노동위"] == "기후에너지환경노동위원회"
    assert Config.COMMITTEE_ABBREVIATIONS["기후환경노동위원회"] == "기후에너지환경노동위원회"
    assert Config.LEGACY_COMMITTEE_XCODES["99"] == "청문회/공청회"


def test_select_live_broadcast_row_matches_legacy_xcode_by_committee_identity():
    selection = select_live_broadcast_row(
        [
            {
                "xstat": "1",
                "xcgcd": "DCM000097224390101",
                "xcode": "97",
                "xname": "청문회/공청회",
                "xdesc": "개의",
                "time": "",
            },
            {
                "xstat": "1",
                "xcgcd": "DCM000048224390101",
                "xcode": "48",
                "xname": "외통위",
                "xdesc": "개의",
                "time": "",
            },
        ],
        target_xcode="99",
    )

    assert selection["ok"] is True
    assert selection["reason"] == "committee_identity"
    row = selection.get("row")
    assert isinstance(row, dict)
    assert row["xcode"] == "97"
    assert row["xcgcd"] == "DCM000097224390101"


def test_select_live_broadcast_row_matches_renamed_committee_by_live_list_alias():
    selection = select_live_broadcast_row(
        [
            {
                "xstat": "1",
                "xcgcd": "DCM000062224390101",
                "xcode": "62",
                "xname": "기후노동위",
                "xdesc": "개의",
                "time": "",
            }
        ],
        target_xcode="62",
    )

    assert selection["ok"] is True
    row = selection.get("row")
    assert isinstance(row, dict)
    assert row["xcgcd"] == "DCM000062224390101"


def test_select_live_broadcast_row_rewrites_stale_xcode_in_url():
    selection = select_live_broadcast_row(
        [
            {
                "xstat": "1",
                "xcgcd": "DCM000097224390101",
                "xcode": "97",
                "xname": "청문회/공청회",
                "xdesc": "개의",
                "time": "",
            }
        ],
        target_xcode="99",
    )
    row = selection.get("row")
    assert isinstance(row, dict)

    resolved = apply_live_broadcast_to_url(
        "https://assembly.webcast.go.kr/main/player.asp?xcode=99",
        row,
    )
    assert "xcode=97" in resolved
    assert "xcgcd=DCM000097224390101" in resolved


def test_select_live_broadcast_row_matches_legacy_finance_xcode_to_current_live_row():
    selection = select_live_broadcast_row(
        [
            {
                "xstat": "1",
                "xcgcd": "DCM000065224390101",
                "xcode": "65",
                "xname": "재경위",
                "xdesc": "개의",
                "time": "",
            }
        ],
        target_xcode="38",
    )

    assert selection["ok"] is True
    assert selection["reason"] == "committee_identity"
    row = selection.get("row")
    assert isinstance(row, dict)
    assert row["xcode"] == "65"


def test_select_live_broadcast_row_still_requires_target_xcode():
    selection = select_live_broadcast_row(
        [
            {
                "xstat": "1",
                "xcgcd": "LIVE001",
                "xcode": "97",
                "xname": "청문회/공청회",
                "time": "",
            }
        ]
    )

    assert selection["ok"] is False
    assert selection["reason"] == "target_xcode_required"


def test_select_live_broadcast_row_refuses_ambiguous_identity_matches():
    selection = select_live_broadcast_row(
        [
            {
                "xstat": "1",
                "xcgcd": "LIVE001",
                "xcode": "97",
                "xname": "청문회/공청회",
                "time": "",
            },
            {
                "xstat": "1",
                "xcgcd": "LIVE002",
                "xcode": "96",
                "xname": "청문회",
                "time": "",
            },
        ],
        target_xcode="99",
    )

    assert selection["ok"] is False
    assert selection["reason"] == "ambiguous_xcode"
    assert selection["candidate_count"] == 2
