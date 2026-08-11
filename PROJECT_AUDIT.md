# Project Audit

감사 기준일: 2026-08-11

감사 방식: `README.md`, `CLAUDE.md` 선행 검토 → CodeGraph 호출 관계/영향 범위 분석 → 필요한 구간 직접 확인 → 회귀 테스트·정적 분석·smoke 검증

검증 결과: `pytest -q` **361 passed, 2 skipped**, pyright **0 errors / 0 warnings (138 files)**, 창 생성 smoke **성공**

## 1. Executive Summary

이 프로젝트는 국회 의사중계 웹사이트의 AI 자막을 Selenium으로 수집하고, PyQt6 UI에서 실시간 처리하며, JSON·SQLite·여러 문서 형식으로 저장하는 Windows 중심 데스크톱 애플리케이션이다. 최근 여러 차례의 안정화 작업으로 URL/selector 검증, run-scoped worker queue, 원자 저장, runtime archive 무결성 검사, DB 직렬 worker, 종료 대기 등이 잘 갖춰져 있다. 현재 전체 테스트와 pyright도 통과한다.

그러나 기능 관점의 전체 위험도는 **High**로 평가한다. Critical 급 원격 코드 실행이나 즉시 재현되는 광범위 데이터 손상은 확인하지 못했지만, 아래 두 문제는 사용자가 저장되었다고 믿은 데이터와 실제 상태를 다르게 만들 수 있다.

1. 비동기 세션 저장 완료 시 저장 시작 이후 발생한 자막/편집까지 포함해 dirty 상태를 무조건 해제한다. 저장 도중 들어온 변경이 저장되지 않았는데도 종료 경고가 사라질 수 있다.
2. DB 저장을 15초 후 실패로 보고하면서 실제 DB worker 작업은 취소되지 않고 계속된다. UI는 “DB 저장 실패”를 표시하지만 DB에는 나중에 행이 추가될 수 있어 저장 계보와 재시도 결과가 어긋날 수 있다.

그 밖에 runtime segment 및 DB 세션 전체 로드의 메모리 상한 부재, Windows 경로 대소문자 별칭을 구분하지 못하는 중복 저장 가드, 폭넓은 URL 허용 정책, 큐 포화 시 preview 유실 가능성이 있다. 자동화된 품질 게이트는 강하지만, 저장 도중 상태 변경·늦게 완료되는 DB 작업·대용량 복구 자료 같은 시간축 시나리오는 충분히 검증하지 않는다.

## 2. Project Understanding

### 목적과 사용자 기능

`README.md`와 `CLAUDE.md`에 따르면 주요 목적은 국회 의사중계의 AI 자막을 지연 없이 수집하고, 발언자 전환·중복 제거·재연결을 처리한 뒤 TXT, SRT, VTT, DOCX, HWPX, HWP, RTF, JSON 및 SQLite로 보존하는 것이다. 세션 저장/복구, DB 검색, 장시간 세션 runtime archive, 실시간 저장, 생중계 목록, 사용자 프리셋도 제공한다.

### 구조

- 엔트리포인트: `국회의사중계 자막.py`
- UI 조립: `ui/main_window.py`의 `MainWindow`가 runtime, capture, pipeline, view, persistence, database, UI mixin을 조합한다.
- 수집: `ui/main_window_impl/capture_*`가 Chrome WebDriver, live URL 해석, MutationObserver, structured probe, 재연결을 담당한다.
- 자막 처리: `core/live_capture.py`, `core/subtitle_pipeline.py` 및 각각의 `*_impl` 모듈이 row reconciliation, suffix 기반 증분 추출, merge/reset/keepalive를 담당한다.
- 메시지 전달: capture worker는 `MainWindowMessageQueue`, 저장/DB/hydrate 등 control-plane은 `AppControlMessageQueue`를 사용한다.
- 저장/복구: `ui/main_window_impl/persistence_*`가 JSON 저장, 자동 백업, 여러 형식 export, runtime manifest/segment/tail을 관리한다.
- DB: `core/database_manager.py` facade와 `core/database_impl/*`가 SQLite schema, FTS, 세션 저장/로드/검색을 담당하고, UI에서는 단일 `DBWorker`가 작업을 직렬화한다.
- 설정/경로: `core/config.py`가 development, portable, frozen 모드별 storage root와 시간·크기 상한을 정의한다.

### 주요 실행 흐름

CodeGraph에서 확인한 대표 호출 흐름은 다음과 같다.

1. 시작: `MainWindow._start()` → URL/selector 검증 → dirty/기존 세션 보호 → `_begin_extraction_run()` → non-daemon `ExtractionWorker` 시작.
2. 수집: `_extraction_worker()` → live URL 해석 → Chrome/자막 레이어 활성화 → Observer/structured probe → `_emit_worker_message()`.
3. 처리: `_process_message_queue()` → `_handle_message()` → structured payload는 `_apply_structured_preview_payload()` → `apply_preview()`/`commit_live_row()` → `CaptureSessionState.entries` 갱신.
4. 중지: `_stop()` → `stop_event` 설정 → pending preview drain/finalize → driver/worker 종료 대기 → realtime 저장 및 UI 상태 정리.
5. 세션 저장: `_save_session()` → snapshot clone → `_start_async_session_snapshot_save()` → `_write_session_snapshot()` → JSON 원자 저장 → `_run_db_task_sync()` → `DatabaseManager.save_session()`.
6. 장시간 세션: active tail이 임계값을 넘으면 `_maybe_schedule_runtime_segment_flush()`가 segment를 기록하고, 완료 메시지 처리 후 메모리 prefix를 제거하고 manifest/tail을 갱신한다.
7. DB 로드: `_start_db_session_load()` → `DBWorker` → `DatabaseManager.load_session()` → 전체 subtitle 목록 역직렬화 → `_complete_loaded_session()`에서 현재 세션 교체.

### 문서와 구현의 주요 불일치

- `CLAUDE.md:336`은 세션 저장의 DB sync save가 “timeout 없이 DB worker 완료를 기다린다”고 설명하지만, 실제 `ui/main_window_impl/persistence_session.py:435-454`는 `Config.DB_SYNC_TASK_TIMEOUT_SECONDS`를 전달하고 `core/config.py:514`의 값은 15초다.
- `CLAUDE.md:317`에는 timeout 실패를 명시적으로 처리한다고도 적혀 있어 같은 문서 안에서도 계약이 충돌한다. 현재 구현은 timeout을 “실패로 표시”할 뿐 실행 중인 DB 작업을 취소하지 않으므로, 완료 의미론까지 처리한 것은 아니다.
- README의 장시간 세션 메모리 절감 설명은 수집/runtime archive 경로에는 대체로 맞지만, DB 세션 로드는 여전히 전체 행을 `fetchall()`하고 전부 메모리에 materialize한다.

## 3. High-Risk Issues

### 3.1 비동기 저장 완료가 저장 이후 변경까지 clean 처리

* 위치: `ui/main_window_impl/persistence_session.py:63-101`, `ui/main_window_impl/pipeline_messages.py:366-387`, `ui/main_window_impl/runtime_driver.py:438-445`, `ui/main_window_impl/pipeline_state.py:457-468`
* 문제: 세션 저장은 시작 시 entry snapshot을 clone하지만, 저장 완료 메시지를 처리할 때 현재 상태의 revision을 비교하지 않고 `_clear_session_dirty()`를 무조건 호출한다. dirty 상태는 boolean 하나뿐이며 저장 시작 시점과 현재 시점을 구분하지 않는다.
* 영향: 저장 worker가 실행되는 동안 새 자막이 들어오거나 사용자가 편집/삭제하면 그 변경은 저장 파일에 없을 수 있다. 그런데 저장 완료 후 세션은 clean으로 표시되어, 이후 종료 시 저장 확인 없이 변경이 유실될 수 있다.
* 근거: `_start_async_session_snapshot_save()`는 `snapshot_entries`를 고정한 후 background worker를 시작한다. 자막 갱신 경로는 계속 `_mark_session_dirty()`를 호출하지만, `session_save_done` 분기는 순서와 무관하게 `_clear_session_dirty()`를 실행한다. `_is_runtime_mutation_blocked()`도 실행 중 캡처/종료만 검사하고 `_session_save_in_progress`는 검사하지 않는다. CodeGraph 영향 범위상 capture pipeline, 편집, 병합 등 여러 mutation 경로가 동일 boolean을 공유한다.
* 권장 수정 방향: 세션에 단조 증가하는 `session_revision`을 두고 모든 mutation에서 증가시킨다. 저장 시작 시 revision을 payload에 캡처하고, 완료 시 현재 revision이 동일할 때만 clean 처리한다. 다르면 “스냅샷 저장 완료, 이후 변경은 미저장” 상태를 유지한다. 최소 수정으로는 저장 도중 모든 mutation을 차단할 수 있으나 실시간 캡처 저장 요구와 충돌하므로 revision 방식이 적합하다.
* 우선순위: **High**

### 3.2 DB 저장 timeout 뒤 작업이 계속되어 UI와 DB 상태가 분기

* 위치: `ui/main_window_impl/database_worker.py:141-177`, `ui/main_window_impl/persistence_session.py:415-464`, `core/database_impl/sessions.py:23-145`, `ui/main_window_impl/pipeline_messages.py:366-387`
* 문제: `_run_db_task_sync()`는 15초 동안 `done_event`를 기다린 뒤 `TimeoutError`를 발생시키지만, 큐에 들어간 작업을 취소하거나 결과를 후속 전달하지 않는다. `DatabaseManager.save_session()`은 계속 실행되어 나중에 commit할 수 있다.
* 영향: UI는 “JSON 저장 완료, DB 저장 실패”라고 알리고 `db_session_id`를 적용하지 않지만, DB에는 뒤늦게 세션이 생성될 수 있다. 사용자가 재시도하면 중복 저장본이 생기고, `parent_session_id`가 직전 저장본을 가리키지 않는 등 계보가 부정확해질 수 있다. 종료/재시도 시점에 따라 결과가 비결정적이다.
* 근거: `persistence_session.py:453`은 15초 상수를 넘기며, timeout 시 `db_saved=False`로 반환한다. 반면 `database_worker.py:170-174`는 대기자에게 예외만 반환하고 task 취소 상태를 기록하지 않는다. DB 저장은 하나의 transaction을 `commit()`할 때까지 계속된다. `tests/test_session_stability_followup_plan_20260405.py:506-522`도 현재 timeout 전달과 즉시 실패 보고만 고정하며 늦은 commit을 검증하지 않는다. `CLAUDE.md:336`의 timeout-free 설명과도 어긋난다.
* 권장 수정 방향: 세션 저장의 DB 단계는 문서 계약대로 `timeout=None`으로 완료를 기다리거나, task ID와 명시적 취소/late-completion 상태를 도입한다. SQLite 작업은 안전하게 중단하기 어려우므로 “timeout=실패”로 단정하지 말고 “계속 처리 중” 상태와 최종 결과를 UI에 전달하는 방식이 안전하다. 재시도에는 idempotency key 또는 저장 operation ID를 적용한다.
* 우선순위: **High**

### 3.3 runtime manifest의 개별 segment 크기 제한 부재

* 위치: `ui/main_window_impl/persistence_session.py:177-224`, `ui/main_window_impl/persistence_runtime_manifest.py:99-145`, `ui/main_window_impl/persistence_runtime_segments.py:374-419`, `core/config.py:338`
* 문제: 일반 세션 파일은 background load 전에 100MB 상한을 검사하지만, runtime manifest가 참조하는 `segment_*.json`은 크기를 검사하지 않고 `json.load()`로 전체 파일을 읽는다. salvage 모드는 디렉터리의 모든 `segment_*.json`을 열거한다.
* 영향: 손상되었거나 조작된 작은 manifest가 매우 큰 sibling segment를 참조하면 일반 세션 크기 제한을 우회해 메모리 고갈, 긴 UI 대기, 프로세스 종료를 유발할 수 있다. 정상 장시간 세션도 segment 수/크기가 비정상적으로 커지면 같은 문제가 생긴다.
* 근거: `_start_session_load_from_path()`는 선택한 manifest 파일 자체에만 `SESSION_LOAD_MAX_BYTES`를 적용한다. `_read_runtime_entries_file()`은 `Path.stat()`이나 누적 byte/entry budget 없이 바로 `json.load(f)`를 수행한다. 경로 탈출은 `_resolve_runtime_relative_path()`가 방어하지만 resource budget은 없다.
* 권장 수정 방향: manifest, 각 segment, tail checkpoint에 개별 크기 상한과 전체 누적 byte/entry 상한을 적용한다. 가능하면 streaming parser를 사용하고, `HYDRATE_MAX_ENTRIES`와 동일한 정책을 load/salvage 단계에도 적용한다. 초과 시 손상 파일과 구분되는 명확한 오류를 사용자에게 표시한다.
* 우선순위: **High**

### 3.4 DB 세션 로드가 전체 자막을 중복 materialize

* 위치: `core/database_impl/sessions.py:147-214`, `ui/main_window_impl/database_dialogs.py:83-174`, `ui/main_window_impl/pipeline_messages.py:65-169`
* 문제: `DatabaseManager.load_session()`은 해당 세션의 모든 subtitle을 `fetchall()`한 뒤 dict list로 만들고, UI worker는 이를 다시 `SubtitleEntry` list로 역직렬화한다. runtime hydrate의 `HYDRATE_MAX_ENTRIES`와 같은 상한이나 cancel/pagination이 적용되지 않는다.
* 영향: DB에 저장된 매우 긴 세션을 불러올 때 row list, dict list, model list가 겹쳐 메모리 사용량이 급증한다. DBWorker가 직렬이므로 이 시간 동안 다른 DB 작업도 모두 대기한다. 백그라운드 실행이라 UI event loop 자체는 살아 있어도 메모리 압박과 종료 지연이 발생할 수 있다.
* 근거: SQL 결과는 `cursor.fetchall()`로 전량 로드되며, list comprehension으로 새 payload를 만든다. `_start_db_session_load()`는 다시 `_deserialize_subtitles()`를 호출한다. CodeGraph 호출 경로에는 streaming iterator나 entry limit가 없다. README의 장시간 세션 지원은 runtime archive에만 적용되고 DB reload에는 이어지지 않는다.
* 권장 수정 방향: 세션 metadata와 subtitle page/iterator를 분리하고 `fetchmany()`로 점진 로드한다. UI에는 진행률·취소·최대 엔트리 확인을 제공하고, 큰 DB 세션은 runtime archive와 같은 segment-backed representation으로 직접 연결한다.
* 우선순위: **Medium**

### 3.5 Windows에서 대소문자 별칭으로 동일 파일 동시 저장 가능

* 위치: `ui/main_window_impl/persistence_exports.py:36-110`
* 문제: 중복 저장 가드는 `str(Path(path).resolve())`를 set key로 사용한다. Windows 파일 시스템은 일반적으로 대소문자를 구분하지 않지만 문자열 set은 구분하므로, 경로 casing만 다른 두 입력이 같은 실제 파일을 서로 다른 key로 통과할 수 있다.
* 영향: 동일 대상에 두 `FileSaveWorker`가 동시에 원자 교체를 수행해 마지막 완료 작업이 앞선 결과를 덮어쓴다. 확장자가 다른 export를 동일 파일명으로 강제 선택한 경우 사용자가 예상하지 못한 내용이 남을 수 있다.
* 근거: 실제 Windows 환경에서 `Path(r'D:\AuditCase\Foo.txt').resolve()`와 `Path(r'd:\auditcase\foo.TXT').resolve()`는 casing이 다른 문자열로 유지됐다. 현재 회귀 테스트는 정확히 동일한 문자열 경로의 중복만 검사한다.
* 권장 수정 방향: Windows에서는 `os.path.normcase(os.path.realpath(path))` 또는 동등한 canonical key를 사용한다. 가능하면 파일 ID 기반 확인도 고려하고, 대소문자/상대경로/심볼릭 링크 별칭 테스트를 추가한다.
* 우선순위: **Medium**

### 3.6 URL 검증이 host/scheme만 확인해 기능적으로 무효한 URL을 시작 단계에서 허용

* 위치: `core/url_policy.py:23-47`, `ui/main_window_impl/runtime_lifecycle.py:85-116`, `ui/main_window_impl/ui/history_presets.py:178-191`
* 문제: URL 정책은 `http/https`와 `assembly.webcast.go.kr` 계열 host만 확인한다. URL 길이, userinfo/port, player/pressplayer 경로, `xcode`/`xcgcd` 형식은 시작 시 검증하지 않는다.
* 영향: 같은 host의 임의 경로, 비정상적으로 긴 query, 잘못된 방송 파라미터가 히스토리·프리셋에 저장되고 worker까지 시작된다. 사용자는 입력 시점이 아니라 Chrome 실행·selector 탐색 이후에 실패를 보게 되며, 불필요한 재연결과 오류 로그가 발생한다.
* 근거: `validate_assembly_url()`은 scheme과 hostname 검사 후 원문 URL을 그대로 반환한다. 반면 `core/live_list.py`에는 `xcode`/`xcgcd` 형식 검증 함수가 이미 있으나 일반 시작 URL 검증과 연결되지 않았다.
* 권장 수정 방향: 허용 path와 port를 명시하고, player URL에는 query key를 case-insensitive하게 정규화한 뒤 `normalize_live_xcode()`/`normalize_live_xcgcd()`를 적용한다. 전체 URL 및 프리셋 이름/태그 길이도 제한한다. 기자회견 URL은 별도 정책으로 유지한다.
* 우선순위: **Medium**

### 3.7 큐 포화 시 preview가 의도적으로 유실될 수 있음

* 위치: `ui/main_window_impl/pipeline_queue.py:104-175`, `ui/main_window_impl/pipeline_queue.py:189-236`, `core/config.py:290`, `ui/main_window_impl/pipeline_messages.py:171-220`
* 문제: worker queue가 가득 차면 preview를 overflow passthrough에 보존하지만 이 목록도 128개로 제한되며, 한도를 넘으면 낮은 우선순위 메시지를 삭제한다. preview는 terminal/segment보다 낮은 우선순위다.
* 영향: UI가 장시간 멈추거나 preview 생산량이 급증하면 중간 preview가 삭제된다. 이후 payload가 충분한 누적 문맥을 포함하면 복구될 수 있지만, 짧은 발화·reset 경계·DOM 교체와 겹치면 누락 가능성이 남는다. 사용자 경고가 있어 silent failure는 아니지만 데이터 완전성은 보장되지 않는다.
* 근거: `_trim_overflow_passthrough_messages()`는 `OVERFLOW_PASSTHROUGH_MAX=128`을 넘을 때 가장 낮은 priority부터 제거한다. 테스트는 drop 카운터와 알림을 검증하지만, drop 이후 실제 자막 복원 여부를 end-to-end로 검증하지 않는다.
* 권장 수정 방향: preview payload의 누적/증분 계약을 명확히 하고 sequence number와 gap detection을 추가한다. gap 발생 시 structured full snapshot을 즉시 요청하거나 disk-backed spool로 복구한다. 최소한 세션 결과에 drop 발생 사실과 구간을 남겨야 한다.
* 우선순위: **Medium**

## 4. Potential Functional Gaps

아래 항목은 코드에서 완전한 제품 요구사항을 확인할 수 없어 **추정**으로 분류한다.

1. **추정 — 저장 revision/operation history UI**: 현재 저장 성공/실패 토스트만 있고 “어느 revision까지 저장되었는지” 확인할 방법이 없다. 실시간 캡처 중 수동 저장을 공식 지원한다면 저장 시점과 이후 미저장 변경 수를 표시할 필요가 높다.
2. **추정 — 대용량 세션 열기 전 예상 비용 안내**: runtime archive와 DB 세션 모두 entry 수·예상 메모리를 미리 보여주고 취소할 UI가 필요할 수 있다.
3. **추정 — 복구 세트 관리**: recovery state는 최신 포인터 하나를 중심으로 동작한다. runtime manifest와 5분 backup이 함께 있을 때 사용자가 여러 후보를 비교·선택하는 전용 화면은 확인되지 않았다.
4. **추정 — 수집 품질 리포트**: queue drop, suffix desync, reconnect, salvage 제외 수를 세션 metadata로 영속화하면 결과물의 신뢰도를 판단하기 쉽다. 현재는 주로 로그/토스트에 남는다.
5. **추정 — 실제 Chrome DOM 계약 테스트**: opt-in live smoke는 live-list schema 중심이며, 실제 AI 자막 버튼 활성화, iframe, multi-speaker, Observer buffer를 지속적으로 검증하는 E2E는 부족하다.
6. **추정 — 보관 데이터 보호**: 자막·URL·위원회 정보가 JSON/SQLite/log에 평문 저장된다. 사용자 환경에서 회의 자막을 민감 데이터로 취급해야 한다면 암호화, 보존 기간, 전체 삭제 기능이 필요하다.
7. **추정 — 업데이트/서명 경로**: 배포 EXE의 코드 서명, 자동 업데이트, rollback 정책은 감사 범위에서 구현을 확인하지 못했다.

## 5. Recommended Fix Plan

### 1단계 — 즉시 수정해야 할 문제

1. 세션 dirty boolean을 revision 기반으로 전환하고, async save 완료 시 저장 revision과 현재 revision을 비교한다.
2. DB save timeout 의미론을 수정한다. 완료를 기다리거나, late completion을 추적하는 operation ID/idempotency 계약을 도입한다.
3. runtime manifest/segment/tail에 개별 및 누적 byte/entry 상한을 적용하고, load 전에 검증한다.
4. 위 세 문제에 대해 실패 재현 테스트를 먼저 추가하고, 사용자에게 저장 범위를 오해시키는 성공/실패 문구를 수정한다.

### 2단계 — 안정성 개선

1. DB 세션 로드를 `fetchmany()` 기반 점진 처리로 바꾸고 progress/cancel/entry cap을 추가한다.
2. Windows save-path key를 case-insensitive canonical form으로 정규화한다.
3. 시작 URL의 path/query/길이/port 정책을 강화하고 live token 정규화 함수를 재사용한다.
4. preview에 sequence/gap detection 및 full snapshot 재요청 경로를 추가한다.
5. URL history, preset, live-list 응답에도 파일/응답 크기 상한과 문자열 길이 상한을 둔다.

### 3단계 — 구조 개선

1. `_session_dirty`, `_session_save_in_progress`, `_session_load_in_progress`, `_exit_in_progress` boolean 조합을 명시적 lifecycle state와 operation token으로 통합한다.
2. 세션 파일, runtime segment, DB load가 공통 streaming entry reader와 공통 resource budget을 사용하도록 추상화한다.
3. CodeGraph상 테스트 연결이 약한 mixin orchestration(`MainWindowDatabaseWorkerMixin`, runtime manifest writer, close continuation)에 좁은 계약 테스트를 추가한다.
4. 실제 사이트 DOM E2E와 frozen EXE 검증을 릴리스 게이트의 명시적 단계로 운영한다.

## 6. Test Recommendations

### 저장/상태 관리

1. async save 시작 후 새 자막을 append하고, 이전 snapshot 저장 완료 메시지를 처리해도 dirty가 유지되는지 검증한다.
2. async save 시작 후 편집·삭제·병합을 수행하는 각각의 시나리오에서 revision이 증가하는지 검증한다.
3. 저장 중 연속 두 번의 mutation과 저장 완료 순서를 무작위화하는 state-machine/property test를 추가한다.
4. dirty-save deferred action이 저장한 revision까지만 clean 처리하고, 이후 변경이 있으면 원래 action을 자동 재개하지 않는 정책을 검증한다.

### DB 동시성/계보

1. DB save가 timeout 직후 실제로 commit되는 fake worker 테스트를 만들고, UI 최종 상태와 `current_db_session_id`가 일치하는지 검증한다.
2. timeout 후 사용자가 재시도했을 때 idempotency key로 중복 row가 생기지 않는지 검증한다.
3. 150,000개 이상 세션을 `fetchmany()`로 로드하면서 cancel, progress, 메모리 상한, DBWorker 후속 작업 진행을 검증한다.
4. 종료 중 진행 중인 DB save를 기다리기/진단 저장/강제 종료 각 경로에서 commit 및 계보 상태를 확인한다.

### 세션/복구 입력

1. 작은 manifest가 상한을 넘는 큰 segment를 참조하는 테스트를 추가하고 `json.load()` 전에 거부되는지 확인한다.
2. segment 여러 개의 합계가 누적 budget을 넘는 경우, salvage 모드에서도 중단·경고되는지 검증한다.
3. path traversal, absolute path, symlink/junction 별칭, 손상 fingerprint, 중복 segment index를 함께 조합한 복구 테스트를 추가한다.
4. 일반 JSON 세션과 runtime manifest에 같은 entry-count/byte 정책이 적용되는지 계약 테스트를 추가한다.

### 파일/OS 호환성

1. Windows에서 drive/path/extension casing만 다른 두 경로가 동일 save key가 되는지 검증한다.
2. UNC 경로, 장경로, 읽기 전용 폴더, 네트워크 드라이브에서 원자 교체 실패와 임시 파일 정리를 검증한다.
3. UTF-8 without BOM 정책과 사용자 TXT의 `utf-8-sig` 예외를 실제 Windows 메모장/한글 round-trip fixture로 유지한다.

### 수집 파이프라인/큐

1. queue 500 + overflow 128을 모두 포화시킨 뒤 sequence gap을 감지하고 full snapshot으로 최종 자막이 복구되는지 검증한다.
2. 반복 문구가 suffix에 여러 번 나타나고 그 사이에 짧은 발화/reset/reconnect가 끼는 fuzz test를 추가한다.
3. 실제 또는 고정 DOM fixture에서 AI 버튼 active 상태, iframe, multi-speaker row, Observer clear/reset, poll fallback을 브라우저 E2E로 검증한다.
4. live-list smoke와 별도로 실제 player DOM drift를 탐지하되 외부 서비스 장애와 코드 회귀를 구분해 보고한다.

### 현재 검증 기준 유지

- `pytest -q`: 이번 감사에서 **361 passed, 2 skipped**.
- `python scripts/check_before_push.py --pyright-only`: **0 errors, 0 warnings, 138 files**.
- `python "국회의사중계 자막.py" --smoke --smoke-instantiate-window --smoke-storage-dir .pytest_tmp/audit-smoke`: storage preflight, HWPX, import, `MainWindow()` 생성 모두 성공.
- 위 결과는 강한 회귀 기준이지만, 본 감사의 주요 문제는 단일 함수 정상 동작이 아니라 작업 순서와 늦은 완료에서 발생하므로 별도의 concurrency/state 테스트가 필요하다.
