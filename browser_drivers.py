# -*- coding: utf-8 -*-
"""
브라우저 드라이버 추상화 모듈
다중 브라우저 지원 (Chrome, Firefox, Edge)
"""

import logging
import sys
import os
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, List, Dict, Any
import shutil  # 브라우저 확인용 (상단 import로 이동)

logger = logging.getLogger("SubtitleExtractor")

# PyInstaller 환경 감지
def is_frozen():
    """PyInstaller로 패키징된 환경인지 확인"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


class BrowserType(Enum):
    """지원되는 브라우저 종류"""
    # Selenium 기반
    CHROME = "chrome"
    FIREFOX = "firefox"
    EDGE = "edge"
    # Playwright 기반
    PLAYWRIGHT_CHROMIUM = "playwright_chromium"
    PLAYWRIGHT_FIREFOX = "playwright_firefox"
    PLAYWRIGHT_WEBKIT = "playwright_webkit"
    
    @classmethod
    def from_string(cls, name: str) -> 'BrowserType':
        """문자열에서 BrowserType 변환"""
        name_lower = name.lower()
        for browser in cls:
            if browser.value == name_lower:
                return browser
        return cls.CHROME  # 기본값
    
    @classmethod
    def is_playwright(cls, browser_type: 'BrowserType') -> bool:
        """Playwright 기반 브라우저인지 확인"""
        return browser_type.value.startswith('playwright_')


class BaseBrowserDriver(ABC):
    """브라우저 드라이버 추상 클래스"""
    
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.driver = None
        self._browser_type: BrowserType = BrowserType.CHROME
    
    @property
    def browser_type(self) -> BrowserType:
        return self._browser_type
    
    @abstractmethod
    def create_driver(self) -> Any:
        """WebDriver 인스턴스 생성"""
        pass
    
    @abstractmethod
    def get_options(self) -> Any:
        """브라우저 옵션 객체 반환"""
        pass
    
    def get(self, url: str) -> None:
        """URL로 이동"""
        if self.driver:
            self.driver.get(url)
    
    def find_element(self, by, value):
        """요소 찾기"""
        if self.driver:
            return self.driver.find_element(by, value)
        return None
    
    def find_elements(self, by, value):
        """여러 요소 찾기"""
        if self.driver:
            return self.driver.find_elements(by, value)
        return []
    
    def execute_script(self, script: str, *args):
        """JavaScript 실행"""
        if self.driver:
            return self.driver.execute_script(script, *args)
        return None
    
    def quit(self) -> None:
        """브라우저 종료"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.debug(f"브라우저 종료 중 오류: {e}")
            finally:
                self.driver = None
    
    def is_alive(self) -> bool:
        """브라우저가 살아있는지 확인"""
        if not self.driver:
            return False
        try:
            _ = self.driver.title
            return True
        except Exception:
            return False


class ChromeDriver(BaseBrowserDriver):
    """Chrome 브라우저 드라이버"""
    
    def __init__(self, headless: bool = False):
        super().__init__(headless)
        self._browser_type = BrowserType.CHROME
    
    def get_options(self):
        """Chrome 옵션 생성"""
        from selenium.webdriver.chrome.options import Options
        
        options = Options()
        options.add_argument("--log-level=3")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        if self.headless:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1280,720")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-setuid-sandbox")
            options.add_argument("--remote-debugging-port=9222")
            options.add_argument("--enable-javascript")
        
        return options
    
    def create_driver(self):
        """Chrome WebDriver 생성"""
        from selenium import webdriver
        
        options = self.get_options()
        self.driver = webdriver.Chrome(options=options)
        return self.driver


class FirefoxDriver(BaseBrowserDriver):
    """Firefox 브라우저 드라이버"""
    
    def __init__(self, headless: bool = False):
        super().__init__(headless)
        self._browser_type = BrowserType.FIREFOX
    
    def get_options(self):
        """Firefox 옵션 생성"""
        from selenium.webdriver.firefox.options import Options
        
        options = Options()
        
        if self.headless:
            options.add_argument("--headless")
            options.add_argument("--width=1280")
            options.add_argument("--height=720")
        
        # Firefox 로그 레벨 설정
        options.set_preference("devtools.console.stdout.content", False)
        
        return options
    
    def create_driver(self):
        """Firefox WebDriver 생성"""
        from selenium import webdriver
        
        options = self.get_options()
        self.driver = webdriver.Firefox(options=options)
        return self.driver


class EdgeDriver(BaseBrowserDriver):
    """Edge 브라우저 드라이버"""
    
    def __init__(self, headless: bool = False):
        super().__init__(headless)
        self._browser_type = BrowserType.EDGE
    
    def get_options(self):
        """Edge 옵션 생성"""
        from selenium.webdriver.edge.options import Options
        
        options = Options()
        options.add_argument("--log-level=3")
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        if self.headless:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1280,720")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
        
        return options
    
    def create_driver(self):
        """Edge WebDriver 생성"""
        from selenium import webdriver
        
        options = self.get_options()
        self.driver = webdriver.Edge(options=options)
        return self.driver


# ============================================================
# Playwright 기반 드라이버
# ============================================================

class PlaywrightDriver(BaseBrowserDriver):
    """Playwright 기반 브라우저 드라이버 (공통 베이스)"""
    
    def __init__(self, headless: bool = False):
        super().__init__(headless)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
    
    def get_options(self) -> dict:
        """Playwright 옵션 반환"""
        return {
            'headless': self.headless,
            'args': ['--disable-blink-features=AutomationControlled'],
        }
    
    @abstractmethod
    def _get_browser_launcher(self):
        """브라우저 런처 반환 (chromium, firefox, webkit)"""
        pass
    
    def create_driver(self):
        """Playwright 브라우저 생성"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError(
                "Playwright가 설치되지 않았습니다.\n"
                "설치: pip install playwright\n"
                "브라우저 설치: playwright install"
            )
        
        self._playwright = sync_playwright().start()
        launcher = self._get_browser_launcher()
        
        options = self.get_options()
        self._browser = launcher.launch(
            headless=options['headless'],
            args=options.get('args', [])
        )
        self._context = self._browser.new_context(
            viewport={'width': 1280, 'height': 720}
        )
        self._page = self._context.new_page()
        
        # Selenium 호환 래퍼 설정
        self.driver = PlaywrightSeleniumWrapper(self._page)
        return self.driver
    
    def get(self, url: str) -> None:
        """URL로 이동"""
        if self._page:
            self._page.goto(url, wait_until='domcontentloaded')
    
    def find_element(self, by, value):
        """요소 찾기 (Selenium 형식 지원)"""
        if self._page:
            selector = self._convert_selector(by, value)
            try:
                element = self._page.query_selector(selector)
                if element:
                    return PlaywrightElementWrapper(element)
            except Exception:
                pass
        return None
    
    def find_elements(self, by, value):
        """여러 요소 찾기"""
        if self._page:
            selector = self._convert_selector(by, value)
            try:
                elements = self._page.query_selector_all(selector)
                return [PlaywrightElementWrapper(e) for e in elements]
            except Exception:
                pass
        return []
    
    def execute_script(self, script: str, *args):
        """JavaScript 실행"""
        if self._page:
            try:
                return self._page.evaluate(script, *args) if args else self._page.evaluate(script)
            except Exception:
                pass
        return None
    
    @staticmethod
    def _convert_by_to_selector(by, value) -> str:
        """
        Selenium By를 Playwright 셀렉터로 변환하는 공통 함수
        PlaywrightDriver와 PlaywrightSeleniumWrapper 모두에서 사용
        """
        by_str = str(by).lower() if not isinstance(by, str) else by.lower()
        
        if 'css' in by_str or by_str == 'css selector':
            return value
        elif 'id' in by_str:
            return f'#{value}'
        elif 'class' in by_str:
            return f'.{value}'
        elif 'xpath' in by_str:
            return f'xpath={value}'
        elif 'tag' in by_str:
            return value
        return value  # 기본: CSS 셀렉터로 처리
    
    def _convert_selector(self, by, value) -> str:
        """Selenium By를 Playwright 셀렉터로 변환"""
        return self._convert_by_to_selector(by, value)

    
    def quit(self) -> None:
        """브라우저 종료"""
        try:
            if self._page:
                self._page.close()
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.debug(f"Playwright 종료 중 오류: {e}")
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
            self.driver = None
    
    def is_alive(self) -> bool:
        """브라우저가 살아있는지 확인"""
        if not self._page:
            return False
        try:
            _ = self._page.title()
            return True
        except Exception:
            return False


class PlaywrightSeleniumWrapper:
    """Playwright Page를 Selenium WebDriver처럼 사용할 수 있게 하는 래퍼"""
    
    def __init__(self, page):
        self._page = page
    
    @property
    def title(self):
        return self._page.title()
    
    def get(self, url):
        self._page.goto(url)
    
    def find_element(self, by, value):
        # 공통 셀렉터 변환 로직 사용 (중복 코드 제거)
        selector = PlaywrightDriver._convert_by_to_selector(by, value)
        
        element = self._page.query_selector(selector)
        if element:
            return PlaywrightElementWrapper(element)
        raise Exception(f"Element not found: {selector}")
    
    def find_elements(self, by, value):
        # 공통 셀렉터 변환 로직 사용 (중복 코드 제거)
        selector = PlaywrightDriver._convert_by_to_selector(by, value)
        
        elements = self._page.query_selector_all(selector)
        return [PlaywrightElementWrapper(e) for e in elements]
    
    def execute_script(self, script, *args):
        return self._page.evaluate(script, *args) if args else self._page.evaluate(script)
    
    def quit(self):
        pass  # 상위에서 처리


class PlaywrightElementWrapper:
    """Playwright Element를 Selenium WebElement처럼 사용할 수 있게 하는 래퍼"""
    
    def __init__(self, element):
        self._element = element
    
    @property
    def text(self) -> str:
        try:
            return self._element.text_content() or ""
        except Exception:
            return ""
    
    def click(self):
        self._element.click()
    
    def send_keys(self, text):
        self._element.fill(text)
    
    def get_attribute(self, name):
        return self._element.get_attribute(name)


class PlaywrightChromiumDriver(PlaywrightDriver):
    """Playwright Chromium 드라이버"""
    
    def __init__(self, headless: bool = False):
        super().__init__(headless)
        self._browser_type = BrowserType.PLAYWRIGHT_CHROMIUM
    
    def _get_browser_launcher(self):
        return self._playwright.chromium


class PlaywrightFirefoxDriver(PlaywrightDriver):
    """Playwright Firefox 드라이버"""
    
    def __init__(self, headless: bool = False):
        super().__init__(headless)
        self._browser_type = BrowserType.PLAYWRIGHT_FIREFOX
    
    def _get_browser_launcher(self):
        return self._playwright.firefox


class PlaywrightWebKitDriver(PlaywrightDriver):
    """Playwright WebKit (Safari) 드라이버"""
    
    def __init__(self, headless: bool = False):
        super().__init__(headless)
        self._browser_type = BrowserType.PLAYWRIGHT_WEBKIT
    
    def _get_browser_launcher(self):
        return self._playwright.webkit


# ============================================================
# 브라우저 팩토리
# ============================================================

class BrowserFactory:
    """브라우저 드라이버 팩토리"""
    
    # 브라우저 타입별 드라이버 클래스 매핑
    _driver_classes: Dict[BrowserType, type] = {
        # Selenium 기반
        BrowserType.CHROME: ChromeDriver,
        BrowserType.FIREFOX: FirefoxDriver,
        BrowserType.EDGE: EdgeDriver,
        # Playwright 기반
        BrowserType.PLAYWRIGHT_CHROMIUM: PlaywrightChromiumDriver,
        BrowserType.PLAYWRIGHT_FIREFOX: PlaywrightFirefoxDriver,
        BrowserType.PLAYWRIGHT_WEBKIT: PlaywrightWebKitDriver,
    }
    
    # 브라우저 표시 이름
    BROWSER_NAMES: Dict[BrowserType, str] = {
        BrowserType.CHROME: "Chrome (Selenium)",
        BrowserType.FIREFOX: "Firefox (Selenium)",
        BrowserType.EDGE: "Edge (Selenium)",
        BrowserType.PLAYWRIGHT_CHROMIUM: "Chromium (Playwright)",
        BrowserType.PLAYWRIGHT_FIREFOX: "Firefox (Playwright)",
        BrowserType.PLAYWRIGHT_WEBKIT: "WebKit (Playwright)",
    }
    
    @classmethod
    def create(cls, browser_type: BrowserType, headless: bool = False) -> BaseBrowserDriver:
        """브라우저 드라이버 인스턴스 생성
        
        Args:
            browser_type: 브라우저 종류
            headless: 헤드리스 모드 여부
            
        Returns:
            BaseBrowserDriver 인스턴스
        """
        driver_class = cls._driver_classes.get(browser_type, ChromeDriver)
        return driver_class(headless=headless)
    
    @classmethod
    def get_available_browsers(cls) -> List[BrowserType]:
        """설치된 브라우저 목록 반환"""
        available = []
        
        # Selenium 브라우저
        if cls._check_chrome():
            available.append(BrowserType.CHROME)
        
        if cls._check_firefox():
            available.append(BrowserType.FIREFOX)
        
        if cls._check_edge():
            available.append(BrowserType.EDGE)
        
        # Playwright 브라우저
        if cls._check_playwright():
            available.append(BrowserType.PLAYWRIGHT_CHROMIUM)
            available.append(BrowserType.PLAYWRIGHT_FIREFOX)
            available.append(BrowserType.PLAYWRIGHT_WEBKIT)
        
        # 아무것도 없으면 기본 Chrome 반환
        if not available:
            available.append(BrowserType.CHROME)
        
        return available
    
    @classmethod
    def _check_chrome(cls) -> bool:
        """
        Chrome 설치 확인
        shutil, os, sys는 상단에서 import됨 (중복 import 제거)
        """
        if sys.platform == 'win32':
            paths = [
                os.path.expandvars(r'%PROGRAMFILES%\Google\Chrome\Application\chrome.exe'),
                os.path.expandvars(r'%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe'),
                os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
            ]
            for path in paths:
                if os.path.exists(path):
                    return True
        
        return shutil.which('chrome') is not None or shutil.which('google-chrome') is not None
    
    @classmethod
    def _check_firefox(cls) -> bool:
        """
        Firefox 설치 확인
        shutil, os, sys는 상단에서 import됨 (중복 import 제거)
        """
        if sys.platform == 'win32':
            paths = [
                os.path.expandvars(r'%PROGRAMFILES%\Mozilla Firefox\firefox.exe'),
                os.path.expandvars(r'%PROGRAMFILES(X86)%\Mozilla Firefox\firefox.exe'),
            ]
            for path in paths:
                if os.path.exists(path):
                    return True
        
        return shutil.which('firefox') is not None
    
    @classmethod
    def _check_edge(cls) -> bool:
        """
        Edge 설치 확인
        shutil, os, sys는 상단에서 import됨 (중복 import 제거)
        """
        if sys.platform == 'win32':
            paths = [
                os.path.expandvars(r'%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe'),
                os.path.expandvars(r'%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe'),
            ]
            for path in paths:
                if os.path.exists(path):
                    return True
        
        return shutil.which('msedge') is not None
    
    @classmethod
    def _check_playwright(cls) -> bool:
        """Playwright 사용 가능 여부 확인
        
        PyInstaller 환경에서는 Playwright가 제대로 작동하지 않을 수 있으므로
        제외합니다. Playwright는 Node.js 프로세스를 사용하며, 패키징된 환경에서는
        경로 문제로 실패할 수 있습니다.
        """
        # PyInstaller 환경에서는 Playwright 사용 불가
        if is_frozen():
            logger.debug("PyInstaller 환경 - Playwright 드라이버 사용 불가")
            return False
        
        try:
            import playwright
            # 실제 브라우저가 설치되어 있는지도 확인
            try:
                from playwright.sync_api import sync_playwright
                return True
            except Exception:
                return False
        except ImportError:
            return False
    
    @classmethod
    def get_browser_name(cls, browser_type: BrowserType) -> str:
        """브라우저 표시 이름 반환"""
        return cls.BROWSER_NAMES.get(browser_type, "Unknown")
    
    @classmethod
    def is_playwright_available(cls) -> bool:
        """Playwright 사용 가능 여부"""
        return cls._check_playwright()


# 테스트용
if __name__ == "__main__":
    print("사용 가능한 브라우저:")
    for browser in BrowserFactory.get_available_browsers():
        print(f"  - {BrowserFactory.get_browser_name(browser)}")
    
    print(f"\nPlaywright 설치됨: {BrowserFactory.is_playwright_available()}")

