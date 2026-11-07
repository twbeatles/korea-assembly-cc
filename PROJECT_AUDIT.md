# Project Audit

## 후속 구현 및 검증 — 2026-11-07

사용자의 후속 수정 요청에 따라 아래 감사(§1–9) 항목을 main 작업 트리에서 수정했다. §1–9는 수정 전 `e2545a5`에 대한 감사 기록으로 그대로 보존하며, 현재 미해결 목록이 아니다. 버전 증가·커밋·푸시·배포는 하지 않았다.

| 감사 항목 | 현재 상태 | 구현 |
|---|---|---|
| ISSUE-001: gap 거절로 종료 직전 preview 유실 | 수정·검증 | `_accept_preview_sequence`가 gap 뒤 preview를 거절하지 않고 run별 보류 목록(`_preview_held_by_run`, 상한 `Config.PREVIEW_HELD_MAX=256`)에 넣는다. 보류가 있는 동안 들어온 preview도 순서를 지키기 위해 보류한다. `_drain_held_previews`는 대기 중인 coalesced snapshot(`worker_sequence`)과 보류분을 오름차순으로 적용하고, 이미 반영한 sequence 이하는 버린다. 매 큐 tick 끝, coalesced preview drain, `_drain_pending_previews`(stop·terminal barrier)에서 소진한다. run 폐기·큐 비우기 시 함께 정리한다. 첫 preview가 1번이 아닌 경우도 gap으로 다룬다 |
| ISSUE-002: PID 재사용 시 archive 영구 제외 | 수정·검증 | `core/process_wait.process_creation_marker`(Windows `GetProcessTimes`, Linux `/proc/<pid>/stat` starttime)를 추가했다. `write_owner_file`이 `process_marker`를 기록하고, `is_archive_owner_alive`는 PID가 살아 있어도 marker가 다르면 종료로 판정한다. marker가 없는 기존 lease나 현재 marker를 읽을 수 없는 경우는 기존 PID 판정을 유지한다(보수적). macOS는 marker를 제공하지 않아 PID 판정 그대로다 |
| Phase 3: legacy `error`/`subtitle_not_found` handler | 정합화 | 삭제 대신 `finished`와 같은 `_finalize_terminal_capture_state`(예약 reset 취소, 마지막 fallback commit, `finalize_session`, legacy 버퍼)를 쓰게 맞췄다. 기존 테스트가 이 메시지를 사용하므로 호환을 유지했다 |
| 문서 불일치 | 수정 | `CLAUDE.md`·`GEMINI.md`·`PIPELINE_LOCK.md`·README 배지의 PyQt6 표기를 PySide6로 바로잡았다. `CLAUDE.md` §4.2·§1, `GEMINI.md`, `PIPELINE_LOCK.md` §2.1, README 변경 이력에 이번 변경을 기록했다 |
| CI·릴리스 gate | 반영 | `tests/test_audit_followup_20261107.py`를 CI의 명시적 gate 두 곳과 `scripts/run_release_verification.py`에 추가했다 |

### 의도적으로 바꾸지 않은 항목

- **heartbeat 갱신:** `heartbeat_at`은 여전히 시작 시각만 기록한다. PID 재사용은 process marker로 판정하므로 주기 갱신 타이머는 추가하지 않았다.
- **gap 사용자 알림:** 수정 후에는 gap이 데이터 유실로 이어지지 않는다. 실제로 드롭되는 overflow trim은 기존처럼 상태·토스트와 `queue_drops`로 알린다. 별도 알림은 추가하지 않았다.
- **복구 탐색 budget의 전부-아니면-전무 동작:** 문서화된 의도("부분 후보 적용 안 함")와 기존 테스트 계약을 유지했다.
- **stable·unstable 혼재 row:** 추정 항목이며 parity 계약(D5)을 바꿔야 하므로 확장 저장소와 함께 결정할 사항으로 남겼다.

### 검증

- 새 회귀 `tests/test_audit_followup_20261107.py`: **9 passed**. 감사 probe 시나리오(`finished`·`_stop()`·수집 중 tick), 오래된 coalesced snapshot 무시, run 폐기 시 보류분 정리, marker 불일치·일치·판독 불가, legacy lease, 실제 다른 프로세스 PID 재사용 후보 노출, 현재 프로세스 lease 유지를 검증한다.
- 저장소 루트 전체 `pytest`: **715 passed / 20 skipped**. skip 중 17건은 ARM64에 QtWebEngine이 없어 생긴 브라우저 DOM 검사이며, `KACC_TEST_BROWSER=chrome`로 다시 실행해 **20 passed**였다.
- `pyright`: **0 errors / 0 warnings**.
- 실제 생중계 큐 포화, Windows x64, macOS/Linux의 원격 CI 결과는 확인하지 않았다.

---

**아래는 수정 전 감사 기록이다.**

감사일: **2026-11-07 (Asia/Seoul)**
대상: **Korea Assembly CC v16.14.16 / main / `e2545a5`** (작업 트리 clean 상태에서 시작)
방식: 기능 구현·런타임 안정성 감사. **제품 코드·테스트·설정은 수정하지 않았고, 저장소 변경은 이 보고서뿐이다.** 재현 검사는 저장소 밖 임시 복사본에서만 실행했다.

> 이전 감사(`2b7af3a` 대상)와 그 후속 구현·검증 기록은 커밋 `e2545a5`의 `PROJECT_AUDIT.md`에 있다(`git show e2545a5:PROJECT_AUDIT.md`). 이 문서는 그 수정이 반영된 현재 커밋을 새로 감사한 결과이며, 아래 ISSUE 번호는 이 문서 안에서만 쓴다.

## 1. Executive Summary

**전체 상태:** 직전 감사의 High 3건(저장 snapshot/revision 불일치, terminal 처리 순서, 종료 fallback 부수 효과)은 현재 코드에서 수정되어 있고 회귀 테스트도 있다. 실제로 다시 확인했다. 전체 회귀는 격리 복사본에서 **706 passed / 20 skipped**이다. skip 20건 중 17건은 이 ARM64 환경에 `PySide6.QtWebEngineCore`가 없어 생긴 것이며, `KACC_TEST_BROWSER=chrome`로 다시 실행한 결과 **20 passed**였다. pyright는 **202 files / 0 errors / 0 warnings**이다. URL 검증, run 식별, bounded queue, JSON budget, archive 무결성, atomic 교체, SQLite transaction·operation ID 멱등성, 업데이트 서명·rollback 같은 방어 장치도 확인했다.

**전체 위험도: Medium.** 새로 확정한 결함은 2건이다.

| 우선순위 | 이슈 | 핵심 결과 |
|---|---|---|
| 1 | ISSUE-001 — 큐 포화 후 수집이 끝나면 마지막 preview가 sequence gap으로 거절됨 | 임시 재현에서 4개 발언 중 마지막 `넷째 발언` 유실. worker `finished`와 사용자 `_stop()` 모두 재현 |
| 2 | ISSUE-002 — runtime archive 소유권을 PID 생존만으로 판정 | 비정상 종료된 archive의 PID를 다른 프로세스가 재사용하면 수동 복구 후보와 GC에서 영구 제외. 재현 확인 |

**데이터 손상/유실:** DB·파일의 물리적 손상, 임의 명령 실행, path traversal은 확인하지 못했다. ISSUE-001은 **이미 관측한 마지막 발언이 저장되지 않는 논리적 유실**이다. 이 발언은 화면, 실시간 TXT, 이후 JSON/DB 어디에도 남지 않는다. ISSUE-002에서는 데이터가 디스크에 남지만 앱 UI로 복구할 경로가 사라질 수 있다.

**가장 먼저 수정할 영역:** preview sequence gap 처리와 coalesced snapshot의 적용 순서(ISSUE-001). terminal/stop barrier가 "최신 관측을 반드시 반영한다"는 계약을 지키도록 고쳐야 한다.

## 2. Project Understanding

### 목적

국회 의사중계 사이트(`assembly.webcast.go.kr`)의 AI 자막을 Selenium Chrome으로 실시간 수집한다. 수집한 자막은 PySide6 UI에서 검색·편집·병합하고, JSON 세션·SQLite 히스토리·TXT/SRT/VTT/DOCX/HWPX/HWP/RTF로 저장한다. 주 대상은 Windows 데스크톱이다. HWP 출력은 한컴 COM에 의존한다. Chrome 확장은 별도 저장소이며 `parity/` 계약만 공유한다.

확인한 문서는 `README.md`, `CLAUDE.md`, `GEMINI.md`, `PIPELINE_LOCK.md`, `docs/CHROME_EXTENSION_PARITY.md`, `requirements-dev.txt`, `pytest.ini`, `pyrightconfig.json`, `.github/workflows/ci.yml`, `subtitle_extractor.spec`이다. 루트에 `AGENTS.md`는 **없다**.

### 주요 entrypoint와 핵심 모듈

| 영역 | 파일·심볼 | 역할 |
|---|---|---|
| 앱 시작 | `국회의사중계 자막.py::main` | CLI(smoke/update) 분기, storage preflight, `QApplication`·`MainWindow` |
| UI 조립 | `ui/main_window.py::MainWindow`, `ui/main_window_impl/runtime_state.py` | mixin 조립, 큐·타이머·DB worker 초기화 |
| 수집 lifecycle | `runtime_lifecycle_extraction.py::_start/_begin_extraction_run`, `runtime_lifecycle_stop.py::_stop` | 입력 검증, run 시작·중지 |
| worker | `capture_browser.py::_extraction_worker/_open_capture_driver_session` | Chrome, live URL 해석, observer/probe, 재연결, `finished` |
| 큐 | `pipeline_queue.py::_emit_worker_message/_accept_preview_sequence`, `pipeline_messages.py::_process_message_queue/_handle_message` | run envelope, sequence, coalescing, terminal stash |
| commit | `pipeline_state.py::_apply_structured_preview_payload/_commit_fallback_preview`, `core/subtitle_pipeline.py`, `core/live_capture_impl/` | stable row ledger, fallback 안정화, suffix 증분 |
| 세션·복구 | `persistence_session_*.py`, `persistence_runtime_*.py`, `core/recovery_candidates.py`, `core/runtime_archive_owner.py` | snapshot 저장, 백업, segment/tail archive, 복구 후보 |
| 내보내기 | `persistence_exports_*.py`, `core/export_text.py`, `core/hwpx_export.py`, `core/file_io.py` | streaming writer, atomic 교체 |
| DB | `core/database_manager.py`, `core/database_impl/sessions.py` 등 | thread별 connection, WAL, transaction, lineage, FTS |
| 업데이트 | `core/update_manifest.py`, `core/update_installer.py` | Ed25519 manifest, rename-swap, smoke, rollback |

### 데이터 저장과 외부 의존성

- 상태의 원본은 `capture_state.entries`이고 `self.subtitles`는 alias이다. 핵심 공유 상태는 `live_capture_ledger`, `_session_revision`/dirty, `_active_capture_run_id`, 그리고 worker 큐·overflow·coalesced·terminal 저장소다.
- 장시간 수집은 `backups/runtime_sessions/run_*/`에 `manifest.json`, `segment_*.json`, `tail_checkpoint*.json`, `owner.json`으로 남는다. 복구 포인터는 `session_recovery.json` 하나다.
- 외부 의존성은 국회 사이트 DOM과 `live_list.asp`, Chrome/WebDriver, GitHub 업데이트 채널, python-docx, pywin32·한컴, cryptography다.

### 핵심 실행 흐름

```text
URL/selector 입력 → _start(URL·selector 검증, dirty 확인) → _begin_extraction_run
→ ExtractionWorker(_extraction_worker) → Chrome·DOM → _emit_worker_message(run_id, sequence)
→ MainWindowMessageQueue(500) | 포화 시 coalesced(full_snapshot) / overflow / terminal stash
→ _process_message_queue(100ms, 8ms·50건 budget) → _accept_preview_sequence → _handle_message
→ stable row commit_live_row 또는 fallback 안정 관측 commit → capture_state.entries
→ 렌더·revision/dirty·실시간 TXT·키워드 알림·runtime tail/segment flush

중지/종료 → _stop 또는 finished barrier(_drain_pending_previews) → _materialize_pending_preview
→ finalize_session → _retire_capture_run → UI reset

세션 저장 → 경로 선택 후 SessionSaveSnapshot(entries+manifest+revision+메타데이터)
→ background _write_session_snapshot → atomic JSON → DB worker(transaction, operation id)
→ session_save_done → revision 일치 시 dirty·복구 포인터 해제

시작/수동 복구 → RecoveryScanWorker(discover_recovery_candidates: pointer+backup+runtime manifest,
   owner 생존 archive 제외, budget·취소) → 후보 선택 → dirty 확인 → background load
```

## 3. Audit Coverage & Limitations

### CodeGraph 사용

`.codegraph/`가 있어 **CodeGraph MCP `codegraph_explore`를 실제로 사용했다.** 확인한 주요 호출·영향 관계는 다음과 같다.

- `_handle_message(finished) → _drain_pending_previews → _process_preview_queue_message → _apply_structured_preview_payload → _publish_capture_commit`, 그리고 `_materialize_pending_preview → _commit_fallback_preview`, `_retire_capture_run`.
- `_emit_worker_message → _accept_preview_sequence / _drain_terminal_worker_messages / _requeue_message_item / _unwrap_message_item`.
- `_save_session → _start_async_session_snapshot_save → SessionSaveSnapshot.capture → _write_session_snapshot`, `_clear_session_dirty`/`_mark_session_dirty`.

결과가 잘린 부분과 CodeGraph가 다루지 않는 범위(한글 파일명 entrypoint, 설정·CI·문서)는 파일을 직접 읽거나 grep으로 보완했다. 직접 읽은 범위는 `persistence_session_recovery.py`, `core/recovery_candidates.py`, `persistence_session_backup.py`, `persistence_exports_text.py`, `persistence_exports_dispatch.py`, `runtime_lifecycle_stop.py`, `runtime_lifecycle_shutdown.py`(종료 흐름), `runtime_lifecycle_extraction.py`, `persistence_runtime_archive.py`(cleanup/GC/start), `core/database_impl/sessions.py`, `core/update_installer.py`(apply/launcher), `core/runtime_archive_owner.py`, `core/process_wait.py`, `core/live_capture_impl/reconcile.py`, `capture_browser.py`(재연결·finally)이다. Python mixin·`getattr`·Qt signal 경로는 색인으로 완전히 추적되지 않을 수 있어 테스트와 실제 실행으로 교차 확인했다.

### 실행한 검증

환경: **Windows 11 ARM64 / 저장소 `.venv` Python / PySide6 6.12.0 / pytest 9.1.1 / pyright 1.1.414**. 의존성은 설치하지 않았다. `git archive HEAD`로 추적 파일만 scratchpad에 복사해 실행했고, 사용자 DB·세션·백업·설정은 사용하지 않았다.

| 검증 | 명령 | 결과 |
|---|---|---|
| 전체 회귀 | `QT_QPA_PLATFORM=offscreen python -m pytest tests -q --tb=short -ra` | **706 passed / 20 skipped / 30.8초** |
| 브라우저 DOM 회귀 | `KACC_TEST_BROWSER=chrome python -m pytest tests/test_capture_chrome_parity_p1.py tests/test_support -q` | **20 passed / 54.7초** |
| 정적 검사 | `pyright --outputjson` | **202 files / 0 errors / 0 warnings** |
| ISSUE-001 재현 | 임시 `tests/test_zz_audit_probe.py`(복사본에만 둠), 기존 `qt_window` fixture | **2 failed / 1 passed**. 실패 2건이 결함 증거이고, 통과 1건은 포화 없는 대조군 |
| ISSUE-002 재현 | 임시 `probes/probe_owner_pid.py` | 재사용 PID owner일 때 `candidates=0`, owner 제거 시 `candidates=1` |

전체 회귀의 skip 내역은 QtWebEngine 부재 17건(Chrome으로 별도 통과), opt-in soak 1건, live-list smoke(`RUN_LIVE_SMOKE`) 1건, subprocess 환경의 in-process pyright fallback 1건이다. README의 723 passed / 3 skipped와는 환경 차이일 뿐이고 합계는 같다.

### 반증으로 제외한 후보

다음 후보는 조사 결과 결함이 아니라고 판단했다.

- `recovery_scan_*` 같은 control 메시지가 coalescing으로 유실될 가능성: 큐 포화가 비현실적이다(후보는 수십 개 수준).
- 복구 budget(256 MiB, 1,000 후보) 초과: `backup_*.json`은 runtime archive가 없을 때만 쓰이고 최대 10개로 유지된다.
- 저장 중 archive 삭제: `_start`·`_begin_extraction_run`이 `_session_save_in_progress`를 막는다.
- 구조적 모드 고착(`capture_mode`): 이벤트마다 다시 계산된다.
- SRT 음수 시간: 0으로 clamp된다.
- 업데이트 launcher 인자 주입: `"`·개행을 거부하고 `%`를 escape한다.
- DB 동시 저장: unique operation ID와 IntegrityError 재조회로 처리된다.

`error`·`subtitle_not_found` worker 메시지 handler는 production emitter가 없다. 전체 grep 결과 worker는 `finished` payload로만 종료를 전달한다. 따라서 이 handler의 materialize/finalize 누락은 위험으로 계산하지 않았다.

### 확인하지 못한 범위

실제 국회 생중계 장시간 운용·재연결, 실제 큐 포화 빈도(UI 정지 시간 측정), 한컴 COM 파일 저장, Windows x64, macOS/Linux, frozen EXE 재빌드, 원격 CI 결과, 전원 차단, 다른 물리 볼륨은 이번에 검증하지 않았다. 보안 검토는 입력·경로·SQL·업데이트 흐름에 한정되며 의존성 취약점 조사는 포함하지 않았다.

## 4. High-Risk Issues

### [ISSUE-001] 큐 포화 후 수집이 끝나면 sequence gap 거절과 coalesced 순서 때문에 마지막 발언이 유실됨

- **위치:** `ui/main_window_impl/pipeline_queue.py:109–139::_accept_preview_sequence`, `pipeline_queue.py:285–319::_emit_worker_message`(포화 시 preview를 `full_snapshot`으로 coalesce), `pipeline_stream.py:326–381::_drain_pending_previews`(일반 큐 → overflow → coalesced 순서), `pipeline_messages.py:186–235::_process_message_queue`, `pipeline_messages.py:245–253`(terminal barrier), `runtime_lifecycle_stop.py::_stop`
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:**
  1. 큐가 가득 찬 순간의 preview(#3)는 coalesced 저장소로 간다.
  2. UI가 항목을 하나 처리해 자리가 나면, 다음 preview(#4)는 일반 큐에 정상 적재된다.
  3. UI는 일반 큐를 먼저 처리하는데, 이때 마지막 수신 sequence가 #2이므로 #4를 **gap으로 판정해 거절**한다. 거절된 내용은 다시 적용되지 않고 resync 요청만 남는다. 그 사이 worker가 보낸 #5, #6…도 같은 이유로 모두 거절된다.
  4. 그 뒤에 더 **오래된** coalesced #3이 적용된다.
  5. 수집이 계속되면 다음 worker preview가 `full_snapshot`으로 따라잡는다. 그러나 수집이 끝나면 따라잡을 preview가 더 오지 않는다.
- **발생 조건:** UI 지연이나 부하로 worker 큐(500)가 한 번 포화되고, 이어서 UI가 소비해 자리가 생긴 상태에서 worker 종료(`finished`)나 사용자 중지가 일어날 때. 포화가 일단 발생하면 이 순서(포화 중 coalesce → 자리 생김 → 다음 preview 정상 적재)가 일반적인 전개다. 큐 용량과 무관하게 같은 메커니즘이 작동한다. 실제 운용에서 포화가 얼마나 자주 일어나는지는 측정하지 않았다.
- **영향:** 거절된 preview에만 있던 마지막 발언이 화면, 실시간 TXT, 키워드 알림, 이후 JSON/DB 어디에도 남지 않는다. capture quality에는 `preview_gaps`만 1 증가하고 사용자에게 유실 사실은 드러나지 않는다.
- **근거:** 임시 probe에서 `maxsize=2` 큐를 사용했다. 순서는 #1·#2 큐 적재 → #3 coalesced → UI가 #1 소비 → #4 적재 → 종료다. 각 preview는 DOM 창처럼 직전 row와 새 row를 함께 담았다. 결과는 다음과 같다.
  - worker `finished`: 관측값 `['첫째 발언','둘째 발언','셋째 발언']`, 기대값에 있는 `'넷째 발언'` 누락, `preview_gaps=1`
  - 사용자 `_stop()`: 같은 누락
  - 대조군(포화 없음, 같은 payload): 4개 모두 보존
- **반증 확인:**
  - e2545a5의 terminal barrier는 일반·overflow·coalesced preview를 run 폐기 **전에** 소진한다. 그러나 소진 과정에서도 같은 `_accept_preview_sequence`가 newer 항목을 거절하므로 이 경우를 막지 못한다.
  - coalesced payload의 `worker_sequence`는 기록만 되고 정렬·비교에 쓰이지 않는다.
  - resync 요청(`_mark_preview_resync_requested`)은 이후 worker preview에만 반영되며, 종료 뒤에는 효과가 없다.
  - `_materialize_pending_preview`는 이미 state에 들어온 fallback preview만 확정한다. structured 모드에서는 바로 반환한다.
  - `test_finished_preserves_coalesced_latest_preview` 등 기존 테스트는 coalesced가 **가장 최신**인 경우만 검사하고, coalesced 뒤에 더 새 queued preview가 있는 경우는 다루지 않는다.
- **호출/영향 범위:** `_extraction_worker → _emit_worker_message → (queue | _coalesced_worker_messages)`. 소비 측은 `_process_message_queue`·`_drain_pending_previews → _unwrap_message_item → _accept_preview_sequence`이고, 이어서 `_drain_coalesced_worker_messages → _apply_structured_preview_payload`, 마지막에 `_retire_capture_run`이 run의 coalesced/sequence 상태를 삭제한다. 실시간 기록, 키워드 알림, 세션 revision, 복구 snapshot까지 영향이 이어진다.
- **권장 수정 방향:**
  - gap을 거절이 아니라 "순서가 다른 최신 snapshot"으로 다룬다. preview는 DOM 창 전체이므로, 대기 중인 coalesced snapshot과 queued preview를 `worker_sequence`/`sequence` 기준으로 정렬해 오래된 것부터 적용하는 방안을 우선 검토한다.
  - 최소한 terminal/stop barrier에서는 같은 run의 모든 대기 preview 중 sequence가 가장 큰 것을 마지막에 적용해야 한다.
  - 오래된 coalesced snapshot을 더 최신 상태 뒤에 다시 적용하지 않도록 sequence 비교를 넣는다.
- **필요한 회귀 테스트:** 위 probe 시나리오를 `finished`와 `_stop()` 두 경로로 고정한다. 기본 용량 500에서도 status 연속 적재로 같은 interleaving을 만든다. #4 뒤에 #5·#6이 이어지는 경우도 검사한다. 기대 결과는 마지막 발언 보존, 중복 0, 실시간 TXT 1회 기록이다.

### [ISSUE-002] runtime archive 소유권이 PID 생존만으로 판정되어, PID가 재사용되면 비정상 종료 archive가 복구 후보와 GC에서 제외됨

- **위치:** `core/runtime_archive_owner.py:13–33`(`heartbeat_at` 기록만 함), `57–79::is_archive_owner_alive`, `core/process_wait.py:37–52, 121–129`(PermissionError·Access denied → alive), `core/recovery_candidates.py:203–207`, `ui/main_window_impl/persistence_runtime_archive.py:478–481`
- **우선순위:** Low
- **신뢰도:** Confirmed
- **문제:** `owner.json`의 `pid`가 살아 있는 프로세스이기만 하면 archive를 "다른 인스턴스가 사용 중"으로 본다. 기록되는 `token`, `started_at`, `heartbeat_at`은 검사하지 않고, heartbeat를 갱신하는 코드도 없다. 앱이 비정상 종료되면 `owner.json`이 남는다. 이후 그 PID가 무관한 프로세스에 재사용되면(Windows에서 흔하고 재부팅 후 특히 잦다), 그 archive는 `discover_recovery_candidates`와 `_cleanup_orphan_runtime_archives` 양쪽에서 계속 건너뛰어진다. 권한 때문에 열 수 없는 프로세스도 alive로 처리된다.
- **발생 조건:** 비정상 종료 + 남은 PID 재사용 + 복구 포인터가 그 archive를 가리키지 않는 경우. 포인터가 없어지는 경우는 사용자가 시작 복구를 거절한 뒤 새 수집이 포인터를 덮어쓰거나, 포인터가 손상되거나, 다중 인스턴스가 공유 포인터를 갱신하는 경우다. 포인터 대상 자체는 owner 검사 없이 후보에 추가되므로 가장 흔한 경로는 보호된다.
- **영향:** 이 경우는 `파일 → 백업에서 세션 복구`가 대비하려는 바로 그 상황이다. 그런데도 해당 archive가 후보 목록에 나타나지 않는다. 디스크에는 남아 있지만 UI로 복구할 수 없고, GC 대상에서도 빠져 계속 쌓인다.
- **근거:** probe에서 무관한 Python 프로세스의 PID와 2020년 heartbeat를 `owner.json`에 기록했다. 결과는 `is_archive_owner_alive=True`, 후보 0개였다. 같은 archive에서 `owner.json`을 지우면 후보가 1개로 나타났다.
- **반증 확인:**
  - 정상 종료와 일반 중지는 `release_owner_file`로 owner를 지운다. 그러나 비정상 종료에는 적용되지 않는다.
  - 시작 복구는 포인터 대상만으로도 동작하므로 이 이슈는 포인터가 없는 수동 경로에 한정된다. 그래서 Low로 평가했다.
- **호출/영향 범위:** `_start_runtime_session_archive → write_owner_file`. 판정 측은 `RecoveryScanWorker → discover_recovery_candidates → is_archive_owner_alive`와 `_start_runtime_session_archive → _cleanup_orphan_runtime_archives → is_archive_owner_alive`이다.
- **권장 수정 방향:** 프로세스 생성 시각(Windows `GetProcessTimes`)이나 실행 파일 이름을 owner에 기록하고 함께 비교한다. 또는 heartbeat를 주기적으로 갱신하고 오래된 heartbeat는 stale로 판정한다. 수동 복구 UI에서는 "다른 프로세스가 사용 중일 수 있음" 경고와 함께 후보를 보여 주는 방안도 있다.
- **필요한 회귀 테스트:** 무관한 살아 있는 PID와 오래된 heartbeat를 가진 archive는 후보에 포함되고 GC 대상이 된다. 현재 PID와 최신 heartbeat를 가진 archive는 제외된다. Access denied를 모사한 경우의 기대 동작도 명시한다.

## 5. Potential Functional Gaps

- **Likely Gap — 수집 품질 진단의 사용자 노출:** `preview_gaps`, `queue_drops` 등은 JSON/DB의 `capture_quality`에 저장된다. 그러나 ISSUE-001 같은 종료 직전 gap이 실제 유실로 이어졌는지 사용자에게 알리는 경로는 확인하지 못했다(gap 시 토스트·상태 표시 없음).
- **Confirmed Gap — 복구 후보 탐색 budget의 전부-아니면-전무 동작:** 후보 1,000개, 256 MiB, 경로 10,000개 중 하나라도 넘으면 `ResourceLimitExceeded`로 전체 검색이 실패한다. 포인터 대상조차 제시되지 않는다. 현재 보존 정책(백업 10개, runtime archive 최근 3개·7일)에서는 도달 가능성이 낮아 결함으로 분류하지 않았다. 문서상 의도("부분 후보 적용 안 함")와도 일치한다.
- **추정 — stable·unstable row가 섞인 DOM:** stable key row가 하나라도 있으면 같은 이벤트의 unstable row 텍스트는 preview에만 나타나고 commit 경로에 들어가지 않는다(`pipeline_state.py:_apply_structured_preview_payload`). parity 계약 D5는 "unstable-only snapshot은 fallback"만 규정한다. 혼재 DOM이 실제 사이트에 존재하는지는 확인하지 못했다.
- **추정 — 장시간 실운용:** 실제 중계 수 시간 동안의 큐 포화 빈도, 재연결 반복, 공유 복구 포인터를 쓰는 다중 인스턴스 운용은 측정하지 않았다.

## 6. Documentation Mismatches

| 문서 | 설명 | 실제 |
|---|---|---|
| `CLAUDE.md` §6 "의존성 전면 업그레이드 (2026-10-13)", `GEMINI.md:466` | `requirements-dev.txt`를 PyQt6 6.11.0으로 상향 | `requirements-dev.txt`는 `PySide6==6.12.0`이며 PyQt6 의존성이 없다 |
| `CLAUDE.md` §6 (2026-04-05/06 메모), `GEMINI.md:546` | frozen 빌드에 `PyQt6.QtNetwork` 포함, `typings/PyQt6/QtNetwork.pyi` 추가 | spec은 `PySide6.QtNetwork`(143행)를 쓰고 stub은 `typings/PySide6/QtNetwork.pyi`에 있다. 과거 메모의 binding 명칭이 현재와 다르다 |
| `CLAUDE.md` §4.2 | "중지 시 preview 큐를 먼저 소진하고 마지막 버퍼를 확정해 누락 방지" | 큐 포화 뒤 종료하면 ISSUE-001처럼 마지막 preview가 거절된다 |
| `CLAUDE.md` §1, `README.md` | 최신 감사·후속 구현 기록은 `PROJECT_AUDIT.md` 참고 | 이 보고서가 그 내용을 대체했다. 이전 기록은 `git show e2545a5:PROJECT_AUDIT.md`로 볼 수 있다. 참조 문구 갱신이 필요하다 |

README의 테스트 수치(723 passed / 3 skipped)는 QtWebEngine이 있는 환경 기준이며 이번 합계와 같으므로 불일치로 보지 않았다. 과거 버전별 수치는 역사 기록으로 명시되어 있다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. **ISSUE-001:** preview 적용 규칙을 sequence 기준 단조 증가로 바꾼다. coalesced와 queued 항목을 함께 정렬하고, gap 항목은 거절하지 않고 최신 snapshot으로 적용한다. terminal/stop barrier에서는 같은 run의 최대 sequence preview가 반드시 마지막에 반영되게 한다. 먼저 probe 시나리오를 회귀 테스트로 고정한다.

### Phase 2 — Stability

- **ISSUE-002:** owner lease에 프로세스 생성 시각 또는 heartbeat stale 판정을 추가한다.
- 종료 직전 preview gap·drop이 있으면 사용자에게 "마지막 자막 일부가 누락됐을 수 있음"을 알리는 진단을 추가한다.
- 실제 중계에서 UI 정지 상황(대형 hydrate, 모달)을 포함한 큐 포화 빈도를 측정한다.
- `CLAUDE.md`·`GEMINI.md`의 PyQt6 명칭과 감사 문서 참조를 정리한다.

### Phase 3 — Structural

- 큐 계층(일반/overflow/coalesced/terminal)마다 흩어진 순서 규칙을 "run별 sequence 정렬 버퍼" 하나로 통합해 처리 순서를 한 곳에서 보장한다.
- production emitter가 없는 `error`·`subtitle_not_found` handler를 제거하거나 `finished` 경로와 같은 finalize 계약으로 맞춰 유지보수 혼동을 줄인다.

**이 계획의 제품 코드 수정은 이번 감사에서 수행하지 않았다.**

## 8. Test Recommendations

| 분류 | 입력·실행 조건 | 기대 결과 |
|---|---|---|
| Unit / Regression — ISSUE-001 | `maxsize=2`: preview #1·#2 적재, #3 coalesced, #1 소비, #4 적재, `finished` | 마지막 발언 포함 4개 entry, 중복 0, `preview_gaps` 기록 |
| Regression — ISSUE-001 | 위와 같으나 `finished` 대신 `_stop()` | 동일 보존. 실시간 TXT에 마지막 발언 1회 |
| Integration — ISSUE-001 | 기본 500 큐: status 499 + preview 연속 + UI 1 tick 처리 + preview #N + `finished` | 최대 sequence preview가 마지막에 적용됨 |
| Concurrency — ISSUE-001 | worker thread가 preview를 계속 보내는 동안 UI tick을 인위적으로 2초 지연한 뒤 stop | 중지 시점까지 관측한 마지막 DOM 창 내용이 entries에 존재 |
| Regression — ISSUE-001 | 오래된 coalesced #3이 최신 #4 적용 뒤 도착 | #3이 #4의 결과를 되돌리거나 중복 entry를 만들지 않음 |
| Unit — ISSUE-002 | `owner.json`에 무관한 live PID + 오래된 heartbeat 또는 다른 생성 시각 | 복구 후보에 포함, GC 대상 |
| Unit — ISSUE-002 | 현재 프로세스 PID·생성 시각·최신 heartbeat | 후보와 GC에서 제외 |
| Platform-specific — ISSUE-002 | Windows Access denied 프로세스 PID | 명시한 정책(경고와 함께 후보 표시 등)대로 동작 |
| End-to-End | Chrome 오프라인 DOM → worker → Qt 큐 포화 주입 → stop → JSON/DB 저장 → 재로드 | 발언 수·텍스트·화자 보존, `capture_quality`에 gap 기록 |
| Platform-specific | Windows x64 frozen EXE에서 `--smoke --smoke-instantiate-window`, portable preflight | exit 0 |

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Acceptable | 정상 경로 회귀 전체 통과. 큐 포화 후 종료라는 특정 경계에서 마지막 발언 유실(ISSUE-001) |
| Runtime Stability | Acceptable | bounded queue, run 격리, worker·driver 종료 보호, 종료 escalation 확인. 이번에 크래시성 결함은 발견하지 못함 |
| Data Integrity | Needs Work | 직전 감사의 저장·종료 결함은 수정됨. 큐 포화 뒤 종료 시 관측 데이터가 조용히 빠지는 경로가 남음 |
| Error Resilience | Acceptable | atomic 쓰기, transaction rollback, 로드 취소, budget이 일관됨. owner lease의 stale 판정만 약함(ISSUE-002) |
| Cross-platform Robustness | Acceptable | ARM64 소스 범위에서 통과. CI에 Windows 3.10, macOS/Linux 3.15 job이 있으나 원격 결과와 x64 frozen은 이번에 확인하지 못함 |
| Test Confidence | Acceptable | 726개 수준 회귀와 pyright 0 errors. 단 coalesced 뒤에 더 새 queued preview가 있는 interleaving은 기존 테스트가 다루지 않음 |

**실제로 먼저 수정할 문제 3개:**

1. **ISSUE-001:** 큐 포화 후 종료 시 newer preview가 sequence gap으로 거절되고 오래된 coalesced snapshot만 남아 마지막 발언이 유실되는 문제.
2. **ISSUE-002:** PID 생존만으로 archive owner를 판정해, 비정상 종료 archive가 수동 복구 후보와 GC에서 영구 제외될 수 있는 문제.
3. **문서 정합성:** `CLAUDE.md`·`GEMINI.md`의 PyQt6 명칭과 §4.2 "중지 시 누락 방지" 서술을 실제 구현(PySide6, ISSUE-001 수정 전 한계)에 맞게 바로잡는 작업.
