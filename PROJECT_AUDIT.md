# Project Audit

감사 기준일: 2026-08-16. 이 보고서는 이번에 추가된 GitHub Releases 기반 업데이트 기능을 중심으로 한 기능 구현 감사다. 코드 수정은 수행하지 않았다.

## 1. Executive Summary

업데이트 기능은 서명된 manifest, HTTPS, 만료일, 버전·크기·SHA-256 검증, 별도 helper 프로세스, smoke 실패 시 롤백이라는 핵심 안전장치를 갖췄다. 관련 단위 테스트도 `20 passed`로 통과했다.

최초 감사 당시 전체 위험도는 **High**였다. 아래 3.1~3.4의 구현 문제는 2026-08-16에 수정했고, 관련 회귀 테스트를 추가했다. 남은 운영 위험은 실제 frozen Windows helper 통합 검증과 release asset/main manifest의 완전한 트랜잭션 보장이다.

## 2. Project Understanding

README와 CLAUDE에 따르면 이 프로젝트는 PyQt6 기반 Windows 데스크톱 앱으로, 국회 의사중계의 실시간 자막을 Selenium으로 수집하고 SQLite·세션 파일·내보내기 기능으로 보존한다. UI는 메인 스레드에서, 수집·저장·DB 작업은 worker와 queue를 통해 처리해야 하며, 종료와 dirty session 보호가 주요 개발 규칙이다.

CodeGraph 분석 결과 업데이트 흐름은 다음과 같다.

```text
MainWindow 시작 1초 후 / 도움말의 수동 확인
  -> MainWindowUIHelpMixin._check_for_updates()
  -> background UpdateCheckWorker
  -> download_release_manifest() + verify_release_manifest()
  -> AppControlMessageQueue (update_manifest_ready)
  -> _handle_update_manifest_ready()
  -> background UpdateDownloadWorker
  -> stream_update_artifact() + prepare_staged_update()
  -> AppControlMessageQueue (update_install_ready)
  -> _handle_update_install_ready() + launch_update_helper()
  -> 복사된 EXE의 --apply-update
  -> scripts.apply_update._wait_for_parent() + apply_staged_update()
  -> EXE 교체, --smoke, 실패 시 backup 복원
```

주요 구현 위치는 `core/update_manifest.py`(신뢰 검증), `core/update_installer.py`(다운로드 staging·교체·rollback), `ui/main_window_impl/ui/help.py`(사용자 흐름), `ui/main_window_impl/pipeline_messages.py`(control message 수신), `scripts/apply_update.py`(helper), `.github/workflows/release.yml`(빌드·서명·manifest 게시)이다.

확인한 테스트는 `tests/test_update_manifest.py`, `tests/test_update_installer.py`, `tests/test_apply_update_script.py`, `tests/test_update_startup.py`, `tests/test_build_update_manifest.py`이며, 실행 결과는 20 passed였다.

## 3. High-Risk Issues

### 3.1 릴리스 개인키와 앱 내장 공개키의 일치가 CI에서 검증되지 않음

상태: **해결됨** — `scripts/verify_update_release_key.py`와 release workflow 검증을 추가했다.

* 위치: `.github/workflows/release.yml`의 `Build signed-update artifact`, `scripts/build_update_manifest.py`, `core/config.py:366-369`
* 문제: 워크플로는 `KACC_UPDATE_PRIVATE_KEY_B64`로 manifest를 서명하지만, 배포 EXE가 신뢰하는 `Config.UPDATE_PUBLIC_KEY_B64`와 그 개인키가 한 쌍인지 검증하지 않는다. 워크플로의 `KACC_UPDATE_PUBLIC_KEY_B64`는 존재 여부만 확인되고 manifest 생성에는 사용되지 않는다.
* 영향: Secret 회전·오입력 시 GitHub Release와 `updates/latest.json`은 성공적으로 게시될 수 있으나, 배포된 모든 앱이 서명 검증에서 실패한다. 사용자에게는 업데이트 실패만 보이고, 릴리스 파이프라인도 이를 잡지 못한다.
* 근거: `build_update_manifest.py`는 private key만 로드해 서명한다. `release.yml`은 공개키의 non-empty 여부만 확인하며, `verify_release_manifest(..., public_key=Config.UPDATE_PUBLIC_KEY_B64)`를 생성 manifest에 실행하지 않는다.
* 권장 수정 방향: 빌드 단계에서 private key로부터 raw public key를 도출해 `Config.UPDATE_PUBLIC_KEY_B64`의 기본값과 byte 단위 비교하고, 생성된 manifest를 그 기본값으로 검증하라. 환경변수 override가 아닌 실제 frozen source의 값을 검증 대상으로 고정해야 한다.
* 우선순위: High

### 3.2 helper 적용/롤백 결과가 사용자와 앱에 전달되지 않음

상태: **해결됨** — helper result JSON과 다음 시작 알림을 추가했다.

* 위치: `core/update_installer.py:156-191`의 `launch_update_helper`, `scripts/apply_update.py:16-49`, `ui/main_window_impl/ui/help.py:208-267`
* 문제: 앱은 helper를 hidden process로 시작한 즉시 `QApplication.quit()`한다. helper의 예외, parent 종료 timeout, 파일 권한 오류, smoke 실패 및 rollback은 호출 앱에 전달될 수 없고 결과 파일·다음 실행 시 알림·로그 경로도 남기지 않는다.
* 영향: 업데이트가 실패하거나 백업으로 복원돼도 사용자는 앱이 종료된 이유와 실제 결과를 알 수 없다. 특히 설치 경로 권한 또는 백신 잠금처럼 현장에서 빈번한 Windows 오류의 지원·재시도가 어렵다.
* 근거: `Popen(..., creationflags=CREATE_NO_WINDOW)`은 stdout/stderr를 수집하지 않는다. `scripts/apply_update.main()`은 예외를 처리하거나 결과를 영속화하지 않으며, UI는 helper 시작 성공만 상태바에 표시한다.
* 권장 수정 방향: helper가 target 옆 또는 storage에 원자적 result JSON(성공/rollback/오류/버전/시간)을 기록하고, 다음 시작 시 앱이 이를 읽어 사용자에게 결과와 릴리스 페이지 fallback을 제공하도록 하라. helper 자체 로그도 남기고 stale result를 정리하라.
* 우선순위: High

### 3.3 자동 시작 업데이트 확인이 캡처 실행 상태와 경합할 수 있음

상태: **해결됨** — manifest 수신·다운로드 시작·설치 확정 직전에 활성 수집 상태를 재검사한다.

* 위치: `ui/main_window_impl/runtime_state.py:333-344`, `ui/main_window_impl/ui/help.py:31-33, 83-176`, `ui/main_window_impl/persistence_session.py:130-144`
* 문제: 수동 확인만 `_is_runtime_mutation_blocked()`로 막고, 시작 시 `interactive=False` 검사는 이를 우회한다. manifest 응답이 도착하기 전에 사용자가 캡처를 시작하면, 이후 설치 선택은 dirty session 여부만 확인하고 `is_running` 같은 활성 캡처 상태는 확인하지 않는다.
* 영향: 활성 캡처 중에도 사용자 승인 후 앱 종료·업데이트가 진행될 수 있다. 저장되지 않은 자막이 없거나 dirty 상태가 정확히 반영되지 않은 초기에 특히 의도치 않은 수집 중단이 가능하다.
* 근거: `_schedule_startup_update_check()`는 `_check_for_updates(interactive=False)`를 직접 호출한다. `_run_after_dirty_session_action()`의 구현은 dirty 세션 확인만 수행하며 실행 중 수집을 검사하지 않는다.
* 권장 수정 방향: manifest 수신 시점과 설치 확정 직전에 모두 활성 수집/저장/종료 상태를 재검사하라. 실행 중이면 설치를 보류하고, 캡처 중지 및 세션 저장 후 다시 시도하는 명시적 흐름을 제공하라.
* 우선순위: High

### 3.4 helper 시작 실패 경로는 수동 다운로드 fallback을 제공하지 않음

상태: **해결됨** — 정리 오류를 흡수하고 기존 실패 dialog/fallback을 재사용한다.

* 위치: `ui/main_window_impl/ui/help.py:208-262`
* 문제: 다운로드·검증 후 `launch_update_helper()`가 실패하면 staged 파일을 삭제하고 상태바 오류만 표시한다. 일반 업데이트 확인 실패의 `_handle_update_failure()`는 릴리스 페이지 버튼을 제공하지만 이 경로에서는 호출되지 않는다.
* 영향: 권한·파일 잠금·디스크 오류로 helper를 시작하지 못한 사용자가 즉시 안전한 대안인 GitHub Release로 이동할 수 없다. `staged.unlink()` 자체가 실패하면 UI handler에서 추가 예외가 발생할 가능성도 있다.
* 근거: 해당 `except` 블록은 `_set_status(...)` 후 return만 수행하며, unlink는 별도 예외 처리 없이 실행된다.
* 권장 수정 방향: 정리 실패를 별도로 기록하고, interactive 여부를 payload에 포함해 `_handle_update_failure()` 또는 동일한 릴리스 fallback dialog를 호출하라.
* 우선순위: Medium

### 3.5 release 이후 main manifest 게시가 원자적이지 않음

상태: **부분 완화됨** — workflow를 직렬화하고 tag commit의 main 포함 여부 및 rebase를 검증한다. GitHub Release 생성과 main push는 서로 다른 원격 변경이므로 완전한 원자성은 여전히 제공되지 않는다.

* 위치: `.github/workflows/release.yml`의 `Create GitHub Release`, `Publish latest manifest on main`
* 문제: Release asset과 manifest asset을 먼저 공개한 뒤, 별도 `git checkout main`/commit/push로 raw `updates/latest.json`을 갱신한다. 마지막 push가 branch protection, 충돌, 네트워크 오류로 실패하면 공개 릴리스는 존재하지만 앱이 조회하는 main manifest는 이전 버전 그대로다.
* 영향: 자동 업데이트 채널이 새 릴리스를 배포하지 못한다. 실패 알림·보상 처리·재게시 절차가 워크플로에 없다.
* 근거: 앱 기본 endpoint는 `.../main/updates/latest.json`이고, workflow의 마지막 단계 실패는 이미 생성된 GitHub Release를 되돌리지 않는다.
* 권장 수정 방향: manifest 게시 권한과 main 보호 규칙을 사전 검증하고, 실패 시 명확한 운영 알림을 남겨 재실행 가능하게 하라. 가능하면 immutable release asset을 기준으로 하거나 manifest publication을 release 전에 검증 가능한 단계로 분리하라.
* 우선순위: Medium

## 4. Potential Functional Gaps

다음은 실제 누락이 확정된 결함이라기보다, 운영 요구사항에 따라 보완 가능성이 높은 항목이다.

* **추정 — 업데이트 완료 뒤 재실행 경험:** 성공 시 helper는 새 EXE를 smoke만 하고 앱을 다시 실행하지 않는다. 의도된 정책이라면 UI에 “업데이트가 완료되면 다시 실행하세요”를 명시해야 하며, 자동 재시작을 원한다면 별도 opt-in 설계가 필요하다.
* **추정 — manifest 만료 운영:** manifest 기본 만료는 365일이다. 1년 동안 릴리스가 없으면 정상 앱도 만료 manifest를 거부한다. 만료 전 경고 또는 재서명만 하는 유지보수 작업이 없다.
* **추정 — backup 보존 정책:** 성공한 업데이트마다 target 폴더에 새 `.bak` 파일을 보존하지만 정리·보존 개수·복원 UI가 없다. 장기적으로 디스크 사용량과 사용자의 혼동이 누적될 수 있다.
* **추정 — 최초 updater 도입 버전의 전달:** updater가 없는 구버전은 manifest를 읽을 수 없으므로 최초 배포는 수동 설치가 필요하다. README의 설치/업데이트 안내에 이 전환 조건과 릴리스 페이지 fallback을 명시하는 편이 안전하다.
* **추정 — manifest URL/public key 환경변수 override:** `KACC_UPDATE_MANIFEST_URL`, `KACC_UPDATE_PUBLIC_KEY_B64`는 실행 환경에서 값을 바꿀 수 있다. 로컬 실행자가 자신의 환경을 조작할 수 있는 범위이므로 원격 취약점으로 보기는 어렵지만, 배포판의 신뢰 경계를 고정하려면 release build에서는 override를 비활성화하거나 명시적 개발 모드로 제한할 수 있다.

README/CLAUDE와 구현의 불일치도 확인됐다. README는 v16.14.9인데 빌드 산출물 예시는 v16.14.8이고, 업데이트 채널이 “배포 빌드에 설정해야 활성화”되며 개발 빌드는 두 값이 비어 있다고 설명한다. 실제 `Config`는 공개 endpoint와 공개키를 기본값으로 내장한다. CLAUDE의 프로젝트 버전과 최신 변경 기준도 v16.14.8로 남아 있다.

## 5. Recommended Fix Plan

### 1단계 — 즉시 수정

1. Release workflow에 private/public key pair 검증과 생성 manifest의 `Config` 기본 공개키 검증을 추가한다.
2. helper가 성공·실패·rollback 결과를 영속화하고, 다음 앱 시작 시 결과를 사용자에게 표시한다.
3. 자동 업데이트 흐름에서 캡처 실행, session save, shutdown 상태를 설치 직전 재검사해 업데이트를 보류한다.

### 2단계 — 안정성 개선

1. helper 시작 실패와 staged 정리 실패를 예외 안전하게 처리하고 릴리스 페이지 fallback을 일관되게 제공한다.
2. manifest 게시 실패를 배포 운영 장애로 명확히 알리고, 재실행 가능한 절차를 workflow/문서에 추가한다.
3. manifest 만료 사전 경고, backup 보존 개수/정리, 업데이트 결과 로그를 도입한다.

### 3단계 — 구조 개선

1. update state를 단순 boolean 대신 `checking/downloading/awaiting-confirmation/applying/deferred/failed` 상태 모델로 분리해 queue message와 UI를 명시적으로 연결한다.
2. release manifest publication을 tag/main 관계와 branch protection까지 검증하는 재현 가능한 release pipeline으로 정리한다.
3. README와 CLAUDE의 버전·기본 설정·업데이트 UX를 현재 구현과 동기화하고, 최초 수동 전환 및 실패 복구 운영 절차를 추가한다.

## 6. Test Recommendations

* CI에서 임시 Ed25519 private key와 `Config.UPDATE_PUBLIC_KEY_B64`의 일치/불일치 각각을 검증하고, 불일치 시 release 단계가 실패하는 테스트를 추가한다.
* frozen Windows 통합 테스트에서 helper EXE가 parent 종료를 기다린 뒤 target을 교체하고, 새 EXE smoke 성공·실패·rollback 결과 파일을 정확히 남기는지 검증한다.
* helper의 parent PID timeout, target 잠금/권한 거부, `Popen` 실패, staged 삭제 실패의 각 경우에 기존 EXE와 세션 데이터가 보존되고 UI fallback이 노출되는지 테스트한다.
* 자동 시작 검사 도중 캡처가 시작되는 순서를 재현해, 설치가 보류되고 수집이 종료되지 않는지 테스트한다. dirty session이 비어 있는 활성 캡처도 포함한다.
* `update_manifest_ready`, `update_install_ready`, 실패 message의 중복·역순 도착을 포함한 control queue 상태 전이 테스트를 추가한다.
* release workflow를 로컬 또는 reusable workflow 수준에서 검증해, main manifest 게시 실패가 명확히 감지되고 재게시 절차가 가능한지 확인한다.
* 문서 회귀 테스트 또는 release checklist 검사로 README, CLAUDE, `Config.VERSION`, spec 버전, 실제 artifact 명명 규칙의 일관성을 확인한다.
