# -*- coding: utf-8 -*-

"""Theme implementation package (palettes/template/api)."""

from ui.themes_impl.api import DARK_THEME, LIGHT_THEME, _build_theme, get_palette
from ui.themes_impl.palettes import _DARK_PALETTE, _LIGHT_PALETTE
from ui.themes_impl.template import _THEME_TEMPLATE

__all__ = [
    "DARK_THEME",
    "LIGHT_THEME",
    "_DARK_PALETTE",
    "_LIGHT_PALETTE",
    "_THEME_TEMPLATE",
    "_build_theme",
    "get_palette",
]
