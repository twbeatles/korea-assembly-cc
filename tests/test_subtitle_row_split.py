# -*- coding: utf-8 -*-
"""multi-speaker 분할 규칙(probe JS 미러) 단위 테스트."""

from core.subtitle_row_split import (
    SpeakerSpanInput,
    build_split_node_keys,
    collect_multi_speaker_segments,
)


def test_splits_when_two_spans_have_different_colors() -> None:
    spans = [
        SpeakerSpanInput("위원장 발언입니다.", "rgb(30, 30, 30)", "segarr_1_0", 0),
        SpeakerSpanInput("의원 발언입니다.", "rgb(35, 124, 147)", "segarr_1_1", 1),
    ]
    segments = collect_multi_speaker_segments(spans)
    assert len(segments) == 2
    keys = build_split_node_keys("class:stxt1", segments)
    assert keys == [
        "class:stxt1#segarr_1_0",
        "class:stxt1#segarr_1_1",
    ]
    assert segments[0].speaker_color == "rgb(30, 30, 30)"
    assert segments[1].speaker_color == "rgb(35, 124, 147)"


def test_no_split_when_same_color() -> None:
    spans = [
        SpeakerSpanInput("첫째", "rgb(35, 124, 147)", "a", 0),
        SpeakerSpanInput("둘째", "rgb(35, 124, 147)", "b", 1),
    ]
    assert collect_multi_speaker_segments(spans) == []


def test_no_split_single_span() -> None:
    spans = [SpeakerSpanInput("한 줄", "rgb(35, 124, 147)", "only", 0)]
    assert collect_multi_speaker_segments(spans) == []


def test_skips_empty_text_spans() -> None:
    spans = [
        SpeakerSpanInput("  ", "rgb(30, 30, 30)", "empty", 0),
        SpeakerSpanInput("본문", "rgb(35, 124, 147)", "body", 1),
        SpeakerSpanInput("다른 화자", "rgb(30, 30, 30)", "other", 2),
    ]
    segments = collect_multi_speaker_segments(spans)
    assert len(segments) == 2
    assert segments[0].key_suffix == "body"
