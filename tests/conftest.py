import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_subprocess: 자식 프로세스 생성이 가능한 환경에서만 실행",
    )


def pytest_collection_modifyitems(config, items: list[pytest.Item]) -> None:
    from tests.test_support.subprocess_compat import subprocess_spawn_supported

    if subprocess_spawn_supported():
        return
    skip_marker = pytest.mark.skip(
        reason="현재 환경에서 subprocess 자식 프로세스 생성이 불가합니다."
    )
    for item in items:
        if "requires_subprocess" in item.keywords:
            item.add_marker(skip_marker)