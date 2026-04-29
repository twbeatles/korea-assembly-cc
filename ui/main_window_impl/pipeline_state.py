# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

from datetime import datetime
from importlib import import_module
from typing import Any

from PyQt6.QtCore import QTimer

from core import utils
from core.config import Config
from core.live_capture import (
    clear_live_capture_ledger,
    create_empty_live_capture_ledger,
    get_live_row,
    mark_live_row_committed,
    normalize_capture_event,
    reconcile_live_capture,
    set_live_row_baseline,
)
from core.logging_utils import logger
from core.models import CaptureSessionState, ObservedSubtitleRow, SubtitleEntry
from core.subtitle_pipeline import (
    LiveRowCommitMeta,
    PipelineSourceMeta,
    apply_preview,
    apply_reset,
    commit_live_row,
    create_empty_capture_state,
    flush_pending_previews,
)
from ui.main_window_common import _ResetTimerShim
from ui.main_window_impl.contracts import PipelineStateHost


def _pipeline_public() -> Any:
    return import_module("ui.main_window_pipeline")


PipelineStateBase = object


class MainWindowPipelineStateMixin(PipelineStateBase):
    def _bind_subtitles_to_capture_state(self) -> None:
        state = self.__dict__.get("capture_state")
        if not isinstance(state, CaptureSessionState):
            return
        with self.subtitle_lock:
            if self.__dict__.get("subtitles") is not state.entries:
                self.subtitles = state.entries

    def _ensure_capture_runtime_state(self) -> None:
        pipeline_mod = _pipeline_public()
        capture_state = self.__dict__.get("capture_state")
        if not isinstance(capture_state, CaptureSessionState):
            state = create_empty_capture_state()
            existing_entries = self.__dict__.get("subtitles", [])
            if isinstance(existing_entries, list):
                state.entries = existing_entries
            else:
                state.entries = list(existing_entries)
            if state.entries:
                pipeline_mod.rebuild_confirmed_history(state)
            self.capture_state = state
        self._bind_subtitles_to_capture_state()
        state_dict = self.__dict__
        if "live_capture_ledger" not in state_dict:
            self.live_capture_ledger = create_empty_live_capture_ledger()
        if "_pending_subtitle_reset_source" not in state_dict:
            self._pending_subtitle_reset_source = ""
        if "_pending_subtitle_reset_timer" not in state_dict:
            try:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(self._commit_scheduled_subtitle_reset)
            except Exception:
                timer = _ResetTimerShim()
            self._pending_subtitle_reset_timer = timer

    def _current_capture_settings(self) -> dict[str, int | bool]:
        return {
            "merge_gap_seconds": int(Config.ENTRY_MERGE_MAX_GAP),
            "merge_max_chars": int(Config.ENTRY_MERGE_MAX_CHARS),
            "confirmed_compact_max_len": int(Config.CONFIRMED_COMPACT_MAX_LEN),
            "auto_clean_newlines": bool(self._is_auto_clean_newlines_enabled()),
        }

    def _sync_capture_state_entries(self, force_refresh: bool = False) -> None:
        self._ensure_capture_runtime_state()
        self._bind_subtitles_to_capture_state()
        self._rebuild_stats_cache()
        self._schedule_ui_refresh(
            count=True,
            render=True,
            force_full=force_refresh,
        )
        preview_text = (
            getattr(self.live_capture_ledger, "preview_text", "")
            or self.capture_state.preview_text
        )
        self._set_preview_text(preview_text)

    def _apply_capture_pipeline_refresh(
        self,
        *,
        preview_text: str,
        appended_entries: list[SubtitleEntry] | None = None,
        updated_existing: bool = False,
        force_refresh: bool = False,
    ) -> None:
        self._ensure_capture_runtime_state()
        self._bind_subtitles_to_capture_state()

        for entry in appended_entries or []:
            self._cached_total_chars += entry.char_count
            self._cached_total_words += entry.word_count

        if updated_existing:
            self._rebuild_stats_cache()

        if appended_entries or updated_existing:
            self._mark_runtime_tail_dirty()
            self._schedule_ui_refresh(
                count=True,
                render=True,
                force_full=force_refresh,
            )
            if appended_entries:
                self._maybe_schedule_runtime_segment_flush()

        self._set_preview_text(preview_text)

    def _cancel_scheduled_subtitle_reset(self) -> None:
        self._ensure_capture_runtime_state()
        if self._pending_subtitle_reset_timer.isActive():
            self._pending_subtitle_reset_timer.stop()
        self._pending_subtitle_reset_source = ""

    def _schedule_deferred_subtitle_reset(self, source: str) -> None:
        self._ensure_capture_runtime_state()
        if self._pending_subtitle_reset_timer.isActive():
            return
        self._pending_subtitle_reset_source = str(source or "")
        self._pending_subtitle_reset_timer.start(int(Config.SUBTITLE_RESET_GRACE_MS))

    def _commit_scheduled_subtitle_reset(self) -> None:
        self._ensure_capture_runtime_state()
        reset_timer = self._pending_subtitle_reset_timer
        timer_was_active = bool(reset_timer.isActive())
        if timer_was_active:
            reset_timer.stop()
        source = self._pending_subtitle_reset_source
        self._pending_subtitle_reset_source = ""
        if not source and not timer_was_active:
            return
        if not self.is_running:
            return
        apply_reset(
            self.capture_state,
            datetime.now(),
            self._current_capture_settings(),
        )
        self.live_capture_ledger = clear_live_capture_ledger()
        self._sync_capture_state_entries(force_refresh=False)
        if source:
            logger.info("subtitle_reset 적용: %s", source)

    def _commit_scheduled_subtitle_reset_before_preview(self) -> None:
        self._ensure_capture_runtime_state()
        reset_timer = self.__dict__.get("_pending_subtitle_reset_timer")
        if reset_timer is None:
            return
        try:
            is_active = bool(reset_timer.isActive())
        except Exception:
            is_active = False
        if not is_active:
            return
        self._commit_scheduled_subtitle_reset()

    def _format_subtitle_reset_source(
        self,
        data: object,
        default: str = "subtitle_reset",
    ) -> str:
        if not isinstance(data, dict):
            return str(data or default)
        source = str(data.get("source") or data.get("kind") or default)
        selector = str(data.get("selector") or "").strip()
        frame_path = data.get("frame_path", data.get("framePath", ""))
        previous_length = data.get("previous_length", data.get("previousLength", ""))
        parts = [source]
        if selector:
            parts.append(f"selector={selector}")
        if frame_path not in ("", None):
            parts.append(f"frame_path={frame_path}")
        if previous_length not in ("", None):
            parts.append(f"previous_length={previous_length}")
        return " ".join(parts)

    def _build_prepared_capture_state(self) -> CaptureSessionState:
        self._ensure_capture_runtime_state()
        return flush_pending_previews(
            self.capture_state,
            datetime.now(),
            self._current_capture_settings(),
        )

    def _materialize_pending_preview(self) -> None:
        self._ensure_capture_runtime_state()
        self.capture_state = self._build_prepared_capture_state()
        self._sync_capture_state_entries(force_refresh=False)

    def _build_prepared_entries_snapshot(self) -> list[SubtitleEntry]:
        return self._build_prepared_capture_state().entries

    def _coerce_frame_path(self, value: object) -> tuple[int, ...]:
        if isinstance(value, tuple):
            raw_items = value
        elif isinstance(value, list):
            raw_items = tuple(value)
        else:
            return ()

        frame_path: list[int] = []
        for item in raw_items:
            try:
                frame_path.append(int(item))
            except Exception:
                continue
        return tuple(frame_path)

    def _coerce_observed_rows(self, rows: object) -> list[ObservedSubtitleRow]:
        observed: list[ObservedSubtitleRow] = []
        if not isinstance(rows, list):
            return observed

        for row in rows:
            if isinstance(row, ObservedSubtitleRow):
                text = self._normalize_subtitle_text_for_option(row.text).strip()
                if not utils.compact_subtitle_text(text):
                    continue
                observed.append(
                    ObservedSubtitleRow(
                        node_key=str(row.node_key or "").strip(),
                        text=text,
                        speaker_color=str(row.speaker_color or ""),
                        speaker_channel=row.speaker_channel,
                        unstable_key=bool(row.unstable_key),
                    )
                )
                continue

            if not isinstance(row, dict):
                continue

            node_key = str(row.get("node_key") or row.get("nodeKey") or "").strip()
            text = self._normalize_subtitle_text_for_option(
                row.get("text", "")
            ).strip()
            if not node_key or not utils.compact_subtitle_text(text):
                continue

            speaker_channel = str(
                row.get("speaker_channel") or row.get("speakerChannel") or "unknown"
            )
            if speaker_channel not in ("primary", "secondary", "unknown"):
                speaker_channel = "unknown"

            observed.append(
                ObservedSubtitleRow(
                    node_key=node_key,
                    text=text,
                    speaker_color=str(
                        row.get("speaker_color") or row.get("speakerColor") or ""
                    ),
                    speaker_channel=speaker_channel,
                    unstable_key=bool(
                        row.get("unstable_key") or row.get("unstableKey") or False
                    ),
                )
            )

        return observed

    def _build_preview_payload_from_probe(
        self,
        probe_result: dict[str, Any],
    ) -> dict[str, Any]:
        rows = [
            {
                "nodeKey": row.node_key,
                "text": row.text,
                "speakerColor": row.speaker_color,
                "speakerChannel": row.speaker_channel,
                "unstableKey": row.unstable_key,
            }
            for row in self._coerce_observed_rows(probe_result.get("rows", []))
        ]
        return {
            "raw": self._normalize_subtitle_text_for_option(
                probe_result.get("text", "")
            ).strip(),
            "rows": rows,
            "selector": str(
                probe_result.get("matched_selector") or probe_result.get("selector") or ""
            ),
            "frame_path": self._coerce_frame_path(
                probe_result.get("frame_path") or probe_result.get("framePath")
            ),
            "source_mode": str(
                probe_result.get("source_mode") or probe_result.get("sourceMode") or ""
            ),
        }

    def _apply_structured_preview_payload(
        self,
        payload: object,
        now: datetime | None = None,
    ) -> bool:
        if not isinstance(payload, dict):
            return False

        selector = str(
            payload.get("selector") or payload.get("matched_selector") or ""
        ).strip()
        frame_path = self._coerce_frame_path(
            payload.get("frame_path") or payload.get("framePath")
        )
        observed_rows = self._coerce_observed_rows(payload.get("rows", []))
        raw = self._normalize_subtitle_text_for_option(
            payload.get("raw") or payload.get("text") or ""
        ).strip()
        source_mode = str(
            payload.get("source_mode") or payload.get("sourceMode") or ""
        ).strip()

        self._ensure_capture_runtime_state()
        now = now or datetime.now()
        self._commit_scheduled_subtitle_reset_before_preview()

        event = normalize_capture_event(
            raw=raw,
            rows=observed_rows,
            selector=selector,
            frame_path=frame_path,
            timestamp=now.timestamp(),
        )
        reconciliation = reconcile_live_capture(self.live_capture_ledger, event)
        self.live_capture_ledger = reconciliation.ledger
        settings = self._current_capture_settings()
        changed = reconciliation.changed
        appended_entries: list[SubtitleEntry] = []
        updated_existing = False
        force_refresh = False

        if event.rows:
            for row_change in reconciliation.row_changes:
                live_row = get_live_row(self.live_capture_ledger, row_change.key)
                if not live_row:
                    continue

                baseline_compact = live_row.baseline_compact
                if baseline_compact is None:
                    baseline_compact = self.capture_state.confirmed_compact

                meta = LiveRowCommitMeta(
                    selector=live_row.selector or selector,
                    frame_path=live_row.frame_path or frame_path,
                    source_node_key=live_row.key,
                    source_entry_id=live_row.committed_entry_id or "",
                    speaker_color=live_row.speaker_color,
                    speaker_channel=live_row.speaker_channel,
                    source_mode=source_mode or event.capture_mode,
                    baseline_compact=baseline_compact,
                )
                result = commit_live_row(
                    self.capture_state,
                    live_row.text,
                    event.preview_text,
                    now,
                    settings,
                    meta=meta,
                )
                if result.reason == "row_entry_missing" and meta.source_entry_id:
                    result = commit_live_row(
                        self.capture_state,
                        live_row.text,
                        event.preview_text,
                        now,
                        settings,
                        meta=LiveRowCommitMeta(
                            selector=meta.selector,
                            frame_path=meta.frame_path,
                            source_node_key=meta.source_node_key,
                            speaker_color=meta.speaker_color,
                            speaker_channel=meta.speaker_channel,
                            source_mode=meta.source_mode,
                            baseline_compact=meta.baseline_compact,
                        ),
                    )

                changed = changed or result.changed
                if result.appended_entry:
                    appended_entries.append(result.appended_entry)
                elif result.updated_entry:
                    updated_existing = True
                committed_entry = result.updated_entry or result.appended_entry
                if committed_entry and committed_entry.entry_id:
                    self.live_capture_ledger = set_live_row_baseline(
                        self.live_capture_ledger,
                        row_change.key,
                        baseline_compact,
                    )
                    self.live_capture_ledger = mark_live_row_committed(
                        self.live_capture_ledger,
                        row_change.key,
                        committed_entry.entry_id,
                    )
                if (
                    result.updated_entry
                    and self.capture_state.entries
                    and result.updated_entry is not self.capture_state.entries[-1]
                ):
                    force_refresh = True

            self.capture_state.preview_text = event.preview_text
            self.capture_state.last_observed_raw = event.preview_text
            self.capture_state.last_processed_raw = event.preview_text
            self.capture_state.last_observer_event_at = now.timestamp()
            self.capture_state.last_committed_reset_at = None
            if selector:
                self.capture_state.current_selector = selector
            self.capture_state.current_frame_path = frame_path
        else:
            preview_result = apply_preview(
                self.capture_state,
                event.preview_text,
                now,
                settings,
                meta=PipelineSourceMeta(
                    selector=selector,
                    frame_path=frame_path,
                    source_mode=source_mode or event.capture_mode,
                ),
            )
            changed = changed or preview_result.changed
            if preview_result.appended_entry:
                appended_entries.append(preview_result.appended_entry)
            elif preview_result.updated_entry:
                updated_existing = True

        self._apply_capture_pipeline_refresh(
            preview_text=event.preview_text,
            appended_entries=appended_entries,
            updated_existing=updated_existing,
            force_refresh=force_refresh,
        )
        if appended_entries or updated_existing:
            self._mark_session_dirty()
            self._invalidate_destructive_undo()
            self._schedule_initial_recovery_snapshot_if_needed(
                self._build_prepared_entries_snapshot()
            )
        return changed
