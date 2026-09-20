# -*- coding: utf-8 -*-

from collections.abc import Iterable
from typing import cast

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost
from core.resource_budget import ResourceBudget, ResourceBudgetLimits


class MainWindowDatabaseDialogsSearchMixin(MainWindowHost):
    """자막 검색 다이얼로그 (SRP: 검색 목록/표시)."""

    def _format_db_search_item(self, row: dict[str, Any]) -> str:
            created = row.get("created_at", "")[:10] if row.get("created_at") else ""
            committee = row.get("committee_name") or ""
            text = row.get("text", "")[:100]
            return f"[{created}] {committee}: {text}"

    def _update_db_search_loaded_label(self) -> None:
            state = self.__dict__.get("_db_search_dialog_state") or {}
            loaded_label = state.get("loaded_label")
            results = state.get("results")
            if loaded_label is None or not isinstance(results, list):
                return
            loaded_label.setText(f"현재 {len(results)}개 로드됨")

    def _append_db_search_results(self, results: list[dict[str, Any]]) -> None:
            state = self.__dict__.get("_db_search_dialog_state") or {}
            current_results = state.get("results")
            list_widget = state.get("list_widget")
            if not isinstance(current_results, list) or list_widget is None:
                return

            rendered_items = [self._format_db_search_item(row) for row in results]
            current_results.extend(results)
            set_updates_enabled = getattr(list_widget, "setUpdatesEnabled", None)
            if callable(set_updates_enabled):
                set_updates_enabled(False)
            try:
                for item_text in rendered_items:
                    list_widget.addItem(item_text)
            finally:
                if callable(set_updates_enabled):
                    set_updates_enabled(True)

            state["offset"] = len(current_results)
            state["has_more"] = len(results) >= int(
                state.get("page_size", Config.DB_SEARCH_PAGE_SIZE)
                or Config.DB_SEARCH_PAGE_SIZE
            )
            state["loading"] = False
            more_btn = state.get("more_btn")
            if more_btn is not None:
                more_btn.setEnabled(bool(state["has_more"]))
            self._update_db_search_loaded_label()

    def _show_db_search(self):
            """자막 통합 검색 다이얼로그"""
            db = self.db
            if db is None or not bool(self.__dict__.get("db_available", False)):
                QMessageBox.warning(self, "알림", self._get_db_degraded_message())
                return

            query, ok = QInputDialog.getText(self, "자막 검색", "검색어:")
            query = query.strip() if ok and query else ""
            if not query:
                return

            request_token = int(self.__dict__.get("_db_search_request_token", 0)) + 1
            self._db_search_request_token = request_token
            self._run_db_task(
                "db_search",
                worker=lambda q=query: db.search_subtitles(
                    q,
                    limit=Config.DB_SEARCH_PAGE_SIZE,
                    offset=0,
                    syntax="literal",
                ),
                context={
                    "query": query,
                    "offset": 0,
                    "limit": Config.DB_SEARCH_PAGE_SIZE,
                    "request_token": request_token,
                },
                loading_text=f"DB 자막 검색 중... ({query[:15]})",
            )

    def _show_db_search_results(
            self,
            query: str,
            results: list[dict],
            page_size: int = Config.DB_SEARCH_PAGE_SIZE,
            request_token: int | None = None,
        ) -> None:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"🔍 검색 결과 - '{query}'")
            dialog.setMinimumSize(700, 500)

            layout = QVBoxLayout(dialog)

            loaded_label = QLabel("")
            layout.addWidget(loaded_label)

            list_widget = QListWidget()
            layout.addWidget(list_widget)

            status_label = QLabel("")
            status_label.hide()
            layout.addWidget(status_label)

            button_layout = QHBoxLayout()
            load_btn = QPushButton("세션 불러오기")
            focus_btn = QPushButton("결과로 이동")

            def load_selected(highlight: bool) -> None:
                if self._is_runtime_mutation_blocked(
                    "세션 불러오기" if not highlight else "검색 결과 이동"
                ):
                    return
                idx = list_widget.currentRow()
                if idx < 0 or idx >= len(results):
                    return

                selected = results[idx]
                session_id = selected.get("session_id")
                highlight_sequence = (
                    self._coerce_highlight_sequence(selected.get("sequence"))
                    if highlight
                    else -1
                )
                self._start_db_session_load(
                    session_id=session_id,
                    task_name="db_search_load_selected",
                    action_name="검색 결과 이동" if highlight else "세션 불러오기",
                    loading_text="DB 검색 결과 세션 불러오는 중...",
                    busy_message="검색 결과 세션을 불러오는 중입니다...",
                    source_tag="db_search_session",
                    set_busy=self._set_db_search_dialog_busy,
                    dialog=dialog,
                    highlight_sequence=highlight_sequence,
                    highlight_query=query,
                )

            load_btn.clicked.connect(lambda: load_selected(False))
            focus_btn.clicked.connect(lambda: load_selected(True))
            load_btn.setEnabled(not self.is_running)
            focus_btn.setEnabled(not self.is_running)
            button_layout.addWidget(load_btn)
            button_layout.addWidget(focus_btn)

            more_btn = QPushButton("더 보기")

            def load_more():
                state = self.__dict__.get("_db_search_dialog_state") or {}
                if state.get("loading"):
                    return
                if not state.get("has_more", False):
                    return

                db = self.db
                if db is None:
                    self._show_toast("데이터베이스가 초기화되지 않았습니다.", "error")
                    return
                offset = int(state.get("offset", len(state.get("results", []))) or 0)
                request_token = int(state.get("request_token", 0)) + 1
                state["request_token"] = request_token
                started = self._run_db_task(
                    "db_search_more",
                    worker=lambda q=query, off=offset: db.search_subtitles(
                        q,
                        limit=page_size,
                        offset=off,
                        syntax="literal",
                    ),
                    context={
                        "query": query,
                        "offset": offset,
                        "limit": page_size,
                        "request_token": request_token,
                    },
                    loading_text=f"DB 자막 검색 추가 조회 중... ({query[:15]})",
                )
                if started:
                    state["loading"] = True
                    self._set_db_search_dialog_busy(True, "검색 결과를 더 불러오는 중입니다...")

            more_btn.clicked.connect(load_more)
            button_layout.addWidget(more_btn)

            close_btn = QPushButton("닫기")
            close_btn.clicked.connect(dialog.reject)
            button_layout.addWidget(close_btn)
            layout.addLayout(button_layout)

            self._db_search_dialog_state = {
                "dialog": dialog,
                "query": query,
                "results": results,
                "list_widget": list_widget,
                "status_label": status_label,
                "loaded_label": loaded_label,
                "load_btn": load_btn,
                "focus_btn": focus_btn,
                "close_btn": close_btn,
                "more_btn": more_btn,
                "offset": len(results),
                "page_size": page_size,
                "has_more": len(results) >= page_size,
                "loading": False,
                "request_token": int(
                    request_token
                    if request_token is not None
                    else self.__dict__.get("_db_search_request_token", 0)
                ),
            }
            for row in results:
                list_widget.addItem(self._format_db_search_item(row))
            self._update_db_search_loaded_label()
            more_btn.setEnabled(len(results) >= page_size)
            if list_widget.count() > 0:
                list_widget.setCurrentRow(0)
            dialog.finished.connect(lambda *_: self._clear_db_search_dialog_state())

            dialog.exec()
