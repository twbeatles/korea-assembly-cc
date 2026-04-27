# -*- coding: utf-8 -*-

from __future__ import annotations

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowUIHelpMixin(MainWindowHost):
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
        <li>실시간 저장: 자막 실시간 파일 저장 (추출 시작 전 설정)</li>
        <li>헤드리스 모드: 브라우저 창 숨기고 실행 (추출 시작 전 설정)</li>
        </ul>
    </li>
    <li><b>시작</b> 버튼 클릭 (또는 F5)</li>
    <li>자막 추출 완료 후 <b>파일 저장</b></li>
    </ol>

    <h3>⌨️ 주요 단축키</h3>
    <table>
    <tr><td><b>F5</b></td><td>시작</td></tr>
    <tr><td><b>Escape</b></td><td>검색창 닫기 / 추출 중지</td></tr>
    <tr><td><b>Ctrl+F</b></td><td>검색</td></tr>
    <tr><td><b>F3</b></td><td>다음 검색</td></tr>
    <tr><td><b>Ctrl+T</b></td><td>테마 전환</td></tr>
    <tr><td><b>Ctrl+S</b></td><td>TXT 저장</td></tr>
    <tr><td><b>Ctrl+Shift+C</b></td><td>전체 자막 복사</td></tr>
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
    <tr><td><b>Escape</b></td><td>검색창 닫기 / 추출 중지</td></tr>
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
    <tr><td><b>Ctrl+Shift+C</b></td><td>전체 자막 복사</td></tr>
    <tr><td><b>Ctrl+C</b></td><td>선택한 텍스트 복사</td></tr>
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
    3초 동안 자막이 변경되지 않으면 자동으로 확정됩니다.</p>

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
    자막 추출 중 다른 작업을 할 수 있으며, 실행 중에는 변경할 수 없습니다.</p>

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

    <p><b>© 2024-2026</b></p>
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
