from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from core.process_wait import wait_for_process_exit
from core.update_installer import (
    apply_staged_update,
    relaunch_updated_executable,
    write_update_result,
)


def _wait_for_parent(
    parent_pid: int,
    timeout: float = 120.0,
    wait_impl: Callable[[int, float], bool] | None = None,
) -> None:
    wait_for_process_exit(parent_pid, timeout=timeout, wait_impl=wait_impl)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply staged application update")
    parser.add_argument("--target", required=True)
    parser.add_argument("--staged", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--parent-pid", required=True, type=int)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-size", required=True, type=int)
    parser.add_argument("--result-file", required=True)
    parser.add_argument(
        "--no-relaunch",
        action="store_true",
        help="Do not restart the updated executable after a successful apply.",
    )
    args = parser.parse_args(argv)
    base_result = {
        "target": str(Path(args.target).resolve()),
        "backup": str(Path(args.backup).resolve()),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _wait_for_parent(args.parent_pid)
        apply_staged_update(
            target=Path(args.target),
            staged=Path(args.staged),
            backup=Path(args.backup),
            expected_sha256=args.expected_sha256,
            expected_size=args.expected_size,
        )
    except Exception as exc:
        status = "rolled_back" if "rolled back" in str(exc).lower() else "failed"
        write_update_result(
            args.result_file,
            {**base_result, "status": status, "error": str(exc)},
        )
        return 1
    write_update_result(args.result_file, {**base_result, "status": "applied"})
    if not args.no_relaunch:
        try:
            relaunch_updated_executable(args.target)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
