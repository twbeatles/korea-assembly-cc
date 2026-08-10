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


def _format_pyright_failure(payload_or_summary: object) -> str:
    """CI 로그에서 원인 파일을 바로 보이게 한다."""
    if isinstance(payload_or_summary, dict) and "generalDiagnostics" in payload_or_summary:
        payload = payload_or_summary
        summary = payload.get("summary") or {}
        lines = [
            f"errorCount={summary.get('errorCount')} "
            f"filesAnalyzed={summary.get('filesAnalyzed')}"
        ]
        for diag in (payload.get("generalDiagnostics") or [])[:15]:
            if str(diag.get("severity") or "").lower() != "error":
                continue
            path = str(diag.get("file") or "")
            line = int((diag.get("range") or {}).get("start", {}).get("line", 0)) + 1
            msg = str(diag.get("message") or "").split("\n", 1)[0]
            rule = str(diag.get("rule") or "")
            lines.append(f"  {path}:{line}: {msg}" + (f" ({rule})" if rule else ""))
        return "\n".join(lines)
    return repr(payload_or_summary)


def test_pyright_reports_zero_workspace_errors_in_process():
    exit_code, summary = run_pyright_workspace_check(PROJECT_ROOT)

    assert exit_code == 0, _format_pyright_failure(summary)
    assert summary.get("errorCount") == 0, _format_pyright_failure(summary)


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

    payload: dict[str, object] = {}
    summary: dict[str, object] = {}
    if result.stdout:
        payload = json.loads(result.stdout)
        summary = payload.get("summary", {})  # type: ignore[assignment]

    detail = _format_pyright_failure(payload if payload else summary)
    assert result.returncode == 0, detail or (result.stdout or result.stderr)
    assert summary.get("errorCount") == 0, detail


def test_pyright_regression_has_subprocess_fallback_path():
    """에이전트 샌드박스에서는 in-process 경로가 기본으로 동작해야 한다."""
    if subprocess_spawn_supported():
        pytest.skip("subprocess 가능 환경에서는 in-process 전용 fallback 검증을 생략합니다.")
    exit_code, summary = run_pyright_workspace_check(PROJECT_ROOT)
    assert exit_code == 0
    assert summary.get("errorCount") == 0