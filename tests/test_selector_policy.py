from __future__ import annotations

from core.config import Config
from core.selector_policy import validate_subtitle_selector


def test_validate_subtitle_selector_accepts_default_presets():
    for selector in Config.DEFAULT_SELECTORS:
        assert validate_subtitle_selector(selector) == (selector, None)


def test_validate_subtitle_selector_rejects_empty_and_unsafe_values():
    assert validate_subtitle_selector("") == (None, "CSS 선택자를 입력하세요.")
    assert validate_subtitle_selector("a[b=\"x\"];alert(1)") == (
        None,
        "허용되지 않는 문자가 포함된 CSS 선택자입니다.",
    )


def test_validate_subtitle_selector_accepts_simple_custom_selector():
    assert validate_subtitle_selector("#viewSubtit .custom_word") == (
        "#viewSubtit .custom_word",
        None,
    )