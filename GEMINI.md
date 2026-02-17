# AI Context: 국회 의사중계 자막 추출기

이 문서는 AI 에이전트(Gemini)가 `국회 의사중계 자막 추출기` 프로젝트를 이해하고 코드를 수정할 때 참고해야 할 핵심 정보를 담고 있습니다.

## 1. 프로젝트 개요

- **목표**: 국회 의사중계 웹사이트에서 AI 자막을 실시간으로 추출
- **버전**: v16.12
- **핵심 가치**: 실시간 자막 캡처, 안정적 멀티스레딩, 모던 UI, SQLite 데이터베이스

## 2. 기술 스택

- **언어**: Python 3.9+
- **GUI**: PyQt6 (Qt)
- **웹 자동화**: Selenium + Chrome WebDriver
- **동시성**: threading, queue.Queue
- **설정**: QSettings, JSON
- **데이터베이스**: SQLite3 (database.py)
- **문서 출력**: python-docx (DOCX), pywin32 (HWP), 내장 (TXT/SRT/VTT/RTF)
- **로깅**: logging (파일 + 콘솔)

## 3. 아키텍처 요약

```
┌──────────────────────────────────────────────┐
│           MainWindow (UI Thread)             │
│  - 사용자 입력, 자막 렌더링, 통계 업데이트      │
│  - 연결 상태 모니터링 (🟢/🔴/🟡)              │
└───────────────────────┬──────────────────────┘
                        │ message_queue (Queue)
┌───────────────────────▼──────────────────────┐
│         Worker Thread (Background)           │
│  - Selenium 구동                              │
│  - MutationObserver 우선 + 폴링 fallback     │
│  - 자동 재연결 (지수 백오프)                   │
│  - stop_event 기반 안전 종료                  │
└───────────────────────┬──────────────────────┘
                        │
┌───────────────────────▼──────────────────────┐
│         DatabaseManager (database.py)        │
│  - SQLite 세션/자막 저장 및 검색               │
└──────────────────────────────────────────────┘
```

## 4. 핵심 규칙

### 4.1 UI/Logic 분리
- UI 스레드와 Worker 스레드 간 통신은 `queue.Queue` 사용
- 직접 UI 객체 수정 금지 (스레드 안전하지 않음)
- **subtitle_lock**: 자막 리스트 접근 시 `threading.Lock()` 필수
- 스마트 스크롤: 사용자가 스크롤하면 자동 스크롤 일시 중지 및 위치 유지

### 4.2 자막 처리 흐름
1. Worker: MutationObserver 우선, 폴링 fallback → compact 기준 중복 전송 억제 후 `preview` 전송
2. Worker: 선택자 우선순위(`.smi_word:last-child` 우선) + 기본 문서/iframe 순회로 자막 요소 탐색
3. Worker: 타겟 미탐색 시 `allow_poll_fallback` 기반 JS 폴링 브리지 활성화
4. UI: `_prepare_preview_raw`에서 정규화/게이팅/재동기화 처리 (desync 시 `_soft_resync`)
5. Core: `_process_raw_text`(GlobalHistory + Suffix, `rfind` 기반)로 새 부분 추출
6. 후단 정제: `get_word_diff` + recent compact tail 체크로 대량 반복 누적 2차 방지
7. 중지 시: `_drain_pending_previews`로 큐를 소진하고 강제 플러시로 누락 방지
8. 동일 자막 유지 시: 마지막 엔트리 `end_time` 주기 갱신

### 4.3 예외 처리
- 파일 I/O: `try-except` 필수
- WebDriver 연결: 지수 백오프로 최대 5회 재시도 (#31)
- 자막 요소: 여러 CSS 선택자 순차 시도

## 5. 주요 클래스

| 클래스 | 파일 | 역할 |
|--------|------|------|
| `Config` | core/config.py | 상수 및 기본 설정 |
| `ToastWidget` | ui/widgets.py | 비차단 토스트 알림 |
| `SubtitleEntry` | core/models.py | 자막 데이터 모델 |
| `MainWindow` | ui/main_window.py | 메인 윈도우 + 통합 로직 |
| `DatabaseManager` | database.py | SQLite CRUD (#26) |

## 6. 핵심 메서드

| 메서드 | 설명 |
|--------|------|
| `_start()` / `_stop()` | 추출 시작/중지 |
| `_extraction_worker()` | 백그라운드 스레드 메인 루프 (MutationObserver 하이브리드) |
| `_inject_mutation_observer()` | JS MutationObserver 페이지 주입 |
| `_inject_mutation_observer_here()` | 현재 문맥(frame) Observer/폴링 브리지 주입 |
| `_collect_observer_changes()` | Observer 버퍼에서 변경 텍스트 수집 |
| `_build_subtitle_selector_candidates()` | 선택자 후보 생성 및 우선순위 정렬 |
| `_read_subtitle_text_by_selectors()` | 선택자 + 프레임 경로 순회 기반 자막 읽기 |
| `_activate_subtitle()` | AI 자막 레이어 활성화 |
| `_process_message_queue()` | Queue 폴링 (100ms) |
| `_prepare_preview_raw()` | preview 입력 정규화/게이트/재동기화 |
| `_soft_resync()` | 소프트 리셋 (최근 자막 기반 히스토리 복원) |
| `_extract_stream_delta()` | 직전 raw 대비 증분 추출 fallback |
| `_slice_incremental_part()` | anchor/suffix 기반 증분 추출 fallback |
| `_process_raw_text()` | 스트리밍 Diff/Append 처리 (rfind 기반) |
| `_extract_new_part()` | suffix 기반 새 부분 추출 (rfind) |
| `_join_stream_text()` | 웹 형태에 맞춘 공백/문장부호 보존 결합 |
| `_finalize_subtitle()` | 종료 시 마지막 버퍼 확정 |
| `_drain_pending_previews()` | 종료 직전 preview 큐 소진 |
| `_render_subtitles()` | 자막 렌더링 + 하이라이트 |
| `_save_in_background()` | 비동기 파일 저장 헬퍼 |
| `_update_connection_status()` | 연결 상태 UI 업데이트 (#30) |
| `_generate_smart_filename()` | 자동 파일명 생성 (#28) |
| `_show_merge_dialog()` | 자막 병합 다이얼로그 (#20) |
| `_show_db_history()` | DB 세션 히스토리 (#26) |

## 7. 파일 구조

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
  test_core_algorithm.py    # 코어 알고리즘 단위 테스트
  test_reflow.py            # Reflow 테스트
  README.md                 # 문서
  CLAUDE.md                 # AI 컨텍스트
  GEMINI.md                 # AI 컨텍스트
  PIPELINE_LOCK.md          # 파이프라인 고정 문서
  ALGORITHM_ANALYSIS.md     # 알고리즘 분석 문서
  subtitle_history.db       # SQLite DB (자동 생성)
  url_history.json          # URL 히스토리 (자동 생성)
  committee_presets.json    # 상임위 프리셋 (자동 생성)
  logs/
    subtitle_YYYYMMDD.log
  sessions/
  backups/
  realtime_output/
```

## 8. 의존성

```bash
pip install PyQt6 selenium python-docx
pip install pywin32  # HWP 저장
```

## 9. v16.6 신규 기능

### #30 연결 상태 모니터링
- 상태바에 🟢/🔴/🟡 아이콘 표시
- 툴팁에 응답 시간 표시

### #31 자동 재연결
- 지수 백오프 알고리즘 (2→4→8→16→32초)
- 최대 5회 재시도, 토스트 알림

### #28 자동 파일명 생성
- 형식: `20260122_법제사법위원회_134500.txt`
- TXT/SRT/VTT/DOCX/RTF 저장에 자동 적용 (HWP는 기본 파일명 사용)

### #26 SQLite 데이터베이스
- `database.py` 모듈
- 메뉴: 데이터베이스 → 세션 히스토리/자막 검색/통계

### #20 자막 병합
- 메뉴: 도구 → 자막 병합 (Ctrl+Shift+M)
- 중복 제거, 시간순 정렬 옵션

## 9.1 v16.7 신규 기능

### URL 감지 로직 개선
- `_detect_live_broadcast`: API(`live_list.asp`)를 통해 `xcode`에 매칭되는 `xcgcd` 자동 탐색
- 메인 페이지 리다이렉트 시 `xcode`에 해당하는 '생중계' 버튼 자동 클릭 및 복구 로직 추가
- **생중계 목록 선택 UI 추가**: '📡 생중계 목록' 버튼을 통해 현재 진행 중인 방송을 확인하고 직접 선택하여 접속 가능 (`LiveBroadcastDialog`)


### 특별위원회 프리셋 추가
- `Config.DEFAULT_COMMITTEE_PRESETS`: 국정감사, 국정조사, 국회정보나침반 URL
- `Config.SPECIAL_COMMITTEE_XCODES`: 문자열 xcode 매핑 (IO, NA, PP)

### 사용자 안내 개선
- `subtitle_not_found` 메시지 상세화: 가능한 원인, 해결 방법, URL 예시 포함

## 9.2 v16.8 신규 기능

### 상임위원회 xcode 최신화 (2026.01.23)
국회 의사중계 시스템의 최신 변경 사항을 반영:

| 변경 전 | 변경 후 | xcode |
|---------|---------|-------|
| 기획재정위원회 | 재정경제기획위원회 | 65 (이전 38) |
| 환경노동위원회 | 기후환경노동위원회 | 62 (동일) |
| 여성가족위원회 | 성평등가족위원회 | 63 (이전 36) |
| - | 정무위원회 (신규 추가) | 26 |

- `Config.DEFAULT_COMMITTEE_PRESETS`: 위원회 명칭 및 xcode 업데이트
- `Config.COMMITTEE_XCODE_MAP`: xcode 매핑 정보 최신화
- `Config.COMMITTEE_ABBREVIATIONS`: 약칭 매핑 업데이트

### 성능 최적화 (v16.8)
- 정규식 캐싱: `Config.RE_YEAR`, `RE_ZERO_WIDTH`, `RE_MULTI_SPACE`
- QTextCharFormat 캐싱: `_highlight_fmt`, `_normal_fmt`, `_timestamp_fmt`, `_preview_fmt`
- 통계 캐시: `_cached_total_chars`, `_cached_total_words`

## 9.3 v16.9 신규 기능

### 🛡️ 데이터 안정성
- **자동 백업 백그라운드 처리**: UI 프리즈 없이 파일 I/O 수행
- **중복 백업 방지**: 백업 중복 실행 방지 락 적용
- **세션 로드 복구**: JSON 파일 손상 시 `backups` 폴더 열기 안내 제공

### 🔒 안정성 및 성능
- **스레드 안전성 전면 강화**: 자막 `subtitles` 리스트 접근 시 전역에서 `subtitle_lock` 사용, 경쟁 조건 원천 차단
- **DB 최적화**: `database.py` 개선 (연결 캐싱, Bulk Insert, 트랜잭션 처리 최적화)
- **자막 렌더링 가속**: 전체 텍스트 재작성 대신 `_render_subtitles`에서 증분 렌더링(새 자막만 append) 도입

### 🎨 UI/UX 개선
- **키워드 입력 최적화**: 디바운싱(Debouncing) 적용으로 키워드 입력 시 렌더링 렉 제거
- **병합 옵션 세분화**: 병합 시 현재 세션의 자막을 보존할지 덮어쓸지 선택 가능
- **HWP 저장 개선**: 저장 실패 시 RTF/DOCX 등 대체 포맷 제안 다이얼로그 표시

## 9.4 v16.10 안정화 및 최적화

### 🔒 안정성 대폭 강화
- **자동 재연결 메커니즘 개선**: WebDriver 연결 끊김 시 지수 백오프로 재연결 시도 및 상태 UI 피드백 (#4, #5)
- **실시간 저장 오류 감지**: 파일 저장 실패 3회 연속 발생 시 사용자에게 토스트 경고 표시 (#3)
- **종료 처리 완벽화**: `closeEvent` 및 `_stop` 시 WebDriver, DB 연결, 스레드, 파일 핸들러 완전 정리 (좀비 프로세스 방지) (#2)

### 🚀 성능 및 리소스 최적화
- **대량 자막 렌더링 최적화**: `MAX_RENDER_ENTRIES`(500개) 도입으로 장시간 실행 시 UI 프리즈 제거 (#4)
- **텍스트 비교 알고리즘 개선**: `get_word_diff`의 비교 범위 제한(`MAX_WORD_DIFF_OVERLAP`)으로 CPU 스파이크 방지 (#1)
- **DB 검색 Fallback**: FTS 검색 실패 시 `LIKE` 쿼리로 자동 전환하여 특수문자 검색 지원 (#6)

### ✨ 기타 개선
- **인코딩 호환성**: 실시간 저장 파일에 `utf-8-sig`(BOM) 적용으로 Windows 메모장 호환성 확보 (#12)
- **스레드 안전성**: `_finalize_subtitle` 등 핵심 로직에 락(Lock) 적용으로 경쟁 조건 완전 차단 (#1)
- **설정 상수화**: 렌더링 및 알고리즘 임계값을 `Config` 클래스로 중앙 관리

## 9.5 v16.12 코어 알고리즘 개선

### 🎯 정확성 고위험 수정
- **`rfind()` 전환**: `_extract_new_part`에서 `find()` → `rfind()` — suffix 중복 시 마지막 위치 기준 추출 (과잉 추출 방지)
- **소프트 리셋 `_soft_resync()`**: desync/ambiguous 리셋 시 전체 초기화 대신 최근 5개 자막 기반 히스토리 재구성 (대량 중복 방지)

### 🔄 MutationObserver 하이브리드
- **`_inject_mutation_observer()`**: JS MutationObserver를 페이지에 주입하여 이벤트 기반 자막 캡처
- **`_collect_observer_changes()`**: Observer 버퍼에서 변경 텍스트 수집
- **하이브리드 구조**: Observer 우선 → 폴링 fallback (기존 동작 100% 호환)
- **프레임 경로 탐색**: 최근 성공 프레임 + 중첩 iframe/frame 순회
- **폴링 브리지 fallback**: 타겟 요소 미탐색 시 JS 내부 180ms 주기 selector 스캔 브리지 활성화
- **재연결 시 자동 재주입**: WebDriver 재연결 후 Observer 자동 재주입


## 10. 자막 수집 알고리즘

> [!IMPORTANT]
> 글로벌 히스토리 Suffix 매칭의 **핵심 의미론**은 수많은 시행착오 끝에 완성되었습니다.
> 수정 시 `PIPELINE_LOCK.md`의 §2 수정 이력에 반드시 기록하세요.

### 핵심 개념: 글로벌 히스토리 + Suffix 매칭

```python
# 상태 변수
self._confirmed_compact = ""   # 확정된 모든 텍스트 (공백 제거)
self._trailing_suffix = ""     # 마지막 50자

# 처리 흐름
def _process_raw_text(self, raw):
    raw_compact = compact(raw)
    
    # suffix가 raw에 있으면 그 이후만 추출 (rfind: 마지막 위치 기준)
    pos = raw_compact.rfind(self._trailing_suffix)
    if pos >= 0:
        new_part = raw[pos + len(suffix):]
    
    # 새 내용을 히스토리에 추가
    self._confirmed_compact += new_part
    self._trailing_suffix = self._confirmed_compact[-50:]
    
    # 자막에 추가
    add_to_subtitles(new_part)
```

### 운영 고정 규칙
- `_process_raw_text`, `_extract_new_part`의 핵심 의미론(글로벌 히스토리 + suffix)은 유지한다.
- 코어 수정 시 `PIPELINE_LOCK.md` §2를 함께 갱신한다.
- 반복/누락 이슈 대응은 아래 레이어에서 우선 수행한다.
  1. Worker 전처리(정규화, compact 중복 전송 억제)
  2. 선택자 우선순위/프레임 탐색 경로
  3. `_prepare_preview_raw` 게이트 임계값/재동기화 기준
  4. `_extract_stream_delta`, `_slice_incremental_part` fallback 조건
  5. `_drain_pending_previews` 종료 직전 플러시 정책
- 운영 로그 키워드: `preview suffix desync reset`, `소프트 리셋: suffix=`, `MutationObserver 주입 성공`, `MutationObserver 폴링 브리지 활성화`

### 과거 시도 및 실패 기록 (참고용)
| 접근법 | 실패 이유 |
|--------|-----------|
| 앵커 기반 | 확정 전까지 앵커가 없어 모든 raw가 delta로 처리됨 |
| 버퍼 비교 (startswith) | 공백/줄바꿈 차이로 매칭 실패 |
| 문장 해시 | 문장이 섞여 들어오면 다른 해시가 됨 |


## 11. 개선 영역

1. 모듈 분리 (core/, ui/ 완료, utils/ 필요 시)
2. pytest 테스트 추가
3. 타입 힌트 강화
4. PyInstaller 패키징

---

*새 세션에서 이 파일을 먼저 읽어 프로젝트 맥락을 파악하세요.*
