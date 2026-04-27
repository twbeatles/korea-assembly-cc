# -*- coding: utf-8 -*-

from __future__ import annotations

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowUIThemeStatusMixin(MainWindowHost):
    def _apply_theme(self):
            self.setStyleSheet(DARK_THEME if self.is_dark_theme else LIGHT_THEME)
            self.theme_action.setText("라이트 테마" if self.is_dark_theme else "다크 테마")

            # 테마에 따른 동적 스타일 업데이트
            if self.is_dark_theme:
                stat_bg = "rgba(88, 166, 255, 0.08)"
                search_bg = "rgba(88, 166, 255, 0.05)"
                search_border = "rgba(88, 166, 255, 0.2)"
                status_bg = "rgba(48, 54, 61, 0.3)"
                count_color = "#8b949e"
                preview_bg = "rgba(88, 166, 255, 0.08)"
                preview_border = "rgba(88, 166, 255, 0.25)"
            else:
                stat_bg = "rgba(9, 105, 218, 0.06)"
                search_bg = "rgba(9, 105, 218, 0.04)"
                search_border = "rgba(9, 105, 218, 0.15)"
                status_bg = "rgba(208, 215, 222, 0.4)"
                count_color = "#57606a"
                preview_bg = "rgba(9, 105, 218, 0.05)"
                preview_border = "rgba(9, 105, 218, 0.15)"

            # 통계 라벨 스타일 업데이트
            try:
                stat_labels = [
                    self.stat_time,
                    self.stat_chars,
                    self.stat_words,
                    self.stat_sents,
                    self.stat_cpm,
                ]
                for label in stat_labels:
                    label.setStyleSheet(f"""
                        padding: 6px 8px;
                        border-radius: 6px;
                        background-color: {stat_bg};
                    """)

                # 검색바 스타일 업데이트
                self.search_frame.setStyleSheet(f"""
                    QFrame {{
                        background-color: {search_bg};
                        border: 1px solid {search_border};
                        border-radius: 10px;
                        padding: 5px;
                    }}
                """)

                # 상태바 카운트 라벨 색상 업데이트
                self.count_label.setStyleSheet(
                    f"color: {count_color}; background: transparent; border: none;"
                )

                # 미리보기 영역 스타일 업데이트
                if hasattr(self, "preview_frame"):
                    self.preview_frame.setStyleSheet(
                        f"background-color: {preview_bg}; border: 1px solid {preview_border}; "
                        "border-radius: 8px;"
                    )
            except AttributeError:
                # UI가 아직 완전히 초기화되지 않은 경우
                pass


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
            """상태 표시 (아이콘 + 색상)"""
            status_label = self.__dict__.get("status_label")
            if status_label is None:
                self._last_status_message = str(text or "")
                return
            icons = {
                "info": "ℹ️",
                "success": "✅",
                "warning": "⚠️",
                "error": "❌",
                "running": "🔄",
            }
            colors = {
                "info": "#4fc3f7",
                "success": "#4caf50",
                "warning": "#ff9800",
                "error": "#f44336",
                "running": "#ab47bc",
            }
            icon = icons.get(status_type, "")
            color = colors.get(status_type, "#eaeaea")
            rendered = f"{icon} {text}"[:100]
            current_style = f"color: {color};"
            if status_label.text() != rendered:
                status_label.setText(rendered)
            if status_label.styleSheet() != current_style:
                status_label.setStyleSheet(current_style)
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
            """연결 상태 인디케이터 업데이트 (#30)

            Args:
                status: 'connected', 'disconnected', 'reconnecting'
                latency: 응답 시간 (ms), 연결된 경우에만
            """
            self.connection_status = status

            # 상태별 아이콘과 툴팁
            status_config = {
                "connected": ("🟢", "#4caf50", "연결됨"),
                "disconnected": ("🔴", "#f44336", "연결 끊김"),
                "reconnecting": ("🟡", "#ff9800", "재연결 중..."),
            }

            icon, color, text = status_config.get(status, ("⚫", "#888", "알 수 없음"))

            # 레이턴시가 있으면 툴팁에 표시
            if latency is not None and status == "connected":
                self.ping_latency = latency
                tooltip = f"연결 상태: {text} ({latency}ms)"
            elif status == "reconnecting":
                tooltip = f"연결 상태: {text} (시도 {self.reconnect_attempts}/{Config.MAX_RECONNECT_ATTEMPTS})"
            else:
                tooltip = f"연결 상태: {text}"

            current_style = (
                f"background: transparent; border: none; font-size: 12px; color: {color};"
            )
            if self.connection_indicator.text() != icon:
                self.connection_indicator.setText(icon)
            if self.connection_indicator.toolTip() != tooltip:
                self.connection_indicator.setToolTip(tooltip)
            if self.connection_indicator.styleSheet() != current_style:
                self.connection_indicator.setStyleSheet(current_style)


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


