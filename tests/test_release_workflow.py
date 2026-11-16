# -*- coding: utf-8 -*-
"""release.yml 회귀 (docs/BUILD_TROUBLESHOOTING.md §2.4).

- 배포 EXE 는 CI 와 같은 Python 버전으로 만든다.
- GUI(console=False) EXE smoke 는 `& $artifact` 로 실행하면 PowerShell 이 종료를 기다리지 않아
  실패한 EXE 도 통과했다. Start-Process -Wait 의 종료 코드와 smoke JSON ok 로 판정해야 한다.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _python_versions(text: str) -> list[str]:
    return re.findall(r'(?m)^\s*python-version:\s*"([^"]+)"', text)


def test_release_builds_with_same_python_as_ci() -> None:
    assert _python_versions(RELEASE) == _python_versions(CI) == ["3.15"]


def test_release_frozen_smoke_waits_for_gui_exe_exit_code() -> None:
    assert not re.search(r"(?m)^\s*&\s*\$artifact\b", RELEASE), (
        "`& $artifact` does not wait for a GUI-subsystem exe and leaves $LASTEXITCODE stale"
    )
    assert "Start-Process -FilePath $artifact" in RELEASE
    assert "-Wait -PassThru" in RELEASE
    assert "$smoke.ExitCode -ne 0" in RELEASE
    assert "--smoke-output" in RELEASE
    assert "$smokeResult.ok" in RELEASE
