# -*- coding: utf-8 -*-

from typing import TYPE_CHECKING, Any

from ui.main_window_common import *
from ui.main_window_capture import MainWindowCaptureMixin
from ui.main_window_database import MainWindowDatabaseMixin
from ui.main_window_impl.runtime_driver import MainWindowRuntimeDriverMixin
from ui.main_window_impl.runtime_lifecycle import MainWindowRuntimeLifecycleMixin
from ui.main_window_impl.runtime_state import MainWindowRuntimeStateMixin
from ui.main_window_persistence import MainWindowPersistenceMixin
from ui.main_window_pipeline import MainWindowPipelineMixin
from ui.main_window_ui import MainWindowUIMixin
from ui.main_window_view import MainWindowViewMixin
import ui.main_window_capture as capture_mod

MainWindowQtBase = object if TYPE_CHECKING else QMainWindow


class MainWindow(  # pyright: ignore[reportGeneralTypeIssues]
    MainWindowRuntimeStateMixin,
    MainWindowRuntimeLifecycleMixin,
    MainWindowRuntimeDriverMixin,
    MainWindowQtBase,
    MainWindowUIMixin,
    MainWindowCaptureMixin,
    MainWindowPipelineMixin,
    MainWindowViewMixin,
    MainWindowPersistenceMixin,
    MainWindowDatabaseMixin,
):
    def _sync_capture_compat_globals(self) -> None:
        capture_mod.webdriver = webdriver
        capture_mod.WebDriverWait = WebDriverWait
        capture_mod.EC = EC
        capture_mod.By = By

    def _activate_subtitle(self, driver: Any) -> bool:
        self._sync_capture_compat_globals()
        return MainWindowCaptureMixin._activate_subtitle(self, driver)

    def _detect_live_broadcast(self, driver: Any, original_url: str) -> str:
        self._sync_capture_compat_globals()
        return MainWindowCaptureMixin._detect_live_broadcast(self, driver, original_url)

    def _read_subtitle_probe_by_selectors(
        self,
        driver: Any,
        selectors: list[str],
        preferred_frame_path: tuple[int, ...] = (),
        filter_unconfirmed_enabled: bool = True,
    ) -> dict[str, Any]:
        self._sync_capture_compat_globals()
        return MainWindowCaptureMixin._read_subtitle_probe_by_selectors(
            self,
            driver,
            selectors,
            preferred_frame_path=preferred_frame_path,
            filter_unconfirmed_enabled=filter_unconfirmed_enabled,
        )

    def _read_subtitle_text_by_selectors(
        self,
        driver: Any,
        selectors: list[str],
        preferred_frame_path: tuple[int, ...] = (),
    ) -> tuple[str, str, bool]:
        self._sync_capture_compat_globals()
        return MainWindowCaptureMixin._read_subtitle_text_by_selectors(
            self,
            driver,
            selectors,
            preferred_frame_path=preferred_frame_path,
        )

    def _extraction_worker(
        self,
        url: str,
        selector: str,
        headless: bool,
        run_id: int | None = None,
    ) -> None:
        self._sync_capture_compat_globals()
        return MainWindowCaptureMixin._extraction_worker(
            self, url, selector, headless, run_id=run_id
        )
