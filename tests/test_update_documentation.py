from __future__ import annotations

from pathlib import Path

from core.config import Config


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_update_documentation_matches_current_version_and_defaults() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    spec = (REPO_ROOT / "subtitle_extractor.spec").read_text(encoding="utf-8")

    assert f"v{Config.VERSION}" in readme
    assert f"**버전**: v{Config.VERSION}" in claude
    assert f'default: str = "{Config.VERSION}"' in spec
    assert "UPDATE_PUBLIC_KEY_B64_DEFAULT" in readme or "기본 manifest URL과 공개키" in readme
