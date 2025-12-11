# -*- coding: utf-8 -*-
"""
국회 의사중계 자막 추출기 v8.0
PyQt6 모던 UI 버전
"""

import sys
import os
import time
import threading
import queue
import re
import json
import hashlib
import gc
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any
from enum import Enum
from collections import deque, OrderedDict
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox, QCheckBox,
        QGroupBox, QSplitter, QFrame, QListWidget, QProgressBar,
        QMenuBar, QMenu, QStatusBar, QFileDialog, QMessageBox,
        QInputDialog, QDialog, QDialogButtonBox, QListWidgetItem,
        QScrollArea, QSizePolicy, QSpacerItem, QToolButton, QButtonGroup,
        QRadioButton, QSlider, QSpinBox, QTabWidget, QGridLayout
    )
    from PyQt6.QtCore import (
        Qt, QTimer, QThread, pyqtSignal, QSize, QPropertyAnimation,
        QEasingCurve, QPoint, QRect, QUrl, QMargins
    )
    from PyQt6.QtGui import (
        QFont, QColor, QPalette, QIcon, QAction, QTextCursor,
        QTextCharFormat, QBrush, QLinearGradient, QPainter, QPen,
        QFontDatabase, QShortcut, QKeySequence, QDesktopServices
    )
except ImportError:
    logger.error("PyQt6 필요: pip install PyQt6")
    sys.exit(1)

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import WebDriverException, NoSuchElementException, StaleElementReferenceException
    from selenium.webdriver.chrome.options import Options
except ImportError:
    logger.error("selenium 필요: pip install selenium")
    sys.exit(1)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# ============================================================
# 테마 및 스타일
# ============================================================

class Theme(Enum):
    DARK = "dark"
    LIGHT = "light"


@dataclass
class ThemeColors:
    bg_primary: str
    bg_secondary: str
    bg_tertiary: str
    fg_primary: str
    fg_secondary: str
    fg_muted: str
    accent: str
    accent_hover: str
    success: str
    warning: str
    error: str
    border: str
    shadow: str
    card_bg: str
    input_bg: str
    highlight: str


THEMES = {
    Theme.DARK: ThemeColors(
        bg_primary="#0d1117",
        bg_secondary="#161b22",
        bg_tertiary="#21262d",
        fg_primary="#e6edf3",
        fg_secondary="#8b949e",
        fg_muted="#484f58",
        accent="#58a6ff",
        accent_hover="#79c0ff",
        success="#3fb950",
        warning="#d29922",
        error="#f85149",
        border="#30363d",
        shadow="#010409",
        card_bg="#161b22",
        input_bg="#0d1117",
        highlight="#388bfd33",
    ),
    Theme.LIGHT: ThemeColors(
        bg_primary="#ffffff",
        bg_secondary="#f6f8fa",
        bg_tertiary="#eaeef2",
        fg_primary="#1f2328",
        fg_secondary="#656d76",
        fg_muted="#8c959f",
        accent="#0969da",
        accent_hover="#0550ae",
        success="#1a7f37",
        warning="#9a6700",
        error="#cf222e",
        border="#d0d7de",
        shadow="#8c959f33",
        card_bg="#ffffff",
        input_bg="#f6f8fa",
        highlight="#54aeff33",
    ),
}

SPEAKER_COLORS = {
    Theme.DARK: ['#58a6ff', '#f85149', '#3fb950', '#d29922', '#a371f7', 
                 '#79c0ff', '#7ee787', '#e3b341', '#ff7b72', '#d2a8ff'],
    Theme.LIGHT: ['#0969da', '#cf222e', '#1a7f37', '#9a6700', '#8250df',
                  '#0550ae', '#116329', '#7d4e00', '#a40e26', '#6639ba'],
}


def get_stylesheet(theme: Theme) -> str:
    """테마별 스타일시트 생성"""
    c = THEMES[theme]
    return f"""
    /* 전역 스타일 */
    QMainWindow, QWidget {{
        background-color: {c.bg_primary};
        color: {c.fg_primary};
        font-family: 'Malgun Gothic', 'Segoe UI', sans-serif;
        font-size: 13px;
    }}
    
    /* 카드 스타일 그룹박스 */
    QGroupBox {{
        background-color: {c.card_bg};
        border: 1px solid {c.border};
        border-radius: 12px;
        margin-top: 16px;
        padding: 16px;
        padding-top: 24px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 16px;
        top: 4px;
        color: {c.fg_secondary};
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    
    /* 입력 필드 */
    QLineEdit, QComboBox {{
        background-color: {c.input_bg};
        border: 1px solid {c.border};
        border-radius: 8px;
        padding: 10px 14px;
        color: {c.fg_primary};
        selection-background-color: {c.accent};
    }}
    QLineEdit:focus, QComboBox:focus {{
        border-color: {c.accent};
        outline: none;
    }}
    QComboBox::drop-down {{
        border: none;
        padding-right: 10px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid {c.fg_secondary};
        margin-right: 10px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c.bg_secondary};
        border: 1px solid {c.border};
        border-radius: 8px;
        padding: 4px;
        selection-background-color: {c.highlight};
    }}
    
    /* 버튼 - Primary */
    QPushButton {{
        background-color: {c.accent};
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
        font-weight: 600;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: {c.accent_hover};
    }}
    QPushButton:pressed {{
        background-color: {c.accent};
        padding-top: 11px;
        padding-bottom: 9px;
    }}
    QPushButton:disabled {{
        background-color: {c.bg_tertiary};
        color: {c.fg_muted};
    }}
    
    /* 버튼 - Secondary */
    QPushButton[class="secondary"] {{
        background-color: {c.bg_tertiary};
        color: {c.fg_primary};
        border: 1px solid {c.border};
    }}
    QPushButton[class="secondary"]:hover {{
        background-color: {c.border};
    }}
    
    /* 버튼 - Ghost */
    QPushButton[class="ghost"] {{
        background-color: transparent;
        color: {c.fg_secondary};
        border: none;
    }}
    QPushButton[class="ghost"]:hover {{
        background-color: {c.bg_tertiary};
        color: {c.fg_primary};
    }}
    
    /* 버튼 - Success */
    QPushButton[class="success"] {{
        background-color: {c.success};
    }}
    QPushButton[class="success"]:hover {{
        background-color: {c.success};
        opacity: 0.9;
    }}
    
    /* 버튼 - Danger */
    QPushButton[class="danger"] {{
        background-color: {c.error};
    }}
    QPushButton[class="danger"]:hover {{
        background-color: {c.error};
        opacity: 0.9;
    }}
    
    /* 텍스트 에디터 */
    QTextEdit {{
        background-color: {c.bg_secondary};
        border: 1px solid {c.border};
        border-radius: 12px;
        padding: 16px;
        color: {c.fg_primary};
        selection-background-color: {c.highlight};
        line-height: 1.6;
    }}
    
    /* 리스트 위젯 */
    QListWidget {{
        background-color: {c.bg_secondary};
        border: 1px solid {c.border};
        border-radius: 8px;
        padding: 8px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 8px 12px;
        border-radius: 6px;
        margin: 2px 0;
    }}
    QListWidget::item:hover {{
        background-color: {c.bg_tertiary};
    }}
    QListWidget::item:selected {{
        background-color: {c.highlight};
        color: {c.accent};
    }}
    
    /* 체크박스 */
    QCheckBox {{
        spacing: 8px;
        color: {c.fg_primary};
    }}
    QCheckBox::indicator {{
        width: 20px;
        height: 20px;
        border-radius: 6px;
        border: 2px solid {c.border};
        background-color: {c.input_bg};
    }}
    QCheckBox::indicator:checked {{
        background-color: {c.accent};
        border-color: {c.accent};
        image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNMTAgM0w0LjUgOC41TDIgNiIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz48L3N2Zz4=);
    }}
    QCheckBox::indicator:hover {{
        border-color: {c.accent};
    }}
    
    /* 프로그레스바 */
    QProgressBar {{
        background-color: {c.bg_tertiary};
        border: none;
        border-radius: 4px;
        height: 6px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {c.accent};
        border-radius: 4px;
    }}
    
    /* 스크롤바 */
    QScrollBar:vertical {{
        background-color: transparent;
        width: 12px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background-color: {c.border};
        border-radius: 6px;
        min-height: 40px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {c.fg_muted};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background-color: transparent;
        height: 12px;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {c.border};
        border-radius: 6px;
        min-width: 40px;
        margin: 2px;
    }}
    
    /* 메뉴바 */
    QMenuBar {{
        background-color: {c.bg_secondary};
        border-bottom: 1px solid {c.border};
        padding: 4px 8px;
    }}
    QMenuBar::item {{
        padding: 8px 12px;
        border-radius: 6px;
        color: {c.fg_secondary};
    }}
    QMenuBar::item:selected {{
        background-color: {c.bg_tertiary};
        color: {c.fg_primary};
    }}
    
    /* 메뉴 */
    QMenu {{
        background-color: {c.bg_secondary};
        border: 1px solid {c.border};
        border-radius: 12px;
        padding: 8px;
    }}
    QMenu::item {{
        padding: 10px 16px;
        border-radius: 6px;
        color: {c.fg_primary};
    }}
    QMenu::item:selected {{
        background-color: {c.highlight};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {c.border};
        margin: 8px 12px;
    }}
    
    /* 상태바 */
    QStatusBar {{
        background-color: {c.bg_secondary};
        border-top: 1px solid {c.border};
        padding: 8px 16px;
        color: {c.fg_secondary};
    }}
    
    /* 탭 위젯 */
    QTabWidget::pane {{
        border: 1px solid {c.border};
        border-radius: 8px;
        background-color: {c.card_bg};
    }}
    QTabBar::tab {{
        background-color: transparent;
        color: {c.fg_secondary};
        padding: 10px 20px;
        margin-right: 4px;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
    }}
    QTabBar::tab:selected {{
        background-color: {c.card_bg};
        color: {c.accent};
        border: 1px solid {c.border};
        border-bottom: none;
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {c.bg_tertiary};
    }}
    
    /* 스플리터 */
    QSplitter::handle {{
        background-color: {c.border};
        margin: 0 4px;
    }}
    QSplitter::handle:horizontal {{
        width: 2px;
    }}
    QSplitter::handle:hover {{
        background-color: {c.accent};
    }}
    
    /* 툴팁 */
    QToolTip {{
        background-color: {c.bg_tertiary};
        color: {c.fg_primary};
        border: 1px solid {c.border};
        border-radius: 6px;
        padding: 8px 12px;
    }}
    
    /* 레이블 스타일 */
    QLabel[class="title"] {{
        font-size: 24px;
        font-weight: 700;
        color: {c.fg_primary};
    }}
    QLabel[class="subtitle"] {{
        font-size: 14px;
        color: {c.fg_secondary};
    }}
    QLabel[class="stat-value"] {{
        font-size: 20px;
        font-weight: 700;
        color: {c.fg_primary};
    }}
    QLabel[class="stat-label"] {{
        font-size: 11px;
        color: {c.fg_muted};
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    """


# ============================================================
# 유틸리티 클래스들
# ============================================================

class TextProcessor:
    NOISE_RE = [re.compile(p, re.I) for p in [
        r'\[음성\s*인식\s*중[^\]]*\]', r'\[자막[^\]]*\]', r'\[음악\]', 
        r'\[박수\]', r'\[웃음\]', r'^\s*[-=]{3,}\s*$', r'♪+', r'♬+'
    ]]
    SPEAKER_RE = [re.compile(p) for p in [
        r'^([가-힣]{2,4})\s*(의원|위원장|위원|장관|총리|대통령|의장|부의장|차관|처장|청장)\s*[:\.]?\s*',
        r'^\[([가-힣]{2,4})\s*(의원|위원장|위원|장관)\]\s*',
        r'^○\s*([가-힣]{2,4})\s*(의원|위원장|위원|장관)\s*',
    ]]
    SENT_END_RE = [re.compile(p) for p in [
        r'습니다\s*$', r'니까\s*$', r'세요\s*$', r'해요\s*$', r'네요\s*$', r'죠\s*$', r'요\s*$'
    ]]
    
    def process(self, text, filter_noise=True, add_punct=True):
        if not text:
            return None, ""
        
        # 노이즈 제거
        if filter_noise:
            for p in self.NOISE_RE:
                text = p.sub('', text)
        
        # 공백 정규화
        text = re.sub(r'[ \t]+', ' ', text).strip()
        if not text:
            return None, ""
        
        # 화자 감지
        speaker = None
        for p in self.SPEAKER_RE:
            m = p.match(text)
            if m:
                g = m.groups()
                speaker = f"{g[0]} {g[1]}" if len(g) >= 2 and g[1] else g[0]
                text = text[m.end():].strip()
                break
        
        # 문장부호 추가
        if add_punct and text and text[-1] not in '.!?。':
            for p in self.SENT_END_RE:
                if p.search(text):
                    text += '.'
                    break
        
        return speaker, text


class DuplicateFilter:
    def __init__(self):
        self._cache = OrderedDict()
        self._recent = deque(maxlen=50)
        self._lock = threading.Lock()
    
    def is_dup(self, text, enabled=True):
        if not enabled or not text or len(text) < 5:
            return False
        with self._lock:
            h = hashlib.md5(re.sub(r'\s+', '', text.lower()).encode()).hexdigest()[:16]
            if h in self._cache:
                return True
            for r in self._recent:
                w1, w2 = set(text.split()), set(r.split())
                if w1 and w2 and len(w1 & w2) / len(w1 | w2) >= 0.85:
                    return True
        return False
    
    def add(self, text):
        if not text:
            return
        with self._lock:
            h = hashlib.md5(re.sub(r'\s+', '', text.lower()).encode()).hexdigest()[:16]
            if len(self._cache) >= 1000:
                for _ in range(100):
                    if self._cache:
                        self._cache.popitem(last=False)
            self._cache[h] = True
            self._recent.append(text)
    
    def clear(self):
        with self._lock:
            self._cache.clear()
            self._recent.clear()


class URLHistory:
    def __init__(self, fp="url_history.json"):
        self.fp = fp
        self.history, self.favorites = [], []
        self._lock = threading.Lock()
        self._load()
    
    def _load(self):
        try:
            if Path(self.fp).exists():
                with open(self.fp, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                    self.history = d.get('history', [])
                    self.favorites = d.get('favorites', [])
        except Exception:
            pass
    
    def _save(self):
        try:
            with open(self.fp, 'w', encoding='utf-8') as f:
                json.dump({'history': self.history[-50:], 'favorites': self.favorites}, f, ensure_ascii=False)
        except Exception:
            pass
    
    def add_hist(self, url):
        with self._lock:
            self.history = [h for h in self.history if h['url'] != url]
            self.history.append({'url': url, 'ts': datetime.now().isoformat()})
        self._save()
    
    def add_fav(self, url, title):
        with self._lock:
            if any(f['url'] == url for f in self.favorites):
                return False
            self.favorites.append({'url': url, 'title': title})
        self._save()
        return True
    
    def rm_fav(self, url):
        with self._lock:
            self.favorites = [f for f in self.favorites if f['url'] != url]
        self._save()
    
    def get_recent(self, n=10):
        with self._lock:
            return list(reversed(self.history[-n:]))
    
    def get_favs(self):
        with self._lock:
            return self.favorites.copy()
    
    def clear_hist(self):
        with self._lock:
            self.history = []
        self._save()


class SpeakerColors:
    def __init__(self, theme=Theme.DARK):
        self.theme = theme
        self._colors = {}
        self._idx = 0
        self._lock = threading.Lock()
    
    def set_theme(self, theme):
        with self._lock:
            self.theme = theme
            keys = list(self._colors.keys())
            self._colors.clear()
            self._idx = 0
            for k in keys:
                self.get(k)
    
    def get(self, speaker):
        if not speaker:
            return THEMES[self.theme].fg_primary
        with self._lock:
            if speaker not in self._colors:
                colors = SPEAKER_COLORS[self.theme]
                self._colors[speaker] = colors[self._idx % len(colors)]
                self._idx += 1
            return self._colors[speaker]
    
    def all(self):
        with self._lock:
            return self._colors.copy()
    
    def clear(self):
        with self._lock:
            self._colors.clear()
            self._idx = 0


class RealTimeWriter:
    def __init__(self, base_dir="realtime_output"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
        self.file = None
        self._fh = None
        self._buf = []
        self._lock = threading.Lock()
        self._last_hash = None
    
    def start(self, prefix="자막"):
        with self._lock:
            self.close()
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            self.file = self.base_dir / f"{prefix}_{ts}.txt"
            try:
                self._fh = open(self.file, 'w', encoding='utf-8')
                self._fh.write(f"# 국회 의사중계 자막\n# 시작: {datetime.now():%Y-%m-%d %H:%M:%S}\n{'='*60}\n\n")
                self._fh.flush()
                return str(self.file)
            except Exception:
                self._fh = None
                return None
    
    def write(self, text, speaker=None, ts=None):
        if not text:
            return
        with self._lock:
            if not self._fh:
                return
            h = hashlib.md5(text.encode()).hexdigest()[:16]
            if h == self._last_hash:
                return
            parts = []
            if ts:
                parts.append(f"[{ts}]")
            if speaker:
                parts.append(f"[{speaker}]")
            parts.append(text)
            self._buf.append(' '.join(parts) + '\n')
            self._last_hash = h
            if len(self._buf) >= 5:
                self._flush()
    
    def _flush(self):
        if self._fh and self._buf:
            self._fh.writelines(self._buf)
            self._fh.flush()
            self._buf.clear()
    
    def close(self):
        with self._lock:
            self._flush()
            if self._fh:
                try:
                    self._fh.write(f"\n{'='*60}\n# 종료: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None
    
    def get_path(self):
        with self._lock:
            return str(self.file) if self.file else None


class SubtitleAccumulator:
    def __init__(self):
        self.processor = TextProcessor()
        self.dup_filter = DuplicateFilter()
        self.speaker_mgr = SpeakerColors()
        self._lock = threading.RLock()
        self.sentences = []
        self.current = ""
        self.cur_speaker = None
        self.last_text = ""
        self.total_chars = 0
        self.filtered = 0
        self.noise_enabled = True
        self.dup_enabled = True
        self.punct_enabled = True
    
    def reset(self):
        with self._lock:
            self.sentences.clear()
            self.current = ""
            self.cur_speaker = None
            self.last_text = ""
            self.total_chars = 0
            self.filtered = 0
            self.dup_filter.clear()
            self.speaker_mgr.clear()
    
    def process(self, raw):
        with self._lock:
            result = {'changed': False, 'new_sent': False, 'current': self.current,
                      'speaker': self.cur_speaker}
            if not raw:
                return result
            
            speaker, text = self.processor.process(raw, self.noise_enabled, self.punct_enabled)
            if not text or text == self.last_text:
                return result
            
            # 새 문장 판단
            is_new = not self.last_text or sum(1 for a, b in zip(self.last_text, text) if a == b) < len(self.last_text) * 0.3
            
            if is_new:
                if self.current:
                    if not self.dup_filter.is_dup(self.current, self.dup_enabled):
                        self.sentences.append({'text': self.current, 'speaker': self.cur_speaker, 'ts': datetime.now()})
                        self.dup_filter.add(self.current)
                        self.total_chars += len(self.current)
                        result['new_sent'] = True
                    else:
                        self.filtered += 1
                self.current = text
                self.cur_speaker = speaker
                if speaker:
                    self.speaker_mgr.get(speaker)
            else:
                self.current = text
                if speaker:
                    self.cur_speaker = speaker
                    self.speaker_mgr.get(speaker)
            
            self.last_text = text
            result['changed'] = True
            result['current'] = self.current
            result['speaker'] = self.cur_speaker
            return result
    
    def finalize(self):
        with self._lock:
            if self.current and not self.dup_filter.is_dup(self.current, self.dup_enabled):
                self.sentences.append({'text': self.current, 'speaker': self.cur_speaker, 'ts': datetime.now()})
                self.total_chars += len(self.current)
            self.current = ""
            self.cur_speaker = None
    
    def get_full(self):
        with self._lock:
            parts = []
            for s in self.sentences:
                line = f"[{s['speaker']}] " if s.get('speaker') else ""
                parts.append(line + s['text'])
            if self.current:
                line = f"[{self.cur_speaker}] " if self.cur_speaker else ""
                parts.append(line + self.current)
            return '\n\n'.join(parts)
    
    def get_stats(self):
        with self._lock:
            return {
                'sents': len(self.sentences) + (1 if self.current else 0),
                'chars': self.total_chars + len(self.current),
                'filtered': self.filtered,
                'speakers': list(self.speaker_mgr.all().keys())
            }
    
    def get_last(self):
        with self._lock:
            return self.sentences[-1].copy() if self.sentences else None
    
    def get_sents(self):
        with self._lock:
            return [s.copy() for s in self.sentences]


# ============================================================
# 워커 스레드
# ============================================================

class ExtractionWorker(QThread):
    status_update = pyqtSignal(str)
    connection_update = pyqtSignal(bool)
    subtitle_update = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    finished_signal = pyqtSignal()
    reconnect_update = pyqtSignal(int)
    
    def __init__(self, url, selector, headless=False, auto_reconnect=True):
        super().__init__()
        self.url = url
        self.selector = selector
        self.headless = headless
        self.auto_reconnect = auto_reconnect
        self.running = True
        self.paused = False
        self.driver = None
        self.accumulator = None
        self.writer = None
        self.rt_save = False
    
    def set_components(self, accum, writer, rt_save):
        self.accumulator = accum
        self.writer = writer
        self.rt_save = rt_save
    
    def stop(self):
        self.running = False
    
    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused
    
    def run(self):
        reconnects = 0
        max_reconnects = 5
        
        while self.running:
            try:
                # Chrome 설정
                opts = Options()
                for arg in ["--log-level=3", "--disable-blink-features=AutomationControlled",
                           "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                           "--window-size=1280,720", "--disable-extensions"]:
                    opts.add_argument(arg)
                opts.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
                
                if self.headless:
                    opts.add_argument("--headless=new")
                    self.status_update.emit("헤드리스 모드로 시작 중...")
                
                try:
                    self.driver = webdriver.Chrome(options=opts)
                    self.connection_update.emit(True)
                    self.status_update.emit("Chrome 브라우저 시작됨")
                except Exception as e:
                    self.error_occurred.emit(f"Chrome 시작 실패: {e}")
                    return
                
                # 페이지 로드
                self.status_update.emit("페이지 로딩 중...")
                self.driver.get(self.url)
                time.sleep(3)
                
                # 자막 활성화
                self.status_update.emit("AI 자막 활성화 중...")
                self._activate_subtitle()
                time.sleep(1)
                
                # 자막 요소 찾기
                self.status_update.emit("자막 요소 검색 중...")
                elem = self._find_element()
                if not elem:
                    self.error_occurred.emit("자막 요소를 찾을 수 없습니다.\nAI 자막을 수동으로 활성화해주세요.")
                    return
                
                self.status_update.emit("자막 모니터링 중")
                
                # 메인 루프
                last_check = time.time()
                errors = 0
                
                while self.running:
                    try:
                        if self.paused:
                            time.sleep(0.1)
                            continue
                        
                        now = time.time()
                        if now - last_check >= 0.15:
                            # 연결 확인
                            try:
                                _ = self.driver.current_url
                            except Exception:
                                raise WebDriverException("브라우저 연결 끊김")
                            
                            # 자막 텍스트 추출
                            try:
                                raw = self.driver.find_element(By.CSS_SELECTOR, self.selector).text.strip()
                            except StaleElementReferenceException:
                                elem = self._find_element()
                                raw = elem.text.strip() if elem else ""
                            except NoSuchElementException:
                                errors += 1
                                if errors > 10:
                                    raise Exception("자막 요소 소실")
                                continue
                            
                            # 처리
                            if self.accumulator:
                                result = self.accumulator.process(raw)
                                if result['changed']:
                                    errors = 0
                                    self.subtitle_update.emit(result)
                                    
                                    # 실시간 저장
                                    if result['new_sent'] and self.rt_save and self.writer:
                                        last = self.accumulator.get_last()
                                        if last:
                                            self.writer.write(last['text'], last.get('speaker'), 
                                                            last['ts'].strftime('%H:%M:%S'))
                            
                            gc.collect()
                            last_check = now
                        
                        time.sleep(0.05)
                        
                    except WebDriverException:
                        self.connection_update.emit(False)
                        raise
                    except Exception as e:
                        errors += 1
                        if errors > 10:
                            raise
                        time.sleep(0.3)
                
                break
                
            except WebDriverException as e:
                self.connection_update.emit(False)
                
                if self.running and self.auto_reconnect and reconnects < max_reconnects:
                    reconnects += 1
                    self.reconnect_update.emit(reconnects)
                    self.status_update.emit(f"재연결 시도 중... ({reconnects}/{max_reconnects})")
                    
                    if self.driver:
                        try:
                            self.driver.quit()
                        except Exception:
                            pass
                        self.driver = None
                    
                    time.sleep(3)
                    continue
                else:
                    if self.running:
                        self.error_occurred.emit(f"브라우저 오류: {e}")
                    break
                    
            except Exception as e:
                if self.running:
                    self.error_occurred.emit(f"추출 오류: {e}")
                break
        
        # 정리
        self.connection_update.emit(False)
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        
        self.finished_signal.emit()
    
    def _find_element(self):
        wait = WebDriverWait(self.driver, 10)
        for sel in [self.selector, "#viewSubtit .incont", "#viewSubtit", ".subtitle_area"]:
            try:
                return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
            except Exception:
                continue
        return None
    
    def _activate_subtitle(self):
        scripts = [
            "if(typeof layerSubtit==='function'){layerSubtit();return true;}",
            "document.querySelector('.btn_subtit')?.click();return true;",
            "document.querySelector('#btnSubtit')?.click();return true;",
        ]
        for script in scripts:
            try:
                if self.driver.execute_script(script):
                    return
                time.sleep(0.3)
            except Exception:
                continue


# ============================================================
# 커스텀 위젯들
# ============================================================

class StatCard(QFrame):
    """통계 카드 위젯"""
    def __init__(self, label, value="0", parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(4)
        
        self.value_label = QLabel(value)
        self.value_label.setProperty("class", "stat-value")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.name_label = QLabel(label)
        self.name_label.setProperty("class", "stat-label")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(self.value_label)
        layout.addWidget(self.name_label)
    
    def set_value(self, value):
        self.value_label.setText(str(value))


class ConnectionIndicator(QWidget):
    """연결 상태 인디케이터"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.connected = False
        self.setFixedSize(12, 12)
    
    def set_connected(self, connected):
        self.connected = connected
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if self.connected:
            color = QColor("#3fb950")
        else:
            color = QColor("#484f58")
        
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 12, 12)


class IconButton(QPushButton):
    """아이콘 버튼"""
    def __init__(self, icon_text, tooltip="", parent=None):
        super().__init__(icon_text, parent)
        self.setToolTip(tooltip)
        self.setFixedSize(36, 36)
        self.setProperty("class", "ghost")


# ============================================================
# 메인 윈도우
# ============================================================

class MainWindow(QMainWindow):
    VERSION = "8.0"
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"국회 의사중계 자막 추출기 v{self.VERSION}")
        self.setMinimumSize(1400, 900)
        self.resize(1500, 950)
        
        # 설정 로드
        self.config = self._load_config()
        self.theme = Theme.DARK if self.config.get('theme') == 'dark' else Theme.LIGHT
        
        # 컴포넌트
        self.accumulator = SubtitleAccumulator()
        self.url_history = URLHistory()
        self.writer = RealTimeWriter()
        self.worker = None
        
        # 상태
        self.start_time = None
        self.reconnects = 0
        
        # UI 생성
        self._create_ui()
        self._create_menu()
        self._apply_theme()
        self._apply_settings()
        self._setup_shortcuts()
        self._setup_timers()
        
        # 디렉토리 생성
        Path("realtime_output").mkdir(exist_ok=True)
        
        logger.info(f"v{self.VERSION} 시작")
    
    def _load_config(self):
        cfg = {
            'theme': 'dark', 'headless': False, 'auto_reconnect': True,
            'realtime_save': True, 'show_speaker_colors': True, 'auto_scroll': True,
            'auto_punctuation': True, 'filter_duplicates': True, 'filter_noise': True,
            'font_size': 14,
        }
        try:
            if Path("subtitle_config.json").exists():
                with open("subtitle_config.json", 'r', encoding='utf-8') as f:
                    cfg.update(json.load(f))
        except Exception:
            pass
        return cfg
    
    def _save_config(self):
        try:
            with open("subtitle_config.json", 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    
    def _apply_settings(self):
        self.accumulator.noise_enabled = self.config.get('filter_noise', True)
        self.accumulator.dup_enabled = self.config.get('filter_duplicates', True)
        self.accumulator.punct_enabled = self.config.get('auto_punctuation', True)
    
    def _create_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(20)
        
        # 헤더
        header = self._create_header()
        main_layout.addWidget(header)
        
        # 컨트롤 영역
        controls = self._create_controls()
        main_layout.addWidget(controls)
        
        # 메인 컨텐츠
        content = self._create_content()
        main_layout.addWidget(content, 1)
        
        # 상태바
        self._create_status_bar()
    
    def _create_header(self):
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 타이틀
        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)
        
        title = QLabel("국회 의사중계 자막 추출기")
        title.setProperty("class", "title")
        
        subtitle = QLabel("실시간 자막 추출 및 저장")
        subtitle.setProperty("class", "subtitle")
        
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        layout.addLayout(title_layout)
        
        layout.addStretch()
        
        # 테마 토글
        self.theme_btn = QPushButton("🌙 다크 모드" if self.theme == Theme.DARK else "☀️ 라이트 모드")
        self.theme_btn.setProperty("class", "secondary")
        self.theme_btn.clicked.connect(self._toggle_theme)
        layout.addWidget(self.theme_btn)
        
        return frame
    
    def _create_controls(self):
        group = QGroupBox("연결 설정")
        layout = QVBoxLayout(group)
        layout.setSpacing(16)
        
        # URL 입력
        url_layout = QHBoxLayout()
        url_layout.setSpacing(12)
        
        url_label = QLabel("URL")
        url_label.setFixedWidth(60)
        
        self.fav_btn = IconButton("★", "즐겨찾기 추가")
        self.fav_btn.clicked.connect(self._add_favorite)
        
        self.url_combo = QComboBox()
        self.url_combo.setEditable(True)
        self.url_combo.setMinimumWidth(400)
        self.url_combo.lineEdit().setPlaceholderText("국회 의사중계 URL을 입력하세요")
        self.url_combo.setCurrentText("https://www.webcast.go.kr/live/")
        self.url_combo.currentTextChanged.connect(self._on_url_changed)
        self._update_url_list()
        
        self.selector_combo = QComboBox()
        self.selector_combo.setEditable(True)
        self.selector_combo.setMinimumWidth(200)
        self.selector_combo.addItems(["#viewSubtit .incont", "#viewSubtit", ".subtitle_area", "[id*='subtit']"])
        self.selector_combo.setCurrentText("#viewSubtit .incont")
        
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.fav_btn)
        url_layout.addWidget(self.url_combo, 1)
        url_layout.addWidget(QLabel("CSS 선택자"))
        url_layout.addWidget(self.selector_combo)
        
        layout.addLayout(url_layout)
        
        # 옵션 & 버튼
        options_layout = QHBoxLayout()
        options_layout.setSpacing(24)
        
        # 체크박스들
        checks_layout = QHBoxLayout()
        checks_layout.setSpacing(20)
        
        self.headless_check = QCheckBox("헤드리스 모드")
        self.headless_check.setChecked(self.config.get('headless', False))
        self.headless_check.stateChanged.connect(self._on_setting_changed)
        
        self.reconnect_check = QCheckBox("자동 재연결")
        self.reconnect_check.setChecked(self.config.get('auto_reconnect', True))
        self.reconnect_check.stateChanged.connect(self._on_setting_changed)
        
        self.realtime_check = QCheckBox("실시간 저장")
        self.realtime_check.setChecked(self.config.get('realtime_save', True))
        self.realtime_check.stateChanged.connect(self._on_setting_changed)
        
        self.scroll_check = QCheckBox("자동 스크롤")
        self.scroll_check.setChecked(self.config.get('auto_scroll', True))
        self.scroll_check.stateChanged.connect(self._on_setting_changed)
        
        checks_layout.addWidget(self.headless_check)
        checks_layout.addWidget(self.reconnect_check)
        checks_layout.addWidget(self.realtime_check)
        checks_layout.addWidget(self.scroll_check)
        
        options_layout.addLayout(checks_layout)
        options_layout.addStretch()
        
        # 버튼들
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        self.start_btn = QPushButton("▶  시작")
        self.start_btn.setProperty("class", "success")
        self.start_btn.setMinimumWidth(120)
        self.start_btn.clicked.connect(self._start)
        
        self.pause_btn = QPushButton("⏸  일시정지")
        self.pause_btn.setProperty("class", "secondary")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._toggle_pause)
        
        self.stop_btn = QPushButton("⏹  중지")
        self.stop_btn.setProperty("class", "danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.stop_btn)
        
        options_layout.addLayout(btn_layout)
        layout.addLayout(options_layout)
        
        return group
    
    def _create_content(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        
        # 왼쪽: 자막 영역
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        
        # 검색 바
        search_frame = QFrame()
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(8)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 검색어 입력...")
        self.search_input.returnPressed.connect(self._search)
        
        search_btn = QPushButton("검색")
        search_btn.setProperty("class", "secondary")
        search_btn.setFixedWidth(80)
        search_btn.clicked.connect(self._search)
        
        self.search_prev_btn = QPushButton("◀")
        self.search_prev_btn.setProperty("class", "ghost")
        self.search_prev_btn.setFixedWidth(40)
        self.search_prev_btn.clicked.connect(lambda: self._nav_search(-1))
        
        self.search_next_btn = QPushButton("▶")
        self.search_next_btn.setProperty("class", "ghost")
        self.search_next_btn.setFixedWidth(40)
        self.search_next_btn.clicked.connect(lambda: self._nav_search(1))
        
        self.search_label = QLabel("")
        
        search_layout.addWidget(self.search_input, 1)
        search_layout.addWidget(search_btn)
        search_layout.addWidget(self.search_prev_btn)
        search_layout.addWidget(self.search_next_btn)
        search_layout.addWidget(self.search_label)
        
        left_layout.addWidget(search_frame)
        
        # 자막 텍스트
        subtitle_group = QGroupBox("자막 내용")
        subtitle_layout = QVBoxLayout(subtitle_group)
        
        self.subtitle_text = QTextEdit()
        self.subtitle_text.setReadOnly(True)
        self.subtitle_text.setFont(QFont("Malgun Gothic", self.config.get('font_size', 14)))
        self.subtitle_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        
        subtitle_layout.addWidget(self.subtitle_text)
        left_layout.addWidget(subtitle_group, 1)
        
        splitter.addWidget(left_widget)
        
        # 오른쪽: 사이드바
        right_widget = QWidget()
        right_widget.setFixedWidth(340)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)
        
        # 통계 카드들
        stats_frame = QFrame()
        stats_layout = QGridLayout(stats_frame)
        stats_layout.setSpacing(12)
        
        self.stat_time = StatCard("실행 시간", "--:--:--")
        self.stat_chars = StatCard("글자 수", "0")
        self.stat_sents = StatCard("문장 수", "0")
        self.stat_speakers = StatCard("화자", "0")
        
        stats_layout.addWidget(self.stat_time, 0, 0)
        stats_layout.addWidget(self.stat_chars, 0, 1)
        stats_layout.addWidget(self.stat_sents, 1, 0)
        stats_layout.addWidget(self.stat_speakers, 1, 1)
        
        right_layout.addWidget(stats_frame)
        
        # 미리보기
        preview_group = QGroupBox("실시간 미리보기")
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(120)
        self.preview_text.setFont(QFont("Malgun Gothic", 12))
        
        preview_layout.addWidget(self.preview_text)
        right_layout.addWidget(preview_group)
        
        # 화자 목록
        speaker_group = QGroupBox("감지된 화자")
        speaker_layout = QVBoxLayout(speaker_group)
        
        self.speaker_list = QListWidget()
        self.speaker_list.setMaximumHeight(150)
        
        speaker_layout.addWidget(self.speaker_list)
        right_layout.addWidget(speaker_group)
        
        # 빠른 작업
        action_group = QGroupBox("빠른 작업")
        action_layout = QVBoxLayout(action_group)
        action_layout.setSpacing(8)
        
        save_btn = QPushButton("📄  TXT 저장")
        save_btn.clicked.connect(self._save_txt)
        
        copy_btn = QPushButton("📋  클립보드 복사")
        copy_btn.setProperty("class", "secondary")
        copy_btn.clicked.connect(self._copy_clipboard)
        
        folder_btn = QPushButton("📂  저장 폴더 열기")
        folder_btn.setProperty("class", "secondary")
        folder_btn.clicked.connect(self._open_folder)
        
        clear_btn = QPushButton("🗑️  내용 지우기")
        clear_btn.setProperty("class", "secondary")
        clear_btn.clicked.connect(self._clear_all)
        
        action_layout.addWidget(save_btn)
        action_layout.addWidget(copy_btn)
        action_layout.addWidget(folder_btn)
        action_layout.addWidget(clear_btn)
        
        right_layout.addWidget(action_group)
        right_layout.addStretch()
        
        splitter.addWidget(right_widget)
        splitter.setSizes([900, 340])
        
        return splitter
    
    def _create_menu(self):
        menubar = self.menuBar()
        
        # 파일 메뉴
        file_menu = menubar.addMenu("파일")
        
        save_action = QAction("저장 (Ctrl+S)", self)
        save_action.triggered.connect(self._save_txt)
        file_menu.addAction(save_action)
        
        folder_action = QAction("저장 폴더 열기", self)
        folder_action.triggered.connect(self._open_folder)
        file_menu.addAction(folder_action)
        
        file_menu.addSeparator()
        
        quit_action = QAction("종료 (Ctrl+Q)", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        
        # 편집 메뉴
        edit_menu = menubar.addMenu("편집")
        
        copy_action = QAction("복사 (Ctrl+C)", self)
        copy_action.triggered.connect(self._copy_clipboard)
        edit_menu.addAction(copy_action)
        
        clear_action = QAction("지우기", self)
        clear_action.triggered.connect(self._clear_all)
        edit_menu.addAction(clear_action)
        
        # URL 메뉴
        url_menu = menubar.addMenu("URL")
        
        add_fav_action = QAction("즐겨찾기 추가", self)
        add_fav_action.triggered.connect(self._add_favorite)
        url_menu.addAction(add_fav_action)
        
        manage_fav_action = QAction("즐겨찾기 관리", self)
        manage_fav_action.triggered.connect(self._manage_favorites)
        url_menu.addAction(manage_fav_action)
        
        url_menu.addSeparator()
        
        history_action = QAction("히스토리 보기", self)
        history_action.triggered.connect(self._show_history)
        url_menu.addAction(history_action)
        
        clear_hist_action = QAction("히스토리 삭제", self)
        clear_hist_action.triggered.connect(self._clear_history)
        url_menu.addAction(clear_hist_action)
        
        # 설정 메뉴
        settings_menu = menubar.addMenu("설정")
        
        self.punct_action = QAction("문장부호 자동 교정", self, checkable=True)
        self.punct_action.setChecked(self.config.get('auto_punctuation', True))
        self.punct_action.triggered.connect(self._on_setting_changed)
        settings_menu.addAction(self.punct_action)
        
        self.dup_action = QAction("중복 필터링", self, checkable=True)
        self.dup_action.setChecked(self.config.get('filter_duplicates', True))
        self.dup_action.triggered.connect(self._on_setting_changed)
        settings_menu.addAction(self.dup_action)
        
        self.noise_action = QAction("노이즈 필터링", self, checkable=True)
        self.noise_action.setChecked(self.config.get('filter_noise', True))
        self.noise_action.triggered.connect(self._on_setting_changed)
        settings_menu.addAction(self.noise_action)
        
        self.color_action = QAction("화자별 색상", self, checkable=True)
        self.color_action.setChecked(self.config.get('show_speaker_colors', True))
        self.color_action.triggered.connect(self._on_setting_changed)
        settings_menu.addAction(self.color_action)
        
        settings_menu.addSeparator()
        
        font_up_action = QAction("글자 크게 (Ctrl++)", self)
        font_up_action.triggered.connect(lambda: self._change_font(1))
        settings_menu.addAction(font_up_action)
        
        font_down_action = QAction("글자 작게 (Ctrl+-)", self)
        font_down_action.triggered.connect(lambda: self._change_font(-1))
        settings_menu.addAction(font_down_action)
        
        # 도움말 메뉴
        help_menu = menubar.addMenu("도움말")
        
        shortcuts_action = QAction("단축키", self)
        shortcuts_action.triggered.connect(self._show_shortcuts)
        help_menu.addAction(shortcuts_action)
        
        about_action = QAction("정보", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def _create_status_bar(self):
        status = self.statusBar()
        
        # 연결 상태
        conn_widget = QWidget()
        conn_layout = QHBoxLayout(conn_widget)
        conn_layout.setContentsMargins(0, 0, 0, 0)
        conn_layout.setSpacing(8)
        
        self.conn_indicator = ConnectionIndicator()
        self.status_label = QLabel("대기 중")
        
        conn_layout.addWidget(self.conn_indicator)
        conn_layout.addWidget(self.status_label)
        
        status.addWidget(conn_widget)
        
        # 실시간 저장 상태
        self.rt_label = QLabel("")
        status.addPermanentWidget(self.rt_label)
        
        # 메모리
        self.mem_label = QLabel("")
        status.addPermanentWidget(self.mem_label)
        
        # 프로그레스바
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(150)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.hide()
        status.addPermanentWidget(self.progress)
    
    def _apply_theme(self):
        self.setStyleSheet(get_stylesheet(self.theme))
        self.accumulator.speaker_mgr.set_theme(self.theme)
        
        # 테마 버튼 텍스트 업데이트
        self.theme_btn.setText("🌙 다크 모드" if self.theme == Theme.DARK else "☀️ 라이트 모드")
        
        # StatCard 스타일
        c = THEMES[self.theme]
        stat_style = f"""
            QFrame#statCard {{
                background-color: {c.bg_tertiary};
                border-radius: 12px;
                padding: 8px;
            }}
        """
        for card in [self.stat_time, self.stat_chars, self.stat_sents, self.stat_speakers]:
            card.setStyleSheet(stat_style)
    
    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_txt)
        QShortcut(QKeySequence("Ctrl+Q"), self, self.close)
        QShortcut(QKeySequence("Ctrl+T"), self, self._toggle_theme)
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self.search_input.setFocus())
        QShortcut(QKeySequence("Ctrl++"), self, lambda: self._change_font(1))
        QShortcut(QKeySequence("Ctrl+-"), self, lambda: self._change_font(-1))
        QShortcut(QKeySequence("Ctrl+="), self, lambda: self._change_font(1))
        QShortcut(QKeySequence("F5"), self, self._start)
        QShortcut(QKeySequence("Escape"), self, self._stop)
        QShortcut(QKeySequence("F3"), self, lambda: self._nav_search(1))
        QShortcut(QKeySequence("Shift+F3"), self, lambda: self._nav_search(-1))
    
    def _setup_timers(self):
        # 통계 타이머
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self._update_stats)
        
        # 메모리 타이머
        self.mem_timer = QTimer(self)
        self.mem_timer.timeout.connect(self._update_memory)
        self.mem_timer.start(5000)
    
    # ========== URL 관련 ==========
    
    def _update_url_list(self):
        self.url_combo.clear()
        
        # 즐겨찾기
        for f in self.url_history.get_favs():
            self.url_combo.addItem(f"★ {f['title']}", f['url'])
        
        # 히스토리
        for h in self.url_history.get_recent(10):
            self.url_combo.addItem(h['url'], h['url'])
        
        if self.url_combo.count() == 0:
            self.url_combo.addItem("https://www.webcast.go.kr/live/")
    
    def _on_url_changed(self, text):
        # 즐겨찾기 선택 시 실제 URL로 변환
        if text.startswith("★ "):
            for f in self.url_history.get_favs():
                if f"★ {f['title']}" == text:
                    self.url_combo.setCurrentText(f['url'])
                    break
    
    def _get_url(self):
        text = self.url_combo.currentText().strip()
        if text.startswith("★ "):
            for f in self.url_history.get_favs():
                if f"★ {f['title']}" == text:
                    return f['url']
        return text
    
    def _add_favorite(self):
        url = self._get_url()
        if not url:
            return
        
        title, ok = QInputDialog.getText(self, "즐겨찾기 추가", "이름:", text=url[:50])
        if ok and title:
            if self.url_history.add_fav(url, title):
                self._update_url_list()
                self.status_label.setText("즐겨찾기 추가됨")
            else:
                QMessageBox.information(self, "알림", "이미 존재합니다.")
    
    def _manage_favorites(self):
        favs = self.url_history.get_favs()
        if not favs:
            QMessageBox.information(self, "즐겨찾기", "저장된 즐겨찾기가 없습니다.")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("즐겨찾기 관리")
        dialog.setMinimumSize(500, 300)
        
        layout = QVBoxLayout(dialog)
        
        listbox = QListWidget()
        for f in favs:
            listbox.addItem(f"{f['title']} - {f['url'][:40]}")
        layout.addWidget(listbox)
        
        btn_layout = QHBoxLayout()
        
        del_btn = QPushButton("삭제")
        del_btn.clicked.connect(lambda: self._delete_favorite(listbox, favs, dialog))
        
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(dialog.close)
        
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        
        dialog.exec()
    
    def _delete_favorite(self, listbox, favs, dialog):
        row = listbox.currentRow()
        if row >= 0:
            self.url_history.rm_fav(favs[row]['url'])
            listbox.takeItem(row)
            self._update_url_list()
    
    def _show_history(self):
        hist = self.url_history.get_recent(20)
        if not hist:
            QMessageBox.information(self, "히스토리", "방문 기록이 없습니다.")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("URL 히스토리")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        listbox = QListWidget()
        for h in hist:
            listbox.addItem(h['url'][:70])
        layout.addWidget(listbox)
        
        btn_layout = QHBoxLayout()
        
        use_btn = QPushButton("사용")
        use_btn.clicked.connect(lambda: self._use_history(listbox, hist, dialog))
        
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(dialog.close)
        
        btn_layout.addWidget(use_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        
        dialog.exec()
    
    def _use_history(self, listbox, hist, dialog):
        row = listbox.currentRow()
        if row >= 0:
            self.url_combo.setCurrentText(hist[row]['url'])
            dialog.close()
    
    def _clear_history(self):
        reply = QMessageBox.question(self, "확인", "히스토리를 삭제하시겠습니까?")
        if reply == QMessageBox.StandardButton.Yes:
            self.url_history.clear_hist()
            self._update_url_list()
    
    # ========== 추출 제어 ==========
    
    def _start(self):
        if self.worker and self.worker.isRunning():
            return
        
        url = self._get_url()
        selector = self.selector_combo.currentText().strip()
        
        if not url or not selector:
            QMessageBox.warning(self, "오류", "URL과 CSS 선택자를 입력하세요.")
            return
        
        # URL 히스토리 추가
        self.url_history.add_hist(url)
        self._update_url_list()
        
        # 초기화
        self.accumulator.reset()
        self.subtitle_text.clear()
        self.speaker_list.clear()
        self.start_time = time.time()
        self.reconnects = 0
        
        # 실시간 저장 시작
        if self.realtime_check.isChecked():
            fp = self.writer.start("국회자막")
            if fp:
                self.rt_label.setText(f"저장: {Path(fp).name}")
        
        # 워커 시작
        self.worker = ExtractionWorker(
            url, selector,
            headless=self.headless_check.isChecked(),
            auto_reconnect=self.reconnect_check.isChecked()
        )
        self.worker.set_components(self.accumulator, self.writer, self.realtime_check.isChecked())
        
        self.worker.status_update.connect(self._on_status)
        self.worker.connection_update.connect(self._on_connection)
        self.worker.subtitle_update.connect(self._on_subtitle)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.reconnect_update.connect(self._on_reconnect)
        
        self.worker.start()
        
        # UI 업데이트
        self._update_buttons(True)
        self.progress.show()
        self.stats_timer.start(1000)
        
        logger.info(f"추출 시작: {url}")
    
    def _stop(self):
        if not self.worker or not self.worker.isRunning():
            return
        
        self.worker.stop()
        self.worker.wait(3000)
        
        self.accumulator.finalize()
        self.writer.close()
        self.rt_label.setText("")
        
        self._update_buttons(False)
        self.progress.hide()
        self.stats_timer.stop()
        self.conn_indicator.set_connected(False)
        
        stats = self.accumulator.get_stats()
        self.status_label.setText(f"중지됨 - {stats['sents']}문장, {stats['chars']:,}자")
        
        logger.info("추출 중지")
    
    def _toggle_pause(self):
        if not self.worker:
            return
        
        paused = self.worker.toggle_pause()
        self.pause_btn.setText("▶  재개" if paused else "⏸  일시정지")
        self.status_label.setText("일시정지" if paused else "재개됨")
    
    def _update_buttons(self, running):
        self.start_btn.setEnabled(not running)
        self.pause_btn.setEnabled(running)
        self.stop_btn.setEnabled(running)
        self.url_combo.setEnabled(not running)
        self.selector_combo.setEnabled(not running)
    
    # ========== 시그널 핸들러 ==========
    
    def _on_status(self, msg):
        self.status_label.setText(msg)
    
    def _on_connection(self, connected):
        self.conn_indicator.set_connected(connected)
        if connected:
            self.progress.hide()
    
    def _on_subtitle(self, data):
        # 미리보기
        preview = ""
        if data.get('speaker'):
            preview = f"[{data['speaker']}]\n"
        preview += data.get('current', '')
        self.preview_text.setText(preview)
        
        # 메인 텍스트 새로고침
        self._refresh_text()
        
        # 화자 목록
        speakers = self.accumulator.speaker_mgr.all()
        self.speaker_list.clear()
        for s in speakers.keys():
            item = QListWidgetItem(s)
            item.setForeground(QColor(speakers[s]))
            self.speaker_list.addItem(item)
    
    def _on_error(self, msg):
        self.progress.hide()
        QMessageBox.critical(self, "오류", msg)
        self._update_buttons(False)
        self.stats_timer.stop()
    
    def _on_finished(self):
        self._update_buttons(False)
        self.progress.hide()
        self.stats_timer.stop()
        stats = self.accumulator.get_stats()
        self.status_label.setText(f"완료 - {stats['sents']}문장, {stats['chars']:,}자")
    
    def _on_reconnect(self, count):
        self.reconnects = count
    
    # ========== 화면 업데이트 ==========
    
    def _refresh_text(self):
        self.subtitle_text.clear()
        
        cursor = self.subtitle_text.textCursor()
        sentences = self.accumulator.get_sents()
        speakers = self.accumulator.speaker_mgr.all()
        show_colors = self.color_action.isChecked()
        
        for i, sent in enumerate(sentences):
            if i > 0:
                cursor.insertText("\n\n")
            
            if sent.get('speaker'):
                fmt = QTextCharFormat()
                if show_colors and sent['speaker'] in speakers:
                    fmt.setForeground(QColor(speakers[sent['speaker']]))
                    fmt.setFontWeight(QFont.Weight.Bold)
                cursor.insertText(f"[{sent['speaker']}] ", fmt)
            
            cursor.insertText(sent['text'])
        
        # 현재 진행 중
        current = self.accumulator.current
        cur_speaker = self.accumulator.cur_speaker
        
        if current:
            if sentences:
                cursor.insertText("\n\n")
            
            if cur_speaker:
                fmt = QTextCharFormat()
                if show_colors and cur_speaker in speakers:
                    fmt.setForeground(QColor(speakers[cur_speaker]))
                    fmt.setFontWeight(QFont.Weight.Bold)
                cursor.insertText(f"[{cur_speaker}] ", fmt)
            
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(THEMES[self.theme].fg_muted))
            cursor.insertText(current, fmt)
        
        if self.scroll_check.isChecked():
            self.subtitle_text.moveCursor(QTextCursor.MoveOperation.End)
    
    def _update_stats(self):
        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            h, r = divmod(elapsed, 3600)
            m, s = divmod(r, 60)
            self.stat_time.set_value(f"{h:02d}:{m:02d}:{s:02d}")
        
        stats = self.accumulator.get_stats()
        self.stat_chars.set_value(f"{stats['chars']:,}")
        self.stat_sents.set_value(str(stats['sents']))
        self.stat_speakers.set_value(str(len(stats['speakers'])))
    
    def _update_memory(self):
        if PSUTIL_AVAILABLE:
            try:
                mem = psutil.Process().memory_info().rss / 1024 / 1024
                self.mem_label.setText(f"메모리: {mem:.0f}MB")
            except Exception:
                pass
    
    # ========== 검색 ==========
    
    def _search(self):
        query = self.search_input.text().strip()
        if not query:
            self.search_label.setText("")
            return
        
        text = self.subtitle_text.toPlainText()
        self.search_matches = []
        self.search_idx = 0
        
        start = 0
        while True:
            idx = text.lower().find(query.lower(), start)
            if idx == -1:
                break
            self.search_matches.append((idx, len(query)))
            start = idx + 1
        
        if self.search_matches:
            self.search_label.setText(f"{len(self.search_matches)}개")
            self._highlight_search()
        else:
            self.search_label.setText("없음")
    
    def _nav_search(self, direction):
        if not self.search_matches:
            return
        self.search_idx = (self.search_idx + direction) % len(self.search_matches)
        self._highlight_search()
    
    def _highlight_search(self):
        if not self.search_matches:
            return
        
        idx, length = self.search_matches[self.search_idx]
        cursor = self.subtitle_text.textCursor()
        cursor.setPosition(idx)
        cursor.setPosition(idx + length, QTextCursor.MoveMode.KeepAnchor)
        self.subtitle_text.setTextCursor(cursor)
        self.subtitle_text.ensureCursorVisible()
        
        self.search_label.setText(f"{self.search_idx + 1}/{len(self.search_matches)}")
    
    # ========== 파일 & 클립보드 ==========
    
    def _save_txt(self):
        text = self.accumulator.get_full()
        if not text:
            QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
            return
        
        filename = f"국회자막_{datetime.now():%Y%m%d_%H%M%S}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "저장", filename, "텍스트 파일 (*.txt)")
        
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(text)
                QMessageBox.information(self, "완료", f"저장되었습니다.\n\n{path}")
                self.status_label.setText(f"저장: {path}")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"저장 실패: {e}")
    
    def _copy_clipboard(self):
        text = self.accumulator.get_full()
        if not text:
            QMessageBox.warning(self, "알림", "복사할 내용이 없습니다.")
            return
        
        QApplication.clipboard().setText(text)
        self.status_label.setText(f"복사됨 ({len(text):,}자)")
    
    def _clear_all(self):
        if self.accumulator.get_stats()['sents'] == 0:
            return
        
        reply = QMessageBox.question(self, "확인", "모든 내용을 삭제하시겠습니까?")
        if reply == QMessageBox.StandardButton.Yes:
            self.accumulator.reset()
            self.subtitle_text.clear()
            self.speaker_list.clear()
            self.status_label.setText("내용 삭제됨")
    
    def _open_folder(self):
        folder = Path("realtime_output").absolute()
        folder.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
    
    # ========== 설정 ==========
    
    def _toggle_theme(self):
        self.theme = Theme.LIGHT if self.theme == Theme.DARK else Theme.DARK
        self.config['theme'] = self.theme.value
        self._save_config()
        self._apply_theme()
        self._refresh_text()
    
    def _change_font(self, delta):
        size = self.config.get('font_size', 14)
        size = max(10, min(24, size + delta))
        self.config['font_size'] = size
        self._save_config()
        self.subtitle_text.setFont(QFont("Malgun Gothic", size))
        self.status_label.setText(f"글자 크기: {size}pt")
    
    def _on_setting_changed(self):
        self.config['headless'] = self.headless_check.isChecked()
        self.config['auto_reconnect'] = self.reconnect_check.isChecked()
        self.config['realtime_save'] = self.realtime_check.isChecked()
        self.config['auto_scroll'] = self.scroll_check.isChecked()
        self.config['auto_punctuation'] = self.punct_action.isChecked()
        self.config['filter_duplicates'] = self.dup_action.isChecked()
        self.config['filter_noise'] = self.noise_action.isChecked()
        self.config['show_speaker_colors'] = self.color_action.isChecked()
        
        self._apply_settings()
        self._save_config()
        
        if self.accumulator.get_stats()['sents'] > 0:
            self._refresh_text()
    
    # ========== 도움말 ==========
    
    def _show_shortcuts(self):
        QMessageBox.information(self, "단축키", """
단축키 안내

Ctrl+S : 저장
Ctrl+Q : 종료
Ctrl+T : 테마 전환
Ctrl+F : 검색
Ctrl++/- : 글자 크기
F5 : 시작
ESC : 중지
F3 : 다음 검색
Shift+F3 : 이전 검색
        """)
    
    def _show_about(self):
        QMessageBox.about(self, "정보", f"""
국회 의사중계 자막 추출기 v{self.VERSION}

PyQt6 모던 UI 버전

주요 기능:
• 단어 단위 지능형 누적
• 문장부호 자동 교정
• 노이즈/중복 필터링
• 화자 자동 감지 + 색상 구분
• 실시간 파일 저장
• URL 즐겨찾기/히스토리
• 자동 재연결
• 헤드리스 모드
• 다크/라이트 테마
        """)
    
    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(self, "종료", "추출 중입니다. 종료하시겠습니까?")
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            
            self.worker.stop()
            self.worker.wait(3000)
        
        self.accumulator.finalize()
        self.writer.close()
        self._save_config()
        
        logger.info("프로그램 종료")
        event.accept()


# ============================================================
# 메인
# ============================================================

def main():
    # HiDPI 설정
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # 기본 폰트 설정
    font = QFont("Malgun Gothic", 10)
    app.setFont(font)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
