# -*- coding: utf-8 -*-

"""README 버전 추출 (SRP: 버전 문자열 판독만 담당)."""

from __future__ import annotations

import re
from pathlib import Path

def _load_version_from_readme(default: str = "unknown") -> str:
    """README 첫 줄에서 버전 문자열(vX.YZ)을 추출한다."""
    try:
        readme_path = Path(__file__).resolve().parent.parent.parent / "README.md"
        if not readme_path.exists():
            return default
        with readme_path.open("r", encoding="utf-8") as f:
            first_line = f.readline()
        match = re.search(r"\bv(\d+(?:\.\d+)*)", first_line, re.IGNORECASE)
        return match.group(1) if match else default
    except Exception:
        return default
