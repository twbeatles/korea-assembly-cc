# -*- coding: utf-8 -*-

import json
import time
from urllib.request import Request, urlopen

from PyQt6.QtCore import Qt, QTimer, QObject, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

from core.config import Config

class _LiveListFetchWorker(QObject):
    """live_list.asp API 호출을 UI와 분리하기 위한 워커."""

    finished = pyqtSignal(object)  # {"ok": bool, "result": list} 또는 {"ok": False, "error": str}

    @pyqtSlot()
    def fetch(self):
        """API 호출을 수행하는 슬롯"""
        try:
            api_url = f"https://assembly.webcast.go.kr/main/service/live_list.asp?vv={int(time.time())}"
            req = Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=Config.API_TIMEOUT) as response:
                payload = response.read().decode("utf-8", errors="replace")
            data = json.loads(payload)
            self.finished.emit({"ok": True, "result": data.get("xlist", [])})
        except Exception as e:
            self.finished.emit({"ok": False, "error": str(e)})


class LiveBroadcastDialog(QDialog):
    """현재 생중계 중인 방송 목록을 보여주고 선택하는 다이얼로그"""

    sig_fetch_request = pyqtSignal() # 워커에게 요청을 보내는 시그널

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("실시간 국회 생중계 목록")
        self.resize(700, 450)
        self.selected_broadcast = None
        
        # UI 구성
        layout = QVBoxLayout(self)
        
        # 헤더
        header_layout = QHBoxLayout()
        title_label = QLabel("📡 현재 진행 중인 생중계")
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
        
        # 목록 (TreeWidget)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["상태", "위원회/회의명", "시작 시간", "xcode"])
        self.tree.setColumnWidth(0, 80)
        self.tree.setColumnWidth(1, 400)
        self.tree.setColumnWidth(2, 100)
        self.tree.setColumnHidden(3, True) # xcode는 숨김
        self.tree.itemDoubleClicked.connect(self.accept_selection)
        layout.addWidget(self.tree)
        
        # 안내 메시지
        self.msg_label = QLabel("목록을 불러오는 중...")
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.msg_label)
        
        # 버튼 박스
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept_selection)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
        # 스타일링
        self.setStyleSheet("""
            QTreeWidget::item { padding: 5px; }
            QTreeWidget::item:selected { background-color: #3b82f6; color: white; }
        """)

        # --- 스레드 초기화 (Persistent) ---
        self._fetch_thread = QThread(self)
        self._fetch_worker = _LiveListFetchWorker()
        self._fetch_worker.moveToThread(self._fetch_thread)
        
        # 시그널 연결
        self.sig_fetch_request.connect(self._fetch_worker.fetch)
        self._fetch_worker.finished.connect(self._on_fetch_done)
        
        # 스레드 시작
        self._fetch_thread.start()
        
        # 초기 로딩
        QTimer.singleShot(100, self.load_broadcasts)
        
    def load_broadcasts(self):
        """API 호출 요청"""
        # 중복 요청 방지 (UI 상태로 제어)
        if not self.refresh_btn.isEnabled():
            return
            
        self.tree.clear()
        self.msg_label.setText("데이터 조회 중...")
        self.msg_label.show()
        self.refresh_btn.setEnabled(False)

        # 워커에게 작업 요청
        self.sig_fetch_request.emit()

    def _on_fetch_done(self, payload):
        """live_list fetch 완료 콜백 (UI 스레드)."""
        self.refresh_btn.setEnabled(True)

        if not isinstance(payload, dict) or not payload.get("ok"):
            err = payload.get("error", "알 수 없는 오류") if isinstance(payload, dict) else "알 수 없는 오류"
            self.msg_label.setText(f"조회 실패: {err}")
            return

        result = payload.get("result") or []
        if not result:
            self.msg_label.setText("현재 진행 중인 생중계가 없습니다.")
            return

        self.msg_label.hide()
        
        # 데이터 정렬 (생중계 중인 것 먼저)
        sorted_list = sorted(result, key=lambda x: str(x.get("xstat", "")) != "1")

        added = 0
        for item in sorted_list:
            xstat = str(item.get("xstat", "")).strip()
            xcgcd = str(item.get("xcgcd", "")).strip()
            
            # xcgcd가 없으면 목록에서 제외
            if not xcgcd:
                continue
                
            status_text = "🔴 생중계" if xstat == "1" else "종료/예정"
            
            # 시간 포맷팅
            time_str = str(item.get("time", ""))
            if len(time_str) >= 12:
                time_fmt = f"{time_str[8:10]}:{time_str[10:12]}"
            else:
                time_fmt = time_str
            
            name = item.get("xname", "알 수 없음")
            
            item_widget = QTreeWidgetItem([status_text, name, time_fmt, item.get("xcode", "")])
            item_widget.setData(0, Qt.ItemDataRole.UserRole, item)
            
            if xstat == "1":
                font = item_widget.font(0)
                font.setBold(True)
                item_widget.setFont(0, font)
                item_widget.setForeground(0, QColor("#ef4444")) # Red
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

    def done(self, r):
        """다이얼로그 종료 시 호출 (accept, reject 모두 포함)"""
        # 스레드 안전하게 종료
        if hasattr(self, '_fetch_thread') and self._fetch_thread.isRunning():
            self._fetch_thread.quit()
            self._fetch_thread.wait(1000)
            
        # 워커 제거
        if hasattr(self, '_fetch_worker'):
            self._fetch_worker.deleteLater()
            del self._fetch_worker
            
        # 스레드 제거 (deleteLater는 이벤트 루프 의존적이므로 주의 필요, 여기선 quit/wait로 충분)
        if hasattr(self, '_fetch_thread'):
            # self._fetch_thread.deleteLater() # 크래시 위험으로 제거 -> 부모(self) 소멸 시 자동 정리됨
            pass

        super().done(r)

    def closeEvent(self, event):
        """창 닫기 이벤트"""
        # done()이 호출되지 않는 경우를 대비 (보통 close -> reject -> done 순서임)
        # 하지만 명시적으로 여기서도 체크
        if hasattr(self, '_fetch_thread') and self._fetch_thread.isRunning():
            self._fetch_thread.quit()
            self._fetch_thread.wait(1000)
        super().closeEvent(event)
