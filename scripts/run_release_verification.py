from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import Config


def _run(label: str, args: list[str], *, env: dict[str, str] | None = None) -> None:
    print(f"\n==> {label}")
    subprocess.run(args, cwd=REPO_ROOT, env=env, check=True)


def main() -> int:
    python = sys.executable
    smoke_root = REPO_ROOT / ".pytest_tmp"
    smoke_root.mkdir(exist_ok=True)

    _run("pytest", [python, "-m", "pytest", "-q"])
    _run("pyright", [python, "-m", "pyright", "--outputjson"])
    _run(
        "source smoke",
        [
            python,
            "국회의사중계 자막.py",
            "--smoke",
            "--smoke-storage-dir",
            str(smoke_root / "release-smoke-storage"),
        ],
    )
    _run(
        "source storage preflight",
        [
            python,
            "국회의사중계 자막.py",
            "--smoke-storage-preflight",
            "--smoke-storage-dir",
            str(smoke_root / "release-storage-preflight"),
        ],
    )

    live_env = os.environ.copy()
    live_env["RUN_LIVE_SMOKE"] = "1"
    _run(
        "live contract smoke",
        [python, "-m", "pytest", r"tests\test_live_contract_smoke.py", "-q"],
        env=live_env,
    )
    _run("live list drift report", [python, "scripts/check_live_list_drift.py"])
    _run(
        "PyInstaller clean build",
        [python, "-m", "PyInstaller", "--clean", "subtitle_extractor.spec"],
    )

    exe_path = REPO_ROOT / "dist" / f"국회의사중계자막추출기 v{Config.VERSION}.exe"
    if not exe_path.exists():
        raise FileNotFoundError(f"frozen executable not found: {exe_path}")

    _run(
        "frozen smoke",
        [
            str(exe_path),
            "--smoke",
            "--smoke-storage-dir",
            str(smoke_root / "release-frozen-smoke-storage"),
        ],
    )

    portable_flag = exe_path.parent / "portable.flag"
    created_portable_flag = not portable_flag.exists()
    if created_portable_flag:
        portable_flag.write_text("", encoding="utf-8")
    try:
        _run("frozen portable storage preflight", [str(exe_path), "--smoke-storage-preflight"])
    finally:
        if created_portable_flag:
            portable_flag.unlink(missing_ok=True)

    print("\nRelease verification completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
