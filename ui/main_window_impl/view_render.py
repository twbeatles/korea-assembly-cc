# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import time
from datetime import datetime

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QTextCursor

from core import utils
from core.config import Config
from core.models import SubtitleEntry
from ui.main_window_impl.contracts import ViewRenderHost


ViewRenderBase = object

UI_REFRESH_RENDER = 1
UI_REFRESH_COUNT = 2
UI_REFRESH_STATS = 4
UI_REFRESH_STATUS = 8
UI_REFRESH_SEARCH_COUNT = 16


class MainWindowViewRenderMixin(ViewRenderBase):
    def _ensure_ui_refresh_state(self) -> None:
        state = getattr(self, "__dict__", {})
        if "_pending_ui_refresh_flags" not in state:
            self._pending_ui_refresh_flags = 0
        if "_pending_ui_refresh_force_full" not in state:
            self._pending_ui_refresh_force_full = False
        if "_ui_refresh_scheduled" not in state:
            self._ui_refresh_scheduled = False
        if "_pending_status_text" not in state:
            self._pending_status_text = ""
        if "_pending_status_type" not in state:
            self._pending_status_type = "info"
        if "_pending_search_count_index" not in state:
            self._pending_search_count_index = None

    def _schedule_ui_refresh(
        self,
        *,
        render: bool = False,
        force_full: bool = False,
        count: bool = False,
        stats: bool = False,
        status: bool = False,
        search_count: bool = False,
        search_index: int | None = None,
    ) -> None:
        self._ensure_ui_refresh_state()
        flags = int(self.__dict__.get("_pending_ui_refresh_flags", 0) or 0)
        if render:
            flags |= UI_REFRESH_RENDER
        if count:
            flags |= UI_REFRESH_COUNT
        if stats:
            flags |= UI_REFRESH_STATS
        if status:
            flags |= UI_REFRESH_STATUS
        if search_count:
            flags |= UI_REFRESH_SEARCH_COUNT
            self._pending_search_count_index = search_index
        self._pending_ui_refresh_flags = flags
        if force_full:
            self._pending_ui_refresh_force_full = True
        if not bool(self.__dict__.get("_use_async_ui_refresh", True)):
            self._flush_scheduled_ui_refresh()
            return
        if bool(self.__dict__.get("_ui_refresh_scheduled", False)):
            return
        self._ui_refresh_scheduled = True
        try:
            QTimer.singleShot(0, self._flush_scheduled_ui_refresh)
        except Exception:
            self._ui_refresh_scheduled = False
            return

    def _flush_scheduled_ui_refresh(self) -> None:
        self._ensure_ui_refresh_state()
        flags = int(self.__dict__.get("_pending_ui_refresh_flags", 0) or 0)
        force_full = bool(self.__dict__.get("_pending_ui_refresh_force_full", False))
        search_index = self.__dict__.get("_pending_search_count_index")
        self._pending_ui_refresh_flags = 0
        self._pending_ui_refresh_force_full = False
        self._pending_search_count_index = None
        self._ui_refresh_scheduled = False
        if flags & UI_REFRESH_STATUS:
            self._set_status_now(
                str(self.__dict__.get("_pending_status_text", "") or ""),
                str(self.__dict__.get("_pending_status_type", "info") or "info"),
            )
        if flags & UI_REFRESH_COUNT:
            self._update_count_label_now()
        if flags & UI_REFRESH_SEARCH_COUNT:
            self._update_search_count_label_now(search_index)
        if flags & UI_REFRESH_RENDER:
            self._render_subtitles(force_full=force_full)
        if flags & UI_REFRESH_STATS:
            self._update_stats_now()

    def _schedule_status_update(self, text: str, status_type: str = "info") -> None:
        self._ensure_ui_refresh_state()
        self._pending_status_text = str(text or "")
        self._pending_status_type = str(status_type or "info")
        self._schedule_ui_refresh(status=True)

    def _rebuild_stats_cache(self) -> None:
        with self.subtitle_lock:
            self._cached_total_chars = sum(s.char_count for s in self.subtitles)
            self._cached_total_words = sum(s.word_count for s in self.subtitles)

    def _set_preview_text(self, text: str) -> None:
        if not hasattr(self, "preview_frame"):
            return
        content = (text or "").strip()
        if content:
            if self.preview_label.text() != content:
                self.preview_label.setText(content)
            if not self.preview_frame.isVisible():
                self.preview_frame.show()
        else:
            if self.preview_label.text():
                self.preview_label.setText("")
            if self.preview_frame.isVisible():
                self.preview_frame.hide()

    def _clear_preview(self) -> None:
        self._set_preview_text("")

    def _update_preview(self, raw: str) -> None:
        self._set_preview_text(raw)

    def _build_render_chunk(
        self,
        entry: SubtitleEntry,
        previous_entry: SubtitleEntry | None,
        show_ts: bool,
        last_printed_ts: datetime | None,
    ) -> tuple[str, str, datetime | None]:
        separator = ""
        same_second = False
        if previous_entry is not None:
            same_second = entry.timestamp.replace(
                microsecond=0
            ) == previous_entry.timestamp.replace(microsecond=0)
            separator = " " if same_second else "\n"

        prefix = ""
        next_last_printed_ts = last_printed_ts
        if show_ts and not same_second:
            should_print = False
            if last_printed_ts is None:
                should_print = True
            elif (entry.timestamp - last_printed_ts).total_seconds() >= 60:
                should_print = True

            if should_print:
                prefix = f"[{entry.timestamp.strftime('%H:%M:%S')}] "
                next_last_printed_ts = entry.timestamp

        return separator, prefix, next_last_printed_ts

    def _insert_render_chunk(
        self,
        cursor,
        separator: str,
        prefix: str,
        text: str,
    ) -> tuple[int, int]:
        if separator:
            cursor.insertText(separator, self._normal_fmt)
        if prefix:
            cursor.insertText(prefix, self._timestamp_fmt)
        text_start = cursor.position()
        self._insert_highlighted_text(cursor, text)
        return text_start, cursor.position()

    def _patch_last_render_chunk(self, text: str) -> tuple[bool, tuple[int, int] | None]:
        specs = getattr(self, "_last_render_chunk_specs", [])
        if not specs:
            return False, None

        document = self.subtitle_text.document()
        if document is None:
            return False, None

        start_pos = sum(
            len(sep) + len(prefix) + len(chunk_text)
            for sep, prefix, chunk_text in specs[:-1]
        )
        cursor = self.subtitle_text.textCursor()
        cursor.setPosition(start_pos)
        cursor.setPosition(
            document.characterCount() - 1,
            QTextCursor.MoveMode.KeepAnchor,
        )
        cursor.removeSelectedText()

        separator, prefix, _old_text = specs[-1]
        span = self._insert_render_chunk(cursor, separator, prefix, text)
        specs[-1] = (separator, prefix, text)
        self._last_render_chunk_specs = specs
        return True, span

    def _select_rendered_entry_span(
        self,
        entry_index: int,
        char_start: int | None = None,
        char_length: int | None = None,
    ) -> bool:
        spans = getattr(self, "_rendered_entry_text_spans", {})
        if entry_index not in spans:
            return False

        entry_start, entry_end = spans[entry_index]
        start = entry_start
        end = entry_end
        if char_start is not None and char_length is not None:
            start = min(max(entry_start, entry_start + int(char_start)), entry_end)
            end = min(max(start, start + int(char_length)), entry_end)

        cursor = self.subtitle_text.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.subtitle_text.setTextCursor(cursor)
        self.subtitle_text.ensureCursorVisible()
        return True

    def _focus_loaded_session_result(self, entry_index: int, query: str = "") -> None:
        if entry_index < 0:
            return

        self._search_focus_entry_index = entry_index
        self._pending_search_focus_query = query
        self._refresh_text(force_full=True)

        char_start = None
        char_length = None
        normalized_query = str(query or "").strip()
        entry_text = self._get_global_entry_text(entry_index)

        if normalized_query and entry_text:
            lowered_text = entry_text.lower()
            lowered_query = normalized_query.lower()
            found_at = lowered_text.find(lowered_query)
            if found_at >= 0:
                char_start = found_at
                char_length = len(normalized_query)

        self._select_rendered_entry_span(entry_index, char_start, char_length)
        self._search_focus_entry_index = None
        self._pending_search_focus_query = ""

    def _render_subtitles(self, force_full: bool = False) -> None:
        scrollbar = self.subtitle_text.verticalScrollBar()
        assert scrollbar is not None
        preserve_scroll = bool(getattr(self, "_user_scrolled_up", False))
        saved_scroll = 0
        if preserve_scroll:
            saved_scroll = scrollbar.value()
            scrollbar.blockSignals(True)

        total_count = 0
        render_offset = 0
        anchor_index = None
        search_matches = list(getattr(self, "search_matches", []))
        search_idx = int(getattr(self, "search_idx", 0))
        search_frame = getattr(self, "search_frame", None)
        if (
            search_frame is not None
            and search_frame.isVisible()
            and search_matches
            and 0 <= search_idx < len(search_matches)
        ):
            anchor_index = search_matches[search_idx].entry_index
        else:
            focus_entry_index = getattr(self, "_search_focus_entry_index", None)
            if focus_entry_index is not None:
                anchor_index = int(focus_entry_index)
        total_count = self._get_global_subtitle_count()
        render_end = total_count
        if total_count > Config.MAX_RENDER_ENTRIES:
            if anchor_index is None:
                render_offset = total_count - Config.MAX_RENDER_ENTRIES
            else:
                max_offset = max(0, total_count - Config.MAX_RENDER_ENTRIES)
                render_offset = min(
                    max(0, anchor_index - (Config.MAX_RENDER_ENTRIES // 2)),
                    max_offset,
                )
            render_end = min(total_count, render_offset + Config.MAX_RENDER_ENTRIES)
        subtitles_copy = self._read_global_entries_window(
            render_offset,
            render_end,
            clone_entries=False,
        )

        visible_count = len(subtitles_copy)
        last_text = subtitles_copy[-1].text if subtitles_copy else ""

        timestamp_action = getattr(self, "timestamp_action", None)
        show_ts = bool(timestamp_action.isChecked()) if timestamp_action else False

        if not hasattr(self, "_last_printed_ts"):
            self._last_printed_ts = None

        previous_visible_count = max(
            0, self._last_rendered_count - getattr(self, "_last_render_offset", 0)
        )
        offset_changed = render_offset != getattr(self, "_last_render_offset", 0)
        show_ts_changed = (
            self._last_render_show_ts is not None and show_ts != self._last_render_show_ts
        )
        tail_text_changed = (
            total_count == self._last_rendered_count
            and last_text != self._last_rendered_last_text
        )

        needs_full_render = (
            force_full
            or offset_changed
            or show_ts_changed
            or (total_count < self._last_rendered_count)
            or (previous_visible_count > visible_count)
        )

        if needs_full_render:
            self.subtitle_text.clear()
            self._last_printed_ts = None
            cursor = self.subtitle_text.textCursor()
            chunk_specs: list[tuple[str, str, str]] = []
            text_spans: dict[int, tuple[int, int]] = {}
            last_printed_ts = None

            for i, entry in enumerate(subtitles_copy):
                prev_entry = subtitles_copy[i - 1] if i > 0 else None
                separator, prefix, last_printed_ts = self._build_render_chunk(
                    entry,
                    prev_entry,
                    show_ts,
                    last_printed_ts,
                )
                span = self._insert_render_chunk(cursor, separator, prefix, entry.text)
                chunk_specs.append((separator, prefix, entry.text))
                text_spans[render_offset + i] = span

            self._last_printed_ts = last_printed_ts
            self._last_render_chunk_specs = chunk_specs
            self._rendered_entry_text_spans = text_spans

        elif tail_text_changed and visible_count == previous_visible_count and visible_count > 0:
            patched, span = self._patch_last_render_chunk(last_text)
            if not patched:
                self._render_subtitles(force_full=True)
                return
            if span is not None:
                spans = dict(getattr(self, "_rendered_entry_text_spans", {}))
                spans[render_offset + visible_count - 1] = span
                self._rendered_entry_text_spans = spans

        else:
            cursor = self.subtitle_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            chunk_specs = list(getattr(self, "_last_render_chunk_specs", []))
            text_spans = dict(getattr(self, "_rendered_entry_text_spans", {}))
            last_printed_ts = self._last_printed_ts

            start_local_idx = min(previous_visible_count, visible_count)
            for local_idx in range(start_local_idx, visible_count):
                entry = subtitles_copy[local_idx]
                prev_entry = subtitles_copy[local_idx - 1] if local_idx > 0 else None
                separator, prefix, last_printed_ts = self._build_render_chunk(
                    entry,
                    prev_entry,
                    show_ts,
                    last_printed_ts,
                )
                span = self._insert_render_chunk(cursor, separator, prefix, entry.text)
                chunk_specs.append((separator, prefix, entry.text))
                text_spans[render_offset + local_idx] = span

            self._last_printed_ts = last_printed_ts
            self._last_render_chunk_specs = chunk_specs
            self._rendered_entry_text_spans = {
                idx: span
                for idx, span in text_spans.items()
                if render_offset <= idx < render_offset + visible_count
            }

        self._last_rendered_count = total_count
        self._last_rendered_last_text = last_text
        self._last_render_offset = render_offset
        self._last_render_show_ts = show_ts

        auto_scroll_check = getattr(self, "auto_scroll_check", None)
        if auto_scroll_check is not None and auto_scroll_check.isChecked() and not preserve_scroll:
            self.subtitle_text.moveCursor(QTextCursor.MoveOperation.End)

        if preserve_scroll:
            scrollbar.setValue(min(saved_scroll, scrollbar.maximum()))
            scrollbar.blockSignals(False)

    def _on_scroll_changed(self) -> None:
        scrollbar = self.subtitle_text.verticalScrollBar()
        assert scrollbar is not None
        at_bottom = scrollbar.value() >= scrollbar.maximum() - Config.SCROLL_BOTTOM_THRESHOLD

        if at_bottom:
            self._user_scrolled_up = False
            if hasattr(self, "scroll_to_bottom_btn"):
                self.scroll_to_bottom_btn.hide()
        else:
            self._user_scrolled_up = True
            if self.is_running and hasattr(self, "scroll_to_bottom_btn"):
                self.scroll_to_bottom_btn.show()

    def _scroll_to_bottom(self) -> None:
        self._user_scrolled_up = False
        self.subtitle_text.moveCursor(QTextCursor.MoveOperation.End)
        if hasattr(self, "scroll_to_bottom_btn"):
            self.scroll_to_bottom_btn.hide()

    def _toggle_stats_panel(self) -> None:
        if hasattr(self, "stats_group") and hasattr(self, "toggle_stats_btn"):
            is_visible = self.stats_group.isVisible()
            self.stats_group.setVisible(not is_visible)
            if is_visible:
                self.toggle_stats_btn.setText("📊 통계 보이기")
                self.main_splitter.setSizes([1080, 0])
            else:
                self.toggle_stats_btn.setText("📊 통계 숨기기")
                self.main_splitter.setSizes([860, 220])

    def _refresh_text(self, force_full: bool = False) -> None:
        self._render_subtitles(force_full=force_full)

    def _refresh_text_full(self, *_args) -> None:
        self._refresh_text(force_full=True)

    def _update_stats(self) -> None:
        self._update_stats_now()

    def _finalize_subtitle(self, text):
        if not text:
            return
        text = str(text).strip()
        if not text:
            return

        last_processed_raw = self.__dict__.get("_last_processed_raw", "")
        capture_state = self.__dict__.get("capture_state")
        capture_last_processed_raw = (
            getattr(capture_state, "last_processed_raw", "") if capture_state is not None else ""
        )
        if text == last_processed_raw or text == capture_last_processed_raw:
            return

        self.subtitle_processor.add_confirmed(text)
        now = datetime.now()
        new_part = text
        force_new_entry = False

        with self.subtitle_lock:
            if self.subtitles:
                last_text = self.subtitles[-1].text
                new_part = utils.get_word_diff(last_text, text)
                if new_part:
                    new_part = new_part.strip()
                if new_part:
                    force_new_entry = (
                        len(last_text) + len(new_part) > Config.STREAM_SUBTITLE_MAX_LENGTH
                    )
                else:
                    self.subtitles[-1].end_time = now
                    return

        result = self._append_text_to_subtitles_shared(
            new_part,
            now=now,
            force_new_entry=force_new_entry,
        )
        if result.get("changed"):
            self.capture_state.last_processed_raw = text
            self._last_processed_raw = text

    def _insert_highlighted_text(self, cursor, text):
        text = self._normalize_subtitle_text_for_option(text)
        if not text:
            return
        if not self._keyword_pattern:
            cursor.insertText(text, self._normal_fmt)
            return

        parts = self._keyword_pattern.split(text)
        for part in parts:
            if not part:
                continue
            if part.lower() in self._keywords_lower_set:
                cursor.insertText(part, self._highlight_fmt)
            else:
                cursor.insertText(part, self._normal_fmt)

    def _toggle_theme_from_button(self) -> None:
        self._toggle_theme()
        if hasattr(self, "theme_toggle_btn"):
            self.theme_toggle_btn.setText("🌙" if self.is_dark_theme else "☀️")

    def _update_stats_now(self) -> None:
        if any(
            self.__dict__.get(name) is None
            for name in ("stat_time", "stat_chars", "stat_words", "stat_sents", "stat_cpm")
        ):
            return
        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            h, r = divmod(elapsed, 3600)
            m, s = divmod(r, 60)
            self.stat_time.setText(f"⏱️ 실행 시간: {h:02d}:{m:02d}:{s:02d}")

            subtitle_count = self._get_global_subtitle_count()
            total_chars = self._get_global_total_chars()
            total_words = self._get_global_total_words()

            self.stat_chars.setText(f"📝 글자 수: {total_chars:,}")
            self.stat_words.setText(f"📖 공백 기준 단어 수: {total_words:,}")
            self.stat_sents.setText(f"💬 문장 수: {subtitle_count}")

            if elapsed > 0:
                cpm = int(total_chars / (elapsed / 60))
                self.stat_cpm.setText(f"⚡ 분당 글자: {cpm}")
