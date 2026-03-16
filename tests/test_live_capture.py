from core.live_capture import (
    LIVE_LEDGER_MAX_ROWS,
    create_empty_live_capture_ledger,
    get_live_row,
    list_live_panel_rows,
    mark_live_row_committed,
    normalize_capture_event,
    reconcile_live_capture,
    set_live_row_baseline,
)
from core.models import ObservedSubtitleRow


def test_reconcile_live_capture_preserves_row_metadata_on_correction():
    ledger = create_empty_live_capture_ledger()
    first = reconcile_live_capture(
        ledger,
        normalize_capture_event(
            raw="첫 문장",
            rows=[
                ObservedSubtitleRow(
                    node_key="row_1",
                    text="첫 문장",
                    speaker_color="rgb(35, 124, 147)",
                    speaker_channel="primary",
                )
            ],
            timestamp=1.0,
        ),
    )

    row_key = first.live_rows[0].key
    ledger = set_live_row_baseline(first.ledger, row_key, "기준이력")
    ledger = mark_live_row_committed(ledger, row_key, "entry_1")

    second = reconcile_live_capture(
        ledger,
        normalize_capture_event(
            raw="첫 문장 보정",
            rows=[
                ObservedSubtitleRow(
                    node_key="row_1",
                    text="첫 문장 보정",
                    speaker_color="rgb(35, 124, 147)",
                    speaker_channel="primary",
                )
            ],
            timestamp=2.0,
        ),
    )

    assert second.changed is True
    assert len(second.row_changes) == 1
    assert second.row_changes[0].is_new is False
    assert second.live_rows[0].key == row_key
    assert get_live_row(second.ledger, row_key).committed_entry_id == "entry_1"
    assert get_live_row(second.ledger, row_key).baseline_compact == "기준이력"


def test_reconcile_live_capture_fallback_clears_only_active_rows():
    structured = reconcile_live_capture(
        create_empty_live_capture_ledger(),
        normalize_capture_event(
            raw="현재 row",
            rows=[
                ObservedSubtitleRow(
                    node_key="row_1",
                    text="현재 row",
                    speaker_color="rgb(35, 124, 147)",
                    speaker_channel="primary",
                )
            ],
            timestamp=10.0,
        ),
    )

    fallback = reconcile_live_capture(
        structured.ledger,
        normalize_capture_event(
            raw="fallback preview",
            rows=[],
            timestamp=11.0,
        ),
    )

    row_key = structured.live_rows[0].key
    assert fallback.changed is True
    assert fallback.live_rows == []
    assert fallback.ledger.active_row_keys == []
    assert fallback.ledger.preview_text == "fallback preview"
    assert get_live_row(fallback.ledger, row_key).text == "현재 row"
    assert list_live_panel_rows(fallback.ledger)[0].text == "현재 row"


def test_reconcile_live_capture_bounds_ledger_and_distinguishes_frame_paths():
    ledger = create_empty_live_capture_ledger()

    for index in range(LIVE_LEDGER_MAX_ROWS + 20):
        ledger = reconcile_live_capture(
            ledger,
            normalize_capture_event(
                raw=f"문장-{index}",
                rows=[ObservedSubtitleRow(node_key=f"row_{index}", text=f"문장-{index}")],
                timestamp=float(index + 1),
            ),
        ).ledger

    assert len(ledger.order) == LIVE_LEDGER_MAX_ROWS
    assert ledger.active_row_keys == [f"top::row_{LIVE_LEDGER_MAX_ROWS + 19}"]
    assert get_live_row(ledger, "top::row_0") is None

    frame_split = reconcile_live_capture(
        create_empty_live_capture_ledger(),
        normalize_capture_event(
            raw="같은 key",
            rows=[ObservedSubtitleRow(node_key="row_shared", text="상단 프레임")],
            timestamp=1.0,
            frame_path=(),
        ),
    ).ledger
    frame_split = reconcile_live_capture(
        frame_split,
        normalize_capture_event(
            raw="같은 key",
            rows=[ObservedSubtitleRow(node_key="row_shared", text="하위 프레임")],
            timestamp=2.0,
            frame_path=(0,),
        ),
    ).ledger

    assert get_live_row(frame_split, "top::row_shared").text == "상단 프레임"
    assert get_live_row(frame_split, "0::row_shared").text == "하위 프레임"
