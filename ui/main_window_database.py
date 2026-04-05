# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_impl.database_dialogs import MainWindowDatabaseDialogsMixin
from ui.main_window_impl.database_worker import MainWindowDatabaseWorkerMixin
from ui.main_window_types import MainWindowHost


class MainWindowDatabaseMixin(
    MainWindowDatabaseWorkerMixin,
    MainWindowDatabaseDialogsMixin,
    MainWindowHost,
):
    pass
