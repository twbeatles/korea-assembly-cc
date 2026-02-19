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
from typing import Any

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QComboBox,
    QCheckBox,
    QApplication,
    QFrame,
    QProgressBar,
    QMessageBox,
    QFileDialog,
    QGroupBox,
    QGridLayout,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QSplitter,
    QMenu,
    QMenuBar,
    QInputDialog,
    QSystemTrayIcon,
    QAbstractItemView,
    QTreeWidget,
    QTreeWidgetItem,
    QToolBar,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QSettings
from PyQt6.QtGui import (
    QFont,
    QColor,
    QTextCursor,
    QTextCharFormat,
    QAction,
    QShortcut,
    QKeySequence,
    QIcon,
)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    WebDriverException,
    NoSuchElementException,
    StaleElementReferenceException,
)
from selenium.webdriver.chrome.options import Options

from core.config import Config
from core.logging_utils import logger
from core.models import SubtitleEntry
from ui.dialogs import LiveBroadcastDialog
from ui.themes import DARK_THEME, LIGHT_THEME
from ui.widgets import CollapsibleGroupBox, ToastWidget
from core import utils
from core.subtitle_processor import SubtitleProcessor

try:
    from database import DatabaseManager

    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    logger.warning(
        "database.py 모듈을 찾을 수 없습니다. 데이터베이스 기능은 비활성화됩니다."
    )


class RecoverableWebDriverError(RuntimeError):
    """웹드라이버 재연결로 복구 가능한 오류"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{Config.APP_NAME} v{Config.VERSION}")
        self.setMinimumSize(1100, 750)
        self.resize(1200, 800)

        # 설정
        self.settings = QSettings("AssemblySubtitle", "Extractor")
        self.is_dark_theme = self.settings.value("dark_theme", True, type=bool)
        self.font_size = self.settings.value(
            "font_size", Config.DEFAULT_FONT_SIZE, type=int
        )
        self.minimize_to_tray = self.settings.value(
            "minimize_to_tray", False, type=bool
        )

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
        self._last_raw_text = ""
        self._last_processed_raw = ""
        self._stream_start_time = None

        # [NEW] 글로벌 히스토리 + Suffix 매칭 (#GlobalHistorySuffix)
        self._confirmed_compact = ""  # 확정된 모든 텍스트 (compact, 공백 제거)
        self._trailing_suffix = ""  # 히스토리의 마지막 N자 (suffix 매칭용)
        self._suffix_length = 50  # suffix 길이
        self._preview_desync_count = 0
        self._preview_ambiguous_skip_count = 0
        self._last_good_raw_compact = ""
        self._preview_resync_threshold = 10
        self._preview_ambiguous_resync_threshold = 6

        # 자막 데이터 (타임스탬프 포함)
        self.subtitles = []  # List[SubtitleEntry]

        # [Fix] 자막 중복 방지 프로세서 (#SubtitleRepetitionFix)
        self.subtitle_processor = SubtitleProcessor()

        # 저장된 키워드 로드
        saved_keywords = self.settings.value("highlight_keywords", "")
        if not saved_keywords:
            legacy_keywords = self.settings.value("keywords", "", type=str)
            if legacy_keywords:
                saved_keywords = legacy_keywords
                self.settings.setValue("highlight_keywords", legacy_keywords)
                self.settings.remove("keywords")
        self.keywords = (
            [k.strip() for k in saved_keywords.split(",") if k.strip()]
            if saved_keywords
            else []
        )
        saved_alert = self.settings.value("alert_keywords", "")
        self.alert_keywords = (
            [k.strip() for k in saved_alert.split(",") if k.strip()]
            if saved_alert
            else []
        )
        self._alert_keywords_cache = []
        self._rebuild_alert_keyword_cache(
            self.alert_keywords, update_settings=False
        )
        self.last_update_time = 0  # 마지막 자막 업데이트 시간

        # 성능 최적화: QTextCharFormat 캐싱
        self._highlight_fmt = QTextCharFormat()
        self._highlight_fmt.setBackground(QColor("#ffd700"))  # 골드 배경
        self._highlight_fmt.setForeground(QColor("#000000"))  # 검정 글자
        self._highlight_fmt.setFontWeight(QFont.Weight.Bold)
        self._normal_fmt = QTextCharFormat()
        self._timestamp_fmt = QTextCharFormat()
        self._timestamp_fmt.setForeground(QColor("#888888"))

        # 성능 최적화: 키워드 패턴 캐싱
        self._keyword_pattern = None  # 컴파일된 정규식 패턴
        self._keywords_lower_set = set()  # 빠른 검색용 set
        self._rebuild_keyword_cache(self.keywords, update_settings=False, refresh=False)

        # 성능 최적화: 통계 캐싱
        self._cached_total_chars = 0
        self._cached_total_words = 0

        # 렌더링 상태 캐싱
        self._last_rendered_count = 0
        self._last_rendered_last_text = ""
        self._last_render_offset = 0
        self._last_render_show_ts = None

        # 토스트 스택 관리
        self.active_toasts = []  # 현재 표시 중인 토스트 목록

        # 실시간 저장
        self.realtime_file = None
        self._realtime_error_count = 0  # 실시간 저장 연속 오류 카운트 (#3)

        # 중지 시 브라우저 유지용 (종료 시 정리)
        self._detached_drivers = []
        self._detached_drivers_lock = threading.Lock()
        self._last_subtitle_frame_path = ()

        # 연결 상태 모니터링 (#30)
        self.connection_status = "disconnected"  # connected, disconnected, reconnecting
        self.last_ping_time = 0
        self.ping_latency = 0  # ms

        # 자동 재연결 (#31)
        self.reconnect_attempts = 0
        self.auto_reconnect_enabled = self.settings.value(
            "auto_reconnect", True, type=bool
        )
        self.current_url = ""  # 현재 연결 중인 URL 저장

        # 스마트 스크롤 상태 (사용자가 위로 스크롤하면 자동 스크롤 일시 중지)
        self._user_scrolled_up = False
        self._is_stopping = False
        self._last_status_message = ""
        self._session_save_in_progress = False
        self._session_load_in_progress = False
        self._db_history_dialog_state = None

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
        self._db_tasks_inflight = set()
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
            self.tray_icon.setIcon(
                self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon)
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
        # copy_action.setShortcut("Ctrl+C") # 텍스트 선택 복사 충돌 방지
        copy_action.setToolTip("전체 자막을 클립보드에 복사합니다")
        copy_action.triggered.connect(self._copy_to_clipboard)
        edit_menu.addAction(copy_action)

        clear_action = QAction("내용 지우기", self)
        clear_action.setToolTip("모든 자막 내용을 삭제합니다")
        clear_action.triggered.connect(self._clear_text)
        edit_menu.addAction(clear_action)

        # 보기 메뉴
        view_menu = menubar.addMenu("보기")

        self.theme_action = QAction(
            "라이트 테마" if self.is_dark_theme else "다크 테마", self
        )
        self.theme_action.setShortcut("Ctrl+T")
        self.theme_action.triggered.connect(self._toggle_theme)
        view_menu.addAction(self.theme_action)

        self.timestamp_action = QAction("타임스탬프 표시", self)
        self.timestamp_action.setCheckable(True)
        self.timestamp_action.setChecked(True)
        self.timestamp_action.triggered.connect(self._refresh_text_full)
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
            font_action.triggered.connect(
                lambda checked, s=size: self._set_font_size(s)
            )
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

        # 줄넘김 정리
        clean_newlines_action = QAction("줄넘김 정리", self)
        clean_newlines_action.setShortcut("Ctrl+Shift+L")
        clean_newlines_action.setToolTip(
            "문장 부호로 끝나지 않는 줄을 병합하여 문장을 정리합니다"
        )
        clean_newlines_action.triggered.connect(self._clean_newlines)
        tools_menu.addAction(clean_newlines_action)

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
        # === 상단 영역 컨테이너 ===
        self.top_header_container = QWidget()
        top_header_layout = QVBoxLayout(self.top_header_container)
        top_header_layout.setContentsMargins(0, 0, 0, 0)
        top_header_layout.setSpacing(15)
        top_header_layout.addWidget(header)

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

        # 자막 줄넘김 정리 버튼 (New)
        clean_btn = QPushButton("✨ 줄넘김 정리")
        clean_btn.setStyleSheet(toolbar_btn_style)
        clean_btn.setToolTip(
            "문장 부호로 끊어지지 않은 줄을 자동으로 병합 (Ctrl+Shift+L)"
        )
        clean_btn.clicked.connect(self._clean_newlines)

        # 자막 지우기 버튼
        clear_btn = QPushButton("🗑️ 지우기")
        clear_btn.setStyleSheet(toolbar_btn_style)
        clear_btn.setToolTip("현재 자막 목록 초기화")
        clear_btn.clicked.connect(self._clear_subtitles)

        toolbar_layout.addWidget(quick_save_btn)
        toolbar_layout.addWidget(search_btn)
        toolbar_layout.addWidget(copy_btn)
        toolbar_layout.addWidget(clean_btn)
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

        top_header_layout.addWidget(toolbar_frame)
        layout.addWidget(self.top_header_container)

        # === URL/설정 영역 (접기/펼치기 가능) ===
        self.settings_group = CollapsibleGroupBox("⚙️ 설정")
        settings_layout = QGridLayout(self.settings_group)
        settings_layout.setSpacing(10)

        # URL
        url_label = QLabel("📌 URL:")
        url_label.setToolTip("국회 의사중계 웹사이트 URL을 입력하세요")
        settings_layout.addWidget(url_label, 0, 0)

        url_layout = QHBoxLayout()
        self.url_combo = QComboBox()
        self.url_combo.setEditable(True)
        self.url_combo.setToolTip(
            "국회 의사중계 웹사이트 URL\n최근 사용한 URL이 자동 저장됩니다\n태그가 있으면 [태그] 형태로 표시됩니다"
        )

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
        self.tag_btn.setFixedWidth(90)
        self.tag_btn.clicked.connect(self._edit_url_tag)
        url_layout.addWidget(self.tag_btn)

        # 상임위원회 프리셋 버튼
        self.preset_btn = QPushButton("📋 상임위")
        self.preset_btn.setToolTip("상임위원회 프리셋 선택\n빠른 URL 입력을 위한 기능")
        self.preset_btn.setFixedWidth(120)

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
        self.live_btn.setFixedWidth(140)
        self.live_btn.clicked.connect(self._show_live_dialog)
        url_layout.addWidget(self.live_btn)

        # 선택자
        selector_label = QLabel("🔍 선택자:")
        selector_label.setToolTip("자막 요소의 CSS 선택자")
        settings_layout.addWidget(selector_label, 1, 0)
        self.selector_combo = QComboBox()
        self.selector_combo.setEditable(True)
        self.selector_combo.addItems(Config.DEFAULT_SELECTORS)
        self.selector_combo.setToolTip(
            "자막 텍스트가 표시되는 HTML 요소의 CSS 선택자\n기본값을 사용하거나 직접 입력하세요"
        )
        settings_layout.addWidget(self.selector_combo, 1, 1)

        # 옵션
        options_layout = QHBoxLayout()
        options_layout.setSpacing(20)

        self.auto_scroll_check = QCheckBox("📜 자동 스크롤")
        self.auto_scroll_check.setChecked(True)
        self.auto_scroll_check.setToolTip(
            "새 자막이 추가될 때 자동으로 맨 아래로 스크롤합니다"
        )

        self.realtime_save_check = QCheckBox("💾 실시간 저장")
        self.realtime_save_check.setChecked(False)
        self.realtime_save_check.setToolTip(
            "자막이 확정될 때마다 자동으로 파일에 저장합니다\n저장 위치: realtime_output 폴더"
        )

        self.headless_check = QCheckBox("🔇 헤드리스 모드 (인터넷창 숨김)")
        self.headless_check.setChecked(False)
        self.headless_check.setToolTip(
            "Chrome 브라우저 창을 숨기고 백그라운드에서 실행합니다.\n자막 추출 중 다른 작업을 할 수 있습니다."
        )
        options_layout.addWidget(self.auto_scroll_check)
        options_layout.addWidget(self.realtime_save_check)
        options_layout.addWidget(self.headless_check)
        options_layout.addStretch()
        settings_layout.addLayout(options_layout, 2, 0, 1, 2)

        # 키워드 알림 (추가)
        keyword_layout = QHBoxLayout()
        keyword_label = QLabel("✨ 하이라이트 키워드:")
        keyword_label.setToolTip("강조 표시할 키워드 (쉼표로 구분)")
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("예: 예산, 경제, 의원님 (쉼표 구분)")
        self.keyword_input.setToolTip(
            "자막에 해당 키워드가 등장하면 강조 표시됩니다.\n여러 키워드는 쉼표(,)로 구분하세요."
        )
        # 키워드 변경 시 캐시 업데이트 (디바운싱 적용)
        self.keyword_input.textChanged.connect(self._update_keyword_cache)

        # 키워드 초기값 로드
        saved_keywords = self.settings.value("highlight_keywords", "", type=str)
        self.keyword_input.setText(saved_keywords)
        self._perform_keyword_cache_update()  # 초기 캐시 빌드

        keyword_layout.addWidget(keyword_label)
        keyword_layout.addWidget(self.keyword_input)
        settings_layout.addLayout(keyword_layout, 3, 0, 1, 2)

        layout.addWidget(self.settings_group)

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

        # 상단 접기/펼치기 버튼
        self.toggle_header_btn = QPushButton("🔼 상단 접기")
        self.toggle_header_btn.setToolTip(
            "상단 타이틀과 툴바를 숨겨 자막 영역을 넓힙니다"
        )
        self.toggle_header_btn.setFixedWidth(120)
        self.toggle_header_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(88, 166, 255, 0.1);
                border: 1px solid rgba(88, 166, 255, 0.3);
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: rgba(88, 166, 255, 0.2);
            }
        """)
        self.toggle_header_btn.clicked.connect(self._toggle_top_header)
        btn_layout.addWidget(self.toggle_header_btn)

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
        self.subtitle_text.setUndoRedoEnabled(False)

        # 스마트 스크롤: 스크롤바 값 변경 시 사용자 스크롤 감지
        self.subtitle_text.verticalScrollBar().valueChanged.connect(
            self._on_scroll_changed
        )

        subtitle_layout.addWidget(self.subtitle_text)

        # 실시간 미리보기 영역 (별도 표시)
        self.preview_frame = QFrame()
        preview_layout = QHBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(8, 6, 8, 6)
        preview_layout.setSpacing(8)

        preview_title = QLabel("⏳ 미리보기")
        preview_title.setFixedWidth(90)
        preview_title.setStyleSheet(
            "background: transparent; border: none; font-weight: 600;"
        )

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("background: transparent; border: none;")

        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(self.preview_label, 1)

        self.preview_frame.hide()
        subtitle_layout.addWidget(self.preview_frame)

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

        stat_labels = [
            self.stat_time,
            self.stat_chars,
            self.stat_words,
            self.stat_sents,
            self.stat_cpm,
        ]
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
        # === 상태바 - 모던 디자인 ===
        status_frame = QFrame()
        status_frame.setFixedHeight(48)  # 높이 고정
        status_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(48, 54, 61, 0.3);
                border-radius: 10px;
                padding: 4px;
            }
        """)
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(16, 4, 16, 4)  # 상하 여백 축소
        status_layout.setSpacing(12)

        # 상태 텍스트
        self.status_label = QLabel("⚪ 대기 중")
        self.status_label.setStyleSheet(
            "background: transparent; border: none; font-weight: 600; font-size: 13px;"
        )

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
        separator.setStyleSheet(
            "background-color: rgba(88, 166, 255, 0.3); max-width: 1px;"
        )

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

    def _set_status(self, text: str, status_type: str = "info"):
        """상태 표시 (아이콘 + 색상)"""
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
        self.status_label.setText(rendered)
        self.status_label.setStyleSheet(f"color: {color};")
        self._last_status_message = rendered

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

        self.connection_indicator.setText(icon)
        self.connection_indicator.setToolTip(tooltip)
        self.connection_indicator.setStyleSheet(
            f"background: transparent; border: none; font-size: 12px; color: {color};"
        )

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
            if Path(Config.URL_HISTORY_FILE).exists():
                with open(Config.URL_HISTORY_FILE, "r", encoding="utf-8") as f:
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
            utils.atomic_write_json(
                Config.URL_HISTORY_FILE,
                self.url_history,
                ensure_ascii=False,
                indent=2,
            )
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

        match = re.search(r"xcode=([^&]+)", url)
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
        if not url or not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "알림", "태그를 지정할 URL을 먼저 선택하세요.")
            return

        current_tag = self.url_history.get(url, "")
        tag, ok = QInputDialog.getText(
            self,
            "URL 태그 설정",
            f"URL: {url[:50]}...\n\n태그 입력 (예: 본회의, 법사위, 상임위):",
            text=current_tag,
        )

        if ok:
            self._add_to_history(url, tag.strip())
            QMessageBox.information(
                self,
                "성공",
                f"태그가 설정되었습니다: [{tag}]" if tag else "태그가 제거되었습니다.",
            )

    # ========== 상임위 프리셋 ==========

    def _load_committee_presets(self):
        """프리셋 파일에서 로드 (없으면 기본값 사용)"""
        self.committee_presets = dict(Config.DEFAULT_COMMITTEE_PRESETS)
        self.custom_presets = {}

        try:
            if Path(Config.PRESET_FILE).exists():
                with open(Config.PRESET_FILE, "r", encoding="utf-8") as f:
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
            data = {"presets": self.committee_presets, "custom": self.custom_presets}
            utils.atomic_write_json(
                Config.PRESET_FILE,
                data,
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            logger.warning(f"프리셋 저장 오류: {e}")

    def _build_preset_menu(self):
        """프리셋 메뉴 구성"""
        self.preset_menu.clear()

        # 기본 상임위원회
        for name, url in self.committee_presets.items():
            action = QAction(name, self)
            action.setData(url)
            action.triggered.connect(
                lambda checked, u=url, n=name: self._select_preset(u, n)
            )
            self.preset_menu.addAction(action)

        # 사용자 정의 프리셋이 있으면 구분선 추가
        if self.custom_presets:
            self.preset_menu.addSeparator()
            self.preset_menu.addAction("── 사용자 정의 ──").setEnabled(False)

            for name, url in self.custom_presets.items():
                action = QAction(f"⭐ {name}", self)
                action.setData(url)
                action.triggered.connect(
                    lambda checked, u=url, n=name: self._select_preset(u, n)
                )
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
            self, "프리셋 추가", "프리셋 이름을 입력하세요:"
        )
        if not ok or not name.strip():
            return

        name = name.strip()
        current_url = self._get_current_url()

        url, ok = QInputDialog.getText(
            self,
            "프리셋 URL",
            f"'{name}' 프리셋의 URL을 입력하세요:",
            text=current_url if current_url.startswith("http") else Config.DEFAULT_URL,
        )

        if ok and url.strip():
            self.custom_presets[name] = url.strip()
            self._save_committee_presets()
            self._build_preset_menu()
            self._show_toast(f"프리셋 '{name}' 추가됨", "success")

    def _manage_presets(self):
        """프리셋 관리 대화상자"""
        if not self.custom_presets:
            QMessageBox.information(
                self,
                "프리셋 관리",
                "사용자 정의 프리셋이 없습니다.\n\n"
                "'➕ 프리셋 추가'를 통해 새 프리셋을 추가하세요.",
            )
            return

        # 작업 선택
        names = list(self.custom_presets.keys())
        actions = ["수정", "삭제"]
        action, ok = QInputDialog.getItem(
            self, "프리셋 관리", "작업을 선택하세요:", actions, 0, False
        )

        if not ok:
            return

        # 프리셋 선택
        name, ok = QInputDialog.getItem(
            self,
            f"프리셋 {action}",
            f"{action}할 프리셋을 선택하세요:",
            names,
            0,
            False,
        )

        if not ok or not name:
            return

        if action == "삭제":
            reply = QMessageBox.question(
                self,
                "확인",
                f"'{name}' 프리셋을 삭제하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                del self.custom_presets[name]
                self._save_committee_presets()
                self._build_preset_menu()
                self._show_toast(f"프리셋 '{name}' 삭제됨", "warning")

        elif action == "수정":
            # 이름 수정
            new_name, ok = QInputDialog.getText(
                self, "프리셋 이름 수정", f"'{name}' 프리셋의 새 이름:", text=name
            )
            if not ok:
                return

            # URL 수정
            current_url = self.custom_presets[name]
            new_url, ok = QInputDialog.getText(
                self, "프리셋 URL 수정", f"'{new_name}' 프리셋의 URL:", text=current_url
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
                    "custom": self.custom_presets,
                }
                with open(path, "w", encoding="utf-8") as f:
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
                with open(path, "r", encoding="utf-8") as f:
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
                    self._show_toast(
                        f"프리셋 {imported_count}개 가져오기 완료!", "success"
                    )
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

        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "오류", "올바른 URL을 입력하세요.")
            return

        try:
            # 히스토리에 추가
            self._add_to_history(url)
            self.current_url = url

            # 초기화
            self.subtitle_text.clear()
            with self.subtitle_lock:
                self.subtitles = []
            self._cached_total_chars = 0
            self._cached_total_words = 0
            self._last_rendered_count = 0
            self._last_rendered_last_text = ""
            self._last_render_offset = 0
            self._last_render_show_ts = None
            self._last_printed_ts = None
            self._update_count_label()

            self.last_subtitle = ""
            self.last_update_time = 0
            self._last_raw_text = ""
            self._last_processed_raw = ""
            self._stream_start_time = None
            self._confirmed_compact = ""
            self._trailing_suffix = ""
            self._preview_desync_count = 0
            self._preview_ambiguous_skip_count = 0
            self._last_good_raw_compact = ""
            self._is_stopping = False
            self.finalize_timer.stop()
            self._clear_preview()
            self.start_time = time.time()

            # 큐 비우기
            self._clear_message_queue()

            # 실시간 저장 설정 (예외 처리 추가)
            self.realtime_file = None
            if self.realtime_save_check.isChecked():
                try:
                    Path(Config.REALTIME_DIR).mkdir(exist_ok=True)
                    filename = f"{Config.REALTIME_DIR}/자막_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    self.realtime_file = open(
                        filename, "w", encoding="utf-8-sig"
                    )  # BOM 포함 (#12)
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
                daemon=True,
            )
            self.worker.start()

            # 타이머 시작
            self.stats_timer.start(Config.STATS_UPDATE_INTERVAL)
            self.backup_timer.start(Config.AUTO_BACKUP_INTERVAL)

            # 시작 시 자동으로 상단 UI 접기 (사용자 요청)
            if self.top_header_container.isVisible():
                self._toggle_top_header()

        except Exception as e:
            logger.exception(f"시작 오류: {e}")
            # 파일 핸들 정리
            if self.realtime_file:
                try:
                    self.realtime_file.close()
                except Exception as close_err:
                    logger.debug(f"실시간 저장 파일 닫기 오류: {close_err}")
                self.realtime_file = None
            self._reset_ui()
            QMessageBox.critical(self, "오류", f"시작 중 오류 발생: {e}")

    def _stop(self, for_app_exit: bool = False):
        if not self.is_running:
            return

        try:
            self.is_running = False
            self.stop_event.set()  # 워커 스레드에 종료 신호
            self._set_status("중지 중...", "warning")
            self._is_stopping = True

            # 확정 타이머 중지
            self.finalize_timer.stop()

            # 종료 직전 큐 preview 소진 + 마지막 자막 확정
            self._drain_pending_previews(requeue_others=True)
            self._finalize_pending_subtitle()

            force_driver_quit = for_app_exit or (not Config.KEEP_BROWSER_ON_STOP)

            # 앱 종료 또는 브라우저 미유지 설정일 때는 워커 대기 전에 드라이버를 먼저 정리
            if force_driver_quit and self.driver:
                driver = self.driver
                self.driver = None
                self._force_quit_driver_with_timeout(
                    driver, timeout=2.0, source="stop_initial"
                )

            worker_stopped = self._wait_worker_shutdown(
                timeout=Config.THREAD_STOP_TIMEOUT
            )

            # 수동 중지 + 브라우저 유지 모드에서 종료가 지연되면 1회 에스컬레이션
            if not worker_stopped and not force_driver_quit and self.driver:
                logger.warning("워커 스레드 종료 지연 감지 - 드라이버 강제 종료 후 재대기")
                driver = self.driver
                self.driver = None
                self._force_quit_driver_with_timeout(
                    driver, timeout=2.0, source="stop_escalation"
                )
                worker_stopped = self._wait_worker_shutdown(timeout=1.0)

            if not worker_stopped:
                logger.warning("워커 스레드가 시간 내에 종료되지 않음(종료 계속 진행)")

            # 종료 후에도 남아있던 preview 처리
            self._drain_pending_previews(requeue_others=True)
            self._finalize_pending_subtitle()
            self._clear_preview()

            # 실시간 저장 종료
            if self.realtime_file:
                try:
                    self.realtime_file.close()
                except Exception as e:
                    logger.debug(f"파일 닫기 오류: {e}")
                self.realtime_file = None

            # 중지 이후 남아있을 수 있는 detached WebDriver 정리
            self._cleanup_detached_drivers_with_timeout(timeout=2.0)

            self._clear_message_queue()
            self._reset_ui()
            self._set_status("중지됨", "warning")
            self._update_tray_status("⚪ 대기 중")
        except Exception as e:
            logger.error(f"중지 중 오류 발생: {e}")
            self._reset_ui()
        finally:
            self._is_stopping = False

    def _force_quit_driver_with_timeout(
        self, driver, timeout: float = 2.0, source: str = "shutdown"
    ) -> bool:
        """WebDriver quit()를 타임박스로 실행해 UI 스레드 무기한 대기를 방지한다."""
        if not driver:
            return True

        done = threading.Event()
        error_holder = {"error": None}

        def _quit_driver():
            try:
                driver.quit()
            except Exception as e:
                error_holder["error"] = e
            finally:
                done.set()

        threading.Thread(
            target=_quit_driver,
            daemon=True,
            name=f"DriverQuitThread-{source}",
        ).start()

        if not done.wait(timeout=timeout):
            logger.warning(
                "WebDriver 종료 타임아웃 (source=%s, timeout=%.1fs)",
                source,
                timeout,
            )
            return False

        if error_holder["error"] is not None:
            logger.debug(
                "WebDriver 종료 오류 (source=%s): %s",
                source,
                error_holder["error"],
            )
            return False

        return True

    def _wait_worker_shutdown(self, timeout: float) -> bool:
        """워커 스레드 종료를 제한 시간 동안 대기한다."""
        if not self.worker or not self.worker.is_alive():
            return True
        self.worker.join(timeout=timeout)
        return not self.worker.is_alive()

    def _cleanup_detached_drivers_with_timeout(self, timeout: float = 2.0) -> None:
        """분리된(detached) 드라이버를 타임박스로 종료한다."""
        with self._detached_drivers_lock:
            detached_drivers = list(self._detached_drivers)
            self._detached_drivers.clear()

        for idx, drv in enumerate(detached_drivers, start=1):
            self._force_quit_driver_with_timeout(
                drv,
                timeout=timeout,
                source=f"detached_{idx}",
            )

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

    # ========== 워커 스레드 ==========

    def _get_query_param(self, url: str, name: str) -> str:
        """URL 쿼리 파라미터 값 추출 (없으면 빈 문자열)"""
        match = re.search(r"(?:^|[?&])" + re.escape(name) + r"=([^&]*)", url)
        return match.group(1) if match else ""

    def _set_query_param(self, url: str, name: str, value: str) -> str:
        """URL 쿼리 파라미터 설정/교체"""
        base_url = url.strip().rstrip("&")
        pattern = re.compile(r"([?&])" + re.escape(name) + r"=[^&]*")
        if pattern.search(base_url):
            return pattern.sub(
                lambda m: f"{m.group(1)}{name}={value}", base_url, count=1
            )
        sep = "&" if "?" in base_url else "?"
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
        dialog.finished.connect(dialog.deleteLater)
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
                    self._show_toast(
                        f"방송이 선택되었습니다:\n{name}", toast_type="success"
                    )

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
            if resolved_url != original_url and self._get_query_param(
                resolved_url, "xcgcd"
            ):
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
                match = re.search(r"DCM0000([A-Za-z0-9]+)", xcgcd_val)
                if match:
                    code = match.group(1)
                    # 숫자+나머지 패턴 (예: 25224310401 -> 25)
                    num_match = re.match(r"^(\d{2})", code)
                    if num_match:
                        return num_match.group(1)
                    # 문자+나머지 패턴 (예: IO224310401 -> IO)
                    alpha_match = re.match(r"^([A-Za-z]+)", code)
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
                            if (
                                found_xcode
                                and target_xcode_norm
                                and found_xcode.upper() != target_xcode_norm
                            ):
                                logger.warning(
                                    f"JavaScript xcgcd의 xcode({found_xcode})가 target({target_xcode})와 불일치 - 무시"
                                )
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
                        if (
                            found_xcode
                            and target_xcode_norm
                            and found_xcode.upper() != target_xcode_norm
                        ):
                            logger.warning(
                                f"리다이렉트된 xcgcd의 xcode({found_xcode})가 target({target_xcode})와 불일치 - 무시"
                            )
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
                            logger.info(
                                f"페이지 요소에서 xcode={target_xcode} 매칭 xcgcd 발견: {xcgcd}"
                            )
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
                    self.message_queue.put(
                        ("status", "🔍 메인 페이지에서 생중계 목록 확인 중...")
                    )
                    driver.get(main_url)
                    navigated_to_main = True

                    # 동적 콘텐츠 로딩 대기 (최대 10초)
                    try:
                        wait = WebDriverWait(driver, 10)
                        wait.until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, 'a[href*="xcgcd="]')
                            )
                        )
                    except Exception:
                        # 타임아웃 시 기본 대기 (종료 신호에 즉시 반응)
                        self.stop_event.wait(timeout=3)

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
                                bc_xcode = str(bc.get("xcode", "")).strip()
                                if (
                                    target_xcode_norm
                                    and bc_xcode.upper() == target_xcode_norm
                                ):
                                    xcgcd = bc["xcgcd"]
                                    logger.info(
                                        f"xcode={target_xcode} 매칭 성공: xcgcd={xcgcd}"
                                    )
                                    break
                            # target_xcode가 있는데 매칭 실패하면 xcgcd를 설정하지 않음
                            if not xcgcd:
                                logger.warning(
                                    f"xcode={target_xcode}에 해당하는 생중계를 찾지 못함"
                                )
                        else:
                            # target_xcode가 없는 경우(본회의 등)에만 첫 번째 생중계 사용
                            xcgcd = broadcasts[0]["xcgcd"]
                            first_bc = broadcasts[0]
                            logger.info(
                                f"첫 번째 생중계 사용: xcgcd={xcgcd}, text={first_bc.get('text', '')[:30]}"
                            )

                except Exception as e:
                    logger.debug(f"메인 페이지 조회 오류: {e}")

            # 방법 5: 메인 페이지 리다이렉트 시 화면의 '생중계' 버튼 자동 클릭 (개선됨)
            if not xcgcd and target_xcode:
                # 현재 URL이 메인 페이지인지 확인 (player.asp가 아님)
                current_url = driver.current_url
                if "/main/player.asp" not in current_url:
                    try:
                        self.message_queue.put(
                            (
                                "status",
                                f"🖱️ 메인 화면에서 xcode={target_xcode} 버튼 탐색 중...",
                            )
                        )
                        logger.info(
                            f"메인 페이지 리다이렉트 감지 - 버튼 클릭 시도 (xcode={target_xcode})"
                        )

                        # 동적 콘텐츠 로딩 대기 (최대 10초) - onair 클래스가 나타날 때까지
                        try:
                            WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located(
                                    (By.CSS_SELECTOR, ".onair")
                                )
                            )
                        except Exception:
                            logger.debug(
                                "onair 요소 대기 타임아웃 (생중계가 없거나 로딩 지연)"
                            )

                        # 1. onair 버튼 찾기 (xcode 매칭)
                        # 다양한 선택자 시도 - 더 포괄적으로
                        selectors = [
                            f'a.onair[href*="xcode={target_xcode}"]',
                            f'a.btn[href*="xcode={target_xcode}"]',  # onair 클래스가 없을 수도 있음
                            f'div.onair a[href*="xcode={target_xcode}"]',
                            f'a[href*="xcode={target_xcode}"]:has(.icon_onair)',
                            f'a[href*="xcode={target_xcode}"]',  # 최후의 수단: 그냥 링크 찾기
                        ]

                        btn = None
                        for sel in selectors:
                            try:
                                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                                # onair 클래스가 있는 요소 우선 선택
                                for elem in elems:
                                    if "onair" in elem.get_attribute(
                                        "class"
                                    ) or elem.find_elements(By.CSS_SELECTOR, ".onair"):
                                        btn = elem
                                        break

                                if btn:
                                    break

                                # onair가 없더라도 첫 번째 요소 선택 (클릭해보는 것이 나음)
                                if elems and not btn:
                                    btn = elems[0]
                                    break
                            except Exception:
                                continue

                        if btn:
                            # 2. 스크롤하여 요소 보이게 하기
                            driver.execute_script(
                                "arguments[0].scrollIntoView({block: 'center'});", btn
                            )
                            # 스크롤 후 안정화 대기 (종료 신호에 즉시 반응)
                            self.stop_event.wait(timeout=1.0)

                            # 3. 클릭 (JavaScript 사용이 더 안정적)
                            driver.execute_script("arguments[0].click();", btn)
                            logger.info(
                                f"메인 페이지에서 생중계 버튼 자동 클릭 성공: xcode={target_xcode}"
                            )
                            self.message_queue.put(
                                ("status", "✅ 생중계 버튼 자동 클릭 성공")
                            )

                            # 4. 페이지 전환 대기
                            try:
                                WebDriverWait(driver, 5).until(
                                    lambda d: "player.asp" in d.current_url
                                )
                                # 페이지 전환 후 URL 반환
                                return driver.current_url
                            except Exception:
                                logger.warning("버튼 클릭 후 페이지 전환 타임아웃")
                        else:
                            logger.warning(
                                f"메인 페이지에서 xcode={target_xcode} 생중계 버튼을 찾을 수 없음"
                            )

                    except Exception as e:
                        logger.warning(f"생중계 버튼 클릭 로직 실패: {e}")
                    finally:
                        # 버튼 클릭도 실패한 경우 원래 URL로 복귀
                        # 단, 버튼 클릭으로 페이지가 이동했다면 복귀하지 않음
                        if (
                            navigated_to_main
                            and not xcgcd
                            and "/main/player.asp" not in driver.current_url
                        ):
                            try:
                                # 이미 버튼 클릭 시도로 URL이 바뀌었을 수 있으므로 체크
                                if original_url not in driver.current_url:
                                    driver.get(original_url)
                                    self.stop_event.wait(timeout=2)
                                    logger.info(f"원래 URL로 복귀: {original_url}")
                            except Exception as e:
                                logger.debug(f"원래 URL 복귀 실패: {e}")

            # xcgcd를 찾았으면 URL 업데이트 (유효성 검증 포함)
            if (
                xcgcd and len(xcgcd) >= 10
            ):  # 최소 길이 검증 (유효한 xcgcd는 보통 20자 이상)
                new_url = self._set_query_param(original_url, "xcgcd", xcgcd)
                if not self._get_query_param(new_url, "xcode"):
                    inferred_xcode = target_xcode or extract_xcode_from_xcgcd(xcgcd)
                    if inferred_xcode:
                        new_url = self._set_query_param(
                            new_url, "xcode", inferred_xcode
                        )

                display_xcgcd = xcgcd[:15] + "..." if len(xcgcd) > 15 else xcgcd
                self.message_queue.put(
                    ("status", f"✅ 생중계 감지 성공! (xcgcd={display_xcgcd})")
                )
                logger.info(f"생중계 URL 업데이트: {new_url}")
                return new_url
            else:
                # target_xcode 정보를 포함하여 더 구체적인 메시지 표시
                target_xcode = (
                    self._get_query_param(original_url, "xcode").strip() or None
                )

                if target_xcode:
                    self.message_queue.put(
                        (
                            "status",
                            f"⚠️ xcode={target_xcode} 위원회의 진행 중인 생중계를 찾을 수 없음",
                        )
                    )
                    logger.warning(
                        f"xcode={target_xcode}에 해당하는 생중계가 없음, 원래 URL 사용"
                    )
                else:
                    self.message_queue.put(
                        ("status", "⚠️ 생중계 정보를 찾을 수 없음 - 기본 URL 사용")
                    )
                    logger.warning("생중계 xcgcd를 찾을 수 없음, 원래 URL 사용")
                return original_url

        except Exception as e:
            logger.error(f"생중계 감지 오류: {e}")
            self.message_queue.put(("status", f"⚠️ 생중계 감지 실패: {e}"))
            return original_url

    def _get_reconnect_delay(self, attempt: int) -> float:
        """지수 백오프 기반 재연결 대기 시간(초) 계산"""
        if attempt <= 0:
            return 0.0
        delay = Config.RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
        return min(delay, Config.RECONNECT_MAX_DELAY)

    def _is_recoverable_webdriver_error(self, error: Exception) -> bool:
        """재연결로 복구 가능한 웹드라이버 오류인지 판단"""
        msg = str(error).lower()
        markers = [
            "invalid session",
            "no such execution context",
            "chrome not reachable",
            "disconnected",
            "target closed",
            "session deleted",
            "connection reset",
            "connection refused",
            "web view not found",
        ]
        return any(marker in msg for marker in markers)

    def _ping_driver(self, driver):
        """웹드라이버 응답 시간을 측정 (ms). 실패 시 None 반환."""
        start = time.time()
        try:
            driver.execute_script("return 1")
        except Exception:
            return None
        return int((time.time() - start) * 1000)

    def _extraction_worker(self, url, selector, headless):
        """자막 추출 워커 스레드 (Legacy Logic Restoration)"""
        driver = None

        try:
            options = Options()
            options.add_argument("--log-level=3")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option(
                "excludeSwitches", ["enable-logging", "enable-automation"]
            )
            options.add_experimental_option("useAutomationExtension", False)

            # 헤드리스 모드
            if headless:
                options.add_argument("--headless=new")
                options.add_argument("--window-size=1280,720")
                self.message_queue.put(("status", "헤드리스 모드로 시작 중..."))

            try:
                driver = webdriver.Chrome(options=options)
                self.driver = driver
                self.message_queue.put(("status", "Chrome 시작 완료"))
            except Exception as e:
                self.message_queue.put(("error", f"Chrome 오류: {e}"))
                return

            self.message_queue.put(("status", "페이지 로딩 중..."))
            driver.get(url)
            self.stop_event.wait(timeout=3)

            self.message_queue.put(("status", "AI 자막 활성화 중..."))
            self._activate_subtitle(driver)

            self.message_queue.put(("status", "자막 요소 검색 중..."))
            wait = WebDriverWait(driver, 20)

            found = False
            selector_candidates = self._build_subtitle_selector_candidates(selector)
            active_selector = ""
            for sel in selector_candidates:
                try:
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    self.message_queue.put(("status", f"자막 요소 찾음: {sel}"))
                    active_selector = sel
                    found = True
                    break
                except Exception:
                    continue

            if not found:
                detected_selector = self._find_subtitle_selector(driver)
                if detected_selector:
                    selector_candidates = self._build_subtitle_selector_candidates(
                        detected_selector, selector_candidates
                    )
                    active_selector = selector_candidates[0]
                    self.message_queue.put(
                        ("status", f"자막 요소 자동 감지: {active_selector}")
                    )
                    found = True

            if not found:
                self.message_queue.put(("error", "자막 요소를 찾을 수 없습니다."))
                return

            self.message_queue.put(("status", "자막 모니터링 중"))

            # MutationObserver 주입 (하이브리드 아키텍처)
            observer_active, observer_frame_path = self._inject_mutation_observer(
                driver, ",".join(selector_candidates)
            )
            observer_retry_interval = 3.0
            last_observer_retry = time.time()
            last_selector_refresh = time.time()

            last_check = time.time()
            last_connection_check = time.time()
            # [Fix] 지역 변수로 변경 - 스레드 안전성 확보 (Race condition 방지)
            worker_last_raw_text = ""
            worker_last_raw_compact = ""
            reconnect_attempt = 0

            # stop_event 사용으로 더 빠른 종료 응답
            while not self.stop_event.is_set():
                try:
                    now = time.time()

                    # 연결 상태 모니터링 (#5) - 5초마다 체크
                    if now - last_connection_check >= 5.0:
                        ping_time = self._ping_driver(driver)
                        if ping_time is not None:
                            self.message_queue.put(
                                (
                                    "connection_status",
                                    {"status": "connected", "latency": ping_time},
                                )
                            )
                            reconnect_attempt = 0  # 연결 성공 시 재연결 횟수 초기화
                        else:
                            self.message_queue.put(
                                ("connection_status", {"status": "disconnected"})
                            )
                        last_connection_check = now

                    if now - last_check >= 0.2:
                        changes_processed = False

                        # 1단계: MutationObserver 버퍼에서 수집 (이벤트 기반)
                        if observer_active:
                            observer_changes = self._collect_observer_changes(
                                driver, observer_frame_path
                            )
                            if observer_changes is None:
                                # Observer가 죽었으면 비활성화 후 폴링 fallback
                                observer_active = False
                                logger.warning("MutationObserver 비활성화, 폴링 fallback")
                            elif observer_changes:
                                for change_text in observer_changes:
                                    # 클리어 마커 감지 (발언자 전환)
                                    if change_text == "__SUBTITLE_CLEARED__":
                                        self.message_queue.put(
                                            ("subtitle_reset", "observer_cleared")
                                        )
                                        worker_last_raw_text = ""
                                        worker_last_raw_compact = ""
                                        continue
                                    c_text = utils.clean_text_display(change_text)
                                    c_compact = utils.compact_subtitle_text(c_text)
                                    if (
                                        c_text
                                        and c_compact
                                        and c_compact != worker_last_raw_compact
                                    ):
                                        worker_last_raw_text = c_text
                                        worker_last_raw_compact = c_compact
                                        self.message_queue.put(("preview", c_text))
                                        changes_processed = True

                        # 2단계: Observer 결과가 없으면 기존 폴링 fallback
                        if not changes_processed:
                            text, matched_selector, selector_found = (
                                self._read_subtitle_text_by_selectors(
                                    driver, selector_candidates
                                )
                            )
                            if selector_found:
                                reconnect_attempt = 0
                                if matched_selector and matched_selector != active_selector:
                                    active_selector = matched_selector
                                    selector_candidates = (
                                        self._build_subtitle_selector_candidates(
                                            active_selector, selector_candidates
                                        )
                                    )
                            elif now - last_selector_refresh >= 5.0:
                                # 셀렉터 변화 대응: 주기적 자동 재탐색
                                detected_selector = self._find_subtitle_selector(driver)
                                if detected_selector:
                                    selector_candidates = (
                                        self._build_subtitle_selector_candidates(
                                            detected_selector, selector_candidates
                                        )
                                    )
                                    active_selector = selector_candidates[0]
                                    logger.info(
                                        "자막 셀렉터 자동 전환: %s", active_selector
                                    )
                                last_selector_refresh = now

                            if (
                                not observer_active
                                and now - last_observer_retry >= observer_retry_interval
                            ):
                                observer_active, observer_frame_path = self._inject_mutation_observer(
                                    driver, ",".join(selector_candidates)
                                )
                                last_observer_retry = now

                            text = utils.clean_text_display(text)
                            text_compact = utils.compact_subtitle_text(text)

                            if (
                                text
                                and text_compact
                                and text_compact != worker_last_raw_compact
                            ):
                                worker_last_raw_text = text
                                worker_last_raw_compact = text_compact
                                self.message_queue.put(("preview", text))
                            elif (
                                not text
                                and selector_found
                                and worker_last_raw_compact
                            ):
                                # 폴링에서도 빈 텍스트 감지 (발언자 전환)
                                self.message_queue.put(
                                    ("subtitle_reset", "polling_cleared")
                                )
                                worker_last_raw_text = ""
                                worker_last_raw_compact = ""

                        last_check = now

                    # stop_event 대기 (0.05초, 즉시 응답 가능)
                    self.stop_event.wait(timeout=0.05)

                except Exception as e:
                    if self.stop_event.is_set():
                        break

                    # 자동 재연결 로직 (#4)
                    if (
                        self.auto_reconnect_enabled
                        and self._is_recoverable_webdriver_error(e)
                    ):
                        reconnect_attempt += 1
                        if reconnect_attempt <= Config.MAX_RECONNECT_ATTEMPTS:
                            delay = self._get_reconnect_delay(reconnect_attempt)
                            self.message_queue.put(
                                (
                                    "reconnecting",
                                    {
                                        "attempt": reconnect_attempt,
                                        "max_attempts": Config.MAX_RECONNECT_ATTEMPTS,
                                        "delay": delay,
                                    },
                                )
                            )
                            logger.warning(
                                f"WebDriver 연결 오류, {delay}초 후 재연결 시도 ({reconnect_attempt}/{Config.MAX_RECONNECT_ATTEMPTS})"
                            )

                            # 기존 드라이버 정리
                            if driver:
                                try:
                                    driver.quit()
                                except Exception as quit_err:
                                    logger.debug(
                                        f"드라이버 종료 실패, detached 목록에 추가: {quit_err}"
                                    )
                                    with self._detached_drivers_lock:
                                        self._detached_drivers.append(driver)

                            # 대기 후 재연결 (종료 신호에 즉시 반응)
                            if self.stop_event.wait(timeout=delay):
                                break

                            try:
                                driver = webdriver.Chrome(options=options)
                                self.driver = driver
                                driver.get(url)
                                if self.stop_event.wait(timeout=2):
                                    break
                                self._activate_subtitle(driver)
                                self.message_queue.put(
                                    (
                                        "status",
                                        f"✅ 재연결 성공 (시도 {reconnect_attempt})",
                                    )
                                )
                                self.message_queue.put(
                                    ("connection_status", {"status": "connected"})
                                )
                                last_check = time.time()
                                last_connection_check = time.time()
                                detected_selector = self._find_subtitle_selector(driver)
                                if detected_selector:
                                    selector_candidates = (
                                        self._build_subtitle_selector_candidates(
                                            detected_selector, selector_candidates
                                        )
                                    )
                                    active_selector = selector_candidates[0]
                                # 재연결 후 MutationObserver 재주입
                                observer_active, observer_frame_path = self._inject_mutation_observer(
                                    driver, ",".join(selector_candidates)
                                )
                                last_observer_retry = time.time()
                                continue
                            except Exception as reconnect_error:
                                logger.error(f"재연결 실패: {reconnect_error}")
                        else:
                            self.message_queue.put(
                                (
                                    "error",
                                    f"최대 재연결 시도 횟수({Config.MAX_RECONNECT_ATTEMPTS}) 초과",
                                )
                            )
                            break
                    else:
                        # 복구 불가능한 오류
                        logger.warning(f"모니터링 중 오류: {e}")
                        self.stop_event.wait(timeout=0.5)

        except Exception as e:
            if not self.stop_event.is_set():
                self.message_queue.put(("error", str(e)))

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as e:
                    logger.debug(f"WebDriver 종료 오류: {e}")
                self.driver = None
            self.message_queue.put(("finished", ""))

    def _build_subtitle_selector_candidates(
        self, primary_selector: str, extras: list[str] | None = None
    ) -> list[str]:
        """우선순위가 반영된 자막 CSS 셀렉터 후보 목록을 생성한다."""
        candidates = []

        def _add(sel: str) -> None:
            if not isinstance(sel, str):
                return
            norm = sel.strip()
            if not norm or norm in candidates:
                return
            candidates.append(norm)

        _add(primary_selector or "")
        for sel in [
            "#viewSubtit .smi_word:last-child",
            "#viewSubtit .smi_word",
            "#viewSubtit .incont",
            "#viewSubtit span",
            "#viewSubtit",
            ".subtitle_area",
            ".ai_subtitle",
            "[class*='subtitle']",
        ]:
            _add(sel)

        if extras:
            for sel in extras:
                _add(sel)

        # 컨테이너형 셀렉터보다 실제 자막 라인(.smi_word)을 우선한다.
        broad_selectors = {
            "#viewSubtit .incont",
            "#viewSubtit",
            ".subtitle_area",
            ".ai_subtitle",
            "[class*='subtitle']",
        }
        priority = {
            "#viewSubtit .smi_word:last-child": 0,
            "#viewSubtit .smi_word": 1,
            "#viewSubtit span": 2,
            "#viewSubtit .incont": 7,
            "#viewSubtit": 8,
            ".subtitle_area": 9,
            ".ai_subtitle": 10,
            "[class*='subtitle']": 11,
        }
        primary_norm = (primary_selector or "").strip()

        order_map = {sel: idx for idx, sel in enumerate(candidates)}

        def _weight(sel: str) -> tuple[int, int]:
            original_idx = order_map.get(sel, 999)
            if sel in priority:
                return priority[sel], original_idx
            if sel == primary_norm and sel not in broad_selectors:
                return 3, original_idx
            if sel in broad_selectors:
                return 12, original_idx
            return 4, original_idx

        return sorted(candidates, key=_weight)

    def _join_stream_text(self, base: str, addition: str) -> str:
        """스트리밍 텍스트를 공백/문장부호를 보존해 결합한다."""
        left = str(base or "")
        right = str(addition or "")
        if not left:
            return right.strip()
        if not right:
            return left.strip()

        left = left.rstrip()
        right = right.lstrip()
        if not left:
            return right
        if not right:
            return left

        no_space_before = set(".,!?;:)]}%\"'”’…")
        no_space_after = set("([{<\"'“‘")
        if right[0] in no_space_before or left[-1] in no_space_after:
            return left + right
        return left + " " + right

    def _read_subtitle_text_by_selectors(
        self,
        driver,
        selectors: list[str],
        preferred_frame_path: tuple[int, ...] = (),
    ) -> tuple[str, str, bool]:
        """여러 셀렉터를 순차 시도해 자막 텍스트를 읽는다.

        Returns:
            (text, matched_selector, found_element)
        """
        def _read_in_current_context() -> tuple[str, str, bool]:
            for sel in selectors:
                try:
                    element = driver.find_element(By.CSS_SELECTOR, sel)
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
                except Exception as e:
                    logger.debug("셀렉터 조회 오류 (%s): %s", sel, e)
                    continue

                try:
                    text = (element.text or "").strip()
                except StaleElementReferenceException:
                    continue
                except Exception:
                    text = ""
                return text, sel, True
            return "", "", False

        # 선호 프레임(Observer가 설치된 프레임)을 우선 확인
        if preferred_frame_path:
            try:
                if self._switch_to_frame_path(driver, preferred_frame_path):
                    result = _read_in_current_context()
                    if result[2]:
                        self._last_subtitle_frame_path = preferred_frame_path
                        return result
            finally:
                driver.switch_to.default_content()

        # 기본 문서 확인
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        result = _read_in_current_context()
        if result[2]:
            self._last_subtitle_frame_path = ()
            return result

        # 중첩 iframe/frame 순회 확인
        for frame_path in self._iter_frame_paths(driver, max_depth=3, max_frames=60):
            try:
                if self._switch_to_frame_path(driver, frame_path):
                    result = _read_in_current_context()
                    if result[2]:
                        self._last_subtitle_frame_path = frame_path
                        return result
            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass

        return "", "", False

    def _switch_to_frame_path(self, driver, frame_path: tuple[int, ...]) -> bool:
        """frame index 경로로 이동한다. 실패 시 False."""
        try:
            driver.switch_to.default_content()
        except Exception:
            return False

        for idx in frame_path:
            try:
                frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
                if idx < 0 or idx >= len(frames):
                    return False
                driver.switch_to.frame(frames[idx])
            except Exception:
                return False
        return True

    def _iter_frame_paths(
        self, driver, max_depth: int = 3, max_frames: int = 60
    ) -> list[tuple[int, ...]]:
        """중첩 iframe/frame 경로 목록을 반환한다."""
        paths: list[tuple[int, ...]] = []

        def _walk(path: tuple[int, ...], depth: int) -> None:
            if len(paths) >= max_frames or depth > max_depth:
                return
            if not self._switch_to_frame_path(driver, path):
                return
            try:
                frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
            except Exception:
                return

            for idx in range(len(frames)):
                child = path + (idx,)
                paths.append(child)
                if len(paths) >= max_frames:
                    return
                _walk(child, depth + 1)

        try:
            _walk((), 0)
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

        return paths

    def _inject_mutation_observer_here(
        self, driver, selector: str, allow_poll_fallback: bool = False
    ) -> bool:
        """현재 문맥(현재 frame)에서 Observer를 주입한다."""
        default_selector = (
            "#viewSubtit .smi_word:last-child, #viewSubtit .smi_word, "
            "#viewSubtit .incont, #viewSubtit, .subtitle_area"
        )
        safe_selector = (
            selector if isinstance(selector, str) and selector.strip() else default_selector
        )
        result = driver.execute_script(
            """
            return (function(selectorArg, allowPollFallbackArg) {
                if (window.__subtitleObserver) {
                    try { window.__subtitleObserver.disconnect(); } catch(e) {}
                }
                if (window.__subtitlePollTimer) {
                    try { clearInterval(window.__subtitlePollTimer); } catch(e) {}
                    window.__subtitlePollTimer = null;
                }
                window.__subtitleBuffer = [];
                window.__subtitleLastText = '';
                window.__subtitleLastEmitTs = 0;

                var rawSelector = (typeof selectorArg === 'string') ? selectorArg : '';
                var allowPollFallback = !!allowPollFallbackArg;
                var selectors = rawSelector
                    .split(',')
                    .map(function(s) { return (s || '').trim(); })
                    .filter(function(s) { return s.length > 0; });
                if (!selectors.length) {
                    selectors = [
                        '#viewSubtit .smi_word:last-child',
                        '#viewSubtit .smi_word',
                        '#viewSubtit .incont',
                        '#viewSubtit',
                        '.subtitle_area',
                        '.ai_subtitle',
                        "[class*='subtitle']"
                    ];
                }

                var target = null;
                for (var i = 0; i < selectors.length; i++) {
                    try {
                        target = document.querySelector(selectors[i]);
                    } catch (e) {
                        target = null;
                    }
                    if (target) break;
                }

                function normalizeText(text) {
                    return String(text || '').replace(/\\s+/g, ' ').trim();
                }

                function isLikelySubtitleText(text) {
                    if (!text) return false;
                    if (text.length < 3 || text.length > 320) return false;
                    if (!/[가-힣A-Za-z]/.test(text)) return false;
                    if (/^[\\d\\s:.,\\-_/()%]+$/.test(text)) return false;
                    return true;
                }

                function pickBestMutationText(mutations) {
                    var bestText = '';
                    var bestScore = -1;
                    for (var i = 0; i < mutations.length; i++) {
                        var m = mutations[i];
                        var node = m && m.target ? m.target : null;
                        var el = null;
                        if (node && node.nodeType === 1) el = node;
                        else if (node && node.parentElement) el = node.parentElement;
                        if (!el) continue;
                        if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
                        if (typeof el.closest === 'function') {
                            var bad = el.closest('script,style,head,noscript');
                            if (bad) continue;
                        }

                        var text = normalizeText(el.innerText || el.textContent || '');
                        if (!isLikelySubtitleText(text)) continue;

                        if (text.length > 120) {
                            var lines = String(el.innerText || '').split('\\n')
                                .map(function(v) { return normalizeText(v); })
                                .filter(function(v) { return !!v; });
                            if (lines.length) {
                                var tail = lines[lines.length - 1];
                                if (isLikelySubtitleText(tail)) text = tail;
                            }
                        }

                        var score = 0;
                        try {
                            var idClass = ((el.id || '') + ' ' + (el.className || '')).toLowerCase();
                            if (/subtit|subtitle|caption|script|stt|transcript|incont|viewsubtit/.test(idClass)) score += 6;
                            var rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
                            if (rect && rect.width > 0 && rect.height > 0) score += 2;
                            if (rect && rect.bottom >= (window.innerHeight * 0.35)) score += 1;
                        } catch (e) {}

                        score += Math.min(4, Math.floor(text.length / 25));

                        if (score > bestScore) {
                            bestScore = score;
                            bestText = text;
                        }
                    }
                    return bestText;
                }

                if (target) {
                    window.__subtitleObserver = new MutationObserver(function() {
                        try {
                            var text = target.innerText || target.textContent || '';
                            text = normalizeText(text);
                            if (!text && window.__subtitleLastText) {
                                window.__subtitleBuffer.push('__SUBTITLE_CLEARED__');
                                window.__subtitleLastText = '';
                                return;
                            }
                            if (text && text !== window.__subtitleLastText) {
                                window.__subtitleLastText = text;
                                window.__subtitleBuffer.push(text);
                                if (window.__subtitleBuffer.length > 100) {
                                    window.__subtitleBuffer = window.__subtitleBuffer.slice(-50);
                                }
                            }
                        } catch (e) {}
                    });

                    window.__subtitleObserver.observe(target, {
                        childList: true,
                        subtree: true,
                        characterData: true,
                        attributes: true
                    });
                    return true;
                }

                var root = document.body || document.documentElement;
                if (!root || !allowPollFallback) return false;

                // 타겟을 못 찾은 경우: 주기적 selector 스캔으로 Observer 버퍼 브리지
                window.__subtitlePollTimer = setInterval(function() {
                    try {
                        var now = Date.now();
                        if (now - (window.__subtitleLastEmitTs || 0) < 100) {
                            return;
                        }
                        var liveTarget = null;
                        for (var i = 0; i < selectors.length; i++) {
                            try {
                                liveTarget = document.querySelector(selectors[i]);
                            } catch (e) {
                                liveTarget = null;
                            }
                            if (liveTarget) break;
                        }
                        if (!liveTarget) {
                            return;
                        }

                        var text = normalizeText(liveTarget.innerText || liveTarget.textContent || '');
                        if (!text && window.__subtitleLastText) {
                            window.__subtitleBuffer.push('__SUBTITLE_CLEARED__');
                            window.__subtitleLastText = '';
                            window.__subtitleLastEmitTs = now;
                            return;
                        }
                        if (!text || !isLikelySubtitleText(text)) {
                            return;
                        }
                        if (text && text !== window.__subtitleLastText) {
                            window.__subtitleLastText = text;
                            window.__subtitleLastEmitTs = now;
                            window.__subtitleBuffer.push(text);
                            if (window.__subtitleBuffer.length > 100) {
                                window.__subtitleBuffer = window.__subtitleBuffer.slice(-50);
                            }
                        }
                    } catch (e) {
                    }
                }, 180);
                return true;
            })(arguments[0], arguments[1]);
            """,
            safe_selector,
            allow_poll_fallback,
        )
        return bool(result)

    def _inject_mutation_observer(self, driver, selector: str) -> tuple[bool, tuple[int, ...]]:
        """MutationObserver를 페이지에 주입하여 자막 변경을 이벤트 기반으로 캡처한다.

        Returns:
            (주입 성공 여부, observer frame 경로)
        """
        try:
            safe_selector = selector if isinstance(selector, str) else ""
            priority_paths: list[tuple[int, ...]] = []
            last_path = getattr(self, "_last_subtitle_frame_path", ())
            if isinstance(last_path, tuple):
                priority_paths.append(last_path)
            priority_paths.append(())
            for p in self._iter_frame_paths(driver, max_depth=3, max_frames=60):
                if p not in priority_paths:
                    priority_paths.append(p)

            # 1) 타겟 기반 Observer 우선 시도
            for frame_path in priority_paths:
                if not self._switch_to_frame_path(driver, frame_path):
                    continue
                if self._inject_mutation_observer_here(
                    driver, safe_selector, allow_poll_fallback=False
                ):
                    location = "default" if frame_path == () else f"frame={frame_path}"
                    logger.info(
                        "MutationObserver 주입 성공: %s (%s)", location, safe_selector
                    )
                    return True, frame_path

            # 2) 타겟 미탐색 시 JS 폴링 브리지 fallback
            for frame_path in priority_paths:
                if not self._switch_to_frame_path(driver, frame_path):
                    continue
                if self._inject_mutation_observer_here(
                    driver, safe_selector, allow_poll_fallback=True
                ):
                    location = "default" if frame_path == () else f"frame={frame_path}"
                    logger.info(
                        "MutationObserver 폴링 브리지 활성화: %s (%s)",
                        location,
                        safe_selector,
                    )
                    return True, frame_path

            logger.warning("MutationObserver 주입 실패: 대상 요소 없음 (%s)", safe_selector)
            return False, ()
        except Exception as e:
            logger.warning("MutationObserver 주입 오류: %s", e)
            return False, ()
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    def _collect_observer_changes(
        self, driver, frame_path: tuple[int, ...] = ()
    ) -> list | None:
        """MutationObserver 버퍼에서 변경된 텍스트를 수집한다.

        Returns:
            list: 변경된 텍스트 목록 (비어있을 수 있음)
            None: Observer가 죽었거나 오류 발생 (폴링 fallback 필요)
        """
        try:
            if not self._switch_to_frame_path(driver, frame_path):
                return None
            result = driver.execute_script(
                """
                if (!window.__subtitleBuffer) return null;
                var buf = window.__subtitleBuffer;
                window.__subtitleBuffer = [];
                return buf;
                """
            )
            if result is None:
                return None  # Observer가 없음
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.debug("Observer 버퍼 수집 오류: %s", e)
            return None
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

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
        for idx, script in enumerate(activation_scripts, start=1):
            try:
                result = driver.execute_script(script)
                if result:
                    logger.info(
                        "자막 활성화 성공 (step=%s/%s): %s...",
                        idx,
                        len(activation_scripts),
                        script[:50],
                    )
                    activated = True
                    break
                self.stop_event.wait(timeout=0.5)
            except Exception as e:
                logger.debug(f"자막 활성화 스크립트 실패: {e}")

        # 추가 대기 - 자막 레이어 로딩 (종료 신호에 즉시 반응)
        self.stop_event.wait(timeout=2.0)
        return activated

    def _find_subtitle_selector(self, driver) -> str:
        """사용 가능한 자막 셀렉터 자동 감지

        Returns:
            str: 찾은 셀렉터. 찾지 못하면 빈 문자열.
        """
        # 우선순위대로 셀렉터 확인
        selectors = [
            "#viewSubtit .smi_word:last-child",
            "#viewSubtit .smi_word",
            "#viewSubtit .incont",
            "#viewSubtit span",
            "#viewSubtit",
            ".subtitle_area",
            ".ai_subtitle",
            "[class*='subtitle']",
        ]

        text, matched_selector, found = self._read_subtitle_text_by_selectors(
            driver, selectors
        )
        if found and matched_selector:
            if text and len(text) > 2:
                logger.info(f"자막 셀렉터 발견: {matched_selector}")
            return matched_selector
        return ""

    def _clear_message_queue(self) -> None:
        """메시지 큐 비우기 (중지/재시작 안정성용)"""
        try:
            while True:
                self.message_queue.get_nowait()
        except queue.Empty:
            pass

    def _process_subtitle_segments(self, data) -> None:
        """세그먼트 형태로 들어온 자막 데이터를 처리한다."""
        if not data:
            return
        if isinstance(data, (list, tuple)):
            for item in data:
                if item:
                    prepared = self._prepare_preview_raw(item)
                    if prepared:
                        self._process_raw_text(prepared)
            return
        if isinstance(data, str):
            prepared = self._prepare_preview_raw(data)
            if prepared:
                self._process_raw_text(prepared)

    def _prepare_preview_raw(self, raw):
        """preview 입력을 정규화/게이팅하여 core 알고리즘에 전달할지 결정한다."""
        if raw is None:
            return None

        normalized = utils.clean_text_display(str(raw)).strip()
        if not normalized:
            return None

        raw_compact = utils.compact_subtitle_text(normalized)
        if not raw_compact:
            return None

        def accept(text: str):
            self._preview_desync_count = 0
            self._preview_ambiguous_skip_count = 0
            self._last_good_raw_compact = raw_compact
            return text

        suffix = self._trailing_suffix
        if not suffix:
            return accept(normalized)

        first_pos = raw_compact.find(suffix)
        if first_pos < 0:
            # 1차 fallback: 직전 raw 대비 증분(delta)만 추출
            delta = self._extract_stream_delta(normalized, self._last_raw_text)
            if isinstance(delta, str):
                delta = delta.strip()
                if len(delta) >= 1 and len(delta) < len(normalized):
                    return accept(delta)
                if not delta:
                    pass

            # 2차 fallback: 최근 확정 히스토리 tail anchor로 증분 추출
            history_anchor = self._confirmed_history_compact_tail(
                max_entries=8, max_compact_len=3000
            )
            incremental = self._slice_incremental_part(
                normalized,
                history_anchor,
                raw_compact,
                min_anchor=20,
                min_overlap=8,
            )
            if isinstance(incremental, str):
                incremental = incremental.strip()
                if len(incremental) >= 1 and len(incremental) < len(normalized):
                    return accept(incremental)
                if not incremental:
                    return None

            self._preview_desync_count += 1
            if self._preview_desync_count >= self._preview_resync_threshold:
                logger.warning(
                    "preview suffix desync reset: count=%s", self._preview_desync_count
                )
                self._soft_resync()
                return accept(normalized)
            return None

        last_pos = raw_compact.rfind(suffix)
        if first_pos != last_pos:
            predicted_append = len(raw_compact) - (first_pos + len(suffix))
            large_append_threshold = max(200, len(raw_compact) // 3)
            if predicted_append > large_append_threshold:
                incremental = self._slice_incremental_part(
                    normalized,
                    suffix,
                    raw_compact,
                    min_anchor=20,
                    min_overlap=8,
                )
                if isinstance(incremental, str):
                    incremental = incremental.strip()
                    if len(incremental) >= 1 and len(incremental) < len(normalized):
                        return accept(incremental)
                    if not incremental:
                        return None

                self._preview_ambiguous_skip_count += 1
                if (
                    self._preview_ambiguous_skip_count
                    >= self._preview_ambiguous_resync_threshold
                ):
                    logger.warning(
                        "preview ambiguous suffix reset: count=%s, predicted_append=%s",
                        self._preview_ambiguous_skip_count,
                        predicted_append,
                    )
                    self._soft_resync()
                    return accept(normalized)
                return None

        return accept(normalized)

    def _drain_pending_previews(
        self, max_items: int = 2000, requeue_others: bool = True
    ) -> None:
        """큐에 남은 preview/segments 메시지를 소진해 마지막 자막 누락을 줄인다."""
        drained = 0
        pending = []
        try:
            while drained < max_items:
                msg_type, data = self.message_queue.get_nowait()
                if msg_type == "preview":
                    prepared = self._prepare_preview_raw(data)
                    if prepared:
                        self._process_raw_text(prepared)
                    elif data:
                        forced = utils.clean_text_display(str(data)).strip()
                        if forced:
                            self._process_raw_text(forced)
                elif msg_type == "subtitle_segments":
                    self._process_subtitle_segments(data)
                else:
                    pending.append((msg_type, data))
                drained += 1
        except queue.Empty:
            pass

        if drained >= max_items:
            logger.warning("preview 큐 소진 제한 도달: max_items=%s", max_items)

        if requeue_others and pending:
            for item in pending:
                self.message_queue.put(item)

    def _finalize_pending_subtitle(self) -> None:
        """남아있는 버퍼를 확정 처리 (종료/중지 안전성용)."""
        if self.last_subtitle:
            self._finalize_subtitle(self.last_subtitle)
            self.last_subtitle = ""
            self._stream_start_time = None
            self._clear_preview()

    def _reset_stream_state_after_subtitle_change(
        self, keep_history_from_subtitles: bool
    ) -> None:
        """외부 편집/로드 후 스트리밍 파이프라인 상태를 재동기화한다."""
        self.last_subtitle = ""
        self._stream_start_time = None
        self._last_raw_text = ""
        self._last_processed_raw = ""
        self._preview_desync_count = 0
        self._preview_ambiguous_skip_count = 0
        self._last_good_raw_compact = ""
        self.finalize_timer.stop()
        self._clear_preview()

        if keep_history_from_subtitles:
            self._soft_resync()
        else:
            self._confirmed_compact = ""
            self._trailing_suffix = ""

    def _replace_subtitles_and_refresh(
        self, new_subtitles: list, keep_history_from_subtitles: bool | None = None
    ) -> None:
        """자막 전체 교체 후 상태/통계/UI를 일관되게 갱신한다."""
        if keep_history_from_subtitles is None:
            keep_history_from_subtitles = bool(new_subtitles)

        with self.subtitle_lock:
            self.subtitles = list(new_subtitles)

        self._reset_stream_state_after_subtitle_change(
            keep_history_from_subtitles=keep_history_from_subtitles
        )
        self._rebuild_stats_cache()
        self._refresh_text(force_full=True)
        self._update_count_label()

    def _check_finalize(self):
        """현재 스트리밍 알고리즘에서는 finalize 타이머를 사용하지 않는다."""
        if self.finalize_timer.isActive():
            self.finalize_timer.stop()

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
            if self._is_stopping and msg_type not in (
                "db_task_result",
                "db_task_error",
                "session_save_done",
                "session_save_failed",
                "session_load_done",
                "session_load_failed",
                "session_load_json_error",
            ):
                return
            if msg_type == "status":
                status_text = str(data)[:200]
                if status_text != self._last_status_message:
                    self.status_label.setText(status_text)
                    self._last_status_message = status_text

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
                prepared = self._prepare_preview_raw(data)
                if prepared:
                    self._process_raw_text(prepared)

            elif msg_type == "subtitle_reset":
                # 발언자 전환으로 자막 영역이 클리어됨 → 완전 리셋
                # (자막 영역이 빈 상태이므로 중복 유입 위험 없음)
                logger.info("subtitle_reset 감지: %s", data)
                # 이전 발언자의 마지막 버퍼 확정
                if self.last_subtitle:
                    self._finalize_subtitle(self.last_subtitle)
                    self.last_subtitle = ""
                    self._stream_start_time = None
                self._confirmed_compact = ""
                self._trailing_suffix = ""
                self._last_raw_text = ""
                self._last_processed_raw = ""
                self._preview_desync_count = 0
                self._preview_ambiguous_skip_count = 0

            elif msg_type == "keepalive":
                self._handle_keepalive(data)

            elif msg_type == "error":
                self.progress.hide()
                self._reset_ui()
                self._update_tray_status("⚪ 대기 중")
                self._update_connection_status("disconnected")
                self._clear_preview()
                QMessageBox.critical(self, "오류", str(data))

            elif msg_type == "finished":
                if self.last_subtitle:
                    self._finalize_subtitle(self.last_subtitle)
                    self.last_subtitle = ""
                    self._stream_start_time = None
                self.finalize_timer.stop()
                self._clear_preview()

                self._refresh_text()
                self._reset_ui()
                self._update_tray_status("⚪ 대기 중")
                self._update_connection_status("disconnected")

                # 스레드 안전하게 통계 계산
                with self.subtitle_lock:
                    subtitle_count = len(self.subtitles)
                total_chars = self._cached_total_chars
                self.status_label.setText(
                    f"완료 - {subtitle_count}문장, {total_chars:,}자"
                )

            elif msg_type == "session_save_done":
                self._session_save_in_progress = False
                info = data if isinstance(data, dict) else {}
                saved_count = int(info.get("saved_count", 0) or 0)
                db_saved = bool(info.get("db_saved", False))
                db_error = str(info.get("db_error", "") or "").strip()
                if db_saved:
                    self._set_status(
                        f"세션 저장 완료 ({saved_count}개, DB 저장 포함)", "success"
                    )
                    self._show_toast("세션 저장 완료! (JSON + DB)", "success")
                else:
                    self._set_status(f"세션 저장 완료 ({saved_count}개)", "success")
                    if db_error:
                        self._show_toast(
                            "세션 저장 완료 (DB 저장은 실패)", "warning", 3500
                        )
                        logger.warning("세션 저장: DB 저장 실패 - %s", db_error)
                    else:
                        self._show_toast("세션 저장 완료!", "success")

            elif msg_type == "session_save_failed":
                self._session_save_in_progress = False
                err = data.get("error") if isinstance(data, dict) else str(data)
                self._set_status(f"세션 저장 실패: {err}", "error")
                QMessageBox.critical(self, "오류", f"세션 저장 실패: {err}")

            elif msg_type == "session_load_done":
                self._session_load_in_progress = False
                payload = data if isinstance(data, dict) else {}
                session_version = str(payload.get("version", "unknown"))
                source_path = str(payload.get("path", ""))
                source_url = str(payload.get("url", "") or "")
                loaded_subtitles = payload.get("subtitles", [])
                skipped_items = int(payload.get("skipped", 0) or 0)

                if session_version != Config.VERSION:
                    reply = QMessageBox.question(
                        self,
                        "버전 불일치",
                        f"세션 버전({session_version})이 현재 버전({Config.VERSION})과 다릅니다.\n"
                        "계속 불러오시겠습니까?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if reply == QMessageBox.StandardButton.No:
                        self._set_status("세션 불러오기 취소됨 (버전 불일치)", "warning")
                        return

                self._replace_subtitles_and_refresh(
                    loaded_subtitles, keep_history_from_subtitles=bool(loaded_subtitles)
                )
                if source_url:
                    self.url_combo.setCurrentText(source_url)

                summary = f"세션 불러오기 완료! {len(self.subtitles)}개 문장"
                if skipped_items > 0:
                    summary += f" (손상 항목 {skipped_items}개 제외)"
                self._set_status(summary, "success")
                self._show_toast(summary, "success")
                if source_path:
                    logger.info("세션 불러오기 완료: %s", source_path)

            elif msg_type == "session_load_json_error":
                self._session_load_in_progress = False
                info = data if isinstance(data, dict) else {}
                path = str(info.get("path", ""))
                err = str(info.get("error", "JSON 파싱 오류"))
                reply = QMessageBox.question(
                    self,
                    "파일 손상",
                    f"세션 파일이 손상되었습니다 (JSON 오류).\n위치: {path}\n오류: {err}\n\n"
                    "백업 폴더를 열어 복구를 시도하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    backup_path = os.path.abspath(Config.BACKUP_DIR)
                    if os.name == "nt":
                        os.startfile(backup_path)
                self._set_status("세션 불러오기 실패 (JSON 오류)", "error")

            elif msg_type == "session_load_failed":
                self._session_load_in_progress = False
                err = data.get("error") if isinstance(data, dict) else str(data)
                self._set_status(f"세션 불러오기 실패: {err}", "error")
                QMessageBox.critical(self, "오류", f"불러오기 실패: {err}")

            elif msg_type == "subtitle_not_found":
                # 자막 요소를 찾지 못했을 때 사용자 안내
                self.progress.hide()
                self._reset_ui()
                self._update_tray_status("⚪ 대기 중")
                self._clear_preview()

                # 상세 안내 다이얼로그
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("자막을 찾을 수 없습니다")
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setText(str(data))
                msg_box.setStandardButtons(
                    QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Ok
                )
                msg_box.button(QMessageBox.StandardButton.Open).setText(
                    "🌐 사이트 열기"
                )
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
                self._show_toast(
                    f"재연결 시도 중... ({self.reconnect_attempts}/{Config.MAX_RECONNECT_ATTEMPTS})",
                    "warning",
                    2000,
                )

            # 재연결 성공 (#31)
            elif msg_type == "reconnected":
                self.reconnect_attempts = 0
                self._update_connection_status("connected")
                self._show_toast("재연결 성공!", "success", 2000)

            elif msg_type == "hwp_save_failed":
                error = data.get("error") if isinstance(data, dict) else data
                self._handle_hwp_save_failure(error)

            elif msg_type == "db_task_result":
                task_name = data.get("task") if isinstance(data, dict) else None
                result = data.get("result") if isinstance(data, dict) else None
                context = data.get("context") if isinstance(data, dict) else {}
                if task_name:
                    self._db_tasks_inflight.discard(task_name)
                    self._handle_db_task_result(task_name, result, context or {})

            elif msg_type == "db_task_error":
                task_name = data.get("task") if isinstance(data, dict) else "db_unknown"
                error = data.get("error") if isinstance(data, dict) else str(data)
                context = data.get("context") if isinstance(data, dict) else {}
                self._db_tasks_inflight.discard(task_name)
                self._handle_db_task_error(task_name, error, context or {})

        except Exception as e:
            logger.error(f"메시지 처리 오류 ({msg_type}): {e}")

    def _handle_keepalive(self, raw: str) -> None:
        """동일 자막이 유지될 때 마지막 엔트리의 end_time을 갱신한다."""
        if not raw:
            return
        # 현재 진행 중인 버퍼가 있으면 확정 이후에만 갱신
        if self.last_subtitle:
            return
        raw_compact = utils.compact_subtitle_text(raw)
        if not raw_compact:
            return

        with self.subtitle_lock:
            if not self.subtitles:
                return
            last_entry = self.subtitles[-1]
            last_compact = utils.compact_subtitle_text(last_entry.text)
            if raw_compact != last_compact:
                return
            last_entry.end_time = datetime.now()

    def _should_merge_entry(
        self, last_entry: SubtitleEntry, new_text: str, now: datetime
    ) -> bool:
        """기존 자막에 이어붙여도 되는지 판단 (단순 시간/길이 체크)"""
        if not last_entry or not new_text:
            return False

        # 마지막 자막과 시간 차이가 너무 크면 분리
        if (
            last_entry.end_time
            and (now - last_entry.end_time).total_seconds() > Config.ENTRY_MERGE_MAX_GAP
        ):
            return False

        # 너무 길어지면 분리
        if len(last_entry.text) + 1 + len(new_text) > Config.ENTRY_MERGE_MAX_CHARS:
            return False

        return True

    def _confirmed_history_compact_tail(
        self, max_entries: int = 10, max_compact_len: int = 3000
    ) -> str:
        """최근 확정 자막들의 compact tail 문자열(겹침/중복 제거용)"""
        with self.subtitle_lock:
            if not self.subtitles:
                return ""
            tail_entries = self.subtitles[-max_entries:]
            combined = " ".join(e.text for e in tail_entries if e and e.text)

        compact = utils.compact_subtitle_text(combined)
        if max_compact_len > 0 and len(compact) > max_compact_len:
            compact = compact[-max_compact_len:]
        return compact

    def _slice_incremental_part(
        self,
        raw: str,
        anchor_compact: str,
        raw_compact: str,
        min_anchor: int = 12,
        min_overlap: int = 4,
    ):
        """anchor 기준으로 raw에서 새로 추가된 부분을 반환한다.

        반환값:
          - None: 겹침 없음 (문맥 전환으로 처리)
          - "": 겹침은 있으나 새 내용 없음
          - str: 새로 추가된 텍스트
        """
        if not raw or not anchor_compact or not raw_compact:
            return None

        # anchor가 길면, raw 내부에서 마지막으로 등장하는 위치를 기준으로 슬라이스
        if len(anchor_compact) >= min_anchor:
            idx = raw_compact.rfind(anchor_compact)
            if idx != -1:
                return utils.slice_from_compact_index(
                    raw, idx + len(anchor_compact)
                ).strip()

        # fallback: suffix-prefix overlap
        overlap_len = utils.find_compact_suffix_prefix_overlap(
            anchor_compact, raw_compact, min_overlap=min_overlap
        )
        if overlap_len > 0:
            return utils.slice_from_compact_index(raw, overlap_len).strip()

        return None

    def _extract_stream_delta(self, raw: str, last_raw: str):
        """이전 raw 대비 새로 추가된 부분(delta)을 추출한다.

        Returns:
            str: 새로 추가된 텍스트 (없으면 "")
            None: 문맥 전환(새 문장)으로 판단
        """
        if not last_raw:
            return None

        raw_compact = utils.compact_subtitle_text(raw)
        last_compact = utils.compact_subtitle_text(last_raw)
        if not raw_compact or not last_compact:
            return ""

        if raw_compact == last_compact:
            return ""

        if last_compact in raw_compact:
            idx = raw_compact.rfind(last_compact)
            start = idx + len(last_compact)
            if start <= 0 or start >= len(raw_compact):
                return ""
            return utils.slice_from_compact_index(raw, start).strip()

        if utils.is_continuation_text(last_raw, raw):
            return ""

        return None

    def _process_raw_text(self, raw):
        """글로벌 히스토리 + Suffix 매칭 (#GlobalHistorySuffix)

        이 세션에서 확정된 모든 텍스트를 누적하고,
        새 raw에서 히스토리의 마지막 부분(suffix) 이후만 추출합니다.

        DOM 루핑에 완전히 면역입니다.
        """
        if not raw:
            return

        raw = raw.strip()

        # 동일한 raw면 무시 (빠른 경로)
        if raw == self._last_raw_text:
            return
        self._last_raw_text = raw

        # raw를 compact (공백 제거)
        raw_compact = utils.compact_subtitle_text(raw)

        if not raw_compact:
            return

        # 새로운 부분 추출
        new_part = self._extract_new_part(raw, raw_compact)

        if not new_part or len(new_part.strip()) < 3:
            # 새 내용 없음
            return

        new_part = new_part.strip()

        # 코어 알고리즘 결과를 최근 확정 자막 기준으로 한 번 더 정제해
        # 대량 반복 블록이 그대로 누적되는 것을 방지한다.
        with self.subtitle_lock:
            last_text = self.subtitles[-1].text if self.subtitles else ""

        if last_text:
            refined_part = utils.get_word_diff(last_text, new_part)
            if not refined_part or len(refined_part.strip()) < 3:
                return
            new_part = refined_part.strip()

        new_compact = utils.compact_subtitle_text(new_part)
        recent_compact_tail = self._confirmed_history_compact_tail(
            max_entries=12, max_compact_len=5000
        )
        if (
            len(new_compact) >= 20
            and recent_compact_tail
            and new_compact in recent_compact_tail
        ):
            return

        # 히스토리에 추가
        self._confirmed_compact += new_compact

        # suffix 갱신
        if len(self._confirmed_compact) >= self._suffix_length:
            self._trailing_suffix = self._confirmed_compact[-self._suffix_length :]
        else:
            self._trailing_suffix = self._confirmed_compact

        # 자막에 추가
        self._add_text_to_subtitles(new_part)
        self._last_processed_raw = raw

    def _extract_new_part(self, raw: str, raw_compact: str) -> str:
        """히스토리의 suffix 이후의 새 부분만 추출

        Args:
            raw: 원본 텍스트
            raw_compact: 공백 제거된 텍스트

        Returns:
            새로운 부분 (원본 형태로)
        """
        # 히스토리가 없으면 전체가 새로운 것
        if not self._trailing_suffix:
            return raw

        # suffix가 raw_compact에 있는지 검색 (rfind: 마지막 위치 기준으로 과잉 추출 방지)
        pos = raw_compact.rfind(self._trailing_suffix)

        if pos >= 0:
            # suffix 이후 부분만 반환
            start_idx = pos + len(self._trailing_suffix)
            if start_idx >= len(raw_compact):
                return ""  # suffix 이후에 내용 없음
            return utils.slice_from_compact_index(raw, start_idx)

        # 정말 새로운 문맥 - 전체 반환
        return raw

    def _soft_resync(self) -> None:
        """전체 리셋 대신, 최근 확정 자막에서 히스토리를 재구성한다.

        desync/ambiguous 리셋 시 _confirmed_compact를 완전 초기화하면
        이미 처리된 텍스트가 재유입되어 대량 중복이 발생할 수 있다.
        최근 자막의 compact를 기반으로 suffix를 복원하면 이를 방지한다.
        """
        with self.subtitle_lock:
            if self.subtitles:
                # 최근 5개 자막의 compact로 히스토리 재구성
                recent = " ".join(
                    e.text for e in self.subtitles[-5:] if e and e.text
                )
                self._confirmed_compact = utils.compact_subtitle_text(recent)
                if len(self._confirmed_compact) >= self._suffix_length:
                    self._trailing_suffix = self._confirmed_compact[
                        -self._suffix_length :
                    ]
                else:
                    self._trailing_suffix = self._confirmed_compact
                logger.info(
                    "소프트 리셋: suffix=%s",
                    self._trailing_suffix[-20:] if self._trailing_suffix else "(empty)",
                )
            else:
                # 자막이 없으면 어쩔 수 없이 전체 리셋
                self._confirmed_compact = ""
                self._trailing_suffix = ""
                logger.info("소프트 리셋: 자막 없음, 전체 리셋")

    def _find_overlap(self, suffix: str, text: str) -> int:
        """suffix의 뒷부분과 text의 앞부분이 겹치는 길이 반환"""
        max_overlap = min(len(suffix), len(text))
        for i in range(max_overlap, 0, -1):
            if suffix[-i:] == text[:i]:
                return i
        return 0

    def _add_text_to_subtitles(self, text: str) -> None:
        """확정된 텍스트를 SubtitleEntry로 변환하여 저장"""
        if not text or len(text) < 3:
            return

        with self.subtitle_lock:
            # 마지막 엔트리에 이어붙일지, 새 엔트리 만들지 결정
            if self.subtitles:
                last_entry = self.subtitles[-1]
                # [FIX] end_time이 None인 경우 방어 처리 (reflow 후 발생 가능)
                can_append = False
                if last_entry.end_time is not None:
                    elapsed = (datetime.now() - last_entry.end_time).total_seconds()
                    if elapsed < 5.0 and len(last_entry.text) + len(text) < 300:
                        can_append = True

                if can_append:
                    old_chars = last_entry.char_count
                    old_words = last_entry.word_count
                    last_entry.update_text(
                        self._join_stream_text(last_entry.text, text)
                    )
                    last_entry.end_time = datetime.now()
                    self._cached_total_chars += last_entry.char_count - old_chars
                    self._cached_total_words += last_entry.word_count - old_words
                else:
                    # 새 엔트리
                    entry = SubtitleEntry(text)
                    entry.start_time = datetime.now()
                    entry.end_time = datetime.now()
                    self.subtitles.append(entry)
                    self._cached_total_chars += entry.char_count
                    self._cached_total_words += entry.word_count
            else:
                # 첫 엔트리
                entry = SubtitleEntry(text)
                entry.start_time = datetime.now()
                entry.end_time = datetime.now()
                self.subtitles.append(entry)
                self._cached_total_chars += entry.char_count
                self._cached_total_words += entry.word_count

        # 키워드 알림 확인
        self._check_keyword_alert(text)

        # 카운트 라벨 업데이트
        self._update_count_label()

        # UI 갱신
        self._refresh_text(force_full=False)

        # 실시간 저장
        if self.realtime_file:
            try:
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.realtime_file.write(f"[{timestamp}] {text}\n")
                self.realtime_file.flush()
                self._realtime_error_count = 0
            except IOError as e:
                self._realtime_error_count = (
                    getattr(self, "_realtime_error_count", 0) + 1
                )
                if self._realtime_error_count == 3:
                    logger.error(f"실시간 저장 연속 실패: {e}")

    def _set_preview_text(self, text: str) -> None:
        """미리보기 텍스트 표시/숨김"""
        if not hasattr(self, "preview_frame"):
            return
        content = (text or "").strip()
        if content:
            self.preview_label.setText(content)
            self.preview_frame.show()
        else:
            self.preview_label.setText("")
            self.preview_frame.hide()

    def _clear_preview(self) -> None:
        """미리보기 초기화"""
        self._set_preview_text("")

    def _update_preview(self, raw: str) -> None:
        """미리보기 업데이트 (별도 UI)"""
        self._set_preview_text(raw)

    def _render_subtitles(self, force_full: bool = False) -> None:
        """Render subtitles with incremental updates when possible."""
        scrollbar = self.subtitle_text.verticalScrollBar()
        preserve_scroll = self._user_scrolled_up and scrollbar is not None
        saved_scroll = None
        if preserve_scroll:
            saved_scroll = scrollbar.value()
            scrollbar.blockSignals(True)

        # Snapshot for rendering
        with self.subtitle_lock:
            subtitles_copy = list(self.subtitles)

        total_count = len(subtitles_copy)

        # 성능 최적화: 대량 자막 시 최근 항목만 렌더링 (#4)
        render_offset = 0
        if total_count > Config.MAX_RENDER_ENTRIES:
            render_offset = total_count - Config.MAX_RENDER_ENTRIES
            subtitles_copy = subtitles_copy[render_offset:]

        visible_count = len(subtitles_copy)
        last_text = subtitles_copy[-1].text if subtitles_copy else ""

        show_ts = self.timestamp_action.isChecked()

        # 마지막 출력된 타임스탬프 (희소 타임스탬프용)
        # 렌더링 시작 시 초기화
        if not hasattr(self, "_last_printed_ts"):
            self._last_printed_ts = None

        previous_visible_count = max(
            0, self._last_rendered_count - getattr(self, "_last_render_offset", 0)
        )
        offset_changed = render_offset != getattr(self, "_last_render_offset", 0)
        show_ts_changed = (
            self._last_render_show_ts is not None and show_ts != self._last_render_show_ts
        )

        needs_full_render = (
            force_full
            or offset_changed
            or show_ts_changed
            or (total_count < self._last_rendered_count)
            or (previous_visible_count > visible_count)
            or (
                total_count == self._last_rendered_count
                and last_text != self._last_rendered_last_text
            )
        )

        if needs_full_render:
            self.subtitle_text.clear()
            self._last_printed_ts = None  # 풀 렌더링 시 초기화
            cursor = self.subtitle_text.textCursor()

            for i, entry in enumerate(subtitles_copy):
                same_second = False
                if i > 0:
                    prev_entry = subtitles_copy[i - 1]
                    same_second = entry.timestamp.replace(
                        microsecond=0
                    ) == prev_entry.timestamp.replace(microsecond=0)
                    cursor.insertText(" " if same_second else "\n\n")

                if show_ts:
                    # 1분 간격 타임스탬프 로직
                    should_print = False
                    if not same_second:
                        if self._last_printed_ts is None:
                            should_print = True
                        elif (
                            entry.timestamp - self._last_printed_ts
                        ).total_seconds() >= 60:
                            should_print = True

                    if should_print:
                        cursor.insertText(
                            f"[{entry.timestamp.strftime('%H:%M:%S')}] ",
                            self._timestamp_fmt,
                        )
                        self._last_printed_ts = entry.timestamp

                self._insert_highlighted_text(cursor, entry.text)

        else:
            cursor = self.subtitle_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)

            start_local_idx = min(previous_visible_count, visible_count)
            for local_idx in range(start_local_idx, visible_count):
                entry = subtitles_copy[local_idx]
                same_second = False
                if local_idx > 0:
                    prev_entry = subtitles_copy[local_idx - 1]
                    same_second = entry.timestamp.replace(
                        microsecond=0
                    ) == prev_entry.timestamp.replace(microsecond=0)
                    cursor.insertText(" " if same_second else "\n\n")

                if show_ts:
                    # 1분 간격 타임스탬프 로직 (증분)
                    should_print = False
                    if not same_second:
                        if self._last_printed_ts is None:
                            should_print = True
                        elif (
                            entry.timestamp - self._last_printed_ts
                        ).total_seconds() >= 60:
                            should_print = True

                    if should_print:
                        cursor.insertText(
                            f"[{entry.timestamp.strftime('%H:%M:%S')}] ",
                            self._timestamp_fmt,
                        )
                        self._last_printed_ts = entry.timestamp

                self._insert_highlighted_text(cursor, entry.text)

        self._last_rendered_count = total_count
        self._last_rendered_last_text = last_text
        self._last_render_offset = render_offset
        self._last_render_show_ts = show_ts

        if self.auto_scroll_check.isChecked() and not self._user_scrolled_up:
            self.subtitle_text.moveCursor(QTextCursor.MoveOperation.End)

        if preserve_scroll:
            scrollbar.setValue(min(saved_scroll, scrollbar.maximum()))
            scrollbar.blockSignals(False)

    def _on_scroll_changed(self) -> None:
        """스크롤바 위치 변경 감지 - 스마트 스크롤용"""
        scrollbar = self.subtitle_text.verticalScrollBar()
        # 스크롤이 맨 아래에서 일정 거리 이내면 자동 스크롤 활성화
        at_bottom = (
            scrollbar.value() >= scrollbar.maximum() - Config.SCROLL_BOTTOM_THRESHOLD
        )

        if at_bottom:
            self._user_scrolled_up = False
            if hasattr(self, "scroll_to_bottom_btn"):
                self.scroll_to_bottom_btn.hide()
        else:
            # 사용자가 위로 스크롤한 경우
            self._user_scrolled_up = True
            # 추출 중일 때만 버튼 표시
            if self.is_running and hasattr(self, "scroll_to_bottom_btn"):
                self.scroll_to_bottom_btn.show()

    def _scroll_to_bottom(self) -> None:
        """맨 아래로 스크롤하고 자동 스크롤 재개"""
        self._user_scrolled_up = False
        self.subtitle_text.moveCursor(QTextCursor.MoveOperation.End)
        if hasattr(self, "scroll_to_bottom_btn"):
            self.scroll_to_bottom_btn.hide()

    def _toggle_stats_panel(self) -> None:
        """통계 패널 숨기기/보이기"""
        if hasattr(self, "stats_group") and hasattr(self, "toggle_stats_btn"):
            is_visible = self.stats_group.isVisible()
            self.stats_group.setVisible(not is_visible)

            if is_visible:
                self.toggle_stats_btn.setText("📊 통계 보이기")
                # 자막 영역이 전체 너비를 사용하도록
                self.main_splitter.setSizes([1080, 0])
            else:
                self.toggle_stats_btn.setText("📊 통계 숨기기")
                self.main_splitter.setSizes([860, 220])

    def _refresh_text(self, force_full: bool = False) -> None:
        """확정된 자막만 표시 (진행 중인 자막 없음)"""
        self._render_subtitles(force_full=force_full)

    def _refresh_text_full(self, *_args) -> None:
        """렌더 캐시를 무시하고 전체 다시 그리기"""
        self._refresh_text(force_full=True)

    def _finalize_subtitle(self, text):
        """자막 확정 - 단어 단위 증분 병합 (Incremental Word Accumulation)

        [Thread Safety] subtitle_lock으로 self.subtitles 접근 보호
        """
        if not text:
            return

        # [Fix] 중복 처리 방지: _process_raw_text에서 이미 처리된 텍스트면 건너뜀
        # _last_processed_raw가 동일하면 이미 _process_raw_text에서 자막이 추가됨
        if text == self._last_processed_raw:
            return

        # [Fix] 확정된 자막을 프로세서에 등록 (#SubtitleRepetitionFix)
        self.subtitle_processor.add_confirmed(text)

        # 스레드 안전하게 자막 접근
        with self.subtitle_lock:
            # 이전에 확정된 자막이 있으면, 겹치는 부분 제거
            if self.subtitles:
                last_text = self.subtitles[-1].text

                # [Smart Merge] 단어 단위 겹침 분석하여 새로운 단어만 추출
                new_part = utils.get_word_diff(last_text, text)

                if new_part:
                    # [Length Check] 문장이 너무 길어지면 강제로 끊고 시 타임스탬프 생성
                    current_len = len(last_text)
                    new_len = len(new_part)

                    # 기존 길이에 새 내용을 더했을 때 최대 길이를 초과하면 분리
                    if current_len + new_len > Config.STREAM_SUBTITLE_MAX_LENGTH:
                        entry = SubtitleEntry(new_part)
                        entry.start_time = datetime.now()
                        entry.end_time = datetime.now()
                        self.subtitles.append(entry)
                        # 통계 캐시 갱신
                        self._cached_total_chars += entry.char_count
                        self._cached_total_words += entry.word_count

                        if self.realtime_file:
                            try:
                                # 분리된 새 문장으로 저장
                                timestamp = entry.timestamp.strftime("%H:%M:%S")
                                self.realtime_file.write(f"[{timestamp}] {new_part}\n")
                                self.realtime_file.flush()
                            except IOError as e:
                                logger.warning(f"실시간 저장 쓰기 오류: {e}")
                    else:
                        # 새로운 내용이 있으면 이어붙이기 - update_text()로 캐시 갱신 포함
                        old_chars = self.subtitles[-1].char_count
                        old_words = self.subtitles[-1].word_count
                        self.subtitles[-1].update_text(
                            self._join_stream_text(self.subtitles[-1].text, new_part)
                        )
                        self.subtitles[-1].end_time = datetime.now()
                        # 통계 캐시 갱신
                        self._cached_total_chars += (
                            self.subtitles[-1].char_count - old_chars
                        )
                        self._cached_total_words += (
                            self.subtitles[-1].word_count - old_words
                        )

                        # 실시간 저장
                        if self.realtime_file:
                            try:
                                # + 기호로 이어붙여진 내용임을 표시
                                self.realtime_file.write(f"+ {new_part}\n")
                                self.realtime_file.flush()
                            except IOError as e:
                                logger.warning(f"실시간 저장 쓰기 오류: {e}")
                    return
                else:
                    # 겹치는 내용만 있고 새로운 내용이 없으면 (부분집합)
                    # 시간만 갱신하고 종료
                    self.subtitles[-1].end_time = datetime.now()
                    return

            # 첫 번째 자막 또는 완전히 새로운 문장
            entry = SubtitleEntry(text)
            entry.start_time = datetime.now()
            entry.end_time = datetime.now()

            self.subtitles.append(entry)
            # 통계 캐시 갱신
            self._cached_total_chars += entry.char_count
            self._cached_total_words += entry.word_count

        # 키워드 알림 확인 (락 밖에서 - UI 작업)
        self._check_keyword_alert(text)

        # 카운트 라벨 업데이트
        self._update_count_label()

        # 실시간 저장
        if self.realtime_file:
            try:
                timestamp = entry.timestamp.strftime("%H:%M:%S")
                self.realtime_file.write(f"[{timestamp}] {text}\n")
                self.realtime_file.flush()
            except IOError as e:
                logger.warning(f"실시간 저장 쓰기 오류: {e}")

        self._refresh_text(force_full=False)

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

    def _rebuild_keyword_cache(
        self, keywords: list, update_settings: bool = True, refresh: bool = True
    ) -> None:
        """하이라이트 키워드 캐시 재구성"""
        cleaned = [k.strip() for k in keywords if k and k.strip()]
        self.keywords = cleaned
        self._keywords_lower_set = {k.lower() for k in cleaned}

        if cleaned:
            pattern = "|".join(re.escape(k) for k in cleaned)
            try:
                self._keyword_pattern = re.compile(f"({pattern})", re.IGNORECASE)
            except re.error:
                self._keyword_pattern = None
        else:
            self._keyword_pattern = None

        if update_settings:
            self.settings.setValue("highlight_keywords", ", ".join(self.keywords))

        if refresh and hasattr(self, "subtitle_text"):
            self._refresh_text(force_full=True)

    def _update_keyword_cache(self):
        """키워드 패턴 캐시 업데이트 (디바운싱 적용)"""
        # 디바운싱: 이전 타이머 취소
        if (
            hasattr(self, "_keyword_debounce_timer")
            and self._keyword_debounce_timer.isActive()
        ):
            self._keyword_debounce_timer.stop()

        def do_update():
            self._perform_keyword_cache_update()

        # 300ms 후 실행
        self._keyword_debounce_timer = QTimer(self)
        self._keyword_debounce_timer.setSingleShot(True)
        self._keyword_debounce_timer.timeout.connect(do_update)
        self._keyword_debounce_timer.start(300)

    def _perform_keyword_cache_update(self):
        """실제 키워드 캐시 업데이트 로직"""
        try:
            if hasattr(self, "keyword_input"):
                raw_text = self.keyword_input.text()
            else:
                raw_text = ", ".join(self.keywords)

            keywords = [k.strip() for k in raw_text.split(",") if k.strip()]
            self._rebuild_keyword_cache(keywords, update_settings=True, refresh=True)
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
            count = len(self.subtitles)
        if not count:
            self._show_toast("지울 자막이 없습니다", "warning")
            return

        reply = QMessageBox.question(
            self,
            "자막 지우기",
            f"현재 {count}개의 자막을 모두 지우시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self._replace_subtitles_and_refresh([], keep_history_from_subtitles=False)
        self._show_toast(f"🗑️ {count}개 자막 삭제됨", "success")

    def _toggle_theme_from_button(self) -> None:
        """툴바 버튼에서 테마 전환"""
        self._toggle_theme()
        # 버튼 아이콘 업데이트
        if hasattr(self, "theme_toggle_btn"):
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
        self._refresh_text(force_full=True)

    def _do_search(self):
        query = self.search_input.text()
        if not query:
            return

        query_l = query.lower()
        text_l = self.subtitle_text.toPlainText().lower()
        self.search_matches = []

        start = 0
        while True:
            idx = text_l.find(query_l, start)
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
            self,
            "하이라이트 키워드 설정",
            "하이라이트할 키워드 (쉼표로 구분):",
            text=current,
        )

        if ok:
            keywords = [k.strip() for k in text.split(",") if k.strip()]
            if hasattr(self, "keyword_input"):
                self.keyword_input.blockSignals(True)
                self.keyword_input.setText(", ".join(keywords))
                self.keyword_input.blockSignals(False)
            self._rebuild_keyword_cache(keywords, update_settings=True, refresh=True)
            self._show_toast(f"하이라이트 키워드 {len(keywords)}개 설정됨", "success")

    def _rebuild_alert_keyword_cache(
        self, keywords: list, update_settings: bool = True
    ) -> None:
        """알림 키워드 캐시를 재구성한다."""
        cleaned = [k.strip() for k in keywords if k and k.strip()]
        self.alert_keywords = cleaned
        self._alert_keywords_cache = [(k, k.lower()) for k in cleaned]
        if update_settings:
            self.settings.setValue("alert_keywords", ", ".join(cleaned))

    def _set_alert_keywords(self):
        """알림 키워드 설정 - 해당 키워드 감지 시 토스트 알림"""
        current = ", ".join(self.alert_keywords)
        text, ok = QInputDialog.getText(
            self,
            "알림 키워드 설정",
            "알림을 받을 키워드 (쉼표로 구분):\n예: 법안, 의결, 통과",
            text=current,
        )

        if ok:
            self._rebuild_alert_keyword_cache(
                [k.strip() for k in text.split(",") if k.strip()],
                update_settings=True,
            )
            self._show_toast(
                f"알림 키워드 {len(self.alert_keywords)}개 설정됨", "success"
            )

    def _check_keyword_alert(self, text: str):
        """키워드 포함 시 알림 표시"""
        if not self._alert_keywords_cache:
            return

        text_lower = text.lower()
        for original, keyword_lower in self._alert_keywords_cache:
            if keyword_lower and keyword_lower in text_lower:
                self._show_toast(f"🔔 키워드 감지: {original}", "warning", 5000)
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

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_dir / f"backup_{timestamp}.json"

            # 스레드 안전하게 자막 스냅샷 생성 (UI 스레드)
            with self.subtitle_lock:
                subtitles_copy = [s.to_dict() for s in self.subtitles]

            data = {
                "version": Config.VERSION,
                "created": datetime.now().isoformat(),
                "url": self._get_current_url(),
                "subtitles": subtitles_copy,
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
                utils.atomic_write_json(
                    backup_file,
                    data,
                    ensure_ascii=False,
                    indent=2,
                )

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
            for old_backup in backups[Config.MAX_BACKUP_COUNT :]:
                old_backup.unlink()
                logger.debug(f"오래된 백업 삭제: {old_backup}")
        except Exception as e:
            logger.warning(f"백업 정리 중 오류: {e}")

    # ========== 파일 저장 ==========

    def _save_in_background(
        self, save_func, path: str, success_msg: str, error_prefix: str
    ):
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
                self.message_queue.put(
                    ("toast", {"message": success_msg, "toast_type": "success"})
                )
            except Exception as e:
                logger.error(f"{error_prefix}: {e}")
                self.message_queue.put(
                    (
                        "toast",
                        {
                            "message": f"{error_prefix}: {e}",
                            "toast_type": "error",
                            "duration": 5000,
                        },
                    )
                )

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
        path, _ = QFileDialog.getSaveFileName(
            self, "통계 내보내기", filename, "텍스트 (*.txt)"
        )

        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("=" * 50 + "\n")
                    f.write("        🏛️ 국회 자막 통계 보고서\n")
                    f.write("=" * 50 + "\n\n")

                    f.write(
                        f"생성 일시: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')}\n\n"
                    )

                    f.write("📊 기본 통계\n")
                    f.write("-" * 30 + "\n")
                    f.write(f"  총 문장 수: {len(subtitles_snapshot):,}개\n")
                    f.write(f"  총 글자 수: {total_chars:,}자\n")
                    f.write(f"  총 단어 수: {total_words:,}개\n")
                    f.write(
                        f"  평균 문장 길이: {total_chars / len(subtitles_snapshot):.1f}자\n"
                    )
                    f.write(
                        f"  평균 단어 수: {total_words / len(subtitles_snapshot):.1f}개\n\n"
                    )

                    f.write("📏 문장 분석\n")
                    f.write("-" * 30 + "\n")
                    f.write(f"  가장 긴 문장: {len(longest.text)}자\n")
                    f.write(
                        f'    "{longest.text[:50]}{"..." if len(longest.text) > 50 else ""}"\n'
                    )
                    f.write(f"  가장 짧은 문장: {len(shortest.text)}자\n")
                    f.write(f'    "{shortest.text}"\n\n')

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
        """URL과 현재 시간 기반 스마트 파일명 생성 (#28)"""
        # 위원회명 추출 (현재 URL에서 자동 감지)
        current_url = self._get_current_url()
        committee_name = self._autodetect_tag(current_url)
        return utils.generate_filename(committee_name, extension)

    def _save_txt(self):
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return

        filename = self._generate_smart_filename("txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "TXT 저장", filename, "텍스트 (*.txt)"
        )

        if path:
            # 스레드 안전하게 자막 스냅샷 생성 (UI 스레드에서)
            with self.subtitle_lock:
                subtitles_snapshot = [
                    (entry.timestamp, entry.text) for entry in self.subtitles
                ]

            # 실제 저장 함수 정의
            def do_save(filepath):
                with open(filepath, "w", encoding="utf-8-sig") as f:
                    last_printed_ts = None
                    for i, (timestamp, text) in enumerate(subtitles_snapshot):
                        # 메인 윈도우와 동일: 1분 간격으로 타임스탬프 표시
                        should_print_ts = False
                        if last_printed_ts is None:
                            should_print_ts = True
                        elif (timestamp - last_printed_ts).total_seconds() >= 60:
                            should_print_ts = True

                        if should_print_ts:
                            f.write(f"[{timestamp.strftime('%H:%M:%S')}] {text}\n")
                            last_printed_ts = timestamp
                        else:
                            f.write(f"{text}\n")

            # 백그라운드에서 저장 실행
            self._save_in_background(do_save, path, "TXT 저장 완료!", "TXT 저장 실패")

    def _save_srt(self):
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return

        filename = self._generate_smart_filename("srt")
        path, _ = QFileDialog.getSaveFileName(
            self, "SRT 저장", filename, "SubRip (*.srt)"
        )

        if path:
            # 스레드 안전하게 자막 스냅샷 생성 (UI 스레드에서)
            with self.subtitle_lock:
                subtitles_snapshot = [
                    (entry.start_time, entry.end_time, entry.timestamp, entry.text)
                    for entry in self.subtitles
                ]

            def do_save(filepath):
                with open(filepath, "w", encoding="utf-8") as f:
                    for i, (start_time, end_time, timestamp, text) in enumerate(
                        subtitles_snapshot, 1
                    ):
                        if start_time and end_time:
                            # [Fix] 밀리초 정밀도 개선
                            start = f"{start_time.strftime('%H:%M:%S')},{start_time.microsecond // 1000:03d}"
                            end = f"{end_time.strftime('%H:%M:%S')},{end_time.microsecond // 1000:03d}"
                        else:
                            start = f"{timestamp.strftime('%H:%M:%S')},{timestamp.microsecond // 1000:03d}"
                            fallback_end = timestamp + timedelta(seconds=3)
                            end = f"{fallback_end.strftime('%H:%M:%S')},{fallback_end.microsecond // 1000:03d}"
                        f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

            self._save_in_background(do_save, path, "SRT 저장 완료!", "SRT 저장 실패")

    def _save_vtt(self):
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return

        filename = self._generate_smart_filename("vtt")
        path, _ = QFileDialog.getSaveFileName(
            self, "VTT 저장", filename, "WebVTT (*.vtt)"
        )

        if path:
            with self.subtitle_lock:
                subtitles_snapshot = [
                    (entry.start_time, entry.end_time, entry.timestamp, entry.text)
                    for entry in self.subtitles
                ]

            def do_save(filepath):
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write("WEBVTT\n\n")
                    for i, (start_time, end_time, timestamp, text) in enumerate(
                        subtitles_snapshot, 1
                    ):
                        if start_time and end_time:
                            # [Fix] 밀리초 정밀도 개선
                            start = f"{start_time.strftime('%H:%M:%S')}.{start_time.microsecond // 1000:03d}"
                            end = f"{end_time.strftime('%H:%M:%S')}.{end_time.microsecond // 1000:03d}"
                        else:
                            start = f"{timestamp.strftime('%H:%M:%S')}.{timestamp.microsecond // 1000:03d}"
                            fallback_end = timestamp + timedelta(seconds=3)
                            end = f"{fallback_end.strftime('%H:%M:%S')}.{fallback_end.microsecond // 1000:03d}"
                        f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

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
                self,
                "라이브러리 필요",
                "DOCX 저장을 위해 python-docx 라이브러리가 필요합니다.\n\n"
                "설치: pip install python-docx",
            )
            return

        filename = self._generate_smart_filename("docx")
        path, _ = QFileDialog.getSaveFileName(
            self, "DOCX 저장", filename, "Word 문서 (*.docx)"
        )

        if path:
            # 스레드 안전하게 자막 스냅샷 생성
            with self.subtitle_lock:
                subtitles_snapshot = [
                    (entry.timestamp, entry.text) for entry in self.subtitles
                ]

            generated_at = datetime.now().strftime("%Y년 %m월 %d일 %H:%M:%S")
            total_chars = sum(len(text) for _, text in subtitles_snapshot)

            def do_save(filepath):
                doc = Document()

                # 제목
                title = doc.add_heading("국회 의사중계 자막", 0)
                title.alignment = WD_ALIGN_PARAGRAPH.CENTER

                # 생성 일시
                doc.add_paragraph(f"생성 일시: {generated_at}")
                doc.add_paragraph()

                # 자막 내용 - 1분 간격으로 타임스탬프 표시
                last_printed_ts = None
                for timestamp, text in subtitles_snapshot:
                    should_print_ts = False
                    if last_printed_ts is None:
                        should_print_ts = True
                    elif (timestamp - last_printed_ts).total_seconds() >= 60:
                        should_print_ts = True

                    p = doc.add_paragraph()
                    if should_print_ts:
                        ts = timestamp.strftime("%H:%M:%S")
                        run = p.add_run(f"[{ts}] ")
                        run.font.size = Pt(9)
                        run.font.color.rgb = None  # 기본 색상
                        last_printed_ts = timestamp
                    p.add_run(text)

                # 통계
                doc.add_paragraph()
                doc.add_paragraph(
                    f"총 {len(subtitles_snapshot)}문장, {total_chars:,}자"
                )

                doc.save(filepath)

            self._save_in_background(do_save, path, "DOCX 저장 완료!", "DOCX 저장 실패")

    def _save_hwp(self):
        """HWP 파일로 저장 (Hancom Office 필요)"""
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return

        try:
            import win32com.client
        except ImportError:
            QMessageBox.warning(
                self,
                "라이브러리 필요",
                "HWP 저장을 위해 pywin32 라이브러리가 필요합니다.\n\n"
                "설치: pip install pywin32\n\n"
                "RTF 형식으로 저장을 시도합니다.",
            )
            self._save_rtf()
            return

        # 저장 대화상자
        filename = f"국회자막_{datetime.now().strftime('%Y%m%d_%H%M%S')}.hwp"
        path, _ = QFileDialog.getSaveFileName(
            self, "HWP 저장", filename, "HWP 문서 (*.hwp)"
        )

        if not path:
            return

        # 스레드 안전하게 자막 스냅샷 생성
        with self.subtitle_lock:
            subtitles_snapshot = [
                (entry.timestamp, entry.text) for entry in self.subtitles
            ]

        generated_at = datetime.now().strftime("%Y년 %m월 %d일 %H:%M:%S")
        total_chars = sum(len(text) for _, text in subtitles_snapshot)

        def do_save(filepath):
            hwp = None
            pythoncom = None
            try:
                try:
                    import pythoncom

                    pythoncom.CoInitialize()
                except Exception:
                    pythoncom = None

                # win32com.client.dynamic.Dispatch 사용으로 캐시 문제 회피
                hwp = win32com.client.dynamic.Dispatch("HWPFrame.HwpObject")
                hwp.XHwpWindows.Item(0).Visible = True
                hwp.RegisterModule(
                    "FilePathCheckDLL", "SecurityModule"
                )  # 보안 모듈 등록 시도

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
                hwp.HParameterSet.HInsertText.Text = (
                    f"생성 일시: {generated_at}\r\n\r\n"
                )
                hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)

                # 자막 내용 - 1분 간격으로 타임스탬프 표시
                last_printed_ts = None
                for timestamp, text in subtitles_snapshot:
                    should_print_ts = False
                    if last_printed_ts is None:
                        should_print_ts = True
                    elif (timestamp - last_printed_ts).total_seconds() >= 60:
                        should_print_ts = True

                    if should_print_ts:
                        ts = timestamp.strftime("%H:%M:%S")
                        hwp.HParameterSet.HInsertText.Text = f"[{ts}] {text}\r\n"
                        last_printed_ts = timestamp
                    else:
                        hwp.HParameterSet.HInsertText.Text = f"{text}\r\n"
                    hwp.HAction.Execute(
                        "InsertText", hwp.HParameterSet.HInsertText.HSet
                    )

                # 통계
                hwp.HParameterSet.HInsertText.Text = (
                    f"\r\n총 {len(subtitles_snapshot)}문장, {total_chars:,}자\r\n"
                )
                hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)

                # FileSaveAs_S 액션 사용
                hwp.HAction.GetDefault(
                    "FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet
                )
                hwp.HParameterSet.HFileOpenSave.filename = filepath
                hwp.HParameterSet.HFileOpenSave.Format = "HWP"
                hwp.HAction.Execute(
                    "FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet
                )
            finally:
                if hwp:
                    try:
                        hwp.Quit()
                    except Exception:
                        pass
                if pythoncom:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass

        def do_save_with_error(filepath):
            last_error = None
            for attempt in range(2):
                try:
                    do_save(filepath)
                    saved_path = Path(filepath)
                    if not saved_path.exists() or saved_path.stat().st_size <= 0:
                        raise RuntimeError("저장된 파일이 확인되지 않습니다.")
                    return
                except Exception as e:
                    last_error = e
                    logger.warning(f"HWP 저장 재시도 실패 ({attempt + 1}/2): {e}")
                    time.sleep(1)
            self.message_queue.put(("hwp_save_failed", {"error": str(last_error)}))
            raise last_error

        self._save_in_background(
            do_save_with_error, path, "HWP 저장 완료!", "HWP 저장 실패"
        )

    def _handle_hwp_save_failure(self, error) -> None:
        """HWP 저장 실패 시 대체 저장 안내"""
        error_msg = str(error).lower()
        logger.error(f"HWP 저장 실패: {error}")

        # 권한 문제 힌트 제공
        if "access denied" in error_msg or "권한" in str(error):
            advice = (
                "\n\n관리자 권한으로 실행하거나 한글 프로그램을 먼저 실행해 보세요."
            )
        elif "server execution failed" in error_msg:
            advice = "\n\n한글 프로그램이 응답하지 않습니다. 한글을 종료하고 다시 시도하세요."
        else:
            advice = ""

        # 사용자에게 대체 저장 방식 제안
        reply = QMessageBox.question(
            self,
            "HWP 저장 실패",
            f"한글 파일 저장 중 오류가 발생했습니다: {error}{advice}\n\n"
            "대체 형식으로 저장하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            items = ["RTF (한글 호환)", "DOCX (Word)", "TXT (텍스트)"]
            item, ok = QInputDialog.getItem(
                self, "형식 선택", "저장 형식:", items, 0, False
            )
            if ok and item:
                if "RTF" in item:
                    self._save_rtf()
                elif "DOCX" in item:
                    self._save_docx()
                else:
                    self._save_txt()

    def _rtf_encode(self, text: str) -> str:
        """유니코드 문자를 RTF 형식으로 인코딩 (특수문자 이스케이프)"""
        result = []
        for char in text:
            if char == "\\":
                result.append("\\\\")
            elif char == "{":
                result.append("\\{")
            elif char == "}":
                result.append("\\}")
            else:
                result.append(char)
        return "".join(result)

    def _save_rtf(self):
        """RTF 파일로 저장 (HWP에서 열기 가능)"""
        if not self.subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return

        filename = self._generate_smart_filename("rtf")
        path, _ = QFileDialog.getSaveFileName(
            self, "RTF 저장", filename, "RTF 문서 (*.rtf)"
        )

        if path:
            try:
                # 스레드 안전하게 자막 스냅샷 생성
                with self.subtitle_lock:
                    subtitles_snapshot = list(self.subtitles)

                with open(path, "wb") as f:  # 바이너리 모드로 변경
                    # RTF 헤더 (유니코드 지원)
                    f.write(b"{\\rtf1\\ansi\\ansicpg949\\deff0")
                    f.write(
                        b"{\\fonttbl{\\f0\\fnil\\fcharset129 \\'b8\\'c0\\'c0\\'ba \\'b0\\'ed\\'b5\\'f1;}}"
                    )
                    f.write(
                        b"{\\colortbl;\\red0\\green0\\blue0;\\red128\\green128\\blue128;}"
                    )
                    f.write(b"\n")

                    # 제목
                    title = self._rtf_encode("국회 의사중계 자막")
                    f.write(b"\\pard\\qc\\b\\fs28 ")
                    f.write(title.encode("cp949", errors="replace"))
                    f.write(b"\\b0\\par\n")

                    # 생성 일시
                    date_str = self._rtf_encode(
                        f"생성 일시: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')}"
                    )
                    f.write(b"\\pard\\ql\\fs20 ")
                    f.write(date_str.encode("cp949", errors="replace"))
                    f.write(b"\\par\\par\n")

                    # 자막 내용
                    for entry in subtitles_snapshot:
                        timestamp = entry.timestamp.strftime("%H:%M:%S")
                        text = self._rtf_encode(entry.text)
                        f.write(b"\\cf2[")
                        f.write(timestamp.encode("cp949", errors="replace"))
                        f.write(b"]\\cf1 ")
                        f.write(text.encode("cp949", errors="replace"))
                        f.write(b"\\par\n")

                    # 통계
                    total_chars = sum(len(s.text) for s in subtitles_snapshot)
                    stats = self._rtf_encode(
                        f"총 {len(subtitles_snapshot)}문장, {total_chars:,}자"
                    )
                    f.write(b"\\par\\fs18 ")
                    f.write(stats.encode("cp949", errors="replace"))
                    f.write(b"\\par}")

                QMessageBox.information(
                    self,
                    "성공",
                    f"RTF 저장 완료!\n\n파일: {path}\n\n이 파일은 한글(HWP)에서 열 수 있습니다.",
                )

            except Exception as e:
                QMessageBox.critical(self, "오류", f"RTF 저장 실패: {e}")

    # ========== 세션 ==========

    def _save_session(self):
        with self.subtitle_lock:
            has_subtitles = bool(self.subtitles)
        if not has_subtitles:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return

        if self._session_save_in_progress:
            self._show_toast("이미 세션 저장이 진행 중입니다.", "info")
            return

        filename = (
            f"{Config.SESSION_DIR}/세션_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "세션 저장", filename, "JSON (*.json)"
        )

        if not path:
            return

        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"세션 저장 경로 준비 실패: {e}")
            return

        self._session_save_in_progress = True
        self._set_status("세션 저장 중...", "running")

        current_url = self._get_current_url()
        committee_name = self._autodetect_tag(current_url) or ""
        duration = int(time.time() - self.start_time) if self.start_time else 0

        def background_save():
            try:
                with self.subtitle_lock:
                    snapshot = [
                        (s.text, s.timestamp, s.start_time, s.end_time)
                        for s in self.subtitles
                    ]

                subtitles_copy = [
                    {
                        "text": text,
                        "timestamp": timestamp.isoformat() if timestamp else None,
                        "start_time": start_time.isoformat() if start_time else None,
                        "end_time": end_time.isoformat() if end_time else None,
                    }
                    for text, timestamp, start_time, end_time in snapshot
                ]

                data = {
                    "version": Config.VERSION,
                    "created": datetime.now().isoformat(),
                    "url": current_url,
                    "committee_name": committee_name,
                    "subtitles": subtitles_copy,
                }

                utils.atomic_write_json(
                    path,
                    data,
                    ensure_ascii=False,
                    indent=2,
                )

                db_saved = False
                db_error = ""
                if self.db:
                    try:
                        db_data = {
                            "url": current_url,
                            "committee_name": committee_name,
                            "subtitles": subtitles_copy,
                            "version": Config.VERSION,
                            "duration_seconds": duration,
                        }
                        self.db.save_session(db_data)
                        db_saved = True
                    except Exception as db_exc:
                        db_error = str(db_exc)

                self.message_queue.put(
                    (
                        "session_save_done",
                        {
                            "path": path,
                            "saved_count": len(subtitles_copy),
                            "db_saved": db_saved,
                            "db_error": db_error,
                        },
                    )
                )
            except Exception as e:
                logger.error(f"세션 저장 오류: {e}")
                self.message_queue.put(
                    ("session_save_failed", {"path": path, "error": str(e)})
                )

        threading.Thread(
            target=background_save, daemon=True, name="SessionSaveWorker"
        ).start()
        self._show_toast(f"💾 세션 저장 시작: {Path(path).name}", "info", 1500)

    def _load_session(self):
        if self._session_load_in_progress:
            self._show_toast("이미 세션 불러오기가 진행 중입니다.", "info")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "세션 불러오기", f"{Config.SESSION_DIR}/", "JSON (*.json)"
        )

        if not path:
            return

        self._session_load_in_progress = True
        self._set_status("세션 불러오기 중...", "running")

        def background_load():
            try:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except json.JSONDecodeError as json_err:
                    self.message_queue.put(
                        (
                            "session_load_json_error",
                            {"path": path, "error": str(json_err)},
                        )
                    )
                    return

                session_version = data.get("version", "unknown")
                new_subtitles = []
                skipped = 0
                for item in data.get("subtitles", []):
                    try:
                        new_subtitles.append(SubtitleEntry.from_dict(item))
                    except ValueError as e:
                        logger.warning(f"손상된 자막 항목 건너뜀: {e}")
                        skipped += 1

                self.message_queue.put(
                    (
                        "session_load_done",
                        {
                            "path": path,
                            "version": session_version,
                            "url": data.get("url", ""),
                            "subtitles": new_subtitles,
                            "skipped": skipped,
                        },
                    )
                )
            except Exception as e:
                logger.error(f"세션 불러오기 오류: {e}")
                self.message_queue.put(
                    ("session_load_failed", {"path": path, "error": str(e)})
                )

        threading.Thread(
            target=background_load, daemon=True, name="SessionLoadWorker"
        ).start()
        self._show_toast(f"📂 세션 불러오기 시작: {Path(path).name}", "info", 1500)

    # ========== 유틸리티 ==========
    def _clear_text(self):
        if not self.subtitles:
            return

        reply = QMessageBox.question(
            self,
            "확인",
            "모든 내용을 지우시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._replace_subtitles_and_refresh(
                [], keep_history_from_subtitles=False
            )
            self.status_label.setText("내용 삭제됨")

    def _edit_subtitle(self):
        """선택한 자막 편집"""
        if not self.subtitles:
            self._show_toast("편집할 자막이 없습니다.", "warning")
            return
        if self.is_running:
            self._show_toast(
                "추출 중에는 편집이 불안정할 수 있습니다. 먼저 중지하세요.", "warning"
            )
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
            timestamp = entry.timestamp.strftime("%H:%M:%S")
            text_preview = (
                entry.text[:50] + "..." if len(entry.text) > 50 else entry.text
            )
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
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
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
                        self._cached_total_chars += entry.char_count - old_chars
                        self._cached_total_words += entry.word_count - old_words
                    self._refresh_text(force_full=True)
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
            self._show_toast(
                "추출 중에는 삭제가 불안정할 수 있습니다. 먼저 중지하세요.", "warning"
            )
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
            timestamp = entry.timestamp.strftime("%H:%M:%S")
            text_preview = (
                entry.text[:50] + "..." if len(entry.text) > 50 else entry.text
            )
            list_widget.addItem(f"[{timestamp}] {text_preview}")
        layout.addWidget(list_widget)

        # 버튼
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("삭제")

        def delete_selected():
            selected_rows = sorted(
                [i.row() for i in list_widget.selectedIndexes()], reverse=True
            )
            if not selected_rows:
                QMessageBox.warning(dialog, "알림", "삭제할 자막을 선택해주세요.")
                return

            reply = QMessageBox.question(
                dialog,
                "확인",
                f"선택한 {len(selected_rows)}개의 자막을 삭제하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                with self.subtitle_lock:
                    for row in selected_rows:
                        entry = self.subtitles[row]
                        self._cached_total_chars -= entry.char_count
                        self._cached_total_words -= entry.word_count
                        del self.subtitles[row]
                self._refresh_text(force_full=True)
                self._update_count_label()
                self._show_toast(
                    f"{len(selected_rows)}개 자막이 삭제되었습니다.", "success"
                )
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

    def _set_db_history_dialog_busy(self, busy: bool, message: str = "") -> None:
        """DB 히스토리 다이얼로그의 버튼/목록 상태를 토글한다."""
        state = self._db_history_dialog_state or {}
        load_btn = state.get("load_btn")
        delete_btn = state.get("delete_btn")
        close_btn = state.get("close_btn")
        list_widget = state.get("list_widget")
        status_label = state.get("status_label")

        for btn in (load_btn, delete_btn, close_btn):
            if btn is not None:
                btn.setEnabled(not busy)
        if list_widget is not None:
            list_widget.setEnabled(not busy)

        if status_label is not None:
            if busy:
                status_label.setText(message or "처리 중입니다...")
                status_label.show()
            elif message:
                status_label.setText(message)
                status_label.show()
            else:
                status_label.hide()

    def _clear_db_history_dialog_state(self) -> None:
        """활성 DB 히스토리 다이얼로그 상태를 정리한다."""
        self._db_history_dialog_state = None

    def _run_db_task(
        self,
        task_name: str,
        worker,
        context: dict | None = None,
        loading_text: str = "",
    ) -> bool:
        """DB 작업을 백그라운드 스레드에서 실행하고 결과를 큐로 전달한다."""
        if not self.db:
            QMessageBox.warning(self, "알림", "데이터베이스가 초기화되지 않았습니다.")
            return False

        if task_name in self._db_tasks_inflight:
            self._show_toast("이미 같은 DB 작업이 실행 중입니다.", "info")
            return False

        self._db_tasks_inflight.add(task_name)
        if loading_text:
            self._set_status(loading_text, "running")

        payload_context = dict(context or {})

        def _work():
            try:
                result = worker()
                self.message_queue.put(
                    (
                        "db_task_result",
                        {
                            "task": task_name,
                            "result": result,
                            "context": payload_context,
                        },
                    )
                )
            except Exception as e:
                logger.exception("DB 작업 실패 (%s)", task_name)
                self.message_queue.put(
                    (
                        "db_task_error",
                        {"task": task_name, "error": str(e), "context": payload_context},
                    )
                )

        threading.Thread(target=_work, daemon=True, name=f"DBTask-{task_name}").start()
        return True

    def _handle_db_task_result(
        self, task_name: str, result: Any, context: dict | None = None
    ) -> None:
        """DB 비동기 작업 완료 처리 (UI 스레드)."""
        context = context or {}
        if task_name == "db_history_list":
            sessions = result if isinstance(result, list) else []
            if not sessions:
                QMessageBox.information(self, "세션 히스토리", "저장된 세션이 없습니다.")
                self._set_status("세션 히스토리 없음", "info")
                return
            self._open_db_history_dialog(sessions)
            self._set_status("세션 히스토리 조회 완료", "success")
            return

        if task_name == "db_search":
            query = str(context.get("query", "")).strip()
            results = result if isinstance(result, list) else []
            if not results:
                QMessageBox.information(
                    self, "검색 결과", f"'{query}'에 대한 검색 결과가 없습니다."
                )
                self._set_status("자막 검색 결과 없음", "info")
                return
            self._show_db_search_results(query, results)
            self._set_status(f"자막 검색 완료 ({len(results)}건)", "success")
            return

        if task_name == "db_stats":
            stats = result if isinstance(result, dict) else {}
            self._show_db_stats_dialog(stats)
            self._set_status("DB 통계 조회 완료", "success")
            return

        if task_name == "db_history_load_selected":
            self._set_db_history_dialog_busy(False)
            payload = result if isinstance(result, dict) else {}
            if not payload.get("ok"):
                self._set_status("세션 불러오기 실패", "error")
                self._show_toast("세션을 불러오지 못했습니다.", "error")
                return

            new_subtitles = payload.get("subtitles", [])
            skipped = int(payload.get("skipped", 0) or 0)
            self._replace_subtitles_and_refresh(new_subtitles)

            message = f"세션 불러오기 완료! {len(new_subtitles)}개 문장"
            if skipped > 0:
                message += f" (손상 항목 {skipped}개 제외)"
            self._show_toast(message, "success")
            self._set_status(message, "success")

            state = self._db_history_dialog_state or {}
            dialog = state.get("dialog")
            if dialog is not None:
                dialog.accept()
            return

        if task_name == "db_history_delete_selected":
            self._set_db_history_dialog_busy(False)
            deleted = bool(result)
            if not deleted:
                self._set_status("세션 삭제 실패", "error")
                self._show_toast("세션 삭제 실패", "error")
                return

            state = self._db_history_dialog_state or {}
            sessions = state.get("sessions")
            list_widget = state.get("list_widget")
            session_id = context.get("session_id")

            remove_idx = None
            if isinstance(sessions, list):
                for i, item in enumerate(sessions):
                    if item.get("id") == session_id:
                        remove_idx = i
                        break
            if (
                remove_idx is not None
                and list_widget is not None
                and isinstance(sessions, list)
            ):
                list_widget.takeItem(remove_idx)
                sessions.pop(remove_idx)

            self._show_toast("세션 삭제됨", "info")
            self._set_status("세션 삭제 완료", "success")
            return

    def _handle_db_task_error(
        self, task_name: str, error: str, context: dict | None = None
    ) -> None:
        """DB 비동기 작업 실패 처리 (UI 스레드)."""
        context = context or {}
        if task_name in ("db_history_load_selected", "db_history_delete_selected"):
            self._set_db_history_dialog_busy(False)
        query_hint = str(context.get("query", "")).strip()
        message = f"DB 작업 실패 ({task_name}): {error}"
        if task_name == "db_search" and query_hint:
            message = f"검색 실패 ('{query_hint}'): {error}"
        self._set_status(message, "error")
        QMessageBox.warning(self, "데이터베이스 오류", message)

    def _show_db_history(self):
        """세션 히스토리 다이얼로그 표시"""
        self._run_db_task(
            "db_history_list",
            worker=lambda: self.db.list_sessions(limit=50),
            loading_text="DB 세션 히스토리 조회 중...",
        )

    def _open_db_history_dialog(self, sessions: list[dict]) -> None:
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
            list_widget.addItem(
                f"[{created}] {committee} - {subtitles}문장, {chars:,}자"
            )

        layout.addWidget(list_widget)

        status_label = QLabel("")
        status_label.hide()
        layout.addWidget(status_label)

        # 버튼
        btn_layout = QHBoxLayout()

        load_btn = QPushButton("불러오기")

        def load_selected():
            idx = list_widget.currentRow()
            if idx < 0 or idx >= len(sessions):
                return

            session_id = sessions[idx].get("id")
            if not session_id:
                self._show_toast("유효한 세션 ID가 없습니다.", "warning")
                return

            def worker(sid=session_id):
                session_data = self.db.load_session(sid)
                if not session_data:
                    return {"ok": False, "subtitles": [], "skipped": 0}
                new_subtitles = []
                skipped = 0
                for item in session_data.get("subtitles", []):
                    try:
                        new_subtitles.append(SubtitleEntry.from_dict(item))
                    except ValueError as e:
                        logger.warning(f"DB 자막 항목 건너뜀: {e}")
                        skipped += 1
                return {"ok": True, "subtitles": new_subtitles, "skipped": skipped}

            started = self._run_db_task(
                "db_history_load_selected",
                worker=worker,
                context={"session_id": session_id, "row": idx},
                loading_text="DB 세션 불러오는 중...",
            )
            if started:
                self._set_db_history_dialog_busy(
                    True, "세션을 불러오는 중입니다..."
                )

        load_btn.clicked.connect(load_selected)
        btn_layout.addWidget(load_btn)

        delete_btn = QPushButton("삭제")

        def delete_selected():
            idx = list_widget.currentRow()
            if idx < 0 or idx >= len(sessions):
                return

            session_id = sessions[idx].get("id")
            if not session_id:
                self._show_toast("유효한 세션 ID가 없습니다.", "warning")
                return

            reply = QMessageBox.question(
                dialog,
                "삭제 확인",
                "선택한 세션을 삭제하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            started = self._run_db_task(
                "db_history_delete_selected",
                worker=lambda sid=session_id: self.db.delete_session(sid),
                context={"session_id": session_id, "row": idx},
                loading_text="DB 세션 삭제 중...",
            )
            if started:
                self._set_db_history_dialog_busy(True, "세션을 삭제하는 중입니다...")

        delete_btn.clicked.connect(delete_selected)
        btn_layout.addWidget(delete_btn)

        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        self._db_history_dialog_state = {
            "dialog": dialog,
            "sessions": sessions,
            "list_widget": list_widget,
            "status_label": status_label,
            "load_btn": load_btn,
            "delete_btn": delete_btn,
            "close_btn": close_btn,
        }
        dialog.finished.connect(lambda *_: self._clear_db_history_dialog_state())
        dialog.exec()

    def _show_db_search(self):
        """자막 통합 검색 다이얼로그"""
        if not self.db:
            QMessageBox.warning(self, "알림", "데이터베이스가 초기화되지 않았습니다.")
            return

        query, ok = QInputDialog.getText(self, "자막 검색", "검색어:")
        query = query.strip() if ok and query else ""
        if not query:
            return

        self._run_db_task(
            "db_search",
            worker=lambda q=query: self.db.search_subtitles(q),
            context={"query": query},
            loading_text=f"DB 자막 검색 중... ({query[:15]})",
        )

    def _show_db_search_results(self, query: str, results: list[dict]) -> None:
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
        self._run_db_task(
            "db_stats",
            worker=lambda: self.db.get_statistics(),
            loading_text="DB 통계 조회 중...",
        )

    def _show_db_stats_dialog(self, stats: dict) -> None:
        msg = f"""
<h2>📊 데이터베이스 통계</h2>
<table>
<tr><td><b>총 세션 수:</b></td><td>{stats.get("total_sessions", 0):,}개</td></tr>
<tr><td><b>총 자막 수:</b></td><td>{stats.get("total_subtitles", 0):,}개</td></tr>
<tr><td><b>총 글자 수:</b></td><td>{stats.get("total_characters", 0):,}자</td></tr>
<tr><td><b>총 녹화 시간:</b></td><td>{stats.get("total_duration_hours", 0):.1f}시간</td></tr>
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
                dialog, "세션 파일 선택", f"{Config.SESSION_DIR}/", "JSON 파일 (*.json)"
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
                    dialog,
                    "기존 자막 처리",
                    f"현재 {len(self.subtitles)}개의 자막이 있습니다.\n\n"
                    "기존 자막을 병합 결과에 포함하시겠습니까?\n"
                    "(Yes: 포함하여 병합 / No: 기존 자막 무시하고 파일들만 병합)",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel,
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    return

                if reply == QMessageBox.StandardButton.Yes:
                    with self.subtitle_lock:
                        existing_subtitles = list(self.subtitles)

            merged = self._merge_sessions(
                file_paths,
                remove_duplicates=remove_dup_check.isChecked(),
                sort_by_time=sort_check.isChecked(),
                existing_subtitles=existing_subtitles,
            )

            if merged:
                self._replace_subtitles_and_refresh(merged)
                self._show_toast(f"병합 완료! {len(merged)}개 문장", "success")
                dialog.accept()

        merge_btn.clicked.connect(do_merge)
        btn_layout.addWidget(merge_btn)

        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)
        dialog.exec()

    def _clean_newlines(self):
        """줄넘김 정리: 문장 부호 분리 및 병합 (스마트 리플로우)"""
        # 자막이 없는 경우 처리
        if not self.subtitles:
            self._show_toast("정리할 자막이 없습니다.", "warning")
            return

        # 사용자 확인
        reply = QMessageBox.question(
            self,
            "줄넘김 정리 (Smart Reflow)",
            "자막 재정렬을 수행하시겠습니까?\n\n"
            "기능:\n"
            "1. 텍스트 내 타임스탬프([HH:MM:SS])를 감지하여 분리\n"
            "2. 문장 부호(. ? !) 기준으로 줄 바꿈\n"
            "3. 끊어진 문장 병합\n\n"
            "(주의: 되돌리기는 지원되지 않습니다.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.No:
            return

        # 병합/분리 로직 (utils 모듈 위임)
        try:
            old_count = len(self.subtitles)

            # 스레드 안전하게 복사본 생성 후 처리
            with self.subtitle_lock:
                current_subs = list(self.subtitles)

            # 처리 (시간 소요 가능성 있으므로 락 밖에서 수행 권장하지만, 데이터가 크지 않아 즉시 수행)
            new_subtitles = utils.reflow_subtitles(current_subs)

            if not new_subtitles:
                return

            # 원본과 개수 차이 확인
            logger.info(f"스마트 리플로우: {old_count} -> {len(new_subtitles)}")

            self._replace_subtitles_and_refresh(new_subtitles)

            # 결과 알림
            self._show_toast(f"정리 완료! ({len(new_subtitles)}개 문장)", "success")

        except Exception as e:
            logger.error(f"리플로우 중 오류: {e}")
            self._show_toast(f"오류 발생: {e}", "error")

    def _merge_sessions(
        self,
        file_paths: list,
        remove_duplicates: bool = True,
        sort_by_time: bool = True,
        existing_subtitles: list = None,
    ) -> list:
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
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                for item in data.get("subtitles", []):
                    try:
                        entry = SubtitleEntry.from_dict(item)
                        all_entries.append(entry)
                    except ValueError as e:
                        logger.warning(f"자막 항목 건너뜀 ({path}): {e}")

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
                2000,
            )
            event.ignore()
            return

        # 추출 중이면 종료 확인 후 먼저 안전 중지(큐 소진/마지막 자막 확정)
        if self.is_running:
            reply = QMessageBox.question(
                self,
                "종료",
                "추출 중입니다. 종료하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self._stop(for_app_exit=True)

        with self.subtitle_lock:
            subtitle_count = len(self.subtitles)

        # 저장하지 않은 자막이 있으면 확인
        if subtitle_count:
            reply = QMessageBox.question(
                self,
                "종료 확인",
                f"저장하지 않은 자막 {subtitle_count}개가 있습니다.\n\n"
                "저장하시겠습니까?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
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
                    with open(path, "w", encoding="utf-8") as f:
                        for entry in subtitles_snapshot:
                            f.write(
                                f"[{entry.timestamp.strftime('%H:%M:%S')}] {entry.text}\n"
                            )
                except Exception as e:
                    QMessageBox.critical(self, "오류", f"저장 실패: {e}")
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

        if self.realtime_file:
            try:
                self.realtime_file.close()
            except Exception as e:
                logger.debug(f"파일 닫기 오류: {e}")
            self.realtime_file = None

        # closeEvent 시에는 실행 여부와 무관하게 드라이버 정리를 시도한다.
        if self.driver:
            driver = self.driver
            self.driver = None
            self._force_quit_driver_with_timeout(
                driver, timeout=2.0, source="close_event_idle"
            )
        self._cleanup_detached_drivers_with_timeout(timeout=2.0)

        # 데이터베이스 연결 정리
        if getattr(self, "db", None):
            try:
                self.db.close_all()
            except Exception as e:
                logger.debug(f"DB 연결 종료 오류: {e}")

        logger.info("프로그램 종료")
        event.accept()

    def _toggle_top_header(self):
        """상단 영역(헤더/툴바) 표시/숨김 토글"""
        if self.top_header_container.isVisible():
            # 접기: 헤더 숨김 & 설정 그룹 접기
            self.top_header_container.hide()
            self.settings_group.set_collapsed(True)
            self.toggle_header_btn.setText("🔽 상단 펼치기")
        else:
            # 펼치기: 헤더 보임 & 설정 그룹 펼치기
            self.top_header_container.show()
            self.settings_group.set_collapsed(False)
            self.toggle_header_btn.setText("🔼 상단 접기")
