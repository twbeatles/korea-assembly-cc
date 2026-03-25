import json
from datetime import datetime

import pytest

from core.models import SubtitleEntry

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


def test_subtitle_entry_from_dict_rejects_non_dict():
    with pytest.raises(ValueError):
        SubtitleEntry.from_dict("not-a-dict")


def test_deserialize_subtitles_skips_corrupted_items():
    win = MainWindow.__new__(MainWindow)

    items = [
        {"text": "정상 자막", "timestamp": "2026-02-12T10:00:00"},
        "잘못된 타입",
        None,
        {"text": "타임스탬프 누락"},
    ]

    parsed, skipped = MainWindow._deserialize_subtitles(
        win, items, source="test-mixed"
    )

    assert len(parsed) == 1
    assert parsed[0].text == "정상 자막"
    assert skipped == 3


def test_merge_sessions_skips_corrupted_items(tmp_path):
    win = MainWindow.__new__(MainWindow)

    valid_and_invalid = tmp_path / "mixed.json"
    valid_and_invalid.write_text(
        json.dumps(
            {
                "subtitles": [
                    {"text": "정상 항목", "timestamp": "2026-02-12T11:00:00"},
                    "깨진 항목",
                    {"timestamp": "2026-02-12T11:00:01"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    broken_json = tmp_path / "broken.json"
    broken_json.write_text("{not-json", encoding="utf-8")

    merged = MainWindow._merge_sessions(
        win,
        [str(valid_and_invalid), str(broken_json)],
        remove_duplicates=False,
        sort_by_time=True,
    )

    assert len(merged) == 1
    assert merged[0].text == "정상 항목"


def test_merge_sessions_dedup_uses_time_bucket(tmp_path):
    win = MainWindow.__new__(MainWindow)

    path = tmp_path / "bucket.json"
    path.write_text(
        json.dumps(
            {
                "subtitles": [
                    {
                        "text": "반복 발화",
                        "timestamp": "2026-02-12T11:00:05",
                    },
                    {
                        "text": "반복 발화",
                        "timestamp": "2026-02-12T11:00:20",
                    },
                    {
                        "text": "반복 발화",
                        "timestamp": "2026-02-12T11:00:40",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    merged = MainWindow._merge_sessions(
        win,
        [str(path)],
        remove_duplicates=True,
        sort_by_time=True,
    )

    assert len(merged) == 2
    assert [e.timestamp for e in merged] == [
        datetime.fromisoformat("2026-02-12T11:00:05"),
        datetime.fromisoformat("2026-02-12T11:00:40"),
    ]


def test_merge_sessions_conservative_dedup_uses_same_second(tmp_path):
    win = MainWindow.__new__(MainWindow)

    path = tmp_path / "conservative.json"
    path.write_text(
        json.dumps(
            {
                "subtitles": [
                    {
                        "text": "같은 초 반복 발화",
                        "timestamp": "2026-02-12T11:00:05.100000",
                    },
                    {
                        "text": "같은 초 반복 발화",
                        "timestamp": "2026-02-12T11:00:05.900000",
                    },
                    {
                        "text": "같은 초 반복 발화",
                        "timestamp": "2026-02-12T11:00:06.100000",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    merged = MainWindow._merge_sessions(
        win,
        [str(path)],
        remove_duplicates=True,
        sort_by_time=True,
        dedupe_mode="conservative_same_second",
    )

    assert len(merged) == 2
    assert [e.timestamp for e in merged] == [
        datetime.fromisoformat("2026-02-12T11:00:05.100000"),
        datetime.fromisoformat("2026-02-12T11:00:06.100000"),
    ]
