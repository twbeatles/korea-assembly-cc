# -*- coding: utf-8 -*-

from __future__ import annotations

from ui.main_window_impl.ui.help import MainWindowUIHelpMixin
from ui.main_window_impl.ui.history_presets import MainWindowUIHistoryPresetsMixin
from ui.main_window_impl.ui.layout import MainWindowUILayoutMixin
from ui.main_window_impl.ui.menus import MainWindowUIMenuMixin
from ui.main_window_impl.ui.runtime_controls import MainWindowUIRuntimeControlsMixin
from ui.main_window_impl.ui.theme_status import MainWindowUIThemeStatusMixin
from ui.main_window_impl.ui.tray import MainWindowUITrayMixin
from ui.main_window_types import MainWindowHost


class MainWindowUIMixin(
    MainWindowUITrayMixin,
    MainWindowUIMenuMixin,
    MainWindowUILayoutMixin,
    MainWindowUIThemeStatusMixin,
    MainWindowUIHistoryPresetsMixin,
    MainWindowUIRuntimeControlsMixin,
    MainWindowUIHelpMixin,
    MainWindowHost,
):
    pass
