from __future__ import annotations

import pytest

from scripts.apply_update import _wait_for_parent


def test_wait_for_parent_rejects_non_positive_pid() -> None:
    with pytest.raises(ValueError, match="positive"):
        _wait_for_parent(0)
