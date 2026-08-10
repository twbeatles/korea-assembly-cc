# -*- coding: utf-8 -*-
"""크롬 확장 대비 수집 정합 P1-A/P1-B 회귀."""

from __future__ import annotations

import inspect

import pytest

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow

from ui.main_window_impl import capture_dom as capture_dom_mod
from ui.main_window_impl import capture_observer as capture_observer_mod


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
        return bool(self._success_when(text, args))


def test_activate_subtitle_prefers_ai_button_before_generic():
    """P1-B: .btn_subtit_ai / .btn_subtit_def 가 일반 .btn_subtit 보다 앞선다."""
    source = inspect.getsource(
        capture_observer_mod.MainWindowCaptureObserverMixin._activate_subtitle
    )
    ai_pos = source.find(".btn_subtit_ai")
    def_pos = source.find(".btn_subtit_def")
    generic_pos = source.find("'.btn_subtit'")
    smi_btn_pos = source.find("'#smi_btn'")

    assert ai_pos >= 0, "AI 자막 버튼 선택자가 없습니다"
    assert def_pos >= 0, "기본 자막 버튼 선택자가 없습니다"
    assert generic_pos >= 0, "일반 .btn_subtit 선택자가 없습니다"
    assert smi_btn_pos >= 0, "#smi_btn 선택자가 없습니다"
    assert ai_pos < def_pos < generic_pos < smi_btn_pos
    # active 재클릭 방지
    assert "isActive" in source
    assert "already-active" in source
    assert "끄기" in source or "닫기" in source


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


def test_probe_js_contains_multi_speaker_split():
    """P1-A: probe JS에 다중 화자 span 분할 로직이 포함된다."""
    source = inspect.getsource(capture_dom_mod.MainWindowCaptureDomMixin._read_subtitle_probe_by_selectors)
    assert "collectMultiSpeakerSegments" in source
    assert "keySuffix" in source
    assert "baseNodeKey + '#'" in source or "baseNodeKey + '#' +" in source
    assert "pushObservedRow" in source


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
