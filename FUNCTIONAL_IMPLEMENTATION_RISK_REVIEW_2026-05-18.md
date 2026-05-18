# 기능 구현 리스크 개선 및 문서 정합성 보고서 (2026-05-18)

## 검토 기준

- 기준 문서: `README.md`, `CLAUDE.md`, `GEMINI.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`
- 패키징 표면: `subtitle_extractor.spec`
- ignore 표면: `.gitignore`, `pytest.ini`, `pyrightconfig.json`
- 주요 코드 표면: `core/config.py`, `core/live_list.py`, `ui/dialogs.py`, `ui/main_window_impl/capture_live.py`, `ui/main_window_impl/pipeline_messages.py`, `ui/main_window_impl/persistence_runtime_*.py`, `core/database_impl/*`

## 반영 완료 내용

1. 생중계 URL 선택 정책을 안전하게 고정했다.
   - `Config.DEFAULT_URL`과 본회의 프리셋은 `xcode=10` 기준이다.
   - `특별위원회(xcode=91)`, `청문회/공청회(xcode=99)` 기본 프리셋과 약칭을 추가했다.
   - stale `IO` 기본 프리셋은 제거했다. 사용자가 이미 저장한 외부 프리셋 JSON은 강제 삭제하지 않는다.
   - `target_xcode`가 없으면 단일 live row도 자동 선택하지 않는다.
   - `resolved_url` 메시지는 `current_url`, URL history, `_capture_source_url`, `_capture_source_committee`를 모두 resolved URL 기준으로 갱신한다.

2. 생중계 목록 UI와 문서 정책을 맞췄다.
   - `LiveBroadcastDialog`는 `생중계`와 `종료/예정` row를 함께 표시한다.
   - `xcgcd`가 없는 row는 회색 안내 row로 표시하고 URL 적용을 차단한다.
   - `xcgcd`가 있는 non-live row는 기존 확인 prompt 뒤 URL만 입력한다.

3. runtime archive 무결성 검증을 추가했다.
   - segment/tail load 시 `entry_count`, `first_entry_id`, `last_entry_id`, `entries_digest`가 있으면 실제 entries fingerprint와 비교한다.
   - strict load에서는 `무결성 불일치` 오류로 실패한다.
   - recovery salvage에서는 불일치 파일을 제외하고 `recovery_warnings`에 `무결성 불일치`를 남긴다.
   - `tail_checkpoint.json`에는 entries fingerprint와 `tail_revision`을 기록한다.
   - fingerprint가 없는 기존 checkpoint는 legacy로 허용한다.
   - runtime recovery snapshot mismatch fallback은 `subtitle_lock` 안에서 clone snapshot을 만든 뒤 checkpoint를 다시 쓴다.

4. release/live-list drift 검증을 명령화했다.
   - `scripts/check_live_list_drift.py`: 실제 `live_list.asp` xcode set과 `Config` 프리셋/map 차이를 JSON으로 보고한다. drift 자체는 실패가 아니며 네트워크/스키마 실패만 실패 처리한다.
   - `scripts/run_release_verification.py`: pytest, pyright, source smoke, storage preflight, opt-in live smoke, drift report, PyInstaller clean build, frozen smoke, portable storage preflight를 순서대로 실행한다.

5. 파일 단위 pyright suppression을 제거했다.
   - repo source의 파일 단위 `# pyright:` directive를 제거했다.
   - mixin self 계약은 `ui/main_window_impl/contracts.py`, `ui/main_window_types.py`, `core/database_impl/contracts.py`로 관리한다.
   - `tests/test_pyright_suppression_policy.py`가 파일 단위 directive 재도입을 차단한다.

## spec / Markdown / .gitignore 정합성 점검

### `subtitle_extractor.spec`

- `core.database_impl.contracts`를 hidden import에 명시했다.
- release 검증용 `scripts/check_live_list_drift.py`, `scripts/run_release_verification.py`는 frozen 번들 대상이 아니며, 추가 datas가 필요 없음을 spec 주석에 명시했다.
- 기존 hidden import 범위는 `ui.main_window_impl.persistence_runtime_*`, `core.database_impl.*`, `core.subtitle_pipeline_impl.*`, `PyQt6.QtNetwork`까지 현재 분할 구조를 덮는다.

### Markdown 문서

- `README.md`, `CLAUDE.md`, `GEMINI.md`는 다음 정책을 현재 코드와 맞췄다.
  - 본회의 `xcode=10`
  - `특별위원회(91)`, `청문회/공청회(99)`
  - no-target 자동 선택 차단
  - 종료/예정 row 표시 및 `xcgcd` 없는 row URL 적용 차단
  - runtime archive fingerprint 검증
  - release verification/drift report 명령
  - 파일 단위 pyright directive 금지
- `PIPELINE_LOCK.md`는 stale `IO` 기본 프리셋 설명을 제거하고, 2026-05-18 live selection/runtime integrity 변경이 코어 자막 증분 파이프라인 의미론을 바꾸지 않는다는 점을 추가했다.
- `ALGORITHM_ANALYSIS.md`는 이번 변경과 충돌하는 알고리즘 설명이 없어 수정하지 않았다.

### `.gitignore`

대표 산출물 기준으로 ignore coverage를 확인했다.

- `.pytest_tmp/`, `.pytest_cache/`, `__pycache__/`
- `build/`, `dist/`, PyInstaller 보조 산출물
- `logs/`, `sessions/`, `backups/`, `runtime_sessions/`, `realtime_output/`
- `subtitle_history.db`, `url_history.json`, `committee_presets.json`, `session_recovery.json`
- `.claude/`

신규 추적 대상은 ignore되지 않음을 확인했다.

- `scripts/check_live_list_drift.py`
- `scripts/run_release_verification.py`
- `core/database_impl/contracts.py`
- `tests/test_pyright_suppression_policy.py`
- `FUNCTIONAL_IMPLEMENTATION_RISK_REVIEW_2026-05-18.md`

따라서 이번 정합성 점검에서 `.gitignore` 규칙 변경은 필요하지 않았다.

## 최종 검증

- `python scripts/run_release_verification.py`: 통과
- 내부 실행 결과: `pytest -q` `228 passed, 1 skipped`
- `python -m pyright --outputjson`: `0 errors / 0 warnings`, `111 files analyzed`
- source smoke: `ok=true`
- source storage preflight: `ok=true`
- `RUN_LIVE_SMOKE=1 pytest tests\test_live_contract_smoke.py -q`: `1 passed`
- `python scripts/check_live_list_drift.py`: row_count `20`, dropped_rows `0`, drift `false`
- `python -m PyInstaller --clean subtitle_extractor.spec`: 빌드 성공
- frozen EXE `--smoke`: 통과
- frozen EXE + `portable.flag` `--smoke-storage-preflight`: 통과

## publish 메모

- `FUNCTIONAL_IMPLEMENTATION_AUDIT_2026-05-06.md` 삭제 상태는 이번 2026-05-18 보고서로 대체되는 문서 정리로 함께 포함한다.
- 요청 범위에 따라 문서 삭제 상태와 신규 파일을 포함한 전체 worktree를 push 대상으로 둔다.
