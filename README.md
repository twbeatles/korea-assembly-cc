# 🏛️ 국회 의사중계 자막 추출기 v16.14.0

국회 의사중계 웹사이트에서 **실시간 AI 자막**을 자동으로 추출하고 저장하는 PyQt6 기반 데스크톱 프로그램입니다.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green)
![Selenium](https://img.shields.io/badge/Automation-Selenium-orange)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

---

## 📋 목차
- [크롬 파이프라인 정리 + SOLID 분할 리팩토링 (v16.14.0)](#-v16140-크롬-파이프라인-정리--solid-분할-리팩토링-2026-03-16)
- [운영 정합성 업데이트 (v16.13.2)](#-v16132-운영-정합성-업데이트-2026-03-05)
- [새 기능 (v16.13.1)](#-v16131-새-기능)
- [주요 기능](#-주요-기능)
- [설치 방법](#-설치-방법)
- [사용 방법](#-사용-방법)
- [단축키](#️-단축키)
- [저장 형식](#-저장-형식)
- [상세 기능 설명](#-상세-기능-설명)
- [문제 해결](#-문제-해결)
- [개발 검증](#-개발-검증)
- [빌드 방법](#️-빌드-방법)
- [변경 이력](#-변경-이력)
- [파이프라인 고정 문서](#-파이프라인-고정-문서)

---

## ✨ v16.14.0 크롬 파이프라인 정리 + SOLID 분할 리팩토링 (2026-03-16)

### 🧩 크롬 확장 자막 알고리즘 구조 고정
- `core/live_capture.py`와 `core/subtitle_pipeline.py`를 기준 코어로 유지하고, `framePath::nodeKey` 기반 row reconciliation, grace reset, prepared snapshot 저장 경로를 운영 기본값으로 고정했습니다.
- 같은 화면 row 수정은 기존 엔트리를 제자리 업데이트하고, preview-only 자막도 TXT/SRT/VTT/세션 저장 직전에 공통 snapshot 경로로 materialize합니다.

### 🏗️ MainWindow 책임 분할
- `ui/main_window.py`는 파사드 역할만 담당하고, 실제 구현은 `ui/main_window_ui.py`, `ui/main_window_capture.py`, `ui/main_window_pipeline.py`, `ui/main_window_view.py`, `ui/main_window_persistence.py`, `ui/main_window_database.py`로 분리했습니다.
- `ui/main_window_types.py`의 `MainWindowHost` 계약으로 분할된 mixin의 공통 `self` 타입을 고정해 Pylance/Pyright 진단 기준을 안정화했습니다.
- 직접 호출되던 `MainWindow` 메서드 표면은 유지해 기존 테스트와 엔트리포인트 import 경로를 깨지 않도록 정리했습니다.

### 🧰 코어/호환 계층 정리
- `core/file_io.py`, `core/text_utils.py`, `core/reflow.py`, `core/database_manager.py`를 추가하고, `core/utils.py`, `database.py`는 호환용 shim으로 유지했습니다.
- `subtitle_extractor.spec`는 새 모듈 구조를 hidden import에 반영하고, 빌드 버전 기본값을 `v16.14.0`으로 동기화했습니다.
- `tests/test_pyright_regression.py`와 확장된 `tests/test_encoding_hygiene.py`로 `pyright 0 errors`와 핵심 한글 문자열 UTF-8 round-trip을 회귀 검증합니다.

## ✨ v16.13.1 새 기능 (Hot!)

### 🧩 첫 문장 이후 정체 완화 (수집 경로 보강)
- `.smi_word:last-child` 단일 노드 의존을 줄이고, `.smi_word` 목록 전체를 수집해 최근 창(window) 텍스트를 조합하도록 보강했습니다.
- Observer 타겟 선택 시 `#viewSubtit .incont`, `#viewSubtit` 같은 컨테이너를 우선 시도해 사이트 DOM 변동에서 수집 정체를 줄였습니다.
- 긴 컨테이너 텍스트는 최근 라인 중심으로 축약해 버퍼 과대 입력으로 인한 게이트 정체를 완화했습니다.

---

## ✨ v16.13.2 운영 정합성 업데이트 (2026-03-05)

### 🔒 종료 lifecycle 통합
- 파일 저장/세션 저장·불러오기/DB 비동기 작업을 공통 백그라운드 레지스트리로 추적합니다.
- `closeEvent`에서 `신규 작업 차단 → inflight 대기 → 자원 정리` 순서로 종료하여 종료 시점 데이터 유실 위험을 줄였습니다.

### 🧠 스트리밍 히스토리 메모리 상한
- `_confirmed_compact` 누적 버퍼에 상한(`Config.CONFIRMED_COMPACT_MAX_LEN=50000`)을 적용했습니다.
- suffix 기반 코어 의미론은 유지하면서 tail만 보존해 장시간 세션 메모리 증가를 억제합니다.

### 📎 병합 정책 정합성
- 실시간 병합 기준을 Config 상수로 일원화했습니다 (`ENTRY_MERGE_MAX_GAP=5`, `ENTRY_MERGE_MAX_CHARS=300`).
- 세션 병합 중복 제거를 텍스트-only에서 `정규화 텍스트 + 시간 버킷(30초)` 기준으로 개선했습니다.

### 🗄️ DB 경로 정책 통일
- `DatabaseManager()` 기본 경로를 앱 기준 `Config.DATABASE_PATH`로 통일해 실행 위치(CWD) 의존성을 제거했습니다.

---

## ✨ v16.13 운영 안정화

### 🧭 생중계 URL 자동 보완 경로 실연결
- `_detect_live_broadcast`가 워커 시작 직후와 재연결 경로 모두에서 실제 호출됩니다.
- `xcode-only` URL에서도 `xcgcd`를 자동 보완해 동일한 수집 경로로 재진입합니다.

### ⏱️ keepalive 기반 end_time 보정 활성화
- 동일 자막 유지 구간에서 `keepalive` 메시지를 주기 발행해 마지막 엔트리 `end_time`을 갱신합니다.
- 기존 미사용 finalize 타이머 경로를 정리해 스트리밍 확정 정책을 단일화했습니다.

### 💾 저장/종료 안정성 강화
- TXT/SRT/VTT/RTF 저장에 원자적 저장(임시파일 후 교체)을 적용했습니다.
- 백그라운드 저장 스레드를 추적하고 종료 시 제한시간(`5초`) 대기해 저장 중단 손상 위험을 낮췄습니다.

### 🧪 운영 품질 보강
- 로그 저장 경로를 항상 앱 기준 `logs`로 고정했습니다.
- `LiveBroadcastDialog` 종료 경로를 단일화해 QThread 종료 안정성을 강화했습니다.
- 짧은 발화는 허용하고 숫자/기호 노이즈는 차단하는 필터를 도입했습니다.

---

## ✨ v16.12 핵심 개선

### 🎤 발언자 전환 즉시 감지 (Zero-Delay)
- **자막 영역 클리어 감지** - 발언자가 바뀔 때 자막 영역이 비워지는 순간을 **실시간으로 감지**합니다.
- **즉시 완전 리셋** - 기존에는 2초간 자막이 멈추던 현상을 해결하여, 새 발언자의 첫 마디를 놓치지 않고 **즉시 수집**합니다.
- **버퍼 확정** - 전환 직전의 마지막 텍스트가 유실되지 않도록 강제로 저장합니다.

### 🧬 MutationObserver 하이브리드 엔진
- **이벤트 기반 캡처** - JavaScript `MutationObserver`를 사용하여 자막 변경을 실시간 이벤트로 감지합니다.
- **폴링 Fallback** - 기존의 0.2초 폴링 방식도 함께 작동하여 어떤 상황에서도 자막을 놓치지 않는 **이중 안전장치**를 구축했습니다.
- **자동 재주입** - 페이지 새로고침이나 네트워크 재연결 시에도 Observer가 자동으로 재설치됩니다.

### 🎯 코어 정확성 및 안정성 강화
- **스마트 Suffix 매칭 (`rfind`)** - "위원장... 위원장..." 처럼 반복되는 문구 처리 시 과잉 추출 문제를 원천 차단했습니다.
- **소프트 리셋 (Soft Resync)** - 네트워크 지연 등으로 동기화가 깨졌을 때, 전체 데이터를 날리지 않고 최근 10초간의 자막 맥락만 유지하며 **자연스럽게 복구**합니다.
- **대량 중복 방지** - 리셋 직후 발생할 수 있는 대량 중복 텍스트 유입을 알고리즘 레벨에서 차단했습니다.

---

## 🛠️ v16.12 안정화 패치 (2026-02-25)

- **생중계 URL 자동 보완 연결**: 시작/재연결 시 URL에 `xcgcd`가 없으면 `xcode` 기준 자동 감지를 실제 워커 흐름에 연결했습니다.
- **짧은 발화 수집 보강**: `네/예` 같은 1~2글자 발화를 수집하면서, 기호-only/숫자-only 노이즈는 차단하는 텍스트 게이트를 적용했습니다.
- **세션 내결함성 강화**: 세션 로드/병합 시 손상 항목이 섞여도 유효 항목만 복원하도록 개선했습니다.
- **저장 비차단화 확대**: RTF 저장, 통계 내보내기를 백그라운드 처리로 전환해 UI 프리징을 줄였습니다.
- **로그 경로 일관화**: 실행 위치와 무관하게 앱 기준 경로(`Config.LOG_DIR`)에 로그가 저장되도록 통일했습니다.

---

## ✨ v16.11 주요 개선 사항

### 🧠 자막 수집 알고리즘 완벽 재설계
- **글로벌 히스토리 Suffix 매칭** - 확정된 모든 텍스트를 누적하고, 새 raw에서 히스토리의 마지막 부분(suffix) 이후만 추출
- **DOM 루핑 면역** - 웹사이트 특유의 텍스트 반복/루핑 현상 완벽 대응
- **자막 반복 완전 해결** - 기존 앵커 기반, 버퍼 비교, 문장 해시 방식 모두 실패 → 새 알고리즘으로 해결

### 🛡️ 파이프라인 안정화 고정
- **입력 게이트 레이어** - `preview`는 `_prepare_preview_raw`를 통과한 뒤 코어 알고리즘으로 전달
- **다단계 fallback** - suffix desync/ambiguous 상황에서 증분 우선 추출
- **안전한 재동기화** - 반복 실패 시에만 제한적으로 리셋 수행

---

## 📌 파이프라인 고정 문서

자막 수집 구조 고정 기준은 아래 문서를 참고하세요.

- `PIPELINE_LOCK.md`

---

## ✨ 주요 기능

### 🎯 실시간 자막 추출
- 국회 의사중계 웹사이트의 AI 자막을 실시간으로 캡처
- **스트리밍 엔진**: 딜레이 없이 즉시 자막 표시 및 저장
- 중복 자막 자동 제거 및 스마트 이어붙이기

### 💾 다양한 저장 형식
TXT, SRT, VTT, DOCX, HWP, RTF, JSON 세션 저장

### 🔍 검색 및 하이라이트
- **실시간 검색** (Ctrl+F)
- **키워드 하이라이트** - 특정 단어 강조
- **알림 키워드** - 감지 시 토스트 알림

### 🏛️ 상임위원회 프리셋
- 상임위원회/특별위원회 URL 빠른 선택
- 사용자 정의 프리셋 추가/관리
- **생중계 목록 선택** - 현재 방송을 목록에서 직접 선택 (📡 생중계 목록)

### ⚙️ 편의 기능
- 헤드리스 모드 (브라우저 창 숨김)
- 실시간 저장, 세션 저장/불러오기
- 자동 백업 (5분마다)
- 다크/라이트 테마
- 저장/백업/DB/히스토리 파일은 **실행 위치와 무관하게 앱 기준 경로**에 저장

---

## 📦 설치 방법

### 1. Python 설치
Python 3.10 이상이 필요합니다.
- [Python 공식 사이트](https://www.python.org/downloads/)에서 다운로드

### 2. 개발/검증 의존성 설치
```bash
pip install -r requirements-dev.txt
```

### 3. 선택 기능 참고
- `requirements-dev.txt`에는 DOCX(`python-docx`)와 HWP(`pywin32`) 저장 기능용 패키지가 함께 정리되어 있습니다.
- 최소 실행만 필요하면 `pip install PyQt6 selenium`만 설치해도 됩니다.
- HWP 저장은 Windows 환경과 한컴오피스가 추가로 필요합니다.

### 4. Chrome 브라우저
- Chrome 브라우저가 설치되어 있어야 합니다
- Selenium 4.x가 자동으로 WebDriver를 관리합니다

---

## 🚀 사용 방법

### 기본 사용법

#### 1단계: 프로그램 실행
```bash
python "국회의사중계 자막.py"
```

#### 2단계: 위원회 선택
세 가지 방법 중 선택:

**방법 A: 프리셋 사용 (권장)**
1. `📋 상임위` 버튼 클릭
2. 원하는 위원회 선택 (예: 본회의, 법제사법위원회)
3. URL이 자동으로 입력됨

**방법 B: 직접 URL 입력**
1. URL 입력창에 국회 의사중계 URL 입력
2. 예: `https://assembly.webcast.go.kr/main/player.asp?xcode=10`

**방법 C: 생중계 목록 선택**
1. `📡 생중계 목록` 버튼 클릭
2. 목록에서 현재 방송 선택
3. URL이 자동으로 입력됨

#### 3단계: 옵션 설정
- ✅ **자동 스크롤**: 새 자막이 추가될 때 자동으로 아래로 스크롤 (사용자 스크롤 시 일시 중지)
- ✅ **실시간 저장**: 자막을 파일에 실시간으로 저장 (앱 기준 `realtime_output` 폴더)
- ✅ **헤드리스 모드**: 브라우저 창을 숨기고 백그라운드에서 실행

#### 4단계: 추출 시작
- `▶ 시작` 버튼 클릭 또는 **F5** 키
- 상태바에서 진행 상황 확인:
  - `🔍 현재 생중계 감지 중...` - xcgcd 자동 탐지 진행
  - `✅ 생중계 감지 성공!` - 오늘 생중계 발견
  - `자막 모니터링 중` - 정상 동작 중
- 연결 상태 표시: 🟢 연결됨, 🔴 끊김, 🟡 재연결 중

#### 5단계: 자막 확인
- 왼쪽 패널에 자막이 실시간으로 표시됨
- 오른쪽 통계 패널에서 글자수, 단어수, 실행 시간 확인
- `⏳` 표시는 아직 확정되지 않은 진행 중 자막

#### 6단계: 저장
추출 완료 후 다양한 형식으로 저장 (자동 파일명 제안됨):
- **파일 → TXT 저장** (Ctrl+S) - 일반 텍스트
- **파일 → SRT 저장** - 자막 파일 형식
- **파일 → DOCX 저장** - Word 문서
- **파일 → 세션 저장** (Ctrl+Shift+S) - 나중에 다시 불러오기 가능 + DB 저장

---

## ⌨️ 단축키

### 기본 조작
| 단축키 | 기능 |
|--------|------|
| **F5** | 추출 시작 |
| **Escape** | 추출 중지 |
| **Ctrl+Q** | 프로그램 종료 |

### 검색 및 편집
| 단축키 | 기능 |
|--------|------|
| **Ctrl+F** | 검색창 열기 |
| **F3** | 다음 검색 결과 |
| **Shift+F3** | 이전 검색 결과 |
| **Ctrl+E** | 자막 편집 |
| **Delete** | 자막 삭제 |
| **Ctrl+C** | 전체 자막 복사 |

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

| 형식 | 확장자 | 설명 | 필요 라이브러리 |
|------|--------|------|-----------------| 
| **TXT** | .txt | 타임스탬프 포함 텍스트 | 없음 |
| **SRT** | .srt | SubRip 자막 파일 | 없음 |
| **VTT** | .vtt | WebVTT 자막 파일 | 없음 |
| **DOCX** | .docx | Word 문서 | python-docx |
| **HWP** | .hwp | 한글 문서 | pywin32 + 한컴오피스 |
| **RTF** | .rtf | 서식 있는 텍스트 (HWP 호환) | 없음 |
| **JSON** | .json | 세션 저장 (복원 가능) | 없음 |
| **SQLite** | .db | 데이터베이스 히스토리 | 없음 (내장) |

---

## 📚 상세 기능 설명

### 자막 파이프라인 고정 구조 (중요)
현재 자막 수집 파이프라인은 아래 구조로 **고정**되어 있습니다.

1. **Worker (하이브리드)**:
   - 선택자 후보를 우선순위로 구성: `#viewSubtit .smi_word:last-child` → `#viewSubtit .smi_word` → 컨테이너 계열
   - 기본 문서 + 중첩 iframe/frame 경로를 순회해 자막 요소 탐색
   - 시작/재연결 시 `_detect_live_broadcast`로 `xcgcd` 보완 URL을 우선 확정
   - `MutationObserver` 주입 우선, 실패 시 JS 폴링 브리지(약 180ms) 활성화
   - 메인 루프(0.2초)에서 Observer 버퍼 우선 수집, 없으면 폴링 fallback
   - URL에 `xcgcd`가 없으면 시작 시 1회 자동 감지해 보완 URL로 재접속
   - 동일 raw 유지 구간은 `keepalive`를 주기 발행해 `end_time` 연장
   - **자막 영역 클리어 감지** 시 `subtitle_reset` 신호 전송
2. **UI Queue**:
   - `subtitle_reset` 수신 시 **즉시 완전 리셋** 및 이전 버퍼 확정
   - `preview` 메시지를 `_prepare_preview_raw`로 정규화/게이팅
   - `keepalive` 메시지를 수신해 마지막 자막 엔트리 종료 시각 갱신
3. **Core Algorithm**:
   - 통과된 입력만 `_process_raw_text`(글로벌 히스토리 + Suffix)로 전달
   - `rfind`를 사용하여 반복 문구 과잉 추출 방지
4. **후단 정제**:
   - `get_word_diff`로 미세 중복 제거
   - recent compact tail 체크로 대량 반복 블록 재누적 차단
   - 한글/영문 포함 짧은 발화(1~2글자) 허용 + 기호/숫자-only 노이즈 차단
   - `_join_stream_text`로 문장부호 기준 공백 결합(웹 표시 형태 최대 보존)
5. **종료 처리**:
   - `_drain_pending_previews`에서 남은 큐 소진
   - 마지막 항목 보정 및 저장
   - 백그라운드 작업(파일/세션/DB) 종료 대기 후 종료(`SAVE_THREAD_SHUTDOWN_TIMEOUT`)

운영 원칙:
- 코어 알고리즘(`_process_raw_text`, `_extract_new_part`)은 직접 수정하지 않음
- 반복/누락 이슈는 우선 게이트 임계값과 fallback 경로에서 조정
- 로그 키워드: `subtitle_reset 감지`, `preview suffix desync reset`, `MutationObserver 주입 성공`, `MutationObserver 폴링 브리지 활성화`

---

## 🔧 문제 해결

### Chrome 시작 오류
- Chrome 브라우저가 최신 버전인지 확인
- 프로그램이 자동으로 최대 3회 재시도합니다
- Selenium 4.x가 WebDriver를 자동 관리합니다

### 자막이 표시되지 않음
1. 국회 의사중계 페이지에서 자막이 활성화되어 있는지 확인
2. 다른 CSS 선택자 시도: `#viewSubtit .smi_word:last-child`, `#viewSubtit .smi_word`, `#viewSubtit .incont`
3. 생중계가 진행 중인지 확인
4. `xcode-only` URL도 자동 보완되지만, 실패 시 `📡 생중계 목록`에서 직접 선택
5. `xcode`만 입력했다면 시작 후 자동 보완된 URL로 바뀌는지 확인

### 짧은 발화가 누락되는 것처럼 보임
- 현재 버전은 `네/예/ok` 같은 짧은 발화를 수집합니다.
- `...`, `--`, `123`처럼 **문자(한글/영문) 없는 입력**은 노이즈로 차단됩니다.

### 연결이 자주 끊김
- v16.6부터 자동 재연결이 지원됩니다
- 상태바에서 연결 상태(🟢/🔴/🟡) 확인
- 네트워크 환경 점검 필요

### HWP 저장 오류
- **한글 오피스**가 설치되어 있어야 합니다
- 저장 실패 시 RTF/DOCX/TXT 대체 형식을 선택할 수 있습니다
- RTF 파일은 한글에서 열 수 있습니다

---

## ✅ 개발 검증

코드 변경 후 현재 저장소에서 맞춰야 하는 최소 검증 기준은 아래와 같습니다.

```bash
pip install -r requirements-dev.txt
pyright
pytest -q
python -c "import ui.main_window as m; print(m.MainWindow.__name__)"
```

- 정적 분석 기준은 루트 `pyrightconfig.json` 기반 `pyright 0 errors`입니다.
- 테스트 기준은 루트 `tests/` 전체 통과입니다.
- `tests/test_pyright_regression.py`는 워크스페이스 전체 `pyright --outputjson` 결과가 `0 errors`인지 회귀 검증합니다.
- 소스 코드, 문서(`.md`), 빌드 스펙(`subtitle_extractor.spec`)은 **UTF-8 without BOM**을 유지합니다.
- 사용자 내보내기 텍스트 중 일부 경로(TXT 실시간 저장/일반 TXT 저장)는 Windows 메모장 호환을 위해 `utf-8-sig`를 사용합니다.
- VS Code/Pylance는 루트 `pyrightconfig.json`과 `.vscode/settings.json`을 기준으로 같은 진단 기준을 사용합니다.
- Windows PowerShell 5.x 기본 출력 인코딩에서는 UTF-8 without BOM 파일이 콘솔에 깨져 보일 수 있습니다. 저장소 기준 파일 자체는 UTF-8입니다.

### 저장소 기준 파일
- `pyrightconfig.json`: Pylance/Pyright의 저장소 공통 타입 체크 기준(`standard`, Python 3.10)
- `.vscode/settings.json`: 워크스페이스 단위 Pylance/UTF-8 설정
- `.editorconfig`, `.gitattributes`: UTF-8 without BOM + CRLF 기준 유지
- `requirements-dev.txt`: 개발/검증 및 optional export 의존성 기준선
- `ui/main_window_types.py`: 분할된 `MainWindow` mixin의 공통 `self` 타입 계약(`MainWindowHost`)
- `tests/test_encoding_hygiene.py`: repo tracked 텍스트 파일의 UTF-8/BOM/U+FFFD 위생 및 핵심 한글 문자열 round-trip 검증
- `tests/test_pyright_regression.py`: 워크스페이스 전체 `pyright --outputjson` 결과가 `0 errors`인지 회귀 검증

---

## 🛠️ 빌드 방법

### PyInstaller로 EXE 빌드
```bash
# PyInstaller 설치
pip install pyinstaller

# 빌드 실행
pyinstaller subtitle_extractor.spec

# 결과물
dist/국회의사중계자막추출기 v16.14.0.exe
```

- `subtitle_extractor.spec`는 frozen 환경에서도 `Config.VERSION`이 README 첫 줄의 버전을 읽을 수 있도록 `README.md`를 함께 포함합니다.
- EXE 이름도 `subtitle_extractor.spec`에서 README 첫 줄을 읽어 동기화하므로, 릴리스 버전 변경 시 README 상단 버전과 함께 맞춰집니다.
- `python-docx`와 분할된 `ui.main_window_*` 모듈(`ui.main_window_types` 포함)은 런타임 동적 import 경로를 고려해 `.spec`의 hidden import 목록에도 함께 반영합니다.

---

## 📝 변경 이력

### v16.14.0 (2026-03-16)
- 크롬 확장 자막 파이프라인을 기준 구조로 고정하고 `core/live_capture.py` + `core/subtitle_pipeline.py` 중심으로 운영 경로를 정리
- `ui/main_window.py`를 capture / pipeline / view / persistence / database / ui mixin 모듈로 분할
- `core/file_io.py`, `core/text_utils.py`, `core/reflow.py`, `core/database_manager.py` 추가 및 `core/utils.py`, `database.py` 호환 shim 전환
- `subtitle_extractor.spec`, `README.md`, `PIPELINE_LOCK.md`, `ALGORITHM_ANALYSIS.md`, `CLAUDE.md`, `GEMINI.md`를 새 구조와 `v16.14.0` 기준으로 동기화
- 버전 동기화/호환 import 검증 테스트(`tests/test_version_sync.py`, `tests/test_compat_imports.py`) 추가
- `ui/main_window_types.py`, `tests/test_pyright_regression.py`, 확장된 `tests/test_encoding_hygiene.py`로 Pylance/UTF-8 회귀 기준을 보강

### v16.13.2 (2026-03-05)
- 🔒 **종료 lifecycle 통합**: 파일 저장/세션 저장·불러오기/DB task를 공통 레지스트리로 추적하고 종료 시 drain 대기 적용
- 🧠 **메모리 상한 적용**: `_confirmed_compact` 상한(`50000`) 도입으로 장시간 세션 메모리 증가 억제
- 📎 **병합 정책 일원화**: 실시간 병합 기준을 Config로 통합(`5초/300자`), 세션 dedupe를 시간창(30초) 기반으로 개선
- 🗄️ **DB 경로 정합성**: `DatabaseManager()` 기본 경로를 `Config.DATABASE_PATH`로 통일
- ✅ **회귀 테스트 확장**: background lifecycle, 병합 정책, compact 상한, DB 기본 경로 검증 추가

### v16.13.1 (2026-02-27)
- 🧩 **수집 정체 완화**: `.smi_word` 전체 목록 기반 창(window) 수집으로 첫 문장 이후 멈춤 현상 완화
- 🎯 **Observer 타겟 우선순위 조정**: 컨테이너(`.incont`, `#viewSubtit`) 우선 주입으로 DOM 구조 변화 대응 강화
- 🧪 **회귀 테스트 추가**: `.smi_word` 창 수집 동작 검증 케이스 보강

### v16.13 (2026-02-27)
- 🧭 **xcgcd 자동 보완 실연결**: 워커 시작/재연결 경로에서 `_detect_live_broadcast`를 실제 적용
- ⏱️ **keepalive 재활성화**: 동일 자막 유지 시 `end_time` 주기 갱신으로 SRT/VTT 타이밍 정확도 개선
- 💾 **원자적 파일 저장**: TXT/SRT/VTT/RTF에 임시파일 교체 방식 적용
- 🔒 **종료 안정성**: 저장 스레드 추적 + 종료 대기(기본 5초) 추가
- 🧩 **다이얼로그 종료 보강**: `LiveBroadcastDialog` 스레드 종료 경로 단일화
- 📝 **짧은 발화 정책 개선**: 의미 있는 1~2자 발화 허용, 숫자/기호 노이즈 차단
- 📁 **로그 경로 통일**: `Config.LOG_DIR` 기반 앱 경로 고정

### v16.12.1 (2026-02-25)
- 🔗 **생중계 자동 감지 연결**: `xcgcd` 미포함 URL 시작 시 `_detect_live_broadcast`를 실제 워커에 연결
- 🗣️ **짧은 발화 수집 보강**: 1~2글자 발화 허용 + 노이즈 필터(`기호-only/숫자-only`) 적용
- 🧱 **세션 내결함성 강화**: 세션 로드/DB 로드/병합 시 손상 항목만 건너뛰고 계속 진행
- 🧵 **UI 비차단화 확장**: RTF 저장/통계 내보내기를 백그라운드 처리로 전환
- 📁 **로그 경로 정합성 수정**: `Config.LOG_DIR` 기반으로 로그 저장 위치 통일
- ✅ **테스트 보강**: 생중계 자동 감지 연결, 짧은 발화 게이트, 세션 손상 복원, 로그 경로 검증 추가

### v16.12 (2026-02-12)
- 🎤 **발언자 전환 즉시 감지**: 자막 영역 클리어 시 즉시 리셋으로 2초 딜레이 제거
- 🧬 **하이브리드 엔진**: MutationObserver + 폴링 구조로 수집 신뢰성 극대화
- 🎯 **정확성 향상**: `rfind` 도입으로 Suffix 충돌 방지, `소프트 리셋`으로 복구 안정성 강화
- 📝 **문서 업데이트**: PIPELINE_LOCK.md 및 알고리즘 분석 문서 최신화

### v16.11 (2026-01-29)
- 🧠 **자막 알고리즘 완벽 재설계**: 글로벌 히스토리 Suffix 매칭 알고리즘 도입
- 📝 **타임스탬프 저장 개선**: TXT/DOCX/HWP 저장 시 1분 간격으로 타임스탬프 표시
- 🐛 **버그 수정**: 줄넘김 정리 후 자막 수집 중단 오류 해결, end_time null 오류 수정

### v16.10 (2026-01-27)
- ⚡ **스트리밍 아키텍처**: 자막 수집 로직 전면 재설계 (Diff & Append 방식)
- 🐛 **버그 수정**: 1분 이상 자막 수집 시 사라지는 문제 해결
- 🛡️ **안정성**: 중지 버튼 클릭 시 크래시 해결
- 🎨 **UI**: 버튼 레이아웃 개선 및 키워드 입력창 복구

### v16.9 (2026-01-23)
- 🛡️ **데이터 안정성 강화**: 자동 백업 백그라운드 처리 + 중복 실행 방지
- 🔒 **스레드 안전성**: 자막 데이터 접근 락(Lock) 전면 적용
- ⚡ **DB 성능 개선**: 연결 캐싱, FTS5 검색 적용, 대량 삽입 최적화

### v16.8 (2026-01-23)
- 🧾 **상임위원회 xcode 최신화** (기재위, 여가위, 정무위 등 반영)
- ⚡ **성능 최적화**: 정규식/포맷 캐싱, 통계 캐시

### v16.7 (2026-01-23)
- 🧭 **URL 감지 강화**: API 기반 xcgcd 자동 보완
- 📡 **생중계 목록 선택 UI**: 현재 방송 직접 선택 버튼
- 🧩 **특별위원회 지원**: 국정감사 등 특위 코드 대응

### v16.6 (2026-01-22)
- 🔌 **연결 상태 모니터링**: 상태바 아이콘 표시
- 🔄 **자동 재연결**: 지수 백오프 재시도
- 📝 **자동 파일명 생성**: 위원회명 자동 추출
- 🗄️ **SQLite 데이터베이스**: 세션 히스토리 및 검색
- 📎 **자막 병합**: 다중 세션 병합 도구

---

## 📄 라이선스

MIT License

© 2024-2026
