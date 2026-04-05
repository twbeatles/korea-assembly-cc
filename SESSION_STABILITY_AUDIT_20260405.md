# 세션 안정성 감사 보고서 (2026-04-05)

## 범위
- 기준 문서: `README.md`, `CLAUDE.md`
- 점검 초점: 몇 시간 이상 자막 수집을 지속하는 운영 시나리오에서의 세션 안정성
- 중점 영역: Chrome/WebDriver 연결 수명주기, 장시간 수집 중 프로그램 생존성, 저장/종료 interlock, 장시간 누적 성능 비용

## 현재 기준선
- `pytest -q`: `131 passed`
- `pyright`: `0 errors, 0 warnings, 0 informations`

현재 회귀 테스트와 타입 체크는 통과하지만, 아래 항목들은 장시간 수집에서 실제 장애나 반쯤 멈춘 상태를 만들 수 있는 잠재 리스크로 보입니다.

## 주요 Findings

### 1. `worker finally`의 `driver.quit()`가 무기한 멈출 수 있음
- 심각도: 높음
- 근거:
  - `ui/main_window_impl/capture_browser.py:116-127`
  - `ui/main_window_impl/capture_browser.py:545-548`
  - 비교 기준: `ui/main_window_impl/runtime_lifecycle.py:227-266`
  - 문서 기대치: `README.md:39-42`, `README.md:129-130`, `CLAUDE.md:69`, `CLAUDE.md:215`
- 관찰:
  - Worker 종료 경로의 `_dispose_driver()`는 `driver.quit()`를 직접 호출합니다.
  - `stop/close` 경로에는 `_force_quit_driver_with_timeout()`가 있지만, worker `finally`에는 같은 보호가 적용되지 않습니다.
- 장시간 운영 리스크:
  - Chrome 세션이 비정상 상태일 때 `quit()`가 반환하지 않으면 worker thread가 끝나지 않습니다.
  - 이후 재시작, 종료, 세션 전환이 “살아는 있지만 안 끝나는” 상태로 꼬일 수 있습니다.
  - README/CLAUDE가 강조하는 driver lifecycle 정합성과 실제 종료 경로가 일부 분리되어 있습니다.
- 권장 수정:
  - Worker 쪽 드라이버 폐기도 timeout wrapper를 공용 사용으로 통일합니다.
  - timeout 시 detached quarantine로 넘기고, worker는 반드시 빠져나오게 해야 합니다.

### 2. 자동 재연결이 꺼져 있을 때 recoverable WebDriver 오류가 “실패 종료”가 아니라 경고 루프로 남을 수 있음
- 심각도: 높음
- 근거:
  - `ui/main_window_impl/capture_browser.py:455-538`
  - 문서 기대치: `README.md:415`, `README.md:620`, `CLAUDE.md:215`
- 관찰:
  - `auto_reconnect_enabled`가 `False`인 상태에서 recoverable 오류가 발생해도, 현재 코드는 fatal 종료 대신 `logger.warning(...)` 후 `0.5초` 대기 루프로 남습니다.
  - 이 분기에서는 `error`/`finished`를 사용자 의미상 “세션 실패”로 승격하지 않습니다.
- 장시간 운영 리스크:
  - 크롬 세션은 이미 죽었는데 UI는 추출 중처럼 보일 수 있습니다.
  - 로그만 계속 쌓이고 실제 수집은 진행되지 않는 half-dead 상태가 생깁니다.
  - 장시간 unattended 운용에서 가장 위험한 유형입니다. 사용자는 “수집이 살아 있다”고 오해하기 쉽습니다.
- 권장 수정:
  - 자동 재연결이 꺼진 경우 recoverable 오류도 즉시 terminal failure로 승격합니다.
  - 상태바/트레이/토스트에 “연결 끊김으로 수집 종료”를 명시하고 worker를 정리해야 합니다.

### 3. bounded queue가 가득 찰 때 background save/load/DB thread가 `put()`에서 영구 대기할 수 있음
- 심각도: 높음
- 근거:
  - `ui/main_window_common.py:241-268`
  - `ui/main_window_impl/pipeline_messages.py:101-123`
  - `ui/main_window_persistence.py:1131-1145`
  - `ui/main_window_database.py:260-280`
  - 문서 기대치: `README.md:169`, `CLAUDE.md:23`, `CLAUDE.md:253`
- 관찰:
  - worker 메시지는 run-scoped/coalescing 경로를 타지만, 세션 저장 완료/실패와 DB task 결과는 일반 queue에 직접 `put()`합니다.
  - `MainWindowMessageQueue.put()`는 worker run id가 없으면 내부 `queue.Queue.put()`를 그대로 호출합니다.
  - UI thread는 `_process_message_queue()`에서 `약 8ms / 최대 50건`만 처리합니다.
- 장시간 운영 리스크:
  - UI thread가 잠시 막히거나 backlog가 커지면 background thread가 완료 메시지를 queue에 못 넣고 block될 수 있습니다.
  - 종료 시 `_wait_for_background_threads_during_exit()`는 해당 thread 종료를 기다리므로, save/load/DB thread와 종료가 함께 물리는 교착형 증상이 발생할 수 있습니다.
- 권장 수정:
  - non-worker control message도 timeout 있는 `put()` 또는 별도 완료 채널로 분리하는 것이 안전합니다.
  - 적어도 `session_save_done`, `session_save_failed`, `db_task_result`, `db_task_error`는 queue full 시 block 대신 drop-safe/replace-safe 정책이 필요합니다.

### 4. detached driver 정리가 `stop/close` 때만 이뤄져 장시간 재연결 중 Chrome 프로세스가 누적될 수 있음
- 심각도: 중간
- 근거:
  - `ui/main_window_impl/capture_browser.py:121-124`
  - `ui/main_window_impl/runtime_lifecycle.py:211-212`
  - `ui/main_window_impl/runtime_lifecycle.py:274-284`
  - `ui/main_window_impl/runtime_lifecycle.py:494-494`
- 관찰:
  - `_dispose_driver()`에서 `quit()` 예외가 나면 driver를 `_detached_drivers`에 쌓습니다.
  - 실제 정리는 `_cleanup_detached_drivers_with_timeout()`이 호출되는 `stop/close` 시점까지 미뤄집니다.
- 장시간 운영 리스크:
  - 수집 도중 네트워크/Chrome 불안정으로 reconnect가 반복되면 실패한 old driver가 세션 종료 전까지 남을 수 있습니다.
  - 누적되면 메모리, 핸들, Chrome 프로세스 수가 늘어 운영 안정성을 갉아먹습니다.
- 권장 수정:
  - reconnect 성공 직후 또는 주기적 janitor 타이머에서 detached driver 정리를 시도하는 편이 안전합니다.
  - 최소한 detached driver 수를 상태/로그에 집계해 누적 여부를 드러내는 것이 좋습니다.

### 5. 렌더 경로가 전체 자막을 먼저 clone한 뒤 tail만 잘라서, 세션이 길어질수록 UI 갱신 비용이 계속 증가함
- 심각도: 중간
- 근거:
  - `ui/main_window_impl/view_render.py:174-212`
  - `ui/main_window_impl/view_render.py:350-351`
  - `ui/main_window_impl/pipeline_stream.py:150`
  - 문서 기대치: `README.md:660`, `CLAUDE.md:264`
- 관찰:
  - `_render_subtitles()`는 `self.subtitles` 전체를 `[entry.clone() for entry in self.subtitles]`로 먼저 복제합니다.
  - 그 뒤에야 `Config.MAX_RENDER_ENTRIES` 기준으로 뒤쪽만 잘라 씁니다.
- 장시간 운영 리스크:
  - 화면에는 최대 500개만 보여도, 실제 렌더 비용은 전체 자막 길이에 비례합니다.
  - preview/commit 때마다 이 경로가 반복되므로 몇 시간 뒤에는 “데이터는 쌓이는데 UI가 점점 무거워지는” 현상이 나올 수 있습니다.
- 권장 수정:
  - lock 안에서 필요한 tail 구간의 index만 계산한 뒤, visible window만 clone하는 방식으로 바꾸는 것이 좋습니다.
  - 장시간 세션을 위한 render budget telemetry도 있으면 좋습니다.

### 6. 자동 백업이 전체 세션을 주기적으로 재스냅샷하여 긴 세션에서 CPU/메모리 spike를 만들 수 있음
- 심각도: 중간
- 근거:
  - `ui/main_window_impl/pipeline_state.py:156-170`
  - `ui/main_window_persistence.py:316-356`
  - `ui/main_window_persistence.py:409-417`
  - `core/models.py:223-240`
  - `core/config.py:63-67`
  - 문서 기대치: `README.md:63-64`, `CLAUDE.md:95`
- 관찰:
  - 자동 백업은 5분마다 prepared snapshot을 만들고, 백업 write 시작 시 다시 `snapshot_entries = [entry.clone() for entry in prepared_entries]`를 수행합니다.
  - JSON writer는 streaming이지만, 그 전에 전체 자막 리스트 복제가 선행됩니다.
- 장시간 운영 리스크:
  - 자막이 수만 건으로 커지면 5분마다 큰 메모리 할당과 CPU burst가 반복됩니다.
  - 수집/렌더와 겹치는 타이밍에 일시적인 끊김이나 queue backlog를 악화시킬 수 있습니다.
- 권장 수정:
  - auto backup은 immutable prepared snapshot을 더 직접적으로 활용하거나, chunked/appendable journal 방식으로 전환하는 것이 좋습니다.
  - 최소한 백업 대상 길이, 백업 소요 시간, 백업 skip 횟수를 로그/상태로 남겨 장시간 세션에서 관찰 가능해야 합니다.

### 7. 로그 파일이 프로세스 생존 시간 동안 무한 증가하며, 경고 루프와 결합되면 디스크 압박이 빨라짐
- 심각도: 중간 이하
- 근거:
  - `core/logging_utils.py:13-46`
- 관찰:
  - 파일 로그는 startup 시점 날짜로만 파일명을 정하고, 이후에는 plain `FileHandler`로 계속 append합니다.
  - 프로세스가 자정을 넘어도 새 파일로 넘어가지 않고, size rotation도 없습니다.
- 장시간 운영 리스크:
  - 수집을 오래 켜둘수록 하나의 로그 파일이 계속 커집니다.
  - 특히 Finding 2처럼 경고 루프가 생기면 디스크 사용량이 빠르게 증가합니다.
- 권장 수정:
  - `TimedRotatingFileHandler` 또는 size-based rotation을 도입하는 편이 좋습니다.
  - 운영 빌드에서는 debug log verbosity 상한도 같이 검토할 가치가 있습니다.

### 8. 종료는 데이터 보존 측면에서 안전해졌지만, background thread가 진짜로 멎으면 앱이 영구히 안 꺼질 수 있음
- 심각도: 중간
- 근거:
  - `ui/main_window_impl/runtime_lifecycle.py:380-418`
  - `ui/main_window_impl/runtime_lifecycle.py:448-476`
  - `core/config.py:63`
- 관찰:
  - 현재 `SAVE_THREAD_SHUTDOWN_TIMEOUT`은 force-exit cutoff가 아니라 warning emission 시점입니다.
  - 백그라운드 작업이 실제로 종료되지 않으면 `closeEvent()`는 계속 기다립니다.
- 장시간 운영 리스크:
  - 저장 안전성은 올라가지만, 저장 thread/DB thread/queue blocked thread가 wedge되면 사용자는 앱을 정상 종료할 수 없습니다.
  - 운영자 관점에서는 “데이터 보전”과 “강제 탈출 수단”이 둘 다 필요합니다.
- 권장 수정:
  - 현 정책은 유지하더라도, 2차 선택지로 `강제 종료` 버튼 또는 진단 정보 포함 대화상자를 추가하는 것이 좋습니다.
  - 어떤 thread를 기다리는지 이름과 경과 시간을 보여주면 현장 대응성이 좋아집니다.

## 테스트 공백
- `tests/test_worker_stability.py`에는 reconnect/health check는 있지만, `driver.quit()` hang 또는 worker finally timeout 경로 검증은 없습니다.
- queue full 상태에서 `session_save_done`/`db_task_result`가 background thread를 block하지 않는지 검증하는 테스트가 없습니다.
- 장시간 세션 크기 증가에 따른 render/auto-backup 비용 상한을 확인하는 회귀 테스트가 없습니다.
- 자동 재연결이 꺼진 상태에서 recoverable 오류가 “명확한 종료”로 정리되는지 검증하는 테스트가 없습니다.

## 우선순위 제안
1. Worker driver dispose timeout 통일
2. auto reconnect off 상태의 recoverable 오류를 terminal failure로 승격
3. background 완료 메시지의 queue-full block 제거
4. long-session render/backup 비용 절감
5. detached driver janitor 및 log rotation 추가

## 총평
현재 구현은 문서에서 약속한 “자동 재연결, 복구 스냅샷, 종료 대기”의 큰 방향은 잘 반영되어 있습니다. 다만 장시간 세션 안정성 기준으로 보면, 진짜 위험한 지점은 “즉시 크래시”보다 “죽지 않았지만 더 이상 제대로 수집하지 않는 상태”와 “오래 켜둘수록 커지는 누적 비용”입니다.

특히 1, 2, 3번은 수집 세션을 몇 시간 이상 돌릴 때 운영 신뢰성을 직접 떨어뜨릴 수 있는 항목이라 우선 대응 가치가 높습니다.
