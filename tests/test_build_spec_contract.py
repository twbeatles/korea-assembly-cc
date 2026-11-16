# -*- coding: utf-8 -*-
"""PyInstaller spec 빌드 계약 회귀 (docs/BUILD_TROUBLESHOOTING.md §2.2·§2.3).

로컬 3.15 빌드에서 PATH 의 다른 버전 python3t.dll(C:\\Python314, 3.14t)이 번들되어
frozen EXE 가 `DLL load failed while importing _rust` 로 죽은 문제를 다시 만들지 않는다.
"""

from __future__ import annotations

import re
from pathlib import Path

SPEC_PATH = Path(__file__).resolve().parents[1] / "subtitle_extractor.spec"
SPEC = SPEC_PATH.read_text(encoding="utf-8")


def _extract_assignment(name: str) -> str:
    match = re.search(rf"^{name} = (.+)$", SPEC, re.MULTILINE)
    assert match, f"{name} assignment missing in spec"
    return match.group(1)


def test_python3t_dll_comes_from_current_interpreter_abi3t_compat() -> None:
    assert "os.path.join(sys.base_prefix, 'abi3t-compat', 'python3t.dll')" in SPEC
    # python-build-standalone(uv) 배포판은 prefix 루트에 둔다.
    assert "os.path.join(sys.base_prefix, 'python3t.dll')" in SPEC
    # 같은 이름이 이미 수집돼 있어도 교체해야 한다(이전 구현은 존재하면 추가를 건너뛰었다).
    assert "_binary_basename(b) != _py3t_dest" in SPEC
    assert "a.binaries.append((_py3t_dest, _py3t_dll, 'BINARY'))" in SPEC


def test_foreign_free_threaded_runtime_pattern() -> None:
    pattern_source = _extract_assignment("_FOREIGN_FT_RUNTIME")
    literal = re.search(r"re\.compile\(r'(.+)'\)", pattern_source)
    assert literal, pattern_source
    pattern = re.compile(literal.group(1))
    assert pattern.fullmatch("python314t.dll")
    assert pattern.fullmatch("python315t.dll")
    assert not pattern.fullmatch("python315.dll")
    assert not pattern.fullmatch("python3t.dll")
    assert not pattern.fullmatch("python3.dll")
    assert "_FOREIGN_FT_RUNTIME.fullmatch(_binary_basename(b))" in SPEC


def test_upx_excludes_native_runtime_and_rust_extension() -> None:
    assert "upx_exclude=_UPX_EXCLUDE" in SPEC
    block = SPEC[SPEC.index("_UPX_EXCLUDE = [") : SPEC.index("]", SPEC.index("_UPX_EXCLUDE = ["))]
    for name in ("'_rust.pyd'", "'python3.dll'", "'python3t.dll'", "'vcruntime140.dll'"):
        assert name in block, name
    assert "f'python{sys.version_info.major}{sys.version_info.minor}.dll'" in block


def test_fallback_commit_module_is_bundled() -> None:
    assert "'core.fallback_commit'," in SPEC


def test_missing_interpreter_python3t_with_foreign_copy_fails_the_build() -> None:
    assert "raise SystemExit(" in SPEC
    assert "BUILD_TROUBLESHOOTING.md" in SPEC
