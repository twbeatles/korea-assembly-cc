# -*- coding: utf-8 -*-
"""parity/ 사본을 Chrome 확장 저장소(korea-assembly-cc-chrome)와 비교한다.

형제 저장소가 없으면(CI 등) 건너뛴다. 줄바꿈(CRLF/LF) 차이는 무시한다.

사용:
  python scripts/check_parity_sync.py
  python scripts/check_parity_sync.py --write   # 이 저장소 사본을 Chrome 저장소에 복사
  KOREA_ASSEMBLY_CC_CHROME_DIR=... python scripts/check_parity_sync.py
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

PARITY_FILES = ("README.md", "capture-contract.json", "pipeline-vectors.json")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _sibling_parity_dir() -> Path:
    override = os.environ.get("KOREA_ASSEMBLY_CC_CHROME_DIR", "").strip()
    root = Path(override) if override else _repo_root().parent / "korea-assembly-cc-chrome"
    return root.resolve() / "parity"


def _read_normalized(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except FileNotFoundError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Chrome 저장소 사본을 덮어쓴다")
    args = parser.parse_args(argv)

    local_dir = _repo_root() / "parity"
    sibling_dir = _sibling_parity_dir()
    if not sibling_dir.is_dir():
        print(
            f"Parity sync skipped: chrome repository not found at {sibling_dir} "
            "(set KOREA_ASSEMBLY_CC_CHROME_DIR)"
        )
        return 0

    if args.write:
        for name in PARITY_FILES:
            shutil.copyfile(local_dir / name, sibling_dir / name)
        print(f"Parity files copied to {sibling_dir}")
        return 0

    mismatches: list[str] = []
    for name in PARITY_FILES:
        local_text = _read_normalized(local_dir / name)
        sibling_text = _read_normalized(sibling_dir / name)
        if local_text is None:
            mismatches.append(f"{name}: missing in this repository")
        elif sibling_text is None:
            mismatches.append(f"{name}: missing in chrome repository")
        elif local_text != sibling_text:
            mismatches.append(f"{name}: content differs")

    if mismatches:
        print(f"Parity files differ from {sibling_dir}:", file=sys.stderr)
        for item in mismatches:
            print(f"- {item}", file=sys.stderr)
        print("Update both repositories (see parity/README.md).", file=sys.stderr)
        return 1

    print(f"Parity sync passed: {sibling_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
