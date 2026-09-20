# -*- coding: utf-8 -*-

from collections.abc import Iterable
from typing import cast

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost
from core.resource_budget import ResourceBudget, ResourceBudgetLimits


class MainWindowDatabaseDialogsBaseMixin(MainWindowHost):
    """DB 세션 로드·다이얼로그 busy/state (SRP: 대화상자 상태 관리)."""

    def _cancel_db_session_load(self) -> None:
            cancel_event = self.__dict__.get("_db_session_load_cancel_event")
            if cancel_event is not None:
                cancel_event.set()

    def _set_db_history_dialog_busy(self, busy: bool, message: str = "") -> None:
            """DB 히스토리 다이얼로그의 버튼/목록 상태를 토글한다."""
            state = self.__dict__.get("_db_history_dialog_state") or {}
            load_btn = state.get("load_btn")
            delete_btn = state.get("delete_btn")
            close_btn = state.get("close_btn")
            more_btn = state.get("more_btn")
            list_widget = state.get("list_widget")
            status_label = state.get("status_label")

            if load_btn is not None:
                load_btn.setEnabled((not busy) and (not self.is_running))
            for btn in (delete_btn, close_btn):
                if btn is not None:
                    btn.setEnabled(not busy)
            if more_btn is not None:
                more_btn.setEnabled((not busy) and bool(state.get("has_more", False)))
            if list_widget is not None:
                list_widget.setEnabled(not busy)

            if status_label is not None:
                if busy:
                    status_label.setText(message or "처리 중입니다...")
                    status_label.show()
                elif message:
                    status_label.setText(message)
                    status_label.show()
                else:
                    status_label.hide()

    def _set_db_search_dialog_busy(self, busy: bool, message: str = "") -> None:
            """DB 검색 결과 다이얼로그의 버튼/목록 상태를 토글한다."""
            state = self.__dict__.get("_db_search_dialog_state") or {}
            load_btn = state.get("load_btn")
            focus_btn = state.get("focus_btn")
            close_btn = state.get("close_btn")
            more_btn = state.get("more_btn")
            list_widget = state.get("list_widget")
            status_label = state.get("status_label")

            for btn in (load_btn, focus_btn):
                if btn is not None:
                    btn.setEnabled((not busy) and (not self.is_running))
            if close_btn is not None:
                close_btn.setEnabled(not busy)
            if more_btn is not None:
                more_btn.setEnabled((not busy) and bool(state.get("has_more", False)))
            if list_widget is not None:
                list_widget.setEnabled(not busy)

            if status_label is not None:
                if busy:
                    status_label.setText(message or "처리 중입니다...")
                    status_label.show()
                elif message:
                    status_label.setText(message)
                    status_label.show()
                else:
                    status_label.hide()

    def _clear_db_history_dialog_state(self) -> None:
            """활성 DB 히스토리 다이얼로그 상태를 정리한다."""
            self._db_history_dialog_state = None
            self._db_history_request_token = int(
                self.__dict__.get("_db_history_request_token", 0)
            ) + 1

    def _clear_db_search_dialog_state(self) -> None:
            """활성 DB 검색 다이얼로그 상태를 정리한다."""
            self._db_search_dialog_state = None
            self._db_search_request_token = int(
                self.__dict__.get("_db_search_request_token", 0)
            ) + 1

    def _start_db_session_load(
            self,
            session_id: int | str | None,
            *,
            task_name: str,
            action_name: str,
            loading_text: str,
            busy_message: str,
            source_tag: str,
            set_busy: Callable[[bool, str], None] | None = None,
            dialog: object | None = None,
            highlight_sequence: int = -1,
            highlight_query: str = "",
        ) -> bool:
            """DB 세션 로드를 공통 보호 흐름으로 시작한다."""
            if session_id is None:
                self._show_toast("유효한 세션 ID가 없습니다.", "warning")
                return False
            if self._block_session_replacement_while_saving(action_name):
                return False

            if isinstance(session_id, int):
                normalized_session_id = session_id
            elif isinstance(session_id, str):
                stripped_session_id = session_id.strip()
                if not stripped_session_id:
                    self._show_toast("유효한 세션 ID가 없습니다.", "warning")
                    return False
                try:
                    normalized_session_id = int(stripped_session_id)
                except ValueError:
                    self._show_toast("유효한 세션 ID가 없습니다.", "warning")
                    return False
            else:
                self._show_toast("유효한 세션 ID가 없습니다.", "warning")
                return False

            db = self.db
            if db is None:
                self._show_toast("데이터베이스가 초기화되지 않았습니다.", "error")
                return False

            started_holder: dict[str, bool | None] = {"value": None}
            cancel_event = self.__dict__.get("_db_session_load_cancel_event")
            if cancel_event is None:
                cancel_event = threading.Event()
                self._db_session_load_cancel_event = cancel_event
            cancel_event.clear()
            request_token = int(self.__dict__.get("_db_session_load_request_token", 0)) + 1
            self._db_session_load_request_token = request_token

            def continue_load() -> None:
                def worker(sid: int = normalized_session_id):
                    metadata_loader = getattr(db, "get_session_metadata", None)
                    subtitle_iterator = getattr(db, "iter_session_subtitles", None)
                    if callable(metadata_loader) and callable(subtitle_iterator):
                        session_data = cast(
                            dict[str, Any] | None,
                            metadata_loader(sid),
                        )
                        if not session_data:
                            return {}
                        max_entries = int(Config.SESSION_RESOURCE_MAX_ENTRIES)
                        budget = ResourceBudget(
                            ResourceBudgetLimits(
                                per_file_bytes=0,
                                total_bytes=0,
                                max_entries=max_entries,
                                max_segments=0,
                            ),
                            cancel_check=cancel_event.is_set,
                        )
                        declared_count = int(
                            session_data.get("total_subtitles", 0) or 0
                        )
                        if declared_count > 0:
                            budget.consume_entries(declared_count)
                            budget = ResourceBudget(
                                budget.limits,
                                cancel_check=cancel_event.is_set,
                            )
                        new_subtitles: list[SubtitleEntry] = []
                        skipped = 0
                        processed = 0
                        raw_batch: list[dict[str, Any]] = []
                        streamed_rows = cast(
                            Iterable[dict[str, Any]],
                            subtitle_iterator(sid, batch_size=500),
                        )
                        for raw_item in streamed_rows:
                            budget.check_cancelled()
                            raw_batch.append(raw_item)
                            if len(raw_batch) < 500:
                                continue
                            parsed, batch_skipped = self._deserialize_subtitles(
                                raw_batch,
                                source=f"{source_tag}:{sid}",
                            )
                            budget.consume_entries(len(parsed))
                            new_subtitles.extend(parsed)
                            skipped += batch_skipped
                            processed += len(raw_batch)
                            raw_batch = []
                            self._emit_control_message(
                                "db_session_load_progress",
                                {"current": processed, "total": declared_count},
                            )
                        if raw_batch:
                            parsed, batch_skipped = self._deserialize_subtitles(
                                raw_batch,
                                source=f"{source_tag}:{sid}",
                            )
                            budget.consume_entries(len(parsed))
                            new_subtitles.extend(parsed)
                            skipped += batch_skipped
                            processed += len(raw_batch)
                        budget.check_cancelled()
                    else:
                        session_data = db.load_session(sid)
                        if not session_data:
                            return {}
                        new_subtitles, skipped = self._deserialize_subtitles(
                            session_data.get("subtitles", []),
                            source=f"{source_tag}:{sid}",
                        )
                    if not session_data:
                        return {}
                    payload = {
                        "db_session_id": session_data.get("id"),
                        "version": session_data.get("version", "unknown"),
                        "created_at": session_data.get("created_at", ""),
                        "url": session_data.get("url", ""),
                        "committee_name": session_data.get("committee_name", ""),
                        "lineage_id": session_data.get("lineage_id", ""),
                        "capture_quality": session_data.get("capture_quality", {}),
                        "subtitles": new_subtitles,
                        "skipped": skipped,
                    }
                    if highlight_sequence >= 0:
                        payload["highlight_sequence"] = highlight_sequence
                        payload["highlight_query"] = highlight_query
                    return payload

                context: dict[str, Any] = {
                    "session_id": normalized_session_id,
                    "request_token": request_token,
                }
                if dialog is not None:
                    context["dialog"] = dialog
                if highlight_sequence >= 0:
                    context["highlight"] = True
                    context["query"] = highlight_query

                started = self._run_db_task(
                    task_name,
                    worker=worker,
                    context=context,
                    loading_text=loading_text,
                )
                if started and set_busy is not None:
                    set_busy(True, busy_message)
                started_holder["value"] = bool(started)

            started_or_continued = self._run_after_dirty_session_action(
                action_name,
                continue_load,
            )
            if started_holder["value"] is not None:
                return bool(started_holder["value"])
            return bool(started_or_continued)
