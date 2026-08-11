# Project Audit Remediation Design

Date: 2026-08-11

## 1. Objective

`PROJECT_AUDIT.md`에서 확인된 기능·안정성·운영 개선을 위험 우선 순서로 구현한다. 기존 JSON 세션, runtime archive, SQLite DB, CLI, 공개 import 경로와 Windows 전용 배포 구조는 유지한다.

범위에는 저장 정합성, DB 완료 의미론, 대용량 로드, 입력·경로 검증, queue gap 복구, 복구 후보 UX, 수집 품질 리포트, 서명된 업데이트 알림·사용자 승인 설치·rollback이 포함된다.

사용자 결정에 따라 보관 데이터 보호 기능 전체(암호화, 키 관리, 보존 기간, 로컬 데이터 전체 삭제)는 제외한다.

## 2. Delivery Strategy

네 개의 독립 배치로 구현한다.

1. 저장 정합성: session revision, save operation ID, DB late completion과 idempotency, runtime load budget.
2. 대용량·입력 안정성: DB batch load/cancel, Windows path canonicalization, URL·preset·history·network payload 제한.
3. 수집 품질·복구 UX: preview sequence/gap recovery, capture quality metadata, 복구 후보 선택.
4. 배포 안정성: signed release manifest, 사용자 승인 업데이트, smoke 검증과 rollback, portable mode.

각 배치는 기존 회귀를 모두 통과한 상태에서 다음 배치로 진행한다. 기존 mixin facade와 공개 API는 유지하고 내부 helper를 추가하는 additive 변경을 우선한다.

## 3. State and Save Consistency

### 3.1 Session revision

- 모든 의미 있는 자막 mutation은 단조 증가하는 `session_revision`을 증가시킨다.
- dirty 여부는 현재 revision과 마지막으로 성공 저장된 revision의 비교로 계산한다.
- 기존 `_session_dirty`는 호환 surface로 유지하되 revision 상태에서 파생되도록 한다.
- 세션 교체/신규 캡처/성공 load는 revision baseline을 재설정한다.

### 3.2 Save operation

- 저장 시작 시 `operation_id`, `snapshot_revision`, immutable entry snapshot, runtime context를 고정한다.
- JSON 원자 저장과 DB 저장 결과는 동일 operation ID로 묶는다.
- 완료 시 현재 revision이 snapshot revision과 같을 때만 clean 처리한다.
- 이후 mutation이 있으면 JSON/DB 저장 성공과 별개로 dirty를 유지하고 사용자에게 이후 변경이 미저장임을 알린다.
- deferred destructive action은 저장 revision 이후 변경이 없을 때만 자동 재개한다.

### 3.3 DB completion and idempotency

- DB save는 timeout을 최종 실패로 오인하지 않는다.
- 세션 저장 경로는 DB worker의 실제 완료 결과를 기다린다. 종료 UX는 기존 wait/escalation 흐름을 사용한다.
- `save_operation_id` nullable unique 식별자를 additive migration으로 추가한다.
- 동일 operation ID 재시도는 기존 session ID를 반환한다.
- legacy DB row는 operation ID가 없어도 그대로 읽는다.

## 4. Resource-Bounded Loading

### 4.1 Common budget

공통 resource budget은 다음을 추적한다.

- 단일 파일 byte 상한
- 전체 누적 byte 상한
- 전체 entry 상한
- 처리된 segment 수
- cancel token

일반 JSON, runtime manifest/segment/tail, salvage, DB load가 같은 정책을 사용한다. 상한 초과는 손상과 구분된 사용자 조치 오류다.

### 4.2 Runtime files

- manifest를 읽기 전에 크기를 검사한다.
- 각 segment와 tail checkpoint를 `json.load()` 전에 검사한다.
- manifest metadata의 entry count를 사전 검증하되 실제 fingerprint 검증도 유지한다.
- salvage도 누적 budget을 공유하며 무제한 sibling scan/load를 허용하지 않는다.

### 4.3 DB sessions

- metadata 조회와 subtitle batch 조회를 분리한다.
- `fetchmany()` 기반 iterator/page API를 제공한다.
- UI worker는 progress와 cancel을 처리하고, 완료된 임시 builder만 현재 세션과 교체한다.
- 취소/오류 시 현재 세션과 DB identity는 변경하지 않는다.

## 5. Input, Path, and Network Policy

### 5.1 File save identity

- Windows save-path key는 `realpath`와 `normcase`를 사용한다.
- 상대경로, drive casing, extension casing, junction/symlink 별칭을 가능한 범위에서 동일 대상으로 취급한다.
- atomic replace와 active-save registry는 canonical key를 공유한다.

### 5.2 URL and preset validation

- scheme, allowed host, default port, 허용 player path를 검증한다.
- player URL의 `xcode`/`xcgcd`를 case-insensitive query parsing 후 기존 token normalizer로 검사한다.
- press player는 별도 허용 규칙을 사용한다.
- URL, preset 이름, tag, description에 길이 상한을 둔다.
- 기존 history/preset의 무효 항목은 자동 삭제하지 않고 격리·경고한다.

### 5.3 Payload limits

- live-list response는 body byte 상한을 적용한다.
- URL history와 preset JSON은 load 전에 byte 상한을 적용한다.
- 오류 메시지와 로그에는 제한된 길이만 노출한다.

## 6. Capture Quality and Queue Recovery

- worker preview envelope에 run ID와 단조 증가 sequence를 포함한다.
- UI는 run별 expected sequence를 유지한다.
- gap 발견 시 incremental append를 중단하고 worker에 full structured snapshot 요청을 전달한다.
- full snapshot 적용 후 expected sequence와 suffix/history를 재동기화한다.
- drop, gap, reconnect, desync, salvage excluded count를 `capture_quality`에 누적한다.
- JSON과 DB는 optional quality metadata를 additive하게 저장한다.
- legacy message와 legacy session은 sequence/quality가 없어도 처리한다.

## 7. Recovery Candidate UX

- runtime manifest, tail checkpoint, 자동 backup 후보를 수집한다.
- 후보마다 시간, entry 수, source URL, 무결성 상태, 경고를 표시한다.
- 최신 후보를 기본 선택하되 사용자가 다른 후보나 취소를 선택할 수 있다.
- 선택 전 원본을 변경하지 않고, 성공 load 후에만 현재 세션을 교체한다.
- salvage 결과와 capture quality를 복구 완료 요약에 포함한다.

## 8. Signed Update and Rollback

- 업데이트 확인은 HTTPS release metadata와 별도 서명된 manifest를 사용한다.
- 애플리케이션에는 공개키만 포함한다. 개인키는 CI secret 또는 오프라인 release 절차에 둔다.
- 개발 빌드와 서명 검증 실패 상태에서는 설치를 허용하지 않는다.
- 사용자가 업데이트를 승인해야 다운로드와 설치를 시작한다.
- 다운로드 hash와 manifest 서명을 검증한다.
- 적용 전 현재 실행 파일과 필요한 launcher metadata를 백업한다.
- 새 버전 source/frozen smoke가 실패하면 이전 버전을 복원한다.
- portable mode는 같은 디렉터리의 staged replacement를 사용하고 사용자 데이터는 교체 대상에서 제외한다.
- 코드 서명 인증서가 없는 환경에서는 Authenticode 연결 지점과 검증 스크립트까지 구현하고 실제 서명 단계는 명확히 skip/fail 상태로 보고한다.

## 9. Error Model

- 재시도 가능: network, update check, transient SQLite busy.
- 사용자 조치 필요: invalid URL, resource budget 초과, 권한, portable update conflict.
- 부분 복구 가능: 일부 손상 segment/row. 정상 항목 유지와 제외 내역 기록.
- 정합성 위반: revision mismatch, operation ID collision, sequence gap, digest mismatch. 성공 처리 금지.

오류는 status/toast/log에 일관된 분류와 operation context로 노출한다. late completion은 최종 상태가 확정될 때까지 실패로 표시하지 않는다.

## 10. Compatibility

- 기존 JSON/runtime 파일은 새 필드 없이 읽힌다.
- 기존 DB는 nullable column과 보조 index/table만 추가한다.
- 읽기만으로 기존 파일을 재작성하지 않는다.
- `MainWindow` facade, 공개 method, CLI smoke options와 compatibility shim을 유지한다.
- Windows-only, PyQt6, Selenium, PyInstaller, optional HWP 구조를 유지한다.

## 11. Testing and Completion Criteria

각 동작 변경은 TDD로 구현한다.

- 저장 중 append/edit/delete와 out-of-order completion
- DB timeout/late commit/idempotent retry/lineage
- runtime file 개별·누적 budget과 salvage
- DB batch load/progress/cancel/atomic replacement
- Windows path aliases
- URL path/query/port/length와 legacy quarantine
- queue overflow/gap/full snapshot recovery
- repeated suffix/reset/reconnect fuzz cases
- recovery candidate ordering/integrity/selection
- update signature tamper/version/user cancel/smoke failure rollback/portable mode

각 배치 완료 조건:

1. 새 regression test의 red-green 확인
2. 전체 `pytest -q` 통과
3. pyright 0 errors, 0 warnings
4. source 및 `MainWindow()` smoke 통과
5. 관련 README, CLAUDE, PROJECT_AUDIT, 운영 문서 갱신
6. 업데이트 배치는 frozen fixture 또는 frozen EXE smoke와 rollback 검증

실제 국회 사이트와 코드 서명 인증서가 필요한 검증은 opt-in으로 분리하되 fixture 기반 계약 검증은 기본 CI에 포함한다.
