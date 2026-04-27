# -*- coding: utf-8 -*-

from __future__ import annotations

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowUILayoutMixin(MainWindowHost):
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
            self.clean_btn = QPushButton("✨ 줄넘김 정리")
            self.clean_btn.setStyleSheet(toolbar_btn_style)
            self.clean_btn.setToolTip(
                "문장 부호로 끊어지지 않은 줄을 자동으로 병합 (Ctrl+Shift+L)"
            )
            self.clean_btn.clicked.connect(self._clean_newlines)

            # 자막 지우기 버튼
            self.clear_btn = QPushButton("🗑️ 지우기")
            self.clear_btn.setStyleSheet(toolbar_btn_style)
            self.clear_btn.setToolTip("현재 자막 목록 초기화")
            self.clear_btn.clicked.connect(self._clear_subtitles)

            toolbar_layout.addWidget(quick_save_btn)
            toolbar_layout.addWidget(search_btn)
            toolbar_layout.addWidget(copy_btn)
            toolbar_layout.addWidget(self.clean_btn)
            toolbar_layout.addWidget(self.clear_btn)
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
            self.tag_btn.setToolTip(
                "현재 URL에 태그 추가/편집\n예: 본회의, 법사위, 상임위\n추출 중에는 변경할 수 없습니다"
            )
            self.tag_btn.setFixedWidth(90)
            self.tag_btn.clicked.connect(self._edit_url_tag)
            url_layout.addWidget(self.tag_btn)

            # 상임위원회 프리셋 버튼
            self.preset_btn = QPushButton("📋 상임위")
            self.preset_btn.setToolTip(
                "상임위원회 프리셋 선택\n빠른 URL 입력을 위한 기능\n추출 중에는 변경할 수 없습니다"
            )
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
            self.live_btn.setToolTip(
                "현재/종료 생중계 목록을 확인하고 선택합니다\n추출 중에는 변경할 수 없습니다"
            )
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

            self.auto_clean_newlines_check = QCheckBox("✨ 자동 줄넘김 정리")
            self.auto_clean_newlines_check.setChecked(
                bool(getattr(self, "auto_clean_newlines_enabled", True))
            )
            self.auto_clean_newlines_check.setToolTip(
                "수집 중 줄바꿈과 빈 줄을 자동으로 한 줄로 정리합니다.\n"
                "자막 내용은 유지하고 개행만 정리합니다."
            )
            self.auto_clean_newlines_check.toggled.connect(
                self._toggle_auto_clean_newlines_option
            )

            self.realtime_save_check = QCheckBox("💾 실시간 저장")
            self.realtime_save_check.setChecked(False)
            self.realtime_save_check.setToolTip(
                "자막이 확정될 때마다 자동으로 파일에 저장합니다\n"
                "저장 위치: realtime_output 폴더\n"
                "추출 시작 전에만 변경할 수 있습니다"
            )

            self.headless_check = QCheckBox("🔇 헤드리스 모드 (인터넷창 숨김)")
            self.headless_check.setChecked(False)
            self.headless_check.setToolTip(
                "Chrome 브라우저 창을 숨기고 백그라운드에서 실행합니다.\n"
                "자막 추출 중 다른 작업을 할 수 있습니다.\n"
                "추출 시작 전에만 변경할 수 있습니다."
            )
            options_layout.addWidget(self.auto_scroll_check)
            options_layout.addWidget(self.auto_clean_newlines_check)
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
            subtitle_scrollbar = self.subtitle_text.verticalScrollBar()
            assert subtitle_scrollbar is not None
            subtitle_scrollbar.valueChanged.connect(self._on_scroll_changed)

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
            self.stat_words = QLabel("📖 공백 기준 단어 수: 0")
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
            self.search_input.textChanged.connect(self._schedule_search)
            self.search_input.returnPressed.connect(self._trigger_search_now)
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

            self.realtime_status_label = QLabel("")
            self.realtime_status_label.setStyleSheet(
                "background: transparent; border: none; font-weight: 600;"
            )
            self.realtime_status_label.hide()
            self.db_status_label = QLabel("")
            self.db_status_label.setStyleSheet(
                "background: transparent; border: none; font-weight: 600;"
            )
            self.db_status_label.hide()

            status_layout.addWidget(self.status_label)
            status_layout.addStretch()
            status_layout.addWidget(self.connection_indicator)
            status_layout.addWidget(separator)
            status_layout.addWidget(self.realtime_status_label)
            status_layout.addWidget(self.db_status_label)
            status_layout.addWidget(self.count_label)

            layout.addWidget(status_frame)

            # 검색 상태
            self.search_matches = []
            self.search_idx = 0
            self._runtime_sensitive_controls.extend(
                [
                    self.load_session_action,
                    self.edit_subtitle_action,
                    self.delete_subtitle_action,
                    self.clear_action,
                    self.merge_action,
                    self.clean_newlines_action,
                    self.clean_btn,
                    self.clear_btn,
                    self.preset_btn,
                    self.live_btn,
                    self.tag_btn,
                    self.realtime_save_check,
                    self.headless_check,
                    self.keep_browser_action,
                ]
            )

            # 저장된 폰트 크기 적용
            self._set_font_size(self.font_size)


