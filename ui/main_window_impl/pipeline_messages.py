# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import os
import queue
import time
from datetime import datetime
from importlib import import_module

from PyQt6.QtCore import QTimer

from core.config import Config
from core.logging_utils import logger
from core.subtitle_pipeline import finalize_session
from ui.main_window_impl.contracts import PipelineMessagesHost


def _pipeline_public():
    return import_module("ui.main_window_pipeline")


PipelineMessagesBase = object


class MainWindowPipelineMessagesMixin(PipelineMessagesBase):
    def _has_pending_message_backlog(self) -> bool:
        try:
            if bool(self.__dict__.get("_overflow_passthrough_messages", [])):
                return True
            if bool(self.__dict__.get("_coalesced_control_messages", {})):
                return True
            if bool(self.__dict__.get("_coalesced_worker_messages", {})):
                return True
            qsize = getattr(self.message_queue, "qsize", None)
            if callable(qsize):
                return int(qsize()) > 0
        except Exception:
            return False
        return False

    def _schedule_followup_message_queue_drain(self) -> None:
        if not bool(self.__dict__.get("_use_async_queue_drain", False)):
            return
        if bool(self.__dict__.get("_queue_drain_scheduled", False)):
            return
        self._queue_drain_scheduled = True

        def drain_again() -> None:
            self._queue_drain_scheduled = False
            self._process_message_queue()

        try:
            QTimer.singleShot(0, drain_again)
        except Exception:
            self._queue_drain_scheduled = False

    def _complete_loaded_session(self, payload: dict[str, object]) -> bool:
        pipeline_mod = _pipeline_public()
        if not isinstance(payload, dict):
            return False

        session_version = str(payload.get("version", "unknown"))
        source_path = str(payload.get("path", "") or "")
        source_url = str(payload.get("url", "") or "")
        committee_name = str(payload.get("committee_name", "") or "")
        created_at = str(payload.get("created_at", "") or "")
        loaded_subtitles = payload.get("subtitles", [])
        try:
            skipped_items = int(payload.get("skipped", 0) or 0)
        except Exception:
            skipped_items = 0
        mark_dirty = bool(payload.get("mark_dirty", False))
        recovery = bool(payload.get("recovery", False))
        highlight_sequence = self._coerce_highlight_sequence(
            payload.get("highlight_sequence")
        )
        highlight_query = str(payload.get("highlight_query", "") or "")

        if not isinstance(loaded_subtitles, list):
            return False

        if session_version != Config.VERSION:
            reply = pipeline_mod.QMessageBox.question(
                self,
                "버전 불일치",
                f"세션 버전({session_version})이 현재 버전({Config.VERSION})과 다릅니다.\n"
                "계속 불러오시겠습니까?",
                pipeline_mod.QMessageBox.StandardButton.Yes
                | pipeline_mod.QMessageBox.StandardButton.No,
            )
            if reply == pipeline_mod.QMessageBox.StandardButton.No:
                payload["_cancelled"] = True
                self._set_status("세션 불러오기 취소됨 (버전 불일치)", "warning")
                return False

        self._replace_subtitles_and_refresh(
            loaded_subtitles, keep_history_from_subtitles=bool(loaded_subtitles)
        )
        self._cleanup_runtime_session_archive(remove_files=True)
        self._clear_destructive_undo_state()
        self._initial_recovery_snapshot_done = False
        self._set_capture_source_metadata(
            source_url,
            committee_name,
            headless=bool(self.__dict__.get("_capture_source_headless", False)),
            realtime=bool(self.__dict__.get("_capture_source_realtime", False)),
        )
        if source_url:
            self.url_combo.setCurrentText(source_url)
            self._add_to_history(source_url, committee_name)
            self.current_url = source_url

        if recovery:
            self._clear_recovery_state()

        summary_prefix = "세션 복구 완료!" if recovery else "세션 불러오기 완료!"
        summary = f"{summary_prefix} {self._get_global_subtitle_count()}개 문장"
        if skipped_items > 0:
            summary += f" (손상 항목 {skipped_items}개 제외)"
        self._set_status(summary, "success")
        self._show_toast(summary, "success")
        if mark_dirty:
            self._mark_session_dirty()
        else:
            self._clear_session_dirty()

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
            self._queue_drain_scheduled = False
            deadline = time.perf_counter() + 0.008
            processed = 0
            if time.perf_counter() <= deadline:
                processed += self._drain_overflow_passthrough_items(
                    max_items=50,
                )
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
                processed += self._drain_coalesced_control_messages(
                    max_items=remaining_budget,
                )
            remaining_budget = max(0, 50 - processed)
            if remaining_budget > 0 and time.perf_counter() <= deadline:
                processed += self._drain_coalesced_worker_messages(
                    max_items=remaining_budget,
                )
            if self._has_pending_message_backlog():
                self._schedule_followup_message_queue_drain()
        except Exception as e:
            logger.error(f"큐 처리 오류: {e}")

    def _handle_message(self, msg_type, data):
        pipeline_mod = _pipeline_public()
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
                    self._schedule_status_update(status_text, "info")

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
                logger.info("subtitle_reset 감지: %s", data)
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
                pipeline_mod.QMessageBox.critical(self, "오류", str(data))

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
                self._reset_ui()
                self._update_tray_status("⚪ 대기 중")
                self._update_connection_status("disconnected")
                subtitle_count = self._get_global_subtitle_count()
                total_chars = self._get_global_total_chars()
                self._schedule_status_update(
                    f"완료 - {subtitle_count}문장, {total_chars:,}자",
                    "success",
                )

            elif msg_type == "session_save_done":
                self._session_save_in_progress = False
                info = data if isinstance(data, dict) else {}
                saved_count = int(info.get("saved_count", 0) or 0)
                db_saved = bool(info.get("db_saved", False))
                db_error = str(info.get("db_error", "") or "").strip()
                self._cleanup_runtime_session_archive(remove_files=True)
                self._clear_session_dirty()
                if db_saved:
                    self._set_status(
                        f"세션 저장 완료 ({saved_count}개, DB 저장 포함)", "success"
                    )
                    self._show_toast("세션 저장 완료! (JSON + DB)", "success")
                else:
                    self._set_status(f"세션 저장 완료 ({saved_count}개)", "success")
                    if db_error:
                        self._show_toast("세션 저장 완료 (DB 저장은 실패)", "warning", 3500)
                        logger.warning("세션 저장: DB 저장 실패 - %s", db_error)
                    else:
                        self._show_toast("세션 저장 완료!", "success")

            elif msg_type == "session_save_failed":
                self._session_save_in_progress = False
                err = data.get("error") if isinstance(data, dict) else str(data)
                self._set_status(f"세션 저장 실패: {err}", "error")
                pipeline_mod.QMessageBox.critical(self, "오류", f"세션 저장 실패: {err}")

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
                if bool(info.get("recovery", False)):
                    self._clear_recovery_state()
                reply = pipeline_mod.QMessageBox.question(
                    self,
                    "파일 손상",
                    f"세션 파일이 손상되었습니다 (JSON 오류).\n위치: {path}\n오류: {err}\n\n"
                    "백업 폴더를 열어 복구를 시도하시겠습니까?",
                    pipeline_mod.QMessageBox.StandardButton.Yes
                    | pipeline_mod.QMessageBox.StandardButton.No,
                )
                if reply == pipeline_mod.QMessageBox.StandardButton.Yes:
                    backup_path = os.path.abspath(Config.BACKUP_DIR)
                    if os.name == "nt":
                        os.startfile(backup_path)
                self._set_status("세션 불러오기 실패 (JSON 오류)", "error")

            elif msg_type == "session_load_failed":
                self._session_load_in_progress = False
                err = data.get("error") if isinstance(data, dict) else str(data)
                self._set_status(f"세션 불러오기 실패: {err}", "error")
                pipeline_mod.QMessageBox.critical(self, "오류", f"불러오기 실패: {err}")

            elif msg_type == "reflow_done":
                self._reflow_in_progress = False
                payload = data if isinstance(data, dict) else {}
                new_subtitles = payload.get("subtitles", [])
                old_count = int(payload.get("old_count", len(self.subtitles)) or 0)
                if not isinstance(new_subtitles, list) or not new_subtitles:
                    self._set_status("줄넘김 정리 결과가 비어 있어 적용하지 않았습니다.", "warning")
                    self._show_toast("줄넘김 정리 결과가 비어 있습니다.", "warning")
                    return
                logger.info(f"스마트 리플로우: {old_count} -> {len(new_subtitles)}")
                self._store_destructive_undo_snapshot()
                self._replace_subtitles_and_refresh(new_subtitles)
                self._mark_session_dirty()
                self._notify_destructive_undo_available()
                self._set_status(
                    f"줄넘김 정리 완료 ({old_count} -> {len(new_subtitles)})",
                    "success",
                )
                self._show_toast(f"정리 완료! ({len(new_subtitles)}개 문장)", "success")

            elif msg_type == "reflow_failed":
                self._reflow_in_progress = False
                err = data.get("error") if isinstance(data, dict) else str(data)
                self._set_status(f"줄넘김 정리 실패: {err}", "error")
                self._show_toast(f"줄넘김 정리 실패: {err}", "error", 4000)

            elif msg_type == "subtitle_not_found":
                self._retire_capture_run()
                self.worker = None
                self.progress.hide()
                self._reset_ui()
                self._update_tray_status("⚪ 대기 중")
                self._clear_preview()
                msg_box = pipeline_mod.QMessageBox(self)
                msg_box.setWindowTitle("자막을 찾을 수 없습니다")
                msg_box.setIcon(pipeline_mod.QMessageBox.Icon.Warning)
                msg_box.setText(str(data))
                msg_box.setStandardButtons(
                    pipeline_mod.QMessageBox.StandardButton.Open
                    | pipeline_mod.QMessageBox.StandardButton.Ok
                )
                open_button = msg_box.button(pipeline_mod.QMessageBox.StandardButton.Open)
                if open_button is not None:
                    open_button.setText("🌐 사이트 열기")
                ok_button = msg_box.button(pipeline_mod.QMessageBox.StandardButton.Ok)
                if ok_button is not None:
                    ok_button.setText("확인")
                result = msg_box.exec()
                if result == pipeline_mod.QMessageBox.StandardButton.Open:
                    import webbrowser

                    webbrowser.open("https://assembly.webcast.go.kr")

            elif msg_type == "connection_status":
                status = data.get("status", "disconnected")
                latency = data.get("latency")
                self._update_connection_status(status, latency)

            elif msg_type == "reconnecting":
                self.reconnect_attempts = data.get("attempt", 0)
                self._update_connection_status("reconnecting")
                self._show_toast(
                    f"재연결 시도 중... ({self.reconnect_attempts}/{Config.MAX_RECONNECT_ATTEMPTS})",
                    "warning",
                    2000,
                )

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

            elif msg_type == "runtime_segment_flush_done":
                payload = data if isinstance(data, dict) else {}
                self._handle_runtime_segment_flush_done(payload)

            elif msg_type == "runtime_segment_flush_failed":
                payload = data if isinstance(data, dict) else {}
                self._handle_runtime_segment_flush_failed(payload)

            elif msg_type == "runtime_search_done":
                payload = data if isinstance(data, dict) else {}
                self._handle_runtime_search_done(payload)

            elif msg_type == "runtime_search_failed":
                payload = data if isinstance(data, dict) else {}
                self._handle_runtime_search_failed(payload)

        except Exception as e:
            logger.error(f"메시지 처리 오류 ({msg_type}): {e}")
