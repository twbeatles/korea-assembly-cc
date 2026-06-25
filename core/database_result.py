# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class DatabaseOperationResult(Generic[T]):
    """DB read/write 결과를 성공/실패와 값으로 명시적으로 전달한다."""

    ok: bool
    value: T | None = None
    error: str = ""
    error_type: str = ""

    @classmethod
    def success(cls, value: T) -> DatabaseOperationResult[T]:
        return cls(ok=True, value=value)

    @classmethod
    def failure(
        cls,
        error: str,
        *,
        error_type: str = "runtime",
    ) -> DatabaseOperationResult[T]:
        return cls(ok=False, error=str(error or ""), error_type=error_type)


def unwrap_database_result(result: Any) -> Any:
    if isinstance(result, DatabaseOperationResult):
        if not result.ok:
            raise RuntimeError(result.error or "DB operation failed")
        return result.value
    return result