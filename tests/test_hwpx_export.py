from __future__ import annotations

from datetime import datetime
from io import BytesIO
from zipfile import ZipFile

from core.hwpx_export import build_hwpx_bytes, build_hwpx_lines


def test_build_hwpx_lines_includes_title_timestamps_and_stats() -> None:
    entries = [
        (datetime(2026, 3, 23, 10, 0, 0), "첫 문장"),
        (datetime(2026, 3, 23, 10, 0, 30), "둘째 문장"),
        (datetime(2026, 3, 23, 10, 1, 5), "셋째 문장"),
    ]

    lines = build_hwpx_lines(entries, datetime(2026, 3, 23, 18, 0, 0))

    assert lines[0] == "국회 의사중계 자막"
    assert lines[1].startswith("생성 일시: 2026년 03월 23일 18:00:00")
    assert "[10:00:00] 첫 문장" in lines
    assert "둘째 문장" in lines
    assert "[10:01:05] 셋째 문장" in lines
    assert lines[-1] == "총 3문장, 14자"


def test_build_hwpx_bytes_escapes_special_characters_and_preserves_multiline() -> None:
    entries = [
        (datetime(2026, 3, 23, 10, 0, 0), "첫 줄 & 둘째 <줄>"),
        (datetime(2026, 3, 23, 10, 2, 0), "줄바꿈 첫째\n줄바꿈 둘째"),
    ]

    payload = build_hwpx_bytes(entries, datetime(2026, 3, 23, 18, 0, 0))

    with ZipFile(BytesIO(payload)) as archive:
        section_xml = archive.read("Contents/section0.xml").decode("utf-8")
        preview_text = archive.read("Preview/PrvText.txt").decode("utf-8")

    assert "&amp;" in section_xml
    assert "&lt;줄&gt;" in section_xml
    assert "첫 줄 & 둘째 <줄>" in preview_text
    assert "줄바꿈 첫째" in preview_text
    assert "줄바꿈 둘째" in preview_text
    assert "[10:02:00] 줄바꿈 첫째" in preview_text
