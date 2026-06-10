# Project Audit

## 1. Executive Summary

이 프로젝트는 국회 의사중계 웹사이트의 AI 자막을 PyQt6 GUI, Selenium worker, runtime archive, SQLite DB, 다중 export 경로로 수집/저장하는 Windows 중심 데스크톱 앱이다. README.md와 CLAUDE.md 기준으로 공개 facade import 경로를 유지하면서 실제 구현은 `ui/main_window_impl/`, `core/database_impl/`, `core/subtitle_pipeline_impl/`, `core/live_capture_impl/`로 분리되어 있다.

감사 당시 전체 위험도는 **Medium-High**로 보았다. 자막 수집 파이프라인, URL host 정책, runtime manifest path confinement, 파일 원자 저장, queue overflow 보존 같은 핵심 안정화는 상당히 구현되어 있었지만, 기능 구현 관점에서 실제 사용자 데이터 흐름에 영향을 줄 수 있는 문제가 남아 있었다.

- 가장 큰 확인 이슈는 DB 조회/로드/삭제/통계 오류가 일부 경로에서 예외로 전파되지 않고 `[]`, `None`, `False`, `{}`로 축소되어 UI가 "데이터 없음"처럼 오인할 수 있다는 점이다.
- 두 번째 확인 이슈는 capture 시작/중지 시 `_clear_message_queue()`가 worker 메시지뿐 아니라 세션 저장/로드/DB 작업 같은 control 메시지도 삭제할 수 있어, 저장 완료 상태가 영구적으로 풀리지 않는 race가 가능하다는 점이다.
- live_list/페이지에서 얻는 `xcode`, `xcgcd` 값은 host 정책 밖의 내부 query 값인데, 현재는 trim만 하고 URL/CSS selector에 직접 삽입한다. 공식 API 기반이라 즉시 위험은 제한적이지만 사용자 입력 검증/OS 브라우저 자동화 안정성 측면에서 보강이 필요하다.

2026-06-11 후속 구현으로 확인 이슈와 즉시/안정성 개선 계획을 반영했다. 현재 잔여 위험도는 **Low-Medium**으로 낮아졌으며, 장기 구조 개선 항목은 별도 리팩터링 후보로 남긴다.

구현 완료 항목:

- DB 조회/로드/삭제/통계의 unexpected exception을 다시 전파하도록 수정했다.
- `_clear_message_queue()`가 stale worker message는 제거하되 durable control message는 보존하도록 수정했다.
- `_start()`가 세션 저장/로드 진행 중에는 새 캡처 시작을 차단하도록 수정했다.
- live `xcode`/`xcgcd` 검증과 `urllib.parse` 기반 query 조립을 추가하고, CSS selector에 query 값을 직접 보간하는 경로를 제거했다.
- 세션 JSON 저장 후 DB 저장 대기는 `Config.DB_SYNC_TASK_TIMEOUT_SECONDS`를 사용하도록 변경했다.
- 일반 JSON 세션 로드 전에 `Config.SESSION_LOAD_MAX_BYTES` 기반 파일 크기 guard를 추가했다.

검증 결과:

- `python -m pytest -q`: `263 passed, 1 skipped`
- `python -m pyright --outputjson`: `0 errors / 0 warnings`
- `python "국회의사중계 자막.py" --smoke --smoke-storage-dir .pytest_tmp\smoke-storage`: `ok: true`
- `python scripts\run_release_verification.py --instantiate-window`: 통과, PyInstaller clean build 및 frozen smoke 포함

## 2. Project Understanding

README.md와 CLAUDE.md에서 확인한 프로젝트 목적은 국회 의사중계 웹사이트의 실시간 AI 자막을 수집하고 TXT/SRT/VTT/DOCX/HWPX/HWP/RTF/JSON/SQLite 형태로 저장하는 것이다. 핵심 가치는 지연 없는 실시간 수집, 안정적인 멀티스레딩, SQLite 기반 세션 관리, 장시간 세션 안정성, PyInstaller frozen 실행 안정성이다.

CodeGraph 상태:

- 인덱스: 116 files, 2454 nodes, 6014 edges
- 언어: Python 115개, XML 1개
- 주요 구조: `ui/main_window.py`의 `MainWindow` facade가 runtime/capture/pipeline/view/persistence/database/ui mixin을 조합한다.

주요 실행 흐름:

1. `국회의사중계 자막.py`가 CLI smoke/preflight 옵션을 처리한 뒤, 일반 실행에서는 PyQt6/Selenium import, `Config.run_storage_preflight()`, `QApplication`, `MainWindow()` 생성 순서로 시작한다.
2. `MainWindowRuntimeLifecycleMixin._start()`는 현재 URL과 selector를 읽고 `core.url_policy.validate_assembly_url()`로 `http/https` 및 `assembly.webcast.go.kr` 계열 host를 검증한다.
3. `_start()`는 runtime archive를 초기화하고 `_clear_message_queue()` 후 Selenium worker thread를 시작한다.
4. `capture_browser._extraction_worker()`는 Chrome/WebDriver를 열고 live URL 보완, MutationObserver, structured probe fallback, keepalive, reset 이벤트를 `MainWindowMessageQueue`로 UI thread에 전달한다.
5. `pipeline_messages._process_message_queue()`는 terminal worker message, overflow passthrough, raw queue, coalesced control/worker message를 제한 시간 안에서 drain하고 `_handle_message()`로 반영한다.
6. 장시간 세션은 `backups/runtime_sessions/<run_id>/manifest.json`, `segment_*.json`, `tail_checkpoint.json` 구조로 보관된다. manifest loader는 relative path confinement와 entries digest 검증, salvage warning을 갖고 있다.
7. 세션 저장은 JSON snapshot을 원자 저장한 뒤 `DBWorker`를 통해 `DatabaseManager.save_session()`을 직렬 실행한다. DB 검색/히스토리/통계도 같은 worker queue를 통해 UI thread로 result/error control message를 전달한다.

CodeGraph impact로 본 영향 범위:

- `list_sessions`, `load_session`, `delete_session`, `get_statistics` 변경은 `DatabaseManager`, `DatabaseProtocol`, `DBWorker`, DB 히스토리/로드/삭제/통계 UI에 영향을 준다.
- `_clear_message_queue` 변경은 `_start`, `_stop`, `closeEvent`, persistence save/load, runtime hydration/search/segment flush, DB worker result, reflow result 등 40개 이상 symbol에 영향을 준다.
- `apply_live_broadcast_to_url` 변경은 live_list payload URL 적용, `_resolve_live_url_from_payload`, `_resolve_live_url_from_list`, `_detect_live_broadcast`에 영향을 준다.

## 3. High-Risk Issues

### 3.1 DB 조회 계층이 실제 오류를 "데이터 없음"으로 축소할 수 있음

위치: `core/database_impl/sessions.py` `load_session()`, `list_sessions()`, `delete_session()` / `core/database_impl/search_stats.py` `get_statistics()` / `ui/main_window_impl/database_worker.py` `_handle_db_task_result()` / `ui/main_window_impl/database_dialogs.py`

문제:
`search_subtitles()`는 예외를 다시 던져 `db_task_error`로 전파되지만, 세션 로드/목록/삭제/통계는 예외를 삼키고 각각 `None`, `[]`, `False`, `{}`를 반환한다. UI는 이 값을 정상 결과로 처리해 "저장된 세션이 없습니다", 빈 통계, 단순 삭제 실패처럼 보여줄 수 있다.

영향:
SQLite 파일 손상, schema migration 오류, 권한/lock 오류가 발생해도 사용자는 실제 DB 장애인지 빈 DB인지 구분하기 어렵다. 특히 `list_sessions()` 오류가 `[]`로 반환되면 기존 히스토리가 사라진 것처럼 보일 수 있어 데이터 신뢰도에 직접 영향을 준다.

근거:
- `load_session()`은 예외를 `logger.exception("세션 로드 오류")` 후 `return None`으로 처리한다.
- `list_sessions()`는 예외를 `logger.exception("세션 목록 조회 오류")` 후 `return []`로 처리한다.
- `delete_session()`은 예외 후 rollback하고 `return False`로 처리한다.
- `get_statistics()`는 예외 후 `return {}`로 처리한다.
- UI result handler는 `db_history_list` 결과가 빈 list면 "저장된 세션이 없습니다."를 표시하고, `db_stats`는 `{}`도 정상 통계 dialog로 표시한다.
- 반대로 `tests/test_database_manager.py::test_database_search_reraises_unexpected_connection_errors`는 검색 오류 전파만 검증한다.

권장 수정 방향:
예상 가능한 "not found"와 실제 DB 오류를 분리한다. `load_session()`의 미존재는 `None` 유지가 가능하지만 DB 연결/쿼리 오류는 re-raise하거나 `DatabaseOperationResult(error=...)` 같은 구조로 반환해야 한다. `list_sessions()`, `get_statistics()`, `delete_session()`도 unexpected DB 오류는 `DBWorker`의 `db_task_error`로 전파되게 맞춘다. UI는 "데이터 없음"과 "DB 오류"를 별도 메시지로 표시해야 한다.

우선순위: High

조치 상태: 완료 (2026-06-11). `core/database_impl/sessions.py`, `core/database_impl/search_stats.py`에서 unexpected DB 예외를 re-raise하도록 수정했고, `tests/test_database_manager.py`에 read/list/stats/delete 오류 전파 테스트를 추가했다.

### 3.2 `_clear_message_queue()`가 저장/로드/DB control 메시지까지 삭제할 수 있음

위치: `ui/main_window_impl/pipeline_queue.py` `_clear_message_queue()` / `ui/main_window_impl/runtime_lifecycle.py` `_start()`, `_stop()` / `ui/main_window_impl/persistence_session.py` `_start_async_session_snapshot_save()` / `ui/main_window_impl/pipeline_messages.py` `session_save_done`, `session_save_failed`

문제:
`_start()`와 `_stop()`은 capture run 정리를 위해 `_clear_message_queue()`를 호출한다. 그런데 `_clear_message_queue()`는 raw queue뿐 아니라 `_coalesced_control_messages`, `_overflow_passthrough_messages`, `_terminal_worker_messages`까지 모두 비운다. control message에는 `session_save_done`, `session_save_failed`, `session_load_done`, `db_task_result`, `hydrate_done`, `runtime_segment_flush_done` 등이 포함된다.

영향:
세션 저장 background worker가 완료 메시지를 queue/coalesced control에 넣은 직후 사용자가 capture 시작/중지를 누르면 완료 메시지가 삭제될 수 있다. 이 경우 `_session_save_in_progress`는 `True`로 남고, dirty session clear, DB identity 반영, pending deferred action resume가 실행되지 않을 수 있다. 이후 세션 불러오기/병합 등은 `_block_session_replacement_while_saving()`에 의해 계속 막힐 가능성이 있다.

근거:
- `_start()`는 runtime archive 시작 후 `_clear_message_queue()`를 호출한다.
- `_stop()`은 worker shutdown/finalize 후 `_clear_message_queue()`를 호출한다.
- `_clear_message_queue()`는 queue drain 후 `_coalesced_control_messages.clear()`, `_overflow_passthrough_messages.clear()`, `_terminal_worker_messages.clear()`를 수행한다.
- `_start_async_session_snapshot_save()`는 `_session_save_in_progress = True`로 설정한 뒤 background thread가 `session_save_done` 또는 `session_save_failed` control message를 emit한다.
- `_session_save_in_progress`를 `False`로 되돌리는 코드는 `pipeline_messages._handle_message()`의 `session_save_done/session_save_failed` 처리 경로다.
- 기존 테스트는 queue full일 때 `session_save_done`이 coalesced control로 보존되고 drain되는지만 검증하고, `_clear_message_queue()`와 completion race는 직접 검증하지 않는다.
- CodeGraph impact 기준 `_clear_message_queue`는 start/stop/close, persistence save/load, runtime hydration/search/segment flush, DB worker result까지 폭넓게 닿는다.

권장 수정 방향:
worker capture run 메시지와 앱 control message를 분리한다. `_clear_message_queue()`는 stale `WorkerQueueMessage`만 제거하고, `session_*`, `db_task_*`, `hydrate_*`, `runtime_*`, `reflow_*` 같은 durable control message는 보존하거나 먼저 처리해야 한다. 추가로 `_start()`는 `_session_save_in_progress` 또는 `_session_load_in_progress`가 true일 때 시작을 차단하거나 완료 drain 후 진행해야 한다.

우선순위: High

조치 상태: 완료 (2026-06-11). `ui/main_window_impl/pipeline_queue.py`의 `_clear_message_queue()`가 durable control message를 보존하도록 수정했고, `ui/main_window_impl/runtime_lifecycle.py`의 `_start()`에 세션 저장/로드 진행 중 시작 차단을 추가했다. 관련 회귀 테스트는 `tests/test_lossless_session_plan_20260401.py`에 추가했다.

### 3.3 live_list/page/query에서 얻은 `xcode`, `xcgcd`가 검증/인코딩 없이 URL과 CSS selector에 삽입됨

위치: `core/live_list.py` `normalize_live_list_row()`, `apply_live_broadcast_to_url()` / `ui/main_window_impl/capture_live.py` `_get_query_param()`, `_set_query_param()`, `_detect_live_broadcast()`

문제:
live_list API row의 `xcode`, `xcgcd`는 문자열 trim만 거친 뒤 URL query에 직접 붙는다. 페이지/사용자 URL에서 얻은 `target_xcode`도 CSS selector 문자열에 직접 보간된다. host는 `assembly.webcast.go.kr`로 제한되지만, query 값 자체의 문자 집합/길이/URL encoding/CSS escaping은 보장되지 않는다.

영향:
공식 API가 일시적으로 이상한 값을 반환하거나 사용자가 특수문자가 포함된 `xcode` URL을 입력하면 자동 생중계 감지 URL이 깨지거나, 추가 query parameter가 삽입되거나, Selenium selector가 invalid selector 예외를 만들 수 있다. 대부분 예외는 catch되지만 감지 실패/잘못된 URL 적용으로 이어질 수 있다.

근거:
- `normalize_live_list_row()`는 `xcgcd = str(...).strip()`, `xcode = str(...).strip()`만 수행한다.
- `apply_live_broadcast_to_url()`은 `name=value`를 문자열 치환/이어붙이기로 직접 구성한다.
- `_set_query_param()`도 value를 그대로 삽입한다.
- `_detect_live_broadcast()`는 `target_xcode`를 `f'a.onair[href*="xcode={target_xcode}"]'` 같은 CSS selector에 직접 넣는다.
- 테스트는 live row 선택, ambiguous 처리, live_list 오류 표시는 다루지만, `&`, `"`, `]`, whitespace 같은 query/selector 특수문자 방어는 보이지 않는다.

권장 수정 방향:
`xcode`, `xcgcd`의 허용 패턴과 길이를 명시한다. 예: `xcode`는 현재 운영 코드 체계에 맞는 `[A-Za-z0-9]{1,10}` 수준으로 제한하고, `xcgcd`는 실제 포맷을 기준으로 허용 문자/길이를 제한한다. URL 수정은 `urllib.parse.urlsplit`, `parse_qsl`, `urlencode`, `urlunsplit` 기반으로 처리한다. CSS selector는 query 값을 직접 보간하지 말고 링크 href를 수집해 URL parser로 비교하거나 CSS escaping을 적용한다.

우선순위: Medium

조치 상태: 완료 (2026-06-11). `core/live_list.py`에 `normalize_live_xcode()`, `normalize_live_xcgcd()`, `set_live_query_param()`를 추가했고, `ui/main_window_impl/capture_live.py`는 URL parser 기반 비교와 안전한 query 조립을 사용하도록 수정했다. malformed live row/query와 invalid xcode 자동 감지 차단 테스트를 추가했다.

### 3.4 세션 JSON 저장 후 DB 저장을 무기한 대기할 수 있음

위치: `ui/main_window_impl/persistence_session.py` `_write_session_snapshot()` / `ui/main_window_impl/database_worker.py` `_run_db_task_sync()`

문제:
세션 저장은 JSON snapshot을 먼저 원자 저장한 뒤, 같은 background save thread 안에서 `_run_db_task_sync("db_session_save", ..., timeout=None)`로 DB 저장 완료를 무기한 기다린다. DB worker가 SQLite lock, 장기 작업, 예기치 못한 deadlock에 걸리면 background save thread가 끝나지 않는다.

영향:
JSON 파일은 이미 저장되었더라도 UI에는 `session_save_done`이 오지 않아 `_session_save_in_progress`가 유지될 수 있다. 종료 시에는 background thread 대기/escalation modal로 이어지고, dirty action의 "저장 후 원래 액션 재개" 흐름도 진행되지 않는다.

근거:
- `_write_session_snapshot()`은 `atomic_write_json_stream()`으로 JSON을 쓴 뒤 DB 저장을 수행한다.
- DB 저장 호출은 `_run_db_task_sync(..., write_task=True, timeout=None)`이다.
- `_run_db_task_sync()`는 `done_event.wait(timeout=None)`이면 완료될 때까지 무기한 대기한다.
- `DBWorker`는 단일 thread/queue 구조이므로 이전 작업이 막히면 후속 sync save도 같이 막힌다.

권장 수정 방향:
JSON 저장 성공을 primary success로 유지하고, DB 저장은 충분히 긴 finite timeout이나 watchdog을 둔다. timeout 시 `db_error`를 채워 `session_save_done`은 emit하되 "JSON 저장 완료, DB 저장 지연/실패"를 사용자에게 표시하는 편이 데이터 손실 오인을 줄인다. DB worker queue health도 shutdown diagnostic에 이미 있으므로, timeout 시 diagnostic 저장을 연결할 수 있다.

우선순위: Medium

조치 상태: 완료 (2026-06-11). `_write_session_snapshot()`의 DB 저장 동기 대기를 `Config.DB_SYNC_TASK_TIMEOUT_SECONDS`로 제한했고, timeout은 JSON 저장 성공과 별개의 `db_error`로 보고되도록 기존 반환 구조를 유지했다. 관련 테스트를 `tests/test_session_stability_followup_plan_20260405.py`에 추가했다.

## 4. Potential Functional Gaps

- 조치 완료: `_start()`가 `_session_save_in_progress`/`_session_load_in_progress`를 직접 확인하지 않아 새 capture run을 시작할 수 있던 추정 gap은 시작 차단으로 보완했다.
- 조치 완료: 일반 JSON 세션 로드가 `json.load()`로 전체 파일을 메모리에 올리는 추정 gap은 백그라운드 로드 시작 전 파일 크기 guard로 1차 보완했다.
- 조치 완료: DB read-only/locked/corrupt 상황에서 search 외 기능의 오류 전파 테스트가 부족했던 gap은 cursor 오류 re-raise 테스트로 보강했다.
- 조치 완료: live_list `xcode/xcgcd` malformed query value가 URL builder와 selector builder를 깨지 않는지에 대한 테스트를 추가했다.
- 잔여 추정: 파일 저장 background export는 성공/실패를 주로 toast/control message로 전달한다. 이번 `_clear_message_queue()` 보존 변경으로 start/stop clear에 의한 유실 위험은 줄었지만, 장기적으로 app control queue와 capture worker queue를 분리하면 더 명확하다.

## 5. Recommended Fix Plan

### 1단계: 즉시 수정해야 할 문제

상태: 완료 (2026-06-11)

1. DB 조회/로드/삭제/통계의 예외 처리 정책을 검색과 맞춘다.
   - `list_sessions()`, `load_session()`, `delete_session()`, `get_statistics()`에서 unexpected DB exception을 re-raise한다.
   - UI에서는 not found/empty와 DB error를 분리해 메시지를 표시한다.
2. `_clear_message_queue()`를 worker-run cleanup과 app-control cleanup으로 분리한다.
   - start/stop에서 stale worker message만 제거한다.
   - `session_save_done/failed`, `session_load_*`, `db_task_*`, `hydrate_*`, `runtime_*`, `reflow_*`는 보존하거나 처리 후 clear한다.
3. `_start()` 전에 `_session_save_in_progress`/`_session_load_in_progress`를 확인해 진행 중인 저장/로드가 있으면 시작을 차단한다.

### 2단계: 안정성 개선

상태: 완료 (2026-06-11)

1. DB session save sync wait에 finite timeout 또는 watchdog을 둔다.
2. `xcode`, `xcgcd` 값 검증/encoding을 중앙 유틸로 분리하고 URL query 조작을 `urllib.parse` 기반으로 바꾼다.
3. CSS selector에 query 값을 직접 넣는 경로를 제거하거나 escaping/URL parser 기반 비교로 바꾼다.
4. 일반 JSON 세션 파일 로드에 파일 크기/entry count guard 또는 streaming load 전략을 검토한다.

### 3단계: 구조 개선

상태: 후속 리팩터링 후보. 이번 변경은 공개 API/동작면의 기능 리스크를 줄이는 범위로 제한했고, queue/DB result 타입 구조 개편은 별도 작업으로 분리하는 것이 안전하다.

1. DB API를 `None/[]/False/{}` 반환 중심에서 `Result` 계열 구조로 정리해 "정상 empty"와 "실패"를 타입 차원에서 분리한다.
2. capture worker message queue와 app background control queue를 논리적으로 분리한다.
3. shutdown/start/stop race 테스트를 공통 fake queue/fake background worker fixture로 만들고, 세션 저장/로드/runtime flush/DB worker result를 같은 패턴으로 검증한다.

## 6. Test Recommendations

1. DB 오류 전파 테스트
   - `_get_connection()` 또는 cursor execute가 `sqlite3.OperationalError`를 던질 때 `list_sessions()`, `load_session()`, `delete_session()`, `get_statistics()`가 실제 오류를 UI `db_task_error`로 전달하는지 검증한다.
   - 빈 DB와 DB 오류가 서로 다른 UI 메시지를 내는지 검증한다.
   - 상태: DB 메서드 예외 전파 테스트를 추가했고 전체 검증에서 통과했다.

2. queue clear race 테스트
   - `session_save_done`이 raw queue 또는 `_coalesced_control_messages`에 있는 상태에서 `_start()` 또는 `_stop()`을 호출해도 `_session_save_in_progress`가 해제되고 dirty/deferred action이 정상 처리되는지 검증한다.
   - `_clear_message_queue()`가 stale `WorkerQueueMessage`만 제거하고 durable control message는 보존하는지 검증한다.
   - 상태: durable control message 보존과 세션 저장/로드 중 시작 차단 테스트를 추가했고 전체 검증에서 통과했다.

3. 세션 저장 DB worker hang 테스트
   - DB worker task가 완료되지 않는 상황을 fake로 만들고, JSON 저장 성공이 사용자에게 완료/경고로 표시되며 UI가 영구 저장 중 상태에 갇히지 않는지 검증한다.
   - 상태: DB 동기 저장 호출이 설정 타임아웃을 사용하는지와 timeout이 `db_error`로 반환되는지 테스트했다.

4. live URL query validation 테스트
   - live_list row의 `xcgcd`, `xcode`에 `&`, `=`, `"`, `]`, whitespace, 매우 긴 값이 들어왔을 때 reject 또는 percent-encode되는지 검증한다.
   - `target_xcode`가 특수문자를 포함해도 Selenium CSS selector가 invalid selector를 만들지 않는지 검증한다.
   - 상태: malformed row reject, query replacement, invalid xcode 감지 차단 테스트를 추가했다.

5. 큰/손상 세션 파일 테스트
   - 단일 JSON 세션 파일이 너무 큰 경우 사용자에게 명확한 오류/확인을 보여주는지 검증한다.
   - runtime manifest strict/salvage 경로는 이미 잘 나뉘어 있으므로, segment integrity mismatch와 tail checkpoint 누락 케이스를 계속 유지한다.
   - 상태: oversized JSON 세션 파일이 백그라운드 worker 시작 전에 차단되는지 테스트했다.

6. 회귀 게이트
   - 기능 수정 후 최소 `pytest -q`, `python -m pyright --outputjson`, `python "국회의사중계 자막.py" --smoke --smoke-storage-dir .pytest_tmp/smoke-storage`, 필요 시 `python scripts/run_release_verification.py --offline --skip-build --instantiate-window`를 실행한다.
   - 상태: `pytest -q`, `pyright`, source smoke, `run_release_verification.py --instantiate-window`를 모두 실행했고 통과했다.
