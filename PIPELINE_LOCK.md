# 자막 파이프라인 구조 고정 문서

## 1. 문서 목적

이 문서는 현재 자막 수집 구조를 안정적으로 유지하기 위한 고정 기준입니다.
운영 목표는 아래 두 가지입니다.

- 반복 누적 방지
- 연속 발화 누락 최소화

---

## 2. 코어 고정 범위

아래 코어 알고리즘은 직접 수정하지 않습니다.

- `ui/main_window.py`의 `_process_raw_text`
- `ui/main_window.py`의 `_extract_new_part`

고정 의미론
- `_confirmed_compact`와 `_trailing_suffix`를 기준으로 새 텍스트를 추출하는 글로벌 히스토리 + suffix 방식

---

## 3. 현재 고정 파이프라인

```text
Worker(raw)
  -> clean/compact 기준 중복 전송 억제
  -> Queue(preview)
  -> _prepare_preview_raw(정규화, 게이트, 재동기화, fallback)
  -> _process_raw_text(GlobalHistory+Suffix core)
  -> 후단 정제(get_word_diff, recent compact tail)
  -> _add_text_to_subtitles
  -> 종료 시 _drain_pending_previews 강제 플러시
```

---

## 4. 단계별 책임

### 4.1 Worker 입력 안정화
- `clean_text_display` 적용
- compact 기준으로 동일 입력 반복 전송 억제

### 4.2 Preview 게이트
함수: `_prepare_preview_raw`

역할
- suffix desync 감지
- ambiguous suffix 감지
- fallback으로 증분 추출 시도
  - `_extract_stream_delta`
  - `_slice_incremental_part`
- 반복 실패 누적 시 제한적 resync reset

### 4.3 Core
함수: `_process_raw_text`, `_extract_new_part`

역할
- 글로벌 히스토리 + suffix 기준으로 new_part 확정

### 4.4 후단 정제
- `get_word_diff` 기반 2차 정제
- recent compact tail 포함 여부 확인으로 대량 재누적 차단

### 4.5 종료 보정
함수: `_drain_pending_previews`

역할
- 종료 직전 preview와 segments 소진
- 누락 감소를 위한 강제 플러시

---

## 5. 허용 조정 영역

문제 대응은 아래 영역에서만 조정합니다.

1) Worker 전처리
- 정규화 방식
- compact 기준 전송 억제 조건

2) Preview 게이트 임계값
- `_preview_resync_threshold`
- `_preview_ambiguous_resync_threshold`
- ambiguous large append 기준

3) fallback 파라미터
- `_extract_stream_delta` 사용 조건
- `_slice_incremental_part`의 `min_anchor`, `min_overlap`

4) 종료 플러시 정책
- 종료 직전 강제 처리 조건

---

## 6. 현재 운영 임계값

- `_preview_resync_threshold = 10`
- `_preview_ambiguous_resync_threshold = 6`
- ambiguous large append 기준은 `max(200, len(raw_compact) // 3)`
- 누락 완화를 위해 fallback delta는 1자 이상 허용

---

## 7. 로그 기반 운영

관측 로그
- `preview suffix desync reset`
- `preview ambiguous suffix reset`

해석
- 위 로그가 과도하게 자주 발생하면
  - 게이트 임계값이 낮거나 입력 흔들림이 큰 상태
- 로그가 거의 없는데 누락이 많으면
  - 게이트가 너무 보수적으로 동작할 가능성

---

## 8. 튜닝 우선순위

아래 순서로만 조정합니다.

1. `_prepare_preview_raw` 임계값 조정
2. fallback 조건 조정
3. 종료 플러시 조건 조정
4. Worker 전처리 조건 조정

코어 알고리즘 직접 수정은 금지합니다.

---

## 9. 변경 전 체크리스트

- 재현 로그 5줄 이상 확보
- 반복 문제인지 누락 문제인지 분류
- 변경 범위가 코어 외곽 레이어인지 확인

## 10. 변경 후 체크리스트

- 문법 검사
  - `python -c "import ast, pathlib; ast.parse(pathlib.Path('ui/main_window.py').read_text(encoding='utf-8'))"`
- 스모크 테스트
  - `python test_reflow.py`
- 실운영 확인
  - 반복 누적 감소 여부
  - 연속 발화 누락 여부

---

## 11. 관련 함수 인덱스

- 수집: `_extraction_worker`
- 입력 게이트: `_prepare_preview_raw`
- fallback: `_extract_stream_delta`, `_slice_incremental_part`
- core: `_process_raw_text`, `_extract_new_part`
- 후단 반영: `_add_text_to_subtitles`
- 종료 소진: `_drain_pending_previews`

---

## 12. 문서 유지 원칙

- 파이프라인 구조가 바뀌면 이 문서를 먼저 갱신
- 임계값 변경 시 이유와 기대 효과를 함께 기록
- `README.md`, `CLAUDE.md`, `GEMINI.md`와 내용 충돌 금지
