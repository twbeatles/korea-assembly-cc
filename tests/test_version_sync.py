# -*- coding: utf-8 -*-

import re
from pathlib import Path

from core.config import Config


def test_readme_and_config_version_are_synced():
    readme_first_line = Path("README.md").read_text(encoding="utf-8").splitlines()[0]
    match = re.search(r"\bv(\d+(?:\.\d+)*)", readme_first_line)
    assert match is not None
    assert Config.VERSION == match.group(1)


def test_spec_default_version_matches_readme():
    spec_text = Path("subtitle_extractor.spec").read_text(encoding="utf-8")
    readme_first_line = Path("README.md").read_text(encoding="utf-8").splitlines()[0]

    spec_match = re.search(
        r'_load_version_from_readme\(default: str = "(\d+(?:\.\d+)*)"\)', spec_text
    )
    readme_match = re.search(r"\bv(\d+(?:\.\d+)*)", readme_first_line)

    assert spec_match is not None
    assert readme_match is not None
    assert spec_match.group(1) == readme_match.group(1)
