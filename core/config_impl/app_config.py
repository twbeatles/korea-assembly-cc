# -*- coding: utf-8 -*-

"""앱 설정 상수 (SRP: 설정값 보관만 담당)."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from core.config_impl.storage import resolve_storage_resolution
from core.config_impl.version import _load_version_from_readme

_STORAGE_RESOLUTION = resolve_storage_resolution()

class Config:
    """프로그램 설정 상수"""
    VERSION = _load_version_from_readme()
    APP_NAME = "국회 의사중계 자막 추출기"
    APP_BASE_DIR = _STORAGE_RESOLUTION.install_dir
    STORAGE_DIR = str(_STORAGE_RESOLUTION.storage_dir)
    STORAGE_MODE = _STORAGE_RESOLUTION.storage_mode
    PORTABLE_FLAG_PATH = str(_STORAGE_RESOLUTION.portable_flag_path)
    SETTINGS_INI_PATH = (
        str(_STORAGE_RESOLUTION.settings_ini_path)
        if _STORAGE_RESOLUTION.settings_ini_path
        else ""
    )

    @staticmethod
    def get_resource_path(relative_path: str) -> str:
        """앱 내부 리소스 절대 경로를 반환한다 (PyInstaller 임시폴더 대응)"""
        base_path = getattr(sys, '_MEIPASS', None)
        if base_path:
            return os.path.join(base_path, relative_path)
        return os.path.join(Config.APP_BASE_DIR, relative_path)

    @staticmethod
    def run_storage_preflight() -> tuple[bool, str]:
        # NOTE: 실제 preflight 구현은 `core.config` 퍼사드가 소유한다.
        # 테스트가 `core.config._probe_*`를 monkeypatch하므로
        # 여기서는 호출 시점에 퍼사드로 late-binding 해야 패치가 유효하다.
        from core import config as _config_facade

        return _config_facade.run_storage_preflight(
            Config.STORAGE_DIR,
            settings_ini_path=Config.SETTINGS_INI_PATH or None,
            database_path=Config.DATABASE_PATH,
            preset_file=Config.PRESET_FILE,
            url_history_file=Config.URL_HISTORY_FILE,
            recovery_state_file=Config.RECOVERY_STATE_FILE,
        )
    
    # 타이밍 상수 (초)
    ANCHOR_SUFFIX_LENGTH = 80          # 앵커로 저장할 텍스트 길이 (compact 기준)
    SUBTITLE_KEEPALIVE_INTERVAL = 1.0  # 동일 자막 유지 시 end_time 갱신 간격 (초)
    QUEUE_PROCESS_INTERVAL = 100       # 메시지 큐 처리 간격 (ms)
    MESSAGE_QUEUE_MAX_SIZE = 500
    CONTROL_MESSAGE_QUEUE_MAX_SIZE = 200
    OVERFLOW_PASSTHROUGH_MAX = 128
    OVERFLOW_DROP_NOTICE_INTERVAL = 30.0
    WORKER_MESSAGE_PUT_TIMEOUT = 1.0
    PREVIEW_DRAIN_MAX_ITEMS = 2000
    STATS_UPDATE_INTERVAL = 1000       # 통계 업데이트 간격 (ms)
    SUBTITLE_CHECK_INTERVAL = 0.2      # 자막 확인 간격 (초)
    THREAD_STOP_TIMEOUT = 3            # 스레드 종료 대기 시간 (초)
    PAGE_LOAD_WAIT = 3                 # 페이지 로딩 대기 시간 (초)
    WEBDRIVER_WAIT_TIMEOUT = 20        # WebDriver 대기 타임아웃 (초)
    SCRIPT_DELAY = 0.5                 # 스크립트 실행 후 대기 (초)
    WEBDRIVER_SCRIPT_TIMEOUT = 20      # execute_script 타임아웃 (초)
    WEBDRIVER_IMPLICIT_WAIT = 0        # implicit wait 비활성화 (명시적 wait 사용)
    
    # 네트워크 타임아웃 (초)
    API_TIMEOUT = 5           # API 호출
    PAGE_LOAD_TIMEOUT = 30    # 페이지 로딩
    ELEMENT_WAIT_TIMEOUT = 10 # 요소 대기
    SAVE_THREAD_SHUTDOWN_TIMEOUT = 5.0  # 저장 스레드 종료 대기 시간 (초)
    DRIVER_QUIT_TIMEOUT = 2.0           # WebDriver 종료 대기 시간 (초)
    DETACHED_DRIVER_QUIT_TIMEOUT = 1.0  # 분리된 드라이버 정리 대기 시간 (초)
    DETACHED_DRIVER_CLEANUP_INTERVAL = 60000  # 분리된 드라이버 재정리 주기 (ms)
    
    # 자동 백업
    AUTO_BACKUP_INTERVAL = 300000      # 5분 (ms)
    MAX_BACKUP_COUNT = 10
    MAX_URL_HISTORY = 50               # URL 히스토리 최대 개수
    MAX_URL_LENGTH = 2048
    MAX_HISTORY_TAG_LENGTH = 100
    MAX_PRESET_NAME_LENGTH = 100
    URL_HISTORY_MAX_BYTES = 2 * 1024 * 1024
    PRESET_FILE_MAX_BYTES = 2 * 1024 * 1024
    LIVE_LIST_MAX_BYTES = 2 * 1024 * 1024
    LIVE_LIST_MAX_ROWS = 2000
    LIVE_LIST_MAX_STRING_LENGTH = 500
    RUNTIME_SESSION_DIR = str(Path(STORAGE_DIR) / "backups" / "runtime_sessions")
    RUNTIME_SEGMENT_FLUSH_THRESHOLD = 2000
    RUNTIME_ACTIVE_TAIL_ENTRIES = 1000
    RUNTIME_SEARCH_MATCH_LIMIT = 5000
    # 최근 N개 runtime archive는 유지하되, 이 일수를 넘으면 recovery 보존 대상이 아니면 삭제
    RUNTIME_ARCHIVE_KEEP_RECENT = 3
    RUNTIME_ARCHIVE_MAX_AGE_DAYS = 7
    # 장시간 세션 hydrate 안전 상한 (초과 시 편집 전 hydrate 거부)
    HYDRATE_MAX_ENTRIES = 150_000
    SESSION_RESOURCE_MAX_ENTRIES = HYDRATE_MAX_ENTRIES
    SESSION_RESOURCE_MAX_SEGMENTS = 10_000
    EXIT_ESCALATION_AFTER_SECONDS = 30.0
    EXIT_ESCALATION_REPEAT_SECONDS = 30.0

    # 성능 최적화 상수 (#4, #1)
    MAX_RENDER_ENTRIES = 500           # 한 번에 렌더링할 최대 자막 수
    MAX_WORD_DIFF_OVERLAP = 200        # get_word_diff 최대 겹침 탐색 길이
    DB_HISTORY_PAGE_SIZE = 50
    DB_SEARCH_PAGE_SIZE = 100
    SUBTITLE_DIALOG_PAGE_SIZE = 200
    
    # 경로
    LOG_DIR = str(Path(STORAGE_DIR) / "logs")
    SESSION_DIR = str(Path(STORAGE_DIR) / "sessions")
    SESSION_LOAD_MAX_BYTES = 100 * 1024 * 1024
    SESSION_RESOURCE_PER_FILE_MAX_BYTES = SESSION_LOAD_MAX_BYTES
    SESSION_RESOURCE_TOTAL_MAX_BYTES = SESSION_LOAD_MAX_BYTES
    REALTIME_DIR = str(Path(STORAGE_DIR) / "realtime_output")
    BACKUP_DIR = str(Path(STORAGE_DIR) / "backups")
    PRESET_FILE = str(Path(STORAGE_DIR) / "committee_presets.json")
    URL_HISTORY_FILE = str(Path(STORAGE_DIR) / "url_history.json")
    RECOVERY_STATE_FILE = str(Path(STORAGE_DIR) / "session_recovery.json")
    RECOVERY_CANDIDATE_MAX = 50
    # Public update-channel metadata is configurable at build time. The signing
    # private key must never be present in this repository or an executable.
    UPDATE_MANIFEST_URL = os.environ.get(
        "KACC_UPDATE_MANIFEST_URL",
        (
            "https://raw.githubusercontent.com/"
            "twbeatles/korea-assembly-cc/main/updates/latest.json"
        ),
    )
    UPDATE_PUBLIC_KEY_B64_DEFAULT = "sn3XzoeY1T6FwqMn0kQiaZWWZE72rBRFNWEjr43AE0M="
    UPDATE_PUBLIC_KEY_B64 = os.environ.get(
        "KACC_UPDATE_PUBLIC_KEY_B64",
        UPDATE_PUBLIC_KEY_B64_DEFAULT,
    )
    UPDATE_RELEASES_URL = (
        "https://github.com/twbeatles/korea-assembly-cc/releases/latest"
    )
    UPDATE_MANIFEST_MAX_BYTES = 256 * 1024
    UPDATE_ARTIFACT_MAX_BYTES = 500 * 1024 * 1024
    UPDATE_REQUEST_TIMEOUT_SECONDS = 20
    UPDATE_BACKUP_KEEP_COUNT = 2
    
    # 기본 CSS 선택자
    DEFAULT_SELECTORS = [
        "#viewSubtit .smi_word:last-child",
        "#viewSubtit .smi_word",
        "#viewSubtit .incont",
        "#viewSubtit",
        ".subtitle_area",
    ]
    
    # 기본 URL
    DEFAULT_URL = "https://assembly.webcast.go.kr/main/player.asp?xcode=10"
    
    # 상임위원회 기본 프리셋 (v16.0 기준 동작하는 xcode 값)
    # xcode: 위원회(채널) 구분 고정 값
    # xcgcd: 해당 회의의 고유 방송 ID (매 회의마다 변경)
    DEFAULT_COMMITTEE_PRESETS = {
        "본회의": "https://assembly.webcast.go.kr/main/player.asp?xcode=10",
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
        "기후에너지환경노동위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=62",
        "국토교통위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=54",
        "성평등가족위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=63",
        "예산결산특별위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=21",
        "특별위원회": "https://assembly.webcast.go.kr/main/player.asp?xcode=91",
        "청문회/공청회": "https://assembly.webcast.go.kr/main/player.asp?xcode=97",
        "기자회견": "https://assembly.webcast.go.kr/main/pressplayer.asp",
    }
    
    # 상임위원회 xcode 값 매핑 (v16.0 기준 동작하는 값)
    COMMITTEE_XCODE_MAP = {
        "본회의": 10,
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
        "기후에너지환경노동위원회": 62,
        "국토교통위원회": 54,
        "성평등가족위원회": 63,
        "예산결산특별위원회": 21,
        "특별위원회": 91,
        "청문회/공청회": 97,
    }
    
    # 특별위원회 문자열 xcode 목록 (숫자가 아닌 코드들)
    # 현재 기본값에는 검증된 문자열 xcode가 없다. 사용자가 직접 저장한
    # 기존 프리셋 JSON은 유지하되, 새 기본 프리셋에는 stale 코드를 넣지 않는다.
    SPECIAL_COMMITTEE_XCODES = {}

    # 사이트 live_list가 바꾼 이전 xcode. 기본 프리셋에는 넣지 않고
    # 사용자 저장 URL/구 북마크 식별용으로만 유지한다.
    LEGACY_COMMITTEE_XCODES = {
        "99": "청문회/공청회",  # 2026-09 live_list 기준 97
        "38": "재정경제기획위원회",  # 구 기획재정/기재위
        "34": "기후에너지환경노동위원회",  # 구 환경노동위원회
        "36": "성평등가족위원회",  # 구 여성가족위원회
        "ED": "특별위원회",
    }

    # 정보위원회 xcode/생중계 여부는 이번 배치에서 외부 검증하지 않는다.
    # 사용자가 직접 확인한 URL은 사용자 프리셋/직접 입력으로 사용할 수 있다.
    
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
        "환노위": "기후에너지환경노동위원회",  # 구 환경노동위원회
        "기후노동위": "기후에너지환경노동위원회",  # 사이트 약칭
        "기후환경노동위원회": "기후에너지환경노동위원회",  # 구 공식명
        "국토위": "국토교통위원회",
        "여가위": "성평등가족위원회",  # 구 여성가족위원회 → 성평등가족위원회
        "성평등가족위": "성평등가족위원회",  # 사이트 내 타이틀 표기
        "예결위": "예산결산특별위원회",
        "특별위": "특별위원회",
        "청문회": "청문회/공청회",
        "공청회": "청문회/공청회",
    }
    
    # 폰트 설정
    DEFAULT_FONT_SIZE = 14
    MIN_FONT_SIZE = 10
    MAX_FONT_SIZE = 24
    
    # 연결 상태 모니터링 (#30)
    CONNECTION_CHECK_INTERVAL = 5000   # 연결 상태 체크 간격 (ms)
    DRIVER_HEALTH_CHECK_INTERVAL = 5.0
    DRIVER_HEALTH_FAILURE_THRESHOLD = 2

    # 스마트 스크롤
    SCROLL_BOTTOM_THRESHOLD = 50       # 맨 아래 감지 임계값 (픽셀)

    # 생중계 갱신 감지 (초)
    LIVE_BROADCAST_REFRESH_INTERVAL = 30
    LIVE_LIST_REQUEST_TIMEOUT_MS = 10000

    # 자동 재연결 (#31)
    AUTO_RECONNECT_ENABLED = True
    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_BASE_DELAY = 2           # 초기 대기 시간 (초)
    RECONNECT_MAX_DELAY = 60           # 최대 대기 시간 (초)
    SUBTITLE_RESET_GRACE_MS = 1000

    # Chrome 장기 실행 안정화
    CHROME_PAGE_LOAD_STRATEGY = "eager"
    CHROME_WINDOW_SIZE = "1280,720"
    CHROME_STABILITY_ARGS = (
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-dev-shm-usage",
        "--disable-session-crashed-bubble",
        "--disable-features=CalculateNativeWinOcclusion",
        "--no-first-run",
        "--no-default-browser-check",
    )

    # 중지 시 브라우저 창 유지 기본값 (QSettings keep_browser_on_stop으로 덮어씀)
    KEEP_BROWSER_ON_STOP = False

    # 자막 병합 기준 (현재 운영 동작 유지: 5초/300자)
    ENTRY_MERGE_MAX_CHARS = 300
    ENTRY_MERGE_MAX_GAP = 5  # 초

    # 스트리밍 자막 최대 길이 (초과 시 강제 분할하여 새 타임스탬프 생성)
    STREAM_SUBTITLE_MAX_LENGTH = 300

    # 글로벌 compact 히스토리 메모리 상한 (공백 제거 기준 글자 수)
    CONFIRMED_COMPACT_MAX_LEN = 50000

    # preview / live-row delta 추출 시 비교에 사용할 최근 히스토리 윈도우 길이
    # CONFIRMED_COMPACT_MAX_LEN 의 작은 슬라이스로 동작하며, 두 값은 함께 튜닝한다.
    RECENT_HISTORY_COMPACT_LENGTH = 5000

    # 자동 줄넘김 정리 기본값
    AUTO_CLEAN_NEWLINES_DEFAULT = True

    # 세션 병합 중복 제거 시간 버킷(초)
    MERGE_DEDUP_TIME_BUCKET_SECONDS = 30

    
    # 자동 파일명 생성 (#28)
    DEFAULT_FILENAME_TEMPLATE = "{date}_{committee}_{time}"
    FILENAME_DATE_FORMAT = "%Y%m%d"
    FILENAME_TIME_FORMAT = "%H%M%S"
    
    # 데이터베이스 (#26)
    DATABASE_PATH = str(Path(STORAGE_DIR) / "subtitle_history.db")
    DB_SYNC_TASK_TIMEOUT_SECONDS = 15.0
    # 로그 보존·민감 정책 (프라이버시: 자막 전문은 기본 로그에 남기지 않음)
    LOG_RETENTION_DAYS = 14
    # 파일 로그 기본 레벨. 환경변수 SUBTITLE_LOG_LEVEL=DEBUG 로 상향 가능
    LOG_FILE_LEVEL = "INFO"
    LOG_CONSOLE_LEVEL = "INFO"
    # True면 로그 헬퍼가 긴 자막 본문을 잘라 기록 (운영 기본)
    LOG_REDACT_LONG_TEXT = True
    LOG_REDACT_MAX_CHARS = 80
    
    # 성능 최적화: 사전 컴파일된 정규식 패턴
    RE_YEAR = re.compile(r'\b\d{4}년\b')              # 년도 제거용
    RE_ZERO_WIDTH = re.compile(r'[\u200b\u200c\u200d\ufeff]')  # Zero-width 문자
    RE_MULTI_SPACE = re.compile(r'\s+')              # 연속 공백 정규화



# ============================================================
# 라이브 방송 선택 다이얼로그
# ============================================================
