# Project Audit

## 후속 구현 및 검증 — 2026-11-08

사용자의 후속 수정 요청에 따라 아래 감사(§1–9)의 제안을 main 작업 트리에서 구현했다. §1–9는 수정 전 `7b88e47`에 대한 감사 기록으로 그대로 보존하며, 현재 미해결 목록이 아니다. 버전 증가·커밋·푸시·배포는 하지 않았다.

| 감사 항목 | 현재 상태 | 구현 |
|---|---|---|
| ISSUE-001 (Phase 1): reset이 coalesced·held preview를 앞질러 확정 발언 중복 | 수정·검증 | `ORDERED_STREAM_MESSAGE_TYPES = {preview, subtitle_reset, reconnected}`가 run별 sequence를 공유한다(`_emit_worker_message`). `_accept_preview_sequence`는 이 세 유형에 적용되고, gap 뒤 메시지를 종류와 함께 보류한다. 보류가 있는 동안 들어온 메시지도 보류한다. `_drain_held_previews`는 coalesced의 `preview`·`reconnected`(둘 다 `worker_sequence` 기록)까지 모아 sequence 순서로 재적용한다. stream handler가 처리하지 않는 유형(`reconnected`)은 `_handle_message`로 넘긴다. `_drain_coalesced_worker_messages`는 꺼낸 stream 메시지를 모두 보류한 뒤 한 번에 재적용한다 |
| ISSUE-001 overflow 경로 | 수정·검증 | `_process_message_queue` 순서를 terminal → worker 큐 → overflow → coalesced → held로 바꿨다(기존: overflow가 큐보다 먼저). coalesced worker drain과 held 재적용은 worker 큐가 비고(`_is_worker_queue_empty`) overflow에 같은 run의 stream 메시지가 없을 때(`_has_overflow_stream_messages`)만 수행한다. `_drain_pending_previews`도 예산이 소진돼 큐가 남으면 overflow·coalesced·held를 재적용하지 않는다 |
| gap 뒤 full snapshot 즉시 수용 | 보강 | overflow·coalesced에 같은 run의 더 오래된 stream 메시지가 있으면 즉시 수용하지 않고 보류한다(`_has_stashed_stream_messages`). 없으면 기존처럼 즉시 수용한다 |
| 재큐잉 중복 판정 | 보강 | 이미 수용된 stream 메시지를 다시 넣을 때 `_as_requeueable`로 sequence를 지운다. 두 번째 unwrap에서 중복으로 버려지지 않는다 |
| Phase 2: 사용자 진단 | 구현 | held 상한 초과 드롭은 `_record_overflow_drop`(queue_drops + 상태/토스트)으로 알린다. `PREVIEW_HELD_MAX`는 256 → 1024로 올렸다(큐 500 + overflow 128보다 커야 정상 경로에서 드롭이 없음). 중지/완료 요약(`_build_capture_summary_text`)에 이번 run 동안 늘어난 드롭 수를 표시한다. 기준값은 `_begin_extraction_run`이 기록한다 |
| Phase 2: `reconnected`·`keepalive` 순서 결정 | 결정·고정 | `reconnected`는 순서 대상에 포함했다. 재연결 이전 preview는 `_soft_resync` 전에, 이후 preview는 그 뒤에 적용된다. `keepalive`는 마지막 entry의 `end_time`만 늘리고 coalesced(최신값)이므로 순서 대상에서 제외했다. 테스트로 sequence 없음을 고정했다 |
| Phase 2: 문서 | 수정 | `CLAUDE.md` §1·§4.2·§8.5(CI matrix), `GEMINI.md`, `PIPELINE_LOCK.md` §2, README 변경 이력 |
| Phase 3: 순서 규칙 통합 | 부분 구현 | 스트림 순서 규칙을 `_accept_preview_sequence`(수용/보류)와 `_drain_held_previews`(재적용) 두 곳으로 모았다. 큐 계층(일반/overflow/coalesced/terminal) 자체를 하나의 정렬 버퍼로 합치는 구조 변경은 하지 않았다. 계층마다 용량·우선순위·알림 계약과 기존 테스트가 걸려 있어 별도 작업으로 남긴다 |
| CI·릴리스 gate | 반영 | `tests/test_audit_followup_20261108.py`를 CI 명시 gate 두 곳과 `scripts/run_release_verification.py`에 추가했다 |

### 의도적으로 바꾸지 않은 항목

- **reset 의미론:** grace(1초)와 "다음 preview 전 reset commit" 규칙, `apply_reset`, commit 경로, 글로벌 히스토리 + suffix 의미론은 그대로다. 바꾼 것은 메시지가 그 규칙에 도달하는 순서뿐이다.
- **stale reset:** 이미 반영한 sequence보다 오래된 `subtitle_reset`은 적용하지 않고 로그만 남긴다. 늦게 적용하면 ledger가 비워져 다음 preview의 row가 다시 commit되기 때문이다.
- **parity 계약:** 큐 순서는 데스크톱 내부 전달 계층이며 `parity/` 계약(수집·파이프라인 의미론)에는 해당하지 않아 바꾸지 않았다.

### 검증

- 새 회귀 `tests/test_audit_followup_20261108.py`: **13 passed**. 감사 probe의 세 실패 경로(수집 중 tick, `finished`, overflow), `_stop()`·포화 없는 대조군, reset sequence 공유와 keepalive 제외, coalesced `reconnected` 재적용 순서, 오래된 stash가 있을 때 full snapshot 보류와 없을 때 즉시 수용, 예산 제한 drain의 재적용 보류, 재큐잉, held 초과 알림, run 단위 드롭 요약을 검증한다. 테스트는 8ms tick 예산에 의존하지 않도록 backlog가 빌 때까지 tick을 반복한다.
- 저장소 루트 전체 `pytest`: **728 passed / 20 skipped**. skip 중 17건은 ARM64에 QtWebEngine이 없어 생긴 브라우저 DOM 검사이며 이번에는 Chrome으로 다시 실행하지 않았다.
- `pyright`: **204 files / 0 errors / 0 warnings**.
- 실제 생중계 큐 포화, Windows x64, macOS/Linux의 원격 CI 결과는 확인하지 않았다.

---

**아래는 수정 전 감사 기록이다.**

감사일: **2026-11-08 (Asia/Seoul)**
대상: **Korea Assembly CC v16.14.16 / main / `7b88e47`** (작업 트리 clean 상태에서 시작)
방식: 기능 구현·런타임 안정성 감사. **제품 코드·테스트·설정은 수정하지 않았고, 저장소 변경은 이 보고서뿐이다.** 재현 검사는 저장소 밖 임시 복사본(`git archive`)에서만 실행했다.

> 직전 감사(`e2545a5` 대상)와 그 후속 구현·검증 기록(2026-11-07)은 커밋 `7b88e47`의 `PROJECT_AUDIT.md`에 있다(`git show 7b88e47:PROJECT_AUDIT.md`). 이 문서는 그 수정이 반영된 현재 커밋을 새로 감사한 결과이다. ISSUE 번호는 이 문서 안에서만 쓴다.

## 1. Executive Summary

**전체 상태:** 직전 감사의 두 결함은 현재 코드에서 수정되어 있고 회귀 테스트도 있다. 하나는 sequence gap 뒤 preview 유실, 다른 하나는 PID 재사용 시 archive가 영구 제외되는 문제였다. 이번에 다시 확인했다. 격리 복사본의 전체 회귀는 **715 passed / 20 skipped**, pyright는 **203 files / 0 errors / 0 warnings**이다. URL 검증, run 식별, bounded queue, terminal barrier, JSON budget, archive 무결성, atomic 교체, SQLite transaction·operation ID 멱등성, 업데이트 서명·rollback 같은 방어 장치도 그대로 유지된다.

**전체 위험도: Medium.** 새로 확정한 결함은 1건이다.

| 우선순위 | 이슈 | 핵심 결과 |
|---|---|---|
| 1 | ISSUE-001 — 큐 포화 뒤 `subtitle_reset`이 더 오래된 preview보다 먼저 적용되어 이미 확정된 발언이 **중복 entry**로 다시 기록됨 | 임시 재현 5개 경로 중 3개에서 중복 발생: 수집 중 tick, worker `finished`, overflow 경로. 사용자 `_stop()` 경로와 포화 없는 대조군은 정상. 직전 커밋 `e2545a5`에서도 같은 중복이 재현되어 이번 수정 이전부터 있던 결함이다 |

**데이터 손상/유실:** DB·파일의 물리적 손상, 임의 명령 실행, path traversal은 발견하지 못했다. ISSUE-001은 **유실이 아니라 중복**이다. 이미 확정된 발언이 새 entry로 한 번 더 추가된다. 이 중복은 일반 commit 경로를 타므로 화면, 실시간 TXT, 키워드 알림, 이후 JSON/DB 저장에 그대로 남는다. 사용자가 편집으로 지울 수는 있지만 따로 알림은 없다.

**가장 먼저 수정할 영역:** worker 스트림 메시지의 순서 보장이다. `preview`만 sequence를 가지고, `subtitle_reset`(그리고 `keepalive`)은 sequence 없이 들어온 즉시 처리된다. 큐 포화로 preview가 보류·coalesce되거나 reset이 overflow 경로로 가면 이 둘의 상대 순서가 뒤집힌다.

## 2. Project Understanding

### 목적

국회 의사중계 사이트(`assembly.webcast.go.kr`)의 AI 자막을 Selenium Chrome으로 실시간 수집한다. 수집한 자막은 PySide6 UI에서 검색·편집·병합하고, JSON 세션·SQLite 히스토리·TXT/SRT/VTT/DOCX/HWPX/HWP/RTF로 저장한다. 주 대상은 Windows 데스크톱이다. Chrome 확장은 별도 저장소이며 `parity/` 계약만 공유한다.

확인한 문서는 `README.md`, `CLAUDE.md`, `PIPELINE_LOCK.md`, `requirements-dev.txt`, `pytest.ini`, `pyrightconfig.json`, `.github/workflows/ci.yml`, 직전 `PROJECT_AUDIT.md`이다. 루트에 `AGENTS.md`는 **없다**.

### 주요 entrypoint와 핵심 모듈

| 영역 | 파일·심볼 | 역할 |
|---|---|---|
| 앱 시작 | `국회의사중계 자막.py::main` | CLI(smoke/update) 분기, storage preflight, `QApplication`·`MainWindow` |
| UI 조립 | `ui/main_window.py::MainWindow`, `ui/main_window_impl/runtime_state.py` | mixin 조립, 큐(worker 500 / control 200)·타이머·DB worker |
| 수집 lifecycle | `runtime_lifecycle_extraction.py::_start`, `runtime_lifecycle_stop.py::_stop` | 입력 검증, run 시작·중지 |
| worker | `capture_browser.py::_extraction_worker` | Chrome, observer/probe, `preview`·`keepalive`·`subtitle_reset`·`finished` 발행 |
| 큐 | `pipeline_queue.py::_emit_worker_message/_accept_preview_sequence/_drain_held_previews`, `pipeline_messages.py::_process_message_queue/_handle_message` | run envelope, preview sequence, coalescing, overflow·terminal stash, gap 보류 |
| commit | `pipeline_state.py::_apply_structured_preview_payload/_commit_scheduled_subtitle_reset`, `core/live_capture_impl/`, `core/subtitle_pipeline.py` | stable row ledger, reset grace, suffix 증분 |
| 세션·복구 | `persistence_session_*.py`, `persistence_runtime_*.py`, `core/recovery_candidates.py`, `core/runtime_archive_owner.py`, `core/process_wait.py` | snapshot 저장, segment/tail archive, owner lease(process marker) |
| 내보내기 | `persistence_exports_*.py`, `core/timestamp_blocks.py`, `core/export_text.py`, `core/hwpx_export.py` | 표시 레이아웃 스냅샷, streaming writer, atomic 교체 |
| DB | `core/database_manager.py`, `core/database_impl/` | thread별 connection, WAL, transaction, lineage, FTS |
| 업데이트 | `core/update_manifest.py`, `core/update_installer.py` | Ed25519 manifest, rename-swap, smoke, rollback |

### 데이터 저장과 외부 의존성

- 상태의 원본은 `capture_state.entries`이고 `self.subtitles`는 alias이다. 핵심 공유 상태는 `live_capture_ledger`, reset grace 타이머(`_pending_subtitle_reset_timer`), `_session_revision`/dirty, `_active_capture_run_id`이다. 큐 관련 상태로는 worker 큐, overflow, coalesced, terminal, held(`_preview_held_by_run`)가 있다.
- 장시간 수집은 `backups/runtime_sessions/run_*/`에 manifest·segment·tail checkpoint·`owner.json`으로 남고, 복구 포인터는 `session_recovery.json`이다.
- 외부 의존성은 국회 사이트 DOM과 `live_list.asp`, Chrome/WebDriver, GitHub 업데이트 채널, python-docx, pywin32·한컴, cryptography다.

### 핵심 실행 흐름

```text
URL/selector 입력 → _start(검증, dirty 확인) → _begin_extraction_run
→ ExtractionWorker → Chrome DOM → message_queue.put(tuple) → _emit_worker_message(run_id, preview만 sequence)
   ├ 정상: MainWindowMessageQueue(500)
   ├ 포화 + coalesced 유형(preview/keepalive/status…): 최신값으로 덮어씀 (preview는 full_snapshot + worker_sequence)
   ├ 포화 + 비coalesced(subtitle_reset 등): 1초 blocking put → 실패 시 overflow passthrough(128)
   └ 포화 + terminal: terminal stash
→ _process_message_queue(100ms·8ms·50건): terminal → overflow → control/worker 큐 → coalesced → held
→ preview: _accept_preview_sequence(gap이면 held) → _apply_structured_preview_payload
     → _commit_scheduled_subtitle_reset_before_preview → reconcile ledger → commit_live_row
     → _publish_capture_commit(실시간 TXT·키워드 알림) → revision/dirty → runtime tail
→ subtitle_reset: grace 타이머 예약(1초) → 다음 preview 직전 또는 타이머 만료 시 apply_reset + ledger 초기화

중지 → _stop(is_running=False, reset 취소) → _drain_pending_previews → finalize → _retire_capture_run
worker 종료 → finished barrier(_drain_pending_previews) → _finalize_terminal_capture_state → retire
세션 저장 → SessionSaveSnapshot → background atomic JSON → DB worker → revision 일치 시 dirty 해제
```

## 3. Audit Coverage & Limitations

### CodeGraph 사용

`.codegraph/`가 있어 **CodeGraph MCP `codegraph_explore`를 실제로 사용했다.** 확인한 주요 호출·영향 관계는 다음과 같다.

- `_retire_capture_run`, `_has_pending_message_backlog`, `_schedule_followup_message_queue_drain`, `_mark_preview_resync_requested`, `_emit_worker_message`, `_drain_coalesced_worker_messages`의 호출 관계. held·coalesced 정리가 run 폐기와 큐 비우기 양쪽에서 이루어지는 것도 확인했다.
- `_schedule_deferred_subtitle_reset → _commit_scheduled_subtitle_reset_before_preview → _commit_scheduled_subtitle_reset(apply_reset, clear_live_capture_ledger)`. 이 흐름이 `_apply_structured_preview_payload`의 첫 단계에서 실행된다.
- `_get_display_layout`의 caller(렌더·클립보드·TXT/DOCX/HWPX/RTF export)와 `core/timestamp_blocks.py`.

CodeGraph가 다루지 않거나 결과가 잘린 부분은 직접 읽거나 grep으로 보완했다. 범위는 `7b88e47` diff 전체, `pipeline_queue.py`(1–100, 236–720행), `pipeline_messages.py::_process_message_queue/_handle_message`, `pipeline_stream.py::_process_preview_queue_message/_drain_pending_previews`, `capture_browser.py` 수집 루프(540–670행), `runtime_lifecycle_stop.py`의 중지 순서, `ci.yml`이다. Python mixin·`getattr`·Qt signal 경로는 색인으로 완전히 추적되지 않을 수 있어 실제 실행으로 교차 확인했다.

### 실행한 검증

환경: **Windows 11 ARM64 / 저장소 `.venv` Python 3.15.2 / PySide6 6.12.0**. 의존성은 설치하지 않았다. 사용자 DB·세션·백업·설정은 사용하지 않았다.

| 검증 | 명령·방법 | 결과 |
|---|---|---|
| 전체 회귀 (`7b88e47` 복사본) | `QT_QPA_PLATFORM=offscreen python -m pytest tests -q --tb=short -ra` | **715 passed / 20 skipped / 31.3초** |
| 정적 검사 | `pyright --outputjson` | **203 files / 0 errors / 0 warnings** |
| ISSUE-001 재현 (`7b88e47`) | 임시 `tests/test_zz_probe_reset_order.py`(복사본에만 두고 실행 후 삭제), 기존 `qt_window` fixture | **3 failed / 2 passed**. 실패 3건이 결함 증거이다. 통과 2건은 포화 없는 대조군과 사용자 `_stop()` 경로 |
| ISSUE-001 기원 확인 (`e2545a5`) | 같은 probe를 직전 커밋 복사본에서 실행 | 같은 중복 재현(그 커밋에는 직전 감사의 유실 결함도 함께 있음) |

skip 20건 중 17건은 이 ARM64 환경에 `PySide6.QtWebEngineCore`가 없어 생긴 브라우저 DOM 검사이다. 나머지는 opt-in soak 1건, live-list smoke(`RUN_LIVE_SMOKE`) 1건, subprocess 환경의 in-process pyright fallback 1건이다. 이번에는 Chrome으로 DOM 검사를 다시 돌리지 않았다(직전 감사 기록에서는 20 passed).

### 반증으로 제외한 후보

- **`_requeue_message_item`이 preview를 `worker_sequence` 없이 coalesced에 넣는 문제:** `_process_preview_queue_message`는 preview에 대해 항상 True를 반환한다. 따라서 preview가 `pending`에 들어가지 않아 도달할 수 없는 경로다.
- **retired run의 held preview가 남아 follow-up drain이 무한 반복되는 문제:** `_retire_capture_run`과 `_clear_message_queue`가 held를 지운다.
- **held 상한(`PREVIEW_HELD_MAX=256`) 초과 시 조용한 드롭:** held는 매 tick 끝에 모두 소진된다. 한 tick의 처리량도 50건 이하라서 현실적으로 도달하지 않는다.
- **process marker 판정:** Linux `/proc/<pid>/stat`의 `)` 뒤 index 19가 starttime(22번째 필드)인 것을 확인했다. Windows `OpenProcess` 실패는 None으로 처리되어 기존 PID 판정으로 되돌아간다(보수적).
- **사용자 `_stop()` 경로의 reset 역전:** `_stop`은 `is_running=False`(39행), reset 취소(55행)를 drain(57행)보다 먼저 수행한다. `_commit_scheduled_subtitle_reset`도 `not is_running`이면 반환하므로 재현되지 않았다.
- **타임스탬프 블록 레이아웃:** 표시 전용이고 `SubtitleEntry`를 바꾸지 않는다. export는 UI 스레드에서 만든 `DisplayLayout` 스냅샷을 받는다.

### 확인하지 못한 범위

실제 국회 생중계 장시간 운용, 실제 큐 포화 빈도, Chrome 브라우저 DOM 회귀 재실행, 한컴 COM 저장, Windows x64, macOS/Linux, frozen EXE 재빌드, 원격 CI 결과는 이번에 검증하지 않았다. 직전 감사가 상세히 다룬 세션 저장·DB·복구·업데이트 경로는 `7b88e47`에서 바뀌지 않았으므로 회귀 통과로만 확인했다. 의존성 취약점 조사는 포함하지 않았다.

## 4. High-Risk Issues

### [ISSUE-001] 큐 포화 뒤 `subtitle_reset`이 더 오래된 preview보다 먼저 적용되어, 이미 확정된 발언이 중복 entry로 다시 기록됨

- **위치:**
  - `ui/main_window_impl/pipeline_messages.py:204–256::_process_message_queue`: 처리 순서가 terminal → overflow → 큐 → coalesced → held이다.
  - `pipeline_messages.py:299–303`: `subtitle_reset`을 받는 즉시 grace 타이머를 예약한다.
  - `ui/main_window_impl/pipeline_state.py:316–350::_commit_scheduled_subtitle_reset(_before_preview)`: `apply_reset` + `clear_live_capture_ledger`.
  - `pipeline_state.py:532`: 모든 preview 적용 전에 예약된 reset을 먼저 commit한다.
  - `ui/main_window_impl/pipeline_queue.py:109–148, 191–235`: gap 보류와 held replay.
  - `pipeline_queue.py:354–401::_emit_worker_message`: preview에만 sequence를 붙인다. 비coalesced 유형은 1초 put 실패 시 overflow로 보낸다.
  - `capture_browser.py:576–578, 659–661`: production reset 발행 지점.
  - `pipeline_stream.py:326–381::_drain_pending_previews`: finished barrier.
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** worker는 `preview #N → subtitle_reset → preview #N+1` 순서로 발행한다. 그런데 UI 쪽에서 preview만 sequence로 정렬하고 reset은 들어온 즉시 처리한다. 다음 두 경로에서 reset이 자기보다 먼저 발행된 preview보다 앞서 적용된다.
  1. **coalesced/held 경로:** 포화 때문에 preview #3은 coalesced에 있고 #4는 gap으로 held된 상태다. 같은 tick에서 큐의 reset이 먼저 타이머로 예약된다. 이어서 tick 끝 `_drain_held_previews`가 #3을 적용하면 `_commit_scheduled_subtitle_reset_before_preview`가 **#3보다 먼저 reset을 commit**하고 ledger를 비운다. 그러면 #3에 포함된 직전 row(이미 확정된 `둘째 발언`)가 새 stable identity로 보여 다시 append된다.
  2. **overflow 경로:** 큐가 가득 찬 채 UI가 1초(`WORKER_MESSAGE_PUT_TIMEOUT`) 넘게 멈추면 reset은 overflow passthrough로 간다. overflow는 다음 tick에서 **일반 큐보다 먼저** drain되므로, 큐에 남아 있던 더 오래된 preview들이 모두 reset 뒤에 적용된다.
- **발생 조건:** worker 큐(500)가 한 번 포화된 뒤, 아직 처리되지 않은 preview 뒤에 DOM clear(`subtitle_reset`)가 이어질 때. reset 자체는 발언 교체나 polling clear마다 발행되는 일상적인 이벤트다. 포화가 전제 조건이며, 실제 운용에서 포화 빈도는 측정하지 않았다. 사용자 `_stop()`은 reset을 취소하고 `is_running=False`에서 drain하므로 해당하지 않는다. worker `finished` barrier는 `is_running=True`인 상태에서 drain하므로 해당한다.
- **영향:** 이미 확정된 발언이 새 entry로 한 번 더 추가된다. 이 entry는 일반 commit 경로(`_publish_capture_commit`)를 타므로 화면, 실시간 TXT 기록, 키워드 알림, 세션 dirty, 이후 JSON/DB 저장까지 그대로 이어진다. 중복이라 내용이 사라지지는 않지만, 회의록 성격의 산출물에 같은 발언이 두 번 나타난다. `capture_quality`에는 `preview_gaps`만 기록되고 중복 사실은 드러나지 않는다.
- **근거:** 임시 probe 결과(`maxsize=2` 큐; preview #1·#2 적재, #3 coalesced, #1 소비, #4 적재, #2 소비, reset 적재. 각 preview는 DOM 창처럼 직전 row와 새 row를 함께 담음):

  | 경로 | 관측 entries | 기대 |
  |---|---|---|
  | 수집 중 tick + reset 뒤 새 발언 | `첫째, 둘째, **둘째**, 셋째, 넷째, 다섯째` | `첫째, 둘째, 셋째, 넷째, 다섯째` |
  | worker `finished` | `첫째, 둘째, **둘째**, 셋째, 넷째` | `첫째, 둘째, 셋째, 넷째` |
  | overflow 경로(put timeout 0.01초로 축소, #2·#3 큐 적재 중 reset) | `첫째, **첫째**, 둘째, 셋째, 넷째` | `첫째, 둘째, 셋째, 넷째` |
  | 사용자 `_stop()` | 정상 | — |
  | 대조군(포화 없음, 같은 메시지 순서) | 정상 | — |

  같은 probe를 `e2545a5`에서 실행해도 같은 중복이 재현됐다(그 커밋에서는 #4 유실도 함께 발생). 따라서 `7b88e47`이 새로 만든 결함이 아니라, preview만 sequence로 정렬하는 설계에서 온 기존 결함이다.
- **반증 확인:**
  - `subtitle_reset` grace(1초)와 "다음 preview 전에 reset commit" 규칙은 새 발언자가 이전 entry에 merge되는 것을 막으려는 의도된 장치다. 그러나 이 규칙은 "다음 preview가 reset보다 나중에 발행됐다"는 전제에 의존한다. 그 전제가 큐 포화 시 깨진다.
  - ledger 초기화 뒤의 baseline은 전역 `confirmed_compact`를 쓰지만, probe에서 보듯 이 baseline이 직전 row의 재commit을 막지 못한다.
  - `7b88e47`의 held replay는 preview끼리의 순서만 맞춘다. reset·keepalive는 sequence가 없어 정렬 대상이 아니다.
  - 기존 회귀(`test_audit_followup_20261107.py`, `test_preview_gap_recovery.py`, `test_project_audit_queue_hardening.py`)는 포화 중 reset이 끼어드는 interleaving을 다루지 않는다.
- **호출/영향 범위:** `_extraction_worker → message_queue.put → _emit_worker_message → (큐 | coalesced | overflow)`. 소비 측은 `_process_message_queue`·`_drain_pending_previews → _handle_message/_process_preview_queue_message("subtitle_reset") → _schedule_deferred_subtitle_reset`이다. 이후 `_drain_held_previews → _apply_structured_preview_payload → _commit_scheduled_subtitle_reset → clear_live_capture_ledger → commit_live_row → _publish_capture_commit`로 이어진다. 영향 모듈은 실시간 저장, 키워드 알림, 세션 revision, runtime archive tail, JSON/DB 저장이다.
- **권장 수정 방향:**
  - `subtitle_reset`(필요하면 `keepalive`도)에 preview와 **같은 run별 sequence 공간**의 번호를 붙인다. held preview가 있거나 coalesced preview가 대기 중이면 reset도 보류해 sequence 순서로 함께 replay한다.
  - 최소 조치로, reset을 받았을 때 같은 run에 더 낮은 sequence의 coalesced·held preview가 있으면 그것을 먼저 적용한 뒤 reset을 예약한다.
  - overflow drain을 일반 큐 drain보다 뒤로 옮기거나, overflow 항목도 sequence를 비교해 정렬하는 방안을 검토한다. overflow drain이 큐보다 먼저인 현재 순서는 terminal 외 스트림 메시지에서는 역전을 만든다.
  - 수정 시 `PIPELINE_LOCK.md` §2와 parity 계약(reset 의미론)을 함께 갱신한다. 코어 suffix 의미론은 바꿀 필요가 없다.
- **필요한 회귀 테스트:** 위 probe의 세 실패 경로(tick, `finished`, overflow)를 고정한다. 기대 결과는 확정 발언 중복 0, 실시간 TXT 각 발언 1회, reset 뒤 새 발언이 새 entry로 분리되는 것이다. 대조군과 `_stop()` 경로도 함께 고정해 기존 동작이 바뀌지 않음을 보장한다.

## 5. Potential Functional Gaps

- **Likely Gap — 순서 역전·중복의 사용자 진단 부재:** `preview_gaps`·`queue_drops`는 저장되지만, 포화 뒤 중복이나 순서 역전이 생겼을 수 있다는 사실을 사용자에게 알리지 않는다. overflow trim만 토스트로 알린다.
- **추정 — `reconnected`와 held preview의 순서:** coalesced 순서(`COALESCED_WORKER_MESSAGE_ORDER`)에서 `reconnected`는 `preview`보다 먼저 처리되어 `_soft_resync`를 실행한다. 재연결 직전의 오래된 preview가 coalesced·held 상태라면 resync 뒤에 적용될 수 있다. ISSUE-001과 같은 계열이지만 재현하지 않았다.
- **Confirmed Gap(의도된 동작) — 복구 후보 탐색 budget의 전부-아니면-전무:** 후보 1,000개, 256 MiB, 경로 10,000개 중 하나라도 넘으면 전체 검색이 실패한다. 직전 후속 기록에서 문서화된 의도로 유지하기로 했고, 현재 보존 정책에서는 도달 가능성이 낮다.
- **추정 — stable·unstable 혼재 row:** 직전 감사와 같다. parity 계약 D5 변경이 필요하며 실제 사이트에 이런 DOM이 존재하는지는 확인하지 못했다.
- **추정 — 장시간 실운용:** 실제 중계 수 시간 동안의 큐 포화 빈도와 재연결 반복은 측정하지 않았다. ISSUE-001의 실제 발생률은 이 값에 달려 있다.

## 6. Documentation Mismatches

| 문서 | 설명 | 실제 |
|---|---|---|
| `CLAUDE.md` §8.5 | "GitHub CI: pyright fail-fast → pytest (Windows, Python 3.15)" | `ci.yml`에는 Windows 3.15 주 job 외에 `compatibility` matrix(Windows 3.10, ubuntu 3.15, macOS 3.15)가 있다 |
| `CLAUDE.md` §4.2 | "중지 시 preview 큐를 먼저 소진하고 마지막 버퍼를 확정해 누락 방지… 보류 후 sequence 순서로 적용" | 누락 방지는 맞다. 다만 reset은 sequence 정렬 대상이 아니어서 포화 시 중복이 생길 수 있다(ISSUE-001). 수정 전까지 한계로 명시할 필요가 있다 |
| `CLAUDE.md` §1, README 변경 이력 | 최신 실행 결과와 외부 검증 한계는 `PROJECT_AUDIT.md`의 "후속 구현 기록"을 따른다 | 이 보고서가 그 내용을 대체했다. 2026-11-07 후속 기록은 `git show 7b88e47:PROJECT_AUDIT.md`로 볼 수 있다. 참조 문구 갱신이 필요하다 |

README의 테스트 수치(715 passed / 20 skipped)는 이번 실행과 일치한다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. **ISSUE-001:** 먼저 probe 시나리오 3개를 실패하는 회귀 테스트로 고정한다. 그다음 `subtitle_reset`에 preview와 같은 run별 sequence를 부여하고, held/coalesced replay에 reset을 포함해 발행 순서대로 적용한다. overflow drain 순서도 일반 큐 뒤로 조정하거나 sequence로 정렬한다.

### Phase 2 — Stability

- 큐 포화 이후 gap·overflow가 있었던 run에 대해 "자막 순서가 일시적으로 어긋났을 수 있음" 진단을 상태바나 저장 메타데이터로 노출한다.
- `reconnected`·`keepalive`도 같은 순서 규칙에 포함할지 결정하고 테스트로 고정한다.
- 실제 중계에서 큐 포화 빈도(UI 정지 시간, 대형 hydrate·모달 중 수집)를 측정해 ISSUE-001의 실제 우선순위를 재평가한다.
- `CLAUDE.md` §8.5 CI 설명과 §1·README의 감사 문서 참조를 정리한다.

### Phase 3 — Structural

- worker → UI 스트림을 "run별 sequence 정렬 버퍼" 하나로 통합한다. 일반/overflow/coalesced/held 계층마다 흩어진 순서 규칙을 한 곳에서 보장하는 구조로, 직전 감사에서도 권고한 방향이다. 현재는 계층마다 drain 순서가 달라 각 메시지 유형의 상대 순서를 개별 보정해야 한다.

**이 계획의 제품 코드 수정은 이번 감사에서 수행하지 않았다.**

## 8. Test Recommendations

| 분류 | 입력·실행 조건 | 기대 결과 |
|---|---|---|
| Regression — ISSUE-001 tick | `maxsize=2`: #1·#2 적재, #3 coalesced, #1 소비, #4 적재, #2 소비, `subtitle_reset` 적재 → tick → 새 row preview → tick | entries `첫째·둘째·셋째·넷째·다섯째`, 중복 0 |
| Regression — ISSUE-001 finished | 위와 같고 reset 뒤 `finished` | entries `첫째~넷째`, 중복 0, 실시간 TXT 각 1회 |
| Regression — ISSUE-001 overflow | `WORKER_MESSAGE_PUT_TIMEOUT` 축소. #1 처리 후 #2·#3 적재(포화) 중 reset → overflow → tick → 새 row | entries `첫째~넷째`, `첫째` 중복 0 |
| Regression — 기존 동작 보존 | 포화 없는 같은 순서, 그리고 `_stop()` 경로 | 현재와 동일(정상) |
| Unit — 순서 버퍼 | sequence가 붙은 preview/reset/keepalive를 임의 순서로 큐·coalesced·overflow·held에 분산 주입 | 적용 순서가 sequence 오름차순. 오래된 snapshot은 무시 |
| Concurrency | worker thread가 preview·reset을 계속 발행하는 동안 UI tick을 2초 지연시킨 뒤 재개 | 화자 경계 보존, 중복 0, 마지막 발언 보존 |
| Integration — 저장 | 위 포화 시나리오 후 세션 JSON 저장·재로드와 DB 저장 | 저장된 entry 수·텍스트가 기대값과 일치 |
| End-to-End | Chrome 오프라인 DOM 페이지에서 row 교체·clear 반복 + 큐 포화 주입 → 중지 → 저장 | 발언 수·화자 경계 보존, `capture_quality`에 gap 기록 |
| Platform-specific | Windows x64 frozen EXE `--smoke --smoke-instantiate-window`, portable preflight. Linux에서 process marker 테스트 | exit 0, marker 판정 통과 |

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Acceptable | 정상 경로 회귀 전체 통과. 큐 포화 뒤 reset이 끼면 발언이 중복됨(ISSUE-001) |
| Runtime Stability | Good | bounded queue, run 격리, terminal barrier, worker·driver 종료 보호, held 정리 확인. 크래시성 결함은 발견하지 못함 |
| Data Integrity | Acceptable | 직전 감사의 유실 결함은 수정됨. 포화 조건에서 중복 entry가 저장물까지 전파되는 경로가 남음 |
| Error Resilience | Good | atomic 쓰기, transaction rollback, 로드 취소, budget, 보수적 owner 판정이 일관됨 |
| Cross-platform Robustness | Acceptable | ARM64 소스 범위에서 통과. CI에 Windows 3.10, macOS/Linux 3.15 job이 있으나 원격 결과와 x64 frozen은 이번에 확인하지 못함 |
| Test Confidence | Acceptable | 735개 수준 회귀와 pyright 0 errors. 다만 큐 포화 중 preview 외 스트림 메시지가 끼어드는 interleaving은 기존 테스트가 다루지 않음 |

**실제로 먼저 수정할 문제 3개:**

1. **ISSUE-001:** `subtitle_reset`이 coalesced·held preview보다 먼저 적용되는 순서 역전. tick·`finished` 경로에서 확정 발언이 중복된다.
2. **ISSUE-001 overflow 경로:** overflow passthrough가 일반 큐보다 먼저 drain되어, overflow로 간 reset이 큐에 남은 오래된 preview 전체를 앞지르는 문제. 같은 수정에 포함하되 별도 회귀로 고정한다.
3. **문서 정합성:** `CLAUDE.md` §8.5의 CI 설명, §4.2의 순서 보장 서술에 reset 한계를 추가하는 작업, §1·README의 감사 문서 참조를 실제에 맞게 고치는 작업.
