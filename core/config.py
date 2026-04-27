# -*- coding: utf-8 -*-

import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


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


@dataclass(frozen=True)
class StorageResolution:
    install_dir: Path
    storage_dir: Path
    storage_mode: str
    portable_flag_path: Path
    settings_ini_path: Path | None


def _resolve_install_dir(
    *,
    frozen: bool | None = None,
    executable: str | None = None,
    module_file: str | None = None,
) -> Path:
    """리소스/설치 기준 디렉터리를 계산한다."""
    is_frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    if is_frozen:
        executable_path = executable or getattr(sys, "executable", "")
        return Path(executable_path).resolve().parent
    module_path = module_file or __file__
    return Path(module_path).resolve().parent.parent


def _resolve_local_appdata_dir(
    *,
    localappdata: str | None = None,
    home: str | Path | None = None,
) -> Path:
    env_value = localappdata if localappdata is not None else os.environ.get("LOCALAPPDATA")
    if env_value:
        return Path(env_value).resolve() / "AssemblySubtitle" / "Extractor"
    home_path = Path.home() if home is None else Path(home)
    return home_path.resolve() / "AppData" / "Local" / "AssemblySubtitle" / "Extractor"


def resolve_storage_resolution(
    *,
    frozen: bool | None = None,
    executable: str | None = None,
    module_file: str | None = None,
    portable_flag_exists: bool | None = None,
    localappdata: str | None = None,
    home: str | Path | None = None,
) -> StorageResolution:
    """설치 경로와 저장 경로를 분리해 계산한다."""
    install_dir = _resolve_install_dir(
        frozen=frozen,
        executable=executable,
        module_file=module_file,
    )
    is_frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    portable_flag_path = install_dir / "portable.flag"
    flag_exists = (
        portable_flag_path.exists()
        if portable_flag_exists is None
        else bool(portable_flag_exists)
    )

    if not is_frozen:
        storage_dir = install_dir
        storage_mode = "development"
    elif flag_exists:
        storage_dir = install_dir
        storage_mode = "portable"
    else:
        storage_dir = _resolve_local_appdata_dir(
            localappdata=localappdata,
            home=home,
        )
        storage_mode = "localappdata"

    settings_ini_path = storage_dir / "settings.ini" if storage_mode == "portable" else None
    return StorageResolution(
        install_dir=install_dir,
        storage_dir=storage_dir.resolve(),
        storage_mode=storage_mode,
        portable_flag_path=portable_flag_path.resolve(),
        settings_ini_path=settings_ini_path.resolve() if settings_ini_path else None,
    )


def build_storage_preflight_targets(storage_dir: str | Path, settings_ini_path: str | Path | None = None) -> list[Path]:
    root = Path(storage_dir).resolve()
    targets = [
        root,
        root / "logs",
        root / "sessions",
        root / "realtime_output",
        root / "backups",
        root / "backups" / "runtime_sessions",
    ]
    if settings_ini_path:
        targets.append(Path(settings_ini_path).resolve().parent)
    return targets


def _probe_writable_file_surface(target_path: str | Path, *, sample_text: str) -> None:
    path = Path(target_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.write_text(sample_text, encoding="utf-8")
        path.unlink(missing_ok=True)
        return

    with path.open("r+b") as handle:
        original_size = path.stat().st_size
        if original_size > 0:
            handle.seek(0)
            first_byte = handle.read(1)
            handle.seek(0)
            handle.write(first_byte)
            handle.flush()
            os.fsync(handle.fileno())
            return

        handle.write(b" ")
        handle.truncate(0)
        handle.flush()
        os.fsync(handle.fileno())


def _probe_sqlite_database_surface(database_path: str | Path) -> None:
    path = Path(database_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    probe_table = f"__storage_preflight_{uuid4().hex}"
    transaction_started = False
    try:
        journal_mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        journal_value = str(journal_mode[0] if journal_mode else "").strip().lower()
        if journal_value != "wal":
            raise RuntimeError(f"journal_mode=WAL 적용 실패 (actual={journal_value or 'unknown'})")

        conn.execute("BEGIN IMMEDIATE")
        transaction_started = True
        conn.execute(f'CREATE TABLE "{probe_table}" (id INTEGER PRIMARY KEY, note TEXT)')
        conn.execute(
            f'INSERT INTO "{probe_table}" (note) VALUES (?)',
            ("storage-preflight",),
        )
        conn.execute("ROLLBACK")
        transaction_started = False
    finally:
        if transaction_started:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        conn.close()


def run_storage_preflight(
    storage_dir: str | Path,
    *,
    settings_ini_path: str | Path | None = None,
    database_path: str | Path | None = None,
    preset_file: str | Path | None = None,
    url_history_file: str | Path | None = None,
    recovery_state_file: str | Path | None = None,
) -> tuple[bool, str]:
    """필수 저장소 경로 생성/쓰기 가능 여부를 검증한다."""
    failing_path = ""
    root = Path(storage_dir).resolve()
    preset_path = Path(preset_file).resolve() if preset_file else root / "committee_presets.json"
    url_history_path = (
        Path(url_history_file).resolve() if url_history_file else root / "url_history.json"
    )
    recovery_path = (
        Path(recovery_state_file).resolve()
        if recovery_state_file
        else root / "session_recovery.json"
    )
    settings_path = Path(settings_ini_path).resolve() if settings_ini_path else None
    db_path = Path(database_path).resolve() if database_path else root / "subtitle_history.db"
    try:
        for target_dir in build_storage_preflight_targets(storage_dir, settings_ini_path):
            failing_path = str(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            probe_path = target_dir / ".storage_probe"
            probe_path.write_text("ok", encoding="utf-8")
            probe_path.unlink(missing_ok=True)
        file_surfaces = [
            (preset_path, '{"presets": {}, "custom": {}}\n'),
            (url_history_path, "{}\n"),
            (recovery_path, "{}\n"),
        ]
        if settings_path is not None:
            file_surfaces.append((settings_path, "[General]\n"))
        for path, sample_text in file_surfaces:
            failing_path = str(path)
            _probe_writable_file_surface(path, sample_text=sample_text)
        failing_path = str(db_path)
        _probe_sqlite_database_surface(db_path)
        return True, ""
    except Exception as exc:
        return False, f"{failing_path}\n{exc}"


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
        return run_storage_preflight(
            Config.STORAGE_DIR,
            settings_ini_path=Config.SETTINGS_INI_PATH or None,
            database_path=Config.DATABASE_PATH,
            preset_file=Config.PRESET_FILE,
            url_history_file=Config.URL_HISTORY_FILE,
            recovery_state_file=Config.RECOVERY_STATE_FILE,
        )
    
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
    RUNTIME_SESSION_DIR = str(Path(STORAGE_DIR) / "backups" / "runtime_sessions")
    RUNTIME_SEGMENT_FLUSH_THRESHOLD = 2000
    RUNTIME_ACTIVE_TAIL_ENTRIES = 1000
    RUNTIME_SEARCH_MATCH_LIMIT = 5000
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
    REALTIME_DIR = str(Path(STORAGE_DIR) / "realtime_output")
    BACKUP_DIR = str(Path(STORAGE_DIR) / "backups")
    PRESET_FILE = str(Path(STORAGE_DIR) / "committee_presets.json")
    URL_HISTORY_FILE = str(Path(STORAGE_DIR) / "url_history.json")
    RECOVERY_STATE_FILE = str(Path(STORAGE_DIR) / "session_recovery.json")
    
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
    LOG_RETENTION_DAYS = 14
    
    # 성능 최적화: 사전 컴파일된 정규식 패턴
    RE_YEAR = re.compile(r'\b\d{4}년\b')              # 년도 제거용
    RE_ZERO_WIDTH = re.compile(r'[\u200b\u200c\u200d\ufeff]')  # Zero-width 문자
    RE_MULTI_SPACE = re.compile(r'\s+')              # 연속 공백 정규화



# ============================================================
# 라이브 방송 선택 다이얼로그
# ============================================================

