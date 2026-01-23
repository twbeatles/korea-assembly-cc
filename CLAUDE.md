# AI Context: 국회 의사중계 자막 추출기

이 문서는 AI 에이전트(Claude)가 `국회 의사중계 자막 추출기` 프로젝트를 이해하고 코드를 수정할 때 참고해야 할 핵심 정보를 담고 있습니다.

## 1. 프로젝트 개요

- **목표**: 국회 의사중계 웹사이트에서 AI 자막을 실시간으로 추출하고 저장
- **버전**: v16.9
- **핵심 가치**: 
  - 실시간 자막 캡처 (2초 확정 딜레이)
  - 안정적인 멀티스레딩 아키텍처
  - 모던 UI/UX (다크/라이트 테마)
  - 다양한 출력 형식 지원
  - **SQLite 데이터베이스 기반 세션 관리**

## 2. 기술 스택

| 구성요소 | 기술 |
|---------|------|
| **언어** | Python 3.9+ |
| **GUI 프레임워크** | PyQt6 (Qt6) |
| **웹 자동화** | Selenium + Chrome WebDriver |
| **동시성** | threading, queue.Queue |
| **설정 저장** | QSettings, JSON |
| **데이터베이스** | SQLite3 (세션/자막 히스토리) |
| **문서 출력** | python-docx (DOCX), pywin32 (HWP), 내장 (TXT/SRT/VTT/RTF) |
| **로깅** | logging (파일 + 콘솔) |

## 3. 아키텍처 구조

```
┌─────────────────────────────────────────────────────────────┐
│                       MainWindow (Qt6)                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                  UI Thread (Main)                     │   │
│  │  - 사용자 입력 처리                                    │   │
│  │  - 자막 렌더링 (QTextEdit)                            │   │
│  │  - 통계 업데이트 (QTimer)                             │   │
│  │  - 연결 상태 모니터링 (#30)                           │   │
│  │  - 토스트 알림 (ToastWidget)                          │   │
│  └──────────────────────────────────────────────────────┘   │
│                            ▲                                 │
│                     ┌──────┴──────┐                         │
│                     │   Queue     │   message_queue         │
│                     └──────┬──────┘                         │
│                            ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Worker Thread (Background)               │   │
│  │  - Selenium WebDriver 구동                            │   │
│  │  - 자막 요소 모니터링 (0.2초 간격)                     │   │
│  │  - 자동 재연결 (지수 백오프, #31)                     │   │
│  │  - stop_event 기반 안전 종료                          │   │
│  └──────────────────────────────────────────────────────┘   │
│                            │                                 │
│  ┌──────────────────────────▼───────────────────────────┐   │
│  │              DatabaseManager (database.py)            │   │
│  │  - SQLite 세션/자막 저장                              │   │
│  │  - 통합 검색 기능                                     │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 4. 핵심 규칙

### 4.1 스레드 안전성
1. **Queue 통신**: UI 스레드와 Worker 스레드 간 통신은 반드시 `queue.Queue`를 통해서만 수행
2. **stop_event**: 스레드 종료는 `threading.Event()` 사용 (빠른 응답성 보장)
3. **타이머 기반 업데이트**: UI 업데이트는 `QTimer`를 통해 주기적으로 Queue 폴링
4. **subtitle_lock**: 자막 리스트 접근 시 `threading.Lock()` 사용 (모든 저장/편집/삭제/통계 메서드)
5. **스마트 스크롤**: 사용자가 스크롤하면 자동 스크롤 일시 중지 및 위치 유지

### 4.2 자막 처리 흐름
```
Raw Text → preview 메시지 → 2초 대기 → finalize → SubtitleEntry 저장
                              ↓
                     변경 감지 시 타이머 리셋
```
- 분 경계에서는 즉시 확정, 같은 분은 길이/간격 제한으로 병합

### 4.3 예외 처리
- 파일 I/O는 모두 `try-except`로 보호
- WebDriver 연결 실패 시 **지수 백오프로 자동 재연결** (최대 5회)
- 자막 요소 없을 경우 여러 선택자를 순차 시도

### 4.4 설정 영속성
- `QSettings`: 창 위치, 테마, 폰트 크기 등 사용자 설정
- `url_history.json`: URL 히스토리 및 태그
- `committee_presets.json`: 상임위원회 프리셋 (선택적)
- `subtitle_history.db`: SQLite 데이터베이스 (세션/자막 히스토리)

## 5. 주요 클래스 및 파일 구조

### 5.1 파일 구조
```
assemblyccv3/
  국회의사중계 자막.py       # 메인 엔트리포인트
  core/                         # 공통 로직/설정
    config.py
    logging_utils.py
    models.py
  ui/                           # UI 구성요소
    dialogs.py
    themes.py
    widgets.py
    main_window.py
  database.py               # SQLite DB 관리 (v16.6)
  subtitle_extractor.spec   # PyInstaller 빌드 설정
  README.md                 # 문서
  CLAUDE.md                 # AI 컨텍스트
  GEMINI.md                 # AI 컨텍스트
  subtitle_history.db       # SQLite DB (자동 생성)
  url_history.json          # URL 히스토리 (자동 생성)
  committee_presets.json    # 상임위 프리셋 (자동 생성)
  logs/
    subtitle_YYYYMMDD.log
  sessions/
  backups/
  realtime_output/
```

### 5.2 주요 클래스
| 클래스 | 파일 | 역할 |
|--------|------|------|
| `Config` | core/config.py | 상수 및 기본 설정 값 |
| `ToastWidget` | ui/widgets.py | 비차단 토스트 알림 UI |
| `SubtitleEntry` | core/models.py | 자막 데이터 모델 (타임스탬프 포함) |
| `MainWindow` | ui/main_window.py | 메인 윈도우 및 모든 로직 통합 |
| `DatabaseManager` | database.py | SQLite CRUD 작업 (#26) |

### 5.3 핵심 메서드
| 메서드 | 설명 |
|--------|------|
| `_start()` / `_stop()` | 추출 시작/중지 |
| `_extraction_worker()` | 백그라운드 스레드 메인 루프 |
| `_activate_subtitle()` | AI 자막 레이어 활성화 |
| `_process_message_queue()` | Queue 메시지 처리 (100ms 주기) |
| `_check_finalize()` | 2초 경과 후 자막 확정 |
| `_render_subtitles()` | 자막 화면 렌더링 + 키워드 하이라이트 |
| `_update_connection_status()` | **연결 상태 UI 업데이트 (#30)** |
| `_generate_smart_filename()` | **자동 파일명 생성 (#28)** |
| `_show_merge_dialog()` | **자막 병합 다이얼로그 (#20)** |
| `_show_db_history()` | **세션 히스토리 조회 (#26)** |
| `_show_db_search()` | **자막 통합 검색 (#26)** |

## 6. v16.6에서 추가된 기능

### 6.1 연결 상태 모니터링 (#30)
- 상태바에 연결 상태 표시: 🟢 연결됨, 🔴 끊김, 🟡 재연결 중
- 툴팁에 응답 시간(latency) 표시
- 5초마다 연결 상태 업데이트

### 6.2 자동 감지 및 재연결 (#31)
- 지수 백오프 알고리즘 (최대 5회 재연결)
- **스마트 `xcgcd` 감지**: `xcode`만 입력해도 `live_list.asp` API 및 페이지 분석을 통해 생중계 주소 자동 확보
- **리다이렉트 대응**: 메인 페이지로 이동 시 해당 위원회의 '생중계' 버튼 자동 클릭
- **생중계 목록 선택 UI**: '📡 생중계 목록' 버튼을 통해 실시간 방송 목록 확인 및 직접 선택 (`LiveBroadcastDialog`)

### 6.3 자동 파일명 생성 (#28)
- 형식: `{날짜}_{위원회명}_{시간}.확장자`
- 예: `20260122_법제사법위원회_134500.txt`
- TXT/SRT/VTT/DOCX/RTF 저장에 적용 (HWP는 기본 파일명 사용)

### 6.4 SQLite 데이터베이스 (#26)
- `database.py` 모듈의 `DatabaseManager` 클래스
- 세션 저장 시 자동으로 DB에도 저장
- 메뉴: 데이터베이스 → 세션 히스토리 / 자막 검색 / 전체 통계

### 6.5 자막 병합 (#20)
- 메뉴: 도구 → 자막 병합 (Ctrl+Shift+M)
- 여러 세션 파일을 하나로 병합
- 옵션: 중복 제거, 시간순 정렬

### 6.6 상임위원회 xcode 최신화 (v16.8)
- 재정경제기획위원회(65), 성평등가족위원회(63) 등 최신화
- 정무위원회(26) 신규 추가 및 약칭 매핑 보강

## 7. 저장 형식

| 형식 | 파일 확장자 | 특징 |
|------|-------------|------|
| TXT | `.txt` | 타임스탬프 + 텍스트 |
| SRT | `.srt` | 영상 자막 표준 형식 |
| VTT | `.vtt` | WebVTT 형식 |
| DOCX | `.docx` | Word 문서 (python-docx 필요) |
| HWP | `.hwp` | 한글 문서 (pywin32/한컴오피스 필요) |
| RTF | `.rtf` | 리치 텍스트 형식 |
| JSON (세션) | `.json` | 전체 세션 복원용 |
| SQLite | `.db` | 데이터베이스 히스토리 |

## 8. 개발 관련 주의사항

### 8.1 의존성 설치
```bash
pip install PyQt6 selenium python-docx
pip install pywin32  # HWP 저장
```

### 8.2 Chrome WebDriver
- Selenium 4.x는 자동으로 WebDriver를 관리합니다
- 별도 chromedriver 설치 불필요

### 8.3 HiDPI 지원
```python
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
```

### 8.4 헤드리스 모드
- `--headless=new` 옵션으로 백그라운드 실행 지원
- `--remote-debugging-port=0`으로 동적 포트 할당 (다중 인스턴스 충돌 방지)

## 9. 성능 최적화 (v16.8)

### 9.1 정규식 캐싱
- `Config.RE_YEAR`, `RE_ZERO_WIDTH`, `RE_MULTI_SPACE`: 사전 컴파일된 패턴
- `_clean_text()`, `_extraction_worker()`에서 사용

### 9.2 QTextCharFormat 캐싱
- `_highlight_fmt`, `_normal_fmt`: 키워드 하이라이트용
- `_timestamp_fmt`, `_preview_fmt`: 렌더링용

### 9.3 통계 캐싱
- `_cached_total_chars`, `_cached_total_words`: 누적 통계
- `SubtitleEntry.char_count`, `word_count`: 캐시 프로퍼티
- `_update_stats()`에서 캐시된 값 사용

## 10. 향후 개선 가능 영역

1. **모듈 분리**: core/, ui/ 분리 완료 (필요 시 utils/ 추가)
2. **테스트 코드**: pytest 기반 단위 테스트 추가
3. **타입 힌트 강화**: 모든 함수에 타입 어노테이션 추가
4. **다국어 지원**: i18n 프레임워크 도입
5. ~~설정 UI~~: 메뉴에서 대부분 설정 가능
6. **PyInstaller 패키징**: 독립 실행 파일 생성

## 11. 자막 수집 알고리즘 (핵심)

현재 잘 작동하는 자막 수집 알고리즘의 핵심 로직:

```python
# 1. Worker 스레드에서 0.2초 간격으로 자막 요소 폴링
text = driver.find_element(By.CSS_SELECTOR, selector).text.strip()

# 2. 변경 감지 시 preview 메시지 전송
if text and text != self.last_subtitle:
    self.message_queue.put(("preview", text))

# 3. UI 스레드에서 2초 확정 타이머 관리
elapsed = time.time() - self.last_update_time
if elapsed >= 2.0:  # 2초 동안 변경 없음
    self._finalize_subtitle(self.last_subtitle)

# 4. 겹침 감지 및 이어붙이기
if text.startswith(last_text):
    new_part = text[len(last_text):].strip()
    self.subtitles[-1].text = text  # 기존 자막 업데이트

# 5. 연결 상태 모니터링 (#30)
self.message_queue.put(("connection_status", {"status": "connected", "latency": latency}))

# 6. 자동 재연결 (#31)
delay = min(Config.RECONNECT_BASE_DELAY * (2 ** (attempts - 1)), Config.RECONNECT_MAX_DELAY)
```

---

*이 문서는 AI 에이전트의 코드 이해를 돕기 위한 것입니다. 새 세션에서도 이 파일을 참조하면 프로젝트 맥락을 빠르게 파악할 수 있습니다.*
