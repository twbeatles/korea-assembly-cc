# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import time
from datetime import datetime

from PyQt6.QtGui import QTextCursor

from core import utils
from core.config import Config
from core.models import SubtitleEntry
from ui.main_window_impl.contracts import ViewRenderHost


ViewRenderBase = object


class MainWindowViewRenderMixin(ViewRenderBase):
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
        with self.subtitle_lock:
            if 0 <= entry_index < len(self.subtitles):
                entry_text = self._normalize_subtitle_text_for_option(
                    self.subtitles[entry_index].text
                )
            else:
                entry_text = ""

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

        with self.subtitle_lock:
            subtitles_copy = [entry.clone() for entry in self.subtitles]

        total_count = len(subtitles_copy)
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
        if total_count > Config.MAX_RENDER_ENTRIES:
            if anchor_index is None:
                render_offset = total_count - Config.MAX_RENDER_ENTRIES
            else:
                max_offset = max(0, total_count - Config.MAX_RENDER_ENTRIES)
                render_offset = min(
                    max(0, anchor_index - (Config.MAX_RENDER_ENTRIES // 2)),
                    max_offset,
                )
            subtitles_copy = subtitles_copy[render_offset:]

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

    def _update_stats(self):
        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            h, r = divmod(elapsed, 3600)
            m, s = divmod(r, 60)
            self.stat_time.setText(f"⏱️ 실행 시간: {h:02d}:{m:02d}:{s:02d}")

            with self.subtitle_lock:
                subtitle_count = len(self.subtitles)

            total_chars = self._cached_total_chars
            total_words = self._cached_total_words

            self.stat_chars.setText(f"📝 글자 수: {total_chars:,}")
            self.stat_words.setText(f"📖 공백 기준 단어 수: {total_words:,}")
            self.stat_sents.setText(f"💬 문장 수: {subtitle_count}")

            if elapsed > 0:
                cpm = int(total_chars / (elapsed / 60))
                self.stat_cpm.setText(f"⚡ 분당 글자: {cpm}")
