from __future__ import annotations

import ui.main_window as mw_mod


MainWindow = mw_mod.MainWindow


def _build_window() -> MainWindow:
    win = MainWindow.__new__(MainWindow)
    win._is_stopping = False
    return win


def test_clear_only_succeeds_for_current_revision() -> None:
    win = _build_window()

    saved_revision = win._mark_session_dirty()
    current_revision = win._mark_session_dirty()

    assert current_revision > saved_revision
    assert win._clear_session_dirty(saved_revision=saved_revision) is False
    assert win._has_dirty_session() is True
    assert win._get_session_revision() == current_revision


def test_clear_current_revision_marks_session_clean() -> None:
    win = _build_window()

    saved_revision = win._mark_session_dirty()

    assert win._clear_session_dirty(saved_revision=saved_revision) is True
    assert win._has_dirty_session() is False


def test_revision_state_preserves_legacy_dirty_flag() -> None:
    win = _build_window()
    win._session_dirty = True

    assert win._has_dirty_session() is True
    assert win._get_session_revision() == 1


def test_reset_session_revision_establishes_new_baseline() -> None:
    win = _build_window()
    win._mark_session_dirty()
    win._mark_session_dirty()

    win._reset_session_revision(dirty=False)

    assert win._get_session_revision() == 0
    assert win._has_dirty_session() is False


def test_async_save_result_carries_snapshot_revision() -> None:
    win = _build_window()
    snapshot_revision = win._mark_session_dirty()
    win._session_save_in_progress = False
    win._set_status = lambda *_args, **_kwargs: None
    win._show_toast = lambda *_args, **_kwargs: None
    win._write_session_snapshot = lambda *_args, **_kwargs: {"saved_count": 0}
    emitted: list[tuple[str, object]] = []
    win._emit_control_message = lambda msg_type, data: emitted.append((msg_type, data))
    win._start_background_thread = lambda target, _name: target() or True

    assert win._start_async_session_snapshot_save("session.json", []) is True

    assert emitted[0][0] == "session_save_done"
    assert isinstance(emitted[0][1], dict)
    assert emitted[0][1]["snapshot_revision"] == snapshot_revision


def test_stale_async_save_completion_keeps_dirty_and_does_not_resume() -> None:
    win = _build_window()
    saved_revision = win._mark_session_dirty()
    win._mark_session_dirty()
    win._session_save_in_progress = True
    recovery_cleared: list[bool] = []
    resumed: list[bool] = []
    pending_cleared: list[bool] = []
    win._clear_recovery_state = lambda: recovery_cleared.append(True)
    win._resume_pending_deferred_action = lambda: resumed.append(True) or True
    win._clear_pending_deferred_action = lambda: pending_cleared.append(True)
    win._set_status = lambda *_args, **_kwargs: None
    win._show_toast = lambda *_args, **_kwargs: None
    win._apply_saved_session_db_identity = lambda _info: None

    win._handle_message(
        "session_save_done",
        {"saved_count": 0, "snapshot_revision": saved_revision},
    )

    assert win._has_dirty_session() is True
    assert recovery_cleared == []
    assert resumed == []
    assert pending_cleared == [True]


def test_current_async_save_completion_clears_and_resumes() -> None:
    win = _build_window()
    saved_revision = win._mark_session_dirty()
    win._session_save_in_progress = True
    recovery_cleared: list[bool] = []
    resumed: list[bool] = []
    win._clear_recovery_state = lambda: recovery_cleared.append(True)
    win._resume_pending_deferred_action = lambda: resumed.append(True) or True
    win._set_status = lambda *_args, **_kwargs: None
    win._show_toast = lambda *_args, **_kwargs: None
    win._apply_saved_session_db_identity = lambda _info: None

    win._handle_message(
        "session_save_done",
        {"saved_count": 0, "snapshot_revision": saved_revision},
    )

    assert win._has_dirty_session() is False
    assert recovery_cleared == [True]
    assert resumed == [True]
