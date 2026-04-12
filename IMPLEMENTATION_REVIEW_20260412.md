# 구현 반영 메모 (2026-04-12)

리뷰 문서에서 제안했던 항목들을 실제 코드에 반영한 뒤, 문서/테스트/패키징 정합성까지 다시 확인한 결과를 정리한다.

## 반영 완료 항목

- DB lineage
  - `delete_session()`가 최신 저장본 삭제 후 남은 lineage의 latest를 자동 복구하도록 수정했다.
  - 관련 회귀 테스트를 추가했다.
- 생중계 목록
  - `LiveBroadcastDialog`에 `Config.LIVE_BROADCAST_REFRESH_INTERVAL` 기반 자동 새로고침을 추가했다.
  - 종료 시 auto-refresh timer와 active reply를 함께 정리하도록 맞췄다.
- 프리셋 검증
  - 프리셋 add/edit/import가 `http/https` + `assembly.webcast.go.kr` 계열 URL만 허용하도록 공통 검증 helper를 추가했다.
  - import는 invalid 항목을 건너뛰고 제외 개수를 사용자에게 요약한다.
- export 정리
  - `persistence_exports.py`의 TXT/SRT/VTT/통계 export에서 현재 스트리밍 경로만 남기고 dead legacy branch를 제거했다.

## 문서 / spec 정합성

- `README.md`
  - 생중계 목록 자동 새로고침
  - 프리셋 도메인 검증 정책
  - lineage latest 재정렬 보장
  - 최신 검증 기준선
- `CLAUDE.md`
  - 위와 동일한 구현 메모를 개발자 관점으로 보강
  - export dead branch 제거 메모 추가
- `subtitle_extractor.spec`
  - 추가 hidden import/datas는 필요하지 않음을 재확인했다.
  - 해당 판단이 남도록 상단 주석만 보강했다.

## 검증 결과

- `pytest -q`: `179 passed`
- `pyright`: `0 errors, 0 warnings, 0 informations`

## 메모

- 이번 변경은 사용자 체감 동작 3가지를 바꾼다.
  - DB 히스토리에서 latest 배지가 삭제 후에도 일관되게 유지된다.
  - 생중계 목록이 열려 있는 동안 자동으로 최신 상태를 따라간다.
  - 프리셋 add/edit/import가 국회 도메인 외 URL을 거부하거나 제외한다.
