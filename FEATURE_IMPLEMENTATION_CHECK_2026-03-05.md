# 기능 구현 점검 리포트 (2026-03-05)

## 점검 기준
- 문서 기준: `CLAUDE.md`, `README.md`
- 핵심 구현: `ui/main_window.py`, `core/utils.py`, `core/config.py`, `database.py`
- 회귀 상태: `pytest -q` 기준 `31 passed`

## 핵심 발견 사항 (심각도 순)

### P0

1. 세션 저장/불러오기 스레드가 종료 대기 대상이 아니어서 앱 종료 시 데이터 유실 가능
- 근거:
  - `ui/main_window.py:5692`~`ui/main_window.py:5694` (`SessionSaveWorker`, `daemon=True`)
  - `ui/main_window.py:5750`~`ui/main_window.py:5752` (`SessionLoadWorker`, `daemon=True`)
  - `ui/main_window.py:6752`~`ui/main_window.py:6753`의 종료 대기는 `_active_save_threads`만 대상
- 영향:
  - 세션 저장 직후 종료하면 JSON/DB 저장 완료 전에 프로세스가 내려갈 수 있음
- 권장:
  - 세션 save/load 스레드도 `_active_save_threads`로 추적
  - 또는 non-daemon + 종료 시 `join(timeout)` 일관 적용

2. `_confirmed_compact`가 무제한 누적되어 장시간 수집 시 메모리/성능 저하 위험
- 근거:
  - `ui/main_window.py:128` 초기화 후
  - `ui/main_window.py:4203`에서 지속적으로 `+=`
  - suffix 계산은 `ui/main_window.py:4206`~`ui/main_window.py:4209`에서 일부 tail만 사용
- 영향:
  - 긴 회의에서 문자열 재할당 비용 증가, 메모리 점유 누적
- 권장:
  - `_confirmed_compact`를 고정 길이 ring/tail 버퍼(예: 최근 10k~50k compact chars)로 제한

### P1

3. `_should_merge_entry`가 미사용 상태이며 실제 병합 기준은 하드코딩되어 설정과 불일치
- 근거:
  - 기준 함수 정의: `ui/main_window.py:4043`~`ui/main_window.py:4061`
  - 설정 상수: `core/config.py:196`~`core/config.py:197`
  - 실제 적용 로직: `ui/main_window.py:4292`~`ui/main_window.py:4295` (`5.0초`, `300자` 하드코딩)
  - `_should_merge_entry` 호출 지점 없음
- 영향:
  - 문서/설정으로 병합 정책 튜닝해도 런타임 동작에 반영되지 않음
- 권장:
  - `_add_text_to_subtitles()`에서 `_should_merge_entry()`를 호출하도록 일원화

4. `is_meaningful_subtitle_text`가 중복 정의되어 유지보수 시 오해/회귀 위험
- 근거:
  - `core/utils.py:95`~`core/utils.py:115` 1차 정의
  - `core/utils.py:150`~`core/utils.py:173` 2차 정의(실제로 덮어씀)
- 영향:
  - 앞쪽 정의 수정이 실제 동작에 반영되지 않는 착시 발생 가능
- 권장:
  - 함수 정의를 1개로 통합하고, 규칙을 테스트로 고정

5. 세션 병합의 중복 제거가 텍스트만 기준이라 정상 반복 발화를 과삭제할 수 있음
- 근거:
  - `ui/main_window.py:6673`~`ui/main_window.py:6680`에서 `entry.text.strip().lower()`만으로 dedupe
- 영향:
  - 시점이 다른 동일 발화(예: "네", "감사합니다")가 병합 결과에서 사라질 수 있음
- 권장:
  - `(정규화 텍스트 + 시간 버킷)` 조합으로 중복 판별
  - 또는 "엄격/완화" 중복 제거 옵션 분리

6. DB 비동기 작업 스레드도 daemon이며 종료 시 DB close와 경합 가능
- 근거:
  - `ui/main_window.py:6179` (`DBTask-*`, `daemon=True`)
  - 종료 시 `ui/main_window.py:6781`~`ui/main_window.py:6783`에서 `db.close_all()` 즉시 수행
- 영향:
  - 종료 타이밍에 따라 진행 중 DB 작업이 중단되거나 예외가 발생 가능
- 권장:
  - DB task inflight 카운트 기반 종료 대기
  - 또는 종료 플래그 기반 작업 취소 + close 순서 보장

### P2

7. `DatabaseManager` 기본 DB 경로가 `Path.cwd()` 기준이라 경로 정책이 분산됨
- 근거:
  - `database.py:28`~`database.py:31`
  - 반면 앱 기준 경로 정책은 `Config.DATABASE_PATH` (`core/config.py:209`)
- 영향:
  - `DatabaseManager()`를 직접 호출하는 코드/스크립트에서 실행 위치에 따라 DB 위치가 달라질 수 있음
- 권장:
  - 기본값도 `Config.DATABASE_PATH`를 쓰도록 통일하거나 팩토리 함수로 강제

## 테스트 관점 갭
- 현재 테스트는 기능 정상 경로 중심이며(`31 passed`), 아래 리스크를 직접 검증하지 않음:
  - 종료 직전 세션 저장/불러오기 스레드 완료 보장
  - 장시간 수집 시 `_confirmed_compact` 메모리 상한
  - 병합 dedupe 정책(동일 텍스트, 다른 시점)의 과삭제 여부
  - 종료 시 DB task inflight 처리 순서

## 추가 구현 제안
1. 종료 안정성 통합
- 세션 save/load, 파일 save, DB task를 하나의 lifecycle manager로 추적
- `closeEvent`에서 "신규 작업 수락 중지 -> inflight drain -> 자원 close" 순서 고정

2. 스트리밍 상태 메모리 상한
- `_confirmed_compact`에 상한 정책(슬라이딩 윈도우) 도입
- 상한 도달 시에도 suffix 정확도 유지하는 보정 로직 추가

3. 병합 정책 고도화
- 텍스트만 기준 dedupe를 시간 인지형 dedupe로 교체
- 사용자 옵션(엄격/완화/비활성)을 UI에 노출

4. 회귀 테스트 확장
- 종료 시점 무결성 테스트
- 장시간 입력 시 메모리 증가율/상한 테스트
- 병합 dedupe 정책 케이스 테스트

## 우선 착수 순서
1. P0-1, P1-6: 종료 시 스레드/DB task drain 체계 통합
2. P0-2: `_confirmed_compact` 상한 도입
3. P1-3, P1-4: 병합 기준 함수 일원화 + 유틸 중복 정의 제거
4. P1-5: 병합 dedupe 정책 개선
5. 테스트 확장으로 회귀 방지
