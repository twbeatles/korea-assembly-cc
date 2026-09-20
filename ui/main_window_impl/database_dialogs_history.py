# -*- coding: utf-8 -*-

from collections.abc import Iterable
from typing import cast

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost
from core.resource_budget import ResourceBudget, ResourceBudgetLimits


class MainWindowDatabaseDialogsHistoryMixin(MainWindowHost):
    """세션 히스토리 다이얼로그 (SRP: 히스토리 목록/표시)."""

    def _format_db_history_item(self, session_row: dict[str, Any]) -> str:
            created = session_row.get("created_at", "")[:19] if session_row.get("created_at") else ""
            committee = session_row.get("committee_name") or "알 수 없음"
            subtitles = session_row.get("total_subtitles", 0)
            chars = session_row.get("total_characters", 0)
            is_latest = bool(session_row.get("is_latest_in_lineage", 0))
            lineage_total = max(1, int(session_row.get("lineage_total", 1) or 1))
            newer_versions = max(0, int(session_row.get("newer_versions", 0) or 0))
            if is_latest:
                lineage_badge = "[최신]"
            else:
                previous_total = max(1, lineage_total - 1)
                lineage_badge = f"[이전 저장본 {newer_versions}/{previous_total}]"
            return f"{lineage_badge} [{created}] {committee} - {subtitles}문장, {chars:,}자"

    def _update_db_history_loaded_label(self) -> None:
            state = self.__dict__.get("_db_history_dialog_state") or {}
            loaded_label = state.get("loaded_label")
            sessions = state.get("sessions")
            if loaded_label is None or not isinstance(sessions, list):
                return
            loaded_label.setText(f"현재 {len(sessions)}개 로드됨")

    def _append_db_history_sessions(self, sessions: list[dict[str, Any]]) -> None:
            state = self.__dict__.get("_db_history_dialog_state") or {}
            current_sessions = state.get("sessions")
            list_widget = state.get("list_widget")
            if not isinstance(current_sessions, list) or list_widget is None:
                return

            rendered_items = [self._format_db_history_item(session_row) for session_row in sessions]
            current_sessions.extend(sessions)
            set_updates_enabled = getattr(list_widget, "setUpdatesEnabled", None)
            if callable(set_updates_enabled):
                set_updates_enabled(False)
            try:
                for item_text in rendered_items:
                    list_widget.addItem(item_text)
            finally:
                if callable(set_updates_enabled):
                    set_updates_enabled(True)

            state["offset"] = len(current_sessions)
            state["has_more"] = len(sessions) >= int(
                state.get("page_size", Config.DB_HISTORY_PAGE_SIZE)
                or Config.DB_HISTORY_PAGE_SIZE
            )
            state["loading"] = False
            more_btn = state.get("more_btn")
            if more_btn is not None:
                more_btn.setEnabled(bool(state["has_more"]))
            self._update_db_history_loaded_label()

    def _replace_db_history_sessions(
            self,
            sessions: list[dict[str, Any]],
            page_size: int | None = None,
        ) -> None:
            state = self.__dict__.get("_db_history_dialog_state") or {}
            current_sessions = state.get("sessions")
            list_widget = state.get("list_widget")
            if not isinstance(current_sessions, list) or list_widget is None:
                return

            new_sessions = [dict(item) for item in sessions]
            current_sessions[:] = new_sessions
            set_updates_enabled = getattr(list_widget, "setUpdatesEnabled", None)
            if callable(set_updates_enabled):
                set_updates_enabled(False)
            try:
                clear = getattr(list_widget, "clear", None)
                if callable(clear):
                    clear()
                else:
                    take_item = getattr(list_widget, "takeItem", None)
                    count = getattr(list_widget, "count", None)
                    if callable(take_item) and callable(count):
                        while int(cast(Any, count)()) > 0:
                            take_item(0)
                for session_row in current_sessions:
                    list_widget.addItem(self._format_db_history_item(session_row))
            finally:
                if callable(set_updates_enabled):
                    set_updates_enabled(True)

            raw_page_size = (
                page_size
                if page_size is not None
                else state.get("page_size", Config.DB_HISTORY_PAGE_SIZE)
            )
            try:
                resolved_page_size = int(raw_page_size or Config.DB_HISTORY_PAGE_SIZE)
            except Exception:
                resolved_page_size = Config.DB_HISTORY_PAGE_SIZE
            state["page_size"] = resolved_page_size
            state["offset"] = len(current_sessions)
            state["has_more"] = len(current_sessions) >= resolved_page_size
            state["loading"] = False
            more_btn = state.get("more_btn")
            if more_btn is not None:
                more_btn.setEnabled(bool(state["has_more"]))
            count = getattr(list_widget, "count", None)
            set_current_row = getattr(list_widget, "setCurrentRow", None)
            if (
                callable(count)
                and callable(set_current_row)
                and int(cast(Any, count)()) > 0
            ):
                set_current_row(0)
            self._update_db_history_loaded_label()

    def _show_db_history(self):
            """세션 히스토리 다이얼로그 표시"""
            db = self.db
            if db is None or not bool(self.__dict__.get("db_available", False)):
                QMessageBox.warning(self, "알림", self._get_db_degraded_message())
                return
            self._run_db_task(
                "db_history_list",
                worker=lambda: db.list_sessions(limit=Config.DB_HISTORY_PAGE_SIZE, offset=0),
                context={
                    "offset": 0,
                    "limit": Config.DB_HISTORY_PAGE_SIZE,
                    "request_token": int(self.__dict__.get("_db_history_request_token", 0)),
                },
                loading_text="DB 세션 히스토리 조회 중...",
            )

    def _open_db_history_dialog(
            self,
            sessions: list[dict],
            page_size: int = Config.DB_HISTORY_PAGE_SIZE,
        ) -> None:
            dialog = QDialog(self)
            dialog.setWindowTitle("📋 세션 히스토리")
            dialog.setMinimumSize(700, 500)

            layout = QVBoxLayout(dialog)

            loaded_label = QLabel("")
            layout.addWidget(loaded_label)

            list_widget = QListWidget()
            layout.addWidget(list_widget)

            status_label = QLabel("")
            status_label.hide()
            layout.addWidget(status_label)

            # 버튼
            btn_layout = QHBoxLayout()

            load_btn = QPushButton("불러오기")

            def load_selected():
                if self._is_runtime_mutation_blocked("세션 불러오기"):
                    return
                idx = list_widget.currentRow()
                if idx < 0 or idx >= len(sessions):
                    return

                session_id = sessions[idx].get("id")
                self._start_db_session_load(
                    session_id=session_id,
                    task_name="db_history_load_selected",
                    action_name="세션 불러오기",
                    loading_text="DB 세션 불러오는 중...",
                    busy_message="세션을 불러오는 중입니다...",
                    source_tag="db_session",
                    set_busy=self._set_db_history_dialog_busy,
                )

            load_btn.clicked.connect(load_selected)
            btn_layout.addWidget(load_btn)
            load_btn.setEnabled(not self.is_running)

            delete_btn = QPushButton("삭제")

            def delete_selected():
                idx = list_widget.currentRow()
                if idx < 0 or idx >= len(sessions):
                    return

                session_id = sessions[idx].get("id")
                if not session_id:
                    self._show_toast("유효한 세션 ID가 없습니다.", "warning")
                    return
                db = self.db
                if db is None:
                    self._show_toast("데이터베이스가 초기화되지 않았습니다.", "error")
                    return

                reply = QMessageBox.question(
                    dialog,
                    "삭제 확인",
                    "선택한 세션을 삭제하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

                started = self._run_db_task(
                    "db_history_delete_selected",
                    worker=lambda sid=session_id: db.delete_session(sid),
                    context={"session_id": session_id, "row": idx},
                    loading_text="DB 세션 삭제 중...",
                )
                if started:
                    self._set_db_history_dialog_busy(True, "세션을 삭제하는 중입니다...")

            delete_btn.clicked.connect(delete_selected)
            btn_layout.addWidget(delete_btn)

            more_btn = QPushButton("더 보기")

            def load_more():
                state = self.__dict__.get("_db_history_dialog_state") or {}
                if state.get("loading"):
                    return
                if not state.get("has_more", False):
                    return
                db = self.db
                if db is None:
                    self._show_toast("데이터베이스가 초기화되지 않았습니다.", "error")
                    return
                offset = int(state.get("offset", len(state.get("sessions", []))) or 0)
                request_token = int(state.get("request_token", 0)) + 1
                state["request_token"] = request_token
                started = self._run_db_task(
                    "db_history_list_more",
                    worker=lambda off=offset: db.list_sessions(
                        limit=page_size,
                        offset=off,
                    ),
                    context={
                        "offset": offset,
                        "limit": page_size,
                        "request_token": request_token,
                    },
                    loading_text="DB 세션 히스토리 추가 조회 중...",
                )
                if started:
                    state["loading"] = True
                    self._set_db_history_dialog_busy(True, "세션 목록을 더 불러오는 중입니다...")

            more_btn.clicked.connect(load_more)
            btn_layout.addWidget(more_btn)

            close_btn = QPushButton("닫기")
            close_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(close_btn)

            layout.addLayout(btn_layout)
            if self.is_running:
                status_label.setText("추출 중에는 세션 불러오기를 사용할 수 없습니다.")
                status_label.show()

            self._db_history_dialog_state = {
                "dialog": dialog,
                "sessions": sessions,
                "list_widget": list_widget,
                "status_label": status_label,
                "loaded_label": loaded_label,
                "load_btn": load_btn,
                "delete_btn": delete_btn,
                "close_btn": close_btn,
                "more_btn": more_btn,
                "offset": len(sessions),
                "page_size": page_size,
                "has_more": len(sessions) >= page_size,
                "loading": False,
                "request_token": int(self.__dict__.get("_db_history_request_token", 0)),
            }
            for session_row in sessions:
                list_widget.addItem(self._format_db_history_item(session_row))
            self._update_db_history_loaded_label()
            more_btn.setEnabled(len(sessions) >= page_size)
            if list_widget.count() > 0:
                list_widget.setCurrentRow(0)
            dialog.finished.connect(lambda *_: self._clear_db_history_dialog_state())
            dialog.exec()
