# -*- coding: utf-8 -*-
"""PROJECT_AUDIT 2026-11-16 후속 회귀 테스트.

- ISSUE-001: subtitle_reset 직전 대기 중인 fallback 후보 유실
- ISSUE-002: fallback commit 최대 대기 상한
- ISSUE-003: 시간 역순 엔트리의 타임스탬프 블록 / SRT·VTT 큐
- 업데이트 helper 사본 정리
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any

from core.export_text import RelativeCueTimeline, format_srt_relative
from core.live_capture import create_empty_live_capture_ledger
from core.models import CaptureQualityState
from core.subtitle_pipeline import create_empty_capture_state
from core.timestamp_blocks import DisplayLayout, build_plain_text, iter_display_rows
from core.update_installer import cleanup_update_helper_copies
from ui.main_window import MainWindow

NOW = datetime(2026, 11, 16, 10, 0, 0)


class _FakeTimer:
    def __init__(self) -> None:
        self.active = False
        self.last_msec: int | None = None

    def start(self, msec: int) -> None:
        self.active = True
        self.last_msec = msec

    def stop(self) -> None:
        self.active = False

    def isActive(self) -> bool:
        return self.active


def _build_window() -> Any:
    win: Any = MainWindow.__new__(MainWindow)
    win.is_running = True
    win.subtitle_lock = threading.Lock()
    win.capture_state = create_empty_capture_state()
    win.live_capture_ledger = create_empty_live_capture_ledger()
    win.subtitles = win.capture_state.entries
    win._pending_subtitle_reset_timer = _FakeTimer()
    win._pending_subtitle_reset_source = ""
    win._fallback_commit_timer = _FakeTimer()
    win._fallback_commit_candidate = None
    win._fallback_commit_token = 0
    win._capture_quality = CaptureQualityState()
    win._ensure_capture_runtime_state = lambda: None
    win._normalize_subtitle_text_for_option = lambda text: str(text or "")
    win._current_capture_settings = lambda: {}
    win._apply_capture_pipeline_refresh = lambda **_kwargs: None
    win._mark_session_dirty = lambda: None
    win._invalidate_destructive_undo = lambda: None
    win._schedule_initial_recovery_snapshot_if_needed = lambda _entries: False
    win._build_prepared_entries_snapshot = lambda: list(win.capture_state.entries)
    win._set_preview_text = lambda _text: None
    win._sync_capture_state_entries = lambda force_refresh=False: None
    return win


def _payload(*lines: str) -> dict[str, Any]:
    return {
        "raw": " ".join(lines),
        "rows": [
            {"nodeKey": f"row_gen{index}", "text": text, "unstableKey": True}
            for index, text in enumerate(lines)
        ],
        "selector": "#viewSubtit .smi_word",
        "source_mode": "smi-window",
    }


def _texts(win: Any) -> list[str]:
    return [entry.text for entry in win.capture_state.entries]


def _fire_fallback_timer_if_due(win: Any, now: datetime) -> None:
    candidate = win._fallback_commit_candidate
    timer = win._fallback_commit_timer
    if not candidate or not timer.active or timer.last_msec is None:
        return
    due_at = candidate["first_seen_at"] + timedelta(milliseconds=timer.last_msec)
    if now >= due_at:
        timer.active = False
        MainWindow._commit_fallback_candidate(win, int(candidate["token"]), now)


# --- ISSUE-001 ---------------------------------------------------------------


def test_reset_before_next_preview_keeps_pending_fallback_text() -> None:
    win = _build_window()
    t = NOW
    MainWindow._apply_structured_preview_payload(win, _payload("존경하는 위원장님"), t)
    t += timedelta(milliseconds=400)
    _fire_fallback_timer_if_due(win, t)
    t += timedelta(milliseconds=600)
    MainWindow._apply_structured_preview_payload(
        win, _payload("존경하는 위원장님 이상으로 질의를 마치겠습니다"), t
    )
    t += timedelta(milliseconds=200)
    MainWindow._schedule_deferred_subtitle_reset(win, "polling_cleared")
    t += timedelta(milliseconds=150)
    MainWindow._apply_structured_preview_payload(
        win, _payload("다음은 김철수 위원님 질의하시겠습니다"), t
    )
    t += timedelta(milliseconds=400)
    _fire_fallback_timer_if_due(win, t)

    texts = _texts(win)
    # flush 는 실제 현재 시각으로 commit 되므로 직전 엔트리와 병합 여부는 시계에 따라 다르다.
    # 확인할 것은 직전 발언 끝부분 보존과 새 발언의 별도 엔트리다.
    assert "존경하는 위원장님 이상으로 질의를 마치겠습니다" == " ".join(texts[:-1])
    assert texts[-1] == "다음은 김철수 위원님 질의하시겠습니다"
    assert win._capture_quality.fallback_reset_flushes == 1


def test_reset_grace_timer_path_commits_pending_candidate_first() -> None:
    win = _build_window()
    MainWindow._apply_structured_preview_payload(win, _payload("마지막 발언입니다"), NOW)
    MainWindow._schedule_deferred_subtitle_reset(win, "polling_cleared")
    MainWindow._commit_scheduled_subtitle_reset(win)

    assert _texts(win) == ["마지막 발언입니다"]
    assert win._fallback_commit_candidate is None


def test_reset_without_pending_candidate_does_not_count_flush() -> None:
    win = _build_window()
    MainWindow._schedule_deferred_subtitle_reset(win, "polling_cleared")
    assert win._capture_quality.fallback_reset_flushes == 0


# --- ISSUE-002 ---------------------------------------------------------------


def test_continuously_changing_fallback_commits_within_max_wait() -> None:
    win = _build_window()
    t = NOW
    words: list[str] = []
    first_commit_at: datetime | None = None
    for index in range(25):  # 200ms 간격, 5초
        words.append(f"단어{index}")
        MainWindow._apply_structured_preview_payload(win, _payload(" ".join(words)), t)
        if first_commit_at is None and win.capture_state.entries:
            first_commit_at = t
        t += timedelta(milliseconds=200)
        _fire_fallback_timer_if_due(win, t)
        if first_commit_at is None and win.capture_state.entries:
            first_commit_at = t

    assert first_commit_at is not None
    assert (first_commit_at - NOW).total_seconds() <= 2.2
    assert win._capture_quality.fallback_max_wait_commits >= 1
    # 중간 commit 뒤 이어지는 텍스트는 suffix 증분으로 이어 붙는다(중복 없음).
    joined = " ".join(_texts(win))
    for word in words[:20]:
        assert joined.count(word + " ") + joined.endswith(word) >= 1
    assert joined.count("단어1 ") == 1


def test_stable_fallback_still_commits_after_400ms() -> None:
    win = _build_window()
    MainWindow._apply_structured_preview_payload(win, _payload("안정 텍스트"), NOW)
    assert win._fallback_commit_timer.last_msec == 400
    _fire_fallback_timer_if_due(win, NOW + timedelta(milliseconds=400))
    assert _texts(win) == ["안정 텍스트"]
    assert win._capture_quality.fallback_max_wait_commits == 0


# --- ISSUE-003 ---------------------------------------------------------------


def _out_of_order_rows() -> list[tuple[datetime, str]]:
    today = datetime(2026, 11, 16, 14, 0, 0)
    yesterday = datetime(2026, 11, 15, 10, 0, 0)
    rows = [(today + timedelta(seconds=70 * i), f"오늘{i}") for i in range(3)]
    rows += [(yesterday + timedelta(seconds=70 * i), f"어제{i}") for i in range(5)]
    return rows


def test_timestamp_blocks_start_new_block_when_time_goes_backwards() -> None:
    merged = list(
        iter_display_rows(_out_of_order_rows(), DisplayLayout(True, 60))
    )
    assert len(merged) == 8
    assert all(row.print_timestamp for row in merged)
    assert not any("오늘" in row.text and "어제" in row.text for row in merged)

    plain = build_plain_text(
        _out_of_order_rows(), DisplayLayout(False, 60), with_timestamps=True
    )
    assert "[10:00:00] 어제0" in plain


def test_relative_cue_timeline_is_monotonic_for_out_of_order_entries() -> None:
    timeline = RelativeCueTimeline()
    placed = []
    for timestamp, _text in _out_of_order_rows():
        placed.append(timeline.place(timestamp, timestamp + timedelta(seconds=3)))
    for start, end in placed:
        assert end > start
    starts = [start for start, _end in placed]
    assert starts == sorted(starts)
    # 정상 구간은 첫 큐 기준 상대 시각을 유지한다.
    assert placed[1] == (70.0, 73.0)
    # 역행한 첫 큐는 직전 큐 끝에 이어 붙는다.
    assert placed[3][0] == placed[2][1]
    assert format_srt_relative(placed[3][0]) == "00:02:23,000"


def test_relative_cue_timeline_keeps_normal_overlap() -> None:
    timeline = RelativeCueTimeline()
    assert timeline.place(NOW, NOW + timedelta(seconds=5)) == (0.0, 5.0)
    assert timeline.place(
        NOW + timedelta(seconds=2), NOW + timedelta(seconds=4)
    ) == (2.0, 4.0)


# --- 업데이트 helper 정리 ----------------------------------------------------


def test_cleanup_update_helper_copies_removes_stale_files(tmp_path) -> None:
    staging = tmp_path / "updates"
    install = tmp_path / "app"
    staging.mkdir()
    install.mkdir()
    helper = staging / "update-helper-abc.exe"
    helper.write_bytes(b"x")
    keep_staged = staging / "update-16.14.17-abc.exe"
    keep_staged.write_bytes(b"x")
    apply_tmp = install / ".update-apply-abc.exe"
    apply_tmp.write_bytes(b"x")
    target = install / "app.exe"
    target.write_bytes(b"x")

    removed = cleanup_update_helper_copies(staging, install, exclude=(target,))

    assert removed == 2
    assert not helper.exists()
    assert not apply_tmp.exists()
    assert keep_staged.exists()
    assert target.exists()


def test_cleanup_update_helper_copies_tolerates_missing_dirs(tmp_path) -> None:
    assert cleanup_update_helper_copies(tmp_path / "missing", tmp_path / "nope") == 0
