# -*- coding: utf-8 -*-
"""
세션 탭 위젯 모듈
다중 위원회 동시 모니터링을 위한 탭 기반 UI
"""

import queue
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QTextEdit, QComboBox, QCheckBox, QGroupBox, 
    QGridLayout, QProgressBar, QSplitter, QFrame,
    QTabWidget, QMenu, QInputDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor, QTextCursor, QTextCharFormat

from browser_drivers import BrowserFactory, BrowserType
from subtitle_session import SubtitleSession, SubtitleEntry, SessionManager


class SessionTabWidget(QWidget):
    """단일 세션 탭 위젯 - 하나의 자막 추출 세션 UI"""
    
    def __init__(self, session: SubtitleSession, parent=None):
        super().__init__(parent)
        self.session = session
        
        # UI 상태
        self.keywords = []
        self.alert_keywords = []
        
        # 렌더링 캐시 (증분 렌더링용)
        self._last_rendered_count = 0
        self._cached_char_count = 0
        
        self._create_ui()
        self._setup_timers()
    
    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # === 설정 영역 ===
        settings_group = QGroupBox("⚙️ 설정")
        settings_layout = QGridLayout(settings_group)
        settings_layout.setSpacing(8)
        
        # URL
        url_label = QLabel("📌 URL:")
        settings_layout.addWidget(url_label, 0, 0)
        
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("국회 의사중계 URL 입력...")
        self.url_input.setText(self.session.url)
        url_layout.addWidget(self.url_input, 1)
        
        # 상임위 프리셋 버튼
        self.preset_btn = QPushButton("📋 상임위")
        self.preset_btn.setFixedWidth(100)
        self._setup_preset_menu()
        url_layout.addWidget(self.preset_btn)
        
        settings_layout.addLayout(url_layout, 0, 1)
        
        # 선택자
        selector_label = QLabel("🔍 선택자:")
        settings_layout.addWidget(selector_label, 1, 0)
        
        self.selector_combo = QComboBox()
        self.selector_combo.setEditable(True)
        self.selector_combo.addItems(["#viewSubtit .incont", "#viewSubtit", ".subtitle_area"])
        self.selector_combo.setCurrentText(self.session.selector)
        settings_layout.addWidget(self.selector_combo, 1, 1)
        
        # 브라우저 선택
        browser_label = QLabel("🌐 브라우저:")
        settings_layout.addWidget(browser_label, 2, 0)
        
        browser_layout = QHBoxLayout()
        self.browser_combo = QComboBox()
        self._populate_browser_combo()
        browser_layout.addWidget(self.browser_combo, 1)
        
        # 옵션
        self.headless_check = QCheckBox("🔇 헤드리스")
        self.headless_check.setChecked(self.session.headless)
        self.headless_check.setToolTip("브라우저 창 숨기고 백그라운드 실행")
        browser_layout.addWidget(self.headless_check)
        
        self.auto_scroll_check = QCheckBox("📜 자동 스크롤")
        self.auto_scroll_check.setChecked(True)
        browser_layout.addWidget(self.auto_scroll_check)
        
        self.realtime_save_check = QCheckBox("💾 실시간 저장")
        self.realtime_save_check.setChecked(False)
        browser_layout.addWidget(self.realtime_save_check)
        
        settings_layout.addLayout(browser_layout, 2, 1)
        
        layout.addWidget(settings_group)
        
        # === 컨트롤 버튼 ===
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        self.start_btn = QPushButton("▶️  시작")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setMinimumWidth(120)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._start)
        
        self.stop_btn = QPushButton("⏹️  중지")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setMinimumWidth(120)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.clicked.connect(self._stop)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addStretch()
        
        # 상태 레이블 - 배지 스타일
        self.status_label = QLabel("⚪ 대기 중")
        self.status_label.setStyleSheet("""
            padding: 8px 16px;
            border-radius: 16px;
            background-color: rgba(139, 148, 158, 0.1);
            border: 1px solid rgba(139, 148, 158, 0.3);
            font-weight: bold;
        """)
        btn_layout.addWidget(self.status_label)
        
        layout.addLayout(btn_layout)
        
        # === 진행 표시 ===
        self.progress = QProgressBar()
        self.progress.setMaximum(0)
        self.progress.hide()
        layout.addWidget(self.progress)
        
        # === 메인 콘텐츠 (자막 + 통계) ===
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 자막 텍스트 컨테이너
        subtitle_container = QWidget()
        subtitle_layout = QVBoxLayout(subtitle_container)
        subtitle_layout.setContentsMargins(0, 0, 0, 0)
        subtitle_layout.setSpacing(0)
        
        self.subtitle_text = QTextEdit()
        self.subtitle_text.setReadOnly(True)
        self.subtitle_text.setFont(QFont("맑은 고딕", 13))
        self.subtitle_text.setPlaceholderText("🎬 자막 추출을 시작하면 여기에 표시됩니다.\n\n💡 사용 방법:\n1. URL을 입력하거나 '상임위' 버튼으로 선택하세요\n2. '시작' 버튼을 클릭하세요\n3. AI 자막이 자동으로 추출됩니다")
        subtitle_layout.addWidget(self.subtitle_text)
        
        splitter.addWidget(subtitle_container)
        
        # 통계 패널 - 모던 카드 스타일
        stats_group = QGroupBox("📊 통계")
        stats_layout = QVBoxLayout(stats_group)
        stats_layout.setSpacing(10)
        
        # 통계 항목들 - 개선된 스타일
        stat_style = """
            padding: 10px 12px;
            border-radius: 8px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 rgba(88, 166, 255, 0.08), 
                stop:1 rgba(136, 146, 255, 0.05));
            border: 1px solid rgba(88, 166, 255, 0.15);
            font-size: 12px;
        """
        
        self.stat_time = QLabel("⏱️ 실행 시간\n00:00:00")
        self.stat_chars = QLabel("📝 글자 수\n0")
        self.stat_words = QLabel("📖 단어 수\n0")
        self.stat_sents = QLabel("💬 문장 수\n0")
        self.stat_cpm = QLabel("⚡ 분당 글자\n0")
        
        for label in [self.stat_time, self.stat_chars, self.stat_words, self.stat_sents, self.stat_cpm]:
            label.setStyleSheet(stat_style)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stats_layout.addWidget(label)
        
        stats_layout.addStretch()
        stats_group.setFixedWidth(160)
        splitter.addWidget(stats_group)
        
        splitter.setSizes([750, 160])
        layout.addWidget(splitter)
        
        # === 하단 상태바 ===
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(4, 8, 4, 0)
        
        self.count_label = QLabel("📝 0문장 | 0자")
        self.count_label.setStyleSheet("color: #8b949e; font-size: 12px;")
        footer_layout.addWidget(self.count_label)
        
        footer_layout.addStretch()
        
        # 시간 표시
        self.time_label = QLabel()
        self.time_label.setStyleSheet("color: #6e7681; font-size: 11px;")
        self._update_time_label()
        footer_layout.addWidget(self.time_label)
        
        layout.addLayout(footer_layout)
    
    def _populate_browser_combo(self):
        """브라우저 콤보박스 채우기"""
        available = BrowserFactory.get_available_browsers()
        for browser_type in available:
            name = BrowserFactory.get_browser_name(browser_type)
            self.browser_combo.addItem(name, browser_type)
    
    def _setup_preset_menu(self):
        """상임위 프리셋 메뉴 설정"""
        menu = QMenu(self)
        
        presets = {
            "본회의": "https://assembly.webcast.go.kr/main/player.asp",
            "법제사법위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=25",
            "기획재정위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=38",
            "외교통일위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=48",
            "국방위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=37",
            "행정안전위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=45",
            "교육위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=58",
            "보건복지위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=33",
            "예산결산특별위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=21",
        }
        
        for name, url in presets.items():
            action = menu.addAction(name)
            action.triggered.connect(lambda checked, u=url: self.url_input.setText(u))
        
        self.preset_btn.setMenu(menu)
    
    def _setup_timers(self):
        """타이머 설정"""
        # 메시지 큐 처리 타이머
        self.queue_timer = QTimer(self)
        self.queue_timer.timeout.connect(self._process_message_queue)
        self.queue_timer.start(100)
        
        # 통계 업데이트 타이머
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self._update_stats)
    
    def _start(self):
        """추출 시작"""
        # 세션 설정 업데이트
        self.session.url = self.url_input.text().strip()
        self.session.selector = self.selector_combo.currentText().strip()
        self.session.browser_type = self.browser_combo.currentData()
        self.session.headless = self.headless_check.isChecked()
        self.session.auto_scroll = self.auto_scroll_check.isChecked()
        self.session.realtime_save = self.realtime_save_check.isChecked()
        
        if not self.session.url:
            QMessageBox.warning(self, "오류", "URL을 입력하세요.")
            return
        
        # 세션 시작
        if self.session.start():
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.url_input.setEnabled(False)
            self.browser_combo.setEnabled(False)
            self.progress.show()
            self.stats_timer.start(1000)
            self._set_status("시작 중...", "running")
    
    def _stop(self):
        """추출 중지"""
        self.session.stop()
        self._reset_ui()
        self._set_status("중지됨", "warning")
    
    def _reset_ui(self):
        """UI 초기화"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.url_input.setEnabled(True)
        self.browser_combo.setEnabled(True)
        self.progress.hide()
        self.stats_timer.stop()
    
    def _set_status(self, text: str, status_type: str = "info"):
        """상태 표시"""
        icons = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌", "running": "🔄"}
        colors = {"info": "#4fc3f7", "success": "#4caf50", "warning": "#ff9800", "error": "#f44336", "running": "#ab47bc"}
        
        icon = icons.get(status_type, "")
        color = colors.get(status_type, "#eaeaea")
        self.status_label.setText(f"{icon} {text}"[:100])
        self.status_label.setStyleSheet(f"color: {color};")
    
    def _process_message_queue(self):
        """메시지 큐 처리"""
        for _ in range(10):
            try:
                msg_type, data = self.session.message_queue.get_nowait()
                self._handle_message(msg_type, data)
            except queue.Empty:
                break
    
    def _handle_message(self, msg_type, data):
        """개별 메시지 처리"""
        if msg_type == "status":
            self._set_status(str(data), "running")
        
        elif msg_type == "preview":
            self._render_subtitles(current_raw=data)
        
        elif msg_type == "finalized":
            self._render_subtitles()
            self._update_count_label()
        
        elif msg_type == "error":
            self.progress.hide()
            self._reset_ui()
            self._set_status(f"오류: {data}", "error")
            QMessageBox.critical(self, "오류", str(data))
        
        elif msg_type == "finished":
            self._render_subtitles()
            self._reset_ui()
            total_chars = sum(len(s.text) for s in self.session.subtitles)
            self._set_status(f"완료 - {len(self.session.subtitles)}문장, {total_chars:,}자", "success")
    
    def _render_subtitles(self, current_raw: str = None):
        """자막 렌더링 - 증분 렌더링으로 최적화"""
        cursor = self.subtitle_text.textCursor()
        
        # 새로 추가된 자막만 렌더링 (성능 최적화)
        current_count = len(self.session.subtitles)
        new_entries = self.session.subtitles[self._last_rendered_count:]
        
        if new_entries:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            
            for i, entry in enumerate(new_entries):
                if self._last_rendered_count + i > 0:
                    cursor.insertText("\n\n")
                
                # 타임스탬프
                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#888888"))
                cursor.insertText(f"[{entry.timestamp.strftime('%H:%M:%S')}] ", fmt)
                
                # 텍스트
                fmt = QTextCharFormat()
                cursor.insertText(entry.text, fmt)
                
                # 캐시된 글자 수 업데이트
                self._cached_char_count += len(entry.text)
            
            self._last_rendered_count = current_count
        
        # 프리뷰 자막은 상태바에만 표시 (깜빡임 방지)
        # current_raw는 status로 처리됨
        
        if self.auto_scroll_check.isChecked():
            self.subtitle_text.moveCursor(QTextCursor.MoveOperation.End)
    
    def _update_stats(self):
        """통계 업데이트"""
        stats = self.session.get_stats()
        
        h, r = divmod(stats['elapsed'], 3600)
        m, s = divmod(r, 60)
        
        # 새로운 카드 스타일에 맞게 포맷 변경
        self.stat_time.setText(f"⏱️ 실행 시간\n{h:02d}:{m:02d}:{s:02d}")
        self.stat_chars.setText(f"📝 글자 수\n{stats['char_count']:,}")
        self.stat_words.setText(f"📖 단어 수\n{stats['word_count']:,}")
        self.stat_sents.setText(f"💬 문장 수\n{stats['subtitle_count']}")
        self.stat_cpm.setText(f"⚡ 분당 글자\n{stats['cpm']}")
        
        # 하단 시간 레이블도 업데이트
        self._update_time_label()
    
    def _update_count_label(self):
        """카운트 레이블 업데이트 - 캐시 활용으로 최적화"""
        count = len(self.session.subtitles)
        # 캐시된 글자 수 사용 (반복 계산 제거)
        self.count_label.setText(f"📝 {count}문장 | {self._cached_char_count:,}자")
    
    def get_subtitles_text(self) -> str:
        """자막 텍스트 반환"""
        return "\n".join(s.text for s in self.session.subtitles)
    
    def cleanup(self):
        """타이머 정리 - 탭 닫힐 시 호출 필요"""
        if hasattr(self, 'queue_timer') and self.queue_timer:
            self.queue_timer.stop()
        if hasattr(self, 'stats_timer') and self.stats_timer:
            self.stats_timer.stop()
    
    def _update_time_label(self):
        """하단 시간 레이블 업데이트"""
        from datetime import datetime
        now = datetime.now()
        self.time_label.setText(now.strftime("📅 %Y-%m-%d %H:%M"))


class MultiSessionTabWidget(QTabWidget):
    """다중 세션 탭 위젯"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.session_manager = SessionManager()
        self.tab_widgets: dict = {}  # session_id -> SessionTabWidget
        
        # 탭 설정
        self.setTabsClosable(True)
        self.setMovable(True)
        self.tabCloseRequested.connect(self._close_tab)
        
        # 탭 추가 버튼
        self.setCornerWidget(self._create_add_button(), Qt.Corner.TopRightCorner)
        
        # 첫 번째 세션 추가
        self._add_new_session()
    
    def _create_add_button(self) -> QPushButton:
        """탭 추가 버튼 생성"""
        btn = QPushButton("➕ 새 세션")
        btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(88, 166, 255, 0.1);
                border: 1px solid rgba(88, 166, 255, 0.3);
                border-radius: 6px;
                padding: 6px 12px;
                color: #58a6ff;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(88, 166, 255, 0.2);
            }
        """)
        btn.clicked.connect(self._add_new_session)
        return btn
    
    def _add_new_session(self):
        """새 세션 탭 추가"""
        try:
            session = self.session_manager.create_session()
            tab_widget = SessionTabWidget(session, self)
            
            self.tab_widgets[session.session_id] = tab_widget
            
            index = self.addTab(tab_widget, f"🏛️ {session.name}")
            self.setCurrentIndex(index)
            
        except RuntimeError as e:
            QMessageBox.warning(self, "세션 제한", str(e))
    
    def _close_tab(self, index: int):
        """탭 닫기"""
        if self.count() <= 1:
            QMessageBox.warning(self, "알림", "최소 하나의 세션은 유지해야 합니다.")
            return
        
        widget = self.widget(index)
        if isinstance(widget, SessionTabWidget):
            session_id = widget.session.session_id
            
            # 실행 중이면 확인
            if widget.session.is_running:
                reply = QMessageBox.question(
                    self, "확인",
                    "이 세션은 현재 실행 중입니다. 중지하고 닫으시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            
            # 세션 제거
            widget.cleanup()  # 타이머 정리 (리소스 누수 방지)
            self.session_manager.remove_session(session_id)
            del self.tab_widgets[session_id]
        
        self.removeTab(index)
    
    def rename_current_tab(self):
        """현재 탭 이름 변경"""
        index = self.currentIndex()
        widget = self.widget(index)
        
        if isinstance(widget, SessionTabWidget):
            name, ok = QInputDialog.getText(
                self, "탭 이름 변경",
                "새 이름:",
                text=widget.session.name
            )
            if ok and name.strip():
                widget.session.name = name.strip()
                self.setTabText(index, f"🏛️ {name.strip()}")
    
    def start_all_sessions(self):
        """모든 세션 시작"""
        count = 0
        for widget in self.tab_widgets.values():
            if not widget.session.is_running:
                widget._start()
                count += 1
        return count
    
    def stop_all_sessions(self):
        """모든 세션 중지"""
        count = 0
        for widget in self.tab_widgets.values():
            if widget.session.is_running:
                widget._stop()
                count += 1
        return count
    
    def get_running_count(self) -> int:
        """실행 중인 세션 수"""
        return self.session_manager.get_running_count()
    
    def search_all(self, query: str):
        """모든 세션에서 검색"""
        return self.session_manager.search_all(query)
