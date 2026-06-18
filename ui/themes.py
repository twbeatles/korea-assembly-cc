# -*- coding: utf-8 -*-

"""테마 정의.

다크/라이트 테마는 단일 시맨틱 팔레트(`_DARK_PALETTE`, `_LIGHT_PALETTE`)에서
`_build_theme()`로 생성한다. 컴포넌트별 스타일은 인라인 `setStyleSheet` 대신
`objectName` 기반 QSS 규칙으로 두 테마에 모두 정의해, 테마 전환 시
스타일시트 교체만으로 모든 위젯이 일관되게 다시 칠해지도록 한다.

`objectName` 계약 (layout.py와 공유):
    QFrame#quickToolbar        상단 퀵 액션 툴바
    QPushButton#toolbarButton  툴바 버튼
    QPushButton#themeToggle    테마 토글 버튼
    QPushButton#ghostButton    상단/통계 접기 버튼 등 보조 버튼
    QPushButton#scrollToBottom 최신 자막 플로팅 버튼
    QFrame#searchBar           검색바 컨테이너
    QLineEdit#searchInput      검색 입력
    QPushButton#searchNavButton 검색 이전/다음
    QPushButton#searchCloseButton 검색 닫기
    QLabel#searchCount         검색 결과 카운트
    QFrame#statusBar           하단 상태바
    QFrame#statusSeparator     상태바 구분선
    QLabel#countLabel          자막 카운트 라벨
    QLabel#statChip            통계 칩 라벨
    QFrame#previewFrame        실시간 미리보기 컨테이너
    QLabel#previewTitle        미리보기 제목
"""

from string import Template

# ============================================================
# 시맨틱 팔레트
# ============================================================

_DARK_PALETTE = {
    "bg": "#0d1117",
    "surface": "#161b22",
    "surface_alt": "#21262d",
    "border": "#30363d",
    "border_hover": "#484f58",
    "text": "#e6edf3",
    "text_muted": "#8b949e",
    "accent": "#58a6ff",
    "accent2": "#8892ff",
    "accent3": "#a371f7",
    "accent_light": "#79b8ff",
    "accent_rgb": "88, 166, 255",
    "selection": "#264f78",
    "input_focus_bg": "#0d1117",
    "danger": "#f85149",
    "danger_light": "#ff7b72",
    "danger_rgb": "248, 81, 73",
    "success": "#3fb950",
    "success_dark": "#1a7f37",
    "success_mid": "#238636",
    "success_border": "#2ea043",
    "success_text": "#e6edf3",
    "danger_btn_top": "#da3633",
    "danger_btn_bottom": "#b62324",
    "danger_btn_text": "#e6edf3",
    "status_bg": "rgba(48, 54, 61, 0.3)",
    "btn_top": "#21262d",
    "btn_bottom": "#161b22",
    "btn_hover_top": "#30363d",
    "btn_hover_bottom": "#21262d",
    "btn_pressed": "#161b22",
    "btn_disabled_bg": "#21262d",
    "btn_disabled_text": "#484f58",
    "header_grad_a": "rgba(88, 166, 255, 0.1)",
    "header_grad_b": "rgba(136, 146, 255, 0.1)",
    "menu_bar_bg": "#161b22",
    "scrollbar_bg": "#0d1117",
    "scrollbar_handle": "#30363d",
    "scrollbar_handle_hover": "#484f58",
}

_LIGHT_PALETTE = {
    "bg": "#ffffff",
    "surface": "#f6f8fa",
    "surface_alt": "#eaeef2",
    "border": "#d0d7de",
    "border_hover": "#afb8c1",
    "text": "#24292f",
    "text_muted": "#57606a",
    "accent": "#0969da",
    "accent2": "#8250df",
    "accent3": "#bf3989",
    "accent_light": "#218bff",
    "accent_rgb": "9, 105, 218",
    "selection": "#ddf4ff",
    "input_focus_bg": "#ffffff",
    "danger": "#cf222e",
    "danger_light": "#fa4549",
    "danger_rgb": "207, 34, 46",
    "success": "#2da44e",
    "success_dark": "#1a7f37",
    "success_mid": "#2da44e",
    "success_border": "#1a7f37",
    "success_text": "#ffffff",
    "danger_btn_top": "#cf222e",
    "danger_btn_bottom": "#a40e26",
    "danger_btn_text": "#ffffff",
    "status_bg": "rgba(208, 215, 222, 0.4)",
    "btn_top": "#f6f8fa",
    "btn_bottom": "#eaeef2",
    "btn_hover_top": "#f3f4f6",
    "btn_hover_bottom": "#ebecf0",
    "btn_pressed": "#eaeef2",
    "btn_disabled_bg": "#f6f8fa",
    "btn_disabled_text": "#8c959f",
    "header_grad_a": "rgba(9, 105, 218, 0.08)",
    "header_grad_b": "rgba(130, 80, 223, 0.08)",
    "menu_bar_bg": "#f6f8fa",
    "scrollbar_bg": "#f6f8fa",
    "scrollbar_handle": "#afb8c1",
    "scrollbar_handle_hover": "#8c959f",
}


# ============================================================
# QSS 템플릿 (string.Template, $토큰)
# ============================================================

_THEME_TEMPLATE = Template(
    """
/* ===== 공통 모던 디자인 (팔레트 기반) ===== */
QMainWindow, QWidget {
    background-color: $bg;
    color: $text;
    font-family: '맑은 고딕', 'Malgun Gothic', 'Segoe UI', sans-serif;
}

/* 라벨 */
QLabel {
    color: $text;
}
QLabel#headerLabel {
    font-size: 20px;
    font-weight: bold;
    color: $accent;
    padding: 12px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $header_grad_a, stop:1 $header_grad_b);
    border-radius: 10px;
}

/* 버튼 기본 스타일 */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $btn_top, stop:1 $btn_bottom);
    color: $text;
    border: 1px solid $border;
    padding: 10px 22px;
    border-radius: 8px;
    font-weight: bold;
    font-size: 12px;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $btn_hover_top, stop:1 $btn_hover_bottom);
    border-color: $accent;
}
QPushButton:pressed {
    background: $btn_pressed;
    border-color: $accent;
}
QPushButton:disabled {
    background-color: $btn_disabled_bg;
    color: $btn_disabled_text;
    border-color: $btn_disabled_bg;
}

/* 시작 버튼 - 그린 그라데이션 */
QPushButton#startBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $success_mid, stop:1 $success_dark);
    color: $success_text;
    border: 1px solid $success_border;
    font-size: 14px;
    min-width: 130px;
    padding: 12px 24px;
}
QPushButton#startBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $success, stop:1 $success_mid);
    border-color: $success;
}
QPushButton#startBtn:pressed {
    background: $success_dark;
}

/* 중지 버튼 - 레드 그라데이션 */
QPushButton#stopBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $danger_btn_top, stop:1 $danger_btn_bottom);
    color: $danger_btn_text;
    border: 1px solid $danger;
    font-size: 14px;
    min-width: 130px;
    padding: 12px 24px;
}
QPushButton#stopBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $danger_light, stop:1 $danger_btn_top);
    border-color: $danger;
}
QPushButton#stopBtn:pressed {
    background: $danger_btn_bottom;
}

/* ===== 퀵 액션 툴바 ===== */
QFrame#quickToolbar {
    background-color: rgba($accent_rgb, 0.05);
    border: 1px solid rgba($accent_rgb, 0.15);
    border-radius: 10px;
}
QPushButton#toolbarButton {
    background-color: rgba($accent_rgb, 0.10);
    border: 1px solid rgba($accent_rgb, 0.20);
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton#toolbarButton:hover {
    background-color: rgba($accent_rgb, 0.20);
    border-color: rgba($accent_rgb, 0.40);
}
QPushButton#toolbarButton:pressed {
    background-color: rgba($accent_rgb, 0.30);
}
QPushButton#themeToggle {
    background-color: transparent;
    border: none;
    font-size: 18px;
    padding: 4px 8px;
}
QPushButton#themeToggle:hover {
    background-color: rgba($accent_rgb, 0.10);
    border-radius: 6px;
}

/* 보조(고스트) 버튼 - 상단/통계 접기 등 */
QPushButton#ghostButton {
    background-color: rgba($accent_rgb, 0.10);
    border: 1px solid rgba($accent_rgb, 0.30);
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 500;
}
QPushButton#ghostButton:hover {
    background-color: rgba($accent_rgb, 0.20);
}

/* 최신 자막 플로팅 버튼 */
QPushButton#scrollToBottom {
    background-color: $accent;
    color: #ffffff;
    border: none;
    border-radius: 16px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: bold;
}
QPushButton#scrollToBottom:hover {
    background-color: $accent_light;
}

/* 입력 필드 */
QLineEdit, QComboBox {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 10px 14px;
    color: $text;
    font-size: 13px;
    selection-background-color: $selection;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid $accent;
    background-color: $input_focus_bg;
}
QLineEdit:hover, QComboBox:hover {
    border-color: $border_hover;
}
QComboBox::drop-down {
    border: none;
    padding-right: 10px;
}
QComboBox::down-arrow {
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    selection-background-color: $surface_alt;
    selection-color: $accent;
    padding: 5px;
    outline: none;
}

/* 텍스트 편집 영역 - 자막 뷰어 */
QTextEdit {
    background-color: $bg;
    border: 1px solid $border;
    border-radius: 14px;
    padding: 20px;
    color: $text;
    font-size: 15px;
    line-height: 1.8;
    selection-background-color: $selection;
}
QTextEdit:focus {
    border-color: $accent;
}

/* 그룹박스 - 카드 스타일 */
QGroupBox {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 12px;
    margin-top: 20px;
    padding: 20px 15px 15px 15px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 18px;
    padding: 0 10px;
    color: $accent;
    font-size: 13px;
    background-color: $bg;
    border-radius: 4px;
}

/* 체크박스 */
QCheckBox {
    spacing: 10px;
    color: $text;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid $border;
    background: $surface;
}
QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent, stop:1 $accent2);
    border-color: $accent;
}
QCheckBox::indicator:hover {
    border-color: $accent;
}
QCheckBox::indicator:checked:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_light, stop:1 $accent2);
}

/* 프로그레스바 */
QProgressBar {
    background-color: $surface_alt;
    border-radius: 6px;
    height: 8px;
    text-align: center;
    border: none;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent, stop:0.5 $accent2, stop:1 $accent3);
    border-radius: 6px;
}

/* ===== 실시간 미리보기 ===== */
QFrame#previewFrame {
    background-color: rgba($accent_rgb, 0.08);
    border: 1px solid rgba($accent_rgb, 0.25);
    border-radius: 8px;
}
QLabel#previewTitle {
    background: transparent;
    border: none;
    font-weight: 600;
    color: $accent;
}
QLabel#previewText {
    background: transparent;
    border: none;
}

/* ===== 통계 패널 ===== */
QLabel#statChip {
    padding: 6px 8px;
    border-radius: 6px;
    background-color: rgba($accent_rgb, 0.08);
}

/* ===== 검색바 ===== */
QFrame#searchBar {
    background-color: rgba($accent_rgb, 0.05);
    border: 1px solid rgba($accent_rgb, 0.20);
    border-radius: 10px;
}
QLineEdit#searchInput {
    background-color: transparent;
    border: none;
    padding: 6px;
    font-size: 13px;
}
QLineEdit#searchInput:focus {
    background-color: transparent;
    border: none;
}
QLabel#searchCount {
    color: $text_muted;
    font-size: 12px;
    background: transparent;
    border: none;
    padding: 0 8px;
}
QPushButton#searchNavButton {
    background-color: rgba($accent_rgb, 0.10);
    border: 1px solid rgba($accent_rgb, 0.30);
    border-radius: 6px;
    padding: 6px;
    font-size: 12px;
    min-width: 32px;
}
QPushButton#searchNavButton:hover {
    background-color: rgba($accent_rgb, 0.20);
    border-color: $accent;
}
QPushButton#searchCloseButton {
    background-color: rgba($danger_rgb, 0.10);
    border: 1px solid rgba($danger_rgb, 0.30);
    border-radius: 6px;
    padding: 6px;
    font-size: 12px;
    min-width: 32px;
}
QPushButton#searchCloseButton:hover {
    background-color: rgba($danger_rgb, 0.20);
    border-color: $danger;
}

/* ===== 상태바 ===== */
QFrame#statusBar {
    background-color: $status_bg;
    border-radius: 10px;
}
QFrame#statusSeparator {
    background-color: rgba($accent_rgb, 0.30);
    max-width: 1px;
    border: none;
}
QLabel#countLabel {
    color: $text_muted;
    background: rgba($accent_rgb, 0.08);
    border: none;
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 500;
}

/* 메뉴바 */
QMenuBar {
    background-color: $menu_bar_bg;
    color: $text;
    padding: 6px;
    border-bottom: 1px solid $border;
}
QMenuBar::item {
    padding: 8px 16px;
    border-radius: 6px;
}
QMenuBar::item:selected {
    background-color: $surface_alt;
}

/* 메뉴 */
QMenu {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    padding: 10px 28px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: $surface_alt;
    color: $accent;
}
QMenu::separator {
    height: 1px;
    background-color: $border;
    margin: 6px 10px;
}

/* 스크롤바 */
QScrollBar:vertical {
    background: $scrollbar_bg;
    width: 12px;
    border-radius: 6px;
    margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background: $scrollbar_handle;
    border-radius: 5px;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover {
    background: $scrollbar_handle_hover;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background: $scrollbar_bg;
    height: 12px;
    border-radius: 6px;
    margin: 2px 4px;
}
QScrollBar::handle:horizontal {
    background: $scrollbar_handle;
    border-radius: 5px;
    min-width: 40px;
}
QScrollBar::handle:horizontal:hover {
    background: $scrollbar_handle_hover;
}

/* 스플리터 */
QSplitter::handle {
    background: $border;
    border-radius: 2px;
}
QSplitter::handle:hover {
    background: $accent;
}

/* 프레임 */
QFrame {
    border: none;
}
"""
)


def _build_theme(palette: dict[str, str]) -> str:
    """팔레트 토큰을 적용해 완성된 QSS 문자열을 만든다."""
    return _THEME_TEMPLATE.substitute(palette)


DARK_THEME = _build_theme(_DARK_PALETTE)
LIGHT_THEME = _build_theme(_LIGHT_PALETTE)


# 토스트 등 런타임 위젯이 팔레트 토큰을 재사용할 수 있도록 노출한다.
def get_palette(is_dark: bool) -> dict[str, str]:
    """현재 테마 팔레트 사본을 반환한다."""
    return dict(_DARK_PALETTE if is_dark else _LIGHT_PALETTE)
