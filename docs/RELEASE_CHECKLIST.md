# 릴리스 체크리스트

Windows 데스크톱 배포용 운영 체크리스트입니다. 인증서와 업데이트 호스팅은 외부 릴리스 인프라에서 준비하며 개인 키는 저장소에 넣지 않습니다.

참고 문서:

- [`CHROME_EXTENSION_PARITY.md`](CHROME_EXTENSION_PARITY.md) — Chrome 확장과의 수집 계약 정합
- [`HWPX_EXPORT_ANALYSIS.md`](HWPX_EXPORT_ANALYSIS.md) — HWPX 패키지 유지 방침 (스키마 전면 개편 비대상)

## 1. 품질 게이트

```bash
pip install -r requirements-dev.txt
python scripts/install_git_hooks.py          # 푸시 전 pyright 훅 (1회)
python scripts/check_before_push.py --pyright-only
python -m pytest -q
python -m pyright
python scripts/run_release_verification.py --offline --skip-build --instantiate-window
```

위 검증기는 resource budget, Ed25519 manifest, artifact hash, smoke rollback과 실제 Qt commit·세션/DB 통합·동시 저장 fixture를 전체 pytest 전에 명시적으로 실행한다.

QtWebEngine 미제공 환경에서는 DOM fixture만 skip하며 나머지 capture 테스트는 수집한다. 설치된 Chrome으로 검증할 때는 PowerShell의 `$env:KACC_TEST_BROWSER='chrome'`를 사용한다. Selenium Manager의 최초 드라이버 준비는 네트워크가 필요할 수 있고 fixture 페이지 자체는 오프라인이다.

- [ ] 실제 dict preview의 stable/fallback commit → realtime/알림, JSON·DB·export·재로드 회귀 통과
- [ ] segment missing/변조/손상과 cache hit/miss에서도 기존 저장물·dirty 상태 보존
- [ ] 일반 JSON의 byte/entry 상한·진행 표시·취소·종료 취소 확인
- [ ] observer ON/OFF의 same-text row/화자/frame 변경 보존 확인
- [ ] archive index 0·이모지 뒤 검색·후속 render에서도 검색 선택 유지
- [ ] 기존 HWP 저장 실패 시 원본 보존, 실제 한컴 COM에서도 확인
- [ ] 프리셋 쓰기 실패/이름 충돌 시 기존 상태 보존, stale reflow 결과 거절
- [ ] UI 병합의 손상 파일/항목 거절·누적 상한·runtime manifest 입력 회귀 통과

푸시 전: `pre-push` 훅 또는 `check_before_push.py` 로 **pyright 0 errors** 확인.  
GitHub CI는 **pyright(fail-fast) → pytest** 순으로 실행한다. 타입 오류는 전체 테스트 전에 실패한다.

### CI 실패 시 빠른 대응

| 증상 | 원인 후보 | 조치 |
|------|-----------|------|
| `test_pyright_regression` / Pyright step 실패 | `reportOptionalMemberAccess` 등 타입 오류 | 로컬 `python scripts/check_before_push.py --pyright-only` 로 파일:줄 확인 후 수정 |
| pytest 만 실패 | 회귀 테스트 | 로그의 FAILED 테스트 재현 |
| pip cache / setup-python 실패 | `cache-dependency-path` 누락 | `requirements-dev.txt` 경로 유지 (이미 설정됨) |

`requirements-dev.txt` 의 `pyright==…` 핀을 CI와 로컬이 공유한다. 임의 `pip install -U pyright` 로 버전을 올리면 CI와 결과가 달라질 수 있다.

라이브/빌드 포함 전체:

```bash
python scripts/run_release_verification.py
```

### GitHub Actions (`.github/workflows/ci.yml`)

- 의존성 핀은 **`requirements-dev.txt` 단일 파일**이다 (`requirements.txt` / `pyproject.toml` 없음).
- `actions/setup-python` 에 `cache: pip` 를 쓸 때는 반드시  
  `cache-dependency-path: requirements-dev.txt` 를 함께 지정한다.  
  누락 시 setup 단계에서  
  `No file ... matched to [**/requirements.txt or **/pyproject.toml]` 로 즉시 실패한다.
- Windows runner 환경 변수 고정:
  - `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8` (한글 smoke JSON stdout 유실 방지)
  - `QT_QPA_PLATFORM=offscreen` (GUI 없는 runner 에서 MainWindow smoke)
- subprocess smoke 는 `--smoke-output` 파일 fallback 을 사용한다.
- 회귀: `tests/test_ci_workflow.py`, `tests/test_config_paths.py`

## 2. 패키징

```bash
pyinstaller --clean subtitle_extractor.spec
# dist/국회의사중계자막추출기 vX.Y.Z.exe
```

- [ ] frozen `--smoke` exit 0 (`hwpx_ok` 등 JSON ok)  
- [ ] `portable.flag` 옆 `--smoke-storage-preflight` exit 0  
- [ ] (선택) `--smoke-instantiate-window`  
- [ ] (선택) DOCX: 빌드 env에 `python-docx` 포함 여부 확인  
- [ ] GitHub Actions 최신 main CI **success** 확인

## 3. 보안·프라이버시 안내 (배포 노트)

- [ ] 자막/DB/로그가 로컬 평문 저장임을 사용자 문서에 명시  
- [ ] portable 모드는 EXE 옆에 데이터가 쌓이므로 공유 PC·USB 주의  
- [ ] 로그 기본 레벨 INFO, `SUBTITLE_LOG_LEVEL=DEBUG` 로만 상세 로그  
- [ ] 로그 보존 일수: `Config.LOG_RETENTION_DAYS` (기본 14)

## 4. 코드 서명 (권장, 정책 따름)

- [ ] 배포 빌드에 `Config.UPDATE_MANIFEST_URL`, `Config.UPDATE_PUBLIC_KEY_B64` 설정
- [ ] Ed25519로 manifest canonical payload 서명; artifact URL은 HTTPS, SHA-256·byte size·만료 포함
- [ ] Authenticode 서명 (기관 인증서): `python scripts/run_release_verification.py --skip-live --sign-thumbprint $env:KACC_SIGN_CERT_THUMBPRINT`
- [ ] `scripts/sign_release.ps1`의 서명 후 `Get-AuthenticodeSignature` 결과 `Valid` 확인
- [ ] SmartScreen 평판 축적 계획  
- [ ] 서명 후 해시(SHA-256)를 릴리스 노트에 게시

## 5. 버전 동기화

- [ ] README 첫 줄 버전  
- [ ] `Config.VERSION` (README 로드)  
- [ ] CLAUDE/GEMINI/CHANGELOG 요약  

## 6. 롤백

- [ ] 업데이트 승인 취소 시 staged EXE 삭제 확인
- [ ] helper 교체 후 새 EXE `--smoke` 실패 fixture에서 기존 EXE 자동 복원 확인
- [ ] staged 삭제 PermissionError가 smoke/rollback을 건너뛰지 않는지 확인
- [ ] 두 rename 사이 중단 후 `.updates` 또는 AppData `updates`의 `recover-update-helper-*.cmd`로 복원 가능하며, target 존재 시 덮어쓰지 않는지 확인
- [ ] 낡은 백업이 남아 있어도 `Update backup already exists` 없이 덮어쓰는지 확인
- [ ] helper·재시작·`--smoke` 자식 프로세스가 정리된 환경(`_MEIPASS2`·`_PYI_*` 제거)에서 실행되는지 확인
- [ ] 업데이트 성공 시 설치된 버전이 자동 재시작되는지(`--no-relaunch` 제외) 확인
- [ ] 직전 EXE 백업은 설치 EXE와 같은 디렉터리에만 생성되는지 확인
- [ ] DB(`subtitle_history.db`) 호환(additive migration) 확인
- [ ] Windows ARM64/x64의 frozen 실행·실제 두 볼륨·한컴 COM은 source/offscreen 테스트와 구분해 실기기 검증 결과 기록

## 7. GitHub Releases 업데이트 채널

- [ ] 배포 빌드에 `KACC_UPDATE_PUBLIC_KEY_B64`를 주입하고, 해당 공개키가
  `updates/latest.json`의 서명 키와 일치하는지 확인
- [ ] `KACC_UPDATE_PRIVATE_KEY_B64`는 GitHub Actions Secret에만 보관
- [ ] EXE를 GitHub Release에 먼저 업로드한 뒤 다음 명령으로 manifest 생성

  ```bash
  python scripts/build_update_manifest.py \
    --version X.Y.Z \
    --artifact dist/korea-assembly-cc-vX.Y.Z.exe \
    --artifact-url https://github.com/twbeatles/korea-assembly-cc/releases/download/vX.Y.Z/korea-assembly-cc-vX.Y.Z.exe \
    --output updates/latest.json
  ```

- [ ] 생성된 `updates/latest.json`의 signature, SHA-256, byte size, expiry를
  확인하고 main에 반영
- [ ] frozen EXE에서 시작 시 확인(무알림), 수동 확인, 다운로드 취소, 실패 시
  릴리스 페이지 fallback을 확인

### 최종 감사 회귀 (2026-11-03)

- [ ] `tests/test_recovery_candidates.py`: 크기 초과 포인터 거절, archive 밖 tail/segment 참조 거절, 정상 후보 정렬·중복 제거·누락 경고 유지
- [ ] [감사 문서](../PROJECT_AUDIT.md)의 자동 검증 결과와 실제 한컴 COM·x64·다른 볼륨 미검증 범위를 구분해 기록. 과거 최종 감사는 Git 이력 참고

### 저장·종료 경계 감사 후속 (2026-11-05)

- [ ] `tests/test_audit_followup_20261105.py`: 실제 modal 파일 선택 중 수집·segment flush 이후 JSON/DB 내용·revision 일치
- [ ] 용량 1·500 worker 큐의 terminal overflow와 coalesced 최신 preview 보존, 중복 종료·새 run의 stale 메시지 거절
- [ ] 400ms 전에 중지한 fallback의 자막·실시간 TXT·키워드·dirty·tail·복구 포인터 보존
- [ ] 포인터 없는 수동 복구, 손상 포인터 안내, 후보 검색 취소·최종 완료 직전 취소 시 현재 세션 보존
- [ ] 후보 1,000개·전체 256MiB·탐색 경로 10,000개 상한과 진행 표시 확인. 초과 시 부분 후보를 정상 결과로 적용하지 않음
- [ ] Windows native/비native 파일 대화상자의 timer 동작 차이와 최종 저장 상태를 각각 확인
- [ ] Windows 3.10 및 macOS/Linux 3.15 compatibility job의 실제 결과 확인. 설정 추가를 통과 결과로 간주하지 않음

### 큐 포화 순서 감사 후속 (2026-11-07 / 2026-11-08)

- [ ] `tests/test_audit_followup_20261107.py`: sequence gap 뒤 preview 보존(수집 중·`finished`·`_stop()`), 오래된 coalesced snapshot 무시, PID 재사용 archive의 복구 후보 노출
- [ ] `tests/test_audit_followup_20261108.py`: 큐 포화 중 `subtitle_reset`·`reconnected`가 더 오래된 preview를 앞지르지 않음(수집 중·`finished`·overflow 경로), 확정 발언 중복 0
- [ ] 실제 중계에서 UI를 2초 이상 멈춘 뒤(대형 hydrate·모달) 재개: 화자 경계 보존, 중복 entry 0, 드롭이 있으면 중지/완료 상태 메시지에 건수 표시

오프라인 장기 검증은 사용자 저장소와 분리된 소스 복사본에서 실행합니다. 이 fixture는 임시 DB·INI·archive를 사용하며 실제 생중계 네트워크 재연결을 대신하지 않습니다.

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:KACC_SOAK_SECONDS='3600'
python -m pytest tests/test_audit_followup_20261105.py -k offline_capture_soak -q -s
Remove-Item Env:KACC_SOAK_SECONDS
```

실기기 시나리오의 입력과 통과 기준:

| 환경·입력 | 확인할 결과 |
|---|---|
| 실제 중계 2시간, 파일 선택 중 발언, 네트워크 30초 차단을 3회 | 재연결 안내와 마지막 관측/저장 시각 일치, 저장 뒤 새 변경은 dirty 유지 |
| 한컴 설치 PC, 기존 HWP에 저장, 읽기 전용·다른 프로그램의 공유 잠금 | 성공 문서는 한컴에서 열림, 실패 시 기존 파일 해시 동일·실패 안내 |
| Windows x64·ARM64의 새 frozen EXE, 별도 물리 볼륨에 staging | import/storage/window smoke exit 0, 교체 성공 또는 기존 EXE 유지 |
| 업데이트 두 rename 사이 강제 중단 후 복구 launcher | target 부재 시에만 backup 복원, target 존재 시 보존, 다음 시작 결과 안내 |
| pointer 손상·segment 변조·disk-full 후 재시작 | 수동 복구 진입 가능, 잘못된 archive 정상 로드 금지, 현재 세션 보존 |

각 항목은 실행 일시·OS/아키텍처·입력·출력 파일 해시·로그·pass/fail을 남긴 뒤 체크합니다. 인증서 서명·공개 배포·물리 장비 시험은 자동 회귀 통과와 구분합니다.
