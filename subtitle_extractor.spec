# -*- mode: python ; coding: utf-8 -*-
"""
국회 의사중계 자막 추출기 PyInstaller Build Spec

버전과 EXE 이름은 README.md 첫 줄과 동기화됩니다.

빌드 명령: pyinstaller subtitle_extractor.spec
"""

import re
from pathlib import Path

block_cipher = None


def _load_version_from_readme(default: str = "16.14.2") -> str:
    spec_path = Path(globals().get("__file__", "subtitle_extractor.spec")).resolve()
    readme_path = spec_path.parent / "README.md"
    try:
        first_line = readme_path.read_text(encoding="utf-8").splitlines()[0]
    except Exception:
        return default
    match = re.search(r"\bv(\d+(?:\.\d+)*)", first_line, re.IGNORECASE)
    return match.group(1) if match else default


APP_VERSION = _load_version_from_readme()
APP_ENTRYPOINT = "국회의사중계 자막.py"
APP_EXE_NAME = f"국회의사중계자막추출기 v{APP_VERSION}"

# 제외할 모듈 (경량화)
EXCLUDES = [
    # 불필요한 대형 라이브러리
    'matplotlib', 'numpy', 'pandas', 'scipy', 'PIL', 'cv2',
    'tkinter', 'tk', 'tcl',
    'IPython', 'jupyter', 'notebook',
    'pytest', 'unittest', 'test',
    # Qt 불필요 모듈
    'PyQt6.QtBluetooth', 'PyQt6.QtDesigner', 'PyQt6.QtHelp',
    'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets',
    'PyQt6.QtNetwork', 'PyQt6.QtNfc', 'PyQt6.QtOpenGL',
    'PyQt6.QtPositioning', 'PyQt6.QtPrintSupport',
    'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtQuickWidgets',
    'PyQt6.QtRemoteObjects', 'PyQt6.QtSensors', 'PyQt6.QtSerialPort',
    'PyQt6.QtSql', 'PyQt6.QtSvg', 'PyQt6.QtTest', 'PyQt6.QtWebChannel',
    'PyQt6.QtWebEngine', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebSockets', 'PyQt6.QtXml', 'PyQt6.Qt3DCore',
    'PyQt6.Qt3DAnimation', 'PyQt6.Qt3DExtras', 'PyQt6.Qt3DInput',
    'PyQt6.Qt3DLogic', 'PyQt6.Qt3DRender',
    # 기타
    'lib2to3', 'pydoc', 'doctest',
    'pkg_resources', 'setuptools', 'distutils',
]

# 숨겨진 import 명시
HIDDEN_IMPORTS = [
    'database',
    'docx',
    'docx.shared',
    'docx.enum.text',
    'core.database_manager',
    'core.file_io',
    'core.live_capture',
    'core.logging_utils',
    'core.models',
    'core.reflow',
    'core.subtitle_pipeline',
    'core.text_utils',
    'core.utils',
    'selenium.webdriver.chrome.service',
    'selenium.webdriver.common.by',
    'selenium.webdriver.support.ui',
    'selenium.webdriver.support.expected_conditions',
    'ui.dialogs',
    'ui.main_window',
    'ui.main_window_capture',
    'ui.main_window_common',
    'ui.main_window_database',
    'ui.main_window_persistence',
    'ui.main_window_pipeline',
    'ui.main_window_types',
    'ui.main_window_ui',
    'ui.main_window_view',
    'ui.themes',
    'ui.widgets',
    'win32com',
    'win32com.client',
    'pythoncom',
    'queue',
    'threading',
    'json',
    'logging',
    'queue',
    'threading',
    'json',
    'logging',
]

a = Analysis(
    [APP_ENTRYPOINT],
    pathex=[],
    binaries=[],
    # Config.VERSION이 README 첫 줄에서 버전을 읽으므로 빌드 산출물에도 함께 포함한다.
    datas=[('README.md', '.'), ('assets/icon.ico', 'assets')],
    hiddenimports=HIDDEN_IMPORTS + ['sqlite3'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 불필요한 바이너리 제거 (추가 경량화)
a.binaries = [x for x in a.binaries if not any(
    exc in x[0].lower() for exc in [
        'qt6webengine', 'qt6designer', 'qt6quick', 'qt6qml',
        'qt6multimedia', 'qt6pdf', 'qt6positioning',
        'd3dcompiler', 'opengl32sw',
    ]
)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # Windows에서는 strip 비활성화
    upx=True,  # UPX 압축 사용 (설치되어 있다면)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 콘솔 창 숨김 (GUI 앱)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # 아이콘 설정 (있을 경우)
    icon='assets/icon.ico',
)
