from __future__ import annotations

import argparse
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="국회의사중계 자막 릴리스 검증")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="네트워크가 필요한 live 검증을 건너뜁니다.",
    )
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="live contract smoke와 live-list drift report를 건너뜁니다.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="PyInstaller build와 frozen smoke/preflight를 건너뜁니다.",
    )
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="live-list xcode drift가 있으면 실패합니다.",
    )
    parser.add_argument(
        "--fail-on-name-drift",
        action="store_true",
        help="live-list 명칭 drift가 있으면 실패합니다.",
    )
    parser.add_argument(
        "--instantiate-window",
        action="store_true",
        help="source/frozen smoke에서 MainWindow() 생성까지 검증합니다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    python = sys.executable
    smoke_root = REPO_ROOT / ".pytest_tmp"
    smoke_root.mkdir(exist_ok=True)

    _run("pytest", [python, "-m", "pytest", "-q"])
    _run("pyright", [python, "-m", "pyright", "--outputjson"])
    source_smoke_args = [
        python,
        "국회의사중계 자막.py",
        "--smoke",
        "--smoke-storage-dir",
        str(smoke_root / "release-smoke-storage"),
    ]
    if args.instantiate_window:
        source_smoke_args.append("--smoke-instantiate-window")
    _run(
        "source smoke",
        source_smoke_args,
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

    skip_live = bool(args.offline or args.skip_live)
    if not skip_live:
        live_env = os.environ.copy()
        live_env["RUN_LIVE_SMOKE"] = "1"
        _run(
            "live contract smoke",
            [python, "-m", "pytest", r"tests\test_live_contract_smoke.py", "-q"],
            env=live_env,
        )
        drift_args = [python, "scripts/check_live_list_drift.py"]
        if args.fail_on_drift:
            drift_args.append("--fail-on-drift")
        if args.fail_on_name_drift:
            drift_args.append("--fail-on-name-drift")
        _run("live list drift report", drift_args)

    if args.skip_build:
        print("\nRelease verification completed.")
        return 0

    _run(
        "PyInstaller clean build",
        [python, "-m", "PyInstaller", "--clean", "subtitle_extractor.spec"],
    )

    exe_path = REPO_ROOT / "dist" / f"국회의사중계자막추출기 v{Config.VERSION}.exe"
    if not exe_path.exists():
        raise FileNotFoundError(f"frozen executable not found: {exe_path}")

    frozen_smoke_args = [
        str(exe_path),
        "--smoke",
        "--smoke-storage-dir",
        str(smoke_root / "release-frozen-smoke-storage"),
    ]
    if args.instantiate_window:
        frozen_smoke_args.append("--smoke-instantiate-window")
    _run("frozen smoke", frozen_smoke_args)

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
