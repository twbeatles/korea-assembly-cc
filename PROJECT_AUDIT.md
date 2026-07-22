# Project Audit

> **감사 일자**: 2026-07-22  
> **대상 버전**: v16.14.8 (`Config.VERSION` = README 첫 줄에서 로드)  
> **분석 방법**: README.md · CLAUDE.md 정독 → CodeGraph MCP(`codegraph_explore`) 우선 구조 분석 → 필요 구간만 보조 grep/파일 열람 → `pytest -q` · `pyright --outputjson` 교차 검증  
> **범위**: 기능 구현 관점(잠재 결함, 예외/검증, 상태·비동기, I/O·DB, 보안, 테스트, 문서 정합).  
> **후속 구현**: 2026-07-22 — 본 문서 1~2단계 핵심 반영 완료 (`tests/test_project_audit_20260722.py`).  
> **후속 검증**: `pytest -q` **306 passed / 2 skipped**, `pyright` **0 errors**.

---

## 1. Executive Summary

국회 의사중계 AI 자막을 **PyQt6 UI 스레드 + Selenium ExtractionWorker + 자막 파이프라인 + runtime archive + SQLite** 로 수집·저장하는 Windows 중심 데스크톱 앱이다.  
v16.14.7 감사 후속(2026-06-25), v16.14.8 자동화/TDD 보강(2026-06-30), **2026-07-22 감사 후속 수정**까지 반영된 상태다.

| 축 | 위험도 (후속 반영 후) | 한 줄 요약 |
|----|----------------------|------------|
| **기능 안정성(일반 사용)** | **Low** | 핵심 경로 방어 + 회귀 306건 |
| **극단 부하·종료 경계** | **Low–Medium** | `finished` terminal stash 경로로 수정 완료 |
| **파이프라인 정확성** | **Medium** | suffix/compact 구조 한계는 본질적으로 잔존 |
| **보안** | **Low** | URL host·selector·SQL·runtime path 가드 |
| **문서/에이전트 가이드** | **Low** | CLAUDE/GEMINI/README v16.14.8 동기화 |

**검증 결과**

| 시점 | `pytest -q` | `pyright` |
|------|-------------|-----------|
| 2026-07-22 감사 직후 | 299 passed / 2 skipped | 0 errors |
| 2026-07-22 후속 구현 후 | **306 passed / 2 skipped** | **0 errors** |

**핵심 결론 (후속 반영 후)**

1. Critical 결함 없음.  
2. High였던 worker `finished` raw put 경로는 **`_emit_worker_message(..., run_id=)` + terminal stash** 로 수정.  
3. stop 중 finished/error 멱등 흡수, Observer 짧은 발화 정책 정렬, 문서 버전 동기화 완료.  
4. 잔여: suffix 알고리즘 구조 한계(의도적 보류), Selenium E2E/CI matrix(장기).

---

## 2. Project Understanding

### 2.1 목적 (README · CLAUDE)

- 국회 의사중계 웹의 **실시간 AI 자막**을 딜레이 없이 추출·저장
- 출력: TXT / SRT / VTT / DOCX / HWPX / HWP / RTF / JSON 세션 / SQLite
- 운영 축: 자동 재연결, runtime segmented session, portable/`%LOCALAPPDATA%` 저장소, DB 검색·계보

### 2.2 아키텍처 (CodeGraph + 문서)

```
국회의사중계 자막.py
  └─ storage preflight
  └─ QApplication + MainWindow (facade + mixin 조합)

MainWindow (ui/main_window.py)
  ├─ RuntimeState / Lifecycle / Driver
  ├─ Capture (browser/dom/observer/live)
  ├─ Pipeline (queue / messages / stream / state)
  ├─ Persistence (session / runtime archive / export)
  ├─ Database (DBWorker + DatabaseManager mixin)
  └─ View / UI (render, search, theme, tray)

ExtractionWorker (non-daemon)
  -- MainWindowMessageQueue(maxsize=500, run_id envelope) --> UI
Control plane
  -- AppControlMessageQueue(maxsize=200) ------------------┘
```

### 2.3 주요 실행 흐름 (CodeGraph call path)

1. **시작**  
   `runtime_lifecycle._start()`  
   → `validate_assembly_url` + `validate_subtitle_selector`  
   → `_activate_capture_run` + runtime archive  
   → worker 큐 clear 후 `ExtractionWorker` 시작 (`daemon=False`)

2. **수집**  
   `capture_browser._extraction_worker`  
   → health check / MutationObserver / structured probe  
   → `message_queue.put((type, payload))`  
   → wrapper가 worker thread-local `run_id`가 있으면 `_emit_worker_message`로 envelope·overflow 처리

3. **처리**  
   `pipeline_messages._process_message_queue` (≈8ms / 최대 50건 + backlog follow-up)  
   → `preview` → `_prepare_preview_raw` → `_process_raw_text` (GlobalHistory + suffix)  
   → `SubtitleEntry` / UI 증분 반영

4. **재연결**  
   recoverable WebDriver 오류 → 지수 백오프 → session 재오픈  
   → `reconnected` → `_on_capture_reconnected` → `_soft_resync` + `_reconnect_preview_suppress_until_delta`

5. **중지/종료**  
   `_stop`: preview drain → finalize → worker 대기 → queue clear  
   `closeEvent`: dirty save, background/DB drain, diagnostic escalation, driver/DB 정리

### 2.4 변경 시 영향 범위 (CodeGraph blast radius 요약)

| 영역 | 대표 심볼 | 비고 |
|------|-----------|------|
| Worker 메시지 계약 | `MainWindowMessageQueue`, `_emit_worker_message`, `WorkerQueueMessage` | capture 전역 + 큐 하드닝 테스트 |
| 파이프라인 게이트 | `_prepare_preview_raw`, `_process_raw_text`, `_soft_resync` | 정확성 핵심, PIPELINE_LOCK 대상 |
| 종료 | `closeEvent`, `_wait_for_background_threads_during_exit` | 저장/DB/driver 교차 |
| DB | `DatabaseManager.save_session` / `search_subtitles` | DBWorker 직렬화 |
| URL | `validate_assembly_url` | start/preset/history 공유 |

### 2.5 이전 감사 대비 상태 (v16.14.8)

| 2026-06-30 지적 | 현재 상태 |
|-----------------|-----------|
| subprocess 회귀 샌드박스 실패 | ✅ in-process fallback + `requires_subprocess` skip (299/2) |
| `_prepare_preview_raw` 전용 테스트 부재 | ✅ `tests/test_prepare_preview_raw.py` |
| 재연결 중복 append | ✅ `_reconnect_preview_suppress_until_delta` + handshake 테스트 |
| runtime salvage 테스트 부재 | ✅ `tests/test_runtime_salvage_audit.py` |
| overflow burst | ✅ queue hardening 테스트 확장 |
| CLAUDE/GEMINI 버전 동기화 | ✅ v16.14.8 (2026-07-22 후속) |

---

## 3. High-Risk Issues

> 아래는 **실제 코드 근거**가 있는 항목만 포함한다. 추정은 §4로 분리한다.

### 3.1 Worker `finished`가 run_id 해제 후 raw put 되어 terminal 보호를 우회 — ✅ Resolved

* **위치**: `ui/main_window_impl/capture_browser.py` — `_extraction_worker()` `finally`
* **문제(감사 시점)**: `clear_worker_run_id()` 이후 raw `put(("finished", ...))`로 terminal stash 우회.
* **상태 (2026-07-22)**: **✅ 해소** — `_emit_worker_message("finished", payload, run_id=run_id)` 후 `clear_worker_run_id()`.  
  회귀: `tests/test_project_audit_20260722.py::test_extraction_worker_finished_survives_full_queue`
* **우선순위**: ~~High~~ → **Resolved**

### 3.2 글로벌 히스토리 + suffix 파이프라인의 구조적 정확성 한계

* **위치**:  
  `ui/main_window_impl/pipeline_stream.py` — `_prepare_preview_raw`, `_process_raw_text`, `_soft_resync`  
  `core/text_utils.py` — `compact_subtitle_text` 등  
  고정 문서: `PIPELINE_LOCK.md`
* **문제**: compact(공백 제거) + 고정 길이 suffix(`rfind`/`find`) 매칭은 반복 구문·ambiguous suffix·desync 구간에서 false positive/negative가 구조적으로 가능하다.  
  `_soft_resync()`는 **최근 5개 엔트리** 텍스트만으로 history를 재구성한다.
* **영향**: 같은 문장 반복, 빠른 발언자 전환, AI 인식 흔들림 구간에서 **짧은 중복·누락·잘못된 merge**가 남을 수 있다. 대부분 soft resync·reconnect suppress로 완화되나 완전 제거는 불가.
* **근거**:  
  - `_prepare_preview_raw`의 `first_pos != last_pos` ambiguous 분기 및 desync threshold resync  
  - `_soft_resync`: `self.subtitles[-5:]`  
  - 전용 테스트는 존재하나(`test_prepare_preview_raw.py`, `test_core_algorithm.py`) 실방송 길이·반복 코퍼스 수준은 아님
* **권장 수정 방향**:  
  운영 로그 키워드 모니터링 유지. 알고리즘 변경은 `PIPELINE_LOCK.md` 절차·사용자 승인 후.  
  resync window를 “최근 N compact chars”로 조정하는 실험은 회귀 fixture 선행.
* **우선순위**: **Medium**

### 3.3 중지 중(`_is_stopping`) 일반 워커 메시지 드롭과 `finished` 비화이트리스트

* **위치**:  
  `ui/main_window_impl/pipeline_messages.py` — `_handle_message` (L227–240)  
  `ui/main_window_impl/runtime_lifecycle.py` — `_stop` (L194–281)
* **문제**: `_is_stopping=True` 동안 DB/hydrate/session 계열을 제외한 메시지는 **수신 후 무시**된다.  
  화이트리스트에 `finished`/`error`/`preview`가 없다.  
  `_stop` 자체는 drain·finalize·UI reset을 수행하므로 **의도적 설계에 가깝다**.  
  그러나 큐 타이머가 stop 중간에 `finished`를 dequeue+drop 하면, §3.1과 결합 시 “종료 이벤트 미도달” 디버깅이 어려워진다.
* **영향**: 정상 수동 중지에서는 큰 문제 없음.  
  비정상 종료·부분 실패·동시 stop/error 레이스에서 **상태 정리 경로가 한쪽으로만 의존**.
* **근거**: `_handle_message` early return 목록에 terminal capture 메시지 없음. `_stop` finally에서 `_is_stopping=False`.
* **권장 수정 방향**:  
  - stop 중에도 `finished`/`error`는 no-op이 아니라 **멱등 finalize 헬퍼**로 흡수하거나  
  - drop 시 카운터/로그를 남겨 관측 가능하게  
  - §3.1 수정과 함께 종료 단일 경로 문서화
* **우선순위**: **Medium** (단독보다는 §3.1과 결합 시 의미)

### 3.4 문서·코드 버전 불일치 (에이전트/개발자 오판 유발)

* **위치**: `CLAUDE.md` / `GEMINI.md` / `README.md` / `Config.VERSION`
* **문제**: (감사 시점) AI 컨텍스트 문서가 v16.14.7에 고정되어 있었다.
* **영향**: 에이전트가 구버전 기준으로 판단할 수 있었음.
* **상태 (2026-07-22 후속)**: **✅ 해소** — CLAUDE/GEMINI/README 모두 v16.14.8, 변경 요약 절 추가.
* **우선순위**: ~~Medium~~ → **Resolved**

### 3.5 Observer 단 “짧은 발화” 필터와 파이프라인 정책 불일치 — ✅ Resolved

* **위치**: `ui/main_window_impl/capture_observer.py` — JS `isLikelySubtitleText`
* **문제(감사 시점)**: `text.length < 3` 으로 1–2자 발화 차단.
* **상태 (2026-07-22)**: **✅ 해소** — 길이 하한 제거, 한글/영문 1자 허용.  
  회귀: `test_observer_js_allows_short_hangul_utterance`
* **우선순위**: ~~Medium~~ → **Resolved**

### 3.6 overflow passthrough 상한 초과 시 preview 드롭 (완화됨, 잔존)

* **위치**: `pipeline_queue._trim_overflow_passthrough_messages`, `Config.OVERFLOW_PASSTHROUGH_MAX=128`
* **문제**: 극단 burst에서 overflow stash trim으로 메시지 손실 가능. preview coalescing 제거 후 개선됐으나 상한은 존재.
* **영향**: UI 장기 정체 + 초고속 자막 갱신 시 짧은 구간 누락
* **근거**: trim/drop 카운터·toast, `test_project_audit_queue_hardening.py`
* **권장 수정 방향**: sustained burst 부하 테스트 유지, 필요 시 preview 전용 상한/압축 정책
* **우선순위**: **Low**

### 3.7 보안·입력 검증 — 잔여이지만 낮은 위험

* **위치/상태**:
  - URL: `core/url_policy.validate_assembly_url` — scheme + `assembly.webcast.go.kr` host만 허용 (**path는 미검증**)
  - Selector: `validate_subtitle_selector` — 길이·문자 화이트리스트, JS에는 **인자 전달**(문자열 보간 삽입 아님)
  - SQL: 파라미터 바인딩 + LIKE escape
  - Runtime path: `_resolve_runtime_relative_path`로 root 이탈 차단
  - pickle/yaml.unsafe/`shell=True` 앱 런타임 경로 없음(검증 스크립트 subprocess는 로컬 개발용)
* **문제**: host 허용 내 임의의 path/query는 열 수 있음. 실질 공격면은 로컬 사용자가 악의 URL을 넣는 수준.
* **영향**: 제한적 (로컬 데스크톱 + 고정 공공 사이트)
* **권장 수정 방향**: 필요 시 path allowlist(`/main/player.asp`, `pressplayer.asp` 등) 추가
* **우선순위**: **Low**

---

## 4. Potential Functional Gaps

### 4.1 코드·테스트로 확인된 gap

| Gap | 근거 |
|-----|------|
| **Selenium/Chrome 실연동 E2E 부재** | `test_live_contract_smoke.py`는 live_list API opt-in. DOM/Observer/재연결 E2E 없음 |
| **DBWorker 전용 단위 테스트 약함** | CodeGraph: `database_worker.worker_loop` “no covering tests found”. 간접 테스트는 존재할 수 있음 |
| **impl contracts가 빈 Protocol** | `ui/main_window_impl/contracts.py`의 Host들이 `pass` 수준 → mixin 계약의 정적 강제력 약함 |
| **장시간 세션 + soft_resync 결합 시나리오** | resync는 in-memory tail 기준. archive된 과거와 compact history 정합은 간접 검증 |
| **CLAUDE/GEMINI 구버전** | §3.4 |

### 4.2 추정 gap (미확정 — “추정” 명시)

- **추정**: Python 3.14 + 핀된 PyQt6/Selenium/PyInstaller 조합은 README 권장(3.10–3.12) 밖일 수 있다. 현재 로컬 299 pass는 통과하나 장기 호환은 미검증.
- **추정**: `keep_browser_on_stop` + 즉시 재시작 시 driver handoff 레이스가 드물게 남을 수 있다(`_driver_lock`·identity helper로 상당 부분 완화).
- **추정**: 비정상 종료 직후 runtime salvage 경고가 많은 경우, 사용자 복구 UX가 여전히 복잡할 수 있다(기능 자체는 구현됨).
- **추정**: Linux/macOS는 1급 지원 대상이 아님(README Platform=Windows, HWP/pywin32/LOCALAPPDATA).
- **추정**: FTS `syntax="fts"` UI 노출이 제한적이면 raw FTS 경로는 사실상 미사용일 수 있음(literal 기본은 의도적).

### 4.3 README/CLAUDE vs 구현 정합

| 항목 | 정합 |
|------|------|
| 실시간 수집 / 재연결 / 저장 포맷 | 대체로 일치 |
| worker/control 큐 분리, non-daemon worker | 일치 |
| runtime archive + recovery | 일치 |
| URL host 정책 | 일치 |
| 버전 번호 | **불일치** (CLAUDE/GEMINI 16.14.7 vs 코드 16.14.8) |
| 짧은 발화 수집 | **부분 불일치** (Observer JS min length 3) |
| 회귀 기준선 수치 | CLAUDE 본문 여러 절이 과거 pass 수를 혼재 — README 변경 이력이 더 최신 |

---

## 5. Recommended Fix Plan

### 1단계 — 즉시 수정 (기능 경계 결함)

1. **`finished`/`error` 전달 경로 수정** (§3.1)  
   - `run_id` 캡처 → `_emit_worker_message` → 그 다음 `clear_worker_run_id`  
   - 포화 큐 회귀 테스트 추가
2. **문서 버전 동기화** (§3.4)  
   - CLAUDE.md / GEMINI.md → v16.14.8 + v16.14.8 요약 절
3. **Observer 짧은 발화 정책 정렬** (§3.5)  
   - JS `isLikelySubtitleText`를 파이프라인 게이트와 동일화

### 2단계 — 안정성 개선

1. stop 중 terminal 메시지 멱등 처리 또는 관측 로그 (§3.3)  
2. soft_resync window·ambiguous suffix 실측 로그 기반 튜닝 (PIPELINE_LOCK 준수)  
3. DBWorker enqueue/shutdown/stale token 단위 테스트 보강  
4. overflow sustained burst + finished 동시 시나리오

### 3단계 — 구조·장기 개선

1. Capture DOM 읽기 Protocol을 테스트 더블로 고정해 Chrome 없는 E2E 시뮬  
2. `contracts.py` Host에 실제 속성/메서드 시그니처 보강 (pyright 실효성)  
3. CI matrix: Python 3.10–3.12 + `pip install -r requirements-dev.txt`  
4. suffix 알고리즘 개선은 사용자 요청·로그 근거 있을 때만 (보류 권장)

---

## 6. Test Recommendations

### 6.1 필수 추가 (1단계)

| 테스트 | 내용 |
|--------|------|
| `test_worker_finished_survives_full_queue` | maxsize=1 포화 상태에서 worker finally의 `finished`가 UI 핸들러까지 도달 |
| `test_finished_emitted_with_run_id_envelope` | `clear_worker_run_id` 이후가 아니라 envelope/terminal stash 경로 사용 검증 |
| `test_observer_short_utterance_policy` | Observer 필터가 “네”/“예” 등 1–2자를 파이프라인과 동일하게 취급하는지(또는 probe 보정) |

### 6.2 안정성 보강 (2단계)

| 테스트 | 내용 |
|--------|------|
| stop 중 finished/error 멱등 | `_is_stopping=True`에서도 UI가 깨지지 않음 |
| soft_resync after 100+ entries | 최근 5개만으로 suffix 재구성 후 다음 preview delta 정확성 |
| DBWorker serial + shutdown | 종료 중 enqueue 거부, done_event, stale request token |
| reconnect + full queue | reconnected + preview suppress + finished 순서 |

### 6.3 기존 유지 게이트

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m pyright --outputjson
python "국회의사중계 자막.py" --smoke --smoke-storage-dir .pytest_tmp/smoke-storage
python scripts/run_release_verification.py --offline --skip-build --instantiate-window
```

- live 계약: `RUN_LIVE_SMOKE=1 pytest tests/test_live_contract_smoke.py` (opt-in)
- 파이프라인 변경 시: `PIPELINE_LOCK.md` §2 이력 + `test_prepare_preview_raw.py` / `test_core_algorithm.py` 필수

### 6.4 이번 감사에서 확인된 기준선

| 명령 | 결과 |
|------|------|
| `pytest -q` | 299 passed, 2 skipped |
| `pyright --outputjson` | 0 errors / 0 warnings |

---

## 7. Appendix — 이전 조치 이력 (요약)

### 2026-06-25 (v16.14.7 감사 후속)

preview coalescing 제거, overflow 우선순위 trim, stopping preview drain, control 큐 분리, `DatabaseOperationResult`, non-daemon worker, selector 검증, 재연결 soft_resync, 복구 UX 등.

### 2026-06-30 (v16.14.8)

in-process smoke/pyright fallback, `_prepare_preview_raw` 전용 테스트, reconnect handshake, runtime salvage 테스트, capture Protocol, release verifier deps/codegraph 옵션.

### 2026-07-22 (본 감사)

초기 감사: 기능 코드 변경 없음. High로 worker `finished` raw put 경로를 식별.

### 2026-07-22 (감사 후속 구현)

| 권고 | 상태 | 비고 |
|------|------|------|
| §3.1 finished run_id envelope + terminal stash | ✅ | `capture_browser.py` finally |
| §3.3 stop 중 finished/error 멱등 | ✅ | `pipeline_messages.py` |
| §3.4 CLAUDE/GEMINI 버전 동기화 | ✅ | v16.14.8 |
| §3.5 Observer 짧은 발화 | ✅ | `length < 3` 제거 |
| §3.2 suffix 구조 한계 | 보류 | PIPELINE_LOCK — 알고리즘 변경 없음, soft_resync 회귀만 보강 |
| DBWorker 단위 테스트 | ✅ | shutdown 거부 + result emit |
| contracts Protocol 보강 | ⚠️ 보류 | 시그니처 명시는 pyright abstract/override 회귀 → 문서화만 유지 |
| Selenium E2E / CI matrix | 미착수 | 장기(3단계 잔여) |

**회귀 파일**: `tests/test_project_audit_20260722.py`

---

*감사 리포트 + 후속 구현 현황 문서. suffix 알고리즘 재설계는 별도 승인 작업.*
