# Project Audit

> **감사 일자**: 2026-06-25  
> **대상 버전**: v16.14.7  
> **분석 도구**: README.md, CLAUDE.md, CodeGraph MCP (`codegraph_explore`), 보조 grep/파일 열람, `pytest -q`

## 1. Executive Summary

이 프로젝트는 국회 의사중계 웹사이트의 AI 자막을 PyQt6 GUI + Selenium worker + runtime archive + SQLite DB로 수집·저장하는 Windows 중심 데스크톱 앱이다. README.md와 CLAUDE.md 기준으로 공개 facade import 경로를 유지하면서 실제 구현은 `ui/main_window_impl/`, `core/database_impl/`, `core/subtitle_pipeline_impl/`, `core/live_capture_impl/`로 분리되어 있다.

**전체 위험도: Low–Medium**

2026-06-11 이전 감사에서 지적됐던 DB 오류 축소, `_clear_message_queue()` race, live `xcode`/`xcgcd` 검증 부재, DB sync 무기한 대기 문제는 현재 코드에서 수정·테스트로 확인됐다. 따라서 “즉시 수정” 수준의 구조 결함은 크게 줄었고, 남은 리스크는 **고빈도 자막 스트림에서의 큐 압력**, **글로벌 히스토리 suffix 알고리즘의 잔여 정확성 한계**, **Selenium worker 생명주기**, **장시간 세션 복구 모델의 사용자 기대 차이** 쪽에 집중된다.

핵심 확인 사항:

| 구분 | 요약 |
|------|------|
| 강점 | URL host 정책, storage preflight, atomic 파일 저장, runtime manifest 무결성 검증, DB degraded mode, queue overflow/terminal message 보존, dirty session/종료 escalation |
| 잔여 리스크 | suffix/compact 기반 파이프라인의 구조적 정확성 한계(알고리즘 개선은 보류), 실제 브라우저 E2E 테스트 부재 |
| 문서-구현 차이 | 2026-06-25 후속 조치로 `SUBTITLE_FINALIZE_DELAY` 제거·README runtime 백업 설명 보강 완료 |

**검증 결과**

| 시점 | pytest | pyright |
|------|--------|---------|
| 감사 당시 (2026-06-25) | 263 passed, 1 skipped | 0 errors |
| 1~3단계 조치 후 (2026-06-25) | **279 passed, 1 skipped** | **0 errors** |

CodeGraph 인덱스: 116 files, 2454 nodes, 6014 edges (Python 115)

---

## 2. Project Understanding

### 2.1 프로젝트 목적

README.md와 CLAUDE.md에 따르면 목적은 국회 의사중계 AI 자막을 **딜레이 없이** 실시간 수집하고 TXT/SRT/VTT/DOCX/HWPX/HWP/RTF/JSON/SQLite로 저장하는 것이다. 핵심 가치는 실시간 스트리밍, 멀티스레드 안정성, SQLite 세션 관리, 장시간 세션(runtime archive), frozen/portable 실행 안정성이다.

### 2.2 아키텍처 개요

```
국회의사중계 자막.py
  └─ Config.run_storage_preflight()
  └─ QApplication + MainWindow (facade)

MainWindow (ui/main_window.py)
  ├─ RuntimeLifecycle  : _start / _stop / closeEvent
  ├─ Capture           : _extraction_worker (Selenium)
  ├─ Pipeline          : preview → _prepare_preview_raw → _process_raw_text
  ├─ Persistence       : session/backup/export/runtime archive
  ├─ Database          : DBWorker + DatabaseManager
  └─ View/UI           : render/search/editing/theme

Worker Thread ──MainWindowMessageQueue──▶ UI Thread (_process_message_queue)
Background tasks ──AppControlMessageQueue─┘       └─ SubtitleEntry / render / stats
```

### 2.3 주요 실행 흐름 (CodeGraph 기준)

1. **시작**: `runtime_lifecycle._start()` → `validate_assembly_url()` + `validate_subtitle_selector()` → runtime archive 시작 → `_clear_message_queue()`(worker만) → non-daemon worker thread 시작 (`_extraction_worker`).
2. **수집**: `capture_browser._extraction_worker()` → Observer/structured probe → `message_queue.put(("preview", payload))` 등.
3. **처리**: `pipeline_messages._process_message_queue()` (약 8ms/time budget, 최대 50건) → `_prepare_preview_raw()` → `_process_raw_text()` (GlobalHistory + suffix) → `SubtitleEntry` 반영.
4. **장시간 세션**: `backups/runtime_sessions/<run_id>/manifest.json` + `segment_*.json` + `tail_checkpoint.json`. 메모리에는 tail만 유지.
5. **저장/복구**: JSON atomic write, recovery pointer(`session_recovery.json`), 5분 auto-backup(일반 모드: `backup_*.json`, runtime 모드: runtime recovery snapshot).
6. **종료**: dirty session 확인 → background thread drain → DB worker shutdown → runtime archive 정리.

### 2.4 CodeGraph 영향 범위 (변경 시 주의)

| 심볼 | blast radius |
|------|----------------|
| `_prepare_preview_raw` | 파이프라인 핵심, 직접 단위 테스트 없음 (CodeGraph 표기) |
| `_emit_worker_message` / `_clear_message_queue` | capture start/stop, persistence, DB result, runtime flush 등 40+ symbol |
| `DatabaseManager.save_session/search_subtitles` | DBWorker, history/search dialog, session save |
| `normalize_live_xcode/xcgcd` | live_list, `_detect_live_broadcast`, `LiveBroadcastDialog` |

### 2.5 이미 해소된 이전 High 이슈 (참고)

아래 항목은 2026-06-11 후속 패치 및 현재 테스트로 **해소 확인**됐다. 이번 감사의 High-Risk 목록에서는 제외한다.

- DB read/list/delete/stats의 unexpected exception re-raise (`tests/test_database_manager.py`)
- `_clear_message_queue(preserve_control_messages=True)` durable control 보존 (`tests/test_lossless_session_plan_20260401.py`)
- `_start()`의 세션 저장/로드 진행 중 시작 차단
- live `xcode`/`xcgcd` 패턴 검증 + `urllib.parse` 기반 query 조립 (`core/live_list.py`)
- DB session save sync timeout (`Config.DB_SYNC_TASK_TIMEOUT_SECONDS`)

---

## 3. High-Risk Issues

### 3.1 ~~큐 포화 시 `preview` coalescing~~ → **1단계 조치 완료 (2026-06-25)**

* **조치**: `preview`를 `COALESCED_WORKER_MESSAGE_TYPES`에서 제거. 포화 시 overflow passthrough + 우선순위 trim(`Config.OVERFLOW_PASSTHROUGH_MAX=128`) + drop 카운터/토스트.
* **테스트**: `tests/test_project_audit_queue_hardening.py`
* **잔여**: 극단적 UI 정체 시 overflow 상한 초과 drop 가능성은 남음 (3.2 참고).

### 3.2 overflow passthrough 보존 상한 초과 시 worker 메시지 드롭 → **1단계 조치 완료 (2026-06-25)**

* **조치**: 고정 64건 삭제 대신 **타입별 우선순위 trim**(terminal > preview > 기타), 상한 128건, `_record_overflow_drop()` + rate-limited status/toast.
* **테스트**: `tests/test_project_audit_queue_hardening.py`
* **우선순위**: **Low** (완화됨, 극단 burst만 잔여)

### 3.3 글로벌 히스토리 + suffix 파이프라인의 구조적 정확성 한계

* **위치**: `ui/main_window_impl/pipeline_stream.py` `_prepare_preview_raw()`, `_process_raw_text()` / `core/text_utils.py` `compact_subtitle_text()` / `utils.get_word_diff()`
* **문제**: 50자 suffix, compact(공백 제거) 매칭, 7단계 `get_word_diff` 후단 정제는 반복 구문·compact collision·ambiguous suffix 구간에서 false positive/negative를 유발할 수 있다. `rfind` 전환과 `_soft_resync()`로 완화됐지만 알고리즘 한계는 남아 있다.
* **영향**: 동일 문구 반복 회의, 빠른 발언자 전환, AI 인식 오류 구간에서 짧은 중복·누락·잘못된 merge boundary.
* **근거**: `ALGORITHM_ANALYSIS.md` §2.1–2.5, `_prepare_preview_raw()`의 ambiguous suffix 분기 및 `_soft_resync()` 호출, `CONFIRMED_COMPACT_MAX_LEN=50000` tail 정책
* **권장 수정 방향**: 운영 로그 키워드(`preview suffix desync reset`, `preview ambiguous suffix reset`) 기반 모니터링을 유지하고, 회귀 fixture(반복 구문/전환 시나리오)를 확장한다. 알고리즘 변경은 `PIPELINE_LOCK.md` 절차를 따른다.
* **우선순위**: **Medium**

### 3.4 ~~중지 시 preview drain 상한~~ → **1단계 조치 완료 (2026-06-25)**

* **조치**: `_is_stopping=True`일 때 `_drain_pending_previews()`는 `max_items` 상한 없이 preview-only complete drain.
* **테스트**: `tests/test_project_audit_queue_hardening.py`

### 3.5 ~~extraction worker daemon~~ → **3단계 조치 완료 (2026-06-25)**

* **조치**: `ExtractionWorker`를 `daemon=False`로 전환. 기존 `_wait_worker_shutdown()` + driver quit escalation과 연동.
* **잔여**: OS 강제 kill 등 비정상 종료 시 finally 미보장은 구조적으로 남음.
* **우선순위**: **Low**

### 3.6 재연결 성공 시 worker raw buffer를 초기화해 중복 수집/재동기화 churn 유발 가능

* **위치**: `ui/main_window_impl/capture_browser.py` `_extraction_worker()` 재연결 성공 분기
* **문제**: 재연결 후 `worker_last_raw_text`, `worker_last_raw_compact`를 비운다. UI 파이프라인의 `_confirmed_compact`/`_trailing_suffix`는 유지된 채 probe가 동일 full text를 다시 보낼 수 있다.
* **영향**: 재연결 직후 suffix desync → `_soft_resync()` 또는 중복 append 가능성. 대부분 수렴하지만 사용자 입장에서는 “재연결 후 같은 문장 반복”으로 보일 수 있다.
* **근거**: 재연결 성공 시 `worker_last_raw_text = ""`, `worker_last_raw_compact = ""`; UI `_prepare_preview_raw()`는 독립 history 유지
* **권장 수정 방향**: 재연결 시 UI에 “resync without duplicate append” 신호를 보내거나, worker compact gate를 UI trailing suffix와 align하는 handshake를 추가한다.
* **우선순위**: **Low**

### 3.7 ~~CSS selector 검증 부재~~ → **2단계 조치 완료 (2026-06-25)**

* **조치**: `core/selector_policy.py` `validate_subtitle_selector()` — `_start()` 시작 전 syntax/위험 패턴 검증.
* **테스트**: `tests/test_selector_policy.py`
* **잔여**: 프리셋 외 manual override confirm UI는 미구현.
* **우선순위**: **Low**

---

## 4. Potential Functional Gaps

### 확인된 gap (코드 근거 있음)

- ~~**README 자동 백업 설명과 runtime 모드 동작 차이**~~: README·복구 다이얼로그에 runtime vs flat backup 우선순위 안내 반영 (2026-06-25).
- ~~**`SUBTITLE_FINALIZE_DELAY` dead constant**~~: `core/config.py`에서 제거 (2026-06-25).
- **Selenium 실연동 테스트 부재**: `tests/test_live_contract_smoke.py`는 opt-in(`RUN_LIVE_SMOKE=1`)이며, 실제 Chrome DOM/Observer 동작을 CI에서 검증하지 않는다.
- **CodeGraph 미커버 핫패스**: `_prepare_preview_raw`, `_fetch_live_list`, `_build_salvaged_runtime_segments` 등은 blast radius는 크지만 dedicated unit test가 없거나 제한적이다.

### 추정 gap

- **추정**: 비정상 종료 후 recovery UX가 runtime archive 손상 + flat backup 부재 조합에서 “어느 복구본이 최신인지” 혼란을 줄 수 있다. salvage 경고는 코드에 있으나 UI 요약 강도는 세션마다 다를 수 있다.
- **추정**: Linux/macOS에서 PyQt6+Chrome은 동작 가능성이 있으나 README는 Windows 중심이고 HWP/pywin32/QSettings 경로는 Windows 전제다. cross-platform 공식 지원 gap.
- **추정**: 실행 중 inline full-session search cancel은 구현돼 있으나, 매우 긴 세션에서 첫 검색 latency SLA를 사용자에게 설명하는 UI는 부족할 수 있다.
- **추정**: `validate_assembly_url()`은 host만 제한하고 path는 검증하지 않는다. 같은 host의 비의도 path도 허용되나 실질 피해는 제한적이다.

---

## 5. Recommended Fix Plan

### 1단계: 즉시 수정 — **완료 (2026-06-25)**

1. preview coalescing 제외 + overflow 우선순위 trim(128) + drop 가시화
2. stopping phase preview unlimited drain
3. 재연결 시 `_on_capture_reconnected()` + `_soft_resync()` 연동

### 2단계: 안정성 개선 — **완료 (2026-06-25)**

1. `core/selector_policy.py` selector 검증
2. README runtime 백업 설명 보강, `SUBTITLE_FINALIZE_DELAY` 제거
3. 재연결 resync handshake (1단계에 포함)

### 3단계: 구조 개선 — **완료 (2026-06-25)**

1. `AppControlMessageQueue` — worker `message_queue`와 control 큐 논리 분리
2. `core/database_result.py` `DatabaseOperationResult` — empty vs error 타입 분리
3. extraction worker `daemon=False`
4. 복구 다이얼로그 runtime vs backup 우선순위 안내
5. `run_release_verification.py --with-live-smoke` 옵션

### 4단계: 잔여 (보류·미착수)

1. **suffix/compact 알고리즘 개선** — 사용자 요청으로 보류 (`PIPELINE_LOCK.md` 준수)
2. **재연결 duplicate append** 추가 handshake (3.6)
3. **opt-in live browser E2E** — `RUN_LIVE_SMOKE=1`은 release verifier 기본 경로에 포함, DOM/Observer 실연동은 미구현
4. **파이프라인 회귀 fixture** suffix collision/ambiguous 확장

---

## 6. Test Recommendations

### 6.1 큐 압력·coalescing

- fake queue를 `maxsize=1`로 만들고 연속 `preview` 100건 emit → 최종 자막이 **중간 delta 누락 없이** 재구성되는지 검증
- overflow stash 65건 이상 적재 시 `subtitle_reset`이 보존/드롭되는지, drop 통계가 노출되는지 검증
- `_is_stopping=True` 상태에서 2000건 초과 preview가 있을 때 tail 확정 보장 테스트

### 6.2 파이프라인 정확성

- 반복 구문(“네”, “감사합니다”, “위원장”) suffix collision fixture
- `subtitle_reset` 직후 첫 preview가 이전 entry와 merge되지 않는지 회귀
- 재연결 후 동일 probe text 재전송 시 duplicate append 없음/허용 정책 명시 테스트

### 6.3 persistence/recovery

- runtime archive 활성 상태 `_auto_backup()`이 flat JSON이 아닌 recovery pointer 갱신임을 검증 (이미 부분 테스트 존재 — README 행위 설명과 연계)
- manifest 손상 + sibling segment salvage 후 UI warning payload 검증
- oversized JSON `SESSION_LOAD_MAX_BYTES` 차단 회귀 유지

### 6.4 DB/종료 (기존 회귀 유지·확장)

- `test_database_read_methods_reraise_unexpected_cursor_errors` 유지
- `test_clear_message_queue_preserves_durable_control_messages` + **start/stop와 session_save_done 동시 race** 확장
- `closeEvent` escalation 경로에서 diagnostic JSON 필수 필드 검증

### 6.5 live list / URL

- `normalize_live_xcode/xcgcd` reject/accept matrix 유지
- `validate_assembly_url`에 press player URL, subdomain, invalid scheme 회귀
- **추정**: `RUN_LIVE_SMOKE=1` 주기적 opt-in으로 live_list schema drift와 병행

### 6.6 회귀 게이트 (현재 기준선)

```bash
python -m pytest -q
python -m pyright --outputjson
python "국회의사중계 자막.py" --smoke --smoke-storage-dir .pytest_tmp/smoke-storage
python scripts/run_release_verification.py --offline --skip-build --instantiate-window
```

조치 후 `pytest -q`는 **279 passed / 1 skipped**, `pyright --outputjson` **0 errors**로 통과했다.

---

## 7. 조치 구현 요약 (2026-06-25)

| 항목 | 파일/심볼 | 테스트 |
|------|-----------|--------|
| preview coalescing 제거 | `pipeline_queue.py` | `test_project_audit_queue_hardening.py` |
| overflow 우선순위 trim | `pipeline_queue.py`, `Config.OVERFLOW_PASSTHROUGH_MAX` | 동일 |
| stopping preview drain | `pipeline_stream.py` | 동일 |
| 재연결 resync | `pipeline_messages.py`, `pipeline_stream.py` | 기존 회귀 |
| selector 검증 | `core/selector_policy.py` | `test_selector_policy.py` |
| control 큐 분리 | `AppControlMessageQueue`, `app_control_queue` | `test_project_audit_phase3.py` |
| DB Result 타입 | `core/database_result.py` | `test_database_result.py` |
| non-daemon worker | `runtime_lifecycle.py` | lifecycle 회귀 |
| 복구 UX | `persistence_session.py` | `test_prompt_session_recovery_*` |
| release verifier | `run_release_verification.py --with-live-smoke` | 수동/CI |