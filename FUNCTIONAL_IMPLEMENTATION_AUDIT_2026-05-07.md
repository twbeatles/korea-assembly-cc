# 기능 구현 잠재 리스크 / 추가 개선 점검 보고서 (2026-05-07)

> 본 보고서는 v16.14.7 코드 베이스에서 식별된 잠재 이슈와 후속 개선 권고를 정리한 문서이며,
> 같은 날짜(2026-05-07) 후속 패치에서 아래 §1~§3 / §4 다수 항목이 코드/문서에 반영되었다.

## 검토 기준

- [README.md](README.md) / [CLAUDE.md](CLAUDE.md) / [GEMINI.md](GEMINI.md) (v16.14.7)
- [PIPELINE_LOCK.md](PIPELINE_LOCK.md), [ALGORITHM_ANALYSIS.md](ALGORITHM_ANALYSIS.md)
- 직전 점검 [FUNCTIONAL_IMPLEMENTATION_AUDIT_2026-05-06.md](FUNCTIONAL_IMPLEMENTATION_AUDIT_2026-05-06.md)
- 실제 구현 (`core/`, `ui/main_window_impl/`, `subtitle_extractor.spec`, `tests/`)

---

## 1. 우선순위: 높음 (모두 반영 완료)

### 1.1 [DONE] `core/subtitle_processor.SubtitleProcessor` 죽은 코드 제거

- 운영 자막 파이프라인은 `core/subtitle_pipeline.py` + `core/live_capture.py`만 사용한다. `SubtitleProcessor`는 `add_confirmed()`만 호출되고 절대 읽히지 않는 쓰기 전용 상태였다.
- 적용 내역
  - `ui/main_window_impl/view_render.py`에서 `self.subtitle_processor.add_confirmed(text)` 호출 제거.
  - `ui/main_window_impl/runtime_state.py`에서 `self.subtitle_processor = SubtitleProcessor()` 초기화 및 import 제거.
  - `ui/main_window_common.py`, `ui/main_window_types.py`의 `SubtitleProcessor` import / `MainWindowHost.subtitle_processor` 속성 제거.
  - `tests/test_review_20260323_regressions.py`의 `_DummyProcessor` 및 stub 주입 / `confirmed == []` assertion 제거(대신 `capture_state.last_processed_raw` 검증으로 의미 동등화).
  - `subtitle_extractor.spec` hidden import에서 `core.subtitle_processor` 제거.
  - `core/subtitle_processor.py` 파일 자체 삭제.
  - `CLAUDE.md` / `GEMINI.md` 5.1 파일 트리 및 `README.md` hidden import 안내에서 항목 제거.

### 1.2 [DONE] 트레이 최소화 시 추출 중 종료 프롬프트 우회

- `closeEvent`에서 `minimize_to_tray and is_running`이면 3-way 선택(Yes=백그라운드 캡처 유지, No=중지 후 종료, Cancel=작업 유지) 모달을 띄우고, 트레이 알림 본문도 "추출 중 상태로 트레이에 최소화되었습니다."로 분리해 사용자 의도를 명시한다.

### 1.3 [DONE] DB worker shutdown timeout + 종료 단계 checkpoint

- `closeEvent`에서 `_shutdown_db_worker(timeout=Config.SAVE_THREAD_SHUTDOWN_TIMEOUT)`을 사용해 worker 종료를 합리적으로 대기.
- `db.close_all()` 직전에 `db.checkpoint("TRUNCATE")`를 시도(예외 무시)해 WAL 비대를 방지.
- 강제 종료(escalation `_force_exit_process`) 직전에도 진단 저장 후 `db.checkpoint("PASSIVE")`를 시도.

### 1.4 [DONE] `MainWindowMessageQueue.put` 무한 대기 방어

- `put(item, block=True, timeout=None)` 호출이 raw queue를 무한 대기하지 않도록 안전 timeout(`_PUT_SAFETY_TIMEOUT_SECONDS = 5.0s`) 강제. `queue.Full` 발생 시 호출자가 즉시 인지 가능.
- worker 스레드 경로(run_id 등록 상태)는 기존대로 `_emit_worker_message` 비차단 흐름을 사용해 영향 없음.

---

## 2. 우선순위: 중간 (모두 반영 완료)

### 2.1 [DONE] `LiveBroadcastDialog` visibility-aware 자동 새로고침

- `QShowEvent`에서 timer 재시작 / `QHideEvent`에서 timer 일시정지 추가. 다이얼로그가 숨겨진 동안에는 외부 API(`live_list.asp`) 폴링을 중지한다.

### 2.2 [DONE] JSON 손상 시 백업 폴더 열기 크로스플랫폼 fallback

- `os.startfile` (Windows) 실패 또는 비-Windows 환경에서는 `webbrowser.open(file://...)`로 폴백, 모두 실패 시 경로를 toast로 안내.

### 2.3 [DONE] HWP 저장 retry sleep을 `stop_event.wait`로 교체

- `_save_hwp.do_save_with_error`의 `time.sleep(1)` → `stop_event.wait(1.0)`. 종료 신호를 즉시 반영, 종료 단계 추가 지연 방지.

### 2.4 [DONE] `_cleanup_old_backups` race-safe 처리

- 각 `unlink()`에 `missing_ok=True` 및 개별 `try/except`. 한 항목 삭제 실패가 다른 백업 정리에 영향이 가지 않는다.

### 2.5 [DONE] `_emit_control_message` 큐 포화 시 사용자 알림

- 비-coalescing 메시지 drop 시 `_notify_dropped_control_message(msg_type)`로 30초 rate-limit 이내에서 한 번만 status bar 경고를 노출. logger.warning은 유지.

### 2.6 [DONE] selector 자동 전환 시 Observer 즉시 재주입

- `_extraction_worker`에서 `_find_subtitle_selector` 결과로 selector를 바꾼 즉시 `_inject_mutation_observer`를 호출해 frame_path까지 동기화. 약 3초 polling-only 윈도우 제거.

### 2.7 [DONE] frozen smoke CLI `--smoke-output` 옵션

- `--smoke-output <path>` 추가. stdout 외에 JSON 한 줄을 파일로 기록한다. frozen + console=False에서 stdout이 사라지는 CI 환경에서 신뢰성 확보.

### 2.8 (보류) `_process_message_queue` 종료 단계 backlog

- 종료 단계 backlog는 현재 `_wait_for_background_threads_during_exit` 루프 안에서 반복 `_process_message_queue()` 호출로 흡수된다. 실서비스 영향이 낮아 본 배치에서는 보류, 다음 점검 시 재평가.

---

## 3. 우선순위: 낮음 / 위생

### 3.1 [DONE] `RECENT_HISTORY_COMPACT_LENGTH` Config 노출

- `Config.RECENT_HISTORY_COMPACT_LENGTH = 5000`을 신설하고, `core/subtitle_pipeline.py`는 이 값을 import해 사용. `CONFIRMED_COMPACT_MAX_LEN`과 함께 튜닝 가능.

### 3.2 (참고) `DatabaseManager.get_statistics` SUM NULL 처리

- 현 코드의 `or 0` 패턴은 안전하나 0과 "데이터 없음" 분기는 UI 측에서 의미 분리 필요. 본 배치에서는 동작 변경 없음.

### 3.3 (참고) `database.py` shim

- 외부 호환성 유지를 위해 spec에 등재된 채로 둠. 사용처가 사라지면 다음 메이저 정리에서 삭제 후보.

### 3.4 (보류) `is_meaningful_subtitle_text` 자모 처리

- 사용 케이스 빈도가 매우 낮아 본 배치에서는 변경하지 않음. 추후 한자/외래어 정책 변경 시 재검토.

### 3.5 (참고) 종료 단계 `_save_setting_value` 실패 toast 한계

- toast widget이 정리된 후의 실패는 logger.warning만 남는다. README/CLAUDE.md 문서화 권장 사항이며 동작 변경은 없다.

### 3.6 [DONE] `LiveBroadcastDialog` empty + dropped_rows 메시지 통합

- `표시할 생중계 항목이 없습니다. (손상 항목 N개 제외)` 한 줄로 표시되도록 분기 정리.

---

## 4. 문서 / 테스트 정합 점검

### 4.1 [DONE] `tests/test_review_20260323_regressions.py` 갱신

- `_DummyProcessor`/`subtitle_processor` stub 제거. `_finalize_subtitle` 회귀는 `capture_state.last_processed_raw`로 직접 검증.

### 4.2 [DONE] `CLAUDE.md` / `GEMINI.md` / `README.md` 트리/안내 갱신

- `core/subtitle_processor.py` 항목 제거. spec hidden import 안내 문구도 동기화.

### 4.3 (참고) 단축키 단일 출처

- 다음 PR에서 별도로 정리 권장. 현 보고서에서는 동작 변경 없음.

### 4.4 (참고) `typings/` stub 동기화 규약

- 새 PyQt 모듈 사용 시 stub 갱신을 PR 체크리스트로 추가 권장.

---

## 5. 본 배치 검증 기준선 (2026-05-07)

- `pytest -q`: **216 passed, 1 skipped** (pyright 회귀 1건은 별도 실행으로 검증).
- `python -m pyright --outputjson`: **0 errors / 0 warnings / 0 information**.
- import smoke: `MainWindow 16.14.7`.
- source smoke: `python "국회의사중계 자막.py" --smoke --smoke-storage-dir .pytest_tmp/smoke-storage` → `ok=true`, exit code `0`.
- source storage smoke: `python "국회의사중계 자막.py" --smoke-storage-preflight --smoke-storage-dir .pytest_tmp/smoke-storage` → `ok=true`, exit code `0`.
- `--smoke-output` 옵션이 동일 JSON을 파일로 기록함을 확인.

frozen 빌드 회귀(`pyinstaller --clean subtitle_extractor.spec` + 기본 `--smoke` + `portable.flag` `--smoke-storage-preflight`)는 본 환경에서 실행하지 않았다. 릴리스 직전 동일 절차로 한 번 더 확인할 것.

---

## 6. 후속 권장

- §2.8 종료 단계 message queue backlog 흡수 검증 강화.
- §3.4 `is_meaningful_subtitle_text` 정책 확장 여부 결정.
- §4.3 단축키 단일 출처(테이블 모듈) 도입.
- `database.py` shim 사용처 재확인 후 정리(§3.3).
- 다음 점검 시 본 보고서를 기준으로 §1~§3 미해결 항목과 신규 리스크를 함께 갱신.
