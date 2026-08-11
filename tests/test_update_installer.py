from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core.update_installer import (
    UpdateApplyError,
    apply_staged_update,
    prepare_staged_update,
    resolve_update_staging_root,
    stream_update_artifact,
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
