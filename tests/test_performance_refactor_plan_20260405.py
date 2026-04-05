import queue
import threading
from pathlib import Path
from typing import Callable

import pytest

from core.models import SubtitleEntry

mw_mod = pytest.importorskip("ui.main_window")
persistence_mod = pytest.importorskip("ui.main_window_persistence")
pipeline_messages_mod = pytest.importorskip("ui.main_window_impl.pipeline_messages")
view_render_mod = pytest.importorskip("ui.main_window_impl.view_render")

MainWindow = mw_mod.MainWindow


def test_ui_refresh_scheduler_coalesces_multiple_requests(monkeypatch):
    win = MainWindow.__new__(MainWindow)
    win._pending_ui_refresh_flags = 0
    win._pending_ui_refresh_force_full = False
    win._ui_refresh_scheduled = False
    win._use_async_ui_refresh = True
    win._pending_status_text = ""
    win._pending_status_type = "info"
    win._pending_search_count_index = None

    scheduled: list[Callable[[], None]] = []
    calls = {
        "status": [],
        "count": 0,
        "search": [],
        "render": [],
        "stats": 0,
    }

    monkeypatch.setattr(
        view_render_mod.QTimer,
        "singleShot",
        lambda _ms, callback: scheduled.append(callback),
    )
    win._set_status_now = lambda text, kind="info": calls["status"].append((text, kind))
    win._update_count_label_now = lambda: calls.__setitem__("count", calls["count"] + 1)
    win._update_search_count_label_now = lambda index=None: calls["search"].append(index)
    win._render_subtitles = lambda force_full=False: calls["render"].append(force_full)
    win._update_stats_now = lambda: calls.__setitem__("stats", calls["stats"] + 1)

    MainWindow._schedule_status_update(win, "saving", "running")
    MainWindow._schedule_ui_refresh(win, render=True, force_full=False)
    MainWindow._schedule_ui_refresh(
        win,
        render=True,
        force_full=True,
        count=True,
        stats=True,
        search_count=True,
        search_index=4,
    )

    assert len(scheduled) == 1
    assert calls["render"] == []

    scheduled.pop()()

    assert calls["status"] == [("saving", "running")]
    assert calls["count"] == 1
    assert calls["search"] == [4]
    assert calls["render"] == [True]
    assert calls["stats"] == 1


def test_process_message_queue_schedules_followup_drain_when_backlog_remains(monkeypatch):
    win = MainWindow.__new__(MainWindow)
    win._queue_drain_scheduled = False
    win._use_async_queue_drain = True
    win._overflow_passthrough_messages = [("toast", {"message": "x"})]
    win._coalesced_control_messages = {}
    win._coalesced_worker_messages = {}
    win.message_queue = queue.Queue()
    win._drain_overflow_passthrough_items = lambda max_items=50: 0
    win._drain_coalesced_control_messages = lambda max_items=50: 0
    win._drain_coalesced_worker_messages = lambda max_items=50: 0
    win._unwrap_message_item = lambda item: item
    win._handle_message = lambda *_args, **_kwargs: None

    scheduled: list[Callable[[], None]] = []
    monkeypatch.setattr(
        pipeline_messages_mod.QTimer,
        "singleShot",
        lambda _ms, callback: scheduled.append(callback),
    )

    MainWindow._process_message_queue(win)

    assert len(scheduled) == 1
    assert win._queue_drain_scheduled is True


def test_read_global_entries_window_reuses_cached_window(monkeypatch):
    win = MainWindow.__new__(MainWindow)
    win._runtime_archived_count = 4
    win._runtime_tail_revision = 2
    win._runtime_render_window_cache_key = None
    win._runtime_render_window_cache_entries = []
    win._runtime_segment_locator_starts = [0, 2]
    win._runtime_segment_locator_ends = [2, 4]
    win._runtime_segment_locator_items = [
        {"path": "segment_a.json", "start_index": 0, "end_index": 2, "entry_count": 2},
        {"path": "segment_b.json", "start_index": 2, "end_index": 4, "entry_count": 2},
    ]
    win.subtitle_lock = threading.Lock()
    win.subtitles = []

    segment_entries = {
        "segment_a.json": [SubtitleEntry("a0"), SubtitleEntry("a1")],
        "segment_b.json": [SubtitleEntry("b0"), SubtitleEntry("b1")],
    }
    load_calls: list[str] = []

    def load_segment(segment_info, *, runtime_root=None):
        _ = runtime_root
        path = str(segment_info["path"])
        load_calls.append(path)
        return segment_entries[path]

    win._load_runtime_segment_entries = load_segment

    first = MainWindow._read_global_entries_window(win, 1, 3, clone_entries=False)
    second = MainWindow._read_global_entries_window(win, 1, 3, clone_entries=False)

    assert [entry.text for entry in first] == ["a1", "b0"]
    assert [entry.text for entry in second] == ["a1", "b0"]
    assert load_calls == ["segment_a.json", "segment_b.json"]

    win._runtime_tail_revision = 3
    MainWindow._read_global_entries_window(win, 1, 3, clone_entries=False)

    assert load_calls == [
        "segment_a.json",
        "segment_b.json",
        "segment_a.json",
        "segment_b.json",
    ]


def test_write_session_snapshot_uses_runtime_manifest_snapshot(tmp_path, monkeypatch):
    output_path = tmp_path / "session.json"
    win = MainWindow.__new__(MainWindow)
    win._build_session_save_context = lambda: ("https://assembly.example/live", "행안위", 123)
    win._runtime_segment_manifest = []
    win.db = None
    recorded: dict[str, object] = {}

    monkeypatch.setattr(
        persistence_mod.utils,
        "atomic_write_json_stream",
        lambda path, **kwargs: recorded.update(
            {
                "path": str(path),
                "items": list(kwargs["sequence_items"]),
            }
        ),
    )
    win._record_recovery_snapshot = lambda *args, **kwargs: recorded.update({"recovery": True})

    def iter_serialized(prepared_entries, *, runtime_root=None, runtime_manifest=None):
        recorded["runtime_root"] = runtime_root
        recorded["runtime_manifest"] = list(runtime_manifest or [])
        for item in [{"text": "archived"}, {"text": "tail"}]:
            yield item

    win._iter_full_session_serialized_items = iter_serialized

    info = MainWindow._write_session_snapshot(
        win,
        str(output_path),
        [SubtitleEntry("tail")],
        include_db=False,
        runtime_root=Path("runtime"),
        runtime_manifest=[{"path": "segment_000001.json", "entry_count": 1}],
    )

    assert recorded["path"] == str(output_path)
    assert recorded["items"] == [{"text": "archived"}, {"text": "tail"}]
    assert recorded["runtime_root"] == Path("runtime")
    assert recorded["runtime_manifest"] == [{"path": "segment_000001.json", "entry_count": 1}]
    assert info["saved_count"] == 2


def test_save_txt_streams_from_runtime_segments_without_full_hydration(tmp_path, monkeypatch):
    target_path = tmp_path / "subtitles.txt"
    win = MainWindow.__new__(MainWindow)
    win._generate_smart_filename = lambda ext: f"test.{ext}"
    win._build_prepared_entries_snapshot = lambda: [SubtitleEntry("tail line")]
    win._snapshot_runtime_stream_context = lambda: (
        Path("runtime"),
        [{"path": "segment_000001.json", "entry_count": 1}],
    )

    def fail_full_hydration(*_args, **_kwargs):
        raise AssertionError("full hydration should not be used for TXT export")

    win._build_complete_session_entries_snapshot = fail_full_hydration
    win._save_in_background = lambda save_func, path, *_args: save_func(path)

    called: dict[str, object] = {}

    def iter_rows(prepared_entries, *, runtime_root=None, runtime_manifest=None):
        called["prepared_count"] = len(prepared_entries)
        called["runtime_root"] = runtime_root
        called["runtime_manifest"] = list(runtime_manifest or [])
        yield SubtitleEntry("archived").timestamp, "archived line", True
        yield prepared_entries[0].timestamp, prepared_entries[0].text, False

    win._iter_display_session_rows = iter_rows

    monkeypatch.setattr(
        persistence_mod.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(target_path), "txt"),
    )

    MainWindow._save_txt(win)

    assert called["prepared_count"] == 1
    assert called["runtime_root"] == Path("runtime")
    assert called["runtime_manifest"] == [{"path": "segment_000001.json", "entry_count": 1}]
    saved_text = target_path.read_text(encoding="utf-8-sig")
    assert "archived line" in saved_text
    assert "tail line" in saved_text
