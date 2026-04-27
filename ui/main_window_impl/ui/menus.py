# -*- coding: utf-8 -*-

from __future__ import annotations

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowUIMenuMixin(MainWindowHost):
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
            copy_action.setShortcut("Ctrl+Shift+C")
            copy_action.setToolTip("전체 자막을 클립보드에 복사합니다")
            copy_action.triggered.connect(self._copy_to_clipboard)
            edit_menu.addAction(copy_action)

            self.clear_action = QAction("내용 지우기", self)
            self.clear_action.setToolTip("모든 자막 내용을 삭제합니다")
            self.clear_action.triggered.connect(self._clear_text)
            edit_menu.addAction(self.clear_action)

            self.undo_destructive_action = QAction("마지막 파괴적 변경 되돌리기", self)
            self.undo_destructive_action.setShortcut("Ctrl+Z")
            self.undo_destructive_action.setToolTip(
                "마지막 삭제/정리/병합 변경을 한 번 되돌립니다"
            )
            self.undo_destructive_action.triggered.connect(
                self._restore_last_destructive_change
            )
            edit_menu.addAction(self.undo_destructive_action)

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

            self.keep_browser_action = QAction("중지 시 Chrome 창 유지", self)
            self.keep_browser_action.setCheckable(True)
            self.keep_browser_action.setChecked(self.keep_browser_on_stop)
            self.keep_browser_action.setToolTip(
                "수동 중지 시에만 Chrome 창을 남깁니다. 앱 종료와 다음 시작 전에는 정리됩니다."
            )
            self.keep_browser_action.triggered.connect(
                self._toggle_keep_browser_on_stop
            )
            view_menu.addAction(self.keep_browser_action)

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

            self.db_history_action = QAction("📋 세션 히스토리", self)
            self.db_history_action.setToolTip("최근 저장 세션을 점진적으로 불러와 확인합니다")
            self.db_history_action.triggered.connect(self._show_db_history)
            db_menu.addAction(self.db_history_action)

            self.db_search_action = QAction("🔍 자막 검색", self)
            self.db_search_action.setToolTip(
                "부분문자열 기준으로 검색 결과를 점진적으로 불러와 확인합니다"
            )
            self.db_search_action.triggered.connect(self._show_db_search)
            db_menu.addAction(self.db_search_action)

            db_menu.addSeparator()

            self.db_stats_action = QAction("📊 전체 통계", self)
            self.db_stats_action.setToolTip("데이터베이스 전체 통계를 확인합니다")
            self.db_stats_action.triggered.connect(self._show_db_stats)
            db_menu.addAction(self.db_stats_action)

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


