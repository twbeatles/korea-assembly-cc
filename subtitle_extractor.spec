# -*- mode: python ; coding: utf-8 -*-
"""
국회 의사중계 자막 추출기 v17.1 - PyInstaller Spec File (경량화 버전)

빌드 명령어:
    pyinstaller subtitle_extractor.spec

생성되는 파일:
    dist/subtitle_extractor.exe (단일 실행 파일)

경량화 최적화:
    - 불필요한 모듈 제외 (tkinter, matplotlib, numpy 등)
    - Playwright 제외 (PyInstaller 비호환)
    - UPX 압축 활성화
    - 디버그 정보 제거
"""

import sys
from PyInstaller.utils.hooks import collect_submodules

# ============================================================
# 숨겨진 임포트 (필수 모듈만 포함 - 경량화)
# ============================================================
hiddenimports = [
    # PyQt6 코어 (필수)
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.sip',
    
    # Selenium 코어 (필수)
    'selenium.webdriver',
    'selenium.webdriver.chrome.options',
    'selenium.webdriver.chrome.service',
    'selenium.webdriver.firefox.options',
    'selenium.webdriver.firefox.service',
    'selenium.webdriver.edge.options',
    'selenium.webdriver.edge.service',
    'selenium.webdriver.common.by',
    'selenium.webdriver.support.ui',
    'selenium.webdriver.support.expected_conditions',
    'selenium.common.exceptions',
    
    # 앱 모듈 (v17.1)
    'browser_drivers',
    'subtitle_session',
    'session_tab_widget',
    
    # 표준 라이브러리 (필수)
    'json',
    'logging',
    'queue',
    'threading',
    're',
    'time',
    'datetime',
    'pathlib',
    'shutil',
    'uuid',
    'dataclasses',
    'abc',
    'enum',
    'typing',
]

# 선택적 모듈 (있으면 포함)
optional_modules = [
    'docx',
    'docx.shared',
    'docx.enum.text',
    'win32com.client',
]

for mod in optional_modules:
    try:
        __import__(mod.split('.')[0])
        hiddenimports.append(mod)
    except ImportError:
        pass

# ============================================================
# 제외 모듈 (경량화 - 용량 대폭 감소)
# ============================================================
excludes = [
    # GUI 프레임워크
    'tkinter', '_tkinter', 'tkinter.ttk',
    
    # 과학/데이터 라이브러리
    'matplotlib', 'numpy', 'pandas', 'scipy', 'sklearn',
    'PIL', 'pillow', 'cv2', 'opencv',
    
    # 개발/테스트 도구
    'IPython', 'jupyter', 'notebook', 'pytest', 'unittest',
    'test', 'tests', 'sphinx', 'docutils',
    
    # Playwright (PyInstaller 비호환 - Node.js 의존성)
    'playwright', 'playwright.sync_api', 'playwright.async_api',
    
    # 기타 불필요한 모듈
    'asyncio', 'multiprocessing', 'concurrent',
    'email', 'html.parser', 'http.server',
    'xml.etree', 'xml.dom', 'xml.sax',
    'distutils', 'setuptools', 'pkg_resources',
    'lib2to3', 'pydoc', 'pydoc_data',
]

# ============================================================
# Analysis 설정
# ============================================================
a = Analysis(
    ['multi_session_launcher.py'],  # v17.1 다중 세션 버전
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# ============================================================
# 불필요한 바이너리 제거 (경량화)
# ============================================================
# Qt 플러그인 중 불필요한 것 제거
excluded_binaries = [
    'Qt6Pdf', 'Qt6Quick', 'Qt6Qml', 'Qt6Network', 'Qt6Sql',
    'Qt6Svg', 'Qt63D', 'Qt6Multimedia', 'Qt6WebEngine',
    'opengl32sw', 'd3dcompiler',
]

a.binaries = [b for b in a.binaries if not any(exc in b[0] for exc in excluded_binaries)]

# ============================================================
# PYZ 설정 (압축 최적화)
# ============================================================
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=None,
)

# ============================================================
# EXE 설정 (Onefile + 경량화)
# ============================================================
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='subtitle_extractor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,  # 디버그 심볼 제거 (경량화)
    upx=True,    # UPX 압축 활성화 (경량화)
    upx_exclude=[
        'vcruntime140.dll',
        'python3*.dll',
        'Qt6Core.dll',
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
    ],
    runtime_tmpdir=None,
    console=False,  # GUI 앱 (콘솔 숨김)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    # 버전 정보
    version=None,
)

# ============================================================
# 빌드 안내
# ============================================================
"""
=== 빌드 명령어 ===
pyinstaller subtitle_extractor.spec

=== 경량화 팁 ===
1. UPX 설치: https://github.com/upx/upx/releases
   - 다운로드 후 PATH에 추가하면 자동으로 압축됩니다.

2. 가상 환경 사용:
   - 새 가상환경에서 필수 패키지만 설치하면 더 경량화됩니다.
   - pip install PyQt6 selenium python-docx pywin32

3. 예상 파일 크기:
   - UPX 없이: ~80-100MB
   - UPX 적용: ~40-60MB

=== 주의사항 ===
- Playwright는 PyInstaller에서 지원되지 않습니다.
- EXE 실행 시 Selenium 브라우저만 사용 가능합니다.
- 첫 실행 시 임시 폴더 압축 해제로 시간이 걸릴 수 있습니다.

=== 디버깅 ===
- 오류 확인 시 console=True로 변경하고 재빌드하세요.
"""
