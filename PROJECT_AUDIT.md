# Project Audit

감사일: **2026-09-07 (Asia/Seoul)** · 대상: **v16.14.9 / main / 94a277a**

## 후속 조치 (v16.14.10, 2026-09-07)

아래는 이 감사 이후 구현한 수정이다. 원문 §1–9는 감사 시점의 기록으로 유지한다.

| 이슈 | 상태 | 구현 | 회귀 |
|---|---|---|---|
| ISSUE-001 Windows `os.kill(pid, 0)` | Fixed | `core/process_wait.py`, `scripts/apply_update.py`, dirty handshake + `_force_quit_for_update` | `tests/test_project_audit_20260907.py` |
| ISSUE-002 manifest/tail 세대 불일치 | Fixed | 불변 `tail_checkpoint_{N}.json` 선기록, loader `entry_id` 경계 + warning | 동일 파일 |
| ISSUE-003 다중 인스턴스 소유권 | Fixed | exclusive `run_{time}_{pid}_{token}`, `owner.json`, live-owner GC/복구 제외, TXT `"x"` | 동일 파일 |
| ISSUE-004 cross-volume replace | Fixed | EXDEV 시 대상 디렉터리 복사 후 교체 | 동일 파일 + `tests/test_update_installer.py` |
| 비중계 UX / 최초 retry | Fixed | `NoBroadcastError`, 최초 recoverable retry | 동일 파일 |
| 위원회 정식명 | Fixed | `기후에너지환경노동위원회` + 구명칭 alias | 동일 파일 |
| backup quality / JSON operation ID | Fixed | backup `capture_quality`, JSON `save_operation_id` | 동일 파일 |

남은 한계: 두 물리 볼륨 실기기 교체, frozen helper가 살아 있는 GUI 부모를 기다리는 Windows 통합, 생중계 DOM E2E는 이번 검증에 포함하지 않았다.

기능 구현·런타임 안정성 중심의 일회 감사다. 기존 업데이트 중심 보고서를 현재 저장소 전체 범위의 보고서로 갱신했다. 원 감사 당시에는 **애플리케이션 코드·테스트·설정은 수정하지 않았다.** 아래 결과는 소스 추적, 격리 회귀 테스트, 임시 데이터 재현, 비중계 상태의 실제 사이트 관찰을 구분해서 기술한다.

## 1. Executive Summary

프로젝트는 실시간 캡처, 세션 편집·내보내기, DB 검색, 장애 복구까지 구현되어 있고, revision 기반 저장 완료 처리·원자적 파일 교체·DB transaction·worker 메시지 격리 등 방어 장치가 상당히 갖춰져 있다. 격리 실행한 전체 테스트는 **434 passed / 2 skipped**, 별도 pyright는 **158 files / 0 errors / 0 warnings**였다. 그러나 플랫폼 및 여러 파일에 걸친 복구 경계에 중요한 결함이 남아 있다.

**전체 위험도: High Risk.** 특히 Windows 업데이트 helper는 수정 전 운영 설치 경로로 신뢰하기 어렵다.

| 우선순위 | 문제 | 심각도 / 신뢰도 |
|---|---|---|
| 1 | Windows에서 부모 생존 확인용 `os.kill(pid, 0)`이 부모를 강제 종료 | Critical / Confirmed |
| 2 | runtime manifest와 tail checkpoint의 세대 불일치가 경고 없는 중복 복구로 이어짐 | High / Confirmed |
| 3 | 복수 인스턴스의 runtime 디렉터리 충돌 및 다른 인스턴스 archive의 GC 선택 | High / Confirmed |
| 4 | 비portable 설치 EXE와 AppData가 다른 볼륨이면 업데이트 교체 실패 | Medium / Likely |

**데이터 손상·유실 가능성은 있다.** ISSUE-001은 아직 저장하지 않은 편집이나 진행 중 저장을 끊을 수 있고, ISSUE-002는 복구 데이터의 논리적 중복, ISSUE-003은 디스크에만 남은 archive의 덮어쓰기·삭제를 유발할 수 있다. 실제 사용자 데이터 손실을 관찰한 것은 아니다. SQLite 파일 자체의 물리적 손상은 확인하지 않았으며 WAL·transaction 보호도 존재한다.

가장 먼저 **업데이트의 정상 종료 대기**, **runtime 복구의 세대 일관성**, **프로세스 간 저장소 소유권**을 수정해야 한다. 비중계 상태에서 자막이 없는 현상 자체는 결함으로 분류하지 않았다.

## 2. Project Understanding

### 목적과 실행 환경

- 국회 인터넷의사중계 사이트의 AI 자막을 Selenium/Chrome으로 수집하는 PyQt6 데스크톱 앱이다. Windows를 주 대상으로 하며 README는 Python 3.10 이상, CI는 Windows/Python 3.12를 명시한다.
- 소스 entrypoint: `국회의사중계 자막.py`의 `main()`. 일반 실행, `--smoke`, `--smoke-storage-preflight`, `--smoke-instantiate-window`, 배포 업데이트용 `--apply-update` 경로가 있다.
- `README.md`, `CLAUDE.md`, `PIPELINE_LOCK.md`, 의존성·pytest·pyright 설정, PyInstaller spec 및 CI/release workflow를 확인했다. 저장소 루트의 물리적 `AGENTS.md`는 없었다. 사용자 제공 AGENTS 지침(CodeGraph 우선, main에서 작업)을 적용했다.
- `PIPELINE_LOCK.md`는 글로벌 히스토리 + suffix 추출 의미론의 변경을 제한한다. 이번 감사에서는 변경하지 않았다.

### 주요 모듈과 공유 상태

| 영역 | 주요 구현 | 상태·보호 장치 |
|---|---|---|
| 초기화·종료 | `runtime_state.py`, `runtime_lifecycle.py`, `runtime_driver.py` | 저장소 preflight, dirty/revision, driver identity lock, background task registry |
| 사이트 연결 | `capture_browser.py`, `capture_live.py`, `capture_dom.py`, `capture_observer.py` | URL/selector validation, live-list 선택, iframe 탐색, AI 활성화, 재연결 |
| 캡처·정합 | `core/live_capture_impl/`, `core/subtitle_pipeline*.py`, `pipeline_state.py`, `pipeline_stream.py` | `capture_state.entries`, ledger, suffix history, preview sequence, subtitle lock |
| 큐·UI | `main_window_common.py`, `pipeline_queue.py`, `pipeline_messages.py`, `view_*` | worker run ID, capture/control 큐 분리, terminal 보존, 증분 렌더링 |
| 파일·복구 | `persistence_session.py`, `persistence_runtime_*.py`, `core/file_io.py` | snapshot clone, runtime segment/manifest/tail, fingerprint, resource budget |
| DB | `core/database_impl/`, `database_worker.py`, `database_dialogs.py` | thread별 연결, lock, WAL, FK, operation ID unique index, transaction, FTS fallback |
| 내보내기 | `persistence_exports.py`, `core/export_text.py`, `core/hwpx_export.py` | TXT/SRT/VTT/RTF/DOCX/HWPX/HWP, 형식별 sanitization, 원자적 저장 |
| 업데이트 | `core/update_manifest.py`, `core/update_installer.py`, `ui/help.py`, `scripts/apply_update.py` | Ed25519, HTTPS, 만료·버전·크기·hash 검증, 승인, helper, EXE rollback |

`ui/main_window.py`는 mixin을 묶는 facade이고, `database.py`, `core/utils.py` 등은 호환 진입점을 유지한다. 타입용 선언과 테스트용 fake를 production 구현으로 판단하지 않았다.

### 저장 방식과 외부 의존성

개발 실행은 repo root, portable EXE는 EXE 디렉터리, 일반 배포 EXE는 `%LOCALAPPDATA%/AssemblySubtitle/Extractor`를 저장소로 쓴다. SQLite `subtitle_history.db`, 세션 JSON, backup JSON, runtime `manifest.json`/`segment_*.json`/`tail_checkpoint.json`, `session_recovery.json`, 실시간 TXT, URL history/preset JSON이 있다. 일반 설정은 QSettings, portable 설정은 INI다.

외부 실행 의존성은 PyQt6, Selenium/Chrome/Selenium Manager, cryptography다. DOCX는 python-docx, HWP는 pywin32와 한컴오피스가 필요하며 HWPX는 자체 구현이다. 네트워크 의존성은 국회 사이트와 목록 API, GitHub 업데이트 manifest·release asset이다. DB 저장은 수집 매 건 자동 insert가 아니라 **세션 저장 시 JSON과 함께 수행**되는 경로다.

### 핵심 사용자 실행 흐름

```text
main → storage preflight → QApplication/MainWindow → timers/DB/설정/복구 후보

시작/F5 → _start → URL·selector 검증 + 기존 세션 보호
 → _begin_extraction_run → runtime archive + worker
 → _open_capture_driver_session → Chrome/page → live-list xcgcd 보완
 → AI 자막 활성화 → Observer/structured DOM probe
 → run_id가 붙은 capture queue → _apply_structured_preview_payload
 → ledger/reconciliation + pipeline → capture_state.entries mutation
 → revision/통계/렌더링 + 선택적 realtime TXT + runtime segment flush

중지 → stop_event → pending preview drain → finalize → worker finished → UI 복구

세션 저장 → snapshot + revision + runtime context → background JSON atomic write
 → recovery pointer → DB worker → transaction/operation ID → control queue
 → revision 일치 시 dirty 해제, 불일치 시 후속 destructive action 취소

JSON/runtime/DB 불러오기 → byte/entry budget 또는 DB fetchmany
 → deserialize·fingerprint·취소 검사 → control queue → 사용자 확인 → 세션 교체

검색/편집/병합 → 전체 세션 읽기 또는 hydrate → 결과 이동/편집/정렬·dedupe
 → dirty revision 증가 → 파일 내보내기/세션 저장

업데이트 확인 → 서명 manifest 검증 → 다운로드·hash 검증 → 사용자 설치 승인
 → 복사된 helper EXE → 부모 종료 대기 → EXE 교체 → smoke/rollback → 다음 시작 결과 안내
```

## 3. Audit Coverage & Limitations

### 확인 범위

CodeGraph MCP `codegraph_explore`를 실제 사용했다. entrypoint/캡처/저장/DB/runtime/update를 먼저 질의하고, 이름이 확인된 구체 함수로 재질의했다. 대표 관계는 다음과 같다.

- `_begin_extraction_run → _start_runtime_session_archive → _cleanup_orphan_runtime_archives`
- `_extraction_worker → _open_capture_driver_session / _check_driver_health / _detect_live_broadcast`
- `_drain_pending_previews → _process_preview_queue_message → _process_raw_text`
- `_maybe_schedule_runtime_segment_flush → control message → _handle_runtime_segment_flush_done → manifest/tail write`
- `_write_session_snapshot → _run_db_task_sync → DatabaseSessionMixin.save_session`
- `_start_db_session_load → get_session_metadata / iter_session_subtitles → _complete_loaded_session`
- `_handle_update_install_ready → launch_update_helper → scripts.apply_update.main → _wait_for_parent / apply_staged_update`

CodeGraph가 동적 `getattr` 후보로 production 메서드와 테스트 fake를 함께 제시한 부분은 실제 import·caller로 구별했다. 일부 초기 응답에 pending-sync 경고, source gap/출력 절단이 있었고 한글 entrypoint도 충분히 반환되지 않아 해당 범위는 직접 소스 열람으로 보완했다. 그래프의 caller 개수를 완전한 도달성 증명으로 사용하지 않았다.

### 실제 실행한 검증

| 검증 | 결과와 조건 |
|---|---|
| 전체 pytest | **434 passed, 2 skipped, 18.34s**. Python wrapper에서 Config의 저장 경로를 새 임시 디렉터리로 바꾸고 `pytest.main(['-q', '--tb=short', '--basetemp=<temp>/pytest'])` 실행. `QT_QPA_PLATFORM=offscreen` 사용 |
| Skip 사유 | live contract는 `RUN_LIVE_SMOKE` 미설정으로 skip. subprocess를 사용할 수 있어 in-process 전용 fallback 분기 검증이 skip. live 테스트가 통과했다고 해석하지 않음 |
| 정적 검사 | `python -m pyright --outputjson`: **158 files / 0 errors / 0 warnings**, pyright 1.1.411 |
| runtime 복구 재현 | 실제 manifest/tail writer와 loader를 임시 A/B 데이터에 적용: `ids=['A','A','B'], warnings=[], skipped=0` |
| 복수 인스턴스 경계 | 시간을 고정하고 두 독립 MainWindow 상태의 archive 시작 메서드를 호출: 동일 root, 서로 다른 token. GC는 `shutil.rmtree`를 recorder로 대체해 10초 미만 archive가 삭제 대상으로 선택됨을 확인; 실제 삭제는 실행하지 않음 |
| updater 대기 호출 | `os.kill`을 recorder로 대체: `_wait_for_parent(987654)`가 `(987654, 0)` 호출. 실제 OS signal·프로세스 강제 종료는 실행하지 않음 |
| Qt 반증 실험 | 작은 offscreen QMainWindow에서 `QApplication.quit()`이 `closeEvent`를 호출하고 `ignore()`를 존중함을 확인. 강제 fallback은 그 실험의 event loop에만 `app.exit()` 호출 |
| 사이트 drift CLI | `python scripts/check_live_list_drift.py`: `ok=false`, 연결 오류 **WinError 10053**. 원본 API 계약 검증 미완료 |

로컬 환경은 Python **3.14.7**, PyQt6 **6.11.0**, Selenium **4.48.0**, pytest **9.1.1**, cryptography **50.0.1**, python-docx **1.2.0**이었다. requirements-dev.txt 핀(Python CI 3.12, PyQt6 6.10.2, Selenium 4.40.0 등)과 다르다. 설치 없이 기존 환경으로 검사했으므로 **핀 환경 재현·배포 EXE 검증을 대체하지 않는다.**

테스트 저장소: `%TEMP%/kacc-audit-20260907-zwaeqlqf`. 추가 재현 데이터: `%TEMP%/kacc-audit-probes-nxicxyoj`. 감사 작업은 기존 사용자 세션/DB를 입력으로 사용하거나 수정하지 않았다.

### 현재 사이트 확인 — 비중계 상태 중점

2026-09-07 인앱 브라우저로 [국회 사이트 메인](https://assembly.webcast.go.kr/main/)을 직접 열었다.

- 본회의는 **10:37 산회**. 메인 위원회 목록에 현재 생중계 플레이어 링크가 없고 다른 위원회는 영상회의록 링크를 제공했다.
- README 예제인 [xcode=10 플레이어](https://assembly.webcast.go.kr/main/player.asp?xcode=10)는 **“잘못된 요청입니다.”** alert를 띄웠고, 닫으면 메인으로 이동했다. 비중계 시 서버 동작으로 확인했으며, 생중계 시간에도 동일하게 실패한다고 일반화하지 않았다.
- 사이트 위원회 선택 목록의 정식 이름은 **기후에너지환경노동위원회**였지만 Config에는 **기후환경노동위원회**가 남아 있다. 화면의 약칭 `기후노동위`는 현재 코드에도 있다. 명칭 갱신은 필요하지만 이 사실만으로 xcode=62가 잘못되었다고 판단하지 않았다.
- [live_list.asp](https://assembly.webcast.go.kr/main/service/live_list.asp) 직접 열기는 브라우저 `ERR_BLOCKED_BY_CLIENT`, Python 경로는 10053, web 조회도 접근 실패했다. 환경 차단인지 API 조건인지 분리하지 못했으므로 API 폐기·사이트 장애로 보고하지 않는다.
- 현재 실제 플레이어 DOM/AI 버튼/자막 스트림을 확보하지 못했다. `.btn_subtit_ai`, `.btn_subtit_def`, `.smi_word`, iframe 및 다중 화자 구조의 **현재 live 적합성은 미확인**이다. 비중계 페이지에서 selector가 없다는 이유로 selector 교체를 권하지 않는다.

### 미검증 범위

실제 중계 중 수집→저장 E2E, 장시간 Chrome 구동, 실제 네트워크 단절·재개, pinned Python 3.12 환경, frozen EXE helper 설치, 두 물리 볼륨 간 업데이트, Linux/macOS 실행, 실제 한컴 COM 및 문서 앱 렌더링, 수 시간 부하·전원 차단, GitHub release 운영 권한·secret은 검증하지 않았다. 로컬 회귀는 stub/fake 경로도 포함하며 GUI 사용자 조작 전체를 보증하지 않는다.

## 4. High-Risk Issues

확정 및 근거가 강한 조건부 결함만 수록했다. 섹션 이름과 별개로 각 이슈의 실제 심각도를 표기한다.

### [ISSUE-001] Windows 업데이트 helper가 부모 종료를 기다리는 대신 강제 종료한다

- **위치:** `scripts/apply_update.py:12-22` `_wait_for_parent`; `ui/main_window_impl/ui/help.py:267-329` `_handle_update_install_ready`; `core/update_installer.py:219-253` `launch_update_helper`.
- **우선순위:** Critical
- **신뢰도:** Confirmed — production 호출과 플랫폼 API 계약 확인. 실제 강제 종료 실험은 하지 않았다.
- **문제:** `os.kill(parent_pid, 0)`을 POSIX의 생존 확인처럼 사용한다. Windows에서는 CTRL_C/CTRL_BREAK 이외의 signal 값이 `TerminateProcess`로 처리되므로 0도 종료 요청이다. [Python 공식 os.kill 문서](https://docs.python.org/3/library/os.html#os.kill)
- **발생 조건:** Windows 배포 EXE에서 업데이트 설치를 승인하고 helper가 시작될 때 부모가 아직 종료되지 않은 경우. 다운로드 중 편집, 닫기 시 저장·취소 확인, 트레이 최소화, background 작업 대기 때문에 부모가 살아 있는 상황은 현실적이다.
- **영향:** 정상 close/drain/dirty 보호가 끝나기 전에 프로세스가 종료될 수 있다. 저장되지 않은 편집과 미flush 자막 유실, 진행 중 저장 중단 가능성이 있다. 이미 commit된 SQLite 데이터의 파괴까지 확인한 것은 아니다.
- **근거:** UI는 helper에 `parent_pid=os.getpid()`를 전달한 **후** `QApplication.quit()`을 호출한다. helper의 `main()`은 `_wait_for_parent()`를 먼저 실행한다. recorder 실험 결과는 `[(987654, 0)]`이었다. 기존 helper 테스트는 비양수 PID와 실패 결과 저장만 확인해 Windows의 살아 있는 부모 경로를 다루지 않는다.
- **반증 확인:** 다운로드 전 dirty 확인, 설치 직전 `is_running` 가드, Qt `closeEvent`, 저장 revision 검사가 있다. Qt quit은 실제로 closeEvent를 호출하는 것으로 반증했으므로 “Qt가 종료 이벤트를 우회한다”는 주장은 제외했다. 문제는 별도 helper가 그 정상 종료를 기다리지 않고 끊는 데 있다. Ed25519·hash·EXE rollback은 부모 메모리의 미저장 내용을 복원하지 않는다.
- **호출/영향 범위:** CodeGraph의 `help._handle_update_install_ready → launch_update_helper → scripts.apply_update.main → _wait_for_parent` 경로. frozen `--apply-update` 진입에 연결되어 있고 dead code가 아니다.
- **권장 수정 방향:** Windows에서는 종료 권한이 아닌 synchronize 권한의 process handle과 `WaitForSingleObject` 등으로 기다린다. 접근 거부를 “이미 종료”로 취급하지 않는다. 앱이 저장·종료를 확정한 뒤 helper와 handshake하고 timeout이면 교체를 중단한다.
- **필요한 회귀 테스트:** mock Windows adapter가 생존 확인 중 terminate/signal을 호출하지 않을 것; 부모가 저장 완료를 기다리는 동안 helper도 기다릴 것; 종료 취소·tray·timeout이면 설치하지 않을 것. 별도 Windows 통합 환경에서는 테스트 전용 부모의 정상 종료 marker가 쓰인 후에만 교체가 시작되어야 한다.

### [ISSUE-002] manifest와 tail checkpoint의 불일치가 경고 없이 자막을 중복 복구한다

- **위치:** `ui/main_window_impl/persistence_runtime_segments.py:124-203` `_handle_runtime_segment_flush_done`; `persistence_runtime_archive.py:235-277,546-574`; `persistence_runtime_manifest.py:22-258` `_load_runtime_manifest_payload`.
- **우선순위:** High
- **신뢰도:** Confirmed — 실제 writer/loader를 사용한 임시 데이터 재현.
- **문제:** segment 확정 후 **manifest를 먼저**, tail checkpoint를 다음에 쓴다. 두 원자적 파일 저장 사이에 프로세스가 중단되거나 tail 쓰기가 실패하면 새 manifest와 이전 tail이 남는다. loader는 각 파일 fingerprint만 검사하고 두 파일의 `archived_count`·세대 관계를 맞추지 않은 채 이어 붙인다.
- **발생 조건:** 이전 checkpoint에 `[A,B]`, 새 segment에 `[A]`가 있고 새 manifest는 archived_count=1인데 tail 교체 전에 중단되는 경우. 2,000개 초과 시 발생하는 실제 segment flush에서 같은 구조가 만들어진다.
- **영향:** `[A,B]`가 `[A,A,B]`로 복구된다. 검색·개수·TXT/SRT/VTT/JSON 및 후속 DB 저장까지 중복이 전파될 수 있다. 복구 성공 안내만 보이므로 사용자가 무결성을 오인할 수 있다.
- **근거:** production writer로 `tail archived_count=0, entries=[A,B]`와 `manifest archived_count=1, segment=[A]`를 만들고 `allow_salvage=True`로 읽었다. 출력: `ids=['A','A','B'], warnings=[], skipped=0`. 서로 다른 텍스트 A/B와 고정 entry ID를 사용했다.
- **반증 확인:** temp+fsync+replace는 **각 파일**의 파손을 막는다. fingerprint는 각 파일 내용과 일치하므로 모두 통과한다. run ID/token은 같은 실행의 서로 다른 checkpoint를 구분하지 못한다. loader의 `all_entries.extend(...)` 두 지점 사이에 세대 검증·중복 경계 조정이 없고 `_complete_loaded_session`도 해당 리스트를 그대로 적용한다. salvage는 정상 파싱되는 두 파일의 세대 불일치를 교정하지 않는다.
- **호출/영향 범위:** CodeGraph의 segment worker → control message → flush completion → manifest/tail 저장 및 recovery/session load → `_complete_loaded_session`. archive 전체 검색·내보내기·DB 저장 경로에 연결된다.
- **권장 수정 방향:** 세대별 불변 tail 파일을 쓰고 manifest가 그 정확한 checkpoint를 참조하도록 한 뒤 manifest를 commit 지점으로 사용한다. loader는 count/index/token/generation의 조합을 검증하고 혼합 세대는 조용히 성공시키지 않는다. 단순 텍스트 dedupe는 실제 반복 발언을 지우므로 해결책으로 쓰지 않는다.
- **필요한 회귀 테스트:** segment·manifest·tail 교체의 각 경계에서 예외 주입. 새 manifest+옛 tail 입력은 정확한 `[A,B]`로 복구하거나 명시적 불일치 경고/안전한 거부가 나와야 하며, 정상 동일 텍스트의 서로 다른 발언은 보존해야 한다.

### [ISSUE-003] 여러 앱 인스턴스의 runtime 저장소 소유권이 분리되지 않는다

- **위치:** `ui/main_window_impl/persistence_runtime_archive.py:384-496`; `runtime_state.py:318-339`; `runtime_driver.py:224-246` 실시간 파일 생성; `국회의사중계 자막.py` 일반 시작 경로.
- **우선순위:** High
- **신뢰도:** Confirmed — 경로 충돌과 GC 선택을 재현. 실제 타 인스턴스 파일 삭제는 수행하지 않았다.
- **문제:** runtime root가 `run_<초 단위 시각>_<프로세스 내부 run_id>`이고 `mkdir(exist_ok=True)`를 쓴다. UUID token은 생성되지만 경로에는 포함되지 않는다. GC도 다른 프로세스가 사용하는 archive인지 확인하지 않고 현재 객체 root·단일 recovery pointer·최근 3개/연령만 본다.
- **발생 조건:** 같은 storage root의 두 프로세스가 같은 초에 첫 추출을 시작하면 같은 root를 선택한다. 시작 시각이 달라도 A가 긴 세션을 캡처하는 동안 B에서 여러 세션을 시작하면 A의 archive가 최근 3개 밖으로 밀릴 수 있다. 단일 인스턴스 강제 장치는 entrypoint와 관련 코드에서 찾지 못했다.
- **영향:** 같은 이름의 manifest/segment/tail 덮어쓰기 또는 다른 프로세스의 디스크 archive 삭제. active tail에서 이미 제거된 오래된 자막은 별도 세션 저장이 없다면 잃을 수 있다. 실시간 TXT도 초 단위 이름에 `open(...,'w')`여서 동시 시작에 같은 충돌 유형이 있다.
- **근거:** 2026-09-07 12:00:00으로 고정해 두 독립 상태에서 `_start_runtime_session_archive(1)`을 호출하면 `same_root=True, tokens_differ=True`. 별도 GC 재현은 생성 후 10초 이내 네 디렉터리 중 최근 3개 밖의 `run-0`을 삭제 대상으로 선택했다. 삭제 함수는 recorder로 교체했다.
- **반증 확인:** `_runtime_archive_token`은 자기 프로세스로 돌아오는 메시지의 stale 여부를 검사한다. OS 파일 소유권을 예약하지는 않는다. subtitle lock과 background registry도 프로세스 내부 장치다. SQLite lock은 JSON/디렉터리 GC를 보호하지 않는다. “7일” 설정도 최근 N개 밖의 archive에는 유예로 동작하지 않는다. 정상 종료된 오래된 archive의 의도적 보존 정책 자체를 버그라고 한 것은 아니다.
- **호출/영향 범위:** CodeGraph의 `MainWindow.__init__ → _cleanup_orphan_runtime_archives`, `_begin_extraction_run → _start_runtime_session_archive`, 이후 runtime readers/export/search. 동시에 여러 위원회를 수집하는 사용 방식에 영향이 있다.
- **권장 수정 방향:** 다중 실행을 지원할지 결정한다. 지원한다면 UUID 기반 독점 디렉터리 생성, active owner/lease 또는 process lock, 인스턴스별 recovery 상태, 사용 중 archive를 제외하는 GC를 함께 구현한다. 실시간 파일은 고유명+exclusive create를 쓴다. 지원하지 않으면 storage root별 단일 인스턴스를 명시적으로 강제한다.
- **필요한 회귀 테스트:** 같은 시각·같은 run ID의 두 프로세스가 서로 다른 파일을 쓸 것; A 수집/검색/export 중 B가 4회 이상 세션을 바꿔도 A archive를 GC 대상으로 선택하지 않을 것; 죽은 owner만 정책에 따라 회수할 것.

### [ISSUE-004] 다른 볼륨에 설치된 일반 EXE의 자동 업데이트가 실패한다

- **위치:** `core/update_installer.py:61-69` `resolve_update_staging_root`, `166-216` `apply_staged_update`; `ui/main_window_impl/ui/help.py` 다운로드 경로.
- **우선순위:** Medium
- **신뢰도:** Likely — 코드와 OS 계약이 명확하지만 두 실제 볼륨에서 재현하지 않았다.
- **문제:** 비portable staging은 AppData 아래인데 적용은 `os.replace(staged_path, target_path)`로 바로 수행한다. 대상 EXE와 staging이 다른 볼륨일 때의 복사·재검증 경로가 없다.
- **발생 조건:** `D:/Apps/app.exe`로 설치/실행하고 `portable.flag`가 없으며 AppData는 C:에 있는 경우 등.
- **영향:** 다운로드와 검증·승인까지 끝나도 교체에서 실패한다. 일반적으로 원 EXE/backup은 보존되어 수동 설치가 가능하므로 Critical/High로 올리지 않았다.
- **근거:** staging resolver는 nonportable에서 install_dir를 사용하지 않고, `_validate_apply_paths`는 backup.parent만 target.parent와 비교한다. [Python 공식 os.replace 문서](https://docs.python.org/3/library/os.html#os.replace)는 파일시스템 간 이동 실패 가능성을 명시한다.
- **반증 확인:** portable 분기는 같은 설치 디렉터리 아래 staging이라 해당 조건을 피한다. hash/size 검증과 rollback은 실패 후 보호일 뿐 cross-volume 교체를 구현하지 않는다. 기존 성공 테스트는 같은 tmp_path 안의 파일을 쓴다.
- **호출/영향 범위:** CodeGraph의 download worker → staging resolver → helper → apply_staged_update. ISSUE-001의 종료 대기를 먼저 고친 후 검증해야 한다.
- **권장 수정 방향:** target과 같은 볼륨의 고유 임시 파일로 복사하고 fsync·hash를 다시 검증한 다음 같은 디렉터리에서 원자적으로 교체한다. 준비 실패는 부모 종료 이전에 안내한다.
- **필요한 회귀 테스트:** source/destination volume이 다른 조건과 EXDEV/Windows not-same-device 예외를 테스트한다. 복사 중 공간 부족이면 기존 EXE가 그대로 남아야 하고, 성공 시 새 EXE hash와 smoke 성공을 확인해야 한다.

## 5. Potential Functional Gaps

- **Confirmed Gap — 비중계·준비 상태의 명확한 UX:** 목록 선택의 종료/예정 확인은 이미 있다. 다만 일반 시작은 player에 먼저 접근하고 자막 요소를 기다린다. 현재 관찰된 alert→메인 복귀 상태를 “현재 중계 없음 / 예약 대기 / 사이트 구조 오류”로 일관되게 구별하는 경로와 실제 사이트 회귀가 부족하다. `_resolve_active_selector`는 후보마다 최대 20초 기다린다. 전체 지연 시간을 측정하지 않았으므로 특정 초 수를 장애 수치로 제시하지 않는다.
- **Confirmed Gap — 최초 접속 실패 자동 재시도:** `_extraction_worker`의 최초 `_open_capture_driver_session` 실패는 terminal failure로 종료한다. 최대 5회 재연결 루프는 이미 수집 루프에 진입한 뒤의 오류에 적용된다. 일시적인 최초 네트워크 오류도 재시도하려는 제품 요구라면 별도 초기 연결 retry를 추가해야 한다. 현재 비중계 상태를 무조건 재시도해야 한다는 의미는 아니다.
- **Confirmed Gap — 사이트 정식 위원회 명칭 동기화:** `core/config.py:409,434,468-469`의 `기후환경노동위원회`를 현재 사이트의 `기후에너지환경노동위원회`와 조정할 필요가 있다. 표시·자동 태그·파일명/메타데이터 정합 문제이며 잘못된 방송 수집으로 확정하지 않는다. 기존 사용자 preset 이름의 호환 alias도 고려한다.
- **Confirmed Gap — 일반 backup 품질 metadata:** `persistence_session.py:725-736`의 일반 backup header에는 capture_quality가 없다. runtime checkpoint와 수동 세션 JSON에는 있다. 이 분기가 실행된 backup의 진단 round-trip을 보강해야 한다. 기본 추출은 runtime root를 사용하므로 모든 자동 백업에서 진단이 사라진다고 일반화하지 않는다.
- **Likely Gap — save operation의 재시작 후 재시도:** DB의 동일 ID 멱등 저장은 구현되어 있지만 JSON에는 operation ID가 기록되지 않는다. 앱 재시작 후 실패한 JSON→DB 저장을 같은 operation으로 재개하는 durable 재시도 절차는 확인하지 못했다. 사용자의 새 저장은 원래 별도 계보 revision일 수 있으므로 그 자체를 중복 버그로 분류하지 않는다.
- **추정 — 실제 사이트 자막 활성화 완료 판정:** 활성화 JS는 버튼 click 성공 또는 레이어 표시를 성공으로 반환하는 경로도 있다. 네트워크 구독 성공·첫 row 수신과 구분한 상태가 유용할 수 있다. 실제 live DOM과 지연을 확보하지 못했으므로 현재 AI 활성화가 깨졌다고 판단하지 않는다.

## 6. Documentation Mismatches

| 문서 설명 | 실제 구현 / 수정할 문서 방향 |
|---|---|
| CLAUDE의 “URL은 HTTPS 기본 포트” 계약 | `core/url_policy.py:46-61`은 HTTP/HTTPS 양쪽과 각 기본 포트를 허용한다. 실제 정책을 명시하거나 정책을 바꾼 뒤 문서를 맞춰야 한다. 업데이트 URL은 별도로 HTTPS 검증됨 |
| CLAUDE의 “JSON snapshot의 save_operation_id를 SQLite에도 전달” | operation ID는 worker 결과와 DB에 있으나 `_write_session_snapshot` JSON header에는 없다. 영속 JSON 계약과 메모리 내 저장 context를 구분해야 한다 |
| README/CLAUDE의 일반적 “연결 실패 자동 재연결” | 최초 driver/page/selector 초기화 실패는 즉시 종료하고, 이미 연결된 수집 루프의 오류에 retry가 적용된다. 시작 실패와 운영 중 단절을 나눠 설명해야 한다 |
| README의 “SQLite DB에 자동 저장” | 기능 본문만 읽으면 실시간 연속 저장으로 오해할 수 있다. 구현과 CLAUDE는 세션 저장 시 JSON과 함께 DB 저장한다. 무저장 장기 수집의 복구 근거는 runtime 파일이다 |
| 복구·저장 안정성 설명 | 개별 파일 원자성과 revision 보호는 사실이나 다중 파일 generation 일관성·다중 프로세스 소유권까지 보장하지 않는다. ISSUE-002/003 해결 전 보장 범위를 제한해야 한다 |

README의 과거 변경 이력에 있는 테스트 개수는 당시 기록이므로 현재 434개와 다르다는 이유로 오류로 지적하지 않았다. Windows 전용 HWP, 선택 패키지, source/portable/AppData 저장소 구분은 대체로 구현과 일치한다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. **ISSUE-001:** Windows 부모 대기 API 교체와 정상 종료 handshake를 먼저 구현한다. helper 출시 검증에서 살아 있는 테스트 부모와 저장 지연을 필수 시나리오로 둔다.
2. **ISSUE-002:** checkpoint generation 설계와 혼합 세대 복구 검사부터 추가한다. legacy 파일은 안전하게 경계를 판별할 수 없는 경우 경고하며, text-only dedupe로 조용히 고치지 않는다.
3. **ISSUE-003:** storage root별 단일 실행 또는 명시적 multi-instance 소유권을 확정한다. 그 결정과 동시에 archive GC의 active owner 보호를 구현한다.

### Phase 2 — Stability

- **ISSUE-004:** 대상 볼륨에서 준비·검증·교체하도록 updater staging을 보완한다.
- 비중계/산회, alert, API 실패, selector drift, 최초 접속 실패를 구분하는 사용자 상태와 timeout/cancel을 보완한다.
- 현재 사이트 위원회 명칭, 일반 backup 진단 metadata, 문서상의 저장·재시도 계약을 정리한다.
- 파일별 원자적 쓰기와 복구 가능한 multi-file commit을 구분하고, disk-full/permission 실패를 사용자에게 명시한다.

### Phase 3 — Structural

- runtime snapshot의 generation·reader·GC 소유권을 하나의 저장 프로토콜로 정리한다. UI mixin의 임의 호출 순서가 무결성 계약을 대신하지 않도록 한다.
- parent waiter, filesystem mover, clock, live-list transport를 좁은 인터페이스로 분리하여 실제 OS 동작과 fake를 각각 검증한다.
- frozen helper·실제 Windows 파일시스템·실제 사이트의 계약 테스트를 기존 빠른 fixture 테스트와 별도 게이트로 운영한다. 기존 suffix 추출 의미론의 임의 변경은 피한다.

실제 수정·배포·branch 생성은 수행하지 않았다.

## 8. Test Recommendations

| 유형 / 대상 | 입력·상황 | 기대 결과 |
|---|---|---|
| Unit — ISSUE-001 | Windows parent wait adapter에 살아 있는 handle, 접근 거부, timeout, 종료 handle을 각각 제공 | terminate 호출 0회; 접근 거부는 실패로 노출; 실제 종료만 성공 |
| Integration — ISSUE-001 | 테스트 부모가 임시 JSON 저장 완료 신호를 지연하고 helper가 설치 승인 후 대기 | 완료·정상 종료 전에 EXE 교체하지 않음; 부모 종료 취소 시 설치 중단 |
| Regression — Qt 종료 | dirty 세션/취소 선택, tray ON, active background save 후 quit | closeEvent 보호 유지, helper가 강제 종료하지 않음. Qt quit 우회로 오판하는 테스트를 만들지 않음 |
| Unit/Integration — ISSUE-002 | segment=[A], manifest archived=1, 이전 tail archived=0/[A,B] | `[A,A,B]` 무경고 성공 금지; 정합 복구 `[A,B]` 또는 명확한 오류 |
| Concurrency — ISSUE-002 | 자동 checkpoint와 segment flush를 barrier로 각 쓰기 지점에서 교차 실행 | 재시작 시 한 generation만 복구; count/index/fingerprint 일치 |
| Regression — 정당한 반복 발언 | 다른 entry ID를 가진 동일 문장 두 개와 경계 중복 ID를 함께 입력 | 다른 실제 발언은 유지하고 세대 경계 중복만 처리 |
| Concurrency — ISSUE-003 | 동일 시각·run ID의 두 프로세스, A가 수집 중 B의 반복 시작/종료 | 고유 root/TXT, 서로의 파일 보존, active archive는 GC 제외 |
| Platform-specific — ISSUE-004 | C: staging, 다른 실제 볼륨의 disposable EXE fixture; 복사 중 공간 부족 | 동일 볼륨 최종 교체, 원본 보존, 성공 hash/smoke 일치. 실제 사용자 EXE는 사용하지 않음 |
| E2E — 현재 비중계 사이트 | 목록 non-live, 기본 xcode URL의 alert→메인 복귀 | “현재 중계 없음” 등 적절한 상태, 제한된 대기, 중지 응답, 빈 세션의 성공 수집 오인 방지 |
| E2E — 실제 생중계 | 대상 위원회 1개 선택→xcgcd 확정→AI ON→짧은 발언/화자 전환→중지→JSON/DB/SRT | 다른 위원회 선택 없음; 화자·순서·마지막 발언 보존; SRT 첫 cue 0 기준; JSON/DB 내용 일치 |
| Integration — API 실패 | timeout, HTTP 5xx, HTML 응답, invalid JSON, 2MB 초과, 다중 후보 | 오류 원인 표시, 다른 방송 임의 선택 금지, 늦은 응답이 닫힌 dialog를 변경하지 않음 |
| Regression — 저장 revision | 저장 snapshot 이후 편집/수집, DB 작업 지연 후 완료 | 새 변경 dirty 유지, 종료/로드 자동 재개 금지, 같은 operation ID 재시도는 한 DB 세션 |
| Integration — DB | insert 중 예외, FK 대상 삭제, FTS 사용 불가, load cancel | 부분 세션 commit 없음; FK 정합; literal 검색 fallback; 취소 전 현재 세션 유지 |
| Unit/Integration — 입력·복구 budget | 100MB 초과 JSON, 150,000개 초과 세션, ../·절대 segment 경로, 손상 파일 | 한도·경로 거부, 원 세션 유지, salvage 제외 내역 표시 |
| Regression — 문서·metadata | 기후노동위 선택, 일반 backup의 quality count, 새 operation JSON 저장 | 사이트 정식 명칭/alias 일치, 의도한 metadata round-trip, 문서와 JSON 계약 일치 |
| Platform-specific — 출력 | 한글·emoji·제어 문자·CRLF·긴 경로, 읽기 전용 대상, HWP COM 없음 | 형식별 유효 파일/안내·fallback, 기존 파일 보존, 실패를 성공으로 표시하지 않음 |
| Release — 실제 환경 | requirements 핀 Python 3.12 + clean frozen build + disposable storage | source/constructor/storage smoke와 helper 통합 통과, private/public key 일치, 업데이트 결과 지속성 |

위 표는 **추가로 실행해야 할 검증 계획**이다. 이번에 실행한 검증은 §3에 한정된다.

## 9. Final Assessment

| 영역 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Needs Work | 주요 기능과 회귀는 동작하지만 복구 중복과 조건부 업데이트 실패가 남음 |
| Runtime Stability | Needs Work | 큐/종료 관리가 있으나 Windows helper 강제 종료가 정상 lifecycle을 끊을 수 있음 |
| Data Integrity | High Risk | runtime 세대 불일치 및 다중 프로세스 archive 덮어쓰기·GC 위험. DB transaction 자체는 보호됨 |
| Error Resilience | Needs Work | 다수 예외/fallback은 있으나 경고 없는 혼합 checkpoint 복구와 초기 접속 실패 대응이 부족 |
| Cross-platform Robustness | Needs Work | 주 대상 Windows의 process API 오용, cross-volume 경계 미처리; 타 OS 실검증 없음 |
| Test Confidence | Acceptable | 434 pass와 pyright 0 errors는 유의미하나 OS·frozen helper·live DOM·multi-process 검증을 대신하지 못함 |

**실제로 먼저 수정할 3개:**

1. **ISSUE-001 — Windows 업데이트 부모 대기에서 `os.kill(pid, 0)` 제거 및 정상 종료 handshake.**
2. **ISSUE-002 — runtime manifest/tail을 동일 generation으로 commit·복구.**
3. **ISSUE-003 — 프로세스별 runtime 파일 소유권과 active archive GC 보호.**
