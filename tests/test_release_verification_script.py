from __future__ import annotations

from pathlib import Path

import scripts.run_release_verification as release_mod


def test_release_verification_offline_skip_build_keeps_source_checks(
    tmp_path, monkeypatch
):
    calls: list[tuple[str, list[str], dict[str, str] | None]] = []

    monkeypatch.setattr(release_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        release_mod,
        "_run",
        lambda label, args, env=None: calls.append((label, args, env)),
    )

    assert (
        release_mod.main(["--offline", "--skip-build", "--instantiate-window"])
        == 0
    )

    labels = [label for label, _args, _env in calls]
    assert labels == ["pytest", "pyright", "source smoke", "source storage preflight"]
    source_smoke_args = calls[2][1]
    assert "--smoke-instantiate-window" in source_smoke_args
    assert not any(label == "live contract smoke" for label in labels)
    assert not any(label == "PyInstaller clean build" for label in labels)
    assert (tmp_path / ".pytest_tmp").exists()


def test_release_verification_passes_live_drift_strict_flags(tmp_path, monkeypatch):
    calls: list[tuple[str, list[str], dict[str, str] | None]] = []

    monkeypatch.setattr(release_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        release_mod,
        "_run",
        lambda label, args, env=None: calls.append((label, args, env)),
    )

    assert (
        release_mod.main(
            ["--skip-build", "--fail-on-drift", "--fail-on-name-drift"]
        )
        == 0
    )

    labels = [label for label, _args, _env in calls]
    assert "live contract smoke" in labels
    drift_call = next(call for call in calls if call[0] == "live list drift report")
    assert drift_call[1][-2:] == ["--fail-on-drift", "--fail-on-name-drift"]
    live_call = next(call for call in calls if call[0] == "live contract smoke")
    assert live_call[2] is not None
    assert live_call[2]["RUN_LIVE_SMOKE"] == "1"


def test_release_verification_skip_live_still_runs_build_and_frozen_smoke(
    tmp_path, monkeypatch
):
    calls: list[tuple[str, list[str], dict[str, str] | None]] = []
    exe_dir = tmp_path / "dist"
    exe_dir.mkdir()
    exe_path = exe_dir / f"국회의사중계자막추출기 v{release_mod.Config.VERSION}.exe"
    exe_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(release_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        release_mod,
        "_run",
        lambda label, args, env=None: calls.append((label, args, env)),
    )

    assert release_mod.main(["--skip-live", "--instantiate-window"]) == 0

    labels = [label for label, _args, _env in calls]
    assert "live contract smoke" not in labels
    assert "live list drift report" not in labels
    assert "PyInstaller clean build" in labels
    frozen_smoke_args = next(call[1] for call in calls if call[0] == "frozen smoke")
    assert Path(frozen_smoke_args[0]) == exe_path
    assert "--smoke-instantiate-window" in frozen_smoke_args
