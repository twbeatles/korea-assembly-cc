from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from uuid import uuid4

from core.config import Config
from core.file_io import atomic_write_json
from core.update_manifest import ReleaseManifest


class UpdateApplyError(RuntimeError):
    pass


_BOOTLOADER_ENV_EXACT = frozenset({"_MEIPASS", "_MEIPASS2"})
_BOOTLOADER_ENV_PREFIXES = ("_PYI_",)
_LIBRARY_PATH_KEYS = (
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
)


def sanitized_frozen_child_env(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a child environment without PyInstaller onefile hand-off state.

    A frozen child that inherits ``_MEIPASS2``/``_PYI_*`` reuses the parent's
    extraction directory instead of extracting its own bundle. The parent
    deletes that directory on exit, which breaks the child mid-run. Library
    search paths the bootloader overrode are restored from their ``*_ORIG``
    backups, or dropped when there was no original.
    """
    env = dict(os.environ if base is None else base)
    for key in [
        key
        for key in env
        if key in _BOOTLOADER_ENV_EXACT
        or key.startswith(_BOOTLOADER_ENV_PREFIXES)
    ]:
        env.pop(key, None)
    for key in _LIBRARY_PATH_KEYS:
        original = env.get(f"{key}_ORIG")
        if original is not None:
            env[key] = original
        else:
            env.pop(key, None)
    return env


def relaunch_updated_executable(target: str | Path) -> subprocess.Popen[bytes]:
    """Restart the freshly installed executable with a clean environment.

    Uses a sanitized environment so the new process extracts its own
    PyInstaller bundle instead of reusing the updater's directory.
    """
    return subprocess.Popen(
        [str(Path(target).resolve())],
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=sanitized_frozen_child_env(),
    )


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
    backup.parent.mkdir(parents=True, exist_ok=True)


def _is_cross_device_error(exc: BaseException) -> bool:
    if not isinstance(exc, OSError):
        return False
    if getattr(exc, "errno", None) == errno.EXDEV:
        return True
    return getattr(exc, "winerror", None) == 17


def _rename_with_cross_volume_retry(src: Path, dst: Path) -> None:
    """Rename, retrying once on a cross-device error.

    Both swap moves stay inside the install directory, so a cross-device
    error cannot happen on a real filesystem. The single retry preserves the
    cross-volume replacement contract (the staged copy is already on the
    target volume) when the error is transient.
    """
    try:
        os.replace(src, dst)
    except OSError as exc:
        if not _is_cross_device_error(exc):
            raise
        os.replace(src, dst)


def _recover_interrupted_replacement(target: Path, backup: Path) -> bool:
    """Restore the backup when a previous run died between the two moves.

    The rename swap moves the installed executable to the backup name first
    and the staged file to the target path second. A crash in between leaves
    the install directory without a target. The next run restores the backup
    so the retry starts from the installed executable again.
    """
    try:
        if not target.exists() and backup.is_file():
            os.replace(backup, target)
            return True
    except OSError:
        return False
    return False


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _stage_on_target_volume(
    staged: Path,
    target: Path,
    *,
    expected_sha256: str | None,
    expected_size: int | None,
) -> Path:
    local = (target.parent / f".update-apply-{uuid4().hex}.exe").resolve()
    try:
        shutil.copy2(staged, local)
        with open(local, "rb+") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        if expected_size is not None and local.stat().st_size != int(expected_size):
            raise ValueError("Update artifact size mismatch after copy")
        if (
            expected_sha256 is not None
            and _hash_file(local) != str(expected_sha256).strip().lower()
        ):
            raise ValueError("Update artifact hash mismatch after copy")
        return local
    except Exception:
        local.unlink(missing_ok=True)
        raise


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
    _recover_interrupted_replacement(target_path, backup_path)
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
    # Stage onto the install volume first so the final move never crosses
    # devices. The running executable is never overwritten or deleted: it is
    # renamed to the backup name (allowed on Windows even while the image is
    # mapped), which also overwrites a stale backup from an earlier attempt.
    # The staged file then takes the now-free target path.
    local = _stage_on_target_volume(
        staged_path,
        target_path,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
    )
    try:
        _rename_with_cross_volume_retry(target_path, backup_path)
    except OSError as exc:
        local.unlink(missing_ok=True)
        raise UpdateApplyError(
            "Update failed before replacement and the installed "
            f"executable was left untouched: {exc}"
        ) from exc
    try:
        _rename_with_cross_volume_retry(local, target_path)
    except OSError as exc:
        local.unlink(missing_ok=True)
        try:
            if backup_path.is_file() and not target_path.exists():
                os.replace(backup_path, target_path)
        except OSError as rollback_exc:
            raise UpdateApplyError(
                f"Update failed and rollback also failed: {rollback_exc}"
            ) from exc
        raise UpdateApplyError("Update failed and was rolled back") from exc
    staged_path.unlink(missing_ok=True)
    try:
        if smoke_runner is None:
            completed = subprocess.run(
                [str(target_path), "--smoke"],
                timeout=60,
                check=False,
                capture_output=True,
                env=sanitized_frozen_child_env(),
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
    relaunch: bool = True,
) -> subprocess.Popen[bytes]:
    staged_path = Path(staged).resolve()
    helper_path = staged_path.parent / f"update-helper-{uuid4().hex}.exe"
    shutil.copy2(Path(sys.executable).resolve(), helper_path)
    args = [
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
    ]
    if not relaunch:
        args.append("--update-no-relaunch")
    return subprocess.Popen(
        args,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=sanitized_frozen_child_env(),
    )
