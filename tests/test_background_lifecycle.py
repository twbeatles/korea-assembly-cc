import queue
import threading
import time

import pytest

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


def _build_window():
    win = MainWindow.__new__(MainWindow)
    win.message_queue = queue.Queue()
    win._active_background_threads = set()
    win._active_background_threads_lock = threading.Lock()
    win._background_shutdown_initiated = False
    return win


def test_background_registry_waits_and_blocks_after_shutdown():
    win = _build_window()
    done = threading.Event()

    def worker():
        time.sleep(0.05)
        done.set()

    assert MainWindow._start_background_thread(win, worker, "TestWorker")
    MainWindow._wait_active_background_threads(win, timeout=1.0)

    assert done.is_set()
    with win._active_background_threads_lock:
        assert not any(t.is_alive() for t in win._active_background_threads)

    MainWindow._begin_background_shutdown(win)
    assert not MainWindow._start_background_thread(win, lambda: None, "BlockedWorker")


def test_run_db_task_rejected_during_shutdown():
    win = _build_window()
    win.db = object()
    win._db_tasks_inflight = set()
    win._show_toast = lambda *_args, **_kwargs: None
    win._set_status = lambda *_args, **_kwargs: None

    MainWindow._begin_background_shutdown(win)
    started = MainWindow._run_db_task(
        win,
        task_name="db_stats",
        worker=lambda: {"ok": True},
        loading_text="DB 통계 조회 중...",
    )

    assert started is False
    assert "db_stats" not in win._db_tasks_inflight


def test_start_background_thread_rolls_back_on_start_failure(monkeypatch):
    win = _build_window()

    def fail_start(self):
        raise RuntimeError("boom")

    monkeypatch.setattr(threading.Thread, "start", fail_start)

    started = MainWindow._start_background_thread(win, lambda: None, "BrokenWorker")

    assert started is False
    with win._active_background_threads_lock:
        assert not win._active_background_threads
