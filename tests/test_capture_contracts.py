from __future__ import annotations

from core.capture_contracts import LiveBroadcastResolver, SubtitleProbeReader


def test_capture_contract_protocols_are_importable():
    assert hasattr(SubtitleProbeReader, "read_subtitle_probe_by_selectors")
    assert hasattr(LiveBroadcastResolver, "detect_live_broadcast")