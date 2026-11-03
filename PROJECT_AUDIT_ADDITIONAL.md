# Project Audit — Additional Scope

최종 복구 경로 감사·통합 검증은 [PROJECT_AUDIT_FINAL.md](PROJECT_AUDIT_FINAL.md)를 참고하세요. 아래 701개 결과는 이 추가 감사 시점의 기록이다.

감사·수정일: **2026-11-03 (Asia/Seoul)** · 대상: **v16.14.16 / main 작업트리**. 이전 감사의 5개 수정 사항을 포함한 상태에서 추가 범위를 조사했다. 배포·버전 증가·푸시는 수행하지 않았다.

## 1. Executive Summary

검색·문서 출력·프리셋·병합·백그라운드 편집에서 **7개 Confirmed 이슈**를 확인하고 수정했다. High 2개, Medium 4개, Low 1개다. Critical로 판단할 근거는 발견하지 않았다.

가장 중요한 문제는 HWP 실패 시 기존 출력 파일을 훼손하거나 성공으로 오판하는 경로와, 지연된 리플로우 결과가 이후 편집한 내용을 덮어쓰는 race였다. 사용자 데이터에서 시험하지 않았으며 임시 데이터와 실제 Qt, HWP COM 대역으로 재현했다.

수정 전에는 출력 파일·편집 내용·프리셋의 논리적 유실 가능성이 있었다. 수정 후 회귀와 전체 검사에서는 해당 실패를 차단했다. **추가 범위의 수정 후 평가는 Acceptable**이며, 실제 한컴 COM·대규모 병합의 UI 응답성은 별도 실기기 검증 대상으로 남긴다.

## 2. Project Understanding

기존 목적·저장 구조는 [PROJECT_AUDIT.md](PROJECT_AUDIT.md)에 기록했다. 이번에는 다음 사용자 경로를 중심으로 조사했다.

```text
검색 입력 → 전체 세션 검색 worker → index/offset 직렬화 → UI 결과 수신 → render → QTextCursor 선택
HWP 메뉴 → snapshot → COM 본문 입력/SaveAs → 파일 확인 → 완료 또는 대체 형식 안내
프리셋 추가/수정/삭제/가져오기 → 이름·URL 검증 → JSON 저장 → 메모리·메뉴·알림
병합 dialog → 파일 목록/옵션 → 세션 읽기 → sort/dedupe → 현재 세션 교체
줄넘김 정리 → snapshot → background reflow → control queue → undo snapshot → 세션 교체
```

CodeGraph에서 `view_search → view_render`, `persistence_tools → pipeline_messages`, `database_dialogs_stats_merge → _merge_sessions`, 메뉴 action→프리셋 관리, 문서 export→background dispatch 관계를 확인했다. Qt callback과 새 source identity/revision 검사도 실제 테스트로 보완했다.

## 3. Audit Coverage & Limitations

- **검토:** `view_search.py`, `view_render.py`, `view_editing.py` 관련 호출, `persistence_tools.py`, `database_dialogs_stats_merge.py`, `persistence_exports_documents.py`, `core/hwpx_export.py`, `ui/history_presets.py`, `ui/dialogs.py`, `runtime_lifecycle_shutdown.py`, 변경 함수의 caller와 타입 계약.
- **반증:** 검색 결과가 실제로 dict로 전달되는지, 렌더링이 선택을 다시 없애는지, COM 실패 반환값과 기존 파일 확인이 어떤 순서인지, 프리셋 save wrapper가 실패를 caller에 전달하는지, 리플로우 동안 다른 편집/세션 교체가 가능한지, UI 병합의 부분 결과가 실제 적용되는지 확인했다.
- **검증 위치:** `%LOCALAPPDATA%/Temp/kacc-additional-audit-_r7ru3of/`의 별도 소스 복사본. 사용자 DB/세션·프리셋 파일을 대상으로 시험하지 않았다.
- **추가 회귀:** `tests/test_additional_audit_20261103.py` **16개**. 첫 10개 회귀는 수정 전 모두 실패했다. 이는 독립 버그 10개라는 뜻이 아니다. 이모지 선택은 별도 재현에서 기대한 `검색어` 대신 ` 검색`이 선택됐다.
- **전체 pytest:** `KACC_TEST_BROWSER=chrome`, `QT_QPA_PLATFORM=offscreen`, `PYTHONUTF8=1`에서 **701 passed / 2 skipped**, 73.96초. Chrome의 오프라인 DOM 회귀도 포함된다. 로그: `additional-full.log`.
- **pyright:** **201 files / 0 errors / 0 warnings**. `git diff --check` 통과.
- **frozen:** Windows ARM64 PyInstaller clean build 성공. 임시 저장소의 `--smoke --smoke-instantiate-window` **exit 0**, HWPX/resources/import/storage/창 생성 성공. QSettings INI도 임시 디렉터리에서 확인했다. 로그: `additional-build.log`, `frozen-smoke.json`.
- **한계:** HWP는 실제 COM 객체를 호출하는 production wrapper에 대역을 주입했다. 실제 한컴 버전별 동작·공유 잠금·파일 권한 호환성을 검증한 것은 아니다. 실중계 네트워크 E2E·다른 OS/아키텍처·장시간 부하를 새로 실행하지 않았다. CodeGraph가 생략한 함수 후반부와 테스트 계약만 직접 읽기/rg로 보완했다.

## 4. High-Risk Issues

다음은 **수정 전 발견 사항과 수정 후 상태**다. 모두 현재 수정·회귀 검증을 마쳤다.

### [ISSUE-006] archive 검색의 첫 자막 인덱스 및 선택 영역 손실

- **위치:** `ui/main_window_impl/view_search.py::_handle_runtime_search_done`, `view_render.py::_render_subtitles`.
- **우선순위 / 신뢰도:** Medium / Confirmed.
- **문제·발생 조건:** background 검색 결과의 `entry_index=0`을 `int(value or -1)`로 변환하여 `-1`로 바꿨다. 또한 후속 예약 render가 자동 스크롤을 수행하면서 검색 선택을 해제했다.
- **영향:** 첫 archived 자막 검색 결과를 찾고도 정확한 항목/문자열로 이동하지 못하거나 선택이 사라졌다.
- **근거·반증 확인:** worker가 실제 dict 결과를 발행하는 운영 경로이며 외부 validation이 0을 보정하지 않는다. 실제 segment+tail과 Qt queue를 사용한 테스트에서 확인했다. 인덱스 수정만으로는 event loop 이후 선택이 유지되지 않아 renderer도 검사했다.
- **호출/영향 범위:** `_do_search → background_search → runtime_search_done → _handle_runtime_search_done → _highlight_search → _render_subtitles`. 일반 검색 navigation·archive 검색 표시.
- **수정:** 0을 보존하고, render 뒤에도 현재 검색 결과의 문자 span을 선택한다.
- **회귀:** archived entry 0의 키워드 검색 후 실제 event loop를 처리해도 entry index=0, selectedText=키워드 유지.

### [ISSUE-007] Python 문자 offset과 Qt UTF-16 cursor offset 혼용

- **위치:** `ui/main_window_impl/view_render.py::_select_rendered_entry_span`.
- **우선순위 / 신뢰도:** Low / Confirmed.
- **문제·발생 조건:** 이모지 등 보조 평면 문자가 검색어 앞에 있을 때 Python code-point index를 Qt cursor position에 그대로 더했다.
- **영향:** 검색/DB 결과 focus의 선택 범위가 앞쪽으로 어긋났다. 본문 자체가 손상되는 결함은 아니다.
- **근거·반증 확인:** 실제 QTextEdit에서 `😀 검색어 끝`의 검색 결과가 ` 검색`으로 선택됐다. renderer의 시작/끝 위치는 이미 Qt 단위였고 하위 wrapper가 offset을 변환하지 않았다.
- **호출/영향 범위:** `_search_full_session_entries/_focus_loaded_session_result → _select_rendered_entry_span`. 같은 선택 helper를 사용하는 검색·DB focus.
- **수정:** normalized entry text의 prefix와 선택 문자열을 UTF-16 단위 길이로 변환한다.
- **회귀:** 이모지 뒤 한국어 검색어를 실제 QTextCursor로 정확하게 선택하며 기존 한글/ASCII 검색도 통과.

### [ISSUE-008] HWP COM 실패로 기존 파일이 손상되거나 성공으로 오판

- **위치:** `ui/main_window_impl/persistence_exports_documents.py::_save_hwp`의 `insert_text`, `do_save`, `do_save_with_error`.
- **우선순위 / 신뢰도:** High / Confirmed.
- **문제·발생 조건:** COM SaveAs가 사용자 target을 직접 썼고 실패 반환값을 확인하지 않았다. 기존 파일이 존재하면 새 저장이 실패해도 파일 존재/크기 검사만으로 성공할 수 있었다. 저장 중 부분 기록 후 예외가 나면 기존 파일도 훼손됐다.
- **영향:** 기존 HWP 문서 훼손, 잘못된 완료 알림, 일부 본문 입력 실패 누락.
- **근거·반증 확인:** production export/background 경로에서 SaveAs=False, 부분 기록 후 OSError, InsertText=False를 주입했다. retry는 원본을 복원하지 않으며 외부 export dispatch에도 HWP 전용 원자적 교체가 없었다. 한컴이 항상 예외를 발생시킨다고 가정하지 않았다.
- **호출/영향 범위:** HWP menu→`_save_hwp → _save_in_background → COM → result/대체 형식 안내`. HWP 선택 저장 경로에 한정한다.
- **수정:** 같은 디렉터리의 고유 임시 `.hwp`에 기록한다. 명시적 COM 실패 반환값·새 파일 크기를 검사하고 COM Quit 후 `os.replace`한다. 실패 시 임시 파일을 정리하고 기존 target을 보존한다.
- **회귀:** 실패 3종 모두 원본 byte 보존·실패 알림·COM 종료. 성공만 새 문서로 교체하며 COM의 실제 저장 경로가 target과 다른지도 확인.

### [ISSUE-009] 프리셋 쓰기 실패 뒤 메모리 변경과 성공 알림 유지

- **위치:** `ui/main_window_impl/ui/history_presets.py`의 save/add/manage/import.
- **우선순위 / 신뢰도:** Medium / Confirmed.
- **문제·발생 조건:** 파일 저장 wrapper가 예외를 로그/경고로 끝내고 caller에 실패를 전달하지 않았다. 추가·수정·삭제·가져오기 caller는 이미 메모리를 변경한 뒤 성공 알림·메뉴 갱신을 수행했다.
- **영향:** 화면과 디스크의 프리셋 상태가 달라지고 재시작하면 변경이 사라지거나 삭제한 항목이 다시 나타났다.
- **근거·반증 확인:** 실제 Qt 관리 흐름에 PermissionError를 주입했다. atomic JSON writer는 파일만 보존하며 caller 메모리 rollback·성공 알림 취소는 하지 않는다.
- **호출/영향 범위:** preset menu→add/manage/import→`_save_committee_presets`→JSON. 위원회/사용자 프리셋 및 메뉴.
- **수정:** 새 dictionary 사본을 저장하고 명시적 실패 시 기존 메모리 사본으로 되돌린다. 성공한 경우에만 메뉴/성공 알림을 반영한다.
- **회귀:** 추가·수정·삭제·가져오기 각각에서 파일/메모리의 기존 값 보존, success toast 없음.

### [ISSUE-010] 프리셋 이름 변경으로 다른 프리셋을 조용히 덮어씀

- **위치:** `ui/main_window_impl/ui/history_presets.py::_manage_presets`, `_add_custom_preset`.
- **우선순위 / 신뢰도:** Medium / Confirmed.
- **문제·발생 조건:** A를 이미 존재하는 B로 rename하면 A를 삭제한 뒤 B 값을 덮어썼다. 기존 B에 대한 충돌 검사가 없었다.
- **영향:** 사용자가 편집 대상으로 선택하지 않은 B의 URL이 사라졌다. 같은 이름의 추가도 같은 덮어쓰기를 수행했다.
- **근거·반증 확인:** A/B 두 항목을 가진 실제 Qt 관리 경로에서 확인했다. 삭제 확인은 이름 변경 분기에 적용되지 않았고 dict assignment 자체도 충돌을 알리지 않는다.
- **호출/영향 범위:** preset management→getItem/getText→dictionary 갱신→저장. 다른 사용자 프리셋에 영향.
- **수정:** 충돌 시 기본 No인 덮어쓰기 확인을 거치며, 이름/URL은 기존 공통 validator로 검사한다.
- **회귀:** A→B 변경을 거절하면 두 항목이 모두 그대로 유지된다. 일반 변경·정상 URL 기존 회귀도 통과.

### [ISSUE-011] 늦게 끝난 리플로우가 최신 편집/다른 세션을 덮어씀

- **위치:** `ui/main_window_impl/persistence_tools.py::_clean_newlines`, `pipeline_messages.py::reflow_done`.
- **우선순위 / 신뢰도:** High / Confirmed.
- **문제·발생 조건:** background 리플로우를 시작한 뒤 새 편집·세션 교체가 진행되어도 완료 결과를 무조건 적용했다.
- **영향:** 새 편집/새 세션의 내용이 이전 snapshot의 정리 결과로 교체됐다. undo도 결과 적용 직전에야 만들어져 사용자가 정상 완료로 오인할 수 있다.
- **근거·반증 확인:** worker 실행을 barrier 역할의 pending callback으로 지연하고 실제 Qt 세션을 교체한 뒤 완료시켰다. `_reflow_in_progress`는 같은 작업의 중복 실행만 막으며 다른 편집을 막지 않는다. snapshot clone은 worker 입력을 보호하지만 최신 UI 상태를 보호하지 않는다.
- **호출/영향 범위:** toolbar→`_clean_newlines → ReflowWorker → reflow_done → _replace_subtitles_and_refresh`. 현재 편집 내용과 세션 상태.
- **수정:** source entries identity와 snapshot revision을 함께 확인한다. 수집 중이거나 source가 교체/수정되면 오래된 결과를 버리고 다시 실행하도록 알린다.
- **회귀:** 최신 edit 보존, revision이 같은 clean 세션으로 교체해도 identity 검사로 보존. 정상 정리·undo 기존 회귀는 유지.

### [ISSUE-012] UI 병합의 부분 성공 적용 및 누적 입력 제한 누락

- **위치:** `ui/main_window_impl/persistence_tools.py::_merge_sessions`, `database_dialogs_stats_merge.py::_show_merge_dialog`.
- **우선순위 / 신뢰도:** Medium / Confirmed.
- **문제·발생 조건:** 손상 파일은 로그만 남기고 제외했으며, dialog는 나머지 부분 결과로 현재 세션을 교체했다. 여러 JSON의 bytes/entries 누적 상한도 없었다.
- **영향:** 선택한 파일 일부가 빠진 결과를 정상 병합으로 인식하고 저장할 수 있었고, 일반 JSON load에서 거절할 양의 입력을 병합에서는 받아들였다.
- **근거·반증 확인:** 정상 JSON+손상 JSON을 dialog에서 실행하면 경고 없이 정상 파일의 내용만 적용됐다. entry 상한 1에서 1개짜리 파일 2개도 거절되지 않았다. 기존 helper의 tolerant 동작을 고정한 테스트가 있어 그것을 dead code로 처리하지 않고 UI 적용 정책과 구분했다.
- **호출/영향 범위:** merge dialog→`apply_merge → _merge_sessions → _replace_subtitles_and_refresh`. 입력 파일 전체 및 교체되는 현재 세션.
- **수정:** UI는 `strict=True`로 파일/항목 오류를 명시적으로 거절하고 현재 내용을 보존한다. helper의 legacy tolerant 기본값은 호환성을 위해 유지하되 resource limit은 항상 적용한다. runtime manifest는 기존 strict loader로 읽는다.
- **회귀:** 부분 오류 UI에서 현재 세션 보존, 누적 entry/byte 상한 거절, 정상 runtime manifest 병합. 기존 tolerant 항목 skip·시간 버킷 dedupe 회귀도 통과.

## 5. Potential Functional Gaps

- **Confirmed Gap:** 병합은 현재 UI thread의 동기 경로다. 이번 수정은 입력 한도와 부분 결과 거절을 추가했으며 대규모 입력에서 progress/cancel 가능한 background 병합으로 전환한 것은 아니다. 실제 부하 측정 없이 새로운 장애로 확정하지 않는다.
- **확인 한계:** 한컴 COM의 실제 제품별 반환·잠금·보안 모듈 동작은 대역 테스트로 보장할 수 없다. Windows 실기기에서 기존 문서가 있는 성공/실패 저장을 확인해야 한다.

## 6. Documentation Mismatches

- 리플로우 확인창이 되돌리기 미지원이라고 안내했지만 완료 handler에는 undo snapshot이 있었다. Ctrl+Z 안내로 맞췄다.
- HWP에 일반 export의 파일 원자성 보장이 적용되지 않았다. 실제 구현을 동일 디렉터리 임시 저장/교체로 맞췄다.
- README/CLAUDE에 병합 strict 처리, 공통 budget, 프리셋 저장 실패/충돌 정책을 반영했다.

## 7. Recommended Fix Plan

- **Phase 1 — 완료:** HWP의 원본 보존과 COM 실패 검사, stale reflow 결과 거절.
- **Phase 2 — 완료:** 검색 index/선택/UTF-16 수정, 프리셋 rollback/충돌 확인, UI 병합 strict 검증·누적 resource budget.
- **Phase 3 — 완료:** preset commit 공통 helper로 저장/메모리 전이를 모으고 신규 회귀를 CI 및 release verifier에 포함.
- **후속 실기기:** 실제 한컴 COM·파일 잠금, 큰 병합의 UI 응답성, 장시간 사용 중 검색/편집 운용. 신규 배포는 별도 릴리스 절차에서 수행한다.

## 8. Test Recommendations

이번에 구현한 회귀는 `tests/test_additional_audit_20261103.py`에 있다. 추가 실기기 검증은 아래 조건으로 수행한다.

| 분류 | 입력/조건 | 기대 결과 |
|---|---|---|
| Integration | archive 첫 entry에 검색어, queued render 진행 | index 0과 선택 문자열 유지 |
| Platform/Regression | 이모지 앞/뒤의 한글·ASCII 검색 | 실제 QTextCursor가 정확한 substring 선택 |
| COM/Integration | 기존 HWP, SaveAs 취소·False·디스크/잠금 실패 | 기존 파일 byte 유지, 실패 안내, 임시 파일 정리 |
| Concurrency | reflow 실행 중 edit·다른 clean 세션 load·새 capture | 늦은 결과로 최신 상태를 교체하지 않음 |
| I/O/Regression | 프리셋 쓰기 권한 실패, 이름 충돌의 No/Yes | 실패는 메모리/파일 보존, 명시적 승인만 덮어쓰기 |
| Integration | mixed 정상/손상 JSON, runtime manifest, 누적 상한 | UI는 부분 결과 거절, 정상만 전체 적용, 한도 초과 거절 |
| Performance | 허용 최대 수준의 병합 파일 수/entry 수 | UI 응답 시간 측정 후 background 전환 필요성 판단 |

## 9. Final Assessment

| 항목 | 수정 후 평가 | 근거 |
|---|---|---|
| Functional Correctness | Acceptable | 실제 Qt 검색·편집·프리셋·병합 회귀 통과 |
| Runtime Stability | Acceptable | stale 결과 차단·입력 한도 적용. 대규모 동기 병합 응답성은 미측정 |
| Data Integrity | Acceptable | HWP 실패 원본 보존·프리셋 rollback·부분 병합 적용 차단 |
| Error Resilience | Acceptable | COM 실패 반환과 파일/JSON 실패가 사용자에게 전달됨 |
| Cross-platform Robustness | Acceptable | Qt UTF-16 수정, ARM64 frozen smoke 통과. 한컴/다른 OS 실기기는 별도 |
| Test Confidence | Acceptable | 701 passed, 2 skipped, pyright 무진단. COM 대역과 실제품 검증은 구분 |

이번 우선 수정 3개였던 **HWP 원본 보존**, **stale reflow 거절**, **부분 병합 적용 차단**은 모두 구현·회귀 검증을 마쳤다.
