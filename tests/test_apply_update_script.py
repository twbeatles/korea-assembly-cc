from __future__ import annotations

import pytest

from core.update_installer import UpdateApplyError
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


def _success_args(tmp_path) -> list[str]:
    return [
        "--target",
        str(tmp_path / "app.exe"),
        "--staged",
        str(tmp_path / "staged.exe"),
        "--backup",
        str(tmp_path / "app.exe.bak"),
        "--parent-pid",
        "4242",
        "--expected-sha256",
        "a" * 64,
        "--expected-size",
        "3",
        "--result-file",
        str(tmp_path / "result.json"),
    ]


def test_apply_update_success_relaunches_updated_executable(
    tmp_path, monkeypatch
) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setattr(
        "scripts.apply_update._wait_for_parent", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "scripts.apply_update.apply_staged_update",
        lambda **kwargs: calls.setdefault("applied", kwargs),
    )
    monkeypatch.setattr(
        "scripts.apply_update.relaunch_updated_executable",
        lambda target: calls.setdefault("relaunched", str(target)),
    )

    assert main(_success_args(tmp_path)) == 0

    assert "applied" in calls
    assert calls["relaunched"] == str(tmp_path / "app.exe")
    result_text = (tmp_path / "result.json").read_text(encoding="utf-8")
    assert '"status": "applied"' in result_text


def test_apply_update_no_relaunch_skips_restart(tmp_path, monkeypatch) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setattr(
        "scripts.apply_update._wait_for_parent", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "scripts.apply_update.apply_staged_update",
        lambda **kwargs: calls.setdefault("applied", kwargs),
    )
    monkeypatch.setattr(
        "scripts.apply_update.relaunch_updated_executable",
        lambda target: calls.setdefault("relaunched", str(target)),
    )

    assert main(_success_args(tmp_path) + ["--no-relaunch"]) == 0

    assert "applied" in calls
    assert "relaunched" not in calls


def test_apply_update_rollback_maps_to_rolled_back_status(
    tmp_path, monkeypatch
) -> None:
    def fail(**kwargs: object) -> None:
        raise UpdateApplyError("Update failed and was rolled back")

    monkeypatch.setattr(
        "scripts.apply_update._wait_for_parent", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("scripts.apply_update.apply_staged_update", fail)

    assert main(_success_args(tmp_path) + ["--no-relaunch"]) == 1

    result_text = (tmp_path / "result.json").read_text(encoding="utf-8")
    assert '"status": "rolled_back"' in result_text
