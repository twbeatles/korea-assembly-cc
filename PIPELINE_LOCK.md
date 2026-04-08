# 자막 파이프라인 구조 고정 문서

## 1. 문서 목적

이 문서는 현재 자막 수집 구조를 안정적으로 유지하기 위한 고정 기준입니다.
운영 목표는 아래 두 가지입니다.

- 반복 누적 방지
- 연속 발화 누락 최소화

---

## 2. 코어 고정 범위

아래 코어 알고리즘의 **글로벌 히스토리 + suffix 의미론**은 유지하되, 매칭 전략과 리셋 정책은 개선되었습니다.

- `ui/main_window_pipeline.py`의 `_process_raw_text`
- `ui/main_window_pipeline.py`의 `_extract_new_part` — `rfind()` 사용 (v16.12)
- `ui/main_window_capture.py`의 `_build_subtitle_selector_candidates` — `.smi_word` 우선순위 유지
- `ui/main_window_capture.py`의 `_read_subtitle_text_by_selectors` — default + iframe/frame 순회 + `.smi_word` 창 수집 유지
- `ui/main_window_capture.py`의 `_inject_mutation_observer` — 타겟 기반 주입 후 폴링 브리지 fallback 유지
- `ui/main_window_capture.py`의 `_collect_observer_changes` — Observer 버퍼 우선 수집 유지
- `ui/main_window_pipeline.py`의 `_join_stream_text` — 공백/문장부호 보존 결합 유지
- `ui/main_window_pipeline.py`의 `_handle_keepalive` — 동일 자막 구간 end_time 연장 유지
- `ui/main_window_view.py`의 `_finalize_subtitle` — 호환용 entry point이지만 shared append/merge 규칙 유지
- `core/utils.py`의 `is_meaningful_subtitle_text` — 짧은 발화 허용 + 노이즈 차단 규칙 유지

고정 의미론
- `_confirmed_compact`와 `_trailing_suffix`를 기준으로 새 텍스트를 추출하는 글로벌 히스토리 + suffix 방식
- 공개 고정 경로는 `ui/main_window_capture.py`, `ui/main_window_pipeline.py`, `ui/main_window_view.py`, `core/live_capture.py`이지만 실제 구현은 `ui/main_window_impl/*`, `core/live_capture_impl/*`로 이동할 수 있다. 고정 의미론 변경 시 facade와 내부 구현 문서를 함께 맞춘다.

### 2.1 코어 수정 이력 (v16.12 ~ v16.14.7)
- `ui/main_window_capture.py`/`ui/main_window_impl/capture_browser.py`/`core/config.py`: 브라우저 헬스체크(`window_handles`, `current_url`, script ping), recoverable WebDriver 오류 승격, 같은 모드/마지막 확정 live URL 기반 Chrome 자동 재기동, `reconnected` 상태 반영을 추가했다. 이는 수집 연속성과 driver lifecycle 안정화 레이어 변경이며 글로벌 히스토리 + suffix 의미론 자체는 바꾸지 않는다.
- `ui/main_window.py`/`ui/main_window_capture.py`/`ui/main_window_pipeline.py`/`ui/main_window_view.py`/`core/live_capture.py`: 공개 facade는 유지하고 실제 구현을 `ui/main_window_impl/`, `core/live_capture_impl/`로 재배치했다. 책임 경계와 import 구조만 바뀌며 코어 자막 의미론은 바뀌지 않는다.
- `ui/main_window_database.py`/`ui/main_window_persistence.py`/`subtitle_extractor.spec`: 공개 facade는 유지하되 실제 구현을 `ui/main_window_impl/database_worker.py`, `database_dialogs.py`, `persistence_runtime.py`, `persistence_session.py`, `persistence_exports.py`, `persistence_tools.py`로 재분리했고, PyInstaller hidden import도 같은 경계에 맞춰 갱신했다. 이 변경은 책임 분리와 패키징 정합화이며 코어 의미론은 바뀌지 않는다.
- `ui/main_window.py`/`ui/main_window_persistence.py`/`ui/main_window_pipeline.py`/`core/config.py`: 수동 세션 저장, 종료 저장, 자동 백업이 공통 recovery state(`session_recovery.json`)를 기록하고, 시작 시 최신 복구 가능 스냅샷을 제안하는 흐름을 추가
- `ui/main_window_impl/persistence_runtime.py`/`ui/main_window_impl/persistence_session.py`/`ui/main_window_impl/pipeline_messages.py`: 수동 세션 저장은 실행 중 runtime archive를 더 이상 정리하지 않고, runtime flush/checkpoint/recovery write는 `archive_token` + `run_id` + captured path context를 사용해 stale completion을 무시한다. runtime manifest 복구는 sibling `segment_*.json` + `tail_checkpoint.json` 기준 best-effort salvage를 허용하고, 빈 URL 세션 로드와 recovery pointer 수명주기 hygiene도 같이 정리했다.
- `core/database_manager.py`: `subtitles` 테이블을 additive migration으로 확장해 `entry_id`/`source_*`/`speaker_*`/`speaker_changed`를 lossless round-trip으로 저장하고, 기본 검색을 FTS raw query가 아닌 literal substring 검색으로 고정
- `core/reflow.py`/`ui/main_window_persistence.py`: 수동 reflow를 prepared snapshot 기반 백그라운드 작업으로 이동하고, `SubtitleEntry` 메타데이터 및 timing 정책을 유지하도록 재작성
- `core/hwpx_export.py`/`ui/main_window_persistence.py`: DOCX/HWPX multiline export를 한 `SubtitleEntry = 한 문단/블록` 의미로 통일하고, 내부 개행은 line break로 표현
- `.gitignore`/`subtitle_extractor.spec`: runtime 복구 state(`session_recovery.json`)를 저장소/번들에서 제외하는 규칙을 명시
- `ui/main_window.py`/`ui/main_window_capture.py`/`ui/main_window_database.py`/`ui/main_window_persistence.py`/`ui/main_window_ui.py`/`ui/main_window_view.py`: v16.14.5에서 run-source 스냅샷 고정, live list manual/auto 정책 분리, DB/편집 목록의 점진 로드, dirty-session 종료 프롬프트, 단축키 문구 정합성이 반영되었지만 이 변경은 UI/상태 관리 레이어에 한정되며 코어의 글로벌 히스토리 + suffix 의미론을 바꾸지 않는다.
- `ui/main_window_view.py`/`ui/main_window_pipeline.py`/`ui/main_window_database.py`: v16.14.4에서 검색 기준이 전체 `self.subtitles` 스냅샷으로 바뀌고, 검색/DB 결과 focus 시 해당 entry가 보이도록 렌더 offset을 동적으로 조정했다. 이는 UI 탐색 경로 보강이며 코어의 글로벌 히스토리 + suffix 의미론은 변경하지 않는다.
- `ui/main_window.py`/`ui/main_window_ui.py`/`ui/main_window_persistence.py`/`ui/main_window_database.py`: v16.14.4에서 세션 로드/병합/리플로우/삭제 계열을 공통 runtime mutation guard로 묶고, 파일/DB 세션 로드 payload와 완료 핸들러를 통합했다. 이는 상태 전이 안전성 정리이며 코어 추출 알고리즘 자체는 바꾸지 않는다.
- `core/config.py`/`core/logging_utils.py`/`국회의사중계 자막.py`: v16.14.7(2026-04-08)에서 storage root를 `development/repo`, `portable/EXE`, `frozen default/%LOCALAPPDATA%`로 분리하고 startup storage preflight를 추가했지만, 이는 저장소/배포 경로 안전성 보강일 뿐 코어 파이프라인 의미론을 바꾸지 않는다.
- `ui/main_window_impl/persistence_session.py`/`runtime_lifecycle.py`/`database_dialogs.py`/`database_worker.py`/`persistence_runtime.py`/`view_editing.py`/`persistence_tools.py`: dirty-session save는 `저장 후 원래 액션 재개` deferred flow로 통일되고, archived session hydrate는 background worker + progress/cancel로 옮겨졌지만 이는 저장/편집 UX 보강이며 코어의 글로벌 히스토리 + suffix 추출 규칙은 유지된다.
- `ui/dialogs.py`/`ui/main_window_impl/capture_live.py`/`core/database_manager.py`: live list timeout/schema validation, malformed row drop, DB lineage(`lineage_id`, `parent_session_id`, `is_latest_in_lineage`)와 history badge가 추가되었지만 이는 네트워크/DB 메타데이터 레이어 보강이며 코어 자막 추출 알고리즘 자체는 바꾸지 않는다.
- `ui/main_window.py`/`ui/main_window_capture.py`: `self.driver` 접근을 `_driver_lock` + identity helper로 일원화하고, 시작 시 1회 live URL 감지 + 재연결 URL 재사용으로 handoff race를 줄임
- `ui/main_window_common.py`/`ui/main_window_pipeline.py`: `MainWindowMessageQueue(maxsize=500)`와 `run_id` envelope, 고빈도 메시지 coalescing, stale run drop 도입
- `ui/main_window_pipeline.py`/`ui/main_window_view.py`: `_add_text_to_subtitles`와 `_finalize_subtitle`를 shared append helper로 통합하고 realtime write/flush를 락 밖으로 이동
- `ui/main_window_view.py`: `_render_subtitles()`가 immutable snapshot clone 기준으로 tail patch를 반영
- `core/models.py`/`core/config.py`: `SubtitleEntry(entry_id=None)` 자동 ID 생성, `snapshot_clone()` 문서화, 기본 특별 코드 목록을 `IO`만 남기고 미검증 `정보위원회`/`NA`/`PP` 제거
- `ui/main_window_capture.py`: v16.14.2 수집 회귀 대응으로 자막 수집 경로를 이전 안정 structured probe 루프로 복귀
- `core/subtitle_pipeline.py`: `confirmed_segments` 기반 증분 confirmed-history 갱신으로 append/keepalive/last-row update hot path에서 전체 rebuild를 회피
- `core/models.py`: `SubtitleEntry.__slots__`, compact cache, `CaptureSessionState.snapshot_clone()` 도입으로 prepared snapshot 메모리 복제를 완화
- `ui/main_window_pipeline.py`/`ui/main_window_view.py`: `capture_state.entries`를 단일 source of truth로 고정하고, append/tail update는 delta 기반 갱신 + tail patch render 사용
- `ui/main_window_persistence.py`/`core/file_io.py`/`core/database_manager.py`: streaming JSON 저장, `SubtitleEntry` 직접 DB 저장, stale thread connection cleanup cadence 완화
- `typings/`/`pytest.ini`/`.gitignore`: 로컬 PyQt6·selenium·pytest stub, workspace basetemp(`.pytest_tmp`), 루트 `.hwpx` ignore 규칙으로 저장소 검증 경로를 고정
- `pyrightconfig.json`/`.vscode/settings.json`/`typings/PyQt6/QtNetwork.pyi`/`tests/test_encoding_hygiene.py`: `typings/`를 `stubPath`/`extraPaths`로 명시하고 `.pytest_tmp`를 정적 분석·인코딩 검사에서 제외하며, 로컬 stub 경로의 `reportMissingModuleSource` 경고를 끈다. `QNetworkAccessManager` 경로용 QtNetwork stub을 추가해 CLI `pyright`와 Pylance 결과를 일치시킨다.
- `ui/main_window_persistence.py`/`tests/test_review_20260323_regressions.py`: `pywin32` 미설치 시 HWP 저장은 즉시 HWPX로 대체되고, 저장 실패 후 사용자 선택 다이얼로그는 별도 경로로 유지
- `core/subtitle_pipeline.py`: `auto_clean_newlines` 런타임 옵션 도입, preview/live-row/flush 정규화 경로 통일
- `ui/main_window.py`/`ui/main_window_ui.py`: `✨ 자동 줄넘김 정리` 체크박스 추가, 기본 활성화 + `QSettings` 영속화
- `_extract_new_part`: `find()` → `rfind()` 전환 — suffix 충돌 시 과잉 추출 방지
- `_prepare_preview_raw`: 전체 리셋 → `_soft_resync()` 소프트 리셋 — 대량 중복 유입 방지
- `_extraction_worker`: MutationObserver 하이브리드 아키텍처 도입
- `subtitle_reset` 메커니즘: 발언자 전환(자막 영역 클리어) 감지 시 즉시 완전 리셋 + 버퍼 확정
- `_extraction_worker`: 시작/재연결 시 `_detect_live_broadcast` 실연결 (`xcode` → `xcgcd` 보완 URL 반영)
- `_extraction_worker`/`_handle_keepalive`: 동일 raw 유지 시 keepalive 큐 발행 및 end_time 주기 갱신 활성화
- `is_meaningful_subtitle_text`: 의미 있는 1~2자 발화 허용, 숫자/기호-only 문자열 차단
- `_read_subtitle_text_by_selectors`: `.smi_word` 목록 전체를 수집해 최근 창 텍스트로 조합 (첫 문장 이후 정체 완화)
- `_inject_mutation_observer_here`: Observer 타겟 탐색 시 컨테이너 우선 + 긴 텍스트 축약 보강
- `_process_raw_text`/`_soft_resync`: `_confirmed_compact` 상한(`Config.CONFIRMED_COMPACT_MAX_LEN=50000`) 도입
- `_add_text_to_subtitles`: 병합 기준 하드코딩 제거, Config 상수(`ENTRY_MERGE_MAX_GAP=5`, `ENTRY_MERGE_MAX_CHARS=300`)로 일원화
- `_merge_sessions`: 중복 제거 정책을 텍스트-only에서 `정규화 텍스트 + 시간 버킷(30초)` 기준으로 개선
- `closeEvent`/백그라운드 실행 경로: 공통 레지스트리 기반 종료 drain (`신규 작업 차단 -> inflight 대기 -> 자원 정리`)

### 2.3 구조 분리 이력 (v16.14.0 ~ v16.14.7)
- `ui/main_window.py`는 파사드로 축소되고, 실제 책임은 `ui/main_window_capture.py`, `ui/main_window_pipeline.py`, `ui/main_window_view.py`, `ui/main_window_persistence.py`, `ui/main_window_database.py`, `ui/main_window_ui.py`로 분리되었다.
- `core/live_capture.py`와 `core/subtitle_pipeline.py`는 더 이상 `MainWindow` 내부 임시 로직이 아니라 운영 기준 코어 모듈이다.
- `core/file_io.py`, `core/text_utils.py`, `core/reflow.py`, `core/database_manager.py`를 추가하고, `core/utils.py`와 `database.py`는 호환 shim으로 유지한다.
- `ui/main_window_types.py`는 분할된 mixin이 공유하는 `MainWindowHost` 타입 계약을 제공해 Pylance/Pyright 기준의 공통 `self` 표면을 고정하고, 로컬 `typings/`는 외부 GUI/selenium 패키지 해석 편차를 흡수한다.
- `v16.14.7`에서는 capture/browser/dom/observer, pipeline/state/queue/stream/messages, runtime/state/lifecycle/driver, view/render/search/editing 구현이 `ui/main_window_impl/`로 이동했고, `core/live_capture.py` 내부 구현은 `core/live_capture_impl/ledger.py`, `models.py`, `reconcile.py`로 재배치되었다. `ui/main_window_ui.py`는 공개 UI mixin 경로를 유지한다.
- 후속 리팩토링으로 `ui/main_window_database.py`, `ui/main_window_persistence.py`는 조합 facade만 남기고 세부 책임을 `ui/main_window_impl/database_*`, `ui/main_window_impl/persistence_*`로 세분화했다. facade import 경로와 테스트 진입점은 그대로 유지한다.

### 2.2 안정화 이력 (v16.12.1, 2026-02-25)
- `_extraction_worker`: URL에 `xcgcd`가 없을 때만 `xcode` 기반 자동 감지를 연결
- `_process_raw_text`/`_add_text_to_subtitles`: 1~2글자 발화 허용 + 기호/숫자-only 노이즈 차단 게이트 적용
- 세션 로드/병합 경로: 손상 항목만 건너뛰는 내결함성 강화

---

## 3. 현재 고정 파이프라인

```text
Worker(raw) [stable hybrid: MutationObserver 우선 + structured probe fallback]
  -> 시작/재연결 시 _detect_live_broadcast로 xcgcd 보완 URL 확정
  -> selector 후보 우선순위 정렬 (.smi_word:last-child 우선)
  -> .smi_word 목록 기반 창(window) 텍스트 조합
  -> 기본 문서 + 중첩 iframe/frame 순회
  -> driver lifecycle은 _driver_lock + identity helper로 serialize
  -> MutationObserver 버퍼 우선 수집, 미수집 시 structured probe 수행
  -> auto_clean_newlines 옵션(기본 ON)에 따라 줄바꿈/빈 줄 평탄화
  -> clean/compact 기준 중복 전송 억제
  -> 동일 raw 유지 구간 keepalive 메시지 발행
  -> 자막 영역 클리어 감지 → subtitle_reset (완전 리셋)
  -> MainWindowMessageQueue(preview: dict payload, internal run_id envelope)
  -> _prepare_preview_raw(정규화, 게이트, 재동기화, fallback)
     (desync/ambiguous 반복 시 _soft_resync 소프트 리셋)
  -> _process_raw_text(GlobalHistory+Suffix core, rfind 기반)
  -> 후단 정제(get_word_diff, recent compact tail)
  -> _add_text_to_subtitles / _finalize_subtitle(shared append helper, is_meaningful_subtitle_text 필터)
  -> MainWindowMessageQueue(keepalive/status/resolved_url coalesced) -> _handle_keepalive(end_time 연장)
  -> UI delta 반영 (append/tail update 증분 갱신, immutable snapshot + tail patch render)
  -> 종료 시 _drain_pending_previews 강제 플러시
```

---

## 4. 단계별 책임

### 4.1 Worker 입력 안정화 (하이브리드)
- 시작/재연결 시 `_detect_live_broadcast`로 최종 URL(`xcgcd`) 우선 확정
- 감지는 `xcgcd`가 없을 때 시작 시 1회만 수행하고, 재연결에서는 직전 확정 URL을 우선 재사용
- `self.driver` 읽기/쓰기/clear는 `_driver_lock`, `_set_current_driver`, `_take_current_driver`, `_clear_current_driver_if` 경로로만 수행
- MutationObserver 우선 → structured probe fallback — `_inject_mutation_observer`, `_collect_observer_changes`
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
- 동일 raw 유지 시 keepalive 주기 발행 (`Config.SUBTITLE_KEEPALIVE_INTERVAL`)
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
- 유의미 텍스트 게이트로 짧은 발화(한글/영문 포함) 허용 및 노이즈(기호-only/숫자-only) 차단
- `is_meaningful_subtitle_text` 기준으로 의미 텍스트만 반영

### 4.6 종료 보정
함수: `_drain_pending_previews`

역할
- 종료 직전 preview와 segments 소진
- 게이트 통과 실패 시에도 강제 처리 (`forced = clean_text_display(data)`)
- 누락 감소를 위한 2회 drain + `_finalize_pending_subtitle`
- stop timeout 뒤 inactive run으로 전환된 worker 메시지는 더 이상 세션 상태에 반영되지 않음

### 4.7 저장/렌더링 경로 고정
- `capture_state.entries`가 런타임 단일 source of truth이며, `self.subtitles`는 alias/view로만 유지한다
- `_finalize_subtitle()`는 호환용 API지만 `_add_text_to_subtitles()`와 같은 shared append/merge helper를 사용한다
- prepared snapshot은 `CaptureSessionState.snapshot_clone()`을 사용한다
  - pending preview 없음: shallow list snapshot
  - pending preview 있음: 마지막 엔트리만 clone 허용
- 세션 저장/자동 백업은 streaming JSON writer를 사용하고, DB 저장은 `SubtitleEntry` 직접 입력을 허용한다
- UI는 `PipelineResult` delta 기준으로 append/tail update를 증분 반영하며, 렌더 입력은 immutable snapshot clone을 사용하고 마지막 visible entry 수정은 full clear 대신 tail patch를 우선 사용한다

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
- `_add_text_to_subtitles` 병합 조건: `ENTRY_MERGE_MAX_GAP=5`, `ENTRY_MERGE_MAX_CHARS=300`
- 짧은 발화 정책: 한글/영문 포함 텍스트는 길이와 무관하게 허용
- keepalive 간격: `Config.SUBTITLE_KEEPALIVE_INTERVAL = 1.0초`
- `_confirmed_compact` 최대 길이: `Config.CONFIRMED_COMPACT_MAX_LEN = 50000`
- 세션 병합 dedupe 버킷: `Config.MERGE_DEDUP_TIME_BUCKET_SECONDS = 30`
- Observer 재시도 간격: `3.0초`
- 폴링 브리지 간격: `180ms`
- Worker queue 최대 크기: `500`
- coalesced worker message types: `preview`, `keepalive`, `status`, `resolved_url`
- UI queue drain budget: `약 8ms`, 최대 `50`건

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
- 정적 분석/회귀 테스트
  - `pyright`
  - `pytest -q`
- 스모크 테스트
  - `python tests/test_reflow.py`
  - `python tests/test_core_algorithm.py`
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

## 13. 저장소 기준 파일

- `pyrightconfig.json`: 저장소 공통 타입 체크 기준(`standard`, Python 3.10)
- `.vscode/settings.json`: Pylance 워크스페이스 설정
- `.editorconfig`, `.gitattributes`: UTF-8 without BOM + CRLF 기준 유지
- `typings/`: 글로벌 인터프리터 편차를 흡수하는 로컬 PyQt6/selenium/pytest stub
- `pytest.ini`: 워크스페이스 내부 basetemp(`.pytest_tmp`) 강제
- `requirements-dev.txt`: 개발/검증 및 optional export 의존성 기준선
- `ui/main_window_types.py`: 분할된 `MainWindow` mixin의 공통 `self` 타입 계약(`MainWindowHost`)
- `tests/test_encoding_hygiene.py`: repo tracked 텍스트 파일의 UTF-8/BOM/U+FFFD 위생 및 핵심 한글 문자열 round-trip 검증
- `tests/test_pyright_regression.py`: 워크스페이스 전체 `pyright --outputjson` 결과가 `0 errors`인지 회귀 검증

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
