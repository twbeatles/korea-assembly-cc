# -*- coding: utf-8 -*-

from __future__ import annotations

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowUITrayMixin(MainWindowHost):
    def _setup_tray(self):
            """시스템 트레이 아이콘 설정"""
            self.tray_icon = QSystemTrayIcon(self)
            self.tray_icon.setToolTip(f"{Config.APP_NAME} v{Config.VERSION}")

            # 기본 아이콘 (앱 아이콘이 없으면 기본 아이콘 사용)
            app_icon = self.windowIcon()
            if not app_icon.isNull():
                self.tray_icon.setIcon(app_icon)
            else:
                # 기본 아이콘 사용
                style = self.style()
                assert style is not None
                self.tray_icon.setIcon(
                    style.standardIcon(style.StandardPixmap.SP_ComputerIcon)
                )

            # 트레이 메뉴
            tray_menu = QMenu()

            show_action = QAction("🏛️ 창 보이기", self)
            show_action.triggered.connect(self._show_from_tray)
            tray_menu.addAction(show_action)

            tray_menu.addSeparator()

            # 추출 상태 표시
            self.tray_status_action = QAction("⚪ 대기 중", self)
            self.tray_status_action.setEnabled(False)
            tray_menu.addAction(self.tray_status_action)

            tray_menu.addSeparator()

            start_action = QAction("▶ 시작", self)
            start_action.triggered.connect(self._start)
            tray_menu.addAction(start_action)

            stop_action = QAction("⏹ 중지", self)
            stop_action.triggered.connect(self._stop)
            tray_menu.addAction(stop_action)

            tray_menu.addSeparator()

            quit_action = QAction("❌ 종료", self)
            quit_action.triggered.connect(self._quit_from_tray)
            tray_menu.addAction(quit_action)

            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.activated.connect(self._tray_activated)
            self.tray_icon.show()


    def _show_from_tray(self):
            """트레이에서 창 복원"""
            self.showNormal()
            self.activateWindow()
            self.raise_()


    def _quit_from_tray(self):
            """트레이에서 완전 종료"""
            self.minimize_to_tray = False  # 트레이 최소화 비활성화
            self.close()


    def _tray_activated(self, reason):
            """트레이 아이콘 클릭 처리"""
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
                self._show_from_tray()


    def _update_tray_status(self, status: str):
            """트레이 상태 업데이트"""
            if hasattr(self, "tray_status_action"):
                self.tray_status_action.setText(status)


