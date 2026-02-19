# -*- coding: utf-8 -*-

import re
import sys
from pathlib import Path


def _load_version_from_readme(default: str = "unknown") -> str:
    """README 첫 줄에서 버전 문자열(vX.YZ)을 추출한다."""
    try:
        readme_path = Path(__file__).resolve().parent.parent / "README.md"
        if not readme_path.exists():
            return default
        with readme_path.open("r", encoding="utf-8") as f:
            first_line = f.readline()
        match = re.search(r"\bv(\d+(?:\.\d+)*)", first_line, re.IGNORECASE)
        return match.group(1) if match else default
    except Exception:
        return default


def _resolve_app_base_dir() -> Path:
    """앱 데이터/설정 파일의 기준 디렉터리를 계산한다."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

class Config:
    """프로그램 설정 상수"""
    VERSION = _load_version_from_readme()
    APP_NAME = "국회 의사중계 자막 추출기"
    APP_BASE_DIR = _resolve_app_base_dir()
    
    # 타이밍 상수 (초)
    SUBTITLE_FINALIZE_DELAY = 3.0      # 자막 확정까지 대기 시간 (앵커 기반 알고리즘)
    ANCHOR_SUFFIX_LENGTH = 80          # 앵커로 저장할 텍스트 길이 (compact 기준)
    SUBTITLE_KEEPALIVE_INTERVAL = 1.0  # 동일 자막 유지 시 end_time 갱신 간격 (초)
    FINALIZE_CHECK_INTERVAL = 500      # 자막 확정 체크 간격 (ms)
    QUEUE_PROCESS_INTERVAL = 100       # 메시지 큐 처리 간격 (ms)
    STATS_UPDATE_INTERVAL = 1000       # 통계 업데이트 간격 (ms)
    SUBTITLE_CHECK_INTERVAL = 0.2      # 자막 확인 간격 (초)
    THREAD_STOP_TIMEOUT = 3            # 스레드 종료 대기 시간 (초)
    PAGE_LOAD_WAIT = 3                 # 페이지 로딩 대기 시간 (초)
    WEBDRIVER_WAIT_TIMEOUT = 20        # WebDriver 대기 타임아웃 (초)
    SCRIPT_DELAY = 0.5                 # 스크립트 실행 후 대기 (초)
    
    # 네트워크 타임아웃 (초)
    API_TIMEOUT = 5           # API 호출
    PAGE_LOAD_TIMEOUT = 30    # 페이지 로딩
    ELEMENT_WAIT_TIMEOUT = 10 # 요소 대기
    
    # 자동 백업
    AUTO_BACKUP_INTERVAL = 300000      # 5분 (ms)
    MAX_BACKUP_COUNT = 10
    MAX_URL_HISTORY = 50               # URL 히스토리 최대 개수
    
    # 성능 최적화 상수 (#4, #1)
    MAX_RENDER_ENTRIES = 500           # 한 번에 렌더링할 최대 자막 수
    MAX_WORD_DIFF_OVERLAP = 200        # get_word_diff 최대 겹침 탐색 길이
    
    # 경로
    LOG_DIR = str(APP_BASE_DIR / "logs")
    SESSION_DIR = str(APP_BASE_DIR / "sessions")
    REALTIME_DIR = str(APP_BASE_DIR / "realtime_output")
    BACKUP_DIR = str(APP_BASE_DIR / "backups")
    PRESET_FILE = str(APP_BASE_DIR / "committee_presets.json")
    URL_HISTORY_FILE = str(APP_BASE_DIR / "url_history.json")
    
    # 기본 CSS 선택자
    DEFAULT_SELECTORS = [
        "#viewSubtit .smi_word:last-child",
        "#viewSubtit .smi_word",
        "#viewSubtit .incont",
        "#viewSubtit",
        ".subtitle_area",
    ]
    
    # 기본 URL
    DEFAULT_URL = "https://assembly.webcast.go.kr/main/player.asp"
    
    # 상임위원회 기본 프리셋 (v16.0 기준 동작하는 xcode 값)
    # xcode: 위원회(채널) 구분 고정 값
    # xcgcd: 해당 회의의 고유 방송 ID (매 회의마다 변경)
    DEFAULT_COMMITTEE_PRESETS = {
        "본회의": "https://assembly.webcast.go.kr/main/player.asp",
        "국회운영위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=24",
        "법제사법위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=25",
        "정무위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=26",
        "재정경제기획위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=65",
        "교육위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=58",
        "과학기술정보방송통신위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=56",
        "외교통일위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=48",
        "국방위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=37",
        "행정안전위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=45",
        "문화체육관광위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=59",
        "농림축산식품해양수산위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=53",
        "산업통상자원중소벤처기업위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=55",
        "보건복지위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=33",
        "기후환경노동위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=62",
        "국토교통위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=54",
        "정보위원회": "https://assembly.webcast.go.kr/main/player.asp",
        "성평등가족위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=63",
        "예산결산특별위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=21",
        # 특별위원회 (문자열 xcode 사용)
        "국정감사": "https://assembly.webcast.go.kr/main/player.asp?xcode=IO",
        "국정조사": "https://assembly.webcast.go.kr/main/player.asp?xcode=IO",
        "국회정보나침반": "https://assembly.webcast.go.kr/main/player.asp?xcode=IO",
    }
    
    # 상임위원회 xcode 값 매핑 (v16.0 기준 동작하는 값)
    COMMITTEE_XCODE_MAP = {
        "본회의": None,  # 본회의는 xcode 없이 접근
        "국회운영위원회": 24,
        "법제사법위원회": 25,
        "정무위원회": 26,
        "재정경제기획위원회": 65,
        "교육위원회": 58,
        "과학기술정보방송통신위원회": 56,
        "외교통일위원회": 48,
        "국방위원회": 37,
        "행정안전위원회": 45,
        "문화체육관광위원회": 59,
        "농림축산식품해양수산위원회": 53,
        "산업통상자원중소벤처기업위원회": 55,
        "보건복지위원회": 33,
        "기후환경노동위원회": 62,
        "국토교통위원회": 54,
        "정보위원회": None,
        "성평등가족위원회": 63,
        "예산결산특별위원회": 21,
        # 특별위원회 (문자열 xcode)
        "국정감사": "IO",
        "국정조사": "IO",
        "국회정보나침반": "IO",
    }
    
    # 특별위원회 문자열 xcode 목록 (숫자가 아닌 코드들)
    SPECIAL_COMMITTEE_XCODES = {
        "IO": "국정감사/국정조사",
        "NA": "본회의장",
        "PP": "기자회견",
    }
    
    # 상임위원회 약칭 매핑 (사이트 내 표기 포함)
    COMMITTEE_ABBREVIATIONS = {
        # 기본 약칭
        "운영위": "국회운영위원회",
        "법사위": "법제사법위원회",
        "정무위": "정무위원회",
        "기재위": "재정경제기획위원회",  # 구 기획재정위원회 → 재정경제기획위원회
        "재경위": "재정경제기획위원회",  # 사이트 내 타이틀 표기
        "교육위": "교육위원회",
        "과방위": "과학기술정보방송통신위원회",
        "외통위": "외교통일위원회",
        "국방위": "국방위원회",
        "행안위": "행정안전위원회",
        "문체위": "문화체육관광위원회",
        "농해수위": "농림축산식품해양수산위원회",
        "산자위": "산업통상자원중소벤처기업위원회",
        "산자중기위": "산업통상자원중소벤처기업위원회",
        "복지위": "보건복지위원회",
        "환노위": "기후환경노동위원회",  # 구 환경노동위원회 → 기후환경노동위원회
        "기후노동위": "기후환경노동위원회",  # 사이트 내 타이틀 표기
        "국토위": "국토교통위원회",
        "여가위": "성평등가족위원회",  # 구 여성가족위원회 → 성평등가족위원회
        "성평등가족위": "성평등가족위원회",  # 사이트 내 타이틀 표기
        "예결위": "예산결산특별위원회",
        "특별위": "특별위원회",
    }
    
    # 폰트 설정
    DEFAULT_FONT_SIZE = 14
    MIN_FONT_SIZE = 10
    MAX_FONT_SIZE = 24
    
    # 연결 상태 모니터링 (#30)
    CONNECTION_CHECK_INTERVAL = 5000   # 연결 상태 체크 간격 (ms)
    
    # 스마트 스크롤
    SCROLL_BOTTOM_THRESHOLD = 50       # 맨 아래 감지 임계값 (픽셀)

    # 생중계 갱신 감지 (초)
    LIVE_BROADCAST_REFRESH_INTERVAL = 30

    # 자동 재연결 (#31)
    AUTO_RECONNECT_ENABLED = True
    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_BASE_DELAY = 2           # 초기 대기 시간 (초)
    RECONNECT_MAX_DELAY = 60           # 최대 대기 시간 (초)

    # 중지 시 브라우저 창 유지
    KEEP_BROWSER_ON_STOP = True

    # 자막 병합 기준 (너무 길거나 간격이 크면 분리)
    ENTRY_MERGE_MAX_CHARS = 400
    ENTRY_MERGE_MAX_GAP = 90  # 초

    # 스트리밍 자막 최대 길이 (초과 시 강제 분할하여 새 타임스탬프 생성)
    STREAM_SUBTITLE_MAX_LENGTH = 300

    
    # 자동 파일명 생성 (#28)
    DEFAULT_FILENAME_TEMPLATE = "{date}_{committee}_{time}"
    FILENAME_DATE_FORMAT = "%Y%m%d"
    FILENAME_TIME_FORMAT = "%H%M%S"
    
    # 데이터베이스 (#26)
    DATABASE_PATH = str(APP_BASE_DIR / "subtitle_history.db")
    
    # 성능 최적화: 사전 컴파일된 정규식 패턴
    RE_YEAR = re.compile(r'\b\d{4}년\b')              # 년도 제거용
    RE_ZERO_WIDTH = re.compile(r'[\u200b\u200c\u200d\ufeff]')  # Zero-width 문자
    RE_MULTI_SPACE = re.compile(r'\s+')              # 연속 공백 정규화



# ============================================================
# 라이브 방송 선택 다이얼로그
# ============================================================

