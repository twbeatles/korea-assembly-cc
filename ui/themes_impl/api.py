# -*- coding: utf-8 -*-

"""Theme public API (SRP: 팔레트+템플릿 조합만 담당)."""

from __future__ import annotations

from ui.themes_impl.palettes import _DARK_PALETTE, _LIGHT_PALETTE
from ui.themes_impl.template import _THEME_TEMPLATE

def _build_theme(palette: dict[str, str]) -> str:
    """팔레트 토큰을 적용해 완성된 QSS 문자열을 만든다."""
    return _THEME_TEMPLATE.substitute(palette)


DARK_THEME = _build_theme(_DARK_PALETTE)
LIGHT_THEME = _build_theme(_LIGHT_PALETTE)


# 토스트 등 런타임 위젯이 팔레트 토큰을 재사용할 수 있도록 노출한다.
def get_palette(is_dark: bool) -> dict[str, str]:
    """현재 테마 팔레트 사본을 반환한다."""
    return dict(_DARK_PALETTE if is_dark else _LIGHT_PALETTE)
