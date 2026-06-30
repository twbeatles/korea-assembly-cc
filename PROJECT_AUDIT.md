# Project Audit

> **감사 일자**: 2026-06-30  
> **대상 버전**: v16.14.7  
> **분석 도구**: README.md, CLAUDE.md, CodeGraph MCP (`codegraph init` + `codegraph_explore`), 보조 grep/파일 열람, `pytest -q`, `pyright --outputjson`

## 1. Executive Summary

이 프로젝트는 국회 의사중계 AI 자막을 PyQt6 GUI + Selenium worker + runtime archive + SQLite DB로 수집·저장하는 Windows 중심 데스크톱 앱이다. 2026-06-25 감사 후속 조치(preview coalescing 제거, control 큐 분리, non-daemon worker, selector 검증, 복구 UX 등)가 코드·테스트에 반영된 상태이며, **핵심 기능 결함 수준의 미해결 이슈는 제한적**이다.

**전체 위험도: Low–Medium** (기능 안정성) / **Medium** (에이전트 자율 개발·자동화 적합성)

| 구분 | 요약 |
|------|------|
| 강점 | facade+impl 분리, storage preflight, atomic I/O, runtime manifest 무결성, DB degraded mode, queue overflow/terminal 보존, 38개 테스트 모듈·279건 규모 회귀, smoke CLI·release verifier 스크립트 |
| 잔여 리스크 | suffix/compact 파이프라인 구조적 한계, Selenium 실연동 E2E 부재, **핫패스(`_prepare_preview_raw` 등) 직접 단위 테스트 공백**, **subprocess 기반 회귀 테스트의 샌드박스/에이전트 환경 취약성** |
| 자동화 격차 | `requirements-dev.txt` 핀(pytest 9.0.2)과 실제 환경(pytest 8.4.2) 불일치, CodeGraph 인덱스 미커밋(`.gitignore`), PowerShell에서 `codegraph` 실행 정책 차단 |

**검증 결과 (2026-06-30 감사 세션)**

| 항목 | 결과 | 비고 |
|------|------|------|
| `pytest -q` | **276 passed, 1 skipped, 3 failed** | 실패 3건은 subprocess `WinError 50` (에이전트/제한 환경). 직접 CLI smoke는 성공 |
| `pyright --outputjson` (직접 실행) | **0 errors, 0 warnings** | `test_pyright_regression.py`는 동일 환경에서 subprocess 실패 |
| `--smoke-storage-preflight` (직접 실행) | **exit 0, ok=true** | JSON payload 정상 |
| CodeGraph 인덱스 | **123 files, 2,581 nodes, 7,187 edges** | 감사 중 `codegraph init` 생성. `.codegraph/`는 gitignore |

**Superpowers(TDD·계획 기반·환경 격리) 관점**: 코어 파이프라인·DB·URL 정책·큐 하드닝은 `MainWindow.__new__` 기반 부분 구성 테스트로 Red-Green 루프가 가능하나, **GUI 통합·Selenium·subprocess smoke·PyInstaller 빌드**는 에이전트 샌드박스에서 독립 루프가 깨지기 쉽다. 에이전트가 안전하게 수정하려면 핫패스 직접 테스트 확장과 in-process smoke 대안이 필요하다.

---

## 2. Project Understanding

### 2.1 프로젝트 목적

README.md·CLAUDE.md 기준 목적은 국회 의사중계 AI 자막을 **딜레이 없이** 실시간 수집하고 TXT/SRT/VTT/DOCX/HWPX/HWP/RTF/JSON/SQLite로 저장하는 것이다. 핵심 가치는 실시간 스트리밍, 멀티스레드 안정성, SQLite 세션 관리, 장시간 세션(runtime archive), frozen/portable 실행 안정성이다.

### 2.2 아키텍처 개요

```
국회의사중계 자막.py
  └─ Config.run_storage_preflight()
  └─ QApplication + MainWindow (facade, 9 mixin 조합)

MainWindow (ui/main_window.py)
  ├─ RuntimeLifecycle  : _start / _stop / closeEvent
  ├─ Capture           : _extraction_worker (Selenium, non-daemon)
  ├─ Pipeline          : preview → _prepare_preview_raw → _process_raw_text
  ├─ Persistence       : session/backup/export/runtime archive
  ├─ Database          : DBWorker + DatabaseManager (impl mixin)
  └─ View/UI           : render/search/editing/theme

Worker Thread ──MainWindowMessageQueue(maxsize=500)──▶ UI (_process_message_queue)
Control plane  ──AppControlMessageQueue(maxsize=200)─┘
```

### 2.3 주요 실행 흐름 (CodeGraph 기준)

1. **시작**: `runtime_lifecycle._start()` → `validate_assembly_url()` + `validate_subtitle_selector()` → runtime archive 시작 → worker 큐만 `_clear_message_queue()` → `ExtractionWorker`(daemon=False) 시작.
2. **수집**: `capture_browser._extraction_worker()` → Observer/structured probe → `message_queue.put(preview/keepalive/subtitle_reset/...)`.
3. **처리**: `pipeline_messages._process_message_queue()` (time budget ~8ms, 최대 50건) → `_prepare_preview_raw()` → `_process_raw_text()` (GlobalHistory + suffix) → `SubtitleEntry` 반영.
4. **재연결**: recoverable WebDriver 오류 → 지수 백오프 → driver 재기동 → `reconnected` 메시지 → `_on_capture_reconnected()` → `_soft_resync()`.
5. **장시간 세션**: `backups/runtime_sessions/<run_id>/manifest.json` + `segment_*.json` + `tail_checkpoint.json` + fingerprint 무결성 검증.
6. **종료**: dirty session → background drain → DB worker shutdown → diagnostic escalation.

### 2.4 CodeGraph 영향 범위 (변경 시 주의)

| 심볼 | blast radius | 테스트 커버리지 (CodeGraph) |
|------|----------------|---------------------------|
| `_prepare_preview_raw` | 파이프라인 핵심 게이트 | ⚠️ dedicated test 없음 |
| `_emit_worker_message` / overflow trim | capture·persistence·DB 등 40+ | `test_project_audit_queue_hardening.py` 등 |
| `DatabaseManager.save_session` / `search_subtitles` | DBWorker, history/search | `test_database_manager.py` |
| `normalize_live_xcode` / `xcgcd` | live_list, capture_live, dialog | `test_url_policy.py`, opt-in live smoke |
| `_build_salvaged_runtime_segments` | manifest salvage 복구 | ⚠️ dedicated test 없음 |
| `_has_runtime_archived_segments` | hydrate/search/render 분기 | ⚠️ dedicated test 없음 |

### 2.5 2026-06-25 감사 후속 조치 상태

| 조치 | 상태 |
|------|------|
| preview coalescing 제거 + overflow 우선순위 trim | ✅ 완료 |
| stopping 시 preview unlimited drain | ✅ 완료 |
| `AppControlMessageQueue` 분리 | ✅ 완료 |
| `DatabaseOperationResult` | ✅ 완료 |
| extraction worker non-daemon | ✅ 완료 |
| selector 사전 검증 | ✅ 완료 |
| 재연결 `_on_capture_reconnected` + `_soft_resync` | ✅ 완료 (잔여 handshake는 Low) |
| README runtime 백업 설명 | ✅ 완료 |

---

## 3. High-Risk Issues

### 3.1 subprocess 기반 회귀 테스트가 에이전트/제한 환경에서 실패

* **위치**: `tests/test_config_paths.py` (L184–224), `tests/test_pyright_regression.py` (L12–28), `scripts/run_release_verification.py` (전체 subprocess 체인)
* **문제**: `subprocess.run([sys.executable, "국회의사중계 자막.py", ...])` 및 `subprocess.run([sys.executable, "-m", "pyright", ...])`가 Windows 에이전트/샌드박스에서 `OSError: [WinError 50] 지원되지 않는 요청입니다`로 실패한다. 동일 명령을 직접 실행하면 smoke preflight는 성공하고 pyright도 0 errors다.
* **영향**: Superpowers/CI 에이전트가 `pytest -q` 전체 통과를 게이트로 삼을 때 **거짓 음성(false negative)** 발생. Red-Green-Refactor 루프가 중단된다. `run_release_verification.py`도 동일 패턴으로 연쇄 실패 가능.
* **근거**: 감사 세션 `pytest -q` → 276 pass / **3 fail** (모두 subprocess WinError 50). 직접 실행: `python "국회의사중계 자막.py" --smoke-storage-preflight` → `{"ok": true, ...}`. `pyright --outputjson` 직접 실행 → 0 errors.
* **권장 수정 방향**: (1) smoke/pyright 회귀를 **in-process 호출**(`main([...])`, `pyright` API 또는 import)로 전환하거나, (2) subprocess 실패 시 skip 대신 **환경 capability probe** fixture 도입, (3) release verifier에 `--in-process-smoke` 옵션 추가.
* **우선순위**: **High** (자동화 저해)

### 3.2 글로벌 히스토리 + suffix 파이프라인의 구조적 정확성 한계

* **위치**: `ui/main_window_impl/pipeline_stream.py` `_prepare_preview_raw()` (L173–264), `_process_raw_text()` / `core/text_utils.py` `compact_subtitle_text()`
* **문제**: 50자 suffix, compact(공백 제거) 매칭, ambiguous suffix 분기는 반복 구문·compact collision 구간에서 false positive/negative를 유발할 수 있다. `rfind`·`_soft_resync()`로 완화됐으나 알고리즘 한계는 남아 있다.
* **영향**: 동일 문구 반복 회의, 빠른 발언자 전환, AI 인식 오류 구간에서 짧은 중복·누락·잘못된 merge boundary.
* **근거**: `_prepare_preview_raw()`의 `first_pos != last_pos` ambiguous 분기(L231–262), `preview suffix desync reset` / `preview ambiguous suffix reset` 로그 경로. CodeGraph: **dedicated unit test 없음**. `tests/test_core_algorithm.py`는 `_extract_new_part`·`_soft_resync`만 검증.
* **권장 수정 방향**: `PIPELINE_LOCK.md` 절차 준수 하에 회귀 fixture 확장. 운영 로그 모니터링 유지. 알고리즘 변경은 사용자 승인 후.
* **우선순위**: **Medium**

### 3.3 overflow passthrough 보존 상한 초과 시 worker 메시지 드롭

* **위치**: `ui/main_window_impl/pipeline_queue.py` `_trim_overflow_passthrough_messages()` (L112–125), `Config.OVERFLOW_PASSTHROUGH_MAX=128`
* **문제**: 큐 포화 시 overflow stash가 128건을 넘으면 타입별 우선순위 trim으로 메시지가 드롭된다. preview coalescing 제거 후 완화됐으나 극단 burst에서는 여전히 손실 가능.
* **영향**: UI 스레드 장기 정체 시 자막 delta 누락. 사용자는 짧은 구간 누락으로 인지할 수 있다.
* **근거**: `_record_overflow_drop()` + rate-limited toast. `tests/test_project_audit_queue_hardening.py`가 coalescing·trim·stopping drain을 검증하나 **128건 초과 sustained burst** 시나리오는 없음.
* **권장 수정 방향**: burst 부하 테스트 추가. 필요 시 preview에 대한 overflow 상한 별도 정책 검토.
* **우선순위**: **Low** (완화됨)

### 3.4 `requirements-dev.txt` 핀과 실제 개발 환경 불일치

* **위치**: `requirements-dev.txt` (pytest==9.0.2, PyQt6==6.10.2), 감사 환경 Python 3.14.6 / pytest 8.4.2
* **문제**: 문서·핀 기준(pytest 9.0.2)과 실제 실행 환경(pytest 8.4.2)이 다르다. Python 버전도 README는 3.10+만 명시하고 상한·권장 버전이 없다.
* **영향**: 에이전트/worktree/CI마다 다른 pytest 동작·경고·fixture 차이 가능. **환경 격리 재현성** 저하.
* **근거**: `requirements-dev.txt` L4 `pytest==9.0.2` vs `python -m pytest --version` → `pytest 8.4.2`. CLAUDE.md 회귀 기준선은 279 pass로 기록돼 있으나 감사 세션은 276 pass( subprocess 3 fail).
* **권장 수정 방향**: `pip install -r requirements-dev.txt`를 release verifier 선행 단계로 고정. Python 3.10–3.12 권장 범위를 README에 명시. lock 파일 또는 CI matrix 추가.
* **우선순위**: **Medium** (자동화 재현성)

### 3.5 재연결 시 worker raw buffer 초기화와 UI history 불일치 (잔여)

* **위치**: `ui/main_window_impl/capture_browser.py` `_extraction_worker()` 재연결 성공 분기; `ui/main_window_impl/pipeline_stream.py` `_on_capture_reconnected()` (L303–313)
* **문제**: 재연결 후 worker의 `worker_last_raw_text`/`worker_last_raw_compact`가 비워지면 동일 full probe text가 다시 전송될 수 있다. UI는 `_on_capture_reconnected()`에서 `_soft_resync()`를 호출해 완화하지만, duplicate append 완전 방지 handshake는 없다.
* **영향**: 재연결 직후 일시적 suffix desync·중복 문장 표시. 대부분 수렴.
* **근거**: CodeGraph call path: `reconnected` → `_on_capture_reconnected` → `_soft_resync`. `test_project_audit_queue_hardening.py::test_reconnected_handler_soft_resyncs_when_entries_exist`는 handler 호출만 검증, end-to-end duplicate 없음은 미검증.
* **권장 수정 방향**: 재연결 후 첫 N개 preview에 대해 “resync without duplicate append” 정책 테스트·구현.
* **우선순위**: **Low**

---

## 4. Potential Functional Gaps

### 확인된 gap (코드·CodeGraph 근거)

- **`_prepare_preview_raw` 직접 단위 테스트 부재**: CodeGraph가 “no covering tests found”로 표기. 파이프라인 정확성 회귀의 Red 단계가 약하다.
- **`_build_salvaged_runtime_segments` / `_has_runtime_archived_segments` 테스트 부재**: salvage·full-session search/render 분기 검증 공백.
- **Selenium 실연동 테스트 부재**: `tests/test_live_contract_smoke.py`는 `RUN_LIVE_SMOKE=1` opt-in이며 DOM/Observer/Chrome 동작은 CI 기본 경로에서 검증하지 않는다.
- **MainWindow mixin 통합 테스트 부재**: 다수 mixin(`MainWindowPipelineStreamMixin`, `MainWindowPipelineQueueMixin` 등)이 CodeGraph상 dedicated test 없음. `__new__` 부분 구성 패턴에 의존.
- **CodeGraph 인덱스 미공유**: `.codegraph/`가 `.gitignore`에 포함돼 에이전트 세션마다 `codegraph init` 재실행 필요. PowerShell 기본 실행 정책에서 `codegraph` 직접 호출 실패 → `cmd /c` 우회 필요.

### 추정 gap

- **추정**: Python 3.14 환경에서 PyQt6·selenium·pyinstaller 조합이 공식 검증 범위를 벗어날 수 있다. 현재 276+ 테스트는 통과하나 장기 호환 리스크.
- **추정**: 비정상 종료 후 runtime archive 손상 + flat backup 부재 조합에서 복구본 선택 혼란이 남을 수 있다 (salvage 경고는 코드에 존재).
- **추정**: Linux/macOS에서 PyQt6+Chrome 동작 가능성은 있으나 README·HWP·pywin32·QSettings·`LOCALAPPDATA`는 Windows 전제.
- **추정**: `validate_assembly_url()`은 host만 제한하고 path는 검증하지 않는다. 같은 host의 비의도 path도 허용되나 실질 피해는 제한적.

---

## 5. Recommended Fix Plan

### 1단계 (즉시 수정): 자동화 빌드·TDD 루프 차단 요소

1. **subprocess 회귀 테스트 견고화** — smoke/pyright를 in-process 또는 capability-gated로 전환해 에이전트 샌드박스 false negative 제거.
2. **개발 환경 재현성** — `requirements-dev.txt` 설치를 verifier 선행 단계로 강제, Python 권장 버전 문서화.
3. **핫패스 직접 테스트 추가** — `_prepare_preview_raw` suffix/ambiguous/desync 시나리오 최소 5건.

### 2단계 (안정성 개선): 예외 처리·환경 격리

1. **runtime salvage 테스트** — `_build_salvaged_runtime_segments` 손상 manifest + sibling segment 시나리오.
2. **overflow sustained burst 테스트** — 128건 초과 preview stash trim 후 tail 무결성.
3. **재연결 duplicate append 회귀** — worker buffer clear + 동일 probe 재전송 fixture.
4. **CodeGraph 운영** — CI/에이전트 bootstrap에 `codegraph init` 추가(선택). 또는 인덱스 산출물 공유 정책 검토.

### 3단계 (구조 및 TDD 개선): 모듈화·문서 동기화

1. **파이프라인 테스트 계층 분리** — `core/subtitle_pipeline` 단위 테스트(已有)와 `pipeline_stream` 게이트 테스트를 명시적으로 연결.
2. **Selenium 추상화 인터페이스** — capture worker의 DOM 읽기를 protocol/mock으로 분리해 에이전트가 Chrome 없이 Red-Green 가능하게 (장기).
3. **문서 동기화** — README/CLAUDE.md 회귀 기준선을 “subprocess 포함 전체 pytest” vs “in-process subset”으로 구분 기록.
4. **suffix 알고리즘 개선** — 사용자 요청·`PIPELINE_LOCK.md` 승인 후 (보류 중).

---

## 6. Test Recommendations

### 6.1 자동화·환경 격리 (Superpowers 우선)

- `test_entrypoint_*` / `test_pyright_regression`를 in-process 래퍼로 대체하거나, `subprocess` 실패 시 `@pytest.mark.requires_subprocess`로 분리해 기본 `pytest -q`가 에이전트 환경에서 녹색 유지되게 한다.
- `run_release_verification.py --offline`에 “subprocess-free” 모드 추가 검증.
- CI matrix: Python 3.10 / 3.11 / 3.12 + `pip install -r requirements-dev.txt` 고정.

### 6.2 `_prepare_preview_raw` (핵심 Red-Green 대상)

- suffix 없음 → full normalized 반환.
- suffix 일치·신규 delta만 추출.
- suffix 미발견 → `_extract_stream_delta` / `_slice_incremental_part` fallback.
- ambiguous suffix (`first_pos != last_pos`) → skip 후 threshold에서 `_soft_resync`.
- desync count ≥ threshold → `preview suffix desync reset` + full accept.

### 6.3 큐 압력·coalescing (기존 확장)

- fake queue `maxsize=1` + 연속 preview 100건 → overflow passthrough 후 drain 시 delta 누락 없음.
- overflow 129건 적재 → `subtitle_reset` 보존·drop 통계 노출.
- `_is_stopping=True` + 2000건 preview → tail 확정 보장 (기존 테스트 유지·확장).

### 6.4 persistence/recovery

- manifest 손상 + sibling `segment_*.json` salvage → warning payload·`skipped_files` 검증.
- `_runtime_entries_fingerprint_matches` 불일치 시 strict load 실패 / salvage 제외.
- runtime archive 활성 시 `_auto_backup()`이 flat JSON이 아닌 recovery pointer 갱신임을 검증.

### 6.5 재연결·파이프라인

- 재연결 후 동일 probe text 재전송 → duplicate append 없음 정책 명시 테스트.
- `subtitle_reset` 직후 첫 preview가 이전 entry와 merge되지 않음 (기존 `test_pipeline_risk_hardening.py` 유지).

### 6.6 live list / URL (기존 유지)

- `normalize_live_xcode/xcgcd` reject/accept matrix.
- `validate_assembly_url` press player·subdomain·invalid scheme 회귀.
- `RUN_LIVE_SMOKE=1` opt-in + `check_live_list_drift.py` 주기 실행.

### 6.7 회귀 게이트 (권장 명령)

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m pyright --outputjson
python "국회의사중계 자막.py" --smoke --smoke-storage-dir .pytest_tmp/smoke-storage
python scripts/run_release_verification.py --offline --skip-build --instantiate-window
```

에이전트 환경에서는 subprocess 회귀 3건 실패 가능성을 인지하고, 직접 smoke·pyright로 교차 검증할 것.

---

## 7. 조치 이력 참고 (2026-06-25 완료 항목)

| 항목 | 파일/심볼 | 테스트 |
|------|-----------|--------|
| preview coalescing 제거 | `pipeline_queue.py` | `test_project_audit_queue_hardening.py` |
| overflow 우선순위 trim | `pipeline_queue.py`, `Config.OVERFLOW_PASSTHROUGH_MAX` | 동일 |
| stopping preview drain | `pipeline_stream.py` | 동일 |
| 재연결 resync | `pipeline_messages.py`, `pipeline_stream.py` | `test_reconnected_handler_soft_resyncs_when_entries_exist` |
| selector 검증 | `core/selector_policy.py` | `test_selector_policy.py` |
| control 큐 분리 | `AppControlMessageQueue` | `test_project_audit_phase3.py` |
| DB Result 타입 | `core/database_result.py` | `test_database_result.py` |
| non-daemon worker | `runtime_lifecycle.py` | lifecycle 회귀 |
| 복구 UX | `persistence_session.py` | `test_prompt_session_recovery_*` |
| release verifier | `--with-live-smoke` | `test_release_verification_script.py` |

---

## 8. 2026-06-30 감사 후속 구현 요약

| 항목 | 구현 | 테스트 |
|------|------|--------|
| in-process smoke/pyright fallback | `tests/test_support/subprocess_compat.py` | `test_config_paths.py`, `test_pyright_regression.py` |
| subprocess 회귀 분리 | `@pytest.mark.requires_subprocess` + conftest skip | `*_subprocess` 3건 |
| `_prepare_preview_raw` 직접 테스트 | — | `tests/test_prepare_preview_raw.py` |
| 재연결 duplicate handshake | `pipeline_stream.py` `_reconnect_preview_suppress_until_delta` | `tests/test_reconnect_preview_handshake.py` |
| runtime salvage 테스트 | — | `tests/test_runtime_salvage_audit.py` |
| overflow burst 확장 | — | `test_project_audit_queue_hardening.py` |
| capture Protocol | `core/capture_contracts.py` | `tests/test_capture_contracts.py` |
| release verifier deps/codegraph | `run_release_verification.py --skip-deps`, `--init-codegraph` | `test_release_verification_script.py` |
| pytest stub 보강 | `typings/pytest/__init__.pyi` | `test_pyright_regression.py` |

**회귀 기준선 (구현 후)**: `pytest -q` **299 passed / 2 skipped**, `pyright --outputjson` **0 errors**

---

*이 문서는 기능 감사·Superpowers 자동화 적합성 검증 결과이다. CodeGraph 인덱스는 로컬 생성(`.codegraph/`, gitignore 대상)되며 `run_release_verification.py --init-codegraph`로 재생성할 수 있다.*