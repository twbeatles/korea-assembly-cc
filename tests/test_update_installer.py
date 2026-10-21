from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from core.update_installer import (
    UpdateApplyError,
    apply_staged_update,
    launch_update_helper,
    relaunch_updated_executable,
    sanitized_frozen_child_env,
    consume_update_result,
    prepare_staged_update,
    resolve_update_staging_root,
    stream_update_artifact,
    update_result_path,
    write_update_result,
)
from core.update_manifest import ReleaseManifest
from datetime import datetime, timezone


def _manifest(payload: bytes) -> ReleaseManifest:
    return ReleaseManifest(
        version="99.0.0",
        artifact_url="https://updates.example.com/app.exe",
        artifact_sha256=hashlib.sha256(payload).hexdigest(),
        artifact_size=len(payload),
        expires_at=datetime.now(timezone.utc),
        signature="test",
    )


def test_user_cancel_removes_staged_artifact(tmp_path) -> None:
    payload = b"new executable"
    staged = prepare_staged_update(
        _manifest(payload),
        chunks=[payload],
        staging_root=tmp_path,
        approve=lambda _manifest, _path: False,
    )

    assert staged is None
    assert list(tmp_path.glob("*.exe")) == []


def test_hash_mismatch_rejects_and_removes_staged_artifact(tmp_path) -> None:
    payload = b"new executable"
    with pytest.raises(ValueError, match="hash"):
        prepare_staged_update(
            _manifest(payload),
            chunks=[b"x" * len(payload)],
            staging_root=tmp_path,
            approve=lambda _manifest, _path: True,
        )
    assert list(tmp_path.glob("*.exe")) == []


def test_successful_staged_replacement_keeps_backup(tmp_path) -> None:
    target = tmp_path / "app.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "app.exe.bak"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")

    apply_staged_update(
        target=target,
        staged=staged,
        backup=backup,
        smoke_runner=lambda path: path.read_bytes() == b"new",
    )

    assert target.read_bytes() == b"new"
    assert backup.read_bytes() == b"old"
    assert not staged.exists()


def test_smoke_failure_rolls_back_original(tmp_path) -> None:
    target = tmp_path / "app.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "app.exe.bak"
    target.write_bytes(b"old")
    staged.write_bytes(b"bad new")

    with pytest.raises(UpdateApplyError, match="rolled back"):
        apply_staged_update(
            target=target,
            staged=staged,
            backup=backup,
            smoke_runner=lambda _path: False,
        )

    assert target.read_bytes() == b"old"


def test_portable_staging_stays_under_install_directory(tmp_path) -> None:
    install_dir = tmp_path / "portable"
    storage_dir = tmp_path / "localappdata"

    root = resolve_update_staging_root(
        storage_root=storage_dir,
        install_dir=install_dir,
        storage_mode="portable",
    )

    assert root == (install_dir / ".updates").resolve()


def test_apply_rejects_backup_outside_install_directory(tmp_path) -> None:
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    target = install_dir / "app.exe"
    staged = tmp_path / "staged.exe"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")

    with pytest.raises(ValueError, match="backup"):
        apply_staged_update(
            target=target,
            staged=staged,
            backup=tmp_path / "elsewhere" / "app.bak",
            smoke_runner=lambda _path: True,
        )

    assert target.read_bytes() == b"old"
    assert staged.read_bytes() == b"new"


def test_apply_rejects_non_executable_staging_file(tmp_path) -> None:
    target = tmp_path / "app.exe"
    staged = tmp_path / "staged.bin"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")

    with pytest.raises(ValueError, match=".exe"):
        apply_staged_update(
            target=target,
            staged=staged,
            backup=tmp_path / "app.bak",
            smoke_runner=lambda _path: True,
        )


def test_artifact_download_rejects_redirect_to_http(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def geturl(self):
            return "http://updates.example.com/app.exe"

        def read(self, _size):
            return b""

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response())

    with pytest.raises(ValueError, match="HTTPS"):
        list(stream_update_artifact(_manifest(b"payload")))


def test_apply_rechecks_staged_hash_before_replacement(tmp_path) -> None:
    target = tmp_path / "app.exe"
    staged = tmp_path / "staged.exe"
    target.write_bytes(b"old")
    verified = b"verified artifact"
    staged.write_bytes(b"x" * len(verified))
    expected = hashlib.sha256(verified).hexdigest()

    with pytest.raises(ValueError, match="hash"):
        apply_staged_update(
            target=target,
            staged=staged,
            backup=tmp_path / "app.bak",
            expected_sha256=expected,
            expected_size=len(verified),
            smoke_runner=lambda _path: True,
        )

    assert target.read_bytes() == b"old"
    assert not (tmp_path / "app.bak").exists()


def test_update_result_is_consumed_once(tmp_path) -> None:
    path = update_result_path(tmp_path)
    write_update_result(path, {"status": "applied", "target": "app.exe"})

    assert consume_update_result(path) == {"status": "applied", "target": "app.exe"}
    assert consume_update_result(path) is None


def test_invalid_update_result_is_discarded(tmp_path) -> None:
    path = update_result_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")

    assert consume_update_result(path) is None
    assert not path.exists()


def test_successful_apply_keeps_only_requested_backups(tmp_path, monkeypatch) -> None:
    target = tmp_path / "app.exe"
    target.write_bytes(b"old")
    monkeypatch.setattr("core.update_installer.Config.UPDATE_BACKUP_KEEP_COUNT", 1)
    for version in ("1.0.0", "2.0.0"):
        staged = tmp_path / f"staged-{version}.exe"
        staged.write_bytes(version.encode())
        apply_staged_update(
            target=target,
            staged=staged,
            backup=tmp_path / f"app.exe.v{version}.bak",
            smoke_runner=lambda _path: True,
        )

    assert len(list(tmp_path.glob("app.exe.v*.bak"))) == 1


def test_stale_backup_is_overwritten_instead_of_rejected(tmp_path) -> None:
    target = tmp_path / "app.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "app.exe.bak"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    backup.write_bytes(b"stale backup from an earlier attempt")

    apply_staged_update(
        target=target,
        staged=staged,
        backup=backup,
        smoke_runner=lambda path: True,
    )

    assert target.read_bytes() == b"new"
    assert backup.read_bytes() == b"old"
    assert not staged.exists()


def test_replacement_never_overwrites_the_running_target(
    tmp_path, monkeypatch
) -> None:
    """Simulate Windows locking: overwriting the mapped exe fails (WinError 5).

    Renaming the running image aside and moving the staged file onto the now
    free target path must succeed without ever overwriting the locked file.
    """
    target = tmp_path / "app.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "app.exe.bak"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    backup.write_bytes(b"stale backup from an earlier attempt")
    moves: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def windows_replace(src: str | Path, dst: str | Path) -> None:
        moves.append((Path(src), Path(dst)))
        if Path(dst).name == target.name and Path(dst).exists():
            raise PermissionError(13, "Permission denied")
        real_replace(src, dst)

    monkeypatch.setattr("core.update_installer.os.replace", windows_replace)

    apply_staged_update(
        target=target,
        staged=staged,
        backup=backup,
        smoke_runner=lambda path: True,
    )

    assert target.read_bytes() == b"new"
    assert backup.read_bytes() == b"old"
    assert moves[0][0].name == target.name
    assert moves[0][1].name == backup.name
    assert moves[1][1].name == target.name


def test_first_move_failure_leaves_installed_executable(
    tmp_path, monkeypatch
) -> None:
    target = tmp_path / "app.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "app.exe.bak"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")

    def fail_first_move(src: str | Path, dst: str | Path) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("core.update_installer.os.replace", fail_first_move)

    with pytest.raises(UpdateApplyError, match="left untouched"):
        apply_staged_update(
            target=target,
            staged=staged,
            backup=backup,
            smoke_runner=lambda path: True,
        )

    assert target.read_bytes() == b"old"
    assert staged.read_bytes() == b"new"
    assert not backup.exists()
    assert list(tmp_path.glob(".update-apply-*.exe")) == []


def test_interrupted_replacement_recovers_backup_on_next_run(tmp_path) -> None:
    target = tmp_path / "app.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "app.exe.bak"
    backup.write_bytes(b"old")
    staged.write_bytes(b"new")

    apply_staged_update(
        target=target,
        staged=staged,
        backup=backup,
        smoke_runner=lambda path: True,
    )

    assert target.read_bytes() == b"new"
    assert backup.read_bytes() == b"old"
    assert not staged.exists()


def test_sanitized_frozen_child_env_drops_bootloader_state() -> None:
    env = sanitized_frozen_child_env(
        {
            "_MEIPASS": "C:\\_mei1",
            "_MEIPASS2": "C:\\_mei2",
            "_PYI_APPLICATION_HOME_DIR": "C:\\_mei2",
            "_PYI_ARCHIVE_FILE": "C:\\bundle.exe",
            "_PYI_PARENT_PROCESS_LEVEL": "1",
            "LD_LIBRARY_PATH": "/tmp/_mei/lib:/usr/lib",
            "LD_LIBRARY_PATH_ORIG": "/usr/lib",
            "DYLD_LIBRARY_PATH": "/tmp/_mei/lib",
            "PATH": "keep-me",
        }
    )

    assert "_MEIPASS" not in env
    assert "_MEIPASS2" not in env
    assert not any(key.startswith("_PYI_") for key in env)
    assert env["LD_LIBRARY_PATH"] == "/usr/lib"
    assert "DYLD_LIBRARY_PATH" not in env
    assert env["PATH"] == "keep-me"


def test_smoke_child_runs_without_bootloader_env(tmp_path, monkeypatch) -> None:
    target = tmp_path / "app.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "app.exe.bak"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0

    def fake_run(argv: list[str], **kwargs: object) -> Completed:
        captured["argv"] = argv
        captured["env"] = kwargs.get("env")
        return Completed()

    monkeypatch.setattr("core.update_installer.subprocess.run", fake_run)
    monkeypatch.setenv("_MEIPASS2", "C:\\stale\\_mei")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "C:\\stale\\_mei")

    apply_staged_update(target=target, staged=staged, backup=backup)

    assert captured["argv"] == [str(target.resolve()), "--smoke"]
    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert "_MEIPASS2" not in child_env
    assert not any(str(key).startswith("_PYI_") for key in child_env)


def test_helper_and_relaunch_use_clean_env(tmp_path, monkeypatch) -> None:
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    target = install_dir / "app.exe"
    staged = tmp_path / "staged.exe"
    backup = install_dir / "app.exe.bak"
    result_file = tmp_path / "result.json"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    launches: list[tuple[list[str], dict[str, object]]] = []

    def fake_copy2(src: str | Path, dst: str | Path) -> Path:
        helper = Path(dst)
        helper.write_bytes(b"helper")
        return helper

    class FakeProcess:
        pass

    def fake_popen(
        args: list[str], **kwargs: object
    ) -> FakeProcess:
        launches.append((list(args), dict(kwargs)))
        return FakeProcess()

    monkeypatch.setattr("core.update_installer.shutil.copy2", fake_copy2)
    monkeypatch.setattr("core.update_installer.subprocess.Popen", fake_popen)
    monkeypatch.setenv("_MEIPASS2", "C:\\stale\\_mei")
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "C:\\stale\\bundle.exe")

    helper = launch_update_helper(
        target=target,
        staged=staged,
        backup=backup,
        parent_pid=4242,
        expected_sha256="a" * 64,
        expected_size=3,
        result_file=result_file,
    )
    assert isinstance(helper, FakeProcess)
    helper_args, helper_kwargs = launches[-1]
    assert "--update-no-relaunch" not in helper_args
    helper_env = helper_kwargs.get("env")
    assert isinstance(helper_env, dict)
    assert "_MEIPASS2" not in helper_env
    assert not any(str(key).startswith("_PYI_") for key in helper_env)

    launch_update_helper(
        target=target,
        staged=staged,
        backup=backup,
        parent_pid=4242,
        expected_sha256="a" * 64,
        expected_size=3,
        result_file=result_file,
        relaunch=False,
    )
    assert "--update-no-relaunch" in launches[-1][0]

    relaunched = relaunch_updated_executable(target)
    assert isinstance(relaunched, FakeProcess)
    relaunch_args, relaunch_kwargs = launches[-1]
    assert relaunch_args == [str(target.resolve())]
    relaunch_env = relaunch_kwargs.get("env")
    assert isinstance(relaunch_env, dict)
    assert "_MEIPASS2" not in relaunch_env
    assert not any(str(key).startswith("_PYI_") for key in relaunch_env)
