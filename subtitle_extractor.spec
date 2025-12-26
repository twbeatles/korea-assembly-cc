# -*- mode: python ; coding: utf-8 -*-
"""
국회 의사중계 자막 추출기 v14.0 - PyInstaller Spec File

빌드 명령어:
    pyinstaller subtitle_extractor.spec

생성되는 파일:
    dist/subtitle_extractor/subtitle_extractor.exe
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
    ['251214 국회의사중계 자막.py'],
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

# EXE 설정
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='subtitle_extractor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI 앱이므로 콘솔 숨김
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 아이콘 파일이 있으면 경로 지정: icon='icon.ico'
)

# COLLECT 설정 (폴더 모드)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='subtitle_extractor',
)

# ============================================================
# 빌드 후 추가 작업 안내
# ============================================================
"""
빌드 완료 후:

1. dist/subtitle_extractor/ 폴더에 실행 파일이 생성됩니다.

2. Chrome WebDriver는 Selenium 4.x에서 자동 관리됩니다.
   별도의 chromedriver.exe 파일이 필요하지 않습니다.

3. 배포 시 필요한 파일:
   - dist/subtitle_extractor/ 폴더 전체
   
4. 선택적 파일 (사용자 설정):
   - committee_presets.json (상임위 프리셋)
   - url_history.json (URL 히스토리)

5. 자동 생성되는 폴더:
   - logs/ (로그 파일)
   - sessions/ (세션 저장)
   - backups/ (자동 백업)
   - realtime_output/ (실시간 저장)

문제 해결:
- PyQt6 관련 오류: pip install PyQt6 --upgrade
- Selenium 관련 오류: pip install selenium --upgrade
- 빌드 오류: pip install pyinstaller --upgrade
"""
