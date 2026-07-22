# -*- coding: utf-8 -*-
"""PROJECT_AUDIT 2026-07-22 후속 회귀 테스트."""

from __future__ import annotations

import inspect
import queue
import threading
from typing import Any

import pytest

from core.models import SubtitleEntry
from core.utils import compact_subtitle_text
from ui.main_window_common import MainWindowMessageQueue, WorkerQueueMessage

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


class _AlwaysFullQueue:
    def put_nowait(self, _item: object) -> None:
        raise queue.Full

    def put(self, _item: object, *args: object, **kwargs: object) -> None:
        raise queue.Full

    def empty(self) -> bool:
        return True

    def get_nowait(self) -> object:
        raise queue.Empty


class _FakeDriver:
    def __init__(self) -> None:
        self.quit_calls = 0
        self.get_calls: list[str] = []
        self.current_url = ""

    def get(self, url: str) -> None:
        self.get_calls.append(url)
        self.current_url = url

    def execute_script(self, _script: object) -> int:
        return 1

    def quit(self) -> None:
        self.quit_calls += 1


class _FakeWebDriverWait:
    def __init__(self, _driver: object, _timeout: object) -> None:
        pass

    def until(self, _condition: object) -> bool:
        return True


class _ImmediateStopEvent:
    def is_set(self) -> bool:
        return True

    def wait(self, timeout: object = None) -> bool:
        return True


def test_extraction_worker_finished_survives_full_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """포화 큐에서도 finished 가 terminal stash 로 보존되어야 한다."""
    win = MainWindow.__new__(MainWindow)
    win.message_queue = _AlwaysFullQueue()
    win.stop_event = _ImmediateStopEvent()
    win.auto_reconnect_enabled = False
    win._detached_drivers = []
    win._detached_drivers_lock = threading.Lock()
    win.driver = None
    win._last_subtitle_frame_path = ()
    win._active_capture_run_id = 42
    win._ensure_active_capture_run = lambda: 42
    win._is_active_capture_run = lambda run_id: int(run_id) == 42
    win._activate_subtitle = lambda _driver: True
    win._build_subtitle_selector_candidates = lambda selector, extras=None: [selector]
    win._inject_mutation_observer = lambda _driver, _selector: (False, ())
    win._read_subtitle_probe_by_selectors = (
        lambda _driver, _selectors, preferred_frame_path=(), **_kwargs: {
            "text": "",
            "matched_selector": "",
            "found": False,
            "rows": [],
            "frame_path": preferred_frame_path,
        }
    )
    win._read_subtitle_text_by_selectors = lambda _driver, _selectors: ("", "", False)
    win._find_subtitle_selector = lambda _driver: ""
    win._detect_live_broadcast = lambda _driver, url, **_kwargs: url
    win._dispose_driver = lambda *_args, **_kwargs: True
    win._get_current_driver = lambda: None
    win._open_capture_driver_session = lambda *_args, **_kwargs: (
        _FakeDriver(),
        "https://example.com/live?xcgcd=1",
        ["#viewSubtit"],
        "#viewSubtit",
        False,
        (),
    )
    win._build_chrome_options = lambda _headless: object()

    monkeypatch.setattr(mw_mod.webdriver, "Chrome", lambda options=None: _FakeDriver())
    monkeypatch.setattr(mw_mod, "WebDriverWait", _FakeWebDriverWait)

    MainWindow._extraction_worker(
        win,
        "https://example.com/live?xcgcd=1",
        "#viewSubtit",
        False,
        run_id=42,
    )

    terminal = list(win.__dict__.get("_terminal_worker_messages") or [])
    assert terminal, "포화 큐에서 finished 가 terminal passthrough 에 보존되어야 합니다"
    finished = [
        item
        for item in terminal
        if isinstance(item, WorkerQueueMessage) and item.msg_type == "finished"
    ]
    assert len(finished) == 1
    assert finished[0].run_id == 42
    assert isinstance(finished[0].payload, dict)
    assert finished[0].payload.get("success") is True


def test_finished_emitted_as_worker_queue_message_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """finished 는 raw tuple 이 아니라 WorkerQueueMessage envelope 로 전달된다."""
    win = MainWindow.__new__(MainWindow)
    win.message_queue = queue.Queue()
    win.stop_event = _ImmediateStopEvent()
    win.auto_reconnect_enabled = False
    win._detached_drivers = []
    win._detached_drivers_lock = threading.Lock()
    win.driver = None
    win._last_subtitle_frame_path = ()
    win._ensure_active_capture_run = lambda: 7
    win._is_active_capture_run = lambda run_id: int(run_id) == 7
    win._activate_subtitle = lambda _driver: True
    win._build_subtitle_selector_candidates = lambda selector, extras=None: [selector]
    win._inject_mutation_observer = lambda _driver, _selector: (False, ())
    win._read_subtitle_probe_by_selectors = (
        lambda _driver, _selectors, preferred_frame_path=(), **_kwargs: {
            "text": "",
            "matched_selector": "",
            "found": False,
            "rows": [],
            "frame_path": preferred_frame_path,
        }
    )
    win._read_subtitle_text_by_selectors = lambda _driver, _selectors: ("", "", False)
    win._find_subtitle_selector = lambda _driver: ""
    win._detect_live_broadcast = lambda _driver, url, **_kwargs: url
    win._dispose_driver = lambda *_args, **_kwargs: True
    win._get_current_driver = lambda: None
    win._open_capture_driver_session = lambda *_args, **_kwargs: (
        _FakeDriver(),
        "https://example.com/live?xcgcd=1",
        ["#viewSubtit"],
        "#viewSubtit",
        False,
        (),
    )
    win._build_chrome_options = lambda _headless: object()

    monkeypatch.setattr(mw_mod.webdriver, "Chrome", lambda options=None: _FakeDriver())
    monkeypatch.setattr(mw_mod, "WebDriverWait", _FakeWebDriverWait)

    MainWindow._extraction_worker(
        win,
        "https://example.com/live?xcgcd=1",
        "#viewSubtit",
        False,
        run_id=7,
    )

    items: list[object] = []
    while not win.message_queue.empty():
        items.append(win.message_queue.get_nowait())

    finished_items = [
        item
        for item in items
        if isinstance(item, WorkerQueueMessage) and item.msg_type == "finished"
    ]
    assert finished_items, f"WorkerQueueMessage finished 가 필요합니다: {items!r}"
    assert finished_items[0].run_id == 7
    raw_finished_tuples = [
        item
        for item in items
        if isinstance(item, tuple) and len(item) == 2 and item[0] == "finished"
    ]
    assert not raw_finished_tuples, "finished 를 raw tuple 로 put 하면 안 됩니다"


def test_stopping_absorbs_finished_and_error_idempotently() -> None:
    win = MainWindow.__new__(MainWindow)
    win._is_stopping = True
    retire_calls: list[object] = []
    win._retire_capture_run = lambda: retire_calls.append(True)
    win.worker = object()
    win.progress = type("P", (), {"hide": staticmethod(lambda: None)})()
    win._reset_ui = lambda: (_ for _ in ()).throw(
        AssertionError("stop 중 finished/error 는 UI reset 을 다시 호출하면 안 됩니다")
    )
    win._show_toast = lambda *_a, **_k: None
    win._update_tray_status = lambda *_a, **_k: None
    win._update_connection_status = lambda *_a, **_k: None
    win._clear_preview = lambda: None
    win._schedule_status_update = lambda *_a, **_k: None

    MainWindow._handle_message(
        win,
        "finished",
        {"success": False, "error": "boom", "finalize_preview": True},
    )
    assert win.worker is None
    assert retire_calls == [True]

    win.worker = object()
    MainWindow._handle_message(win, "error", "fatal")
    assert win.worker is None
    assert len(retire_calls) == 2


def test_observer_js_allows_short_hangul_utterance() -> None:
    source = inspect.getsource(MainWindow._inject_mutation_observer_here)
    assert "text.length < 3" not in source
    assert "가-힣A-Za-z" in source
    assert "text.length > 320" in source


def test_soft_resync_uses_only_recent_five_of_many_entries() -> None:
    win = MainWindow.__new__(MainWindow)
    win.subtitle_lock = threading.Lock()
    win._suffix_length = 50
    win.subtitles = [
        SubtitleEntry(f"오래된 자막 번호 {i} 입니다") for i in range(1, 21)
    ] + [
        SubtitleEntry("최근 하나 충분히 긴 텍스트 입니다"),
        SubtitleEntry("최근 둘 충분히 긴 텍스트 입니다"),
        SubtitleEntry("최근 셋 충분히 긴 텍스트 입니다"),
        SubtitleEntry("최근 넷 충분히 긴 텍스트 입니다"),
        SubtitleEntry("최근 다섯 충분히 긴 텍스트 입니다"),
    ]

    MainWindow._soft_resync(win)

    # 최근 5개만 반영
    assert "오래된자막번호1입니다" not in win._confirmed_compact
    assert compact_subtitle_text("최근 다섯 충분히 긴 텍스트 입니다") in win._confirmed_compact
    assert win._trailing_suffix


def test_db_worker_rejects_tasks_during_shutdown() -> None:
    win = MainWindow.__new__(MainWindow)
    win.db = object()
    win._db_worker_lock = threading.Lock()
    win._db_worker_queue = queue.Queue()
    win._db_worker_shutdown = True
    win._db_worker_thread = None
    win._is_background_shutdown_active = lambda: False
    win._show_toast = lambda *_a, **_k: None
    win._set_status = lambda *_a, **_k: None
    win._db_tasks_inflight = set()

    assert MainWindow._ensure_db_worker_started(win) is False

    with pytest.raises(RuntimeError, match="종료 중"):
        MainWindow._run_db_task_sync(win, "probe", lambda: 1)


def test_db_worker_serializes_and_emits_result() -> None:
    win = MainWindow.__new__(MainWindow)
    win.db = type("DB", (), {"checkpoint": staticmethod(lambda *_a, **_k: None)})()
    win._db_worker_lock = threading.Lock()
    win._db_worker_queue = queue.Queue()
    win._db_worker_shutdown = False
    win._db_worker_thread = None
    win._db_worker_current_task = ""
    win._is_background_shutdown_active = lambda: False
    win._db_tasks_inflight = set()
    win._show_toast = lambda *_a, **_k: None
    win._set_status = lambda *_a, **_k: None
    emitted: list[tuple[str, Any]] = []

    def emit_control(msg_type: str, data: Any) -> None:
        emitted.append((msg_type, data))

    win._emit_control_message = emit_control

    assert MainWindow._ensure_db_worker_started(win) is True
    assert MainWindow._run_db_task(win, "unit_probe", lambda: {"ok": True}) is True

    # worker 가 처리할 시간을 짧게 대기
    for _ in range(50):
        if emitted:
            break
        threading.Event().wait(0.02)

    MainWindow._begin_db_worker_shutdown(win)
    MainWindow._shutdown_db_worker(win, timeout=2.0)

    assert emitted
    msg_type, payload = emitted[0]
    assert msg_type == "db_task_result"
    assert payload["task"] == "unit_probe"
    result = payload["result"]
    assert getattr(result, "ok", False) is True
    assert getattr(result, "value", None) == {"ok": True}
