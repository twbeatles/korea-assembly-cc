# 기능 구현 점검 메모 (2026-04-05)

## 범위
- 참조 문서: `README.md`, `CLAUDE.md`
- 점검 대상: 현재 작업 트리 기준 `ui/`, `core/`, `tests/`
- 기준선 확인:
  - `pytest -q` -> `121 passed`
  - `pyright` -> `0 errors, 0 warnings`

## 요약
- 이전 리뷰에서 우선순위가 높았던 `structured preview dirty tracking`, 세션 로드 전 dirty 보호, 종료 시 background drain, RTF 유니코드 저장 문제는 현재 구현에 반영된 것으로 보입니다.
- 다만 `README.md`/`CLAUDE.md`가 강조하는 저장 신뢰성, 복구 가능성, DB 탐색 UX 관점에서 아직 손봐야 할 기능 리스크가 남아 있습니다.
- 우선순위가 높은 항목은 `실시간 저장 실패의 무음 처리`, `복구 스냅샷 초기 공백`, `병합 시 현재 세션 덮어쓰기`입니다.

## 주요 이슈

### 1. [높음] 실시간 저장 실패가 사용자에게 드러나지 않아 저장 성공으로 오인할 수 있음
- 근거:
  - `ui/main_window_impl/runtime_lifecycle.py:99`
  - `ui/main_window_impl/runtime_lifecycle.py:105`
  - `ui/main_window_impl/runtime_lifecycle.py:108`
  - `ui/main_window_impl/pipeline_stream.py:49`
  - `ui/main_window_impl/pipeline_stream.py:57`
- 현재 동작:
  - 추출 시작 시 실시간 저장 파일 생성에 실패해도 로그만 남기고 추출은 계속 진행합니다.
  - 실행 중 쓰기 실패도 `_realtime_error_count`만 올리고, 토스트/상태바/체크박스 상태 변경이 없습니다.
- 문제:
  - 사용자는 `실시간 저장`이 켜져 있다는 이유로 파일이 계속 기록되고 있다고 믿기 쉽습니다.
  - 권한 문제, 디스크 부족, 외장 드라이브 분리 같은 상황에서 실제 파일은 비거나 중간부터 누락될 수 있습니다.
- 권장 수정:
  - 파일 open 실패 시 즉시 토스트 또는 모달 경고를 띄우고 `realtime` 상태를 비활성화합니다.
  - 쓰기 실패가 누적되면 실시간 저장을 자동 중단하고 상태바/트레이에 명시적으로 표시합니다.
  - 세션 메타데이터의 `realtime=True`도 실제 파일 준비 성공 여부 기준으로만 기록하는 편이 안전합니다.

### 2. [높음] 복구 기능에 시작 직후 공백 구간이 있어 짧은 세션/초기 크래시를 복구하지 못함
- 근거:
  - `core/config.py:66`
  - `ui/main_window_impl/runtime_lifecycle.py:131`
  - `ui/main_window_persistence.py:195`
  - `ui/main_window_persistence.py:312`
  - `ui/main_window_persistence.py:354`
- 현재 동작:
  - recovery state는 수동 세션 저장 또는 자동 백업 시점에만 기록됩니다.
  - 자동 백업은 `AUTO_BACKUP_INTERVAL = 300000`으로 5분 뒤부터 동작합니다.
- 문제:
  - 추출 시작 후 첫 5분 내에 앱이 비정상 종료되면, 사용자가 이미 수집한 자막이 있어도 복구 포인트가 전혀 없을 수 있습니다.
  - `README.md`/`CLAUDE.md`의 “복구 가능 스냅샷” 기대와 비교하면 짧은 회의, 급종료, 초기 크래시에서 체감이 좋지 않습니다.
- 권장 수정:
  - 첫 자막 commit 직후 1회성 recovery snapshot을 남기거나,
  - 시작 후 짧은 지연(예: 10~30초)으로 첫 자동 백업을 따로 두고, 이후에만 5분 주기로 전환하는 방식이 좋습니다.

### 3. [높음] 세션 병합에서 “기존 자막 제외”를 선택하면 현재 작업 세션을 저장 확인 없이 덮어쓸 수 있음
- 근거:
  - `ui/main_window_database.py:785`
  - `ui/main_window_database.py:865`
  - `ui/main_window_database.py:891`
  - `ui/main_window_database.py:893`
- 현재 동작:
  - 병합 다이얼로그는 “기존 자막을 병합 결과에 포함할지”만 묻습니다.
  - 사용자가 `No`를 누르면 현재 자막을 병합 결과로 바로 교체하고 dirty만 다시 올립니다.
- 문제:
  - 이 흐름은 실질적으로 “현재 세션 교체”인데, 파일/DB 세션 로드 때와 달리 `Save / Discard / Cancel` 보호가 없습니다.
  - 사용자는 단순 옵션 분기라고 생각할 수 있지만, 실제로는 현재 작업물이 통째로 사라질 수 있습니다.
- 권장 수정:
  - 기존 자막이 있는 상태에서 `No`를 선택해 현재 세션을 버리게 되는 순간, 로드와 동일한 dirty 보호 helper를 거치게 해야 합니다.
  - 최소한 문구도 “현재 작업 세션이 병합 결과로 대체됩니다” 수준으로 더 명시하는 편이 좋습니다.

### 4. [중간] 세션 저장 진행 중 로드/종료가 dirty prompt와 경합해 잘못된 안내를 줄 수 있음
- 근거:
  - `ui/main_window_persistence.py:1073`
  - `ui/main_window_persistence.py:1093`
  - `ui/main_window_impl/pipeline_messages.py:239`
  - `ui/main_window_persistence.py:272`
  - `ui/main_window_persistence.py:1122`
  - `ui/main_window_impl/runtime_lifecycle.py:455`
- 현재 동작:
  - 세션 저장은 background thread에서 수행되고, 완료 메시지가 큐를 통해 처리된 뒤에야 `_session_save_in_progress = False`와 dirty clear가 반영됩니다.
  - 하지만 세션 로드/종료 전 확인 로직은 `_session_save_in_progress`를 보지 않고 `_has_dirty_session()`만 확인합니다.
- 문제:
  - 사용자가 저장 직후 바로 종료/불러오기를 누르면, 이미 저장 중인 세션에 대해 다시 `Save / Discard / Cancel`을 보게 될 수 있습니다.
  - 결과적으로 중복 저장, 불필요한 discard, 저장 완료 여부에 대한 혼란이 생깁니다.
- 권장 수정:
  - 세션 저장 중에는 종료/세션 교체를 잠시 막고 “저장 완료를 기다리는 중” 상태를 보여주거나,
  - 최소한 dirty 확인 helper에서 `_session_save_in_progress`를 먼저 확인해 대기/취소 분기를 제공하는 것이 좋습니다.

### 5. [중간] DB 검색 결과에서 첫 번째 자막(sequence 0)은 “결과로 이동” 포커싱이 누락됨
- 근거:
  - `core/database_manager.py:238`
  - `ui/main_window_database.py:675`
  - `ui/main_window_impl/pipeline_messages.py:44`
  - `ui/main_window_impl/view_render.py:143`
- 현재 동작:
  - DB 저장 시 subtitle `sequence`는 `0`부터 시작합니다.
  - 그런데 검색 결과 이동 시 `int(selected.get("sequence", -1) or -1)`를 사용해 `0`이 `-1`로 바뀝니다.
  - 이후 `_complete_loaded_session()`은 `highlight_sequence >= 0`일 때만 포커싱합니다.
- 문제:
  - 검색 결과가 세션의 첫 문장인 경우에는 세션은 로드되지만, 사용자가 기대한 “해당 결과로 즉시 이동”이 일어나지 않습니다.
  - 같은 기능이 두 번째 문장 이후에는 동작하므로 UX 일관성이 깨집니다.
- 권장 수정:
  - `or -1` 패턴을 제거하고 `None`/빈값만 별도로 처리해야 합니다.
  - 첫 결과(`sequence == 0`) 회귀 테스트를 추가하는 것이 안전합니다.

## 추가 제안

### A. 파괴적 편집 작업에 1단계 undo 또는 임시 스냅샷이 있으면 안정성이 더 좋아짐
- 관련 위치:
  - `ui/main_window_impl/view_editing.py:118`
  - `ui/main_window_impl/view_editing.py:270`
  - `ui/main_window_persistence.py:1175`
  - `ui/main_window_database.py:785`
- `전체 자막 삭제`, `자막 삭제`, `줄넘김 정리`, `병합`은 모두 되돌리기 없이 즉시 상태를 바꿉니다.
- 최소한 메모리 내 마지막 상태 1회 복원 또는 작업 직전 임시 백업을 두면 실사용 안전성이 크게 올라갑니다.

### B. 실시간 저장 상태를 상태바에서 별도 health indicator로 보여주면 좋음
- 관련 위치:
  - `ui/main_window_impl/runtime_lifecycle.py:99`
  - `ui/main_window_impl/pipeline_stream.py:49`
- 현재는 체크박스만으로 기능 활성 여부를 유추해야 합니다.
- `실시간 저장: 정상 / 실패 / 중단` 같은 별도 상태가 있으면 저장 신뢰성을 사용자가 즉시 이해할 수 있습니다.

## 우선순위 제안
1. 실시간 저장 실패 가시화 및 자동 비활성화
2. 첫 recovery snapshot 보강
3. 병합 시 dirty 세션 덮어쓰기 보호
4. 저장 진행 중 종료/로드 경합 방지
5. DB 검색 첫 결과 포커싱 회귀 수정
