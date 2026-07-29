# Project Audit

> **감사 일자**: 2026-07-29  
> **대상 버전**: v16.14.8 (`Config.VERSION` = README 첫 줄에서 로드)  
> **분석 방법**: README.md · CLAUDE.md 정독 → CodeGraph MCP(`codegraph_explore`) 우선 구조·호출 관계 분석 → 필요 구간만 보조 grep/파일 열람 → `pytest -q` · `pyright --outputjson` 교차 검증  
> **범위**: 기능 구현 관점(잠재 결함, 예외/검증, 상태·비동기, I/O·DB, 보안, 테스트, 문서 정합)  
> **후속 구현**: 2026-07-29 — 본 문서 권고 1~3단계 중 **실행 가능 항목 반영** (`tests/test_project_audit_20260729.py`).  
>   - suffix 알고리즘 **근본 재설계**와 CI Python 매트릭스(외부 CI 부재)는 의도적 보류.  
> **선행 이력**: 2026-07-22 감사 후속(finished terminal stash, stop 멱등, Observer 짧은 발화, 문서 버전 동기화) 반영 상태를 기준으로 잔여·신규 이슈를 재평가했다.  
> **확장 감사**: 보안·동시성·성능·아키텍처·테스트·패키징 범위는 [`PROJECT_AUDIT_EXTENDED.md`](PROJECT_AUDIT_EXTENDED.md).

---

## 1. Executive Summary

국회 의사중계 AI 자막을 **PyQt6 UI 스레드 + Selenium ExtractionWorker + 자막 파이프라인 + runtime archive + SQLite** 로 수집·저장하는 Windows 중심 데스크톱 앱이다.  
v16.14.7~v16.14.8 동안 큐 하드닝, 종료 lifecycle, runtime segmented session, URL/selector 검증, DB degraded mode 등이 반복 보강되어 **일반 사용 경로의 성숙도는 높다.**

| 축 | 위험도 (후속 반영 후) | 한 줄 요약 |
|----|----------------------|------------|
| **기능 안정성(일반 사용)** | **Low** | 핵심 경로 방어 + 회귀 321건 |
| **데이터 손실 UX 경계** | **Low** | `_start` dirty/교체 확인 반영 |
| **파이프라인 정확성** | **Medium** | suffix 구조 한계는 잔존, soft_resync 긴 히스토리 유지 보강 |
| **장시간 세션 I/O** | **Low** | orphan segment best-effort 삭제 |
| **극단 부하·큐** | **Low** | overflow/terminal 보호 유지 |
| **보안** | **Low** | host·selector·SQL·runtime path 가드 |
| **문서 정합** | **Low** | PIPELINE_LOCK / 본 문서 후속 동기화 |

**검증 결과**

| 시점 | `pytest -q` | `pyright` |
|------|-------------|-----------|
| 2026-07-29 감사 직후 | 306 passed / 2 skipped | 0 errors |
| 2026-07-29 후속 구현 후 | **321 passed / 2 skipped** | **0 errors** |

**핵심 결론 (후속 반영 후)**

1. Critical 결함 없음.  
2. High였던 `_start` dirty 미보호는 **해소**.  
3. soft_resync 정합 유지, orphan segment 정리, capture probe 테스트 더블 초석 추가.  
4. 잔여: suffix 알고리즘 구조 한계(의도적 보류), Selenium/Chrome 실연동 E2E, CI Python 매트릭스(리포에 `.github` 없음).

---

## 2. Project Understanding

### 2.1 목적 (README · CLAUDE)

- 국회 의사중계 웹의 **실시간 AI 자막**을 딜레이 없이 추출·저장
- 출력: TXT / SRT / VTT / DOCX / HWPX / HWP / RTF / JSON 세션 / SQLite
- 운영 축: 자동 재연결, runtime segmented session, portable/`%LOCALAPPDATA%` 저장소, DB 검색·계보, 다크/라이트 테마

### 2.2 아키텍처 (CodeGraph + 문서)

```
국회의사중계 자막.py
  └─ storage preflight
  └─ QApplication + MainWindow (facade + mixin 조합)

MainWindow (ui/main_window.py)
  ├─ RuntimeState / Lifecycle / Driver
  ├─ Capture (browser / dom / observer / live)
  ├─ Pipeline (queue / messages / stream / state)
  ├─ Persistence (session / runtime archive / export)
  ├─ Database (DBWorker + DatabaseManager mixin)
  └─ View / UI (render, search, theme, tray)

ExtractionWorker (non-daemon, name="ExtractionWorker")
  -- MainWindowMessageQueue(maxsize=500, run_id envelope) --> UI
Control plane
  -- AppControlMessageQueue(maxsize=200) ------------------┘
```

### 2.3 주요 실행 흐름 (CodeGraph call path)

1. **시작**  
   `runtime_lifecycle._start()`  
   → `validate_assembly_url` + `validate_subtitle_selector`  
   → capture state / render / pipeline history **전체 초기화**  
   → `_activate_capture_run` + runtime archive  
   → worker 큐 clear 후 `ExtractionWorker` 시작 (`daemon=False`)

2. **수집**  
   `capture_browser._extraction_worker`  
   → health check / MutationObserver / structured probe  
   → `message_queue.put((type, payload))`  
   → worker thread-local `run_id`가 있으면 `MainWindowMessageQueue.put`이 `_emit_worker_message`로 envelope·overflow/terminal 처리

3. **처리**  
   `pipeline_messages._process_message_queue` (시간 예산 + 최대 건수 + backlog follow-up)  
   → `preview` → `_prepare_preview_raw` → `_process_raw_text` (GlobalHistory + suffix `rfind`)  
   → `SubtitleEntry` / UI 증분 반영  
   → 장시간 시 runtime segment flush (fingerprint + archive_token/run_id stale-drop)

4. **재연결**  
   recoverable WebDriver 오류 → 지수 백오프 → 같은 모드·URL 우선 재오픈  
   → `reconnected` → `_on_capture_reconnected` → `_soft_resync` + `_reconnect_preview_suppress_until_delta`

5. **중지/종료**  
   `_stop`: preview drain → finalize → worker 대기 → queue clear  
   stop 중 `finished`/`error`는 **멱등 흡수**  
   `closeEvent`: dirty save deferred, background/DB drain, diagnostic escalation, driver/DB 정리  
   정상 종료 시 runtime archive 파일 제거 + recovery pointer 정리

### 2.4 변경 시 영향 범위 (CodeGraph blast radius 요약)

| 영역 | 대표 심볼 | 비고 |
|------|-----------|------|
| Worker 메시지 계약 | `MainWindowMessageQueue`, `_emit_worker_message`, `WorkerQueueMessage` | capture 전역 + queue hardening 테스트 |
| 파이프라인 게이트 | `_prepare_preview_raw`, `_process_raw_text`, `_soft_resync` | 정확성 핵심, `PIPELINE_LOCK.md` 대상 |
| 시작/중지 | `_start`, `_stop`, `closeEvent` | 세션 dirty·driver·archive 교차 |
| Runtime archive | segment flush / fingerprint / `_resolve_runtime_relative_path` | 장시간 세션·복구 |
| DB | `DatabaseManager.save_session` / `search_subtitles` | DBWorker 직렬화, parameterized SQL |
| URL/Selector | `validate_assembly_url`, `validate_subtitle_selector` | start/preset/history 공유 |

### 2.5 이전 감사 대비 해소 상태 (요약)

| 2026-07-22 지적 | 현재 상태 |
|-----------------|-----------|
| worker `finished` raw put → terminal 보호 우회 | ✅ `_emit_worker_message(..., run_id=)` 후 `clear_worker_run_id` |
| stop 중 finished/error 드롭 | ✅ whitelist + 멱등 흡수 |
| Observer `length < 3` 짧은 발화 차단 | ✅ 한글/영문 1자 허용 |
| CLAUDE/GEMINI 버전 불일치 | ✅ v16.14.8 |
| subprocess 샌드박스 실패 | ✅ in-process fallback + skip |

---

## 3. High-Risk Issues

> 아래는 **실제 코드 근거**가 있는 항목만 포함한다. 추정은 §4로 분리한다.  
> 이미 해소된 과거 High 이슈는 §7에 두고, 본 절은 **현재 잔여·신규** 중심으로 서술한다.

### 3.1 `_start()`가 dirty 세션 보호 없이 자막/세션을 즉시 초기화 — ✅ Resolved

* **위치**: `ui/main_window_impl/runtime_lifecycle.py` — `_start()` / `_begin_extraction_run()`
* **문제(감사 시점)**: 시작 시 dirty 확인 없이 세션 초기화.
* **상태 (2026-07-29)**: **✅ 해소**  
  - dirty → `_run_after_dirty_session_action("추출 시작", ...)`  
  - clean + 자막 존재 → 교체 확인 다이얼로그  
  - 본문은 `_begin_extraction_run(url, selector)`로 분리  
  - 회귀: `tests/test_project_audit_20260729.py`
* **우선순위**: ~~High~~ → **Resolved**

### 3.2 글로벌 히스토리 + suffix 파이프라인의 구조적 정확성 한계

* **위치**: `pipeline_stream` + `PIPELINE_LOCK.md`
* **문제**: compact + suffix 구조 한계는 **의도적으로 잔존** (근본 재설계 보류).
* **후속 (2026-07-29)**: soft_resync만 **정합 시 긴 compact 유지**로 완화. suffix `rfind` 코어 의미론 변경 없음.
* **우선순위**: **Medium** (잔존, 보류)

### 3.3 soft_resync와 runtime archive active-tail의 결합 — 부분 해소

* **상태 (2026-07-29)**: soft_resync가 기존 compact와 최근 엔트리가 정합하면 긴 히스토리 유지.  
  회귀: `test_soft_resync_keeps_longer_history_when_recent_is_contained`  
* **잔여**: 완전 desync 시 최근 5개로 축소되는 동작은 유지(의도).
* **우선순위**: ~~Medium~~ → **Low** (완화됨)

### 3.4 runtime segment fingerprint 불일치 시 디스크 orphan 파일 — ✅ Resolved

* **상태 (2026-07-29)**: `_cleanup_orphan_runtime_segment_file` + mismatch 경로 연동.  
  회귀: `test_cleanup_orphan_*`, `test_handle_runtime_segment_flush_done_mismatch_cleans_orphan`
* **우선순위**: ~~Low–Medium~~ → **Resolved**

### 3.5 overflow passthrough 상한 초과 시 메시지 드롭 (완화됨, 잔존)

* **위치**: `pipeline_queue._trim_overflow_passthrough_messages`, `Config.OVERFLOW_PASSTHROUGH_MAX`  
  `MainWindowMessageQueue` + `_emit_worker_message`
* **문제**: 극단 burst에서 overflow stash trim으로 낮은 우선순위 메시지 손실 가능.  
  preview coalescing 제거·priority trim·terminal stash로 개선됐으나 **상한 자체는 존재**.
* **영향**: UI 장기 정체 + 초고속 자막 갱신 시 짧은 구간 누락. 일반 국회 발화 속도에서는 드묾.
* **근거**: drop 카운터·toast, `tests/test_project_audit_queue_hardening.py`, finished 포화 테스트(`test_project_audit_20260722.py`)
* **권장 수정 방향**: sustained burst 부하 테스트 유지, 필요 시 preview 전용 상한/압축
* **우선순위**: **Low**

### 3.6 보안·입력 검증 — 잔여이지만 낮은 위험

* **위치/상태**:
  - URL: `core/url_policy.validate_assembly_url` — scheme + `assembly.webcast.go.kr` host만 허용 (**path/query는 미제한**)
  - Selector: `validate_subtitle_selector` — 길이·문자 화이트리스트; Observer 주입은 `execute_script(..., selectorArg)` **인자 전달**(문자열 보간 삽입 아님)
  - SQL: 파라미터 바인딩 + LIKE `ESCAPE '\\'`
  - Runtime path: `_resolve_runtime_relative_path`로 absolute/drive/root 이탈 차단
  - pickle/yaml.unsafe/`shell=True` 앱 런타임 경로 없음(검증 스크립트 subprocess는 로컬 개발용)
* **문제**: 허용 host 내 임의의 path/query는 열 수 있음. 실질 공격면은 **로컬 사용자가 악의 URL/selector를 넣는 수준**.
* **영향**: 제한적 (로컬 데스크톱 + 고정 공공 사이트)
* **권장 수정 방향**: 필요 시 path allowlist(`/main/player.asp`, `pressplayer.asp` 등) 추가
* **우선순위**: **Low**

### 3.7 (참고) 2026-07-22 High — worker `finished` terminal 보호 — ✅ Resolved

* **위치**: `capture_browser._extraction_worker` `finally`
* **현재**: `_emit_worker_message("finished", payload, run_id=run_id)` 후 `clear_worker_run_id()`  
* **회귀**: `tests/test_project_audit_20260722.py::test_extraction_worker_finished_survives_full_queue`  
* **우선순위**: Resolved

---

## 4. Potential Functional Gaps

### 4.1 코드·테스트로 확인된 gap

| Gap | 근거 |
|-----|------|
| **시작 시 dirty 보호 부재** | §3.1 — 종료/로드/병합과 비대칭 |
| **Selenium/Chrome 실연동 E2E 부재** | `test_live_contract_smoke.py`는 live_list API opt-in. DOM/Observer/재연결 E2E 없음 |
| **archive + soft_resync 결합 테스트 부재** | §3.3 |
| **orphan segment 정리 테스트 부재** | §3.4 |
| **impl contracts Protocol 시그니처 빈약** | `ui/main_window_impl/contracts.py` Host가 얇음 → mixin 계약 정적 강제력 약함 (의도적 보류 이력 있음) |
| **DBWorker 단위 테스트 범위** | shutdown/stale 일부 보강됐으나 worker_loop 전 구간 커버는 제한적 |
| **CLAUDE.md 본문 회귀 수치 혼재** | 버전은 16.14.8이나 중간 절에 과거 pass 수가 남아 README 변경 이력이 더 최신 |

### 4.2 추정 gap (미확정 — “추정” 명시)

- **추정**: Python 3.14 + 핀된 PyQt6/Selenium/PyInstaller 조합은 README 권장(3.10–3.12) 밖일 수 있다. 현재 로컬 306 pass는 통과하나 장기 호환 매트릭스는 미검증.
- **추정**: `keep_browser_on_stop` + 즉시 재시작 시 driver handoff 레이스가 드물게 남을 수 있다(`_driver_lock`·identity helper로 상당 부분 완화).
- **추정**: 비정상 종료 직후 runtime salvage 경고가 많은 경우, 복구 UX가 여전히 복잡할 수 있다(기능 자체는 구현됨).
- **추정**: Linux/macOS는 1급 지원 대상이 아님(README Platform=Windows, HWP/pywin32/LOCALAPPDATA).
- **추정**: FTS `syntax="fts"` UI 노출이 제한적이면 raw FTS 경로는 사실상 미사용일 수 있음(literal 기본은 의도적).
- **추정**: MutationObserver 주 경로(텍스트 push)는 `isLikelySubtitleText`를 거치지 않고 poll fallback만 필터한다. 파이프라인 게이트가 후단에서 거르므로 치명적이진 않으나, 버퍼 노이즈가 늘 수 있다.

### 4.3 README/CLAUDE vs 구현 정합

| 항목 | 정합 |
|------|------|
| 실시간 수집 / 재연결 / 저장 포맷 | 일치 |
| worker/control 큐 분리, non-daemon worker | 일치 |
| runtime archive + recovery | 일치 |
| URL host 정책 | 일치 |
| 짧은 발화 수집 (네/예) | 일치 (Observer·파이프라인 정렬됨) |
| 버전 번호 v16.14.8 | 일치 (README / CLAUDE / Config) |
| “미저장 시 종료 프롬프트” | 종료·로드에는 일치, **시작 시 미보호**는 문서에 명시되지 않음 (gap) |
| CLAUDE 중간 절 회귀 pass 수 | 역사 기록 혼재 — 최신 기준은 README 변경 이력·본 문서 §1 |

---

## 5. Recommended Fix Plan

### 1단계 — 즉시 수정 (데이터 손실·기능 경계)

1. **`_start()` dirty/세션 보호** (§3.1)  
   - 자막 존재 또는 dirty일 때 저장/버리기/취소  
   - Cancel 시 시작 중단  
   - 회귀 테스트 3종(취소 유지 / discard 후 시작 / save 후 시작)
2. **(이미 완료 확인)** finished terminal envelope, stop 멱등, Observer 짧은 발화 — 회귀 스위트 유지

### 2단계 — 안정성 개선

1. soft_resync window 정책 재검토 (§3.2·§3.3) — PIPELINE_LOCK 준수, fixture 선행  
2. runtime segment mismatch 시 orphan 파일 정리 (§3.4)  
3. overflow sustained burst + archive flush 동시 시나리오  
4. CLAUDE.md “현재 기준선” 절을 단일 표로 정리(역사 수치는 변경 이력으로만)

### 3단계 — 구조·장기 개선

1. Capture DOM 읽기 Protocol을 테스트 더블로 고정해 Chrome 없는 E2E 시뮬  
2. CI matrix: Python 3.10–3.12 + `pip install -r requirements-dev.txt`  
3. `contracts.py` Host 시그니처 보강은 pyright abstract/override 회귀를 보며 점진 적용  
4. suffix 알고리즘 근본 개선은 **사용자 요청·실방송 로그 근거** 있을 때만 (보류 권장)

---

## 6. Test Recommendations

### 6.1 필수 추가 (1단계)

| 테스트 | 내용 |
|--------|------|
| `test_start_blocks_when_session_dirty_cancel` | dirty + 자막 있는 상태에서 `_start` 시도 → Cancel → 자막/ dirty 유지, worker 미시작 |
| `test_start_after_discard_resets_session` | Discard 후 start 본문 실행 → empty capture state |
| `test_start_after_save_continues` | Save 완료 콜백 후 extraction worker 시작 경로 진입 |

### 6.2 안정성 보강 (2단계)

| 테스트 | 내용 |
|--------|------|
| soft_resync after runtime archive | tail만 남은 상태에서 desync → resync → 다음 preview 중복 없음 |
| segment flush fingerprint mismatch orphan | mismatch 시 manifest 미등록 파일 삭제 또는 재시도 정책 |
| reconnect + archive + suppress | 재연결 handshake와 segment flush 동시 |
| stop 중 finished/error 멱등 | 기존 2026-07-22 테스트 유지 |

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
| `pytest -q` | 306 passed, 2 skipped (≈48.6s) |
| `pyright --outputjson` | 0 errors / 0 warnings |

---

## 7. Appendix — 이전 조치 이력 (요약)

### 2026-06-25 (v16.14.7 감사 후속)

preview coalescing 제거, overflow 우선순위 trim, stopping preview drain, control 큐 분리, `DatabaseOperationResult`, non-daemon worker, selector 검증, 재연결 soft_resync, 복구 UX 등.

### 2026-06-30 (v16.14.8)

in-process smoke/pyright fallback, `_prepare_preview_raw` 전용 테스트, reconnect handshake, runtime salvage 테스트, capture Protocol, release verifier deps/codegraph 옵션.

### 2026-07-22 (감사 + 후속 구현)

| 권고 | 상태 | 비고 |
|------|------|------|
| finished run_id envelope + terminal stash | ✅ | `capture_browser.py` finally |
| stop 중 finished/error 멱등 | ✅ | `pipeline_messages.py` |
| CLAUDE/GEMINI 버전 동기화 | ✅ | v16.14.8 |
| Observer 짧은 발화 | ✅ | `length < 3` 제거 |
| suffix 구조 한계 | 보류 | PIPELINE_LOCK |
| DBWorker shutdown 테스트 | ✅ 일부 | 지속 보강 여지 |
| Selenium E2E / CI matrix | 미착수 | 장기 |

### 2026-07-29 (본 감사)

- 초기 감사: 기능 코드 변경 없음. High로 `_start` dirty 미보호 식별.

### 2026-07-29 (감사 후속 구현)

| 권고 | 상태 | 비고 |
|------|------|------|
| §3.1 `_start` dirty/교체 보호 | ✅ | `_begin_extraction_run` 분리 |
| §3.3 soft_resync 긴 히스토리 유지 | ✅ 부분 | 정합 시 previous 유지 |
| §3.4 orphan segment 정리 | ✅ | best-effort unlink |
| Capture probe 테스트 더블 | ✅ 초석 | `CaptureProbeProtocol` + Fake |
| suffix 알고리즘 근본 재설계 | 보류 | PIPELINE_LOCK |
| CI Python 매트릭스 | 보류 | 리포에 `.github` 없음 |

**회귀 파일**: `tests/test_project_audit_20260729.py`  
**기준선**: `pytest -q` **321 passed / 2 skipped**, `pyright` **0 errors**.

---

*감사 리포트 + 후속 구현 현황. suffix 알고리즘 재설계는 별도 승인 작업.*
