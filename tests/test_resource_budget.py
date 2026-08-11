from __future__ import annotations

import pytest

from core.resource_budget import (
    ResourceBudget,
    ResourceBudgetLimits,
    ResourceLimitExceeded,
    check_file_size,
)


def _limits() -> ResourceBudgetLimits:
    return ResourceBudgetLimits(
        per_file_bytes=8,
        total_bytes=12,
        max_entries=3,
        max_segments=2,
    )


def test_check_file_size_rejects_oversized_file(tmp_path) -> None:
    path = tmp_path / "large.json"
    path.write_bytes(b"123456789")

    with pytest.raises(ResourceLimitExceeded, match="segment") as exc_info:
        check_file_size(path, per_file_limit=8, label="segment")

    assert exc_info.value.resource == "file_bytes"


def test_budget_enforces_cumulative_bytes_entries_and_segments() -> None:
    budget = ResourceBudget(_limits())
    budget.consume_file(7, label="manifest")
    budget.consume_file(5, label="segment")
    budget.consume_entries(3)
    budget.consume_segment()
    budget.consume_segment()

    assert budget.summary() == {
        "total_bytes": 12,
        "entries": 3,
        "segments": 2,
    }
    with pytest.raises(ResourceLimitExceeded) as bytes_error:
        budget.consume_file(1, label="tail")
    assert bytes_error.value.resource == "total_bytes"
    with pytest.raises(ResourceLimitExceeded) as entries_error:
        budget.consume_entries(1)
    assert entries_error.value.resource == "entries"
    with pytest.raises(ResourceLimitExceeded) as segments_error:
        budget.consume_segment()
    assert segments_error.value.resource == "segments"


def test_budget_rejects_per_file_limit_before_mutating_total() -> None:
    budget = ResourceBudget(_limits())

    with pytest.raises(ResourceLimitExceeded) as exc_info:
        budget.consume_file(9, label="segment")

    assert exc_info.value.resource == "file_bytes"
    assert budget.summary()["total_bytes"] == 0


def test_budget_cancel_check_raises_typed_error() -> None:
    budget = ResourceBudget(_limits(), cancel_check=lambda: True)

    with pytest.raises(ResourceLimitExceeded) as exc_info:
        budget.check_cancelled()

    assert exc_info.value.resource == "cancelled"
