# 기능 구현 리뷰 (2026-04-14)

## 범위
- 참조 문서: `README.md`, `CLAUDE.md`
- 점검 대상: `core/config.py`, `core/live_list.py`, `core/database_manager.py`, `ui/dialogs.py`, `ui/main_window_impl/capture_live.py`, `ui/main_window_impl/runtime_state.py`, `ui/main_window_impl/runtime_driver.py`, `ui/main_window_impl/persistence_exports.py`, `ui/main_window_impl/pipeline_messages.py`, `ui/main_window_ui.py`, `subtitle_extractor.spec`, `.gitignore`, 관련 `.md` 문서
- 실행 검증:
- `pytest -q` -> `187 passed`
- `python -m pyright --outputjson` -> `0 errors / 0 warnings`
- `pyinstaller --clean subtitle_extractor.spec` -> 빌드 성공

## 구현 반영 상태 (2026-04-14)
- storage preflight v2 완료: 디렉터리 probe만이 아니라 `subtitle_history.db`, `committee_presets.json`, `url_history.json`, `session_recovery.json`의 실제 파일 surface와 SQLite WAL 가능 여부까지 확인합니다.
- shared live_list service 완료: `core/live_list.py`를 추가해 `LiveBroadcastDialog`와 자동 URL 보완이 같은 payload shape, 오류 분류, row 정규화, 자동 선택 정책을 공유합니다.
- 안전 우선 자동 선택 정책 완료: `xcode`가 없고 live 후보가 여러 개인 경우 첫 후보를 고르지 않고 원래 URL을 유지하며, 상태바/토스트로 수동 선택을 유도합니다.
- DB degraded mode 완료: `db_available`, `fts_available`, `db_degraded_reason` 상태를 UI에 노출하고, FTS 미지원 시 literal `LIKE` fallback과 DB 액션 비활성화를 적용했습니다.
- cleanup / 사용자 피드백 완료: `persistence_exports.py` / `pipeline_messages.py` dead branch를 제거했고, URL 히스토리/프리셋 load-save 실패는 사용자 경고로도 노출합니다.
- 문서/패키징 동기화 완료: `subtitle_extractor.spec` hidden import에 `core.live_list`를 추가했고, `.gitignore`는 `.storage_probe`를 저장소 전체에서 무시하도록 정리했습니다. `README.md`, `CLAUDE.md`, `GEMINI.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`도 현재 동작 기준으로 갱신했습니다.

## 총평
현재 구현은 문서 기준선 대비 전반적으로 안정적입니다. 테스트, 타입 검사, 빌드까지 모두 통과했고, 장시간 세션/복구/내보내기/DB lineage 같은 최근 보강도 실제 코드에 반영되어 있습니다.

아래 상세 항목은 구현 전 리뷰 기준을 보존하기 위한 기록입니다. 현재는 저장소 preflight, live_list 자동 감지 정책, DB degraded mode, export/message dead branch, 문서/spec/.gitignore 정합화까지 모두 이번 배치에 반영됐습니다.

## 우선순위 높은 항목 (구현 전 리뷰 기록)

### 1. 저장소 preflight가 디렉터리만 검사하고 실제 영속화 표면은 검증하지 않음
- 근거:
- `core/config.py`의 초기 preflight는 `logs/`, `sessions/`, `realtime_output/`, `backups/`, `runtime_sessions/` 디렉터리에 `.storage_probe`를 쓰는 수준이었습니다.
- 실제 앱이 자주 쓰는 `subtitle_history.db`, `committee_presets.json`, `url_history.json`, `session_recovery.json`, SQLite WAL/SHM 생성 가능 여부는 시작 시 검증하지 않았습니다.
- 영향:
- 앱은 정상 기동했는데, 나중에 프리셋 저장/URL 히스토리 저장/DB 초기화/복구 포인터 저장에서 개별적으로 실패할 수 있었습니다.
- 특히 문서에는 "startup preflight로 저장소/DB 경로를 먼저 검증"한다고 적혀 있었는데, 구현은 그 약속을 부분적으로만 충족했습니다.
- 권장:
- preflight v2를 두고 디렉터리뿐 아니라 실제 파일 생성/교체/삭제까지 확인하는 방식으로 확장하는 것이 좋았습니다.
- 최소 검증 대상은 `Config.DATABASE_PATH`, `Config.PRESET_FILE`, `Config.URL_HISTORY_FILE`, `Config.RECOVERY_STATE_FILE`이었습니다.
- DB는 SQLite open + `PRAGMA journal_mode=WAL`까지 확인하는 편이 운영 surprise failure를 줄였습니다.

### 2. live_list 경로가 이중화되어 자동 감지와 UI 동작이 일관되지 않을 수 있음
- 근거:
- UI 다이얼로그는 `ui/dialogs.py`에서 `QNetworkAccessManager`를 사용하고 timeout/schema 오류를 사용자에게 보여주었습니다.
- 반면 자동 감지 경로는 `ui/main_window_impl/capture_live.py`에서 별도 네트워크 구현을 사용하고, 실패 시 로그만 남긴 채 빈 리스트로 처리하던 시점이 있었습니다.
- 추가로 `xcode`가 없을 때 "첫 번째 생중계"를 자동 선택하는 경로가 있었습니다.
- 영향:
- 같은 `live_list.asp`를 조회해도 다이얼로그와 자동 감지가 서로 다른 예외 처리, timeout 처리, 프록시/TLS 동작을 가질 수 있었습니다.
- `xcode` 없는 기본 URL이나 애매한 URL에서는 의도하지 않은 다른 위원회 방송으로 붙을 가능성이 있었습니다.
- 사용자 입장에서는 "생중계가 없다"와 "조회 실패"와 "다른 방송으로 붙었다"가 구분되지 않을 수 있었습니다.
- 권장:
- live_list 조회를 하나의 공통 service로 통합하고, UI/worker 모두 같은 payload와 같은 오류 분류를 쓰는 편이 좋았습니다.
- `xcode` 없이 여러 생중계가 잡히는 경우에는 첫 항목 자동 선택 대신 마지막 위원회 태그/프리셋 우선 매칭, 다수 후보면 선택 다이얼로그 표시, 자동 선택 시 상태바에 선택 기준 명시가 필요했습니다.

### 3. DB 초기화 실패가 시작 시 사용자에게 거의 보이지 않음
- 근거:
- DB 생성 실패 시 로그만 남기고 `self.db = None`으로 계속 진행하는 구조가 있었습니다.
- FTS5 virtual table 생성 실패가 DB 전체 가용성처럼 보일 수 있었습니다.
- 이후 DB 기능은 필요 시점에만 "데이터베이스가 초기화되지 않았습니다" 경고가 뜨는 식이었습니다.
- 영향:
- 사용자는 프로그램이 정상 동작한다고 생각한 채 작업을 시작할 수 있고, 나중에 세션 히스토리/검색/JSON+DB 저장에서 뒤늦게 기능 제한을 마주하게 됩니다.
- Python/SQLite 배포 차이로 FTS5가 비활성화된 환경이라면 DB 기능 전체가 조용히 빠질 수 있었습니다.
- 권장:
- 시작 시점에 "DB 비활성화(degraded mode)" 배너/토스트를 띄우고, 어떤 기능이 제한되는지 알려주는 편이 좋았습니다.
- FTS5 생성 실패 시에는 DB 전체를 포기하지 말고 기본 테이블만 유지한 채 검색만 literal LIKE 모드로 제한하는 fallback이 더 안전했습니다.

## 우선순위 중간 항목 (구현 전 리뷰 기록)

### 4. export 계층과 메시지 처리 계층에 shadow code가 남아 있어 회귀 위험이 큼
- 근거:
- `ui/main_window_impl/persistence_exports.py`에는 `return` 뒤에 과거 구현이 남아 있었고, `ui/main_window_impl/pipeline_messages.py`에는 `preview`, `subtitle_reset`, `keepalive` 처리 분기가 중복된 구간이 있었습니다.
- 영향:
- 현재 실행에는 직접 영향이 없더라도, 다음 수정자가 죽은 코드를 고치고 실제 경로를 놓치는 형태의 회귀가 생기기 쉬웠습니다.
- 특히 export 포맷은 DOCX/HWPX/HWP/RTF처럼 포맷별 예외 케이스가 많아서 shadow code가 유지보수 리스크를 키웠습니다.
- 권장:
- dead branch를 제거하고 포맷별 함수를 더 작게 분리하는 것이 좋았습니다.

### 5. URL 히스토리/프리셋 영속화 실패가 사용자에게 보이지 않음
- 근거:
- URL 히스토리/프리셋 load-save 실패가 `logger.warning(...)`만 남기고 UI에는 드러나지 않는 경로가 있었습니다.
- 영향:
- 사용자는 태그나 프리셋을 저장했다고 생각하지만, 실제로는 디스크 권한/파일 손상/인코딩 문제로 저장되지 않을 수 있었습니다.
- 이 문제는 재시작 후에야 드러나므로 체감상 "간헐적으로 사라진다"로 보일 가능성이 컸습니다.
- 권장:
- 저장 실패 시 최소 toast나 status bar 경고를 보여주는 것이 좋았습니다.
- preflight v2와 연결해 "설정/히스토리 저장소 쓰기 불가"를 한 번에 설명하는 경로도 필요했습니다.

## 추가하면 좋았던 항목과 현재 상태

### 6. 자동 검증 범위를 조금 더 운영형으로 넓힐 필요가 있었음
- 현재 기준선은 좋습니다.
- `pytest -q` 187 pass
- `pyright` 0 errors
- `pyinstaller` 빌드 성공
- 이번 배치에서 아래 시나리오가 회귀 테스트에 추가되었습니다.
- DB 초기화 실패 시 degraded mode 상태 노출
- live_list 네트워크 실패 vs schema 실패 vs 다중 live 후보 선택
- preflight에서 파일 단위 쓰기 실패를 잡는 시나리오
- URL 히스토리/프리셋 save 실패의 user-visible warning

### 7. 문서와 코드가 가장 어긋나기 쉬운 지점은 live_list와 저장소 health check였음
- `README.md`, `CLAUDE.md` 기준으로는 storage preflight와 live_list hardening이 이미 강하게 약속되어 있었습니다.
- 이번 동기화에서 자동 감지 쪽 live_list, 파일 단위 저장소 검증, DB degraded mode, hidden import, `.gitignore` 규칙까지 현재 구현 기준으로 다시 맞췄습니다.
- 이후 문서 갱신도 "공유 `core.live_list.py` helper", "파일 surface + WAL preflight", "DB degraded mode" 기준을 유지하는 편이 좋습니다.

## 실제 반영 순서

### 1순위
- storage preflight v2 구현
- 파일 단위 writable/open 검증
- DB WAL/SHM 생성 가능 여부 확인
- 실패 시 어떤 기능이 막히는지 명시

### 2순위
- live_list 조회 service 단일화
- 같은 parse/error/selection helper로 통일
- 다중 live 후보 선택 정책 명문화

### 3순위
- export/message shadow code 제거
- `persistence_exports.py`와 `pipeline_messages.py` dead branch 정리
- 포맷별/메시지별 회귀 테스트 추가

### 4순위
- DB degraded mode 가시화
- 시작 시 토스트/배지/상태바 경고
- FTS 미지원 시 fallback search 모드 도입

## 결론
이번 배치에서 원래 리뷰 문서가 지적했던 항목과 연관 문서/spec/.gitignore 동기화까지 모두 반영했습니다. 코드 경로와 문서 설명, PyInstaller hidden import, 저장소 ignore 규칙이 현재 동작 기준으로 다시 맞춰졌습니다.

현재 기준선은 `pytest -q` `187 passed`, `python -m pyright --outputjson` `0 errors / 0 warnings`, `pyinstaller --clean subtitle_extractor.spec` 빌드 성공입니다.
