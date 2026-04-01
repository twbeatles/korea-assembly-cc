# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import queue
from typing import Any, Callable

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


PipelineQueueBase = object


class MainWindowPipelineQueueMixin(PipelineQueueBase):
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
        if lock is None:
            return
        with lock:
            getattr(self, "_coalesced_worker_messages", {}).clear()
