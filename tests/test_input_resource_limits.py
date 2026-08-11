from __future__ import annotations

import json

import pytest

from core.config import Config
from core.file_io import read_limited_json_file
from core.live_list import normalize_live_list_row, parse_live_list_payload
from core.resource_budget import ResourceLimitExceeded


def test_read_limited_json_file_checks_bytes_before_parse(tmp_path) -> None:
    path = tmp_path / "large.json"
    path.write_text(json.dumps({"value": "x" * 100}), encoding="utf-8")

    with pytest.raises(ResourceLimitExceeded):
        read_limited_json_file(path, max_bytes=32, label="preset")


def test_live_list_payload_rejects_oversized_response(monkeypatch) -> None:
    monkeypatch.setattr(Config, "LIVE_LIST_MAX_BYTES", 16)

    result = parse_live_list_payload(b"{" + b" " * 32 + b"}")

    assert result["ok"] is False
    assert result["error_type"] == "payload_too_large"


def test_live_list_row_rejects_oversized_strings(monkeypatch) -> None:
    monkeypatch.setattr(Config, "LIVE_LIST_MAX_STRING_LENGTH", 10)

    assert normalize_live_list_row({"xcode": "10", "xname": "x" * 11}) is None
