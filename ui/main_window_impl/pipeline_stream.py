# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import queue
from datetime import datetime
from importlib import import_module

from core import utils
from core.config import Config
from core.live_capture import clear_live_capture_ledger
from core.logging_utils import logger
from core.models import SubtitleEntry
from core.subtitle_pipeline import apply_keepalive, create_empty_capture_state
from ui.main_window_impl.contracts import PipelineStreamHost


def _pipeline_public():
    return import_module("ui.main_window_pipeline")


PipelineStreamBase = object


class MainWindowPipelineStreamMixin(PipelineStreamBase):
    def _join_stream_text(self, base: str, addition: str) -> str:
        """스트리밍 텍스트를 공백/문장부호를 보존해 결합한다."""
        left = str(base or "")
        right = str(addition or "")
        if not left:
            return right.strip()
        if not right:
            return left.strip()

        left = left.rstrip()
        right = right.lstrip()
        if not left:
            return right
        if not right:
            return left

        no_space_before = set(".,!?;:)]}%\"'”’…")
        no_space_after = set("([{<\"'“‘")
        if right[0] in no_space_before or left[-1] in no_space_after:
            return left + right
        return left + " " + right

    def _write_realtime_line(self, line: str) -> None:
        if not line or not self.realtime_file:
            return
        try:
            self.realtime_file.write(line)
            self.realtime_file.flush()
            self._realtime_error_count = 0
        except OSError as e:
            self._disable_realtime_save_for_run(
                message=str(e),
                toast_message="실시간 저장 쓰기 실패로 이번 실행의 실시간 저장을 중단합니다.",
                error=e,
            )

    def _append_text_to_subtitles_shared(
        self,
        text: str,
        *,
        now: datetime | None = None,
        force_new_entry: bool = False,
        refresh: bool = True,
        check_alert: bool = True,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "changed": False,
            "action": "noop",
            "entry": None,
            "realtime_line": "",
            "new_text": "",
        }
        if not text or not utils.is_meaningful_subtitle_text(text):
            return result

        new_text = text.strip()
        if not new_text:
            return result

        now = now or datetime.now()
        realtime_line = ""
        entry: SubtitleEntry | None = None

        with self.subtitle_lock:
            if self.subtitles and not force_new_entry:
                last_entry = self.subtitles[-1]
                if self._should_merge_entry(last_entry, new_text, now):
                    old_chars = last_entry.char_count
                    old_words = last_entry.word_count
                    last_entry.update_text(self._join_stream_text(last_entry.text, new_text))
                    last_entry.end_time = now
                    self._cached_total_chars += last_entry.char_count - old_chars
                    self._cached_total_words += last_entry.word_count - old_words
                    realtime_line = f"+ {new_text}\n"
                    entry = last_entry
                    result.update(
                        changed=True,
                        action="update",
                        entry=entry,
                        realtime_line=realtime_line,
                        new_text=new_text,
                    )
                else:
                    entry = SubtitleEntry(new_text, now)
                    entry.start_time = now
                    entry.end_time = now
                    self.subtitles.append(entry)
                    self._cached_total_chars += entry.char_count
                    self._cached_total_words += entry.word_count
                    realtime_line = f"[{entry.timestamp.strftime('%H:%M:%S')}] {new_text}\n"
                    result.update(
                        changed=True,
                        action="append",
                        entry=entry,
                        realtime_line=realtime_line,
                        new_text=new_text,
                    )
            else:
                entry = SubtitleEntry(new_text, now)
                entry.start_time = now
                entry.end_time = now
                self.subtitles.append(entry)
                self._cached_total_chars += entry.char_count
                self._cached_total_words += entry.word_count
                realtime_line = f"[{entry.timestamp.strftime('%H:%M:%S')}] {new_text}\n"
                result.update(
                    changed=True,
                    action="append",
                    entry=entry,
                    realtime_line=realtime_line,
                    new_text=new_text,
                )

        if not result["changed"]:
            return result

        if check_alert:
            self._check_keyword_alert(new_text)
        self._mark_runtime_tail_dirty()
        self._mark_session_dirty()
        self._invalidate_destructive_undo()
        self._schedule_initial_recovery_snapshot_if_needed(
            self._build_prepared_entries_snapshot()
        )
        self._schedule_ui_refresh(count=True)
        if refresh:
            self._schedule_ui_refresh(render=True, force_full=False)
        self._write_realtime_line(realtime_line)
        if str(result.get("action", "")) == "append":
            self._maybe_schedule_runtime_segment_flush()
        return result

    def _process_subtitle_segments(self, data) -> None:
        if not data:
            return
        if isinstance(data, (list, tuple)):
            for item in data:
                if item:
                    prepared = self._prepare_preview_raw(item)
                    if prepared:
                        self._process_raw_text(prepared)
            return
        if isinstance(data, str):
            prepared = self._prepare_preview_raw(data)
            if prepared:
                self._process_raw_text(prepared)

    def _prepare_preview_raw(self, raw):
        if raw is None:
            return None

        normalized = self._normalize_subtitle_text_for_option(raw).strip()
        if not normalized:
            return None

        raw_compact = utils.compact_subtitle_text(normalized)
        if not raw_compact:
            return None

        def accept(text: str):
            self._preview_desync_count = 0
            self._preview_ambiguous_skip_count = 0
            self._last_good_raw_compact = raw_compact
            return text

        suffix = self._trailing_suffix
        if not suffix:
            return accept(normalized)

        first_pos = raw_compact.find(suffix)
        if first_pos < 0:
            delta = self._extract_stream_delta(normalized, self._last_raw_text)
            if isinstance(delta, str):
                delta = delta.strip()
                if len(delta) >= 1 and len(delta) < len(normalized):
                    return accept(delta)
                if not delta:
                    pass

            history_anchor = self._confirmed_history_compact_tail(
                max_entries=8, max_compact_len=3000
            )
            incremental = self._slice_incremental_part(
                normalized,
                history_anchor,
                raw_compact,
                min_anchor=20,
                min_overlap=8,
            )
            if isinstance(incremental, str):
                incremental = incremental.strip()
                if len(incremental) >= 1 and len(incremental) < len(normalized):
                    return accept(incremental)
                if not incremental:
                    return None

            self._preview_desync_count += 1
            if self._preview_desync_count >= self._preview_resync_threshold:
                logger.warning(
                    "preview suffix desync reset: count=%s", self._preview_desync_count
                )
                self._soft_resync()
                return accept(normalized)
            return None

        last_pos = raw_compact.rfind(suffix)
        if first_pos != last_pos:
            predicted_append = len(raw_compact) - (first_pos + len(suffix))
            large_append_threshold = max(200, len(raw_compact) // 3)
            if predicted_append > large_append_threshold:
                incremental = self._slice_incremental_part(
                    normalized,
                    suffix,
                    raw_compact,
                    min_anchor=20,
                    min_overlap=8,
                )
                if isinstance(incremental, str):
                    incremental = incremental.strip()
                    if len(incremental) >= 1 and len(incremental) < len(normalized):
                        return accept(incremental)
                    if not incremental:
                        return None

                self._preview_ambiguous_skip_count += 1
                if (
                    self._preview_ambiguous_skip_count
                    >= self._preview_ambiguous_resync_threshold
                ):
                    logger.warning(
                        "preview ambiguous suffix reset: count=%s, predicted_append=%s",
                        self._preview_ambiguous_skip_count,
                        predicted_append,
                    )
                    self._soft_resync()
                    return accept(normalized)
                return None

        return accept(normalized)

    def _drain_pending_previews(
        self, max_items: int = 2000, requeue_others: bool = True
    ) -> None:
        drained = 0
        pending: list[object] = []
        try:
            while drained < max_items:
                raw_item = self.message_queue.get_nowait()
                decoded = self._unwrap_message_item(raw_item)
                if decoded is None:
                    drained += 1
                    continue
                msg_type, data = decoded
                if msg_type == "preview":
                    if isinstance(data, dict):
                        self._apply_structured_preview_payload(data)
                    else:
                        prepared = self._prepare_preview_raw(data)
                        if prepared:
                            self._process_raw_text(prepared)
                        elif data:
                            forced = self._normalize_subtitle_text_for_option(data).strip()
                            if forced:
                                self._process_raw_text(forced)
                elif msg_type == "subtitle_reset":
                    self._schedule_deferred_subtitle_reset(str(data or "drain"))
                elif msg_type == "keepalive":
                    self._handle_keepalive(str(data or ""))
                elif msg_type == "subtitle_segments":
                    self._process_subtitle_segments(data)
                else:
                    pending.append(raw_item)
                drained += 1
        except queue.Empty:
            pass

        drained += self._drain_coalesced_worker_messages(
            max_items=max(0, max_items - drained),
            allowed_types={"keepalive", "preview", "resolved_url", "status"},
        )

        if drained >= max_items:
            logger.warning("preview 큐 소진 제한 도달: max_items=%s", max_items)

        if requeue_others and pending:
            for item in pending:
                self._requeue_message_item(item)

    def _finalize_pending_subtitle(self) -> None:
        if self.last_subtitle:
            self._finalize_subtitle(self.last_subtitle)
            self.last_subtitle = ""
            self._stream_start_time = None
            self._clear_preview()

    def _reset_stream_state_after_subtitle_change(
        self, keep_history_from_subtitles: bool
    ) -> None:
        self._ensure_capture_runtime_state()
        self.last_subtitle = ""
        self._stream_start_time = None
        self._last_raw_text = ""
        self._last_processed_raw = ""
        self._preview_desync_count = 0
        self._preview_ambiguous_skip_count = 0
        self._last_good_raw_compact = ""
        self.capture_state.preview_text = ""
        self.capture_state.last_observed_raw = ""
        self.capture_state.last_processed_raw = ""
        self.capture_state.preview_desync_count = 0
        self.capture_state.preview_ambiguous_skip_count = 0
        self.capture_state.last_committed_reset_at = None
        self.live_capture_ledger = clear_live_capture_ledger()
        self._cancel_scheduled_subtitle_reset()
        self._clear_preview()

        if keep_history_from_subtitles:
            self._soft_resync()
        else:
            self._confirmed_compact = ""
            self._trailing_suffix = ""

    def _replace_subtitles_and_refresh(
        self, new_subtitles: list, keep_history_from_subtitles: bool | None = None
    ) -> None:
        pipeline_mod = _pipeline_public()
        if keep_history_from_subtitles is None:
            keep_history_from_subtitles = bool(new_subtitles)

        entries = new_subtitles if isinstance(new_subtitles, list) else list(new_subtitles)
        self.capture_state = create_empty_capture_state()
        self.capture_state.entries = entries
        self._bind_subtitles_to_capture_state()
        if keep_history_from_subtitles and self.capture_state.entries:
            pipeline_mod.rebuild_confirmed_history(
                self.capture_state,
                self._current_capture_settings(),
            )

        self._reset_stream_state_after_subtitle_change(
            keep_history_from_subtitles=keep_history_from_subtitles
        )
        self.search_matches = []
        self.search_idx = 0
        self._runtime_search_revision += 1
        self._runtime_search_in_progress = False
        self._runtime_search_query = ""
        self._runtime_search_truncated = False
        self._runtime_search_requested_query = ""
        self._invalidate_runtime_segment_caches()
        self._mark_runtime_tail_dirty()
        search_count = self.__dict__.get("search_count")
        if search_count is not None:
            search_count.setText("")
        self._search_focus_entry_index = None
        self._pending_search_focus_query = ""
        self._rebuild_stats_cache()
        self._schedule_ui_refresh(
            search_count=True,
            render=True,
            force_full=True,
            count=True,
        )

    def _should_merge_entry(
        self, last_entry: SubtitleEntry, new_text: str, now: datetime
    ) -> bool:
        if not last_entry or not new_text:
            return False
        if last_entry.end_time is None:
            return False
        if (now - last_entry.end_time).total_seconds() > Config.ENTRY_MERGE_MAX_GAP:
            return False
        if len(last_entry.text) + 1 + len(new_text) > Config.ENTRY_MERGE_MAX_CHARS:
            return False
        return True

    def _confirmed_history_compact_tail(
        self, max_entries: int = 10, max_compact_len: int = 3000
    ) -> str:
        with self.subtitle_lock:
            if not self.subtitles:
                return ""
            tail_entries = self.subtitles[-max_entries:]
            combined = " ".join(e.text for e in tail_entries if e and e.text)

        compact = utils.compact_subtitle_text(combined)
        if max_compact_len > 0 and len(compact) > max_compact_len:
            compact = compact[-max_compact_len:]
        return compact

    def _slice_incremental_part(
        self,
        raw: str,
        anchor_compact: str,
        raw_compact: str,
        min_anchor: int = 12,
        min_overlap: int = 4,
    ):
        if not raw or not anchor_compact or not raw_compact:
            return None
        if len(anchor_compact) >= min_anchor:
            idx = raw_compact.rfind(anchor_compact)
            if idx != -1:
                return utils.slice_from_compact_index(raw, idx + len(anchor_compact)).strip()
        overlap_len = utils.find_compact_suffix_prefix_overlap(
            anchor_compact, raw_compact, min_overlap=min_overlap
        )
        if overlap_len > 0:
            return utils.slice_from_compact_index(raw, overlap_len).strip()
        return None

    def _extract_stream_delta(self, raw: str, last_raw: str):
        if not last_raw:
            return None

        raw_compact = utils.compact_subtitle_text(raw)
        last_compact = utils.compact_subtitle_text(last_raw)
        if not raw_compact or not last_compact:
            return ""
        if raw_compact == last_compact:
            return ""
        if last_compact in raw_compact:
            idx = raw_compact.rfind(last_compact)
            start = idx + len(last_compact)
            if start <= 0 or start >= len(raw_compact):
                return ""
            return utils.slice_from_compact_index(raw, start).strip()
        if utils.is_continuation_text(last_raw, raw):
            return ""
        return None

    def _process_raw_text(self, raw):
        if not raw:
            return

        raw = raw.strip()
        if raw == self._last_raw_text:
            return
        self._last_raw_text = raw

        raw_compact = utils.compact_subtitle_text(raw)
        if not raw_compact:
            return

        new_part = self._extract_new_part(raw, raw_compact)
        if not new_part:
            return
        new_part = new_part.strip()
        if not utils.is_meaningful_subtitle_text(new_part):
            return

        with self.subtitle_lock:
            last_text = self.subtitles[-1].text if self.subtitles else ""

        if last_text:
            refined_part = utils.get_word_diff(last_text, new_part)
            if not refined_part:
                return
            refined_part = refined_part.strip()
            if not utils.is_meaningful_subtitle_text(refined_part):
                return
            new_part = refined_part

        new_compact = utils.compact_subtitle_text(new_part)
        recent_compact_tail = self._confirmed_history_compact_tail(
            max_entries=12, max_compact_len=5000
        )
        if len(new_compact) >= 20 and recent_compact_tail and new_compact in recent_compact_tail:
            return

        self._confirmed_compact += new_compact
        self._trim_confirmed_compact_history()

        if len(self._confirmed_compact) >= self._suffix_length:
            self._trailing_suffix = self._confirmed_compact[-self._suffix_length :]
        else:
            self._trailing_suffix = self._confirmed_compact

        self._add_text_to_subtitles(new_part)
        self._last_processed_raw = raw
        self.capture_state.last_processed_raw = raw

    def _trim_confirmed_compact_history(self) -> None:
        try:
            max_len = int(Config.CONFIRMED_COMPACT_MAX_LEN)
        except Exception:
            max_len = 0
        if max_len > 0 and len(self._confirmed_compact) > max_len:
            self._confirmed_compact = self._confirmed_compact[-max_len:]

    def _extract_new_part(self, raw: str, raw_compact: str) -> str:
        if not self._trailing_suffix:
            return raw
        pos = raw_compact.rfind(self._trailing_suffix)
        if pos >= 0:
            start_idx = pos + len(self._trailing_suffix)
            if start_idx >= len(raw_compact):
                return ""
            return utils.slice_from_compact_index(raw, start_idx)
        return raw

    def _soft_resync(self) -> None:
        with self.subtitle_lock:
            if self.subtitles:
                recent = " ".join(e.text for e in self.subtitles[-5:] if e and e.text)
                self._confirmed_compact = utils.compact_subtitle_text(recent)
                self._trim_confirmed_compact_history()
                if len(self._confirmed_compact) >= self._suffix_length:
                    self._trailing_suffix = self._confirmed_compact[-self._suffix_length :]
                else:
                    self._trailing_suffix = self._confirmed_compact
                logger.info(
                    "소프트 리셋: suffix=%s",
                    self._trailing_suffix[-20:] if self._trailing_suffix else "(empty)",
                )
            else:
                self._confirmed_compact = ""
                self._trailing_suffix = ""
                logger.info("소프트 리셋: 자막 없음, 전체 리셋")

    def _find_overlap(self, suffix: str, text: str) -> int:
        max_overlap = min(len(suffix), len(text))
        for i in range(max_overlap, 0, -1):
            if suffix[-i:] == text[:i]:
                return i
        return 0

    def _add_text_to_subtitles(self, text: str) -> None:
        self._append_text_to_subtitles_shared(text, now=datetime.now())

    def _handle_keepalive(self, raw: str) -> None:
        if not raw:
            return

        self._ensure_capture_runtime_state()
        result = apply_keepalive(self.capture_state, raw, datetime.now())
        if result.changed:
            return

        if self.last_subtitle:
            return
        raw_compact = utils.compact_subtitle_text(raw)
        if not raw_compact:
            return

        with self.subtitle_lock:
            if not self.subtitles:
                return
            last_entry = self.subtitles[-1]
            last_compact = utils.compact_subtitle_text(last_entry.text)
            if raw_compact != last_compact:
                return
            last_entry.end_time = datetime.now()
