"""Run the application's Selenium scripts against a real, offline Chromium DOM.

QtWebEngine ships with our existing PySide6 dependency. No driver download,
external website, or separately installed Chrome is needed.
"""
from __future__ import annotations

import json
import os
from typing import Any

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication


class BrowserDom:
    def __init__(self) -> None:
        self.driver = None
        if os.environ.get("KACC_TEST_BROWSER") == "chrome":
            from selenium import webdriver
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_page_load_timeout(10)
            return
        # WebEngine is optional on some architectures. Skip only DOM fixtures,
        # keeping the rest of this module's capture tests collectible.
        import pytest
        webengine = pytest.importorskip("PySide6.QtWebEngineCore")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.app = QApplication.instance() or QApplication([])
        self.page = webengine.QWebEnginePage()
        self.switch_to = self

    def default_content(self) -> None:
        """This adapter deliberately supports only the top-level document."""

    def _wait(self, start) -> Any:
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        values: list[Any] = []

        def done(value) -> None:
            values.append(value)
            loop.quit()

        timer.timeout.connect(loop.quit)
        timer.start(10000)
        start(done)
        if not values:
            loop.exec()
        timer.stop()
        assert values, "Chromium did not finish within 10 seconds"
        return values[0]

    def load(self, html: str) -> None:
        if self.driver is not None:
            from urllib.parse import quote
            self.driver.get("data:text/html;charset=utf-8," + quote(html))
            return
        def start(done):
            self.page.loadFinished.connect(done)
            self.page.setHtml(html)

        try:
            assert self._wait(start), "Offline HTML failed to load"
        finally:
            self.page.loadFinished.disconnect()

    def execute_script(self, script: str, *args: object) -> Any:
        if self.driver is not None:
            return self.driver.execute_script(script, *args)
        # Selenium's scripts use top-level return and the arguments object.
        wrapped = (
            "JSON.stringify((function(){" + script + "}).apply(null,"
            + json.dumps(args, ensure_ascii=False) + "))"
        )
        raw = self._wait(lambda done: self.page.runJavaScript(wrapped, done))
        assert isinstance(raw, str), "JavaScript failed or returned undefined"
        return json.loads(raw)

    def close(self) -> None:
        if self.driver is not None:
            self.driver.quit()
            return
        self.page.deleteLater()
        self.app.processEvents()
