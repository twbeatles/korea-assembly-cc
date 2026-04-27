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


class _StopAfterSixWaitsEvent:
    def __init__(self):
        self._wait_calls = 0
        self._is_set = False

    def is_set(self):
        return self._is_set

    def wait(self, timeout=None):
        self._wait_calls += 1
        if self._wait_calls >= 6:
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


class _ProbeFailureDriver:
    def __init__(self, message):
        self.message = message
        self.switch_to = _SwitchToStub()

    def execute_script(self, *_args):
        raise RuntimeError(self.message)

    def find_elements(self, *_args):
        return []


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

    queued = []
    while not win.message_queue.empty():
        queued.append(win.message_queue.get_nowait())

    assert delay_calls == []
    assert any(
        msg_type == "finished"
        and isinstance(payload, dict)
        and payload.get("success") is False
        and "Chrome 연결이 끊겨 수집을 종료합니다" in str(payload.get("error", ""))
        for msg_type, payload in queued
        if isinstance((msg_type, payload), tuple)
    )
    assert not any(msg_type == "error" for msg_type, _payload in queued)


def test_extraction_worker_preserves_driver_on_manual_stop_when_enabled(monkeypatch):
    driver = _FakeDriver()
    win = _build_window(auto_reconnect_enabled=False, stop_event=_StopAfterFirstWaitEvent())
    win._preserve_driver_on_worker_stop = True
    _configure_basic_worker_stubs(win)
    win._get_current_driver = lambda: driver
    dispose_calls: list[object] = []
    win._dispose_driver = lambda drv, source="": dispose_calls.append((drv, source)) or True

    monkeypatch.setattr(mw_mod.webdriver, "Chrome", lambda options=None: driver)
    monkeypatch.setattr(mw_mod, "WebDriverWait", _FakeWebDriverWait)

    MainWindow._extraction_worker(
        win,
        "https://example.com/live?xcode=10&xcgcd=DCM0000101234567890",
        "#viewSubtit",
        False,
    )

    assert dispose_calls == []
    assert driver.quit_calls == 0


def test_dispose_driver_uses_timeout_wrapper_and_quarantines_failed_driver():
    win = _build_window(auto_reconnect_enabled=False)
    driver = _FakeDriver()
    cleared: list[object] = []
    force_quit_calls: list[tuple[object, float, str]] = []
    scheduled: list[float | None] = []

    win._force_quit_driver_with_timeout = (
        lambda drv, timeout=0.0, source="": force_quit_calls.append((drv, timeout, source))
        or False
    )
    win._clear_current_driver_if = lambda drv: cleared.append(drv)
    win._schedule_detached_driver_cleanup = (
        lambda timeout=None: scheduled.append(timeout) or True
    )

    assert MainWindow._dispose_driver(win, driver, source="worker_finally") is False
    assert force_quit_calls == [(driver, mw_mod.Config.DRIVER_QUIT_TIMEOUT, "worker_finally")]
    assert win._detached_drivers == [driver]
    assert scheduled == [mw_mod.Config.DETACHED_DRIVER_QUIT_TIMEOUT]
    assert cleared == [driver]


def test_cleanup_detached_drivers_requeues_failed_driver():
    win = MainWindow.__new__(MainWindow)
    keep_driver = object()
    closed_driver = object()
    win._detached_drivers = [keep_driver, closed_driver]
    win._detached_drivers_lock = threading.Lock()

    force_quit_calls: list[tuple[object, float, str]] = []

    def fake_force_quit(driver, timeout=0.0, source=""):
        force_quit_calls.append((driver, timeout, source))
        return driver is closed_driver

    win._force_quit_driver_with_timeout = fake_force_quit

    MainWindow._cleanup_detached_drivers_with_timeout(win, timeout=0.25)

    assert force_quit_calls == [
        (keep_driver, 0.25, "detached_1"),
        (closed_driver, 0.25, "detached_2"),
    ]
    assert win._detached_drivers == [keep_driver]


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

    assert detect_calls == [original_url]
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
    assert detect_calls == [original_url]

    queued = []
    while not win.message_queue.empty():
        queued.append(win.message_queue.get_nowait())
    assert any(msg_type == "reconnected" for msg_type, _payload in queued)


def test_reconnect_with_stale_xcgcd_force_refreshes_live_url():
    stale_url = "https://example.com/live?xcode=25&xcgcd=OLD"
    fresh_url = "https://example.com/live?xcode=25&xcgcd=DCM0000259999999999"
    driver = _FakeDriver()
    win = _build_window(auto_reconnect_enabled=True)
    _configure_basic_worker_stubs(win)
    win._create_chrome_driver = lambda _options: driver
    win._configure_driver_timeouts = lambda _driver: None
    win._set_current_driver = lambda _driver: setattr(win, "driver", _driver)
    win._inject_mutation_observer = lambda _driver, _selector: (False, ())

    selector_calls = []

    def resolve_active(_driver, candidates):
        selector_calls.append(True)
        return candidates, "" if len(selector_calls) == 1 else candidates[0]

    detect_calls = []

    def detect_live(_driver, url, *, force_refresh=False):
        detect_calls.append((url, force_refresh))
        return fresh_url if force_refresh else url

    win._resolve_active_selector = resolve_active
    win._detect_live_broadcast = detect_live

    result = MainWindow._open_capture_driver_session(
        win,
        object(),
        stale_url,
        "#viewSubtit",
        reconnecting=True,
        cached_live_url=stale_url,
    )

    assert result[1] == fresh_url
    assert detect_calls == [(stale_url, True)]
    assert driver.get_calls == [stale_url, fresh_url]


def test_extraction_worker_reconnects_after_healthcheck_failures(monkeypatch):
    original_url = "https://example.com/live?xcode=25"
    detected_url = "https://example.com/live?xcode=25&xcgcd=DCM0000251234567890"

    win = _build_window(
        auto_reconnect_enabled=True,
        stop_event=_StopAfterSixWaitsEvent(),
    )
    drivers = []
    detect_calls = []
    health_checks = {}

    def create_driver(options=None):
        driver = _FakeDriver()
        drivers.append(driver)
        return driver

    def detect_live(_driver, input_url):
        detect_calls.append(input_url)
        return detected_url

    def fake_health_check(driver):
        key = id(driver)
        health_checks[key] = health_checks.get(key, 0) + 1
        if driver is drivers[0] and health_checks[key] <= 2:
            return None, "silent browser death"
        return 1, driver.current_url

    _configure_basic_worker_stubs(win)
    win._detect_live_broadcast = detect_live
    win._get_reconnect_delay = lambda attempt: 0.0
    win._check_driver_health = fake_health_check

    monkeypatch.setattr(mw_mod.webdriver, "Chrome", create_driver)
    monkeypatch.setattr(mw_mod, "WebDriverWait", _FakeWebDriverWait)
    monkeypatch.setattr(mw_mod.Config, "DRIVER_HEALTH_CHECK_INTERVAL", 0.0)
    monkeypatch.setattr(mw_mod.Config, "DRIVER_HEALTH_FAILURE_THRESHOLD", 2)

    MainWindow._extraction_worker(win, original_url, "#viewSubtit", False)

    assert len(drivers) >= 2
    assert drivers[0].get_calls[:2] == [original_url, detected_url]
    assert drivers[1].get_calls[0] == detected_url
    assert detect_calls == [original_url]

    queued = []
    while not win.message_queue.empty():
        queued.append(win.message_queue.get_nowait())
    assert any(msg_type == "reconnecting" for msg_type, _payload in queued)
    assert any(msg_type == "reconnected" for msg_type, _payload in queued)


def test_extraction_worker_keeps_single_driver_when_healthcheck_is_healthy(
    monkeypatch,
):
    url_with_xcgcd = "https://example.com/live?xcode=10&xcgcd=DCM0000101234567890"

    win = _build_window(
        auto_reconnect_enabled=True,
        stop_event=_StopAfterSecondWaitEvent(),
    )
    drivers = []

    _configure_basic_worker_stubs(win)
    win._check_driver_health = lambda driver: (1, driver.current_url)
    win._get_reconnect_delay = lambda attempt: 0.0

    monkeypatch.setattr(
        mw_mod.webdriver,
        "Chrome",
        lambda options=None: drivers.append(_FakeDriver()) or drivers[-1],
    )
    monkeypatch.setattr(mw_mod, "WebDriverWait", _FakeWebDriverWait)
    monkeypatch.setattr(mw_mod.Config, "DRIVER_HEALTH_CHECK_INTERVAL", 0.0)

    MainWindow._extraction_worker(win, url_with_xcgcd, "#viewSubtit", False)

    assert len(drivers) == 1

    queued = []
    while not win.message_queue.empty():
        queued.append(win.message_queue.get_nowait())
    assert not any(msg_type == "reconnecting" for msg_type, _payload in queued)


def test_collect_observer_changes_raises_recoverable_webdriver_error():
    win = MainWindow.__new__(MainWindow)
    driver = _ProbeFailureDriver("target closed")

    with pytest.raises(mw_mod.RecoverableWebDriverError):
        MainWindow._collect_observer_changes(win, driver)


def test_read_subtitle_probe_raises_recoverable_webdriver_error():
    win = MainWindow.__new__(MainWindow)
    win._last_subtitle_frame_path = ()
    driver = _ProbeFailureDriver("no such window: target window already closed")

    with pytest.raises(mw_mod.RecoverableWebDriverError):
        MainWindow._read_subtitle_probe_by_selectors(
            win,
            driver,
            ["#viewSubtit .smi_word"],
        )


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
