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

위 검증기는 resource budget, Ed25519 manifest, artifact hash, smoke rollback fixture를 전체 pytest 전에 명시적으로 다시 실행한다.

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
- [ ] 직전 EXE 백업은 설치 EXE와 같은 디렉터리에만 생성되는지 확인
- [ ] DB(`subtitle_history.db`) 호환(additive migration) 확인
