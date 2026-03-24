from __future__ import annotations

import codecs
from pathlib import Path
import json


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".pyi",
    ".spec",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {".editorconfig", ".gitattributes", ".gitignore"}
EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
    "backups",
    "build",
    "dist",
    "logs",
    "realtime_output",
    "sessions",
    "tmp_extension_unpacked",
}
ROUND_TRIP_EXPECTATIONS = {
    PROJECT_ROOT / ".editorconfig": "charset = utf-8",
    PROJECT_ROOT / ".gitattributes": "working-tree-encoding=UTF-8",
    PROJECT_ROOT / ".vscode" / "settings.json": '"files.encoding": "utf8"',
    PROJECT_ROOT / "pyrightconfig.json": "국회의사중계 자막.py",
    PROJECT_ROOT / "typings" / "PyQt6" / "QtCore.pyi": "class QSettings(_QtObject): ...",
    PROJECT_ROOT / "ui" / "main_window_ui.py": "국회 의사중계 자막 추출기",
}


def _iter_repo_text_files() -> list[Path]:
    paths: list[Path] = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.name in TEXT_FILENAMES or path.suffix.lower() in TEXT_SUFFIXES:
            paths.append(path)
    return sorted(paths)


def test_repo_text_files_are_utf8_without_bom_or_replacement_chars():
    failures: list[str] = []

    for path in _iter_repo_text_files():
        data = path.read_bytes()
        rel_path = path.relative_to(PROJECT_ROOT)

        if data.startswith(codecs.BOM_UTF8):
            failures.append(f"{rel_path}: UTF-8 BOM detected")
            continue

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{rel_path}: not valid UTF-8 ({exc})")
            continue

        if "\ufffd" in text:
            failures.append(f"{rel_path}: contains replacement character U+FFFD")

    assert not failures, "\n".join(failures)


def test_critical_utf8_files_round_trip_expected_korean_and_config_text():
    for path, expected_text in ROUND_TRIP_EXPECTATIONS.items():
        text = path.read_text(encoding="utf-8")
        assert expected_text in text, f"{path.relative_to(PROJECT_ROOT)} is missing {expected_text!r}"

    config = json.loads((PROJECT_ROOT / "pyrightconfig.json").read_text(encoding="utf-8"))
    assert "국회의사중계 자막.py" in config["include"]
