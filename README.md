# 🏛️ 국회 의사중계 자막 추출기 v16.14.7

국회 의사중계 웹사이트에서 **실시간 AI 자막**을 자동으로 추출하고 저장하는 PyQt6 기반 데스크톱 프로그램입니다.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green)
![Selenium](https://img.shields.io/badge/Automation-Selenium-orange)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

---

## 📋 목차
- [브라우저 자동 복구 + 내부 구조 분리 정합화 (v16.14.7)](#-v16147-브라우저-자동-복구--내부-구조-분리-정합화-2026-04-01)
- [자막 유실 방지 배치 (v16.14.6)](#-v16146-자막-유실-방지-배치-2026-04-01)
- [UI/UX 운영 정합성 보강 (v16.14.5)](#-v16145-uiux-운영-정합성-보강-2026-03-27)
- [기능 안정화 및 UX 정합성 보강 (v16.14.4)](#-v16144-기능-안정화-및-ux-정합성-보강-2026-03-25)
- [운영 정합성 동기화 (v16.14.3)](#-v16143-운영-정합성-동기화-2026-03-23)
- [성능 최적화 중심 리팩토링 (v16.14.2)](#-v16142-성능-최적화-중심-리팩토링-2026-03-18)
- [자동 줄넘김 정리 기본 활성화 (v16.14.1)](#-v16141-자동-줄넘김-정리-기본-활성화-2026-03-17)
- [크롬 파이프라인 정리 + SOLID 분할 리팩토링 (v16.14.0)](#-v16140-크롬-파이프라인-정리--solid-분할-리팩토링-2026-03-16)
- [운영 정합성 업데이트 (v16.13.2)](#-v16132-운영-정합성-업데이트-2026-03-05)
- [새 기능 (v16.13.1)](#-v16131-새-기능)
- [주요 기능](#-주요-기능)
- [설치 방법](#-설치-방법)
- [사용 방법](#-사용-방법)
- [단축키](#️-단축키)
- [저장 형식](#-저장-형식)
- [상세 기능 설명](#-상세-기능-설명)
- [문제 해결](#-문제-해결)
- [개발 검증](#-개발-검증)
- [빌드 방법](#️-빌드-방법)
- [변경 이력](#-변경-이력)
- [파이프라인 고정 문서](#-파이프라인-고정-문서)

---

## ✨ v16.14.7 브라우저 자동 복구 + 내부 구조 분리 정합화 (2026-04-01)

### 🛡️ Chrome 세션 자동 복구
- Worker가 `window_handles`, `current_url`, `execute_script("return 1")` 기준으로 브라우저 생존을 주기적으로 점검하고, 연속 실패 시 recoverable WebDriver 오류로 승격합니다.
- observer/probe/frame 순회 경로에서 `invalid session`, `target closed`, `no such window`, `chrome not reachable` 계열 예외를 더 이상 내부에서 묻지 않고 재기동 루프로 올립니다.
- 재연결 성공 시 같은 headless/visible 모드와 마지막 확정 live URL로 크롬을 다시 띄우고, UI에는 `reconnected` 상태를 명시적으로 반영합니다.

### 🧩 내부 구현 구조 정리
- 공개 import 경로(`ui.main_window`, `ui.main_window_capture`, `ui.main_window_pipeline`, `ui.main_window_view`, `core.live_capture`)는 그대로 유지하고, 실제 구현은 `ui/main_window_impl/`와 `core/live_capture_impl/`로 분리했습니다.
- `ui/main_window_impl/`는 capture/browser/dom/observer, pipeline/state/queue/stream/messages, runtime/state/lifecycle/driver, view/render/search/editing 책임을 나눠 `MainWindow`의 직접 의존을 줄였습니다.
- `ui/main_window_database.py`와 `ui/main_window_persistence.py`는 공개 facade 겸 조합 레이어만 유지하고, 실제 DB worker/dialog 책임은 `ui/main_window_impl/database_*.py`, runtime/session/export 책임은 `ui/main_window_impl/persistence_*.py`로 재배치했습니다.
- `core/live_capture.py`는 호환 facade로 유지하고, ledger/model/reconcile 구현은 `core/live_capture_impl/`로 이동했습니다.
- `ui/main_window_ui.py`는 공개 UI facade만 유지하고, 실제 tray/menu/layout/theme/status/history/preset/help 책임은 `ui/main_window_impl/ui/` 하위 mixin으로 분리했습니다.

### 📦 문서 / 빌드 / 저장소 정합성
- `subtitle_extractor.spec`는 `ui.main_window_impl.*`, `ui.main_window_impl.ui.*`, `ui.main_window_impl.database_*`, `ui.main_window_impl.persistence_*`, `core.live_capture_impl.*` hidden import를 명시해 frozen 빌드에서 facade 뒤 구현 모듈이 누락되지 않도록 맞췄습니다.
- `README.md`, `CLAUDE.md`, `GEMINI.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`를 현재 구조와 버전(`v16.14.7`) 기준으로 동기화했습니다.
- `.gitignore`는 PyInstaller 빌드 중 루트에 남을 수 있는 보조 산출물(`*.manifest`, `*.pyz`)까지 무시하도록 보강했습니다.

### ✅ 현재 검증 상태
- `pytest -q tests/test_review_20260323_regressions.py tests/test_live_capture.py tests/test_worker_stability.py tests/test_worker_probe_payload.py tests/test_feature_plan_20260325.py tests/test_ui_ux_plan_20260327.py tests/test_lossless_session_plan_20260401.py tests/test_compat_imports.py tests/test_pyright_regression.py`: `51 passed`
- import smoke: `MainWindow`, `reconcile_live_capture` 공개 경로 확인
- `pyinstaller --clean subtitle_extractor.spec`: 빌드 성공 (`dist/국회의사중계자막추출기 v16.14.7.exe`)

### ⏱️ 장시간 세션 안정성 후속 보강 (2026-04-05)
- `backups/runtime_sessions/<run_id>/manifest.json` + `segment_*.json` + `tail_checkpoint.json` 기반 runtime archive를 추가해 장시간 캡처에서도 메모리에는 최근 tail만 유지합니다.
- 실행 중 inline search와 render는 archived segment + active tail 전체 세션을 기준으로 동작하고, 중지 후 편집/복사/리플로우가 필요하면 한 번 full hydrate 후 기존 편집 경로를 그대로 사용합니다.
- DB 비동기 작업은 요청마다 임시 스레드를 만들지 않고 앱 런타임 전용 `DBWorker`가 직렬 처리하며, 검색/더보기 결과는 request token으로 stale-drop 됩니다.
- `closeEvent` 장기 대기 시 `계속 기다리기 / 진단 저장 / 강제 종료` escalation modal을 띄우고, 진단은 `logs/shutdown_diagnostic_<timestamp>.json`에 저장합니다.
- `LiveBroadcastDialog`는 daemon fetch thread 대신 `QNetworkAccessManager` + single active reply 구조를 사용하고, `subtitle_extractor.spec`도 `PyQt6.QtNetwork`를 포함하도록 갱신했습니다.
- UI 갱신은 `render/count/stats/status/search-count` 단위의 coalescing scheduler로 묶여 같은 이벤트 루프 tick 안의 중복 repaint를 1회로 합칩니다.
- runtime archive는 segment locator + render window cache + small segment LRU cache를 사용해 장시간 세션에서 동일 window 재렌더와 archived 검색 비용을 줄입니다.
- inline search는 debounce + revision stale-drop을 사용하고, archived segment별 normalized text cache를 재사용해 연속 검색 입력 비용을 줄입니다.
- 세션 저장/TXT/SRT/VTT/DOCX/HWPX/HWP/RTF/통계 export는 archived segment + active tail iterator를 직접 사용해 full-session hydrate 없이 스트리밍 처리합니다.
- 당시 기준선: `pytest -q` `146 passed`, `pyright` `0 errors`.

### 💾 저장소 / 세션 안전성 보강 (2026-04-08)
- frozen 기본 저장소는 `%LOCALAPPDATA%\AssemblySubtitle\Extractor`로 분리했고, EXE 옆 `portable.flag`가 있으면 로그/세션/DB/설정(`settings.ini`)을 EXE 폴더 기준으로 저장합니다.
- 앱 시작 전에 storage preflight를 수행해 `logs/`, `sessions/`, `backups/`, `runtime_sessions/`, DB 경로 생성/쓰기 가능 여부를 먼저 검증하고, 실패 시 UI 조립 전에 blocking 오류로 중단합니다.
- dirty 세션 보호는 `저장 후 원래 액션 재개` 구조로 바뀌어 `종료`, `세션 불러오기`, `DB 세션 로드`, `세션 병합`에서 JSON+DB 저장이 끝난 뒤에만 후속 동작이 이어집니다.
- 장시간 세션 hydrate는 UI 스레드 동기 clone 대신 background worker + modal progress/cancel로 전환되어 편집/삭제/복사/리플로우/병합 시 장시간 정지가 줄었습니다.
- `LiveBroadcastDialog`와 `live_list` 보완 경로는 `10초` timeout, invalid JSON/schema 구분, row 단위 drop, stale reply 무시를 공통으로 적용합니다.
- `LiveBroadcastDialog`는 열려 있는 동안 `30초`마다 목록을 자동 갱신하고, 종료 시 auto-refresh timer와 in-flight reply를 함께 정리합니다.
- DB `sessions` 테이블은 `lineage_id`, `parent_session_id`, `is_latest_in_lineage`를 유지하고, 히스토리 다이얼로그에서 `[최신]`, `[이전 저장본 n/N]` 배지로 같은 세션 계보를 바로 확인할 수 있으며, 최신 저장본 삭제 뒤에도 남은 세션 계보의 latest가 자동 재정렬되도록 보장합니다.
- 당시 기준선: `pytest -q` `179 passed`, `pyright` `0 errors`.

### 🧪 기능 구현 정합성 보강 (2026-04-14)
- storage preflight는 이제 디렉터리 probe에서 끝나지 않고 `subtitle_history.db`, `committee_presets.json`, `url_history.json`, `session_recovery.json`의 실제 생성/교체 가능 여부와 SQLite `PRAGMA journal_mode=WAL`까지 확인합니다.
- `core/live_list.py`를 추가해 `LiveBroadcastDialog`와 자동 URL 보완이 같은 `live_list.asp` URL 생성, payload 파싱, row 정규화, 오류 분류, 자동 선택 정책을 공유합니다.
- `xcode`가 없고 진행 중인 생중계 후보가 여러 개인 경우 더 이상 첫 후보를 자동 선택하지 않고, 원래 URL을 유지한 채 상태바/토스트로 수동 선택을 유도합니다.
- DB 초기화는 base schema와 FTS를 분리해 처리하며, `db_available`, `fts_available`, `db_degraded_reason` 상태를 UI에 노출합니다. FTS를 쓸 수 없으면 검색은 literal `LIKE`로 fallback되고, DB 기능 버튼은 제한 상태에 맞게 비활성화됩니다.
- `ui/main_window_impl/persistence_exports.py`와 `ui/main_window_impl/pipeline_messages.py`의 dead branch를 정리했고, URL 히스토리/프리셋 load-save 실패는 더 이상 로그에만 남기지 않고 사용자 경고로도 노출합니다.
- `subtitle_extractor.spec`, `README.md`, `CLAUDE.md`, `GEMINI.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`, `.gitignore`를 이번 배치 기준으로 다시 맞췄습니다.
- 현재 전체 기준선: `pytest -q` `187 passed`, `python -m pyright --outputjson` `0 errors / 0 warnings`, `pyinstaller --clean subtitle_extractor.spec` 빌드 성공.

### 🧪 기능 구현 정합성 보강 추가 반영 (2026-04-27)
- Worker 종료는 `finished` terminal payload(`success`, `error`, `finalize_preview`)로 통일되어 fatal 실패가 성공 완료 문구로 덮이지 않습니다.
- 보기 메뉴의 `중지 시 Chrome 창 유지` 옵션은 수동 중지에만 적용되며 기본값은 꺼짐입니다. 앱 종료 또는 다음 추출 시작 전에는 남아 있는 Chrome driver를 정리합니다.
- DB 세션 저장은 generator를 전체 materialize하지 않고 세션 row 생성 후 자막 row를 chunk insert하고 totals를 갱신합니다. 세션 저장 worker의 DB 저장은 timeout 없이 완료를 기다립니다.
- runtime 전체 검색은 새 검색마다 이전 검색 cancel token을 set하고, segment/tail batch 단위로 stale 작업을 중단합니다.
- portable preflight는 `settings.ini` 파일 surface까지 확인하고, 주요 QSettings 저장 경로는 `sync/status` 실패를 상태바/토스트 경고로 노출합니다.
- stale `xcgcd` URL 재연결 후 자막 selector를 찾지 못하면 그때만 live list를 강제 재해결합니다.
- DB 히스토리는 `created_at DESC, id DESC`로 정렬하고, 삭제 후 열린 히스토리 다이얼로그는 DB 재조회로 lineage badge를 다시 렌더합니다.
- UI DB 검색은 명시적으로 literal 부분문자열 검색을 요청하며, FTS는 선택 확장/fallback 기반으로만 유지합니다.
- UI 구현은 `ui/main_window_ui.py` facade 뒤로 `tray`, `menus`, `layout`, `theme_status`, `history_presets`, `runtime_controls`, `help` 모듈을 분리해 메뉴/상태/프리셋/도움말 책임을 독립 mixin으로 유지합니다.
- 현재 검증: `pytest -q` `200 passed`, `python -m pyright --outputjson` `0 errors / 0 warnings`, `pyinstaller --clean subtitle_extractor.spec` 빌드 성공.

### 🧱 코드 분할 리팩토링 정합화 (2026-04-05)
- `ui/main_window_database.py`는 facade만 남기고 `database_worker.py` / `database_dialogs.py` 조합으로 분리해 DB 실행 경로와 다이얼로그 UI 경로를 분리했습니다.
- `ui/main_window_persistence.py`는 facade만 남기고 `persistence_runtime.py` / `persistence_session.py` / `persistence_exports.py` / `persistence_tools.py`로 나눠 runtime archive, 세션/복구, export, 유틸 책임을 구분했습니다.
- 공개 import 경로와 테스트의 monkeypatch 경로는 유지해 외부 호출 지점을 깨지 않으면서 긴 파일을 줄였습니다.
- `pyinstaller --clean subtitle_extractor.spec`를 다시 검증했고, `dist/국회의사중계자막추출기 v16.14.7.exe` 빌드가 성공했습니다.

### 🧱 세션 안정성 / 타입·인코딩 위생 보강 (2026-04-06)
- 실행 중 수동 `세션 저장`은 더 이상 현재 run의 runtime archive를 정리하지 않으며, 같은 archive가 이후 segment flush/search/render/export까지 계속 이어집니다.
- runtime archive background 작업은 `archive_token` + `run_id`를 함께 캡처해, `stop -> start` 경계에서 늦게 도착한 flush 완료/실패와 recovery snapshot write가 새 run 상태를 오염시키지 않도록 고정했습니다.
- runtime manifest 복구는 file-level best-effort salvage로 바뀌어 segment/checkpoint 일부 손상이나 manifest JSON 손상 시에도 sibling `segment_*.json` + `tail_checkpoint.json` 기준으로 복구를 시도하고, 제외된 손상 파일/항목 수를 사용자 요약에 표시합니다.
- 빈 URL 세션 로드 시 stale `current_url`과 URL 입력 UI를 명시적으로 비우고, recovery pointer는 복구 거절/복구 성공 시 즉시 지우지 않으며 성공한 JSON 세션 저장 또는 정상 종료에서만 정리합니다.
- `pyrightconfig.json`과 `.vscode/settings.json`은 `typings/`를 `stubPath`/`extraPaths`로 명시하고 `.pytest_tmp`를 분석 범위에서 제외하며, 로컬 stub 환경의 `reportMissingModuleSource` 경고를 끄도록 동기화했습니다.
- `typings/PyQt6/QtNetwork.pyi`를 추가해 `LiveBroadcastDialog`의 `QNetworkAccessManager` 경로까지 CLI `pyright`와 Pylance에서 동일하게 해석됩니다.
- 당시 기준선: `pytest -q` `158 passed`, `pyright --outputjson` `0 errors / 0 warnings`.

## ✨ v16.14.6 자막 유실 방지 배치 (2026-04-01)

### 🛡️ 세션 / 복구
- 수동 세션 저장과 종료 직전 저장 모두 `JSON + DB` 경로를 사용하고, 성공한 세션 저장/자동 백업은 `session_recovery.json`에 최신 복구 가능 스냅샷 메타데이터를 기록합니다.
- 시작 시 복구 state가 남아 있으면 최신 자동 백업 또는 세션 저장본을 제안하고, 복구된 세션은 다시 저장 전까지 dirty 상태로 유지합니다.

### 🧾 Reflow / DB
- 수동 `줄넘김 정리`는 pending preview까지 포함한 prepared snapshot 기준으로 백그라운드 reflow를 수행하며, `SubtitleEntry`의 `entry_id`/`source_*`/`speaker_*`/timing 정책을 보존합니다.
- `DatabaseManager`는 additive migration으로 lossless subtitle metadata를 저장/복원하고, 기본 검색은 FTS raw query가 아니라 literal substring 검색으로 동작합니다.

### 📄 Export / 저장소 hygiene
- DOCX/HWPX는 한 `SubtitleEntry`를 한 문단/블록으로 유지하고, 엔트리 내부 개행은 paragraph split이 아니라 line break로 저장합니다.
- `.gitignore`는 `session_recovery.json` 같은 런타임 복구 state를 무시하고, `subtitle_extractor.spec`은 이 state가 frozen 번들에 포함되지 않음을 명시합니다.

## ✨ v16.14.5 UI/UX 운영 정합성 보강 (2026-03-27)

### 🎛️ 실행 중 상태 고정
- 캡처 시작 시 URL, 위원회 태그, 헤드리스, 실시간 저장 여부를 `run-source` 스냅샷으로 고정합니다.
- 추출 중에는 URL, 프리셋, 생중계 목록, 태그 편집, 실시간 저장, 헤드리스 모드를 모두 잠그고, 저장/자동백업/세션 JSON 메타데이터도 현재 UI가 아니라 시작 시점 스냅샷을 기준으로 기록합니다.
- URL 히스토리는 MRU 순서로 갱신되어, 이미 쓴 URL을 다시 선택하면 목록 맨 뒤 최신 항목으로 재배치됩니다.

### 📡 생중계 선택 정책 정리
- 생중계 목록은 `생중계`와 `종료/예정`을 함께 보여주되, live 항목을 항상 우선 정렬합니다.
- `종료/예정` 항목은 즉시 실행하지 않고 확인 후 URL만 채웁니다.
- 자동 감지 및 `live_list.asp` 기반 URL 보완은 `xstat == "1"`인 실제 live 항목만 사용합니다.
- `LiveBroadcastDialog`는 persistent fetch thread를 제거하고, 요청당 1회성 백그라운드 fetch + request token으로 늦게 도착한 응답을 무시합니다.
- `LiveBroadcastDialog`를 열어둔 동안 목록은 `30초` 간격으로 자동 새로고침됩니다.

### 🗄️ 대용량 목록 / 세션 종료 UX
- DB 세션 히스토리는 50건, 자막 검색은 100건, 자막 편집/삭제 다이얼로그는 200개 단위로 `더 보기` 점진 로드를 사용합니다.
- 편집/삭제 다이얼로그는 원본 subtitle index를 유지하는 검색형 목록으로 바뀌어, 필터링 후에도 정확한 항목을 수정/삭제합니다.
- 세션 dirty tracking을 추가해 종료 프롬프트는 단순 자막 개수가 아니라 실제 미저장 세션 변경 여부를 기준으로 판단합니다.
- 세션 JSON 저장 성공만 clean으로 간주하고, TXT/SRT/VTT/DOCX/HWP/HWPX/RTF/통계 export는 dirty를 유지합니다.

### ⌨️ 단축키 / 문서 / 빌드 정합성
- `Escape`는 검색창이 열려 있으면 닫기, 아니면 실행 중일 때만 추출 중지로 동작합니다.
- 전체 자막 복사는 `Ctrl+Shift+C`, `Ctrl+C`는 `QTextEdit`의 선택 복사로 문서와 실제 동작을 일치시켰습니다.
- `subtitle_extractor.spec`, `README.md`, `CLAUDE.md`, `GEMINI.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`, `FEATURE_IMPLEMENTATION_REVIEW_20260325.md`, `.gitignore`를 `v16.14.5` 기준으로 다시 점검했습니다.

### ✅ 현재 검증 상태
- `pytest -q`: `95 passed`
- `pyright --outputjson`: `0 errors`

---

## ✨ v16.14.4 기능 안정화 및 UX 정합성 보강 (2026-03-25)

### 🔍 검색 / 렌더 정합성
- 검색은 더 이상 현재 `QTextEdit`에 렌더된 최근 500개만 보지 않고, `self.subtitles` 전체 스냅샷을 기준으로 동작합니다.
- 검색 결과 이동 시 해당 자막이 포함되도록 렌더 윈도우를 동적으로 재배치하고, 문서상 텍스트 span을 기준으로 실제 매치 구간을 선택합니다.
- 검색을 닫으면 렌더링은 다시 기본 tail 모드(`MAX_RENDER_ENTRIES=500`)로 복귀합니다.

### 🛡️ 실행 중 상태 변경 차단
- 추출 중에는 세션 불러오기, DB 세션 불러오기, 병합, 줄넘김 정리, 내용 지우기, 전체 삭제, 편집, 삭제를 공통 가드로 차단합니다.
- 메뉴/툴바의 관련 액션은 `_sync_runtime_action_state()`로 일괄 disable 되어, "동작은 눌리지만 나중에 꼬이는" 상태를 줄였습니다.

### 🗄️ 세션 / DB / 프리셋 정합성
- 파일 세션 로드와 DB 세션 로드가 동일 payload(`version`, `url`, `committee_name`, `created_at`, `subtitles`, `skipped`)와 동일 완료 핸들러를 사용합니다.
- DB 자막 검색 결과는 이제 "세션 불러오기"와 "결과로 이동"을 지원하며, `sequence` 기준으로 원문 위치를 복원합니다.
- 프리셋 export/import는 `committee`와 `custom`을 모두 round-trip하고, import 시 동일 키는 가져온 값으로 overwrite 합니다.
- 프리셋 add/edit/import는 `http/https`이면서 `assembly.webcast.go.kr` 계열 URL만 허용하고, invalid import 항목은 건너뛴 뒤 제외 개수를 요약합니다.

### 💾 저장 / 병합 정책
- 통계 export는 `atomic_write_text`, 프리셋 export는 `atomic_write_json`으로 통일했습니다.
- 자막 병합은 dedupe 모드를 노출합니다.
  - `보수적`: 같은 초 + 동일 정규화 문장
  - `기존`: 30초 버킷 + 동일 정규화 문장
- `.gitignore`는 검토 후 루트에 실수로 저장된 `세션_*.json` export가 추적되지 않도록 보강했습니다.

## ✨ v16.14.3 운영 정합성 동기화 (2026-03-23)

### 🔒 Worker lifecycle / queue 정리
- `self.driver` 접근을 `_driver_lock`과 identity helper로 일원화해 시작/중지/재연결/worker finally 간 handoff race를 줄였습니다.
- Worker 메시지는 `MainWindowMessageQueue(maxsize=500)`를 통해 내부 `run_id` envelope로 감싸고, `preview`/`keepalive`/`status`/`resolved_url`는 latest-value coalescing으로 처리합니다.
- stop timeout 뒤에는 해당 run을 즉시 inactive 처리해 늦게 도착한 stale worker 메시지가 새 세션 상태를 오염시키지 못하게 했습니다.
- `xcgcd`가 없는 URL은 시작 시 1회만 자동 감지하고, 재연결에서는 이미 확정한 live URL을 우선 재사용합니다.

### 🧾 자막 경로 / 렌더 정합성
- `_finalize_subtitle`는 호환용 진입점으로 유지하되, 실제 append/update는 파이프라인과 동일한 shared helper를 사용해 중복 append를 막습니다.
- `subtitle_lock` 범위는 상태 계산과 append/update까지만 유지하고, realtime 파일 쓰기/flush, 토스트, UI refresh는 락 밖으로 이동했습니다.
- 렌더링은 live `SubtitleEntry` 객체 대신 immutable snapshot clone을 사용하며, `SubtitleEntry(entry_id=None)`는 런타임에서 항상 ID를 생성합니다.

### ⚙️ 설정 / 저장 / 회귀 테스트
- 확인되지 않은 `정보위원회`, `NA`, `PP` 기본 프리셋/매핑은 제거하고, 현재 기본 특별 코드 목록은 검증된 `IO`만 유지합니다.
- 통계/내보내기/UI의 단어 수 표기는 모두 `공백 기준 단어 수`로 명시해 형태소 통계처럼 오해되지 않도록 정리했습니다.
- 회귀 테스트 범위를 stale run drop, `alert_keywords` 저장/토스트, SRT/VTT `end_time=None`, HWP mock smoke, auto-backup start rollback까지 확장했습니다.
- 로컬 `typings/`에 `PyQt6`/`selenium`/`pytest` 최소 stub을 추가하고 `pytest.ini`를 `--basetemp=.pytest_tmp`로 고정해 Windows 글로벌 Python 환경에서도 `pyright`와 전체 테스트 경로를 안정화했습니다.
- `ui/main_window_types.py`의 `_save_hwpx` 중복 선언을 제거하고, `pywin32` 미설치 시 HWP 저장이 `HWPX`로 자동 대체되는 현재 동작에 맞춰 회귀 테스트와 `.gitignore`의 루트 `.hwpx` 무시 규칙을 정리했습니다.

### ✅ 현재 검증 상태
- `pytest -q`: `76 passed`
- `pyright`: `0 errors`
- `subtitle_extractor.spec`, `README.md`, `CLAUDE.md`, `GEMINI.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`를 `v16.14.3` 기준으로 동기화했습니다.

---

## ✨ v16.14.2 성능 최적화 중심 리팩토링 (2026-03-18)

### ⚙️ 수집 경로 안정화
- 자막 수집 경로는 회귀 이슈 대응을 위해 이전 안정 structured probe 루프로 복귀했습니다.
- `MutationObserver` 우선 + structured probe fallback, `.smi_word` 창 수집, iframe/frame 순회, keepalive 동작은 유지합니다.
- 수집 외 파이프라인/메모리/UI 최적화는 그대로 유지합니다.

### 🧠 파이프라인 / 메모리 최적화
- `core/subtitle_pipeline.py`는 `confirmed_segments` 기반 증분 갱신으로 hot path append/tail update에서 전체 history rebuild를 피합니다.
- `SubtitleEntry`는 `__slots__` + compact cache를 사용하고, `CaptureSessionState.snapshot_clone()`은 no-preview 경로에서 기존 엔트리를 재복제하지 않습니다.
- 세션 저장/자동 백업은 `atomic_write_json_stream()`으로 JSON 배열을 스트리밍 저장하고, DB 저장도 `SubtitleEntry`의 `entry_id`/`source_*`/`speaker_*`/timing 메타데이터를 함께 보존하는 lossless 경로로 동작합니다.

### 🖥️ UI 체감 성능 개선
- `capture_state.entries`를 단일 source of truth로 두고 `self.subtitles`는 alias로 유지합니다.
- append/tail update는 `PipelineResult` delta 기반으로 통계/카운트/렌더링을 증분 반영하고, 마지막 visible entry 수정은 full clear 대신 tail patch를 사용합니다.
- queue drain은 고정 10건 대신 `약 8ms` 예산과 `최대 50건` cap으로 처리해 burst backlog를 줄였습니다.

### ✅ 현재 검증 상태
- `commit_live_row` 1,500회 benchmark: 약 `10.3초 -> 3.8초`
- `pytest -q`: `63 passed`
- `pyright --outputjson`: `0 errors`
- `subtitle_extractor.spec`, `README.md`, `CLAUDE.md`, `GEMINI.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`를 `v16.14.2` 기준으로 동기화했습니다.
- PyInstaller hidden import 목록을 현재 분할 구조와 optional import 경로 기준으로 재점검했습니다.

---

## ✨ v16.14.1 자동 줄넘김 정리 기본 활성화 (2026-03-17)

### 🧹 수집 중 자동 줄넘김 정리 옵션 추가
- 메인 옵션 영역에 `✨ 자동 줄넘김 정리` 체크박스를 추가하고, 기본값을 활성화(`ON`)로 설정했습니다.
- 줄바꿈/빈 줄은 자동으로 한 줄로 정리하되 자막 내용은 유지합니다.
- 설정은 `QSettings`에 저장되어 다음 실행에도 그대로 유지됩니다.

### 🔁 파이프라인 정규화 옵션화
- `core/subtitle_pipeline.py`는 `auto_clean_newlines` 설정값을 읽어 preview/live-row/flush 경로 정규화를 동일하게 적용합니다.
- 옵션을 끄면 기존처럼 개행을 유지한 raw 텍스트 흐름으로 수집할 수 있습니다.
- 수동 `줄넘김 정리`는 pending preview를 포함한 prepared snapshot 기준으로 백그라운드 reflow를 수행하며, `SubtitleEntry` 메타데이터와 timing 정책을 유지합니다.

### 🧪 문서/빌드 정합성 보강
- `subtitle_extractor.spec`, `README.md`, `CLAUDE.md`, `GEMINI.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`를 `v16.14.1` 기준으로 동기화했습니다.
- `.gitignore`에 PyInstaller 패키지 산출물(`*.pkg`) 무시 규칙을 추가했습니다.

---

## ✨ v16.14.0 크롬 파이프라인 정리 + SOLID 분할 리팩토링 (2026-03-16)

### 🧩 크롬 확장 자막 알고리즘 구조 고정
- `core/live_capture.py`와 `core/subtitle_pipeline.py`를 기준 코어로 유지하고, `framePath::nodeKey` 기반 row reconciliation, grace reset, prepared snapshot 저장 경로를 운영 기본값으로 고정했습니다.
- 같은 화면 row 수정은 기존 엔트리를 제자리 업데이트하고, preview-only 자막도 TXT/SRT/VTT/세션 저장 직전에 공통 snapshot 경로로 materialize합니다.

### 🏗️ MainWindow 책임 분할
- `ui/main_window.py`는 파사드 역할만 담당하고, 실제 구현은 `ui/main_window_ui.py`, `ui/main_window_capture.py`, `ui/main_window_pipeline.py`, `ui/main_window_view.py`, `ui/main_window_persistence.py`, `ui/main_window_database.py`로 분리했습니다.
- `ui/main_window_types.py`의 `MainWindowHost` 계약으로 분할된 mixin의 공통 `self` 타입을 고정해 Pylance/Pyright 진단 기준을 안정화했습니다.
- 직접 호출되던 `MainWindow` 메서드 표면은 유지해 기존 테스트와 엔트리포인트 import 경로를 깨지 않도록 정리했습니다.

### 🧰 코어/호환 계층 정리
- `core/file_io.py`, `core/text_utils.py`, `core/reflow.py`, `core/database_manager.py`를 추가하고, `core/utils.py`, `database.py`는 호환용 shim으로 유지했습니다.
- `subtitle_extractor.spec`는 새 모듈 구조를 hidden import에 반영하고, 빌드 버전 기본값을 `v16.14.0`으로 동기화했습니다.
- `tests/test_pyright_regression.py`와 확장된 `tests/test_encoding_hygiene.py`로 `pyright 0 errors`와 핵심 한글 문자열 UTF-8 round-trip을 회귀 검증합니다.

## ✨ v16.13.1 새 기능 (Hot!)

### 🧩 첫 문장 이후 정체 완화 (수집 경로 보강)
- `.smi_word:last-child` 단일 노드 의존을 줄이고, `.smi_word` 목록 전체를 수집해 최근 창(window) 텍스트를 조합하도록 보강했습니다.
- Observer 타겟 선택 시 `#viewSubtit .incont`, `#viewSubtit` 같은 컨테이너를 우선 시도해 사이트 DOM 변동에서 수집 정체를 줄였습니다.
- 긴 컨테이너 텍스트는 최근 라인 중심으로 축약해 버퍼 과대 입력으로 인한 게이트 정체를 완화했습니다.

---

## ✨ v16.13.2 운영 정합성 업데이트 (2026-03-05)

### 🔒 종료 lifecycle 통합
- 파일 저장/세션 저장·불러오기/DB 비동기 작업을 공통 백그라운드 레지스트리로 추적합니다.
- `closeEvent`에서 `신규 작업 차단 → inflight 대기 → 자원 정리` 순서로 종료하여 종료 시점 데이터 유실 위험을 줄였습니다.

### 🧠 스트리밍 히스토리 메모리 상한
- `_confirmed_compact` 누적 버퍼에 상한(`Config.CONFIRMED_COMPACT_MAX_LEN=50000`)을 적용했습니다.
- suffix 기반 코어 의미론은 유지하면서 tail만 보존해 장시간 세션 메모리 증가를 억제합니다.

### 📎 병합 정책 정합성
- 실시간 병합 기준을 Config 상수로 일원화했습니다 (`ENTRY_MERGE_MAX_GAP=5`, `ENTRY_MERGE_MAX_CHARS=300`).
- 세션 병합 중복 제거를 텍스트-only에서 `정규화 텍스트 + 시간 버킷(30초)` 기준으로 개선했습니다.

### 🗄️ DB 경로 정책 통일
- `DatabaseManager()` 기본 경로를 앱 기준 `Config.DATABASE_PATH`로 통일해 실행 위치(CWD) 의존성을 제거했습니다.

---

## ✨ v16.13 운영 안정화

### 🧭 생중계 URL 자동 보완 경로 실연결
- `_detect_live_broadcast`가 워커 시작 직후와 재연결 경로 모두에서 실제 호출됩니다.
- `xcode-only` URL에서도 `xcgcd`를 자동 보완해 동일한 수집 경로로 재진입합니다.

### ⏱️ keepalive 기반 end_time 보정 활성화
- 동일 자막 유지 구간에서 `keepalive` 메시지를 주기 발행해 마지막 엔트리 `end_time`을 갱신합니다.
- 기존 미사용 finalize 타이머 경로를 정리해 스트리밍 확정 정책을 단일화했습니다.

### 💾 저장/종료 안정성 강화
- TXT/SRT/VTT/RTF 저장에 원자적 저장(임시파일 후 교체)을 적용했습니다.
- 백그라운드 저장 스레드를 추적하고 종료 시 제한시간(`5초`) 대기해 저장 중단 손상 위험을 낮췄습니다.

### 🧪 운영 품질 보강
- 로그 저장 경로를 항상 앱 기준 `logs`로 고정했습니다.
- `LiveBroadcastDialog` 종료 경로를 단일화해 QThread 종료 안정성을 강화했습니다.
- 짧은 발화는 허용하고 숫자/기호 노이즈는 차단하는 필터를 도입했습니다.

---

## ✨ v16.12 핵심 개선

### 🎤 발언자 전환 즉시 감지 (Zero-Delay)
- **자막 영역 클리어 감지** - 발언자가 바뀔 때 자막 영역이 비워지는 순간을 **실시간으로 감지**합니다.
- **즉시 완전 리셋** - 기존에는 2초간 자막이 멈추던 현상을 해결하여, 새 발언자의 첫 마디를 놓치지 않고 **즉시 수집**합니다.
- **버퍼 확정** - 전환 직전의 마지막 텍스트가 유실되지 않도록 강제로 저장합니다.

### 🧬 MutationObserver 하이브리드 엔진
- **이벤트 기반 캡처** - JavaScript `MutationObserver`를 사용하여 자막 변경을 실시간 이벤트로 감지합니다.
- **폴링 Fallback** - 기존의 0.2초 폴링 방식도 함께 작동하여 어떤 상황에서도 자막을 놓치지 않는 **이중 안전장치**를 구축했습니다.
- **자동 재주입** - 페이지 새로고침이나 네트워크 재연결 시에도 Observer가 자동으로 재설치됩니다.

### 🎯 코어 정확성 및 안정성 강화
- **스마트 Suffix 매칭 (`rfind`)** - "위원장... 위원장..." 처럼 반복되는 문구 처리 시 과잉 추출 문제를 원천 차단했습니다.
- **소프트 리셋 (Soft Resync)** - 네트워크 지연 등으로 동기화가 깨졌을 때, 전체 데이터를 날리지 않고 최근 10초간의 자막 맥락만 유지하며 **자연스럽게 복구**합니다.
- **대량 중복 방지** - 리셋 직후 발생할 수 있는 대량 중복 텍스트 유입을 알고리즘 레벨에서 차단했습니다.

---

## 🛠️ v16.12 안정화 패치 (2026-02-25)

- **생중계 URL 자동 보완 연결**: 시작/재연결 시 URL에 `xcgcd`가 없으면 `xcode` 기준 자동 감지를 실제 워커 흐름에 연결했습니다.
- **짧은 발화 수집 보강**: `네/예` 같은 1~2글자 발화를 수집하면서, 기호-only/숫자-only 노이즈는 차단하는 텍스트 게이트를 적용했습니다.
- **세션 내결함성 강화**: 세션 로드/병합 시 손상 항목이 섞여도 유효 항목만 복원하도록 개선했습니다.
- **저장 비차단화 확대**: RTF 저장, 통계 내보내기를 백그라운드 처리로 전환해 UI 프리징을 줄였습니다.
- **로그 경로 일관화**: 실행 위치와 무관하게 앱 기준 경로(`Config.LOG_DIR`)에 로그가 저장되도록 통일했습니다.

---

## ✨ v16.11 주요 개선 사항

### 🧠 자막 수집 알고리즘 완벽 재설계
- **글로벌 히스토리 Suffix 매칭** - 확정된 모든 텍스트를 누적하고, 새 raw에서 히스토리의 마지막 부분(suffix) 이후만 추출
- **DOM 루핑 면역** - 웹사이트 특유의 텍스트 반복/루핑 현상 완벽 대응
- **자막 반복 완전 해결** - 기존 앵커 기반, 버퍼 비교, 문장 해시 방식 모두 실패 → 새 알고리즘으로 해결

### 🛡️ 파이프라인 안정화 고정
- **입력 게이트 레이어** - `preview`는 `_prepare_preview_raw`를 통과한 뒤 코어 알고리즘으로 전달
- **다단계 fallback** - suffix desync/ambiguous 상황에서 증분 우선 추출
- **안전한 재동기화** - 반복 실패 시에만 제한적으로 리셋 수행

---

## 📌 파이프라인 고정 문서

자막 수집 구조 고정 기준은 아래 문서를 참고하세요.

- `PIPELINE_LOCK.md`

---

## ✨ 주요 기능

### 🎯 실시간 자막 추출
- 국회 의사중계 웹사이트의 AI 자막을 실시간으로 캡처
- **스트리밍 엔진**: 딜레이 없이 즉시 자막 표시 및 저장
- 중복 자막 자동 제거 및 스마트 이어붙이기

### 💾 다양한 저장 형식
TXT, SRT, VTT, DOCX, HWPX, HWP, RTF, JSON 세션 저장

### 🔍 검색 및 하이라이트
- **실시간 검색** (Ctrl+F, 전체 자막 기준)
- 검색 결과 이동 시 오래된 자막도 자동으로 렌더 범위를 재조정해 표시
- DB 자막 검색은 기본적으로 FTS 문법이 아니라 literal substring 검색으로 동작하며, `%`, `_`, `OR`, `-`, `:` 같은 입력도 문자 그대로 해석합니다.
- **키워드 하이라이트** - 특정 단어 강조
- **알림 키워드** - 감지 시 토스트 알림

### 🏛️ 상임위원회 프리셋
- 상임위원회/특별위원회 URL 빠른 선택
- 사용자 정의 프리셋 추가/관리 (`assembly.webcast.go.kr` 계열 `http/https` URL만 허용)
- **생중계 목록 선택** - 현재 방송을 목록에서 직접 선택 (📡 생중계 목록)
- 기본 제공 특별 코드 프리셋은 현재 검증된 `IO` 계열만 유지하며, 미확인 코드는 직접 URL/사용자 프리셋으로 입력

### ⚙️ 편의 기능
- 헤드리스 모드 (브라우저 창 숨김)
- 실시간 저장, 세션 저장/불러오기
- DB 검색 결과에서 세션 불러오기 / 해당 문장 위치 이동
- 비정상 종료 뒤에는 최신 자동 백업 또는 세션 저장본을 시작 시 복구 제안합니다.
- 자동 줄넘김 정리 옵션 (기본 활성화)
- 자동 백업 (5분마다)
- 다크/라이트 테마
- 저장/백업/DB/히스토리 파일은 **실행 위치와 무관하게 앱 기준 경로**에 저장

---

## 📦 설치 방법

### 1. Python 설치
Python 3.10 이상이 필요합니다.
- [Python 공식 사이트](https://www.python.org/downloads/)에서 다운로드

### 2. 개발/검증 의존성 설치
```bash
pip install -r requirements-dev.txt
```

### 3. 선택 기능 참고
- `requirements-dev.txt`에는 DOCX(`python-docx`)와 HWP(`pywin32`) 저장 기능용 패키지가 함께 정리되어 있습니다.
- 최소 실행만 필요하면 `pip install PyQt6 selenium`만 설치해도 됩니다.
- HWPX 저장은 추가 외부 프로그램 없이 기본 기능으로 사용할 수 있습니다.
- HWP 저장은 Windows 환경과 한컴오피스가 추가로 필요합니다.
- DOCX/HWPX는 한 `SubtitleEntry`를 한 문단/블록으로 유지하고, 엔트리 내부 개행은 paragraph split이 아니라 line break로 저장합니다.

### 4. Chrome 브라우저
- Chrome 브라우저가 설치되어 있어야 합니다
- Selenium 4.x가 자동으로 WebDriver를 관리합니다

---

## 🚀 사용 방법

### 기본 사용법

#### 1단계: 프로그램 실행
```bash
python "국회의사중계 자막.py"
```

#### 2단계: 위원회 선택
세 가지 방법 중 선택:

**방법 A: 프리셋 사용 (권장)**
1. `📋 상임위` 버튼 클릭
2. 원하는 위원회 선택 (예: 본회의, 법제사법위원회)
3. URL이 자동으로 입력됨

**방법 B: 직접 URL 입력**
1. URL 입력창에 국회 의사중계 URL 입력
2. 예: `https://assembly.webcast.go.kr/main/player.asp?xcode=10`

**방법 C: 생중계 목록 선택**
1. `📡 생중계 목록` 버튼 클릭
2. 목록에서 방송 선택
3. `종료/예정` 항목은 확인 후 URL만 입력됨
4. URL이 자동으로 입력됨

- 기본 프리셋은 검증된 상임위와 `IO` 기반 특위만 포함합니다. 확인되지 않은 특수 코드는 직접 URL 또는 사용자 프리셋을 사용하세요.
- 생중계 목록 창은 열려 있는 동안 `30초`마다 자동으로 최신 상태를 다시 불러옵니다.

#### 3단계: 옵션 설정
- ✅ **자동 스크롤**: 새 자막이 추가될 때 자동으로 아래로 스크롤 (사용자 스크롤 시 일시 중지)
- ✅ **자동 줄넘김 정리**: 수집 중 줄바꿈/빈 줄을 자동 정리, 기본 활성화
- ✅ **실시간 저장**: 자막을 파일에 실시간으로 저장 (앱 기준 `realtime_output` 폴더, 시작 전 설정)
- ✅ **헤드리스 모드**: 브라우저 창을 숨기고 백그라운드에서 실행 (시작 전 설정)
- 추출 중에는 URL, 프리셋, 생중계 선택, 실시간 저장, 헤드리스 모드를 변경할 수 없습니다.

#### 4단계: 추출 시작
- `▶ 시작` 버튼 클릭 또는 **F5** 키
- 상태바에서 진행 상황 확인:
  - `🔍 현재 생중계 감지 중...` - xcgcd 자동 탐지 진행
  - `✅ 생중계 감지 성공!` - 오늘 생중계 발견
  - `자막 모니터링 중` - 정상 동작 중
- 연결 상태 표시: 🟢 연결됨, 🔴 끊김, 🟡 재연결 중

#### 5단계: 자막 확인
- 왼쪽 패널에 자막이 실시간으로 표시됨
- 오른쪽 통계 패널에서 글자 수, 공백 기준 단어 수, 실행 시간 확인
- `⏳` 표시는 아직 확정되지 않은 진행 중 자막

#### 6단계: 저장
추출 완료 후 다양한 형식으로 저장 (자동 파일명 제안됨):
- **파일 → TXT 저장** (Ctrl+S) - 일반 텍스트
- **파일 → SRT 저장** - 자막 파일 형식
- **파일 → DOCX 저장** - Word 문서
- **파일 → HWPX 저장** - 한글 문서(기본 포맷)
- **파일 → 세션 저장** (Ctrl+Shift+S) - 나중에 다시 불러오기 가능 + DB 저장

---

## ⌨️ 단축키

### 기본 조작
| 단축키 | 기능 |
|--------|------|
| **F5** | 추출 시작 |
| **Escape** | 검색창 닫기 / 추출 중지 |
| **Ctrl+Q** | 프로그램 종료 |

### 검색 및 편집
| 단축키 | 기능 |
|--------|------|
| **Ctrl+F** | 검색창 열기 |
| **F3** | 다음 검색 결과 |
| **Shift+F3** | 이전 검색 결과 |
| **Ctrl+E** | 자막 편집 |
| **Delete** | 자막 삭제 |
| **Ctrl+Shift+C** | 전체 자막 복사 |
| **Ctrl+C** | 선택한 텍스트 복사 |

### 저장
| 단축키 | 기능 |
|--------|------|
| **Ctrl+S** | TXT 저장 |
| **Ctrl+Shift+S** | 세션 저장 |
| **Ctrl+O** | 세션 불러오기 |
| **Ctrl+Shift+M** | 자막 병합 |

### 보기
| 단축키 | 기능 |
|--------|------|
| **Ctrl+T** | 테마 전환 (다크/라이트) |
| **Ctrl++** | 글자 크기 키우기 |
| **Ctrl+-** | 글자 크기 줄이기 |
| **F1** | 사용법 가이드 |

---

## 📄 저장 형식

| 형식 | 확장자 | 설명 | 필요 라이브러리 |
|------|--------|------|-----------------| 
| **TXT** | .txt | 타임스탬프 포함 텍스트 | 없음 |
| **SRT** | .srt | SubRip 자막 파일 | 없음 |
| **VTT** | .vtt | WebVTT 자막 파일 | 없음 |
| **DOCX** | .docx | Word 문서 | python-docx |
| **HWPX** | .hwpx | 한글 문서 (기본 포맷) | 없음 |
| **HWP** | .hwp | 한글 문서 | pywin32 + 한컴오피스 |
| **RTF** | .rtf | 서식 있는 텍스트 (HWP 호환) | 없음 |
| **JSON** | .json | 세션 저장 (복원 가능) | 없음 |
| **SQLite** | .db | 데이터베이스 히스토리 | 없음 (내장) |

---

## 📚 상세 기능 설명

### 자막 파이프라인 고정 구조 (중요)
현재 자막 수집 파이프라인은 아래 구조로 **고정**되어 있습니다.

1. **Worker (하이브리드)**:
    - 선택자 후보를 우선순위로 구성: `#viewSubtit .smi_word:last-child` → `#viewSubtit .smi_word` → 컨테이너 계열
    - 기본 문서 + 중첩 iframe/frame 경로를 순회해 자막 요소 탐색
    - `self.driver` 접근은 `_driver_lock` + identity helper로 serialize
    - 시작/재연결 시 `_detect_live_broadcast`로 `xcgcd` 보완 URL을 우선 확정
    - `MutationObserver` 주입 우선, 실패 시 JS 폴링 브리지(약 180ms) 활성화
    - 메인 루프(0.2초)에서 Observer 버퍼 우선 수집, 없으면 폴링 fallback
    - URL에 `xcgcd`가 없으면 시작 시 1회만 자동 감지하고, 재연결에서는 직전 확정 URL을 우선 재사용
    - 동일 raw 유지 구간은 `keepalive`를 주기 발행해 `end_time` 연장
    - **자막 영역 클리어 감지** 시 `subtitle_reset` 신호 전송
2. **UI Queue**:
    - `MainWindowMessageQueue(maxsize=500)`가 worker 메시지를 내부 `run_id` envelope로 감싸고 고빈도 메시지를 coalescing
    - inactive/stale run의 메시지는 UI에서 즉시 폐기
    - `subtitle_reset` 수신 시 **즉시 완전 리셋** 및 이전 버퍼 확정
    - `preview` 메시지를 `_prepare_preview_raw`로 정규화/게이팅
    - `keepalive` 메시지를 수신해 마지막 자막 엔트리 종료 시각 갱신
3. **Core Algorithm**:
    - 통과된 입력만 `_process_raw_text`(글로벌 히스토리 + Suffix)로 전달
    - `rfind`를 사용하여 반복 문구 과잉 추출 방지
4. **후단 정제**:
    - `get_word_diff`로 미세 중복 제거
    - recent compact tail 체크로 대량 반복 블록 재누적 차단
    - 한글/영문 포함 짧은 발화(1~2글자) 허용 + 기호/숫자-only 노이즈 차단
    - `_join_stream_text`로 문장부호 기준 공백 결합(웹 표시 형태 최대 보존)
    - `_add_text_to_subtitles`와 `_finalize_subtitle`는 동일 shared append/merge 경로를 사용
    - `_render_subtitles()`는 immutable snapshot clone 기준으로 tail patch를 반영
5. **종료 처리**:
    - `_drain_pending_previews`에서 남은 큐 소진
    - 마지막 항목 보정 및 저장
    - 백그라운드 작업(파일/세션/DB) 종료 대기 후 종료(`SAVE_THREAD_SHUTDOWN_TIMEOUT`)

운영 원칙:
- 코어 알고리즘(`_process_raw_text`, `_extract_new_part`)은 직접 수정하지 않음
- 반복/누락 이슈는 우선 게이트 임계값과 fallback 경로에서 조정
- Worker → UI 통신은 `MainWindowMessageQueue`를 우회하지 않음
- 통계의 `단어 수`는 항상 공백 분리 기준으로 해석
- 로그 키워드: `subtitle_reset 감지`, `preview suffix desync reset`, `MutationObserver 주입 성공`, `MutationObserver 폴링 브리지 활성화`

---

## 🔧 문제 해결

### Chrome 시작 오류
- Chrome 브라우저가 최신 버전인지 확인
- 프로그램이 자동으로 최대 3회 재시도합니다
- Selenium 4.x가 WebDriver를 자동 관리합니다

### 자막이 표시되지 않음
1. 국회 의사중계 페이지에서 자막이 활성화되어 있는지 확인
2. 다른 CSS 선택자 시도: `#viewSubtit .smi_word:last-child`, `#viewSubtit .smi_word`, `#viewSubtit .incont`
3. 생중계가 진행 중인지 확인
4. `xcode-only` URL도 자동 보완되지만, 실패 시 `📡 생중계 목록`에서 직접 선택
5. `xcode`만 입력했다면 시작 후 자동 보완된 URL로 바뀌는지 확인

### 짧은 발화가 누락되는 것처럼 보임
- 현재 버전은 `네/예/ok` 같은 짧은 발화를 수집합니다.
- `...`, `--`, `123`처럼 **문자(한글/영문) 없는 입력**은 노이즈로 차단됩니다.

### 연결이 자주 끊김
- v16.6부터 자동 재연결이 지원됩니다
- 상태바에서 연결 상태(🟢/🔴/🟡) 확인
- 네트워크 환경 점검 필요

### HWP 저장 오류
- **한글 오피스**가 설치되어 있어야 합니다
- `pywin32` 또는 한컴오피스가 없으면 HWP 저장 요청은 즉시 `HWPX`로 자동 대체됩니다
- 저장 실패 시 RTF/DOCX/TXT 대체 형식을 선택할 수 있습니다
- RTF 파일은 한글에서 열 수 있습니다

---

## ✅ 개발 검증

코드 변경 후 현재 저장소에서 맞춰야 하는 최소 검증 기준은 아래와 같습니다.

```bash
pip install -r requirements-dev.txt
pyright
pytest -q
python -c "import ui.main_window as m; print(m.MainWindow.__name__)"
```

- 정적 분석 기준은 루트 `pyrightconfig.json` 기반 `pyright 0 errors`입니다.
- 테스트 기준은 루트 `tests/` 전체 통과입니다.
- `tests/test_pyright_regression.py`는 워크스페이스 전체 `pyright --outputjson` 결과가 `0 errors`인지 회귀 검증합니다.
- 소스 코드, 문서(`.md`), 빌드 스펙(`subtitle_extractor.spec`)은 **UTF-8 without BOM**을 유지합니다.
- 사용자 내보내기 텍스트 중 일부 경로(TXT 실시간 저장/일반 TXT 저장)는 Windows 메모장 호환을 위해 `utf-8-sig`를 사용합니다.
- VS Code/Pylance는 루트 `pyrightconfig.json`과 `.vscode/settings.json`을 기준으로 같은 진단 기준을 사용합니다.
- `pyrightconfig.json`은 `stubPath=typings`, `executionEnvironments[].extraPaths=["typings"]`, `.pytest_tmp` exclude, `reportMissingModuleSource=none`를 공통 기준으로 사용합니다.
- `pytest.ini`는 `--basetemp=.pytest_tmp`를 사용해 Windows 사용자 TEMP 권한 이슈와 한글 사용자명 경로 영향을 줄입니다.
- `tests/test_encoding_hygiene.py`는 repo tracked 파일만 검사하며, Windows 메모장 호환용 BOM이 허용되는 `.pytest_tmp` 같은 workspace temp 산출물은 검사에서 제외합니다.
- Windows PowerShell 5.x 기본 출력 인코딩에서는 UTF-8 without BOM 파일이 콘솔에 깨져 보일 수 있습니다. 저장소 기준 파일 자체는 UTF-8입니다.

### 저장소 기준 파일
- `pyrightconfig.json`: Pylance/Pyright의 저장소 공통 타입 체크 기준(`standard`, Python 3.10)
- `.vscode/settings.json`: 워크스페이스 단위 Pylance/UTF-8 설정
- `.editorconfig`, `.gitattributes`: UTF-8 without BOM + CRLF 기준 유지
- `typings/`: 글로벌 인터프리터 환경에서도 `pyright` errorCount를 0으로 유지하기 위한 로컬 PyQt6/selenium/pytest 최소 stub
- `pytest.ini`: 워크스페이스 내부 basetemp 경로(`.pytest_tmp`)를 강제해 테스트 임시 디렉터리 권한 문제를 우회
- `requirements-dev.txt`: 개발/검증 및 optional export 의존성 기준선
- `ui/main_window_types.py`: 분할된 `MainWindow` mixin의 공통 `self` 타입 계약(`MainWindowHost`)
- `tests/test_encoding_hygiene.py`: repo tracked 텍스트 파일의 UTF-8/BOM/U+FFFD 위생 및 핵심 한글 문자열 round-trip 검증
- `tests/test_pyright_regression.py`: 워크스페이스 전체 `pyright --outputjson` 결과가 `0 errors`인지 회귀 검증

---

## 🛠️ 빌드 방법

### PyInstaller로 EXE 빌드
```bash
# PyInstaller 설치
pip install pyinstaller

# 빌드 실행
pyinstaller subtitle_extractor.spec

# 결과물
dist/국회의사중계자막추출기 v16.14.7.exe
```

- `subtitle_extractor.spec`는 frozen 환경에서도 `Config.VERSION`이 README 첫 줄의 버전을 읽을 수 있도록 `README.md`를 함께 포함합니다.
- EXE 이름도 `subtitle_extractor.spec`에서 README 첫 줄을 읽어 동기화하므로, 릴리스 버전 변경 시 README 상단 버전과 함께 맞춰집니다.
- `python-docx`, `pywin32`, `core.subtitle_processor`, 공유 `core.live_list`, 공개 `ui.main_window_*` facade와 내부 `ui.main_window_impl.*` / `ui.main_window_impl.ui.*` / `ui.main_window_impl.database_*` / `ui.main_window_impl.persistence_*` / `core.live_capture_impl.*`, `PyQt6.QtNetwork` 모듈은 런타임 동적 import 경로를 고려해 `.spec`의 hidden import 목록에 반영합니다.
- frozen 기본 실행은 `%LOCALAPPDATA%\\AssemblySubtitle\\Extractor`를 storage root로 사용하고, EXE 옆에 `portable.flag`를 두면 로그/세션/DB/설정(`settings.ini`)을 EXE 폴더에 저장합니다.
- `typings/`, `.pytest_tmp`, `portable.flag`, `settings.ini`, `session_recovery.json`, `backups/runtime_sessions/` 같은 정적 분석/portable/runtime 산출물은 frozen 번들에 포함하지 않습니다.
- 빌드 산출물은 `.gitignore`의 `build/`, `dist/` 규칙으로, portable 실행 보조 파일은 `/portable.flag`, `/settings.ini`, `.storage_probe` 규칙으로 관리합니다.

---

## 📝 변경 이력

### v16.14.7 (2026-04-01)
- 브라우저 헬스체크, Chrome 세션 자동 재기동, `reconnected` 상태 반영으로 장시간 수집 중 창 종료 복구를 보강
- `ui/main_window_impl/`와 `core/live_capture_impl/`로 capture/pipeline/view/runtime/live capture 내부 구현을 재배치하고 공개 facade import 경로는 유지
- `ui/main_window_database.py`, `ui/main_window_persistence.py`는 facade 조합 레이어로 축소하고 실제 DB/persistence 구현은 `ui/main_window_impl/database_*`, `ui/main_window_impl/persistence_*`로 재분리
- `subtitle_extractor.spec` hidden import를 내부 모듈 구조에 맞게 확장하고, `README.md`, `CLAUDE.md`, `GEMINI.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`, `.gitignore`를 현재 구조 기준으로 재동기화
- `archive_token` + `run_id` 기반 runtime archive identity, best-effort runtime manifest salvage, blank-URL 세션 로드 hygiene, recovery pointer 유지 정책을 추가해 장시간 세션 안정성을 보강
- frozen 기본 저장소를 `%LOCALAPPDATA%\\AssemblySubtitle\\Extractor`로 분리하고, `portable.flag`가 있으면 EXE 폴더 기준 `settings.ini`/로그/세션/DB를 사용하는 portable 모드를 추가
- 앱 시작 전 storage preflight를 도입해 `logs/`, `sessions/`, `backups/`, `runtime_sessions/`, DB 경로 생성/쓰기 실패를 UI 조립 전에 차단하고, 후속 배치에서 실제 파일 surface와 SQLite WAL probe까지 확장
- dirty 세션 보호를 `저장 후 원래 액션 재개` 방식으로 통일하고, 장시간 세션 hydrate를 background worker + progress/cancel 구조로 전환
- `core.live_list.py`를 추가해 `LiveBroadcastDialog`/자동 URL 보완 경로의 `live_list.asp` URL 생성, payload 파싱, row 정규화, 오류 분류를 공통화하고, 다중 live 후보는 더 이상 자동 선택하지 않음
- DB `sessions` 테이블에 `lineage_id`, `parent_session_id`, `is_latest_in_lineage`를 추가하고, 히스토리 다이얼로그에 `[최신]`, `[이전 저장본 n/N]` 배지를 노출
- DB 초기화를 base schema와 FTS로 분리해 degraded mode를 허용하고, `db_available`/`fts_available`/`db_degraded_reason` 상태와 persistent warning UI를 추가
- URL 히스토리/프리셋 load-save 실패를 사용자 경고로 노출하고, export/message 계층의 dead branch를 정리
- `pyrightconfig.json` / `.vscode/settings.json` / `typings/PyQt6/QtNetwork.pyi` / `tests/test_encoding_hygiene.py`를 갱신해 Pylance/CLI `pyright`와 UTF-8 위생 기준을 현재 코드에 맞게 고정
- 검증 기준선: `pytest -q` 187 pass, `pyright --outputjson` 0 errors / 0 warnings

### v16.14.6 (2026-04-01)
- recovery state(`session_recovery.json`) 기반 최신 복구 가능 세션 제안, 종료 직전 저장/자동 백업 메타데이터 정리
- prepared snapshot 기반 수동 reflow, lossless DB metadata round-trip, DOCX/HWPX multiline export 정책 정리
- `.gitignore`와 `subtitle_extractor.spec`에 runtime recovery state 제외 정책을 반영

### v16.14.5 (2026-03-27)
- 캡처 시작 시 URL/위원회/헤드리스/실시간 저장을 `run-source` 스냅샷으로 고정하고, 추출 중 관련 UI 변경을 공통 잠금 정책으로 정리
- 생중계 목록은 `생중계`와 `종료/예정`을 함께 보여주되, 자동 감지는 live-only로 제한하고 종료/예정 선택은 확인 후 URL만 적용
- DB 히스토리(50), DB 검색(100), 자막 편집/삭제(200)를 `더 보기` 기반 점진 로드로 개편
- 세션 dirty tracking과 `Save / Discard / Cancel` 종료 프롬프트를 도입하고, clean 판정은 세션 JSON 저장 성공 기준으로 통일
- 단축키 문서와 실제 동작을 `Escape`, `Ctrl+Shift+C`, `Ctrl+C` 기준으로 동기화
- `subtitle_extractor.spec`, `README.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`, `CLAUDE.md`, `GEMINI.md`, `FEATURE_IMPLEMENTATION_REVIEW_20260325.md`, `.gitignore`를 `v16.14.5` 기준으로 재점검
- 회귀 테스트 추가 후 `pytest -q` 95개 전체 통과, `pyright` 0 errors 확인

### v16.14.4 (2026-03-25)
- 검색을 `QTextEdit` 렌더 텍스트가 아닌 전체 `self.subtitles` 스냅샷 기준으로 전환하고, 검색 이동 시 렌더 윈도우를 동적으로 재배치
- 추출 중 세션 불러오기/DB 세션 로드/병합/줄넘김 정리/지우기/편집/삭제를 공통 가드와 action disable로 차단
- 파일/DB 세션 로드 payload를 통합하고, DB 검색 결과에서 세션 로드 후 `sequence` 위치로 즉시 이동 가능하게 개선
- 프리셋 export/import round-trip(`committee` + `custom`) 및 overwrite 정책 정렬, 통계/프리셋 export의 원자적 저장 경로 통일
- 병합 dedupe 모드에 `보수적(같은 초)` / `기존(30초 버킷)` 옵션 추가
- `subtitle_extractor.spec`, `README.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`, `CLAUDE.md`, `GEMINI.md`, `FEATURE_IMPLEMENTATION_REVIEW_20260325.md`를 `v16.14.4` 기준으로 동기화
- 회귀 테스트 확장 후 `pytest -q` 85개 전체 통과, `pyright` 0 errors 확인

### v16.14.3 (2026-03-23)
- `self.driver` 접근을 `_driver_lock`과 identity helper로 통일하고, stop timeout 이후 stale worker run을 `run_id`로 격리
- `MainWindowMessageQueue(maxsize=500)`와 고빈도 메시지 coalescing으로 preview/keepalive/status/resolved_url backlog를 제한
- `_finalize_subtitle`를 shared append 경로에 연결하고, 렌더는 immutable snapshot clone 기준으로 정리
- `SubtitleEntry(entry_id=None)` 자동 ID 생성, `공백 기준 단어 수` 문구 정리, `정보위원회`/`NA`/`PP` 기본 코드 제거
- `subtitle_extractor.spec`, `README.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`, `CLAUDE.md`, `GEMINI.md`를 `v16.14.3` 기준으로 동기화
- 로컬 `typings/`, `pytest.ini --basetemp=.pytest_tmp`, 루트 `.hwpx`/`.pytest_tmp` ignore 규칙을 추가해 저장소 검증 경로를 고정
- 회귀 테스트 확장 후 `pytest -q` 76개 전체 통과, `pyright` 0 errors 확인

### v16.14.2 (2026-03-18)
- 자막 수집 경로는 회귀 대응을 위해 이전 안정 structured probe 루프로 복귀
- `SubtitleEntry.__slots__`, compact cache, `CaptureSessionState.snapshot_clone()`으로 저장/백업 메모리 증폭 완화
- `atomic_write_json_stream()` 기반 스트리밍 JSON 저장과 `SubtitleEntry` 직접 DB 저장 경로 추가
- `capture_state.entries` 단일화, tail patch render, queue drain time budget으로 UI 갱신 비용 절감
- `subtitle_extractor.spec` hidden import 기준을 현재 모듈 구조와 optional import 경로에 맞게 재점검
- 성능 회귀 테스트 추가 후 `pytest -q` 63개 전체 통과, `pyright` 0 errors 확인

### v16.14.1 (2026-03-17)
- `✨ 자동 줄넘김 정리` 옵션 추가 및 기본 활성화
- preview/live-row/flush 경로에서 `auto_clean_newlines` 설정 기반 정규화 적용
- 줄바꿈 정리 동작을 끈 경우 개행을 유지하는 회귀 테스트 추가
- `subtitle_extractor.spec`, `README.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`, `CLAUDE.md`, `GEMINI.md`를 `v16.14.1` 기준으로 동기화
- `.gitignore`에 PyInstaller `.pkg` 산출물 무시 규칙 추가

### v16.14.0 (2026-03-16)
- 크롬 확장 자막 파이프라인을 기준 구조로 고정하고 `core/live_capture.py` + `core/subtitle_pipeline.py` 중심으로 운영 경로를 정리
- `ui/main_window.py`를 capture / pipeline / view / persistence / database / ui mixin 모듈로 분할
- `core/file_io.py`, `core/text_utils.py`, `core/reflow.py`, `core/database_manager.py` 추가 및 `core/utils.py`, `database.py` 호환 shim 전환
- `subtitle_extractor.spec`, `README.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`, `CLAUDE.md`, `GEMINI.md`를 새 구조와 `v16.14.0` 기준으로 동기화
- 버전 동기화/호환 import 검증 테스트(`tests/test_version_sync.py`, `tests/test_compat_imports.py`) 추가
- `ui/main_window_types.py`, `tests/test_pyright_regression.py`, 확장된 `tests/test_encoding_hygiene.py`로 Pylance/UTF-8 회귀 기준을 보강

### v16.13.2 (2026-03-05)
- 🔒 **종료 lifecycle 통합**: 파일 저장/세션 저장·불러오기/DB task를 공통 레지스트리로 추적하고 종료 시 drain 대기 적용
- 🧠 **메모리 상한 적용**: `_confirmed_compact` 상한(`50000`) 도입으로 장시간 세션 메모리 증가 억제
- 📎 **병합 정책 일원화**: 실시간 병합 기준을 Config로 통합(`5초/300자`), 세션 dedupe를 시간창(30초) 기반으로 개선
- 🗄️ **DB 경로 정합성**: `DatabaseManager()` 기본 경로를 `Config.DATABASE_PATH`로 통일
- ✅ **회귀 테스트 확장**: background lifecycle, 병합 정책, compact 상한, DB 기본 경로 검증 추가

### v16.13.1 (2026-02-27)
- 🧩 **수집 정체 완화**: `.smi_word` 전체 목록 기반 창(window) 수집으로 첫 문장 이후 멈춤 현상 완화
- 🎯 **Observer 타겟 우선순위 조정**: 컨테이너(`.incont`, `#viewSubtit`) 우선 주입으로 DOM 구조 변화 대응 강화
- 🧪 **회귀 테스트 추가**: `.smi_word` 창 수집 동작 검증 케이스 보강

### v16.13 (2026-02-27)
- 🧭 **xcgcd 자동 보완 실연결**: 워커 시작/재연결 경로에서 `_detect_live_broadcast`를 실제 적용
- ⏱️ **keepalive 재활성화**: 동일 자막 유지 시 `end_time` 주기 갱신으로 SRT/VTT 타이밍 정확도 개선
- 💾 **원자적 파일 저장**: TXT/SRT/VTT/RTF에 임시파일 교체 방식 적용
- 🔒 **종료 안정성**: 저장 스레드 추적 + 종료 대기(기본 5초) 추가
- 🧩 **다이얼로그 종료 보강**: `LiveBroadcastDialog` 스레드 종료 경로 단일화
- 📝 **짧은 발화 정책 개선**: 의미 있는 1~2자 발화 허용, 숫자/기호 노이즈 차단
- 📁 **로그 경로 통일**: `Config.LOG_DIR` 기반 앱 경로 고정

### v16.12.1 (2026-02-25)
- 🔗 **생중계 자동 감지 연결**: `xcgcd` 미포함 URL 시작 시 `_detect_live_broadcast`를 실제 워커에 연결
- 🗣️ **짧은 발화 수집 보강**: 1~2글자 발화 허용 + 노이즈 필터(`기호-only/숫자-only`) 적용
- 🧱 **세션 내결함성 강화**: 세션 로드/DB 로드/병합 시 손상 항목만 건너뛰고 계속 진행
- 🧵 **UI 비차단화 확장**: RTF 저장/통계 내보내기를 백그라운드 처리로 전환
- 📁 **로그 경로 정합성 수정**: `Config.LOG_DIR` 기반으로 로그 저장 위치 통일
- ✅ **테스트 보강**: 생중계 자동 감지 연결, 짧은 발화 게이트, 세션 손상 복원, 로그 경로 검증 추가

### v16.12 (2026-02-12)
- 🎤 **발언자 전환 즉시 감지**: 자막 영역 클리어 시 즉시 리셋으로 2초 딜레이 제거
- 🧬 **하이브리드 엔진**: MutationObserver + 폴링 구조로 수집 신뢰성 극대화
- 🎯 **정확성 향상**: `rfind` 도입으로 Suffix 충돌 방지, `소프트 리셋`으로 복구 안정성 강화
- 📝 **문서 업데이트**: PIPELINE_LOCK.md 및 알고리즘 분석 문서 최신화

### v16.11 (2026-01-29)
- 🧠 **자막 알고리즘 완벽 재설계**: 글로벌 히스토리 Suffix 매칭 알고리즘 도입
- 📝 **타임스탬프 저장 개선**: TXT/DOCX/HWP 저장 시 1분 간격으로 타임스탬프 표시
- 🐛 **버그 수정**: 줄넘김 정리 후 자막 수집 중단 오류 해결, end_time null 오류 수정

### v16.10 (2026-01-27)
- ⚡ **스트리밍 아키텍처**: 자막 수집 로직 전면 재설계 (Diff & Append 방식)
- 🐛 **버그 수정**: 1분 이상 자막 수집 시 사라지는 문제 해결
- 🛡️ **안정성**: 중지 버튼 클릭 시 크래시 해결
- 🎨 **UI**: 버튼 레이아웃 개선 및 키워드 입력창 복구

### v16.9 (2026-01-23)
- 🛡️ **데이터 안정성 강화**: 자동 백업 백그라운드 처리 + 중복 실행 방지
- 🔒 **스레드 안전성**: 자막 데이터 접근 락(Lock) 전면 적용
- ⚡ **DB 성능 개선**: 연결 캐싱, FTS5 검색 적용, 대량 삽입 최적화

### v16.8 (2026-01-23)
- 🧾 **상임위원회 xcode 최신화** (기재위, 여가위, 정무위 등 반영)
- ⚡ **성능 최적화**: 정규식/포맷 캐싱, 통계 캐시

### v16.7 (2026-01-23)
- 🧭 **URL 감지 강화**: API 기반 xcgcd 자동 보완
- 📡 **생중계 목록 선택 UI**: 현재 방송 직접 선택 버튼
- 🧩 **특별위원회 지원**: 국정감사 등 특위 코드 대응

### v16.6 (2026-01-22)
- 🔌 **연결 상태 모니터링**: 상태바 아이콘 표시
- 🔄 **자동 재연결**: 지수 백오프 재시도
- 📝 **자동 파일명 생성**: 위원회명 자동 추출
- 🗄️ **SQLite 데이터베이스**: 세션 히스토리 및 검색
- 📎 **자막 병합**: 다중 세션 병합 도구

---

## 📄 라이선스

MIT License

© 2024-2026
