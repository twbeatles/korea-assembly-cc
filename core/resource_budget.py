from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class ResourceLimitExceeded(ValueError):
    def __init__(
        self,
        resource: str,
        *,
        limit: int | None,
        observed: int | None,
        label: str = "resource",
    ) -> None:
        self.resource = resource
        self.limit = limit
        self.observed = observed
        self.label = label
        if resource == "cancelled":
            message = f"{label} 작업이 취소되었습니다."
        else:
            message = (
                f"{label} 리소스 제한 초과: {resource} "
                f"(허용 {limit}, 확인 {observed})"
            )
        super().__init__(message)


@dataclass(frozen=True)
class ResourceBudgetLimits:
    per_file_bytes: int
    total_bytes: int
    max_entries: int
    max_segments: int


def check_file_size(
    path: str | Path,
    *,
    per_file_limit: int,
    label: str,
) -> int:
    size = Path(path).stat().st_size
    if per_file_limit >= 0 and size > per_file_limit:
        raise ResourceLimitExceeded(
            "file_bytes",
            limit=per_file_limit,
            observed=size,
            label=label,
        )
    return size


class ResourceBudget:
    def __init__(
        self,
        limits: ResourceBudgetLimits,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.limits = limits
        self._cancel_check = cancel_check
        self._lock = threading.Lock()
        self._total_bytes = 0
        self._entries = 0
        self._segments = 0

    def check_cancelled(self) -> None:
        if self._cancel_check is not None and self._cancel_check():
            raise ResourceLimitExceeded(
                "cancelled", limit=None, observed=None, label="session load"
            )

    def consume_file(self, size: int, *, label: str) -> None:
        safe_size = max(0, int(size))
        self.check_cancelled()
        with self._lock:
            if safe_size > self.limits.per_file_bytes:
                raise ResourceLimitExceeded(
                    "file_bytes",
                    limit=self.limits.per_file_bytes,
                    observed=safe_size,
                    label=label,
                )
            next_total = self._total_bytes + safe_size
            if next_total > self.limits.total_bytes:
                raise ResourceLimitExceeded(
                    "total_bytes",
                    limit=self.limits.total_bytes,
                    observed=next_total,
                    label=label,
                )
            self._total_bytes = next_total

    def consume_entries(self, count: int) -> None:
        safe_count = max(0, int(count))
        self.check_cancelled()
        with self._lock:
            next_count = self._entries + safe_count
            if next_count > self.limits.max_entries:
                raise ResourceLimitExceeded(
                    "entries",
                    limit=self.limits.max_entries,
                    observed=next_count,
                    label="session entries",
                )
            self._entries = next_count

    def consume_segment(self, count: int = 1) -> None:
        safe_count = max(0, int(count))
        self.check_cancelled()
        with self._lock:
            next_count = self._segments + safe_count
            if next_count > self.limits.max_segments:
                raise ResourceLimitExceeded(
                    "segments",
                    limit=self.limits.max_segments,
                    observed=next_count,
                    label="runtime segments",
                )
            self._segments = next_count

    def summary(self) -> dict[str, int]:
        with self._lock:
            return {
                "total_bytes": self._total_bytes,
                "entries": self._entries,
                "segments": self._segments,
            }
