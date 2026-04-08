# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowDatabaseDialogsMixin(MainWindowHost):

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

            def continue_load() -> None:
                def worker(sid: int = normalized_session_id):
                    session_data = db.load_session(sid)
                    if not session_data:
                        return {}
                    new_subtitles, skipped = self._deserialize_subtitles(
                        session_data.get("subtitles", []),
                        source=f"{source_tag}:{sid}",
                    )
                    payload = {
                        "db_session_id": session_data.get("id"),
                        "version": session_data.get("version", "unknown"),
                        "created_at": session_data.get("created_at", ""),
                        "url": session_data.get("url", ""),
                        "committee_name": session_data.get("committee_name", ""),
                        "lineage_id": session_data.get("lineage_id", ""),
                        "subtitles": new_subtitles,
                        "skipped": skipped,
                    }
                    if highlight_sequence >= 0:
                        payload["highlight_sequence"] = highlight_sequence
                        payload["highlight_query"] = highlight_query
                    return payload

                context: dict[str, Any] = {"session_id": normalized_session_id}
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

    def _show_db_history(self):
            """세션 히스토리 다이얼로그 표시"""
            db = self.db
            if db is None:
                QMessageBox.warning(self, "알림", "데이터베이스가 초기화되지 않았습니다.")
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

    def _show_db_search(self):
            """자막 통합 검색 다이얼로그"""
            db = self.db
            if db is None:
                QMessageBox.warning(self, "알림", "데이터베이스가 초기화되지 않았습니다.")
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

    def _show_db_stats(self):
            """데이터베이스 전체 통계"""
            db = self.db
            if db is None:
                QMessageBox.warning(self, "알림", "데이터베이스가 초기화되지 않았습니다.")
                return
            self._run_db_task(
                "db_stats",
                worker=lambda: db.get_statistics(),
                loading_text="DB 통계 조회 중...",
            )

    def _show_db_stats_dialog(self, stats: dict) -> None:
            msg = f"""
    <h2>📊 데이터베이스 통계</h2>
    <table>
    <tr><td><b>총 세션 수:</b></td><td>{stats.get("total_sessions", 0):,}개</td></tr>
    <tr><td><b>총 자막 수:</b></td><td>{stats.get("total_subtitles", 0):,}개</td></tr>
    <tr><td><b>총 글자 수:</b></td><td>{stats.get("total_characters", 0):,}자</td></tr>
    <tr><td><b>총 녹화 시간:</b></td><td>{stats.get("total_duration_hours", 0):.1f}시간</td></tr>
    </table>
    """
            QMessageBox.information(self, "데이터베이스 통계", msg)

    def _show_merge_dialog(self):
            """자막 병합 다이얼로그"""
            if self._is_runtime_mutation_blocked("세션 병합"):
                return
            dialog = QDialog(self)
            dialog.setWindowTitle("📎 자막 병합")
            dialog.setMinimumSize(600, 500)

            layout = QVBoxLayout(dialog)

            # 파일 목록
            layout.addWidget(QLabel("병합할 세션 파일을 추가하세요:"))
            file_list = QListWidget()
            file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            layout.addWidget(file_list)

            file_paths = []

            # 파일 추가/제거 버튼
            file_btn_layout = QHBoxLayout()

            add_btn = QPushButton("➕ 파일 추가")

            def add_files():
                paths, _ = QFileDialog.getOpenFileNames(
                    dialog, "세션 파일 선택", f"{Config.SESSION_DIR}/", "JSON 파일 (*.json)"
                )
                for path in paths:
                    if path not in file_paths:
                        file_paths.append(path)
                        file_list.addItem(Path(path).name)

            add_btn.clicked.connect(add_files)
            file_btn_layout.addWidget(add_btn)

            remove_btn = QPushButton("➖ 선택 제거")

            def remove_files():
                for item in file_list.selectedItems():
                    idx = file_list.row(item)
                    file_list.takeItem(idx)
                    if idx < len(file_paths):
                        file_paths.pop(idx)

            remove_btn.clicked.connect(remove_files)
            file_btn_layout.addWidget(remove_btn)

            layout.addLayout(file_btn_layout)

            # 옵션
            options_layout = QHBoxLayout()
            remove_dup_check = QCheckBox("중복 자막 제거")
            remove_dup_check.setChecked(True)
            sort_check = QCheckBox("시간순 정렬")
            sort_check.setChecked(True)
            dedupe_mode_combo = QComboBox()
            dedupe_mode_combo.addItem("보수적 (같은 초 동일 문장)", "conservative_same_second")
            dedupe_mode_combo.addItem("기존 (30초 버킷)", "legacy_bucket")
            options_layout.addWidget(remove_dup_check)
            options_layout.addWidget(sort_check)
            options_layout.addWidget(QLabel("중복 기준:"))
            options_layout.addWidget(dedupe_mode_combo)
            options_layout.addStretch()
            layout.addLayout(options_layout)

            # 버튼
            btn_layout = QHBoxLayout()

            merge_btn = QPushButton("병합 실행")

            def do_merge():
                if len(file_paths) < 2:
                    QMessageBox.warning(dialog, "알림", "2개 이상의 파일을 선택하세요.")
                    return

                def apply_merge(
                    existing_subtitles: list[SubtitleEntry] | None = None,
                ) -> None:
                    merged = self._merge_sessions(
                        file_paths,
                        remove_duplicates=remove_dup_check.isChecked(),
                        sort_by_time=sort_check.isChecked(),
                        existing_subtitles=existing_subtitles,
                        dedupe_mode=str(
                            dedupe_mode_combo.currentData() or "legacy_bucket"
                        ),
                    )

                    if merged:
                        self._store_destructive_undo_snapshot()
                        self._replace_subtitles_and_refresh(merged)
                        self._set_capture_source_metadata("", "")
                        self._mark_session_dirty()
                        self._notify_destructive_undo_available()
                        self._show_toast(f"병합 완료! {len(merged)}개 문장", "success")
                        dialog.accept()

                if self.subtitles:
                    reply = QMessageBox.question(
                        dialog,
                        "기존 자막 처리",
                        f"현재 {len(self.subtitles)}개의 자막이 있습니다.\n\n"
                        "기존 자막을 병합 결과에 포함하시겠습니까?\n"
                        "(Yes: 포함하여 병합 / No: 기존 자막 무시하고 파일들만 병합)",
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No
                        | QMessageBox.StandardButton.Cancel,
                    )
                    if reply == QMessageBox.StandardButton.Cancel:
                        return

                    if reply == QMessageBox.StandardButton.Yes:
                        def continue_merge_with_existing() -> None:
                            with self.subtitle_lock:
                                existing_subtitles = list(self.subtitles)
                            apply_merge(existing_subtitles)

                        self._run_after_full_session_hydrated(
                            "세션 병합",
                            continue_merge_with_existing,
                        )
                        return

                    if self._block_session_replacement_while_saving("세션 병합"):
                        return
                    self._run_after_dirty_session_action(
                        "세션 병합",
                        lambda: apply_merge(None),
                    )
                    return

                apply_merge(None)

            merge_btn.clicked.connect(do_merge)
            btn_layout.addWidget(merge_btn)

            cancel_btn = QPushButton("취소")
            cancel_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(cancel_btn)

            layout.addLayout(btn_layout)
            dialog.exec()
