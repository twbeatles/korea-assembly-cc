# -*- coding: utf-8 -*-
"""푸시 전 품질 검사 (pyright 필수, pytest 선택).

사용:
  python scripts/check_before_push.py
  python scripts/check_before_push.py --pyright-only
  python scripts/check_before_push.py --with-pytest
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def run_pyright() -> int:
    root = _repo_root()
    cmd = [sys.executable, "-m", "pyright", "--outputjson"]
    print(">>", " ".join(cmd), flush=True)
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        print(proc.stderr or "pyright 출력 없음", file=sys.stderr)
        return proc.returncode or 1

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(raw)
        print(proc.stderr or "", file=sys.stderr)
        return proc.returncode or 1

    summary = payload.get("summary") or {}
    error_count = int(summary.get("errorCount") or 0)
    warning_count = int(summary.get("warningCount") or 0)
    print(
        f"pyright: errors={error_count} warnings={warning_count} "
        f"files={summary.get('filesAnalyzed', '?')}",
        flush=True,
    )
    if error_count:
        for diag in payload.get("generalDiagnostics") or []:
            if str(diag.get("severity") or "").lower() != "error":
                continue
            file_path = str(diag.get("file") or "")
            line = int((diag.get("range") or {}).get("start", {}).get("line", 0)) + 1
            message = str(diag.get("message") or "")
            print(f"  ERROR {file_path}:{line}: {message}", file=sys.stderr)
        print(
            "\n[실패] pyright errorCount > 0 — 푸시 전에 수정하세요 "
            "(프로젝트 정책: 0 errors).",
            file=sys.stderr,
        )
        return 1
    return 0


def run_pytest() -> int:
    root = _repo_root()
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=line"]
    print(">>", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(root))
    return int(proc.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="푸시 전 pyright/pytest 검사")
    parser.add_argument(
        "--pyright-only",
        action="store_true",
        help="pyright만 실행 (pre-push 훅 기본)",
    )
    parser.add_argument(
        "--with-pytest",
        action="store_true",
        help="pyright 통과 후 pytest 전체 실행",
    )
    args = parser.parse_args(argv)

    code = run_pyright()
    if code != 0:
        return code
    if args.pyright_only and not args.with_pytest:
        return 0
    if args.with_pytest or not args.pyright_only:
        # 기본 호출(인자 없음)은 pyright만 — pre-push 속도 우선
        # --with-pytest 일 때만 pytest
        if args.with_pytest:
            return run_pytest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
