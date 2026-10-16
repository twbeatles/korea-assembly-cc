# 테스트 견고화 검증 기록 (2026-10-16)

CodeGraph MCP로 수집 DOM → live ledger → 자막 파이프라인, 세션 저장 → SQLite worker,
runtime segment → 내보내기의 호출 경로와 기존 회귀 테스트를 조사했다.
분기 커버리지는 취약 경로를 찾는 보조 수단으로 사용했으며, 테스트 개수를 목표로 삼지 않았다.

## 보완한 동작 계약

| 영역 | 실제로 실행하고 확인하는 내용 |
| --- | --- |
| DOM 활성화 | 실제 Chromium HTML에서 AI → 기본 → 일반 → SMI 버튼의 클릭 순서, 이미 활성화된 버튼의 재클릭 방지, 페이지 함수 실행 후 활성 상태 재검사, 레이어 표시와 컨트롤 부재 |
| DOM 수집 | 실제 CSS 계산과 JavaScript로 화자 분리, 정정 후 node key 유지, 미확정 자막의 container fallback 유출 차단, 공백 정규화, 최근 3행 preview |
| 수집 통합 | DOM 결과를 실제 live ledger와 파이프라인에 전달해 중복 이벤트 무시, 기존 행 정정, entry ID와 화자 메타데이터 보존 |
| Observer | 실제 MutationObserver의 변경·동일 텍스트·삭제 reset·다음 발언 이벤트와 버퍼 drain |
| 파일 저장 | JSON/streaming JSON/text/binary 및 writer callback 전체에서 fsync·replace 실패 시 원본 보존, 임시 파일 정리, 재시도 성공 |
| 직렬화 중단 | 생성기나 callback이 일부 데이터를 쓴 뒤 실패해도 기존 파일 또는 파일 부재 상태 유지; 한글·인용부호·개행·이모지 round trip |
| SQLite 트랜잭션 | 실제 배치 삽입 후 iterator 오류와 SQLite trigger 오류를 발생시켜 행·FTS·lineage rollback, 다른 연결에 미완성 데이터 비노출, 동일 operation ID 재시도 |
| SQLite 중복·이관 | 두 실제 스레드의 동시 저장이 한 번만 반영되는지, DB 재개방 후 재시도, 구버전 스키마 이관 후 기존 데이터 보존과 신규 저장 |
| 세션 통합 | 디스크 segment와 메모리 tail을 실제 JSON·SQLite worker·복구 포인터에 저장하고 ID·시간·출처·화자·품질 메타데이터까지 비교 |
| 실패·동시성 | DB 실패 시 완전한 JSON과 복구 포인터 유지 후 재시도; 손상된 archive를 읽다 실패하면 이전 snapshot 보존; 저장 중 capture가 바뀌어도 저장 시작 시점의 자막 유지 |
| 내보내기 | 실제 background worker에서 archive+tail을 SRT/VTT로 내보내고 전체 파일의 cue 번호·상대 시간·내용을 정확히 비교; 작업 후 registry와 스레드 정리 |

기존 `_RecordingDriver`가 dict를 bool로 바꾸어 `{"ok": False}`도 성공처럼 전달하던
테스트 대역을 수정하고 실패 payload 회귀 검증을 추가했다. 소스 문자열을 검사하던
활성화·화자 분리 테스트 두 개는 실제 DOM 결과를 검증하도록 대체했다.

## 테스트 실행 조건

`tests/test_support/browser_dom.py`는 기존 PySide6의 QtWebEngine을 사용한다.
외부 사이트, 별도 Chrome 설치, ChromeDriver 다운로드가 필요하지 않다.
Selenium이 전달하는 원본 스크립트를 Chromium에서 실행하며, 테스트 어댑터는 최상위
문서만 지원한다. iframe 전환과 실제 Selenium 세션 전체를 검증했다고 해석하면 안 된다.
각 JavaScript/HTML 작업은 10초 제한을 두며 브라우저 테스트는 `requires_subprocess`로 분류한다.

저장 통합 테스트는 UI 입력·알림만 대체한다. 파일 I/O, 직렬화, segment 읽기,
SQLite 트랜잭션, DB worker, 내보내기 worker를 대체하지 않는다.
비동기 순서는 Event/Queue로 동기화하고 대기 시간 제한과 스레드 종료 검증을 둔다.

초기 실행에서 Windows 임시 파일 정리 실패가 한 번 관찰됐고, 후속 저장 관련 묶음은
5회 연속 통과했다. 최초 실패의 OS 원인은 특정하지 못했다. 일시적인 PermissionError에
대응하도록 공통 정리 함수에 최대 3회(추가 대기 합계 30ms) 재시도를 추가했다.
6개 writer 각각의 일시 잠금과 영구 잠금 상황을 주입해 정리와 재시도 상한,
최초 저장 예외 보존을 검증한다. 테스트 자체에 실패를 숨기는 재실행은 넣지 않았다.

## 재현 명령

```powershell
python -m pytest -q -rs
python scripts/check_before_push.py --pyright-only
python -m pytest tests/test_capture_chrome_parity_p1.py tests/test_file_io_safety.py tests/test_database_save_idempotency.py tests/test_session_storage_integration.py -q
```

기존 CI의 전체 pytest 경로에 자동 포함되므로 별도 opt-in은 필요하지 않다.
실제 국회 서버 계약 smoke는 기존 `RUN_LIVE_SMOKE=1` 실행 조건을 유지한다.

## 검증 근거

- 변경 전: 전체 **486 passed, 2 skipped**.
- 변경 후: 전체 **539 passed, 2 skipped** (45.54초), pyright **0 errors, 0 warnings**.
  건너뛴 항목은 외부 live 계약 smoke와 subprocess 가능 환경의 in-process 전용 fallback이다.
- Python statement+branch 집계: `core/file_io.py` **76% → 97%**,
  `core/database_impl/sessions.py` **91% → 93%**.
- 의도적 메모리 내 결함 주입: DB rollback 제거, AI 우선순위 반전,
  두 저장 단계의 snapshot clone 제거를 각각 관련 테스트가 실패로 검출했다.
  원본 파일은 수정하지 않았으며, 실험에서는 환경에 설치된 무관한 pytest plugin의
  자동 로딩을 껐다.
- coverage의 Python 분기 집계는 JavaScript 내부 분기를 측정하지 않는다.
  DOM 검증의 근거는 실제 Chromium 실행 결과와 클릭·행·이벤트의 assertion이다.
- 실제 live 서버·설치된 ChromeDriver·frozen EXE 검증은 이 오프라인 실행 범위에 포함하지 않았다.
