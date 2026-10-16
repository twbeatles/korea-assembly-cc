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
from PySide6.QtWebEngineCore import QWebEnginePage


class BrowserDom:
    def __init__(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.app = QApplication.instance() or QApplication([])
        self.page = QWebEnginePage()
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
        def start(done):
            self.page.loadFinished.connect(done)
            self.page.setHtml(html)

        try:
            assert self._wait(start), "Offline HTML failed to load"
        finally:
            self.page.loadFinished.disconnect()

    def execute_script(self, script: str, *args: object) -> Any:
        # Selenium's scripts use top-level return and the arguments object.
        wrapped = (
            "JSON.stringify((function(){" + script + "}).apply(null,"
            + json.dumps(args, ensure_ascii=False) + "))"
        )
        raw = self._wait(lambda done: self.page.runJavaScript(wrapped, done))
        assert isinstance(raw, str), "JavaScript failed or returned undefined"
        return json.loads(raw)

    def close(self) -> None:
        self.page.deleteLater()
        self.app.processEvents()
