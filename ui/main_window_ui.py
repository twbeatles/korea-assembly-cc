# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowUIMixin(MainWindowHost):

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


    def _create_menu(self):
            menubar = self.menuBar()
            assert menubar is not None

            # 파일 메뉴
            file_menu = menubar.addMenu("파일")
            assert file_menu is not None

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

            save_hwp = QAction("HWP 저장 (한글, COM)", self)
            save_hwp.triggered.connect(self._save_hwp)
            file_menu.addAction(save_hwp)

            save_hwpx = QAction("HWPX 저장 (한글 호환)", self)
            save_hwpx.triggered.connect(self._save_hwpx)
            file_menu.addAction(save_hwpx)

            save_rtf = QAction("RTF 저장", self)
            save_rtf.triggered.connect(self._save_rtf)
            file_menu.addAction(save_rtf)

            file_menu.addSeparator()

            save_session = QAction("세션 저장", self)
            save_session.setShortcut("Ctrl+Shift+S")
            save_session.triggered.connect(self._save_session)
            file_menu.addAction(save_session)

            self.load_session_action = QAction("세션 불러오기", self)
            self.load_session_action.setShortcut("Ctrl+O")
            self.load_session_action.triggered.connect(self._load_session)
            file_menu.addAction(self.load_session_action)

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
            assert edit_menu is not None

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

            self.edit_subtitle_action = QAction("✏️ 자막 편집", self)
            self.edit_subtitle_action.setShortcut("Ctrl+E")
            self.edit_subtitle_action.setToolTip("선택한 자막을 편집합니다")
            self.edit_subtitle_action.triggered.connect(self._edit_subtitle)
            edit_menu.addAction(self.edit_subtitle_action)

            self.delete_subtitle_action = QAction("🗑️ 자막 삭제", self)
            self.delete_subtitle_action.setShortcut("Delete")
            self.delete_subtitle_action.setToolTip("선택한 자막을 삭제합니다")
            self.delete_subtitle_action.triggered.connect(self._delete_subtitle)
            edit_menu.addAction(self.delete_subtitle_action)

            edit_menu.addSeparator()

            copy_action = QAction("클립보드 복사", self)
            # copy_action.setShortcut("Ctrl+C") # 텍스트 선택 복사 충돌 방지
            copy_action.setToolTip("전체 자막을 클립보드에 복사합니다")
            copy_action.triggered.connect(self._copy_to_clipboard)
            edit_menu.addAction(copy_action)

            self.clear_action = QAction("내용 지우기", self)
            self.clear_action.setToolTip("모든 자막 내용을 삭제합니다")
            self.clear_action.triggered.connect(self._clear_text)
            edit_menu.addAction(self.clear_action)

            # 보기 메뉴
            view_menu = menubar.addMenu("보기")
            assert view_menu is not None

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
            assert font_menu is not None
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
            assert tools_menu is not None

            self.merge_action = QAction("📎 자막 병합...", self)
            self.merge_action.setShortcut("Ctrl+Shift+M")
            self.merge_action.setToolTip("여러 세션 파일을 하나로 병합합니다")
            self.merge_action.triggered.connect(self._show_merge_dialog)
            tools_menu.addAction(self.merge_action)

            # 줄넘김 정리
            self.clean_newlines_action = QAction("줄넘김 정리", self)
            self.clean_newlines_action.setShortcut("Ctrl+Shift+L")
            self.clean_newlines_action.setToolTip(
                "문장 부호로 끝나지 않는 줄을 병합하여 문장을 정리합니다"
            )
            self.clean_newlines_action.triggered.connect(self._clean_newlines)
            tools_menu.addAction(self.clean_newlines_action)

            # 데이터베이스 메뉴 (#26)
            db_menu = menubar.addMenu("데이터베이스")
            assert db_menu is not None

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
            assert help_menu is not None

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
                "자막이 확정될 때마다 자동으로 파일에 저장합니다\n저장 위치: realtime_output 폴더"
            )

            self.headless_check = QCheckBox("🔇 헤드리스 모드 (인터넷창 숨김)")
            self.headless_check.setChecked(False)
            self.headless_check.setToolTip(
                "Chrome 브라우저 창을 숨기고 백그라운드에서 실행합니다.\n자막 추출 중 다른 작업을 할 수 있습니다."
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
                ]
            )

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
            current_style = f"color: {color};"
            if self.status_label.text() != rendered:
                self.status_label.setText(rendered)
            if self.status_label.styleSheet() != current_style:
                self.status_label.setStyleSheet(current_style)
            self._last_status_message = rendered


    def _update_count_label(self):
            """자막 카운트 라벨 업데이트"""
            with self.subtitle_lock:
                count = len(self.subtitles)
            chars = self._cached_total_chars
            rendered = f"📝 {count}문장 | {chars:,}자"
            if self.count_label.text() != rendered:
                self.count_label.setText(rendered)


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

            self.connection_indicator.setText(icon)
            self.connection_indicator.setToolTip(tooltip)
            self.connection_indicator.setStyleSheet(
                f"background: transparent; border: none; font-size: 12px; color: {color};"
            )


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
                section_action = QAction("── 사용자 정의 ──", self)
                section_action.setEnabled(False)
                self.preset_menu.addAction(section_action)

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
                    utils.atomic_write_json(
                        path,
                        data,
                        ensure_ascii=False,
                        indent=2,
                    )

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

                    if "committee" in data and isinstance(data["committee"], dict):
                        for name, url in data["committee"].items():
                            if self.committee_presets.get(name) != url:
                                self.committee_presets[name] = url
                                imported_count += 1

                    # 사용자 정의 프리셋 가져오기 (기존 것에 추가)
                    if "custom" in data and isinstance(data["custom"], dict):
                        for name, url in data["custom"].items():
                            if self.custom_presets.get(name) != url:
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


    def _reset_ui(self):
            self.is_running = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.url_combo.setEnabled(True)
            self.selector_combo.setEnabled(True)
            self.progress.hide()
            self.stats_timer.stop()
            self.backup_timer.stop()
            self._sync_runtime_action_state()


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
    <li><b>HWPX</b> - 한글 문서 (기본 포맷)</li>
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
    <p>실행 시간, 글자 수, 공백 기준 단어 수, 분당 글자 수를 표시합니다.</p>
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
