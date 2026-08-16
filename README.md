# 🏛️ 국회 의사중계 자막 추출기 v16.14.9

국회 의사중계 웹사이트에서 **실시간 AI 자막**을 자동으로 추출하고 저장하는 PyQt6 기반 데스크톱 프로그램입니다.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green)
![Selenium](https://img.shields.io/badge/Automation-Selenium-orange)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

---

## 📋 목차

- [주요 기능](#-주요-기능)
- [설치 방법](#-설치-방법)
- [사용 방법](#-사용-방법)
- [단축키](#️-단축키)
- [저장 형식](#-저장-형식)
- [문제 해결](#-문제-해결)
- [빌드 (EXE)](#️-빌드-exe)
- [개발 및 검증](#-개발-및-검증)
- [변경 이력](#-변경-이력)

---

## ✨ 주요 기능

### 🎯 실시간 자막 추출
- 국회 의사중계 AI 자막을 **딜레이 없이** 즉시 캡처
- 발언자 전환을 자동 감지해 자막을 구분 저장
- 중복 자막 자동 제거 및 스마트 이어붙이기
- 연결 끊김 시 자동 재연결 — 상태바에 🟢 연결됨 / 🔴 끊김 / 🟡 재연결 중 표시

### 🏛️ 상임위원회 프리셋
- 본회의·상임위·특별위·청문회 URL을 원클릭으로 선택
- `📡 생중계 목록` — 현재 방송 중인 위원회를 목록에서 직접 선택 (30초마다 자동 갱신)
- 사용자 정의 프리셋 추가 및 관리

### 💾 다양한 저장 형식
TXT, SRT, VTT, DOCX, HWPX, HWP, RTF, JSON 세션

### 🔍 검색 및 편집
- 수집된 **전체 자막** 실시간 검색 (Ctrl+F)
- 키워드 하이라이트 / 알림 키워드 감지 시 토스트 알림
- 자막 편집, 삭제, 줄넘김 정리, 여러 세션 병합

### 🗄️ 세션 및 이력 관리
- 세션 저장/불러오기 — 언제든 중단 후 나중에 재개 가능
- SQLite DB에 자동 저장 → 과거 자막 전체 검색 및 세션 불러오기
- 저장 도중 편집·수집이 계속되어도 revision 기준으로 미저장 변경을 정확히 유지하고, DB 재시도는 operation ID로 중복 저장 방지
- 대용량 JSON/runtime/DB 세션은 공통 byte·entry budget과 점진 DB 로드(progress/cancel)를 적용
- 5분마다 자동 백업(일반 세션: `backup_*.json`, 장시간 추출: runtime manifest/tail 복구 포인터), 비정상 종료 후 재시작 시 여러 복구 후보를 비교·선택
- DB 히스토리에서 같은 세션의 저장 계보 (`[최신]`, `[이전 저장본 n/N]`) 확인

### ⚙️ 편의 기능
- **헤드리스 모드** — 브라우저 창을 숨기고 백그라운드에서 실행
- **실시간 저장** — 수집 중 즉시 파일에 기록 (`realtime_output/` 폴더)
- **자동 줄넘김 정리** — 수집 중 줄바꿈·빈 줄을 자동으로 한 줄로 정리 (기본 ON)
- 다크/라이트 테마, 글자 크기 조절
- 저장/백업/DB 파일은 실행 위치와 무관하게 앱 기준 경로에 저장
- preview sequence gap을 감지해 최신 full DOM snapshot으로 복구하고, drop/gap/salvage 품질 진단을 세션에 기록
- 배포 빌드는 도움말의 `업데이트 확인...`에서 Ed25519 서명 manifest와 EXE SHA-256을 검증한 뒤 사용자 승인 시에만 설치; smoke 실패 시 기존 EXE 자동 복원

---

## 📦 설치 방법

### 1. Python 설치

Python **3.10 이상**에서 동작합니다. CI는 **3.12**, 로컬 개발은 3.10–3.14 범위를 지원합니다.  
개발·검증·빌드 시 `requirements-dev.txt` 핀을 그대로 설치하세요.  
[Python 공식 사이트](https://www.python.org/downloads/)에서 다운로드하세요.

### 2. 의존성 설치

```bash
pip install -r requirements-dev.txt
```

최소 실행만 필요한 경우:

```bash
pip install PyQt6 selenium cryptography
```

### 3. 선택 기능 참고

| 기능 | 필요 패키지 |
|------|------------|
| HWPX 저장 | 추가 설치 없음 (기본 내장) |
| DOCX 저장 | `python-docx` (requirements-dev.txt에 포함) |
| HWP 저장 | `pywin32` + 한컴오피스 (Windows 전용) |

### 4. Chrome 브라우저

Chrome이 설치되어 있어야 합니다. Selenium 4.x가 WebDriver를 자동으로 관리하므로 별도 설치는 불필요합니다.

---

## 🚀 사용 방법

### 1단계: 프로그램 실행

```bash
python "국회의사중계 자막.py"
```

### 2단계: 위원회 선택

세 가지 방법 중 선택합니다.

**방법 A — 프리셋 사용 (권장)**
1. `📋 상임위` 버튼 클릭
2. 원하는 위원회 선택 (예: 본회의, 법제사법위원회)
3. URL이 자동으로 입력됨

**방법 B — 직접 URL 입력**
URL 입력창에 국회 의사중계 주소를 입력합니다.  
예: `https://assembly.webcast.go.kr/main/player.asp?xcode=10`

**방법 C — 생중계 목록 선택**
1. `📡 생중계 목록` 버튼 클릭
2. 현재 방송 중인 위원회 선택
3. URL이 자동으로 입력됨 (목록은 30초마다 자동 갱신)

> `종료/예정` 항목은 확인 후 URL만 입력되며 즉시 재생되지 않습니다.

### 3단계: 옵션 설정

추출 **시작 전**에만 변경할 수 있습니다.

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| 자동 스크롤 | ON | 새 자막 추가 시 자동으로 아래로 스크롤 |
| 자동 줄넘김 정리 | ON | 줄바꿈·빈 줄을 한 줄로 자동 정리 |
| 실시간 저장 | OFF | 수집 중 즉시 파일에 저장 |
| 헤드리스 모드 | OFF | 브라우저 창 숨기고 백그라운드 실행 |

### 4단계: 추출 시작

`▶ 시작` 버튼 또는 **F5** 키를 누릅니다.

상태바에서 진행 상황을 확인합니다.
- `🔍 현재 생중계 감지 중...` — 생중계 URL 자동 탐지 진행 중
- `자막 모니터링 중` — 정상 수집 중
- `⏳` 표시 자막 — 아직 확정되지 않은 진행 중 자막

### 5단계: 저장

추출 완료 후 파일명이 자동으로 제안됩니다.

| 메뉴 | 단축키 | 형식 |
|------|--------|------|
| 파일 → TXT 저장 | Ctrl+S | 타임스탬프 포함 텍스트 |
| 파일 → SRT 저장 | — | 영상 자막 표준 형식 |
| 파일 → DOCX 저장 | — | Word 문서 |
| 파일 → HWPX 저장 | — | 한글 문서 (기본 포맷) |
| 파일 → 세션 저장 | Ctrl+Shift+S | 전체 세션 (나중에 불러오기 가능) |

---

## ⌨️ 단축키

### 기본 조작

| 단축키 | 기능 |
|--------|------|
| **F5** | 추출 시작 |
| **Escape** | 검색창 닫기 / 추출 중지 |
| **Ctrl+Q** | 프로그램 종료 |

### 검색 및 편집

| 단축키 | 기능 |
|--------|------|
| **Ctrl+F** | 검색창 열기 |
| **F3** | 다음 검색 결과 |
| **Shift+F3** | 이전 검색 결과 |
| **Ctrl+E** | 자막 편집 |
| **Delete** | 자막 삭제 |
| **Ctrl+Shift+C** | 전체 자막 복사 |
| **Ctrl+C** | 선택한 텍스트 복사 |

### 저장

| 단축키 | 기능 |
|--------|------|
| **Ctrl+S** | TXT 저장 |
| **Ctrl+Shift+S** | 세션 저장 |
| **Ctrl+O** | 세션 불러오기 |
| **Ctrl+Shift+M** | 자막 병합 |

### 보기

| 단축키 | 기능 |
|--------|------|
| **Ctrl+T** | 테마 전환 (다크/라이트) |
| **Ctrl++** | 글자 크기 키우기 |
| **Ctrl+-** | 글자 크기 줄이기 |
| **F1** | 사용법 가이드 |

---

## 📄 저장 형식

| 형식 | 확장자 | 설명 | 추가 설치 |
|------|--------|------|-----------|
| TXT | .txt | 수집 시각(벽시계) 타임스탬프 텍스트 | 없음 |
| SRT | .srt | SubRip — **세션 첫 자막 기준 상대 타임코드** | 없음 |
| VTT | .vtt | WebVTT — **세션 첫 자막 기준 상대 타임코드** | 없음 |
| DOCX | .docx | Word 문서 | python-docx (소스·dev 빌드) |
| HWPX | .hwpx | 한글 문서 (기본 포맷) | 없음 |
| HWP | .hwp | 한글 문서 (COM) | pywin32 + 한컴오피스 (Windows) |
| RTF | .rtf | 서식 있는 텍스트 | 없음 |
| JSON | .json | 전체 세션 저장 (복원 가능) | 없음 |

> HWP 저장 시 한컴오피스가 없으면 자동으로 HWPX로 대체됩니다. RTF 파일도 한글에서 열 수 있습니다.  
> TXT/DOCX/HWP/HWPX 본문의 `[HH:MM:SS]` 는 수집 시각(벽시계)이며, SRT/VTT 큐 시간은 재생 동기화용 상대 시간입니다.  
> **배포 EXE**: DOCX는 빌드 환경에 `python-docx`가 포함되어야 합니다. 없으면 메뉴에서 설치 안내가 뜹니다.

---

## 🔧 문제 해결

### 자막이 표시되지 않음
1. 국회 의사중계 페이지에서 AI 자막이 활성화되어 있는지 확인
2. 현재 생중계가 진행 중인지 확인
3. `📡 생중계 목록`에서 방송을 직접 선택해보세요
4. `xcode`만 있는 URL은 시작 후 자동으로 생중계 주소를 보완합니다

### 연결이 자주 끊김
- 연결 끊김 시 자동으로 재연결을 시도합니다 (상태바에 🟡 표시)
- 지속된다면 네트워크 환경을 점검하세요

### Chrome 실행 오류
- Chrome 브라우저가 설치되어 있는지 확인하세요
- Selenium 4.x가 WebDriver를 자동 관리하므로 chromedriver를 별도로 설치할 필요가 없습니다

### 짧은 발화가 누락됨
- `네/예` 같은 1~2글자 발화는 수집됩니다
- `...`, `--`, `123`처럼 한글·영문이 없는 입력은 노이즈로 자동 차단됩니다

### HWP 저장 오류
- 한컴오피스와 `pywin32`가 모두 필요합니다
- 없으면 자동으로 HWPX로 저장되며, 저장 실패 시 RTF/DOCX/TXT 대체 선택 창이 나타납니다

---

## 🛠️ 빌드 (EXE)

```bash
pip install pyinstaller
pyinstaller subtitle_extractor.spec
# dist/국회의사중계자막추출기 v16.14.9.exe
```

**Portable 모드**: EXE 파일 옆에 `portable.flag` 파일을 만들어두면 로그·세션·DB·설정을 EXE 폴더에 저장합니다.  
**기본 실행**: `%LOCALAPPDATA%\AssemblySubtitle\Extractor` 에 저장됩니다.

---

## ✅ 개발 및 검증

```bash
pip install -r requirements-dev.txt
python scripts/install_git_hooks.py   # 푸시 전 pyright 훅 설치 (1회)
python scripts/check_before_push.py --pyright-only   # 푸시 전 수동 검사
pyright           # 정적 분석 (0 errors 기준)
pytest -q         # 회귀 테스트 전체 통과 기준 (in-process smoke 포함)
```

`git push` 시 pre-push 훅이 `pyright`를 실행하며 **errorCount > 0 이면 푸시가 거부**됩니다.  
CI(`.github/workflows/ci.yml`)도 push/PR 에서 pytest + pyright를 실행합니다.

에이전트/샌드박스 환경에서는 `*_subprocess` 회귀가 skip될 수 있습니다. 기본 `pytest -q`는 in-process smoke·pyright fallback으로 녹색을 유지합니다.

릴리스 전 전체 검증:

```bash
python scripts/run_release_verification.py
python scripts/run_release_verification.py --offline --skip-build --instantiate-window
python scripts/run_release_verification.py --with-live-smoke   # live contract smoke 명시 포함
```

릴리스 EXE에 Authenticode를 적용할 때는 인증서 개인 키를 코드에 넣지 않고 Windows 인증서 저장소를 사용합니다.

```powershell
python scripts/run_release_verification.py --skip-live --sign-thumbprint $env:KACC_SIGN_CERT_THUMBPRINT
```

업데이트 채널의 기본 manifest URL과 공개키는 배포 빌드에 내장됩니다. 개발 실행에서는 자동 설치를 하지 않으며, 업데이트 helper는 다음 시작 시 성공·rollback·실패 결과를 알려줍니다. 첫 updater 도입 이전 버전은 GitHub Releases에서 수동 설치가 필요합니다.

자세한 아키텍처·개발 가이드·파이프라인 고정 규칙은 아래 문서를 참고하세요.

| 문서 | 내용 |
|------|------|
| [CLAUDE.md](CLAUDE.md) | 아키텍처, 핵심 규칙, 개발 가이드 |
| [PROJECT_AUDIT.md](PROJECT_AUDIT.md) | 기능 감사·리스크·조치 현황 |
| [PROJECT_AUDIT_EXTENDED.md](PROJECT_AUDIT_EXTENDED.md) | 보안·동시성·성능·CI·패키징 확장 감사 |
| [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) | 릴리스·서명·프라이버시·CI 배포 체크리스트 |
| [docs/CHROME_EXTENSION_PARITY.md](docs/CHROME_EXTENSION_PARITY.md) | Chrome 확장과 수집 계약 정합 |
| [docs/HWPX_EXPORT_ANALYSIS.md](docs/HWPX_EXPORT_ANALYSIS.md) | HWPX 내보내기 설계·스키마 방침 |
| [PIPELINE_LOCK.md](PIPELINE_LOCK.md) | 자막 수집 파이프라인 고정 기준 |
| [ALGORITHM_ANALYSIS.md](ALGORITHM_ANALYSIS.md) | 알고리즘 잠재 이슈 분석 |

---

## 📝 변경 이력

### v16.14.9 (2026-08-16)
- **업데이트 운영 보강** — 릴리스 개인키·내장 공개키 일치 검증, helper 결과 영속화/다음 시작 알림, 실행 중 수집과의 설치 경합 차단, backup 보존 수 제한, manifest 게시의 main ancestry·직렬화 검증
- **문서·회귀** — 업데이트 채널 기본값과 첫 수동 전환 조건을 문서화하고 key/result/backup 회귀 테스트 보강

### v16.14.8 (2026-06-30 ~ 2026-08-10)
- **2026-08-11 기능 감사 전체 개선** — revision save, DB idempotency, 공통 resource budget/stream load, Windows 경로 정규화, URL·입력 상한, preview gap 복구·품질 metadata, 복구 후보 선택, 서명 업데이트·승인·rollback
- **2026-08-10 수집 정합·export·CI** — Chrome 확장 AI 버튼/active 검사·multi-speaker, export sanitize·SRT/VTT 상대 타임코드, 푸시 전 pyright 훅, CI pyright fail-fast → pytest
- **감사 후속 자동화/TDD 보강** — in-process smoke·pyright fallback, `_prepare_preview_raw`·salvage·reconnect handshake 테스트, capture Protocol, release verifier `pip install`/`--init-codegraph`
- **재연결 중복 append 완화** — `_reconnect_preview_suppress_until_delta` handshake
- **2026-07-22 감사 후속** — worker `finished` terminal 전달 수정, stop 중 finished/error 멱등 흡수, Observer 짧은 발화 정책 정렬, CLAUDE/GEMINI v16.14.8 동기화
- **2026-07-29 기능 감사 후속** — 추출 시작 시 dirty/세션 교체 보호, soft_resync 긴 compact 유지, orphan segment 정리
- **2026-07-29 확장 감사 후속** — 로그 INFO 기본·`safe_log_text`, runtime archive 연령 GC, 종료 중 액션 가드, hydrate 상한·토큰 전달, 검색 `상위 N건+` 표시, GitHub Actions CI, 릴리스 체크리스트
- 회귀 기준: `pytest` 424 pass / 2 skipped, `pyright` 154 files·0 errors/0 warnings, source/창 생성/offline release verification 통과

### v16.14.7 (2026-04-01 ~ 2026-06-25)
- **감사 후속 안정화 (2026-06-25)** — preview coalescing 제거, overflow 우선순위 trim, stopping 시 preview 완전 drain, worker/control 큐 분리(`AppControlMessageQueue`), DB `DatabaseOperationResult`, extraction worker non-daemon, CSS selector 사전 검증, 복구 다이얼로그 우선순위 안내
- Chrome 세션 자동 복구 — 연결 끊김을 감지해 같은 URL로 자동 재기동
- 장시간 세션 지원 — 메모리 절감을 위한 runtime archive 구조 도입
- Portable 모드 및 `%LOCALAPPDATA%` 기본 저장 경로 분리
- 시작 시 저장소 preflight 검증 (쓰기 권한, SQLite WAL 등)
- 생중계 목록 개선 — `생중계` / `종료·예정` 구분 표시, 다중 후보 자동 선택 제거
- DB 세션 계보 배지 (`[최신]`, `[이전 저장본 n/N]`) 추가
- DB degraded mode — FTS 사용 불가 시 literal 검색으로 자동 전환
- URL 정책 일원화 (`assembly.webcast.go.kr` 계열만 허용)
- 토큰 기반 테마 일원화 — 다크/라이트 전환 정확성 개선
- 종료 진단 저장 (`logs/shutdown_diagnostic_*.json`)
- 회귀 기준: `pytest -q` 279 pass / 1 skipped, `pyright` 0 errors

### v16.14.6 (2026-04-01)
- 비정상 종료 후 재시작 시 최신 백업·세션 복구 제안
- 수동 줄넘김 정리를 백그라운드 처리로 전환
- DOCX/HWPX: 엔트리 내부 개행을 줄바꿈(line break)으로 저장

### v16.14.5 (2026-03-27)
- 추출 중 URL·헤드리스·실시간 저장 옵션 잠금
- 생중계 목록 자동 갱신 (30초 간격)
- DB 히스토리·검색 결과 점진 로드 (`더 보기`)
- 세션 dirty tracking — 미저장 변경 시 종료 프롬프트 표시

### v16.14.4 (2026-03-25)
- 검색 기준을 전체 자막으로 확장 (렌더 영역 제한 없음)
- DB 검색 결과에서 세션 불러오기 및 해당 자막 위치로 즉시 이동
- 병합 중복 제거 모드 선택 — `보수적(같은 초)` / `기존(30초 버킷)`

### v16.14.3 (2026-03-23)
- Worker 메시지 큐에 `run_id` 격리 도입 (stale 메시지 자동 폐기)
- HWP 미설치 시 HWPX 자동 대체

### v16.14.2 (2026-03-18)
- 파이프라인 성능 최적화 — 1,500회 처리 기준 약 3.7배 속도 향상
- 자막 렌더링 증분 반영 (tail patch)

### v16.14.1 (2026-03-17)
- `✨ 자동 줄넘김 정리` 옵션 추가 (기본 ON)

### v16.14.0 (2026-03-16)
- MainWindow를 파사드로 축소하고 capture / pipeline / view / persistence 모듈로 분리

### v16.13.2 (2026-03-05)
- 병합 중복 제거 기준 개선 (텍스트 + 30초 시간 버킷)
- 종료 시 저장/DB 작업 완료 대기

### v16.12 (2026-02-12)
- MutationObserver + 폴링 하이브리드 수집 엔진 도입
- 발언자 전환 즉시 감지 (자막 영역 클리어 감지)
- `rfind` 기반 suffix 매칭으로 반복 문구 과잉 추출 방지

### v16.11 (2026-01-29)
- 글로벌 히스토리 + Suffix 매칭 알고리즘 도입 (DOM 루핑 면역)

### v16.6 (2026-01-22)
- 연결 상태 모니터링 (🟢/🔴/🟡)
- 자동 재연결 (지수 백오프)
- 자동 파일명 생성
- SQLite DB 세션 히스토리 및 검색
- 자막 병합 도구

---

## 📄 라이선스

MIT License © 2024-2026
