# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import re
import threading

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QInputDialog

from core.config import Config
from core.logging_utils import logger
from ui.main_window_common import SearchMatch
from ui.main_window_impl.contracts import ViewSearchHost


ViewSearchBase = object


class MainWindowViewSearchMixin(ViewSearchBase):
    def _update_search_count_label_now(self, current_index: int | None = None) -> None:
        search_count = self.__dict__.get("search_count")
        if search_count is None:
            return

        if bool(self.__dict__.get("_runtime_search_in_progress", False)):
            search_count.setText("검색 중...")
            return

        total_matches = len(getattr(self, "search_matches", []))
        if total_matches <= 0:
            rendered = ""
            if str(self.__dict__.get("_runtime_search_query", "") or "").strip():
                rendered = "0건"
            search_count.setText(rendered)
            return

        total_label = (
            f"{total_matches}+건"
            if bool(self.__dict__.get("_runtime_search_truncated", False))
            else f"{total_matches}건"
        )
        if current_index is None:
            search_count.setText(total_label)
            return
        if not bool(self.__dict__.get("_runtime_search_truncated", False)):
            search_count.setText(f"{current_index + 1}/{total_matches}")
            return
        search_count.setText(f"{current_index + 1}/{total_label}")

    def _update_search_count_label(self, current_index: int | None = None) -> None:
        self._update_search_count_label_now(current_index)

    def _cancel_runtime_search(self) -> None:
        cancel_event = self.__dict__.get("_runtime_search_cancel_event")
        if cancel_event is not None:
            try:
                cancel_event.set()
            except Exception:
                pass

    def _new_runtime_search_cancel_event(self):
        self._cancel_runtime_search()
        cancel_event = threading.Event()
        self._runtime_search_cancel_event = cancel_event
        return cancel_event

    def _search_full_session_entries(
        self,
        query: str,
        *,
        cancel_event: object | None = None,
        revision: int | None = None,
    ) -> tuple[list[SearchMatch], bool, bool]:
        query_l = str(query or "").lower()
        if not query_l:
            return [], False, False

        def cancelled() -> bool:
            if cancel_event is not None:
                is_set = getattr(cancel_event, "is_set", None)
                if callable(is_set) and bool(is_set()):
                    return True
            if revision is not None and revision != int(
                self.__dict__.get("_runtime_search_revision", 0) or 0
            ):
                return True
            return False

        matches: list[SearchMatch] = []
        limit = max(1, int(Config.RUNTIME_SEARCH_MATCH_LIMIT))
        for segment_info in list(self.__dict__.get("_runtime_segment_manifest", [])):
            if cancelled():
                return matches, False, True
            start_index = int(segment_info.get("start_index", 0) or 0)
            lowered_texts = self._get_runtime_segment_search_texts(segment_info)
            if cancelled():
                return matches, False, True
            for offset, lowered_text in enumerate(lowered_texts):
                if offset % 64 == 0 and cancelled():
                    return matches, False, True
                start = 0
                while True:
                    if cancelled():
                        return matches, False, True
                    idx = lowered_text.find(query_l, start)
                    if idx == -1:
                        break
                    matches.append(
                        SearchMatch(start_index + offset, idx, len(query))
                    )
                    if len(matches) >= limit:
                        return matches, True, False
                    start = idx + 1

        if cancelled():
            return matches, False, True
        subtitle_lock = self.__dict__.get("subtitle_lock")
        subtitles = getattr(self, "subtitles", [])
        if subtitle_lock is not None:
            with subtitle_lock:
                tail_entries = list(subtitles)
        else:
            tail_entries = list(subtitles)
        tail_start_index = int(self.__dict__.get("_runtime_archived_count", 0) or 0)
        for offset, entry in enumerate(tail_entries):
            if offset % 64 == 0 and cancelled():
                return matches, False, True
            lowered_text = self._normalize_subtitle_text_for_option(entry.text).lower()
            start = 0
            while True:
                if cancelled():
                    return matches, False, True
                idx = lowered_text.find(query_l, start)
                if idx == -1:
                    break
                matches.append(
                    SearchMatch(tail_start_index + offset, idx, len(query))
                )
                if len(matches) >= limit:
                    return matches, True, False
                start = idx + 1
        return matches, False, False

    def _handle_runtime_search_done(self, payload: dict[str, object]) -> None:
        if not isinstance(payload, dict):
            return

        payload_revision = int(payload.get("revision", -1) or -1)
        if payload_revision != int(self.__dict__.get("_runtime_search_revision", 0)):
            return

        query = str(payload.get("query", "") or "").strip()
        if query != str(self.__dict__.get("_runtime_search_query", "") or "").strip():
            return

        matches: list[SearchMatch] = []
        raw_matches = payload.get("matches", [])
        if isinstance(raw_matches, list):
            for item in raw_matches:
                if not isinstance(item, dict):
                    continue
                try:
                    matches.append(
                        SearchMatch(
                            int(item.get("entry_index", -1) or -1),
                            int(item.get("char_start", 0) or 0),
                            int(item.get("char_length", 0) or 0),
                        )
                    )
                except Exception:
                    continue

        self._runtime_search_in_progress = False
        self._runtime_search_truncated = bool(payload.get("truncated", False))
        self.search_matches = matches
        self.search_idx = 0

        if self.search_matches:
            self._highlight_search(0)
            return

        self._schedule_ui_refresh(search_count=True)
        self._schedule_ui_refresh(render=True, force_full=True)

    def _handle_runtime_search_failed(self, payload: dict[str, object]) -> None:
        if not isinstance(payload, dict):
            return

        payload_revision = int(payload.get("revision", -1) or -1)
        if payload_revision != int(self.__dict__.get("_runtime_search_revision", 0)):
            return

        self._runtime_search_in_progress = False
        self.search_matches = []
        self.search_idx = 0
        self._schedule_ui_refresh(search_count=True, render=True, force_full=True)
        err = str(payload.get("error", "") or "알 수 없는 오류")
        self._show_toast(f"검색 실패: {err}", "warning", 3000)

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
            self._save_setting_value(
                "highlight_keywords",
                ", ".join(self.keywords),
                context="하이라이트 키워드 설정 저장",
            )

        if refresh and hasattr(self, "subtitle_text"):
            self._schedule_ui_refresh(render=True, force_full=True)

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

    def _schedule_search(self) -> None:
        search_frame = self.__dict__.get("search_frame")
        if search_frame is not None and not search_frame.isVisible():
            return
        timer = self.__dict__.get("_runtime_search_debounce_timer")
        self._runtime_search_requested_query = self.search_input.text().strip()
        if timer is None:
            self._do_search()
            return
        timer.start(180)

    def _run_scheduled_search(self) -> None:
        self._runtime_search_requested_query = self.search_input.text().strip()
        self._do_search()

    def _trigger_search_now(self) -> None:
        timer = self.__dict__.get("_runtime_search_debounce_timer")
        if timer is not None and timer.isActive():
            timer.stop()
        self._runtime_search_requested_query = self.search_input.text().strip()
        self._do_search()

    def _show_search(self):
        self.search_frame.show()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _hide_search(self):
        self._cancel_runtime_search()
        self._runtime_search_revision = int(
            self.__dict__.get("_runtime_search_revision", 0) or 0
        ) + 1
        self.search_matches = []
        self.search_idx = 0
        self._runtime_search_in_progress = False
        self._runtime_search_query = ""
        self._runtime_search_truncated = False
        self._schedule_ui_refresh(search_count=True)
        self._search_focus_entry_index = None
        self._pending_search_focus_query = ""
        self.search_frame.hide()
        self._schedule_ui_refresh(render=True, force_full=True)

    def _do_search(self):
        query = self.search_input.text().strip()
        if not query:
            self._cancel_runtime_search()
            self._runtime_search_revision = int(
                self.__dict__.get("_runtime_search_revision", 0) or 0
            ) + 1
            self.search_matches = []
            self.search_idx = 0
            self._runtime_search_in_progress = False
            self._runtime_search_query = ""
            self._runtime_search_truncated = False
            self._schedule_ui_refresh(search_count=True, render=True, force_full=True)
            return

        self._runtime_search_revision = int(
            self.__dict__.get("_runtime_search_revision", 0) or 0
        ) + 1
        search_revision = int(self._runtime_search_revision)
        cancel_event = self._new_runtime_search_cancel_event()
        self._runtime_search_query = query
        self._runtime_search_truncated = False
        self.search_matches = []
        self.search_idx = 0

        if self._has_runtime_archived_segments():
            self._runtime_search_in_progress = True
            self._schedule_ui_refresh(search_count=True)

            def background_search() -> None:
                try:
                    matches, truncated, was_cancelled = self._search_full_session_entries(
                        query,
                        cancel_event=cancel_event,
                        revision=search_revision,
                    )
                    if was_cancelled or cancel_event.is_set():
                        return
                    self._emit_control_message(
                        "runtime_search_done",
                        {
                            "query": query,
                            "revision": search_revision,
                            "truncated": truncated,
                            "matches": [
                                {
                                    "entry_index": match.entry_index,
                                    "char_start": match.char_start,
                                    "char_length": match.char_length,
                                }
                                for match in matches
                            ],
                        },
                    )
                except Exception as e:
                    if cancel_event.is_set():
                        return
                    logger.error("runtime search failed: %s", e)
                    self._emit_control_message(
                        "runtime_search_failed",
                        {
                            "query": query,
                            "revision": search_revision,
                            "error": str(e),
                        },
                    )

            started = self._start_background_thread(
                background_search,
                "RuntimeSearchWorker",
            )
            if started:
                self._schedule_ui_refresh(render=True, force_full=True)
                return
            self._runtime_search_in_progress = False

        matches, truncated, was_cancelled = self._search_full_session_entries(
            query,
            cancel_event=cancel_event,
            revision=search_revision,
        )
        if was_cancelled:
            return
        self.search_matches = matches
        self._runtime_search_truncated = truncated

        if self.search_matches:
            self._highlight_search(0)
            return

        self._schedule_ui_refresh(search_count=True, render=True, force_full=True)

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

        self._update_search_count_label(current_index=idx)

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
            self._save_setting_value(
                "alert_keywords",
                ", ".join(cleaned),
                context="알림 키워드 설정 저장",
            )

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
