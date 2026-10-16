# -*- coding: utf-8 -*-
"""크롬 확장 대비 수집 정합 P1-A/P1-B 회귀."""

from __future__ import annotations

import pytest
import threading
from datetime import datetime, timedelta

from core.live_capture import create_empty_live_capture_ledger
from core.subtitle_pipeline import create_empty_capture_state
from ui.main_window_common import _ResetTimerShim

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow

from ui.main_window_impl import capture_observer as capture_observer_mod
from tests.test_support.browser_dom import BrowserDom


@pytest.fixture
def browser_dom():
    browser = BrowserDom()
    try:
        yield browser
    finally:
        browser.close()


class _ImmediateEvent:
    def is_set(self) -> bool:
        return False

    def wait(self, timeout=None) -> bool:
        return False


class _RecordingDriver:
    """execute_script 호출을 기록하고 선택적으로 성공 조건을 적용한다."""

    def __init__(self, success_when=None):
        self.scripts: list[str] = []
        self._success_when = success_when

    def execute_script(self, script, *args):
        text = str(script or "")
        self.scripts.append(text)
        if self._success_when is None:
            return False
        return self._success_when(text, args)


@pytest.mark.requires_subprocess
@pytest.mark.parametrize("missing, expected", [
    ([], "ai"), (["ai"], "default"),
    (["ai", "default"], "generic"),
    (["ai", "default", "generic"], "smi"),
])
def test_activate_subtitle_prefers_ai_button_before_generic(browser_dom, missing, expected):
    browser_dom.load('''
        <button id="smi" class="" onclick="window.clicked.push(this.id)"></button>
        <button id="generic" class="btn_subtit" onclick="window.clicked.push(this.id)"></button>
        <button id="default" class="btn_subtit_def" onclick="window.clicked.push(this.id)"></button>
        <button id="ai" class="btn_subtit_ai" onclick="window.clicked.push(this.id)"></button>
        <script>window.clicked=[]; document.getElementById('smi').id='smi_btn';</script>
    ''')
    browser_dom.execute_script("arguments[0].forEach(id => document.getElementById(id).remove()); return true;", missing)
    win = MainWindow.__new__(MainWindow)
    win.stop_event = _ImmediateEvent()
    assert MainWindow._activate_subtitle(win, browser_dom) is True
    assert browser_dom.execute_script("return window.clicked;") == ["smi_btn" if expected == "smi" else expected]


def test_activate_subtitle_succeeds_when_script_reports_ok():
    """통합 활성화 스크립트가 ok=true 를 반환하면 성공한다."""

    def success_when(script: str, _args):
        assert "btn_subtit_ai" in script
        assert "isActive" in script
        return {"ok": True, "method": "click", "selector": ".btn_subtit_ai"}

    driver = _RecordingDriver(success_when=success_when)
    win = MainWindow.__new__(MainWindow)
    win.stop_event = _ImmediateEvent()

    activated = MainWindow._activate_subtitle(win, driver)

    assert activated is True
    assert len(driver.scripts) == 1


def test_activate_subtitle_rejects_truthy_failure_payload():
    driver = _RecordingDriver(success_when=lambda *_args: {"ok": False, "method": "none"})
    win = MainWindow.__new__(MainWindow)
    win.stop_event = _ImmediateEvent()
    assert MainWindow._activate_subtitle(win, driver) is False


@pytest.mark.requires_subprocess
@pytest.mark.parametrize("active_attribute", ['class="btn_subtit_ai on"', 'class="btn_subtit_ai" title="자막 끄기"', 'class="btn_subtit_ai" aria-pressed="true"'])
def test_activate_subtitle_does_not_toggle_active_control_off(browser_dom, active_attribute):
    browser_dom.load(f'<button {active_attribute} onclick="window.clicks++"></button><script>window.clicks=0;window.layers=0;function layerSubtit(){{window.layers++;}}</script>')
    win = MainWindow.__new__(MainWindow)
    win.stop_event = _ImmediateEvent()
    assert MainWindow._activate_subtitle(win, browser_dom) is True
    assert browser_dom.execute_script("return [window.clicks, window.layers];") == [0, 0]


@pytest.mark.requires_subprocess
def test_activate_subtitle_rechecks_active_after_page_function(browser_dom):
    browser_dom.load('''<button class="btn_subtit_ai" onclick="window.clicks++"></button>
        <script>window.clicks=0; function layerSubtit(){document.querySelector('button').classList.add('on');}</script>''')
    win = MainWindow.__new__(MainWindow)
    win.stop_event = _ImmediateEvent()
    assert MainWindow._activate_subtitle(win, browser_dom) is True
    assert browser_dom.execute_script("return window.clicks;") == 0


@pytest.mark.requires_subprocess
@pytest.mark.parametrize("html, expected", [('<div id="viewSubtit" style="display:none">자막</div>', True), ('<div>컨트롤 없음</div>', False)])
def test_activate_subtitle_layer_fallback_and_missing_controls(browser_dom, html, expected):
    browser_dom.load(html)
    win = MainWindow.__new__(MainWindow)
    win.stop_event = _ImmediateEvent()
    assert MainWindow._activate_subtitle(win, browser_dom) is expected
    if expected:
        assert browser_dom.execute_script("return document.getElementById('viewSubtit').style.display;") == "block"


def _probe_window():
    win = MainWindow.__new__(MainWindow)
    win._iter_frame_paths = lambda *_a, **_k: []
    win._normalize_subtitle_text_for_option = lambda text: str(text or "")
    # Do not swallow JavaScript errors and accidentally accept a fallback result.
    def raise_error(exc, _context):
        raise exc
    win._raise_if_recoverable_webdriver_error = raise_error
    return win


@pytest.mark.requires_subprocess
def test_probe_splits_real_dom_speakers_and_keeps_keys_on_correction(browser_dom):
    browser_dom.load('''<div id="viewSubtit"><div class="smi_word stxt1">
        <span id="chair" style="color:#1e1e1e">위원장 발언입니다.</span>
        <span id="member" style="color:#237c93">의원 발언입니다.</span>
    </div></div>''')
    win = _probe_window()
    first = MainWindow._read_subtitle_probe_by_selectors(win, browser_dom, ["#viewSubtit .smi_word"])
    assert first["source_mode"] == "smi-window"
    assert [row.text for row in first["rows"]] == ["위원장 발언입니다.", "의원 발언입니다."]
    assert [row.speaker_channel for row in first["rows"]] == ["secondary", "primary"]
    assert [row.node_key for row in first["rows"]] == ["class:stxt1#chair", "class:stxt1#member"]
    browser_dom.execute_script("document.getElementById('member').textContent='정정된 의원 발언입니다.'; return true;")
    corrected = MainWindow._read_subtitle_probe_by_selectors(win, browser_dom, ["#viewSubtit .smi_word"])
    assert [row.node_key for row in corrected["rows"]] == [row.node_key for row in first["rows"]]
    assert corrected["rows"][1].text == "정정된 의원 발언입니다."


@pytest.mark.requires_subprocess
@pytest.mark.parametrize("filter_enabled", [True, False])
def test_probe_unconfirmed_text_cannot_leak_through_container_fallback(browser_dom, filter_enabled):
    browser_dom.load('''<div id="viewSubtit"><div class="smi_word stxt1">
        <span style="background-color:yellow">아직 미확정 자막</span>
    </div></div>''')
    result = MainWindow._read_subtitle_probe_by_selectors(
        _probe_window(), browser_dom, ["[invalid", "#viewSubtit .smi_word", "#viewSubtit"],
        filter_unconfirmed_enabled=filter_enabled,
    )
    assert result["found"] is (not filter_enabled)
    assert [row.text for row in result["rows"]] == ([] if filter_enabled else ["아직 미확정 자막"])
    assert result["text"] == ("" if filter_enabled else "아직 미확정 자막")


@pytest.mark.requires_subprocess
def test_probe_normalizes_whitespace_and_retains_only_last_three_preview_rows(browser_dom):
    browser_dom.load('<div id="viewSubtit">' + ''.join(
        f'<div class="smi_word stxt{i}">발언\t {i}\n  내용</div>' for i in range(5)
    ) + '</div>')
    result = MainWindow._read_subtitle_probe_by_selectors(_probe_window(), browser_dom, ["#viewSubtit .smi_word:last-child"])
    assert [row.text for row in result["rows"]] == [f"발언 {i} 내용" for i in range(5)]
    assert result["text"] == "발언 2 내용 발언 3 내용 발언 4 내용"


@pytest.mark.requires_subprocess
def test_observer_delivers_real_mutations_reset_and_drains_buffer(browser_dom):
    browser_dom.load('<div id="viewSubtit"><div class="smi_word stxt1"></div></div>')
    win = _probe_window()
    win._switch_to_frame_path = lambda _driver, path: path == ()
    assert MainWindow._inject_mutation_observer_here(win, browser_dom, "#viewSubtit .smi_word") is True

    def change(text):
        browser_dom.execute_script("document.querySelector('.smi_word').textContent=arguments[0]; return true;", text)
        return MainWindow._collect_observer_changes(win, browser_dom)

    assert change("네") == ["네"]
    assert change("네") == []
    assert change("정정된\t 발언") == ["정정된 발언"]
    assert change("") == [{"kind": "reset", "source": "observer_cleared", "selector": "#viewSubtit .smi_word", "previousLength": len("정정된 발언")}]
    assert MainWindow._collect_observer_changes(win, browser_dom) == []
    assert change("다음 발언") == ["다음 발언"]


@pytest.mark.requires_subprocess
def test_real_dom_corrections_flow_through_live_ledger_without_duplicates(browser_dom):
    browser_dom.load('''<div id="viewSubtit"><div class="smi_word stxt1">
        <span id="chair" style="color:#1e1e1e">위원장 발언입니다.</span>
        <span id="member" style="color:#237c93">의원 발언입니다.</span>
    </div></div>''')
    win = _probe_window()
    win.capture_state = create_empty_capture_state()
    win.subtitle_lock = threading.Lock()
    win.live_capture_ledger = create_empty_live_capture_ledger()
    win._pending_subtitle_reset_timer = _ResetTimerShim()
    win._current_capture_settings = lambda: {}
    win._apply_capture_pipeline_refresh = lambda **_kwargs: None
    win._invalidate_destructive_undo = lambda: None
    win._schedule_initial_recovery_snapshot_if_needed = lambda _entries: False
    now = datetime(2026, 10, 16, 9, 0, 0)

    def capture(at):
        payload = MainWindow._read_subtitle_probe_by_selectors(win, browser_dom, ["#viewSubtit .smi_word"])
        return MainWindow._apply_structured_preview_payload(win, payload, now=at)

    assert capture(now) is True
    original_ids = [entry.entry_id for entry in win.capture_state.entries]
    assert len(original_ids) == 2 and len(set(original_ids)) == 2
    assert capture(now + timedelta(seconds=1)) is False
    browser_dom.execute_script("document.getElementById('chair').textContent='위원장 정정 발언입니다.'; return true;")
    assert capture(now + timedelta(seconds=2)) is True
    entries = win.capture_state.entries
    assert [entry.text for entry in entries] == ["위원장 정정 발언입니다.", "의원 발언입니다."]
    assert [entry.entry_id for entry in entries] == original_ids
    assert [entry.speaker_channel for entry in entries] == ["secondary", "primary"]
    assert [entry.source_node_key for entry in entries] == ["top::class:stxt1#chair", "top::class:stxt1#member"]


def test_probe_normalizes_multi_speaker_rows_from_driver():
    """P1-A: driver가 multi-span row를 반환하면 ObservedSubtitleRow로 정규화된다."""

    multi_rows = [
        {
            "nodeKey": "class:stxt1#segarr_1_0",
            "text": "위원장 발언입니다.",
            "speakerColor": "rgb(30, 30, 30)",
            "speakerChannel": "secondary",
            "unstableKey": False,
        },
        {
            "nodeKey": "class:stxt1#segarr_1_1",
            "text": "의원 발언입니다.",
            "speakerColor": "rgb(35, 124, 147)",
            "speakerChannel": "primary",
            "unstableKey": False,
        },
    ]

    class _SwitchTo:
        def default_content(self) -> None:
            return None

    class _MultiRowDriver:
        def __init__(self) -> None:
            self.switch_to = _SwitchTo()

        def execute_script(self, _script, *_args):
            return {
                "text": "위원장 발언입니다. 의원 발언입니다.",
                "matchedSelector": "#viewSubtit .smi_word",
                "found": True,
                "rows": multi_rows,
                "sourceMode": "smi-window",
            }

    win = MainWindow.__new__(MainWindow)
    win._last_subtitle_frame_path = ()
    win._iter_frame_paths = lambda *_a, **_k: []
    win._switch_to_frame_path = lambda *_a, **_k: True
    win._raise_if_recoverable_webdriver_error = lambda *_a, **_k: None
    win._normalize_subtitle_text_for_option = lambda text: str(text or "")

    result = MainWindow._read_subtitle_probe_by_selectors(
        win,
        _MultiRowDriver(),
        ["#viewSubtit .smi_word"],
        filter_unconfirmed_enabled=True,
    )

    assert result["found"] is True
    assert result["source_mode"] == "smi-window"
    assert len(result["rows"]) == 2
    assert result["rows"][0].node_key == "class:stxt1#segarr_1_0"
    assert result["rows"][0].speaker_channel == "secondary"
    assert result["rows"][1].node_key == "class:stxt1#segarr_1_1"
    assert result["rows"][1].speaker_channel == "primary"
    assert result["rows"][1].text == "의원 발언입니다."


def test_activate_subtitle_source_module_exports_mixin():
    """모듈 경계: observer mixin에 활성화 메서드가 있다."""
    assert hasattr(capture_observer_mod.MainWindowCaptureObserverMixin, "_activate_subtitle")
