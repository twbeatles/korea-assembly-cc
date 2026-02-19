import queue
import threading

import pytest

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


class _ImmediateEvent:
    def is_set(self):
        return False

    def wait(self, timeout=None):
        return False


class _ReconnectEvent:
    def __init__(self):
        self._wait_calls = 0
        self._is_set = False

    def is_set(self):
        return self._is_set

    def wait(self, timeout=None):
        self._wait_calls += 1
        if self._wait_calls == 1:
            return False  # driver.get 이후 대기
        if self._wait_calls == 2:
            raise RuntimeError("disconnected")  # 복구 가능 오류 유도
        self._is_set = True
        return True


class _FakeDriver:
    def __init__(self):
        self.quit_calls = 0

    def get(self, _url):
        return None

    def execute_script(self, _script):
        return 1

    def quit(self):
        self.quit_calls += 1


class _FakeWebDriverWait:
    def __init__(self, _driver, _timeout):
        pass

    def until(self, _condition):
        return True


def _build_window(auto_reconnect_enabled: bool):
    win = MainWindow.__new__(MainWindow)
    win.message_queue = queue.Queue()
    win.stop_event = _ReconnectEvent()
    win.auto_reconnect_enabled = auto_reconnect_enabled
    win._detached_drivers = []
    win._detached_drivers_lock = threading.Lock()
    win.driver = None
    win._last_subtitle_frame_path = ()
    return win


def test_activate_subtitle_stops_after_first_success():
    class ToggleDriver:
        def __init__(self):
            self.calls = 0

        def execute_script(self, _script):
            self.calls += 1
            return self.calls == 1

    win = MainWindow.__new__(MainWindow)
    win.stop_event = _ImmediateEvent()

    driver = ToggleDriver()
    activated = MainWindow._activate_subtitle(win, driver)

    assert activated is True
    assert driver.calls == 1


def test_extraction_worker_respects_auto_reconnect_setting(monkeypatch):
    win = _build_window(auto_reconnect_enabled=False)
    delay_calls = []

    win._activate_subtitle = lambda _driver: True
    win._build_subtitle_selector_candidates = (
        lambda selector, extras=None: [selector]
    )
    win._inject_mutation_observer = lambda _driver, _selector: (False, ())
    win._read_subtitle_text_by_selectors = (
        lambda _driver, _selectors: ("", "", False)
    )
    win._find_subtitle_selector = lambda _driver: ""
    win._get_reconnect_delay = lambda attempt: delay_calls.append(attempt) or 0.0

    monkeypatch.setattr(mw_mod.webdriver, "Chrome", lambda options=None: _FakeDriver())
    monkeypatch.setattr(mw_mod, "WebDriverWait", _FakeWebDriverWait)

    MainWindow._extraction_worker(win, "https://example.com/live", "#viewSubtit", False)

    assert delay_calls == []
