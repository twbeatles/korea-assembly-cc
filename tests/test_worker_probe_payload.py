import queue
import threading
import time

import pytest

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


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


class _StopAfterSecondWaitEvent:
    def __init__(self):
        self._wait_calls = 0
        self._is_set = False

    def is_set(self):
        return self._is_set

    def wait(self, timeout=None):
        if timeout:
            time.sleep(min(timeout, 0.05))
        self._wait_calls += 1
        if self._wait_calls >= 7:
            self._is_set = True
            return True
        return False


def _build_window():
    win = MainWindow.__new__(MainWindow)
    win.message_queue = queue.Queue()
    win.stop_event = _StopAfterSecondWaitEvent()
    win.auto_reconnect_enabled = False
    win._detached_drivers = []
    win._detached_drivers_lock = threading.Lock()
    win.driver = None
    win._last_subtitle_frame_path = ()
    win._activate_subtitle = lambda _driver: True
    win._build_subtitle_selector_candidates = lambda selector, extras=None: [selector]
    win._inject_mutation_observer = lambda _driver, _selector: (False, ())
    win._find_subtitle_selector = lambda _driver: ""
    win._detect_live_broadcast = lambda _driver, url: url
    return win


def test_extraction_worker_emits_structured_preview_payload(monkeypatch):
    win = _build_window()
    win._read_subtitle_probe_by_selectors = (
        lambda _driver, _selectors, preferred_frame_path=(), **_kwargs: {
            "text": "첫 문장 보정",
            "matched_selector": "#viewSubtit .smi_word",
            "found": True,
            "rows": [
                {
                    "nodeKey": "row_1",
                    "text": "첫 문장 보정",
                    "speakerColor": "rgb(35, 124, 147)",
                    "speakerChannel": "primary",
                    "unstableKey": False,
                }
            ],
            "frame_path": preferred_frame_path,
        }
    )

    monkeypatch.setattr(mw_mod.webdriver, "Chrome", lambda options=None: _FakeDriver())
    monkeypatch.setattr(mw_mod, "WebDriverWait", _FakeWebDriverWait)

    MainWindow._extraction_worker(
        win,
        "https://example.com/live?xcgcd=DCM0000101234567890",
        "#viewSubtit .smi_word",
        False,
    )

    preview_payloads = []
    while not win.message_queue.empty():
        msg_type, payload = win.message_queue.get_nowait()
        if msg_type == "preview":
            preview_payloads.append(payload)

    assert len(preview_payloads) == 1
    preview_payload = preview_payloads[0]
    assert isinstance(preview_payload, dict)
    assert preview_payload["raw"] == "첫 문장 보정"
    assert preview_payload["selector"] == "#viewSubtit .smi_word"
    assert preview_payload["rows"][0]["nodeKey"] == "row_1"
