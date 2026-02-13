from datetime import datetime

from core.models import SubtitleEntry
from core.utils import reflow_subtitles


def test_reflow_does_not_mutate_input_entry_timestamp():
    original_timestamp = datetime(2026, 2, 12, 9, 0, 0)
    entry = SubtitleEntry("[09:10:00] 발언 시작", original_timestamp)

    result = reflow_subtitles([entry])

    assert entry.timestamp == original_timestamp
    assert result
    assert result[0].timestamp.hour == 9
    assert result[0].timestamp.minute == 10
    assert result[0].timestamp.second == 0
