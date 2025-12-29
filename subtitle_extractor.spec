# -*- mode: python ; coding: utf-8 -*-
"""
국회 의사중계 자막 추출기 v15.1 - PyInstaller Spec File (Onefile Edition)

빌드 명령어:
    pyinstaller subtitle_extractor.spec

생성되는 파일:
    dist/subtitle_extractor.exe (단일 실행 파일)
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 숨겨진 임포트 모듈 수집
hiddenimports = [
    # PyQt6 관련
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.sip',
    
    # Selenium 관련
    'selenium',
    'selenium.webdriver',
    'selenium.webdriver.chrome',
    'selenium.webdriver.chrome.options',
    'selenium.webdriver.chrome.service',
    'selenium.webdriver.common.by',
    'selenium.webdriver.support.ui',
    'selenium.webdriver.support.expected_conditions',
    'selenium.common.exceptions',
    
    # 표준 라이브러리
    'json',
    'logging',
    'queue',
    'threading',
    're',
    'time',
    'datetime',
    'pathlib',
    
    # 선택적 라이브러리 (있으면 포함)
    'docx',
    'docx.shared',
    'docx.enum.text',
    'win32com.client',
]

# Selenium 서브모듈 자동 수집
try:
    hiddenimports += collect_submodules('selenium')
except Exception:
    pass

# PyQt6 서브모듈 자동 수집
try:
    hiddenimports += collect_submodules('PyQt6')
except Exception:
    pass

# 제외할 모듈 (용량 최적화)
excludes = [
    'tkinter',
    '_tkinter',
    'matplotlib',
    'numpy',
    'pandas',
    'scipy',
    'PIL',
    'cv2',
    'IPython',
    'jupyter',
    'notebook',
    'pytest',
    'unittest',
    'test',
    'tests',
]

# Analysis 설정
a = Analysis(
    ['251226 국회의사중계 자막.py'],
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

# PYZ 설정
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# EXE 설정 (Onefile 모드)
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
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI 앱이므로 콘솔 숨김
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

# COLLECT 설정 제거 (Onefile 모드에서는 사용하지 않음)
# coll = COLLECT(...)

# ============================================================
# 빌드 후 추가 작업 안내
# ============================================================
"""
빌드 완료 후:

1. dist/subtitle_extractor.exe (단일 파일)이 생성됩니다.

2. 이 파일 하나만 배포하면 됩니다.

3. 실행 시 주의사항:
   - 처음 실행 시 임시 폴더에 압축을 풀기 때문에 실행 시간이 조금 더 걸릴 수 있습니다.
   - 일부 백신 프로그램이 오탐지할 수 있습니다.
   - 로그 파일(logs), 프리셋(presets) 등은 실행 파일과 같은 위치에 생성됩니다.

4. 디버깅 시:
   - console=True 로 변경하여 빌드 후 에러 메시지를 확인하세요.

5. 버전 정보:
   - v15.1: UI/UX 리팩토링, 테마 호환성 개선, UI 클리핑 수정
"""
