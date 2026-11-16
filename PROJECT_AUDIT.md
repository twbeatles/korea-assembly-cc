# Project Audit

감사일: **2026-11-16 (Asia/Seoul)** · 대상: **v16.14.16 / main / c607d15**

기능 구현·런타임 안정성 중심의 일회 감사다. 애플리케이션 코드·테스트·설정은 수정하지 않았다. 이 문서는 2026-09-07 감사 보고서(v16.14.9 대상, 당시 ISSUE-001~004는 v16.14.10에서 수정 완료)를 대체하며, 이전 보고서는 git 이력(`c607d15:PROJECT_AUDIT.md`)에 남아 있다.

## 후속 조치 (v16.14.17, 2026-11-16)

아래는 이 감사 이후 구현한 수정이다. 원문 §1–9는 감사 시점의 기록으로 유지한다.

| 항목 | 상태 | 구현 | 회귀 |
|---|---|---|---|
| ISSUE-001 reset 경계 fallback 후보 유실 | Fixed | `subtitle_reset` 수신 즉시·reset 적용 직전 대기 후보 commit (`pipeline_state._flush_fallback_commit_candidate`, parity `commitPendingFallbackOnReset`) | `tests/test_project_audit_20261116.py` |
| ISSUE-002 fallback commit 최대 대기 상한 없음 | Fixed | 순수 함수 `core/fallback_commit.decide_fallback_commit`, `FALLBACK_COMMIT_MAX_WAIT_MS=2000`, 첫 미확정 관측 `pending_since_at` 유지 | 동일 파일 + parity 벡터 `fallbackCommitGate` |
| ISSUE-003 시간 역순 블록·SRT/VTT | Fixed | `starts_new_block` 역행 시 새 블록, `RelativeCueTimeline` 단조 큐 배치 | 동일 파일 |
| Gap: 업데이트 helper 사본 누적 | Fixed | 시작 시 `cleanup_update_helper_copies` (frozen 실행만) | 동일 파일 |
| Gap: 유실·지연 진단 신호 | Fixed | `CaptureQualityState.fallback_reset_flushes`, `fallback_max_wait_commits` | `tests/test_capture_quality.py` |
| Phase 3: 후보 판정 순수 함수화 + parity 벡터 | Done | `core/fallback_commit.py` ↔ Chrome `src/core/subtitle-pipeline/fallback-commit-gate.ts` | 양쪽 parity 테스트 |
| Chrome 확장 동일 결함 | Fixed (확장 저장소) | reset 분기·타이머 flush, `pendingSince` 최대 대기 | 확장 `tests/fallback-commit-reset.test.ts` (수정 전 코드에서 2건 모두 실패 확인) |
| 양 저장소 동일성 (무작위 차등 검증) | Fixed | `scripts/parity_differential.py` 신설. 공백 문자 집합 차이(U+001C–U+001F·U+0085·U+FEFF)를 찾아 계약 `whitespace`로 통일, 시드 3개 약 12만 건 일치 | 양쪽 parity 테스트 `whitespace` + 벡터 |
| 로컬 3.15 빌드 EXE 실행 실패 | Fixed | PATH 의 `C:\Python314\python3t.dll`(3.14t)이 번들되던 문제. spec 이 빌드 인터프리터 사본으로 교체하고 다른 free-threaded 런타임 제거, UPX 제외 | `tests/test_build_spec_contract.py`, `docs/BUILD_TROUBLESHOOTING.md` §2.2·§2.3 |
| 릴리스 frozen smoke 게이트 무효 | Fixed | GUI EXE 를 `& $artifact` 로 실행해 종료를 기다리지 않던 문제(실패 EXE 도 `$LASTEXITCODE=0`). `Start-Process -Wait` + JSON `ok` 판정, 릴리스 빌드 Python 3.12 → 3.15 | `tests/test_release_workflow.py`, `docs/BUILD_TROUBLESHOOTING.md` §2.4 |
| 문서 불일치 (§6) | Fixed | README·CLAUDE·GEMINI 의 "즉시 반영" 설명, PySide6 배지, 빌드 예시 버전, PyQt6 핀 메모 주석 | — |

남은 항목: 실사이트 commit 지연·reset 타이밍 측정용 opt-in 스크립트(§7 Phase 3 두 번째 항목)와 §5 "추정" 두 건(stable/unstable 혼합 row, 본회의 raw 무제한)은 실제 생중계 관측이 필요해 이번에 구현하지 않았다. 새 진단 카운터가 실사이트 빈도 측정의 첫 근거가 된다.

---

이전 감사들이 저장·복구·DB·업데이트 경로를 여러 차례 다뤘으므로, 이번에는 **그 이후 추가된 코드(v16.14.11~16)** 를 중심으로 보고 나머지 흐름은 회귀 여부만 확인했다.

## 1. Executive Summary

**전체 상태: 양호.** 저장·복구·DB·업데이트 경로는 revision 기반 dirty 관리, 원자적 파일 교체, runtime archive fingerprint, 서명 검증 등 방어 장치가 갖춰져 있고, 이전 감사의 High 이상 이슈는 모두 수정되어 회귀 테스트로 고정되어 있다. 전체 테스트는 **646 passed / 2 skipped**였다.

**전체 위험도: Medium.** Critical/High 이슈는 찾지 못했다. 남은 문제는 v16.14.16에서 도입된 "안정 관측 후 commit" 게이트에 몰려 있다. 일반 자막(`p.smi_word`)이 전부 이 경로를 지나므로, 영향 범위는 넓고 개별 영향은 작다.

| 순위 | 문제 | 심각도 / 신뢰도 |
|---|---|---|
| 1 | 자막 영역 reset 직전 400ms 이내에 들어온 미확정 fallback 텍스트가 commit 없이 버려짐 | Medium / Confirmed (코드 재현, 실사이트 빈도 미확인) |
| 2 | fallback commit 게이트에 최대 대기 상한이 없어, 텍스트가 계속 바뀌는 동안 commit·타임스탬프가 무기한 밀림 | Medium / Confirmed (코드 재현, 실사이트 빈도 미확인) |
| 3 | 시간 역순 엔트리(정렬 OFF 병합)에서 타임스탬프 블록이 한 문단으로 뭉치고 SRT/VTT 큐가 0초 길이가 됨 | Low / Confirmed |

**데이터 유실 가능성: 있다(제한적).** ISSUE-001은 발언자 전환 경계에서 직전 발언의 마지막 몇 어절을 잃을 수 있다. 이미 commit된 엔트리, 저장된 세션 JSON, SQLite, runtime archive가 손상되는 경로는 찾지 못했다.

**가장 먼저 볼 영역:** `ui/main_window_impl/pipeline_state.py`의 fallback commit 후보 처리(reset 경계 flush, 최대 대기 상한). Chrome 확장과 공유하는 계약이므로 `parity/`와 함께 고쳐야 한다.

## 2. Project Understanding

### 목적

국회 인터넷의사중계(`assembly.webcast.go.kr`)의 AI 자막을 Selenium/Chrome으로 실시간 수집해 편집·검색·내보내기하는 Windows용 PySide6 데스크톱 앱이다. 같은 수집 계약을 쓰는 Chrome 확장(`korea-assembly-cc-chrome`)이 형제 제품으로 있고, `parity/`의 계약·벡터 파일로 양쪽을 맞춘다.

### Entrypoint

- `국회의사중계 자막.py` `main()`: 일반 실행, `--smoke`, `--smoke-storage-preflight`, `--smoke-instantiate-window`, `--apply-update`(업데이트 helper).
- `scripts/apply_update.py`: frozen EXE 사본이 helper로 실행되어 설치본을 교체한다.
- `scripts/run_release_verification.py`, `scripts/check_before_push.py`: 릴리스·푸시 전 검증.

### 핵심 모듈

| 영역 | 구현 | 비고 |
|---|---|---|
| 수집 worker | `ui/main_window_impl/capture_browser.py`, `capture_dom.py`, `capture_observer.py`, `capture_live.py` | 0.2초 폴링 + MutationObserver, 재연결, live_list 보완 |
| 큐 | `pipeline_queue.py`, `pipeline_messages.py` | `run_id` envelope, capture/control 큐 분리, terminal 메시지 보존 |
| 파이프라인 | `pipeline_state.py`, `pipeline_stream.py`, `core/subtitle_pipeline.py`, `core/subtitle_pipeline_impl/` | 글로벌 히스토리 + suffix, row ledger, **fallback commit 게이트** |
| 표시 | `view_render.py`, `core/timestamp_blocks.py` | 타임스탬프 블록 문단화(표시·export 전용) |
| 저장·복구 | `persistence_session_*.py`, `persistence_runtime_*.py`, `core/file_io.py` | snapshot clone, runtime segment/manifest/tail checkpoint |
| DB | `core/database_impl/`, `database_worker.py` | 단일 DBWorker, WAL, operation ID 멱등 저장 |
| 내보내기 | `persistence_exports_*.py`, `core/export_text.py`, `core/hwpx_export.py` | TXT/SRT/VTT/DOCX/HWPX/HWP/RTF |
| 업데이트 | `core/update_manifest.py`, `core/update_installer.py`, `ui/main_window_impl/ui/help.py` | Ed25519 manifest, rename 스왑, smoke 실패 시 rollback |

### 데이터 저장

저장소 루트는 개발 실행=repo root, portable=EXE 폴더, 일반 배포=`%LOCALAPPDATA%\AssemblySubtitle\Extractor`. SQLite `subtitle_history.db`, 세션 JSON(`sessions/`), 자동 백업과 runtime archive(`backups/runtime_sessions/<run>/`), `session_recovery.json`, 실시간 TXT(`realtime_output/`), URL 히스토리·프리셋 JSON, QSettings(portable은 `settings.ini`).

### 외부 의존성

PySide6 6.12, Selenium 4.x + Chrome, cryptography(업데이트 서명), python-docx(선택), pywin32 + 한컴오피스(HWP, 선택). 네트워크는 국회 사이트·`live_list.asp`, GitHub 업데이트 manifest·release asset.

### 핵심 실행 흐름

```text
시작(F5) → _start: URL·selector 검증 + 기존 세션 보호
  → _begin_extraction_run → runtime archive + ExtractionWorker
  → Chrome 접속 → live_list로 xcgcd 보완 → AI 자막 활성화
  → 0.2초마다 probe → compact 텍스트가 바뀌면 preview, 같으면 1초마다 keepalive,
    비면 subtitle_reset 을 capture 큐에 put

UI 100ms drain → _apply_structured_preview_payload
  ├ stable key row 있음 → commit_live_row → entries 즉시 반영
  └ 없음(일반 자막) → fallback 후보로 보관 → 같은 raw 2회 관측 또는 400ms 유지 시
                       apply_preview(suffix 증분 추출) → entries 반영
  → dirty/revision 증가 → 렌더 → 실시간 TXT → 2,000개 초과 시 runtime segment flush

subtitle_reset → 1초 grace 타이머 → apply_reset(히스토리 초기화)
                 (grace 중 다음 preview 가 오면 그 직전에 즉시 적용)

중지 → stop_event → preview 큐 소진 → preview_text materialize → finalize → worker 종료 대기

세션 저장 → UI 스레드 snapshot → background JSON 원자 저장 → recovery pointer
  → DBWorker save_session(operation ID) → revision 일치 시에만 dirty 해제
```

## 3. Audit Coverage & Limitations

### 확인한 모듈

직접 열람: `pipeline_state.py`(전체), `capture_browser.py`의 `_extraction_worker`, `core/subtitle_pipeline.py`, `core/subtitle_pipeline_impl/entries.py`·`entry_policy.py`, `core/subtitle_confirmation.py`, `core/timestamp_blocks.py`, `persistence_exports_text.py`, `persistence_runtime_readers.py`, `persistence_runtime_segments.py`(flush 완료 처리), `persistence_session_save.py`, `core/update_installer.py`, `scripts/apply_update.py`, `ui/main_window_impl/ui/help.py`(업데이트 흐름), `core/committee_catalog.py`, `core/live_list.py`(선택 로직), `core/config_impl/storage.py`, `pipeline_messages.py`(finished 처리), v16.14.16 diff(`capture_dom.py`, `text_utils.py`).

### CodeGraph 사용

`codegraph_explore`를 실제로 사용했다. 확인한 호출 관계:

- `_stop → _drain_pending_previews → _process_preview_queue_message → _handle_keepalive → _observe_fallback_commit_candidate → _commit_fallback_candidate`
- `_stop → _materialize_pending_preview → flush_pending_previews → apply_preview`

그 밖의 흐름은 CodeGraph가 아니라 파일 직접 열람과 grep으로 추적했다. CodeGraph 응답은 파일당 일부 구간이 생략(gap)되어 돌아왔으므로, 이슈 근거로 쓴 함수는 모두 원본 파일에서 다시 읽었다.

### 실행한 검증

| 검증 | 결과 |
|---|---|
| 전체 pytest | **646 passed, 2 skipped, 44초.** `Config`의 저장 경로를 임시 디렉터리로 돌린 wrapper에서 `pytest -q`, `QT_QPA_PLATFORM=offscreen` |
| skip 사유 | `test_live_contract_smoke`(`RUN_LIVE_SMOKE` 미설정), `test_pyright_regression`의 in-process fallback 분기(subprocess 가능 환경이라 생략) |
| pyright | 단독 실행하지 않았다. `tests/test_pyright_regression.py`의 subprocess 경로가 통과한 것으로만 확인 |
| 프로브 A | production 메서드(`_apply_structured_preview_payload`, `_schedule_deferred_subtitle_reset`, `_commit_fallback_candidate`)에 가짜 타이머를 붙여 reset 경계 유실 재현 → ISSUE-001 |
| 프로브 B | 같은 harness로 200ms마다 자라는 텍스트 20초 주입 → ISSUE-002 |
| 프로브 C | `core.timestamp_blocks.build_plain_text`, `core.export_text`에 시간 역순 행 주입 → ISSUE-003 |

로컬 환경은 Python 3.15.2, PySide6 6.12.0, Selenium **4.52.0**(핀 4.51.0), pytest **9.2.0**(핀 9.1.1)이다. 핀과 다른 버전이 섞여 있으므로 핀 환경 재현을 대신하지 않는다.

### 확인하지 못한 것

- **실제 생중계 DOM.** 사이트에 접속하지 않았다. 자막 텍스트의 갱신 주기, reset(영역 clear) 시점, stable key를 가진 row의 실제 빈도를 모른다. ISSUE-001·002의 "코드상 발생"은 확인했지만 "실사이트에서 얼마나 자주"는 확인하지 못했다.
- frozen EXE 빌드, `--smoke` CLI, `run_release_verification.py`, 실제 업데이트 설치, 한컴 COM, 장시간 수집, Linux/macOS 실행.
- Chrome 확장 저장소. 같은 게이트 규칙이 확장에도 있다고 주석·문서에 적혀 있으나 확장 코드는 보지 않았다.
- 저장소 루트에 `AGENTS.md`는 없다.

## 4. High-Risk Issues

Critical/High에 해당하는 이슈는 없다. 반증되지 않은 Confirmed 이슈만 실제 심각도와 함께 적는다.

### [ISSUE-001] reset 경계에서 미확정 fallback 후보가 commit 없이 버려진다

- **위치:** `ui/main_window_impl/pipeline_state.py` — `_commit_scheduled_subtitle_reset`(275-296), `_commit_scheduled_subtitle_reset_before_preview`(298-309), `_clear_fallback_commit_candidate`(93-101); `core/subtitle_pipeline.py` `apply_reset`(301-314)
- **우선순위:** Medium
- **신뢰도:** Confirmed (production 메서드로 재현. 실사이트 발생 빈도는 미확인)
- **문제:** 일반 자막은 fallback 후보로 400ms 대기한 뒤 commit된다. 그런데 reset이 적용될 때 `apply_reset`이 `preview_text`와 히스토리를 비우고, 바로 이어 `_clear_fallback_commit_candidate()`가 대기 중인 후보를 flush 없이 지운다. 후보에만 있던 증분은 어디에도 남지 않는다.
- **발생 조건:** ① 마지막 텍스트 갱신 → ② 자막 영역 clear(`subtitle_reset`) → ③ 다음 발언 텍스트 도착이 **400ms 안에** 이어질 때. ③의 preview가 처리되기 직전 `_commit_scheduled_subtitle_reset_before_preview`가 reset을 즉시 적용한다. 400ms가 지나면 타이머가 먼저 commit하므로 유실이 없다.
- **영향:** 직전 발언의 마지막 갱신분(마지막 몇 어절)이 자막 목록·실시간 TXT·저장물 전부에서 빠진다. reset 뒤에는 DOM에도 해당 텍스트가 없어 이후 probe로 복구되지 않는다. 경고나 진단 카운터(`CaptureQualityState`)에도 잡히지 않는다.
- **근거:** 프로브 A 출력.
  ```text
  after stable: [('10:00:00.400', '존경하는 위원장님')]
  final: [('10:00:00.400', '존경하는 위원장님'),
          ('10:00:01.750', '다음은 김철수 위원님 질의하시겠습니다')]
  lost '이상으로 질의를 마치겠습니다': True
  ```
  갱신 후 200ms에 clear, 그 150ms 뒤 다음 텍스트를 넣은 경우다. 다음 텍스트를 갱신 500ms 뒤로 늦춘 대조군(A2)은 `'존경하는 위원장님 이상으로 질의를 마치겠습니다'`가 정상 commit되었다.
- **반증 확인:**
  - reset grace가 1,000ms(`SUBTITLE_RESET_GRACE_MS`)로 400ms보다 길어 **타이머 경로**에서는 후보가 먼저 commit된다. 문제는 grace를 건너뛰는 `before_preview` 경로에만 있다.
  - 중지(`_stop`)와 worker `finished` 경로는 `capture_state.preview_text`를 `_materialize_pending_preview`로 확정하므로 유실이 없다. reset 경로에는 이 materialize가 없다.
  - v16.14.15까지는 fallback이 즉시 commit되어 대기 중인 후보 자체가 없었다. v16.14.16의 게이트 도입으로 생긴 창이다.
  - `tests/test_chrome_parity_20261022.py`는 안정 관측·keepalive·placeholder를 검증하지만 reset과 후보가 겹치는 경우는 없다.
- **호출/영향 범위:** worker `subtitle_reset` put(`capture_browser.py` 574, 653) → `_process_message_queue`/`_drain_pending_previews` → `_schedule_deferred_subtitle_reset` → 다음 `_apply_structured_preview_payload`(473행) → `_commit_scheduled_subtitle_reset`. 일반 자막 수집 전체가 이 경로를 지난다.
- **권장 수정 방향:** reset을 적용하기 전에 대기 중인 후보를 commit한다(`_commit_scheduled_subtitle_reset` 안에서 `apply_reset` 앞, `is_running` 확인 뒤). Chrome 확장과 공유하는 규칙이므로 `parity/capture-contract.json`에 "reset 전 후보 flush"를 먼저 적고 양쪽을 맞춘다. `PIPELINE_LOCK.md` §2 이력에도 기록한다. suffix 추출 의미론 자체는 바꿀 필요가 없다.
- **필요한 회귀 테스트:** 후보 대기 중(관측 1회, 경과 <400ms) `_schedule_deferred_subtitle_reset` → 새 payload 적용 → 엔트리가 `[직전 발언 전체, 새 발언]` 두 개이고 새 발언이 직전 엔트리에 merge되지 않을 것. grace 타이머 만료 경로도 같은 기대값.

### [ISSUE-002] fallback commit 게이트에 최대 대기 상한이 없다

- **위치:** `ui/main_window_impl/pipeline_state.py` `_observe_fallback_commit_candidate`(103-159); `capture_browser.py` 637-651(compact 변경 시에만 preview, keepalive는 1초 간격)
- **우선순위:** Medium
- **신뢰도:** Confirmed (결정적 재현. 실사이트에서 400ms 무변화 구간이 얼마나 드문지는 미확인)
- **문제:** raw가 바뀔 때마다 후보가 새로 만들어지고 `first_seen_at`과 400ms 타이머가 초기화된다. 누적 대기 시간에 상한이 없어서, 텍스트가 400ms 이상 멈추기 전에는 아무것도 commit되지 않는다. commit 시 엔트리의 `timestamp`/`start_time`은 발화 시작이 아니라 commit 시각이다.
- **발생 조건:** 자막 DOM이 0.2~0.4초 간격으로 계속 갱신되는 연속 발언 구간.
- **영향:**
  - 엔트리 타임스탬프가 지연 시간만큼 늦어진다. SRT/VTT 큐 시작, TXT `[HH:MM:SS]`, 타임스탬프 블록 경계가 함께 밀린다.
  - 지연된 구간 전체가 한 엔트리로 들어간다(`ENTRY_MERGE_MAX_CHARS=300`은 merge 판단에만 쓰이고 신규 엔트리 길이는 제한하지 않는다).
  - 그동안 자막 목록·실시간 TXT·runtime tail checkpoint에 반영되지 않는다. 이 구간에 프로세스가 죽으면 복구 대상에 없다.
  - README·CLAUDE의 "딜레이 없이", "SubtitleEntry 즉시 반영"과 어긋난다(§6).
- **근거:** 프로브 B 출력. 200ms마다 한 단어씩 20초간 자라는 텍스트를 넣었다.
  ```text
  entries during 20s of continuous change: 0
  after pause: 1 first ts: 10:00:20.200 len: 489
  ```
  10:00:00에 시작한 발언이 10:00:20.2 타임스탬프의 489자 엔트리 하나가 되었다.
- **반증 확인:**
  - 관측 횟수 조건(2회)은 worker가 **같은 raw를 다시 보내지 않으므로**(compact가 같으면 preview 미전송, keepalive는 1초 뒤) 실질적으로 400ms 타이머보다 먼저 충족되지 않는다.
  - 텍스트 자체는 다음 commit 때 suffix 추출로 한꺼번에 들어오므로, 창(비본회의 4KB tail) 안에 있는 한 유실은 아니다. 지연이 4KB를 넘길 만큼 길어지는 경우는 현실적이지 않다고 보고 유실로 분류하지 않았다.
  - 미확정(인식 중) 하이라이트 필터가 갱신 빈도를 낮출 수 있다. 실사이트에서 확정 텍스트가 문장 단위로만 바뀐다면 이 문제는 거의 드러나지 않는다. 이 부분은 확인하지 못했다.
- **호출/영향 범위:** `_apply_structured_preview_payload`의 fallback 분기(580-608행) 전체. 저장·export·runtime archive가 모두 이 엔트리 타임스탬프를 쓴다.
- **권장 수정 방향:** 미commit 구간의 최초 관측 시각을 따로 보관하고, 그로부터 일정 시간(예: 2~3초)이 지나면 raw가 바뀌는 중이어도 commit한다. 엔트리 시작 시각도 최초 관측 시각을 쓰는 편이 SRT 정확도에 맞다. ISSUE-001과 같이 `parity/` 계약을 먼저 고친다.
- **필요한 회귀 테스트:** 200ms 간격으로 raw가 계속 바뀌는 입력을 5초 주입 → 상한 시간 안에 엔트리가 1개 이상 생기고, 첫 엔트리 타임스탬프가 최초 관측 시각 + 상한 이내일 것. 400ms 정지 시 즉시 commit되는 기존 동작은 유지.

### [ISSUE-003] 시간 역순 엔트리에서 타임스탬프 블록과 SRT/VTT 큐가 망가진다

- **위치:** `core/timestamp_blocks.py` `starts_new_block`(57-64), `iter_display_rows`; `core/export_text.py` `format_cue_timestamp_from_seconds`; `persistence_exports_text.py` `_save_srt`/`_save_vtt`
- **우선순위:** Low
- **신뢰도:** Confirmed
- **문제:** 블록 경계는 `timestamp - block_start >= interval`만 본다. 뒤 엔트리의 시각이 블록 시작보다 이르면 차이가 음수라 새 블록이 영영 시작되지 않는다. SRT/VTT는 첫 큐 기준 상대 시각을 쓰고 음수를 0으로 clamp하므로, 역순 엔트리의 큐는 `00:00:00,000 --> 00:00:00,000`이 된다.
- **발생 조건:** 세션 병합에서 `시간순 정렬`을 끄고 더 이른 시각의 세션을 뒤에 붙인 경우. 수집 중 시스템 시계가 뒤로 조정된 경우도 같은 모양이 된다.
- **영향:** 자동 줄넘김 정리 ON이면 뒤 세션 전체가 타임스탬프 없는 한 문단으로 화면·TXT/DOCX/HWPX/HWP/RTF·클립보드에 나온다. OFF면 뒤 세션에 타임스탬프가 하나도 찍히지 않는다. SRT/VTT는 0초 길이 큐가 줄줄이 생긴다. `SubtitleEntry`·JSON·DB 데이터는 그대로이므로 정렬해서 다시 병합하면 복구된다.
- **근거:** 프로브 C. 오늘 14시 3건 뒤에 전날 10시 50건을 붙였다.
  ```text
  merge ON lines: 3            # 53건이 3줄, 마지막 줄에 전날 50건이 모두 붙음
  merge OFF timestamped lines: 3 of 53
  SRT cue for out-of-order entry: 00:00:00,000 --> 00:00:00,000
  ```
- **반증 확인:** 병합 다이얼로그의 `시간순 정렬` 기본값은 켜짐이라 기본 사용에서는 발생하지 않는다. 일반 수집·세션 로드는 시각이 단조 증가한다. 그래서 Low로 둔다.
- **호출/영향 범위:** `_iter_display_session_rows` → `iter_display_rows`를 쓰는 화면 렌더와 텍스트 계열 export 전부, `_iter_full_session_timed_rows`를 쓰는 SRT/VTT.
- **권장 수정 방향:** `starts_new_block`에서 음수 차이(시각 역행)도 새 블록으로 본다. SRT/VTT는 큐 시작이 직전 큐보다 이르면 직전 큐 끝에 이어 붙이거나, 저장 전에 역순을 감지해 경고한다.
- **필요한 회귀 테스트:** `[14:00, 14:01, 전날 10:00, 전날 10:01]` 입력 → merge ON에서 3개 이상 블록, 전날 블록에 타임스탬프 표기. SRT는 모든 큐가 `end > start`.

## 5. Potential Functional Gaps

- **Confirmed Gap — 업데이트 helper 사본이 지워지지 않는다.** `launch_update_helper`(`core/update_installer.py` 388행)가 실행 중인 EXE 전체를 `update-helper-<uuid>.exe`로 staging 폴더에 복사하는데, 이 파일을 지우는 코드가 저장소에 없다(`update-helper` 문자열은 생성 지점 한 곳뿐). 업데이트할 때마다 EXE 크기만큼 `updates/`(portable은 `.updates/`)에 쌓인다. `.bak` 백업은 `cleanup_update_backups`로 정리된다. 기능 오류는 아니고 디스크 누적이다. 다음 시작 시 `_notify_pending_update_result`에서 오래된 helper를 지우면 된다.
- **Likely Gap — 유실·지연에 대한 진단 신호.** ISSUE-001의 후보 폐기와 ISSUE-002의 장기 대기는 로그·`CaptureQualityState` 어디에도 기록되지 않는다. 수정과 별개로 "reset으로 폐기된 후보 수", "최대 commit 지연"을 품질 진단에 넣으면 실사이트 빈도를 측정할 수 있다.
- **추정 — stable row와 unstable row가 한 이벤트에 섞이는 경우.** `_apply_structured_preview_payload`는 stable row가 하나라도 있으면 그것만 commit하고 대기 중인 fallback 후보를 지운다(502행). 같은 화면에 고정 키 row와 일반 row가 함께 뜨는 DOM이 실제로 있다면 일반 row 텍스트가 늦게 들어오거나 빠질 수 있다. 실제 DOM에서 그런 조합이 나오는지 확인하지 못했으므로 버그로 분류하지 않는다.
- **추정 — 본회의 raw 무제한.** probe JS는 본회의(`xcode=10`)에서 container 텍스트를 자르지 않고 전부 반환한다(`preserveFullRaw`). 사이트가 장시간 회의의 자막을 DOM에 계속 쌓아 둔다면 0.2초마다 큰 문자열을 전송·정규화하게 된다. 사이트가 DOM을 얼마나 유지하는지 모르므로 성능 문제로 단정하지 않는다.
- **추정 — 실사이트 E2E 회귀.** 수집 계약은 `parity/` 벡터와 fake DOM 테스트로 고정되어 있지만, 실제 생중계에서 commit 지연·reset 타이밍을 재는 opt-in 테스트는 없다(`RUN_LIVE_SMOKE`는 `live_list` 스키마만 본다).

## 6. Documentation Mismatches

| 문서 | 실제 |
|---|---|
| README 61행 "AI 자막을 **딜레이 없이** 즉시 캡처", CLAUDE §1 "Delay-free", §4.2 흐름도 "SubtitleEntry 즉시 반영" | v16.14.16부터 일반 자막은 같은 raw 2회 관측 또는 400ms 유지 뒤에 commit된다(README v16.14.16 변경 이력에는 맞게 적혀 있다). 상단 소개와 CLAUDE §4.2 흐름도가 옛 설명이다 |
| CLAUDE §6 "의존성 전면 업그레이드" 메모의 `PyQt6 6.11.0`, 여러 메모의 `PyQt6.QtNetwork` | 현재 바인딩은 PySide6 6.12.0(`requirements-dev.txt`, 518a226에서 통일). 과거 메모라 해도 "현재 기준" 문서 안에 PyQt6 핀이 남아 있다 |
| README 9행 배지 alt 텍스트 `PyQt6` | 배지 내용은 PySide6 |
| README 308행 빌드 예시 `dist/국회의사중계자막추출기 v16.14.11.exe` | 현재 버전은 16.14.16 |
| CLAUDE §8.5·2026-10-13 메모 "검증은 프로젝트 루트 `.venv` 격리 환경이 기준" | 작업 트리에 `.venv`가 없다(로컬 사정일 수 있음). 이번 테스트는 전역 Python으로 돌렸다 |
| 감사 지시의 `AGENTS.md` | 저장소에 없다. `CLAUDE.md`·`GEMINI.md`가 그 역할을 한다 |

저장소 3모드, 저장 형식, 재연결 정책, 업데이트 rename 스왑 설명은 구현과 일치했다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. **ISSUE-001:** reset 적용 전에 대기 중인 fallback 후보를 commit한다. `parity/capture-contract.json` → 데스크톱·확장 구현 → `PIPELINE_LOCK.md` 이력 순서로 반영한다.
2. **ISSUE-002:** fallback 후보에 최대 대기 상한과 "최초 관측 시각" 타임스탬프를 넣는다. 같은 parity 변경에 묶는다.

### Phase 2 — Stability

- **ISSUE-003:** 시각 역행을 블록 경계로 처리하고 SRT/VTT 큐의 단조성을 보장한다.
- 업데이트 helper 사본 정리(다음 시작 시 삭제).
- 후보 폐기 수·commit 지연을 `CaptureQualityState`에 기록한다.
- README·CLAUDE의 "즉시 반영" 설명, PyQt6 잔재, 빌드 예시 버전을 정리한다.

### Phase 3 — Structural

- fallback 후보 상태(dict + 토큰 + 타이머)를 `core/`의 순수 클래스로 옮겨 `parity/` 벡터로 직접 검증할 수 있게 한다. 지금은 `MainWindow` mixin 안에 있어 타이머를 가짜로 바꿔야 테스트된다.
- 실제 생중계에서 commit 지연·reset 타이밍을 수집하는 opt-in 측정 스크립트를 둔다(`RUN_LIVE_SMOKE` 확장). "추정" 항목 두 개를 확정하거나 지울 근거가 된다.

## 8. Test Recommendations

**Unit**
- `iter_display_rows`: 시각이 역행하는 행 → 새 블록 시작, 타임스탬프 표기.
- `format_srt_relative`/큐 생성: 역순 엔트리 포함 입력 → 모든 큐 `end > start`, 큐 시작 단조 비감소.
- fallback 후보(순수 함수로 분리 후): raw 변경 N회 + 경과 시간 → commit 여부 표를 `parity/pipeline-vectors.json`에 추가.

**Integration** (`MainWindow.__new__` + 가짜 타이머, `tests/test_chrome_parity_20261022.py` 방식)
- 후보 대기 중 reset 예약 → 150ms 뒤 새 payload → 엔트리 2개, 직전 발언 전체 보존(ISSUE-001).
- 후보 대기 중 grace 타이머 만료 → 후보가 먼저 commit된 뒤 reset.
- 200ms 간격 raw 변경 5초 → 상한 안에 commit, 첫 엔트리 타임스탬프 ≤ 최초 관측 + 상한(ISSUE-002).
- 후보 대기 중 `_stop` → 마지막 텍스트가 엔트리에 포함(현재도 통과해야 하는 기존 동작 고정).

**End-to-End**
- fake DOM 페이지(로컬 HTML)에서 "갱신 → 200ms 뒤 clear → 100ms 뒤 새 발언" 스크립트를 돌려 저장된 세션 JSON에 직전 발언의 마지막 어절이 있는지 확인.
- 정렬 OFF로 두 세션 병합 → TXT·SRT 저장 → 뒤 세션에 타임스탬프가 있고 SRT 큐가 유효.

**Concurrency**
- preview·reset·keepalive가 한 번의 queue drain(8ms/50건 예산) 안에 섞여 들어올 때 처리 순서와 후보 상태. reset이 preview보다 뒤에 put되었는데 coalescing으로 순서가 바뀌지 않는지.

**Regression**
- 업데이트 적용 성공 후 다음 시작 → staging 폴더에 `update-helper-*.exe`가 남지 않을 것.
- stable row commit 직후 같은 텍스트가 fallback raw로 다시 와도 중복 엔트리가 생기지 않을 것(현재 동작 고정).

**Platform-specific**
- Windows frozen EXE: 업데이트 2회 연속 적용 후 `updates/` 용량. portable 모드의 `.updates/`도 같은 확인.
- 핀 환경(Selenium 4.51.0, pytest 9.1.1)에서 전체 테스트 1회. 이번 감사는 4.52.0/9.2.0에서 돌렸다.

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | **Acceptable** | 핵심 흐름은 동작하고 테스트로 고정되어 있다. 새 commit 게이트에 reset 경계 유실(ISSUE-001)이 있다 |
| Runtime Stability | **Good** | 재연결, terminal 메시지 보존, 종료 drain, 업데이트 rollback이 갖춰져 있고 이번에 새 결함을 찾지 못했다 |
| Data Integrity | **Acceptable** | 저장된 데이터의 손상 경로는 없다. 수집 단계에서 마지막 어절 유실과 타임스탬프 지연이 가능하다 |
| Error Resilience | **Good** | 파일·DB·네트워크 실패가 status/toast/결과 타입으로 전달된다. 다만 ISSUE-001·002는 조용히 일어난다 |
| Cross-platform Robustness | **Acceptable** | Windows 전용 제품으로 설계되어 있고 그 범위에서는 경로·인코딩·프로세스 대기가 처리되어 있다. Linux/macOS는 검증하지 않았다 |
| Test Confidence | **Acceptable** | 646건이 통과하고 parity 벡터가 있다. reset과 후보가 겹치는 경우, 연속 변경, 실사이트 타이밍은 테스트에 없다 |

**먼저 수정할 3개**

1. **ISSUE-001** — reset 적용 전에 대기 중인 fallback 후보를 commit한다.
2. **ISSUE-002** — fallback commit에 최대 대기 상한을 두고 엔트리 시각을 최초 관측 시각으로 잡는다.
3. **ISSUE-003** — 시각 역행 시 타임스탬프 블록과 SRT/VTT 큐가 깨지지 않게 한다.
