from __future__ import annotations

from pathlib import Path

from core.config import Config
from core.url_policy import (
    is_allowed_assembly_host,
    sanitize_url_history,
    validate_assembly_url,
)


def test_url_policy_accepts_only_assembly_webcast_hosts():
    assert is_allowed_assembly_host("assembly.webcast.go.kr") is True
    assert is_allowed_assembly_host("sub.assembly.webcast.go.kr.") is True
    assert is_allowed_assembly_host("example.com") is False
    assert is_allowed_assembly_host("assembly.webcast.go.kr.evil.test") is False


def test_validate_assembly_url_allows_default_url_and_rejects_external_values():
    assert validate_assembly_url(Config.DEFAULT_URL) == (Config.DEFAULT_URL, None)

    assert validate_assembly_url("https://example.com/live") == (
        None,
        "프리셋 URL은 assembly.webcast.go.kr 계열만 허용됩니다.",
    )
    assert validate_assembly_url("ftp://assembly.webcast.go.kr/main/player.asp") == (
        None,
        "프리셋 URL은 http:// 또는 https://만 허용됩니다.",
    )


def test_sanitize_url_history_drops_invalid_non_string_and_overflow_entries():
    sanitized, dropped = sanitize_url_history(
        {
            "https://example.com/live": "외부",
            "https://assembly.webcast.go.kr/main/player.asp?xcode=10": "본회의",
            123: "숫자URL",
            "https://assembly.webcast.go.kr/main/player.asp?xcode=25": object(),
        },
        1,
    )

    assert sanitized == {
        "https://assembly.webcast.go.kr/main/player.asp?xcode=25": ""
    }
    assert dropped == 3


def test_initial_layout_uses_config_default_url_for_empty_history():
    source = Path("ui/main_window_impl/ui/layout.py").read_text(encoding="utf-8")

    assert "self.url_combo.addItem(Config.DEFAULT_URL)" in source
    assert (
        'self.url_combo.addItem("https://assembly.webcast.go.kr/main/player.asp")'
        not in source
    )
