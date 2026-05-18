from __future__ import annotations

from pathlib import Path


def test_no_file_level_pyright_directives() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ignored_parts = {
        ".git",
        ".pytest_tmp",
        ".venv",
        ".claude",
        "__pycache__",
        "build",
        "dist",
    }
    offenders: list[str] = []
    for path in repo_root.rglob("*.py"):
        if ignored_parts.intersection(path.relative_to(repo_root).parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(lines, start=1):
            if line.startswith("# pyright:"):
                offenders.append(f"{path.relative_to(repo_root)}:{line_no}")
    assert offenders == []
