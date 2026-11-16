# PyInstaller 빌드 문제 기록

frozen EXE 빌드에서 실제로 겪은 문제, 원인, 고친 방법을 남긴다. 같은 증상이 다시 나오면 이 문서부터 본다.
릴리스 전체 절차는 [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md)에 있다.

## 1. 빌드 환경

| 용도 | Python | 위치 | UPX |
|---|---|---|---|
| 배포 EXE 빌드 | 3.15 | `.github/workflows/release.yml` (`windows-latest`) | 없음 |
| CI 테스트 (pyright → pytest) | 3.15 | `.github/workflows/ci.yml` | 해당 없음 (빌드 안 함) |
| 로컬 개발·검증 빌드 | 3.15 | 개발 PC | 설치되어 있을 수 있음 (`C:\upx-*`) |

세 환경 모두 Python 3.15를 쓴다. 2026-11-16 전까지는 배포 빌드만 3.12였다. 그래서 3.15 전용 문제(§2.1·§2.2)가 배포 EXE에서는 드러나지 않았고 로컬에서만 재현됐다. Python 버전을 올릴 때는 세 곳을 함께 바꾼다. `tests/test_release_workflow.py`가 CI와 릴리스의 버전 일치를 검사한다.

남는 차이는 PATH에 있는 다른 Python 설치와 UPX 유무다. 개발 PC에는 둘 다 있을 수 있다.

**빌드 후에는 반드시 frozen smoke를 돌린다.** 빌드가 성공해도 EXE가 실행되지 않는 경우가 있었다.

```bash
pyinstaller --clean subtitle_extractor.spec
"dist/국회의사중계자막추출기 vX.Y.Z.exe" --smoke --smoke-instantiate-window \
  --smoke-storage-dir .pytest_tmp/frozen-smoke --smoke-output .pytest_tmp/frozen-smoke.json
# exit 0 이고 JSON 이 "ok": true 여야 한다 (PowerShell 에서는 §2.4 처럼 Start-Process -Wait)
```

`python scripts/run_release_verification.py --offline --skip-deps --instantiate-window`는 빌드와 frozen smoke를 한 번에 실행한다. `--skip-deps`를 빼면 `requirements-dev.txt` 핀으로 의존성을 다시 설치한다.

## 2. 증상별 기록

### 2.1 `DLL load failed while importing _rust` — python3t.dll 미수집 (2026-10-14)

- **증상:** frozen EXE가 시작하자마자 종료된다. smoke JSON은 `"error_type": "dependency_import"`다.
- **원인:** Python 3.15용 cryptography 휠(`cp315-abi3t`)의 `_rust.pyd`는 free-threaded 안정 ABI DLL `python3t.dll`을 import한다. PyInstaller는 이 DLL을 자동으로 모으지 않는다.
- **조치:** spec이 `python3t.dll`을 `a.binaries`에 추가한다(커밋 `e9bd309`, §2.2에서 보강).

### 2.2 `DLL 초기화 루틴을 실행할 수 없습니다` / `지정된 프로시저를 찾을 수 없습니다` — 다른 버전의 python3t.dll 번들 (2026-11-16)

- **증상:** 2.1 조치 뒤에도 로컬 빌드 EXE의 smoke가 같은 `_rust` import 오류로 실패했다. 메시지는 "DLL 초기화 루틴을 실행할 수 없습니다"였고, UPX를 제외한 뒤에는 "지정된 프로시저를 찾을 수 없습니다"였다. 변경 전 커밋(v16.14.16)을 같은 PC에서 빌드해도 똑같이 실패했다. 코드 변경과는 무관했다.
- **원인:** PyInstaller 의존성 분석이 `_rust.pyd`의 `python3t.dll`을 **PATH에서** 찾았다. 그 결과 개발 PC에 함께 설치된 `C:\Python314\python3t.dll`(3.14 free-threaded용, `python314t.dll`로 forward)과 `python314t.dll`을 수집했다. 빌드 로그에 두 파일이 보인다. 2.1의 spec 코드는 "같은 이름이 이미 있으면 추가하지 않는다"였으므로 잘못된 사본이 그대로 남았다. 3.15 런타임에는 그 DLL이 forward하는 심볼이 없다.
- **조치 (`subtitle_extractor.spec`):**
  - `python3t.dll` 항목은 무조건 빌드 인터프리터의 사본으로 **교체**한다. 배포판마다 위치가 달라 두 곳을 차례로 찾는다.
    - python.org 설치본(actions/setup-python 포함): `<prefix>\abi3t-compat\`
    - python-build-standalone(uv 등): `<prefix>\`
  - PATH에서 함께 끌려온 free-threaded 런타임(`python3XXt.dll`, 정규식 `python3\d+t\.dll`)은 번들에서 뺀다. 이 앱은 GIL 인터프리터로 빌드한다.
  - 빌드 인터프리터의 사본이 없는데 PATH에서 다른 사본만 수집되면, 깨진 EXE를 만들지 않고 `SystemExit`로 빌드를 실패시킨다.
- **확인 방법:**

  ```bash
  pyinstaller --clean subtitle_extractor.spec > build.log 2>&1
  grep -n "python3t\|python3[0-9]*t\.dll" build.log
  # python3t.dll 출처가 빌드 인터프리터 prefix 여야 하고 python314t.dll 같은 줄이 없어야 한다
  ```

### 2.3 UPX 압축 (예방 조치, 2026-11-16)

- 로컬 PC에 UPX가 있으면 spec의 `upx=True` 때문에 `python315.dll`, `_rust.pyd`(Rust 확장, TLS 콜백 보유), `python3t.dll`까지 압축하려 한다. 빌드 로그에 `Executing: upx ...`가 찍힌다.
- 2.2의 실제 원인은 잘못된 DLL이었고, UPX가 단독으로 실패를 일으켰는지는 입증하지 못했다. 다만 이런 DLL은 압축 이득이 작고 로더 문제 위험이 있다. 그래서 `upx_exclude`로 뺀다: `_rust.pyd`, `python3XX.dll`, `python3.dll`, `python3t.dll`, `vcruntime140*.dll`.
- 배포 빌드 러너에는 UPX가 없으므로 배포 EXE에는 영향이 없다.

### 2.4 릴리스 워크플로의 frozen smoke가 실패를 잡지 못함 (2026-11-16)

- **증상:** `release.yml`은 빌드 직후 `& $artifact --smoke`와 `$LASTEXITCODE`로 EXE를 검사했다. 실패하는 EXE(종료 코드 1)로 같은 명령을 실행하면 8ms 만에 돌아오고 `$LASTEXITCODE=0`이었다.
- **원인:** 이 앱 EXE는 `console=False`(GUI 서브시스템)다. PowerShell은 GUI 서브시스템 프로그램을 `&`로 실행하면 종료를 기다리지 않고 `$LASTEXITCODE`도 갱신하지 않는다. 깨진 배포 EXE도 릴리스를 통과할 수 있었다.
- **조치:** `Start-Process -FilePath $artifact -ArgumentList $smokeArgs -Wait -PassThru -NoNewWindow`로 종료 코드를 받는다. 이어서 `--smoke-output` JSON의 `ok`도 확인하고, `--smoke-instantiate-window`로 `MainWindow()` 생성까지 검사한다.
  - `-ArgumentList`에 배열을 넘기면 공백이 있는 경로를 따옴표로 감싸지 않는다. 그래서 따옴표를 직접 넣은 인자 문자열 하나를 넘긴다.
- **확인:** Windows PowerShell 5.1에서 공백이 들어간 경로로 실행했다. 정상 EXE는 `exit=0 ok=True`, 깨진 EXE는 `exit=1 ok=False`였다.
- **주의:** 로컬 PowerShell 스크립트에서 이 EXE의 결과를 판정할 때도 `&` 대신 `Start-Process -Wait -PassThru`를 쓴다. Python의 `subprocess.run`은 종료를 기다리므로 `run_release_verification.py`에는 문제가 없다.

## 3. 다시 깨지지 않게 하는 장치

| 장치 | 내용 |
|---|---|
| `tests/test_build_spec_contract.py` | spec이 `python3t.dll`을 빌드 인터프리터 사본으로 교체하는지, 다른 버전 free-threaded 런타임을 제거하는지, 사본이 없으면 빌드를 실패시키는지, UPX 제외 목록을 유지하는지 검사한다 |
| `tests/test_release_workflow.py` | `release.yml`과 `ci.yml`의 Python 버전이 같은지, frozen smoke가 `& $artifact` 대신 `Start-Process -Wait` 종료 코드와 JSON `ok`로 판정하는지 검사한다 |
| `scripts/run_release_verification.py` | 빌드 뒤 frozen `--smoke`(선택 `--smoke-instantiate-window`)와 portable storage preflight를 실행한다 |
| `release.yml` | 배포 EXE를 만든 직후 `--smoke --smoke-instantiate-window`를 실행한다. 종료 코드나 JSON `ok`가 실패면 릴리스를 중단한다 |

## 4. 새 문제를 만났을 때

1. smoke JSON의 `error_type`, `error`를 본다. `dependency_import`면 번들된 네이티브 의존성 문제다.
2. 빌드 로그에서 문제 모듈의 DLL이 **어느 경로에서** 수집됐는지 확인한다. 다른 Python 설치(`C:\Python3xx`, uv 경로) 쪽이면 PATH 오염이다.
3. 변경 전 커밋을 별도 worktree에서 같은 환경으로 빌드해 본다. 그러면 코드 변경 때문인지 환경 때문인지 먼저 가를 수 있다.

   ```bash
   git worktree add ../kacc-head HEAD
   cd ../kacc-head && pyinstaller --clean --distpath ../kacc-head-dist subtitle_extractor.spec
   ```

4. 원인과 조치를 이 문서 §2에 날짜와 함께 추가하고, 가능하면 §3에 회귀 장치를 더한다.
