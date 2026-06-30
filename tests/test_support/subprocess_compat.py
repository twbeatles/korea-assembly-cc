from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path
from typing import Any


def subprocess_spawn_supported() -> bool:
    """현재 환경에서 자식 프로세스 생성이 가능한지 확인한다."""
    if os.environ.get("FORCE_IN_PROCESS_SMOKE") == "1":
        return False
    try:
        proc = subprocess.run(
            [sys.executable, "-c", "pass"],
            capture_output=True,
            timeout=15,
            check=False,
        )
        return proc.returncode == 0
    except OSError:
        return False


def load_entrypoint_module(entrypoint_name: str = "국회의사중계 자막.py"):
    module_path = Path(entrypoint_name).resolve()
    spec = importlib.util.spec_from_file_location(
        "assembly_subtitle_entrypoint_for_test",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"entrypoint module load failed: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CONFIG_PATH_FIELDS = (
    "STORAGE_DIR",
    "STORAGE_MODE",
    "SETTINGS_INI_PATH",
    "LOG_DIR",
    "SESSION_DIR",
    "REALTIME_DIR",
    "BACKUP_DIR",
    "RUNTIME_SESSION_DIR",
    "PRESET_FILE",
    "URL_HISTORY_FILE",
    "RECOVERY_STATE_FILE",
    "DATABASE_PATH",
)


def _snapshot_config_paths() -> dict[str, str]:
    from core.config import Config

    return {field: str(getattr(Config, field)) for field in _CONFIG_PATH_FIELDS}


def _restore_config_paths(snapshot: dict[str, str]) -> None:
    from core.config import Config

    for field, value in snapshot.items():
        setattr(Config, field, value)


def run_entrypoint_main(argv: list[str], *, entrypoint_name: str = "국회의사중계 자막.py") -> tuple[int, str]:
    """subprocess 없이 엔트리포인트 main()을 실행하고 stdout JSON 한 줄을 반환한다."""
    module = load_entrypoint_module(entrypoint_name)
    config_snapshot = _snapshot_config_paths()
    buffer = StringIO()
    original_stdout = sys.stdout
    try:
        sys.stdout = buffer
        exit_code = int(module.main(argv))
    finally:
        sys.stdout = original_stdout
        _restore_config_paths(config_snapshot)
    return exit_code, buffer.getvalue().strip()


def run_pyright_workspace_check(project_root: Path) -> tuple[int, dict[str, Any]]:
    """pyright --outputjson 결과를 반환한다. subprocess 불가 시 in-process CLI로 fallback."""
    if subprocess_spawn_supported():
        return _run_pyright_subprocess(project_root)
    return _run_pyright_in_process(project_root)


def _run_pyright_subprocess(project_root: Path) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson"],
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    summary: dict[str, Any] = {}
    if proc.stdout:
        summary = json.loads(proc.stdout).get("summary", {})
    return proc.returncode, summary


def _run_pyright_in_process(project_root: Path) -> tuple[int, dict[str, Any]]:
    from pyright.cli import main as pyright_main

    original_argv = list(sys.argv)
    original_stdout = sys.stdout
    original_cwd = Path.cwd()
    buffer = StringIO()
    try:
        os.chdir(project_root)
        sys.argv = ["pyright", "--outputjson"]
        sys.stdout = buffer
        exit_code = int(pyright_main(["--outputjson"]))
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout
        os.chdir(original_cwd)

    output = buffer.getvalue().strip()
    summary: dict[str, Any] = {}
    if output:
        summary = json.loads(output).get("summary", {})
    return exit_code, summary