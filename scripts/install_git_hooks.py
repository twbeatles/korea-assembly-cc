# -*- coding: utf-8 -*-
"""저장소 git hooks 설치 (pre-push → pyright).

  python scripts/install_git_hooks.py
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    src = root / "scripts" / "git-hooks" / "pre-push"
    git_dir = root / ".git"
    if not git_dir.is_dir():
        print(".git 이 없습니다. 저장소 루트에서 실행하세요.", file=sys.stderr)
        return 1
    if not src.is_file():
        print(f"훅 소스가 없습니다: {src}", file=sys.stderr)
        return 1

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    dest = hooks_dir / "pre-push"

    # Windows에서도 sh 호환 스크립트 복사 (Git for Windows가 실행)
    shutil.copyfile(src, dest)
    mode = dest.stat().st_mode
    dest.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Windows: 추가로 .bat 래퍼 (git config core.hooksPath 없이 동작하는 환경용 참고)
    bat = hooks_dir / "pre-push.cmd"
    bat.write_text(
        "@echo off\r\n"
        "cd /d \"%~dp0..\\..\"\r\n"
        "python scripts\\check_before_push.py --pyright-only\r\n"
        "exit /b %ERRORLEVEL%\r\n",
        encoding="utf-8",
    )

    print(f"설치 완료: {dest}")
    print("푸시 시 pyright 0 errors 검사가 실행됩니다.")
    print("수동 검사: python scripts/check_before_push.py --pyright-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
