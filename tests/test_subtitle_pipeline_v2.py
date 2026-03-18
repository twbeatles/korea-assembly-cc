from datetime import datetime, timedelta

import pytest

import core.subtitle_pipeline as pipeline_mod
from core.subtitle_pipeline import (
    LiveRowCommitMeta,
    apply_keepalive,
    apply_preview,
    commit_live_row,
    create_empty_capture_state,
    flush_pending_previews,
)


def test_commit_live_row_updates_existing_entry_in_place():
    state = create_empty_capture_state()
    now = datetime(2026, 3, 11, 8, 0, 0)

    first = commit_live_row(
        state,
        "first line",
        "first line",
        now,
        meta=LiveRowCommitMeta(
            source_node_key="top::row_1",
            baseline_compact=state.confirmed_compact,
        ),
    )
    assert first.appended_entry is not None
    entry_id = first.appended_entry.entry_id
    assert entry_id is not None

    updated = commit_live_row(
        state,
        "first line corrected",
        "first line corrected",
        now + timedelta(seconds=1),
        meta=LiveRowCommitMeta(
            source_node_key="top::row_1",
            source_entry_id=entry_id,
            baseline_compact="",
        ),
    )

    assert updated.changed is True
    assert len(state.entries) == 1
    assert state.entries[0].text == "first line corrected"
    assert state.entries[0].source_node_key == "top::row_1"


def test_commit_live_row_trims_carry_over_when_new_row_starts():
    state = create_empty_capture_state()
    now = datetime(2026, 3, 11, 8, 5, 0)

    commit_live_row(
        state,
        "We need a careful review of this budget process",
        "We need a careful review of this budget process",
        now,
        meta=LiveRowCommitMeta(
            source_node_key="top::row_1",
            baseline_compact=state.confirmed_compact,
        ),
    )

    result = commit_live_row(
        state,
        "We need a careful review of this budget process and a better plan",
        "We need a careful review of this budget process and a better plan",
        now + timedelta(seconds=1),
        meta=LiveRowCommitMeta(
            source_node_key="top::row_2",
            baseline_compact=state.confirmed_compact,
        ),
    )

    assert result.changed is True
    assert len(state.entries) == 2
    assert state.entries[1].text == "and a better plan"


def test_commit_live_row_reuses_original_baseline_when_row_grows():
    state = create_empty_capture_state()
    now = datetime(2026, 3, 11, 8, 10, 0)

    commit_live_row(
        state,
        "The international situation is very different now",
        "The international situation is very different now",
        now,
        meta=LiveRowCommitMeta(
            source_node_key="top::row_1",
            baseline_compact=state.confirmed_compact,
        ),
    )

    baseline_compact = state.confirmed_compact
    first_commit = commit_live_row(
        state,
        "The international situation is very different now and needs more detail",
        "The international situation is very different now and needs more detail",
        now + timedelta(seconds=1),
        meta=LiveRowCommitMeta(
            source_node_key="top::row_2",
            baseline_compact=baseline_compact,
        ),
    )

    assert first_commit.appended_entry is not None
    entry_id = first_commit.appended_entry.entry_id
    assert entry_id is not None

    updated_commit = commit_live_row(
        state,
        "The international situation is very different now and needs more detail from us",
        "The international situation is very different now and needs more detail from us",
        now + timedelta(seconds=2),
        meta=LiveRowCommitMeta(
            source_node_key="top::row_2",
            source_entry_id=entry_id,
            baseline_compact=baseline_compact,
        ),
    )

    assert updated_commit.changed is True
    assert len(state.entries) == 2
    assert state.entries[1].text == "and needs more detail from us"


def test_apply_preview_avoids_duplicate_reappend_and_keepalive_extends_end_time():
    state = create_empty_capture_state()
    now = datetime(2026, 3, 11, 8, 15, 0)

    apply_preview(state, "Thank you", now)
    apply_preview(state, "Thank you for the comment", now + timedelta(seconds=1))
    duplicate = apply_preview(
        state,
        "Thank you for the comment",
        now + timedelta(seconds=2),
    )
    prior_end_time = state.entries[0].end_time
    assert prior_end_time is not None

    keepalive = apply_keepalive(
        state,
        "Thank you for the comment",
        now + timedelta(seconds=5),
    )

    assert len(state.entries) == 1
    assert duplicate.changed is False
    assert keepalive.changed is True
    assert state.entries[0].end_time is not None
    assert state.entries[0].end_time > prior_end_time


def test_flush_pending_previews_materializes_preview_only_clone():
    state = create_empty_capture_state()
    now = datetime(2026, 3, 11, 8, 20, 0)
    state.preview_text = "preview only line"
    state.current_selector = "#viewSubtit"
    state.current_frame_path = (0,)

    flushed = flush_pending_previews(state, now)

    assert state.entries == []
    assert len(flushed.entries) == 1
    assert flushed.entries[0].text == "preview only line"
    assert flushed.entries[0].source_selector == "#viewSubtit"
    assert flushed.entries[0].source_frame_path == [0]


def test_apply_preview_can_preserve_line_breaks_when_auto_cleanup_disabled():
    state = create_empty_capture_state()
    now = datetime(2026, 3, 11, 8, 25, 0)

    apply_preview(
        state,
        "첫 문장\n\n둘째 문장",
        now,
        settings={"auto_clean_newlines": False},
    )

    assert len(state.entries) == 1
    assert state.entries[0].text == "첫 문장\n\n둘째 문장"


def test_commit_live_row_hot_path_skips_full_rebuild_for_append_and_tail_update(
    monkeypatch: pytest.MonkeyPatch,
):
    state = create_empty_capture_state()
    now = datetime(2026, 3, 11, 8, 30, 0)

    commit_live_row(
        state,
        "위원장님 질의 순서를 진행하겠습니다",
        "위원장님 질의 순서를 진행하겠습니다",
        now,
        meta=LiveRowCommitMeta(
            source_node_key="top::row_1",
            baseline_compact=state.confirmed_compact,
        ),
    )

    row_2_baseline = state.confirmed_compact

    def fail_rebuild(*_args, **_kwargs):
        raise AssertionError("hot path should not rebuild confirmed history")

    monkeypatch.setattr(pipeline_mod, "rebuild_confirmed_history", fail_rebuild)

    appended = commit_live_row(
        state,
        "위원장님 질의 순서를 진행하겠습니다 다음 안건을 상정합니다",
        "위원장님 질의 순서를 진행하겠습니다 다음 안건을 상정합니다",
        now + timedelta(seconds=1),
        meta=LiveRowCommitMeta(
            source_node_key="top::row_2",
            baseline_compact=row_2_baseline,
        ),
    )
    assert appended.appended_entry is not None

    updated = commit_live_row(
        state,
        "위원장님 질의 순서를 진행하겠습니다 다음 안건을 상정하고 토론을 시작합니다",
        "위원장님 질의 순서를 진행하겠습니다 다음 안건을 상정하고 토론을 시작합니다",
        now + timedelta(seconds=2),
        meta=LiveRowCommitMeta(
            source_node_key="top::row_2",
            source_entry_id=appended.appended_entry.entry_id or "",
            baseline_compact=row_2_baseline,
        ),
    )

    assert updated.changed is True
    assert len(state.entries) == 2
    assert state.entries[-1].text == "다음 안건을 상정하고 토론을 시작합니다"


def test_snapshot_clone_reuses_entries_until_tail_clone_is_needed():
    state = create_empty_capture_state()
    now = datetime(2026, 3, 11, 8, 35, 0)

    commit_live_row(
        state,
        "첫 번째 확정 문장",
        "첫 번째 확정 문장",
        now,
        meta=LiveRowCommitMeta(
            source_node_key="top::row_1",
            baseline_compact=state.confirmed_compact,
        ),
    )
    commit_live_row(
        state,
        "첫 번째 확정 문장 두 번째 확정 문장",
        "첫 번째 확정 문장 두 번째 확정 문장",
        now + timedelta(seconds=1),
        meta=LiveRowCommitMeta(
            source_node_key="top::row_2",
            baseline_compact=state.confirmed_compact,
        ),
    )

    shallow_snapshot = state.snapshot_clone(clone_last_entry=False)
    assert shallow_snapshot.entries[0] is state.entries[0]
    assert shallow_snapshot.entries[1] is state.entries[1]

    tail_snapshot = state.snapshot_clone(clone_last_entry=True)
    assert tail_snapshot.entries[0] is state.entries[0]
    assert tail_snapshot.entries[1] is not state.entries[1]
    assert tail_snapshot.entries[1].text == state.entries[1].text
