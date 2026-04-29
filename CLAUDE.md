# AI Context: 국회 의사중계 자막 추출기

이 문서는 AI 에이전트(Claude)가 `국회 의사중계 자막 추출기` 프로젝트를 이해하고 코드를 수정할 때 참고해야 할 핵심 정보를 담고 있습니다.

## 1. 프로젝트 개요

- **목표**: 국회 의사중계 웹사이트에서 AI 자막을 실시간으로 추출하고 저장
- **버전**: v16.14.7
- **핵심 가치**: 
  - **실시간 스트리밍 자막 (Delay-free)**
  - 안정적인 멀티스레딩 아키텍처
  - 모던 UI/UX (다크/라이트 테마)
  - 다양한 출력 형식 지원
  - **SQLite 데이터베이스 기반 세션 관리**

## 2. 기술 스택

| 구성요소 | 기술 |
|---------|------|
| **언어** | Python 3.10+ |
| **GUI 프레임워크** | PyQt6 (Qt6) |
| **웹 자동화** | Selenium + Chrome WebDriver |
| **동시성** | threading, bounded `queue.Queue` wrapper (`MainWindowMessageQueue`) |
| **설정 저장** | QSettings, JSON |
| **데이터베이스** | SQLite3 (세션/자막 히스토리) |
| **문서 출력** | python-docx (DOCX), 내장 HWPX, pywin32 (HWP), 내장 (TXT/SRT/VTT/RTF) |
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
│                     │ bounded queue │  message_queue         │
│                     └──────┬──────┘                         │
│                            ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Worker Thread (Background)               │   │
│  │  - Selenium WebDriver 구동                            │   │
│  │  - MutationObserver + structured probe hybrid        │   │
│  │  - 자동 재연결 (지수 백오프, #31)                     │   │
│  │  - stop_event 기반 안전 종료                          │   │
│  └──────────────────────────────────────────────────────┘   │
│                            │                                 │
│  ┌──────────────────────────▼───────────────────────────┐   │
│  │          DatabaseManager (core/database_manager.py)   │   │
│  │  - SQLite 세션/자막 저장                              │   │
│  │  - 통합 검색 기능                                     │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 4. 핵심 규칙

### 4.1 스레드 안전성
1. **Queue 통신**: UI 스레드와 Worker 스레드 간 통신은 반드시 `MainWindowMessageQueue(maxsize=500)`를 통해서만 수행
2. **stop_event**: 스레드 종료는 `threading.Event()` 사용 (빠른 응답성 보장)
3. **타이머 기반 업데이트**: 통계 및 상태 업데이트는 `QTimer` 사용 (자막 처리는 실시간)
4. **driver lifecycle**: `self.driver` 접근은 `_driver_lock`과 identity helper를 통해서만 수행
5. **subtitle_lock**: 자막 리스트 접근 시 `threading.Lock()` 사용, 단 파일 I/O/토스트/UI refresh는 락 밖에서 처리
6. **스마트 스크롤**: 사용자가 스크롤하면 자동 스크롤 일시 중지 및 위치 유지

### 4.2 자막 처리 흐름
```
Raw Text(Observer/폴링) → preview 메시지 → _prepare_preview_raw(정규화/게이트)
                              ↓
                     _process_raw_text(GlobalHistory+Suffix)
                              ↓
                    후단 정제(get_word_diff/tail check)
                              ↓
                       SubtitleEntry 즉시 반영
```
- Worker는 선택자 후보를 우선순위(`.smi_word:last-child` 우선)로 정렬하고, 기본 문서 + 중첩 iframe/frame 경로를 순회한다.
- `.smi_word` 선택자는 단일 노드에만 의존하지 않고 목록 전체를 수집해 최근 창(window) 텍스트를 조합한다.
- 시작/재연결 시 URL에 `xcgcd`가 없으면 Worker에서 `xcode` 기준 자동 감지를 1회 수행하고, 재연결에서는 직전 확정 URL을 우선 재사용한다.
- Observer 주입은 타겟 기반 우선 시도 후 실패 시 JS 폴링 브리지(`allow_poll_fallback`)로 전환한다.
- Worker는 Observer 버퍼를 우선 읽고, 미수집 시 structured probe fallback으로 자막을 읽는다.
- Worker preview는 dict payload 계약을 유지하고, 내부 큐에서는 `run_id` envelope로 stale run을 구분한다.
- 길이/간격 제한에 따라 기존 엔트리에 병합 또는 분리
- 중지 시 `preview` 큐를 먼저 소진하고 마지막 버퍼를 확정해 누락 방지
- 동일 자막이 유지되면 마지막 엔트리의 `end_time`을 주기적으로 갱신 (SRT/VTT 정확도)
- `subtitle_segments`/`_drain_pending_previews` 경로도 동일 게이트를 거쳐 코어 알고리즘과 동기화
- `capture_state.entries`가 단일 source of truth이고 `self.subtitles`는 alias로 유지된다.
- append/tail update는 `PipelineResult` delta 기반으로 UI 통계/카운트/렌더링을 증분 반영하며, 마지막 visible row 수정은 tail patch를 사용한다.
- 세션 저장/자동 백업은 `snapshot_clone()` + streaming JSON writer를 사용하고, recovery state 파일에 최신 복구 가능 스냅샷을 기록한다.
- DB 세션 저장은 `SubtitleEntry`의 `entry_id`/`source_*`/`speaker_*`/timing 메타데이터까지 포함하는 lossless round-trip을 목표로 유지한다.
- `_finalize_subtitle()`는 호환용 entry point로 유지되며, 실제 append/update는 `_add_text_to_subtitles()`와 shared helper를 사용한다.
- 렌더링은 live `SubtitleEntry` 대신 immutable snapshot clone을 사용한다.

### 4.3 예외 처리
- 파일 I/O는 모두 `try-except`로 보호
- WebDriver 연결 실패 시 **지수 백오프로 자동 재연결** (최대 5회)
- 자막 요소 없을 경우 여러 선택자를 순차 시도

### 4.4 설정 영속성
- 저장소 루트는 `development=repo root`, `portable=EXE dir(옆에 portable.flag 존재)`, `frozen default=%LOCALAPPDATA%\AssemblySubtitle\Extractor` 3가지 모드로 고정한다.
- `QSettings`: 기본 Windows 경로를 사용하되, portable 모드에서는 storage root의 `settings.ini`를 사용한다.
- `url_history.json`, `committee_presets.json`, `subtitle_history.db`, `session_recovery.json`, `logs/`, `sessions/`, `backups/`, `realtime_output/`는 모두 storage root 아래에 생성된다.

## 5. 주요 클래스 및 파일 구조

### 5.1 파일 구조
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
    main_window_ui.py          # 공개 UI facade
    main_window_view.py
    main_window_impl/           # capture/pipeline/view/runtime/ui 내부 구현
      ui/                       # tray/menu/layout/theme/history/preset/help UI mixin
    themes.py
    widgets.py
    main_window.py              # MainWindow 파사드
  database.py                   # SQLite DB 호환 shim
  subtitle_extractor.spec   # PyInstaller 빌드 설정
  tests/
    test_encoding_hygiene.py
    test_feature_plan_20260325.py
    test_pyright_regression.py
    test_review_20260323_regressions.py
    test_session_resilience.py
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

### 5.2 주요 클래스
| 클래스 | 파일 | 역할 |
|--------|------|------|
| `Config` | core/config.py | 상수 및 기본 설정 값 |
| `ToastWidget` | ui/widgets.py | 비차단 토스트 알림 UI |
| `SubtitleEntry` | core/models.py | 자막 데이터 모델 (타임스탬프 포함) |
| `MainWindow` | ui/main_window.py | 메인 윈도우 파사드 및 lifecycle 조립 |
| `MainWindowHost` | ui/main_window_types.py | 분할된 MainWindow mixin의 공통 `self` 타입 계약 |
| `MainWindowCaptureMixin` | ui/main_window_capture.py | Selenium 수집/재연결/observer 처리 |
| `MainWindowPipelineMixin` | ui/main_window_pipeline.py | live row ledger + subtitle pipeline 연동 |
| `MainWindowPersistenceMixin` | ui/main_window_persistence.py | 공개 facade, 실제 구현은 `ui/main_window_impl/persistence_*`로 분리 |
| `DatabaseManager` | core/database_manager.py | SQLite CRUD 작업 (#26) |

추가 메모
- 공개 import 경로는 유지하지만 capture/pipeline/view/runtime의 실제 구현은 `ui/main_window_impl/`로 이동했습니다.
- `core/live_capture.py`는 facade이고 실제 ledger/model/reconcile 구현은 `core/live_capture_impl/`에 있습니다.
- 내부 모듈은 `ui.main_window_impl.contracts`의 좁은 Protocol을 사용하고, 공개 호환 계약은 `ui.main_window_types.MainWindowHost`로 유지합니다.

### 5.3 핵심 메서드
| 메서드 | 설명 |
|--------|------|
| `_start()` / `_stop()` | 추출 시작/중지 |
| `_extraction_worker()` | 백그라운드 스레드 메인 루프 |
| `_activate_subtitle()` | AI 자막 레이어 활성화 |
| `_process_message_queue()` | bounded queue + stale run filtering 처리 (100ms 주기) |
| `_prepare_preview_raw()` | preview 입력 정규화/게이팅/재동기화 |
| `_extract_stream_delta()` | 직전 raw 대비 증분 추출 fallback |
| `_slice_incremental_part()` | anchor/suffix 기반 증분 추출 fallback |
| `_process_raw_text()` | 스트리밍 자막 Diff/Append 처리 |
| `_build_subtitle_selector_candidates()` | 자막 CSS 선택자 후보 생성/우선순위 정렬 |
| `_read_subtitle_text_by_selectors()` | 선택자 + 프레임 경로 순회 기반 자막 읽기 |
| `_inject_mutation_observer()` | Observer 주입 + 프레임 경로/폴링 브리지 fallback |
| `_join_stream_text()` | 웹 형태에 맞춘 공백/문장부호 보존 결합 |
| `_finalize_subtitle()` | 중지 시 마지막 버퍼 확정 |
| `_drain_pending_previews()` | 종료 직전 preview 큐 소진 |
| `_render_subtitles()` | 자막 화면 렌더링 + 키워드 하이라이트 |
| `_save_in_background()` | 파일 저장 백그라운드 처리 (TXT/SRT/VTT/DOCX/HWPX/HWP/RTF/통계 내보내기, 스레드 추적/종료 대기 연동) |
| `_start_background_thread()` | 공통 백그라운드 스레드 등록/시작 (종료 단계 차단 포함) |
| `_wait_active_background_threads()` | 종료 시 백그라운드 작업(파일/세션/DB) 제한시간 대기 |
| `_wait_active_save_threads()` | 종료 시 저장 스레드 제한시간 대기 |
| `_update_connection_status()` | **연결 상태 UI 업데이트 (#30)** |
| `_generate_smart_filename()` | **자동 파일명 생성 (#28)** |
| `_show_merge_dialog()` | **자막 병합 다이얼로그 (#20, dedupe 모드 포함)** |
| `_show_db_history()` | **세션 히스토리 조회 (#26)** |
| `_show_db_search()` | **자막 통합 검색 (#26)** |

## 6. 최신 변경 요약 (v16.14.7 기준)

### v16.14.7 브라우저 자동 복구 + 내부 구조 분리 정합화 메모
- **Chrome 세션 헬스체크**: Worker가 `window_handles`, `current_url`, script ping 기준으로 브라우저 생존을 확인하고 연속 실패 시 recoverable WebDriver 오류로 승격
- **예외 승격 정리**: observer/probe/frame 순회 경로에서 `invalid session`, `target closed`, `no such window`, `chrome not reachable` 계열 오류를 내부에서 삼키지 않고 재기동 루프로 전달
- **재기동 일관성**: 같은 headless/visible 모드와 마지막 확정 live URL을 우선 재사용하고, 성공 시 `reconnected` 메시지로 UI 상태를 갱신
- **내부 구조 분리**: `ui/main_window_impl/`에 capture/browser/dom/observer, pipeline/state/queue/stream/messages, runtime/state/lifecycle/driver, view/render/search/editing 구현을 분리
- **코어 분리 고도화**: `core/live_capture.py`는 호환 facade로 유지하고, ledger/model/reconcile 구현은 `core/live_capture_impl/`로 이동
- **빌드/문서 동기화**: `subtitle_extractor.spec` hidden import를 내부 모듈 구조에 맞게 확장하고, `.gitignore`는 루트 `*.manifest`, `*.pyz` 산출물까지 무시
- **UI facade 분리**: `ui/main_window_ui.py`는 공개 import와 monkeypatch 표면만 유지하고, tray/menu/layout/theme/status/history/preset/help 책임은 `ui/main_window_impl/ui/` 하위 mixin으로 분리

### v16.14.7 장시간 세션 안정성 후속 보강 메모 (2026-04-05)
- **runtime segmented session**: 장시간 캡처는 `backups/runtime_sessions/<run_id>/manifest.json` + `segment_*.json` + `tail_checkpoint.json`으로 내부 보관하고, 메모리에는 최근 tail만 유지한다.
- **full-session search/render**: inline search와 render는 archived segment + active tail 전체 세션을 기준으로 동작하며, 실행 중 복사는 active tail만 허용하고 중지 후 편집/복사/리플로우는 1회 hydrate 후 기존 경로를 사용한다.
- **single DB worker**: DB history/search/stats/session-save DB write는 요청마다 임시 스레드를 만들지 않고 앱 런타임 전용 `DBWorker`가 직렬 처리하며, 검색/더보기는 request token으로 stale-drop 한다.
- **shutdown diagnostics**: `closeEvent` 장기 대기 시 `계속 기다리기 / 진단 저장 / 강제 종료` modal로 escalation 하고, 진단은 `logs/shutdown_diagnostic_<timestamp>.json`에 background thread/DB worker/runtime archive/message queue/driver/session state를 기록한다.
- **coalesced UI refresh**: `render/count/stats/status/search-count` 요청은 단일 scheduler에 모아 같은 event-loop tick 안에서 한 번만 반영한다.
- **segment locator/cache**: runtime archive는 bisect 가능한 segment locator, render window cache, small segment LRU cache를 사용해 장시간 세션의 archived 접근 비용을 줄인다.
- **debounced full-session search**: inline search는 debounce + revision stale-drop으로 최신 query만 반영하고, segment-local normalized text cache를 재사용한다.
- **streaming save/export**: 세션 저장과 TXT/SRT/VTT/DOCX/HWPX/HWP/RTF/통계 export는 archived segment + active tail iterator를 직접 사용해 full hydrate를 피한다.
- **export path cleanup**: `persistence_exports.py`의 TXT/SRT/VTT/통계 export는 현재 스트리밍 구현만 runtime 경로로 유지하고, 함수 내부 dead legacy branch는 제거해 단일 동작 경로로 맞춘다.
- **LiveBroadcastDialog 네트워크 경로**: daemon fetch thread를 제거하고 `QNetworkAccessManager` + single active reply 구조로 전환했으며, frozen build에서는 `PyQt6.QtNetwork`를 포함하도록 `subtitle_extractor.spec`를 갱신했다.
- **회귀 기준선**: `pytest -q` 146 pass, `pyright` 0 errors.

### v16.14.7 코드 분할 리팩토링 정합화 메모 (2026-04-05)
- **Database facade 슬림화**: `ui/main_window_database.py`는 공개 facade만 남기고 실제 DB worker/task/result 처리 책임은 `ui/main_window_impl/database_worker.py`, dialog/UI 책임은 `ui/main_window_impl/database_dialogs.py`로 이동했다.
- **Persistence facade 슬림화**: `ui/main_window_persistence.py`는 공개 facade만 유지하고 runtime archive는 `persistence_runtime.py`, 세션/복구는 `persistence_session.py`, export는 `persistence_exports.py`, 유틸은 `persistence_tools.py`로 재분리했다.
- **패키징 정합화**: `subtitle_extractor.spec` hidden import에 `ui.main_window_impl.database_*`, `ui.main_window_impl.persistence_*`를 반영해 frozen 빌드에서도 facade 뒤 구현이 누락되지 않도록 맞췄다.
- **빌드 재검증**: `pyinstaller --clean subtitle_extractor.spec`로 `dist/국회의사중계자막추출기 v16.14.7.exe` 빌드를 다시 확인했다.

### v16.14.7 세션 안정성 / 도구 체인 정합화 메모 (2026-04-06)
- **runtime archive lifetime 고정**: 실행 중 수동 `세션 저장`은 runtime archive를 끊지 않고 snapshot-only로 처리한다. 이후 segment flush/search/render/export는 같은 archive를 계속 사용한다.
- **run-scoped background isolation**: runtime flush/checkpoint/recovery write는 `archive_token` + `run_id` + captured path context를 함께 들고 가며, stale completion은 no-op으로 버린다.
- **best-effort recovery salvage**: runtime manifest JSON이 손상돼도 sibling `segment_*.json` + `tail_checkpoint.json`를 스캔해 salvage를 시도하고, 제외된 손상 파일/항목 수를 payload와 UI 요약에 함께 노출한다.
- **metadata / recovery hygiene**: 빈 URL 세션 로드 시 stale `current_url`을 비우고, recovery pointer는 복구 거절/복구 성공 시 즉시 삭제하지 않으며 성공한 JSON 저장 또는 정상 종료에서만 정리한다.
- **Pylance/Pyright 고정**: `pyrightconfig.json`은 `stubPath=typings`, `executionEnvironments[].extraPaths=["typings"]`, `.pytest_tmp` exclude, `reportMissingModuleSource=none`를 사용하고, `.vscode/settings.json`도 같은 기준으로 맞췄다.
- **로컬 stub 보강**: `typings/PyQt6/QtNetwork.pyi`를 추가해 `LiveBroadcastDialog`의 `QNetworkAccessManager` 경로까지 CLI `pyright`와 Pylance가 같은 결과를 낸다.
- **회귀 기준선**: `pytest -q` 158 pass, `pyright --outputjson` 0 errors / 0 warnings.

### v16.14.7 저장소 / 세션 안전성 보강 메모 (2026-04-08)
- **storage root 분리**: frozen 기본 저장소는 `%LOCALAPPDATA%\AssemblySubtitle\Extractor`로 이동하고, EXE 옆 `portable.flag`가 있으면 로그/세션/DB/설정(`settings.ini`)을 EXE 폴더에 저장한다.
- **startup preflight**: 앱 시작 전 storage preflight로 `logs/`, `sessions/`, `backups/`, `runtime_sessions/`, DB 경로 생성/쓰기 가능 여부를 검증하고 실패 시 UI 조립 전에 중단한다.
- **dirty-save deferred action**: `종료`, `세션 불러오기`, `DB 세션 로드`, `세션 병합`은 `저장 후 원래 액션 재개` 흐름을 공유하고, DB sync save는 timeout 실패를 명시적으로 처리한다.
- **background hydrate**: archived session 편집/삭제/복사/리플로우/병합은 UI 스레드 동기 clone 대신 modal progress/cancel 기반 hydrate worker를 사용한다.
- **live list hardening**: `LiveBroadcastDialog`와 `capture_live`는 `10초` timeout, invalid JSON/schema 구분, malformed row drop, stale reply 무시를 공통 적용한다.
- **live list auto-refresh**: `LiveBroadcastDialog`는 열려 있는 동안 `Config.LIVE_BROADCAST_REFRESH_INTERVAL` 기준 반복 갱신을 유지하고, 종료 시 auto-refresh timer와 active reply를 함께 정리한다.
- **DB lineage**: `sessions`는 `lineage_id`, `parent_session_id`, `is_latest_in_lineage`를 저장하고, 히스토리 다이얼로그에서 `[최신]`, `[이전 저장본 n/N]` 배지로 계보를 노출하며 latest 저장본 삭제 후 남은 계보의 latest를 자동 복구한다.
- **회귀 기준선**: `pytest -q` 179 pass, `pyright --outputjson` 0 errors / 0 warnings.

### v16.14.7 기능 구현 정합성 보강 메모 (2026-04-14)
- **storage preflight v2**: startup preflight는 디렉터리 probe만이 아니라 `subtitle_history.db`, `committee_presets.json`, `url_history.json`, `session_recovery.json`의 실제 파일 surface와 SQLite `PRAGMA journal_mode=WAL`까지 검증한다.
- **shared live list service**: `core/live_list.py`가 `live_list.asp` URL 생성, payload 파싱, row 정규화, 오류 분류, 자동 선택 정책을 담당하고, `LiveBroadcastDialog`와 `capture_live`가 이를 함께 사용한다.
- **안전 우선 자동 선택**: `xcode`가 없고 진행 중인 생중계 후보가 여러 개인 경우 첫 후보를 자동 선택하지 않고 원래 URL을 유지한다. 상태바/토스트는 `생중계 목록`에서 직접 선택하라고 안내한다.
- **DB degraded mode**: `DatabaseManager`는 base schema와 FTS 초기화를 분리하고, `db_available` / `fts_available` / `db_degraded_reason`를 UI에 노출한다. FTS를 쓸 수 없으면 검색은 literal `LIKE`로 fallback하고 DB 액션은 제한 상태에 맞게 비활성화된다.
- **사용자 경고 정합화**: URL 히스토리/프리셋 load-save 실패는 status/toast에도 노출되고, `persistence_exports.py` / `pipeline_messages.py`의 dead branch는 제거되었다.
- **패키징/문서 동기화**: `subtitle_extractor.spec` hidden import에 `core.live_list`를 추가했고, `.gitignore`는 `.storage_probe`를 저장소 전체에서 무시하도록 맞췄다.
- **회귀 기준선**: `pytest -q` 210 pass, `pyright --outputjson` 0 errors / 0 warnings, import smoke 통과, `pyinstaller --clean subtitle_extractor.spec` 빌드 성공.

### v16.14.7 기능 구현 정합성 추가 반영 메모 (2026-04-27)
- **terminal worker event**: fatal worker failure는 `error` 뒤 success `finished`를 중복 발행하지 않고, `finished` payload의 `success/error/finalize_preview`로 단일 종료 상태를 전달한다.
- **Chrome stop policy**: `keep_browser_on_stop` QSettings 옵션은 보기 메뉴 `중지 시 Chrome 창 유지`로 노출한다. 기본값은 `False`이며 수동 중지에만 적용하고 앱 종료/다음 시작 전에는 driver를 종료한다.
- **bounded DB session save**: `DatabaseManager.save_session()`은 subtitle generator를 `tuple()`로 펼치지 않고 chunk insert 후 totals를 update한다. 세션 저장 worker의 DB sync save는 timeout 없이 DB worker 완료를 기다린다.
- **runtime search cancellation**: inline full-session search는 새 query마다 이전 cancel token을 set하고 segment/tail batch 단위로 cancel/revision을 확인한다.
- **settings durability**: portable preflight는 `settings.ini` 파일 surface까지 검증하고, 주요 QSettings 저장은 `setValue -> sync -> status` helper를 통해 실패를 status/toast로 노출한다.
- **stale xcgcd recovery**: 기존 `xcode+xcgcd` URL은 일반 시작에서 자동 감지를 건너뛰되, 재연결 후 selector를 찾지 못한 경우에만 `force_refresh=True`로 live list를 재해결한다.
- **DB history/search policy**: 히스토리는 `ORDER BY created_at DESC, id DESC`, 삭제 후 열린 다이얼로그는 DB 재조회로 badge를 갱신한다. UI DB 검색은 `syntax="literal"`을 명시한다.
- **UI responsibility split**: `ui/main_window_impl/ui/` 패키지에 tray, menus, layout, theme_status, history_presets, runtime_controls, help mixin을 두고 `main_window_ui.py`는 facade로만 유지한다.
- **회귀 기준선**: `pytest -q` 210 pass, `pyright --outputjson` 0 errors / 0 warnings, import smoke 통과, `pyinstaller --clean subtitle_extractor.spec` 빌드 성공.

### v16.14.7 기능 리스크 hardening 메모 (2026-04-29)
- **reset boundary**: `subtitle_reset` grace는 유지하지만 다음 structured preview 처리 전 pending reset을 먼저 커밋해 새 발언자가 이전 entry와 merge되지 않도록 한다.
- **merge suppression**: `source_node_key` mismatch 외에 speaker color/channel mismatch와 container fallback `source_mode`를 merge boundary로 사용한다.
- **observer reset trust**: Observer clear는 구조화 payload를 사용하고 legacy sentinel을 유지한다. `.smi_word` clear만 reset으로 신뢰하며 broad container clear는 probe 재확인으로 제한한다.
- **runtime archive integrity**: segment flush 완료 시 entry fingerprint가 현재 active prefix와 일치할 때만 prefix를 삭제하고, runtime manifest path는 runtime root 내부 relative path만 허용한다.
- **tooling/docs**: `DatabaseManager.checkpoint()` mode whitelist, mojibake docstring 정리, `subtitle_extractor.spec` hidden import와 `.gitignore` build/runtime ignore 규칙 재점검을 반영했다.
- **회귀 기준선**: `pytest -q` 210 pass, `pyright --outputjson` 0 errors / 0 warnings, import/version smoke 통과, `pyinstaller --clean subtitle_extractor.spec` 빌드 성공.

### v16.14.5 UI/UX 운영 정합성 보강 메모
- **run-source 스냅샷 고정**: 캡처 시작 시 URL, 위원회 태그, 헤드리스, 실시간 저장 여부를 고정하고 저장/백업/세션 메타데이터는 이 스냅샷을 기준으로 기록
- **실행 중 옵션 잠금 확대**: URL, 프리셋, 생중계 목록, 태그 편집, 실시간 저장, 헤드리스 모드를 `_sync_runtime_action_state()`로 함께 disable
- **생중계 목록 정책 분리**: 수동 목록은 `생중계`와 `종료/예정`을 모두 보여주되, 자동 감지/URL 보완은 `xstat == "1"` live-only로 제한
- **LiveBroadcastDialog 비차단 종료**: persistent `QThread`를 제거하고 요청당 1회성 fetch + request token으로 다이얼로그 종료 후 늦은 응답을 무시
- **DB/자막 목록 점진 로드**: 세션 히스토리 50건, 자막 검색 100건, 편집/삭제 200개 단위 `더 보기` 로딩과 원본 index 매핑 helper 도입
- **dirty session 종료 기준 정리**: 세션 JSON 저장 성공만 clean으로 간주하고, 종료 프롬프트는 `_session_dirty` + 자막 수 기준으로 `Save / Discard / Cancel` 또는 `Discard / Cancel`을 선택
- **단축키/문서 정렬**: `Escape` 우선순위와 `Ctrl+Shift+C` / `Ctrl+C` 문구를 실제 구현과 맞춤
- **검증 상태**: `pytest -q` 95 pass, `pyright` 0 errors

### v16.14.4 기능 안정화 및 UX 정합성 보강 메모
- **전체 자막 검색 전환**: 검색은 이제 `QTextEdit.toPlainText()`가 아니라 `self.subtitles` 전체 스냅샷을 기준으로 동작하고, `SearchMatch(entry_index, char_start, char_length)`와 `_rendered_entry_text_spans`로 실제 선택 구간을 추적
- **검색 렌더 앵커링**: 최근 500개 tail 렌더 기본값은 유지하되, 검색 중이거나 DB 검색 결과 focus 시 해당 entry가 보이도록 렌더 offset을 동적으로 조정
- **실행 중 상태 변경 차단**: 세션 불러오기/DB 세션 로드/병합/줄넘김 정리/내용 지우기/전체 삭제/편집/삭제를 `_is_runtime_mutation_blocked()`와 `_sync_runtime_action_state()`로 통일
- **세션 로드 payload 통합**: 파일 세션 로드와 DB 세션 로드가 `version`, `url`, `committee_name`, `created_at`, `subtitles`, `skipped`, optional `highlight_sequence`/`highlight_query`를 공유하고 `_complete_loaded_session()`으로 완료 처리
- **DB 검색 결과 액션 강화**: 검색 결과 다이얼로그에서 세션 자체를 로드하거나, 로드 후 `sequence` 기준 해당 자막 위치로 즉시 이동 가능
- **DB 검색 기본 정책**: 기본 검색은 FTS raw 문법이 아니라 literal substring 검색으로 고정하고, 특수문자도 문자 그대로 해석
- **프리셋/저장 정합성**: 프리셋 export/import가 `committee` + `custom` round-trip을 지원하고, add/edit/import는 `http/https` + `assembly.webcast.go.kr` 계열만 허용하며 invalid import 항목은 제외 개수를 요약한다.
- **병합 dedupe 모드 노출**: `보수적(같은 초)`과 `기존(30초 버킷)`을 UI에서 선택 가능하게 정리
- **저장소 hygiene 점검**: `.gitignore`를 재검토해 루트에 실수로 저장된 `세션_*.json` export가 추적되지 않도록 보강
- **검증 상태**: `pytest -q` 85 pass, `pyright` 0 errors

### HWPX 기본 내보내기 추가 메모
- **기본 HWPX export 추가**: `파일 → HWPX 저장` 메뉴와 `core/hwpx_export.py`를 추가해 한컴 미설치 환경에서도 기본 `.hwpx` 문서를 생성할 수 있게 함
- **패키지 구조**: `assets/hwpx/header.xml` 템플릿과 `Contents/section0.xml`, `Preview/PrvText.txt`, `Contents/content.hpf`를 조합해 최소 유효 HWPX 패키지를 작성
- **검증 보강**: HWPX 저장 회귀 테스트와 특수문자/XML escape, 줄바꿈 preview 검증을 추가해 `pytest -q` 85 pass, `pyright` 0 errors 확인
- **multiline 정책**: DOCX/HWPX는 한 `SubtitleEntry`를 한 문단/블록으로 유지하고, 엔트리 내부 개행은 line break로 표현

### v16.14.3 운영 정합성 동기화 메모
- **driver lifecycle 정리**: `self.driver` 접근을 `_driver_lock` + identity helper로 통일해 start/stop/reconnect/finally handoff race를 줄임
- **run-scoped queue 도입**: `MainWindowMessageQueue(maxsize=500)`가 Worker 메시지를 `run_id` envelope로 감싸고 `preview`/`keepalive`/`status`/`resolved_url`를 coalescing
- **subtitle write path 단일화**: `_finalize_subtitle()`가 shared append/merge helper를 사용하도록 정리되고 realtime write/flush는 락 밖으로 이동
- **모델/설정 정합화**: `SubtitleEntry(entry_id=None)` 자동 ID 생성, `공백 기준 단어 수` 문구 고정, `정보위원회`/`NA`/`PP` 기본 코드 제거
- **회귀 테스트 확장**: stale run drop, alert keyword persistence/toast, HWP smoke, SRT/VTT `end_time=None`, auto-backup start rollback 검증 추가
- **도구 체인 고정**: 로컬 `typings/` stub과 `pytest.ini --basetemp=.pytest_tmp`로 글로벌 Python/Windows TEMP 권한 편차를 흡수하고, 루트 `.hwpx` 산출물도 `.gitignore`에 반영
- **HWP 대체 저장 정렬**: `pywin32` 미설치 시 HWP 저장은 즉시 `HWPX`로 자동 대체되고, 저장 실패 경로에서만 RTF/DOCX/TXT 선택 다이얼로그를 유지
- **검증 상태**: `pytest -q` 85 pass, `pyright` 0 errors
### v16.14.2 성능 최적화 중심 리팩토링 메모
- **수집 경로 안정화**: 자막 수집 회귀 대응으로 Worker 캡처 루프는 이전 안정 structured probe 경로로 복귀
- **Pipeline hot path 최적화**: `confirmed_segments` 증분 갱신으로 append/tail update에서 전체 history rebuild를 피함
- **메모리 절감**: `SubtitleEntry.__slots__`, compact cache, `CaptureSessionState.snapshot_clone()`, streaming JSON 저장 적용
- **UI 증분 반영**: `capture_state.entries` 단일화, tail patch render, queue drain time budget(`약 8ms / 최대 50건`) 도입
- **검증 상태**: `commit_live_row` 1,500회 benchmark 약 `10.3초 -> 3.8초`, `pytest -q` 59 pass, `pyright` 0 errors

### 6.0 v16.14.1 자동 줄넘김 정리 기본 활성화 (2026-03-17)
- 메인 옵션 영역에 `✨ 자동 줄넘김 정리` 체크박스를 추가하고 기본값을 활성화
- `QSettings`에 `auto_clean_newlines`를 저장해 재시작 후에도 동일 옵션 유지
- `core/subtitle_pipeline.py`가 preview/live-row/flush 경로에서 동일 설정을 읽어 정규화 동작을 통일
- 옵션이 꺼진 경우 개행을 유지하는 회귀 테스트를 추가해 기본 동작과 옵션 해제를 모두 검증

### 6.1 v16.14.0 크롬 파이프라인 정리 + SOLID 분할 리팩토링 (2026-03-16)
- `ui/main_window.py`를 파사드로 축소하고 capture / pipeline / view / persistence / database / ui mixin으로 분리
- `core/live_capture.py`와 `core/subtitle_pipeline.py`를 운영 기준 코어로 고정하고 row reconciliation + grace reset + prepared snapshot 경로를 유지
- `core/file_io.py`, `core/text_utils.py`, `core/reflow.py`, `core/database_manager.py`를 추가하고 기존 `core/utils.py`, `database.py`는 호환 shim으로 유지
- 테스트 호환을 위해 `MainWindow` 직접 호출 메서드 표면과 import 경로를 유지
- `ui/main_window_types.py`의 `MainWindowHost` 계약, `tests/test_pyright_regression.py`, 확장된 `tests/test_encoding_hygiene.py`로 Pylance/UTF-8 회귀 기준을 고정

### 6.2 수집 정체 완화
- **`.smi_word` 창 수집 보강**: `_read_subtitle_text_by_selectors`가 `.smi_word` 목록 전체를 읽어 최근 텍스트 창을 구성
- **Observer 타겟 우선순위 보강**: `.incont`/`#viewSubtit` 컨테이너를 우선 시도해 DOM 변동에서 수집 연속성 확보

### 6.3 기능 경로 연결 및 안정성 보강
- **`xcgcd` 자동 보완 실연결**: `_detect_live_broadcast`를 워커 시작/재연결 경로 모두에 실제 연결
- **keepalive 경로 활성화**: 동일 raw 유지 구간에서 `("keepalive", raw)` 메시지를 발행해 end_time 주기 갱신
- **finalize dead path 최소 정리**: 미사용 finalize 타이머 경로 정리, 즉시 확정 + keepalive 보정으로 단일화

### 6.4 저장/종료 안정성 강화
- **원자적 텍스트 저장**: `atomic_write_text` 도입으로 TXT/SRT/VTT/RTF 임시파일 교체 저장
- **저장 스레드 종료 대기**: non-daemon 저장 스레드 추적 및 `closeEvent`에서 제한시간 대기
- **로그 경로 정책 통일**: `core/logging_utils.py`가 `Config.LOG_DIR`를 사용하도록 고정

### 6.5 UI/노이즈 품질 보강
- **LiveBroadcastDialog 종료 비차단화**: persistent fetch thread를 제거하고, `done`/`closeEvent`에서는 closing flag + request token만 갱신해 늦은 응답을 무시
- **짧은 발화 허용 + 노이즈 필터**: 한글/영문 1~2자 허용, 숫자/기호-only 문자열 차단

### 6.6 v16.13.2 운영 정합성 업데이트 (2026-03-05)
- **종료 lifecycle 통합**: 파일 저장/세션 저장·불러오기/DB task를 공통 백그라운드 레지스트리로 추적하고 종료 시 drain 대기를 단일화
- **compact 히스토리 상한**: `_confirmed_compact`를 `Config.CONFIRMED_COMPACT_MAX_LEN(50000)`으로 제한해 장시간 세션 메모리 증가를 억제
- **병합 정책 일원화**: 실시간 병합 기준을 Config 상수(`ENTRY_MERGE_MAX_GAP=5`, `ENTRY_MERGE_MAX_CHARS=300`)로 통합
- **세션 병합 dedupe 고도화**: 텍스트-only 제거에서 `정규화 텍스트 + 30초 시간 버킷`(`MERGE_DEDUP_TIME_BUCKET_SECONDS`) 기준으로 전환
- **DB 기본 경로 통일**: `DatabaseManager()` 기본 경로를 `Config.DATABASE_PATH`로 고정

## 6-1. v16.6에서 추가된 기능 (이전)

### 6.1 연결 상태 모니터링 (#30)
- 상태바에 연결 상태 표시: 🟢 연결됨, 🔴 끊김, 🟡 재연결 중
- 툴팁에 응답 시간(latency) 표시
- 5초마다 연결 상태 업데이트

### 6.2 자동 감지 및 재연결 (#31)
- 지수 백오프 알고리즘 (최대 5회 재연결)
- **스마트 `xcgcd` 감지**: `xcode`만 입력해도 `live_list.asp` API 및 페이지 분석을 통해 생중계 주소 자동 확보
- **연결 지점 명확화**: 감지는 `xcgcd`가 없는 URL에서만 시작/재연결 루프에 연결되며, 기존 `xcgcd`가 있으면 원 URL을 유지
- **리다이렉트 대응**: 메인 페이지로 이동 시 해당 위원회의 '생중계' 버튼 자동 클릭
- **생중계 목록 선택 UI**: '📡 생중계 목록' 버튼을 통해 현재/종료 방송을 함께 확인할 수 있고, `종료/예정` 항목은 확인 후 URL만 채우며 dialog가 열려 있는 동안 목록은 자동 새로고침된다 (`LiveBroadcastDialog`)

### 6.3 자동 파일명 생성 (#28)
- 형식: `{날짜}_{위원회명}_{시간}.확장자`
- 예: `20260122_법제사법위원회_134500.txt`
- TXT/SRT/VTT/DOCX/RTF 저장에 적용 (HWP는 기본 파일명 사용)

### 6.4 SQLite 데이터베이스 (#26)
- `database.py` 모듈의 `DatabaseManager` 클래스
- 세션 저장 시 자동으로 DB에도 저장
- DB load는 JSON 세션과 동일한 메타데이터 fidelity를 목표로 하며, additive migration으로 기존 DB를 확장한다.
- 메뉴: 데이터베이스 → 세션 히스토리 / 자막 검색 / 전체 통계
- DB 검색 결과에서 `세션 불러오기`와 `결과로 이동(sequence focus)`를 지원

### 6.5 자막 병합 (#20)
- 메뉴: 도구 → 자막 병합 (Ctrl+Shift+M)
- 여러 세션 파일을 하나로 병합
- 옵션: 중복 제거, 시간순 정렬, dedupe 기준(`보수적 같은 초` / `기존 30초 버킷`)

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
| HWPX | `.hwpx` | 한글 문서 기본 포맷 (추가 외부 프로그램 불필요) |
| HWP | `.hwp` | 한글 문서 (pywin32/한컴오피스 필요) |
| RTF | `.rtf` | 리치 텍스트 형식 |
| JSON (세션) | `.json` | 전체 세션 복원용 |
| SQLite | `.db` | 데이터베이스 히스토리 |

## 8. 개발 관련 주의사항

### 8.1 의존성 설치
```bash
pip install -r requirements-dev.txt
```

- `requirements-dev.txt`에는 DOCX(`python-docx`)와 HWP(`pywin32`) 저장용 optional 패키지가 함께 정리되어 있음
- HWPX 저장은 기본 내장 기능이며 별도 외부 프로그램이 필요하지 않음

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

### 8.5 개발 품질 게이트
- 정적 분석 기준: 루트 `pyrightconfig.json` 기준으로 `pyright` 실행 시 `0 errors`
- 테스트 기준: 루트에서 `pytest -q` 전체 통과
- pyright 회귀 게이트: `tests/test_pyright_regression.py`가 워크스페이스 전체 `pyright --outputjson` 결과가 `0 errors`인지 확인
- Import smoke check: `python -c "import ui.main_window as m; print(m.MainWindow.__name__)"`
- 인코딩 정책: 소스/문서/`subtitle_extractor.spec`는 UTF-8 without BOM 유지
- 예외: 사용자 TXT 저장/실시간 저장은 Windows 메모장 호환을 위해 `utf-8-sig`를 사용할 수 있음
- VS Code/Pylance는 루트 `pyrightconfig.json`과 `.vscode/settings.json`을 기준으로 동일하게 해석
- `pyrightconfig.json`은 `stubPath=typings`, `executionEnvironments[].extraPaths=["typings"]`, `.pytest_tmp` exclude, `reportMissingModuleSource=none`를 공통 기준으로 사용
- `tests/test_encoding_hygiene.py`는 repo tracked 파일만 검사하고, BOM이 허용되는 `.pytest_tmp` workspace temp 산출물은 제외한다
- Windows PowerShell 5.x 콘솔에서는 UTF-8 without BOM이 깨져 보일 수 있으나 파일 자체는 UTF-8 유지

### 8.6 저장소 기준 파일
- `pyrightconfig.json`: 저장소 공통 타입 체크 기준
- `.vscode/settings.json`: 워크스페이스 Pylance/UTF-8 설정
- `.editorconfig`, `.gitattributes`: 텍스트 파일 인코딩/라인엔딩 기준
- `typings/`: 글로벌 인터프리터 편차를 흡수하는 로컬 PyQt6/selenium/pytest stub
- `pytest.ini`: 워크스페이스 내부 basetemp(`.pytest_tmp`) 강제
- `requirements-dev.txt`: 개발/검증 및 optional export 의존성 기준선
- `ui/main_window_types.py`: 분할된 `MainWindow` mixin의 공통 `self` 타입 계약(`MainWindowHost`)
- `tests/test_encoding_hygiene.py`: UTF-8 without BOM, U+FFFD 금지, 핵심 한글 문자열 round-trip 검증
- `tests/test_hwpx_export.py`: HWPX 패키지 구조, preview 텍스트, XML escape/줄바꿈 회귀 검증
- `tests/test_pyright_regression.py`: 워크스페이스 전체 `pyright --outputjson` 결과가 `0 errors`인지 회귀 검증

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
2. **검증 범위 확장**: `pytest` 회귀 시나리오와 UI/패키징 smoke test를 계속 보강
3. **타입 품질 유지**: 새 코드 추가 시 `pyright 0 errors` 기준 유지
4. **다국어 지원**: i18n 프레임워크 도입
5. ~~설정 UI~~: 메뉴에서 대부분 설정 가능
6. **PyInstaller 패키징**: 릴리스 전 `pyinstaller --clean subtitle_extractor.spec` clean build와 frozen 실행 smoke 확인

## 10-1. v16.12.1 안정화 패치 (2026-02-25)

- **짧은 발화 게이트 보강**: 한글/영문 포함 1~2글자 발화를 수집하고, 기호-only/숫자-only 노이즈를 차단한다.
- **세션 내결함성 강화**: 세션 로드/DB 히스토리 로드/병합에서 손상 항목만 건너뛰고 유효 항목을 유지한다.
- **로그 경로 일관화**: `core/logging_utils.py`가 `Config.LOG_DIR`를 사용하도록 통일했다.

## 11. 자막 수집 알고리즘

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

### v16.12 코어 개선
- **`rfind()` 전환**: suffix가 raw에 여러 번 나타날 때 마지막 위치 기준 추출 (과잉 추출 방지)
- **소프트 리셋 `_soft_resync()`**: desync 시 전체 리셋 대신 최근 5개 자막에서 히스토리 재구성 (대량 중복 방지)
- **MutationObserver 하이브리드**: `_inject_mutation_observer`로 이벤트 기반 캡처 우선, 타겟 미탐색 시 폴링 브리지 fallback 유지

### v16.13 운영 안정화
- **keepalive 메시지 실발행**: 동일 자막 구간의 end_time 갱신 누락 방지
- **짧은 발화 정책 개선**: `is_meaningful_subtitle_text` 기반 의미 텍스트 허용
- **저장 안전성 강화**: `atomic_write_text` + 저장 스레드 종료 대기

### 운영 고정 규칙
- `_process_raw_text`, `_extract_new_part`의 핵심 의미론(글로벌 히스토리 + suffix)은 유지한다.
- `_confirmed_compact`는 상한(`Config.CONFIRMED_COMPACT_MAX_LEN`) 내에서 tail 유지 정책을 따른다.
- 코어 수정 시 `PIPELINE_LOCK.md` §2를 함께 갱신한다.
- 반복/누락 이슈 대응은 아래 레이어에서 우선 수행한다.
  1. Worker 입력 정규화 및 compact 기준 전송 억제
  2. 셀렉터 우선순위/프레임 탐색 경로
  3. `_prepare_preview_raw`의 게이트 임계값/재동기화 정책
  4. `_extract_stream_delta`, `_slice_incremental_part` fallback 조건
  5. `_drain_pending_previews`의 종료 직전 강제 플러시
- 로그 키워드(`preview suffix desync reset`, `소프트 리셋: suffix=`, `MutationObserver 주입 성공`, `MutationObserver 폴링 브리지 활성화`)를 기준으로 동작을 확인한다.

### 과거 시도 및 실패 기록 (참고용)
| 접근법 | 실패 이유 |
|--------|-----------|
| 앵커 기반 | 확정 전까지 앵커가 없어 모든 raw가 delta로 처리됨 |
| 버퍼 비교 (startswith) | 공백/줄바꿈 차이로 매칭 실패 |
| 문장 해시 | 문장이 섞여 들어오면 다른 해시가 됨 |

---

*이 문서는 AI 에이전트의 코드 이해를 돕기 위한 것입니다. 새 세션에서도 이 파일을 참조하면 프로젝트 맥락을 빠르게 파악할 수 있습니다.*
