# 자막 파이프라인 구조 고정 문서

## 1. 문서 목적

이 문서는 현재 자막 수집 구조를 안정적으로 유지하기 위한 고정 기준입니다.
운영 목표는 아래 두 가지입니다.

- 반복 누적 방지
- 연속 발화 누락 최소화

---

## 2. 코어 고정 범위

아래 코어 알고리즘의 **글로벌 히스토리 + suffix 의미론**은 유지하되, 매칭 전략과 리셋 정책은 개선되었습니다.

- `ui/main_window.py`의 `_process_raw_text`
- `ui/main_window.py`의 `_extract_new_part` — `rfind()` 사용 (v16.12)
- `ui/main_window.py`의 `_build_subtitle_selector_candidates` — `.smi_word` 우선순위 유지
- `ui/main_window.py`의 `_read_subtitle_text_by_selectors` — default + iframe/frame 순회 유지
- `ui/main_window.py`의 `_inject_mutation_observer` — 타겟 기반 주입 후 폴링 브리지 fallback 유지
- `ui/main_window.py`의 `_collect_observer_changes` — Observer 버퍼 우선 수집 유지
- `ui/main_window.py`의 `_join_stream_text` — 공백/문장부호 보존 결합 유지

고정 의미론
- `_confirmed_compact`와 `_trailing_suffix`를 기준으로 새 텍스트를 추출하는 글로벌 히스토리 + suffix 방식

### 2.1 코어 수정 이력 (v16.12)
- `_extract_new_part`: `find()` → `rfind()` 전환 — suffix 충돌 시 과잉 추출 방지
- `_prepare_preview_raw`: 전체 리셋 → `_soft_resync()` 소프트 리셋 — 대량 중복 유입 방지
- `_extraction_worker`: MutationObserver 하이브리드 아키텍처 도입
- `subtitle_reset` 메커니즘: 발언자 전환(자막 영역 클리어) 감지 시 즉시 완전 리셋 + 버퍼 확정

---

## 3. 현재 고정 파이프라인

```text
Worker(raw) [MutationObserver 우선 + 폴링 fallback]
  -> selector 후보 우선순위 정렬 (.smi_word:last-child 우선)
  -> 기본 문서 + 중첩 iframe/frame 순회
  -> clean/compact 기준 중복 전송 억제
  -> 자막 영역 클리어 감지 → subtitle_reset (완전 리셋)
  -> Queue(preview)
  -> _prepare_preview_raw(정규화, 게이트, 재동기화, fallback)
     (desync/ambiguous 반복 시 _soft_resync 소프트 리셋)
  -> _process_raw_text(GlobalHistory+Suffix core, rfind 기반)
  -> 후단 정제(get_word_diff, recent compact tail)
  -> _add_text_to_subtitles
  -> 종료 시 _drain_pending_previews 강제 플러시
```

---

## 4. 단계별 책임

### 4.1 Worker 입력 안정화 (하이브리드)
- MutationObserver 우선 → 폴링 fallback — `_inject_mutation_observer`, `_collect_observer_changes`
- 고정 선택자 우선순위
  - `#viewSubtit .smi_word:last-child`
  - `#viewSubtit .smi_word`
  - `#viewSubtit span`
  - `#viewSubtit .incont`
  - `#viewSubtit`
  - `.subtitle_area`
  - `.ai_subtitle`
  - `[class*='subtitle']`
- 프레임 탐색 고정
  - `_last_subtitle_frame_path` 우선
  - default content
  - `_iter_frame_paths(max_depth=3, max_frames=60)`
- Observer 주입 2단계 고정
  - 1차: 타겟 기반 Observer (`allow_poll_fallback=False`)
  - 2차: 타겟 미탐색 시 폴링 브리지 (`allow_poll_fallback=True`)
- `clean_text_display` 적용
- compact 기준으로 동일 입력 반복 전송 억제
- **자막 영역 클리어 감지 (발언자 전환)**
  - Observer: `__SUBTITLE_CLEARED__` 마커 → `subtitle_reset` 메시지
  - 폴링: 텍스트 빈 문자열 + 이전에 내용 있었음 → `subtitle_reset` 메시지

### 4.2 발언자 전환 처리 (`subtitle_reset`)
메시지: `("subtitle_reset", source)`

핸들러 동작 (순서 중요):
1. `last_subtitle` 버퍼가 있으면 **즉시 확정** (`_finalize_subtitle`)
2. `_confirmed_compact = ""`, `_trailing_suffix = ""` (완전 리셋)
3. `_last_raw_text = ""`, `_last_processed_raw = ""`
4. `_preview_desync_count = 0`, `_preview_ambiguous_skip_count = 0`

> ⚠️ 여기서는 `_soft_resync()` 대신 **완전 리셋**을 사용합니다.
> 소프트 리셋은 이전 발언자의 suffix를 복원하므로 새 발언자 텍스트에서 desync가 반복됩니다.
> 자막 영역이 실제로 클리어된 상황이므로 중복 유입 위험이 없습니다.

### 4.3 Preview 게이트
함수: `_prepare_preview_raw`

역할
- suffix desync 감지
- ambiguous suffix 감지
- fallback으로 증분 추출 시도
  - `_extract_stream_delta`
  - `_slice_incremental_part`
- 반복 실패 누적 시 `_soft_resync()` 소프트 리셋 (최근 자막 기반 복원)

### 4.4 Core
함수: `_process_raw_text`, `_extract_new_part`

역할
- 글로벌 히스토리 + suffix 기준으로 new_part 확정
- `rfind()` 사용으로 suffix 충돌 시 마지막 위치 기준 추출

### 4.5 후단 정제
- `get_word_diff` 기반 2차 정제
- recent compact tail 포함 여부 확인으로 대량 재누적 차단

### 4.6 종료 보정
함수: `_drain_pending_previews`

역할
- 종료 직전 preview와 segments 소진
- 게이트 통과 실패 시에도 강제 처리 (`forced = clean_text_display(data)`)
- 누락 감소를 위한 2회 drain + `_finalize_pending_subtitle`

---

## 5. 리셋 정책 정리

| 상황 | 리셋 방식 | 이유 |
|------|----------|------|
| `subtitle_reset` (발언자 전환) | **완전 리셋** | 자막 영역 클리어됨, 중복 위험 없음 |
| desync 임계값 초과 | `_soft_resync` | 자막 영역에 이전 텍스트 존재, 중복 위험 있음 |
| ambiguous 임계값 초과 | `_soft_resync` | 자막 영역에 이전 텍스트 존재, 중복 위험 있음 |

---

## 6. 허용 조정 영역

문제 대응은 아래 영역에서만 조정합니다.

1) Worker 전처리
- 정규화 방식
- compact 기준 전송 억제 조건

2) Preview 게이트 임계값
- `_preview_resync_threshold` (현재: 10)
- `_preview_ambiguous_resync_threshold` (현재: 6)
- ambiguous large append 기준

3) fallback 파라미터
- `_extract_stream_delta` 사용 조건
- `_slice_incremental_part`의 `min_anchor`, `min_overlap`
- Observer 재시도 간격 (`observer_retry_interval`)

4) 종료 플러시 정책
- 종료 직전 강제 처리 조건

코어 알고리즘 직접 수정 시 이 문서의 §2 수정 이력을 함께 갱신합니다.

---

## 7. 현재 운영 임계값

- `_preview_resync_threshold = 10`
- `_preview_ambiguous_resync_threshold = 6`
- ambiguous large append 기준: `max(200, len(raw_compact) // 3)`
- 누락 완화를 위해 fallback delta는 1자 이상 허용
- `_add_text_to_subtitles` 병합 조건: `elapsed < 5.0 and len < 300`
- Observer 재시도 간격: `3.0초`
- 폴링 브리지 간격: `180ms`

---

## 8. 로그 기반 운영

관측 로그
- `subtitle_reset 감지: observer_cleared` — Observer가 발언자 전환 감지
- `subtitle_reset 감지: polling_cleared` — 폴링이 발언자 전환 감지
- `preview suffix desync reset` — desync 임계값 도달, 소프트 리셋
- `preview ambiguous suffix reset` — ambiguous 임계값 도달, 소프트 리셋
- `소프트 리셋: suffix=` — 소프트 리셋 실행
- `MutationObserver 주입 성공` — Observer 정상 주입
- `MutationObserver 폴링 브리지 활성화` — 타겟 미탐색, JS 브리지 fallback 활성
- `MutationObserver 주입 실패: 대상 요소 없음` — Observer/브리지 모두 실패
- `MutationObserver 비활성화, 폴링 fallback` — Observer 죽음, 폴링 전환

해석
- `subtitle_reset`이 정상 빈도로 발생 → 발언자 전환 감지 작동 중
- desync/ambiguous 로그가 과도하면 → 게이트 임계값 조정 필요
- 로그가 거의 없는데 누락 → 게이트가 너무 보수적

---

## 9. 튜닝 우선순위

아래 순서로만 조정합니다.

1. `_prepare_preview_raw` 임계값 조정
2. fallback 조건 조정
3. 종료 플러시 조건 조정
4. Worker 전처리 조건 조정

코어 알고리즘 직접 수정 시 이 문서의 §2 수정 이력을 함께 갱신합니다.

---

## 10. 변경 전 체크리스트

- 재현 로그 5줄 이상 확보
- 반복 문제인지 누락 문제인지 분류
- 변경 범위가 코어 외곽 레이어인지 확인

## 11. 변경 후 체크리스트

- 문법 검사
  - `python -c "import ast, pathlib; ast.parse(pathlib.Path('ui/main_window.py').read_text(encoding='utf-8'))"`
- 스모크 테스트
  - `python test_reflow.py`
  - `python test_core_algorithm.py`
- 실운영 확인
  - 반복 누적 감소 여부
  - 연속 발화 누락 여부
  - 발언자 전환 시 자막 누락 여부

---

## 12. 관련 함수 인덱스

- 수집: `_extraction_worker` (MutationObserver 하이브리드)
- 선택자 후보: `_build_subtitle_selector_candidates`
- 선택자/프레임 탐색: `_read_subtitle_text_by_selectors`, `_switch_to_frame_path`, `_iter_frame_paths`
- Observer 주입: `_inject_mutation_observer`
- Observer 주입(현재 문맥): `_inject_mutation_observer_here`
- Observer 수집: `_collect_observer_changes`
- 발언자 전환: `subtitle_reset` 핸들러 (`_handle_message` 내)
- 입력 게이트: `_prepare_preview_raw`
- 재동기화: `_soft_resync`
- fallback: `_extract_stream_delta`, `_slice_incremental_part`
- core: `_process_raw_text`, `_extract_new_part`
- 후단 반영: `_add_text_to_subtitles`
- 공백 보존 결합: `_join_stream_text`
- 자막 확정: `_finalize_subtitle`
- 종료 소진: `_drain_pending_previews`

---

## 13. 문서 유지 원칙

- 파이프라인 구조가 바뀌면 이 문서를 먼저 갱신
- 임계값 변경 시 이유와 기대 효과를 함께 기록
- `README.md`, `CLAUDE.md`, `GEMINI.md`와 내용 충돌 금지

---

## 14. 다음 제안 백로그 (코어 비수정)

1. 선택자 적중률 로그 강화
- 목표: `selector_candidates`별 적중/미적중 빈도와 frame_path를 로그로 수집
- 기대 효과: 특정 위원회/화면 레이아웃에서 실패 셀렉터를 빠르게 교체

2. Observer 재시도 정책 적응형화
- 목표: 현재 고정값(3초)을 최근 실패 횟수 기준으로 1~5초 범위에서 가변 조정
- 기대 효과: 불안정 구간 복구 속도 개선 + 과도한 재주입 감소

3. 발언자 전환 병합 억제 힌트
- 목표: `_add_text_to_subtitles` 병합 조건에 발언자 전환 신호(`subtitle_reset` 직후 N초) 가중치 반영
- 기대 효과: 서로 다른 발화가 같은 엔트리로 붙는 케이스 감소

4. 게이트 임계값 프로파일 프리셋
- 목표: `_preview_resync_threshold`, `_preview_ambiguous_resync_threshold`를 보수/기본/공격 3개 프리셋으로 관리
- 기대 효과: 회의 유형(빠른 공방/정책 설명)에 맞춰 운영 튜닝 시간 단축

5. 회귀 테스트 보강
- 목표: Observer 반환 누락, 폴링 브리지 활성화, `.smi_word` 우선 선택, 공백 보존 결합에 대한 테스트 추가
- 기대 효과: 재발성 회귀(주입 실패 오탐, 공백 품질 저하) 사전 차단
