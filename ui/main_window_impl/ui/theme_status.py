# -*- coding: utf-8 -*-

from __future__ import annotations

import unicodedata

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


_STATUS_ICONS = {
    "info": "ℹ️",
    "success": "✅",
    "warning": "⚠️",
    "error": "❌",
    "running": "🔄",
}
_STATUS_MAX_LENGTH = 100

# status -> (아이콘, 짧은 라벨)
_CONNECTION_STATES = {
    "idle": ("⚪", "대기"),
    "connecting": ("🔵", "접속 중"),
    "connected": ("🟢", "연결됨"),
    "reconnecting": ("🟡", "재연결 중"),
    "disconnected": ("🔴", "연결 끊김"),
}


def _starts_with_symbol(text: str) -> bool:
    """메시지가 이미 이모지/기호 아이콘으로 시작하는지 확인한다."""
    if not text:
        return False
    return unicodedata.category(text[0]) == "So"


class MainWindowUIThemeStatusMixin(MainWindowHost):
    def _apply_theme(self):
            # 테마 전환은 전체 스타일시트 교체만으로 처리한다.
            # 컴포넌트별 색상은 themes.py의 objectName 기반 QSS 규칙이
            # 두 테마 모두에 정의돼 있어 자동으로 다시 칠해진다.
            self.setStyleSheet(DARK_THEME if self.is_dark_theme else LIGHT_THEME)
            self.theme_action.setText("라이트 테마" if self.is_dark_theme else "다크 테마")

            # 토스트는 자식 위젯이 아니므로 스타일시트가 전파되지 않는다.
            # 현재 떠 있는 토스트만 새 테마에 맞춰 갱신한다.
            for toast in list(getattr(self, "active_toasts", [])):
                apply = getattr(toast, "apply_theme", None)
                if callable(apply):
                    apply(self.is_dark_theme)


    def _toggle_theme(self):
            self.is_dark_theme = not self.is_dark_theme
            self._save_setting_value(
                "dark_theme",
                self.is_dark_theme,
                context="테마 설정 저장",
            )
            self._apply_theme()


    def _toggle_tray_option(self):
            """트레이 최소화 옵션 토글"""
            self.minimize_to_tray = self.tray_action.isChecked()
            self._save_setting_value(
                "minimize_to_tray",
                self.minimize_to_tray,
                context="트레이 최소화 설정 저장",
            )
            if self.minimize_to_tray:
                self._show_toast("창을 닫으면 트레이로 최소화됩니다.", "info")
            else:
                self._show_toast("창을 닫으면 프로그램이 종료됩니다.", "info")


    def _toggle_keep_browser_on_stop(self):
            """수동 중지 시 Chrome 창 유지 옵션 토글"""
            self.keep_browser_on_stop = self.keep_browser_action.isChecked()
            self._save_setting_value(
                "keep_browser_on_stop",
                self.keep_browser_on_stop,
                context="Chrome 유지 설정 저장",
            )
            if self.keep_browser_on_stop:
                self._show_toast("수동 중지 시 Chrome 창을 유지합니다.", "info")
            else:
                self._show_toast("수동 중지 시 Chrome 창을 종료합니다.", "info")


    def _toggle_check_updates_on_startup(self):
            self.check_updates_on_startup = bool(
                self.check_updates_on_startup_action.isChecked()
            )
            self._save_setting_value(
                "check_updates_on_startup",
                self.check_updates_on_startup,
                context="시작 업데이트 확인 설정 저장",
            )

    def _setup_shortcuts(self):
            QShortcut(QKeySequence("F5"), self, self._start)
            QShortcut(QKeySequence("Escape"), self, self._handle_escape_shortcut)
            QShortcut(QKeySequence("F3"), self, lambda: self._nav_search(1))
            QShortcut(QKeySequence("Shift+F3"), self, lambda: self._nav_search(-1))


    def _show_toast(
            self, message: str, toast_type: str = "info", duration: int = 3000
        ) -> None:
            """토스트 알림 표시 - 스택 처리로 겹침 방지"""
            # 만료된 토스트 정리
            self.active_toasts = [t for t in self.active_toasts if t.isVisible()]

            # 새 토스트 y 위치 계산 (기존 토스트 아래에 배치)
            y_offset = 10
            for toast in self.active_toasts:
                y_offset += toast.height() + 5

            # 토스트 제거 콜백
            def remove_toast(t):
                if t in self.active_toasts:
                    self.active_toasts.remove(t)

            # 토스트 생성
            toast = ToastWidget(
                self.centralWidget(),
                message,
                duration,
                toast_type,
                y_offset=y_offset,
                on_close=remove_toast,
                is_dark=bool(getattr(self, "is_dark_theme", True)),
            )
            self.active_toasts.append(toast)

    def _report_user_visible_warning(
            self,
            message: str,
            *,
            toast: bool = True,
            status: bool = True,
        ) -> None:
            warning = str(message or "").strip()
            if not warning:
                return
            status_label = self.__dict__.get("status_label")
            central = None
            try:
                central = self.centralWidget()
            except Exception:
                central = None
            if status_label is None or central is None:
                pending = self.__dict__.get("_startup_warnings")
                if not isinstance(pending, list):
                    pending = []
                    self._startup_warnings = pending
                if warning not in pending:
                    pending.append(warning)
                return
            if status:
                self._set_status(warning, "warning")
            if toast:
                self._show_toast(warning, "warning", 4000)

    def _flush_startup_warnings(self) -> None:
            pending = self.__dict__.get("_startup_warnings", [])
            if not isinstance(pending, list) or not pending:
                return
            messages = [str(item).strip() for item in pending if str(item).strip()]
            self._startup_warnings = []
            for message in messages:
                self._report_user_visible_warning(message)


    def _set_status_now(self, text: str, status_type: str = "info"):
            """상태 표시 (아이콘 + 테마 색상)

            색상은 ``statusType`` 동적 속성과 themes의 QSS 규칙이 담당하므로
            테마 전환 시에도 자동으로 다시 칠해진다. 메시지가 이미 이모지로
            시작하면 아이콘을 중복으로 붙이지 않는다.
            """
            status_label = self.__dict__.get("status_label")
            if status_label is None:
                self._last_status_message = str(text or "")
                return
            if status_type not in _STATUS_ICONS:
                status_type = "info"
            message = str(text or "").strip()
            if _starts_with_symbol(message):
                full_text = message
            else:
                full_text = f"{_STATUS_ICONS[status_type]} {message}".strip()
            rendered = full_text
            if len(rendered) > _STATUS_MAX_LENGTH:
                rendered = rendered[: _STATUS_MAX_LENGTH - 1].rstrip() + "…"
            tooltip = full_text if rendered != full_text else ""
            if status_label.text() != rendered:
                status_label.setText(rendered)
            if status_label.toolTip() != tooltip:
                status_label.setToolTip(tooltip)
            set_state_property(status_label, "statusType", status_type)
            self._last_status_message = rendered

    def _set_status(self, text: str, status_type: str = "info"):
            self._set_status_now(text, status_type)


    def _update_count_label_now(self) -> None:
            """자막 카운트 라벨 업데이트"""
            count_label = self.__dict__.get("count_label")
            if count_label is None:
                return
            count = self._get_global_subtitle_count()
            chars = self._get_global_total_chars()
            rendered = f"📝 {count}문장 | {chars:,}자"
            if count_label.text() != rendered:
                count_label.setText(rendered)


    def _update_count_label(self):
            self._update_count_label_now()


    def _update_connection_status(self, status: str, latency: int | None = None):
            """연결 상태 칩 업데이트 (#30)

            Args:
                status: 'idle', 'connecting', 'connected', 'disconnected', 'reconnecting'
                latency: 응답 시간 (ms), 연결된 경우에만
            """
            if status not in _CONNECTION_STATES:
                status = "disconnected"
            self.connection_status = status
            icon, text = _CONNECTION_STATES[status]

            if latency is not None and status == "connected":
                self.ping_latency = latency
                tooltip = f"연결 상태: {text} (응답 {latency}ms)"
            elif status == "reconnecting":
                attempt = int(self.__dict__.get("reconnect_attempts", 0) or 0)
                text = f"재연결 {attempt}/{Config.MAX_RECONNECT_ATTEMPTS}"
                tooltip = (
                    f"연결 상태: 재연결 중 "
                    f"(시도 {attempt}/{Config.MAX_RECONNECT_ATTEMPTS})"
                )
            else:
                tooltip = f"연결 상태: {text}"

            indicator = self.__dict__.get("connection_indicator")
            if indicator is None:
                return
            rendered = f"{icon} {text}"
            if indicator.text() != rendered:
                indicator.setText(rendered)
            if indicator.toolTip() != tooltip:
                indicator.setToolTip(tooltip)
            set_state_property(indicator, "connState", status)


    def _set_font_size(self, size: int):
            """자막 영역 폰트 크기 변경"""
            size = max(Config.MIN_FONT_SIZE, min(size, Config.MAX_FONT_SIZE))
            self.font_size = size
            font = self.subtitle_text.font()
            font.setPointSize(size)
            self.subtitle_text.setFont(font)
            self._save_setting_value("font_size", size, context="글자 크기 설정 저장")


    def _adjust_font_size(self, delta: int):
            """폰트 크기 조절"""
            self._set_font_size(self.font_size + delta)


