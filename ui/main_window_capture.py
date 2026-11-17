# -*- coding: utf-8 -*-

# explicit re-exports for test patch targets (were star-provided)
from ui.main_window_common import (
    EC as EC,
)
from ui.main_window_common import (
    By as By,
)
from ui.main_window_common import (
    QMessageBox as QMessageBox,
)
from ui.main_window_common import (
    WebDriverWait as WebDriverWait,
)
from ui.main_window_common import (
    webdriver as webdriver,
)
from ui.main_window_impl.capture_browser import MainWindowCaptureBrowserMixin
from ui.main_window_impl.capture_dom import MainWindowCaptureDomMixin
from ui.main_window_impl.capture_live import MainWindowCaptureLiveMixin
from ui.main_window_impl.capture_observer import MainWindowCaptureObserverMixin
from ui.main_window_types import MainWindowHost


class MainWindowCaptureMixin(
    MainWindowCaptureLiveMixin,
    MainWindowCaptureBrowserMixin,
    MainWindowCaptureDomMixin,
    MainWindowCaptureObserverMixin,
    MainWindowHost,
):
    pass
