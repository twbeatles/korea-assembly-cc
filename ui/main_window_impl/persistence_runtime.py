# -*- coding: utf-8 -*-

from ui.main_window_impl.persistence_runtime_archive import MainWindowRuntimeArchiveMixin
from ui.main_window_impl.persistence_runtime_hydration import MainWindowRuntimeHydrationMixin
from ui.main_window_impl.persistence_runtime_manifest import MainWindowRuntimeManifestMixin
from ui.main_window_impl.persistence_runtime_readers import MainWindowRuntimeReadersMixin
from ui.main_window_impl.persistence_runtime_segments import MainWindowRuntimeSegmentsMixin
from ui.main_window_types import MainWindowHost


class MainWindowPersistenceRuntimeMixin(
    MainWindowRuntimeHydrationMixin,
    MainWindowRuntimeArchiveMixin,
    MainWindowRuntimeSegmentsMixin,
    MainWindowRuntimeReadersMixin,
    MainWindowRuntimeManifestMixin,
    MainWindowHost,
):
    pass
