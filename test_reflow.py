from datetime import datetime, timedelta

from core.models import SubtitleEntry
from core.utils import reflow_subtitles


def test_reflow_splits_timestamp_and_keeps_non_empty_entries():
    entries = [
        SubtitleEntry("[14:21:46] 인도와 협정을 맺었습니다"),
        SubtitleEntry("이후 논의가 이어졌습니다."),
        SubtitleEntry("[14:22:49] 새로운 의제가 시작되었습니다"),
    ]

    base_time = datetime(2026, 2, 12, 14, 21, 0)
    for idx, entry in enumerate(entries):
        entry.timestamp = base_time + timedelta(seconds=idx * 5)

    reflowed = reflow_subtitles(entries)

    assert reflowed
    assert all(e.text.strip() for e in reflowed)
    assert any(
        e.timestamp.hour == 14 and e.timestamp.minute == 22 and e.timestamp.second == 49
        for e in reflowed
    )
