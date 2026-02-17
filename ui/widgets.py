# -*- coding: utf-8 -*-

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QFrame, QGroupBox, QHBoxLayout, QLabel

class CollapsibleGroupBox(QGroupBox):
    """접기/펼치기 가능한 그룹박스 - 클릭으로 내용 숨기기/보이기"""
    
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._is_collapsed = False
        self._title = title
        self._animation = None
        self._content_widget = None
        
        # 제목 설정 (접기 아이콘 포함)
        self._update_title()
        
        # 클릭 가능하게 설정
        self.setCheckable(False)
        
        # 스타일 설정 - 제목 클릭 가능하게
        self.setStyleSheet(self.styleSheet() + """
            CollapsibleGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px;
            }
        """)
    
    def _update_title(self):
        """접기/펼치기 상태에 따라 제목 업데이트"""
        icon = "▼" if not self._is_collapsed else "▶"
        self.setTitle(f"{icon} {self._title}")
    
    def mousePressEvent(self, event):
        """제목 영역 클릭 시 접기/펼치기"""
        # 제목 영역 (상단 30px) 클릭 감지
        if event.pos().y() < 25:
            self.toggle_collapsed()
        else:
            super().mousePressEvent(event)
    
    def toggle_collapsed(self):
        """접기/펼치기 토글"""
        self._is_collapsed = not self._is_collapsed
        self._update_title()
        
        # 내용 위젯들 숨기기/보이기
        layout = self.layout()
        if layout:
            for i in range(layout.count()):
                item = layout.itemAt(i)
                widget = item.widget()
                if widget:
                    widget.setVisible(not self._is_collapsed)
                # 레이아웃 아이템 (중첩 레이아웃)
                elif item.layout():
                    self._set_layout_visible(item.layout(), not self._is_collapsed)
        
        # 크기 조정
        if self._is_collapsed:
            self.setMaximumHeight(35)
        else:
            self.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
    
    def _set_layout_visible(self, layout, visible: bool):
        """레이아웃 내 모든 위젯 가시성 설정"""
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget()
            if widget:
                widget.setVisible(visible)
            elif item.layout():
                self._set_layout_visible(item.layout(), visible)
    
    def is_collapsed(self) -> bool:
        """현재 접힘 상태 반환"""
        return self._is_collapsed
    
    def set_collapsed(self, collapsed: bool):
        """접힘 상태 설정"""
        if self._is_collapsed != collapsed:
            self.toggle_collapsed()


# ============================================================
# 토스트 알림 위젯
# ============================================================

class ToastWidget(QFrame):
    """비차단 토스트 알림 위젯 - 스택 처리 지원, 모던 디자인"""
    
    def __init__(self, parent, message: str, duration: int = 3000, 
                 toast_type: str = "info", y_offset: int = 10, on_close=None):
        super().__init__(parent)
        self.setObjectName("toastWidget")
        self.on_close = on_close
        
        # 개선된 색상 팔레트 (더 세련된 컬러)
        colors = {
            "info": ("#58a6ff", "#161b22", "#21262d"),      # 블루 - 정보
            "success": ("#3fb950", "#0d1117", "#1c2128"),   # 그린 - 성공
            "warning": ("#d29922", "#1c1a14", "#2d2a21"),   # 옐로우 - 경고
            "error": ("#f85149", "#1c1418", "#2d2128")      # 레드 - 오류
        }
        accent_color, bg_color, border_bg = colors.get(toast_type, colors["info"])
        
        self.setStyleSheet(f"""
            QFrame#toastWidget {{
                background-color: {bg_color};
                border: 1px solid {accent_color};
                border-left: 4px solid {accent_color};
                border-radius: 10px;
                padding: 12px;
            }}
            QLabel {{
                color: #e6edf3;
                font-size: 13px;
                font-weight: 500;
                background: transparent;
            }}
            QLabel#toastIcon {{
                font-size: 16px;
                min-width: 24px;
            }}
            QLabel#toastMessage {{
                color: #e6edf3;
                padding-left: 8px;
            }}
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        
        # 아이콘 (개선된 이모지)
        icons = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}
        icon_label = QLabel(icons.get(toast_type, "ℹ️"))
        icon_label.setObjectName("toastIcon")
        layout.addWidget(icon_label)
        
        # 메시지
        msg_label = QLabel(message)
        msg_label.setObjectName("toastMessage")
        msg_label.setWordWrap(True)
        layout.addWidget(msg_label, 1)
        
        # 위치 설정 (부모 위젯 상단 중앙 + y_offset)
        self.adjustSize()
        if parent:
            parent_rect = parent.rect()
            x = (parent_rect.width() - self.width()) // 2
            self.move(x, y_offset)
        
        self.show()
        self.raise_()
        
        # 자동 사라짐
        QTimer.singleShot(duration, self._fade_out)
    
    def _fade_out(self):
        """토스트 사라지기"""
        if self.on_close:
            self.on_close(self)
        self.hide()
        self.deleteLater()


# ============================================================
# 자막 데이터 클래스
# ============================================================

