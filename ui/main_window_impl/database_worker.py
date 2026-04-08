# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowDatabaseWorkerMixin(MainWindowHost):

    def _ensure_db_worker_state(self) -> None:
            if self.__dict__.get("_db_worker_lock") is None:
                self._db_worker_lock = threading.Lock()
            if self.__dict__.get("_db_worker_queue") is None:
                self._db_worker_queue = queue.Queue()
            if "_db_worker_shutdown" not in self.__dict__:
                self._db_worker_shutdown = False
            if "_db_worker_current_task" not in self.__dict__:
                self._db_worker_current_task = ""
            if "_db_history_request_token" not in self.__dict__:
                self._db_history_request_token = 0
            if "_db_search_request_token" not in self.__dict__:
                self._db_search_request_token = 0

    def _ensure_db_worker_started(self) -> bool:
            self._ensure_db_worker_state()
            if self._is_background_shutdown_active() or bool(self._db_worker_shutdown):
                return False

            thread = self.__dict__.get("_db_worker_thread")
            if thread is not None and thread.is_alive():
                return True

            with self._db_worker_lock:
                thread = self.__dict__.get("_db_worker_thread")
                if thread is not None and thread.is_alive():
                    return True
                if self._is_background_shutdown_active() or bool(self._db_worker_shutdown):
                    return False

                def worker_loop() -> None:
                    while True:
                        task = self._db_worker_queue.get()
                        if not isinstance(task, dict):
                            continue
                        if bool(task.get("shutdown", False)):
                            break

                        task_name = str(task.get("task_name", "db_task") or "db_task")
                        worker = task.get("worker")
                        context = dict(task.get("context") or {})
                        emit_result = bool(task.get("emit_result", True))
                        write_task = bool(task.get("write_task", False))
                        done_event = task.get("done_event")
                        holder = task.get("holder")
                        self._db_worker_current_task = task_name
                        try:
                            if not callable(worker):
                                raise RuntimeError(f"Invalid DB worker task: {task_name}")
                            result = worker()
                            if write_task and self.db is not None:
                                self.db.checkpoint("PASSIVE")
                            if isinstance(holder, dict):
                                holder["result"] = result
                            if emit_result:
                                self._emit_control_message(
                                    "db_task_result",
                                    {
                                        "task": task_name,
                                        "result": result,
                                        "context": context,
                                    },
                                )
                        except Exception as e:
                            if isinstance(holder, dict):
                                holder["error"] = e
                            if emit_result:
                                logger.exception("DB 작업 실패 (%s)", task_name)
                                self._emit_control_message(
                                    "db_task_error",
                                    {
                                        "task": task_name,
                                        "error": str(e),
                                        "context": context,
                                    },
                                )
                        finally:
                            self._db_worker_current_task = ""
                            if done_event is not None:
                                try:
                                    done_event.set()
                                except Exception:
                                    pass

                    try:
                        if self.db is not None:
                            self.db.checkpoint("PASSIVE")
                    except Exception:
                        logger.debug("DB worker shutdown checkpoint 실패", exc_info=True)
                    finally:
                        self._db_worker_current_task = ""

                worker_thread = threading.Thread(
                    target=worker_loop,
                    daemon=False,
                    name="DBWorker",
                )
                self._db_worker_thread = worker_thread

                try:
                    worker_thread.start()
                except Exception as e:
                    self._db_worker_thread = None
                    logger.error("DB worker 시작 실패: %s", e)
                    return False
            return True

    def _begin_db_worker_shutdown(self) -> None:
            self._ensure_db_worker_state()
            with self._db_worker_lock:
                if self._db_worker_shutdown:
                    return
                self._db_worker_shutdown = True
                thread = self.__dict__.get("_db_worker_thread")
            if thread is not None and thread.is_alive():
                try:
                    self._db_worker_queue.put_nowait({"shutdown": True})
                except Exception:
                    logger.debug("DB worker shutdown sentinel enqueue 실패", exc_info=True)

    def _shutdown_db_worker(self, timeout: float | None = None) -> None:
            self._ensure_db_worker_state()
            self._begin_db_worker_shutdown()
            thread = self.__dict__.get("_db_worker_thread")
            if thread is None:
                return
            join_timeout = None if timeout is None else max(0.0, float(timeout))
            thread.join(timeout=join_timeout)
            if not thread.is_alive():
                self._db_worker_thread = None

    def _run_db_task_sync(
            self,
            task_name: str,
            worker,
            *,
            write_task: bool = False,
        ) -> Any:
            self._ensure_db_worker_state()
            if not self.db:
                raise RuntimeError("데이터베이스가 초기화되지 않았습니다.")
            if self._is_background_shutdown_active() or bool(self._db_worker_shutdown):
                raise RuntimeError("종료 중에는 DB 작업을 시작할 수 없습니다.")
            if not self._ensure_db_worker_started():
                raise RuntimeError("DB worker를 시작할 수 없습니다.")

            done_event = threading.Event()
            holder: dict[str, Any] = {}
            self._db_worker_queue.put(
                {
                    "task_name": task_name,
                    "worker": worker,
                    "emit_result": False,
                    "write_task": write_task,
                    "done_event": done_event,
                    "holder": holder,
                }
            )
            completed = done_event.wait(timeout=float(Config.DB_SYNC_TASK_TIMEOUT_SECONDS))
            if not completed:
                raise TimeoutError(
                    f"DB 작업 타임아웃 ({task_name}, {Config.DB_SYNC_TASK_TIMEOUT_SECONDS:.1f}s)"
                )
            if "error" in holder:
                raise holder["error"]
            return holder.get("result")

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

            if not self._ensure_db_worker_started():
                self._show_toast("DB 워커를 시작할 수 없습니다.", "error")
                if loading_text:
                    self._set_status("DB 작업 시작 실패", "error")
                return False

            self._db_tasks_inflight.add(task_name)
            if loading_text:
                self._set_status(loading_text, "running")

            payload_context = dict(context or {})
            try:
                self._db_worker_queue.put_nowait(
                    {
                        "task_name": task_name,
                        "worker": worker,
                        "context": payload_context,
                        "emit_result": True,
                        "write_task": bool(
                            payload_context.get("write_task", False)
                            or task_name == "db_session_save"
                        ),
                    }
                )
            except Exception:
                self._db_tasks_inflight.discard(task_name)
                if loading_text:
                    self._set_status("DB 작업 시작 실패", "error")
                logger.exception("DB 작업 큐 적재 실패 (%s)", task_name)
                return False
            return True

    def _handle_db_task_result(
            self, task_name: str, result: Any, context: dict | None = None
        ) -> None:
            """DB 비동기 작업 완료 처리 (UI 스레드)."""
            context = context or {}
            request_token = int(context.get("request_token", 0) or 0)
            if task_name == "db_history_list":
                sessions = result if isinstance(result, list) else []
                if not sessions:
                    QMessageBox.information(self, "세션 히스토리", "저장된 세션이 없습니다.")
                    self._set_status("세션 히스토리 없음", "info")
                    return
                self._open_db_history_dialog(
                    sessions,
                    page_size=int(context.get("limit", Config.DB_HISTORY_PAGE_SIZE) or Config.DB_HISTORY_PAGE_SIZE),
                )
                self._set_status(f"세션 히스토리 조회 완료 ({len(sessions)}건)", "success")
                return

            if task_name == "db_history_list_more":
                state = self.__dict__.get("_db_history_dialog_state") or {}
                if request_token and request_token != int(state.get("request_token", 0)):
                    return
                self._set_db_history_dialog_busy(False)
                sessions = result if isinstance(result, list) else []
                self._append_db_history_sessions(sessions)
                if not sessions:
                    state["has_more"] = False
                    more_btn = state.get("more_btn")
                    if more_btn is not None:
                        more_btn.setEnabled(False)
                    self._set_status("세션 히스토리 추가 결과 없음", "info")
                else:
                    self._set_status(f"세션 히스토리 추가 로드 ({len(sessions)}건)", "success")
                return

            if task_name == "db_search":
                query = str(context.get("query", "")).strip()
                if request_token and request_token != int(
                    self.__dict__.get("_db_search_request_token", 0)
                ):
                    return
                results = result if isinstance(result, list) else []
                if not results:
                    QMessageBox.information(
                        self, "검색 결과", f"'{query}'에 대한 검색 결과가 없습니다."
                    )
                    self._set_status("자막 검색 결과 없음", "info")
                    return
                self._show_db_search_results(
                    query,
                    results,
                    page_size=int(context.get("limit", Config.DB_SEARCH_PAGE_SIZE) or Config.DB_SEARCH_PAGE_SIZE),
                    request_token=request_token,
                )
                self._set_status(f"자막 검색 완료 ({len(results)}건)", "success")
                return

            if task_name == "db_search_more":
                state = self.__dict__.get("_db_search_dialog_state") or {}
                if request_token and request_token != int(state.get("request_token", 0)):
                    return
                self._set_db_search_dialog_busy(False)
                results = result if isinstance(result, list) else []
                self._append_db_search_results(results)
                if not results:
                    state["has_more"] = False
                    more_btn = state.get("more_btn")
                    if more_btn is not None:
                        more_btn.setEnabled(False)
                    self._set_status("자막 검색 추가 결과 없음", "info")
                else:
                    self._set_status(f"자막 검색 추가 로드 ({len(results)}건)", "success")
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

                state = self.__dict__.get("_db_history_dialog_state") or {}
                dialog = state.get("dialog")
                if dialog is not None:
                    dialog.accept()
                return

            if task_name == "db_search_load_selected":
                self._set_db_search_dialog_busy(False)
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

                state = self.__dict__.get("_db_history_dialog_state") or {}
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
                    state["offset"] = len(sessions)
                    self._update_db_history_loaded_label()

                self._show_toast("세션 삭제됨", "info")
                self._set_status("세션 삭제 완료", "success")
                return

    def _handle_db_task_error(
            self, task_name: str, error: str, context: dict | None = None
        ) -> None:
            """DB 비동기 작업 실패 처리 (UI 스레드)."""
            context = context or {}
            request_token = int(context.get("request_token", 0) or 0)
            if task_name == "db_search" and request_token:
                if request_token != int(self.__dict__.get("_db_search_request_token", 0)):
                    return
            if task_name == "db_search_more" and request_token:
                search_state = self.__dict__.get("_db_search_dialog_state") or {}
                if request_token != int(search_state.get("request_token", 0)):
                    return
            if task_name == "db_history_list_more" and request_token:
                history_state = self.__dict__.get("_db_history_dialog_state") or {}
                if request_token != int(history_state.get("request_token", 0)):
                    return
            if task_name in (
                "db_history_load_selected",
                "db_history_delete_selected",
                "db_history_list_more",
                "db_search_load_selected",
                "db_search_more",
            ):
                history_state = self.__dict__.get("_db_history_dialog_state") or {}
                search_state = self.__dict__.get("_db_search_dialog_state") or {}
                history_state["loading"] = False
                search_state["loading"] = False
                self._set_db_history_dialog_busy(False)
                self._set_db_search_dialog_busy(False)
            query_hint = str(context.get("query", "")).strip()
            message = f"DB 작업 실패 ({task_name}): {error}"
            if task_name == "db_search" and query_hint:
                message = f"검색 실패 ('{query_hint}'): {error}"
            self._set_status(message, "error")
            QMessageBox.warning(self, "데이터베이스 오류", message)
