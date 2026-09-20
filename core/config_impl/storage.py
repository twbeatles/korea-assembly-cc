# -*- coding: utf-8 -*-

"""저장소 경로 계산 (SRP: 설치/저장 디렉터리 결정만 담당)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class StorageResolution:
    install_dir: Path
    storage_dir: Path
    storage_mode: str
    portable_flag_path: Path
    settings_ini_path: Path | None


def _resolve_install_dir(
    *,
    frozen: bool | None = None,
    executable: str | None = None,
    argv0: str | None = None,
    module_file: str | None = None,
) -> Path:
    """리소스/설치 기준 디렉터리를 계산한다."""
    is_frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    if is_frozen:
        argv0_value = argv0
        if argv0_value is None and executable is None and sys.argv:
            argv0_value = sys.argv[0]
        launch_path = _resolve_existing_file_path(argv0_value)
        if launch_path is not None:
            return launch_path.parent

        executable_path = executable or getattr(sys, "executable", "")
        resolved_executable = _resolve_existing_file_path(executable_path)
        if resolved_executable is not None:
            return resolved_executable.parent
        return Path(executable_path).resolve().parent
    if module_file is not None:
        return Path(module_file).resolve().parent.parent
    # NOTE: split member lives in core/config_impl/ (repo root is 3 levels up).
    return Path(__file__).resolve().parent.parent.parent


def _resolve_existing_file_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    try:
        path = Path(path_value).resolve()
    except Exception:
        return None
    return path if path.is_file() else None


def _resolve_local_appdata_dir(
    *,
    localappdata: str | None = None,
    home: str | Path | None = None,
) -> Path:
    env_value = localappdata if localappdata is not None else os.environ.get("LOCALAPPDATA")
    if env_value:
        return Path(env_value).resolve() / "AssemblySubtitle" / "Extractor"
    home_path = Path.home() if home is None else Path(home)
    return home_path.resolve() / "AppData" / "Local" / "AssemblySubtitle" / "Extractor"


def resolve_storage_resolution(
    *,
    frozen: bool | None = None,
    executable: str | None = None,
    argv0: str | None = None,
    module_file: str | None = None,
    portable_flag_exists: bool | None = None,
    localappdata: str | None = None,
    home: str | Path | None = None,
) -> StorageResolution:
    """설치 경로와 저장 경로를 분리해 계산한다."""
    install_dir = _resolve_install_dir(
        frozen=frozen,
        executable=executable,
        argv0=argv0,
        module_file=module_file,
    )
    is_frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    portable_flag_path = install_dir / "portable.flag"
    flag_exists = (
        portable_flag_path.exists()
        if portable_flag_exists is None
        else bool(portable_flag_exists)
    )

    if not is_frozen:
        storage_dir = install_dir
        storage_mode = "development"
    elif flag_exists:
        storage_dir = install_dir
        storage_mode = "portable"
    else:
        storage_dir = _resolve_local_appdata_dir(
            localappdata=localappdata,
            home=home,
        )
        storage_mode = "localappdata"

    settings_ini_path = storage_dir / "settings.ini" if storage_mode == "portable" else None
    return StorageResolution(
        install_dir=install_dir,
        storage_dir=storage_dir.resolve(),
        storage_mode=storage_mode,
        portable_flag_path=portable_flag_path.resolve(),
        settings_ini_path=settings_ini_path.resolve() if settings_ini_path else None,
    )


def build_storage_preflight_targets(storage_dir: str | Path, settings_ini_path: str | Path | None = None) -> list[Path]:
    root = Path(storage_dir).resolve()
    targets = [
        root,
        root / "logs",
        root / "sessions",
        root / "realtime_output",
        root / "backups",
        root / "backups" / "runtime_sessions",
    ]
    if settings_ini_path:
        targets.append(Path(settings_ini_path).resolve().parent)
    return targets
