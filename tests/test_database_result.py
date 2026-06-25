from __future__ import annotations

import pytest

from core.database_result import DatabaseOperationResult, unwrap_database_result


def test_database_operation_result_success_and_failure():
    result = DatabaseOperationResult.success({"count": 3})
    assert result.ok is True
    assert result.value == {"count": 3}
    assert unwrap_database_result(result) == {"count": 3}

    failed = DatabaseOperationResult.failure("fts unavailable", error_type="degraded")
    assert failed.ok is False
    assert failed.error_type == "degraded"
    with pytest.raises(RuntimeError, match="fts unavailable"):
        unwrap_database_result(failed)


def test_unwrap_database_result_passthrough():
    assert unwrap_database_result(["plain"]) == ["plain"]