from datetime import datetime, timedelta

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
        "첫 문장",
        "첫 문장",
        now,
        meta=LiveRowCommitMeta(
            source_node_key="top::row_1",
            baseline_compact=state.confirmed_compact,
        ),
    )
    entry_id = first.appended_entry.entry_id

    updated = commit_live_row(
        state,
        "첫 문장 보정",
        "첫 문장 보정",
        now + timedelta(seconds=1),
        meta=LiveRowCommitMeta(
            source_node_key="top::row_1",
            source_entry_id=entry_id,
            baseline_compact="",
        ),
    )

    assert updated.changed is True
    assert len(state.entries) == 1
    assert state.entries[0].text == "첫 문장 보정"
    assert state.entries[0].source_node_key == "top::row_1"


def test_commit_live_row_trims_carry_over_when_new_row_starts():
    state = create_empty_capture_state()
    now = datetime(2026, 3, 11, 8, 5, 0)

    commit_live_row(
        state,
        "위원님 말씀드렸듯이 이번 예산 편성 과정에서 여러 해법을",
        "위원님 말씀드렸듯이 이번 예산 편성 과정에서 여러 해법을",
        now,
        meta=LiveRowCommitMeta(
            source_node_key="top::row_1",
            baseline_compact=state.confirmed_compact,
        ),
    )

    result = commit_live_row(
        state,
        "위원님 말씀드렸듯이 이번 예산 편성 과정에서 여러 해법을 찾는 방안을 검토하겠습니다",
        "위원님 말씀드렸듯이 이번 예산 편성 과정에서 여러 해법을 찾는 방안을 검토하겠습니다",
        now + timedelta(seconds=1),
        meta=LiveRowCommitMeta(
            source_node_key="top::row_2",
            baseline_compact=state.confirmed_compact,
        ),
    )

    assert result.changed is True
    assert len(state.entries) == 2
    assert state.entries[1].text == "찾는 방안을 검토하겠습니다"


def test_commit_live_row_reuses_original_baseline_when_row_grows():
    state = create_empty_capture_state()
    now = datetime(2026, 3, 11, 8, 10, 0)

    commit_live_row(
        state,
        "지금 국제정세가 이전과는 많이 달라진 만큼",
        "지금 국제정세가 이전과는 많이 달라진 만큼",
        now,
        meta=LiveRowCommitMeta(
            source_node_key="top::row_1",
            baseline_compact=state.confirmed_compact,
        ),
    )

    baseline_compact = state.confirmed_compact
    first_commit = commit_live_row(
        state,
        "지금 국제정세가 이전과는 많이 달라진 만큼 구체적 논의가 필요합니다",
        "지금 국제정세가 이전과는 많이 달라진 만큼 구체적 논의가 필요합니다",
        now + timedelta(seconds=1),
        meta=LiveRowCommitMeta(
            source_node_key="top::row_2",
            baseline_compact=baseline_compact,
        ),
    )

    entry_id = first_commit.appended_entry.entry_id
    updated_commit = commit_live_row(
        state,
        "지금 국제정세가 이전과는 많이 달라진 만큼 구체적 논의가 필요합니다 그리고 정부도 직접 참여해야 합니다",
        "지금 국제정세가 이전과는 많이 달라진 만큼 구체적 논의가 필요합니다 그리고 정부도 직접 참여해야 합니다",
        now + timedelta(seconds=2),
        meta=LiveRowCommitMeta(
            source_node_key="top::row_2",
            source_entry_id=entry_id,
            baseline_compact=baseline_compact,
        ),
    )

    assert updated_commit.changed is True
    assert len(state.entries) == 2
    assert state.entries[1].text == "구체적 논의가 필요합니다 그리고 정부도 직접 참여해야 합니다"


def test_apply_preview_avoids_duplicate_reappend_and_keepalive_extends_end_time():
    state = create_empty_capture_state()
    now = datetime(2026, 3, 11, 8, 15, 0)

    apply_preview(state, "위원님 감사합니다", now)
    apply_preview(state, "위원님 감사합니다 추가 발언입니다", now + timedelta(seconds=1))
    duplicate = apply_preview(
        state,
        "위원님 감사합니다 추가 발언입니다",
        now + timedelta(seconds=2),
    )
    prior_end_time = state.entries[0].end_time
    keepalive = apply_keepalive(
        state,
        "위원님 감사합니다 추가 발언입니다",
        now + timedelta(seconds=5),
    )

    assert len(state.entries) == 1
    assert duplicate.changed is False
    assert keepalive.changed is True
    assert state.entries[0].end_time > prior_end_time


def test_flush_pending_previews_materializes_preview_only_clone():
    state = create_empty_capture_state()
    now = datetime(2026, 3, 11, 8, 20, 0)
    state.preview_text = "아직 저장 전 미리보기 자막"
    state.current_selector = "#viewSubtit"
    state.current_frame_path = (0,)

    flushed = flush_pending_previews(state, now)

    assert state.entries == []
    assert len(flushed.entries) == 1
    assert flushed.entries[0].text == "아직 저장 전 미리보기 자막"
    assert flushed.entries[0].source_selector == "#viewSubtit"
    assert flushed.entries[0].source_frame_path == [0]
