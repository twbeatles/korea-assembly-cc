# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_impl.view_editing import MainWindowViewEditingMixin
from ui.main_window_impl.view_render import MainWindowViewRenderMixin
from ui.main_window_impl.view_search import MainWindowViewSearchMixin
from ui.main_window_types import MainWindowHost


class MainWindowViewMixin(
    MainWindowViewRenderMixin,
    MainWindowViewSearchMixin,
    MainWindowViewEditingMixin,
    MainWindowHost,
):
    pass
