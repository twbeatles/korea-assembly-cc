"""자막 수집 UI/UX 다듬기 회귀 테스트 (2026-09-30).

- 상태 라벨: 테마 QSS(statusType 속성) 기반 색상, 이모지 중복 방지, 말줄임 + 툴팁
- 연결 칩: idle/connecting/connected/reconnecting/disconnected 상태 텍스트·속성
- 진행 바: 접속 확인 시 숨김, 재연결 중 다시 표시
- 실행 시간: 중지 후 고정 (통계/세션 저장 duration 공통)
- 종료 상태: 성공 완료 시 idle 칩 + 수집 요약
"""

import time
from types import SimpleNamespace
from typing import Any

import pytest

mw_mod = pytest.importorskip("ui.main_window")
widgets_mod = pytest.importorskip("ui.widgets")
from PyQt6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

import ui.main_window_impl.pipeline_messages as pipeline_messages_mod  # noqa: E402
from ui.themes import DARK_THEME, LIGHT_THEME, get_palette  # noqa: E402

MainWindow = mw_mod.MainWindow


_APP_REF: list[Any] = []


def _qapp() -> Any:
    # QApplication이 GC되면 위젯 생성 시 크래시하므로 모듈 수명 동안 참조를 유지한다.
    if not _APP_REF:
        _APP_REF.append(QApplication.instance() or QApplication([]))
    return _APP_REF[0]


class _FakeProgress:
    def __init__(self) -> None:
        self.visible = True

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False


def test_status_label_uses_theme_property_and_avoids_duplicate_icon() -> None:
    _qapp()
    win = MainWindow.__new__(MainWindow)
    win.status_label = QLabel()

    MainWindow._set_status_now(win, "✅ 생중계 감지 성공!", "running")
    assert win.status_label.text() == "✅ 생중계 감지 성공!"
    assert win.status_label.property("statusType") == "running"
    assert win.status_label.styleSheet() == ""

    MainWindow._set_status_now(win, "자막 모니터링 중", "unknown-type")
    assert win.status_label.text() == "ℹ️ 자막 모니터링 중"
    assert win.status_label.property("statusType") == "info"


def test_status_label_truncates_with_ellipsis_and_full_tooltip() -> None:
    _qapp()
    win = MainWindow.__new__(MainWindow)
    win.status_label = QLabel()
    long_text = "가" * 150

    MainWindow._set_status_now(win, long_text, "error")

    rendered = win.status_label.text()
    assert len(rendered) == 100
    assert rendered.endswith("…")
    assert win.status_label.toolTip() == f"❌ {long_text}"

    MainWindow._set_status_now(win, "짧은 메시지", "error")
    assert win.status_label.toolTip() == ""


def test_connection_chip_states() -> None:
    _qapp()
    cases = [
        ("idle", "⚪ 대기"),
        ("connecting", "🔵 접속 중"),
        ("connected", "🟢 연결됨"),
        ("disconnected", "🔴 연결 끊김"),
        ("bogus", "🔴 연결 끊김"),
    ]
    for status, expected_text in cases:
        win = MainWindow.__new__(MainWindow)
        win.connection_indicator = QLabel()

        MainWindow._update_connection_status(win, status, 42)

        assert win.connection_indicator.text() == expected_text
        expected_state = status if status != "bogus" else "disconnected"
        assert win.connection_indicator.property("connState") == expected_state
        assert win.connection_status == expected_state
        if status == "connected":
            assert "42ms" in win.connection_indicator.toolTip()


def test_connection_chip_reconnecting_shows_attempt() -> None:
    _qapp()
    win = MainWindow.__new__(MainWindow)
    win.connection_indicator = QLabel()
    win.reconnect_attempts = 2

    MainWindow._update_connection_status(win, "reconnecting")

    assert win.connection_indicator.text().startswith("🟡 재연결 2/")


def test_connection_status_tolerates_missing_indicator() -> None:
    win = MainWindow.__new__(MainWindow)
    MainWindow._update_connection_status(win, "idle")
    assert win.connection_status == "idle"


def test_elapsed_time_freezes_after_stop() -> None:
    win = MainWindow.__new__(MainWindow)
    now = time.time()
    win.start_time = now - 100
    win.is_running = False
    win._capture_end_time = now - 40

    assert MainWindow._get_capture_elapsed_seconds(win) == 60

    win.is_running = True
    assert MainWindow._get_capture_elapsed_seconds(win) >= 100

    win.start_time = None
    assert MainWindow._get_capture_elapsed_seconds(win) == 0


def test_session_save_duration_uses_frozen_elapsed_time() -> None:
    win = MainWindow.__new__(MainWindow)
    now = time.time()
    win.start_time = now - 500
    win.is_running = False
    win._capture_end_time = now - 400
    win._capture_source_url = "https://assembly.webcast.go.kr/main/player.asp?xcode=10"
    win._capture_source_committee = "본회의"

    _url, _committee, duration = MainWindow._build_session_save_context(win)

    assert duration == 100


def test_capture_summary_text_formats_counts_and_elapsed() -> None:
    win = MainWindow.__new__(MainWindow)
    win._get_global_subtitle_count = lambda: 1234
    win._get_global_total_chars = lambda: 56789
    win._get_capture_elapsed_seconds = lambda: 3725

    assert MainWindow._build_capture_summary_text(win) == "1,234문장 · 56,789자 · 01:02:05"

    win._get_global_subtitle_count = lambda: (_ for _ in ()).throw(RuntimeError("x"))
    assert MainWindow._build_capture_summary_text(win) == ""


def _message_window() -> tuple[Any, list[tuple[str, str]], list[str]]:
    win: Any = MainWindow.__new__(MainWindow)
    win._is_stopping = False
    win.is_running = True
    win.progress = _FakeProgress()
    win.reconnect_attempts = 0
    statuses: list[tuple[str, str]] = []
    connection: list[str] = []
    win._schedule_status_update = lambda text, level: statuses.append((text, level))
    win._update_connection_status = lambda status, *_a: connection.append(status)
    win._show_toast = lambda *_a, **_k: None
    return win, statuses, connection


def test_connected_status_hides_progress_and_reconnecting_shows_it() -> None:
    win, statuses, connection = _message_window()

    MainWindow._handle_message(win, "connection_status", {"status": "connected", "latency": 10})
    assert win.progress.visible is False
    assert connection == ["connected"]

    MainWindow._handle_message(
        win, "reconnecting", {"attempt": 1, "max_attempts": 5, "delay": 2}
    )
    assert win.progress.visible is True
    assert connection[-1] == "reconnecting"
    assert statuses[-1][1] == "warning"
    assert "1/" in statuses[-1][0] and "2초 후 재시도" in statuses[-1][0]


def test_worker_status_message_type_follows_prefix_and_running_state() -> None:
    win, statuses, _connection = _message_window()
    win._last_status_message = ""

    MainWindow._handle_message(win, "status", "자막 모니터링 중")
    MainWindow._handle_message(win, "status", "⚠️ 생중계 감지 실패")
    MainWindow._handle_message(win, "status", "✅ 재연결 성공 (시도 1)")
    win.is_running = False
    MainWindow._handle_message(win, "status", "대기 메시지")

    assert [level for _text, level in statuses] == ["running", "warning", "success", "info"]


def test_finished_success_sets_idle_chip_and_summary(monkeypatch) -> None:
    win, statuses, connection = _message_window()
    win.worker = object()
    win._retire_capture_run = lambda: None
    win._reset_ui = lambda: None
    win._update_tray_status = lambda *_a: None
    win._clear_preview = lambda: None
    win._build_capture_summary_text = lambda: "3문장 · 30자 · 00:00:10"

    MainWindow._handle_message(
        win, "finished", {"success": True, "finalize_preview": False}
    )

    assert connection == ["idle"]
    assert statuses == [("수집 완료 — 3문장 · 30자 · 00:00:10", "success")]


def test_infer_worker_status_type_helper() -> None:
    infer = pipeline_messages_mod._infer_worker_status_type
    assert infer("⚠️ x", "info") == "warning"
    assert infer("❌ x", "info") == "error"
    assert infer("✅ x", "info") == "success"
    assert infer("plain", "running") == "running"


def test_themes_define_capture_state_rules_for_both_palettes() -> None:
    for is_dark, theme in ((True, DARK_THEME), (False, LIGHT_THEME)):
        palette = get_palette(is_dark)
        for key in (
            "state_info",
            "state_success",
            "state_warning",
            "state_error",
            "state_running",
            "state_idle",
        ):
            assert key in palette
        assert 'QLabel#statusLabel[statusType="error"]' in theme
        assert 'QLabel#connectionIndicator[connState="connected"]' in theme
        assert "QPushButton#stopBtn:disabled" in theme
        assert "QProgressBar#captureProgress" in theme
        assert "QFrame#previewFrame" in theme


def test_overlay_anchor_keeps_button_bottom_center() -> None:
    _qapp()
    host = QWidget()
    host.resize(400, 300)
    overlay = QLabel("⬇️ 최신 자막", host)
    anchor = widgets_mod.OverlayAnchor(host, overlay, bottom_margin=10)

    anchor.reposition()

    assert overlay.x() == (400 - overlay.width()) // 2
    assert overlay.y() == 300 - overlay.height() - 10

    host.resize(600, 200)
    anchor.reposition()
    assert overlay.x() == (600 - overlay.width()) // 2
    assert overlay.y() == 200 - overlay.height() - 10


def test_set_state_property_only_repolishes_on_change() -> None:
    _qapp()
    label = QLabel()
    assert widgets_mod.set_state_property(label, "connState", "idle") is True
    assert widgets_mod.set_state_property(label, "connState", "idle") is False
    assert widgets_mod.set_state_property(None, "connState", "idle") is False


def test_stop_disables_stop_button_and_reports_idle(monkeypatch) -> None:
    win = MainWindow.__new__(MainWindow)
    win.is_running = True
    win.keep_browser_on_stop = False
    win.stop_event = SimpleNamespace(set=lambda: None)
    stop_btn_state: list[bool] = []
    win.stop_btn = SimpleNamespace(setEnabled=lambda value: stop_btn_state.append(value))
    statuses: list[tuple[str, str]] = []
    connection: list[str] = []
    win._set_status = lambda text, level="info": statuses.append((text, level))
    win._update_connection_status = lambda status, *_a: connection.append(status)
    win._build_capture_summary_text = lambda: "1문장 · 5자 · 00:00:03"
    for name in (
        "_cancel_scheduled_subtitle_reset",
        "_materialize_pending_preview",
        "_finalize_pending_subtitle",
        "_clear_preview",
        "_close_realtime_save_file",
        "_reset_realtime_save_run_state",
        "_retire_capture_run",
        "_clear_message_queue",
        "_reset_ui",
    ):
        setattr(win, name, lambda *_a, **_k: None)
    win._drain_pending_previews = lambda **_k: None
    win._current_capture_settings = lambda: {}
    win._sync_capture_state_entries = lambda **_k: None
    win._cleanup_detached_drivers_with_timeout = lambda **_k: None
    win._update_tray_status = lambda *_a: None
    win._wait_worker_shutdown = lambda timeout: True
    win._take_current_driver = lambda: None
    from core.subtitle_pipeline import create_empty_capture_state

    win.capture_state = create_empty_capture_state()

    MainWindow._stop(win)

    assert stop_btn_state == [False]
    assert statuses[0][1] == "warning"
    assert statuses[-1] == ("⏹ 중지됨 — 1문장 · 5자 · 00:00:03", "info")
    assert connection == ["idle"]


class _HiddenFrame:
    def isVisible(self) -> bool:
        return False


def _escape_window(confirm_answer: bool) -> tuple[Any, list[str]]:
    win: Any = MainWindow.__new__(MainWindow)
    win.search_frame = _HiddenFrame()
    win.is_running = True
    calls: list[str] = []
    win._stop = lambda *_a, **_k: calls.append("stop")

    def fake_confirm() -> bool:
        calls.append("confirm")
        return confirm_answer

    win._confirm_escape_stop = fake_confirm
    return win, calls


def test_escape_asks_before_stopping_by_default() -> None:
    win, calls = _escape_window(confirm_answer=False)
    MainWindow._handle_escape_shortcut(win)
    assert calls == ["confirm"]

    win, calls = _escape_window(confirm_answer=True)
    MainWindow._handle_escape_shortcut(win)
    assert calls == ["confirm", "stop"]


def test_escape_skips_confirmation_when_disabled() -> None:
    win, calls = _escape_window(confirm_answer=False)
    win.confirm_escape_stop = False
    MainWindow._handle_escape_shortcut(win)
    assert calls == ["stop"]


def test_escape_does_not_stop_if_capture_ended_during_dialog() -> None:
    win, calls = _escape_window(confirm_answer=True)

    def confirm_then_finish() -> bool:
        calls.append("confirm")
        win.is_running = False
        return True

    win._confirm_escape_stop = confirm_then_finish
    MainWindow._handle_escape_shortcut(win)
    assert calls == ["confirm"]


def test_escape_is_noop_when_not_running() -> None:
    win, calls = _escape_window(confirm_answer=True)
    win.is_running = False
    MainWindow._handle_escape_shortcut(win)
    assert calls == []


def test_set_confirm_escape_stop_persists_and_syncs_menu() -> None:
    _qapp()
    from PyQt6.QtGui import QAction

    win: Any = MainWindow.__new__(MainWindow)
    action = QAction("Esc로 중지 전 확인")
    action.setCheckable(True)
    action.setChecked(True)
    win.confirm_escape_stop_action = action
    saved: list[tuple[str, object]] = []
    win._save_setting_value = lambda key, value, **_k: saved.append((key, value))

    MainWindow._set_confirm_escape_stop(win, False)

    assert win.confirm_escape_stop is False
    assert action.isChecked() is False
    assert saved == [("confirm_escape_stop", False)]
