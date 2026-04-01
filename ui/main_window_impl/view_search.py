# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import re

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QInputDialog

from core.logging_utils import logger
from ui.main_window_common import SearchMatch
from ui.main_window_impl.contracts import ViewSearchHost


ViewSearchBase = object


class MainWindowViewSearchMixin(ViewSearchBase):
    def _rebuild_keyword_cache(
        self, keywords: list, update_settings: bool = True, refresh: bool = True
    ) -> None:
        cleaned = [k.strip() for k in keywords if k and k.strip()]
        self.keywords = cleaned
        self._keywords_lower_set = {k.lower() for k in cleaned}

        if cleaned:
            pattern = "|".join(re.escape(k) for k in cleaned)
            try:
                self._keyword_pattern = re.compile(f"({pattern})", re.IGNORECASE)
            except re.error:
                self._keyword_pattern = None
        else:
            self._keyword_pattern = None

        if update_settings:
            self.settings.setValue("highlight_keywords", ", ".join(self.keywords))

        if refresh and hasattr(self, "subtitle_text"):
            self._refresh_text(force_full=True)

    def _update_keyword_cache(self):
        if (
            hasattr(self, "_keyword_debounce_timer")
            and self._keyword_debounce_timer.isActive()
        ):
            self._keyword_debounce_timer.stop()

        def do_update():
            self._perform_keyword_cache_update()

        self._keyword_debounce_timer = QTimer(self)
        self._keyword_debounce_timer.setSingleShot(True)
        self._keyword_debounce_timer.timeout.connect(do_update)
        self._keyword_debounce_timer.start(300)

    def _perform_keyword_cache_update(self):
        try:
            if hasattr(self, "keyword_input"):
                raw_text = self.keyword_input.text()
            else:
                raw_text = ", ".join(self.keywords)

            keywords = [k.strip() for k in raw_text.split(",") if k.strip()]
            self._rebuild_keyword_cache(keywords, update_settings=True, refresh=True)
        except Exception as e:
            logger.error(f"키워드 캐시 업데이트 오류: {e}")

    def _show_search(self):
        self.search_frame.show()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _hide_search(self):
        self.search_matches = []
        self.search_idx = 0
        search_count = self.__dict__.get("search_count")
        if search_count is not None:
            search_count.setText("")
        self._search_focus_entry_index = None
        self._pending_search_focus_query = ""
        self.search_frame.hide()
        self._refresh_text(force_full=True)

    def _do_search(self):
        query = self.search_input.text().strip()
        if not query:
            self.search_matches = []
            self.search_idx = 0
            search_count = self.__dict__.get("search_count")
            if search_count is not None:
                search_count.setText("")
            self._refresh_text(force_full=True)
            return

        query_l = query.lower()
        self.search_matches = []

        with self.subtitle_lock:
            entry_texts = [
                self._normalize_subtitle_text_for_option(entry.text)
                for entry in self.subtitles
            ]

        for entry_index, entry_text in enumerate(entry_texts):
            lowered_text = entry_text.lower()
            start = 0
            while True:
                idx = lowered_text.find(query_l, start)
                if idx == -1:
                    break
                self.search_matches.append(SearchMatch(entry_index, idx, len(query)))
                start = idx + 1

        self.search_idx = 0
        search_count = self.__dict__.get("search_count")
        if search_count is not None:
            search_count.setText(f"{len(self.search_matches)}개")

        if self.search_matches:
            self._highlight_search(0)

    def _nav_search(self, delta):
        if not self.search_matches:
            return

        self.search_idx = (self.search_idx + delta) % len(self.search_matches)
        self._highlight_search(self.search_idx)

    def _highlight_search(self, idx):
        if not self.search_matches:
            return

        match = self.search_matches[idx]
        self._search_focus_entry_index = match.entry_index
        self._refresh_text(force_full=True)
        self._search_focus_entry_index = None
        self._select_rendered_entry_span(
            match.entry_index,
            match.char_start,
            match.char_length,
        )

        search_count = self.__dict__.get("search_count")
        if search_count is not None:
            search_count.setText(f"{idx + 1}/{len(self.search_matches)}")

    def _set_keywords(self):
        current = ", ".join(self.keywords)
        text, ok = QInputDialog.getText(
            self,
            "하이라이트 키워드 설정",
            "하이라이트할 키워드 (쉼표로 구분):",
            text=current,
        )

        if ok:
            keywords = [k.strip() for k in text.split(",") if k.strip()]
            if hasattr(self, "keyword_input"):
                self.keyword_input.blockSignals(True)
                self.keyword_input.setText(", ".join(keywords))
                self.keyword_input.blockSignals(False)
            self._rebuild_keyword_cache(keywords, update_settings=True, refresh=True)
            self._show_toast(f"하이라이트 키워드 {len(keywords)}개 설정됨", "success")

    def _rebuild_alert_keyword_cache(
        self, keywords: list, update_settings: bool = True
    ) -> None:
        cleaned = [k.strip() for k in keywords if k and k.strip()]
        self.alert_keywords = cleaned
        self._alert_keywords_cache = [(k, k.lower()) for k in cleaned]
        if update_settings:
            self.settings.setValue("alert_keywords", ", ".join(cleaned))

    def _set_alert_keywords(self):
        current = ", ".join(self.alert_keywords)
        text, ok = QInputDialog.getText(
            self,
            "알림 키워드 설정",
            "알림을 받을 키워드 (쉼표로 구분):\n예: 법안, 의결, 통과",
            text=current,
        )

        if ok:
            self._rebuild_alert_keyword_cache(
                [k.strip() for k in text.split(",") if k.strip()],
                update_settings=True,
            )
            self._show_toast(
                f"알림 키워드 {len(self.alert_keywords)}개 설정됨", "success"
            )

    def _check_keyword_alert(self, text: str):
        if not self._alert_keywords_cache:
            return

        text_lower = text.lower()
        for original, keyword_lower in self._alert_keywords_cache:
            if keyword_lower and keyword_lower in text_lower:
                self._show_toast(f"🔔 키워드 감지: {original}", "warning", 5000)
                break
