# -*- coding: utf-8 -*-

from ui.main_window_common import *
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
