# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_common import _ResetTimerShim
from ui.main_window_types import MainWindowHost

COALESCED_WORKER_MESSAGE_TYPES = {
    "connection_status",
    "keepalive",
    "preview",
    "reconnected",
    "reconnecting",
    "resolved_url",
    "status",
}
COALESCED_WORKER_MESSAGE_ORDER = (
    "resolved_url",
    "status",
    "connection_status",
    "reconnecting",
    "reconnected",
    "preview",
    "keepalive",
)


class MainWindowPipelineMixin(MainWindowHost):

    def _bind_subtitles_to_capture_state(self) -> None:
            if not hasattr(self, "capture_state") or not isinstance(
                self.capture_state, CaptureSessionState
            ):
                return
            with self.subtitle_lock:
                if getattr(self, "subtitles", None) is not self.capture_state.entries:
                    self.subtitles = self.capture_state.entries


    def _ensure_capture_runtime_state(self) -> None:
            if not hasattr(self, "capture_state") or not isinstance(
                self.capture_state, CaptureSessionState
            ):
                state = create_empty_capture_state()
                existing_entries = getattr(self, "subtitles", [])
                if isinstance(existing_entries, list):
                    state.entries = existing_entries
                else:
                    state.entries = list(existing_entries)
                if state.entries:
                    rebuild_confirmed_history(state)
                self.capture_state = state
            self._bind_subtitles_to_capture_state()
            if not hasattr(self, "live_capture_ledger"):
                self.live_capture_ledger = create_empty_live_capture_ledger()
            if not hasattr(self, "_pending_subtitle_reset_source"):
                self._pending_subtitle_reset_source = ""
            if not hasattr(self, "_pending_subtitle_reset_timer"):
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
            self._update_count_label()
            self._refresh_text(force_full=force_refresh)
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
                self._update_count_label()
                self._refresh_text(force_full=force_refresh)

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
            source = self._pending_subtitle_reset_source
            self._pending_subtitle_reset_source = ""
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
                    probe_result.get("matched_selector")
                    or probe_result.get("selector")
                    or ""
                ),
                "frame_path": self._coerce_frame_path(
                    probe_result.get("frame_path") or probe_result.get("framePath")
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

            self._ensure_capture_runtime_state()
            now = now or datetime.now()
            self._cancel_scheduled_subtitle_reset()

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
            return changed


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

    def _emit_worker_message(
            self,
            msg_type: str,
            data: Any,
            *,
            run_id: int | None = None,
        ) -> None:
            resolved_run_id = run_id if run_id is not None else self._ensure_active_capture_run()
            message = WorkerQueueMessage(int(resolved_run_id), str(msg_type), data)
            try:
                self.message_queue.put_nowait(message)
                return
            except queue.Full:
                if msg_type not in COALESCED_WORKER_MESSAGE_TYPES:
                    self.message_queue.put(message, timeout=1.0)
                    return

            lock = getattr(self, "_worker_message_lock", None)
            if lock is None:
                return
            with lock:
                self._coalesced_worker_messages[(int(resolved_run_id), str(msg_type))] = data

    def _unwrap_message_item(self, item: object) -> tuple[str, Any] | None:
            if isinstance(item, WorkerQueueMessage):
                if not self._is_active_capture_run(item.run_id):
                    return None
                return item.msg_type, item.payload
            if isinstance(item, tuple) and len(item) == 2:
                msg_type, data = item
                return str(msg_type), data
            return None

    def _pop_coalesced_worker_messages(
            self,
            *,
            max_items: int,
            allowed_types: set[str] | None = None,
        ) -> list[tuple[str, Any]]:
            active_run_id = getattr(self, "_active_capture_run_id", None)
            lock = getattr(self, "_worker_message_lock", None)
            if lock is None:
                return []
            if active_run_id is None:
                with lock:
                    getattr(self, "_coalesced_worker_messages", {}).clear()
                return []

            collected: list[tuple[str, Any]] = []
            with lock:
                pending_messages = getattr(self, "_coalesced_worker_messages", {})
                stale_keys = [
                    key
                    for key in pending_messages.keys()
                    if not isinstance(key, tuple) or key[0] != active_run_id
                ]
                for key in stale_keys:
                    pending_messages.pop(key, None)

                for msg_type in COALESCED_WORKER_MESSAGE_ORDER:
                    if allowed_types is not None and msg_type not in allowed_types:
                        continue
                    key = (active_run_id, msg_type)
                    if key not in pending_messages:
                        continue
                    collected.append((msg_type, pending_messages.pop(key)))
                    if len(collected) >= max_items:
                        break

            return collected

    def _drain_coalesced_worker_messages(
            self,
            *,
            max_items: int,
            allowed_types: set[str] | None = None,
            handler: Callable[[str, Any], None] | None = None,
        ) -> int:
            processed = 0
            drain_handler = handler or self._handle_message
            for msg_type, data in self._pop_coalesced_worker_messages(
                max_items=max_items,
                allowed_types=allowed_types,
            ):
                drain_handler(msg_type, data)
                processed += 1
            return processed

    def _write_realtime_line(self, line: str) -> None:
            if not line or not self.realtime_file:
                return
            try:
                self.realtime_file.write(line)
                self.realtime_file.flush()
                self._realtime_error_count = 0
            except IOError as e:
                self._realtime_error_count = getattr(self, "_realtime_error_count", 0) + 1
                if self._realtime_error_count >= 3:
                    logger.error(f"실시간 저장 연속 실패: {e}")
                else:
                    logger.warning(f"실시간 저장 쓰기 오류: {e}")

    def _append_text_to_subtitles_shared(
            self,
            text: str,
            *,
            now: datetime | None = None,
            force_new_entry: bool = False,
            refresh: bool = True,
            check_alert: bool = True,
        ) -> dict[str, Any]:
            """공유 append/update 로직.

            Returns:
                dict: changed/action/entry/realtime_line/new_text
            """
            result: dict[str, Any] = {
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
                        last_entry.update_text(
                            self._join_stream_text(last_entry.text, new_text)
                        )
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
            self._update_count_label()
            if refresh:
                self._refresh_text(force_full=False)
            self._write_realtime_line(realtime_line)
            return result


    def _clear_message_queue(self) -> None:
            """메시지 큐 비우기 (중지/재시작 안정성용)"""
            try:
                while True:
                    self.message_queue.get_nowait()
            except queue.Empty:
                pass
            lock = getattr(self, "_worker_message_lock", None)
            if lock is None:
                return
            with lock:
                getattr(self, "_coalesced_worker_messages", {}).clear()


    def _process_subtitle_segments(self, data) -> None:
            """세그먼트 형태로 들어온 자막 데이터를 처리한다."""
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
            """preview 입력을 정규화/게이팅하여 core 알고리즘에 전달할지 결정한다."""
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
                # 1차 fallback: 직전 raw 대비 증분(delta)만 추출
                delta = self._extract_stream_delta(normalized, self._last_raw_text)
                if isinstance(delta, str):
                    delta = delta.strip()
                    if len(delta) >= 1 and len(delta) < len(normalized):
                        return accept(delta)
                    if not delta:
                        pass

                # 2차 fallback: 최근 확정 히스토리 tail anchor로 증분 추출
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
            """큐에 남은 preview/segments 메시지를 소진해 마지막 자막 누락을 줄인다."""
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
                                forced = self._normalize_subtitle_text_for_option(
                                    data
                                ).strip()
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
                    self.message_queue.put_nowait(item)


    def _finalize_pending_subtitle(self) -> None:
            """남아있는 버퍼를 확정 처리 (종료/중지 안전성용)."""
            if self.last_subtitle:
                self._finalize_subtitle(self.last_subtitle)
                self.last_subtitle = ""
                self._stream_start_time = None
                self._clear_preview()


    def _reset_stream_state_after_subtitle_change(
            self, keep_history_from_subtitles: bool
        ) -> None:
            """외부 편집/로드 후 스트리밍 파이프라인 상태를 재동기화한다."""
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
            """자막 전체 교체 후 상태/통계/UI를 일관되게 갱신한다."""
            if keep_history_from_subtitles is None:
                keep_history_from_subtitles = bool(new_subtitles)

            entries = new_subtitles if isinstance(new_subtitles, list) else list(new_subtitles)
            self.capture_state = create_empty_capture_state()
            self.capture_state.entries = entries
            self._bind_subtitles_to_capture_state()
            if keep_history_from_subtitles and self.capture_state.entries:
                rebuild_confirmed_history(
                    self.capture_state,
                    self._current_capture_settings(),
                )

            self._reset_stream_state_after_subtitle_change(
                keep_history_from_subtitles=keep_history_from_subtitles
            )
            self.search_matches = []
            self.search_idx = 0
            search_count = self.__dict__.get("search_count")
            if search_count is not None:
                search_count.setText("")
            self._search_focus_entry_index = None
            self._pending_search_focus_query = ""
            self._rebuild_stats_cache()
            self._refresh_text(force_full=True)
            self._update_count_label()


    def _complete_loaded_session(self, payload: dict[str, Any]) -> bool:
            if not isinstance(payload, dict):
                return False

            session_version = str(payload.get("version", "unknown"))
            source_path = str(payload.get("path", "") or "")
            source_url = str(payload.get("url", "") or "")
            committee_name = str(payload.get("committee_name", "") or "")
            created_at = str(payload.get("created_at", "") or "")
            loaded_subtitles = payload.get("subtitles", [])
            skipped_items = int(payload.get("skipped", 0) or 0)
            highlight_sequence = int(payload.get("highlight_sequence", -1) or -1)
            highlight_query = str(payload.get("highlight_query", "") or "")

            if not isinstance(loaded_subtitles, list):
                return False

            if session_version != Config.VERSION:
                reply = QMessageBox.question(
                    self,
                    "버전 불일치",
                    f"세션 버전({session_version})이 현재 버전({Config.VERSION})과 다릅니다.\n"
                    "계속 불러오시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.No:
                    payload["_cancelled"] = True
                    self._set_status("세션 불러오기 취소됨 (버전 불일치)", "warning")
                    return False

            self._replace_subtitles_and_refresh(
                loaded_subtitles, keep_history_from_subtitles=bool(loaded_subtitles)
            )
            if source_url:
                self.url_combo.setCurrentText(source_url)
                self._add_to_history(source_url, committee_name)

            summary = f"세션 불러오기 완료! {len(self.subtitles)}개 문장"
            if skipped_items > 0:
                summary += f" (손상 항목 {skipped_items}개 제외)"
            self._set_status(summary, "success")
            self._show_toast(summary, "success")

            if highlight_sequence >= 0:
                self._focus_loaded_session_result(highlight_sequence, highlight_query)

            if source_path:
                logger.info("세션 불러오기 완료: %s", source_path)
            elif created_at:
                logger.info("세션 불러오기 완료: created_at=%s", created_at)
            return True


    def _process_message_queue(self):
            """메시지 큐 처리 (100ms마다 호출) - 예외 처리 강화"""
            try:
                deadline = time.perf_counter() + 0.008
                processed = 0
                while processed < 50 and time.perf_counter() <= deadline:
                    try:
                        raw_item = self.message_queue.get_nowait()
                        decoded = self._unwrap_message_item(raw_item)
                        if decoded is None:
                            processed += 1
                            continue
                        msg_type, data = decoded
                        self._handle_message(msg_type, data)
                        processed += 1
                    except queue.Empty:
                        break
                remaining_budget = max(0, 50 - processed)
                if remaining_budget > 0 and time.perf_counter() <= deadline:
                    processed += self._drain_coalesced_worker_messages(
                        max_items=remaining_budget,
                    )
            except Exception as e:
                logger.error(f"큐 처리 오류: {e}")


    def _handle_message(self, msg_type, data):
            """개별 메시지 처리"""
            try:
                if self._is_stopping and msg_type not in (
                    "db_task_result",
                    "db_task_error",
                    "session_save_done",
                    "session_save_failed",
                    "session_load_done",
                    "session_load_failed",
                    "session_load_json_error",
                ):
                    return
                if msg_type == "preview" and isinstance(data, dict):
                    self._apply_structured_preview_payload(data)
                    return
                if msg_type == "subtitle_reset":
                    logger.info("subtitle_reset 감지: %s", data)
                    self._schedule_deferred_subtitle_reset(str(data or "subtitle_reset"))
                    return
                if msg_type == "keepalive":
                    self._handle_keepalive(str(data or ""))
                    return
                if msg_type == "status":
                    status_text = str(data)[:200]
                    if status_text != self._last_status_message:
                        self.status_label.setText(status_text)
                        self._last_status_message = status_text

                elif msg_type == "resolved_url":
                    resolved_url = str(data or "").strip()
                    if resolved_url:
                        self.current_url = resolved_url
                        self._add_to_history(resolved_url)
                        idx = self.url_combo.findData(resolved_url)
                        if idx >= 0:
                            self.url_combo.setCurrentIndex(idx)
                        else:
                            self.url_combo.setEditText(resolved_url)

                elif msg_type == "toast":
                    # 다른 스레드에서 온 UI 알림은 Queue로 전달받아 UI 스레드에서 처리한다.
                    if isinstance(data, dict):
                        message = data.get("message", "")
                        toast_type = data.get("toast_type", "info")
                        duration = data.get("duration", 3000)
                    else:
                        message = data
                        toast_type = "info"
                        duration = 3000
                    try:
                        duration = int(duration) if duration is not None else 3000
                    except Exception:
                        duration = 3000
                    self._show_toast(str(message), str(toast_type), duration)

                elif msg_type == "preview":
                    if isinstance(data, dict):
                        self._apply_structured_preview_payload(data)
                    else:
                        prepared = self._prepare_preview_raw(data)
                        if prepared:
                            self._process_raw_text(prepared)

                elif msg_type == "subtitle_reset":
                    # 발언자 전환으로 자막 영역이 클리어됨 → 완전 리셋
                    # (자막 영역이 빈 상태이므로 중복 유입 위험 없음)
                    logger.info("subtitle_reset 감지: %s", data)
                    # 이전 발언자의 마지막 버퍼 확정
                    if self.last_subtitle:
                        self._finalize_subtitle(self.last_subtitle)
                        self.last_subtitle = ""
                        self._stream_start_time = None
                    self._confirmed_compact = ""
                    self._trailing_suffix = ""
                    self._last_raw_text = ""
                    self._last_processed_raw = ""
                    self._preview_desync_count = 0
                    self._preview_ambiguous_skip_count = 0

                elif msg_type == "keepalive":
                    self._handle_keepalive(str(data or ""))

                elif msg_type == "error":
                    self._retire_capture_run()
                    self.worker = None
                    self.progress.hide()
                    self._reset_ui()
                    self._update_tray_status("⚪ 대기 중")
                    self._update_connection_status("disconnected")
                    self._clear_preview()
                    QMessageBox.critical(self, "오류", str(data))

                elif msg_type == "finished":
                    self._retire_capture_run()
                    self.worker = None
                    self._cancel_scheduled_subtitle_reset()
                    self._materialize_pending_preview()
                    finalize_session(
                        self.capture_state,
                        datetime.now(),
                        self._current_capture_settings(),
                    )
                    self._sync_capture_state_entries(force_refresh=False)
                    if self.last_subtitle:
                        self._finalize_subtitle(self.last_subtitle)
                        self.last_subtitle = ""
                        self._stream_start_time = None
                    self._clear_preview()

                    self._refresh_text()
                    self._reset_ui()
                    self._update_tray_status("⚪ 대기 중")
                    self._update_connection_status("disconnected")

                    # 스레드 안전하게 통계 계산
                    with self.subtitle_lock:
                        subtitle_count = len(self.subtitles)
                    total_chars = self._cached_total_chars
                    self.status_label.setText(
                        f"완료 - {subtitle_count}문장, {total_chars:,}자"
                    )

                elif msg_type == "session_save_done":
                    self._session_save_in_progress = False
                    info = data if isinstance(data, dict) else {}
                    saved_count = int(info.get("saved_count", 0) or 0)
                    db_saved = bool(info.get("db_saved", False))
                    db_error = str(info.get("db_error", "") or "").strip()
                    if db_saved:
                        self._set_status(
                            f"세션 저장 완료 ({saved_count}개, DB 저장 포함)", "success"
                        )
                        self._show_toast("세션 저장 완료! (JSON + DB)", "success")
                    else:
                        self._set_status(f"세션 저장 완료 ({saved_count}개)", "success")
                        if db_error:
                            self._show_toast(
                                "세션 저장 완료 (DB 저장은 실패)", "warning", 3500
                            )
                            logger.warning("세션 저장: DB 저장 실패 - %s", db_error)
                        else:
                            self._show_toast("세션 저장 완료!", "success")

                elif msg_type == "session_save_failed":
                    self._session_save_in_progress = False
                    err = data.get("error") if isinstance(data, dict) else str(data)
                    self._set_status(f"세션 저장 실패: {err}", "error")
                    QMessageBox.critical(self, "오류", f"세션 저장 실패: {err}")

                elif msg_type == "session_load_done":
                    self._session_load_in_progress = False
                    payload = data if isinstance(data, dict) else {}
                    if not self._complete_loaded_session(payload):
                        if not payload.get("_cancelled"):
                            self._set_status("세션 불러오기 실패", "error")

                elif msg_type == "session_load_json_error":
                    self._session_load_in_progress = False
                    info = data if isinstance(data, dict) else {}
                    path = str(info.get("path", ""))
                    err = str(info.get("error", "JSON 파싱 오류"))
                    reply = QMessageBox.question(
                        self,
                        "파일 손상",
                        f"세션 파일이 손상되었습니다 (JSON 오류).\n위치: {path}\n오류: {err}\n\n"
                        "백업 폴더를 열어 복구를 시도하시겠습니까?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        backup_path = os.path.abspath(Config.BACKUP_DIR)
                        if os.name == "nt":
                            os.startfile(backup_path)
                    self._set_status("세션 불러오기 실패 (JSON 오류)", "error")

                elif msg_type == "session_load_failed":
                    self._session_load_in_progress = False
                    err = data.get("error") if isinstance(data, dict) else str(data)
                    self._set_status(f"세션 불러오기 실패: {err}", "error")
                    QMessageBox.critical(self, "오류", f"불러오기 실패: {err}")

                elif msg_type == "subtitle_not_found":
                    self._retire_capture_run()
                    self.worker = None
                    # 자막 요소를 찾지 못했을 때 사용자 안내
                    self.progress.hide()
                    self._reset_ui()
                    self._update_tray_status("⚪ 대기 중")
                    self._clear_preview()

                    # 상세 안내 다이얼로그
                    msg_box = QMessageBox(self)
                    msg_box.setWindowTitle("자막을 찾을 수 없습니다")
                    msg_box.setIcon(QMessageBox.Icon.Warning)
                    msg_box.setText(str(data))
                    msg_box.setStandardButtons(
                        QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Ok
                    )
                    open_button = msg_box.button(QMessageBox.StandardButton.Open)
                    if open_button is not None:
                        open_button.setText("🌐 사이트 열기")
                    ok_button = msg_box.button(QMessageBox.StandardButton.Ok)
                    if ok_button is not None:
                        ok_button.setText("확인")

                    result = msg_box.exec()

                    # 사이트 열기 버튼 클릭 시 브라우저에서 열기
                    if result == QMessageBox.StandardButton.Open:
                        import webbrowser

                        webbrowser.open("https://assembly.webcast.go.kr")

                # 연결 상태 업데이트 (#30)
                elif msg_type == "connection_status":
                    status = data.get("status", "disconnected")
                    latency = data.get("latency")
                    self._update_connection_status(status, latency)

                # 재연결 시도 (#31)
                elif msg_type == "reconnecting":
                    self.reconnect_attempts = data.get("attempt", 0)
                    self._update_connection_status("reconnecting")
                    self._show_toast(
                        f"재연결 시도 중... ({self.reconnect_attempts}/{Config.MAX_RECONNECT_ATTEMPTS})",
                        "warning",
                        2000,
                    )

                # 재연결 성공 (#31)
                elif msg_type == "reconnected":
                    self.reconnect_attempts = 0
                    self._update_connection_status("connected")
                    self._show_toast("재연결 성공!", "success", 2000)

                elif msg_type == "hwp_save_failed":
                    error = data.get("error") if isinstance(data, dict) else data
                    self._handle_hwp_save_failure(error)

                elif msg_type == "db_task_result":
                    task_name = data.get("task") if isinstance(data, dict) else None
                    result = data.get("result") if isinstance(data, dict) else None
                    context = data.get("context") if isinstance(data, dict) else {}
                    if task_name:
                        self._db_tasks_inflight.discard(task_name)
                        self._handle_db_task_result(task_name, result, context or {})

                elif msg_type == "db_task_error":
                    task_name = (
                        str(data.get("task") or "db_unknown")
                        if isinstance(data, dict)
                        else "db_unknown"
                    )
                    error = (
                        str(data.get("error") or "")
                        if isinstance(data, dict)
                        else str(data)
                    )
                    context = data.get("context") if isinstance(data, dict) else {}
                    self._db_tasks_inflight.discard(task_name)
                    self._handle_db_task_error(task_name, error, context or {})

            except Exception as e:
                logger.error(f"메시지 처리 오류 ({msg_type}): {e}")


    def _should_merge_entry(
            self, last_entry: SubtitleEntry, new_text: str, now: datetime
        ) -> bool:
            """기존 자막에 이어붙여도 되는지 판단 (단순 시간/길이 체크)"""
            if not last_entry or not new_text:
                return False

            # [호환 유지] end_time이 없으면 이어붙이지 않음 (reflow 이후 등)
            if last_entry.end_time is None:
                return False

            # 마지막 자막과 시간 차이가 너무 크면 분리
            if (now - last_entry.end_time).total_seconds() > Config.ENTRY_MERGE_MAX_GAP:
                return False

            # 너무 길어지면 분리
            if len(last_entry.text) + 1 + len(new_text) > Config.ENTRY_MERGE_MAX_CHARS:
                return False

            return True


    def _confirmed_history_compact_tail(
            self, max_entries: int = 10, max_compact_len: int = 3000
        ) -> str:
            """최근 확정 자막들의 compact tail 문자열(겹침/중복 제거용)"""
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
            """anchor 기준으로 raw에서 새로 추가된 부분을 반환한다.

            반환값:
              - None: 겹침 없음 (문맥 전환으로 처리)
              - "": 겹침은 있으나 새 내용 없음
              - str: 새로 추가된 텍스트
            """
            if not raw or not anchor_compact or not raw_compact:
                return None

            # anchor가 길면, raw 내부에서 마지막으로 등장하는 위치를 기준으로 슬라이스
            if len(anchor_compact) >= min_anchor:
                idx = raw_compact.rfind(anchor_compact)
                if idx != -1:
                    return utils.slice_from_compact_index(
                        raw, idx + len(anchor_compact)
                    ).strip()

            # fallback: suffix-prefix overlap
            overlap_len = utils.find_compact_suffix_prefix_overlap(
                anchor_compact, raw_compact, min_overlap=min_overlap
            )
            if overlap_len > 0:
                return utils.slice_from_compact_index(raw, overlap_len).strip()

            return None


    def _extract_stream_delta(self, raw: str, last_raw: str):
            """이전 raw 대비 새로 추가된 부분(delta)을 추출한다.

            Returns:
                str: 새로 추가된 텍스트 (없으면 "")
                None: 문맥 전환(새 문장)으로 판단
            """
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
            """글로벌 히스토리 + Suffix 매칭 (#GlobalHistorySuffix)

            이 세션에서 확정된 모든 텍스트를 누적하고,
            새 raw에서 히스토리의 마지막 부분(suffix) 이후만 추출합니다.

            DOM 루핑에 완전히 면역입니다.
            """
            if not raw:
                return

            raw = raw.strip()

            # 동일한 raw면 무시 (빠른 경로)
            if raw == self._last_raw_text:
                return
            self._last_raw_text = raw

            # raw를 compact (공백 제거)
            raw_compact = utils.compact_subtitle_text(raw)

            if not raw_compact:
                return

            # 새로운 부분 추출
            new_part = self._extract_new_part(raw, raw_compact)

            if not new_part:
                # 새 내용 없음
                return
            new_part = new_part.strip()
            if not utils.is_meaningful_subtitle_text(new_part):
                return

            # 코어 알고리즘 결과를 최근 확정 자막 기준으로 한 번 더 정제해
            # 대량 반복 블록이 그대로 누적되는 것을 방지한다.
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
            if (
                len(new_compact) >= 20
                and recent_compact_tail
                and new_compact in recent_compact_tail
            ):
                return

            # 히스토리에 추가
            self._confirmed_compact += new_compact
            self._trim_confirmed_compact_history()

            # suffix 갱신
            if len(self._confirmed_compact) >= self._suffix_length:
                self._trailing_suffix = self._confirmed_compact[-self._suffix_length :]
            else:
                self._trailing_suffix = self._confirmed_compact

            # 자막에 추가
            self._add_text_to_subtitles(new_part)
            self._last_processed_raw = raw
            self.capture_state.last_processed_raw = raw


    def _trim_confirmed_compact_history(self) -> None:
            """_confirmed_compact를 설정 상한 내로 유지한다."""
            try:
                max_len = int(Config.CONFIRMED_COMPACT_MAX_LEN)
            except Exception:
                max_len = 0
            if max_len > 0 and len(self._confirmed_compact) > max_len:
                self._confirmed_compact = self._confirmed_compact[-max_len:]


    def _extract_new_part(self, raw: str, raw_compact: str) -> str:
            """히스토리의 suffix 이후의 새 부분만 추출

            Args:
                raw: 원본 텍스트
                raw_compact: 공백 제거된 텍스트

            Returns:
                새로운 부분 (원본 형태로)
            """
            # 히스토리가 없으면 전체가 새로운 것
            if not self._trailing_suffix:
                return raw

            # suffix가 raw_compact에 있는지 검색 (rfind: 마지막 위치 기준으로 과잉 추출 방지)
            pos = raw_compact.rfind(self._trailing_suffix)

            if pos >= 0:
                # suffix 이후 부분만 반환
                start_idx = pos + len(self._trailing_suffix)
                if start_idx >= len(raw_compact):
                    return ""  # suffix 이후에 내용 없음
                return utils.slice_from_compact_index(raw, start_idx)

            # 정말 새로운 문맥 - 전체 반환
            return raw


    def _soft_resync(self) -> None:
            """전체 리셋 대신, 최근 확정 자막에서 히스토리를 재구성한다.

            desync/ambiguous 리셋 시 _confirmed_compact를 완전 초기화하면
            이미 처리된 텍스트가 재유입되어 대량 중복이 발생할 수 있다.
            최근 자막의 compact를 기반으로 suffix를 복원하면 이를 방지한다.
            """
            with self.subtitle_lock:
                if self.subtitles:
                    # 최근 5개 자막의 compact로 히스토리 재구성
                    recent = " ".join(
                        e.text for e in self.subtitles[-5:] if e and e.text
                    )
                    self._confirmed_compact = utils.compact_subtitle_text(recent)
                    self._trim_confirmed_compact_history()
                    if len(self._confirmed_compact) >= self._suffix_length:
                        self._trailing_suffix = self._confirmed_compact[
                            -self._suffix_length :
                        ]
                    else:
                        self._trailing_suffix = self._confirmed_compact
                    logger.info(
                        "소프트 리셋: suffix=%s",
                        self._trailing_suffix[-20:] if self._trailing_suffix else "(empty)",
                    )
                else:
                    # 자막이 없으면 어쩔 수 없이 전체 리셋
                    self._confirmed_compact = ""
                    self._trailing_suffix = ""
                    logger.info("소프트 리셋: 자막 없음, 전체 리셋")


    def _find_overlap(self, suffix: str, text: str) -> int:
            """suffix의 뒷부분과 text의 앞부분이 겹치는 길이 반환"""
            max_overlap = min(len(suffix), len(text))
            for i in range(max_overlap, 0, -1):
                if suffix[-i:] == text[:i]:
                    return i
            return 0


    def _add_text_to_subtitles(self, text: str) -> None:
            """확정된 텍스트를 SubtitleEntry로 변환하여 저장"""
            self._append_text_to_subtitles_shared(text, now=datetime.now())

    def _handle_keepalive(self, raw: str) -> None:
            """Refresh the active entry end time without re-appending subtitle text."""
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
