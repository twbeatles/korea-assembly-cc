# -*- coding: utf-8 -*-
"""
국회 의사중계 자막 추출기 v7.0
완전판

추가 기능:
- 문장부호 자동 교정
- 중복 문장 필터링
- 노이즈 필터링 강화
- 실시간 파일 저장
- 화자 자동 감지 + 색상 구분
- URL 히스토리/즐겨찾기
- 자동 재연결 (강화)
- 메모리 최적화
- 헤드리스 모드 옵션
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
import weakref
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import deque, OrderedDict
import colorsys

try:
    import tkinter as tk
    from tkinter import scrolledtext, messagebox, filedialog, ttk, simpledialog
except ImportError:
    print("tkinter 라이브러리를 찾을 수 없습니다.")
    sys.exit(1)

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, 
        WebDriverException,
        NoSuchElementException,
        StaleElementReferenceException
    )
    from selenium.webdriver.chrome.options import Options
except ImportError:
    print("selenium 라이브러리를 찾을 수 없습니다.")
    print("설치: pip install selenium")
    sys.exit(1)


# ============================================================
# 상수 및 설정
# ============================================================

class Theme(Enum):
    DARK = "dark"
    LIGHT = "light"


THEMES = {
    Theme.DARK: {
        'bg': '#1e1e1e',
        'fg': '#e0e0e0',
        'accent': '#4a9eff',
        'secondary_bg': '#2d2d2d',
        'text_bg': '#252526',
        'text_fg': '#d4d4d4',
        'highlight': '#264f78',
        'timestamp': '#6a9955',
        'preview': '#808080',
        'error': '#f44747',
        'success': '#4ec9b0',
        'warning': '#dcdcaa',
        'button_bg': '#0e639c',
        'button_fg': '#ffffff',
        'entry_bg': '#3c3c3c',
        'entry_fg': '#cccccc',
        'border': '#3d3d3d'
    },
    Theme.LIGHT: {
        'bg': '#f5f5f5',
        'fg': '#333333',
        'accent': '#0066cc',
        'secondary_bg': '#ffffff',
        'text_bg': '#ffffff',
        'text_fg': '#1e1e1e',
        'highlight': '#add6ff',
        'timestamp': '#008000',
        'preview': '#a0a0a0',
        'error': '#d32f2f',
        'success': '#2e7d32',
        'warning': '#ed6c02',
        'button_bg': '#0066cc',
        'button_fg': '#ffffff',
        'entry_bg': '#ffffff',
        'entry_fg': '#333333',
        'border': '#d0d0d0'
    }
}

# 화자별 색상 팔레트 (다크/라이트 테마용)
SPEAKER_COLORS_DARK = [
    '#61afef',  # 파랑
    '#e06c75',  # 빨강
    '#98c379',  # 초록
    '#d19a66',  # 주황
    '#c678dd',  # 보라
    '#56b6c2',  # 청록
    '#e5c07b',  # 노랑
    '#be5046',  # 갈색
    '#7ec699',  # 민트
    '#f991b3',  # 분홍
]

SPEAKER_COLORS_LIGHT = [
    '#0066cc',  # 파랑
    '#cc0000',  # 빨강
    '#2e7d32',  # 초록
    '#e65100',  # 주황
    '#7b1fa2',  # 보라
    '#00838f',  # 청록
    '#f9a825',  # 노랑
    '#6d4c41',  # 갈색
    '#00897b',  # 민트
    '#c2185b',  # 분홍
]


# ============================================================
# 텍스트 처리 유틸리티
# ============================================================

class TextProcessor:
    """텍스트 정제 및 처리 유틸리티"""
    
    # 노이즈 패턴
    NOISE_PATTERNS = [
        r'\[음성\s*인식\s*중[^\]]*\]',
        r'\[자막[^\]]*\]',
        r'\[음악\]',
        r'\[박수\]',
        r'\[웃음\]',
        r'^\s*[-=]{3,}\s*$',
        r'^\s*\*{3,}\s*$',
        r'\(음성\s*인식\s*중\)',
        r'♪+',
        r'♬+',
    ]
    
    # 화자 패턴
    SPEAKER_PATTERNS = [
        r'^([가-힣]{2,4})\s*(의원|위원장|위원|장관|총리|대통령|의장|부의장|차관|처장|청장|실장|국장|과장)\s*[:\.]?\s*',
        r'^\[([가-힣]{2,4})\s*(의원|위원장|위원|장관)\]\s*',
        r'^【([가-힣]{2,4})】\s*',
        r'^◯\s*([가-힣]{2,4})\s*(의원|위원장|위원|장관)\s*',
        r'^○\s*([가-힣]{2,4})\s*(의원|위원장|위원|장관)\s*',
    ]
    
    # 문장 종결 패턴
    SENTENCE_END_PATTERNS = [
        r'다\s*$',      # ~합니다, ~했다
        r'요\s*$',      # ~해요, ~이에요  
        r'까\s*$',      # ~합니까, ~할까
        r'죠\s*$',      # ~하죠
        r'니다\s*$',    # ~습니다
        r'세요\s*$',    # ~하세요
        r'시오\s*$',    # ~하시오
        r'구나\s*$',    # ~하는구나
        r'네요\s*$',    # ~하네요
    ]
    
    def __init__(self):
        self._compiled_noise = [re.compile(p, re.MULTILINE | re.IGNORECASE) for p in self.NOISE_PATTERNS]
        self._compiled_speaker = [re.compile(p) for p in self.SPEAKER_PATTERNS]
        self._compiled_sentence_end = [re.compile(p) for p in self.SENTENCE_END_PATTERNS]
    
    def remove_noise(self, text: str) -> str:
        """노이즈 제거"""
        if not text:
            return ""
        
        for pattern in self._compiled_noise:
            text = pattern.sub('', text)
        
        return text.strip()
    
    def detect_speaker(self, text: str) -> Tuple[Optional[str], str]:
        """화자 감지 및 분리"""
        if not text:
            return None, ""
        
        for pattern in self._compiled_speaker:
            match = pattern.match(text)
            if match:
                groups = match.groups()
                if len(groups) >= 2:
                    speaker = f"{groups[0]} {groups[1]}"
                else:
                    speaker = groups[0]
                
                remaining = text[match.end():].strip()
                return speaker, remaining
        
        return None, text
    
    def add_punctuation(self, text: str) -> str:
        """문장부호 자동 추가"""
        if not text:
            return ""
        
        text = text.strip()
        
        # 이미 문장부호가 있으면 그대로
        if text and text[-1] in '.!?。':
            return text
        
        # 문장 종결 패턴 확인
        for pattern in self._compiled_sentence_end:
            if pattern.search(text):
                return text + '.'
        
        return text
    
    def normalize_spaces(self, text: str) -> str:
        """공백 정규화"""
        if not text:
            return ""
        
        # 연속 공백을 하나로
        text = re.sub(r'[ \t]+', ' ', text)
        # 줄바꿈 정리
        text = re.sub(r'\n\s*\n', '\n\n', text)
        
        return text.strip()
    
    def process(self, text: str) -> Tuple[Optional[str], str]:
        """전체 처리 파이프라인"""
        if not text:
            return None, ""
        
        # 1. 노이즈 제거
        text = self.remove_noise(text)
        
        # 2. 공백 정규화
        text = self.normalize_spaces(text)
        
        # 3. 화자 감지
        speaker, text = self.detect_speaker(text)
        
        # 4. 문장부호 추가
        text = self.add_punctuation(text)
        
        return speaker, text


# ============================================================
# 중복 필터링 및 메모리 관리
# ============================================================

class DuplicateFilter:
    """중복 문장 필터링 (메모리 효율적)"""
    
    def __init__(self, max_cache_size: int = 1000):
        self.max_cache_size = max_cache_size
        self._hash_cache: OrderedDict = OrderedDict()
        self._recent_texts: deque = deque(maxlen=50)  # 최근 50개 텍스트
    
    def _compute_hash(self, text: str) -> str:
        """텍스트 해시 계산"""
        normalized = re.sub(r'\s+', '', text.lower())
        return hashlib.md5(normalized.encode()).hexdigest()[:16]
    
    def is_duplicate(self, text: str, similarity_threshold: float = 0.85) -> bool:
        """중복 여부 확인"""
        if not text or len(text) < 5:
            return False
        
        text_hash = self._compute_hash(text)
        
        # 정확히 같은 해시
        if text_hash in self._hash_cache:
            return True
        
        # 최근 텍스트와 유사도 비교
        for recent in self._recent_texts:
            if self._similarity(text, recent) >= similarity_threshold:
                return True
        
        return False
    
    def add(self, text: str):
        """필터에 텍스트 추가"""
        if not text:
            return
        
        text_hash = self._compute_hash(text)
        
        # 캐시 크기 관리
        if len(self._hash_cache) >= self.max_cache_size:
            # 오래된 항목 제거
            for _ in range(self.max_cache_size // 10):
                self._hash_cache.popitem(last=False)
        
        self._hash_cache[text_hash] = True
        self._recent_texts.append(text)
    
    def _similarity(self, text1: str, text2: str) -> float:
        """두 텍스트의 유사도 (0~1)"""
        if not text1 or not text2:
            return 0.0
        
        # 간단한 Jaccard 유사도
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        return intersection / union if union > 0 else 0.0
    
    def clear(self):
        """캐시 초기화"""
        self._hash_cache.clear()
        self._recent_texts.clear()


class MemoryManager:
    """메모리 관리자"""
    
    def __init__(self, check_interval: int = 60):
        self.check_interval = check_interval
        self.last_gc_time = time.time()
        self._weak_refs: List[weakref.ref] = []
    
    def register(self, obj):
        """객체 등록 (약한 참조)"""
        self._weak_refs.append(weakref.ref(obj))
    
    def check_and_cleanup(self):
        """메모리 체크 및 정리"""
        current_time = time.time()
        
        if current_time - self.last_gc_time >= self.check_interval:
            # 죽은 참조 제거
            self._weak_refs = [ref for ref in self._weak_refs if ref() is not None]
            
            # 가비지 컬렉션
            gc.collect()
            
            self.last_gc_time = current_time
            return True
        
        return False


# ============================================================
# URL 히스토리 관리
# ============================================================

class URLHistory:
    """URL 히스토리 및 즐겨찾기 관리"""
    
    def __init__(self, filepath: str = "url_history.json"):
        self.filepath = filepath
        self.history: List[Dict] = []
        self.favorites: List[Dict] = []
        self.max_history = 50
        self.load()
    
    def load(self):
        """파일에서 로드"""
        try:
            if Path(self.filepath).exists():
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.history = data.get('history', [])
                    self.favorites = data.get('favorites', [])
        except:
            self.history = []
            self.favorites = []
    
    def save(self):
        """파일에 저장"""
        try:
            data = {
                'history': self.history[-self.max_history:],
                'favorites': self.favorites
            }
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except:
            pass
    
    def add_history(self, url: str, title: str = ""):
        """히스토리에 추가"""
        # 중복 제거
        self.history = [h for h in self.history if h['url'] != url]
        
        self.history.append({
            'url': url,
            'title': title or url,
            'timestamp': datetime.now().isoformat()
        })
        
        # 최대 개수 유지
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]
        
        self.save()
    
    def add_favorite(self, url: str, title: str):
        """즐겨찾기에 추가"""
        # 중복 체크
        if any(f['url'] == url for f in self.favorites):
            return False
        
        self.favorites.append({
            'url': url,
            'title': title,
            'timestamp': datetime.now().isoformat()
        })
        
        self.save()
        return True
    
    def remove_favorite(self, url: str):
        """즐겨찾기에서 제거"""
        self.favorites = [f for f in self.favorites if f['url'] != url]
        self.save()
    
    def get_recent(self, count: int = 10) -> List[Dict]:
        """최근 히스토리"""
        return list(reversed(self.history[-count:]))
    
    def get_favorites(self) -> List[Dict]:
        """즐겨찾기 목록"""
        return self.favorites.copy()
    
    def clear_history(self):
        """히스토리 초기화"""
        self.history = []
        self.save()


# ============================================================
# 화자 색상 관리
# ============================================================

class SpeakerColorManager:
    """화자별 색상 관리"""
    
    def __init__(self, theme: Theme = Theme.DARK):
        self.theme = theme
        self._speaker_colors: Dict[str, str] = {}
        self._color_index = 0
    
    def set_theme(self, theme: Theme):
        """테마 변경"""
        self.theme = theme
        # 색상 재할당
        speakers = list(self._speaker_colors.keys())
        self._speaker_colors.clear()
        self._color_index = 0
        for speaker in speakers:
            self.get_color(speaker)
    
    def get_color(self, speaker: str) -> str:
        """화자의 색상 반환 (없으면 새로 할당)"""
        if not speaker:
            return THEMES[self.theme]['fg']
        
        if speaker not in self._speaker_colors:
            colors = SPEAKER_COLORS_DARK if self.theme == Theme.DARK else SPEAKER_COLORS_LIGHT
            self._speaker_colors[speaker] = colors[self._color_index % len(colors)]
            self._color_index += 1
        
        return self._speaker_colors[speaker]
    
    def get_all_speakers(self) -> Dict[str, str]:
        """모든 화자와 색상"""
        return self._speaker_colors.copy()
    
    def clear(self):
        """초기화"""
        self._speaker_colors.clear()
        self._color_index = 0


# ============================================================
# 실시간 파일 저장
# ============================================================

class RealTimeWriter:
    """실시간 파일 저장"""
    
    def __init__(self, base_dir: str = "realtime_output"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
        self.current_file: Optional[Path] = None
        self._file_handle = None
        self._write_buffer: List[str] = []
        self._buffer_size = 5  # 5개씩 모아서 쓰기
        self._lock = threading.Lock()
    
    def start_session(self, prefix: str = "자막"):
        """새 세션 시작"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.current_file = self.base_dir / f"{prefix}_{timestamp}.txt"
        
        try:
            self._file_handle = open(self.current_file, 'w', encoding='utf-8')
            # 헤더 작성
            self._file_handle.write(f"# 국회 의사중계 자막\n")
            self._file_handle.write(f"# 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            self._file_handle.write(f"{'='*50}\n\n")
            self._file_handle.flush()
        except Exception as e:
            print(f"파일 생성 오류: {e}")
            self._file_handle = None
    
    def write(self, text: str, speaker: str = None, timestamp: str = None):
        """텍스트 쓰기"""
        if not self._file_handle:
            return
        
        with self._lock:
            line_parts = []
            
            if timestamp:
                line_parts.append(f"[{timestamp}]")
            
            if speaker:
                line_parts.append(f"[{speaker}]")
            
            line_parts.append(text)
            
            line = ' '.join(line_parts) + '\n'
            self._write_buffer.append(line)
            
            # 버퍼가 찼으면 플러시
            if len(self._write_buffer) >= self._buffer_size:
                self._flush()
    
    def _flush(self):
        """버퍼 플러시"""
        if not self._file_handle or not self._write_buffer:
            return
        
        try:
            for line in self._write_buffer:
                self._file_handle.write(line)
            self._file_handle.flush()
            self._write_buffer.clear()
        except:
            pass
    
    def close(self):
        """세션 종료"""
        with self._lock:
            self._flush()
            
            if self._file_handle:
                try:
                    self._file_handle.write(f"\n{'='*50}\n")
                    self._file_handle.write(f"# 종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    self._file_handle.close()
                except:
                    pass
                self._file_handle = None
    
    def get_current_filepath(self) -> Optional[str]:
        """현재 파일 경로"""
        return str(self.current_file) if self.current_file else None


# ============================================================
# 자막 누적 처리기 (개선판)
# ============================================================

class SubtitleAccumulator:
    """스트리밍 자막 누적 처리기 (v2)"""
    
    def __init__(self):
        self.text_processor = TextProcessor()
        self.duplicate_filter = DuplicateFilter()
        self.speaker_manager = SpeakerColorManager()
        
        # 데이터
        self.sentences: List[Dict] = []  # {'text': str, 'speaker': str, 'timestamp': datetime}
        self.current_sentence = ""
        self.current_speaker = None
        self.last_raw_text = ""
        
        # 통계
        self.total_chars = 0
        self.filtered_count = 0  # 필터링된 중복 수
    
    def reset(self):
        """초기화"""
        self.sentences.clear()
        self.current_sentence = ""
        self.current_speaker = None
        self.last_raw_text = ""
        self.total_chars = 0
        self.filtered_count = 0
        self.duplicate_filter.clear()
        self.speaker_manager.clear()
    
    def process(self, raw_text: str) -> Dict:
        """
        새 자막 텍스트 처리
        
        Returns:
            {
                'changed': bool,
                'new_sentence': bool,  # 새 문장이 확정됨
                'current': str,        # 현재 진행 중인 문장
                'speaker': str,        # 현재 화자
                'full_text': str       # 전체 누적 텍스트
            }
        """
        result = {
            'changed': False,
            'new_sentence': False,
            'current': self.current_sentence,
            'speaker': self.current_speaker,
            'full_text': self._build_full_text()
        }
        
        if not raw_text:
            return result
        
        # 텍스트 처리
        speaker, clean_text = self.text_processor.process(raw_text)
        
        if not clean_text:
            return result
        
        # 완전히 동일하면 무시
        if clean_text == self.last_raw_text:
            return result
        
        # 새 문장 판단
        is_new = self._is_new_sentence(clean_text)
        
        if is_new:
            # 이전 문장 확정
            if self.current_sentence:
                if not self.duplicate_filter.is_duplicate(self.current_sentence):
                    self._finalize_current()
                    result['new_sentence'] = True
                else:
                    self.filtered_count += 1
            
            # 새 문장 시작
            self.current_sentence = clean_text
            self.current_speaker = speaker
        else:
            # 기존 문장 확장
            self.current_sentence = clean_text
            if speaker:
                self.current_speaker = speaker
        
        self.last_raw_text = clean_text
        
        result['changed'] = True
        result['current'] = self.current_sentence
        result['speaker'] = self.current_speaker
        result['full_text'] = self._build_full_text()
        
        return result
    
    def _is_new_sentence(self, new_text: str) -> bool:
        """새 문장 여부 판단"""
        if not self.last_raw_text:
            return True
        
        # 공통 접두사 길이
        common = 0
        for i in range(min(len(self.last_raw_text), len(new_text))):
            if self.last_raw_text[i] == new_text[i]:
                common += 1
            else:
                break
        
        # 공통 부분이 30% 미만이면 새 문장
        if common < len(self.last_raw_text) * 0.3:
            return True
        
        return False
    
    def _finalize_current(self):
        """현재 문장 확정"""
        if not self.current_sentence:
            return
        
        self.sentences.append({
            'text': self.current_sentence,
            'speaker': self.current_speaker,
            'timestamp': datetime.now()
        })
        
        self.duplicate_filter.add(self.current_sentence)
        self.total_chars += len(self.current_sentence)
    
    def finalize(self) -> str:
        """최종 확정 (마지막 문장 포함)"""
        if self.current_sentence:
            if not self.duplicate_filter.is_duplicate(self.current_sentence):
                self._finalize_current()
            self.current_sentence = ""
            self.current_speaker = None
        
        return self._build_full_text()
    
    def _build_full_text(self) -> str:
        """전체 텍스트 구성"""
        parts = []
        
        for sent in self.sentences:
            line = ""
            if sent['speaker']:
                line = f"[{sent['speaker']}] "
            line += sent['text']
            parts.append(line)
        
        # 현재 진행 중인 문장
        if self.current_sentence:
            line = ""
            if self.current_speaker:
                line = f"[{self.current_speaker}] "
            line += self.current_sentence
            parts.append(line)
        
        return '\n\n'.join(parts)
    
    def get_stats(self) -> Dict:
        """통계"""
        return {
            'total_sentences': len(self.sentences) + (1 if self.current_sentence else 0),
            'total_chars': self.total_chars + len(self.current_sentence),
            'filtered_duplicates': self.filtered_count,
            'speakers': list(self.speaker_manager.get_all_speakers().keys())
        }
    
    def get_last_sentence(self) -> Optional[Dict]:
        """마지막 확정된 문장"""
        if self.sentences:
            return self.sentences[-1]
        return None


# ============================================================
# 메인 애플리케이션
# ============================================================

class SubtitleExtractor:
    """국회 의사중계 자막 추출기 v7.0"""
    
    VERSION = "7.0"
    CONFIG_FILE = "subtitle_config.json"
    AUTOSAVE_DIR = "subtitle_autosave"
    REALTIME_DIR = "realtime_output"
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"국회 의사중계 자막 추출기 v{self.VERSION}")
        self.root.geometry("1300x850")
        self.root.minsize(1000, 700)
        
        # 설정 로드
        self._load_config()
        
        # 테마
        self.current_theme = Theme.DARK
        
        # 핵심 컴포넌트
        self.accumulator = SubtitleAccumulator()
        self.url_history = URLHistory()
        self.realtime_writer = RealTimeWriter(self.REALTIME_DIR)
        self.memory_manager = MemoryManager()
        
        # 상태
        self.driver: Optional[webdriver.Chrome] = None
        self.extraction_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.is_paused = False
        self.message_queue = queue.Queue()
        
        # 자동 재연결
        self.reconnect_count = 0
        self.max_reconnect = 5
        self.reconnect_delay = 3  # 초
        
        # 시간
        self.start_time: Optional[float] = None
        
        # 자동 저장
        self.autosave_timer: Optional[str] = None
        self.memory_check_timer: Optional[str] = None
        
        # GUI 생성
        self._init_styles()
        self._create_menu()
        self._create_widgets()
        self._apply_theme()
        self._bind_shortcuts()
        
        # 시작
        self._process_queue()
        self._start_memory_monitor()
        
        # 디렉토리 생성
        Path(self.AUTOSAVE_DIR).mkdir(exist_ok=True)
        Path(self.REALTIME_DIR).mkdir(exist_ok=True)
        
        # 종료 핸들러
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
    
    def _load_config(self):
        """설정 로드"""
        self.config = {
            'headless': False,
            'auto_reconnect': True,
            'realtime_save': True,
            'show_speaker_colors': True,
            'auto_scroll': True,
            'auto_punctuation': True,
            'filter_duplicates': True,
            'filter_noise': True,
        }
        
        try:
            if Path(self.CONFIG_FILE).exists():
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    self.config.update(saved)
        except:
            pass
    
    def _save_config(self):
        """설정 저장"""
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except:
            pass
    
    def _init_styles(self):
        """스타일 초기화"""
        self.style = ttk.Style()
        try:
            self.style.theme_use('clam')
        except:
            pass
    
    def _create_menu(self):
        """메뉴바"""
        self.menubar = tk.Menu(self.root)
        self.root.config(menu=self.menubar)
        
        # 파일
        file_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="파일", menu=file_menu)
        file_menu.add_command(label="TXT 저장 (Ctrl+S)", command=self._save_txt)
        file_menu.add_command(label="실시간 저장 폴더 열기", command=self._open_realtime_folder)
        file_menu.add_separator()
        file_menu.add_command(label="종료 (Ctrl+Q)", command=self._on_closing)
        
        # 편집
        edit_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="편집", menu=edit_menu)
        edit_menu.add_command(label="복사 (Ctrl+C)", command=self._copy_clipboard)
        edit_menu.add_command(label="내용 지우기", command=self._clear_all)
        
        # URL
        url_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="URL", menu=url_menu)
        url_menu.add_command(label="즐겨찾기 추가", command=self._add_favorite)
        url_menu.add_command(label="즐겨찾기 관리", command=self._manage_favorites)
        url_menu.add_separator()
        url_menu.add_command(label="히스토리 보기", command=self._show_history)
        url_menu.add_command(label="히스토리 삭제", command=self._clear_history)
        
        # 설정
        settings_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="설정", menu=settings_menu)
        
        self.headless_var = tk.BooleanVar(value=self.config['headless'])
        settings_menu.add_checkbutton(label="헤드리스 모드 (브라우저 숨김)", 
                                      variable=self.headless_var, command=self._on_config_change)
        
        self.auto_reconnect_var = tk.BooleanVar(value=self.config['auto_reconnect'])
        settings_menu.add_checkbutton(label="자동 재연결", 
                                      variable=self.auto_reconnect_var, command=self._on_config_change)
        
        self.realtime_save_var = tk.BooleanVar(value=self.config['realtime_save'])
        settings_menu.add_checkbutton(label="실시간 파일 저장", 
                                      variable=self.realtime_save_var, command=self._on_config_change)
        
        settings_menu.add_separator()
        
        self.speaker_colors_var = tk.BooleanVar(value=self.config['show_speaker_colors'])
        settings_menu.add_checkbutton(label="화자별 색상 구분", 
                                      variable=self.speaker_colors_var, command=self._on_config_change)
        
        self.auto_punct_var = tk.BooleanVar(value=self.config['auto_punctuation'])
        settings_menu.add_checkbutton(label="문장부호 자동 교정", 
                                      variable=self.auto_punct_var, command=self._on_config_change)
        
        self.filter_dup_var = tk.BooleanVar(value=self.config['filter_duplicates'])
        settings_menu.add_checkbutton(label="중복 문장 필터링", 
                                      variable=self.filter_dup_var, command=self._on_config_change)
        
        self.filter_noise_var = tk.BooleanVar(value=self.config['filter_noise'])
        settings_menu.add_checkbutton(label="노이즈 필터링", 
                                      variable=self.filter_noise_var, command=self._on_config_change)
        
        # 보기
        view_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="보기", menu=view_menu)
        view_menu.add_command(label="테마 전환 (Ctrl+T)", command=self._toggle_theme)
        view_menu.add_separator()
        view_menu.add_command(label="글자 크게 (Ctrl++)", command=lambda: self._font_size(1))
        view_menu.add_command(label="글자 작게 (Ctrl+-)", command=lambda: self._font_size(-1))
        view_menu.add_separator()
        view_menu.add_command(label="화자 목록 보기", command=self._show_speakers)
        
        # 도움말
        help_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="도움말", menu=help_menu)
        help_menu.add_command(label="단축키", command=self._show_shortcuts)
        help_menu.add_command(label="정보", command=self._show_about)
    
    def _create_widgets(self):
        """위젯 생성"""
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 상단 컨트롤
        self._create_control_area()
        
        # 설정 영역
        self._create_settings_area()
        
        # 메인 콘텐츠
        self._create_content_area()
        
        # 하단 상태바
        self._create_status_bar()
    
    def _create_control_area(self):
        """컨트롤 영역"""
        frame = ttk.Frame(self.main_frame)
        frame.pack(fill=tk.X, pady=(0, 10))
        
        # URL 라벨과 즐겨찾기 버튼
        url_label_frame = ttk.Frame(frame)
        url_label_frame.pack(side=tk.LEFT)
        
        ttk.Label(url_label_frame, text="URL:", font=("맑은 고딕", 10, "bold")).pack(side=tk.LEFT)
        
        self.favorite_btn = ttk.Button(url_label_frame, text="★", width=2, command=self._add_favorite)
        self.favorite_btn.pack(side=tk.LEFT, padx=(5, 0))
        
        # URL 콤보박스 (히스토리 포함)
        self.url_var = tk.StringVar()
        self.url_combo = ttk.Combobox(frame, textvariable=self.url_var, font=("맑은 고딕", 10), width=60)
        self.url_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 10))
        self.url_combo.set("https://www.webcast.go.kr/live/")
        self._update_url_dropdown()
        
        # 버튼
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(side=tk.RIGHT)
        
        self.start_btn = ttk.Button(btn_frame, text="▶ 시작", width=10, command=self._start)
        self.start_btn.pack(side=tk.LEFT, padx=2)
        
        self.pause_btn = ttk.Button(btn_frame, text="⏸ 일시정지", width=10, 
                                    command=self._toggle_pause, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=2)
        
        self.stop_btn = ttk.Button(btn_frame, text="⏹ 중지", width=10, 
                                   command=self._stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=2)
    
    def _create_settings_area(self):
        """설정 영역"""
        frame = ttk.LabelFrame(self.main_frame, text="설정", padding="8")
        frame.pack(fill=tk.X, pady=(0, 10))
        
        inner = ttk.Frame(frame)
        inner.pack(fill=tk.X)
        
        # CSS 선택자
        ttk.Label(inner, text="CSS 선택자:").pack(side=tk.LEFT)
        
        self.selector_combo = ttk.Combobox(inner, width=25, font=("맑은 고딕", 9))
        self.selector_combo['values'] = [
            "#viewSubtit .incont",
            "#viewSubtit",
            ".subtitle_area",
            "[id*='subtit']"
        ]
        self.selector_combo.set("#viewSubtit .incont")
        self.selector_combo.pack(side=tk.LEFT, padx=(5, 20))
        
        # 체크박스
        self.auto_scroll_var = tk.BooleanVar(value=self.config['auto_scroll'])
        ttk.Checkbutton(inner, text="자동 스크롤", variable=self.auto_scroll_var).pack(side=tk.LEFT, padx=5)
        
        # 상태 표시
        self.mode_label = ttk.Label(inner, text="", font=("맑은 고딕", 9))
        self.mode_label.pack(side=tk.RIGHT, padx=10)
        self._update_mode_label()
    
    def _create_content_area(self):
        """콘텐츠 영역"""
        frame = ttk.Frame(self.main_frame)
        frame.pack(fill=tk.BOTH, expand=True)
        
        self.paned = ttk.PanedWindow(frame, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)
        
        # 왼쪽: 자막
        left = ttk.Frame(self.paned)
        self.paned.add(left, weight=3)
        
        # 검색
        search_frame = ttk.Frame(left)
        search_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(search_frame, text="🔍").pack(side=tk.LEFT)
        self.search_entry = ttk.Entry(search_frame, font=("맑은 고딕", 9))
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.search_entry.bind('<Return>', lambda e: self._search())
        
        ttk.Button(search_frame, text="검색", width=8, command=self._search).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_frame, text="▲", width=3, command=lambda: self._nav_search(-1)).pack(side=tk.LEFT)
        ttk.Button(search_frame, text="▼", width=3, command=lambda: self._nav_search(1)).pack(side=tk.LEFT)
        
        self.search_label = ttk.Label(search_frame, text="")
        self.search_label.pack(side=tk.LEFT, padx=10)
        
        # 자막 텍스트
        text_frame = ttk.LabelFrame(left, text="자막 내용", padding="5")
        text_frame.pack(fill=tk.BOTH, expand=True)
        
        container = ttk.Frame(text_frame)
        container.pack(fill=tk.BOTH, expand=True)
        
        self.font_size = 11
        self.subtitle_text = tk.Text(
            container,
            wrap=tk.WORD,
            font=("맑은 고딕", self.font_size),
            relief=tk.FLAT,
            padx=10,
            pady=10,
            undo=True
        )
        
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=self.subtitle_text.yview)
        self.subtitle_text.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.subtitle_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self._setup_tags()
        
        # 오른쪽: 사이드바
        self._create_sidebar()
    
    def _create_sidebar(self):
        """사이드바"""
        sidebar = ttk.Frame(self.paned)
        self.paned.add(sidebar, weight=1)
        
        # 통계
        stats_frame = ttk.LabelFrame(sidebar, text="통계", padding="10")
        stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.stat_labels = {}
        stats = [
            ('time', '실행 시간'),
            ('chars', '총 글자 수'),
            ('lines', '총 문장 수'),
            ('speakers', '감지 화자'),
            ('filtered', '필터링됨'),
            ('reconnect', '재연결')
        ]
        
        for key, label in stats:
            f = ttk.Frame(stats_frame)
            f.pack(fill=tk.X, pady=1)
            ttk.Label(f, text=f"{label}:", font=("맑은 고딕", 9)).pack(side=tk.LEFT)
            self.stat_labels[key] = ttk.Label(f, text="-", font=("맑은 고딕", 9, "bold"))
            self.stat_labels[key].pack(side=tk.RIGHT)
        
        # 미리보기
        preview_frame = ttk.LabelFrame(sidebar, text="실시간 미리보기", padding="10")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.preview_text = tk.Text(
            preview_frame,
            wrap=tk.WORD,
            font=("맑은 고딕", 10),
            height=6,
            relief=tk.FLAT
        )
        self.preview_text.pack(fill=tk.BOTH, expand=True)
        self.preview_text.config(state=tk.DISABLED)
        
        # 화자 목록
        speaker_frame = ttk.LabelFrame(sidebar, text="화자 목록", padding="10")
        speaker_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.speaker_listbox = tk.Listbox(speaker_frame, height=5, font=("맑은 고딕", 9))
        self.speaker_listbox.pack(fill=tk.X)
        
        # 버튼
        btn_frame = ttk.LabelFrame(sidebar, text="빠른 작업", padding="10")
        btn_frame.pack(fill=tk.X)
        
        ttk.Button(btn_frame, text="📄 TXT 저장", command=self._save_txt).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="📋 클립보드 복사", command=self._copy_clipboard).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="📂 실시간 저장 폴더", command=self._open_realtime_folder).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="🗑️ 내용 지우기", command=self._clear_all).pack(fill=tk.X, pady=2)
    
    def _create_status_bar(self):
        """상태바"""
        frame = ttk.Frame(self.main_frame)
        frame.pack(fill=tk.X, pady=(10, 0))
        
        # 연결 표시
        self.conn_indicator = tk.Label(frame, text="●", font=("맑은 고딕", 12))
        self.conn_indicator.pack(side=tk.LEFT, padx=(0, 5))
        
        # 상태
        self.status_label = ttk.Label(frame, text="대기 중", font=("맑은 고딕", 9))
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 실시간 저장 표시
        self.realtime_label = ttk.Label(frame, text="", font=("맑은 고딕", 9))
        self.realtime_label.pack(side=tk.RIGHT, padx=10)
        
        # 메모리 표시
        self.memory_label = ttk.Label(frame, text="", font=("맑은 고딕", 9))
        self.memory_label.pack(side=tk.RIGHT, padx=10)
        
        # 진행바
        self.progress = ttk.Progressbar(frame, mode='indeterminate', length=100)
        self.progress.pack(side=tk.RIGHT)
        self.progress.pack_forget()
    
    def _setup_tags(self):
        """텍스트 태그"""
        colors = THEMES[self.current_theme]
        
        self.subtitle_text.tag_configure('timestamp', foreground=colors['timestamp'])
        self.subtitle_text.tag_configure('preview', foreground=colors['preview'])
        self.subtitle_text.tag_configure('highlight', background=colors['highlight'])
        self.subtitle_text.tag_configure('current', background=colors['accent'], foreground='white')
        
        # 화자별 색상 태그
        speaker_colors = SPEAKER_COLORS_DARK if self.current_theme == Theme.DARK else SPEAKER_COLORS_LIGHT
        for i, color in enumerate(speaker_colors):
            self.subtitle_text.tag_configure(f'speaker_{i}', foreground=color, font=("맑은 고딕", self.font_size, "bold"))
    
    def _apply_theme(self):
        """테마 적용"""
        colors = THEMES[self.current_theme]
        
        self.root.configure(bg=colors['bg'])
        
        self.style.configure('TFrame', background=colors['bg'])
        self.style.configure('TLabel', background=colors['bg'], foreground=colors['fg'])
        self.style.configure('TLabelframe', background=colors['bg'])
        self.style.configure('TLabelframe.Label', background=colors['bg'], foreground=colors['accent'])
        self.style.configure('TButton', background=colors['button_bg'])
        self.style.configure('TEntry', fieldbackground=colors['entry_bg'])
        self.style.configure('TCombobox', fieldbackground=colors['entry_bg'])
        self.style.configure('TCheckbutton', background=colors['bg'], foreground=colors['fg'])
        
        self.subtitle_text.configure(
            bg=colors['text_bg'],
            fg=colors['text_fg'],
            insertbackground=colors['fg'],
            selectbackground=colors['highlight']
        )
        
        self.preview_text.configure(bg=colors['secondary_bg'], fg=colors['preview'])
        self.speaker_listbox.configure(bg=colors['secondary_bg'], fg=colors['fg'])
        
        self._update_connection(False)
        self._setup_tags()
        
        # 화자 색상 매니저 테마 업데이트
        self.accumulator.speaker_manager.set_theme(self.current_theme)
    
    def _bind_shortcuts(self):
        """단축키"""
        self.root.bind('<Control-s>', lambda e: self._save_txt())
        self.root.bind('<Control-S>', lambda e: self._save_txt())
        self.root.bind('<Control-q>', lambda e: self._on_closing())
        self.root.bind('<Control-Q>', lambda e: self._on_closing())
        self.root.bind('<Control-t>', lambda e: self._toggle_theme())
        self.root.bind('<Control-T>', lambda e: self._toggle_theme())
        self.root.bind('<Control-f>', lambda e: self.search_entry.focus_set())
        self.root.bind('<Control-F>', lambda e: self.search_entry.focus_set())
        self.root.bind('<Control-plus>', lambda e: self._font_size(1))
        self.root.bind('<Control-minus>', lambda e: self._font_size(-1))
        self.root.bind('<Control-equal>', lambda e: self._font_size(1))
        self.root.bind('<F5>', lambda e: self._start())
        self.root.bind('<Escape>', lambda e: self._stop() if self.is_running else None)
        self.root.bind('<F3>', lambda e: self._nav_search(1))
        self.root.bind('<Shift-F3>', lambda e: self._nav_search(-1))
    
    # --------------------------------------------------------
    # URL 히스토리 관련
    # --------------------------------------------------------
    
    def _update_url_dropdown(self):
        """URL 드롭다운 업데이트"""
        items = []
        
        # 즐겨찾기
        for fav in self.url_history.get_favorites():
            items.append(f"★ {fav['title']}")
        
        # 최근 히스토리
        for hist in self.url_history.get_recent(10):
            items.append(hist['url'])
        
        self.url_combo['values'] = items if items else ["https://www.webcast.go.kr/live/"]
    
    def _add_favorite(self):
        """즐겨찾기 추가"""
        url = self.url_var.get().strip()
        if not url:
            return
        
        # URL에서 ★ 제거
        if url.startswith("★ "):
            messagebox.showinfo("알림", "이미 즐겨찾기에 있습니다.")
            return
        
        title = simpledialog.askstring("즐겨찾기 추가", "이름을 입력하세요:", initialvalue=url[:50])
        if title:
            if self.url_history.add_favorite(url, title):
                self._update_url_dropdown()
                self._update_status("즐겨찾기에 추가됨")
            else:
                messagebox.showinfo("알림", "이미 즐겨찾기에 있습니다.")
    
    def _manage_favorites(self):
        """즐겨찾기 관리"""
        favorites = self.url_history.get_favorites()
        if not favorites:
            messagebox.showinfo("즐겨찾기", "저장된 즐겨찾기가 없습니다.")
            return
        
        # 즐겨찾기 관리 창
        win = tk.Toplevel(self.root)
        win.title("즐겨찾기 관리")
        win.geometry("500x300")
        win.transient(self.root)
        
        # 목록
        listbox = tk.Listbox(win, font=("맑은 고딕", 10))
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        for fav in favorites:
            listbox.insert(tk.END, f"{fav['title']} - {fav['url'][:50]}")
        
        # 버튼
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        def delete_selected():
            sel = listbox.curselection()
            if sel:
                idx = sel[0]
                url = favorites[idx]['url']
                self.url_history.remove_favorite(url)
                listbox.delete(idx)
                self._update_url_dropdown()
        
        ttk.Button(btn_frame, text="삭제", command=delete_selected).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="닫기", command=win.destroy).pack(side=tk.RIGHT)
    
    def _show_history(self):
        """히스토리 보기"""
        history = self.url_history.get_recent(20)
        if not history:
            messagebox.showinfo("히스토리", "방문 기록이 없습니다.")
            return
        
        win = tk.Toplevel(self.root)
        win.title("URL 히스토리")
        win.geometry("600x400")
        win.transient(self.root)
        
        listbox = tk.Listbox(win, font=("맑은 고딕", 10))
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        for hist in history:
            time_str = datetime.fromisoformat(hist['timestamp']).strftime('%m/%d %H:%M')
            listbox.insert(tk.END, f"[{time_str}] {hist['url'][:70]}")
        
        def use_selected():
            sel = listbox.curselection()
            if sel:
                url = history[sel[0]]['url']
                self.url_var.set(url)
                win.destroy()
        
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(btn_frame, text="사용", command=use_selected).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="닫기", command=win.destroy).pack(side=tk.RIGHT)
    
    def _clear_history(self):
        """히스토리 삭제"""
        if messagebox.askyesno("확인", "모든 URL 히스토리를 삭제하시겠습니까?"):
            self.url_history.clear_history()
            self._update_url_dropdown()
            self._update_status("히스토리 삭제됨")
    
    def _get_actual_url(self) -> str:
        """실제 URL 가져오기"""
        url = self.url_var.get().strip()
        
        # 즐겨찾기 항목이면 실제 URL 추출
        if url.startswith("★ "):
            title = url[2:]
            for fav in self.url_history.get_favorites():
                if fav['title'] == title:
                    return fav['url']
        
        return url
    
    # --------------------------------------------------------
    # 추출 로직
    # --------------------------------------------------------
    
    def _start(self):
        """시작"""
        url = self._get_actual_url()
        if not url:
            messagebox.showerror("오류", "URL을 입력해주세요.")
            return
        
        selector = self.selector_combo.get().strip()
        if not selector:
            messagebox.showerror("오류", "CSS 선택자를 입력해주세요.")
            return
        
        # URL 히스토리 추가
        self.url_history.add_history(url)
        self._update_url_dropdown()
        
        # 초기화
        self.accumulator.reset()
        self.subtitle_text.delete('1.0', tk.END)
        self.speaker_listbox.delete(0, tk.END)
        self.start_time = time.time()
        self.reconnect_count = 0
        
        # 실시간 저장 시작
        if self.realtime_save_var.get():
            self.realtime_writer.start_session("국회자막")
            filepath = self.realtime_writer.get_current_filepath()
            if filepath:
                self.realtime_label.config(text=f"저장: {Path(filepath).name}")
        
        # UI 상태
        self.is_running = True
        self.is_paused = False
        self._update_ui_state()
        self._show_progress(True)
        self._update_status("Chrome 시작 중...")
        
        # 스레드 시작
        self.extraction_thread = threading.Thread(
            target=self._extraction_worker,
            args=(url, selector),
            daemon=True
        )
        self.extraction_thread.start()
        
        self._update_stats()
    
    def _stop(self):
        """중지"""
        if not self.is_running:
            return
        
        self.is_running = False
        self.is_paused = False
        self._update_status("중지 중...")
        
        # 마지막 확정
        self.accumulator.finalize()
        
        # 드라이버 종료
        self._close_driver()
        
        # 실시간 저장 종료
        self.realtime_writer.close()
        self.realtime_label.config(text="")
        
        # UI 업데이트
        self._update_ui_state()
        self._show_progress(False)
        self._update_connection(False)
        
        stats = self.accumulator.get_stats()
        self._update_status(f"중지됨 - {stats['total_sentences']}문장, {stats['total_chars']}자")
    
    def _toggle_pause(self):
        """일시정지"""
        if not self.is_running:
            return
        
        self.is_paused = not self.is_paused
        
        if self.is_paused:
            self.pause_btn.config(text="▶ 재개")
            self._update_status("일시정지됨")
        else:
            self.pause_btn.config(text="⏸ 일시정지")
            self._update_status("재개됨")
    
    def _extraction_worker(self, url: str, selector: str):
        """추출 작업 스레드"""
        driver = None
        
        while self.is_running:
            try:
                # Chrome 옵션
                options = Options()
                options.add_argument("--log-level=3")
                options.add_argument("--disable-blink-features=AutomationControlled")
                options.add_argument("--disable-infobars")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--disable-gpu")
                options.add_argument("--window-size=1280,720")
                options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
                options.add_experimental_option('useAutomationExtension', False)
                
                # 헤드리스 모드
                if self.headless_var.get():
                    options.add_argument("--headless=new")
                    self.message_queue.put(("status", "헤드리스 모드로 시작 중..."))
                
                # 메모리 최적화 옵션
                options.add_argument("--disable-extensions")
                options.add_argument("--disable-plugins")
                options.add_argument("--disable-images")  # 이미지 비활성화로 메모리 절약
                
                # 드라이버 시작
                try:
                    driver = webdriver.Chrome(options=options)
                    self.driver = driver
                    self.message_queue.put(("connection", True))
                    self.message_queue.put(("status", "Chrome 시작 완료"))
                except Exception as e:
                    self.message_queue.put(("error", f"Chrome 드라이버 오류: {str(e)}"))
                    return
                
                # 페이지 로드
                self.message_queue.put(("status", "페이지 로딩 중..."))
                driver.get(url)
                time.sleep(3)
                
                # AI 자막 활성화
                self.message_queue.put(("status", "AI 자막 활성화 시도..."))
                self._activate_subtitle(driver)
                time.sleep(1)
                
                # 자막 요소 찾기
                self.message_queue.put(("status", "자막 요소 검색 중..."))
                element = self._find_element(driver, selector)
                
                if not element:
                    self.message_queue.put(("error", "자막 요소를 찾을 수 없습니다."))
                    return
                
                self.message_queue.put(("status", "자막 모니터링 중..."))
                self.message_queue.put(("progress_hide", None))
                
                # 메인 루프
                check_interval = 0.15
                last_check = time.time()
                error_count = 0
                
                while self.is_running:
                    try:
                        if self.is_paused:
                            time.sleep(0.1)
                            continue
                        
                        now = time.time()
                        if now - last_check >= check_interval:
                            # 브라우저 체크
                            try:
                                _ = driver.current_url
                            except:
                                raise WebDriverException("브라우저 연결 끊김")
                            
                            # 자막 텍스트
                            try:
                                raw_text = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
                            except StaleElementReferenceException:
                                element = self._find_element(driver, selector)
                                if element:
                                    raw_text = element.text.strip()
                                else:
                                    continue
                            except NoSuchElementException:
                                error_count += 1
                                if error_count > 10:
                                    raise Exception("자막 요소 소실")
                                continue
                            
                            # 자막 처리
                            result = self.accumulator.process(raw_text)
                            
                            if result['changed']:
                                error_count = 0
                                self.message_queue.put(("update", result))
                                
                                # 실시간 저장
                                if result['new_sentence'] and self.realtime_save_var.get():
                                    last = self.accumulator.get_last_sentence()
                                    if last:
                                        ts = last['timestamp'].strftime('%H:%M:%S')
                                        self.realtime_writer.write(
                                            last['text'],
                                            speaker=last['speaker'],
                                            timestamp=ts
                                        )
                            
                            # 메모리 체크
                            if self.memory_manager.check_and_cleanup():
                                self.message_queue.put(("memory_cleaned", None))
                            
                            last_check = now
                        
                        time.sleep(0.05)
                        
                    except WebDriverException as e:
                        self.message_queue.put(("connection", False))
                        raise e
                    except Exception as e:
                        error_count += 1
                        if error_count > 10:
                            raise e
                        time.sleep(0.3)
                
                # 정상 종료
                break
                
            except WebDriverException as e:
                self.message_queue.put(("connection", False))
                
                # 자동 재연결
                if self.is_running and self.auto_reconnect_var.get() and self.reconnect_count < self.max_reconnect:
                    self.reconnect_count += 1
                    self.message_queue.put(("reconnect", self.reconnect_count))
                    self.message_queue.put(("status", f"재연결 시도 {self.reconnect_count}/{self.max_reconnect}..."))
                    
                    # 드라이버 정리
                    if driver:
                        try:
                            driver.quit()
                        except:
                            pass
                        driver = None
                        self.driver = None
                    
                    time.sleep(self.reconnect_delay)
                    continue
                else:
                    if self.is_running:
                        self.message_queue.put(("error", f"브라우저 오류: {str(e)}"))
                    break
                    
            except Exception as e:
                if self.is_running:
                    self.message_queue.put(("error", f"추출 오류: {str(e)}"))
                break
        
        # 정리
        self.message_queue.put(("connection", False))
        if driver:
            try:
                driver.quit()
            except:
                pass
            self.driver = None
        
        self.message_queue.put(("finished", None))
    
    def _find_element(self, driver, selector: str):
        """자막 요소 찾기"""
        selectors = [selector, "#viewSubtit .incont", "#viewSubtit", ".subtitle_area", "[id*='subtit']"]
        wait = WebDriverWait(driver, 10)
        
        for sel in selectors:
            try:
                return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
            except:
                continue
        return None
    
    def _activate_subtitle(self, driver):
        """자막 활성화"""
        scripts = [
            "if (typeof layerSubtit === 'function') { layerSubtit(); return true; }",
            "document.querySelector('.btn_subtit')?.click(); return true;",
            "document.querySelector('#btnSubtit')?.click(); return true;",
            "document.querySelector('[onclick*=\"layerSubtit\"]')?.click(); return true;"
        ]
        
        for script in scripts:
            try:
                if driver.execute_script(script):
                    return True
                time.sleep(0.3)
            except:
                continue
        
        btn_selectors = ["button[onclick*='layerSubtit']", ".btn_subtit", "#btnSubtit"]
        for sel in btn_selectors:
            try:
                btn = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                btn.click()
                return True
            except:
                continue
        
        return False
    
    def _close_driver(self):
        """드라이버 종료"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
    
    # --------------------------------------------------------
    # 메시지 큐 처리
    # --------------------------------------------------------
    
    def _process_queue(self):
        """메시지 큐"""
        try:
            while True:
                msg_type, data = self.message_queue.get_nowait()
                
                if msg_type == "status":
                    self._update_status(data)
                elif msg_type == "connection":
                    self._update_connection(data)
                elif msg_type == "update":
                    self._update_display(data)
                elif msg_type == "error":
                    self._handle_error(data)
                elif msg_type == "finished":
                    self._handle_finished()
                elif msg_type == "progress_hide":
                    self._show_progress(False)
                elif msg_type == "reconnect":
                    self.stat_labels['reconnect'].config(text=str(data))
                elif msg_type == "memory_cleaned":
                    pass  # 조용히 처리
                    
        except queue.Empty:
            pass
        finally:
            if self.root.winfo_exists():
                self.root.after(50, self._process_queue)
    
    def _update_status(self, msg: str):
        try:
            self.status_label.config(text=str(msg)[:150])
        except:
            pass
    
    def _update_connection(self, connected: bool):
        colors = THEMES[self.current_theme]
        try:
            if connected:
                self.conn_indicator.config(fg=colors['success'])
            else:
                self.conn_indicator.config(fg=colors['error'] if self.is_running else colors['preview'])
        except:
            pass
    
    def _update_display(self, data: Dict):
        """화면 업데이트"""
        try:
            # 미리보기
            self.preview_text.config(state=tk.NORMAL)
            self.preview_text.delete('1.0', tk.END)
            if data.get('speaker'):
                self.preview_text.insert('1.0', f"[{data['speaker']}]\n")
            self.preview_text.insert(tk.END, data.get('current', ''))
            self.preview_text.config(state=tk.DISABLED)
            
            # 메인 텍스트
            self._refresh_main_text()
            
            # 화자 목록 업데이트
            speakers = self.accumulator.speaker_manager.get_all_speakers()
            self.speaker_listbox.delete(0, tk.END)
            for speaker, color in speakers.items():
                self.speaker_listbox.insert(tk.END, speaker)
            
        except Exception as e:
            print(f"Display error: {e}")
    
    def _refresh_main_text(self):
        """메인 텍스트 새로고침 (화자 색상 적용)"""
        self.subtitle_text.delete('1.0', tk.END)
        
        speaker_colors = self.accumulator.speaker_manager.get_all_speakers()
        color_list = SPEAKER_COLORS_DARK if self.current_theme == Theme.DARK else SPEAKER_COLORS_LIGHT
        speaker_to_tag = {}
        
        for i, speaker in enumerate(speaker_colors.keys()):
            tag_name = f'speaker_{i % len(color_list)}'
            speaker_to_tag[speaker] = tag_name
        
        # 확정된 문장들
        for i, sent in enumerate(self.accumulator.sentences):
            if i > 0:
                self.subtitle_text.insert(tk.END, '\n\n')
            
            if sent['speaker'] and self.speaker_colors_var.get():
                tag = speaker_to_tag.get(sent['speaker'], 'speaker_0')
                self.subtitle_text.insert(tk.END, f"[{sent['speaker']}] ", tag)
            elif sent['speaker']:
                self.subtitle_text.insert(tk.END, f"[{sent['speaker']}] ")
            
            self.subtitle_text.insert(tk.END, sent['text'])
        
        # 현재 진행 중인 문장
        if self.accumulator.current_sentence:
            if self.accumulator.sentences:
                self.subtitle_text.insert(tk.END, '\n\n')
            
            if self.accumulator.current_speaker and self.speaker_colors_var.get():
                tag = speaker_to_tag.get(self.accumulator.current_speaker, 'speaker_0')
                self.subtitle_text.insert(tk.END, f"[{self.accumulator.current_speaker}] ", tag)
            elif self.accumulator.current_speaker:
                self.subtitle_text.insert(tk.END, f"[{self.accumulator.current_speaker}] ")
            
            self.subtitle_text.insert(tk.END, self.accumulator.current_sentence, 'preview')
        
        if self.auto_scroll_var.get():
            self.subtitle_text.see(tk.END)
    
    def _handle_error(self, msg: str):
        self._update_status(f"오류: {msg[:100]}")
        self._show_progress(False)
        messagebox.showerror("오류", msg)
        self._reset_ui()
    
    def _handle_finished(self):
        self._reset_ui()
        stats = self.accumulator.get_stats()
        self._update_status(f"완료 - {stats['total_sentences']}문장, {stats['total_chars']}자")
    
    def _reset_ui(self):
        self.is_running = False
        self.is_paused = False
        self._update_ui_state()
        self._show_progress(False)
    
    def _update_ui_state(self):
        try:
            if self.is_running:
                self.start_btn.config(state=tk.DISABLED)
                self.pause_btn.config(state=tk.NORMAL)
                self.stop_btn.config(state=tk.NORMAL)
                self.url_combo.config(state=tk.DISABLED)
                self.selector_combo.config(state=tk.DISABLED)
            else:
                self.start_btn.config(state=tk.NORMAL)
                self.pause_btn.config(state=tk.DISABLED, text="⏸ 일시정지")
                self.stop_btn.config(state=tk.DISABLED)
                self.url_combo.config(state=tk.NORMAL)
                self.selector_combo.config(state=tk.NORMAL)
        except:
            pass
    
    def _show_progress(self, show: bool):
        try:
            if show:
                self.progress.pack(side=tk.RIGHT)
                self.progress.start(10)
            else:
                self.progress.stop()
                self.progress.pack_forget()
        except:
            pass
    
    # --------------------------------------------------------
    # 통계 및 메모리
    # --------------------------------------------------------
    
    def _update_stats(self):
        """통계 업데이트"""
        try:
            if self.start_time:
                elapsed = int(time.time() - self.start_time)
                hrs, rem = divmod(elapsed, 3600)
                mins, secs = divmod(rem, 60)
                time_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"
            else:
                time_str = "--:--:--"
            
            stats = self.accumulator.get_stats()
            
            self.stat_labels['time'].config(text=time_str)
            self.stat_labels['chars'].config(text=f"{stats['total_chars']:,}")
            self.stat_labels['lines'].config(text=f"{stats['total_sentences']}")
            self.stat_labels['speakers'].config(text=f"{len(stats['speakers'])}")
            self.stat_labels['filtered'].config(text=f"{stats['filtered_duplicates']}")
            
            if self.is_running:
                self.root.after(1000, self._update_stats)
        except:
            pass
    
    def _start_memory_monitor(self):
        """메모리 모니터 시작"""
        def update():
            try:
                import psutil
                process = psutil.Process()
                mem_mb = process.memory_info().rss / 1024 / 1024
                self.memory_label.config(text=f"메모리: {mem_mb:.0f}MB")
            except:
                pass
            
            if self.root.winfo_exists():
                self.memory_check_timer = self.root.after(5000, update)
        
        update()
    
    def _update_mode_label(self):
        """모드 라벨 업데이트"""
        modes = []
        if self.headless_var.get():
            modes.append("헤드리스")
        if self.realtime_save_var.get():
            modes.append("실시간저장")
        if self.auto_reconnect_var.get():
            modes.append("자동재연결")
        
        self.mode_label.config(text=" | ".join(modes) if modes else "")
    
    def _on_config_change(self):
        """설정 변경"""
        self.config['headless'] = self.headless_var.get()
        self.config['auto_reconnect'] = self.auto_reconnect_var.get()
        self.config['realtime_save'] = self.realtime_save_var.get()
        self.config['show_speaker_colors'] = self.speaker_colors_var.get()
        self.config['auto_punctuation'] = self.auto_punct_var.get()
        self.config['filter_duplicates'] = self.filter_dup_var.get()
        self.config['filter_noise'] = self.filter_noise_var.get()
        
        self._save_config()
        self._update_mode_label()
        
        # 화자 색상 변경 시 새로고침
        if hasattr(self, 'accumulator') and self.accumulator.sentences:
            self._refresh_main_text()
    
    # --------------------------------------------------------
    # 검색
    # --------------------------------------------------------
    
    def _search(self):
        query = self.search_entry.get().strip()
        
        self.subtitle_text.tag_remove('highlight', '1.0', tk.END)
        self.subtitle_text.tag_remove('current', '1.0', tk.END)
        self.search_matches = []
        self.search_idx = 0
        
        if not query:
            self.search_label.config(text="")
            return
        
        start = '1.0'
        while True:
            pos = self.subtitle_text.search(query, start, tk.END, nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(query)}c"
            self.search_matches.append((pos, end))
            self.subtitle_text.tag_add('highlight', pos, end)
            start = end
        
        count = len(self.search_matches)
        if count > 0:
            self.search_label.config(text=f"{count}개")
            self._highlight_search()
        else:
            self.search_label.config(text="없음")
    
    def _nav_search(self, direction: int):
        if not hasattr(self, 'search_matches') or not self.search_matches:
            return
        self.search_idx = (self.search_idx + direction) % len(self.search_matches)
        self._highlight_search()
    
    def _highlight_search(self):
        if not self.search_matches:
            return
        self.subtitle_text.tag_remove('current', '1.0', tk.END)
        pos, end = self.search_matches[self.search_idx]
        self.subtitle_text.tag_add('current', pos, end)
        self.subtitle_text.see(pos)
        self.search_label.config(text=f"{self.search_idx + 1}/{len(self.search_matches)}")
    
    # --------------------------------------------------------
    # 파일 저장
    # --------------------------------------------------------
    
    def _save_txt(self):
        text = self.accumulator._build_full_text()
        
        if not text:
            messagebox.showwarning("알림", "저장할 내용이 없습니다.")
            return
        
        try:
            default = f"국회자막_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            
            path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                initialfile=default,
                filetypes=[("텍스트 파일", "*.txt"), ("모든 파일", "*.*")]
            )
            
            if not path:
                return
            
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
            
            messagebox.showinfo("저장 완료", f"저장되었습니다.\n\n파일: {path}")
            self._update_status(f"저장: {path}")
        except Exception as e:
            messagebox.showerror("오류", f"저장 실패: {str(e)}")
    
    def _copy_clipboard(self):
        text = self.accumulator._build_full_text()
        
        if not text:
            messagebox.showwarning("알림", "복사할 내용이 없습니다.")
            return
        
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._update_status(f"클립보드 복사됨 ({len(text):,}자)")
        except Exception as e:
            messagebox.showerror("오류", f"복사 실패: {str(e)}")
    
    def _clear_all(self):
        if not self.accumulator.sentences and not self.accumulator.current_sentence:
            return
        
        if messagebox.askyesno("확인", "모든 내용을 삭제하시겠습니까?"):
            self.accumulator.reset()
            self.subtitle_text.delete('1.0', tk.END)
            self.speaker_listbox.delete(0, tk.END)
            self._update_status("내용 삭제됨")
    
    def _open_realtime_folder(self):
        """실시간 저장 폴더 열기"""
        folder = Path(self.REALTIME_DIR).absolute()
        folder.mkdir(exist_ok=True)
        
        try:
            if sys.platform == 'win32':
                os.startfile(folder)
            elif sys.platform == 'darwin':
                os.system(f'open "{folder}"')
            else:
                os.system(f'xdg-open "{folder}"')
        except:
            messagebox.showinfo("폴더 경로", str(folder))
    
    # --------------------------------------------------------
    # UI 유틸
    # --------------------------------------------------------
    
    def _toggle_theme(self):
        self.current_theme = Theme.LIGHT if self.current_theme == Theme.DARK else Theme.DARK
        self._apply_theme()
        self._refresh_main_text()
        self._update_status(f"테마: {self.current_theme.value}")
    
    def _font_size(self, delta: int):
        self.font_size = max(8, min(24, self.font_size + delta))
        self.subtitle_text.configure(font=("맑은 고딕", self.font_size))
        self._setup_tags()
        self._update_status(f"글자 크기: {self.font_size}pt")
    
    def _show_speakers(self):
        """화자 목록"""
        speakers = self.accumulator.speaker_manager.get_all_speakers()
        if not speakers:
            messagebox.showinfo("화자 목록", "감지된 화자가 없습니다.")
            return
        
        text = "감지된 화자 목록:\n\n"
        for speaker, color in speakers.items():
            text += f"• {speaker}\n"
        
        messagebox.showinfo("화자 목록", text)
    
    def _show_shortcuts(self):
        text = """
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
        """
        messagebox.showinfo("단축키", text.strip())
    
    def _show_about(self):
        text = f"""
국회 의사중계 자막 추출기 v{self.VERSION}

주요 기능:
• 단어 단위 누적 (중복 제거)
• 문장부호 자동 교정
• 노이즈 필터링
• 화자 자동 감지 + 색상 구분
• 실시간 파일 저장
• URL 히스토리/즐겨찾기
• 자동 재연결
• 헤드리스 모드
• 메모리 최적화
        """
        messagebox.showinfo("정보", text.strip())
    
    def _on_closing(self):
        if self.is_running:
            if not messagebox.askokcancel("종료", "추출 중입니다. 종료하시겠습니까?"):
                return
        
        # 설정 저장
        self._save_config()
        
        # 실시간 저장 종료
        self.realtime_writer.close()
        
        # 타이머 취소
        if self.memory_check_timer:
            self.root.after_cancel(self.memory_check_timer)
        
        self.is_running = False
        self._close_driver()
        
        try:
            self.root.destroy()
        except:
            pass


# ============================================================
# 메인
# ============================================================

def main():
    try:
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass
        
        root = tk.Tk()
        app = SubtitleExtractor(root)
        root.mainloop()
        
    except Exception as e:
        print(f"오류: {e}")
        import traceback
        traceback.print_exc()
        messagebox.showerror("오류", f"프로그램 오류:\n{str(e)}")


if __name__ == '__main__':
    main()
