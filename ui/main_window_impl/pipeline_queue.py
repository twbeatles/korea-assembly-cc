# -*- coding: utf-8 -*-

from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING, Any, Callable

from core.config import Config
from core.logging_utils import logger
from ui.main_window_common import WorkerQueueMessage
from ui.main_window_impl.contracts import PipelineQueueHost


COALESCED_WORKER_MESSAGE_TYPES = {
    "connection_status",
    "keepalive",
    "reconnected",
    "reconnecting",
    "resolved_url",
    "status",
}
PRIORITY_OVERFLOW_WORKER_TYPES = frozenset(
    {
        "error",
        "finished",
        "subtitle_not_found",
        "subtitle_reset",
        "subtitle_segments",
    }
)
TERMINAL_WORKER_MESSAGE_TYPES = {
    "error",
    "finished",
    "subtitle_not_found",
}
COALESCED_WORKER_MESSAGE_ORDER = (
    "resolved_url",
    "status",
    "connection_status",
    "reconnecting",
    "reconnected",
    "keepalive",
)
COALESCED_CONTROL_MESSAGE_TYPES = {
    "db_task_error",
    "db_task_result",
    "hydrate_cancelled",
    "hydrate_done",
    "hydrate_failed",
    "hydrate_progress",
    "hwp_save_failed",
    "reflow_done",
    "reflow_failed",
    "runtime_search_done",
    "runtime_search_failed",
    "runtime_segment_flush_done",
    "runtime_segment_flush_failed",
    "session_load_done",
    "session_load_failed",
    "session_load_json_error",
    "session_save_done",
    "session_save_failed",
    "toast",
}
DURABLE_CONTROL_MESSAGE_TYPES = set(COALESCED_CONTROL_MESSAGE_TYPES)


PipelineQueueBase = PipelineQueueHost if TYPE_CHECKING else object


class MainWindowPipelineQueueMixin(PipelineQueueBase):
    def _ensure_overflow_passthrough_state(self) -> None:
        state = getattr(self, "__dict__", {})
        if state.get("_overflow_passthrough_lock") is None:
            self._overflow_passthrough_lock = threading.Lock()
        if state.get("_overflow_passthrough_messages") is None:
            self._overflow_passthrough_messages = []

    def _ensure_terminal_worker_message_state(self) -> None:
        state = getattr(self, "__dict__", {})
        if state.get("_terminal_worker_message_lock") is None:
            self._terminal_worker_message_lock = threading.Lock()
        if state.get("_terminal_worker_messages") is None:
            self._terminal_worker_messages = []

    def _ensure_queue_backpressure_state(self) -> None:
        state = getattr(self, "__dict__", {})
        if state.get("_overflow_drop_total") is None:
            self._overflow_drop_total = 0
        if state.get("_worker_message_coalesce_total") is None:
            self._worker_message_coalesce_total = 0
        if not isinstance(state.get("_queue_backpressure_notice_at"), dict):
            self._queue_backpressure_notice_at = {}

    @staticmethod
    def _overflow_message_type(item: object) -> str:
        if isinstance(item, WorkerQueueMessage):
            return str(item.msg_type or "")
        if isinstance(item, tuple) and len(item) == 2:
            return str(item[0] or "")
        return ""

    def _overflow_message_priority(self, item: object) -> int:
        msg_type = self._overflow_message_type(item)
        if msg_type in PRIORITY_OVERFLOW_WORKER_TYPES:
            return 2
        if msg_type == "preview":
            return 1
        return 0

    def _trim_overflow_passthrough_messages(self, messages: list[object]) -> int:
        limit = max(1, int(Config.OVERFLOW_PASSTHROUGH_MAX))
        dropped = 0
        while len(messages) > limit:
            drop_index = 0
            lowest_priority = 3
            for idx, item in enumerate(messages):
                priority = self._overflow_message_priority(item)
                if priority < lowest_priority:
                    lowest_priority = priority
                    drop_index = idx
            messages.pop(drop_index)
            dropped += 1
        return dropped

    def _record_overflow_drop(self, dropped_count: int, *, reason: str) -> None:
        if dropped_count <= 0:
            return
        self._ensure_queue_backpressure_state()
        self._overflow_drop_total = int(self._overflow_drop_total or 0) + int(dropped_count)
        logger.warning(
            "overflow passthrough 메시지 %s건 드롭 (%s, 누적=%s)",
            dropped_count,
            reason,
            self._overflow_drop_total,
        )
        self._notify_worker_queue_backpressure(
            f"내부 메시지 보존 한도 초과로 worker 메시지 {dropped_count}건이 드롭되었습니다.",
            notice_key="overflow_drop",
        )

    def _notify_worker_queue_backpressure(self, message: str, *, notice_key: str) -> None:
        self._ensure_queue_backpressure_state()
        try:
            import time as _time_mod

            now = _time_mod.monotonic()
        except Exception:
            now = 0.0
        last_at = float(self._queue_backpressure_notice_at.get(notice_key, 0.0))
        if now - last_at < float(Config.OVERFLOW_DROP_NOTICE_INTERVAL):
            return
        self._queue_backpressure_notice_at[notice_key] = now
        try:
            status_setter = getattr(self, "_set_status", None)
            if callable(status_setter):
                status_setter(message, "warning")
        except Exception:
            logger.debug("queue backpressure 상태 표시 실패", exc_info=True)
        try:
            toast_setter = getattr(self, "_show_toast", None)
            if callable(toast_setter):
                toast_setter(message, "warning", 3000)
        except Exception:
            logger.debug("queue backpressure toast 표시 실패", exc_info=True)

    def _stash_overflow_passthrough_item(self, item: object) -> None:
        self._ensure_overflow_passthrough_state()
        with self._overflow_passthrough_lock:
            messages = self._overflow_passthrough_messages
            messages.append(item)
            dropped = self._trim_overflow_passthrough_messages(messages)
        if dropped:
            self._record_overflow_drop(dropped, reason="overflow_passthrough_trim")

    def _stash_terminal_worker_message(self, item: WorkerQueueMessage) -> None:
        self._ensure_terminal_worker_message_state()
        with self._terminal_worker_message_lock:
            self._terminal_worker_messages.append(item)

    def _ensure_control_message_state(self) -> None:
        state = getattr(self, "__dict__", {})
        if state.get("_control_message_lock") is None:
            self._control_message_lock = threading.Lock()
        if state.get("_coalesced_control_messages") is None:
            self._coalesced_control_messages = {}

    def _emit_worker_message(
        self,
        msg_type: str,
        data: Any,
        *,
        run_id: int | None = None,
    ) -> None:
        resolved_run_id = (
            run_id if run_id is not None else self._ensure_active_capture_run()
        )
        message = WorkerQueueMessage(int(resolved_run_id), str(msg_type), data)
        try:
            self.message_queue.put_nowait(message)
            return
        except queue.Full:
            if msg_type in TERMINAL_WORKER_MESSAGE_TYPES:
                self._stash_terminal_worker_message(message)
                return
            if msg_type not in COALESCED_WORKER_MESSAGE_TYPES:
                try:
                    self.message_queue.put(
                        message,
                        timeout=float(Config.WORKER_MESSAGE_PUT_TIMEOUT),
                    )
                    return
                except queue.Full:
                    logger.warning(
                        "메시지 큐 포화로 worker 메시지를 overflow 경로에 보존: %s",
                        msg_type,
                    )
                    self._stash_overflow_passthrough_item(message)
                return

        lock = getattr(self, "_worker_message_lock", None)
        if lock is None:
            return
        with lock:
            self._coalesced_worker_messages[(int(resolved_run_id), str(msg_type))] = data
            self._ensure_queue_backpressure_state()
            self._worker_message_coalesce_total = int(
                self._worker_message_coalesce_total or 0
            ) + 1
        if msg_type == "keepalive":
            return
        self._notify_worker_queue_backpressure(
            f"메시지 큐 포화로 {msg_type} 상태를 최신값으로 병합했습니다.",
            notice_key=f"coalesce_{msg_type}",
        )

    def _unwrap_message_item(self, item: object) -> tuple[str, Any] | None:
        if isinstance(item, WorkerQueueMessage):
            if not self._is_active_capture_run(item.run_id):
                return None
            return item.msg_type, item.payload
        if isinstance(item, tuple) and len(item) == 2:
            msg_type, data = item
            return str(msg_type), data
        return None

    def _is_durable_control_message(self, item: object) -> bool:
        if not isinstance(item, tuple) or len(item) != 2:
            return False
        msg_type, _data = item
        return str(msg_type) in DURABLE_CONTROL_MESSAGE_TYPES

    def _build_control_message_key(self, msg_type: str, data: Any) -> object | None:
        if msg_type not in COALESCED_CONTROL_MESSAGE_TYPES:
            return None
        if msg_type in {"db_task_result", "db_task_error"}:
            task_name = ""
            if isinstance(data, dict):
                task_name = str(data.get("task", "") or "").strip()
            return (msg_type, task_name or "db_unknown")
        if msg_type == "toast":
            if isinstance(data, dict):
                toast_type = str(data.get("toast_type", "info") or "info").strip()
                return (msg_type, toast_type or "info")
            return (msg_type, "info")
        return msg_type

    def _emit_control_message(self, msg_type: str, data: Any) -> None:
        normalized_type = str(msg_type)
        item = (normalized_type, data)
        control_queue = self.__dict__.get("app_control_queue")
        if control_queue is None:
            logger.warning("app_control_queue 미초기화 - control 메시지 드롭: %s", normalized_type)
            return
        try:
            control_queue.put_nowait(item)
            return
        except queue.Full:
            pass

        control_key = self._build_control_message_key(normalized_type, data)
        if control_key is None:
            logger.warning("메시지 큐 포화로 nonblocking 메시지 드롭: %s", normalized_type)
            self._notify_dropped_control_message(normalized_type)
            return
        self._ensure_control_message_state()
        with self._control_message_lock:
            self._coalesced_control_messages[control_key] = item

    def _notify_dropped_control_message(self, msg_type: str) -> None:
        """drop 발생 시 사용자에게 한 번이라도 노출 (rate-limit 30s)."""
        state = getattr(self, "__dict__", {})
        last_at_map = state.get("_dropped_control_notice_at")
        if not isinstance(last_at_map, dict):
            last_at_map = {}
            self._dropped_control_notice_at = last_at_map
        try:
            import time as _time_mod
            now = _time_mod.monotonic()
        except Exception:
            now = 0.0
        last_at = float(last_at_map.get(msg_type, 0.0))
        if now - last_at < 30.0:
            return
        last_at_map[msg_type] = now
        try:
            status_setter = getattr(self, "_set_status", None)
            if callable(status_setter):
                status_setter(
                    f"내부 메시지 큐 포화로 메시지({msg_type})가 일시 드롭되었습니다.",
                    "warning",
                )
        except Exception:
            logger.debug("dropped control 메시지 상태 표시 실패", exc_info=True)

    def _requeue_message_item(self, item: object) -> None:
        try:
            self.message_queue.put_nowait(item)
            return
        except queue.Full:
            pass

        if isinstance(item, WorkerQueueMessage):
            if item.msg_type in TERMINAL_WORKER_MESSAGE_TYPES:
                self._stash_terminal_worker_message(item)
                return
            if item.msg_type in COALESCED_WORKER_MESSAGE_TYPES:
                lock = getattr(self, "_worker_message_lock", None)
                if lock is not None:
                    with lock:
                        self._coalesced_worker_messages[(int(item.run_id), str(item.msg_type))] = item.payload
                    return
            self._stash_overflow_passthrough_item(item)
            return

        if isinstance(item, tuple) and len(item) == 2:
            msg_type, data = item
            if self._is_durable_control_message(item):
                control_queue = self.__dict__.get("app_control_queue")
                if control_queue is not None:
                    try:
                        control_queue.put_nowait((str(msg_type), data))
                        return
                    except queue.Full:
                        pass
            control_key = self._build_control_message_key(str(msg_type), data)
            if control_key is not None:
                self._ensure_control_message_state()
                with self._control_message_lock:
                    self._coalesced_control_messages[control_key] = (str(msg_type), data)
                return

        self._stash_overflow_passthrough_item(item)

    def _pop_terminal_worker_messages(self, *, max_items: int) -> list[object]:
        if max_items <= 0:
            return []
        self._ensure_terminal_worker_message_state()
        with self._terminal_worker_message_lock:
            items = list(self._terminal_worker_messages[:max_items])
            del self._terminal_worker_messages[:max_items]
        return items

    def _drain_terminal_worker_messages(
        self,
        *,
        max_items: int,
        handler: Callable[[str, Any], None] | None = None,
    ) -> int:
        processed = 0
        drain_handler = handler or self._handle_message
        for raw_item in self._pop_terminal_worker_messages(max_items=max_items):
            decoded = self._unwrap_message_item(raw_item)
            if decoded is None:
                continue
            msg_type, data = decoded
            drain_handler(msg_type, data)
            processed += 1
        return processed

    def _pop_overflow_passthrough_items(self, *, max_items: int) -> list[object]:
        if max_items <= 0:
            return []
        self._ensure_overflow_passthrough_state()
        with self._overflow_passthrough_lock:
            items = list(self._overflow_passthrough_messages[:max_items])
            del self._overflow_passthrough_messages[:max_items]
        return items

    def _drain_overflow_passthrough_items(
        self,
        *,
        max_items: int,
        handler: Callable[[str, Any], None] | None = None,
        allowed_types: set[str] | None = None,
        requeue_others: bool = False,
    ) -> int:
        processed = 0
        drain_handler = handler or self._handle_message
        requeue: list[object] = []
        for raw_item in self._pop_overflow_passthrough_items(max_items=max_items):
            decoded = self._unwrap_message_item(raw_item)
            if decoded is None:
                processed += 1
                continue
            msg_type, data = decoded
            if allowed_types is not None and msg_type not in allowed_types:
                requeue.append(raw_item)
                continue
            drain_handler(msg_type, data)
            processed += 1
        if requeue_others and requeue:
            for item in requeue:
                self._stash_overflow_passthrough_item(item)
        return processed

    def _pop_coalesced_control_messages(self, *, max_items: int) -> list[tuple[str, Any]]:
        if max_items <= 0:
            return []
        self._ensure_control_message_state()
        collected: list[tuple[str, Any]] = []
        with self._control_message_lock:
            keys = list(self._coalesced_control_messages.keys())[:max_items]
            for key in keys:
                payload = self._coalesced_control_messages.pop(key, None)
                if (
                    isinstance(payload, tuple)
                    and len(payload) == 2
                ):
                    collected.append((str(payload[0]), payload[1]))
        return collected

    def _drain_coalesced_control_messages(
        self,
        *,
        max_items: int,
        handler: Callable[[str, Any], None] | None = None,
    ) -> int:
        processed = 0
        drain_handler = handler or self._handle_message
        for msg_type, data in self._pop_coalesced_control_messages(max_items=max_items):
            drain_handler(msg_type, data)
            processed += 1
        return processed

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

    def _clear_message_queue(self, *, preserve_control_messages: bool = True) -> None:
        """worker capture 큐만 비운다. control 큐는 기본적으로 유지한다."""
        try:
            while True:
                self.message_queue.get_nowait()
        except queue.Empty:
            pass
        lock = getattr(self, "_worker_message_lock", None)
        if lock is not None:
            with lock:
                getattr(self, "_coalesced_worker_messages", {}).clear()
        self._ensure_control_message_state()
        if not preserve_control_messages:
            control_queue = self.__dict__.get("app_control_queue")
            if control_queue is not None:
                clear_queue = getattr(control_queue, "clear", None)
                if callable(clear_queue):
                    clear_queue()
            with self._control_message_lock:
                self._coalesced_control_messages.clear()
        self._ensure_overflow_passthrough_state()
        with self._overflow_passthrough_lock:
            self._overflow_passthrough_messages[:] = [
                item
                for item in self._overflow_passthrough_messages
                if not self._is_durable_control_message(item)
            ]
        self._ensure_terminal_worker_message_state()
        with self._terminal_worker_message_lock:
            self._terminal_worker_messages.clear()
