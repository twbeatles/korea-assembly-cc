"""GitHub Actions CI 워크플로 정합성 회귀 테스트.

재발 방지: setup-python cache: pip 는 기본으로 requirements.txt /
pyproject.toml 만 찾고, 이 저장소는 requirements-dev.txt 만 사용한다.
cache-dependency-path 누락 시 Windows CI 가 install 전에 즉시 실패한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEV_REQUIREMENTS = REPO_ROOT / "requirements-dev.txt"


def _workflow_text() -> str:
    assert CI_WORKFLOW.is_file(), f"missing CI workflow: {CI_WORKFLOW}"
    return CI_WORKFLOW.read_text(encoding="utf-8")


def test_requirements_dev_exists() -> None:
    assert DEV_REQUIREMENTS.is_file(), "requirements-dev.txt must exist at repo root"


def test_ci_workflow_installs_requirements_dev() -> None:
    text = _workflow_text()
    assert "requirements-dev.txt" in text
    assert re.search(
        r"pip\s+install\s+-r\s+requirements-dev\.txt",
        text,
    ), "CI must install from requirements-dev.txt"


def test_ci_setup_python_cache_uses_requirements_dev() -> None:
    """cache: pip 사용 시 cache-dependency-path 가 실제 의존성 파일을 가리켜야 한다."""
    text = _workflow_text()
    if not re.search(r"(?m)^\s*cache:\s*pip\s*$", text):
        pytest.skip("CI does not enable pip cache")

    match = re.search(
        r"(?m)^\s*cache-dependency-path:\s*(.+?)\s*$",
        text,
    )
    assert match is not None, (
        "actions/setup-python with cache: pip requires cache-dependency-path "
        "pointing at requirements-dev.txt (this repo has no requirements.txt)"
    )
    path_value = match.group(1).strip().strip("\"'")
    # 단일 파일 또는 공백/줄바꿈 목록 중 requirements-dev.txt 포함 여부
    declared = {
        part.strip()
        for part in re.split(r"[\s,]+", path_value)
        if part.strip()
    }
    assert "requirements-dev.txt" in declared, (
        f"cache-dependency-path must include requirements-dev.txt, got {path_value!r}"
    )
    for rel in declared:
        candidate = REPO_ROOT / rel
        assert candidate.is_file(), (
            f"cache-dependency-path entry does not exist: {rel}"
        )


def test_ci_does_not_assume_missing_requirements_txt() -> None:
    """requirements.txt 가 없는 한, 워크플로가 그 파일만 의존하지 않는지 확인."""
    text = _workflow_text()
    has_root_requirements = (REPO_ROOT / "requirements.txt").is_file()
    if has_root_requirements:
        return
    # install 단계에서 requirements.txt 단독 설치를 강제하지 말 것
    assert not re.search(
        r"pip\s+install\s+-r\s+requirements\.txt\b",
        text,
    ), "CI must not pip install -r requirements.txt when the file is absent"


def test_ci_forces_utf8_and_offscreen_for_windows_runner() -> None:
    """Windows runner 에서 한글 JSON smoke / Qt 창 생성이 안정적으로 동작하도록 환경 고정."""
    text = _workflow_text()
    assert re.search(r"(?m)^\s*PYTHONUTF8:\s*[\"']?1[\"']?\s*$", text)
    assert re.search(r"(?m)^\s*PYTHONIOENCODING:\s*utf-8\s*$", text)
    assert re.search(r"(?m)^\s*QT_QPA_PLATFORM:\s*offscreen\s*$", text)


def test_ci_runs_update_signature_and_rollback_fixtures() -> None:
    text = _workflow_text()
    assert "tests/test_update_manifest.py" in text
    assert "tests/test_update_installer.py" in text
    assert "tests/test_resource_budget.py" in text
