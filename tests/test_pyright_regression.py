from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_pyright_reports_zero_workspace_errors():
    result = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    summary = {}
    if result.stdout:
        summary = json.loads(result.stdout).get("summary", {})

    assert result.returncode == 0, result.stdout or result.stderr
    assert summary.get("errorCount") == 0, result.stdout
