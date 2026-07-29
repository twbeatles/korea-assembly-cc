# -*- coding: utf-8 -*-
"""PROJECT_AUDIT 2026-07-29 후속 회귀 테스트.

- _start dirty/세션 교체 보호
- soft_resync 긴 compact 유지
- orphan runtime segment 정리
- capture probe 테스트 더블 계약 (Chrome 없는 시뮬 초석)
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pytest

from core.models import SubtitleEntry
from core.utils import compact_subtitle_text

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _StubCombo:
    def __init__(self, text: str) -> None:
        self._text = text

    def currentText(self) -> str:
        return self._text


class _StubCheck:
    def __init__(self, checked: bool = False) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


def _base_start_window() -> Any:
    win = MainWindow.__new__(MainWindow)
    win.is_running = False
    win._session_save_in_progress = False
    win._session_load_in_progress = False
    win.subtitles = []
    win._runtime_archived_count = 0
    win._session_dirty = False
    win.selector_combo = _StubCombo("#viewSubtit .smi_word")
    win.url_combo = _StubCombo(
        "https://assembly.webcast.go.kr/main/player.asp?xcode=10"
    )
    win._get_current_url = lambda: win.url_combo.currentText()
    win.headless_check = _StubCheck(False)
    win.realtime_save_check = _StubCheck(False)
    begin_calls: list[tuple[str, str]] = []
    win.begin_calls = begin_calls
    win._begin_extraction_run = lambda url, selector: begin_calls.append(
        (url, selector)
    )
    win._has_dirty_session = lambda: bool(win._session_dirty)
    win._get_global_subtitle_count = lambda: (
        int(win._runtime_archived_count or 0) + len(win.subtitles)
    )
    win._set_status = lambda *_a, **_k: None
    win._show_toast = lambda *_a, **_k: None
    return win


# ---------------------------------------------------------------------------
# 1단계: _start dirty / replace 보호
# ---------------------------------------------------------------------------


def test_start_blocks_when_session_dirty_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    win = _base_start_window()
    win._session_dirty = True
    win.subtitles = [SubtitleEntry("미저장 자막")]

    def _deny(_action: str, on_continue=None):  # type: ignore[no-untyped-def]
        return False

    win._run_after_dirty_session_action = _deny

    MainWindow._start(win)

    assert win.begin_calls == []


def test_start_after_discard_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    win = _base_start_window()
    win._session_dirty = True
    win.subtitles = [SubtitleEntry("버릴 자막")]

    def _discard(_action: str, on_continue=None):  # type: ignore[no-untyped-def]
        if callable(on_continue):
            on_continue()
        return True

    win._run_after_dirty_session_action = _discard

    MainWindow._start(win)

    assert len(win.begin_calls) == 1
    assert "xcode=10" in win.begin_calls[0][0]
    assert win.begin_calls[0][1] == "#viewSubtit .smi_word"


def test_start_after_dirty_save_deferred_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Save 경로: on_continue 가 나중에 호출되면 begin 이 실행된다."""
    win = _base_start_window()
    win._session_dirty = True
    held: list[Any] = []

    def _save_later(_action: str, on_continue=None):  # type: ignore[no-untyped-def]
        held.append(on_continue)
        return True  # async save 시작됨, 아직 continue 안 함

    win._run_after_dirty_session_action = _save_later
    MainWindow._start(win)
    assert win.begin_calls == []
    assert held and callable(held[0])
    held[0]()
    assert len(win.begin_calls) == 1


def test_start_clean_with_subtitles_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    win = _base_start_window()
    win._session_dirty = False
    win.subtitles = [SubtitleEntry("저장된 자막"), SubtitleEntry("두번째")]
    win._confirm_replace_session_for_start = lambda _count: False

    MainWindow._start(win)

    assert win.begin_calls == []


def test_start_clean_with_subtitles_confirm_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = _base_start_window()
    win._session_dirty = False
    win.subtitles = [SubtitleEntry("기존 자막")]
    win._confirm_replace_session_for_start = lambda count: count == 1

    MainWindow._start(win)

    assert len(win.begin_calls) == 1


def test_start_empty_clean_session_starts_immediately() -> None:
    win = _base_start_window()
    win._session_dirty = False
    win.subtitles = []
    called: list[bool] = []
    win._confirm_replace_session_for_start = lambda _c: called.append(True) or True

    MainWindow._start(win)

    assert win.begin_calls
    assert called == []  # 자막 없으면 교체 확인 스킵


def test_start_rejects_invalid_url_before_dirty_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = _base_start_window()
    win._session_dirty = True
    win.url_combo = _StubCombo("https://evil.example.com/")
    win._get_current_url = lambda: win.url_combo.currentText()
    dirty_calls: list[str] = []
    win._run_after_dirty_session_action = lambda action, on_continue=None: dirty_calls.append(
        str(action)
    ) or False
    warnings: list[str] = []

    class _MB:
        @staticmethod
        def warning(_parent: object, _title: object, message: object) -> None:
            warnings.append(str(message))

    import ui.main_window as real_mw

    monkeypatch.setattr(real_mw, "QMessageBox", _MB)
    MainWindow._start(win)

    assert win.begin_calls == []
    assert dirty_calls == []  # URL 검증이 dirty 확인보다 선행
    assert any("assembly.webcast.go.kr" in w or "URL" in w for w in warnings)


# ---------------------------------------------------------------------------
# 2단계: soft_resync
# ---------------------------------------------------------------------------


def test_soft_resync_keeps_longer_history_when_recent_is_contained() -> None:
    win = MainWindow.__new__(MainWindow)
    win.subtitle_lock = threading.Lock()
    win._suffix_length = 50
    win.subtitles = [
        SubtitleEntry("가" * 10 + "국회본회의가 시작되었습니다"),
        SubtitleEntry("다음 발언입니다"),
    ]
    full = "서론입니다 " + " ".join(e.text for e in win.subtitles)
    win._confirmed_compact = compact_subtitle_text(full)
    previous = win._confirmed_compact
    previous_len = len(previous)

    MainWindow._soft_resync(win)

    assert win._confirmed_compact == previous
    assert len(win._confirmed_compact) == previous_len
    assert win._trailing_suffix == win._confirmed_compact[-win._suffix_length :]


def test_soft_resync_rebuilds_from_entries_when_desynced() -> None:
    win = MainWindow.__new__(MainWindow)
    win.subtitle_lock = threading.Lock()
    win._suffix_length = 50
    win._confirmed_compact = compact_subtitle_text("완전히다른과거히스토리" * 5)
    win.subtitles = [
        SubtitleEntry("새로운발언하나"),
        SubtitleEntry("새로운발언둘"),
    ]

    MainWindow._soft_resync(win)

    expected = compact_subtitle_text("새로운발언하나 새로운발언둘")
    assert win._confirmed_compact == expected


def test_soft_resync_empty_subtitles_clears_history() -> None:
    win = MainWindow.__new__(MainWindow)
    win.subtitle_lock = threading.Lock()
    win._suffix_length = 50
    win._confirmed_compact = "something"
    win._trailing_suffix = "something"
    win.subtitles = []

    MainWindow._soft_resync(win)

    assert win._confirmed_compact == ""
    assert win._trailing_suffix == ""


# ---------------------------------------------------------------------------
# 2단계: orphan segment cleanup
# ---------------------------------------------------------------------------


def test_cleanup_orphan_runtime_segment_file_deletes_untracked(
    tmp_path: Path,
) -> None:
    win = MainWindow.__new__(MainWindow)
    win._runtime_session_root = tmp_path
    win._runtime_segment_manifest = []
    orphan = tmp_path / "segment_000001.json"
    orphan.write_text('{"subtitles":[]}', encoding="utf-8")

    deleted = MainWindow._cleanup_orphan_runtime_segment_file(
        win, "segment_000001.json", segment_index=1
    )

    assert deleted is True
    assert not orphan.exists()


def test_cleanup_orphan_skips_manifest_tracked_file(tmp_path: Path) -> None:
    win = MainWindow.__new__(MainWindow)
    win._runtime_session_root = tmp_path
    win._runtime_segment_manifest = [{"path": "segment_000002.json"}]
    tracked = tmp_path / "segment_000002.json"
    tracked.write_text("{}", encoding="utf-8")

    deleted = MainWindow._cleanup_orphan_runtime_segment_file(
        win, "segment_000002.json", segment_index=2
    )

    assert deleted is False
    assert tracked.exists()


def test_handle_runtime_segment_flush_done_mismatch_cleans_orphan(
    tmp_path: Path,
) -> None:
    win = MainWindow.__new__(MainWindow)
    win.subtitle_lock = threading.Lock()
    win.subtitles = [SubtitleEntry("현재 다른 내용")]
    win._runtime_session_root = tmp_path
    win._runtime_segment_manifest = []
    win._runtime_segment_flush_in_progress = True
    win._runtime_archived_count = 0
    win._is_runtime_archive_identity_current = lambda *_a, **_k: True
    win._runtime_entries_fingerprint_matches = lambda *_a, **_k: False
    win._maybe_schedule_runtime_segment_flush = lambda: True
    orphan = tmp_path / "segment_000003.json"
    orphan.write_text("{}", encoding="utf-8")

    MainWindow._handle_runtime_segment_flush_done(
        win,
        {
            "archive_token": "",
            "run_id": None,
            "entry_count": 1,
            "char_count": 1,
            "word_count": 1,
            "segment_index": 3,
            "path": "segment_000003.json",
            "start_index": 0,
            "first_entry_id": "x",
            "last_entry_id": "y",
            "entries_digest": "z",
        },
    )

    assert not orphan.exists()
    assert win._runtime_segment_flush_in_progress is False


# ---------------------------------------------------------------------------
# 3단계: capture probe 테스트 더블 계약
# ---------------------------------------------------------------------------


@runtime_checkable
class CaptureProbeProtocol(Protocol):
    """Chrome 없는 E2E 시뮬용 최소 probe 계약."""

    def read_subtitle_probe(
        self,
        selector_candidates: list[str],
        *,
        preferred_frame_path: tuple[int, ...] = (),
    ) -> dict[str, Any]: ...


class FakeCaptureProbe:
    def __init__(self, texts: list[str] | None = None) -> None:
        self._texts = list(texts or [])
        self._index = 0
        self.calls: list[tuple[tuple[str, ...], tuple[int, ...]]] = []

    def read_subtitle_probe(
        self,
        selector_candidates: list[str],
        *,
        preferred_frame_path: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        self.calls.append((tuple(selector_candidates), preferred_frame_path))
        if self._index >= len(self._texts):
            text = self._texts[-1] if self._texts else ""
        else:
            text = self._texts[self._index]
            self._index += 1
        return {
            "text": text,
            "found": bool(text),
            "matched_selector": selector_candidates[0] if selector_candidates else "",
            "frame_path": list(preferred_frame_path),
        }


def test_fake_capture_probe_protocol_contract() -> None:
    probe: CaptureProbeProtocol = FakeCaptureProbe(["안녕하세요", "안녕하세요 이어서"])
    assert isinstance(probe, CaptureProbeProtocol)

    first = probe.read_subtitle_probe(["#viewSubtit .smi_word"])
    second = probe.read_subtitle_probe(
        ["#viewSubtit .smi_word", ".incont"],
        preferred_frame_path=(0, 1),
    )

    assert first["text"] == "안녕하세요"
    assert first["found"] is True
    assert second["text"] == "안녕하세요 이어서"
    assert second["frame_path"] == [0, 1]


def test_fake_capture_probe_drives_prepare_preview_raw() -> None:
    """probe 더블 → prepare_preview_raw 경로 스모크 (Chrome 없음)."""
    win = MainWindow.__new__(MainWindow)
    win.subtitles = []
    win.subtitle_lock = threading.Lock()
    win._confirmed_compact = ""
    win._trailing_suffix = ""
    win._suffix_length = 50
    win._last_raw_text = ""
    win._preview_desync_count = 0
    win._preview_ambiguous_skip_count = 0
    win._last_good_raw_compact = ""
    win._preview_resync_threshold = 3
    win._preview_ambiguous_resync_threshold = 3
    win._normalize_subtitle_text_for_option = lambda text: str(text or "")
    win._reconnect_preview_suppress_until_delta = False

    probe = FakeCaptureProbe(["첫 발언", "첫 발언 이어짐"])
    p1 = probe.read_subtitle_probe(["#viewSubtit"])
    prepared1 = MainWindow._prepare_preview_raw(win, p1["text"])
    assert prepared1 == "첫 발언"

    # suffix 설정 후 증분
    win._trailing_suffix = compact_subtitle_text("첫 발언")
    p2 = probe.read_subtitle_probe(["#viewSubtit"])
    prepared2 = MainWindow._prepare_preview_raw(win, p2["text"])
    assert prepared2 is not None
    assert "이어짐" in prepared2 or prepared2 == p2["text"]
