# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowDatabaseMixin(MainWindowHost):

    def _set_db_history_dialog_busy(self, busy: bool, message: str = "") -> None:
            """DB 히스토리 다이얼로그의 버튼/목록 상태를 토글한다."""
            state = self._db_history_dialog_state or {}
            load_btn = state.get("load_btn")
            delete_btn = state.get("delete_btn")
            close_btn = state.get("close_btn")
            list_widget = state.get("list_widget")
            status_label = state.get("status_label")

            for btn in (load_btn, delete_btn, close_btn):
                if btn is not None:
                    btn.setEnabled(not busy)
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


    def _run_db_task(
            self,
            task_name: str,
            worker,
            context: dict | None = None,
            loading_text: str = "",
        ) -> bool:
            """DB 작업을 백그라운드 스레드에서 실행하고 결과를 큐로 전달한다."""
            if self._is_background_shutdown_active():
                self._show_toast("종료 중이라 DB 작업을 시작할 수 없습니다.", "warning")
                return False

            if not self.db:
                QMessageBox.warning(self, "알림", "데이터베이스가 초기화되지 않았습니다.")
                return False

            if task_name in self._db_tasks_inflight:
                self._show_toast("이미 같은 DB 작업이 실행 중입니다.", "info")
                return False

            self._db_tasks_inflight.add(task_name)
            if loading_text:
                self._set_status(loading_text, "running")

            payload_context = dict(context or {})

            def _work():
                try:
                    result = worker()
                    self.message_queue.put(
                        (
                            "db_task_result",
                            {
                                "task": task_name,
                                "result": result,
                                "context": payload_context,
                            },
                        )
                    )
                except Exception as e:
                    logger.exception("DB 작업 실패 (%s)", task_name)
                    self.message_queue.put(
                        (
                            "db_task_error",
                            {"task": task_name, "error": str(e), "context": payload_context},
                        )
                    )

            started = self._start_background_thread(_work, f"DBTask-{task_name}")
            if not started:
                self._db_tasks_inflight.discard(task_name)
                if loading_text:
                    self._set_status("DB 작업 시작 거부 (종료 중)", "warning")
                return False
            return True


    def _handle_db_task_result(
            self, task_name: str, result: Any, context: dict | None = None
        ) -> None:
            """DB 비동기 작업 완료 처리 (UI 스레드)."""
            context = context or {}
            if task_name == "db_history_list":
                sessions = result if isinstance(result, list) else []
                if not sessions:
                    QMessageBox.information(self, "세션 히스토리", "저장된 세션이 없습니다.")
                    self._set_status("세션 히스토리 없음", "info")
                    return
                self._open_db_history_dialog(sessions)
                self._set_status("세션 히스토리 조회 완료", "success")
                return

            if task_name == "db_search":
                query = str(context.get("query", "")).strip()
                results = result if isinstance(result, list) else []
                if not results:
                    QMessageBox.information(
                        self, "검색 결과", f"'{query}'에 대한 검색 결과가 없습니다."
                    )
                    self._set_status("자막 검색 결과 없음", "info")
                    return
                self._show_db_search_results(query, results)
                self._set_status(f"자막 검색 완료 ({len(results)}건)", "success")
                return

            if task_name == "db_stats":
                stats = result if isinstance(result, dict) else {}
                self._show_db_stats_dialog(stats)
                self._set_status("DB 통계 조회 완료", "success")
                return

            if task_name == "db_history_load_selected":
                self._set_db_history_dialog_busy(False)
                payload = result if isinstance(result, dict) else {}
                if not self._complete_loaded_session(payload):
                    if not payload.get("_cancelled"):
                        self._set_status("세션 불러오기 실패", "error")
                        self._show_toast("세션을 불러오지 못했습니다.", "error")
                    return

                state = self._db_history_dialog_state or {}
                dialog = state.get("dialog")
                if dialog is not None:
                    dialog.accept()
                return

            if task_name == "db_search_load_selected":
                payload = result if isinstance(result, dict) else {}
                if not self._complete_loaded_session(payload):
                    if not payload.get("_cancelled"):
                        self._set_status("검색 결과 세션 불러오기 실패", "error")
                        self._show_toast("검색 결과 세션을 불러오지 못했습니다.", "error")
                    return
                dialog = context.get("dialog")
                if dialog is not None:
                    dialog.accept()
                return

            if task_name == "db_history_delete_selected":
                self._set_db_history_dialog_busy(False)
                deleted = bool(result)
                if not deleted:
                    self._set_status("세션 삭제 실패", "error")
                    self._show_toast("세션 삭제 실패", "error")
                    return

                state = self._db_history_dialog_state or {}
                sessions = state.get("sessions")
                list_widget = state.get("list_widget")
                session_id = context.get("session_id")

                remove_idx = None
                if isinstance(sessions, list):
                    for i, item in enumerate(sessions):
                        if item.get("id") == session_id:
                            remove_idx = i
                            break
                if (
                    remove_idx is not None
                    and list_widget is not None
                    and isinstance(sessions, list)
                ):
                    list_widget.takeItem(remove_idx)
                    sessions.pop(remove_idx)

                self._show_toast("세션 삭제됨", "info")
                self._set_status("세션 삭제 완료", "success")
                return


    def _handle_db_task_error(
            self, task_name: str, error: str, context: dict | None = None
        ) -> None:
            """DB 비동기 작업 실패 처리 (UI 스레드)."""
            context = context or {}
            if task_name in (
                "db_history_load_selected",
                "db_history_delete_selected",
                "db_search_load_selected",
            ):
                self._set_db_history_dialog_busy(False)
            query_hint = str(context.get("query", "")).strip()
            message = f"DB 작업 실패 ({task_name}): {error}"
            if task_name == "db_search" and query_hint:
                message = f"검색 실패 ('{query_hint}'): {error}"
            self._set_status(message, "error")
            QMessageBox.warning(self, "데이터베이스 오류", message)


    def _show_db_history(self):
            """세션 히스토리 다이얼로그 표시"""
            db = self.db
            if db is None:
                QMessageBox.warning(self, "알림", "데이터베이스가 초기화되지 않았습니다.")
                return
            self._run_db_task(
                "db_history_list",
                worker=lambda: db.list_sessions(limit=50),
                loading_text="DB 세션 히스토리 조회 중...",
            )


    def _open_db_history_dialog(self, sessions: list[dict]) -> None:
            dialog = QDialog(self)
            dialog.setWindowTitle("📋 세션 히스토리")
            dialog.setMinimumSize(700, 500)

            layout = QVBoxLayout(dialog)

            # 세션 목록
            list_widget = QListWidget()
            for s in sessions:
                created = s.get("created_at", "")[:19] if s.get("created_at") else ""
                committee = s.get("committee_name") or "알 수 없음"
                subtitles = s.get("total_subtitles", 0)
                chars = s.get("total_characters", 0)
                list_widget.addItem(
                    f"[{created}] {committee} - {subtitles}문장, {chars:,}자"
                )

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
                if not session_id:
                    self._show_toast("유효한 세션 ID가 없습니다.", "warning")
                    return
                db = self.db
                if db is None:
                    self._show_toast("데이터베이스가 초기화되지 않았습니다.", "error")
                    return

                def worker(sid=session_id):
                    session_data = db.load_session(sid)
                    if not session_data:
                        return {}
                    new_subtitles, skipped = self._deserialize_subtitles(
                        session_data.get("subtitles", []),
                        source=f"db_session:{sid}",
                    )
                    return {
                        "version": session_data.get("version", "unknown"),
                        "created_at": session_data.get("created_at", ""),
                        "url": session_data.get("url", ""),
                        "committee_name": session_data.get("committee_name", ""),
                        "subtitles": new_subtitles,
                        "skipped": skipped,
                    }

                started = self._run_db_task(
                    "db_history_load_selected",
                    worker=worker,
                    context={"session_id": session_id, "row": idx},
                    loading_text="DB 세션 불러오는 중...",
                )
                if started:
                    self._set_db_history_dialog_busy(
                        True, "세션을 불러오는 중입니다..."
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
                "load_btn": load_btn,
                "delete_btn": delete_btn,
                "close_btn": close_btn,
            }
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

            self._run_db_task(
                "db_search",
                worker=lambda q=query: db.search_subtitles(q),
                context={"query": query},
                loading_text=f"DB 자막 검색 중... ({query[:15]})",
            )


    def _show_db_search_results(self, query: str, results: list[dict]) -> None:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"🔍 검색 결과 - '{query}'")
            dialog.setMinimumSize(700, 500)

            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel(f"총 {len(results)}개 결과"))

            list_widget = QListWidget()
            for r in results:
                created = r.get("created_at", "")[:10] if r.get("created_at") else ""
                committee = r.get("committee_name") or ""
                text = r.get("text", "")[:100]
                list_widget.addItem(f"[{created}] {committee}: {text}")

            layout.addWidget(list_widget)

            if list_widget.count() > 0:
                list_widget.setCurrentRow(0)

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
                if not session_id:
                    self._show_toast("유효한 세션 ID가 없습니다.", "warning")
                    return

                db = self.db
                if db is None:
                    self._show_toast("데이터베이스가 초기화되지 않았습니다.", "error")
                    return

                def worker(sid=session_id, row=selected):
                    session_data = db.load_session(sid)
                    if not session_data:
                        return {}
                    new_subtitles, skipped = self._deserialize_subtitles(
                        session_data.get("subtitles", []),
                        source=f"db_search_session:{sid}",
                    )
                    payload = {
                        "version": session_data.get("version", "unknown"),
                        "created_at": session_data.get("created_at", ""),
                        "url": session_data.get("url", ""),
                        "committee_name": session_data.get("committee_name", ""),
                        "subtitles": new_subtitles,
                        "skipped": skipped,
                    }
                    if highlight:
                        payload["highlight_sequence"] = int(row.get("sequence", -1) or -1)
                        payload["highlight_query"] = query
                    return payload

                self._run_db_task(
                    "db_search_load_selected",
                    worker=worker,
                    context={
                        "dialog": dialog,
                        "session_id": session_id,
                        "highlight": highlight,
                        "query": query,
                    },
                    loading_text="DB 검색 결과 세션 불러오는 중...",
                )

            load_btn.clicked.connect(lambda: load_selected(False))
            focus_btn.clicked.connect(lambda: load_selected(True))
            load_btn.setEnabled(not self.is_running)
            focus_btn.setEnabled(not self.is_running)
            button_layout.addWidget(load_btn)
            button_layout.addWidget(focus_btn)

            close_btn = QPushButton("닫기")
            close_btn.clicked.connect(dialog.reject)
            button_layout.addWidget(close_btn)
            layout.addLayout(button_layout)

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

                # 기존 자막 처리 옵션 확인
                existing_subtitles: list[SubtitleEntry] | None = None
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
                        with self.subtitle_lock:
                            existing_subtitles = list(self.subtitles)

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
                    self._replace_subtitles_and_refresh(merged)
                    self._show_toast(f"병합 완료! {len(merged)}개 문장", "success")
                    dialog.accept()

            merge_btn.clicked.connect(do_merge)
            btn_layout.addWidget(merge_btn)

            cancel_btn = QPushButton("취소")
            cancel_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(cancel_btn)

            layout.addLayout(btn_layout)
            dialog.exec()
