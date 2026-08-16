from __future__ import annotations

import pytest

from scripts.apply_update import _wait_for_parent, main


def test_wait_for_parent_rejects_non_positive_pid() -> None:
    with pytest.raises(ValueError, match="positive"):
        _wait_for_parent(0)


def test_apply_update_failure_writes_result_file(tmp_path) -> None:
    result_file = tmp_path / "result.json"
    exit_code = main(
        [
            "--target",
            str(tmp_path / "missing.exe"),
            "--staged",
            str(tmp_path / "staged.exe"),
            "--backup",
            str(tmp_path / "backup.bak"),
            "--parent-pid",
            "0",
            "--expected-sha256",
            "0" * 64,
            "--expected-size",
            "1",
            "--result-file",
            str(result_file),
        ]
    )

    assert exit_code == 1
    assert '"status": "failed"' in result_file.read_text(encoding="utf-8")
