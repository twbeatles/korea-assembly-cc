# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false

import json
import time

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QCloseEvent
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core.config import Config


def _normalize_live_list_row(item: object) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    xcgcd = str(item.get("xcgcd", "") or "").strip()
    if not xcgcd:
        return None
    return {
        "xstat": str(item.get("xstat", "") or "").strip(),
        "xcgcd": xcgcd,
        "xcode": str(item.get("xcode", "") or "").strip(),
        "xname": str(item.get("xname", "이름 없음") or "이름 없음").strip() or "이름 없음",
        "time": str(item.get("time", "") or "").strip(),
    }


def _parse_live_list_payload(payload: bytes) -> dict[str, object]:
    try:
        decoded = payload.decode("utf-8", errors="replace")
        data = json.loads(decoded)
    except Exception as e:
        return {"ok": False, "error": str(e), "error_type": "invalid_json"}

    if not isinstance(data, dict):
        return {
            "ok": False,
            "error": "응답 루트가 객체(dict)가 아닙니다.",
            "error_type": "invalid_schema",
        }

    rows = data.get("xlist")
    if not isinstance(rows, list):
        return {
            "ok": False,
            "error": "응답의 xlist가 목록(list)이 아닙니다.",
            "error_type": "invalid_schema",
        }

    valid_rows: list[dict[str, str]] = []
    dropped_rows = 0
    for item in rows:
        normalized = _normalize_live_list_row(item)
        if normalized is None:
            dropped_rows += 1
            continue
        valid_rows.append(normalized)

    if not valid_rows and rows:
        return {
            "ok": False,
            "error": f"유효한 방송 항목이 없습니다. (손상 항목 {dropped_rows}개)",
            "error_type": "invalid_schema",
            "dropped_rows": dropped_rows,
        }

    return {
        "ok": True,
        "result": valid_rows,
        "dropped_rows": dropped_rows,
        "error_type": "none",
    }


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
        QTimer.singleShot(100, self.load_broadcasts)

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

        api_url = (
            f"https://assembly.webcast.go.kr/main/service/live_list.asp?vv={int(time.time())}"
        )
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
        if not result:
            self.msg_label.setText("표시할 생중계 항목이 없습니다.")
            return

        dropped_rows = int(payload.get("dropped_rows", 0) or 0)
        if dropped_rows > 0:
            self.msg_label.setText(f"일부 손상 항목 {dropped_rows}개를 제외했습니다.")
            self.msg_label.show()
        else:
            self.msg_label.hide()
        sorted_list = sorted(result, key=lambda x: str(x.get("xstat", "")) != "1")

        added = 0
        for item in sorted_list:
            xstat = str(item.get("xstat", "")).strip()
            xcgcd = str(item.get("xcgcd", "")).strip()
            if not xcgcd:
                continue

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

            if xstat == "1":
                font = item_widget.font(0)
                font.setBold(True)
                item_widget.setFont(0, font)
                item_widget.setForeground(0, QColor("#ef4444"))
                item_widget.setFont(1, font)
            else:
                item_widget.setForeground(0, QColor("gray"))

            self.tree.addTopLevelItem(item_widget)
            added += 1

        if added == 0:
            self.msg_label.setText("현재 선택 가능한 생중계가 없습니다.")
            self.msg_label.show()
        else:
            self.tree.expandAll()

    def accept_selection(self):
        item = self.tree.currentItem()
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
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
        self._abort_active_reply()
