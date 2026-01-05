# -*- coding: utf-8 -*-
"""
국회 의사중계 자막 추출기 v17.0 - 다중 세션 버전
- 다중 위원회 동시 모니터링
- 다중 브라우저 지원 (Selenium + Playwright)
"""

import sys
import os
import logging
from datetime import datetime
from pathlib import Path

# HiDPI 지원
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'

# 로깅 설정
def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / f"subtitle_{datetime.now().strftime('%Y%m%d')}.log"
    
    logger = logging.getLogger("SubtitleExtractor")
    logger.setLevel(logging.DEBUG)
    
    if logger.handlers:
        return logger
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(funcName)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('[%(levelname)s] %(message)s')
    console_handler.setFormatter(console_format)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QMessageBox, QFileDialog, QInputDialog,
        QMenuBar, QMenu, QDialog, QDialogButtonBox, QListWidget,
        QLineEdit, QTextEdit
    )
    from PyQt6.QtCore import Qt, QSettings, QTimer
    from PyQt6.QtGui import QFont, QAction, QShortcut, QKeySequence
except ImportError:
    print("PyQt6 필요: pip install PyQt6")
    sys.exit(1)

from session_tab_widget import MultiSessionTabWidget


# ============================================================
# 테마 정의
# ============================================================

DARK_THEME = """
/* === 글로벌 스타일 === */
QMainWindow, QWidget {
    background-color: #0d1117;
    color: #e6edf3;
    font-family: '맑은 고딕', 'Malgun Gothic', 'Segoe UI', sans-serif;
}

/* === 레이블 === */
QLabel { 
    color: #e6edf3; 
}
QLabel#headerLabel {
    font-size: 22px;
    font-weight: bold;
    color: #58a6ff;
    padding: 16px 20px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
        stop:0 rgba(88, 166, 255, 0.15), 
        stop:0.5 rgba(136, 146, 255, 0.1), 
        stop:1 rgba(163, 113, 247, 0.15));
    border-radius: 12px;
    border: 1px solid rgba(88, 166, 255, 0.2);
}
QLabel#statusBadge {
    padding: 6px 12px;
    border-radius: 16px;
    font-weight: bold;
    font-size: 12px;
}
QLabel#runningBadge {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(35, 134, 54, 0.3), stop:1 rgba(46, 160, 67, 0.3));
    border: 1px solid #2ea043;
    color: #3fb950;
    padding: 8px 16px;
    border-radius: 20px;
    font-weight: bold;
}

/* === 버튼 - 모던 스타일 === */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #21262d, stop:1 #161b22);
    color: #e6edf3;
    border: 1px solid #30363d;
    padding: 12px 24px;
    border-radius: 10px;
    font-weight: bold;
    font-size: 13px;
}
QPushButton:hover { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #30363d, stop:1 #21262d);
    border-color: #58a6ff;
    color: #ffffff;
}
QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #161b22, stop:1 #21262d);
    border-color: #388bfd;
}
QPushButton:disabled {
    background: #161b22;
    color: #484f58;
    border-color: #21262d;
}

/* 시작 버튼 - 그린 그라데이션 */
QPushButton#startBtn { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #238636, stop:1 #1a7f37);
    border: 1px solid #2ea043;
    color: #ffffff;
}
QPushButton#startBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2ea043, stop:1 #238636);
    border-color: #3fb950;
}
QPushButton#startBtn:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1a7f37, stop:1 #238636);
}
QPushButton#startBtn:disabled {
    background: #21262d;
    border-color: #30363d;
    color: #484f58;
}

/* 중지 버튼 - 레드 그라데이션 */
QPushButton#stopBtn { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #da3633, stop:1 #b62324);
    border: 1px solid #f85149;
    color: #ffffff;
}
QPushButton#stopBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f85149, stop:1 #da3633);
    border-color: #ff7b72;
}
QPushButton#stopBtn:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #b62324, stop:1 #da3633);
}
QPushButton#stopBtn:disabled {
    background: #21262d;
    border-color: #30363d;
    color: #484f58;
}

/* === 입력 필드 - 모던 스타일 === */
QLineEdit, QComboBox {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 12px 16px;
    color: #e6edf3;
    font-size: 13px;
    selection-background-color: #388bfd;
}
QLineEdit:hover, QComboBox:hover {
    border-color: #484f58;
}
QLineEdit:focus, QComboBox:focus {
    border: 2px solid #58a6ff;
    padding: 11px 15px;
    background-color: #0d1117;
}
QLineEdit::placeholder {
    color: #6e7681;
}
QComboBox::drop-down {
    border: none;
    padding-right: 10px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #8b949e;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: #21262d;
}

/* === 텍스트 에디터 - 자막 표시 영역 === */
QTextEdit {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 14px;
    padding: 18px;
    color: #e6edf3;
    font-size: 14px;
    line-height: 1.6;
}
QTextEdit:focus {
    border-color: #58a6ff;
}

/* === 그룹박스 - 카드 스타일 === */
QGroupBox {
    background-color: rgba(22, 27, 34, 0.8);
    border: 1px solid rgba(48, 54, 61, 0.8);
    border-radius: 14px;
    margin-top: 24px;
    padding: 22px 18px 18px 18px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 20px;
    padding: 2px 14px;
    color: #58a6ff;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0d1117, stop:1 rgba(13, 17, 23, 0.9));
    border-radius: 6px;
    font-size: 13px;
}

/* === 탭 위젯 - 모던 탭 === */
QTabWidget::pane {
    border: 1px solid #30363d;
    border-radius: 12px;
    background-color: #0d1117;
    top: -1px;
}
QTabBar::tab {
    background-color: #161b22;
    color: #8b949e;
    padding: 12px 24px;
    margin-right: 3px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    border: 1px solid transparent;
    border-bottom: none;
    font-weight: 500;
}
QTabBar::tab:selected {
    background-color: #0d1117;
    color: #58a6ff;
    border: 1px solid #30363d;
    border-bottom: 1px solid #0d1117;
}
QTabBar::tab:hover:!selected {
    background-color: #21262d;
    color: #e6edf3;
}
QTabBar::close-button {
    image: none;
    subcontrol-position: right;
    padding: 4px;
}
QTabBar::close-button:hover {
    background-color: rgba(248, 81, 73, 0.2);
    border-radius: 4px;
}

/* === 체크박스 - 모던 스타일 === */
QCheckBox { 
    spacing: 10px; 
    color: #e6edf3;
    font-size: 13px;
}
QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border-radius: 6px;
    border: 2px solid #30363d;
    background: #161b22;
}
QCheckBox::indicator:hover {
    border-color: #58a6ff;
    background: #21262d;
}
QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #58a6ff, stop:1 #8892ff);
    border-color: #58a6ff;
    image: none;
}
QCheckBox::indicator:checked:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #79b8ff, stop:1 #a5b4fc);
}

/* === 프로그레스바 - 글로우 효과 === */
QProgressBar {
    background-color: #21262d;
    border-radius: 8px;
    height: 10px;
    border: 1px solid #30363d;
}
QProgressBar::chunk { 
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
        stop:0 #58a6ff, 
        stop:0.4 #8892ff, 
        stop:0.6 #a371f7,
        stop:1 #58a6ff);
    border-radius: 7px; 
}

/* === 메뉴바 - 세련된 스타일 === */
QMenuBar { 
    background-color: #161b22; 
    color: #e6edf3;
    padding: 8px 12px;
    border-bottom: 1px solid #21262d;
}
QMenuBar::item { 
    padding: 10px 18px;
    border-radius: 8px;
    margin: 2px;
}
QMenuBar::item:selected { 
    background-color: #21262d;
    color: #58a6ff;
}

/* === 메뉴 - 드롭다운 === */
QMenu { 
    background-color: #161b22; 
    color: #e6edf3; 
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 8px;
}
QMenu::item { 
    padding: 12px 32px 12px 16px;
    border-radius: 8px;
    margin: 2px;
}
QMenu::item:selected { 
    background-color: #21262d;
    color: #58a6ff;
}
QMenu::separator {
    height: 1px;
    background-color: #30363d;
    margin: 6px 12px;
}

/* === 스크롤바 - 미니멀 스타일 === */
QScrollBar:vertical {
    background: transparent;
    width: 14px;
    border-radius: 7px;
    margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 5px;
    min-height: 40px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover { 
    background: #484f58; 
}
QScrollBar::handle:vertical:pressed { 
    background: #6e7681; 
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { 
    height: 0px; 
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

/* 수평 스크롤바 */
QScrollBar:horizontal {
    background: transparent;
    height: 14px;
    border-radius: 7px;
    margin: 2px 4px;
}
QScrollBar::handle:horizontal {
    background: #30363d;
    border-radius: 5px;
    min-width: 40px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover { 
    background: #484f58; 
}

/* === 툴팁 - 모던 스타일 === */
QToolTip {
    background-color: #161b22;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
}

/* === 스플리터 핸들 === */
QSplitter::handle {
    background-color: #30363d;
    width: 2px;
    margin: 4px 2px;
    border-radius: 1px;
}
QSplitter::handle:hover {
    background-color: #58a6ff;
}

/* === 다이얼로그 버튼 === */
QDialogButtonBox QPushButton {
    min-width: 80px;
}

/* === 리스트 위젯 === */
QListWidget {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 8px;
}
QListWidget::item {
    padding: 10px 12px;
    border-radius: 6px;
    margin: 2px;
}
QListWidget::item:selected {
    background-color: rgba(88, 166, 255, 0.15);
    color: #58a6ff;
}
QListWidget::item:hover:!selected {
    background-color: #21262d;
}

/* === 메시지 박스 === */
QMessageBox {
    background-color: #161b22;
}
QMessageBox QLabel {
    color: #e6edf3;
    font-size: 13px;
}
"""



# ============================================================
# 메인 윈도우
# ============================================================

class MultiSessionMainWindow(QMainWindow):
    """다중 세션 지원 메인 윈도우"""
    
    VERSION = "17.0"
    APP_NAME = "국회 의사중계 자막 추출기"
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{self.APP_NAME} v{self.VERSION} - 다중 세션")
        self.setMinimumSize(1200, 800)
        self.resize(1300, 900)
        
        # 설정
        self.settings = QSettings("AssemblySubtitle", "MultiSession")
        
        # UI 생성
        self._create_menu()
        self._create_ui()
        self.setStyleSheet(DARK_THEME)
        self._setup_shortcuts()
        
        # 창 위치/크기 복원
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        logger.info("다중 세션 메인 윈도우 초기화 완료")
        
        # 실행 중 세션 수 자동 업데이트 타이머
        self._running_count_timer = QTimer(self)
        self._running_count_timer.timeout.connect(self._update_running_count)
        self._running_count_timer.start(2000)  # 2초마다 업데이트
    
    def _create_menu(self):
        menubar = self.menuBar()
        
        # 파일 메뉴
        file_menu = menubar.addMenu("파일")
        
        save_all = QAction("📁 모든 세션 저장", self)
        save_all.setShortcut("Ctrl+Shift+S")
        save_all.triggered.connect(self._save_all_sessions)
        file_menu.addAction(save_all)
        
        file_menu.addSeparator()
        
        exit_action = QAction("종료", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 세션 메뉴
        session_menu = menubar.addMenu("세션")
        
        new_session = QAction("➕ 새 세션", self)
        new_session.setShortcut("Ctrl+N")
        new_session.triggered.connect(self._add_session)
        session_menu.addAction(new_session)
        
        rename_session = QAction("✏️ 탭 이름 변경", self)
        rename_session.triggered.connect(self._rename_session)
        session_menu.addAction(rename_session)
        
        session_menu.addSeparator()
        
        start_all = QAction("▶ 모든 세션 시작", self)
        start_all.triggered.connect(self._start_all)
        session_menu.addAction(start_all)
        
        stop_all = QAction("⏹ 모든 세션 중지", self)
        stop_all.triggered.connect(self._stop_all)
        session_menu.addAction(stop_all)
        
        # 검색 메뉴
        search_menu = menubar.addMenu("검색")
        
        search_all = QAction("🔍 전체 세션 검색", self)
        search_all.setShortcut("Ctrl+Shift+F")
        search_all.triggered.connect(self._search_all)
        search_menu.addAction(search_all)
        
        # 도움말 메뉴
        help_menu = menubar.addMenu("도움말")
        
        about_action = QAction("정보", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def _create_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # 헤더
        header_layout = QHBoxLayout()
        
        header = QLabel("🏛️ 국회 의사중계 자막 추출기 - 다중 세션")
        header.setObjectName("headerLabel")
        header.setFont(QFont("맑은 고딕", 16, QFont.Weight.Bold))
        header_layout.addWidget(header)
        
        header_layout.addStretch()
        
        # 실행 중 세션 수 표시
        self.running_label = QLabel("🟢 실행 중: 0")
        self.running_label.setStyleSheet("color: #58a6ff; font-weight: bold;")
        header_layout.addWidget(self.running_label)
        
        layout.addLayout(header_layout)
        
        # 다중 세션 탭 위젯
        self.tab_widget = MultiSessionTabWidget(self)
        layout.addWidget(self.tab_widget)
        
        # 상태바
        status_layout = QHBoxLayout()
        
        self.status_label = QLabel("ℹ️ 준비됨 - 세션 탭에서 URL을 입력하고 시작하세요")
        self.status_label.setStyleSheet("color: #8b949e;")
        status_layout.addWidget(self.status_label)
        
        status_layout.addStretch()
        
        # Playwright 상태 표시
        from browser_drivers import BrowserFactory
        if BrowserFactory.is_playwright_available():
            pw_label = QLabel("✅ Playwright")
            pw_label.setStyleSheet("color: #3fb950;")
        else:
            pw_label = QLabel("⚠️ Playwright 미설치")
            pw_label.setStyleSheet("color: #d29922;")
            pw_label.setToolTip("pip install playwright && playwright install")
        status_layout.addWidget(pw_label)
        
        layout.addLayout(status_layout)
    
    def _setup_shortcuts(self):
        QShortcut(QKeySequence("F5"), self, self._start_current)
        QShortcut(QKeySequence("Escape"), self, self._stop_current)
    
    def _add_session(self):
        self.tab_widget._add_new_session()
    
    def _rename_session(self):
        self.tab_widget.rename_current_tab()
    
    def _start_all(self):
        count = self.tab_widget.start_all_sessions()
        self.status_label.setText(f"▶ {count}개 세션 시작됨")
        self._update_running_count()
    
    def _stop_all(self):
        count = self.tab_widget.stop_all_sessions()
        self.status_label.setText(f"⏹ {count}개 세션 중지됨")
        self._update_running_count()
    
    def _start_current(self):
        """현재 탭 시작"""
        widget = self.tab_widget.currentWidget()
        if hasattr(widget, '_start'):
            widget._start()
            self._update_running_count()
    
    def _stop_current(self):
        """현재 탭 중지"""
        widget = self.tab_widget.currentWidget()
        if hasattr(widget, '_stop'):
            widget._stop()
            self._update_running_count()
    
    def _update_running_count(self):
        count = self.tab_widget.get_running_count()
        self.running_label.setText(f"🟢 실행 중: {count}")
    
    def _save_all_sessions(self):
        """모든 세션 저장"""
        folder = QFileDialog.getExistingDirectory(self, "저장 폴더 선택")
        if not folder:
            return
        
        saved = 0
        for session_id, widget in self.tab_widget.tab_widgets.items():
            if widget.session.subtitles:
                filename = f"{folder}/{widget.session.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                try:
                    with open(filename, 'w', encoding='utf-8') as f:
                        for entry in widget.session.subtitles:
                            f.write(f"[{entry.timestamp.strftime('%H:%M:%S')}] {entry.text}\n")
                    saved += 1
                except Exception as e:
                    logger.error(f"저장 오류: {e}")
        
        QMessageBox.information(self, "저장 완료", f"{saved}개 세션이 저장되었습니다.")
    
    def _search_all(self):
        """전체 세션 검색"""
        query, ok = QInputDialog.getText(self, "전체 검색", "검색어:")
        if not ok or not query.strip():
            return
        
        results = self.tab_widget.search_all(query.strip())
        
        if not results:
            QMessageBox.information(self, "검색 결과", "검색 결과가 없습니다.")
            return
        
        # 결과 다이얼로그
        dialog = QDialog(self)
        dialog.setWindowTitle(f"검색 결과: '{query}' ({len(results)}개)")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        list_widget = QListWidget()
        for session_name, idx, entry in results:
            timestamp = entry.timestamp.strftime('%H:%M:%S')
            preview = entry.text[:80] + "..." if len(entry.text) > 80 else entry.text
            list_widget.addItem(f"[{session_name}] [{timestamp}] {preview}")
        
        layout.addWidget(list_widget)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        
        dialog.exec()
    
    def _show_about(self):
        about = f"""
<h2>🏛️ 국회 의사중계 자막 추출기</h2>
<p><b>버전:</b> {self.VERSION} (다중 세션)</p>
<p><b>새 기능:</b></p>
<ul>
<li>📑 다중 위원회 동시 모니터링</li>
<li>🌐 다중 브라우저 지원 (Selenium + Playwright)</li>
<li>🔍 전체 세션 통합 검색</li>
</ul>
<p><b>지원 브라우저:</b></p>
<ul>
<li>Chrome, Firefox, Edge (Selenium)</li>
<li>Chromium, Firefox, WebKit (Playwright)</li>
</ul>
"""
        msg = QMessageBox(self)
        msg.setWindowTitle("정보")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(about)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()
    
    def closeEvent(self, event):
        # 실행 중인 세션 확인
        running = self.tab_widget.get_running_count()
        if running > 0:
            reply = QMessageBox.question(
                self, "종료 확인",
                f"{running}개 세션이 실행 중입니다. 종료하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        
        # 모든 세션 중지
        self.tab_widget.stop_all_sessions()
        
        # 타이머 정리
        if hasattr(self, '_running_count_timer'):
            self._running_count_timer.stop()
        
        # 설정 저장
        self.settings.setValue("geometry", self.saveGeometry())
        
        logger.info("프로그램 종료")
        event.accept()


def main():
    """메인 함수"""
    try:
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        app.setStyle("Fusion")
        app.setFont(QFont("맑은 고딕", 10))
        
        window = MultiSessionMainWindow()
        window.show()
        
        sys.exit(app.exec())
    
    except Exception as e:
        logger.exception(f"프로그램 오류: {e}")
        QMessageBox.critical(None, "오류", f"프로그램 실행 중 오류 발생:\n{e}")


if __name__ == '__main__':
    main()
