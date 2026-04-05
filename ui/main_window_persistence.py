# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_common import _import_optional_module
from ui.main_window_impl.persistence_exports import MainWindowPersistenceExportsMixin
from ui.main_window_impl.persistence_runtime import MainWindowPersistenceRuntimeMixin
from ui.main_window_impl.persistence_session import MainWindowPersistenceSessionMixin
from ui.main_window_impl.persistence_tools import MainWindowPersistenceToolsMixin
from ui.main_window_types import MainWindowHost


class MainWindowPersistenceMixin(
    MainWindowPersistenceRuntimeMixin,
    MainWindowPersistenceSessionMixin,
    MainWindowPersistenceExportsMixin,
    MainWindowPersistenceToolsMixin,
    MainWindowHost,
):
    pass
