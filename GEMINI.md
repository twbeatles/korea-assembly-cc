# AI Context: 국회 의사중계 자막 추출기

이 문서는 AI 에이전트(Gemini)가 `국회 의사중계 자막 추출기` 프로젝트를 이해하고 코드를 수정할 때 참고해야 할 핵심 정보를 담고 있습니다.

## 1. 프로젝트 개요

- **목표**: 국회 의사중계 웹사이트에서 AI 자막을 실시간으로 추출
- **버전**: v16.14.7
- **핵심 가치**: 실시간 자막 캡처, 안정적 멀티스레딩, 모던 UI, SQLite 데이터베이스

## 2. 기술 스택

- **언어**: Python 3.10+
- **GUI**: PyQt6 (Qt)
- **웹 자동화**: Selenium + Chrome WebDriver
- **동시성**: threading, bounded `queue.Queue` wrapper (`MainWindowMessageQueue`)
- **설정**: QSettings, JSON
- **데이터베이스**: SQLite3 (`core/database_manager.py`, `database.py` shim)
- **문서 출력**: python-docx (DOCX), 내장 HWPX, pywin32 (HWP), 내장 (TXT/SRT/VTT/RTF)
- **로깅**: logging (파일 + 콘솔)

## 3. 아키텍처 요약

```
┌──────────────────────────────────────────────┐
│           MainWindow (UI Thread)             │
│  - 사용자 입력, 자막 렌더링, 통계 업데이트      │
│  - 연결 상태 모니터링 (🟢/🔴/🟡)              │
└───────────────────────┬──────────────────────┘
                        │ message_queue (bounded queue)
┌───────────────────────▼──────────────────────┐
│         Worker Thread (Background)           │
│  - Selenium 구동                              │
│  - MutationObserver + structured probe hybrid │
│  - keepalive 기반 end_time 연장                │
│  - 자동 재연결 (지수 백오프)                   │
│  - stop_event 기반 안전 종료                  │
└───────────────────────┬──────────────────────┘
                        │
┌───────────────────────▼──────────────────────┐
│   DatabaseManager (core/database_manager.py) │
│  - SQLite 세션/자막 저장 및 검색               │
└──────────────────────────────────────────────┘
```

## 4. 핵심 규칙

### 4.1 UI/Logic 분리
- UI 스레드와 Worker 스레드 간 통신은 `MainWindowMessageQueue(maxsize=500)` 사용
- 직접 UI 객체 수정 금지 (스레드 안전하지 않음)
- `self.driver` 접근은 `_driver_lock` + identity helper 경로만 사용
- **subtitle_lock**: 자막 리스트 접근 시 `threading.Lock()` 필수, 단 파일 I/O/토스트/UI refresh는 락 밖에서 수행
- 스마트 스크롤: 사용자가 스크롤하면 자동 스크롤 일시 중지 및 위치 유지

### 4.2 자막 처리 흐름
1. Worker: MutationObserver 버퍼를 우선 수집하고, 미수집 시 structured probe fallback으로 `preview` 전송
2. Worker: 시작/재연결 시 URL에 `xcgcd`가 없으면 `xcode` 기준 자동 감지를 1회 수행하고, 재연결에서는 직전 확정 URL을 우선 재사용
3. Worker: 선택자 우선순위(`.smi_word:last-child` 우선) + 기본 문서/iframe 순회로 자막 요소 탐색
4. Worker: `.smi_word`는 단일 노드 대신 목록 전체를 수집해 최근 창(window) 텍스트로 조합
5. Worker: 타겟 미탐색 시 `allow_poll_fallback` 기반 JS 폴링 브리지 활성화
6. Worker: preview 기본 계약은 dict payload 유지, 내부 큐에서는 `run_id` envelope로 stale run 구분
7. UI: `_prepare_preview_raw`에서 정규화/게이팅/재동기화 처리 (desync 시 `_soft_resync`)
8. Core: `_process_raw_text`(GlobalHistory + Suffix, `rfind` 기반)로 새 부분 추출
9. 후단 정제: `get_word_diff` + recent compact tail 체크 + 유의미 텍스트 게이트(짧은 발화 허용/노이즈 차단)
10. UI/Persistence: `capture_state.entries` 단일화, delta render/tail patch, immutable render snapshot, `snapshot_clone()` + streaming JSON 저장
11. finalize 호환 경로도 shared append/merge helper를 사용해 duplicate append를 방지
12. 중지 시: `_drain_pending_previews`로 큐를 소진하고 강제 플러시로 누락 방지
13. 동일 자막 유지 시: 마지막 엔트리 `end_time` 주기 갱신

### 4.3 예외 처리
- 파일 I/O: `try-except` 필수
- WebDriver 연결: 지수 백오프로 최대 5회 재시도 (#31)
- 자막 요소: 여러 CSS 선택자 순차 시도

### 4.4 저장소 / 세션 상태
- 저장소 루트는 `development=repo root`, `portable=EXE dir(옆에 portable.flag 존재)`, `frozen default=%LOCALAPPDATA%\AssemblySubtitle\Extractor` 3가지 모드로 고정된다.
- `QSettings`는 기본 Windows 경로를 사용하되, portable 모드에서는 storage root의 `settings.ini`를 사용한다.
- `url_history.json`, `committee_presets.json`, `subtitle_history.db`, `session_recovery.json`, `logs/`, `sessions/`, `backups/`, `realtime_output/`는 모두 storage root 아래에 생성된다.

## 5. 주요 클래스

| 클래스 | 파일 | 역할 |
|--------|------|------|
| `Config` | core/config.py | 상수 및 기본 설정 |
| `ToastWidget` | ui/widgets.py | 비차단 토스트 알림 |
| `SubtitleEntry` | core/models.py | 자막 데이터 모델 |
| `MainWindow` | ui/main_window.py | 메인 윈도우 파사드 및 lifecycle 조립 |
| `MainWindowHost` | ui/main_window_types.py | 분할된 MainWindow mixin의 공통 `self` 타입 계약 |
| `MainWindowCaptureMixin` | ui/main_window_capture.py | Selenium 수집/재연결/observer 처리 |
| `MainWindowPipelineMixin` | ui/main_window_pipeline.py | live row ledger + subtitle pipeline 연동 |
| `MainWindowPersistenceMixin` | ui/main_window_persistence.py | 공개 facade, 실제 구현은 `ui/main_window_impl/persistence_*`로 분리 |
| `DatabaseManager` | core/database_manager.py | SQLite CRUD (#26) |

추가 메모
- 공개 import 경로는 유지하지만 capture/pipeline/view/runtime의 실제 구현은 `ui/main_window_impl/`로 이동했습니다.
- `core/live_capture.py`는 facade이고 실제 ledger/model/reconcile 구현은 `core/live_capture_impl/`에 있습니다.
- 내부 구현 계약은 `ui/main_window_impl/contracts.py`의 관심사별 Protocol로 더 잘게 분리되어 있고, 공개 호환 표면만 `MainWindowHost`로 유지됩니다.

## 6. 핵심 메서드

| 메서드 | 설명 |
|--------|------|
| `_start()` / `_stop()` | 추출 시작/중지 |
| `_extraction_worker()` | 백그라운드 스레드 메인 루프 (MutationObserver 하이브리드) |
| `_inject_mutation_observer()` | JS MutationObserver 페이지 주입 |
| `_inject_mutation_observer_here()` | 현재 문맥(frame) Observer/폴링 브리지 주입 |
| `_collect_observer_changes()` | Observer 버퍼에서 변경 텍스트 수집 |
| `_build_subtitle_selector_candidates()` | 선택자 후보 생성 및 우선순위 정렬 |
| `_read_subtitle_text_by_selectors()` | 선택자 + 프레임 경로 순회 기반 자막 읽기 (`.smi_word` 창 수집 포함) |
| `_activate_subtitle()` | AI 자막 레이어 활성화 |
| `_process_message_queue()` | bounded queue + stale run filtering (100ms) |
| `_build_persistent_entries_snapshot()` | 저장/export/자동백업/리플로우 worker용 clone 기반 불변 snapshot 생성 |
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
| `_save_in_background()` | 비동기 파일 저장 헬퍼 (TXT/SRT/VTT/DOCX/HWPX/HWP/RTF/통계 내보내기, 스레드 추적/종료 대기 연동) |
| `_start_background_thread()` | 공통 백그라운드 스레드 등록/시작 (종료 단계 차단 포함) |
| `_wait_active_background_threads()` | 종료 시 백그라운드 작업(파일/세션/DB) 제한시간 대기 |
| `_wait_active_save_threads()` | 종료 시 저장 스레드 제한시간 대기 |
| `_update_connection_status()` | 연결 상태 UI 업데이트 (#30) |
| `_generate_smart_filename()` | 자동 파일명 생성 (#28) |
| `_show_merge_dialog()` | 자막 병합 다이얼로그 (#20, dedupe 모드 포함) |
| `_show_db_history()` | DB 세션 히스토리 (#26) |

## 7. 파일 구조

```
korea-assembly-cc/
  국회의사중계 자막.py       # 메인 엔트리포인트
  core/                         # 공통 로직/설정
    config.py
    database_manager.py
    file_io.py
    live_capture.py
    live_capture_impl/          # ledger/model/reconcile 내부 구현
    live_list.py                # live_list.asp 공유 fetch/parse/selection helper
    logging_utils.py
    models.py
    reflow.py
    subtitle_pipeline.py
    subtitle_processor.py
    text_utils.py
    hwpx_export.py              # 기본 HWPX 내보내기
    utils.py                    # 호환용 re-export shim
  ui/                           # UI 구성요소
    dialogs.py
    main_window_capture.py
    main_window_common.py
    main_window_database.py
    main_window_persistence.py
    main_window_pipeline.py
    main_window_types.py
    main_window_ui.py
    main_window_view.py
    main_window_impl/           # capture/pipeline/view/runtime 내부 구현
    themes.py
    widgets.py
    main_window.py              # MainWindow 파사드
  database.py                   # SQLite DB 호환 shim
  subtitle_extractor.spec   # PyInstaller 빌드 설정
  tests/
    test_core_algorithm.py      # 코어 알고리즘 단위 테스트
    test_encoding_hygiene.py    # UTF-8/BOM/U+FFFD/한글 round-trip 검증
    test_feature_plan_20260325.py  # 검색/세션/프리셋/저장 정합성 회귀 테스트
    test_pyright_regression.py  # pyright 0 error 회귀 테스트
    test_review_20260323_regressions.py  # run_id/alert/HWP/SRT-VTT 회귀 테스트
    test_reflow.py              # Reflow 테스트
    test_session_resilience.py  # 세션 병합/손상 항목/ dedupe 정책 회귀 테스트
  README.md                 # 문서
  CLAUDE.md                 # AI 컨텍스트
  GEMINI.md                 # AI 컨텍스트
  PIPELINE_LOCK.md          # 파이프라인 고정 문서
  ALGORITHM_ANALYSIS.md     # 알고리즘 분석 문서
  portable.flag             # portable 모드 sentinel (선택적, 커밋 금지)
  storage_root/             # development=repo root, portable=EXE dir, frozen default=%LOCALAPPDATA%\AssemblySubtitle\Extractor
    settings.ini            # portable 모드에서만 사용
    subtitle_history.db     # SQLite DB (자동 생성)
    url_history.json        # URL 히스토리 (자동 생성)
    committee_presets.json  # 상임위 프리셋 (자동 생성)
    session_recovery.json   # 복구 포인터/state (자동 생성)
    logs/
      subtitle_YYYYMMDD.log
    sessions/
    backups/
    realtime_output/
```

## 8. 의존성

```bash
pip install -r requirements-dev.txt
```

- `requirements-dev.txt`에는 DOCX(`python-docx`)와 HWP(`pywin32`) 저장용 optional 패키지가 함께 정리되어 있음
- `pyinstaller==6.19.0`은 release/frozen smoke 검증용 개발 의존성으로 고정되어 있음
- HWPX 저장은 기본 내장 기능이며 별도 외부 프로그램이 필요하지 않음

### 8.1 개발 품질 게이트
- 정적 분석 기준: 루트 `pyrightconfig.json` 기준으로 `pyright` 실행 시 `0 errors`
- 테스트 기준: 루트에서 `pytest -q` 전체 통과
- pyright 회귀 게이트: `tests/test_pyright_regression.py`가 워크스페이스 전체 `pyright --outputjson` 결과가 `0 errors`인지 확인
- Import smoke check: `python -c "import ui.main_window as m; print(m.MainWindow.__name__)"`
- Source smoke check: `python "국회의사중계 자막.py" --smoke --smoke-storage-dir .pytest_tmp/smoke-storage`
- Storage smoke check: `python "국회의사중계 자막.py" --smoke-storage-preflight --smoke-storage-dir .pytest_tmp/smoke-storage`
- Frozen smoke check: `pyinstaller --clean subtitle_extractor.spec` 후 EXE `--smoke`, EXE 옆 `portable.flag` 생성 후 `--smoke-storage-preflight` exit code 0 확인
- 인코딩 정책: 소스/문서/`subtitle_extractor.spec`는 UTF-8 without BOM 유지
- 예외: 사용자 TXT 저장/실시간 저장은 Windows 메모장 호환을 위해 `utf-8-sig`를 사용할 수 있음
- VS Code/Pylance는 루트 `pyrightconfig.json`과 `.vscode/settings.json`을 기준으로 동일하게 해석
- `pyrightconfig.json`은 `stubPath=typings`, `executionEnvironments[].extraPaths=["typings"]`, `.pytest_tmp` exclude, `reportMissingModuleSource=none`를 공통 기준으로 사용
- `tests/test_encoding_hygiene.py`는 repo tracked 파일만 검사하고, BOM이 허용되는 `.pytest_tmp` workspace temp 산출물은 제외한다
- Windows PowerShell 5.x 콘솔에서는 UTF-8 without BOM이 깨져 보일 수 있으나 파일 자체는 UTF-8 유지

### 8.2 저장소 기준 파일
- `pyrightconfig.json`: 저장소 공통 타입 체크 기준
- `.vscode/settings.json`: 워크스페이스 Pylance/UTF-8 설정
- `.editorconfig`, `.gitattributes`: 텍스트 파일 인코딩/라인엔딩 기준
- `typings/`: 글로벌 인터프리터 편차를 흡수하는 로컬 PyQt6/selenium/pytest stub
- `pytest.ini`: 워크스페이스 내부 basetemp(`.pytest_tmp`) 강제
- `requirements-dev.txt`: 개발/검증 및 optional export 의존성 기준선
- `ui/main_window_types.py`: 분할된 `MainWindow` mixin의 공통 `self` 타입 계약(`MainWindowHost`)
- `tests/test_encoding_hygiene.py`: UTF-8 without BOM, U+FFFD 금지, 핵심 한글 문자열 round-trip 검증
- `tests/test_hwpx_export.py`: HWPX 패키지 구조, preview 텍스트, XML escape/줄바꿈 회귀 검증
- `tests/test_live_contract_smoke.py`: `RUN_LIVE_SMOKE=1` opt-in 실제 `live_list.asp` schema smoke
- `tests/test_pyright_regression.py`: 워크스페이스 전체 `pyright --outputjson` 결과가 `0 errors`인지 회귀 검증

## 9. HWPX 기본 내보내기 추가 (2026-03-23)

- **기본 HWPX export 추가**: `파일 → HWPX 저장` 메뉴와 `core/hwpx_export.py`를 추가해 한컴 미설치 환경에서도 기본 `.hwpx` 문서를 생성할 수 있게 함
- **패키지 구조**: `assets/hwpx/header.xml` 템플릿과 `Contents/section0.xml`, `Preview/PrvText.txt`, `Contents/content.hpf`를 조합해 최소 유효 HWPX 패키지를 작성
- **검증 보강**: HWPX 저장 회귀 테스트와 특수문자/XML escape, 줄바꿈 preview 검증을 추가해 `pytest -q` 85 pass, `pyright` 0 errors 확인

## 9. v16.6 신규 기능

### #30 연결 상태 모니터링
- 상태바에 🟢/🔴/🟡 아이콘 표시
- 툴팁에 응답 시간 표시

### #31 자동 재연결
- 지수 백오프 알고리즘 (2→4→8→16→32초)
- 최대 5회 재시도, 토스트 알림
- URL에 `xcgcd`가 없는 경우에만 자동 감지를 연결하고, 이미 있으면 기존 URL 유지

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
- **생중계 목록 선택 UI 추가**: '📡 생중계 목록' 버튼을 통해 현재/종료 방송을 함께 확인할 수 있고, `종료/예정` 항목은 확인 후 URL만 채움 (`LiveBroadcastDialog`)


### 특별위원회 프리셋 추가
- `Config.DEFAULT_COMMITTEE_PRESETS`: 국정감사, 국정조사, 국회정보나침반 URL
- `Config.SPECIAL_COMMITTEE_XCODES`: 현재 검증된 문자열 xcode는 `IO`만 유지

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

## 9.6 v16.12.1 안정화 패치 (2026-02-25)

- **짧은 발화 수집 보강**: `네/예/ok` 같은 1~2글자 발화를 허용하고, 기호-only/숫자-only 노이즈를 차단
- **세션 내결함성 개선**: 세션 로드/DB 로드/병합에서 손상 항목만 건너뛰고 나머지 항목은 유지
- **저장 비차단화 확장**: RTF 저장, 통계 내보내기를 `_save_in_background` 경로로 전환
- **로그 경로 정합성**: 로그 디렉터리를 `Config.LOG_DIR` 기준으로 통일

## 9.7 v16.13 운영 안정화

### 🔧 기능 경로 연결
- **`xcgcd` 자동 보완 실연결**: `_detect_live_broadcast`를 워커 시작 직후/재연결 경로에서 실제 호출
- **URL 재사용 일관화**: 감지된 URL을 지역 `url`에 반영해 최초 경로와 재연결 경로를 통일

### ⏱️ keepalive 및 타이밍 보정
- **keepalive 활성화**: 동일 `raw_compact` 유지 시 `Config.SUBTITLE_KEEPALIVE_INTERVAL` 주기로 `keepalive` 발행
- **타이머 dead path 정리**: 미사용 finalize 타이머 경로 제거, 즉시 확정 + keepalive 보정으로 단일화

### 💾 저장/종료 안전성
- **원자적 텍스트 저장**: `atomic_write_text` 도입, TXT/SRT/VTT/RTF 저장에 적용
- **저장 스레드 추적**: non-daemon 저장 스레드 등록/해제 및 종료 시 제한시간 대기
- **로그 경로 통일**: `core/logging_utils.py`가 `Config.LOG_DIR`를 사용하도록 정렬

### 🧩 UI 안정성/노이즈 필터
- **LiveBroadcastDialog 종료 비차단화**: persistent fetch thread를 제거하고, `done`/`closeEvent`는 closing flag + request token만 갱신
- **짧은 발화 허용 + 노이즈 차단**: `is_meaningful_subtitle_text`로 1~2자 한글/영문 허용, 숫자/기호-only 차단

## 9.8 v16.13.1 수집 안정화

### 🧩 첫 문장 이후 정체 완화
- **`.smi_word` 창 수집**: 단일 `:last-child` 대신 `.smi_word` 목록 전체를 수집해 최근 창 텍스트를 조합
- **Observer 타겟 보강**: `.incont`/`#viewSubtit` 컨테이너 우선 탐색으로 DOM 구조 변화 대응 강화
- **긴 텍스트 축약 보강**: Observer 버퍼에 과도한 컨테이너 텍스트가 들어올 때 최근 라인 중심으로 축약

## 9.9 v16.14.2 성능 최적화 중심 리팩토링
### ⚙️ Worker CPU 절감
- 자막 수집 회귀 대응으로 Worker 캡처 루프는 이전 안정 structured probe 경로로 복귀
### 🧠 Pipeline / Memory 최적화
- `confirmed_segments` 증분 갱신으로 append/tail update hot path에서 전체 history rebuild를 피함
- `SubtitleEntry.__slots__`, compact cache, `CaptureSessionState.snapshot_clone()`, streaming JSON 저장으로 메모리 피크 완화
### 🖥️ UI 체감 성능
- `capture_state.entries`를 단일 source of truth로 유지하고, `PipelineResult` delta 기준 append/tail update만 증분 반영
- 마지막 visible row 수정은 tail patch render를 사용하고 queue drain은 `약 8ms / 최대 50건` 예산으로 처리
### ✅ 검증 상태
- `commit_live_row` 1,500회 benchmark 약 `10.3초 -> 3.8초`
- `pytest -q` 59 pass, `pyright` 0 errors

## 9.9.0 v16.14.5 UI/UX 운영 정합성 보강 (2026-03-27)

- 캡처 시작 시 URL/위원회/헤드리스/실시간 저장을 `run-source` 스냅샷으로 고정하고, 추출 중 관련 UI 변경을 함께 잠금
- 생중계 목록은 `생중계`와 `종료/예정`을 함께 보여주되 자동 감지는 live-only로 제한
- DB 히스토리 50건, DB 검색 100건, 편집/삭제 200개 단위 `더 보기` 로딩을 도입
- 편집/삭제 다이얼로그는 원본 subtitle index를 유지하는 검색형 목록으로 재구성
- 세션 dirty tracking과 종료 시 `Save / Discard / Cancel` 정책을 세션 JSON 저장 기준으로 정리
- `Escape`, `Ctrl+Shift+C`, `Ctrl+C` 문서와 실제 구현을 일치시킴
- `pytest -q` 95 pass, `pyright` 0 errors

## 9.9.1 v16.14.4 기능 안정화 및 UX 정합성 보강 (2026-03-25)

- 검색 기준을 전체 `self.subtitles` 스냅샷으로 전환하고, 검색 이동 시 해당 entry가 보이도록 렌더 offset을 동적으로 조정
- 추출 중 세션 불러오기/DB 세션 로드/병합/줄넘김 정리/지우기/편집/삭제를 공통 가드와 action disable로 차단
- 파일/DB 세션 로드 payload를 `version`, `url`, `committee_name`, `created_at`, `subtitles`, `skipped`, optional highlight 정보로 통합
- DB 검색 결과에서 `세션 불러오기`와 `결과로 이동(sequence focus)`를 지원
- 프리셋 export/import가 `committee` + `custom` round-trip을 지원하고, 통계/프리셋 export는 원자적 저장으로 통일
- 자막 병합은 dedupe 기준을 `보수적(같은 초)` / `기존(30초 버킷)`으로 선택 가능
- `.gitignore`를 재검토해 루트 `세션_*.json` export가 실수로 추적되지 않도록 보강
- `pytest -q` 85 pass, `pyright` 0 errors

## 9.9.2 v16.14.3 운영 정합성 동기화 (2026-03-23)
### 🔒 Worker lifecycle / queue
- `self.driver` 접근을 `_driver_lock` + identity helper로 통일하고, stop timeout 뒤 stale run을 즉시 inactive 처리
- `MainWindowMessageQueue(maxsize=500)`가 Worker 메시지를 `run_id` envelope로 감싸고 `preview`/`keepalive`/`status`/`resolved_url`를 coalescing
- `xcgcd` 자동 감지는 시작 시 1회만 수행하고, 재연결에서는 이미 해석된 live URL을 우선 재사용
### 🧾 Subtitle path / render
- `_finalize_subtitle()`는 shared append/merge helper를 사용해 파이프라인과 동일한 반영 규칙을 따름
- realtime write/flush는 `subtitle_lock` 밖으로 이동하고, 렌더는 immutable snapshot clone을 사용
- `SubtitleEntry(entry_id=None)`는 런타임에서 항상 ID를 생성
### ⚙️ 설정 / 검증
- 미검증 `정보위원회`/`NA`/`PP` 기본 코드 제거, `공백 기준 단어 수` 문구 정리
- 로컬 `typings/` stub과 `pytest.ini --basetemp=.pytest_tmp`로 글로벌 Python/Windows TEMP 권한 편차를 흡수하고, 루트 `.hwpx` 산출물도 `.gitignore`에 반영
- `pywin32` 미설치 시 HWP 저장은 즉시 `HWPX`로 자동 대체되고, 저장 실패 경로에서만 RTF/DOCX/TXT 선택 다이얼로그를 유지
- `pytest -q` 85 pass, `pyright` 0 errors

## 9.9.4 v16.14.7 브라우저 자동 복구 + 내부 구조 분리 정합화 (2026-04-01)
### 🛡️ 브라우저 자동 복구
- Worker가 `window_handles`, `current_url`, `execute_script("return 1")` 기준으로 브라우저 헬스체크를 수행하고, 연속 실패는 recoverable WebDriver 오류로 승격
- observer/probe/frame 순회 경로가 `invalid session`, `target closed`, `no such window`, `chrome not reachable` 계열 오류를 재기동 루프로 전달
- 같은 headless/visible 모드와 마지막 확정 live URL을 우선 재사용하며, 성공 시 `reconnected` 메시지로 UI 상태를 갱신
### 🧩 구조 분리
- 공개 facade(`ui.main_window*`, `core.live_capture`)는 유지하고, 실제 구현은 `ui/main_window_impl/`와 `core/live_capture_impl/`로 이동
- `ui/main_window_ui.py`는 이번 배치에서 공개 UI mixin 경로를 유지하고, shell/preset/help 책임은 후속 분리 대상으로 남음
### 📦 빌드 / 문서 / ignore
- `subtitle_extractor.spec` hidden import를 내부 모듈 구조에 맞게 확장
- `.gitignore`는 루트 `*.manifest`, `*.pyz` 산출물까지 무시

## 9.9.5 v16.14.7 장시간 세션 성능 최적화 (2026-04-05)
- UI 갱신은 `render/count/stats/status/search-count` 단위의 coalescing scheduler로 모아 같은 event-loop tick 안의 중복 repaint를 1회로 줄인다.
- runtime archive는 bisect 가능한 segment locator, render window cache, small segment LRU cache를 사용해 archived window 재렌더와 segment 재파싱 비용을 줄인다.
- inline search는 debounce + revision stale-drop으로 최신 query만 반영하고, segment-local normalized text cache를 재사용해 장시간 세션 검색 비용을 줄인다.
- 세션 저장과 TXT/SRT/VTT/DOCX/HWPX/HWP/RTF/통계 export는 archived segment + active tail iterator를 직접 사용해 full-session hydrate를 피한다.
- DB 히스토리/검색 결과 append는 기존 항목 전체 재구성 대신 신규 row만 추가하는 방향으로 유지한다.

## 9.9.6 v16.14.7 코드 분할 리팩토링 정합화 (2026-04-05)
- `ui/main_window_database.py`는 공개 facade만 남기고 실제 DB worker/task/result 처리 책임은 `ui/main_window_impl/database_worker.py`, dialog/UI 책임은 `ui/main_window_impl/database_dialogs.py`로 이동했다.
- `ui/main_window_persistence.py`는 facade만 유지하고 runtime archive는 `persistence_runtime.py`, 세션/복구는 `persistence_session.py`, export는 `persistence_exports.py`, 유틸은 `persistence_tools.py`로 재분리했다.
- `subtitle_extractor.spec` hidden import에는 `ui.main_window_impl.database_*`, `ui.main_window_impl.persistence_*`를 추가해 frozen 빌드에서도 facade 뒤 구현이 누락되지 않도록 맞췄다.
- `pyinstaller --clean subtitle_extractor.spec`로 `dist/국회의사중계자막추출기 v16.14.7.exe` 빌드를 다시 검증했다.

## 9.9.7 v16.14.7 세션 안정성 / 도구 체인 정합화 (2026-04-06)
- 실행 중 수동 `세션 저장`은 runtime archive를 정리하지 않고 snapshot-only로 처리되며, 이후 segment flush/search/render/export는 같은 archive를 계속 사용한다.
- runtime flush/checkpoint/recovery write는 `archive_token` + `run_id` + captured path context를 함께 유지하고, stale completion은 무시한다.
- runtime manifest 복구는 best-effort salvage로 동작하며, manifest JSON 손상 시 sibling `segment_*.json` + `tail_checkpoint.json`에서 복구를 시도하고 제외된 파일/항목 수를 사용자 요약에 노출한다.
- 빈 URL 세션 로드 시 stale `current_url`을 비우고, recovery pointer는 복구 거절/복구 성공 시 즉시 지우지 않으며 성공한 JSON 저장 또는 정상 종료에서만 정리한다.
- `pyrightconfig.json` / `.vscode/settings.json`은 `typings/`를 `stubPath`/`extraPaths`로 명시하고 `.pytest_tmp`를 분석 범위에서 제외하며, 로컬 stub 환경의 `reportMissingModuleSource` 경고를 끈다.
- `typings/PyQt6/QtNetwork.pyi`를 추가해 `LiveBroadcastDialog`의 `QNetworkAccessManager` 경로까지 CLI `pyright`와 Pylance에서 동일하게 해석된다.
- 당시 기준선은 `pytest -q` 158 pass, `pyright --outputjson` 0 errors / 0 warnings 이다.

## 9.9.8 v16.14.7 저장소 / 세션 안전성 보강 (2026-04-08)
- frozen 기본 저장소는 `%LOCALAPPDATA%\AssemblySubtitle\Extractor`로 이동하고, EXE 옆 `portable.flag`가 있으면 로그/세션/DB/설정(`settings.ini`)을 EXE 폴더에 저장한다.
- 앱 시작 전 storage preflight로 `logs/`, `sessions/`, `backups/`, `runtime_sessions/`, DB 경로 생성/쓰기 가능 여부를 검사하고 실패 시 UI 조립 전에 중단한다.
- `종료`, `세션 불러오기`, `DB 세션 로드`, `세션 병합`은 `저장 후 원래 액션 재개` 흐름을 공유하고, DB sync save는 timeout 실패를 명시적으로 처리한다.
- archived session 편집/삭제/복사/줄넘김 정리/병합은 background hydrate worker + modal progress/cancel로 전환되어 장시간 UI 정지를 줄인다.
- `LiveBroadcastDialog`와 `capture_live`는 `10초` timeout, invalid JSON/schema 구분, malformed row drop, stale reply 무시를 공통 적용한다.
- DB `sessions`는 `lineage_id`, `parent_session_id`, `is_latest_in_lineage`를 유지하고, 히스토리 다이얼로그는 `[최신]`, `[이전 저장본 n/N]` 배지로 계보를 표시한다.
- 당시 기준선은 `pytest -q` 170 pass, `pyright --outputjson` 0 errors / 0 warnings 이다.

## 9.9.9 v16.14.7 기능 구현 정합성 보강 (2026-04-14)
- storage preflight는 이제 디렉터리 probe뿐 아니라 `subtitle_history.db`, `committee_presets.json`, `url_history.json`, `session_recovery.json`의 실제 파일 surface와 SQLite `PRAGMA journal_mode=WAL`까지 검증한다.
- `core/live_list.py`가 `live_list.asp` URL 생성, payload 파싱, row 정규화, 오류 분류, 자동 선택 정책을 공통화하고, `LiveBroadcastDialog`와 `capture_live`는 같은 helper를 사용한다.
- `xcode`가 없고 진행 중인 생중계 후보가 여러 개인 경우 첫 후보를 자동 선택하지 않고 원래 URL을 유지하며, 상태바/토스트로 `생중계 목록` 수동 선택을 유도한다.
- `DatabaseManager`는 base schema와 FTS 초기화를 분리하고, `db_available`, `fts_available`, `db_degraded_reason`를 UI에 노출한다. FTS를 사용할 수 없으면 검색은 literal `LIKE`로 fallback한다.
- URL 히스토리/프리셋 load-save 실패는 더 이상 로그에만 남지 않고 사용자 경고로 노출되며, `persistence_exports.py` / `pipeline_messages.py` dead branch는 정리되었다.
- `subtitle_extractor.spec` hidden import에 `core.live_list`가 추가되었고, `.gitignore`는 `.storage_probe`를 저장소 전체에서 무시한다.
- 최신 기준선은 `pytest -q` 210 pass, `pyright --outputjson` 0 errors / 0 warnings, import smoke 통과, `pyinstaller --clean subtitle_extractor.spec` 빌드 성공이다.

## 9.9.10 v16.14.7 기능 리스크 hardening (2026-04-29)
- `subtitle_reset`은 `Config.SUBTITLE_RESET_GRACE_MS` grace를 유지하지만, 새 structured preview 처리 전 pending reset을 먼저 커밋해 발언자 전환 경계를 보장한다.
- merge boundary는 기존 `source_node_key` mismatch 외에 speaker color/channel mismatch와 container fallback `source_mode`를 사용해 fallback preview가 이전 structured entry에 붙는 일을 막는다.
- Observer clear 이벤트는 `{kind:"reset", selector, previousLength}` 구조를 사용하며, legacy `__SUBTITLE_CLEARED__`도 계속 허용한다. `.smi_word` 계열 clear만 즉시 reset으로 신뢰하고 broad container clear는 probe 재확인으로 보낸다.
- runtime segment flush는 `first_entry_id`, `last_entry_id`, `entries_digest` fingerprint가 현재 active prefix와 일치할 때만 prefix를 삭제한다.
- runtime manifest의 segment/tail path는 runtime root 내부 relative path로 제한하고, salvage mode에서는 잘못된 path를 warning과 함께 skip한다.
- `DatabaseManager.checkpoint()`는 `PASSIVE`, `FULL`, `RESTART`, `TRUNCATE`만 허용한다.
- `subtitle_extractor.spec`는 현재 hidden import 목록에 `core.config`를 명시하고, `.gitignore`는 PyInstaller/root-level 보조 산출물과 root `runtime_sessions/`를 추가로 제외한다.
- 검증 기준선은 `pytest -q` 210 pass, `pyright --outputjson` 0 errors / 0 warnings, import/version smoke 통과, `pyinstaller --clean subtitle_extractor.spec` 빌드 성공이다.

## 9.9.11 v16.14.7 기능 구현 리스크 개선 전체 배치 (2026-05-06)
- 저장/export/자동백업/리플로우 background 경로는 `_build_persistent_entries_snapshot()`을 사용해 active tail entry를 `SubtitleEntry.clone()`으로 freeze한다.
- bounded queue가 가득 찬 경우에도 `finished`, `error`, `subtitle_not_found` terminal worker message는 `_terminal_worker_messages` priority passthrough에 보존하고 일반 overflow보다 먼저 drain한다.
- `DatabaseManager` FTS5 초기화는 table/trigger 보장과 rebuild 필요 판단을 분리한다. `rebuild`는 최초 생성, FTS 접근 오류, 최근 sample probe 누락 등 drift가 의심될 때만 실행한다.
- `국회의사중계 자막.py`는 GUI 없는 `--smoke`, `--smoke-storage-preflight`, `--smoke-storage-dir`를 제공한다. source smoke는 JSON 한 줄을 출력하고 frozen smoke는 exit code 0을 기준으로 release 검증에 포함한다.
- `tests/test_live_contract_smoke.py`는 `RUN_LIVE_SMOKE=1`일 때만 실제 `live_list.asp` 응답 schema를 확인한다.
- 수정한 `pipeline_queue`, `pipeline_state`, `pipeline_messages`, `runtime_driver`는 `TYPE_CHECKING` Host base를 사용해 파일 단위 blanket pyright suppression을 제거했다.
- 최신 기준선은 `pytest -q` 217 pass / 1 skipped, `pyright --outputjson` 0 errors / 0 warnings, import smoke 및 source smoke 2종 통과, `pyinstaller --clean subtitle_extractor.spec` 빌드 성공, frozen EXE 기본 `--smoke`와 `portable.flag` `--smoke-storage-preflight` exit code 0이다.

## 9.9.3 v16.14.6 자막 유실 방지 배치 (2026-04-01)
### 🛡️ 세션 / 복구
- 수동 세션 저장과 종료 직전 저장 모두 `JSON + DB` 경로를 사용하고, 성공한 세션 저장/자동 백업은 `session_recovery.json`에 최신 복구 가능 스냅샷 메타데이터를 기록
- 시작 시 복구 state가 남아 있으면 최신 자동 백업 또는 세션 저장본을 제안하고, 복구된 세션은 다시 저장 전까지 dirty 상태로 유지
### 🧾 Reflow / DB
- 수동 `줄넘김 정리`는 pending preview까지 포함한 prepared snapshot 기준으로 백그라운드 reflow를 수행하며, `SubtitleEntry`의 `entry_id`/`source_*`/`speaker_*`/timing 정책을 보존
- `DatabaseManager`는 additive migration으로 lossless subtitle metadata를 저장/복원하고, 기본 검색은 FTS raw query가 아니라 literal substring 검색으로 동작
### 📄 Export / 저장소 hygiene
- DOCX/HWPX는 한 `SubtitleEntry`를 한 문단/블록으로 유지하고, 엔트리 내부 개행은 paragraph split이 아니라 line break로 저장
- `.gitignore`는 `session_recovery.json` 같은 런타임 복구 state를 무시하고, `subtitle_extractor.spec`은 이 state가 frozen 번들에 포함되지 않음을 명시

## 9.10 v16.14.1 자동 줄넘김 정리 기본 활성화 (2026-03-17)
### 🧹 자동 줄넘김 정리 옵션
- 메인 옵션 영역에 `✨ 자동 줄넘김 정리` 체크박스를 추가하고 기본값을 활성화
- 설정은 `QSettings`에 저장되며, 수집 중 줄바꿈/빈 줄만 자동 정리하고 자막 내용은 유지
### 🔁 파이프라인 정규화 옵션화
- `core/subtitle_pipeline.py`가 `auto_clean_newlines` 설정을 읽어 preview/live-row/flush 경로의 정규화를 통일
- 옵션이 꺼진 경우 개행을 유지하는 회귀 테스트로 기본 동작과 예외 경로를 함께 검증

## 9.11 v16.14.0 크롬 파이프라인 정리 + SOLID 분할 리팩토링 (2026-03-16)
### 🧩 코어 구조 고정
- `core/live_capture.py`와 `core/subtitle_pipeline.py`를 기준 구조로 유지하고, row reconciliation / grace reset / prepared snapshot 동작을 운영 기본 경로로 고정
### 🏗️ MainWindow 책임 분리
- `ui/main_window.py`는 파사드만 담당하고, 실제 구현을 capture / pipeline / view / persistence / database / ui mixin 모듈로 분리
### 🔁 호환 계층 유지
- `core/utils.py`, `database.py`, `ui.main_window.MainWindow` import 경로는 유지하고 실제 구현만 새 모듈로 이동
### 🛡️ Pylance / UTF-8 회귀 보강
- `ui/main_window_types.py`의 `MainWindowHost`로 분할 mixin의 공통 `self` 타입을 고정하고, `tests/test_pyright_regression.py`와 확장된 `tests/test_encoding_hygiene.py`로 품질 게이트를 강화

## 9.12 v16.13.2 운영 정합성 업데이트 (2026-03-05)

### 🔒 종료 lifecycle 통합
- 파일 저장/세션 저장·불러오기/DB task를 공통 백그라운드 레지스트리로 추적
- 종료 시 `신규 작업 차단 -> inflight drain -> 자원 정리` 순서로 단일화

### 🧠 스트리밍 메모리 상한
- `_confirmed_compact`에 상한(`Config.CONFIRMED_COMPACT_MAX_LEN=50000`) 적용
- suffix 의미론은 유지하고 tail만 보존

### 📎 병합 정책 정합성
- 실시간 병합 기준을 Config 상수(`ENTRY_MERGE_MAX_GAP=5`, `ENTRY_MERGE_MAX_CHARS=300`)로 일원화
- 세션 병합 dedupe를 `정규화 텍스트 + 시간 버킷(30초)`(`MERGE_DEDUP_TIME_BUCKET_SECONDS`)으로 전환

### 🗄️ DB 경로 정책 통일
- `DatabaseManager()` 기본 경로를 `Config.DATABASE_PATH`로 통일 (CWD 의존 제거)


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
    self._confirmed_compact = self._confirmed_compact[-Config.CONFIRMED_COMPACT_MAX_LEN:]
    self._trailing_suffix = self._confirmed_compact[-50:]
    
    # 자막에 추가
    add_to_subtitles(new_part)
```

### 운영 고정 규칙
- `_process_raw_text`, `_extract_new_part`의 핵심 의미론(글로벌 히스토리 + suffix)은 유지한다.
- `_confirmed_compact`는 상한(`Config.CONFIRMED_COMPACT_MAX_LEN`) 내에서 tail 유지 정책을 따른다.
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
2. pytest 회귀 시나리오와 UI/패키징 smoke test 확장
3. pyright 0-error 기준 유지 및 신규 코드 타입 보강
4. PyInstaller 패키징

---

*새 세션에서 이 파일을 먼저 읽어 프로젝트 맥락을 파악하세요.*
