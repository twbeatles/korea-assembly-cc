from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from uuid import uuid4

from core.config import Config
from core.file_io import atomic_write_json
from core.update_manifest import ReleaseManifest


class UpdateApplyError(RuntimeError):
    pass


def update_result_path(staging_root: str | Path) -> Path:
    return (Path(staging_root).resolve() / "last-update-result.json").resolve()


def write_update_result(path: str | Path, payload: dict[str, object]) -> None:
    data = dict(payload)
    data["status"] = str(data.get("status", "failed") or "failed")
    atomic_write_json(Path(path).resolve(), data, ensure_ascii=False)


def consume_update_result(path: str | Path) -> dict[str, object] | None:
    result_path = Path(path).resolve()
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        try:
            result_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    if not isinstance(data, dict) or str(data.get("status", "")) not in {
        "applied",
        "rolled_back",
        "failed",
    }:
        try:
            result_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    try:
        result_path.unlink(missing_ok=True)
    except OSError:
        pass
    return data


def resolve_update_staging_root(
    *,
    storage_root: str | Path,
    install_dir: str | Path,
    storage_mode: str,
) -> Path:
    if str(storage_mode or "").strip().lower() == "portable":
        return (Path(install_dir) / ".updates").resolve()
    return (Path(storage_root) / "updates").resolve()


def prepare_staged_update(
    manifest: ReleaseManifest,
    *,
    chunks: Iterable[bytes],
    staging_root: str | Path,
    approve: Callable[[ReleaseManifest, Path], bool],
) -> Path | None:
    root = Path(staging_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    staged = root / f"update-{manifest.version}-{uuid4().hex}.exe"
    digest = hashlib.sha256()
    total = 0
    try:
        with open(staged, "xb") as handle:
            for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise TypeError("Update chunk must be bytes")
                total += len(chunk)
                if total > manifest.artifact_size or total > int(
                    Config.UPDATE_ARTIFACT_MAX_BYTES
                ):
                    raise ValueError("Update artifact size mismatch")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if total != manifest.artifact_size:
            raise ValueError("Update artifact size mismatch")
        if digest.hexdigest().lower() != manifest.artifact_sha256.lower():
            raise ValueError("Update artifact hash mismatch")
        if not approve(manifest, staged):
            staged.unlink(missing_ok=True)
            return None
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def stream_update_artifact(manifest: ReleaseManifest) -> Iterable[bytes]:
    from urllib.request import Request, urlopen

    request = Request(
        manifest.artifact_url,
        headers={"User-Agent": "KoreaAssemblyCC-Updater"},
    )
    with urlopen(
        request,
        timeout=float(Config.UPDATE_REQUEST_TIMEOUT_SECONDS),
    ) as response:
        from urllib.parse import urlsplit

        final_url = urlsplit(response.geturl())
        if final_url.scheme.lower() != "https" or not final_url.hostname:
            raise ValueError("Update artifact redirect must remain HTTPS")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                return
            yield chunk


def _validate_apply_paths(target: Path, staged: Path, backup: Path) -> None:
    paths = [target.resolve(), staged.resolve(), backup.resolve()]
    if len(set(paths)) != 3:
        raise ValueError("Update target, staged, and backup paths must be distinct")
    if target.suffix.lower() != ".exe" or staged.suffix.lower() != ".exe":
        raise ValueError("Update target and staged artifact must be .exe files")
    if backup.parent != target.parent:
        raise ValueError("Update backup must stay in the target install directory")
    if not target.is_file() or not staged.is_file():
        raise FileNotFoundError("Update target or staged artifact is missing")
    if backup.exists():
        raise FileExistsError(f"Update backup already exists: {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)


def cleanup_update_backups(target: str | Path, *, keep_count: int | None = None) -> None:
    target_path = Path(target).resolve()
    keep = max(0, int(Config.UPDATE_BACKUP_KEEP_COUNT if keep_count is None else keep_count))
    candidates: list[tuple[float, Path]] = []
    for backup in target_path.parent.glob(f"{target_path.name}.v*.bak"):
        try:
            candidates.append((backup.stat().st_mtime, backup))
        except OSError:
            continue
    backups = [item for _mtime, item in sorted(candidates, reverse=True)]
    for backup in backups[keep:]:
        try:
            backup.unlink()
        except OSError:
            continue


def apply_staged_update(
    *,
    target: str | Path,
    staged: str | Path,
    backup: str | Path,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
    smoke_runner: Callable[[Path], bool] | None = None,
) -> None:
    target_path = Path(target).resolve()
    staged_path = Path(staged).resolve()
    backup_path = Path(backup).resolve()
    _validate_apply_paths(target_path, staged_path, backup_path)
    if expected_size is not None and staged_path.stat().st_size != int(expected_size):
        raise ValueError("Update artifact size mismatch before replacement")
    if expected_sha256 is not None:
        digest = hashlib.sha256()
        with open(staged_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != str(expected_sha256).strip().lower():
            raise ValueError("Update artifact hash mismatch before replacement")
    shutil.copy2(target_path, backup_path)
    try:
        os.replace(staged_path, target_path)
        if smoke_runner is None:
            completed = subprocess.run(
                [str(target_path), "--smoke"],
                timeout=60,
                check=False,
                capture_output=True,
            )
            smoke_ok = completed.returncode == 0
        else:
            smoke_ok = bool(smoke_runner(target_path))
        if not smoke_ok:
            raise RuntimeError("updated executable smoke check failed")
        try:
            cleanup_update_backups(target_path)
        except Exception:
            # Backup retention must not turn a successful replacement into a rollback.
            pass
    except Exception as exc:
        try:
            if backup_path.is_file():
                os.replace(backup_path, target_path)
        except Exception as rollback_exc:
            raise UpdateApplyError(
                f"Update failed and rollback also failed: {rollback_exc}"
            ) from exc
        raise UpdateApplyError("Update failed and was rolled back") from exc


def launch_update_helper(
    *,
    target: str | Path,
    staged: str | Path,
    backup: str | Path,
    parent_pid: int,
    expected_sha256: str,
    expected_size: int,
    result_file: str | Path,
) -> subprocess.Popen[bytes]:
    staged_path = Path(staged).resolve()
    helper_path = staged_path.parent / f"update-helper-{uuid4().hex}.exe"
    shutil.copy2(Path(sys.executable).resolve(), helper_path)
    return subprocess.Popen(
        [
            str(helper_path),
            "--apply-update",
            "--update-target",
            str(Path(target).resolve()),
            "--update-staged",
            str(staged_path),
            "--update-backup",
            str(Path(backup).resolve()),
            "--update-parent-pid",
            str(int(parent_pid)),
            "--update-expected-sha256",
            str(expected_sha256),
            "--update-expected-size",
            str(int(expected_size)),
            "--update-result-file",
            str(Path(result_file).resolve()),
        ],
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
