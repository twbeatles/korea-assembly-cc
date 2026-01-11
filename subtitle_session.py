# -*- coding: utf-8 -*-
"""
자막 추출 세션 관리 모듈
다중 세션 지원을 위한 독립적인 세션 클래스
"""

import threading
import queue
import time
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass, field

from browser_drivers import BrowserFactory, BrowserType, BaseBrowserDriver

logger = logging.getLogger("SubtitleExtractor")

# Selenium 관련 import (조건부 - Playwright 사용 시에도 호환성 유지)
try:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    By = None
    WebDriverWait = None
    EC = None
    NoSuchElementException = Exception
    StaleElementReferenceException = Exception


@dataclass
class SubtitleEntry:
    """자막 항목"""
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            'text': self.text,
            'timestamp': self.timestamp.isoformat(),
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'SubtitleEntry':
        """딕셔너리에서 생성"""
        entry = cls(data['text'])
        entry.timestamp = datetime.fromisoformat(data['timestamp'])
        if data.get('start_time'):
            entry.start_time = datetime.fromisoformat(data['start_time'])
        if data.get('end_time'):
            entry.end_time = datetime.fromisoformat(data['end_time'])
        return entry


class SubtitleSession:
    """단일 자막 추출 세션
    
    각 세션은 독립적인 브라우저 인스턴스와 자막 데이터를 가집니다.
    """
    
    # 세션 상태
    STATE_IDLE = "idle"
    STATE_STARTING = "starting"
    STATE_RUNNING = "running"
    STATE_STOPPING = "stopping"
    STATE_ERROR = "error"
    
    # 설정 상수
    SUBTITLE_FINALIZE_TIMEOUT = 2.0  # 자막 확정 타임아웃 (초)
    MONITOR_INTERVAL = 0.2  # 모니터링 간격 (초)
    BROWSER_RETRY_COUNT = 3  # 브라우저 재시도 횟수
    WORKER_THREAD_TIMEOUT = 3  # 워커 스레드 종료 대기 (초)
    ELEMENT_WAIT_TIMEOUT = 20  # 요소 대기 타임아웃 (초)
    
    def __init__(self, session_id: str, name: str = ""):
        self.session_id = session_id
        self.name = name or f"세션 {session_id[:8]}"
        
        # 설정
        self.url: str = ""
        self.selector: str = "#viewSubtit .incont"
        self.browser_type: BrowserType = BrowserType.CHROME
        self.headless: bool = False
        self.auto_scroll: bool = True
        self.realtime_save: bool = False
        
        # 상태
        self._state: str = self.STATE_IDLE
        self._state_lock = threading.Lock()
        self.stop_event = threading.Event()
        
        # 데이터
        self.subtitles: List[SubtitleEntry] = []
        self._subtitles_lock = threading.Lock()  # 자막 리스트 동기화
        self._realtime_file_lock = threading.Lock()  # 실시간 파일 쓰기 동기화
        self.last_subtitle: str = ""
        self.last_update_time: float = 0
        self.start_time: Optional[float] = None
        
        # 브라우저
        self.browser: Optional[BaseBrowserDriver] = None
        self.worker_thread: Optional[threading.Thread] = None
        
        # 메시지 큐 (UI 스레드와 통신)
        self.message_queue: queue.Queue = queue.Queue()
        
        # 콜백
        self.on_subtitle_update: Optional[Callable[[str], None]] = None
        self.on_subtitle_finalized: Optional[Callable[[SubtitleEntry], None]] = None
        self.on_state_changed: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        
        # 실시간 저장
        self.realtime_file = None
    
    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state
    
    @state.setter
    def state(self, value: str):
        with self._state_lock:
            old_state = self._state
            self._state = value
        if old_state != value and self.on_state_changed:
            self.on_state_changed(value)
    
    @property
    def is_running(self) -> bool:
        return self.state in (self.STATE_STARTING, self.STATE_RUNNING)
    
    def start(self) -> bool:
        """추출 시작"""
        # 원자적 상태 체크 및 변경 (경쟁 조건 방지)
        with self._state_lock:
            if self._state in (self.STATE_STARTING, self.STATE_RUNNING):
                return False
            self._state = self.STATE_STARTING
        
        if not self.url or not self.selector:
            self.state = self.STATE_IDLE
            self.message_queue.put(("error", "URL과 선택자를 입력하세요."))
            return False
        
        # 초기화
        with self._subtitles_lock:
            self.subtitles = []
        self.last_subtitle = ""
        self.start_time = time.time()
        self.stop_event.clear()
        
        # 실시간 저장 설정
        if self.realtime_save:
            try:
                Path("realtime_output").mkdir(exist_ok=True)
                filename = f"realtime_output/{self.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                self.realtime_file = open(filename, 'w', encoding='utf-8')
            except Exception as e:
                logger.error(f"실시간 저장 파일 생성 오류: {e}")
                self.realtime_file = None  # 명시적 None 할당
        
        # 워커 스레드 시작
        self.worker_thread = threading.Thread(
            target=self._extraction_worker,
            daemon=True
        )
        self.worker_thread.start()
        
        return True
    
    def stop(self) -> None:
        """추출 중지"""
        # 원자적 상태 체크 (경쟁 조건 방지)
        with self._state_lock:
            if self._state not in (self.STATE_STARTING, self.STATE_RUNNING):
                return
            self._state = self.STATE_STOPPING
        
        self.stop_event.set()
        
        # 워커 스레드 종료 대기
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=self.WORKER_THREAD_TIMEOUT)
            if self.worker_thread.is_alive():
                logger.warning(f"워커 스레드가 여전히 실행 중: {self.session_id}")
        
        # 마지막 자막 저장
        if self.last_subtitle:
            self._finalize_subtitle(self.last_subtitle)
            self.last_subtitle = ""
        
        # 실시간 저장 종료 (finally 패턴으로 확실히 닫기)
        try:
            if self.realtime_file:
                self.realtime_file.close()
        except Exception as e:
            logger.debug(f"실시간 저장 파일 닫기 오류: {e}")
        finally:
            self.realtime_file = None
        
        # 브라우저 종료 (finally 패턴으로 확실히 정리)
        try:
            if self.browser:
                self.browser.quit()
        except Exception as e:
            logger.debug(f"브라우저 종료 중 오류: {e}")
        finally:
            self.browser = None
        
        self.state = self.STATE_IDLE
    
    def _extraction_worker(self):
        """자막 추출 워커 스레드"""
        try:
            # 브라우저 생성
            self.message_queue.put(("status", f"{BrowserFactory.get_browser_name(self.browser_type)} 시작 중..."))
            self.browser = BrowserFactory.create(self.browser_type, self.headless)
            
            # 재시도 로직
            for attempt in range(self.BROWSER_RETRY_COUNT):
                try:
                    self.browser.create_driver()
                    self.message_queue.put(("status", "브라우저 시작 완료"))
                    break
                except Exception as e:
                    if attempt < self.BROWSER_RETRY_COUNT - 1:
                        self.message_queue.put(("status", f"재시도 ({attempt+2}/{self.BROWSER_RETRY_COUNT})..."))
                        time.sleep(2)
                    else:
                        self.message_queue.put(("error", f"브라우저 오류 ({self.BROWSER_RETRY_COUNT}회 시도 실패): {e}"))
                        return
            
            # 페이지 로드
            self.message_queue.put(("status", "페이지 로딩 중..."))
            self.browser.get(self.url)
            time.sleep(5)
            
            # 자막 활성화
            self.message_queue.put(("status", "AI 자막 활성화 중..."))
            self._activate_subtitle()
            
            # 자막 요소 확인 (Selenium/Playwright 호환성 처리)
            self.message_queue.put(("status", "자막 요소 검색 중..."))
            
            found = False
            selectors_to_try = [self.selector, "#viewSubtit .incont", "#viewSubtit", ".subtitle_area"]
            
            # Selenium 사용 시 WebDriverWait 활용
            if SELENIUM_AVAILABLE and WebDriverWait is not None and not BrowserType.is_playwright(self.browser_type):
                wait = WebDriverWait(self.browser.driver, self.ELEMENT_WAIT_TIMEOUT)
                for sel in selectors_to_try:
                    try:
                        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                        self.selector = sel
                        self.message_queue.put(("status", f"자막 요소 찾음: {sel}"))
                        found = True
                        break
                    except Exception:
                        continue
            else:
                # Playwright 또는 Selenium 미설치 시 직접 대기
                for sel in selectors_to_try:
                    for _ in range(self.ELEMENT_WAIT_TIMEOUT):  # 대기
                        try:
                            element = self.browser.find_element(By.CSS_SELECTOR, sel) if By else self.browser.find_element("css selector", sel)
                            if element:
                                self.selector = sel
                                self.message_queue.put(("status", f"자막 요소 찾음: {sel}"))
                                found = True
                                break
                        except Exception:
                            pass
                        time.sleep(1)
                    if found:
                        break
            
            if not found:
                self.message_queue.put(("error", "자막 요소를 찾을 수 없습니다."))
                return
            
            self.state = self.STATE_RUNNING
            self.message_queue.put(("status", "자막 모니터링 중"))
            
            # 모니터링 루프
            last_check = time.time()
            while not self.stop_event.is_set():
                try:
                    now = time.time()
                    if now - last_check >= self.MONITOR_INTERVAL:
                        try:
                            # Selenium/Playwright 호환성 처리
                            if By is not None:
                                text = self.browser.find_element(By.CSS_SELECTOR, self.selector).text.strip()
                            else:
                                # Playwright 또는 Selenium 미설치 환경
                                text = self.browser.find_element("css selector", self.selector).text.strip()
                        except (NoSuchElementException, StaleElementReferenceException):
                            text = ""
                        except AttributeError:
                            # find_element 결과가 None인 경우
                            text = ""
                        except Exception:
                            text = ""
                        
                        text = self._clean_text(text)
                        if text and text != self.last_subtitle:
                            self.last_update_time = now
                            self.last_subtitle = text
                            self.message_queue.put(("preview", text))
                        
                        # 타임아웃 경과 시 확정
                        if self.last_subtitle and (now - self.last_update_time) >= self.SUBTITLE_FINALIZE_TIMEOUT:
                            self._finalize_subtitle(self.last_subtitle)
                            self.last_subtitle = ""
                        
                        last_check = now
                    
                    self.stop_event.wait(timeout=0.05)
                except Exception as e:
                    if not self.stop_event.is_set():
                        logger.warning(f"모니터링 중 오류: {e}")
                    time.sleep(0.5)
        
        except Exception as e:
            if not self.stop_event.is_set():
                self.message_queue.put(("error", str(e)))
                self.state = self.STATE_ERROR
        
        finally:
            if self.browser:
                self.browser.quit()
                self.browser = None
            self.message_queue.put(("finished", ""))
    
    def _activate_subtitle(self) -> bool:
        """자막 레이어 활성화"""
        activation_scripts = [
            "if(typeof layerSubtit==='function'){layerSubtit(); return true;} return false;",
            "var btn=document.querySelector('.btn_subtit'); if(btn){btn.click(); return true;} return false;",
            "var btn=document.querySelector('#btnSubtit'); if(btn){btn.click(); return true;} return false;",
            "var layer=document.querySelector('#viewSubtit'); if(layer){layer.style.display='block'; return true;} return false;",
        ]
        
        activated = False
        for script in activation_scripts:
            try:
                result = self.browser.execute_script(script)
                if result:
                    activated = True
                time.sleep(0.5)
            except Exception:
                pass
        
        time.sleep(2.0)
        return activated
    
    def _clean_text(self, text: str) -> str:
        """자막 텍스트 정리"""
        if not text:
            return ""
        text = re.sub(r'\b\d{4}년\b', '', text)
        text = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def _finalize_subtitle(self, text: str) -> None:
        """자막 확정 - 스레드 안전하게 처리"""
        if not text:
            return
        
        entry = None  # 콜백용 변수 (lock 외부에서 사용)
        
        # 스레드 안전한 자막 리스트 접근
        with self._subtitles_lock:
            # 중복/겹침 처리
            if self.subtitles:
                last_text = self.subtitles[-1].text
                if text.startswith(last_text):
                    new_part = text[len(last_text):].strip()
                    if new_part:
                        self.subtitles[-1].text = text
                        self.subtitles[-1].end_time = datetime.now()
                        self._write_realtime(f"+{new_part}\n")
                    return
            
            # 새 자막
            entry = SubtitleEntry(text)
            entry.start_time = datetime.now()
            entry.end_time = datetime.now()
            self.subtitles.append(entry)
        
        # 콜백 (lock 외부에서 실행 - entry가 None이 아닐 때만)
        if entry:
            if self.on_subtitle_finalized:
                self.on_subtitle_finalized(entry)
            
            self.message_queue.put(("finalized", entry))
            
            # 실시간 저장
            timestamp = entry.timestamp.strftime('%H:%M:%S')
            self._write_realtime(f"[{timestamp}] {text}\n")
    
    def _write_realtime(self, text: str) -> None:
        """스레드 안전한 실시간 파일 쓰기"""
        with self._realtime_file_lock:
            if self.realtime_file:
                try:
                    self.realtime_file.write(text)
                    self.realtime_file.flush()
                except Exception:
                    pass
    
    def get_stats(self) -> Dict[str, Any]:
        """통계 정보 반환 - 스레드 안전하게 단일 순회로 최적화"""
        elapsed = int(time.time() - self.start_time) if self.start_time else 0
        
        # 스레드 안전한 접근으로 한 번의 순회로 모든 통계 계산
        total_chars = 0
        total_words = 0
        with self._subtitles_lock:
            subtitle_count = len(self.subtitles)
            for s in self.subtitles:
                total_chars += len(s.text)
                total_words += len(s.text.split())
        
        # ZeroDivisionError 방지
        cpm = int(total_chars / (elapsed / 60)) if elapsed > 0 else 0
        
        return {
            'elapsed': elapsed,
            'subtitle_count': subtitle_count,
            'char_count': total_chars,
            'word_count': total_words,
            'cpm': cpm,
        }
    
    def to_dict(self) -> dict:
        """세션 정보를 딕셔너리로 변환"""
        return {
            'session_id': self.session_id,
            'name': self.name,
            'url': self.url,
            'selector': self.selector,
            'browser_type': self.browser_type.value,
            'headless': self.headless,
            'subtitles': [s.to_dict() for s in self.subtitles],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'SubtitleSession':
        """딕셔너리에서 세션 생성"""
        session = cls(data['session_id'], data.get('name', ''))
        session.url = data.get('url', '')
        session.selector = data.get('selector', '#viewSubtit .incont')
        session.browser_type = BrowserType.from_string(data.get('browser_type', 'chrome'))
        session.headless = data.get('headless', False)
        session.subtitles = [SubtitleEntry.from_dict(s) for s in data.get('subtitles', [])]
        return session


class SessionManager:
    """다중 세션 관리자"""
    
    MAX_SESSIONS = 5  # 최대 동시 세션 수
    
    def __init__(self):
        self.sessions: Dict[str, SubtitleSession] = {}
        self._lock = threading.Lock()
    
    def create_session(self, name: str = "") -> SubtitleSession:
        """새 세션 생성"""
        import uuid
        
        with self._lock:
            if len(self.sessions) >= self.MAX_SESSIONS:
                raise RuntimeError(f"최대 세션 수({self.MAX_SESSIONS})에 도달했습니다.")
            
            session_id = str(uuid.uuid4())
            session = SubtitleSession(session_id, name or f"세션 {len(self.sessions) + 1}")
            self.sessions[session_id] = session
            return session
    
    def remove_session(self, session_id: str) -> bool:
        """세션 제거"""
        with self._lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                if session.is_running:
                    session.stop()
                del self.sessions[session_id]
                return True
            return False
    
    def get_session(self, session_id: str) -> Optional[SubtitleSession]:
        """세션 가져오기"""
        return self.sessions.get(session_id)
    
    def get_all_sessions(self) -> List[SubtitleSession]:
        """모든 세션 목록"""
        return list(self.sessions.values())
    
    def start_all(self) -> int:
        """모든 세션 시작"""
        count = 0
        for session in self.sessions.values():
            if not session.is_running and session.url:
                if session.start():
                    count += 1
        return count
    
    def stop_all(self) -> int:
        """모든 세션 중지"""
        count = 0
        for session in self.sessions.values():
            if session.is_running:
                session.stop()
                count += 1
        return count
    
    def get_running_count(self) -> int:
        """실행 중인 세션 수"""
        return sum(1 for s in self.sessions.values() if s.is_running)
    
    def search_all(self, query: str) -> List[tuple]:
        """모든 세션에서 검색
        
        Returns:
            [(session_name, subtitle_index, SubtitleEntry), ...]
        """
        results = []
        query_lower = query.lower()
        
        for session in self.sessions.values():
            for i, entry in enumerate(session.subtitles):
                if query_lower in entry.text.lower():
                    results.append((session.name, i, entry))
        
        return results


# 테스트용
if __name__ == "__main__":
    manager = SessionManager()
    session = manager.create_session("테스트 세션")
    print(f"세션 생성됨: {session.name} ({session.session_id})")
    print(f"전체 세션 수: {len(manager.get_all_sessions())}")
