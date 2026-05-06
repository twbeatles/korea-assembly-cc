import os
from urllib.request import urlopen

import pytest

from core.live_list import build_live_list_url, parse_live_list_payload


def test_live_list_contract_smoke():
    if os.environ.get("RUN_LIVE_SMOKE") != "1":
        pytest.skip("RUN_LIVE_SMOKE=1일 때만 실제 국회 live_list 계약을 확인합니다.")

    with urlopen(build_live_list_url(), timeout=10) as response:
        payload = response.read()

    parsed = parse_live_list_payload(payload)

    assert parsed["ok"] is True
    rows = parsed["result"]
    assert isinstance(rows, list)
    if rows:
        first = rows[0]
        assert {"xstat", "xcgcd", "xcode", "xname", "xdesc", "time"} <= set(first)
