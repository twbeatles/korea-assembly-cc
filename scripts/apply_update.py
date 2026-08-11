from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from core.update_installer import apply_staged_update


def _wait_for_parent(parent_pid: int, timeout: float = 30.0) -> None:
    if parent_pid <= 0:
        raise ValueError("Parent process ID must be positive")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(parent_pid, 0)
        except OSError:
            return
        time.sleep(0.2)
    raise TimeoutError("Parent process did not exit before update")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply staged application update")
    parser.add_argument("--target", required=True)
    parser.add_argument("--staged", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--parent-pid", required=True, type=int)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-size", required=True, type=int)
    args = parser.parse_args(argv)
    _wait_for_parent(args.parent_pid)
    apply_staged_update(
        target=Path(args.target),
        staged=Path(args.staged),
        backup=Path(args.backup),
        expected_sha256=args.expected_sha256,
        expected_size=args.expected_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
