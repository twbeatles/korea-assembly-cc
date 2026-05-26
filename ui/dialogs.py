# -*- coding: utf-8 -*-
from typing import Any

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QCloseEvent
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core.config import Config
from core.live_list import build_live_list_url, parse_live_list_payload


def _parse_live_list_payload(payload: bytes) -> dict[str, object]:
    return parse_live_list_payload(payload)


class LiveBroadcastDialog(QDialog):
    """현재 생중계 중인 방송 목록을 보여주고 선택하는 다이얼로그"""

    sig_fetch_done = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("국회 생중계 목록")
        self.resize(700, 450)
        self.selected_broadcast = None
        self._is_closing = False
        self._fetch_request_token = 0
        self._network_manager = QNetworkAccessManager(self)
        self._active_reply: QNetworkReply | None = None
        self._active_timeout_timer: QTimer | None = None
        self._auto_refresh_timer: QTimer | None = None

        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        title_label = QLabel("현재 / 종료 생중계 목록")
        font = title_label.font()
        font.setPointSize(12)
        font.setBold(True)
        title_label.setFont(font)
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.refresh_btn = QPushButton("새로고침")
        self.refresh_btn.clicked.connect(self.load_broadcasts)
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["상태", "위원회/회의명", "시작 시간", "xcode"])
        self.tree.setColumnWidth(0, 80)
        self.tree.setColumnWidth(1, 400)
        self.tree.setColumnWidth(2, 100)
        self.tree.setColumnHidden(3, True)
        self.tree.itemDoubleClicked.connect(self.accept_selection)
        layout.addWidget(self.tree)

        self.msg_label = QLabel("목록을 불러오는 중...")
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.msg_label)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept_selection)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self.setStyleSheet(
            """
            QTreeWidget::item { padding: 5px; }
            QTreeWidget::item:selected { background-color: #3b82f6; color: white; }
            """
        )
        self.sig_fetch_done.connect(self._on_fetch_done)
        self._start_auto_refresh_timer()
        QTimer.singleShot(100, self.load_broadcasts)

    def _start_auto_refresh_timer(self) -> None:
        interval_ms = max(1, int(Config.LIVE_BROADCAST_REFRESH_INTERVAL)) * 1000
        timer = self._auto_refresh_timer
        if timer is None:
            timer = QTimer(self)
            timer.timeout.connect(self.load_broadcasts)
            self._auto_refresh_timer = timer
        timer.setInterval(interval_ms)
        timer.start()

    def _pause_auto_refresh_timer(self) -> None:
        timer = self._auto_refresh_timer
        if timer is not None and timer.isActive():
            timer.stop()

    def _stop_auto_refresh_timer(self) -> None:
        timer = self._auto_refresh_timer
        self._auto_refresh_timer = None
        if timer is None:
            return
        timer.stop()
        timer.deleteLater()

    def showEvent(self, a0: Any) -> None:
        # 다이얼로그가 다시 표시될 때 자동 새로고침 재개
        if not self._is_closing:
            self._start_auto_refresh_timer()
        handler = getattr(super(), "showEvent", None)
        if a0 is not None and callable(handler):
            handler(a0)

    def hideEvent(self, a0: Any) -> None:
        # 다이얼로그가 숨겨지면 자동 새로고침 일시정지 (외부 API 호출 절약)
        self._pause_auto_refresh_timer()
        handler = getattr(super(), "hideEvent", None)
        if a0 is not None and callable(handler):
            handler(a0)

    def _abort_active_reply(self) -> None:
        timeout_timer = self._active_timeout_timer
        self._active_timeout_timer = None
        if timeout_timer is not None:
            timeout_timer.stop()
            timeout_timer.deleteLater()
        reply = self._active_reply
        if reply is None:
            return
        self._active_reply = None
        try:
            reply.finished.disconnect()
        except Exception:
            pass
        if reply.isRunning():
            reply.abort()
        reply.deleteLater()

    def load_broadcasts(self):
        """API 호출 요청"""
        if self._is_closing:
            return
        if not self.refresh_btn.isEnabled():
            return

        self._abort_active_reply()
        self.tree.clear()
        self.msg_label.setText("데이터 조회 중...")
        self.msg_label.show()
        self.refresh_btn.setEnabled(False)
        self._fetch_request_token += 1
        request_token = self._fetch_request_token

        api_url = build_live_list_url()
        request = QNetworkRequest(QUrl(api_url))
        request.setRawHeader(b"User-Agent", b"Mozilla/5.0")
        reply = self._network_manager.get(request)
        self._active_reply = reply
        completion = {"done": False}

        timeout_timer = QTimer(self)
        timeout_timer.setSingleShot(True)
        self._active_timeout_timer = timeout_timer

        def finalize(payload: dict[str, object]) -> None:
            if completion["done"]:
                return
            completion["done"] = True
            if self._active_timeout_timer is timeout_timer:
                self._active_timeout_timer = None
            timeout_timer.stop()
            timeout_timer.deleteLater()
            if reply is self._active_reply:
                self._active_reply = None
            try:
                reply.finished.disconnect()
            except Exception:
                pass
            reply.deleteLater()
            self.sig_fetch_done.emit(request_token, payload)

        def handle_timeout() -> None:
            if self._is_closing or reply is not self._active_reply:
                return
            if reply.isRunning():
                reply.abort()
            finalize(
                {
                    "ok": False,
                    "error": f"응답 시간 초과 ({Config.LIVE_LIST_REQUEST_TIMEOUT_MS}ms)",
                    "error_type": "timeout",
                }
            )

        def handle_finished() -> None:
            if completion["done"]:
                return
            payload: dict[str, object]
            if self._is_closing or reply is not self._active_reply:
                finalize({"ok": False, "error": "stale reply", "error_type": "stale"})
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                payload = {
                    "ok": False,
                    "error": reply.errorString(),
                    "error_type": "network",
                }
            else:
                payload = _parse_live_list_payload(bytes(reply.readAll()))
            finalize(payload)

        reply.finished.connect(handle_finished)
        timeout_timer.timeout.connect(handle_timeout)
        timeout_timer.start(Config.LIVE_LIST_REQUEST_TIMEOUT_MS)

    def _on_fetch_done(self, request_token: int, payload):
        """live_list fetch 완료 콜백 (UI 스레드)."""
        if self._is_closing or request_token != self._fetch_request_token:
            return
        self.refresh_btn.setEnabled(True)

        if not isinstance(payload, dict) or not payload.get("ok"):
            err = (
                payload.get("error", "알 수 없는 오류")
                if isinstance(payload, dict)
                else "알 수 없는 오류"
            )
            error_type = (
                str(payload.get("error_type", "") or "")
                if isinstance(payload, dict)
                else ""
            )
            if error_type == "invalid_schema":
                self.msg_label.setText(f"응답 구조 오류: {err}")
            elif error_type == "timeout":
                self.msg_label.setText(f"조회 시간 초과: {err}")
            else:
                self.msg_label.setText(f"조회 실패: {err}")
            return

        result = payload.get("result") or []
        dropped_rows = int(payload.get("dropped_rows", 0) or 0)
        if not result:
            if dropped_rows > 0:
                self.msg_label.setText(
                    f"표시할 생중계 항목이 없습니다. (손상 항목 {dropped_rows}개 제외)"
                )
            else:
                self.msg_label.setText("표시할 생중계 항목이 없습니다.")
            self.msg_label.show()
            return

        if dropped_rows > 0:
            self.msg_label.setText(f"일부 손상 항목 {dropped_rows}개를 제외했습니다.")
            self.msg_label.show()
        else:
            self.msg_label.hide()
        sorted_list = sorted(
            result,
            key=lambda x: (
                str(x.get("xstat", "")) != "1",
                not bool(str(x.get("xcgcd", "")).strip()),
                str(x.get("xname", "")),
            ),
        )

        added = 0
        for item in sorted_list:
            xstat = str(item.get("xstat", "")).strip()
            xcgcd = str(item.get("xcgcd", "")).strip()
            can_build_url = bool(xcgcd)

            status_text = "생중계" if xstat == "1" else "종료/예정"
            time_str = str(item.get("time", ""))
            if len(time_str) >= 12:
                time_fmt = f"{time_str[8:10]}:{time_str[10:12]}"
            else:
                time_fmt = time_str

            name = item.get("xname", "이름 없음")
            item_widget = QTreeWidgetItem(
                [status_text, name, time_fmt, item.get("xcode", "")]
            )
            item_widget.setData(0, Qt.ItemDataRole.UserRole, item)
            item_widget.setData(1, Qt.ItemDataRole.UserRole, can_build_url)

            if xstat == "1":
                font = item_widget.font(0)
                font.setBold(True)
                item_widget.setFont(0, font)
                item_widget.setForeground(0, QColor("#ef4444"))
                item_widget.setFont(1, font)
            else:
                for column in range(4):
                    item_widget.setForeground(column, QColor("gray"))
            if not can_build_url:
                item_widget.setToolTip(1, "현재 생중계 URL을 만들 수 없습니다.")
                for column in range(4):
                    item_widget.setForeground(column, QColor("#9ca3af"))

            self.tree.addTopLevelItem(item_widget)
            added += 1

        if added == 0:
            self.msg_label.setText("표시할 생중계 항목이 없습니다.")
            self.msg_label.show()
        else:
            self.tree.expandAll()

    def accept_selection(self):
        item = self.tree.currentItem()
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            can_build_url = bool(item.data(1, Qt.ItemDataRole.UserRole))
            if not can_build_url:
                QMessageBox.information(
                    self,
                    "URL 생성 불가",
                    "이 항목은 현재 생중계 URL을 만들 수 없습니다.",
                )
                return
            self.selected_broadcast = data
            self.accept()

    def done(self, a0: int) -> None:
        self._mark_closing()
        super().done(a0)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        self._mark_closing()
        if a0 is None:
            return
        super().closeEvent(a0)

    def _mark_closing(self):
        if self._is_closing:
            return
        self._is_closing = True
        self._fetch_request_token += 1
        self._stop_auto_refresh_timer()
        self._abort_active_reply()
