from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_support.subprocess_compat import (
    run_pyright_workspace_check,
    subprocess_spawn_supported,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_pyright_reports_zero_workspace_errors_in_process():
    exit_code, summary = run_pyright_workspace_check(PROJECT_ROOT)

    assert exit_code == 0, summary
    assert summary.get("errorCount") == 0, summary


@pytest.mark.requires_subprocess
def test_pyright_reports_zero_workspace_errors_subprocess():
    result = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    summary: dict[str, object] = {}
    if result.stdout:
        summary = json.loads(result.stdout).get("summary", {})

    assert result.returncode == 0, result.stdout or result.stderr
    assert summary.get("errorCount") == 0, result.stdout


def test_pyright_regression_has_subprocess_fallback_path():
    """에이전트 샌드박스에서는 in-process 경로가 기본으로 동작해야 한다."""
    if subprocess_spawn_supported():
        pytest.skip("subprocess 가능 환경에서는 in-process 전용 fallback 검증을 생략합니다.")
    exit_code, summary = run_pyright_workspace_check(PROJECT_ROOT)
    assert exit_code == 0
    assert summary.get("errorCount") == 0