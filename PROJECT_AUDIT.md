# Project Audit

## 후속 구현 및 검증 — 2026-11-05

사용자의 후속 수정 요청에 따라 **main에서 제품 코드·테스트·문서를 수정했다.** 아래 §1–9는 `2b7af3a`에 대한 원 감사 기록이며, 현재 미해결 결함 목록이 아니다. 버전 증가·푸시·공개 배포·업데이트 manifest 게시는 하지 않았다.

**2026-11-06 문서 정리:** 현재 감사·수정·검증 상태는 이 문서로 안내한다. 과거 개별 감사 문서 3개는 작업트리에서 제거하고 README·CLAUDE·GEMINI·릴리스 체크리스트의 참조를 정리했다. 과거 문서 본문은 Git 이력에 남아 있다. 제품 코드와 검증 수치는 2026-11-05 후속 작업 기준이며, 실기기·원격 CI의 미확인 범위는 그대로 유지한다.

커밋 전에는 제품 코드·테스트·CI·검증 스크립트가 앞서 검증한 소스 복사본과 바이트 단위로 동일함을 확인했다. 문서 정리 후 격리 복사본에서 인코딩·CI 설정·감사 후속 회귀는 **27 passed / 1 skipped**, pyright는 **202 files / 0 errors / 0 warnings**였다. skip은 명시적 환경 변수가 필요한 soak 검사다. 변경 문서의 로컬 Markdown 링크와 `git diff --check`도 통과했다.

| 감사 제안 | 현재 상태 | 구현·검증 |
|---|---|---|
| ISSUE-001: snapshot/revision 불일치 | 수정·검증 | 일반·deferred 저장에서 파일 선택 후 entries/manifest 확보. `SessionSaveSnapshot`이 entries clone·읽기 전용 메타데이터·revision을 UI에서 고정하며 worker가 UI/현재 세션 메타데이터를 다시 읽지 않음. 실제 modal 동안 새 발언·segment flush를 교차해 JSON/DB 동일 내용 검증 |
| ISSUE-002: terminal 이전 pending 데이터 유실 | 수정·검증 | terminal handler가 일반·overflow·coalesced preview를 소진한 뒤 run 폐기. 최신 coalesced DOM snapshot은 이전 overflow 뒤 반영. 용량 1·500과 새 run에 늦은 이전 preview 유입 거절 검증 |
| ISSUE-003: 최종 fallback 부수 효과 누락 | 수정·검증 | `_commit_fallback_preview`를 일반 timer/종료 경로가 공유. TXT·알림·revision·dirty·tail·복구 snapshot 반영. stop/finished 반복에도 한 번만 기록 |
| structured snapshot의 중복 재생 | 추가 수정·검증 | row identity로 이미 확정한 structured preview는 snapshot/종료에서 suffix fallback에 다시 넣지 않음. 서로 다른 stable row 저장·종료에서 중복 없음 |
| 포인터 없는 복구·손상 포인터 안내 | 구현·검증 | `파일 → 백업에서 세션 복구...` 추가. 포인터 없는 정상 시작은 계속 조용히 유지. 손상 포인터는 수동 복구 안내. 복구 선택 후 기존 dirty 확인을 거치며 취소는 현재 세션 보존 |
| 복구 후보 전체 작업량·UI 응답성 | 구현·검증 | background scan + 진행 표시·취소·완료 직전 취소 재확인. 후보 1,000개·전체 읽기 256MiB·탐색 경로 10,000개 budget. 취소·상한 초과 시 부분 후보 적용 안 함. 오래된 token 결과도 거절 |
| Python/OS 검증 축 | CI 구성 완료, 원격 결과 미확인 | Windows 3.10 및 macOS/Linux 3.15의 pinned dependency 설치·핵심 회귀·소스 창 생성 smoke job 추가. 기존 Windows 3.15 전체 gate 유지. 이 로컬 실행이 타 OS 또는 원격 CI 성공을 뜻하지 않음 |
| 장기 검증 재현성 | fixture·절차 추가 | `KACC_SOAK_SECONDS`로 queue/thread/archive/JSON/DB/reload soak를 선택 실행. 이번 10초 실행 통과. 실제 중계 2시간·네트워크 단절·HWP 잠금·업데이트 중단·물리 볼륨의 입력/기대 결과는 release checklist에 구체화 |
| 문서·품질 gate | 반영 | README 빌드 파일명·복구 UX·CI 범위, CLAUDE·PIPELINE_LOCK 정합화. 새 Qt 회귀를 CI와 release verifier의 명시적 gate에 포함 |

### 이번 후속 작업의 실제 검증

- 격리 소스에서 Chrome 오프라인 DOM 포함 전체 pytest: **723 passed / 3 skipped / 73.99초**. skip은 opt-in soak, live API smoke, subprocess 환경의 in-process pyright fallback이다. 앞의 두 검사는 별도로 아래와 같이 실행했다.
- 새 회귀·세션 통합을 `KACC_SOAK_SECONDS=10`으로 실행: **25 passed / 13.45초**. 이는 실제 중계 수 시간의 soak 결과가 아니다.
- 실제 국회 live-list API 계약: **1 passed / 0.13초**. 실제 중계 자막 Selenium E2E·장시간 재연결 검증과 구분한다.
- pyright: **202 files / 0 errors / 0 warnings**.
- Windows ARM64 PyInstaller **새 빌드 성공**. frozen `--smoke --smoke-instantiate-window`는 **exit 0**, imports/resource/storage/HWPX/창 생성 모두 성공했다.
- 같은 볼륨의 임시 target/staged/backup EXE로 실제 frozen `--apply-update --update-no-relaunch`: **exit 0 / applied**, 교체 후 child smoke 및 파일 바이트 확인. 임시 backup의 frozen `--recover-update`: **exit 0**, target 복원 확인. 기존 설치본과 사용자 저장소를 대상으로 하지 않았다.
- 실제 한컴 COM의 **독립 DispatchEx 인스턴스 생성·Version 조회·Quit 성공**(12, 0, 0, 4637). 파일 접근용 `SecurityModule` 등록은 False였으므로 문서 저장·재열기 시험은 진행하지 않았다. 이를 실제 HWP 출력 검증 성공으로 계산하지 않는다.
- 검증 중 기존 fake-host 테스트는 snapshot 메타데이터를 UI에서 확보하는 새 경계에 맞게 초기화했다. concurrency 테스트의 barrier는 메타데이터 getter에서 실제 writer로 이동하여 기존 entries/manifest 동시 변경 assertions를 유지했다.

검증 소스·테스트 출력은 `%TEMP%/kacc-fixes-0fb0934220164c2f91fb5a9890163a6c`와 `%TEMP%/kacc-fixes-*.log`, 빌드·frozen/COM 증거는 해당 소스 경로에 `-build`를 붙인 디렉터리에 보관했다. 원본 DB·세션·백업·설정은 시험 대상으로 사용하지 않았다.

### 남은 외부·실기기 확인

실제 생중계 2시간 이상 운용과 네트워크 단절 반복, 한컴 파일 접근 모듈이 준비된 환경의 저장·열기·잠금 실패, Windows x64 frozen, 서로 다른 물리 볼륨, 전원 차단 복구, 새 compatibility job의 실제 원격 결과는 남아 있다. 서명 인증서와 공개 배포 채널도 변경하지 않았다. 구체적인 입력·통과 기준은 `docs/RELEASE_CHECKLIST.md`의 2026-11-05 항목에 있다.

수정 후 로컬 검증 범위의 평가는 **Acceptable**이다. 세 확정 결함의 수정과 자동 회귀 통과를 확인했으나 위 실환경 검증까지 완료했다고 주장하지 않는다. 원 감사의 High Risk 판정은 수정 전 상태의 기록으로 보존한다.

---

**아래는 수정 전 원 감사 기록이다.**

감사일: **2026-11-05 (Asia/Seoul)**

대상: **Korea Assembly CC v16.14.16 / main / 2b7af3a**

방식: 기능 구현·런타임 안정성 감사. **원 감사 당시 제품 코드·테스트·설정은 수정하지 않았으며, 당시 저장소 변경은 이 보고서뿐이었다.**

이 문서는 현재 커밋에 대한 새 감사다. `PROJECT_AUDIT_ADDITIONAL.md`, `PROJECT_AUDIT_EXTENDED.md`, `PROJECT_AUDIT_FINAL.md`의 과거 수정·검증 기록을 현재 미해결 결함으로 재분류하지 않았다. 아래 ISSUE 번호는 이 문서 안에서만 사용한다.

## 1. Executive Summary

핵심 기능은 구현되어 있고 기존 회귀 범위도 넓다. URL 검증, 수집 run 식별, bounded queue, JSON 자원 제한, archive 무결성 검사, atomic 파일 교체, SQLite transaction·중복 저장 방지, 업데이트 서명·해시 검증 등 중요한 방어 장치를 확인했다. 기존 전체 테스트는 **706 passed / 2 skipped**, pyright는 **201 files / 0 errors / 0 warnings**, 격리 저장소에서 소스 창 생성 smoke는 성공했다.

그러나 저장·종료 경계에서 **High / Confirmed 3건**이 남아 전체 위험도는 **High Risk**로 평가한다. 별도 임시 재현 검사 6개가 이 세 결함에서 실패했다. 기존 테스트 통과가 이 경계까지 보장하지 않는다.

| 우선순위 | 이슈 | 핵심 결과 |
|---|---|---|
| 1 | ISSUE-001 — 저장 대화상자 전후 snapshot/revision 불일치 | 메모리 자막 2개, JSON 저장 1개인데 dirty=False. DB도 이전 snapshot 저장 |
| 2 | ISSUE-003 — 종료 시 fallback 확정의 부수 효과 누락 | 화면에는 자막이 생기지만 dirty=False, revision 증가 없음, 실시간 TXT·키워드 알림 없음 |
| 3 | ISSUE-002 — 종료 메시지가 대기 자막보다 먼저 처리됨 | 실제 기본 큐 용량 500에서도 마지막 preview가 폐기되어 자막 0개 |

**데이터 손상/유실:** 기존 DB·파일의 물리적 파괴나 임의 외부 명령 실행은 확인하지 않았다. 다만 새 발언이 저장되지 않거나 저장 필요 상태를 잃는 **논리적 자막 유실 가능성은 확인했다.** 저장 완료 뒤 종료·세션 교체를 하면 누락분을 다시 요구하지 않을 수 있다. 기존 백업이 일부 구간을 살릴 가능성과 누락 방지를 보장하는 것은 구분해야 한다.

가장 먼저 수정할 영역은 **snapshot과 revision의 동일 시점 확보**, **종료 시 commit의 일관성**, **terminal 처리 전 해당 run의 pending 데이터 소진**이다.

## 2. Project Understanding

### 목적과 실행 환경

국회 의사중계 사이트의 AI 자막을 Selenium Chrome으로 수집하고 PySide6 화면에서 검색·편집·병합하며, JSON 세션·SQLite 히스토리 및 TXT/SRT/VTT/DOCX/HWPX/HWP/RTF로 보존하는 데스크톱 앱이다. Windows가 기본 지원 대상이고 HWP 출력은 Windows 한컴 COM에 의존한다. Chrome 확장 제품은 별도 저장소이며 본 감사 대상이 아니다.

`README.md`, `CLAUDE.md`, 전달된 AGENTS 지침, `requirements-dev.txt`, `pytest.ini`, `pyrightconfig.json`, `.github/workflows/ci.yml`, `subtitle_extractor.spec` 및 기존 감사 기록을 확인했다. 루트에는 실제 `AGENTS.md` 파일이 없었으므로 대화에서 제공된 CodeGraph 우선·main 직접 작업 지침을 적용했다.

### 주요 entrypoint와 모듈

| 영역 | 주요 파일·심볼 | 역할 |
|---|---|---|
| 앱 시작 | `국회의사중계 자막.py::main` | CLI 분기, import, 저장소 preflight, QApplication·MainWindow 생성 |
| UI 조립·상태 | `ui/main_window.py::MainWindow`, `runtime_state.py` | mixin 조립, 타이머·큐·설정·DB 초기화 |
| 수집 lifecycle | `runtime_lifecycle_extraction.py`, `runtime_lifecycle_stop.py`, `capture_browser.py` | 입력 검증, run 시작·중지, WebDriver·재연결 |
| 관측·commit | `pipeline_queue.py`, `pipeline_messages.py`, `pipeline_state.py`, `core/subtitle_pipeline.py`, `core/live_capture_impl/` | 큐 전달, stable row ledger, fallback 안정화, 증분 자막 확정 |
| 화면·사용자 변경 | `view_render.py`, `view_search.py`, `view_editing.py` | 렌더·검색, 편집·삭제·복사와 dirty 갱신 |
| 세션·복구 | `persistence_session_*.py`, `persistence_runtime_*.py`, `core/recovery_candidates.py` | snapshot, 백업, segment/tail archive, 로드·취소·후보 검사 |
| 내보내기 | `persistence_exports_*.py`, `core/file_io.py`, `core/export_text.py`, `core/hwpx_export.py` | 형식 변환, background 저장, atomic 교체 |
| DB | `core/database_manager.py`, `core/database_impl/` | 연결·migration·CRUD·FTS·저장 계보·operation ID |
| 업데이트 | `core/update_manifest.py`, `core/update_installer.py`, `scripts/apply_update.py` | 서명 검증, artifact 확인, helper 교체·smoke·rollback |

### 저장과 공유 상태

- `capture_state.entries`가 자막 원본 상태이고 `self.subtitles`는 alias다. `live_capture_ledger`는 DOM row identity와 commit 상태를 관리한다.
- `_session_revision`/dirty, `_active_capture_run_id`, worker sequence와 coalesced/terminal 큐, runtime archive token·manifest·tail revision이 핵심 공유 상태다.
- 일반 세션 JSON과 DB는 저장 시점의 snapshot이다. 장시간 수집은 runtime segment + manifest + tail checkpoint를 사용한다. JSON reader에는 byte·entry budget과 취소 검사가 있다.
- SQLite는 thread별 connection, manager의 RLock, foreign key, WAL, busy timeout을 사용한다. 저장의 session/자막/계보 갱신은 commit·rollback 경계에 있고 operation ID 중복은 unique constraint 충돌 후 재조회도 처리한다.
- 개발 실행은 repo root, portable은 EXE 위치, frozen 기본 실행은 `%LOCALAPPDATA%\AssemblySubtitle\Extractor`를 저장 루트로 쓴다. QSettings는 기본 native 저장소 또는 명시적 INI를 사용한다.
- 외부 의존성은 국회 웹사이트 DOM·live-list API, Chrome/WebDriver, 업데이트 HTTPS 서버다. DOCX는 python-docx, HWP는 pywin32·한컴, 업데이트 검증은 cryptography에 의존한다.

### 핵심 실행 흐름

```text
python "국회의사중계 자막.py"
→ main → storage preflight → QApplication → MainWindow → 시작/복구 UI

URL·selector 입력 → _start → URL/selector 검증 → _begin_extraction_run
→ _extraction_worker → Chrome·국회 DOM/Observer/probe
→ run/sequence가 붙은 preview → _process_message_queue → _handle_message
→ stable row commit 또는 fallback 안정화 → capture_state.entries
→ 렌더·revision/dirty·runtime tail·실시간 TXT·키워드 알림

세션 저장 → prepared entries + runtime manifest snapshot → 파일 대화상자
→ _start_async_session_snapshot_save → _write_session_snapshot
→ atomic JSON → recovery pointer → DB worker/transaction
→ session_save_done → saved revision 비교 → dirty 해제 또는 유지

파일/DB 불러오기 → 제한·무결성 검사·진행/취소 → background loader
→ 완료 메시지의 취소 재확인 → _complete_loaded_session → UI 세션 교체

중지/worker 종료 → pending preview 확정 → finalize_session → UI reset
→ 정상 앱 종료 시 dirty 확인·background 대기·archive/recovery 정리
```

## 3. Audit Coverage & Limitations

### 확인 범위와 CodeGraph 사용

`.codegraph/`가 존재함을 확인하고 **CodeGraph MCP `codegraph_explore`를 실제 사용했다.** 주요 호출·영향 관계는 다음과 같다.

- `_start → _begin_extraction_run → _extraction_worker`, 초기 driver session·재연결·종료 전달.
- `_emit_worker_message → terminal/coalesced 보관 → _process_message_queue → _handle_message`, `_retire_capture_run`의 영향.
- `_apply_structured_preview_payload → _commit_fallback_candidate / commit_live_row → _publish_capture_commit`, `_materialize_pending_preview → flush_pending_previews`의 차이.
- `_save_session → _start_async_session_snapshot_save → _write_session_snapshot → DatabaseSessionMixin.save_session`, 완료 메시지·revision 비교·dirty 보호.
- runtime segment reader의 경로·count/digest 검사, recovery 후보 탐색과 UI gate, DB 저장·삭제의 transaction과 계보 복원.
- export dispatcher의 중복 경로 보호, TXT/SRT/VTT streaming writer, 편집의 dirty 갱신, updater 서명·해시·rollback 경계.

CodeGraph의 응답이 큰 파일의 일부 body를 생략한 곳은 생략 부분만 직접 읽었다. 한글 이름 entrypoint 파일은 CodeGraph에서 관련 소스를 찾지 못해 직접 열람·symbol 검색으로 보완했다. CodeGraph가 보고한 caller 수는 색인 기반 참고치이며 Python mixin·Qt signal·`getattr`의 모든 런타임 연결을 보장하지 않는다. 실제 Qt 경로와 테스트를 함께 확인했다.

### 이번에 실행한 검증

환경: **Windows ARM64 / Python 3.15.2 / PySide6 6.12.0 / Selenium 4.51.0 / pytest 9.1.1 / pyright 1.1.414**. dependency 설치는 하지 않았다. Git 추적 소스·설정·자원을 임시 위치로 복사했고 사용자 DB·세션·백업은 복사·변경하지 않았다. 실제 Qt fixture는 임시 DB·INI·세션 경로를 사용했다.

| 검증 | 명령·방법 | 이번 결과 |
|---|---|---|
| 기존 전체 회귀 | 임시 소스에서 `python -m pytest tests -q --tb=short -ra`, `QT_QPA_PLATFORM=offscreen`, `KACC_TEST_BROWSER=chrome` | **706 passed / 2 skipped / 71.63초** |
| 정적 검사 | 임시 소스에서 `pyright --outputjson` | **201 files / 0 errors / 0 warnings** |
| 소스 CLI smoke | entrypoint의 `--smoke --smoke-instantiate-window --smoke-storage-dir <temp> --smoke-output <temp>` | **exit 0**, imports/resource/storage/HWPX/창 생성 성공 |
| 새 결함 재현 | 저장소 밖 임시 pytest 3개 파일, 해당 6개 검사 선택 | **6 failed / 1 deselected / 1.10초**. 실패 assertion이 아래 3건의 결함 증거 |
| 복구 gate 관측 | 포인터 없이 유효한 backup JSON을 두고 startup recovery 호출 | 후보 탐색 미호출 확인. 의도·정상 종료 gate를 고려하여 버그로 확정하지 않음 |

전체 회귀의 skip은 실제 국회 live-list smoke(`RUN_LIVE_SMOKE` 미설정)와 subprocess 가능 환경에서 불필요한 in-process pyright fallback 각 1개다. Chrome 오프라인 DOM 회귀는 실행되었다. 이는 실제 국회 생중계 Selenium 접속·재연결 E2E가 아니다. 기존 E2E fixture도 초기 driver session을 대체하므로 사이트 접속·자막 활성화 전체를 검증했다고 볼 수 없다.

초기 검증에서는 임시 복사본의 `.vscode/settings.json` 누락 및 감사용 파일의 BOM/PowerShell UTF-16 출력 때문에 인코딩 검사에 실패했다. 복사본을 보완하고 감사 증거를 소스 트리 밖으로 옮긴 후 위 **전체 통과 결과**를 다시 얻었다. 이 준비 오류들을 제품 결함에 포함하지 않았다.

### 증거 보관과 재현

- 임시 소스: `C:\Users\soulb\AppData\Local\Temp\kacc-audit-d3a0861c9a834a7cb7ce33534925bd89`
- 별도 증거: 위 경로에 `-evidence`를 붙인 디렉터리.
- 전체 로그: 임시 소스의 `audit-pytest-clean.log`.
- 증거 디렉터리: `audit-confirmed-issues.log`, `audit-pyright.json`, `smoke-result.json`, `audit_queue_probe.py`, `audit_finalization_probe.py`, `audit_save_revision_probe.py`.
- 재현 검사는 기존 `qt_window` 임시 fixture를 재사용했다. 저장 검사에는 실제 Qt `QFileDialog`의 비native modal event loop를 사용하고, 그 안에서 QTimer로 production commit 메서드를 호출했다. 실제 중계 신호를 주입한 것은 아니다.

### 확인하지 못한 범위

실제 생중계 장시간 운용, 사이트 변경, 네트워크 단절·복구 실기기, 한컴 COM 제품에서 결과 열기, 신규 frozen EXE 빌드·서명·배포, Windows x64, macOS/Linux, 물리적으로 다른 볼륨, 전원 차단·디스크 고장·공유 잠금 실기기는 이번에 검증하지 않았다. 과거 보고서의 frozen/실서비스 결과는 이번 실행 결과로 계산하지 않았다. 보안 검토는 관련 입력·경로·SQL·업데이트 흐름에 한정되며 전체 침투 테스트나 의존성 취약점 조사는 아니다.

## 4. High-Risk Issues

### [ISSUE-001] 저장 대화상자 이전 데이터에 이후 revision을 붙여 미저장 변경을 지움

- **위치:** `ui/main_window_impl/persistence_exports_session.py:27–55::_save_session`, `persistence_session_save.py:37–71::_start_async_session_snapshot_save`, `pipeline_messages.py:389–437::session_save_done`.
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** `_save_session`은 파일 선택 전에 entries와 runtime context를 준비한다. 대화상자에서 돌아온 뒤 `_start_async_session_snapshot_save`가 **그때의 최신 revision**을 읽어 이전 entries에 부여한다. 대화상자가 열린 동안 수집이 진행되면 snapshot 내용과 revision이 다른 시점을 나타낸다.
- **발생 조건:** 수집 중 저장 대화상자의 modal event loop가 Qt timer·queued 처리를 허용하고 새 자막이 commit되는 경우. 실제 Qt 비native 파일 대화상자로 재현했다. Windows native 정적 파일 대화상자는 timer 동작이 다를 수 있으므로 모든 Windows 설정에서 동일 빈도로 발생한다고 주장하지 않는다.
- **영향:** JSON·DB에 새 발언이 빠졌는데 dirty가 해제되고 복구 포인터도 정리될 수 있다. 이후 닫기·불러오기는 미저장 경고를 건너뛸 수 있어 새 발언이 유실된다.
- **근거:** `test_capture_during_real_modal_save_keeps_dirty`에서 첫 stable row 이후 저장을 시작하고 실제 파일 대화상자 안의 QTimer로 두 번째 stable row를 추가했다. 완료 후 관측값은 `memory=['첫 발언','새 발언']`, `saved=['첫 발언']`, `dirty=False`였다. DB 저장 로그도 자막 1개다.
- **반증 확인:** worker 시작 **이후** 변경을 잡는 revision 비교 자체는 존재한다. 하지만 저장 시작 전에 생긴 변경을 이미 snapshot revision에 포함하므로 이 비교로 막지 못한다. clone은 변이를 막지만 시간 일치를 보장하지 않는다. atomic JSON과 DB transaction은 제공받은 과거 snapshot을 정상 저장할 뿐 누락을 감지하지 못한다.
- **호출/영향 범위:** CodeGraph의 `_save_session → _start_async_session_snapshot_save → _write_session_snapshot → DB save → _handle_message(session_save_done) → _clear_session_dirty/_clear_recovery_state`. 뒤이어 `_confirm_dirty_session_action`을 사용하는 종료·로드·병합·업데이트 판단에도 영향이 이어진다. runtime manifest도 파일 선택 전에 확보되므로 함께 시점을 고정해야 한다.
- **권장 수정 방향:** 경로 선택 후 entries·manifest·revision을 하나의 시점으로 확보하거나, 경로 선택 전 snapshot과 함께 당시 revision을 묶어서 전달한다. snapshot 이후 변경이 있으면 dirty와 recovery 근거를 유지한다. 데이터 없는 경우 등의 재검증도 같은 경계에서 수행한다.
- **필요한 회귀 테스트:** 파일 선택 중 stable/fallback commit 또는 runtime segment flush가 진행되는 실제 modal 테스트. 저장본이 최신 내용을 모두 포함하거나, 이전 snapshot 저장 시 dirty=True이고 종료 전 저장 질문이 반드시 나타나야 한다. JSON과 DB의 entries·revision 대응도 검사한다.

### [ISSUE-002] terminal 메시지 우선 처리와 run 폐기가 대기 preview를 유실시킴

- **위치:** `ui/main_window_impl/pipeline_queue.py:256–323,454–469`, `pipeline_messages.py:186–233,341–388`, `runtime_driver.py:635–670::_retire_capture_run`.
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** 큐가 차면 `finished`는 별도 terminal 목록, `preview`는 최신 snapshot 병합 영역에 들어간다. 큐 처리기는 terminal을 먼저 처리하고, `finished` handler는 preview 소진 전에 run을 폐기한다. 일반 큐의 해당 run 메시지는 stale로 거부되고 coalesced preview는 `_retire_capture_run`에서 삭제된다. `finished`가 일반 큐에 들어가더라도 남은 coalesced preview는 처리 전에 사라질 수 있다.
- **발생 조건:** UI 처리 지연·부하로 worker 큐가 포화된 뒤 worker가 종료되는 경우. 재연결 실패 등 자연 종료 경로가 해당한다. 사용자 `_stop`이 먼저 previews를 drain한 경우와 구분한다.
- **영향:** worker가 이미 관측한 마지막 자막이 UI·실시간 파일·이후 JSON/DB 어느 곳에도 commit되지 않는다. gap 복구용 마지막 full snapshot까지 폐기되므로 종료 뒤 후속 관측으로 복구할 수 없다.
- **근거:** `test_terminal_overflow_preserves_pending_previews`, `test_finished_preserves_coalesced_latest_preview`가 각각 큐 preview와 coalesced preview 유실을 재현했다. 작은 큐의 인위적 한계인지 반증하기 위해 **기본 용량 500**에서도 499개 status + 마지막 preview + overflow finished를 넣었다. `test_terminal_overflow_at_production_capacity`의 결과는 기대 `['끝 발언']`, 실제 `[]`였다.
- **반증 확인:** terminal 보존 장치는 종료 메시지 자체의 유실은 막지만 데이터 순서는 보장하지 않는다. sequence gap/full snapshot 보호도 run 폐기 후에는 작동하지 않는다. `_materialize_pending_preview`는 이미 state에 도달한 preview만 확정하므로 아직 큐 안에 있는 내용을 살릴 수 없다. `_stop`에는 명시적 drain이 있지만 worker `finished` 처리에는 같은 보호가 없다.
- **호출/영향 범위:** CodeGraph의 `_extraction_worker finally → _emit_worker_message → _stash_terminal_worker_message → _process_message_queue → _drain_terminal_worker_messages → _handle_message(finished) → _retire_capture_run`. 정상 큐의 `_unwrap_message_item`, 병합 큐, snapshot 복구·실시간 기록까지 영향.
- **권장 수정 방향:** 종료를 해당 run의 데이터 처리 완료 barrier로 다룬다. 그 run의 일반·overflow·coalesced preview를 순서와 full-snapshot 의미에 맞게 소진·확정한 뒤 run을 폐기한다. 종료 상태 반영은 멱등이어야 하고 예전 run이 새 세션으로 유입되지 않아야 한다.
- **필요한 회귀 테스트:** 기본 500 용량과 최소 용량에서 terminal overflow/일반 finished 양쪽을 검사한다. 마지막 stable row·unstable fallback·gap snapshot이 보존되고, 종료 두 번 처리 시 중복이 없으며, 재시작한 새 run에는 이전 자막이 들어오지 않아야 한다.

### [ISSUE-003] 종료 시 fallback 확정이 dirty·revision·실시간 기록·알림 갱신을 우회함

- **위치:** `ui/main_window_impl/pipeline_state.py:363–379::_materialize_pending_preview`, `core/subtitle_pipeline.py:333–352::flush_pending_previews`, `pipeline_messages.py:361–375`, `runtime_lifecycle_stop.py:57–65,98–108`.
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** 안정화 대기 중인 fallback preview를 종료 때 `flush_pending_previews`로 복제 state에 확정한 뒤 그 state를 live state로 바꾼다. 이 경로는 일반 commit의 `_publish_capture_commit`, `_mark_session_dirty`, `_mark_runtime_tail_dirty`, 초기 복구 snapshot 일정을 거치지 않는다. 순수 snapshot 준비 helper를 live mutation에 사용하면서 commit 부수 효과가 빠진다.
- **발생 조건:** 일반 `p.smi_word` 등 unstable row/container fallback이 마지막 관측 뒤 안정화 시간(기본 400ms)이나 재관측 횟수를 채우기 전에 수집이 중지·종료되는 경우. 마지막 관측이 아직 queue에 있는 ISSUE-002와 달리 **이미 UI에서 preview로 수신된 데이터**다.
- **영향:** 화면에는 마지막 발언이 보이지만 실시간 TXT에는 없고 키워드 알림도 발생하지 않는다. 이전 상태가 clean이면 마지막 발언이 생겨도 clean으로 남아 종료·불러오기에서 저장 질문을 생략할 수 있다. runtime tail revision도 그대로여서 체크포인트 최신성 판단이 실제 내용과 달라질 수 있다.
- **근거:** `test_final_fallback_is_written_and_alerted`에서 unstable preview 직후 finished를 처리하면 state에는 `예산안을 의결합니다`가 있지만 닫힌 실시간 파일 내용은 빈 문자열이었다. 별도 `test_final_fallback_marks_dirty_and_records_alert`의 관측값은 `texts=['예산안을 의결합니다']`, `dirty=False`, `revision_delta=0`, `keyword_notices=0`이었다.
- **반증 확인:** 정상 fallback timer commit에는 기록·dirty·초기 복구 처리가 있다. 하지만 finished는 먼저 후보 timer를 취소하고 별도 materialize 경로를 쓴다. `_sync_capture_state_entries`는 alias·통계·렌더를 갱신할 뿐 dirty·기록 처리를 하지 않는다. `finalize_session`은 timing/preview 정리만 한다. legacy `last_subtitle` finalize는 structured dict fallback의 일반 대체 경로가 아니다. 닫기는 dirty 검사 후 archive·recovery를 정리하므로 최종 저장 안전망으로 볼 수 없다.
- **호출/영향 범위:** CodeGraph의 `_handle_message(finished)` 및 `_stop → _materialize_pending_preview → _build_prepared_capture_state → flush_pending_previews/apply_preview → state 교체`. 영향을 받는 기능은 실시간 TXT, 키워드 알림, 저장 revision, 종료 보호, runtime 복구다.
- **권장 수정 방향:** 순수 snapshot과 live commit을 구분하고, 종료 시 새로 확정한 delta를 일반 commit과 같은 부수 효과 경로에 정확히 한 번 전달한다. 이미 commit한 내용은 다시 기록하지 않는다. 후보 timer 취소·stop의 is_running=False 상태에서도 최종 commit이 정상 반영되도록 한다.
- **필요한 회귀 테스트:** 빈 clean 세션 및 저장 직후 clean 세션에 unstable preview 1회를 주고 400ms 전에 `_stop` 또는 finished 처리. 최종 자막 보존, revision 증가·dirty=True, TXT 1회·키워드 1회, tail revision 갱신, 저장 질문 유지. 중복 finished/stop에도 중복 출력이 없어야 한다.

## 5. Potential Functional Gaps

이 절은 확정 버그 목록과 구분한다.

- **Confirmed Gap — 복구 포인터 없이 기존 백업을 찾는 사용자 경로:** `discover_recovery_candidates` 자체는 포인터 없이 백업·runtime 후보를 찾을 수 있지만 startup UI는 `_load_recovery_state()`가 없거나 실패하면 먼저 반환한다. 유효 백업만 둔 임시 검사에서도 discovery는 호출되지 않았다. 포인터 손상·분실 후 수동으로 복구 후보를 여는 기능을 검토할 수 있다. 단, 포인터 없음은 정상 종료 후에도 의도된 상태이므로 무조건 매번 자동 복구를 제안하는 변경이 정답이라고 단정하지 않는다.
- **Confirmed Gap — 복구 후보 탐색의 전체 작업량·응답성:** 후보마다 제한은 있으나 `discover_recovery_candidates`는 모든 후보를 검사·정렬한 뒤 `RECOVERY_CANDIDATE_MAX`로 자른다. UI startup 경로에서 호출한다. 전체 후보 수 budget·background 진행·취소가 필요한지는 대량 측정으로 판단해야 한다. 실제 시작 멈춤 시간을 재현한 것은 아니다.
- **Confirmed Gap — 검증 환경의 지원 범위 차이:** 문서는 Python 3.10+를 안내하지만 CI는 Windows/Python 3.15 한 축이다. 이번은 ARM64 한 환경뿐이다. 최소 Python·x64·다른 OS의 설치/소스 실행 검증이 필요하다. 현재 다른 버전에서 실행 실패한다는 의미는 아니다.
- **추정 — 장시간·다중 인스턴스 운영:** owner lease·operation ID·atomic 쓰기 보호는 있으나 실제 중계 중 수 시간의 큐 부하, 서로 다른 인스턴스의 공용 복구 포인터 운영 경험은 이번에 측정하지 못했다. 별도 soak test와 복구 UX 평가 대상으로 남긴다.

## 6. Documentation Mismatches

| 문서 | 설명 | 실제 확인한 차이 |
|---|---|---|
| `README.md:82`, `CLAUDE.md` revision 저장 규칙 | 저장 도중 수집·편집해도 미저장 변경을 정확히 유지 | 파일 선택 중 변경은 snapshot보다 최신 revision에 포함되어 ISSUE-001처럼 clean으로 오판 가능 |
| `CLAUDE.md` 자막 처리 흐름·종료 보호 | 중지 시 마지막 preview를 확정하고 mutation은 revision으로 보호 | 큐 포화 worker 종료의 preview 유실, materialize mutation의 dirty/실시간 부수 효과 누락이 남음 |
| `README.md:310` EXE 빌드 예시 | 결과 파일명 `v16.14.11.exe` | spec은 README 첫 줄의 버전을 읽어 현재 `v16.14.16` 이름 생성. 사용자가 예시 파일을 찾지 못할 수 있음 |

README의 macOS/Linux 전면 지원 문구는 **별도 Chrome 확장** 설명이므로 데스크톱 앱의 미검증 지원 약속으로 오해하지 않았다. 과거 버전별 통과 수치도 역사 기록으로 명시되어 있어 현재 수치와 다르다는 이유만으로 결함 처리하지 않았다. 과거 최종 감사의 Acceptable 평가는 그때의 범위이며, 이번 추가 재현 결과로 현재 평가는 달라진다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. **ISSUE-001:** entries·manifest·revision snapshot의 시점을 일치시키고 실제 modal 저장 회귀를 먼저 고정한다. 저장한 revision보다 새 데이터가 있으면 dirty·복구 근거를 보존한다.
2. **ISSUE-003:** stop/finished 최종 fallback 확정을 공통 live commit 경로에 연결한다. dirty·revision·실시간 기록·알림·tail 변경을 함께 처리하고 중복 부수 효과를 막는다.
3. **ISSUE-002:** terminal 처리 전 해당 run의 pending 데이터를 소진하도록 순서를 정한다. priority·sequence gap·run retirement를 하나의 종료 계약으로 검사한다.

### Phase 2 — Stability

- 실제 국회 중계에서 capture→저장 modal→재연결 실패→종료→재실행 복구 흐름을 검증한다.
- 복구 포인터 손상 시 안내와 수동 후보 탐색, 후보 전체 작업량 budget·진행·취소를 보완한다.
- 실제 한컴 COM, Windows x64 frozen, 다른 볼륨·공유 잠금·업데이트 중단 복구를 확인한다.
- Python 최소 지원 버전의 의존성 설치·소스 smoke를 별도 gate로 검증한다.

### Phase 3 — Structural

- entries·manifest·revision·메타데이터를 담는 immutable save context를 단일 생성 경계에서 만든다.
- 순수 snapshot 변환과 live commit을 API 수준에서 구별하고, live mutation의 후처리 책임을 한 곳에 둔다.
- terminal은 단순 상태 알림이 아니라 run의 데이터 처리 완료 계약으로 정의한다.
- 기존 fake-host 단위 테스트를 유지하면서 실제 Qt modal·queue·파일/DB를 잇는 경계 테스트를 CI에 추가한다.

**이 계획의 제품 코드 수정은 이번 감사에서 수행하지 않았다.**

## 8. Test Recommendations

| 분류 | 입력·실행 조건 | 기대 결과 |
|---|---|---|
| Unit / Regression — ISSUE-001 | revision 1의 snapshot 확보 후 파일 선택 동안 revision 2 mutation, revision 1 snapshot 저장 완료 | 저장본이 revision 1이면 dirty=True, recovery 유지, deferred destructive action 재개 금지 |
| Integration — ISSUE-001 | 실제 Qt 비native 파일 대화상자에서 QTimer로 새 row를 commit한 뒤 JSON+DB 저장 | JSON/DB 내용 일치. 누락 row가 있으면 반드시 dirty=True. 이후 로드/닫기에서 저장 질문 |
| Concurrency — ISSUE-001 | 저장 대화상자 동안 runtime segment flush 완료와 tail append를 교차 | snapshot에 segment와 tail의 누락·중복 없음. 저장 revision과 포함된 항목이 동일 시점 |
| Unit / Integration — ISSUE-002 | 기본 500 큐: status 499 + stable preview 1 + finished overflow | 마지막 preview commit 후 run 종료. 마지막 자막·TXT·snapshot에 같은 내용 존재 |
| Concurrency — ISSUE-002 | preview를 coalesced로 이동한 뒤 finished가 일반 큐 또는 terminal stash로 도착 | 양쪽에서 마지막 full snapshot 적용. queue gap 이후 종료에도 누락 없음 |
| Regression — ISSUE-002 | 동일 run finished 2회, 직후 새 run 시작, 늦은 예전 preview 도착 | 최종 확정·기록 각 1회, 새 run에 stale 데이터 없음 |
| Unit / Regression — ISSUE-003 | clean 빈 세션에 unstable preview 1회, 400ms 전에 finished | 최종 자막 1개, dirty=True, revision 증가, tail revision 증가, TXT·알림 각 1회 |
| Integration — ISSUE-003 | stable 자막 저장 후 clean 상태에서 마지막 fallback을 받고 즉시 stop·종료 | 마지막 fallback 저장 요구. 마지막 저장 뒤 새 발언이 조용히 사라지지 않음 |
| End-to-End | Chrome 오프라인 DOM→실제 worker/Qt→실시간 TXT→JSON/SQLite→SRT→재로드, 중간에 modal 저장·종료 부하 주입 | 발언 identity·화자·text·시간과 총 개수 보존. 독립 정상 경로 통과뿐 아니라 경계 조합도 검증 |
| Integration — 파일·DB 실패 | JSON atomic replace 실패, DB batch 중간 예외, 같은 operation ID를 두 manager에서 동시 저장 | 기존 파일·이전 lineage 유지, rollback 후 재시도 가능, 중복 session/자막 없음 |
| Integration — 로드·복구 | missing/tampered segment, path traversal, byte/entry 초과, 완료 메시지 직전 취소 | 현재 세션 유지, 외부 파일 접근 거부, 오류/취소 안내, 부분 결과 정상 적용 금지 |
| Platform-specific | Windows native/비native 파일 대화상자, x64/ARM64, 문서화한 최소 Python, macOS/Linux 소스 smoke | modal timer 차이를 명시하고 저장 상태 일관성 유지. 지원 대상별 설치·저장소·종료 성공 |
| Platform-specific — HWP·업데이트 | 실제 한컴 파일 잠금·SaveAs 실패; 다른 볼륨 staging·업데이트 helper 중단 | 기존 HWP/설치 EXE 보존, 실패 안내, 복구 launcher 동작·결과 파일 정확성 |
| Soak / Resilience | 수 시간 capture, UI 지연과 네트워크 단절 반복, 디스크 쓰기 실패 후 중지·재실행 | bounded 메모리, 명시적 오류·drop 진단, 마지막 성공 복구 지점까지 일관되게 로드 |

위는 권장 테스트다. 이번 실행 여부는 §3에 기재한 항목만 해당하며, 실기기·soak 권고를 실행 완료로 간주하지 않는다.

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Needs Work | 주요 정상 기능은 회귀 통과하지만 저장 modal과 종료 최종 commit에 확정 누락 |
| Runtime Stability | Needs Work | 큐·thread·driver 보호는 있으나 terminal과 data 순서가 종료 시 깨짐 |
| Data Integrity | High Risk | 누락된 저장본을 clean으로 인정하고 마지막 발언의 dirty를 잃는 사례 재현. 물리 DB 파괴와는 구분 |
| Error Resilience | Needs Work | atomic/transaction/취소 보호는 양호하나 종료·복구 판단에 사용하는 상태가 불완전 |
| Cross-platform Robustness | Acceptable | Windows ARM64의 이번 소스 회귀·창 생성 범위에서 통과. x64·한컴·다른 OS·최소 Python 판정은 보류 |
| Test Confidence | Needs Work | 기존 706개 통과·타입 검사와 별개로 실제 modal/terminal 경계의 6개 추가 검사가 실패 |

**실제로 먼저 수정할 문제 3개:**

1. **ISSUE-001:** 저장 snapshot과 revision의 시점 불일치로 누락된 저장본을 clean 처리하는 문제.
2. **ISSUE-003:** 종료 시 마지막 fallback 확정에서 dirty·실시간 기록·알림·복구 상태가 빠지는 문제.
3. **ISSUE-002:** terminal 우선 처리·run 폐기로 아직 처리하지 않은 마지막 preview가 유실되는 문제.
