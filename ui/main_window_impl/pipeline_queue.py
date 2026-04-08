# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from core.logging_utils import logger
from ui.main_window_common import WorkerQueueMessage
from ui.main_window_impl.contracts import PipelineQueueHost


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


PipelineQueueBase = object


class MainWindowPipelineQueueMixin(PipelineQueueBase):
    def _ensure_overflow_passthrough_state(self) -> None:
        state = getattr(self, "__dict__", {})
        if state.get("_overflow_passthrough_lock") is None:
            self._overflow_passthrough_lock = threading.Lock()
        if state.get("_overflow_passthrough_messages") is None:
            self._overflow_passthrough_messages = []

    def _stash_overflow_passthrough_item(self, item: object) -> None:
        self._ensure_overflow_passthrough_state()
        with self._overflow_passthrough_lock:
            messages = self._overflow_passthrough_messages
            messages.append(item)
            if len(messages) > 64:
                del messages[:-64]

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
        try:
            put_nowait = getattr(self.message_queue, "put_nowait", None)
            if callable(put_nowait):
                put_nowait(item)
            else:
                self.message_queue.put(item)
            return
        except queue.Full:
            pass

        control_key = self._build_control_message_key(normalized_type, data)
        if control_key is None:
            logger.warning("메시지 큐 포화로 nonblocking 메시지 드롭: %s", normalized_type)
            return
        self._ensure_control_message_state()
        with self._control_message_lock:
            self._coalesced_control_messages[control_key] = item

    def _requeue_message_item(self, item: object) -> None:
        try:
            self.message_queue.put_nowait(item)
            return
        except queue.Full:
            pass

        if isinstance(item, WorkerQueueMessage):
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
            control_key = self._build_control_message_key(str(msg_type), data)
            if control_key is not None:
                self._ensure_control_message_state()
                with self._control_message_lock:
                    self._coalesced_control_messages[control_key] = (str(msg_type), data)
                return

        self._stash_overflow_passthrough_item(item)

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
    ) -> int:
        processed = 0
        drain_handler = handler or self._handle_message
        for raw_item in self._pop_overflow_passthrough_items(max_items=max_items):
            decoded = self._unwrap_message_item(raw_item)
            if decoded is None:
                continue
            msg_type, data = decoded
            drain_handler(msg_type, data)
            processed += 1
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

    def _clear_message_queue(self) -> None:
        """메시지 큐 비우기 (중지/재시작 안정성용)"""
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
        with self._control_message_lock:
            self._coalesced_control_messages.clear()
        self._ensure_overflow_passthrough_state()
        with self._overflow_passthrough_lock:
            self._overflow_passthrough_messages.clear()
