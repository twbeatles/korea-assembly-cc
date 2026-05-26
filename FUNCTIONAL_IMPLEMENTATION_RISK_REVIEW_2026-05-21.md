# 기능 구현 리스크 후속 점검 및 정합성 보고서 (2026-05-21)

## 결론

- `FUNCTIONAL_IMPLEMENTATION_RISK_REVIEW_2026-05-18.md`의 후속 권고 5개를 모두 구현했고, 기존 2026-05-18 보고서는 삭제 상태로 정리했다.
- 현재 코드 기준으로 `README.md`, `CLAUDE.md`, `GEMINI.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`, `subtitle_extractor.spec`, `.gitignore`를 다시 대조했다.
- spec hidden import나 datas 추가는 필요하지 않다. 새 기능은 기존 `core.file_io`, `core.utils`, `ui.main_window`, `ui.main_window_impl.capture_live`, `ui.main_window_impl.persistence_session` import surface 안에서 수집된다.
- `.gitignore`는 현재 build/runtime/verification 산출물을 이미 덮고 있어 추가 수정하지 않았다. 새 보고서 Markdown은 ignore되지 않아 추적 대상이다.

## 구현 완료 항목

1. `--smoke-instantiate-window` 옵션 추가
   - 기본 `--smoke`는 기존 import/resource/storage 검증을 유지한다.
   - 옵션 사용 시 `QApplication` + `MainWindow()` 생성, title 확인, close/deleteLater/processEvents 정리까지 수행한다.
   - 실패 시 JSON에 `window_instantiated=false`, `error_type=window_instantiation`을 담고 exit code `2`로 종료한다.

2. live-list drift 진단 확장
   - 기존 `drift`는 xcode set drift 의미를 유지한다.
   - `api_code_to_names`, `api_code_to_descriptions`, `config_name_to_code`, `config_alias_to_code`, `name_mismatch`, `name_drift`를 추가했다.
   - `--fail-on-drift`, `--fail-on-name-drift` strict 옵션을 추가했다.

3. 자동 URL 보완 실패 원인 노출
   - `live_list` fetch/schema/network 실패 payload를 selection issue로 보존한다.
   - 최종 fallback 실패 시 status/toast에 `live_list 조회 실패(<error_type>): <error>` 형식으로 표시한다.

4. 백업/세션 파일명 충돌 방지
   - `core.file_io.next_available_path()`를 추가하고 `core.utils`에서 재수출했다.
   - 세션/백업 기본 파일명은 microsecond timestamp를 사용한다.
   - 자동 백업은 같은 tick 충돌 시 `_001`, `_002` suffix를 붙여 기존 파일을 덮지 않는다.

5. release verifier 옵션화
   - `scripts/run_release_verification.py`에 `--offline`, `--skip-live`, `--skip-build`, `--fail-on-drift`, `--fail-on-name-drift`, `--instantiate-window`를 추가했다.
   - 기본 실행은 기존 릴리스 전체 검증 흐름을 유지한다.
   - 개발 반복용으로 `python scripts/run_release_verification.py --offline --skip-build --instantiate-window`를 사용할 수 있다.

## 문서/spec/.gitignore 정합성

- `README.md`: 2026-05-21 후속 구현 항목, smoke/window 검증, live-list name drift, release verifier 옵션, 최신 검증 기준선을 반영했다.
- `CLAUDE.md`: AI 에이전트용 구현/검증 계약에 constructor smoke, strict drift, source-only release verification, 백업 파일명 충돌 방지 정책을 추가했다.
- `GEMINI.md`: 동일한 운영·검증 계약과 2026-05-21 변경 이력을 반영했다.
- `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`: 이번 변경이 운영 진단·검증·저장 파일명 hygiene 변경이며 글로벌 히스토리 + suffix 코어 의미론을 바꾸지 않는다고 명시했다.
- `subtitle_extractor.spec`: 새 기능은 기존 import surface로 수집되므로 hidden import 추가는 필요하지 않다. 주석만 constructor smoke와 source-only release script 옵션에 맞게 갱신했다.
- `.gitignore`: `build/`, `dist/`, `.pytest_tmp/`, `logs/`, `sessions/`, `backups/`, `realtime_output/`, `portable.flag`, `settings.ini`, `.storage_probe`가 이미 무시된다. `FUNCTIONAL_IMPLEMENTATION_RISK_REVIEW_2026-05-21.md`는 무시되지 않는다.

## 검증 결과

| 명령 | 결과 |
| --- | --- |
| `python -m pytest tests\test_file_io_safety.py tests\test_live_list_drift_report.py tests\test_release_verification_script.py tests\test_config_paths.py -q` | `27 passed` |
| `python -m pytest tests\test_ui_ux_plan_20260327.py tests\test_lossless_session_plan_20260401.py -q` | `61 passed` |
| `python -m pytest tests\test_pyright_regression.py tests\test_live_list_drift_report.py tests\test_config_paths.py -q` | `19 passed` |
| `python -m pyright --outputjson` | `113 files analyzed`, `0 errors`, `0 warnings` |
| `python "국회의사중계 자막.py" --smoke --smoke-instantiate-window --smoke-storage-dir .pytest_tmp\smoke-window-manual` | `ok=true`, `window_instantiated=true`, title 확인 |
| `python scripts\check_live_list_drift.py` | `row_count=20`, `dropped_rows=0`, `drift=false`, `name_drift=false` |
| `python scripts\run_release_verification.py --offline --skip-build --instantiate-window` | `243 passed, 1 skipped`, pyright 통과, source window smoke/preflight 통과 |
| `python scripts\run_release_verification.py` | `243 passed, 1 skipped`, live contract smoke 통과, `drift=false`, `name_drift=false`, PyInstaller clean build/frozen smoke/portable preflight 통과 |

## 종합 판단

현재 main 기준 구현은 README/CLAUDE/GEMINI/spec의 설명과 맞고, 2026-05-18 리스크 개선 내용도 회귀하지 않았다. 2026-05-21 후속 구현으로 constructor smoke, live-list name drift, live-list 실패 원인 노출, 백업 파일명 충돌 방지, release verifier 옵션화가 추가되어 운영 진단과 릴리스 검증 표면이 강화되었다.
