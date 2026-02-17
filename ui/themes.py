# -*- coding: utf-8 -*-

DARK_THEME = """
/* ===== 다크 테마 - 프리미엄 모던 디자인 ===== */
QMainWindow, QWidget {
    background-color: #0d1117;
    color: #e6edf3;
    font-family: '맑은 고딕', 'Malgun Gothic', 'Segoe UI', sans-serif;
}

/* 라벨 */
QLabel { 
    color: #e6edf3; 
}
QLabel#headerLabel {
    font-size: 20px;
    font-weight: bold;
    color: #58a6ff;
    padding: 12px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(88, 166, 255, 0.1), stop:1 rgba(136, 146, 255, 0.1));
    border-radius: 10px;
}

/* 버튼 기본 스타일 */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #21262d, stop:1 #161b22);
    color: #e6edf3;
    border: 1px solid #30363d;
    padding: 10px 22px;
    border-radius: 8px;
    font-weight: bold;
    font-size: 12px;
}
QPushButton:hover { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #30363d, stop:1 #21262d);
    border-color: #58a6ff;
}
QPushButton:pressed {
    background: #161b22;
    border-color: #58a6ff;
}
QPushButton:disabled { 
    background-color: #21262d; 
    color: #484f58;
    border-color: #21262d;
}

/* 시작 버튼 - 그린 그라데이션 */
QPushButton#startBtn { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #238636, stop:1 #1a7f37);
    border: 1px solid #2ea043;
    font-size: 14px;
    min-width: 130px;
    padding: 12px 24px;
}
QPushButton#startBtn:hover { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2ea043, stop:1 #238636);
    border-color: #3fb950;
}
QPushButton#startBtn:pressed {
    background: #1a7f37;
}

/* 중지 버튼 - 레드 그라데이션 */
QPushButton#stopBtn { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #da3633, stop:1 #b62324);
    border: 1px solid #f85149;
    font-size: 14px;
    min-width: 130px;
    padding: 12px 24px;
}
QPushButton#stopBtn:hover { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f85149, stop:1 #da3633);
    border-color: #ff7b72;
}
QPushButton#stopBtn:pressed {
    background: #b62324;
}

/* 입력 필드 */
QLineEdit, QComboBox {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 10px 14px;
    color: #e6edf3;
    font-size: 13px;
    selection-background-color: #264f78;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #58a6ff;
    background-color: #0d1117;
}
QLineEdit:hover, QComboBox:hover {
    border-color: #484f58;
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
    background-color: #161b22;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 8px;
    selection-background-color: #21262d;
    selection-color: #58a6ff;
    padding: 5px;
    outline: none;
}

/* 텍스트 편집 영역 - 자막 뷰어 */
QTextEdit {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 14px;
    padding: 20px;
    color: #e6edf3;
    font-size: 15px;
    line-height: 1.8;
    selection-background-color: #264f78;
}
QTextEdit:focus {
    border-color: #58a6ff;
}

/* 그룹박스 - 카드 스타일 */
QGroupBox {
    background-color: rgba(22, 27, 34, 0.6);
    border: 1px solid #30363d;
    border-radius: 12px;
    margin-top: 20px;
    padding: 20px 15px 15px 15px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 18px;
    padding: 0 10px;
    color: #58a6ff;
    font-size: 13px;
    background-color: #0d1117;
    border-radius: 4px;
}

/* 체크박스 */
QCheckBox {
    spacing: 10px;
    color: #e6edf3;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #30363d;
    background: #161b22;
}
QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #58a6ff, stop:1 #8892ff);
    border-color: #58a6ff;
}
QCheckBox::indicator:hover {
    border-color: #58a6ff;
}
QCheckBox::indicator:checked:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #79b8ff, stop:1 #a0aaff);
}

/* 프로그레스바 */
QProgressBar {
    background-color: #21262d;
    border-radius: 6px;
    height: 8px;
    text-align: center;
    border: none;
}
QProgressBar::chunk { 
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #58a6ff, stop:0.5 #8892ff, stop:1 #a371f7);
    border-radius: 6px; 
}

/* 메뉴바 */
QMenuBar { 
    background-color: #161b22; 
    color: #e6edf3;
    padding: 6px;
    border-bottom: 1px solid #21262d;
}
QMenuBar::item { 
    padding: 8px 16px;
    border-radius: 6px;
}
QMenuBar::item:selected { 
    background-color: #21262d; 
}

/* 메뉴 */
QMenu { 
    background-color: #161b22; 
    color: #e6edf3; 
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item { 
    padding: 10px 28px;
    border-radius: 6px;
}
QMenu::item:selected { 
    background-color: #21262d;
    color: #58a6ff;
}
QMenu::separator {
    height: 1px;
    background-color: #30363d;
    margin: 6px 10px;
}

/* 스크롤바 */
QScrollBar:vertical {
    background: #0d1117;
    width: 12px;
    border-radius: 6px;
    margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 5px;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover {
    background: #484f58;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background: #0d1117;
    height: 12px;
    border-radius: 6px;
    margin: 2px 4px;
}
QScrollBar::handle:horizontal {
    background: #30363d;
    border-radius: 5px;
    min-width: 40px;
}
QScrollBar::handle:horizontal:hover {
    background: #484f58;
}

/* 스플리터 */
QSplitter::handle {
    background: #30363d;
    border-radius: 2px;
}
QSplitter::handle:hover {
    background: #58a6ff;
}

/* 프레임 */
QFrame {
    border: none;
}
"""

LIGHT_THEME = """
/* ===== 라이트 테마 - 클린 모던 디자인 ===== */
QMainWindow, QWidget {
    background-color: #ffffff;
    color: #24292f;
    font-family: '맑은 고딕', 'Malgun Gothic', 'Segoe UI', sans-serif;
}

/* 라벨 */
QLabel { 
    color: #24292f; 
}
QLabel#headerLabel {
    font-size: 20px;
    font-weight: bold;
    color: #0969da;
    padding: 12px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(9, 105, 218, 0.08), stop:1 rgba(130, 80, 223, 0.08));
    border-radius: 10px;
}

/* 버튼 기본 스타일 */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f6f8fa, stop:1 #eaeef2);
    color: #24292f;
    border: 1px solid #d0d7de;
    padding: 10px 22px;
    border-radius: 8px;
    font-weight: bold;
    font-size: 12px;
}
QPushButton:hover { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f3f4f6, stop:1 #ebecf0);
    border-color: #afb8c1;
}
QPushButton:pressed {
    background: #eaeef2;
    border-color: #afb8c1;
}
QPushButton:disabled { 
    background-color: #f6f8fa; 
    color: #8c959f;
    border-color: #d0d7de;
}

/* 시작 버튼 - 그린 그라데이션 */
QPushButton#startBtn { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2da44e, stop:1 #1a7f37);
    color: white;
    border: 1px solid #1a7f37;
    font-size: 14px;
    min-width: 130px;
    padding: 12px 24px;
}
QPushButton#startBtn:hover { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3fb950, stop:1 #2da44e);
    border-color: #2da44e;
}
QPushButton#startBtn:pressed {
    background: #1a7f37;
}

/* 중지 버튼 - 레드 그라데이션 */
QPushButton#stopBtn { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #cf222e, stop:1 #a40e26);
    color: white;
    border: 1px solid #a40e26;
    font-size: 14px;
    min-width: 130px;
    padding: 12px 24px;
}
QPushButton#stopBtn:hover { 
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fa4549, stop:1 #cf222e);
    border-color: #cf222e;
}
QPushButton#stopBtn:pressed {
    background: #a40e26;
}

/* 입력 필드 */
QLineEdit, QComboBox {
    background-color: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    padding: 10px 14px;
    color: #24292f;
    font-size: 13px;
    selection-background-color: #ddf4ff;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #0969da;
    background-color: #ffffff;
}
QLineEdit:hover, QComboBox:hover {
    border-color: #afb8c1;
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
    background-color: #ffffff;
    color: #24292f;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    selection-background-color: #ddf4ff;
    selection-color: #0969da;
    padding: 5px;
    outline: none;
}

/* 텍스트 편집 영역 - 자막 뷰어 */
QTextEdit {
    background-color: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 14px;
    padding: 20px;
    color: #24292f;
    font-size: 15px;
    line-height: 1.8;
    selection-background-color: #ddf4ff;
}
QTextEdit:focus {
    border-color: #0969da;
}

/* 그룹박스 - 카드 스타일 */
QGroupBox {
    background-color: #f6f8fa;
    border: 1px solid #d0d7de;
    border-radius: 12px;
    margin-top: 20px;
    padding: 20px 15px 15px 15px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 18px;
    padding: 0 10px;
    color: #0969da;
    font-size: 13px;
    background-color: #ffffff;
    border-radius: 4px;
}

/* 체크박스 */
QCheckBox {
    spacing: 10px;
    color: #24292f;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #d0d7de;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0969da, stop:1 #8250df);
    border-color: #0969da;
}
QCheckBox::indicator:hover {
    border-color: #0969da;
}
QCheckBox::indicator:checked:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #218bff, stop:1 #a475f9);
}

/* 프로그레스바 */
QProgressBar {
    background-color: #eaeef2;
    border-radius: 6px;
    height: 8px;
    text-align: center;
    border: none;
}
QProgressBar::chunk { 
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0969da, stop:0.5 #8250df, stop:1 #bf3989);
    border-radius: 6px; 
}

/* 메뉴바 */
QMenuBar { 
    background-color: #f6f8fa; 
    color: #24292f;
    padding: 6px;
    border-bottom: 1px solid #d0d7de;
}
QMenuBar::item { 
    padding: 8px 16px;
    border-radius: 6px;
}
QMenuBar::item:selected { 
    background-color: #eaeef2; 
}

/* 메뉴 */
QMenu { 
    background-color: #ffffff; 
    color: #24292f; 
    border: 1px solid #d0d7de;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item { 
    padding: 10px 28px;
    border-radius: 6px;
}
QMenu::item:selected { 
    background-color: #ddf4ff;
    color: #0969da;
}
QMenu::separator {
    height: 1px;
    background-color: #d0d7de;
    margin: 6px 10px;
}

/* 스크롤바 */
QScrollBar:vertical {
    background: #f6f8fa;
    width: 12px;
    border-radius: 6px;
    margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background: #afb8c1;
    border-radius: 5px;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover {
    background: #8c959f;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background: #f6f8fa;
    height: 12px;
    border-radius: 6px;
    margin: 2px 4px;
}
QScrollBar::handle:horizontal {
    background: #afb8c1;
    border-radius: 5px;
    min-width: 40px;
}
QScrollBar::handle:horizontal:hover {
    background: #8c959f;
}

/* 스플리터 */
QSplitter::handle {
    background: #d0d7de;
    border-radius: 2px;
}
QSplitter::handle:hover {
    background: #0969da;
}

/* 프레임 */
QFrame {
    border: none;
}
"""


# ============================================================
# 접기/펼치기 가능한 그룹박스
# ============================================================
