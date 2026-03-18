import queue
import threading

import pytest
import ui.main_window_capture as capture_mod

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


class _StopAfterFirstWaitEvent:
    def __init__(self):
        self._wait_calls = 0
        self._is_set = False

    def is_set(self):
        return self._is_set

    def wait(self, timeout=None):
        self._wait_calls += 1
        if self._wait_calls >= 1:
            self._is_set = True
            return True
        return False


class _StopAfterSecondWaitEvent:
    def __init__(self):
        self._wait_calls = 0
        self._is_set = False

    def is_set(self):
        return self._is_set

    def wait(self, timeout=None):
        self._wait_calls += 1
        if self._wait_calls >= 2:
            self._is_set = True
            return True
        return False


class _StopAfterNWaitsEvent:
    def __init__(self, wait_limit):
        self._wait_calls = 0
        self._wait_limit = wait_limit
        self._is_set = False

    def is_set(self):
        return self._is_set

    def wait(self, timeout=None):
        self._wait_calls += 1
        if self._wait_calls >= self._wait_limit:
            self._is_set = True
            return True
        return False


class _ReconnectOnceEvent:
    def __init__(self):
        self._wait_calls = 0
        self._is_set = False

    def is_set(self):
        return self._is_set

    def wait(self, timeout=None):
        self._wait_calls += 1
        if self._wait_calls in (1, 2):
            return False
        if self._wait_calls == 3:
            raise RuntimeError("disconnected")
        if self._wait_calls in (4, 5):
            return False
        self._is_set = True
        return True


class _FakeDriver:
    def __init__(self):
        self.quit_calls = 0
        self.get_calls = []
        self.current_url = ""

    def get(self, url):
        self.get_calls.append(url)
        self.current_url = url
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


class _SwitchToStub:
    def default_content(self):
        return None


class _SmiWordCollectDriver:
    def __init__(self, rows):
        self.rows = rows
        self.switch_to = _SwitchToStub()

    def execute_script(self, _script, _selector):
        return self.rows


class _TextElement:
    def __init__(self, text):
        self.text = text


class _ElementTextDriver:
    def __init__(self, text):
        self.text = text
        self.switch_to = _SwitchToStub()

    def find_element(self, _by, _selector):
        return _TextElement(self.text)


def _build_window(auto_reconnect_enabled: bool, stop_event=None):
    win = MainWindow.__new__(MainWindow)
    win.message_queue = queue.Queue()
    win.stop_event = stop_event or _ReconnectEvent()
    win.auto_reconnect_enabled = auto_reconnect_enabled
    win._detached_drivers = []
    win._detached_drivers_lock = threading.Lock()
    win.driver = None
    win._last_subtitle_frame_path = ()
    return win


def _configure_basic_worker_stubs(win):
    win._activate_subtitle = lambda _driver: True
    win._build_subtitle_selector_candidates = (
        lambda selector, extras=None: [selector]
    )
    win._inject_mutation_observer = lambda _driver, _selector: (False, ())
    win._read_subtitle_probe_by_selectors = (
        lambda _driver, _selectors, preferred_frame_path=(), **_kwargs: {
            "text": "",
            "matched_selector": "",
            "found": False,
            "rows": [],
            "frame_path": preferred_frame_path,
        }
    )
    win._read_subtitle_text_by_selectors = (
        lambda _driver, _selectors: ("", "", False)
    )
    win._find_subtitle_selector = lambda _driver: ""


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

    _configure_basic_worker_stubs(win)
    win._get_reconnect_delay = lambda attempt: delay_calls.append(attempt) or 0.0

    monkeypatch.setattr(mw_mod.webdriver, "Chrome", lambda options=None: _FakeDriver())
    monkeypatch.setattr(mw_mod, "WebDriverWait", _FakeWebDriverWait)

    MainWindow._extraction_worker(win, "https://example.com/live", "#viewSubtit", False)

    assert delay_calls == []


def test_extraction_worker_detects_live_url_when_xcgcd_missing(monkeypatch):
    driver = _FakeDriver()
    win = _build_window(auto_reconnect_enabled=False)
    win.stop_event = _StopAfterFirstWaitEvent()
    _configure_basic_worker_stubs(win)

    original_url = "https://example.com/live?xcode=10"
    resolved_url = "https://example.com/live?xcode=10&xcgcd=DCM0000101234567890"
    detect_calls = []

    def fake_detect(_driver, url):
        detect_calls.append(url)
        return resolved_url

    win._detect_live_broadcast = fake_detect

    monkeypatch.setattr(mw_mod.webdriver, "Chrome", lambda options=None: driver)
    monkeypatch.setattr(mw_mod, "WebDriverWait", _FakeWebDriverWait)

    MainWindow._extraction_worker(win, original_url, "#viewSubtit", False)

    assert detect_calls[:2] == [original_url, resolved_url]
    assert driver.get_calls[:2] == [original_url, resolved_url]

    queued = []
    while not win.message_queue.empty():
        queued.append(win.message_queue.get_nowait())
    assert ("resolved_url", resolved_url) in queued


def test_extraction_worker_skips_live_detect_when_xcgcd_exists(monkeypatch):
    driver = _FakeDriver()
    win = _build_window(auto_reconnect_enabled=False)
    win.stop_event = _StopAfterFirstWaitEvent()
    _configure_basic_worker_stubs(win)

    url_with_xcgcd = "https://example.com/live?xcode=10&xcgcd=DCM0000101234567890"

    def should_not_call(*_args, **_kwargs):
        raise AssertionError("_detect_live_broadcast should not be called")

    win._detect_live_broadcast = should_not_call

    monkeypatch.setattr(mw_mod.webdriver, "Chrome", lambda options=None: driver)
    monkeypatch.setattr(mw_mod, "WebDriverWait", _FakeWebDriverWait)

    MainWindow._extraction_worker(win, url_with_xcgcd, "#viewSubtit", False)

    assert driver.get_calls == [url_with_xcgcd]

    queued = []
    while not win.message_queue.empty():
        queued.append(win.message_queue.get_nowait())
    assert not any(msg_type == "resolved_url" for msg_type, _ in queued)


def test_extraction_worker_reconnect_reuses_detected_url(monkeypatch):
    original_url = "https://example.com/live?xcode=25"
    detected_url = "https://example.com/live?xcode=25&xcgcd=DCM0000251234567890"

    win = _build_window(auto_reconnect_enabled=True, stop_event=_ReconnectOnceEvent())
    drivers = []
    detect_calls = []

    def create_driver(options=None):
        driver = _FakeDriver()
        drivers.append(driver)
        return driver

    def detect_live(_driver, input_url):
        detect_calls.append(input_url)
        return detected_url

    _configure_basic_worker_stubs(win)
    win._detect_live_broadcast = detect_live
    win._get_reconnect_delay = lambda attempt: 0.0

    monkeypatch.setattr(mw_mod.webdriver, "Chrome", create_driver)
    monkeypatch.setattr(mw_mod, "WebDriverWait", _FakeWebDriverWait)

    MainWindow._extraction_worker(win, original_url, "#viewSubtit", False)

    assert len(drivers) >= 2
    assert drivers[0].get_calls[:2] == [original_url, detected_url]
    assert drivers[1].get_calls[0] == detected_url
    assert detect_calls[0] == original_url
    assert detect_calls[1] == detected_url


def test_read_subtitle_text_collects_smi_word_window():
    rows = [
        {"id": "s1", "text": "첫 문장"},
        {"id": "s2", "text": "둘째 문장"},
        {"id": "s2_dup", "text": "둘째 문장"},
        {"id": "s3", "text": "셋째 문장"},
    ]
    driver = _SmiWordCollectDriver(rows)
    win = MainWindow.__new__(MainWindow)
    win._last_subtitle_frame_path = ()

    text, matched_selector, found = MainWindow._read_subtitle_text_by_selectors(
        win,
        driver,
        ["#viewSubtit .smi_word:last-child"],
    )

    assert found is True
    assert matched_selector == "#viewSubtit .smi_word:last-child"
    assert text == "첫 문장 둘째 문장 셋째 문장"


def test_read_subtitle_text_flattens_container_line_breaks():
    driver = _ElementTextDriver("첫 문장\n\n둘째 문장\n셋째 문장")
    win = MainWindow.__new__(MainWindow)
    win._last_subtitle_frame_path = ()

    text, matched_selector, found = MainWindow._read_subtitle_text_by_selectors(
        win,
        driver,
        ["#viewSubtit"],
    )

    assert found is True
    assert matched_selector == "#viewSubtit"
    assert text == "첫 문장 둘째 문장 셋째 문장"


def test_extraction_worker_uses_health_probe_when_observer_is_idle(monkeypatch):
    driver = _FakeDriver()
    win = _build_window(
        auto_reconnect_enabled=False,
        stop_event=_StopAfterNWaitsEvent(wait_limit=10),
    )
    _configure_basic_worker_stubs(win)

    time_values = iter(index * 0.25 for index in range(64))
    probe_calls = []
    frame_refresh_calls = []

    monkeypatch.setattr(capture_mod.time, "time", lambda: next(time_values))
    monkeypatch.setattr(mw_mod.webdriver, "Chrome", lambda options=None: driver)
    monkeypatch.setattr(mw_mod, "WebDriverWait", _FakeWebDriverWait)

    win._iter_frame_paths = lambda _driver, max_depth=3, max_frames=60: (
        frame_refresh_calls.append((max_depth, max_frames)) or []
    )
    win._inject_mutation_observer = lambda _driver, _selector: (True, ())
    win._collect_observer_changes = lambda _driver, _frame_path: []
    win._read_subtitle_probe_by_selectors = (
        lambda _driver, _selectors, preferred_frame_path=(), **_kwargs: (
            probe_calls.append(preferred_frame_path)
            or {
                "text": "",
                "matched_selector": "#viewSubtit",
                "found": True,
                "rows": [],
                "frame_path": preferred_frame_path,
                "source_mode": "observer",
            }
        )
    )

    MainWindow._extraction_worker(win, "https://example.com/live", "#viewSubtit", False)

    assert len(frame_refresh_calls) == 1
    assert len(probe_calls) == 3
