# -*- mode: python ; coding: utf-8 -*-
"""
국회 의사중계 자막 추출기 v16.11
PyInstaller Build Spec - 경량화 최적화 버전

빌드 명령: pyinstaller subtitle_extractor.spec
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

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
    'selenium.webdriver.chrome.service',
    'selenium.webdriver.common.by',
    'selenium.webdriver.support.ui',
    'selenium.webdriver.support.expected_conditions',
    'win32com',
    'win32com.client',
    'pythoncom',
    'queue',
    'threading',
    'json',
    'logging',
]

a = Analysis(
    ['국회의사중계 자막.py'],
    pathex=[],
    binaries=[],
    datas=[('README.md', '.')],
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
    name='국회의사중계자막추출기 v16.11',
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
    # icon='icon.ico',
)
