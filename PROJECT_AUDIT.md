# Project Audit

**최종 상태:** [PROJECT_AUDIT_FINAL.md](PROJECT_AUDIT_FINAL.md)에 마지막 복구 경로 감사와 최종 검증을 기록했다. 아래 실행 수치는 각 감사 시점의 기록이다.

감사일: **2026-11-03 (Asia/Seoul)** · 대상: **v16.14.16 / main / c607d15**

**추가 범위 감사·수정:** [PROJECT_AUDIT_ADDITIONAL.md](PROJECT_AUDIT_ADDITIONAL.md). 검색·UTF-16 선택, HWP, 프리셋, 병합, stale 리플로우에서 확인한 ISSUE-006–012를 수정했다. 최신 전체 검증은 **701 passed / 2 skipped**, pyright **201 files / 0 errors / 0 warnings**, Windows ARM64 frozen 창 생성 smoke **exit 0**다. 아래 첫 후속 구현의 685개 결과는 그 이전 검증 기록이다.

## 후속 구현 — 2026-11-03

사용자의 후속 수정 요청에 따라 main 작업트리에서 아래 개선을 구현했다. **아래 §1–9는 c607d15에 대한 원 감사 기록이며, 수정 후 현재의 미해결 이슈 목록이 아니다.** 배포·푸시·버전 증가는 하지 않았다.

| 항목 | 현재 상태 | 구현 및 회귀 |
|---|---|---|
| ISSUE-001 | 수정·검증 | `PipelineResult.previous_text`와 `_publish_capture_commit()`으로 실제 stable/fallback commit의 TXT·알림 연결. append/확장/정정·중복 억제·쓰기 실패 검증 |
| ISSUE-002 | 수정·검증 | missing/path/skipped/count/digest 오류를 일반 reader도 실패로 전달. stat 기반 cache 재검증, atomic replace 전 출력 count 확인. 기존 JSON/SRT·hydrate 상태 보존 검증 |
| ISSUE-003 | 수정·검증 | raw+row identity/text/speaker/frame/selector/source mode signature. 새 stable identity는 별도 발언 baseline, 기존 row 수정/초기 handoff는 각각 ledger/global snapshot baseline. 같은 `네`의 다른 화자 보존 검증 |
| ISSUE-004 | 수정·검증 | bounded byte reader·변환 전 entry budget·읽기/변환 진행/취소. 완료 큐 수신 전 취소와 종료 취소도 기존 세션 보존 |
| ISSUE-005 | 수정·검증 | staged cleanup을 smoke/rollback 뒤 best-effort로 이동. 삭제 PermissionError의 성공/rollback 분기 검증 |
| 일반 JSON progress/cancel gap | 구현 | 실제 Qt progress dialog, chunk/entry 사이 취소 확인. 표준 `json.loads` 실행 중에는 중단하지 않고 전후 확인하는 한계는 문서화 |
| 업데이트 중단 후 복구 진입점 | 구현 | helper 옆 `recover-update-helper-*.cmd`를 교체 전에 생성. `--recover-update`로 target 부재 시에만 backup 복원. Unicode·batch 문자·CLI·기존 EXE 보존 회귀 |
| DB 동시 operation ID | 보강 | 서로 다른 DatabaseManager의 선조회 race를 unique constraint가 결정한 뒤 loser는 rollback/재조회하여 동일 저장 ID 반환. barrier 동시 실행 회귀 |
| 실제 사용자 경로 검증 부족 | 보강 | 실제 QApplication·Qt timer·오프라인 Chrome DOM→worker→JSON/SQLite→SRT→재로드. capture 중 archive manifest 전진/저장 snapshot 동시성 회귀 |
| CI·문서·플랫폼 범위 | 반영 | 새 회귀를 CI/release gate에 포함. README/CLAUDE/PIPELINE_LOCK/릴리스 체크리스트 정합화. WebEngine 없는 환경은 DOM fixture만 skip, 명시적 Chrome fixture 선택 가능 |
| 검증 저장소 격리 | 보강 | `--smoke-storage-dir`가 파일·DB뿐 아니라 QSettings도 임시 INI로 격리 |

### 수정 후 검증

- `.venv`에 프로젝트 핀 `PySide6==6.12.0`을 설치하여 AST 추출 없이 실제 GUI 경로로 검증했다.
- 임시 소스 복사본에서 `KACC_TEST_BROWSER=chrome`, `QT_QPA_PLATFORM=offscreen`, `PYTHONUTF8=1`로 전체 pytest: **685 passed / 2 skipped**. 실제 Chrome 오프라인 DOM 검증도 이 결과에 포함된다.
- 별도 `RUN_LIVE_SMOKE=1`의 실제 국회 live-list 계약: **1 passed**. 이것을 실제 생중계 자막 Selenium E2E로 간주하지 않는다.
- pyright: **200 files / 0 errors / 0 warnings**.
- Windows ARM64 PyInstaller EXE 빌드 성공. 임시 저장소의 frozen `--smoke --smoke-instantiate-window`: **exit 0**, resource/import/HWPX/preflight/창 생성 모두 성공.
- frozen `--recover-update --update-no-relaunch`: **exit 0 / rolled_back**, 임시 백업 복원 확인.
- 동일 볼륨의 임시 EXE 복사본을 실제 frozen helper로 교체: **exit 0 / applied**, 부모 종료 대기→hash/size→rename→새 EXE smoke→backup/staged 상태 확인. `LOCALAPPDATA`도 임시 디렉터리로 격리했다.
- `git diff --check` 통과. 사용자 세션·DB 파일을 대상으로 시험하지 않았다. 임시 로그·빌드 자료는 `%LOCALAPPDATA%/Temp/kacc-remediation-zqd1fywk/`에 있다.

### 남은 외부 검증

실제 중계 중 reconnect/DOM 변경·장시간 운용, 서로 다른 **물리 볼륨**, 실제 공유 잠금/전원 차단 중 복구 launcher, 한컴오피스 COM 출력, Windows x64 frozen 및 macOS/Linux 실기기는 별도 확인이 필요하다. 서명된 업데이트의 공개 배포는 수행하지 않았다. source 테스트의 예외 주입·동일 볼륨 frozen 시험으로 이 검증을 대체했다고 주장하지 않는다.

현재 코드 수준에서 감사의 5개 확정 결함은 수정되었고, 알려진 누락/오류 경계에 대한 회귀가 통과했다. 배포 전에는 위 실기기·실중계 항목을 릴리스 체크리스트로 확인한다. 원 감사의 High Risk 판정은 수정 전 상태에 대한 기록으로 보존한다.

---

기능 구현·런타임 안정성 중심의 일회 감사다. 기존 보고서를 감사 시점 코드 기준으로 갱신했다. **원 감사 당시** 애플리케이션 코드·테스트·설정은 변경하지 않았다. 아래 Confirmed는 명시한 코드 경계에서 확인했다는 뜻이며, 실제 생중계나 배포 EXE에서 모든 현상을 재현했다는 뜻은 아니다.

## 1. Executive Summary

핵심 수집·편집·검색·내보내기·복구·업데이트 기능과 상당한 방어 장치가 구현되어 있다. 그러나 새 수집 파이프라인에서 기존 기능의 부수 효과가 빠졌고, 장시간 세션을 읽는 일반 경로와 복구 경로의 검증 수준이 다르다.

**전체 위험도: High Risk.** 다음 5개 결함을 확인했다. Critical로 판단할 근거는 발견하지 않았다.

| 순서 | 문제 | 우선순위 | 신뢰도 |
|---|---|---|---|
| 1 | dict preview의 실제 commit 경로가 실시간 TXT 기록·키워드 알림을 호출하지 않음 | High | Confirmed |
| 2 | 누락·변경된 runtime segment를 일반 저장/내보내기에서 검증하지 않아 불완전한 결과를 성공으로 저장 | High | Confirmed |
| 3 | 텍스트가 같은 새 row·화자 변경을 worker가 preview 발행 전에 제거 | High | Confirmed |
| 4 | 일반 세션 JSON 로드가 공통 entry 상한을 우회 | Medium | Confirmed |
| 5 | 업데이트 교체 후 staged 파일 삭제 실패가 smoke·rollback을 건너뜀 | Medium | Confirmed |

**데이터 누락·논리적 손상 가능성이 있다.** ISSUE-002는 이미 메모리에서 내려간 자막을 누락한 JSON/DB/export를 정상 결과로 취급할 수 있다. ISSUE-003은 수집 입력 자체를 놓치며, ISSUE-001은 실시간 저장 파일에 자막이 남지 않을 수 있다. 실제 사용자 데이터 유실이나 SQLite 파일의 물리적 손상을 관찰한 것은 아니다. DB transaction·FK·WAL·저장 operation ID와 파일 원자적 교체는 유효한 보호 장치다.

가장 먼저 실제 commit 경로의 실시간 저장·알림을 연결하고, runtime segment 읽기를 엄격하게 만들며, worker의 변경 판정을 구조화된 row 기준으로 수정해야 한다.

## 2. Project Understanding

### 목적·실행·규칙

- 국회 의사중계 사이트의 AI 자막을 Selenium/Chrome으로 읽는 **PySide6 데스크톱 앱**이다. 직접 음성 인식하는 제품은 아니다.
- 소스 실행: `python "국회의사중계 자막.py"`. Windows가 주 대상이며 HWP COM 출력은 Windows/한컴오피스 전용이다. README는 Python 3.10+를 안내한다.
- entrypoint `main()`은 일반 GUI, `--smoke`, `--smoke-storage-preflight`, `--apply-update`를 분기한다. `--smoke-instantiate-window`는 생성자까지 확인하는 선택 경로다.
- `README.md`, `CLAUDE.md`, `PIPELINE_LOCK.md`, 의존성·pytest·pyright 설정, PyInstaller spec, CI/release workflow를 확인했다. 루트에 물리적 `AGENTS.md`는 없으며 사용자 제공 AGENTS 지침을 적용했다. main에서 작업했고 별도 브랜치를 만들지 않았다.
- `PIPELINE_LOCK.md`의 글로벌 히스토리/suffix 의미론 고정 규칙을 확인했다. 이번 감사는 해당 알고리즘을 변경하지 않는다.

### 핵심 모듈·공유 상태

| 영역 | 구현 | 핵심 상태/보호 |
|---|---|---|
| 조립·시작·중지·종료 | `ui/main_window.py`, `runtime_lifecycle_*.py` | stop event, background thread registry, dirty session 보호 |
| 브라우저 수집 | `capture_browser.py`, `capture_dom.py`, `capture_observer.py`, `capture_live.py` | driver identity/lock, selector/frame 탐색, Observer+probe, 재연결 |
| 정합·commit | `core/live_capture_impl/`, `core/subtitle_pipeline.py`, `pipeline_state.py` | ledger row key, `capture_state.entries`, confirmed history, tail 변경 |
| 큐·표시·검색·편집 | `pipeline_queue.py`, `pipeline_messages.py`, `pipeline_stream.py`, `view_*.py` | run ID, preview sequence, bounded queue, immutable snapshot, revision |
| 세션·복구 | `persistence_session_*.py`, `persistence_runtime_*.py` | JSON, segment/manifest/tail checkpoint, digest, owner lease, resource budget |
| DB | `core/database_impl/`, `database_worker.py` | thread별 SQLite 연결, RLock, transaction, FK, FTS fallback, operation ID |
| 내보내기 | `persistence_exports_*.py`, `core/export_text.py`, `core/hwpx_export.py` | TXT/SRT/VTT/DOCX/HWPX/HWP/RTF, 원자적 파일 교체 |
| 업데이트 | `core/update_manifest.py`, `core/update_installer.py`, `scripts/apply_update.py` | Ed25519, HTTPS, hash/size, 부모 종료 대기, rename 교체, smoke/rollback |

`self.subtitles`는 `capture_state.entries`의 alias다. UI가 큐에서 수집 결과를 적용하며, 백그라운드 저장은 clone한 active tail과 runtime manifest context를 사용한다. 장시간 수집은 2,000개 초과 시 오래된 prefix를 segment로 내리고 1,000개 tail을 유지하도록 설정되어 있다.

### 저장·외부 의존성

- 개발 실행은 repo root, portable은 EXE 옆 `portable.flag`가 있는 디렉터리, 일반 frozen 실행은 `%LOCALAPPDATA%/AssemblySubtitle/Extractor`를 쓴다.
- SQLite `subtitle_history.db`, 세션/백업 JSON, runtime `segment_*.json`·`manifest.json`·세대별 tail checkpoint, `session_recovery.json`, 실시간 TXT를 저장한다. 일반 설정은 QSettings, portable 설정은 INI다.
- DB는 매 자막마다 자동 저장하는 방식이 아니라 세션 저장 시 JSON과 함께 저장하는 경로다. JSON 성공 후 DB 실패는 별도 경고로 처리한다.
- 외부 의존성: PySide6, Selenium/Chrome/Selenium Manager, cryptography, 선택적 python-docx·pywin32/한컴오피스. 외부 서비스는 국회 player/live-list와 GitHub 업데이트 채널이다.
- `requirements-dev.txt`가 단일 의존성 핀 파일이다. CI는 Windows/Python 3.15, release workflow는 Windows/Python 3.12를 사용한다.

### 사용자 실행 흐름

```text
main → 저장소 preflight → QApplication/MainWindow → 설정·DB·복구 후보 → event loop

F5/시작 → _start → URL/selector 검증 + dirty/교체 확인
 → _begin_extraction_run → runtime archive 생성 + worker
 → Chrome/session → live URL 보완 → AI 자막 활성화 → Observer/structured probe
 → worker preview(dict) → run ID/sequence 큐 → _handle_message
 → _apply_structured_preview_payload
 → stable row: reconcile_live_capture → commit_live_row
 → unstable/container: 안정 관측 timer/keepalive → _commit_fallback_candidate → apply_preview
 → capture_state.entries 변경 → revision·통계·렌더·runtime segment
 [이 실제 흐름에서 실시간 TXT·키워드 알림 연결 누락: ISSUE-001]

중지 → stop_event → pending preview drain → finalize → worker 대기/driver 정리 → UI 복원

세션 저장 → tail clone + revision/runtime context → background JSON atomic write
 → recovery pointer → DB worker → save_session transaction/operation ID
 → control queue → revision 일치 시 dirty 해제/후속 액션

일반 JSON 불러오기 → 크기 stat → json.load → SubtitleEntry.from_dict → UI 세션 교체
runtime 복구 → manifest/budget/path/fingerprint 검증 → strict 실패 또는 salvage 경고
DB 불러오기 → metadata + fetchmany → budget/progress/cancel → UI 적용

export → tail clone + manifest context → segment/tail 순회 → 형식 변환 → atomic replace → toast
검색 → archived segment + active tail → match index → 해당 window 렌더/선택
편집·삭제·병합 → 필요 시 hydrate → 사용자 작업 → dirty revision

업데이트 → 서명/만료/버전 검증 → 다운로드 hash/size → 사용자 승인
 → helper → 부모 종료 대기 → 같은 볼륨 staging → rename 교체 → smoke/rollback → 결과/재시작
```

## 3. Audit Coverage & Limitations

### 실제 확인 범위

CodeGraph MCP를 사용해 entrypoint 관련 경로, 수집/큐/ledger/pipeline, 저장/DB/export/hydrate, 복구 checkpoint, 시작/중지/종료, URL policy·파일 I/O·업데이트를 조사했다. 특히 다음 호출 관계와 영향 범위를 확인했다.

- `_start → _begin_extraction_run → _extraction_worker` 및 브라우저 초기화/재연결.
- `preview → _handle_message/_process_preview_queue_message → _apply_structured_preview_payload → reconcile_live_capture/commit_live_row`.
- `_commit_fallback_candidate → apply_preview → _apply_capture_pipeline_refresh`.
- `_write_session_snapshot → _iter_full_session_entries → _load_runtime_segment_entries`; 동일 reader의 export·검색·hydrate 사용.
- `_run_after_full_session_hydrated`의 편집·복사·병합 caller, segment flush와 tail/manifest 저장, recovery strict/salvage의 별도 검증.
- `save_session`의 operation ID 조회·unique index·transaction/rollback, `delete_session`의 lineage latest 복원.
- `apply_update.main → apply_staged_update → copy/hash/rename/smoke/rollback`.

CodeGraph가 한국어 entrypoint 파일을 찾지 못한 경우 직접 읽었다. 응답에서 생략된 긴 함수의 후반부, 비색인 설정·문서, 특정 보호 장치의 전체 호출 여부만 직접 열람/rg로 보완했다. AST/타입용 Protocol·호환 shim·테스트 fake를 운영 구현으로 오인하지 않았다. 그래프에 관련 없는 `main` 후보 등이 섞이는 한계가 있어 보고서에는 소스로 확인한 관계만 기록했다.

### 실행한 검증

Git 추적 파일을 별도 임시 디렉터리로 복사하여 **현재 repo의 `.venv/Scripts/python.exe`(Python 3.15.1 ARM64)**로 실행했다. 의존성 설치는 하지 않았다.

| 실행 | 실제 결과 |
|---|---|
| `python -m pytest -q --tb=short` | PySide6 미설치로 collection 중단: 20 errors / 14 skipped. 테스트 본문 전체 실행 못함 |
| `python -m pytest -q --tb=line --continue-on-collection-errors` | **287 passed / 6 failed / 24 skipped / 20 errors**, 13.69초 |
| `python -m pyright --outputjson` | **199 files / 0 errors / 0 warnings** |
| 임시 `audit-repro.py` | 아래 6개 assertion 시나리오 통과 |

pytest의 6 failures와 20 collection errors는 출력상 모두 PySide6 import 실패 또는 그에 따른 smoke 실패였다. 이를 제품 결함 26개로 계산하지 않았다. skipped에는 의존성 부족에 따른 모듈 skip 등이 포함되며, 실중계 검증을 통과했다는 의미가 아니다. 정적 분석은 저장소 stub을 사용하므로 **pyright 성공이 실제 Qt import/GUI 실행을 보장하지 않는다.**

재현은 다음 결과를 확인했다.

```text
MISSING_SEGMENT: reported_count=2, actual_count=1, texts=['tail']
CHANGED_SEGMENT: ['changed', 'tail']  # 잘못된 digest를 가진 segment도 일반 reader에서 사용
JSON_BUDGET_BYPASS: limit=1, loaded=2, session_load_done
UPDATE_CLEANUP_FAILURE: target='new', backup='old', smoke_calls=0
IDENTICAL_TEXT_NEW_ROW: probe_count=2, preview_count=1, emitted_keys=['row1']
STRUCTURED_SIDE_EFFECTS: committed_entries=1, realtime_write_calls=0, alert_calls=0
```

Qt를 import할 수 없어 GUI 관련 재현은 **원본 메서드 AST를 수정 없이 추출·실행**했다. 저장 reader/JSON writer와 모델, structured ledger·commit은 실제 코어 구현을 사용했다. GUI 표시·timer·브라우저 입력 등은 최소 host stub으로 대체했다. worker 재현은 결정적 clock·두 probe·종료 event를 사용했고, 업데이트는 실제 함수에 staged `unlink`만 PermissionError로 주입했다. AST 추출 검증은 전체 MainWindow 통합 테스트가 아니므로 이 한계를 각 결과 해석에 적용해야 한다.

임시 검증 자료: `%LOCALAPPDATA%/Temp/kacc-functional-audit-6uof99bk/`의 `audit-repro.py`, `audit-pytest.log`, `audit-pyright.json`. 저장소에 테스트 파일을 추가하지 않았다.

### 미확인 환경·한계

- PySide6를 갖춘 전체 pytest/실제 GUI 생성·조작, 실제 Chrome/생중계 DOM·iframe·네트워크 장애 E2E는 실행하지 못했다.
- 한컴오피스 COM, frozen EXE 재빌드/실행, 실행 중 Windows EXE 잠금, 실제 두 물리 볼륨 업데이트, macOS/Linux 실기기는 확인하지 못했다.
- 사용자 DB·기존 session/backup 내용, 실제 credential은 읽지 않았다. 대규모 OOM·전원 차단·실제 프로세스 강제 종료 실험은 하지 않았다.
- 기존 보고서의 Fixed 표기는 현행 버그의 근거로 재사용하지 않았다. 이번 평가는 현재 소스와 이번 실행 결과에 한정한다. 전수 함수 감사나 모든 race의 부재를 보증하지 않는다.

## 4. High-Risk Issues

확정된 High 3개와 안정성에 직접 영향을 주는 Medium 2개를 기록한다. Speculative 항목은 이 절에 넣지 않았다.

### [ISSUE-001] 실제 dict preview commit에서 실시간 저장·키워드 알림이 실행되지 않음

- **위치:** `ui/main_window_impl/pipeline_messages.py:260`, `pipeline_state.py:167`, `pipeline_state.py:231`, `pipeline_state.py:449`; 비교 경로 `pipeline_stream.py:143`·`:153`.
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** worker는 dict preview를 발행한다. 해당 handler는 structured/fallback core에 직접 commit한 뒤 통계·렌더·dirty·복구만 반영한다. 실시간 파일 기록과 키워드 검사는 기존 `_append_text_to_subtitles_shared()`에만 연결되어 있어 이 경로에서 호출되지 않는다.
- **발생 조건:** 실시간 저장 또는 알림 키워드를 활성화한 상태에서 현재 worker의 dict preview를 수신한다. stable row와 안정 관측 fallback 모두 같은 refresh 경로를 쓴다.
- **영향:** 화면/세션에는 자막이 존재하지만 실시간 TXT에는 기록되지 않고 감지 알림도 오지 않을 수 있다. 장시간 무인 수집·키워드 모니터링의 명시된 기능이 실패한다. JSON/DB 수동 저장 전체가 실패한다는 뜻은 아니다.
- **근거:** 실제 ledger/`commit_live_row`와 원본 UI commit/refresh 메서드로 stable row 1개가 entries에 추가됨을 확인했지만 realtime writer·alert spy 호출은 모두 0이었다. 전체 호출 검색에서도 두 기능 호출은 기존 stream helper에만 있었다. fallback `_commit_fallback_candidate()`도 해당 helper를 호출하지 않는다.
- **반증 확인:** 상위 `_handle_message()`는 dict preview 처리 직후 return한다. preview drain도 직접 structured handler를 호출한다. timer/keepalive는 fallback commit 또는 timing을 갱신할 뿐 파일 기록·알림을 보완하지 않는다. 코어 모듈은 GUI 파일/알림을 소유하지 않으므로 framework가 자동 수행하지 않는다. 레거시 string/segments 경로에 기능이 남아 있다는 점은 확인했으나 현재 dict 운영 경로를 보호하지 못한다.
- **호출/영향 범위:** `_extraction_worker → preview → _handle_message → _apply_structured_preview_payload → commit_live_row` 또는 `_commit_fallback_candidate → apply_preview → _apply_capture_pipeline_refresh`. 실시간 TXT와 alert 기능에 영향. CodeGraph가 확인한 `_write_realtime_line`·`_check_keyword_alert` caller는 stream helper 계열이다.
- **권장 수정 방향:** 실제 commit delta 처리에 실시간 출력·키워드 검사를 연결한다. append와 기존 row 보정을 구분하여 중복 알림/전체 문장 반복 기록 정책을 명시한다. 파일 I/O는 subtitle lock 밖에 둔다.
- **필요한 회귀 테스트:** realtime ON/키워드 `예산` 상태에서 stable dict row와 unstable fallback을 각각 commit하면 TXT에 내용이 있고 알림이 1회 발생해야 한다. 동일 snapshot·keepalive 재수신으로 같은 문장 전체가 중복 기록되지 않아야 한다. write PermissionError는 run 저장 중단 경고로 표시되어야 한다.

### [ISSUE-002] 일반 runtime reader가 누락·손상 segment를 성공 결과로 흘려보냄

- **위치:** `ui/main_window_impl/persistence_runtime_segments.py:327`, `:384`, `:463`; `persistence_runtime_readers.py:31`; `persistence_session_save.py:118`.
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** `_load_runtime_segment_entries()`는 파일이 없으면 빈 리스트를 반환한다. 일반 segment reader는 JSON을 역직렬화할 뿐 manifest/file의 count·entry ID·digest를 대조하지 않는다. 손상 항목 skipped 수도 호출자에 전달하지 않는다. 저장 count는 실제 출력 수가 아닌 manifest count+tail로 계산한다.
- **발생 조건:** archive 이후 디스크 segment가 삭제·이동되거나, 읽을 수 있는 JSON 형태로 내용이 변경/일부 손상된다. 외부 정리·파일 조작·저장장치 문제 등이 조건이며 정상 무결 파일에서 항상 발생하는 결함은 아니다. 메모리 segment cache에 남아 있지 않은 경우가 특히 해당한다.
- **영향:** 과거 자막을 빠뜨리거나 변경된 자막을 JSON/DB/export로 전달하고 성공 처리할 수 있다. hydrate도 불완전한 리스트를 현재 세션으로 교체할 수 있다. 이후 저장본만 믿고 종료하면 누락분의 복구 가능성이 줄어든다.
- **근거:** manifest 1개+tail 1개, segment 파일 없음 조건에서 실제 atomic JSON writer가 tail 1개만 저장했지만 반환값 `saved_count=2`였다. 다음에는 잘못된 digest와 변경된 텍스트를 가진 유효 segment JSON을 reader가 그대로 반환했다.
- **반증 확인:** `_load_runtime_manifest_payload()`의 strict/salvage는 경로·fingerprint를 검사한다. 그러나 이미 실행 중인 세션의 저장/export/hydrate는 그 loader를 거치지 않는다. 원자적 writer는 예외가 발생해야 기존 파일을 보존하는데 빈 리스트 반환은 예외가 아니다. DB transaction도 입력 generator가 불완전하다는 것을 판별하지 못한다. path traversal 방어는 있으나 파일 완전성 검사를 대체하지 않는다.
- **호출/영향 범위:** CodeGraph: `_write_session_snapshot → _iter_full_session_entries → _load_runtime_segment_entries`. 같은 reader를 text/timed export·전체 snapshot·검색 window·hydrate가 사용한다. JSON·DB·문서 출력과 장시간 세션 편집에 영향.
- **권장 수정 방향:** 일반 읽기는 missing/불일치/skipped 발생 시 명시적으로 실패하게 한다. fingerprint 검증과 cache 정책을 통일하고, 부분 복구는 사용자가 선택한 salvage 경로로만 허용한다. 실제 직렬화 count를 검증한 뒤 저장 성공/dirty 해제를 판단한다.
- **필요한 회귀 테스트:** 정상 segment를 만든 뒤 삭제, text 변조, entry 일부 손상, 잘못된 count/digest를 각각 주입한다. 일반 저장/export/hydrate는 실패하고 기존 출력·현재 세션을 보존해야 한다. salvage만 경고와 누락 통계를 반환해야 한다. 캐시 hit/miss/eviction도 각각 검증한다.

### [ISSUE-003] compact 텍스트만 비교하여 새 row·화자 메타데이터 변경을 누락

- **위치:** `ui/main_window_impl/capture_browser.py:637` `_extraction_worker()`의 preview/keepalive 분기; `pipeline_state.py:419`.
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** probe의 `text_compact`가 바뀔 때만 structured preview를 발행한다. row key·화자 channel/color·frame/selector 변경은 발행 조건에 없다. 같은 글자의 새 row는 텍스트-only keepalive로 대체되거나 아무 메시지도 발행하지 않는다.
- **발생 조건:** 중간 empty/reset을 관측하지 않은 상태에서 서로 다른 stable row 또는 화자가 같은 텍스트를 말한다. 예: `row1/primary: 네` 다음 `row2/secondary: 네`. DOM이 한 번에 교체되거나 polling 사이에 전환하면 현실적으로 도달 가능하다. 화면 누적 문구 자체가 변하는 일반 추가는 해당하지 않는다.
- **영향:** 새 발언 또는 화자 변경이 ledger/pipeline에 전달되지 않는다. 다음 텍스트 변화 때 row가 사라져 있으면 영구 누락되고, 이후 나타나더라도 타이밍/화자 정보가 지연된다. 공백 보정만 있는 row 수정도 compact 비교 때문에 전달되지 않는다.
- **근거:** 원본 worker를 두 개의 위 probe로 실행해 정상 `finished.success=True`를 확인했다. probe 2회에 preview는 row1 1회만 발행됐다. 하위 `reconcile_live_capture()`는 새 key와 speaker 변경을 변경사항으로 처리할 수 있지만 입력을 받지 못한다.
- **반증 확인:** Observer text change는 그 자체를 structured preview로 보내지 않고 probe를 수행하게 한다. trusted reset을 관측하면 이전 compact가 비워져 보호되지만, 모든 row 교체가 clear/reset을 발생시킨다는 보장은 없다. keepalive에는 row identity가 없고 기존 entry timing/fallback 관측만 처리한다. run ID/sequence gap 복구는 애초 발행되지 않은 preview를 검출하지 못한다.
- **호출/영향 범위:** `_read_subtitle_probe_by_selectors → worker gate → _build_preview_payload_from_probe → queue → _apply_structured_preview_payload → reconcile_live_capture`. 수집 원본·speaker/timing 및 그 후 모든 저장 결과에 영향.
- **권장 수정 방향:** stable row의 key 순서·text·speaker 정보·frame/selector/source mode를 포함한 변경 signature를 사용한다. 완전히 같은 관측만 keepalive로 처리하고 텍스트 fallback 중복 제거 정책은 별도로 유지한다.
- **필요한 회귀 테스트:** raw 동일/row key 변경, key 동일/speaker 변경, frame 변경, 공백 보정은 preview를 발행해야 한다. 모든 구조·텍스트가 같은 반복 probe는 중복 commit 없이 keepalive만 발생해야 한다. Observer ON/OFF를 모두 검증한다.

### [ISSUE-004] 일반 JSON 로드가 공통 entry budget을 적용하지 않음

- **위치:** `ui/main_window_impl/persistence_session_load.py:35`, `:70`, `:108`, `:169`; `core/config_impl/app_config.py:103`.
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** 일반 JSON 경로는 시작 전 100 MiB file stat만 검사하고 `json.load()` 후 전체 항목을 `SubtitleEntry`로 변환한다. `SESSION_RESOURCE_MAX_ENTRIES=150,000`이나 ResourceBudget을 적용하지 않는다.
- **발생 조건:** byte 상한 이내이면서 entry 상한을 초과하는 세션 파일을 사용자가 불러온다. 작은 자막 항목 다수를 가진 파일이면 가능하다.
- **영향:** runtime/DB에서 거절하는 크기의 세션이 일반 JSON에서는 로드된다. 대량 object 생성·전체 UI 적용으로 메모리 사용과 응답 지연이 커질 수 있다. 실제 OOM은 재현하지 않았으므로 강제 종료·데이터 유실을 확정하지 않는다.
- **근거:** 공통 상한을 1로 낮춘 격리 시험에서 유효 자막 2개의 작은 JSON을 원본 `_start_session_load_from_path()`로 처리했고 `session_load_done`에 2개가 전달됐다. 기본 150,000을 실제 초과하는 부하 실험 대신 동일 분기의 저비용 검증을 사용했다.
- **반증 확인:** runtime manifest loader와 DB/hydrate에 ResourceBudget이 존재하지만 일반 JSON 분기에서는 호출하지 않는다. `_deserialize_subtitles()`는 항목 유효성 검사와 skip만 수행하며 개수/취소 검사는 없다. 외부 try/except는 명시적 budget 거절을 대신하지 못한다. 파일 byte 제한은 있으므로 무제한 파일 읽기라고 표현하지 않는다.
- **호출/영향 범위:** `_load_session → _start_session_load_from_path → json.load → _deserialize_subtitles → session_load_done → _complete_loaded_session`. 일반 JSON·일반 backup 복구와 대량 UI 상태 교체에 영향.
- **권장 수정 방향:** 일반 JSON도 공통 byte/entry budget을 적용하고 entry 생성 전에 개수를 검사한다. 장기 작업에는 진행/취소를 제공하고 실패 시 기존 세션을 보존한다. stat 이후 실제 읽기 크기도 제한하는 bounded reader 사용을 검토한다.
- **필요한 회귀 테스트:** 상한 2에서 2개 성공/3개 실패, byte 상한 이내의 많은 작은 entry 거절, 취소 시 현재 세션 보존. runtime/DB/일반 JSON의 동일 상한 결과를 비교한다.

### [ISSUE-005] 업데이트 staged 삭제 오류가 smoke와 rollback 경계를 벗어남

- **위치:** `core/update_installer.py:345` `apply_staged_update()`; `scripts/apply_update.py:44`.
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** 새 EXE를 target에 설치한 직후 `staged_path.unlink()`를 smoke/rollback try 블록 바깥에서 실행한다. 삭제가 실패하면 교체 완료 상태에서 예외가 전파되어 smoke도 rollback도 실행하지 않는다.
- **발생 조건:** staged 파일은 읽기/복사 가능하지만 삭제가 거부된다. Windows 공유 잠금·읽기 전용 속성·일시적 보안 프로그램 잠금 등이 가능한 조건이다. 실제 보안 프로그램에서 재현한 것은 아니며 PermissionError를 주입했다.
- **영향:** helper는 failed/exit 1로 보고하지만 실제 target은 새 버전이고 old backup만 남는다. 새 EXE의 런타임 유효성을 검사하지 않았고 자동 재시작도 생략된다. 서명/hash 검증 우회나 임의 코드 설치를 확인한 결함은 아니다.
- **근거:** 임시 target=`old`, staged=`new`, 올바른 hash/size로 실제 `apply_staged_update()`를 호출하고 staged unlink만 거부했다. 결과 target=`new`, backup=`old`, smoke call=0, PermissionError였다.
- **반증 확인:** 앞선 rename 실패 처리와 이후 smoke 실패 rollback은 존재한다. 다만 삭제 줄이 그 사이의 보호되지 않은 위치다. script의 외부 catch는 실패 결과 JSON만 쓰며 복원하지 않는다. `missing_ok=True`는 파일 부재만 허용하며 PermissionError를 무시하지 않는다.
- **호출/영향 범위:** `main --apply-update → scripts.apply_update.main → apply_staged_update → staged unlink`. 사용자 승인 후 frozen 업데이트 설치·실패 상태 보고·재시작 경로에 영향.
- **권장 수정 방향:** smoke/rollback을 핵심 transaction 경계로 삼고 staged 정리는 성공 후 best-effort/retry로 처리한다. 정리 실패를 설치 실패로 혼동하지 않으며 실제 target 상태와 결과 상태를 일치시킨다.
- **필요한 회귀 테스트:** staged unlink PermissionError 상태에서도 smoke가 반드시 실행되어야 한다. smoke 실패라면 old로 복원하고 rolled_back을 기록한다. smoke 성공이면 target=new/applied를 유지하고 staged 정리만 경고/재시도해야 한다.

## 5. Potential Functional Gaps

- **Confirmed Gap — 실제 commit과 기능 검증의 연결 부족:** realtime writer·keyword alert 단위 회귀는 존재하지만 dict preview에서 출발한 정상 수집 흐름이 그 기능에 도달하는 검증이 부족하다. ISSUE-001처럼 개별 함수 통과와 제품 기능 동작이 분리될 수 있다.
- **Confirmed Gap — 일반 JSON 로드의 progress/cancel:** DB/hydrate에는 점진 처리/취소가 있지만 일반 JSON background load는 전체 parse/역직렬화 후 결과를 전달한다. ISSUE-004의 budget 수정과 함께 작업 중 취소/종료 응답성을 보완할 필요가 있다.
- **Likely Gap — 업데이트 중단 후 사용자 복구 경로:** 두 rename 사이에 helper가 중단되면 target이 없어질 수 있다. `_recover_interrupted_replacement()`는 다음 apply 호출 시 복원하지만 사용자가 기존 shortcut으로 앱을 열 수 없으면 그 호출에 도달하기 어렵다. 영구 데이터 유실로 확정하지 않으며 별도 launcher/안내·잔존 helper 재실행 절차의 실제 사용자 검증이 필요하다.
- **추정 — OS/아키텍처 지원 축:** 현재 Windows 중심 CI와 소스 portability helper만으로 macOS/Linux/Windows ARM64의 GUI·Chrome·frozen 제품 전체를 지원한다고 볼 수 없다. 지원 확대 자체는 enhancement이며 현재 Windows 핵심 기능 버그로 분류하지 않는다.

## 6. Documentation Mismatches

| 문서 설명 | 실제 구현/판정 |
|---|---|
| README 주요 기능: 수집 중 즉시 실시간 저장·키워드 알림 | dict commit 경로에서 부수 효과 누락. ISSUE-001 |
| README 및 CLAUDE 마지막 resource budget 설명: 일반 JSON/runtime/DB가 공통 byte·entry 상한 공유 | 일반 JSON에는 entry budget 없음. ISSUE-004 |
| CLAUDE의 segment/tail load fingerprint 검증 설명 | recovery manifest strict/salvage에는 있으나 일반 실행 중 segment reader에는 없음. ISSUE-002. 적용 범위를 구분해야 함 |
| CLAUDE §4.2: 실제 append/update는 `_add_text_to_subtitles()`와 shared helper 사용 | dict preview는 `commit_live_row`/`apply_preview`로 직접 수정. 레거시 경로 설명이 현재 운영 흐름 전체를 설명하지 못함 |
| README 옵션은 시작 전에만 변경 가능이라는 일괄 설명 | 바로 아래 timestamp 간격은 수집 중 변경 가능으로 명시. 범위를 한정할 필요가 있는 문서 내 모순 |

CLAUDE의 일부 **변경 이력**에 남은 PyQt6 표기는 과거 이력일 수 있으므로 현재 runtime import 결함으로 분류하지 않았다. PySide6 미설치는 이번 로컬 환경 상태이며 requirements 파일에 누락된 의존성이라는 뜻은 아니다. 이전 감사의 해결 완료 이슈는 현행 미해결 이슈로 재등록하지 않았다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. **ISSUE-001:** structured/fallback commit delta가 실시간 출력·알림을 수행하도록 연결하고 실제 dict preview 회귀를 먼저 고정한다.
2. **ISSUE-002:** 일반 segment reader에서 missing/무결성 오류를 실패로 전달한다. 불완전한 저장이 성공/clean 상태가 되는 것을 차단한다.
3. **ISSUE-003:** worker가 텍스트와 구조 메타데이터를 함께 비교하도록 수정한다. 새 발언 identity가 텍스트 중복 필터에 제거되지 않게 한다.

### Phase 2 — Stability

1. **ISSUE-004:** JSON/runtime/DB의 공통 budget과 취소 정책을 일치시킨다.
2. **ISSUE-005:** 업데이트 cleanup과 설치 transaction 경계를 정리하고 오류별 결과 상태를 검증한다.
3. PySide6가 있는 환경에서 전체 pytest와 constructor smoke를 다시 실행한다. 현재 로컬 결과를 성공 baseline으로 사용하지 않는다.
4. 실제 Chrome에서 재연결·same-text row 교체·중지 drain을 확인하고, Windows EXE·COM·비ASCII 경로 테스트를 수행한다.

### Phase 3 — Structural

- commit delta의 UI 통계·dirty·복구·realtime·alert 적용 책임을 한 지점에서 검증 가능하게 만든다. 글로벌 히스토리/suffix 의미론 변경은 별도 승인을 받은 작업으로 취급한다.
- runtime reader의 strict/salvage 및 cache 무결성 정책을 공유해 저장·복구·검색의 검증 차이를 줄인다.
- fake host 단위 테스트와 실제 QApplication/worker/storage 통합 테스트의 역할을 구분한다. public facade 호환성 테스트는 유지한다.
- 문서의 일반 보장과 경로별 보장을 구분하고, 수집 입력부터 저장물까지 확인하는 회귀를 release gate에 포함한다.

이 감사에서는 위 수정이나 설정 변경을 실행하지 않았다.

## 8. Test Recommendations

| 분류 | 입력/장애 조건 | 기대 결과 |
|---|---|---|
| Unit / ISSUE-001 | stable dict row에 알림 키워드 포함, realtime ON | append 1개·realtime 기록·알림 각각 발생. 동일 snapshot 반복은 중복 알림/전체 줄 중복 없음 |
| Integration / ISSUE-001 | unstable/container preview → 400ms 안정 timer 또는 재관측 → 실제 fallback commit | UI 자막과 realtime 파일의 내용이 일치하고 해당 키워드 알림 발생 |
| Regression / ISSUE-002 | segment+tail 저장 직전 segment 삭제, cached/uncached 각각 | 저장 실패·오류 경로 노출·기존 출력 byte 동일·현재 dirty 유지·DB 신규 불완전 세션 없음 |
| Integration / ISSUE-002 | 유효 JSON의 text/digest/count 변경 또는 일부 invalid entry | 일반 reader 거절; 명시적 salvage만 누락 경고와 정확한 count 반환 |
| End-to-End / ISSUE-003 | 로컬 browser fixture에서 같은 `네`의 row1/primary → row2/secondary를 clear 없이 교체 | 두 구조 변화가 worker 큐에 도달하고 row identity·speaker/timing이 정확히 반영 |
| Regression / ISSUE-003 | raw 동일 + color/frame/selector 변경; 완전히 동일한 probe 반복 | metadata 변경은 preview, 완전 동일 관측은 keepalive. stale run 결과는 무시 |
| Unit·Integration / ISSUE-004 | entry 상한 N, 파일은 byte 상한 이내, N/N+1개 정상 항목 | N 성공/N+1 typed limit 오류. UI 교체 전에 거절하고 이전 세션 보존 |
| Integration / ISSUE-004 | JSON·DB·runtime에서 같은 개수·누적 bytes, 중도 cancel | 상한 판정 일치·취소 완료·worker 종료·현재 세션 보존 |
| Regression / ISSUE-005 | staged 삭제 PermissionError + smoke 성공/실패 | smoke 반드시 실행. 성공은 applied/new, 실패는 rolled_back/old; cleanup 실패가 상태를 왜곡하지 않음 |
| Concurrency | segment flush와 snapshot 저장/backup을 barrier로 겹침 | 각 저장물이 하나의 완전한 prefix+tail을 포함하고 entry ID 중복/누락 없음 |
| Concurrency | DB 저장 중 같은 operation ID 재시도·서로 다른 manager 동시 저장 | 최종 logical save 1개, transient 충돌은 명시 처리, lineage latest·자막 count 일관 |
| End-to-End | 입력 URL → 검증 → Chrome fixture → preview → stop → JSON/DB/export → 재로드 | text·ID·source/speaker·start/end metadata 일치, 마지막 pending 자막 보존 |
| Integration | JSON 기록 성공 뒤 DB insert trigger로 실패 주입 | JSON 완전 유지·DB rollback·사용자 DB 경고·동일 operation ID 재시도 시 중복 없음 |
| Regression | capture 중 async 저장 후 추가 편집/새 자막 수신 | 저장 결과는 snapshot revision, 새 변경은 dirty 유지, destructive deferred action 실행 안 됨 |
| Platform-specific | Windows 한글/공백/긴 경로·read-only staged·실행 EXE 잠금 | 파일명/인코딩 정상, 오류 메시지/기존 파일 보존, updater rollback 상태 정확 |
| Platform-specific | portable/일반 frozen, 서로 다른 설치·AppData 볼륨 | 지정 root에만 쓰고 update local staging·clean child env·재시작 정상 |
| Platform-specific | HWP COM 미설치 또는 SaveAs 실패 | 문서화된 HWPX 대체/실패 안내, 기존 파일 손상 없음 |
| Runtime·Network | 최초 접속 오류·연결 단절·live-list timeout·중지 직전 지연 응답 | 의도한 재시도 횟수/상태 표시, 취소 가능, 오래된 run/result가 새 세션에 섞이지 않음 |

실제 GUI 통합 회귀는 `MainWindow.__new__` 또는 AST 추출만으로 대체하지 않는다. `QT_QPA_PLATFORM=offscreen` QApplication을 사용하는 테스트와 실제 Chrome fixture를 함께 두며, destructive fault injection은 임시 데이터에서만 수행한다.

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | **Needs Work** | 실제 dict commit의 realtime/alert 단절과 same-text row 입력 누락 |
| Runtime Stability | **Needs Work** | budget의 경로별 차이와 업데이트 중간 예외. GUI 실행 검증도 현재 환경에서 제한 |
| Data Integrity | **High Risk** | 일반 runtime reader가 불완전한 장시간 세션을 정상 저장물로 만들 수 있음 |
| Error Resilience | **Needs Work** | atomic write·transaction·recovery 방어는 있으나 조용한 segment 생략과 updater cleanup 경계가 남음 |
| Cross-platform Robustness | **Acceptable** | Windows 중심 목적에 맞는 경로/프로세스 helper와 HWP fallback 존재. 실제 frozen·ARM64·다른 OS 검증은 미완료 |
| Test Confidence | **Needs Work** | 287개 통과·pyright 무진단이나 전체 pytest 미통과. legacy helper 단위 테스트가 실제 신규 commit 경로의 결함을 놓침 |

**실제로 먼저 수정할 문제 3개:**

1. **ISSUE-001:** 실제 dict preview commit에 실시간 TXT 기록·키워드 알림을 연결한다.
2. **ISSUE-002:** runtime segment 누락·무결성 불일치가 정상 저장/내보내기로 이어지지 못하게 한다.
3. **ISSUE-003:** worker 변경 판정에 row identity·화자·source metadata를 포함한다.
