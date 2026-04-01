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


def test_reflow_preserves_metadata_for_unchanged_entry():
    entry = SubtitleEntry(
        "그대로 유지되는 문장입니다.",
        datetime(2026, 2, 12, 14, 30, 0),
        entry_id="entry-1",
        source_selector="#subtitle",
        source_frame_path=[1, 2],
        source_node_key="row-1",
        speaker_color="#ffcc00",
        speaker_channel="primary",
        speaker_changed=True,
    )
    entry.start_time = datetime(2026, 2, 12, 14, 30, 0)
    entry.end_time = datetime(2026, 2, 12, 14, 30, 2)

    result = reflow_subtitles([entry])

    assert len(result) == 1
    restored = result[0]
    assert restored is not entry
    assert restored.to_dict() == entry.to_dict()


def test_reflow_timestamp_split_copies_metadata_and_links_times():
    entry = SubtitleEntry(
        "머리말 [09:10:00] 첫 문장 [09:10:05] 둘째 문장",
        datetime(2026, 2, 12, 9, 0, 0),
        entry_id="entry-2",
        source_selector="#subtitle",
        source_frame_path=[0, 1],
        source_node_key="row-2",
        speaker_color="#00aaee",
        speaker_channel="secondary",
        speaker_changed=True,
    )
    entry.start_time = datetime(2026, 2, 12, 9, 0, 0)
    entry.end_time = datetime(2026, 2, 12, 9, 10, 9)

    result = reflow_subtitles([entry])

    assert [item.text for item in result] == ["머리말", "첫 문장", "둘째 문장"]
    assert [item.timestamp for item in result] == [
        datetime(2026, 2, 12, 9, 0, 0),
        datetime(2026, 2, 12, 9, 10, 0),
        datetime(2026, 2, 12, 9, 10, 5),
    ]
    assert result[0].start_time == entry.start_time
    assert result[0].end_time == datetime(2026, 2, 12, 9, 10, 0)
    assert result[1].start_time == datetime(2026, 2, 12, 9, 10, 0)
    assert result[1].end_time == datetime(2026, 2, 12, 9, 10, 5)
    assert result[2].start_time == datetime(2026, 2, 12, 9, 10, 5)
    assert result[2].end_time == entry.end_time
    assert all(item.entry_id != entry.entry_id for item in result)
    assert all(item.source_selector == entry.source_selector for item in result)
    assert all(item.source_frame_path == entry.source_frame_path for item in result)
    assert all(item.source_node_key == entry.source_node_key for item in result)
    assert all(item.speaker_color == entry.speaker_color for item in result)
    assert all(item.speaker_channel == entry.speaker_channel for item in result)
    assert all(item.speaker_changed is True for item in result)


def test_reflow_sentence_split_assigns_edge_timings_only():
    entry = SubtitleEntry(
        "첫 문장. 둘째 문장?",
        datetime(2026, 2, 12, 10, 0, 0),
        entry_id="entry-3",
    )
    entry.start_time = datetime(2026, 2, 12, 10, 0, 0)
    entry.end_time = datetime(2026, 2, 12, 10, 0, 4)

    result = reflow_subtitles([entry])

    assert [item.text for item in result] == ["첫 문장.", "둘째 문장?"]
    assert result[0].start_time == entry.start_time
    assert result[0].end_time is None
    assert result[1].start_time is None
    assert result[1].end_time == entry.end_time
    assert all(item.entry_id != entry.entry_id for item in result)


def test_reflow_does_not_merge_entries_with_different_metadata():
    first = SubtitleEntry(
        "이어지는 문장",
        datetime(2026, 2, 12, 11, 0, 0),
        source_node_key="row-1",
        speaker_channel="primary",
        speaker_color="#111111",
    )
    second = SubtitleEntry(
        "다음 줄",
        datetime(2026, 2, 12, 11, 0, 1),
        source_node_key="row-2",
        speaker_channel="secondary",
        speaker_color="#222222",
    )

    result = reflow_subtitles([first, second])

    assert len(result) == 2
    assert [item.text for item in result] == ["이어지는 문장", "다음 줄"]
