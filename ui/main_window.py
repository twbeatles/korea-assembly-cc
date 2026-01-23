# -*- coding: utf-8 -*-

import os
import time
import threading
import queue
import re
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox, QCheckBox,
    QFrame, QProgressBar, QMessageBox, QFileDialog,
    QGroupBox, QGridLayout, QDialog, QDialogButtonBox, QListWidget,
    QSplitter, QMenu, QMenuBar, QInputDialog, QSystemTrayIcon, QAbstractItemView,
    QTreeWidget, QTreeWidgetItem, QToolBar, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QSettings
from PyQt6.QtGui import (
    QFont, QColor, QTextCursor, QTextCharFormat, QAction,
    QShortcut, QKeySequence, QIcon
)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.chrome.options import Options

from core.config import Config
from core.logging_utils import logger
from core.models import SubtitleEntry
from ui.dialogs import LiveBroadcastDialog
from ui.themes import DARK_THEME, LIGHT_THEME
from ui.widgets import CollapsibleGroupBox, ToastWidget

try:
    from database import DatabaseManager
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    logger.warning("database.py 모듈을 찾을 수 없습니다. 데이터베이스 기능은 비활성화됩니다.")


class MainWindow(QMainWindow):
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{Config.APP_NAME} v{Config.VERSION}")
        self.setMinimumSize(1100, 750)
        self.resize(1200, 800)
        
        # 설정
        self.settings = QSettings("AssemblySubtitle", "Extractor")
        self.is_dark_theme = self.settings.value("dark_theme", True, type=bool)
        self.font_size = self.settings.value("font_size", Config.DEFAULT_FONT_SIZE, type=int)
        self.minimize_to_tray = self.settings.value("minimize_to_tray", False, type=bool)
        
        # 메시지 큐
        self.message_queue = queue.Queue()
        
        # 상태
        self.worker = None
        self.driver = None
        self.is_running = False
        self.stop_event = threading.Event()  # 스레드 안전한 종료 시그널
        self.subtitle_lock = threading.Lock()  # 자막 리스트 접근 동기화
        self._auto_backup_lock = threading.Lock()  # 자동 백업 중복 실행 방지
        self.start_time = None
        self.last_subtitle = ""
        
        # 자막 데이터 (타임스탬프 포함)
        self.subtitles = []  # List[SubtitleEntry]
        # 저장된 키워드 로드
        saved_keywords = self.settings.value("highlight_keywords", "")
        self.keywords = [k.strip() for k in saved_keywords.split(",") if k.strip()] if saved_keywords else []
        saved_alert = self.settings.value("alert_keywords", "")
        self.alert_keywords = [k.strip() for k in saved_alert.split(",") if k.strip()] if saved_alert else []
        self.last_update_time = 0  # 마지막 자막 업데이트 시간
        
        # 성능 최적화: QTextCharFormat 캐싱
        self._highlight_fmt = QTextCharFormat()
        self._highlight_fmt.setBackground(QColor("#ffd700"))  # 골드 배경
        self._highlight_fmt.setForeground(QColor("#000000"))  # 검정 글자
        self._highlight_fmt.setFontWeight(QFont.Weight.Bold)
        self._normal_fmt = QTextCharFormat()
        self._timestamp_fmt = QTextCharFormat()
        self._timestamp_fmt.setForeground(QColor("#888888"))
        self._preview_fmt = QTextCharFormat()
        self._preview_fmt.setForeground(QColor("#aaaaaa"))
        
        # 성능 최적화: 키워드 패턴 캐싱
        self._keyword_pattern = None  # 컴파일된 정규식 패턴
        self._keywords_lower_set = set()  # 빠른 검색용 set
        self._update_keyword_cache()
        
        # 성능 최적화: 통계 캐싱
        self._cached_total_chars = 0
        self._cached_total_words = 0
        
        # 토스트 스택 관리
        self.active_toasts = []  # 현재 표시 중인 토스트 목록
        
        # 실시간 저장
        self.realtime_file = None
        
        # 연결 상태 모니터링 (#30)
        self.connection_status = "disconnected"  # connected, disconnected, reconnecting
        self.last_ping_time = 0
        self.ping_latency = 0  # ms
        
        # 자동 재연결 (#31)
        self.reconnect_attempts = 0
        self.auto_reconnect_enabled = self.settings.value("auto_reconnect", True, type=bool)
        self.current_url = ""  # 현재 연결 중인 URL 저장
        
        # 스마트 스크롤 상태 (사용자가 위로 스크롤하면 자동 스크롤 일시 중지)
        self._user_scrolled_up = False
        self._is_stopping = False
        self._pending_minute_bucket = None
        
        # URL 히스토리
        self.url_history = self._load_url_history()
        
        # UI 생성
        self._create_menu()
        self._create_ui()
        self._apply_theme()
        self._setup_shortcuts()
        
        # 타이머
        self.queue_timer = QTimer(self)
        self.queue_timer.timeout.connect(self._process_message_queue)
        self.queue_timer.start(Config.QUEUE_PROCESS_INTERVAL)
        
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self._update_stats)
        
        # 자막 확정 타이머
        self.finalize_timer = QTimer(self)
        self.finalize_timer.timeout.connect(self._check_finalize)
        
        # 자동 백업 타이머
        self.backup_timer = QTimer(self)
        self.backup_timer.timeout.connect(self._auto_backup)
        
        # 디렉토리 생성
        Path(Config.SESSION_DIR).mkdir(exist_ok=True)
        Path(Config.REALTIME_DIR).mkdir(exist_ok=True)
        Path(Config.BACKUP_DIR).mkdir(exist_ok=True)
        
        # 데이터베이스 매니저 초기화 (#26)
        self.db = None
        if DB_AVAILABLE:
            try:
                self.db = DatabaseManager(Config.DATABASE_PATH)
            except Exception as e:
                logger.error(f"데이터베이스 초기화 실패: {e}")
        
        # 창 위치/크기 복원
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)
        
        # 시스템 트레이 설정
        self._setup_tray()

    def _rebuild_stats_cache(self) -> None:
        """현재 자막 리스트 기반으로 통계 캐시를 재계산.

        - 세션 로드/병합/삭제/편집 등으로 자막 리스트가 바뀌는 경우 호출한다.
        - 캐시는 UI 통계/카운트 라벨에서 재계산 비용을 줄이기 위해 사용된다.
        """
        with self.subtitle_lock:
            self._cached_total_chars = sum(s.char_count for s in self.subtitles)
            self._cached_total_words = sum(s.word_count for s in self.subtitles)
    
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
            self.tray_icon.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
        
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
        if hasattr(self, 'tray_status_action'):
            self.tray_status_action.setText(status)
    
    def _create_menu(self):
        menubar = self.menuBar()
        
        # 파일 메뉴
        file_menu = menubar.addMenu("파일")
        
        save_txt = QAction("TXT 저장", self)
        save_txt.setShortcut("Ctrl+S")
        save_txt.triggered.connect(self._save_txt)
        file_menu.addAction(save_txt)
        
        save_srt = QAction("SRT 저장", self)
        save_srt.triggered.connect(self._save_srt)
        file_menu.addAction(save_srt)
        
        save_vtt = QAction("VTT 저장", self)
        save_vtt.triggered.connect(self._save_vtt)
        file_menu.addAction(save_vtt)
        
        save_docx = QAction("DOCX 저장 (Word)", self)
        save_docx.triggered.connect(self._save_docx)
        file_menu.addAction(save_docx)
        
        save_hwp = QAction("HWP 저장 (한글)", self)
        save_hwp.triggered.connect(self._save_hwp)
        file_menu.addAction(save_hwp)
        
        save_rtf = QAction("RTF 저장", self)
        save_rtf.triggered.connect(self._save_rtf)
        file_menu.addAction(save_rtf)
        
        file_menu.addSeparator()
        
        save_session = QAction("세션 저장", self)
        save_session.setShortcut("Ctrl+Shift+S")
        save_session.triggered.connect(self._save_session)
        file_menu.addAction(save_session)
        
        load_session = QAction("세션 불러오기", self)
        load_session.setShortcut("Ctrl+O")
        load_session.triggered.connect(self._load_session)
        file_menu.addAction(load_session)
        
        file_menu.addSeparator()
        
        export_stats = QAction("📊 통계 내보내기", self)
        export_stats.triggered.connect(self._export_stats)
        file_menu.addAction(export_stats)
        
        file_menu.addSeparator()
        
        exit_action = QAction("종료", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 편집 메뉴
        edit_menu = menubar.addMenu("편집")
        
        search_action = QAction("검색", self)
        search_action.setShortcut("Ctrl+F")
        search_action.triggered.connect(self._show_search)
        edit_menu.addAction(search_action)
        
        keyword_action = QAction("하이라이트 키워드 설정", self)
        keyword_action.triggered.connect(self._set_keywords)
        edit_menu.addAction(keyword_action)
        
        alert_keyword_action = QAction("알림 키워드 설정", self)
        alert_keyword_action.setToolTip("특정 키워드 감지 시 알림을 표시합니다")
        alert_keyword_action.triggered.connect(self._set_alert_keywords)
        edit_menu.addAction(alert_keyword_action)
        
        edit_menu.addSeparator()
        
        edit_subtitle_action = QAction("✏️ 자막 편집", self)
        edit_subtitle_action.setShortcut("Ctrl+E")
        edit_subtitle_action.setToolTip("선택한 자막을 편집합니다")
        edit_subtitle_action.triggered.connect(self._edit_subtitle)
        edit_menu.addAction(edit_subtitle_action)
        
        delete_subtitle_action = QAction("🗑️ 자막 삭제", self)
        delete_subtitle_action.setShortcut("Delete")
        delete_subtitle_action.setToolTip("선택한 자막을 삭제합니다")
        delete_subtitle_action.triggered.connect(self._delete_subtitle)
        edit_menu.addAction(delete_subtitle_action)
        
        edit_menu.addSeparator()
        
        copy_action = QAction("클립보드 복사", self)
        copy_action.setShortcut("Ctrl+C")
        copy_action.setToolTip("전체 자막을 클립보드에 복사합니다")
        copy_action.triggered.connect(self._copy_to_clipboard)
        edit_menu.addAction(copy_action)
        
        clear_action = QAction("내용 지우기", self)
        clear_action.setToolTip("모든 자막 내용을 삭제합니다")
        clear_action.triggered.connect(self._clear_text)
        edit_menu.addAction(clear_action)
        
        # 보기 메뉴
        view_menu = menubar.addMenu("보기")
        
        self.theme_action = QAction("라이트 테마" if self.is_dark_theme else "다크 테마", self)
        self.theme_action.setShortcut("Ctrl+T")
        self.theme_action.triggered.connect(self._toggle_theme)
        view_menu.addAction(self.theme_action)
        
        self.timestamp_action = QAction("타임스탬프 표시", self)
        self.timestamp_action.setCheckable(True)
        self.timestamp_action.setChecked(True)
        self.timestamp_action.triggered.connect(self._refresh_text)
        view_menu.addAction(self.timestamp_action)
        
        self.tray_action = QAction("🔽 트레이로 최소화", self)
        self.tray_action.setCheckable(True)
        self.tray_action.setChecked(self.minimize_to_tray)
        self.tray_action.setToolTip("활성화 시 창을 닫으면 트레이로 최소화됩니다")
        self.tray_action.triggered.connect(self._toggle_tray_option)
        view_menu.addAction(self.tray_action)
        
        view_menu.addSeparator()
        
        # 글자 크기 서브메뉴
        font_menu = view_menu.addMenu("📝 글자 크기")
        for size in [12, 14, 16, 18, 20, 22, 24]:
            font_action = QAction(f"{size}pt", self)
            font_action.triggered.connect(lambda checked, s=size: self._set_font_size(s))
            font_menu.addAction(font_action)
        
        view_menu.addSeparator()
        
        font_increase = QAction("글자 크기 키우기", self)
        font_increase.setShortcut("Ctrl++")
        font_increase.triggered.connect(lambda: self._adjust_font_size(2))
        view_menu.addAction(font_increase)
        
        font_decrease = QAction("글자 크기 줄이기", self)
        font_decrease.setShortcut("Ctrl+-")
        font_decrease.triggered.connect(lambda: self._adjust_font_size(-2))
        view_menu.addAction(font_decrease)
        
        # 도구 메뉴 (#20)
        tools_menu = menubar.addMenu("도구")
        
        merge_action = QAction("📎 자막 병합...", self)
        merge_action.setShortcut("Ctrl+Shift+M")
        merge_action.setToolTip("여러 세션 파일을 하나로 병합합니다")
        merge_action.triggered.connect(self._show_merge_dialog)
        tools_menu.addAction(merge_action)
        
        # 데이터베이스 메뉴 (#26)
        db_menu = menubar.addMenu("데이터베이스")
        
        db_history_action = QAction("📋 세션 히스토리", self)
        db_history_action.setToolTip("저장된 모든 세션 목록을 확인합니다")
        db_history_action.triggered.connect(self._show_db_history)
        db_menu.addAction(db_history_action)
        
        db_search_action = QAction("🔍 자막 검색", self)
        db_search_action.setToolTip("모든 세션에서 키워드를 검색합니다")
        db_search_action.triggered.connect(self._show_db_search)
        db_menu.addAction(db_search_action)
        
        db_menu.addSeparator()
        
        db_stats_action = QAction("📊 전체 통계", self)
        db_stats_action.setToolTip("데이터베이스 전체 통계를 확인합니다")
        db_stats_action.triggered.connect(self._show_db_stats)
        db_menu.addAction(db_stats_action)
        
        # 도움말 메뉴
        help_menu = menubar.addMenu("도움말")
        
        guide_action = QAction("사용법 가이드", self)
        guide_action.setShortcut("F1")
        guide_action.setToolTip("프로그램 사용법 안내")
        guide_action.triggered.connect(self._show_guide)
        help_menu.addAction(guide_action)
        
        features_action = QAction("기능 소개", self)
        features_action.setToolTip("프로그램의 주요 기능 소개")
        features_action.triggered.connect(self._show_features)
        help_menu.addAction(features_action)
        
        shortcuts_action = QAction("⌨️ 키보드 단축키", self)
        shortcuts_action.setToolTip("사용 가능한 키보드 단축키 목록")
        shortcuts_action.triggered.connect(self._show_shortcuts)
        help_menu.addAction(shortcuts_action)
        
        help_menu.addSeparator()
        
        about_action = QAction("정보", self)
        about_action.setToolTip("프로그램 정보 및 버전")
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def _create_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # === 헤더 ===
        header = QLabel("🏛️ 국회 의사중계 자막 추출기")
        header.setObjectName("headerLabel")
        header.setFont(QFont("맑은 고딕", 18, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)
        
        # === 퀵 액션 툴바 ===
        toolbar_frame = QFrame()
        toolbar_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(88, 166, 255, 0.05);
                border: 1px solid rgba(88, 166, 255, 0.15);
                border-radius: 10px;
                padding: 4px;
            }
        """)
        toolbar_layout = QHBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(8)
        
        # 툴바 버튼 스타일
        toolbar_btn_style = """
            QPushButton {
                background-color: rgba(88, 166, 255, 0.1);
                border: 1px solid rgba(88, 166, 255, 0.2);
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: rgba(88, 166, 255, 0.2);
                border-color: rgba(88, 166, 255, 0.4);
            }
            QPushButton:pressed {
                background-color: rgba(88, 166, 255, 0.3);
            }
        """
        
        # 빠른 저장 버튼
        quick_save_btn = QPushButton("💾 빠른 저장")
        quick_save_btn.setStyleSheet(toolbar_btn_style)
        quick_save_btn.setToolTip("현재 자막을 TXT로 빠르게 저장 (Ctrl+S)")
        quick_save_btn.clicked.connect(self._save_txt)
        
        # 검색 버튼
        search_btn = QPushButton("🔍 검색")
        search_btn.setStyleSheet(toolbar_btn_style)
        search_btn.setToolTip("자막 내 키워드 검색 (Ctrl+F)")
        search_btn.clicked.connect(self._show_search)
        
        # 클립보드 복사 버튼
        copy_btn = QPushButton("📋 복사")
        copy_btn.setStyleSheet(toolbar_btn_style)
        copy_btn.setToolTip("전체 자막을 클립보드에 복사")
        copy_btn.clicked.connect(self._copy_to_clipboard)
        
        # 자막 지우기 버튼
        clear_btn = QPushButton("🗑️ 지우기")
        clear_btn.setStyleSheet(toolbar_btn_style)
        clear_btn.setToolTip("현재 자막 목록 초기화")
        clear_btn.clicked.connect(self._clear_subtitles)
        
        toolbar_layout.addWidget(quick_save_btn)
        toolbar_layout.addWidget(search_btn)
        toolbar_layout.addWidget(copy_btn)
        toolbar_layout.addWidget(clear_btn)
        toolbar_layout.addStretch()
        
        # 테마 토글 버튼
        self.theme_toggle_btn = QPushButton("🌙" if self.is_dark_theme else "☀️")
        self.theme_toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                font-size: 18px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: rgba(88, 166, 255, 0.1);
                border-radius: 6px;
            }
        """)
        self.theme_toggle_btn.setToolTip("테마 전환")
        self.theme_toggle_btn.clicked.connect(self._toggle_theme_from_button)
        toolbar_layout.addWidget(self.theme_toggle_btn)
        
        layout.addWidget(toolbar_frame)
        
        # === URL/설정 영역 (접기/펼치기 가능) ===
        settings_group = CollapsibleGroupBox("⚙️ 설정")
        settings_layout = QGridLayout(settings_group)
        settings_layout.setSpacing(10)

        
        # URL
        url_label = QLabel("📌 URL:")
        url_label.setToolTip("국회 의사중계 웹사이트 URL을 입력하세요")
        settings_layout.addWidget(url_label, 0, 0)
        
        url_layout = QHBoxLayout()
        self.url_combo = QComboBox()
        self.url_combo.setEditable(True)
        self.url_combo.setToolTip("국회 의사중계 웹사이트 URL\n최근 사용한 URL이 자동 저장됩니다\n태그가 있으면 [태그] 형태로 표시됩니다")
        
        # URL 히스토리 로드 및 콤보박스 초기화
        for url, tag in self.url_history.items():
            if tag:
                self.url_combo.addItem(f"[{tag}] {url}", url)
            else:
                self.url_combo.addItem(url, url)
        
        if not self.url_history:
            self.url_combo.addItem("https://assembly.webcast.go.kr/main/player.asp")
        
        url_layout.addWidget(self.url_combo, 1)
        
        # 태그 버튼
        self.tag_btn = QPushButton("🏷️ 태그")
        self.tag_btn.setToolTip("현재 URL에 태그 추가/편집\n예: 본회의, 법사위, 상임위")
        self.tag_btn.setFixedWidth(85)
        self.tag_btn.clicked.connect(self._edit_url_tag)
        url_layout.addWidget(self.tag_btn)
        
        # 상임위원회 프리셋 버튼
        self.preset_btn = QPushButton("📋 상임위")
        self.preset_btn.setToolTip("상임위원회 프리셋 선택\n빠른 URL 입력을 위한 기능")
        self.preset_btn.setFixedWidth(110)
        
        # 프리셋 메뉴 생성
        self.preset_menu = QMenu(self)
        self._load_committee_presets()
        self._build_preset_menu()
        self.preset_btn.setMenu(self.preset_menu)
        url_layout.addWidget(self.preset_btn)
        
        settings_layout.addLayout(url_layout, 0, 1)

        # 생중계 목록 버튼 (추가)
        self.live_btn = QPushButton("📡 생중계 목록")
        self.live_btn.setToolTip("현재 진행 중인 생중계 목록을 확인하고 선택합니다")
        self.live_btn.setFixedWidth(120)
        self.live_btn.clicked.connect(self._show_live_dialog)
        url_layout.addWidget(self.live_btn)

        
        # 선택자
        selector_label = QLabel("🔍 선택자:")
        selector_label.setToolTip("자막 요소의 CSS 선택자")
        settings_layout.addWidget(selector_label, 1, 0)
        self.selector_combo = QComboBox()
        self.selector_combo.setEditable(True)
        self.selector_combo.addItems(["#viewSubtit .incont", "#viewSubtit", ".subtitle_area"])
        self.selector_combo.setToolTip("자막 텍스트가 표시되는 HTML 요소의 CSS 선택자\n기본값을 사용하거나 직접 입력하세요")
        settings_layout.addWidget(self.selector_combo, 1, 1)
        
        # 옵션
        options_layout = QHBoxLayout()
        options_layout.setSpacing(20)
        
        self.auto_scroll_check = QCheckBox("📜 자동 스크롤")
        self.auto_scroll_check.setChecked(True)
        self.auto_scroll_check.setToolTip("새 자막이 추가될 때 자동으로 맨 아래로 스크롤합니다")
        
        self.realtime_save_check = QCheckBox("💾 실시간 저장")
        self.realtime_save_check.setChecked(False)
        self.realtime_save_check.setToolTip("자막이 확정될 때마다 자동으로 파일에 저장합니다\n저장 위치: realtime_output 폴더")
        
        self.headless_check = QCheckBox("🔇 헤드리스 모드 (인터넷창 숨김)")
        self.headless_check.setChecked(False)
        self.headless_check.setToolTip("Chrome 브라우저 창을 숨기고 백그라운드에서 실행합니다.\n자막 추출 중 다른 작업을 할 수 있습니다.")
        options_layout.addWidget(self.auto_scroll_check)
        options_layout.addWidget(self.realtime_save_check)
        options_layout.addWidget(self.headless_check)
        options_layout.addStretch()
        settings_layout.addLayout(options_layout, 2, 0, 1, 2)
        
        layout.addWidget(settings_group)
        
        # === 컨트롤 버튼 ===
        btn_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("▶  시작")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.clicked.connect(self._start)
        
        self.stop_btn = QPushButton("⏹  중지")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # === 진행 표시 ===
        self.progress = QProgressBar()
        self.progress.setMaximum(0)
        self.progress.hide()
        layout.addWidget(self.progress)
        
        # === 메인 콘텐츠 (자막 + 통계) ===
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 자막 영역 컨테이너 (자막 텍스트 + 통계 토글 버튼)
        subtitle_container = QWidget()
        subtitle_layout = QVBoxLayout(subtitle_container)
        subtitle_layout.setContentsMargins(0, 0, 0, 0)
        subtitle_layout.setSpacing(8)
        
        # 자막 텍스트
        self.subtitle_text = QTextEdit()
        self.subtitle_text.setReadOnly(True)
        
        # 스마트 스크롤: 스크롤바 값 변경 시 사용자 스크롤 감지
        self.subtitle_text.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        
        subtitle_layout.addWidget(self.subtitle_text)
        
        # 통계 토글 버튼 (자막 영역 하단)
        self.toggle_stats_btn = QPushButton("📊 통계 숨기기")
        self.toggle_stats_btn.setToolTip("통계 패널 숨기기/보이기")
        self.toggle_stats_btn.setFixedHeight(28)
        self.toggle_stats_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(88, 166, 255, 0.1);
                border: 1px solid rgba(88, 166, 255, 0.3);
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(88, 166, 255, 0.2);
            }
        """)
        self.toggle_stats_btn.clicked.connect(self._toggle_stats_panel)
        subtitle_layout.addWidget(self.toggle_stats_btn)
        
        self.main_splitter.addWidget(subtitle_container)
        
        # 통계 패널 - 모던 디자인
        self.stats_group = QGroupBox("📊 통계")
        stats_layout = QVBoxLayout(self.stats_group)
        stats_layout.setSpacing(12)
        stats_layout.setContentsMargins(12, 20, 12, 12)
        
        self.stat_time = QLabel("⏱️ 실행 시간: 00:00:00")
        self.stat_chars = QLabel("📝 글자 수: 0")
        self.stat_words = QLabel("📖 단어 수: 0")
        self.stat_sents = QLabel("💬 문장 수: 0")
        self.stat_cpm = QLabel("⚡ 분당 글자: 0")
        
        stat_labels = [self.stat_time, self.stat_chars, self.stat_words, self.stat_sents, self.stat_cpm]
        for label in stat_labels:
            label.setFont(QFont("맑은 고딕", 10))
            label.setStyleSheet("""
                padding: 6px 8px;
                border-radius: 6px;
                background-color: rgba(88, 166, 255, 0.08);
            """)
            stats_layout.addWidget(label)
        
        stats_layout.addStretch()
        self.stats_group.setFixedWidth(220)
        self.main_splitter.addWidget(self.stats_group)
        
        self.main_splitter.setSizes([860, 220])
        layout.addWidget(self.main_splitter)
        
        # === "최신 자막" 플로팅 버튼 (스마트 스크롤용) ===
        self.scroll_to_bottom_btn = QPushButton("⬇️ 최신 자막")
        self.scroll_to_bottom_btn.setToolTip("최신 자막으로 이동하고 자동 스크롤 재개")
        self.scroll_to_bottom_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(88, 166, 255, 0.9);
                color: white;
                border: none;
                border-radius: 16px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(88, 166, 255, 1.0);
            }
        """)
        self.scroll_to_bottom_btn.clicked.connect(self._scroll_to_bottom)
        self.scroll_to_bottom_btn.hide()  # 초기에는 숨김
        layout.addWidget(self.scroll_to_bottom_btn)
        
        # === 검색바 (숨김) - 개선된 디자인 ===
        self.search_frame = QFrame()
        self.search_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(88, 166, 255, 0.05);
                border: 1px solid rgba(88, 166, 255, 0.2);
                border-radius: 10px;
                padding: 5px;
            }
        """)
        search_layout = QHBoxLayout(self.search_frame)
        search_layout.setContentsMargins(12, 8, 12, 8)
        search_layout.setSpacing(8)
        
        # 검색 아이콘 라벨
        search_icon = QLabel("🔍")
        search_icon.setStyleSheet("background: transparent; border: none;")
        search_layout.addWidget(search_icon)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색어 입력...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: transparent;
                border: none;
                padding: 6px;
                font-size: 13px;
            }
        """)
        self.search_input.returnPressed.connect(self._do_search)
        search_layout.addWidget(self.search_input, 1)
        
        self.search_count = QLabel("")
        self.search_count.setStyleSheet("""
            color: #8b949e;
            font-size: 12px;
            background: transparent;
            border: none;
            padding: 0 8px;
        """)
        search_layout.addWidget(self.search_count)
        
        # 검색 버튼 스타일
        search_btn_style = """
            QPushButton {
                background-color: rgba(88, 166, 255, 0.1);
                border: 1px solid rgba(88, 166, 255, 0.3);
                border-radius: 6px;
                padding: 6px;
                font-size: 12px;
                min-width: 32px;
            }
            QPushButton:hover {
                background-color: rgba(88, 166, 255, 0.2);
                border-color: #58a6ff;
            }
        """
        
        search_prev = QPushButton("◀")
        search_prev.setStyleSheet(search_btn_style)
        search_prev.setFixedWidth(36)
        search_prev.clicked.connect(lambda: self._nav_search(-1))
        
        search_next = QPushButton("▶")
        search_next.setStyleSheet(search_btn_style)
        search_next.setFixedWidth(36)
        search_next.clicked.connect(lambda: self._nav_search(1))
        
        search_close = QPushButton("✕")
        search_close.setStyleSheet("""
            QPushButton {
                background-color: rgba(248, 81, 73, 0.1);
                border: 1px solid rgba(248, 81, 73, 0.3);
                border-radius: 6px;
                padding: 6px;
                font-size: 12px;
                min-width: 32px;
            }
            QPushButton:hover {
                background-color: rgba(248, 81, 73, 0.2);
                border-color: #f85149;
            }
        """)
        search_close.setFixedWidth(36)
        search_close.clicked.connect(self._hide_search)
        
        search_layout.addWidget(search_prev)
        search_layout.addWidget(search_next)
        search_layout.addWidget(search_close)
        
        # 검색바 초기에 숨김 상태
        self.search_frame.hide()
        layout.addWidget(self.search_frame)
        
        # === 상태바 - 모던 디자인 ===
        status_frame = QFrame()
        status_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(48, 54, 61, 0.3);
                border-radius: 10px;
                padding: 4px;
            }
        """)
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(16, 10, 16, 10)
        status_layout.setSpacing(12)
        
        # 상태 텍스트
        self.status_label = QLabel("⚪ 대기 중")
        self.status_label.setStyleSheet("background: transparent; border: none; font-weight: 600; font-size: 13px;")
        
        # 연결 상태 인디케이터 (#30) - 개선된 디자인
        self.connection_indicator = QLabel("⚫")
        self.connection_indicator.setToolTip("연결 상태: 대기 중")
        self.connection_indicator.setStyleSheet("""
            background: transparent; 
            border: none; 
            font-size: 14px;
            padding: 2px 8px;
            border-radius: 4px;
        """)
        
        # 구분선
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setStyleSheet("background-color: rgba(88, 166, 255, 0.3); max-width: 1px;")
        
        # 카운트 라벨 - 개선된 스타일
        self.count_label = QLabel("📝 0문장 | 0자")
        self.count_label.setStyleSheet("""
            color: #8b949e; 
            background: rgba(88, 166, 255, 0.08); 
            border: none;
            border-radius: 6px;
            padding: 4px 10px;
            font-weight: 500;
        """)
        
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.connection_indicator)
        status_layout.addWidget(separator)
        status_layout.addWidget(self.count_label)
        
        layout.addWidget(status_frame)

        
        # 검색 상태
        self.search_matches = []
        self.search_idx = 0
        
        # 저장된 폰트 크기 적용
        self._set_font_size(self.font_size)
    
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
        else:
            stat_bg = "rgba(9, 105, 218, 0.06)"
            search_bg = "rgba(9, 105, 218, 0.04)"
            search_border = "rgba(9, 105, 218, 0.15)"
            status_bg = "rgba(208, 215, 222, 0.4)"
            count_color = "#57606a"
        
        # 통계 라벨 스타일 업데이트
        try:
            stat_labels = [self.stat_time, self.stat_chars, self.stat_words, self.stat_sents, self.stat_cpm]
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
            self.count_label.setStyleSheet(f"color: {count_color}; background: transparent; border: none;")
        except AttributeError:
            # UI가 아직 완전히 초기화되지 않은 경우
            pass
    
    def _toggle_theme(self):
        self.is_dark_theme = not self.is_dark_theme
        self.settings.setValue("dark_theme", self.is_dark_theme)
        self._apply_theme()
    
    def _toggle_tray_option(self):
        """트레이 최소화 옵션 토글"""
        self.minimize_to_tray = self.tray_action.isChecked()
        self.settings.setValue("minimize_to_tray", self.minimize_to_tray)
        if self.minimize_to_tray:
            self._show_toast("창을 닫으면 트레이로 최소화됩니다.", "info")
        else:
            self._show_toast("창을 닫으면 프로그램이 종료됩니다.", "info")
    
    def _setup_shortcuts(self):
        QShortcut(QKeySequence("F5"), self, self._start)
        QShortcut(QKeySequence("Escape"), self, self._stop)
        QShortcut(QKeySequence("F3"), self, lambda: self._nav_search(1))
        QShortcut(QKeySequence("Shift+F3"), self, lambda: self._nav_search(-1))
    
    # ========== 토스트 및 상태 표시 ==========
    
    def _show_toast(self, message: str, toast_type: str = "info", duration: int = 3000) -> None:
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
            self.centralWidget(), message, duration, toast_type,
            y_offset=y_offset, on_close=remove_toast
        )
        self.active_toasts.append(toast)
    
    def _set_status(self, text: str, status_type: str = "info"):
        """상태 표시 (아이콘 + 색상)"""
        icons = {
            "info": "ℹ️",
            "success": "✅",
            "warning": "⚠️",
            "error": "❌",
            "running": "🔄"
        }
        colors = {
            "info": "#4fc3f7",
            "success": "#4caf50",
            "warning": "#ff9800",
            "error": "#f44336",
            "running": "#ab47bc"
        }
        icon = icons.get(status_type, "")
        color = colors.get(status_type, "#eaeaea")
        self.status_label.setText(f"{icon} {text}"[:100])
        self.status_label.setStyleSheet(f"color: {color};")
    
    def _update_count_label(self):
        """자막 카운트 라벨 업데이트"""
        with self.subtitle_lock:
            count = len(self.subtitles)
        chars = self._cached_total_chars
        self.count_label.setText(f"📝 {count}문장 | {chars:,}자")
    
    def _update_connection_status(self, status: str, latency: int = None):
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
            "reconnecting": ("🟡", "#ff9800", "재연결 중...")
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
        
        self.connection_indicator.setText(icon)
        self.connection_indicator.setToolTip(tooltip)
        self.connection_indicator.setStyleSheet(f"background: transparent; border: none; font-size: 12px; color: {color};")
    
    # ========== 글자 크기 ==========
    
    def _set_font_size(self, size: int):
        """자막 영역 폰트 크기 변경"""
        size = max(Config.MIN_FONT_SIZE, min(size, Config.MAX_FONT_SIZE))
        self.font_size = size
        font = self.subtitle_text.font()
        font.setPointSize(size)
        self.subtitle_text.setFont(font)
        self.settings.setValue("font_size", size)
    
    def _adjust_font_size(self, delta: int):
        """폰트 크기 조절"""
        self._set_font_size(self.font_size + delta)
    
    # ========== URL 히스토리 (태그 지원) ==========
    
    def _load_url_history(self):
        """URL 히스토리 로드 - {url: tag} 형태"""
        try:
            if Path("url_history.json").exists():
                with open("url_history.json", 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # dict 형태인지 확인 (새로운 형식)
                    if isinstance(data, dict):
                        return data
                    # 이전 list 형태면 dict로 변환
                    elif isinstance(data, list):
                        return {url: "" for url in data}
        except Exception as e:
            logger.warning(f"URL 히스토리 로드 오류: {e}")
        return {}
    
    def _save_url_history(self):
        """URL 히스토리 저장"""
        try:
            if not isinstance(self.url_history, dict):
                self.url_history = {}
            with open("url_history.json", 'w', encoding='utf-8') as f:
                json.dump(self.url_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"URL 히스토리 저장 오류: {e}")
    
    def _add_to_history(self, url, tag=""):
        """URL 히스토리에 추가 (자동 태그 매칭)"""
        if not isinstance(self.url_history, dict):
            self.url_history = {}
        
        # 태그가 없으면 자동 감지
        if not tag:
            # 1. 이미 저장된 태그가 있는지 확인
            if url in self.url_history and self.url_history[url]:
                tag = self.url_history[url]
            else:
                # 2. 프리셋/약칭에서 매칭 확인
                tag = self._autodetect_tag(url)
        
        self.url_history[url] = tag
        
        # 히스토리 크기 제한
        if len(self.url_history) > Config.MAX_URL_HISTORY:
            # 가장 오래된 항목 삭제 (dict는 삽입 순서 유지)
            oldest_key = next(iter(self.url_history))
            del self.url_history[oldest_key]
        
        self._save_url_history()
        self._refresh_url_combo()

    def _autodetect_tag(self, url):
        """URL을 기반으로 위원회 이름/약칭 자동 감지"""
        # 1. 정확한 URL 매칭 확인 (프리셋)
        for name, preset_url in self.committee_presets.items():
            if url == preset_url:
                # 약칭이 있으면 약칭 사용 (더 짧고 보기 좋음)
                for abbr, full_name in Config.COMMITTEE_ABBREVIATIONS.items():
                    if full_name == name:
                        return abbr
                return name
        
        # 2. xcode 파라미터 매칭 (숫자 또는 문자열 xcode 모두 지원)
        import re
        match = re.search(r'xcode=([^&]+)', url)
        if match:
            xcode = match.group(1)
            # 프리셋에서 해당 xcode를 가진 URL 찾기
            for name, preset_url in self.committee_presets.items():
                if f"xcode={xcode}" in preset_url:
                    # 약칭 리턴
                    for abbr, full_name in Config.COMMITTEE_ABBREVIATIONS.items():
                        if full_name == name:
                            return abbr
                    return name
                    
        return ""
    
    def _refresh_url_combo(self):
        """URL 콤보박스 새로고침"""
        current_text = self.url_combo.currentText()
        self.url_combo.clear()
        
        for url, tag in self.url_history.items():
            if tag:
                self.url_combo.addItem(f"[{tag}] {url}", url)
            else:
                self.url_combo.addItem(url, url)
        
        # 기본 URL 추가
        if not self.url_history:
            self.url_combo.addItem("https://assembly.webcast.go.kr/main/player.asp")
        
        # 이전 텍스트 복원
        if current_text:
            self.url_combo.setCurrentText(current_text)
    
    def _get_current_url(self):
        """현재 선택된 URL 반환 (태그 제거)"""
        text = self.url_combo.currentText().strip()
        text_url = text
        if text.startswith("[") and "] " in text:
            text_url = text.split("] ", 1)[1].strip()
        
        data = self.url_combo.currentData()
        if data:
            data_url = str(data).strip()
            if text_url and text_url != data_url:
                return text_url
            return data_url
        
        return text_url
    
    def _edit_url_tag(self):
        """현재 URL의 태그 편집"""
        url = self._get_current_url()
        if not url or not url.startswith(('http://', 'https://')):
            QMessageBox.warning(self, "알림", "태그를 지정할 URL을 먼저 선택하세요.")
            return
        
        current_tag = self.url_history.get(url, "")
        tag, ok = QInputDialog.getText(
            self, "URL 태그 설정",
            f"URL: {url[:50]}...\n\n태그 입력 (예: 본회의, 법사위, 상임위):",
            text=current_tag
        )
        
        if ok:
            self._add_to_history(url, tag.strip())
            QMessageBox.information(self, "성공", f"태그가 설정되었습니다: [{tag}]" if tag else "태그가 제거되었습니다.")
    
    # ========== 상임위 프리셋 ==========
    
    def _load_committee_presets(self):
        """프리셋 파일에서 로드 (없으면 기본값 사용)"""
        self.committee_presets = dict(Config.DEFAULT_COMMITTEE_PRESETS)
        self.custom_presets = {}
        
        try:
            if Path(Config.PRESET_FILE).exists():
                with open(Config.PRESET_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if "presets" in data:
                        self.committee_presets.update(data["presets"])
                    if "custom" in data:
                        self.custom_presets = data["custom"]
        except Exception as e:
            logger.warning(f"프리셋 로드 오류: {e}")
    
    def _save_committee_presets(self):
        """프리셋을 파일에 저장"""
        try:
            data = {
                "presets": self.committee_presets,
                "custom": self.custom_presets
            }
            with open(Config.PRESET_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"프리셋 저장 오류: {e}")
    
    def _build_preset_menu(self):
        """프리셋 메뉴 구성"""
        self.preset_menu.clear()
        
        # 기본 상임위원회
        for name, url in self.committee_presets.items():
            action = QAction(name, self)
            action.setData(url)
            action.triggered.connect(lambda checked, u=url, n=name: self._select_preset(u, n))
            self.preset_menu.addAction(action)
        
        # 사용자 정의 프리셋이 있으면 구분선 추가
        if self.custom_presets:
            self.preset_menu.addSeparator()
            self.preset_menu.addAction("── 사용자 정의 ──").setEnabled(False)
            
            for name, url in self.custom_presets.items():
                action = QAction(f"⭐ {name}", self)
                action.setData(url)
                action.triggered.connect(lambda checked, u=url, n=name: self._select_preset(u, n))
                self.preset_menu.addAction(action)
        
        # 관리 메뉴
        self.preset_menu.addSeparator()
        add_action = QAction("➕ 프리셋 추가...", self)
        add_action.triggered.connect(self._add_custom_preset)
        self.preset_menu.addAction(add_action)
        
        edit_action = QAction("✏️ 프리셋 관리...", self)
        edit_action.triggered.connect(self._manage_presets)
        self.preset_menu.addAction(edit_action)
        
        self.preset_menu.addSeparator()
        export_action = QAction("📤 프리셋 내보내기...", self)
        export_action.triggered.connect(self._export_presets)
        self.preset_menu.addAction(export_action)
        
        import_action = QAction("📥 프리셋 가져오기...", self)
        import_action.triggered.connect(self._import_presets)
        self.preset_menu.addAction(import_action)
    
    def _select_preset(self, url, name):
        """프리셋 선택 시 URL 설정"""
        self.url_combo.setCurrentText(url)
        self._show_toast(f"'{name}' 선택됨", "success", 1500)
    
    def _add_custom_preset(self):
        """사용자 정의 프리셋 추가"""
        name, ok = QInputDialog.getText(
            self, "프리셋 추가",
            "프리셋 이름을 입력하세요:"
        )
        if not ok or not name.strip():
            return
        
        name = name.strip()
        current_url = self._get_current_url()
        
        url, ok = QInputDialog.getText(
            self, "프리셋 URL",
            f"'{name}' 프리셋의 URL을 입력하세요:",
            text=current_url if current_url.startswith('http') else Config.DEFAULT_URL
        )
        
        if ok and url.strip():
            self.custom_presets[name] = url.strip()
            self._save_committee_presets()
            self._build_preset_menu()
            self._show_toast(f"프리셋 '{name}' 추가됨", "success")
    
    def _is_similar_subtitle(self, text1: str, text2: str, threshold: float = 0.9) -> bool:
        """두 자막이 유사한지 판단 (Jaccard 유사도)"""
        norm1 = self._compact_subtitle_text(text1)
        norm2 = self._compact_subtitle_text(text2)
        
        if norm1 == norm2:
            return True
        
        # 문자 단위 Jaccard 유사도
        set1, set2 = set(norm1), set(norm2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return (intersection / union) >= threshold if union > 0 else False

    def _manage_presets(self):
        """프리셋 관리 대화상자"""
        if not self.custom_presets:
            QMessageBox.information(
                self, "프리셋 관리",
                "사용자 정의 프리셋이 없습니다.\n\n"
                "'➕ 프리셋 추가'를 통해 새 프리셋을 추가하세요."
            )
            return
        
        # 작업 선택
        names = list(self.custom_presets.keys())
        actions = ["수정", "삭제"]
        action, ok = QInputDialog.getItem(
            self, "프리셋 관리",
            "작업을 선택하세요:",
            actions, 0, False
        )
        
        if not ok:
            return
        
        # 프리셋 선택
        name, ok = QInputDialog.getItem(
            self, f"프리셋 {action}",
            f"{action}할 프리셋을 선택하세요:",
            names, 0, False
        )
        
        if not ok or not name:
            return
        
        if action == "삭제":
            reply = QMessageBox.question(
                self, "확인",
                f"'{name}' 프리셋을 삭제하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                del self.custom_presets[name]
                self._save_committee_presets()
                self._build_preset_menu()
                self._show_toast(f"프리셋 '{name}' 삭제됨", "warning")
        
        elif action == "수정":
            # 이름 수정
            new_name, ok = QInputDialog.getText(
                self, "프리셋 이름 수정",
                f"'{name}' 프리셋의 새 이름:",
                text=name
            )
            if not ok:
                return
            
            # URL 수정
            current_url = self.custom_presets[name]
            new_url, ok = QInputDialog.getText(
                self, "프리셋 URL 수정",
                f"'{new_name}' 프리셋의 URL:",
                text=current_url
            )
            if not ok:
                return
            
            # 기존 프리셋 삭제 후 새로 추가 (이름이 변경되었을 수 있으므로)
            del self.custom_presets[name]
            self.custom_presets[new_name.strip()] = new_url.strip()
            self._save_committee_presets()
            self._build_preset_menu()
            self._show_toast(f"프리셋 '{new_name}' 수정됨", "success")
    
    def _export_presets(self):
        """프리셋을 파일로 내보내기"""
        filename = f"presets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "프리셋 내보내기", filename, "JSON 파일 (*.json)"
        )
        
        if path:
            try:
                data = {
                    "version": Config.VERSION,
                    "exported": datetime.now().isoformat(),
                    "committee": self.committee_presets,
                    "custom": self.custom_presets
                }
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                total = len(self.committee_presets) + len(self.custom_presets)
                self._show_toast(f"프리셋 {total}개 내보내기 완료!", "success")
                logger.info(f"프리셋 내보내기 완료: {path}")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"프리셋 내보내기 실패: {e}")
    
    def _import_presets(self):
        """파일에서 프리셋 가져오기"""
        path, _ = QFileDialog.getOpenFileName(
            self, "프리셋 가져오기", "", "JSON 파일 (*.json)"
        )
        
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                imported_count = 0
                
                # 사용자 정의 프리셋 가져오기 (기존 것에 추가)
                if "custom" in data and isinstance(data["custom"], dict):
                    for name, url in data["custom"].items():
                        if name not in self.custom_presets:
                            self.custom_presets[name] = url
                            imported_count += 1
                
                if imported_count > 0:
                    self._save_committee_presets()
                    self._build_preset_menu()
                    self._show_toast(f"프리셋 {imported_count}개 가져오기 완료!", "success")
                else:
                    self._show_toast("가져올 새 프리셋이 없습니다", "info")
                
                logger.info(f"프리셋 가져오기 완료: {path}, {imported_count}개")
            except json.JSONDecodeError:
                QMessageBox.warning(self, "오류", "잘못된 JSON 파일 형식입니다.")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"프리셋 가져오기 실패: {e}")
    
    # ========== 추출 제어 ==========
    
    def _start(self):
        if self.is_running:
            return
        
        url = self._get_current_url().strip()
        selector = self.selector_combo.currentText().strip()
        
        if not url or not selector:
            QMessageBox.warning(self, "오류", "URL과 선택자를 입력하세요.")
            return
        
        if not url.startswith(('http://', 'https://')):
            QMessageBox.warning(self, "오류", "올바른 URL을 입력하세요.")
            return
        
        try:
            # 히스토리에 추가
            self._add_to_history(url)
            
            # 초기화
            self.subtitle_text.clear()
            with self.subtitle_lock:
                self.subtitles = []
            self._cached_total_chars = 0
            self._cached_total_words = 0
            self._update_count_label()

            self.last_subtitle = ""
            self.last_update_time = 0
            self._pending_minute_bucket = None
            self._is_stopping = False
            self.finalize_timer.stop()
            self.start_time = time.time()
            
            # 큐 비우기
            self._clear_message_queue()
            
            # 실시간 저장 설정 (예외 처리 추가)
            self.realtime_file = None
            if self.realtime_save_check.isChecked():
                try:
                    Path(Config.REALTIME_DIR).mkdir(exist_ok=True)
                    filename = f"{Config.REALTIME_DIR}/자막_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    self.realtime_file = open(filename, 'w', encoding='utf-8')
                    self._set_status(f"실시간 저장: {filename}", "success")
                except Exception as e:
                    logger.error(f"실시간 저장 파일 생성 오류: {e}")
            
            # UI 업데이트
            self.is_running = True
            self.stop_event.clear()  # 종료 이벤트 초기화
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.url_combo.setEnabled(False)
            self.selector_combo.setEnabled(False)
            self.progress.show()
            
            self._set_status("Chrome 브라우저 시작 중...", "running")
            self._update_tray_status("🟢 추출 중")
            
            # UI 값을 시작 시점에 복사 (스레드 안전성)
            headless = self.headless_check.isChecked()
            
            # 워커 시작
            self.worker = threading.Thread(
                target=self._extraction_worker,
                args=(url, selector, headless),
                daemon=True
            )
            self.worker.start()
            
            # 타이머 시작
            self.stats_timer.start(Config.STATS_UPDATE_INTERVAL)
            self.backup_timer.start(Config.AUTO_BACKUP_INTERVAL)
        
        except Exception as e:
            logger.exception(f"시작 오류: {e}")
            # 파일 핸들 정리
            if self.realtime_file:
                try:
                    self.realtime_file.close()
                except Exception:
                    pass
                self.realtime_file = None
            self._reset_ui()
            QMessageBox.critical(self, "오류", f"시작 중 오류 발생: {e}")
    
    def _stop(self):
        if not self.is_running:
            return
        
        self._is_stopping = True
        self.is_running = False
        self.stop_event.set()  # 워커 스레드에 종료 신호
        self._set_status("중지 중...", "warning")
        
        # 확정 타이머 중지 (수동 확정/종료 시 불필요한 타이머 반복 방지)
        self.finalize_timer.stop()

        # 마지막 자막 즉시 확정
        if self.last_subtitle:
            self._finalize_subtitle(self.last_subtitle, entry_timestamp=self._pending_minute_bucket)
            self.last_subtitle = ""
            self._pending_minute_bucket = None
        else:
            self._pending_minute_bucket = None

        # 워커 스레드 종료 대기 (최대 3초)
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=Config.THREAD_STOP_TIMEOUT)
            if self.worker.is_alive():
                logger.warning("워커 스레드가 시간 내에 종료되지 않음")
        
        # 실시간 저장 종료
        if self.realtime_file:
            try:
                self.realtime_file.close()
            except Exception as e:
                logger.debug(f"파일 닫기 오류: {e}")
            self.realtime_file = None
        
        # WebDriver 종료 (중복 종료 방지)
        if self.driver:
            try:
                driver = self.driver
                self.driver = None  # 먼저 None 설정
                driver.quit()
            except Exception as e:
                logger.debug(f"WebDriver 종료 중 오류 (무시됨): {e}")

        self._clear_message_queue()
        self._reset_ui()
        self._set_status("중지됨", "warning")
        self._update_tray_status("⚪ 대기 중")
        self._is_stopping = False
    
    def _reset_ui(self):
        self.is_running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.url_combo.setEnabled(True)
        self.selector_combo.setEnabled(True)
        self.progress.hide()
        self.stats_timer.stop()
        self.backup_timer.stop()
        self.finalize_timer.stop()
        self._pending_minute_bucket = None
    
    # ========== 워커 스레드 ==========
    
    def _get_query_param(self, url: str, name: str) -> str:
        """URL 쿼리 파라미터 값 추출 (없으면 빈 문자열)"""
        match = re.search(r'(?:^|[?&])' + re.escape(name) + r'=([^&]*)', url)
        return match.group(1) if match else ""
    
    def _set_query_param(self, url: str, name: str, value: str) -> str:
        """URL 쿼리 파라미터 설정/교체"""
        base_url = url.strip().rstrip('&')
        pattern = re.compile(r'([?&])' + re.escape(name) + r'=[^&]*')
        if pattern.search(base_url):
            return pattern.sub(lambda m: f"{m.group(1)}{name}={value}", base_url, count=1)
        sep = '&' if '?' in base_url else '?'
        return f"{base_url}{sep}{name}={value}"
    
    def _fetch_live_list(self):
        """국회 생중계 목록 API에서 현재 방송 목록 가져오기"""
        api_url = f"https://assembly.webcast.go.kr/main/service/live_list.asp?vv={int(time.time())}"
        try:
            req = Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=10) as response:
                payload = response.read().decode("utf-8", errors="replace")
            data = json.loads(payload)
            if isinstance(data, dict):
                return data.get("xlist", [])
        except (HTTPError, URLError, json.JSONDecodeError) as e:
            logger.debug(f"live_list API 오류: {e}")
        except Exception as e:
            logger.debug(f"live_list 처리 오류: {e}")
        return []
    
    def _show_live_dialog(self):
        """생중계 목록 다이얼로그 표시"""
        dialog = LiveBroadcastDialog(self)
        if dialog.exec():
            data = dialog.selected_broadcast
            if data:
                # 선택된 방송 정보로 URL 생성
                # player.asp?xcode={xcode}&xcgcd={xcgcd} 형식이 가장 안정적임
                xcode = str(data.get("xcode", "")).strip()
                xcgcd = str(data.get("xcgcd", "")).strip()
                
                if xcode and xcgcd:
                    # 기본 URL
                    base_url = "https://assembly.webcast.go.kr/main/player.asp"
                    new_url = f"{base_url}?xcode={xcode}&xcgcd={xcgcd}"
                    
                    # 콤보박스에 설정
                    name = data.get("xname", "").strip()
                    self._add_to_history(new_url, name)
                    idx = self.url_combo.findData(new_url)
                    if idx >= 0:
                        self.url_combo.setCurrentIndex(idx)
                    else:
                        self.url_combo.setEditText(new_url)
                    
                    # 태그 자동 설정 (방송명) - _add_to_history에서 처리됨
                    # 바로 시작할지 물어보는 것도 좋지만, 일단 URL만 채워줌
                    # Toast 알림
                    self._show_toast(f"방송이 선택되었습니다:\n{name}", toast_type="success")

    def _resolve_live_url_from_list(self, original_url: str, target_xcode: str) -> str:

        """live_list API로 xcgcd/xcode를 보완하여 URL 생성"""
        broadcasts = self._fetch_live_list()
        if not broadcasts:
            return original_url
        
        current_xcgcd = self._get_query_param(original_url, "xcgcd").strip()
        target_norm = target_xcode.strip().upper() if target_xcode else ""
        
        # xcgcd가 있으면 유효한 것으로 간주 (xstat 상태와 무관하게 시도)
        def is_valid_broadcast(item):
            return bool(str(item.get("xcgcd", "")).strip())
        
        if current_xcgcd and not target_norm:
            for bc in broadcasts:
                bc_xcgcd = str(bc.get("xcgcd", "")).strip()
                if bc_xcgcd and bc_xcgcd == current_xcgcd:
                    bc_xcode = str(bc.get("xcode", "")).strip()
                    if bc_xcode:
                        new_url = self._set_query_param(original_url, "xcode", bc_xcode)
                        logger.info(f"live_list로 xcode 보완: xcode={bc_xcode}")
                        return new_url
        
        if target_norm:
            for bc in broadcasts:
                bc_xcode = str(bc.get("xcode", "")).strip()
                # xcode가 일치하고 xcgcd가 있으면 사용 (xstat 조건 완화)
                if bc_xcode.upper() == target_norm and is_valid_broadcast(bc):
                    xcgcd = str(bc.get("xcgcd", "")).strip()
                    new_url = self._set_query_param(original_url, "xcgcd", xcgcd)
                    if not self._get_query_param(new_url, "xcode"):
                        new_url = self._set_query_param(new_url, "xcode", bc_xcode)
                    logger.info(f"live_list 매칭 성공: xcode={bc_xcode}, xcgcd={xcgcd}")
                    return new_url
            logger.warning(f"live_list에서 xcode={target_norm} 생중계 미발견")
        else:
            for bc in broadcasts:
                if is_valid_broadcast(bc):
                    xcgcd = str(bc.get("xcgcd", "")).strip()
                    new_url = self._set_query_param(original_url, "xcgcd", xcgcd)
                    if not self._get_query_param(new_url, "xcode"):
                        bc_xcode = str(bc.get("xcode", "")).strip()
                        if bc_xcode:
                            new_url = self._set_query_param(new_url, "xcode", bc_xcode)
                    logger.info(f"live_list 첫 생중계 사용: xcgcd={xcgcd}")
                    return new_url
        
        return original_url
    
    def _detect_live_broadcast(self, driver, original_url: str) -> str:
        """현재 진행 중인 생중계의 xcgcd를 자동 감지
        
        Args:
            driver: Selenium WebDriver
            original_url: 원래 요청된 URL
            
        Returns:
            str: 감지된 xcgcd를 포함한 URL, 감지 실패 시 원래 URL 반환
        """
        try:
            existing_xcgcd = self._get_query_param(original_url, "xcgcd").strip()
            existing_xcode = self._get_query_param(original_url, "xcode").strip()
            
            # 원래 URL에 xcode/xcgcd가 모두 있으면 그대로 사용
            if existing_xcgcd and existing_xcode:
                logger.info(f"URL에 이미 xcode/xcgcd 포함됨: {original_url}")
                return original_url
            
            self.message_queue.put(("status", "🔍 현재 생중계 감지 중..."))
            
            # xcode 추출 (모든 방법에서 공통으로 사용)
            target_xcode = existing_xcode or None
            target_xcode_norm = target_xcode.upper() if target_xcode else None
            logger.info(f"xcgcd 탐색 시작 - target_xcode: {target_xcode}")
            
            # 방법 0: live_list API로 생중계 정보 확인 (사이트 구조 기반)
            resolved_url = self._resolve_live_url_from_list(original_url, target_xcode)
            if resolved_url != original_url and self._get_query_param(resolved_url, "xcgcd"):
                logger.info(f"live_list 기반 URL 감지 성공: {resolved_url}")
                return resolved_url
            
            # xcgcd에서 xcode 추출하는 헬퍼 함수
            # xcgcd 형식: DCM0000XX... 여기서 XX가 xcode 부분 (예: IO, 25 등)
            def extract_xcode_from_xcgcd(xcgcd_val):
                """xcgcd 값에서 xcode 부분 추출 시도"""
                if not xcgcd_val:
                    return None
                # DCM0000 접두사 이후 부분 추출 시도
                # 예: DCM0000IO224310401 -> IO
                # 예: DCM000025224310401 -> 25
                match = re.search(r'DCM0000([A-Za-z0-9]+)', xcgcd_val)
                if match:
                    code = match.group(1)
                    # 숫자+나머지 패턴 (예: 25224310401 -> 25)
                    num_match = re.match(r'^(\d{2})', code)
                    if num_match:
                        return num_match.group(1)
                    # 문자+나머지 패턴 (예: IO224310401 -> IO)
                    alpha_match = re.match(r'^([A-Za-z]+)', code)
                    if alpha_match:
                        return alpha_match.group(1)
                return None
            
            # 방법 1: 현재 페이지의 JavaScript 변수에서 xcgcd 가져오기
            scripts = [
                # 전역 변수에서 xcgcd 찾기
                "return typeof xcgcd !== 'undefined' ? xcgcd : null;",
                "return typeof XCGCD !== 'undefined' ? XCGCD : null;",
                "return window.xcgcd || null;",
                "return window.XCGCD || null;",
                # URL 파라미터에서 추출
                "return new URLSearchParams(window.location.search).get('xcgcd');",
                # 현재 스트림 정보에서 추출
                "if(typeof streamInfo !== 'undefined' && streamInfo.xcgcd) return streamInfo.xcgcd; return null;",
                # 플레이어 정보에서 추출
                "if(typeof playerConfig !== 'undefined' && playerConfig.xcgcd) return playerConfig.xcgcd; return null;",
            ]
            
            xcgcd = None
            for script in scripts:
                try:
                    result = driver.execute_script(script)
                    if result:
                        found_xcgcd = str(result)
                        # target_xcode가 있으면 xcgcd의 xcode 부분 검증
                        if target_xcode:
                            found_xcode = extract_xcode_from_xcgcd(found_xcgcd)
                            if found_xcode and target_xcode_norm and found_xcode.upper() != target_xcode_norm:
                                logger.warning(f"JavaScript xcgcd의 xcode({found_xcode})가 target({target_xcode})와 불일치 - 무시")
                                continue
                        xcgcd = found_xcgcd
                        logger.info(f"JavaScript에서 xcgcd 발견: {xcgcd}")
                        break
                except Exception as e:
                    logger.debug(f"Script 실행 오류: {e}")
            
            # 방법 2: URL이 리다이렉트 되었는지 확인
            if not xcgcd:
                current_url = driver.current_url
                found_xcgcd = self._get_query_param(current_url, "xcgcd").strip()
                if found_xcgcd:
                    # target_xcode 검증
                    if target_xcode:
                        found_xcode = extract_xcode_from_xcgcd(found_xcgcd)
                        if found_xcode and target_xcode_norm and found_xcode.upper() != target_xcode_norm:
                            logger.warning(f"리다이렉트된 xcgcd의 xcode({found_xcode})가 target({target_xcode})와 불일치 - 무시")
                        else:
                            xcgcd = found_xcgcd
                            logger.info(f"리다이렉트된 URL에서 xcgcd 발견: {xcgcd}")
                    else:
                        xcgcd = found_xcgcd
                        logger.info(f"리다이렉트된 URL에서 xcgcd 발견: {xcgcd}")
            
            # 방법 3: 페이지 내 생중계 목록에서 현재 방송 찾기
            # 주의: 이 페이지에 여러 방송 링크가 있을 수 있으므로 xcode 검증 필요
            # (target_xcode는 이미 위에서 추출됨)
            if not xcgcd:
                try:
                    if target_xcode:
                        # target_xcode가 있으면 해당 xcode가 포함된 링크만 검색
                        script = f"""
                        var links = document.querySelectorAll('a[href*="xcode={target_xcode}"][href*="xcgcd="]');
                        for(var i=0; i<links.length; i++) {{
                            var href = links[i].getAttribute('href');
                            var match = href.match(/xcgcd=([^&]+)/);
                            if(match) return match[1];
                        }}
                        return null;
                        """
                        result = driver.execute_script(script)
                        if result:
                            xcgcd = str(result)
                            logger.info(f"페이지 요소에서 xcode={target_xcode} 매칭 xcgcd 발견: {xcgcd}")
                    else:
                        # target_xcode가 없으면(본회의 등) 기존 로직 사용
                        live_scripts = [
                            """
                            var links = document.querySelectorAll('a[href*="xcgcd="]');
                            for(var i=0; i<links.length; i++) {
                                var href = links[i].getAttribute('href');
                                if(href && href.includes('xcgcd=')) {
                                    var match = href.match(/xcgcd=([^&]+)/);
                                    if(match) return match[1];
                                }
                            }
                            return null;
                            """,
                            """
                            var iframe = document.querySelector('iframe[src*="xcgcd="]');
                            if(iframe) {
                                var src = iframe.getAttribute('src');
                                var match = src.match(/xcgcd=([^&]+)/);
                                if(match) return match[1];
                            }
                            return null;
                            """,
                            """
                            var input = document.querySelector('input[name="xcgcd"], input#xcgcd');
                            if(input) return input.value;
                            return null;
                            """,
                        ]
                        
                        for script in live_scripts:
                            result = driver.execute_script(script)
                            if result:
                                xcgcd = str(result)
                                logger.info(f"페이지 요소에서 xcgcd 발견: {xcgcd}")
                                break
                except Exception as e:
                    logger.debug(f"생중계 목록 파싱 오류: {e}")
            
            # 방법 4: 메인 페이지에서 오늘의 생중계 정보 가져오기 (개선됨)
            # (target_xcode는 이미 위에서 추출됨)
            if not xcgcd:
                navigated_to_main = False
                try:
                    
                    # 메인 페이지로 이동
                    main_url = "https://assembly.webcast.go.kr/main/"
                    self.message_queue.put(("status", "🔍 메인 페이지에서 생중계 목록 확인 중..."))
                    driver.get(main_url)
                    navigated_to_main = True
                    
                    # 동적 콘텐츠 로딩 대기 (최대 10초)
                    try:
                        wait = WebDriverWait(driver, 10)
                        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="xcgcd="]')))
                    except Exception:
                        # 타임아웃 시 기본 대기
                        time.sleep(3)
                    
                    # 모든 생중계 링크 수집
                    all_broadcasts_script = """
                    var results = [];
                    var links = document.querySelectorAll('a[href*="xcgcd="]');
                    for(var i=0; i<links.length; i++) {
                        var href = links[i].getAttribute('href');
                        var text = links[i].innerText || links[i].textContent || '';
                        if(href && href.includes('xcgcd=')) {
                            var xcgcdMatch = href.match(/xcgcd=([^&]+)/);
                            var xcodeMatch = href.match(/xcode=([^&]+)/);
                            if(xcgcdMatch) {
                                results.push({
                                    xcgcd: xcgcdMatch[1],
                                    xcode: xcodeMatch ? xcodeMatch[1] : null,
                                    text: text.trim()
                                });
                            }
                        }
                    }
                    return JSON.stringify(results);
                    """
                    
                    broadcasts_json = driver.execute_script(all_broadcasts_script)
                    broadcasts = json.loads(broadcasts_json) if broadcasts_json else []
                    logger.info(f"발견된 생중계 목록: {len(broadcasts)}개")
                    
                    if broadcasts:
                        # target_xcode가 있으면 해당 xcode 매칭 우선
                        if target_xcode:
                            for bc in broadcasts:
                                bc_xcode = str(bc.get('xcode', '')).strip()
                                if target_xcode_norm and bc_xcode.upper() == target_xcode_norm:
                                    xcgcd = bc['xcgcd']
                                    logger.info(f"xcode={target_xcode} 매칭 성공: xcgcd={xcgcd}")
                                    break
                            # target_xcode가 있는데 매칭 실패하면 xcgcd를 설정하지 않음
                            if not xcgcd:
                                logger.warning(f"xcode={target_xcode}에 해당하는 생중계를 찾지 못함")
                        else:
                            # target_xcode가 없는 경우(본회의 등)에만 첫 번째 생중계 사용
                            xcgcd = broadcasts[0]['xcgcd']
                            first_bc = broadcasts[0]
                            logger.info(f"첫 번째 생중계 사용: xcgcd={xcgcd}, text={first_bc.get('text', '')[:30]}")
                            
                except Exception as e:
                    logger.debug(f"메인 페이지 조회 오류: {e}")
                
            # 방법 5: 메인 페이지 리다이렉트 시 화면의 '생중계' 버튼 자동 클릭 (개선됨)
            if not xcgcd and target_xcode:
                # 현재 URL이 메인 페이지인지 확인 (player.asp가 아님)
                current_url = driver.current_url
                if "/main/player.asp" not in current_url:
                    try:
                        self.message_queue.put(("status", f"🖱️ 메인 화면에서 xcode={target_xcode} 버튼 탐색 중..."))
                        logger.info(f"메인 페이지 리다이렉트 감지 - 버튼 클릭 시도 (xcode={target_xcode})")
                        
                        # 동적 콘텐츠 로딩 대기 (최대 10초) - onair 클래스가 나타날 때까지
                        try:
                            WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, ".onair"))
                            )
                        except Exception:
                            logger.debug("onair 요소 대기 타임아웃 (생중계가 없거나 로딩 지연)")

                        # 1. onair 버튼 찾기 (xcode 매칭)
                        # 다양한 선택자 시도 - 더 포괄적으로
                        selectors = [
                            f'a.onair[href*="xcode={target_xcode}"]',
                            f'a.btn[href*="xcode={target_xcode}"]', # onair 클래스가 없을 수도 있음
                            f'div.onair a[href*="xcode={target_xcode}"]',
                            f'a[href*="xcode={target_xcode}"]:has(.icon_onair)',
                            f'a[href*="xcode={target_xcode}"]', # 최후의 수단: 그냥 링크 찾기
                        ]
                        
                        btn = None
                        for sel in selectors:
                            try:
                                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                                # onair 클래스가 있는 요소 우선 선택
                                for elem in elems:
                                    if "onair" in elem.get_attribute("class") or elem.find_elements(By.CSS_SELECTOR, ".onair"):
                                        btn = elem
                                        break
                                
                                if btn: break
                                
                                # onair가 없더라도 첫 번째 요소 선택 (클릭해보는 것이 나음)
                                if elems and not btn:
                                    btn = elems[0]
                                    break
                            except:
                                pass
                        
                        if btn:
                            # 2. 스크롤하여 요소 보이게 하기
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                            time.sleep(1.0) # 스크롤 후 안정화 대기
                            
                            # 3. 클릭 (JavaScript 사용이 더 안정적)
                            driver.execute_script("arguments[0].click();", btn)
                            logger.info(f"메인 페이지에서 생중계 버튼 자동 클릭 성공: xcode={target_xcode}")
                            self.message_queue.put(("status", "✅ 생중계 버튼 자동 클릭 성공"))
                            
                            # 4. 페이지 전환 대기
                            try:
                                WebDriverWait(driver, 5).until(lambda d: "player.asp" in d.current_url)
                                # 페이지 전환 후 URL 반환
                                return driver.current_url
                            except Exception:
                                logger.warning("버튼 클릭 후 페이지 전환 타임아웃")
                        else:
                            logger.warning(f"메인 페이지에서 xcode={target_xcode} 생중계 버튼을 찾을 수 없음")
                            
                    except Exception as e:
                        logger.warning(f"생중계 버튼 클릭 로직 실패: {e}")
                    finally:
                        # 버튼 클릭도 실패한 경우 원래 URL로 복귀
                        # 단, 버튼 클릭으로 페이지가 이동했다면 복귀하지 않음
                        if navigated_to_main and not xcgcd and "/main/player.asp" not in driver.current_url:
                            try:
                                # 이미 버튼 클릭 시도로 URL이 바뀌었을 수 있으므로 체크
                                if original_url not in driver.current_url:
                                    driver.get(original_url)
                                    time.sleep(2)
                                    logger.info(f"원래 URL로 복귀: {original_url}")
                            except Exception as e:
                                logger.debug(f"원래 URL 복귀 실패: {e}")
            
            # xcgcd를 찾았으면 URL 업데이트 (유효성 검증 포함)
            if xcgcd and len(xcgcd) >= 10:  # 최소 길이 검증 (유효한 xcgcd는 보통 20자 이상)
                new_url = self._set_query_param(original_url, "xcgcd", xcgcd)
                if not self._get_query_param(new_url, "xcode"):
                    inferred_xcode = target_xcode or extract_xcode_from_xcgcd(xcgcd)
                    if inferred_xcode:
                        new_url = self._set_query_param(new_url, "xcode", inferred_xcode)
                
                display_xcgcd = xcgcd[:15] + '...' if len(xcgcd) > 15 else xcgcd
                self.message_queue.put(("status", f"✅ 생중계 감지 성공! (xcgcd={display_xcgcd})"))
                logger.info(f"생중계 URL 업데이트: {new_url}")
                return new_url
            else:
                # target_xcode 정보를 포함하여 더 구체적인 메시지 표시
                target_xcode = self._get_query_param(original_url, "xcode").strip() or None
                
                if target_xcode:
                    self.message_queue.put(("status", f"⚠️ xcode={target_xcode} 위원회의 진행 중인 생중계를 찾을 수 없음"))
                    logger.warning(f"xcode={target_xcode}에 해당하는 생중계가 없음, 원래 URL 사용")
                else:
                    self.message_queue.put(("status", "⚠️ 생중계 정보를 찾을 수 없음 - 기본 URL 사용"))
                    logger.warning("생중계 xcgcd를 찾을 수 없음, 원래 URL 사용")
                return original_url
                
        except Exception as e:
            logger.error(f"생중계 감지 오류: {e}")
            self.message_queue.put(("status", f"⚠️ 생중계 감지 실패: {e}"))
            return original_url
    
    def _extraction_worker(self, url, selector, headless):
        """자막 추출 워커 스레드
        
        Args:
            url: 대상 웹사이트 URL
            selector: 자막 요소 CSS 선택자
            headless: 헤드리스 모드 여부 (시작 시점에 복사됨)
        """
        driver = None
        
        try:
            options = Options()
            options.add_argument("--log-level=3")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            # 헤드리스 모드
            if headless:
                options.add_argument("--headless=new")
                options.add_argument("--window-size=1280,720")
                options.add_argument("--disable-gpu")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--disable-setuid-sandbox")
                options.add_argument("--remote-debugging-port=0")  # 동적 포트 할당 (다중 인스턴스 충돌 방지)
                options.add_argument("--enable-javascript")
                self.message_queue.put(("status", "헤드리스 모드로 시작 중..."))
            
            # WebDriver 초기화 재시도 (최대 3회)
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    driver = webdriver.Chrome(options=options)
                    self.driver = driver
                    self.message_queue.put(("status", "Chrome 시작 완료"))
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        self.message_queue.put(("status", f"Chrome 시작 재시도 ({attempt+2}/{max_retries})..."))
                        time.sleep(2)
                    else:
                        self.message_queue.put(("error", f"Chrome 오류 ({max_retries}회 시도 실패): {e}"))
                        return
            
            self.message_queue.put(("status", "페이지 로딩 중..."))
            target_xcode = self._get_query_param(url, "xcode").strip()
            target_xcgcd = self._get_query_param(url, "xcgcd").strip()
            
            # ========== 새로운 접근 방식 ==========
            # 국회 의사중계 시스템은 직접 URL 접속 시 메인 페이지로 리다이렉트됨
            # 따라서 항상 메인 페이지 → 생중계 버튼 클릭 방식으로 진입해야 함
            
            logger.info(f"[extraction] 추출 시작 - xcode={target_xcode}, xcgcd={target_xcgcd[:20] if target_xcgcd else 'None'}...")
            
            # 1. 먼저 메인 페이지로 이동
            main_url = "https://assembly.webcast.go.kr/main/"
            self.message_queue.put(("status", "🌐 메인 페이지 이동 중..."))
            driver.get(main_url)
            time.sleep(3)
            
            player_loaded = False
            
            # 2. xcode가 있으면 해당 생중계 버튼 클릭
            if target_xcode:
                self.message_queue.put(("status", f"🖱️ xcode={target_xcode} 생중계 버튼 찾는 중..."))
                
                try:
                    # 동적 콘텐츠 로딩 대기
                    try:
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='xcode=']"))
                        )
                    except Exception:
                        logger.debug("생중계 링크 대기 타임아웃")
                    
                    # 생중계 버튼 찾기 (다양한 선택자 시도)
                    selectors = [
                        f'a.onair[href*="xcode={target_xcode}"]',
                        f'a[href*="xcode={target_xcode}"].onair',
                        f'a[href*="xcode={target_xcode}"]',
                    ]
                    
                    btn = None
                    btn_href = ""
                    for sel in selectors:
                        try:
                            elems = driver.find_elements(By.CSS_SELECTOR, sel)
                            if not elems:
                                continue
                            # 표시되는 요소 중 플레이어 링크를 우선 선택
                            for elem in elems:
                                try:
                                    if not elem.is_displayed():
                                        continue
                                    href = elem.get_attribute("href") or ""
                                    if "player.asp" in href:
                                        btn = elem
                                        btn_href = href
                                        break
                                except StaleElementReferenceException:
                                    continue
                            # 플레이어 링크가 없으면 표시되는 첫 요소 사용
                            if not btn:
                                for elem in elems:
                                    try:
                                        if elem.is_displayed():
                                            btn = elem
                                            btn_href = elem.get_attribute("href") or ""
                                            break
                                    except StaleElementReferenceException:
                                        continue
                            # 표시 여부 판단이 불가한 경우를 대비해 첫 요소로 폴백
                            if not btn:
                                try:
                                    btn = elems[0]
                                    btn_href = btn.get_attribute("href") or ""
                                except Exception:
                                    pass
                            if btn:
                                logger.info(f"생중계 버튼 발견: {sel}")
                                break
                        except Exception:
                            pass
                    
                    if btn:
                        # 버튼 클릭
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", btn)
                        self.message_queue.put(("status", "✅ 생중계 버튼 클릭 성공"))
                        logger.info(f"생중계 버튼 클릭 완료: xcode={target_xcode}")
                        
                        # 페이지 전환 대기
                        try:
                            WebDriverWait(driver, 10).until(
                                lambda d: "player.asp" in d.current_url
                            )
                            player_loaded = True
                            logger.info(f"플레이어 페이지 로드 완료: {driver.current_url}")
                        except Exception:
                            logger.warning("플레이어 페이지 전환 타임아웃")
                        
                        # 클릭 후에도 이동 실패하면 링크 직접 접속
                        if not player_loaded and btn_href:
                            if not btn_href.startswith("http"):
                                btn_href = f"https://assembly.webcast.go.kr/{btn_href.lstrip('/')}"
                            self.message_queue.put(("status", "🔄 링크 직접 접속 시도..."))
                            driver.get(btn_href)
                            time.sleep(3)
                            if "player.asp" in driver.current_url:
                                player_loaded = True
                                logger.info(f"플레이어 페이지 직접 이동 성공: {driver.current_url}")
                    else:
                        logger.warning(f"xcode={target_xcode} 생중계 버튼을 찾을 수 없음")
                        self.message_queue.put(("status", f"⚠️ xcode={target_xcode} 버튼 없음 - 생중계 중인지 확인하세요"))
                        
                except Exception as e:
                    logger.error(f"생중계 버튼 클릭 오류: {e}")
            
            # 3. xcode가 없는 경우에만 첫 번째 생중계 시도
            #    (xcode가 지정되었는데 못 찾으면: 다른 생중계로 진입하지 않음)
            if not player_loaded and not target_xcode:
                self.message_queue.put(("status", "🔍 진행 중인 생중계 찾는 중..."))
                try:
                    # onair 클래스가 있는 생중계 버튼 클릭
                    onair_btns = driver.find_elements(By.CSS_SELECTOR, "a.onair[href*='player.asp']")
                    if onair_btns:
                        driver.execute_script("arguments[0].click();", onair_btns[0])
                        time.sleep(3)
                        if "player.asp" in driver.current_url:
                            player_loaded = True
                            logger.info(f"첫 번째 생중계로 이동: {driver.current_url}")
                except Exception as e:
                    logger.debug(f"첫 번째 생중계 시도 실패: {e}")
            
            # 4. 그래도 플레이어 로드 안되면 원래 URL 직접 시도 (최후의 수단)
            if not player_loaded and target_xcgcd:
                self.message_queue.put(("status", "🔄 직접 URL 접속 시도..."))
                driver.get(url)
                time.sleep(5)
                if "player.asp" in driver.current_url:
                    player_loaded = True
            
            # 5. xcode가 지정되었는데 실패한 경우: 사용자에게 알림 후 종료
            if not player_loaded and target_xcode:
                self.message_queue.put((
                    "error",
                    f"❌ 선택한 위원회(xcode={target_xcode})의 생중계를 찾을 수 없습니다.\n\n"
                    "가능한 원인:\n"
                    "• 해당 위원회에서 현재 진행 중인 생중계가 없음\n"
                    "• 생중계가 종료되었거나 아직 시작되지 않음\n\n"
                    "💡 해결 방법:\n"
                    "• '📡 생중계 목록' 버튼을 눌러 현재 진행 중인 방송을 확인하세요"
                ))
                return
            
            # 6. 플레이어 로드 후 추가 대기
            if player_loaded:
                time.sleep(3)  # 플레이어 안정화 대기
            else:
                time.sleep(2)

            
            self.message_queue.put(("status", "AI 자막 활성화 중..."))
            self._activate_subtitle(driver)
            
            self.message_queue.put(("status", "자막 요소 검색 중..."))
            
            # 헤드리스 모드에서는 타임아웃 증가 (JavaScript 로딩 지연 대비)
            timeout = 30 if headless else 20
            wait = WebDriverWait(driver, timeout)
            
            # _find_subtitle_selector를 활용하여 자막 요소 자동 감지
            detected_selector = self._find_subtitle_selector(driver)
            selectors_to_try = [selector, detected_selector, "#viewSubtit .incont", "#viewSubtit", ".subtitle_area"]
            # 중복 제거
            selectors_to_try = list(dict.fromkeys(selectors_to_try))
            
            found = False
            working_selector = selector  # 실제 동작하는 셀렉터 저장
            for sel in selectors_to_try:
                try:
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    self.message_queue.put(("status", f"자막 요소 찾음: {sel}"))
                    found = True
                    working_selector = sel
                    break
                except Exception:
                    continue
            
            if not found:
                # 사용자에게 직접 링크를 가져오라고 안내 (개선된 메시지)
                self.message_queue.put((
                    "subtitle_not_found",
                    "자막 요소를 찾을 수 없습니다.\n\n"
                    "❌ 가능한 원인:\n"
                    "  • 현재 진행 중인 생중계가 없음\n"
                    "  • 선택한 위원회에서 현재 회의가 없음\n"
                    "  • URL에 방송 ID(xcgcd)가 누락됨\n\n"
                    "📌 해결 방법:\n"
                    "  1. 사이트 열기 버튼을 클릭하세요\n"
                    "  2. '오늘의 생중계' 목록에서 원하는 중계를 클릭\n"
                    "  3. 브라우저 주소창의 URL을 전체 복사\n"
                    "  4. 프로그램의 URL 입력란에 붙여넣기\n\n"
                    "💡 올바른 URL 예시:\n"
                    "   https://assembly.webcast.go.kr/main/player.asp?xcode=IO&xcgcd=DCM0000IO...\n\n"
                    "ℹ️ xcgcd는 각 회의마다 고유한 방송 ID입니다."
                ))
                return
            
            # 찾은 셀렉터를 사용하여 모니터링
            selector = working_selector
            
            self.message_queue.put(("status", "자막 모니터링 중"))
            # 연결 성공 상태 전송 (#30)
            self.message_queue.put(("connection_status", {"status": "connected", "latency": 0}))
            
            last_check = time.time()
            last_ping = time.time()  # 연결 상태 체크용 (#30)
            consecutive_errors = 0  # 네트워크 오류 재연결 카운터
            empty_text_count = 0  # 빈 텍스트 연속 카운터
            max_empty_text = 30  # 30회 연속 빈 텍스트 (약 6초) 시 경고
            
            # stop_event 사용으로 더 빠른 종료 응답
            while not self.stop_event.is_set():
                try:
                    now = time.time()
                    if now - last_check >= 0.2:
                        ping_start = time.time()  # 레이턴시 측정 (#30)
                        try:
                            text = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
                            consecutive_errors = 0  # 성공 시 카운터 리셋
                            
                            # 주기적으로 연결 상태 업데이트 (#30)
                            if now - last_ping >= 5:  # 5초마다
                                latency = int((time.time() - ping_start) * 1000)
                                self.message_queue.put(("connection_status", {"status": "connected", "latency": latency}))
                                last_ping = now
                                
                        except (NoSuchElementException, StaleElementReferenceException):
                            text = ""
                        
                        text = self._clean_text(text)
                        
                        # 빈 텍스트 연속 감지 (방송 종료 또는 자막 없음)
                        if not text:
                            empty_text_count += 1
                            if empty_text_count == max_empty_text:
                                self.message_queue.put(("status", "⏸️ 자막 대기 중... (방송 확인 필요)"))
                        else:
                            empty_text_count = 0  # 리셋
                        
                        # 텍스트 정규화 비교 (공백/특수문자 차이 무시) - 성능 최적화
                        normalized_text = Config.RE_MULTI_SPACE.sub(' ', text).strip()
                        normalized_last = Config.RE_MULTI_SPACE.sub(' ', self.last_subtitle).strip() if self.last_subtitle else ""
                        
                        if text and normalized_text != normalized_last:
                            self.message_queue.put(("preview", text))
                        
                        last_check = now
                    
                    # stop_event 대기 (0.05초, 즉시 응답 가능)
                    self.stop_event.wait(timeout=0.05)
                    
                except WebDriverException as e:
                    # 네트워크/브라우저 오류 - 지수 백오프로 재연결 시도 (#31)
                    consecutive_errors += 1
                    if not self.stop_event.is_set():
                        logger.warning(f"브라우저 오류 ({consecutive_errors}/{Config.MAX_RECONNECT_ATTEMPTS}): {e}")
                        
                        # 연결 끊김 상태 전송 (#30)
                        self.message_queue.put(("connection_status", {"status": "disconnected"}))
                        
                        if consecutive_errors >= Config.MAX_RECONNECT_ATTEMPTS:
                            self.message_queue.put(("error", f"네트워크 오류로 중단됨: {consecutive_errors}회 연속 실패"))
                            break
                        
                        # 재연결 시도 알림 (#31)
                        self.message_queue.put(("reconnecting", {"attempt": consecutive_errors}))
                        
                        # 지수 백오프 대기 (#31)
                        delay = min(
                            Config.RECONNECT_BASE_DELAY * (2 ** (consecutive_errors - 1)),
                            Config.RECONNECT_MAX_DELAY
                        )
                        logger.info(f"재연결 대기: {delay}초")
                        if self.stop_event.wait(timeout=delay):
                            break  # 종료 신호 받으면 즉시 탈출
                        
                        try:
                            driver.refresh()
                            time.sleep(3)
                            self._activate_subtitle(driver)
                            # 재연결 성공 (#31)
                            self.message_queue.put(("reconnected", {}))
                            consecutive_errors = 0  # 성공 시 리셋
                        except Exception as reconnect_error:
                            logger.warning(f"재연결 실패: {reconnect_error}")
                            
                except Exception as e:
                    if not self.stop_event.is_set():
                        logger.warning(f"모니터링 중 오류: {e}")
                    time.sleep(0.5)
        
        except Exception as e:
            if not self.stop_event.is_set():
                self.message_queue.put(("error", str(e)))
        
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as e:
                    logger.debug(f"워커 WebDriver 종료 중 오류: {e}")
                self.driver = None
            self.message_queue.put(("finished", ""))
    
    def _activate_subtitle(self, driver) -> bool:
        """자막 레이어 활성화 - 다양한 방법 시도
        
        Returns:
            bool: 활성화 성공 여부
        """
        activation_scripts = [
            # 방법 1: layerSubtit 함수 호출
            "if(typeof layerSubtit==='function'){layerSubtit(); return true;} return false;",
            # 방법 2: 자막 버튼 클릭
            "var btn=document.querySelector('.btn_subtit'); if(btn){btn.click(); return true;} return false;",
            "var btn=document.querySelector('#btnSubtit'); if(btn){btn.click(); return true;} return false;",
            # 방법 3: AI 자막 버튼
            "var btn=document.querySelector('[data-action=\\'subtitle\\']'); if(btn){btn.click(); return true;} return false;",
            # 방법 4: 자막 레이어 직접 표시
            "var layer=document.querySelector('#viewSubtit'); if(layer){layer.style.display='block'; return true;} return false;",
        ]
        
        activated = False
        for script in activation_scripts:
            try:
                result = driver.execute_script(script)
                if result:
                    logger.info(f"자막 활성화 성공: {script[:50]}...")
                    activated = True
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"자막 활성화 스크립트 실패: {e}")
        
        # 추가 대기 - 자막 레이어 로딩
        time.sleep(2.0)
        
        # 활성화 검증: 자막 요소가 실제로 보이는지 확인
        try:
            elem = driver.find_element(By.CSS_SELECTOR, "#viewSubtit")
            is_visible = driver.execute_script(
                "return arguments[0].offsetParent !== null && getComputedStyle(arguments[0]).display !== 'none';",
                elem
            )
            if is_visible:
                logger.info("자막 레이어 활성화 확인됨")
                return True
            else:
                logger.warning("자막 레이어가 숨겨져 있음")
        except Exception as e:
            logger.debug(f"자막 레이어 확인 실패: {e}")
        
        return activated
    
    def _find_subtitle_selector(self, driver) -> str:
        """사용 가능한 자막 셀렉터 자동 감지
        
        Returns:
            str: 찾은 셀렉터 또는 기본 셀렉터
        """
        # 우선순위대로 셀렉터 확인
        selectors = [
            "#viewSubtit .incont",
            "#viewSubtit span",
            "#viewSubtit",
            ".subtitle_area",
            ".ai_subtitle",
            "[class*='subtitle']",
        ]
        
        for sel in selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, sel)
                for elem in elements:
                    text = elem.text.strip()
                    if text and len(text) > 2:  # 의미 있는 텍스트가 있는 경우
                        logger.info(f"자막 셀렉터 발견: {sel}")
                        return sel
            except Exception:
                continue
        
        return "#viewSubtit .incont"  # 기본값
    
    def _clean_text(self, text: str) -> str:
        """자막 텍스트 정리 (성능 최적화: 사전 컴파일된 정규식 사용)"""
        if not text:
            return ""
        # 년도 제거
        text = Config.RE_YEAR.sub('', text)
        # 특수 문자 정리 (Zero-width 문자 제거)
        text = Config.RE_ZERO_WIDTH.sub('', text)
        # 연속 공백 정리
        text = Config.RE_MULTI_SPACE.sub(' ', text)
        return text.strip()

    def _clear_message_queue(self) -> None:
        """메시지 큐 비우기 (중지/재시작 안정성용)"""
        try:
            while True:
                self.message_queue.get_nowait()
        except queue.Empty:
            pass
    
    # ========== 메시지 큐 처리 ==========
    
    def _process_message_queue(self):
        """메시지 큐 처리 (100ms마다 호출) - 예외 처리 강화"""
        try:
            # 최대 10개 메시지까지 처리 (무한 루프 방지)
            for _ in range(10):
                try:
                    msg_type, data = self.message_queue.get_nowait()
                    self._handle_message(msg_type, data)
                except queue.Empty:
                    break
        except Exception as e:
            logger.error(f"큐 처리 오류: {e}")
    
    def _handle_message(self, msg_type, data):
        """개별 메시지 처리"""
        try:
            if self._is_stopping:
                return
            if msg_type == "status":
                self.status_label.setText(str(data)[:200])

            elif msg_type == "toast":
                # 다른 스레드에서 온 UI 알림은 Queue로 전달받아 UI 스레드에서 처리한다.
                if isinstance(data, dict):
                    message = data.get("message", "")
                    toast_type = data.get("toast_type", "info")
                    duration = data.get("duration", 3000)
                else:
                    message = data
                    toast_type = "info"
                    duration = 3000
                try:
                    duration = int(duration) if duration is not None else 3000
                except Exception:
                    duration = 3000
                self._show_toast(str(message), str(toast_type), duration)
            
            elif msg_type == "preview":
                self._process_raw_text(data)
            
            elif msg_type == "error":
                self.progress.hide()
                self._reset_ui()
                QMessageBox.critical(self, "오류", str(data))
            
            elif msg_type == "finished":
                if self.last_subtitle:
                    self._finalize_subtitle(self.last_subtitle, entry_timestamp=self._pending_minute_bucket)
                    self.last_subtitle = ""
                    self._pending_minute_bucket = None
                else:
                    self._pending_minute_bucket = None
                self.finalize_timer.stop()
                
                self._refresh_text()
                self._reset_ui()
                
                # 스레드 안전하게 통계 계산
                with self.subtitle_lock:
                    subtitle_count = len(self.subtitles)
                    total_chars = sum(len(s.text) for s in self.subtitles)
                self.status_label.setText(f"완료 - {subtitle_count}문장, {total_chars:,}자")
            
            elif msg_type == "subtitle_not_found":
                # 자막 요소를 찾지 못했을 때 사용자 안내
                self.progress.hide()
                self._reset_ui()
                self._update_tray_status("⚪ 대기 중")
                
                # 상세 안내 다이얼로그
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("자막을 찾을 수 없습니다")
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setText(str(data))
                msg_box.setStandardButtons(
                    QMessageBox.StandardButton.Open | 
                    QMessageBox.StandardButton.Ok
                )
                msg_box.button(QMessageBox.StandardButton.Open).setText("🌐 사이트 열기")
                msg_box.button(QMessageBox.StandardButton.Ok).setText("확인")
                
                result = msg_box.exec()
                
                # 사이트 열기 버튼 클릭 시 브라우저에서 열기
                if result == QMessageBox.StandardButton.Open:
                    import webbrowser
                    webbrowser.open("https://assembly.webcast.go.kr")
            
            # 연결 상태 업데이트 (#30)
            elif msg_type == "connection_status":
                status = data.get("status", "disconnected")
                latency = data.get("latency")
                self._update_connection_status(status, latency)
            
            # 재연결 시도 (#31)
            elif msg_type == "reconnecting":
                self.reconnect_attempts = data.get("attempt", 0)
                self._update_connection_status("reconnecting")
                self._show_toast(f"재연결 시도 중... ({self.reconnect_attempts}/{Config.MAX_RECONNECT_ATTEMPTS})", "warning", 2000)
            
            # 재연결 성공 (#31)
            elif msg_type == "reconnected":
                self.reconnect_attempts = 0
                self._update_connection_status("connected")
                self._show_toast("재연결 성공!", "success", 2000)
        
        except Exception as e:
            logger.error(f"메시지 처리 오류 ({msg_type}): {e}")

    def _normalize_subtitle_text(self, text: str) -> str:
        """자막 비교용 정규화 (공백 정리)"""
        if not text:
            return ""
        return Config.RE_MULTI_SPACE.sub(' ', text).strip()

    def _minute_bucket(self, dt: datetime) -> datetime:
        """분 단위 버킷으로 시간 절삭"""
        return dt.replace(second=0, microsecond=0)

    def _should_merge_minute_bucket(self, last_entry: SubtitleEntry, new_text: str,
                                    bucket_time: datetime, now: datetime) -> bool:
        """같은 분 버킷에 합쳐도 되는지 판단"""
        if not last_entry or not new_text or not bucket_time:
            return False
        last_bucket = self._minute_bucket(last_entry.timestamp)
        if last_bucket != self._minute_bucket(bucket_time):
            return False
        if last_entry.end_time and (now - last_entry.end_time).total_seconds() > Config.MINUTE_BUCKET_MAX_GAP:
            return False
        if len(last_entry.text) + 1 + len(new_text) > Config.MINUTE_BUCKET_MAX_CHARS:
            return False
        return True

    def _compact_subtitle_text(self, text: str) -> str:
        """겹침/중복 판별용 정규화 (공백 제거 + zero-width 제거)"""
        if not text:
            return ""
        text = Config.RE_ZERO_WIDTH.sub('', text)
        return Config.RE_MULTI_SPACE.sub('', text).strip()

    def _slice_from_compact_index(self, text: str, compact_index: int) -> str:
        """compact 인덱스(공백 제거 기준) 위치부터 원문 슬라이스를 반환"""
        if not text:
            return ""
        if compact_index <= 0:
            return text

        text = Config.RE_ZERO_WIDTH.sub('', text)
        count = 0
        for i, ch in enumerate(text):
            if ch.isspace():
                continue
            if count >= compact_index:
                return text[i:]
            count += 1
        return ""

    def _same_leading_context(self, a: str, b: str, take: int = 20) -> bool:
        """실시간 자막이 같은 흐름인지(앞부분이 유지되는지) 공백 무시로 판별"""
        a_compact = self._compact_subtitle_text(a)
        b_compact = self._compact_subtitle_text(b)
        prefix_len = min(take, len(a_compact), len(b_compact))
        if prefix_len <= 0:
            return True
        return a_compact[:prefix_len] == b_compact[:prefix_len]

    def _is_continuation_text(self, previous: str, current: str) -> bool:
        """이전 raw 대비 현재 raw가 같은 흐름의 업데이트인지(윈도우 슬라이딩 포함) 판별"""
        prev_compact = self._compact_subtitle_text(previous)
        cur_compact = self._compact_subtitle_text(current)
        if not prev_compact or not cur_compact:
            return True

        # 포함 관계면 같은 흐름(확장/축약/공백차)
        if prev_compact in cur_compact or cur_compact in prev_compact:
            return True

        # 이전 텍스트의 최근 tail이 현재에 포함되면 같은 흐름(앞부분이 슬라이딩되어도 유지)
        tail_len = min(60, len(prev_compact))
        if tail_len >= 15 and prev_compact[-tail_len:] in cur_compact:
            return True

        # 앞부분이 유사하면 같은 흐름
        prefix_len = min(30, len(prev_compact), len(cur_compact))
        if prefix_len >= 15 and prev_compact[:prefix_len] == cur_compact[:prefix_len]:
            return True

        return False

    def _confirmed_history_compact_tail(self, max_entries: int = 10, max_compact_len: int = 3000) -> str:
        """최근 확정 자막들의 compact tail 문자열(겹침/중복 제거용)"""
        with self.subtitle_lock:
            if not self.subtitles:
                return ""
            tail_entries = self.subtitles[-max_entries:]
            combined = " ".join(e.text for e in tail_entries if e and e.text)

        compact = self._compact_subtitle_text(combined)
        if max_compact_len > 0 and len(compact) > max_compact_len:
            compact = compact[-max_compact_len:]
        return compact

    def _is_redundant_to_confirmed_history(self, raw: str) -> bool:
        """최근 확정 자막들의 tail에 포함되는(이미 확정된) 텍스트인지 확인"""
        if not raw:
            return False
        raw_compact = self._compact_subtitle_text(raw)
        if not raw_compact:
            return False
        history_tail = self._confirmed_history_compact_tail()
        return bool(history_tail) and (raw_compact in history_tail)

    def _find_compact_suffix_prefix_overlap(self, last_compact: str, text_compact: str,
                                           min_overlap: int = 10, max_overlap: int = 500) -> int:
        """last_compact의 suffix와 text_compact의 prefix가 겹치는 최대 길이(공백 무시)를 반환"""
        if not last_compact or not text_compact:
            return 0
        max_possible = min(len(last_compact), len(text_compact), max_overlap)
        for overlap_len in range(max_possible, min_overlap - 1, -1):
            if last_compact.endswith(text_compact[:overlap_len]):
                return overlap_len
        return 0

    def _is_redundant_text(self, candidate: str, last_text: str) -> bool:
        """이미 확정된 자막과 중복/포함 관계인지 판단"""
        cand_norm = self._normalize_subtitle_text(candidate)
        last_norm = self._normalize_subtitle_text(last_text)
        if not cand_norm or not last_norm:
            return False
        if cand_norm == last_norm:
            return True
        if len(cand_norm) <= len(last_norm) and cand_norm in last_norm:
            return True

        # 공백 차이(예: "국 장" vs "국장")로 인해 중복/포함 판단이 실패하는 케이스 보완
        cand_compact = self._compact_subtitle_text(candidate)
        last_compact = self._compact_subtitle_text(last_text)
        if cand_compact and last_compact:
            if cand_compact == last_compact:
                return True
            return len(cand_compact) <= len(last_compact) and cand_compact in last_compact
        return False

    def _is_redundant_to_last_confirmed(self, raw: str) -> bool:
        """마지막 확정 자막보다 진전이 없는 텍스트인지 확인"""
        if not raw:
            return False
        with self.subtitle_lock:
            if not self.subtitles:
                return False
            last_text = self.subtitles[-1].text
        return self._is_redundant_text(raw, last_text)
    
    def _process_raw_text(self, raw):
        """자막 텍스트 처리 - 텍스트 비어질 때 즉시 확정"""
        
        # 텍스트가 비어있는 경우: 이전 자막 확정
        if not raw:
            if self.last_subtitle:
                self._finalize_subtitle(self.last_subtitle, entry_timestamp=self._pending_minute_bucket)
                self.last_subtitle = ""
                self._pending_minute_bucket = None
                self.finalize_timer.stop()
                self._refresh_text()
            else:
                self._pending_minute_bucket = None
            return

        now_bucket = self._minute_bucket(datetime.now())
        if self.last_subtitle and not self._pending_minute_bucket:
            self._pending_minute_bucket = now_bucket

        # 분 경계가 넘어가면 현재 자막을 강제로 확정
        if self.last_subtitle and self._pending_minute_bucket and now_bucket != self._pending_minute_bucket:
            self._finalize_subtitle(self.last_subtitle, entry_timestamp=self._pending_minute_bucket)
            self.last_subtitle = ""
            self._pending_minute_bucket = None
            self.finalize_timer.stop()
            self._refresh_text()
        
        # 이전 자막과 같으면 무시 (공백 차이 무시)
        if self._normalize_subtitle_text(raw) == self._normalize_subtitle_text(self.last_subtitle):
            return
        
        # 완전히 다른 흐름으로 변경된 경우에만 이전 자막을 즉시 확정
        # (윈도우 슬라이딩/공백 변화로 인한 조기 확정 남발 방지)
        if self.last_subtitle and not self._is_continuation_text(self.last_subtitle, raw):
            # 이전 자막 확정
            self._finalize_subtitle(self.last_subtitle, entry_timestamp=self._pending_minute_bucket)
            self._refresh_text()

        if self._is_redundant_to_confirmed_history(raw) or self._is_redundant_to_last_confirmed(raw):
            self.last_subtitle = ""
            self._pending_minute_bucket = None
            self.finalize_timer.stop()
            return
        
        # 시간 기반 확정: 자막이 변경될 때마다 시간 기록
        # 2초 동안 변경 없으면 확정
        self.last_update_time = time.time()
        self.last_subtitle = raw
        self._pending_minute_bucket = now_bucket
        
        # 확정 타이머 시작 (아직 안돌고 있으면)
        if not self.finalize_timer.isActive():
            self.finalize_timer.start(Config.FINALIZE_CHECK_INTERVAL)
        
        # 화면에는 현재 자막만 표시 (누적 없음, 미리보기만)
        self._update_preview(raw)
    
    def _check_finalize(self):
        """2초 동안 변경 없으면 현재 자막 확정"""
        if not self.last_subtitle:
            return

        now_dt = datetime.now()
        if self._pending_minute_bucket:
            now_bucket = self._minute_bucket(now_dt)
            if now_bucket != self._pending_minute_bucket:
                self._finalize_subtitle(self.last_subtitle, entry_timestamp=self._pending_minute_bucket)
                self.last_subtitle = ""
                self._pending_minute_bucket = None
                self.finalize_timer.stop()
                self._refresh_text()
                return
        
        elapsed = time.time() - self.last_update_time
        if elapsed >= Config.SUBTITLE_FINALIZE_DELAY:  # 2초 동안 변경 없음
            self._finalize_subtitle(self.last_subtitle, entry_timestamp=self._pending_minute_bucket)
            self.last_subtitle = ""
            self._pending_minute_bucket = None
            self.finalize_timer.stop()
            self._refresh_text()
    
    def _update_preview(self, raw: str) -> None:
        """미리보기 업데이트 - 확정 자막 + 현재 자막 모두 표시"""
        self._render_subtitles(current_raw=raw)
    
    def _render_subtitles(self, current_raw: str = None) -> None:
        """자막 렌더링 공통 메소드 (성능 최적화: 증분 렌더링 및 캐시된 포맷 사용)
        
        Args:
            current_raw: 현재 진행 중인 자막 (None이면 확정 자막만 표시)
        """
        scrollbar = self.subtitle_text.verticalScrollBar()
        preserve_scroll = self._user_scrolled_up and scrollbar is not None
        saved_scroll = None
        if preserve_scroll:
            saved_scroll = scrollbar.value()
            scrollbar.blockSignals(True)

        # 증분 렌더링을 위한 상태 추적
        if not hasattr(self, '_last_rendered_count'):
            self._last_rendered_count = 0
            
        # 자막이 줄었거나 초기화된 경우 전체 렌더링
        if len(self.subtitles) < self._last_rendered_count:
            self.subtitle_text.clear()
            self._last_rendered_count = 0
            
        cursor = self.subtitle_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        # 마지막 렌더링 이후에 추가된 자막만 처리
        # (단, 텍스트가 모두 지워진 상태라면 처음부터 렌더링)
        if self._last_rendered_count == 0:
            self.subtitle_text.clear()
            cursor = self.subtitle_text.textCursor()
            
        show_ts = self.timestamp_action.isChecked()
        
        # 확정된 자막들 표시 (스레드 안전하게 복사하여 순회)
        with self.subtitle_lock:
            total_count = len(self.subtitles)
            # 새로 추가된 자막들만 슬라이싱
            new_entries = self.subtitles[self._last_rendered_count:] if self._last_rendered_count < total_count else []
            # 렌더링 카운트 업데이트
            self._last_rendered_count = total_count
            
        for i, entry in enumerate(new_entries):
            # 첫 번째 자막이 아니면 줄바꿈 추가
            # (전체 자막 기준 인덱스: self._last_rendered_count - len(new_entries) + i)
            global_idx = self._last_rendered_count - len(new_entries) + i
            if global_idx > 0:
                cursor.insertText("\n\n")
            
            # 타임스탬프 (캐시된 포맷 사용)
            if show_ts:
                cursor.insertText(f"[{entry.timestamp.strftime('%H:%M:%S')}] ", self._timestamp_fmt)
            
            # 텍스트 (키워드 하이라이트)
            self._insert_highlighted_text(cursor, entry.text)
        
        # 현재 진행 중인 자막 (preview) 처리
        # preview는 항상 갱신되어야 하므로, 이전 preview를 지우는 로직이 필요하거나
        # 별도의 preview 영역을 사용하는 것이 좋지만, 현재 구조상 텍스트 에디터에 추가함.
        # 기존: clear() 후 전체 다시 씀 -> 변경: 확정 자막은 유지, preview만 갱신 불가능하므로
        # preview가 있을 때는 어쩔 수 없이 임시로 전체 렌더링을 하거나, preview 영역을 분리해야 함.
        # 하지만 현재 구조 유지를 위해, preview가 있을 때는 증분 렌더링을 포기하거나 
        # preview 업데이트 방식을 개선해야 함.
        
        # 해결책: preview가 있는 경우, 일단 렌더링된 확정 자막 뒤에 preview를 붙였다가,
        # 다음 확정 시에는 그 preview를 지우고 확정 자막을 쓰는 방식이 필요함.
        # 하지만 QTextEdit 수정이 복잡하므로, preview가 없을 때만 증분 렌더링을 적용하고,
        # preview가 있으면 (드물게 발생) 전체 렌더링을 하거나, 
        # 혹은 preview 갱신 시에는 전체 렌더링을 하도록 둠.
        
        # 여기서는 preview가 있는 경우(current_raw is not None) 기존 방식을 유지하고,
        # preview가 없는 경우(확정 시) 증분 렌더링을 적용.
        
        if current_raw:
             # preview 모드: 전체 다시 그리기 (기존 방식)
            self.subtitle_text.clear()
            cursor = self.subtitle_text.textCursor()
            self._last_rendered_count = 0 # 리셋
            
            with self.subtitle_lock:
                subtitles_copy = list(self.subtitles)
            
            for i, entry in enumerate(subtitles_copy):
                if i > 0:
                    cursor.insertText("\n\n")
                if show_ts:
                    cursor.insertText(f"[{entry.timestamp.strftime('%H:%M:%S')}] ", self._timestamp_fmt)
                self._insert_highlighted_text(cursor, entry.text)
            
            if subtitles_copy:
                cursor.insertText("\n\n")
            cursor.insertText("⏳ ", self._preview_fmt)
            cursor.insertText(current_raw)
            
            # 렌더링 상태 업데이트 (다음 확정 시 증분 렌더링을 위해 현재 상태 저장)
            self._last_rendered_count = len(subtitles_copy)
        
        # 스마트 스크롤: 자동 스크롤 체크 + 사용자가 위로 스크롤하지 않은 경우에만
        if self.auto_scroll_check.isChecked() and not self._user_scrolled_up:
            self.subtitle_text.moveCursor(QTextCursor.MoveOperation.End)

        if preserve_scroll:
            scrollbar.setValue(min(saved_scroll, scrollbar.maximum()))
            scrollbar.blockSignals(False)
    
    def _on_scroll_changed(self) -> None:
        """스크롤바 위치 변경 감지 - 스마트 스크롤용"""
        scrollbar = self.subtitle_text.verticalScrollBar()
        # 스크롤이 맨 아래에서 일정 거리 이내면 자동 스크롤 활성화
        threshold = 50  # 픽셀 단위 허용치
        at_bottom = scrollbar.value() >= scrollbar.maximum() - threshold
        
        if at_bottom:
            self._user_scrolled_up = False
            if hasattr(self, 'scroll_to_bottom_btn'):
                self.scroll_to_bottom_btn.hide()
        else:
            # 사용자가 위로 스크롤한 경우
            self._user_scrolled_up = True
            # 추출 중일 때만 버튼 표시
            if self.is_running and hasattr(self, 'scroll_to_bottom_btn'):
                self.scroll_to_bottom_btn.show()
    
    def _scroll_to_bottom(self) -> None:
        """맨 아래로 스크롤하고 자동 스크롤 재개"""
        self._user_scrolled_up = False
        self.subtitle_text.moveCursor(QTextCursor.MoveOperation.End)
        if hasattr(self, 'scroll_to_bottom_btn'):
            self.scroll_to_bottom_btn.hide()
    
    def _toggle_stats_panel(self) -> None:
        """통계 패널 숨기기/보이기"""
        if hasattr(self, 'stats_group') and hasattr(self, 'toggle_stats_btn'):
            is_visible = self.stats_group.isVisible()
            self.stats_group.setVisible(not is_visible)
            
            if is_visible:
                self.toggle_stats_btn.setText("📊 통계 보이기")
                # 자막 영역이 전체 너비를 사용하도록
                self.main_splitter.setSizes([1080, 0])
            else:
                self.toggle_stats_btn.setText("📊 통계 숨기기")
                self.main_splitter.setSizes([860, 220])
    
    def _refresh_text(self) -> None:
        """확정된 자막만 표시 (진행 중인 자막 없음)"""
        self._render_subtitles(current_raw=None)


    
    def _finalize_subtitle(self, text: str, entry_timestamp: datetime = None) -> None:
        """자막 확정 - 이전 확정 자막과 겹치는 부분 제거 후 이어붙이기
        
        성능 최적화: 통계 캐시 갱신
        """
        if not text:
            return
        
        now_dt = datetime.now()
        bucket_time = self._minute_bucket(entry_timestamp or now_dt)
        entry = None
        finalized_text = None
        with self.subtitle_lock:
            text_compact = self._compact_subtitle_text(text)
            if not text_compact:
                return

            # "확정 후 다음 자막" 방식: 최근 확정 히스토리(tail)와 겹치는 부분은 제거하고,
            # 새로 추가된 부분만 새로운 SubtitleEntry로 추가
            tail_entries = self.subtitles[-10:] if self.subtitles else []
            history_joined = " ".join(e.text for e in tail_entries if e and e.text)
            history_tail = self._compact_subtitle_text(history_joined)
            if len(history_tail) > 3000:
                history_tail = history_tail[-3000:]
            if history_tail and (text_compact in history_tail):
                return

            overlap_len = self._find_compact_suffix_prefix_overlap(history_tail, text_compact, max_overlap=1200)
            new_part = self._slice_from_compact_index(text, overlap_len).strip()
            if not new_part:
                return

            # 안전장치: 델타가 여전히 최근 확정 히스토리에 포함되면 추가하지 않음
            new_part_compact = self._compact_subtitle_text(new_part)
            if history_tail and new_part_compact and (new_part_compact in history_tail):
                return

            last_entry = self.subtitles[-1] if self.subtitles else None
            if self._should_merge_minute_bucket(last_entry, new_part, bucket_time, now_dt):
                old_chars = last_entry.char_count
                old_words = last_entry.word_count
                separator = " " if last_entry.text and not last_entry.text.endswith((" ", "\n")) else ""
                last_entry.update_text(f"{last_entry.text}{separator}{new_part}")
                if last_entry.timestamp != bucket_time:
                    last_entry.timestamp = bucket_time
                last_entry.end_time = now_dt
                entry = last_entry
                finalized_text = new_part
                self._cached_total_chars += (last_entry.char_count - old_chars)
                self._cached_total_words += (last_entry.word_count - old_words)
            else:
                entry = SubtitleEntry(new_part, timestamp=bucket_time)
                entry.start_time = now_dt
                entry.end_time = now_dt
                
                self.subtitles.append(entry)
                finalized_text = entry.text
                
                # 통계 캐시 갱신 (새 자막 추가)
                self._cached_total_chars += entry.char_count
                self._cached_total_words += entry.word_count
        
        # 키워드 알림 확인 (lock 외부)
        if finalized_text:
            self._check_keyword_alert(finalized_text)
        
        # 카운트 라벨 업데이트
        self._update_count_label()
        
        # 실시간 저장
        if self.realtime_file:
            try:
                if entry and finalized_text:
                    timestamp = entry.timestamp.strftime('%H:%M:%S')
                    self.realtime_file.write(f"[{timestamp}] {finalized_text}\n")
                    self.realtime_file.flush()
            except IOError as e:
                logger.warning(f"실시간 저장 쓰기 오류: {e}")
        
        self._refresh_text()

    
    def _insert_highlighted_text(self, cursor, text):
        """텍스트에서 키워드만 하이라이트 (성능 최적화: 캐시된 패턴/포맷 사용)"""
        # 키워드 캐시가 비어있으면 일반 텍스트로 삽입
        if not self._keyword_pattern:
            cursor.insertText(text, self._normal_fmt)
            return
        
        # 캐시된 패턴으로 분할
        parts = self._keyword_pattern.split(text)
        
        for part in parts:
            if not part:  # 빈 문자열 건너뛰기
                continue
            
            if part.lower() in self._keywords_lower_set:
                # 키워드: 캐시된 하이라이트 포맷 사용
                cursor.insertText(part, self._highlight_fmt)
            else:
                # 일반 텍스트: 캐시된 일반 포맷 사용
                cursor.insertText(part, self._normal_fmt)
    
    def _update_keyword_cache(self):
        """키워드 패턴 캐시 업데이트 (디바운싱 적용)"""
        # 디바운싱: 이전 타이머 취소
        if hasattr(self, '_keyword_debounce_timer') and self._keyword_debounce_timer.isActive():
            self._keyword_debounce_timer.stop()
            
        # 실제 업데이트 로직
        def do_update():
            self._perform_keyword_cache_update()
            
        # 300ms 후 실행
        self._keyword_debounce_timer = QTimer()
        self._keyword_debounce_timer.setSingleShot(True)
        self._keyword_debounce_timer.timeout.connect(do_update)
        self._keyword_debounce_timer.start(300)

    def _perform_keyword_cache_update(self):
        """실제 키워드 캐시 업데이트 로직"""
        try:
            keywords = [k.strip() for k in self.keyword_input.text().split(',') if k.strip()]
            if not keywords:
                self._keyword_patterns = []
                self.settings.setValue("keywords", "")
                return

            patterns = []
            for k in keywords:
                try:
                    patterns.append(re.compile(re.escape(k), re.IGNORECASE))
                except re.error:
                    pass
            self._keyword_patterns = patterns
            self.settings.setValue("keywords", ",".join(keywords))
            
            # 키워드 변경 시 전체 다시 렌더링
            self._last_rendered_count = 0 
            self._render_subtitles()
        except Exception as e:
            logger.error(f"키워드 캐시 업데이트 오류: {e}")
    
    # ========== 퀵 액션 ==========
    
    def _copy_to_clipboard(self) -> None:
        """자막 전체를 클립보드에 복사"""
        with self.subtitle_lock:
            if not self.subtitles:
                self._show_toast("복사할 자막이 없습니다", "warning")
                return
            
            text = "\n".join(s.text for s in self.subtitles)
        
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self._show_toast(f"📋 {len(self.subtitles)}개 자막 복사됨", "success")
    
    def _clear_subtitles(self) -> None:
        """자막 목록 초기화"""
        with self.subtitle_lock:
            if not self.subtitles:
                self._show_toast("지울 자막이 없습니다", "warning")
                return
            
            count = len(self.subtitles)
            
            # 확인 다이얼로그
            reply = QMessageBox.question(
                self, "자막 지우기",
                f"현재 {count}개의 자막을 모두 지우시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            self.subtitles.clear()
            self._cached_total_chars = 0
            self._cached_total_words = 0
        
        self._refresh_text()
        self._update_count_label()
        self._show_toast(f"🗑️ {count}개 자막 삭제됨", "success")
    
    def _toggle_theme_from_button(self) -> None:
        """툴바 버튼에서 테마 전환"""
        self._toggle_theme()
        # 버튼 아이콘 업데이트
        if hasattr(self, 'theme_toggle_btn'):
            self.theme_toggle_btn.setText("🌙" if self.is_dark_theme else "☀️")
    
    # ========== 통계 ==========
    
    def _update_stats(self):
        """통계 업데이트 (성능 최적화: 캐시된 통계 사용)"""
        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            h, r = divmod(elapsed, 3600)
            m, s = divmod(r, 60)
            self.stat_time.setText(f"⏱️ 실행 시간: {h:02d}:{m:02d}:{s:02d}")
            
            # 캐시된 통계 사용 (스레드 안전)
            with self.subtitle_lock:
                subtitle_count = len(self.subtitles)
            
            # 캐시된 값 직접 사용 (매번 재계산 대신)
            total_chars = self._cached_total_chars
            total_words = self._cached_total_words
            
            self.stat_chars.setText(f"📝 글자 수: {total_chars:,}")
            self.stat_words.setText(f"📖 단어 수: {total_words:,}")
            self.stat_sents.setText(f"💬 문장 수: {subtitle_count}")
            
            if elapsed > 0:
                cpm = int(total_chars / (elapsed / 60))
                self.stat_cpm.setText(f"⚡ 분당 글자: {cpm}")
    
    # ========== 검색 ==========
    
    def _show_search(self):
        self.search_frame.show()
        self.search_input.setFocus()
        self.search_input.selectAll()
    
    def _hide_search(self):
        self.search_frame.hide()
        self._refresh_text()
    
    def _do_search(self):
        query = self.search_input.text()
        if not query:
            return
        
        text = self.subtitle_text.toPlainText()
        self.search_matches = []
        
        start = 0
        while True:
            idx = text.lower().find(query.lower(), start)
            if idx == -1:
                break
            self.search_matches.append(idx)
            start = idx + 1
        
        self.search_idx = 0
        self.search_count.setText(f"{len(self.search_matches)}개")
        
        if self.search_matches:
            self._highlight_search(0)
    
    def _nav_search(self, delta):
        if not self.search_matches:
            return
        
        self.search_idx = (self.search_idx + delta) % len(self.search_matches)
        self._highlight_search(self.search_idx)
    
    def _highlight_search(self, idx):
        if not self.search_matches:
            return
        
        pos = self.search_matches[idx]
        query = self.search_input.text()
        
        cursor = self.subtitle_text.textCursor()
        cursor.setPosition(pos)
        cursor.setPosition(pos + len(query), QTextCursor.MoveMode.KeepAnchor)
        
        self.subtitle_text.setTextCursor(cursor)
        self.subtitle_text.ensureCursorVisible()
        
        self.search_count.setText(f"{idx + 1}/{len(self.search_matches)}")
    
    # ========== 키워드 ==========
    
    def _set_keywords(self):
        """하이라이트 키워드 설정"""
        current = ", ".join(self.keywords)
        text, ok = QInputDialog.getText(
            self, "하이라이트 키워드 설정",
            "하이라이트할 키워드 (쉼표로 구분):",
            text=current
        )
        
        if ok:
            self.keywords = [k.strip() for k in text.split(",") if k.strip()]
            # 설정 저장
            self.settings.setValue("highlight_keywords", ", ".join(self.keywords))
            # 성능 최적화: 키워드 캐시 업데이트
            self._update_keyword_cache()
            self._refresh_text()
            self._show_toast(f"하이라이트 키워드 {len(self.keywords)}개 설정됨", "success")
    
    def _set_alert_keywords(self):
        """알림 키워드 설정 - 해당 키워드 감지 시 토스트 알림"""
        current = ", ".join(self.alert_keywords)
        text, ok = QInputDialog.getText(
            self, "알림 키워드 설정",
            "알림을 받을 키워드 (쉼표로 구분):\n예: 법안, 의결, 통과",
            text=current
        )
        
        if ok:
            self.alert_keywords = [k.strip() for k in text.split(",") if k.strip()]
            # 설정 저장
            self.settings.setValue("alert_keywords", ", ".join(self.alert_keywords))
            self._show_toast(f"알림 키워드 {len(self.alert_keywords)}개 설정됨", "success")
    
    def _check_keyword_alert(self, text: str):
        """키워드 포함 시 알림 표시"""
        if not self.alert_keywords:
            return
        
        for keyword in self.alert_keywords:
            if keyword and keyword.lower() in text.lower():
                self._show_toast(f"🔔 키워드 감지: {keyword}", "warning", 5000)
                break  # 한 번만 알림
    
    # ========== 자동 백업 ==========
    
    def _auto_backup(self):
        """자동 백업 실행"""
        if not self.subtitles:
            return

        # UI 스레드가 멈추지 않도록(긴 세션/대용량) 파일 I/O는 백그라운드에서 처리
        if not self._auto_backup_lock.acquire(blocking=False):
            return  # 이미 백업 중

        try:
            backup_dir = Path(Config.BACKUP_DIR)
            backup_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = backup_dir / f"backup_{timestamp}.json"

            # 스레드 안전하게 자막 스냅샷 생성 (UI 스레드)
            with self.subtitle_lock:
                subtitles_copy = [s.to_dict() for s in self.subtitles]

            data = {
                'version': Config.VERSION,
                'created': datetime.now().isoformat(),
                'url': self._get_current_url(),
                'subtitles': subtitles_copy
            }

        except Exception as e:
            try:
                self._auto_backup_lock.release()
            except Exception:
                pass
            logger.error(f"자동 백업 준비 오류: {e}")
            return

        def write_backup():
            try:
                with open(backup_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                # 오래된 백업 삭제 (최대 개수 유지)
                self._cleanup_old_backups()

                logger.info(f"자동 백업 완료: {backup_file}")
            except Exception as e:
                logger.error(f"자동 백업 오류: {e}")
            finally:
                try:
                    self._auto_backup_lock.release()
                except Exception:
                    pass

        threading.Thread(target=write_backup, daemon=True).start()
    
    def _cleanup_old_backups(self):
        """오래된 백업 파일 정리"""
        try:
            backup_dir = Path(Config.BACKUP_DIR)
            backups = sorted(backup_dir.glob("backup_*.json"), reverse=True)
            
            # 최대 개수 초과분 삭제
            for old_backup in backups[Config.MAX_BACKUP_COUNT:]:
                old_backup.unlink()
                logger.debug(f"오래된 백업 삭제: {old_backup}")
        except Exception as e:
            logger.warning(f"백업 정리 중 오류: {e}")
    
    # ========== 파일 저장 ==========
    
    def _save_in_background(self, save_func, path: str, success_msg: str, error_prefix: str):
        """백그라운드에서 파일 저장 (자막 수집 중단 없이)
        
        Args:
            save_func: 실제 저장을 수행하는 함수 (path를 인자로 받음)
            path: 저장할 파일 경로
            success_msg: 성공 시 토스트 메시지
            error_prefix: 실패 시 에러 메시지 접두어
        """
        def background_save():
            try:
                save_func(path)
                # UI 스레드로 안전하게 전달 (Queue 기반)
                self.message_queue.put(("toast", {"message": success_msg, "toast_type": "success"}))
            except Exception as e:
                logger.error(f"{error_prefix}: {e}")
                self.message_queue.put((
                    "toast",
                    {"message": f"{error_prefix}: {e}", "toast_type": "error", "duration": 5000}
                ))
        
        # 백그라운드 스레드에서 저장 실행
        save_thread = threading.Thread(target=background_save, daemon=True)
        save_thread.start()
        
        # 저장 시작 알림 (즉시)
        self._show_toast(f"💾 저장 중... ({Path(path).name})", "info", 1500)
    
    def _get_accumulated_text(self):
        with self.subtitle_lock:
            return "\n".join(s.text for s in self.subtitles)
    
    def _export_stats(self):
        """자막 통계 내보내기"""
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "내보낼 내용이 없습니다.")
            return
        
        # 스레드 안전하게 자막 스냅샷 생성
        with self.subtitle_lock:
            subtitles_snapshot = list(self.subtitles)
        
        # 통계 계산
        total_chars = sum(len(s.text) for s in subtitles_snapshot)
        total_words = sum(len(s.text.split()) for s in subtitles_snapshot)
        
        # 시간대별 통계
        hour_counts = {}
        for entry in subtitles_snapshot:
            hour = entry.timestamp.hour
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
        
        # 가장 긴/짧은 문장
        longest = max(subtitles_snapshot, key=lambda s: len(s.text))
        shortest = min(subtitles_snapshot, key=lambda s: len(s.text))
        
        # 파일 저장
        filename = f"자막통계_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "통계 내보내기", filename, "텍스트 (*.txt)")
        
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write("=" * 50 + "\n")
                    f.write("        🏛️ 국회 자막 통계 보고서\n")
                    f.write("=" * 50 + "\n\n")
                    
                    f.write(f"생성 일시: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')}\n\n")
                    
                    f.write("📊 기본 통계\n")
                    f.write("-" * 30 + "\n")
                    f.write(f"  총 문장 수: {len(subtitles_snapshot):,}개\n")
                    f.write(f"  총 글자 수: {total_chars:,}자\n")
                    f.write(f"  총 단어 수: {total_words:,}개\n")
                    f.write(f"  평균 문장 길이: {total_chars/len(subtitles_snapshot):.1f}자\n")
                    f.write(f"  평균 단어 수: {total_words/len(subtitles_snapshot):.1f}개\n\n")
                    
                    f.write("📏 문장 분석\n")
                    f.write("-" * 30 + "\n")
                    f.write(f"  가장 긴 문장: {len(longest.text)}자\n")
                    f.write(f"    \"{longest.text[:50]}{'...' if len(longest.text) > 50 else ''}\"\n")
                    f.write(f"  가장 짧은 문장: {len(shortest.text)}자\n")
                    f.write(f"    \"{shortest.text}\"\n\n")
                    
                    if hour_counts:
                        f.write("⏰ 시간대별 분포\n")
                        f.write("-" * 30 + "\n")
                        for h in sorted(hour_counts.keys()):
                            bar = "█" * min(hour_counts[h] // 2, 20)
                            f.write(f"  {h:02d}시: {bar} {hour_counts[h]}개\n")
                        f.write("\n")
                    
                    # 하이라이트 키워드 통계
                    if self.keywords:
                        f.write("🔍 키워드 빈도\n")
                        f.write("-" * 30 + "\n")
                        all_text = " ".join(s.text for s in subtitles_snapshot).lower()
                        for kw in self.keywords:
                            count = all_text.count(kw.lower())
                            if count > 0:
                                f.write(f"  {kw}: {count}회\n")
                        f.write("\n")
                    
                    f.write("=" * 50 + "\n")
                
                self._show_toast("통계 내보내기 완료!", "success")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"통계 저장 실패: {e}")
    
    def _generate_smart_filename(self, extension: str) -> str:
        """URL과 현재 시간 기반 스마트 파일명 생성 (#28)
        
        Args:
            extension: 파일 확장자 (txt, srt, vtt 등)
            
        Returns:
            str: "20260122_법제사법위원회_134500.txt" 형태의 파일명
        """
        now = datetime.now()
        date_str = now.strftime(Config.FILENAME_DATE_FORMAT)
        time_str = now.strftime(Config.FILENAME_TIME_FORMAT)
        
        # 위원회명 추출 (현재 URL에서 자동 감지)
        current_url = self._get_current_url()
        committee_name = self._autodetect_tag(current_url)
        
        # 위원회명이 없으면 기본값 사용
        if not committee_name:
            committee_name = "국회자막"
        
        # 파일명에 사용할 수 없는 문자 제거
        safe_committee = re.sub(r'[\\/*?:"<>|]', '', committee_name)
        
        # 템플릿 기반 파일명 생성
        filename = Config.DEFAULT_FILENAME_TEMPLATE.format(
            date=date_str,
            committee=safe_committee,
            time=time_str
        )
        
        return f"{filename}.{extension}"

    def _save_txt(self):
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return
        
        filename = self._generate_smart_filename("txt")
        path, _ = QFileDialog.getSaveFileName(self, "TXT 저장", filename, "텍스트 (*.txt)")
        
        if path:
            # 스레드 안전하게 자막 스냅샷 생성 (UI 스레드에서)
            with self.subtitle_lock:
                subtitles_snapshot = list(self.subtitles)
            
            # 실제 저장 함수 정의
            def do_save(filepath):
                with open(filepath, 'w', encoding='utf-8') as f:
                    for entry in subtitles_snapshot:
                        f.write(f"[{entry.timestamp.strftime('%H:%M:%S')}] {entry.text}\n")
            
            # 백그라운드에서 저장 실행
            self._save_in_background(do_save, path, "TXT 저장 완료!", "TXT 저장 실패")
    
    def _save_srt(self):
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return
        
        filename = self._generate_smart_filename("srt")
        path, _ = QFileDialog.getSaveFileName(self, "SRT 저장", filename, "SubRip (*.srt)")
        
        if path:
            # 스레드 안전하게 자막 스냅샷 생성 (UI 스레드에서)
            with self.subtitle_lock:
                subtitles_snapshot = list(self.subtitles)
            
            def do_save(filepath):
                with open(filepath, 'w', encoding='utf-8') as f:
                    for i, entry in enumerate(subtitles_snapshot, 1):
                        if entry.start_time and entry.end_time:
                            start = entry.start_time.strftime('%H:%M:%S,000')
                            end = entry.end_time.strftime('%H:%M:%S,000')
                        else:
                            start = entry.timestamp.strftime('%H:%M:%S,000')
                            end_time = entry.timestamp + timedelta(seconds=3)
                            end = end_time.strftime('%H:%M:%S,000')
                        f.write(f"{i}\n{start} --> {end}\n{entry.text}\n\n")
            
            self._save_in_background(do_save, path, "SRT 저장 완료!", "SRT 저장 실패")
    
    def _save_vtt(self):
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return
        
        filename = self._generate_smart_filename("vtt")
        path, _ = QFileDialog.getSaveFileName(self, "VTT 저장", filename, "WebVTT (*.vtt)")
        
        if path:
            with self.subtitle_lock:
                subtitles_snapshot = list(self.subtitles)
            
            def do_save(filepath):
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write("WEBVTT\n\n")
                    for i, entry in enumerate(subtitles_snapshot, 1):
                        if entry.start_time and entry.end_time:
                            start = entry.start_time.strftime('%H:%M:%S.000')
                            end = entry.end_time.strftime('%H:%M:%S.000')
                        else:
                            start = entry.timestamp.strftime('%H:%M:%S.000')
                            end_time = entry.timestamp + timedelta(seconds=3)
                            end = end_time.strftime('%H:%M:%S.000')
                        f.write(f"{i}\n{start} --> {end}\n{entry.text}\n\n")
            
            self._save_in_background(do_save, path, "VTT 저장 완료!", "VTT 저장 실패")
    
    def _save_docx(self):
        """DOCX (Word) 파일로 저장"""
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return
        
        try:
            from docx import Document
            from docx.shared import Pt, Inches
            from docx.enum.text import WD_ALIGN_PARAGRAPH
        except ImportError:
            QMessageBox.warning(
                self, "라이브러리 필요",
                "DOCX 저장을 위해 python-docx 라이브러리가 필요합니다.\n\n"
                "설치: pip install python-docx"
            )
            return
        
        filename = self._generate_smart_filename("docx")
        path, _ = QFileDialog.getSaveFileName(self, "DOCX 저장", filename, "Word 문서 (*.docx)")
        
        if path:
            try:
                doc = Document()
                
                # 제목
                title = doc.add_heading("국회 의사중계 자막", 0)
                title.alignment = WD_ALIGN_PARAGRAPH.CENTER
                
                # 생성 일시
                doc.add_paragraph(f"생성 일시: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')}")
                doc.add_paragraph()
                
                # 스레드 안전하게 자막 스냅샷 생성
                with self.subtitle_lock:
                    subtitles_snapshot = list(self.subtitles)
                
                # 자막 내용
                for entry in subtitles_snapshot:
                    timestamp = entry.timestamp.strftime('%H:%M:%S')
                    p = doc.add_paragraph()
                    run = p.add_run(f"[{timestamp}] ")
                    run.font.size = Pt(9)
                    run.font.color.rgb = None  # 기본 색상
                    p.add_run(entry.text)
                
                # 통계
                doc.add_paragraph()
                total_chars = sum(len(s.text) for s in subtitles_snapshot)
                doc.add_paragraph(f"총 {len(subtitles_snapshot)}문장, {total_chars:,}자")
                
                doc.save(path)
                QMessageBox.information(self, "성공", f"DOCX 저장 완료!\n\n파일: {path}")
            
            except Exception as e:
                QMessageBox.critical(self, "오류", f"DOCX 저장 실패: {e}")
    
    def _save_hwp(self):
        """HWP 파일로 저장 (Hancom Office 필요)"""
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return
        
        try:
            import win32com.client
        except ImportError:
            QMessageBox.warning(
                self, "라이브러리 필요",
                "HWP 저장을 위해 pywin32 라이브러리가 필요합니다.\n\n"
                "설치: pip install pywin32\n\n"
                "RTF 형식으로 저장을 시도합니다."
            )
            self._save_rtf()
            return
        
        hwp = None
        
        try:
            # win32com.client.dynamic.Dispatch 사용으로 캐시 문제 회피
            hwp = win32com.client.dynamic.Dispatch("HWPFrame.HwpObject")
            hwp.XHwpWindows.Item(0).Visible = True
            hwp.RegisterModule("FilePathCheckDLL", "SecurityModule")  # 보안 모듈 등록 시도
            
            # 새 문서 생성
            hwp.HAction.Run("FileNew")
            
            # 제목 입력
            hwp.HAction.Run("CharShapeBold")
            hwp.HAction.Run("ParagraphShapeAlignCenter")
            hwp.HAction.GetDefault("InsertText", hwp.HParameterSet.HInsertText.HSet)
            hwp.HParameterSet.HInsertText.Text = "국회 의사중계 자막\r\n"
            hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)
            
            hwp.HAction.Run("CharShapeBold")
            hwp.HAction.Run("ParagraphShapeAlignLeft")
            
            # 생성 일시
            hwp.HParameterSet.HInsertText.Text = f"생성 일시: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')}\r\n\r\n"
            hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)
            
            # 스레드 안전하게 자막 스냅샷 생성
            with self.subtitle_lock:
                subtitles_snapshot = list(self.subtitles)
            
            # 자막 내용
            for entry in subtitles_snapshot:
                timestamp = entry.timestamp.strftime('%H:%M:%S')
                hwp.HParameterSet.HInsertText.Text = f"[{timestamp}] {entry.text}\r\n"
                hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)
            
            # 통계
            total_chars = sum(len(s.text) for s in subtitles_snapshot)
            hwp.HParameterSet.HInsertText.Text = f"\r\n총 {len(subtitles_snapshot)}문장, {total_chars:,}자\r\n"
            hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)
            
            # 저장 대화상자
            filename = f"국회자막_{datetime.now().strftime('%Y%m%d_%H%M%S')}.hwp"
            path, _ = QFileDialog.getSaveFileName(self, "HWP 저장", filename, "HWP 문서 (*.hwp)")
            
            if path:
                # FileSaveAs_S 액션 사용
                hwp.HAction.GetDefault("FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet)
                hwp.HParameterSet.HFileOpenSave.filename = path
                hwp.HParameterSet.HFileOpenSave.Format = "HWP"
                hwp.HAction.Execute("FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet)
                
                QMessageBox.information(self, "성공", f"HWP 저장 완료!\n\n파일: {path}")
            
        except Exception as e:
            error_msg = str(e).lower()
            logger.error(f"HWP 저장 실패: {e}")
            
            # 권한 문제 힌트 제공
            if "access denied" in error_msg or "권한" in str(e):
                advice = "\n\n관리자 권한으로 실행하거나 한글 프로그램을 먼저 실행해 보세요."
            elif "server execution failed" in error_msg:
                advice = "\n\n한글 프로그램이 응답하지 않습니다. 한글을 종료하고 다시 시도하세요."
            else:
                advice = ""
                
            # 사용자에게 대체 저장 방식 제안
            reply = QMessageBox.question(
                self, "HWP 저장 실패", 
                f"한글 파일 저장 중 오류가 발생했습니다: {e}{advice}\n\n"
                "대체 형식으로 저장하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                items = ["RTF (한글 호환)", "DOCX (Word)", "TXT (텍스트)"]
                item, ok = QInputDialog.getItem(self, "형식 선택", "저장 형식:", items, 0, False)
                if ok and item:
                    if "RTF" in item:
                        self._save_rtf()
                    elif "DOCX" in item:
                        self._save_docx()
                    else:
                        self._save_txt()
            
        finally:
            if hwp:
                try:
                    hwp.Quit()
                except Exception:
                    pass
    
    def _rtf_encode(self, text: str) -> str:
        """유니코드 문자를 RTF 형식으로 인코딩 (특수문자 이스케이프)"""
        result = []
        for char in text:
            if char == '\\':
                result.append("\\\\")
            elif char == '{':
                result.append("\\{")
            elif char == '}':
                result.append("\\}")
            else:
                result.append(char)
        return ''.join(result)
    
    def _save_rtf(self):
        """RTF 파일로 저장 (HWP에서 열기 가능)"""
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return
        
        filename = self._generate_smart_filename("rtf")
        path, _ = QFileDialog.getSaveFileName(self, "RTF 저장", filename, "RTF 문서 (*.rtf)")
        
        if path:
            try:
                # 스레드 안전하게 자막 스냅샷 생성
                with self.subtitle_lock:
                    subtitles_snapshot = list(self.subtitles)
                
                with open(path, 'wb') as f:  # 바이너리 모드로 변경
                    # RTF 헤더 (유니코드 지원)
                    f.write(b"{\\rtf1\\ansi\\ansicpg949\\deff0")
                    f.write(b"{\\fonttbl{\\f0\\fnil\\fcharset129 \\'b8\\'c0\\'c0\\'ba \\'b0\\'ed\\'b5\\'f1;}}")
                    f.write(b"{\\colortbl;\\red0\\green0\\blue0;\\red128\\green128\\blue128;}")
                    f.write(b"\n")
                    
                    # 제목
                    title = self._rtf_encode("국회 의사중계 자막")
                    f.write(b"\\pard\\qc\\b\\fs28 ")
                    f.write(title.encode('cp949', errors='replace'))
                    f.write(b"\\b0\\par\n")
                    
                    # 생성 일시
                    date_str = self._rtf_encode(f"생성 일시: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')}")
                    f.write(b"\\pard\\ql\\fs20 ")
                    f.write(date_str.encode('cp949', errors='replace'))
                    f.write(b"\\par\\par\n")
                    
                    # 자막 내용
                    for entry in subtitles_snapshot:
                        timestamp = entry.timestamp.strftime('%H:%M:%S')
                        text = self._rtf_encode(entry.text)
                        f.write(b"\\cf2[")
                        f.write(timestamp.encode('cp949', errors='replace'))
                        f.write(b"]\\cf1 ")
                        f.write(text.encode('cp949', errors='replace'))
                        f.write(b"\\par\n")
                    
                    # 통계
                    total_chars = sum(len(s.text) for s in subtitles_snapshot)
                    stats = self._rtf_encode(f"총 {len(subtitles_snapshot)}문장, {total_chars:,}자")
                    f.write(b"\\par\\fs18 ")
                    f.write(stats.encode('cp949', errors='replace'))
                    f.write(b"\\par}")
                
                QMessageBox.information(self, "성공", f"RTF 저장 완료!\n\n파일: {path}\n\n이 파일은 한글(HWP)에서 열 수 있습니다.")
            
            except Exception as e:
                QMessageBox.critical(self, "오류", f"RTF 저장 실패: {e}")
    
    # ========== 세션 ==========
    
    def _save_session(self):
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return
        
        filename = f"{Config.SESSION_DIR}/세션_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path, _ = QFileDialog.getSaveFileName(self, "세션 저장", filename, "JSON (*.json)")
        
        if path:
            try:
                # 디렉토리 존재 확인
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                
                # 스레드 안전하게 자막 복사
                with self.subtitle_lock:
                    subtitles_copy = [s.to_dict() for s in self.subtitles]
                
                # 위원회명 추출
                current_url = self._get_current_url()
                committee_name = self._autodetect_tag(current_url) or ""
                
                data = {
                    'version': Config.VERSION,
                    'created': datetime.now().isoformat(),
                    'url': current_url,
                    'committee_name': committee_name,
                    'subtitles': subtitles_copy
                }
                
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                # 데이터베이스에도 저장 (#26)
                if self.db:
                    try:
                        duration = int(time.time() - self.start_time) if self.start_time else 0
                        db_data = {
                            'url': current_url,
                            'committee_name': committee_name,
                            'subtitles': subtitles_copy,
                            'version': Config.VERSION,
                            'duration_seconds': duration
                        }
                        self.db.save_session(db_data)
                    except Exception as db_error:
                        logger.warning(f"DB 저장 실패 (JSON 저장은 성공): {db_error}")
                
                self._show_toast("세션 저장 완료!", "success")
            except Exception as e:
                logger.error(f"세션 저장 오류: {e}")
                QMessageBox.critical(self, "오류", f"세션 저장 실패: {e}")
    
    def _load_session(self):
        path, _ = QFileDialog.getOpenFileName(self, "세션 불러오기", f"{Config.SESSION_DIR}/", "JSON (*.json)")
        
        if path:
            try:
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except json.JSONDecodeError as je:
                    # JSON 파싱 오류 시 백업 안내
                    reply = QMessageBox.question(
                        self, "파일 손상",
                        f"세션 파일이 손상되었습니다 (JSON 오류).\n위치: {path}\n\n"
                        "백업 폴더를 열어 복구를 시도하시겠습니까?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        backup_path = os.path.abspath(Config.BACKUP_DIR)
                        if os.name == 'nt':
                            os.startfile(backup_path)
                    return
                
                # 세션 버전 호환성 확인
                session_version = data.get('version', 'unknown')
                if session_version != Config.VERSION:
                    reply = QMessageBox.question(
                        self, "버전 불일치",
                        f"세션 버전({session_version})이 현재 버전({Config.VERSION})과 다릅니다.\n"
                        "계속 불러오시겠습니까?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.No:
                        return
                
                # 스레드 안전하게 자막 교체
                new_subtitles = [
                    SubtitleEntry.from_dict(item) 
                    for item in data.get('subtitles', [])
                ]
                with self.subtitle_lock:
                    self.subtitles = new_subtitles
                self.last_subtitle = ""
                self._pending_minute_bucket = None
                self.finalize_timer.stop()
                self._rebuild_stats_cache()
                
                if data.get('url'):
                    self.url_combo.setCurrentText(data['url'])
                
                self._refresh_text()
                self._update_count_label()
                self._show_toast(f"세션 불러오기 완료! {len(self.subtitles)}개 문장", "success")
            
            except Exception as e:
                QMessageBox.critical(self, "오류", f"불러오기 실패: {e}")
    
    # ========== 유틸리티 ==========
    
    def _copy_to_clipboard(self):
        text = self._get_accumulated_text()
        if not text:
            self._show_toast("복사할 내용이 없습니다.", "warning")
            return
        
        QApplication.clipboard().setText(text)
        self._show_toast(f"클립보드에 복사되었습니다. ({len(text):,}자)", "success")
    
    def _clear_text(self):
        if not self.subtitles:
            return
        
        reply = QMessageBox.question(
            self, "확인", "모든 내용을 지우시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            with self.subtitle_lock:
                self.subtitles = []
            self._cached_total_chars = 0
            self._cached_total_words = 0
            self.last_subtitle = ""
            self._pending_minute_bucket = None
            self.finalize_timer.stop()
            self.subtitle_text.clear()
            self._update_count_label()
            self.status_label.setText("내용 삭제됨")
    
    def _edit_subtitle(self):
        """선택한 자막 편집"""
        if not self.subtitles:
            self._show_toast("편집할 자막이 없습니다.", "warning")
            return
        if self.is_running:
            self._show_toast("추출 중에는 편집이 불안정할 수 있습니다. 먼저 중지하세요.", "warning")
            return
        
        # 자막 목록 다이얼로그
        dialog = QDialog(self)
        dialog.setWindowTitle("자막 편집")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # 안내 라벨
        info_label = QLabel("편집할 자막을 선택하세요:")
        layout.addWidget(info_label)
        
        # 자막 목록
        list_widget = QListWidget()
        for i, entry in enumerate(self.subtitles):
            timestamp = entry.timestamp.strftime('%H:%M:%S')
            text_preview = entry.text[:50] + "..." if len(entry.text) > 50 else entry.text
            list_widget.addItem(f"[{timestamp}] {text_preview}")
        layout.addWidget(list_widget)
        
        # 편집 영역
        edit_label = QLabel("자막 내용:")
        layout.addWidget(edit_label)
        
        edit_text = QTextEdit()
        edit_text.setMaximumHeight(100)
        layout.addWidget(edit_text)
        
        # 선택 시 내용 로드
        def on_selection_changed():
            idx = list_widget.currentRow()
            if 0 <= idx < len(self.subtitles):
                edit_text.setText(self.subtitles[idx].text)
        
        list_widget.currentRowChanged.connect(on_selection_changed)
        
        # 버튼
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        
        def save_edit():
            idx = list_widget.currentRow()
            if 0 <= idx < len(self.subtitles):
                new_text = edit_text.toPlainText().strip()
                if new_text:
                    with self.subtitle_lock:
                        entry = self.subtitles[idx]
                        old_chars = entry.char_count
                        old_words = entry.word_count
                        entry.update_text(new_text)
                        self._cached_total_chars += (entry.char_count - old_chars)
                        self._cached_total_words += (entry.word_count - old_words)
                    self._refresh_text()
                    self._update_count_label()
                    self._show_toast("자막이 수정되었습니다.", "success")
                    dialog.accept()
                else:
                    QMessageBox.warning(dialog, "알림", "자막 내용을 입력해주세요.")
            else:
                QMessageBox.warning(dialog, "알림", "편집할 자막을 선택해주세요.")
        
        buttons.accepted.connect(save_edit)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        # 첫 번째 항목 선택
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
        
        dialog.exec()
    
    def _delete_subtitle(self):
        """선택한 자막 삭제"""
        if not self.subtitles:
            self._show_toast("삭제할 자막이 없습니다.", "warning")
            return
        if self.is_running:
            self._show_toast("추출 중에는 삭제가 불안정할 수 있습니다. 먼저 중지하세요.", "warning")
            return
        
        # 자막 목록 다이얼로그
        dialog = QDialog(self)
        dialog.setWindowTitle("자막 삭제")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # 안내 라벨
        info_label = QLabel("삭제할 자막을 선택하세요 (다중 선택 가능):")
        layout.addWidget(info_label)
        
        # 자막 목록 (다중 선택 가능)
        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        
        for i, entry in enumerate(self.subtitles):
            timestamp = entry.timestamp.strftime('%H:%M:%S')
            text_preview = entry.text[:50] + "..." if len(entry.text) > 50 else entry.text
            list_widget.addItem(f"[{timestamp}] {text_preview}")
        layout.addWidget(list_widget)
        
        # 버튼
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("삭제")
        
        def delete_selected():
            selected_rows = sorted([i.row() for i in list_widget.selectedIndexes()], reverse=True)
            if not selected_rows:
                QMessageBox.warning(dialog, "알림", "삭제할 자막을 선택해주세요.")
                return
            
            reply = QMessageBox.question(
                dialog, "확인",
                f"선택한 {len(selected_rows)}개의 자막을 삭제하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                with self.subtitle_lock:
                    for row in selected_rows:
                        entry = self.subtitles[row]
                        self._cached_total_chars -= entry.char_count
                        self._cached_total_words -= entry.word_count
                        del self.subtitles[row]
                self._refresh_text()
                self._update_count_label()
                self._show_toast(f"{len(selected_rows)}개 자막이 삭제되었습니다.", "success")
                dialog.accept()
        
        buttons.accepted.connect(delete_selected)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        dialog.exec()
    
    # ========== 도움말 ==========
    
    def _show_guide(self):
        """사용법 가이드 표시"""
        guide = """
<h2>🏛️ 사용법 가이드</h2>

<h3>📋 기본 사용법</h3>
<ol>
<li><b>URL 입력</b> - 국회 의사중계 페이지 URL을 입력합니다</li>
<li><b>선택자 확인</b> - 기본값을 사용하거나 수정합니다</li>
<li><b>옵션 설정</b>
    <ul>
    <li>자동 스크롤: 새 자막 자동 따라가기</li>
    <li>실시간 저장: 자막 실시간 파일 저장</li>
    <li>헤드리스 모드: 브라우저 창 숨기고 실행</li>
    </ul>
</li>
<li><b>시작</b> 버튼 클릭 (또는 F5)</li>
<li>자막 추출 완료 후 <b>파일 저장</b></li>
</ol>

<h3>⌨️ 주요 단축키</h3>
<table>
<tr><td><b>F5</b></td><td>시작</td></tr>
<tr><td><b>Escape</b></td><td>중지</td></tr>
<tr><td><b>Ctrl+F</b></td><td>검색</td></tr>
<tr><td><b>F3</b></td><td>다음 검색</td></tr>
<tr><td><b>Ctrl+T</b></td><td>테마 전환</td></tr>
<tr><td><b>Ctrl+S</b></td><td>TXT 저장</td></tr>
</table>
"""
        msg = QMessageBox(self)
        msg.setWindowTitle("사용법 가이드")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(guide)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()
    
    def _show_shortcuts(self):
        """키보드 단축키 목록 표시"""
        shortcuts = """
<h2>⌨️ 키보드 단축키</h2>

<h3>📋 기본 조작</h3>
<table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
<tr style="background-color: #f0f0f0;"><th>단축키</th><th>기능</th></tr>
<tr><td><b>F5</b></td><td>추출 시작</td></tr>
<tr><td><b>Escape</b></td><td>추출 중지</td></tr>
<tr><td><b>Ctrl+Q</b></td><td>프로그램 종료</td></tr>
</table>

<h3>🔍 검색 및 편집</h3>
<table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
<tr style="background-color: #f0f0f0;"><th>단축키</th><th>기능</th></tr>
<tr><td><b>Ctrl+F</b></td><td>검색창 열기</td></tr>
<tr><td><b>F3</b></td><td>다음 검색 결과</td></tr>
<tr><td><b>Shift+F3</b></td><td>이전 검색 결과</td></tr>
<tr><td><b>Ctrl+E</b></td><td>자막 편집</td></tr>
<tr><td><b>Delete</b></td><td>자막 삭제</td></tr>
<tr><td><b>Ctrl+C</b></td><td>클립보드 복사</td></tr>
</table>

<h3>💾 저장</h3>
<table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
<tr style="background-color: #f0f0f0;"><th>단축키</th><th>기능</th></tr>
<tr><td><b>Ctrl+S</b></td><td>TXT 저장</td></tr>
<tr><td><b>Ctrl+Shift+S</b></td><td>세션 저장</td></tr>
<tr><td><b>Ctrl+O</b></td><td>세션 불러오기</td></tr>
</table>

<h3>🎨 보기</h3>
<table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
<tr style="background-color: #f0f0f0;"><th>단축키</th><th>기능</th></tr>
<tr><td><b>Ctrl+T</b></td><td>테마 전환</td></tr>
<tr><td><b>Ctrl++</b></td><td>글자 크기 키우기</td></tr>
<tr><td><b>Ctrl+-</b></td><td>글자 크기 줄이기</td></tr>
<tr><td><b>F1</b></td><td>사용법 가이드</td></tr>
</table>
"""
        msg = QMessageBox(self)
        msg.setWindowTitle("키보드 단축키")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(shortcuts)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()
    
    def _show_features(self):
        """기능 소개 표시"""
        features = """
<h2>✨ 기능 소개</h2>

<h3>🎯 실시간 자막 추출</h3>
<p>국회 의사중계 웹사이트의 AI 자막을 실시간으로 캡처합니다.<br>
2초 동안 자막이 변경되지 않으면 자동으로 확정됩니다.</p>

<h3>💾 다양한 저장 형식</h3>
<ul>
<li><b>TXT</b> - 일반 텍스트</li>
<li><b>SRT</b> - 자막 파일 형식</li>
<li><b>VTT</b> - WebVTT 자막 형식</li>
<li><b>DOCX</b> - Word 문서</li>
</ul>

<h3>🔍 검색 및 하이라이트</h3>
<ul>
<li><b>실시간 검색</b> - Ctrl+F로 자막 내 텍스트 검색</li>
<li><b>키워드 하이라이트</b> - 특정 단어 강조</li>
</ul>

<h3>⚙️ 헤드리스 모드 (인터넷창 숨김)</h3>
<p>브라우저 창을 숨기고 백그라운드에서 실행합니다.<br>
자막 추출 중 다른 작업을 할 수 있습니다.</p>

<h3>📊 통계 패널</h3>
<p>실행 시간, 글자 수, 단어 수, 분당 글자 수를 표시합니다.</p>
"""
        msg = QMessageBox(self)
        msg.setWindowTitle("기능 소개")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(features)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()
    
    def _show_about(self):
        """프로그램 정보 표시"""
        about = f"""
<h2>🏛️ 국회 의사중계 자막 추출기</h2>
<p><b>버전:</b> {Config.VERSION}</p>
<p><b>설명:</b> 국회 의사중계 웹사이트에서 실시간 AI 자막을<br>
자동으로 추출하고 저장하는 프로그램입니다.</p>

<h3>📦 필요 라이브러리</h3>
<ul>
<li>PyQt6</li>
<li>selenium</li>
<li>python-docx (DOCX 저장용)</li>
</ul>

<p><b>© 2024-2025</b></p>
"""
        msg = QMessageBox(self)
        msg.setWindowTitle("정보")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(about)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()
    
    # ========== 데이터베이스 기능 (#26) ==========
    
    def _show_db_history(self):
        """세션 히스토리 다이얼로그 표시"""
        if not self.db:
            QMessageBox.warning(self, "알림", "데이터베이스가 초기화되지 않았습니다.")
            return
        
        sessions = self.db.list_sessions(limit=50)
        if not sessions:
            QMessageBox.information(self, "세션 히스토리", "저장된 세션이 없습니다.")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("📋 세션 히스토리")
        dialog.setMinimumSize(700, 500)
        
        layout = QVBoxLayout(dialog)
        
        # 세션 목록
        list_widget = QListWidget()
        for s in sessions:
            created = s.get("created_at", "")[:19] if s.get("created_at") else ""
            committee = s.get("committee_name") or "알 수 없음"
            subtitles = s.get("total_subtitles", 0)
            chars = s.get("total_characters", 0)
            list_widget.addItem(f"[{created}] {committee} - {subtitles}문장, {chars:,}자")
        
        layout.addWidget(list_widget)
        
        # 버튼
        btn_layout = QHBoxLayout()
        
        load_btn = QPushButton("불러오기")
        def load_selected():
            idx = list_widget.currentRow()
            if idx >= 0:
                session_id = sessions[idx].get("id")
                session_data = self.db.load_session(session_id)
                if session_data:
                    new_subtitles = [
                        SubtitleEntry.from_dict(s) 
                        for s in session_data.get("subtitles", [])
                    ]
                    with self.subtitle_lock:
                        self.subtitles = new_subtitles
                    self.last_subtitle = ""
                    self._pending_minute_bucket = None
                    self.finalize_timer.stop()
                    self._rebuild_stats_cache()
                    self._refresh_text()
                    self._update_count_label()
                    self._show_toast(f"세션 불러오기 완료! {len(new_subtitles)}개 문장", "success")
                    dialog.accept()
        load_btn.clicked.connect(load_selected)
        btn_layout.addWidget(load_btn)
        
        delete_btn = QPushButton("삭제")
        def delete_selected():
            idx = list_widget.currentRow()
            if idx >= 0:
                session_id = sessions[idx].get("id")
                reply = QMessageBox.question(dialog, "삭제 확인", 
                    "선택한 세션을 삭제하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    if self.db.delete_session(session_id):
                        list_widget.takeItem(idx)
                        sessions.pop(idx)
                        self._show_toast("세션 삭제됨", "info")
        delete_btn.clicked.connect(delete_selected)
        btn_layout.addWidget(delete_btn)
        
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
        dialog.exec()
    
    def _show_db_search(self):
        """자막 통합 검색 다이얼로그"""
        if not self.db:
            QMessageBox.warning(self, "알림", "데이터베이스가 초기화되지 않았습니다.")
            return
        
        query, ok = QInputDialog.getText(self, "자막 검색", "검색어:")
        if not ok or not query.strip():
            return
        
        results = self.db.search_subtitles(query.strip())
        if not results:
            QMessageBox.information(self, "검색 결과", "검색 결과가 없습니다.")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"🔍 검색 결과 - '{query}'")
        dialog.setMinimumSize(700, 500)
        
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"총 {len(results)}개 결과"))
        
        list_widget = QListWidget()
        for r in results:
            created = r.get("created_at", "")[:10] if r.get("created_at") else ""
            committee = r.get("committee_name") or ""
            text = r.get("text", "")[:100]
            list_widget.addItem(f"[{created}] {committee}: {text}")
        
        layout.addWidget(list_widget)
        
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(dialog.reject)
        layout.addWidget(close_btn)
        
        dialog.exec()
    
    def _show_db_stats(self):
        """데이터베이스 전체 통계"""
        if not self.db:
            QMessageBox.warning(self, "알림", "데이터베이스가 초기화되지 않았습니다.")
            return
        
        stats = self.db.get_statistics()
        msg = f"""
<h2>📊 데이터베이스 통계</h2>
<table>
<tr><td><b>총 세션 수:</b></td><td>{stats.get('total_sessions', 0):,}개</td></tr>
<tr><td><b>총 자막 수:</b></td><td>{stats.get('total_subtitles', 0):,}개</td></tr>
<tr><td><b>총 글자 수:</b></td><td>{stats.get('total_characters', 0):,}자</td></tr>
<tr><td><b>총 녹화 시간:</b></td><td>{stats.get('total_duration_hours', 0):.1f}시간</td></tr>
</table>
"""
        QMessageBox.information(self, "데이터베이스 통계", msg)
    
    # ========== 자막 병합 기능 (#20) ==========
    
    def _show_merge_dialog(self):
        """자막 병합 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("📎 자막 병합")
        dialog.setMinimumSize(600, 500)
        
        layout = QVBoxLayout(dialog)
        
        # 파일 목록
        layout.addWidget(QLabel("병합할 세션 파일을 추가하세요:"))
        file_list = QListWidget()
        file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(file_list)
        
        file_paths = []
        
        # 파일 추가/제거 버튼
        file_btn_layout = QHBoxLayout()
        
        add_btn = QPushButton("➕ 파일 추가")
        def add_files():
            paths, _ = QFileDialog.getOpenFileNames(
                dialog, "세션 파일 선택", f"{Config.SESSION_DIR}/",
                "JSON 파일 (*.json)"
            )
            for path in paths:
                if path not in file_paths:
                    file_paths.append(path)
                    file_list.addItem(Path(path).name)
        add_btn.clicked.connect(add_files)
        file_btn_layout.addWidget(add_btn)
        
        remove_btn = QPushButton("➖ 선택 제거")
        def remove_files():
            for item in file_list.selectedItems():
                idx = file_list.row(item)
                file_list.takeItem(idx)
                if idx < len(file_paths):
                    file_paths.pop(idx)
        remove_btn.clicked.connect(remove_files)
        file_btn_layout.addWidget(remove_btn)
        
        layout.addLayout(file_btn_layout)
        
        # 옵션
        options_layout = QHBoxLayout()
        remove_dup_check = QCheckBox("중복 자막 제거")
        remove_dup_check.setChecked(True)
        sort_check = QCheckBox("시간순 정렬")
        sort_check.setChecked(True)
        options_layout.addWidget(remove_dup_check)
        options_layout.addWidget(sort_check)
        options_layout.addStretch()
        layout.addLayout(options_layout)
        
        # 버튼
        btn_layout = QHBoxLayout()
        
        merge_btn = QPushButton("병합 실행")
        def do_merge():
            if len(file_paths) < 2:
                QMessageBox.warning(dialog, "알림", "2개 이상의 파일을 선택하세요.")
                return
            
        # 기존 자막 처리 옵션 확인
        existing_subtitles = None
        if self.subtitles:
            reply = QMessageBox.question(
                dialog, "기존 자막 처리",
                f"현재 {len(self.subtitles)}개의 자막이 있습니다.\n\n"
                "기존 자막을 병합 결과에 포함하시겠습니까?\n"
                "(Yes: 포함하여 병합 / No: 기존 자막 무시하고 파일들만 병합)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            
            if reply == QMessageBox.StandardButton.Yes:
                existing_subtitles = list(self.subtitles)
        
        merged = self._merge_sessions(
            file_paths,
            remove_duplicates=remove_dup_check.isChecked(),
            sort_by_time=sort_check.isChecked(),
            existing_subtitles=existing_subtitles
        )
        
        if merged:
            with self.subtitle_lock:
                self.subtitles = merged
            self.last_subtitle = ""
            self._pending_minute_bucket = None
            self.finalize_timer.stop()
            self._rebuild_stats_cache()
            self._refresh_text()
            self._update_count_label()
            self._show_toast(f"병합 완료! {len(merged)}개 문장", "success")
            dialog.accept()
        merge_btn.clicked.connect(do_merge)
        btn_layout.addWidget(merge_btn)
        
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
        dialog.exec()
    
    def _merge_sessions(self, file_paths: list, remove_duplicates: bool = True, 
                       sort_by_time: bool = True, existing_subtitles: list = None) -> list:
        """여러 세션 파일을 병합
        
        Args:
            file_paths: 병합할 파일 경로 목록
            remove_duplicates: 중복 자막 제거 여부
            sort_by_time: 시간순 정렬 여부
            existing_subtitles: 기존 자막 리스트 (선택)
            
        Returns:
            List[SubtitleEntry]: 병합된 자막 목록
        """
        all_entries = []
        
        # 기존 자막 추가
        if existing_subtitles:
            all_entries.extend(existing_subtitles)
        
        for path in file_paths:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                for item in data.get("subtitles", []):
                    entry = SubtitleEntry.from_dict(item)
                    all_entries.append(entry)
                    
            except Exception as e:
                logger.warning(f"파일 로드 실패 ({path}): {e}")
        
        # 시간순 정렬
        if sort_by_time:
            all_entries.sort(key=lambda e: e.timestamp)
        
        # 중복 제거
        if remove_duplicates:
            seen = set()
            unique_entries = []
            for entry in all_entries:
                text_normalized = entry.text.strip().lower()
                if text_normalized not in seen:
                    seen.add(text_normalized)
                    unique_entries.append(entry)
            all_entries = unique_entries
        
        logger.info(f"병합 완료: {len(all_entries)}개 자막")
        return all_entries

    def closeEvent(self, event):
        # 트레이 최소화 모드
        if self.minimize_to_tray and self.tray_icon.isVisible():
            self.hide()
            self.tray_icon.showMessage(
                Config.APP_NAME,
                "프로그램이 트레이로 최소화되었습니다.\n트레이 아이콘을 더블클릭하여 다시 열 수 있습니다.",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
            event.ignore()
            return
        
        # 저장하지 않은 자막이 있으면 확인
        if self.subtitles:
            reply = QMessageBox.question(
                self, "종료 확인",
                f"저장하지 않은 자막 {len(self.subtitles)}개가 있습니다.\n\n"
                "저장하시겠습니까?",
                QMessageBox.StandardButton.Save | 
                QMessageBox.StandardButton.Discard | 
                QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            elif reply == QMessageBox.StandardButton.Save:
                # 저장 대화상자에서 취소하면 종료도 취소
                filename = f"국회자막_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                path, _ = QFileDialog.getSaveFileName(
                    self, "TXT 저장", filename, "텍스트 (*.txt)"
                )
                if not path:  # 사용자가 취소한 경우
                    event.ignore()
                    return
                # 파일 저장 (스레드 안전하게 자막 복사)
                try:
                    with self.subtitle_lock:
                        subtitles_snapshot = list(self.subtitles)
                    with open(path, 'w', encoding='utf-8') as f:
                        for entry in subtitles_snapshot:
                            f.write(f"[{entry.timestamp.strftime('%H:%M:%S')}] {entry.text}\n")
                except Exception as e:
                    QMessageBox.critical(self, "오류", f"저장 실패: {e}")
                    event.ignore()
                    return
        
        # 추출 중이면 확인
        if self.is_running:
            reply = QMessageBox.question(
                self, "종료", "추출 중입니다. 종료하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        
        # 창 위치/크기 저장
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        
        # 타이머 정리
        self.queue_timer.stop()
        self.stats_timer.stop()
        self.finalize_timer.stop()
        self.backup_timer.stop()
        
        # 워커 스레드 종료
        self.is_running = False
        self.stop_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=Config.THREAD_STOP_TIMEOUT)
        
        if self.realtime_file:
            try:
                self.realtime_file.close()
            except Exception as e:
                logger.debug(f"파일 닫기 오류: {e}")
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.debug(f"WebDriver 종료 오류: {e}")
        
        # 데이터베이스 연결 정리
        if getattr(self, 'db', None):
            try:
                self.db.close_all()
            except Exception as e:
                logger.debug(f"DB 연결 종료 오류: {e}")

        logger.info("프로그램 종료")
        event.accept()


