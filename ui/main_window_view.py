# -*- coding: utf-8 -*-

# explicit re-exports for test patch targets (were star-provided)
from ui.main_window_common import (
    QMessageBox as QMessageBox,
)
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
