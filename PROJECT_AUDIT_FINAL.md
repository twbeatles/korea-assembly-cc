# Project Audit — Final Verification

감사·수정일: **2026-11-03 (Asia/Seoul)**. 대상: v16.14.16, main. 앞선 [기능 감사](PROJECT_AUDIT.md), [추가 감사](PROJECT_AUDIT_ADDITIONAL.md)의 수정을 포함한다. 이 문서는 마지막 점검과 검증 범위를 기록한다. 배포·원격 푸시·업데이트 manifest 게시는 포함하지 않는다.

## 1. Executive Summary

마지막 범위는 앱 시작 시 복구 포인터 읽기, 복구 후보 검사, 문서·검증 명령·패키징 정합성이다. 복구 사전검사의 입력 제한과 경로 검증 누락을 재현하고 수정했다. 이전 감사의 HWP 원본 보존, stale 리플로우 거절, 부분 병합 적용 차단을 포함한 수정 상태를 다시 검증한다.

수정 후 전체 평가는 **Acceptable**이다. 이번 복구 문제 자체에서 데이터 파괴나 외부 전송은 확인하지 않았다. 기존 감사에서 확인한 편집·출력 파일의 유실 가능성은 회귀로 차단했다. 실제 한컴 COM과 장시간·대용량 운용의 실기기 검증은 남는다.

## 2. Project Understanding

PySide6 데스크톱 앱이 Selenium Chrome에서 국회 생중계 자막을 수집하고 JSON·SQLite·runtime archive에 보존하며 문서로 내보낸다. entrypoint는 `국회의사중계 자막.py`다.

```text
MainWindow 시작 → recovery pointer 제한 읽기 → 후보 탐색·manifest 검사
→ 사용자 복구 선택 → background session loader → resource/path/integrity 검사
→ UI 세션 교체 또는 오류 안내
```

복구 후보 정보는 미리보기이며 모든 segment 본문의 무결성을 보장하지 않는다. 실제 불러오기에서 별도의 경로·count·digest 검사를 수행한다. `valid`는 후보 검사 범위에서의 판정이다.

## 3. Audit Coverage & Limitations

- CodeGraph로 `core/recovery_candidates.py`와 `persistence_session_recovery.py`의 현재 소스, 시작·복구·archive caller, 기존 회귀를 확인했다. 설정·Markdown·실행 로그는 직접 확인했다.
- `tests/test_recovery_candidates.py`에 5개 회귀를 추가했다. 수정 전 5개 모두 실패했고 수정 후 9개 전체가 통과했다.
- 전체 pytest는 별도 임시 소스 복사본에서 수행하며 Chrome 오프라인 DOM fixture를 포함한다. 사용자 DB·백업·프리셋을 시험 대상으로 사용하지 않았다.
- 최종 전체 테스트·정적 검사·빌드 결과는 아래 검증 기록에 기재한다. 이전 보고서의 수치는 해당 시점의 기록으로 유지한다.
- 한컴 COM 실제 제품, 다른 물리 볼륨, macOS/Linux, 실제 중계의 장시간 연속 수집은 이번 최종 실행에서 검증하지 않는다. ARM64 빌드는 x64 배포 검증을 대신하지 않는다.

## 4. High-Risk Issues

### [ISSUE-013] 복구 사전검사의 입력 제한과 경로 검증 누락 — 수정 완료

- **위치:** `persistence_session_recovery.py::_load_recovery_state`, `core/recovery_candidates.py::inspect_recovery_candidate`.
- **우선순위:** Medium.
- **신뢰도:** Confirmed.
- **문제:** 시작 시 포인터는 무제한 `read_text/json.loads`를 사용했다. 후보 검사에서는 manifest의 segment/tail 경로가 archive 내부인지 확인하지 않았다.
- **발생 조건:** 손상·외부 편집 등으로 비정상적으로 큰 포인터가 생기거나, manifest에 `../outside.json` 또는 절대 경로가 들어가는 경우.
- **영향:** 포인터의 메모리·파싱 비용 제한이 우회되고, archive 밖의 tail JSON을 미리 읽어 복구 후보를 정상으로 표시할 수 있었다. 실제 대용량 장애 시간이나 데이터 외부 전송은 확인하지 않았다.
- **근거:** 크기 상한 64 bytes를 넘는 포인터가 승인됐다. segment/tail의 상대 탈출·절대 경로 4가지도 invalid로 판정되지 않았으며 외부 tail 읽기가 가능했다.
- **반증 확인:** 후보 탐색의 포인터 reader와 실제 session loader에는 이미 제한·경로 보호가 있었다. 하지만 UI 시작 경로의 포인터는 먼저 무제한으로 읽고, 후보 미리보기는 실제 loader보다 먼저 실행되므로 두 사전검사를 보호하지 못했다. 실제 loader의 보호 덕분에 이 문제를 임의 파일 복구·파괴로 분류하지 않는다.
- **호출/영향 범위:** CodeGraph의 `_prompt_session_recovery_if_available → _load_recovery_state / discover_recovery_candidates → inspect_recovery_candidate`; archive 유지·복구 후보 UI에도 영향.
- **수정:** 포인터는 기존 `read_limited_json_file`과 `URL_HISTORY_MAX_BYTES`를 사용한다. 후보 resource는 상대 경로만 받고 resolve 후 archive root 하위인지 검사해 외부 경로는 invalid 처리한다. 정상적인 파일 누락은 기존 warning 정책을 유지한다.
- **필요한 회귀 테스트:** 크기 초과 포인터는 None과 기존 정리 경로로 전달; 외부 tail/segment의 상대·절대 참조는 invalid이고 외부 파일을 읽지 않음; 기존 정상 후보 정렬·중복 제거·누락 경고 유지. 모두 구현했다.

## 5. Potential Functional Gaps

- **Confirmed Gap:** 복구 후보 탐색은 파일별 제한을 적용하지만 전체 후보를 검사한 뒤 표시 개수를 자른다. 후보가 매우 많은 경우의 응답성을 측정하지 않았다. 생성 시각 정렬·명시적 복구 포인터 우선순위를 보존하면서 background/progress 처리를 검토할 수 있다. 재현하지 않은 시작 장애로 단정하지 않는다.
- **Confirmed Gap:** 병합은 아직 UI 동기 경로다. byte·entry 누적 제한과 부분 결과 거절은 구현되어 있다. 대용량 UI 응답성 측정이 후속 작업이다.
- **확인 한계:** 실제 한컴 COM·파일 잠금의 성공/실패 검증은 대역 테스트와 구분한다.

## 6. Documentation Mismatches

README의 ARM64 frozen 검증 안내를 이번 실제 창 생성 smoke 결과에 맞췄다. GEMINI에 누락되어 있던 최신 감사 결과·동작 정책을 연결하고, 이전 버전의 테스트 수치는 역사 기록임을 명시했다. README/CLAUDE/GEMINI가 최종 감사와 같은 검증 범위를 가리키도록 정리했다. CI와 release verifier의 명시적 회귀 gate에 복구 후보 테스트를 포함했다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

완료: 이전 감사의 실시간 commit 전달, archive 읽기 실패, 관측 identity, HWP 원본 보존, stale 결과·부분 병합 차단. 원본을 보존하는 실패 정책을 회귀로 유지한다.

### Phase 2 — Stability

완료: JSON 자원 제한·취소, 프리셋 저장 rollback, 검색 선택, 복구 사전검사. 후속: 실제 한컴 COM·x64 빌드·다른 물리 볼륨에서 검증한다.

### Phase 3 — Structural

회귀 gate와 문서 연결을 정리했다. 대용량 병합·복구 후보 탐색은 측정 후 background 처리를 검토한다. 새 기능이나 배포는 이 감사의 버그 수정과 별도로 판단한다.

## 8. Test Recommendations

| 분류 | 입력 조건 | 기대 결과 |
|---|---|---|
| Unit/Regression | 포인터 크기를 상한보다 크게 작성 | 파싱 승인 없이 실패 처리, startup 예외 전파 없음 |
| Integration | manifest의 외부 tail/segment, 상대·절대 경로 | invalid 판정, 외부 JSON read 없음 |
| Integration | 정상 후보 2개, 중복 pointer, 누락 segment | 시간순 정렬·중복 제거·warning 정책 유지 |
| E2E | 오프라인 DOM 관측→worker→Qt→JSON/DB→SRT→reload | 화자·동일 발언 구분과 전체 자막 보존 |
| Concurrency | 별도 DB manager가 같은 operation ID 동시 저장 | 단일 session ID, 중복 자막 저장 없음 |
| Regression | export 실패, 저장 실패, reflow 중 세션 교체 | 기존 파일·현재 세션·프리셋 보존 |
| Platform-specific | ARM64 frozen 창 생성과 임시 storage | exit 0, 리소스·설정·창 생성 성공 |
| 실기기 후속 | 한컴 설치, 기존 HWP, 저장 취소·파일 잠금 | 실패 알림과 원본 보존, 성공 파일 실제 열기 |

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Acceptable | 주요 사용자 흐름과 오류 조건을 실제 Qt 회귀로 검증 |
| Runtime Stability | Acceptable | stale 결과·취소·입력 제한 보강, 대량 운용 측정은 남음 |
| Data Integrity | Acceptable | 실패 시 원본 보존·archive 무결성·DB 동시성 회귀 |
| Error Resilience | Acceptable | 실패가 성공 안내나 부분 세션 교체로 이어지는 경로 차단 |
| Cross-platform Robustness | Acceptable | Windows ARM64 검증 범위 한정, 한컴·다른 OS는 미검증 |
| Test Confidence | Acceptable | 자동 회귀·정적 검사·frozen smoke와 실기기 한계를 구분 |

가장 먼저 수정해야 했던 **HWP 파일 원본 보존**, **stale 리플로우의 최신 편집 덮어쓰기**, **부분 병합의 정상 결과 적용**은 모두 수정했다. 다음 우선 작업 3개는 실제 한컴 COM 검증, 대용량 병합 응답성 측정, 다수 복구 후보 탐색 응답성 측정이다.

### 최종 검증 기록

- Windows ARM64, Python 3.15.1, PySide6 6.12.0, 설치된 Chrome을 사용했다.
- 격리 소스: `%LOCALAPPDATA%/Temp/kacc-final-audit-5r79rlae/`.
- `KACC_TEST_BROWSER=chrome`, `QT_QPA_PLATFORM=offscreen`, `PYTHONUTF8=1`에서 전체 pytest **706 passed / 2 skipped**, **73.60초**. 로그: 격리 소스의 `final-tests.log`.
- `python scripts/check_before_push.py --pyright-only`: **201 files / 0 errors / 0 warnings**, sibling Chrome 확장 parity sync 통과.
- 문서 변경 후 `test_encoding_hygiene.py`, `test_version_sync.py`, `test_release_verification_script.py`: **11 passed**. 주요 Markdown 8개 문서의 로컬 링크 검사와 `git diff --check` 통과.
- `python -m PyInstaller --clean --noconfirm subtitle_extractor.spec`: **성공**. Windows ARM64, PyInstaller 6.22.3. 기존 dist의 사용자 DB·세션은 대상으로 삼지 않았다.
- 산출물: `dist/국회의사중계자막추출기 v16.14.16.exe`, **51,035,848 bytes**. 버전 증가·서명·배포는 수행하지 않았다.
- SHA-256: `510c6f0e2e344e61a208fe625310634b34b36c7e1ba361ab56ecd0f3750963d1`.
- source와 frozen 모두 `--smoke --smoke-instantiate-window --smoke-storage-dir <임시 경로>` **exit 0**. imports/resources/HWPX/storage/QApplication/MainWindow 생성 성공.
- EXE를 임시 portable 디렉터리에 복사하고 `portable.flag`를 만든 뒤 `--smoke-storage-preflight`: **exit 0 / portable**. 실제 dist의 사용자 데이터와 분리했다.
- 로그·JSON: 격리 소스의 `final-build.log`, `source-smoke-final.json`, `frozen-smoke-final.json`, `frozen-portable-preflight-final.json`, `artifact-info.json`.
