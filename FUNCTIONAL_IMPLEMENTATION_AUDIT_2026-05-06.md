# 기능 구현 리스크 점검 및 개선 보고서 (2026-05-06)

## 검토 기준

`README.md`, `CLAUDE.md`, `GEMINI.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`, `subtitle_extractor.spec`, `.gitignore`, `requirements-dev.txt`와 실제 구현을 함께 대조했다. 중점 범위는 실시간 캡처 worker, bounded message queue, runtime archive, 세션 저장/복구, export, DB FTS, smoke/portable/frozen 패키징 표면이다.

## 반영 완료 항목

1. 저장/export/자동백업/리플로우 worker snapshot 불변성
   - `_build_persistent_entries_snapshot()`을 추가했다.
   - background I/O에 넘기는 active tail entry는 `SubtitleEntry.clone()`으로 freeze한다.
   - snapshot 생성 뒤 원본 entry가 변경되어도 저장/export 결과가 바뀌지 않는 회귀 테스트를 추가했다.

2. bounded queue 포화 시 terminal worker message 보장
   - `finished`, `error`, `subtitle_not_found`를 terminal worker message로 분리했다.
   - queue가 가득 차면 `_terminal_worker_messages` priority passthrough에 보존하고 일반 overflow보다 먼저 drain한다.
   - nonterminal non-coalesced message도 두 번째 `queue.Full`에서 worker 밖으로 예외가 전파되지 않도록 overflow 경로로 보낸다.

3. DB FTS rebuild 조건부화
   - FTS table/trigger 보장과 rebuild 필요 판단을 분리했다.
   - rebuild는 최초 생성, FTS 접근 오류, 최근 row sample probe 누락 등 drift가 의심될 때만 수행한다.
   - 정상 재시작에서 rebuild가 생략되고 drift 시 rebuild되는 회귀 테스트를 추가했다.

4. source/frozen/portable smoke 자동화
   - `국회의사중계 자막.py`에 GUI 없는 `--smoke`, `--smoke-storage-preflight`, `--smoke-storage-dir`를 추가했다.
   - smoke 결과는 JSON 한 줄로 출력하고, release 검증에서는 exit code `0`도 함께 확인한다.
   - frozen 기본 storage와 EXE 옆 `portable.flag` storage preflight를 모두 검증했다.

5. 외부 live contract opt-in smoke
   - `RUN_LIVE_SMOKE=1 pytest tests/test_live_contract_smoke.py`로 실제 `live_list.asp` schema를 확인할 수 있게 했다.
   - 기본 `pytest`에서는 네트워크/사이트 상태에 영향받지 않도록 skip된다.

6. pyright suppression 축소
   - 수정한 `pipeline_queue`, `pipeline_state`, `pipeline_messages`, `runtime_driver`는 `TYPE_CHECKING` Host base를 사용해 파일 단위 blanket suppression을 제거했다.
   - 전체 UI mixin strict 전환은 별도 리팩토링 범위로 남긴다.

## 문서/스펙/ignore 정합성

- `README.md`, `CLAUDE.md`, `GEMINI.md`에 2026-05-06 hardening, smoke 명령, 최신 검증 기준선을 반영했다.
- `PIPELINE_LOCK.md`와 `ALGORITHM_ANALYSIS.md`에는 이번 변경이 저장/큐/DB/검증 레이어 보강이며 글로벌 히스토리 + suffix 코어 의미론을 바꾸지 않는다고 명시했다.
- `subtitle_extractor.spec`에는 persistent snapshot/terminal queue/conditional FTS/smoke CLI가 추가 data 없이 동작한다는 설명과 smoke CLI 표준 라이브러리 hidden import를 반영했다.
- `requirements-dev.txt`에는 release/frozen build 검증에 사용하는 `pyinstaller==6.19.0`을 추가했다.
- `.gitignore`에는 SQLite rollback journal 계열(`*.db-journal`, `*.sqlite*`)을 추가해 smoke/DB 검증 산출물이 실수로 올라가지 않도록 보강했다.

## 검증 기준선

- `pytest -q`: `217 passed, 1 skipped`
- `python -m pyright --outputjson`: `0 errors / 0 warnings`
- import smoke: `MainWindow 16.14.7 True`
- source smoke: `python "국회의사중계 자막.py" --smoke --smoke-storage-dir .pytest_tmp/smoke-storage`
- source storage smoke: `python "국회의사중계 자막.py" --smoke-storage-preflight --smoke-storage-dir .pytest_tmp/smoke-storage`
- frozen build: `pyinstaller --clean subtitle_extractor.spec`
- frozen EXE 기본 `--smoke`: exit code `0`
- frozen EXE + `portable.flag` `--smoke-storage-preflight`: exit code `0`

