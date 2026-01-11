# 🏛️ 국회 의사중계 자막 추출기 v17.2

국회 의사중계 웹사이트에서 **실시간 AI 자막**을 자동으로 추출하고 저장하는 PyQt6 기반 프로그램입니다.

---

## ✨ v17.2 안정성 업데이트

### 🛡️ 스레드 안전성 강화
- **경쟁 조건 해결** - 자막 처리 시 발생할 수 있는 데이터 손상 방지
- **파일 저장 동기화** - 실시간 저장 파일 접근 시 락(Lock) 적용

### ⚡ 시스템 안정성
- **리소스 관리** - 브라우저 및 파일 핸들 정리 로직 개선
- **오류 처리** - Playwright 브라우저 감지 및 초기화 로직 강화
- **예외 처리** - 워커 스레드 종료 대기 및 재시도 메커니즘 개선

---

## ✨ v17.0 기능

### 📑 다중 위원회 동시 모니터링
- **탭 기반 다중 세션** - 여러 상임위원회를 동시에 모니터링
- **독립적인 세션 관리** - 각 탭이 독립적인 브라우저와 자막 데이터 보유
- **전체 세션 검색** (Ctrl+Shift+F) - 모든 세션에서 키워드 검색
- **일괄 시작/중지** - 모든 세션 한 번에 제어

### 🌐 다중 브라우저 지원
- **Selenium 기반**: Chrome, Firefox, Edge
- **Playwright 기반**: Chromium, Firefox, WebKit (Safari 호환)
- 설치된 브라우저 **자동 감지**
- 세션별 **브라우저 개별 선택** 가능

### 📂 파일 구조
| 파일 | 설명 |
|------|------|
| `multi_session_launcher.py` | 다중 세션 버전 실행 파일 |
| `browser_drivers.py` | 브라우저 추상화 모듈 |
| `subtitle_session.py` | 세션 관리 모듈 |
| `session_tab_widget.py` | 탭 UI 위젯 |

---

## ✨ 주요 기능

### 🎯 실시간 자막 추출
- 국회 의사중계 웹사이트의 AI 자막을 실시간으로 캡처
- **2초 타임아웃**으로 자막 자동 확정
- 중복 자막 자동 제거 및 병합

### 💾 다양한 저장 형식

| 형식 | 설명 | 단축키/라이브러리 |
|------|------|-------------------|
| **TXT** | 일반 텍스트 | Ctrl+S |
| **SRT** | 자막 파일 형식 | - |
| **VTT** | WebVTT 자막 형식 | - |
| **DOCX** | Word 문서 | python-docx 필요 |
| **HWP** | 한글 문서 | Hancom Office + pywin32 |
| **RTF** | 서식 있는 텍스트 | 기본 (HWP 호환) |

### 🔍 검색 및 하이라이트
- **실시간 검색** - 자막 내 텍스트 검색 (Ctrl+F)
- **키워드 하이라이트** - 특정 단어 강조 표시
- **알림 키워드** - 특정 키워드 감지 시 토스트 알림

### 🏛️ 상임위원회 프리셋
- **📋 상임위 버튼** - 16개 상임위원회 URL 빠른 선택
- **사용자 정의 프리셋** 추가/수정/관리 기능

### ⚙️ 편의 기능
- **헤드리스 모드** - 브라우저 창 숨기고 백그라운드 실행
- **실시간 저장** - 자막을 파일에 자동 저장
- **세션 저장/불러오기** - 작업 내용 보존
- **URL 히스토리** - 최근 사용한 URL 자동 저장 (태그 지원)
- **자동 백업** - 5분마다 자동 백업
- **통계 내보내기** - 상세 통계 보고서 생성

### 🎨 UI 기능
- **다크/라이트 테마** 전환 (Ctrl+T)
- **시스템 트레이** 지원
- **타임스탬프 표시** 옵션
- **자동 스크롤** 옵션
- **통계 패널** - 글자 수, 단어 수, 분당 글자 수
- **토스트 알림** - 비차단 알림 메시지 (스택 지원)
- **글자 크기 조절** - Ctrl++/Ctrl-- 또는 메뉴에서 선택
- **HiDPI 지원** - 고해상도 모니터 지원

---

## 📦 설치

### 필수 라이브러리

```bash
pip install PyQt6 selenium
```

### 선택 라이브러리 (추가 기능)

```bash
pip install python-docx  # DOCX 저장용
pip install pywin32      # HWP 저장용 (Windows)

# Playwright (다중 브라우저 지원)
pip install playwright
playwright install  # 브라우저 설치
```

### 브라우저 요구사항
- **Selenium**: Chrome, Firefox 또는 Edge 중 하나 설치 필요
- **Playwright**: 자동으로 브라우저 설치 (`playwright install`)

---

## 🚀 실행

### 다중 세션 버전 (권장)

```bash
python multi_session_launcher.py
```

### 기본 버전 (단일 세션)

```bash
python "251226 국회의사중계 자막.py"
```

### EXE 빌드 및 실행

```bash
# 빌드 (단일 실행 파일 생성)
pyinstaller subtitle_extractor.spec

# 실행
dist\subtitle_extractor.exe
```

---

## ⌨️ 단축키

| 단축키 | 기능 |
|--------|------|
| **F5** | 추출 시작 |
| **Escape** | 추출 중지 |
| **Ctrl+F** | 검색창 열기 |
| **F3** | 다음 검색 결과 |
| **Shift+F3** | 이전 검색 결과 |
| **Ctrl+N** | 새 세션 추가 |
| **Ctrl+Shift+F** | 전체 세션 검색 |
| **Ctrl+C** | 자막 전체 복사 |
| **Ctrl+T** | 테마 전환 |
| **Ctrl+S** | TXT 저장 |
| **Ctrl+Shift+S** | 모든 세션 저장 |
| **Ctrl++** | 글자 크기 키우기 |
| **Ctrl+-** | 글자 크기 줄이기 |
| **Ctrl+Q** | 종료 |

---

## 📁 파일 구조

```
korea-assembly-cc/
├── multi_session_launcher.py    # 다중 세션 메인 프로그램
├── browser_drivers.py           # 브라우저 추상화 모듈
├── subtitle_session.py          # 세션 관리 모듈
├── session_tab_widget.py        # 탭 UI 위젯
├── 251226 국회의사중계 자막.py  # 단일 세션 버전
├── subtitle_extractor.spec      # PyInstaller 빌드 설정
├── README.md                    # 이 문서
├── subtitle_config.json         # 프로그램 설정
├── url_history.json             # URL 히스토리 (자동 생성)
├── logs/                        # 로그 파일
├── sessions/                    # 세션 저장 파일
├── backups/                     # 자동 백업 파일
└── realtime_output/             # 실시간 저장 파일
```

---

## 🔧 문제 해결

### Chrome 시작 오류
- Chrome 브라우저가 최신 버전인지 확인
- 프로그램이 자동으로 최대 3회 재시도합니다

### 자막이 표시되지 않음
- 국회 의사중계 페이지에서 자막 버튼을 수동으로 클릭해 보세요
- 다른 CSS 선택자를 시도해 보세요

### HWP 저장 오류
- 한글 Office가 설치되어 있어야 합니다
- COM 캐시 오류 시 자동으로 캐시 정리 후 RTF로 저장됩니다

### Playwright 관련
- PyInstaller로 패키징된 EXE에서는 Playwright가 지원되지 않습니다
- Playwright는 Python 스크립트 실행 시에만 사용 가능합니다

---

## 📝 변경 이력

### v17.2 (2026-01-11)
- 🛡️ **안정성 강화** - 스레드 안전성 확보 (경쟁 조건 해결), 리소스 관리 개선
- 🔧 **기능 개선** - `find_element` 호환성 수정, Playwright 감지 로직 개선
- 🐛 **버그 수정** - 세션 저장 시 동기화 문제 해결

### v17.1 (2025-01-05)
- 🎨 **UI/UX 전면 개선** - 모던 다크 테마, Empty State
- ⚡ **성능 최적화** - 증분 렌더링, 캐싱
- 🐛 **버그 수정** - 타이머 cleanup, Playwright 호환성

### v17.0 (2025-01-04)
- ✨ **다중 위원회 동시 모니터링** - 탭 기반 UI
- ✨ **다중 브라우저 지원** - Selenium + Playwright
- 🔍 **전체 세션 검색** - Ctrl+Shift+F

### v16.0 (2025-12-29)
- ✨ **시스템 트레이 통합** - 트레이 최소화 옵션
- ✨ **자막 편집/삭제 기능** - Ctrl+E, Delete
- 🐛 **HWP 저장 오류 수정**

---

## 📄 라이선스

MIT License

© 2024-2025
