# Project Audit

> **감사 일자**: 2026-08-10  
> **대상 버전**: v16.14.8 (`Config.VERSION` = README 첫 줄 로드)  
> **초점**: 최근 추가 기능 — Chrome 확장 수집 정합(P1-A/B), export 견고화(`core/export_text`, HWP/HWPX/SRT/VTT/DOCX), 운영 문서  
> **분석 방법**: README.md · CLAUDE.md 정독 → CodeGraph MCP(`codegraph_explore`) 우선 구조·호출 관계 분석 → 필요 구간만 보조 검색/파일 열람 → `pytest` · `pyright` 교차 검증  
> **범위**: 기능 구현 관점(잠재 결함, 예외/검증, 상태·비동기, I/O·DB, 보안, 테스트, 문서 정합)  
> **선행 문서**: `docs/CHROME_EXTENSION_PARITY.md`, `docs/HWPX_EXPORT_ANALYSIS.md`, `PIPELINE_LOCK.md`  
> **확장 감사**: 보안·동시성·성능 광역은 필요 시 [`PROJECT_AUDIT_EXTENDED.md`](PROJECT_AUDIT_EXTENDED.md) 병행  
> **후속 구현 (2026-08-10)**: 본 문서 권고 1~3단계 개선 착수 — H1 pyright HWP 바인딩, H2/H3 자막 활성화 active 검사, H5 저장 path 가드, H6 HWP 이중 통지·Visible·대용량 안내, H4 row-split 순수 미러 테스트, H7 SRT/VTT 상대 타임코드, H9/H10 README, 푸시 전 pyright 훅(`scripts/check_before_push.py`, `scripts/install_git_hooks.py`).

---

## 1. Executive Summary

국회 의사중계 AI 자막을 **PyQt6 UI + Selenium ExtractionWorker + structured probe + 자막 파이프라인 + runtime archive + SQLite** 로 수집·저장하는 Windows 중심 데스크톱 앱이다.  
2026-08-10 커밋(`0da15e1`)으로 **크롬 확장 수집 정합**과 **내보내기 견고화**가 들어갔고, 전체 회귀는 대부분 유지되나 **pyright 0 errors 게이트가 깨진 상태**가 확인되었다.

| 축 | 위험도 | 한 줄 요약 |
|----|--------|------------|
| **신규 수집 정합(P1)** | **Medium** | multi-speaker·AI 버튼 의도 반영, 토글/검증 미흡 잔존 |
| **신규 export 견고화** | **Low~Medium** | sanitize·cue time 개선됨, 동시 저장·HWP COM·pyright 이슈 |
| **품질 게이트** | **High** | `pyright` **5 errors** (HWP `insert_text` nested closure) |
| **기능 안정성(기존 코어)** | **Low~Medium** | 장시간 세션·큐 하드닝은 성숙, suffix 구조 한계는 잔존 |
| **문서 정합** | **Low~Medium** | 신규 docs 양호, README Python 범위 vs 실빌드 3.14 편차 |
| **보안** | **Low** | URL host 정책·atomic write 유지, 외부 네트워크 최소 |

**검증 스냅샷**

| 시점 | 항목 | 결과 |
|------|------|------|
| 2026-08-10 감사 직후 | `pytest` / `pyright` | 352 pass / 2 fail (pyright 5 errors) |
| **2026-08-10 후속 구현 후** | 로컬 `pytest` | **~360 passed / 2 skipped** |
| | `pyright` | **0 errors** |
| | GitHub CI | **success** (pyright fail-fast → pytest) |
| | pre-push 훅 | pyright 0 통과 후 push |

**핵심 결론 (후속 반영 후)**

1. Critical 급 데이터 손실 결함 없음. H1 pyright·H2 AI 토글·H5 저장 가드·H6 HWP 통지·H7 상대 타임코드 등 **1~3단계 조치 반영**.  
2. **품질 게이트**: 로컬 pre-push + CI fail-fast pyright + `test_pyright_regression` 3중.  
3. 잔여: probe **실 DOM E2E**(opt-in), suffix 구조 한계(의도적 보류), Node 20 Actions deprecation 경고(빌드 비차단).

---

## 2. Project Understanding

### 2.1 목적 (README · CLAUDE)

- 국회 의사중계 웹 **실시간 AI 자막**을 딜레이 없이 추출·저장
- 출력: TXT / SRT / VTT / DOCX / **HWPX** / HWP / RTF / JSON 세션 / SQLite
- 운영: 자동 재연결, runtime segmented session, portable/`%LOCALAPPDATA%` 저장소, DB 검색·계보
- 형제 제품: Chrome 확장(`korea-assembly-cc-chrome`) — **코드 공유 없음**, **사이트 DOM/수집 의미론 공유** (`docs/CHROME_EXTENSION_PARITY.md`)

### 2.2 아키텍처 (CLAUDE + CodeGraph)

```text
국회의사중계 자막.py
  └─ storage preflight → QApplication + MainWindow(facade+mixins)

MainWindow
  ├─ Runtime (lifecycle / driver / background registry)
  ├─ Capture (browser / dom probe / observer / live list)
  ├─ Pipeline (queue / messages / stream / state · PIPELINE_LOCK)
  ├─ Persistence (session / runtime archive / **exports**)
  ├─ Database (DBWorker + DatabaseManager)
  └─ View / UI

ExtractionWorker (non-daemon)
  -- MainWindowMessageQueue(maxsize=500, run_id) --> UI
Control plane
  -- AppControlMessageQueue(maxsize=200) --------┘
```

### 2.3 신규·관련 실행 흐름 (CodeGraph 기준)

#### A. 수집 정합 P1

1. Worker 시작/재연결 → `_activate_subtitle`  
   (`capture_browser` → `capture_observer._activate_subtitle`)  
   - 순서: `layerSubtit()` → `.btn_subtit_ai` → `.btn_subtit_def` → … → display:block  
2. 주기 루프: Observer 버퍼(리셋 신호) 또는  
   `_read_subtitle_probe_by_selectors` (SoT)  
3. probe JS `collectMultiSpeakerSegments`  
   - 서로 다른 화자색 span → `nodeKey = base#segarr_*` 분할  
4. preview payload → pipeline → live ledger / entries

#### B. 내보내기 견고화

1. UI `_save_*` → `_build_persistent_entries_snapshot()` + runtime stream context  
2. `_save_in_background` → `_start_background_thread(..., "FileSaveWorker")`  
3. 형식별 writer:
   - TXT/DOCX/HWP/HWPX/RTF: `sanitize_document_text` / HWPX `strip_illegal_xml_chars`
   - SRT/VTT: `sanitize_subtitle_cue_text` + `resolve_cue_time_range`
   - HWPX: `save_hwpx_document` → `atomic_write_bytes`
   - DOCX: temp + `os.replace`
   - HWP: COM `InsertText` 루프 + 실패 시 `hwp_save_failed` control 메시지

### 2.4 개발 규칙 (CLAUDE에서 추출)

- Worker ↔ UI: bounded queue + `run_id` stale drop  
- `subtitle_lock` 하에서 리스트 접근, I/O는 락 밖  
- 파이프라인 suffix `rfind` 의미론 변경 시 `PIPELINE_LOCK.md` 필수  
- pyright **0 errors** 정책, 파일 단위 `# pyright:` 금지  
- 저장소 root 3모드(dev / portable / frozen LOCALAPPDATA)

---

## 3. High-Risk Issues

### H1. HWP `insert_text` nested closure — pyright 5 errors / 품질 게이트 붕괴

* **위치**: `ui/main_window_impl/persistence_exports.py` — `_save_hwp` 내부 `insert_text` (약 475–482행)  
* **문제**: `hwp = None` 이후 nested 함수가 `hwp.HAction` 등을 참조. 타입 체커는 `hwp`를 `None` 가능으로 본다.  
* **영향**:  
  - `tests/test_pyright_regression.py` 실패 (감사 시 2 failed)  
  - 프로젝트 규칙 “pyright 0 errors” 위반 → CI/로컬 게이트 차단  
* **근거**: `pyright --outputjson` → errorCount=5, 전부 해당 파일 해당 줄. `pytest` pyright 회귀 실패.  
* **권장 수정 방향**:  
  - `insert_text`를 `hwp` 할당 **이후**에 정의하거나, 인자로 `hwp`를 넘기고 `assert hwp is not None` / 로컬 non-optional 바인딩.  
  - 수정 후 `pyright` 0 + 해당 회귀 테스트 통과 확인.  
* **우선순위**: **High** (기능 즉시 장애는 아니나 게이트 Critical에 가깝고 최근 변경 도입)

---

### H2. AI 자막 버튼 — “이미 ON” 상태 재클릭 시 OFF 토글 가능

* **위치**: `ui/main_window_impl/capture_observer.py` — `_activate_subtitle`  
* **문제**: `.btn_subtit_ai` 등이 보이기만 하면 `click()` 후 성공 반환. **현재 활성(끄기/ON 클래스) 여부를 검사하지 않음**. 재연결·재시작 시 이미 AI 자막이 켜져 있으면 클릭으로 **꺼질 수 있음**.  
* **영향**: 수집 시작 직후 자막이 안 잡히거나, 일반/AI 경로가 바뀌어 공백·미수집.  
* **근거**:  
  - 코드: `document.querySelector('.btn_subtit_ai'); if(btn){btn.click(); return true;}`  
  - 크롬 확장(`docs/CHROME_EXTENSION_PARITY.md` 참조 경로 `subtitle-layer.ts`)은 `isActivationControlActive`로 ON이면 클릭하지 않음.  
  - 재연결 경로: `capture_browser`가 `_activate_subtitle` 재호출.  
* **권장 수정 방향**:  
  - title/class/`aria-pressed`로 active 판별 후 **비활성일 때만** 클릭.  
  - `layerSubtit()` 성공만으로 조기 종료하지 말고, AI 컨트롤 active 또는 `.smi_word` 존재를 확인하는 2단 검증 검토.  
* **우선순위**: **High**

---

### H3. `layerSubtit()` 우선 성공 시 AI 버튼 경로 스킵

* **위치**: 동일 `_activate_subtitle` 첫 스크립트  
* **문제**: `layerSubtit()`이 true를 반환하면 AI 버튼 클릭 루프에 진입하지 않음. 레이어만 열리고 **AI 모드가 아닌 상태**일 수 있음.  
* **영향**: 일반 자막/빈 레이어만 보이는 세션 → probe는 동작하나 AI 계약(stxt/segarr)과 다를 수 있음.  
* **근거**: activation_scripts 순서 고정 + 첫 성공 시 break.  
* **권장 수정 방향**:  
  - `layerSubtit` 후 AI 버튼 active 검사, 미활성이면 계속 시도.  
  - 또는 AI 버튼을 `layerSubtit`보다 우선(사이트 회귀 테스트 후).  
* **우선순위**: **Medium** (H2와 연계)

---

### H4. multi-speaker 분할 — 임베디드 JS의 실 DOM 회귀 부재

* **위치**: `ui/main_window_impl/capture_dom.py` — probe IIFE 내 `collectMultiSpeakerSegments` / `readObservedRows`  
* **문제**: 로직은 크롬 확장과 정렬했으나, 테스트는 (1) 소스 문자열 존재, (2) driver mock이 이미 분할된 row를 돌려줄 때 Python 정규화만 검증. **브라우저 JS 실행으로 multi-color span 분할을 검증하지 않음**.  
* **영향**: 향후 인라인 JS 수정 시 silent regression 가능. 동일 색 multi-span은 미분할(의도)이나 사이트 DOM 변형 시 미탐지.  
* **근거**: `tests/test_capture_chrome_parity_p1.py`; CodeGraph blast: probe 경로 의존.  
* **권장 수정 방향**:  
  - probe JS를 테스트 가능한 문자열/모듈로 추출하거나, selenium opt-in fixture로 `stxt`+`segarr` DOM을 주입해 row 개수·channel 단언.  
* **우선순위**: **Medium**

---

### H5. 동일 경로 병렬 `FileSaveWorker` — 덮어쓰기·부분 파일 경쟁

* **위치**: `persistence_exports._save_in_background` → `runtime_lifecycle._start_background_thread`  
* **문제**: 저장마다 새 스레드를 시작. **동일 `path`에 대한 직렬화/락 없음**. 사용자가 연속 저장하거나 HWP 실패 후 대체 저장이 겹치면, atomic replace 간 race 가능.  
* **영향**: 드물게 최종 파일이 예상과 다르거나(나중 완료분 승리), 실패 토스트와 성공 토스트 혼재.  
* **근거**: `_start_background_thread`는 shutdown 가드만 있고 path mutex 없음. CodeGraph: `background_save` 호출자 다수.  
* **권장 수정 방향**:  
  - path 단위 lock, 또는 “저장 중” 플래그로 동일 형식 중복 시작 거부.  
  - 성공 토스트에 실제 기록 entry 수 표시.  
* **우선순위**: **Medium**

---

### H6. HWP COM 경로 — Visible 강제·장시간 세션·이중 실패 통지

* **위치**: `_save_hwp` / `do_save_with_error` / `pipeline_messages` `hwp_save_failed`  
* **문제**:  
  1. `XHwpWindows.Item(0).Visible = True` — 백그라운드 저장인데 UI 노출.  
  2. 문장마다 COM `InsertText` — 수천 엔트리 시 수분~수십 분 가능, 사용자 취소 경로 약함.  
  3. 실패 시 `hwp_save_failed` emit **후** `raise` → `_save_in_background` 에러 토스트 + UI 대체 저장 다이얼로그 **이중 통지**.  
* **영향**: UX 혼란, 한컴 프로세스 점유, 대용량 시 앱 종료 대기 지연.  
* **근거**: 코드 경로 및 `pipeline_messages` 핸들러.  
* **권장 수정 방향**:  
  - Visible=False 시도(한컴 버전별 검증), 대용량 시 HWPX 권장 안내/자동 전환 임계값.  
  - 실패 시 emit만 하거나 raise만 하도록 단일화.  
* **우선순위**: **Medium**

---

### H7. SRT/VTT 타임코드가 “영상 상대 시간”이 아닌 벽시계 `HH:MM:SS`

* **위치**: `core/export_text.format_srt_timestamp` / `persistence_exports._save_srt`·`_save_vtt`  
* **문제**: `datetime.strftime('%H:%M:%S')` 사용 → 자막 수집 시각(벽시계)이 그대로 큐 타임코드. 플레이어에 얹으면 00:00 기준 영상과 **어긋남**.  
* **영향**: “영상 자막 파일”로 쓸 때 동기화 실패. 회의 로그 용도에는 유효.  
* **근거**: README가 SRT/VTT를 저장 형식으로 나열하나 “영상 상대” 명시 없음. 코드는 wall-clock.  
* **권장 수정 방향**:  
  - 옵션: 세션 첫 entry 기준 relative cue, 또는 문서에 “벽시계 기준” 명시.  
* **우선순위**: **Medium** (요구 정의 이슈에 가깝지만 기능 오해 가능)

---

### H8. (잔존) 파이프라인 suffix 구조 한계

* **위치**: `core/subtitle_pipeline*` · `PIPELINE_LOCK.md`  
* **문제**: 글로벌 compact + rfind는 장시간·대규모 반복 발화에서 desync/중복 잔존 가능. soft_resync로 완화.  
* **영향**: 수집 정확도 이슈(기존 알려진 한계).  
* **근거**: 기존 감사·PIPELINE_LOCK 이력. 이번 신규 기능 범위 밖.  
* **권장 수정 방향**: 의도적 보류 유지 또는 별도 연구 과제.  
* **우선순위**: **Low~Medium** (신규 기능 비대상)

---

### H9. (문서) README Python 권장 범위 vs 실제 빌드 환경

* **위치**: `README.md` “Python 3.10–3.12 권장” / 로컬 PyInstaller 로그 `Python: 3.14.7`  
* **문제**: 문서 권장과 실빌드 인터프리터 불일치. 3.14에서 미검증 의존성 이슈 가능.  
* **영향**: 기여자/CI 환경 편차, 간헐적 패키징 차이.  
* **근거**: README 문구, 직전 빌드 로그.  
* **권장 수정 방향**: README를 실제 지원 범위에 맞게 수정하거나 CI 매트릭스 고정.  
* **우선순위**: **Low**

---

### H10. (패키징) frozen EXE에서 `python-docx` hidden import 누락 가능

* **위치**: `subtitle_extractor.spec` / PyInstaller 로그 `Hidden import 'docx' not found`  
* **문제**: DOCX는 optional인데 frozen 환경에 미포함이면 메뉴는 있으나 저장 시 ImportError 안내.  
* **영향**: 배포 EXE 사용자 DOCX 불가(문서상 optional과 정합할 수 있음).  
* **근거**: 빌드 로그 ERROR Hidden import docx.  
* **권장 수정 방향**: requirements를 빌드 env에 포함하거나 README/EXE 안내에 “DOCX는 소스+python-docx” 명시.  
* **우선순위**: **Low**

---

## 4. Potential Functional Gaps

| 항목 | 상태 | 비고 |
|------|------|------|
| 미확정 필터 UI 토글 | **추정 갭** | `filter_unconfirmed_enabled` 파라미터는 있으나 워커 호출은 기본 `True` 고정, UI 설정 노출 없음 |
| unconfirmed fallback streak (확장 P2) | 의도적 미이식 | `CHROME_EXTENSION_PARITY.md` — 정체 제보 시 검토 |
| unconfirmed `backgroundImage` 샘플링 | 의도적 미이식 | 사이트 실측은 color 중심 |
| multi-speaker 실 DOM E2E | **추정 갭** | H4 참고 |
| SRT relative timeline 옵션 | **추정 갭** | H7 참고 |
| 저장 중 동일 파일 재진입 방지 | **추정 갭** | H5 참고 |
| HWP 대용량 진행률/취소 | **추정 갭** | H6 참고 |
| AI 버튼 active 검사 | **기능 갭** | H2 참고 (추정 아님) |
| 발언자 라벨 export (확장 v1.0.13) | 의도적 미이식 | 데스크톱 제품 범위 외 |
| HWPX 스키마 전면 개편 | **불필요** 판정 | `docs/HWPX_EXPORT_ANALYSIS.md` |
| probe 빈 결과 시 사용자 진단(selector/mode) | 부분 존재 | 확장 진단 패널 수준은 없음 — **추정 개선점** |

---

## 5. Recommended Fix Plan

### 1단계 — 즉시 (게이트·수집 회귀 위험)

1. **H1** pyright 5건 해소 (`insert_text` non-optional 바인딩) → `pytest tests/test_pyright_regression.py` 통과.  
2. **H2** AI/일반 자막 컨트롤 **active 검사** 후 클릭 (확장 subtitle-layer 정책 정렬).  
3. 회귀 테스트: “이미 ON인 버튼은 클릭하지 않음” 스크립트/소스 계약 또는 fake driver 시퀀스.

### 2단계 — 안정성

4. **H3** `layerSubtit` 성공 후에도 AI active 미확인 시 버튼 경로 계속.  
5. **H5** FileSaveWorker path/형식 단위 중복 시작 가드.  
6. **H6** HWP 실패 통지 단일화, Visible 정책 재검토, 대용량 시 HWPX 유도.  
7. SRT/VTT **빈 큐만 남는 저장** 시 경고(성공 토스트 방지).

### 3단계 — 구조·제품

8. **H4** probe JS 추출 또는 DOM fixture 테스트.  
9. **H7** relative SRT 옵션 또는 README 명시.  
10. filter_unconfirmed UI/설정 노출 여부 결정.  
11. **H9/H10** 지원 Python·optional DOCX 문서/빌드 정합.  
12. suffix 파이프라인 구조 개선은 별도 연구(기존 보류 유지 가능).

---

## 6. Test Recommendations

| 우선 | 테스트 | 목적 |
|------|--------|------|
| P0 | `test_pyright_regression` 재통과 | 게이트 복구 |
| P0 | `_activate_subtitle`: ON 상태 버튼 미클릭 | H2 회귀 |
| P1 | `_activate_subtitle`: `layerSubtit` true여도 AI inactive면 버튼 시도 | H3 |
| P1 | multi-speaker: 실 JS 또는 추출 함수로 이색 span → row 2개 | H4 |
| P1 | SRT: `end<=start`, 빈 줄 본문, 제어문자 (이미 `test_export_hardening` 존재 — 유지) | 회귀 고정 |
| P1 | HWPX: `\x00` strip (이미 존재 — 유지) | |
| P2 | 동일 path에 FileSaveWorker 2회 연속 → 직렬/거부 | H5 |
| P2 | HWP 실패 시 toast 1회 + dialog 1회만 | H6 |
| P2 | 모든 엔트리가 sanitize 후 빈 문자열 → 사용자 경고 | export edge |
| P3 | opt-in live smoke: AI 버튼 on, `stxt`+`segarr` 수집 | 사이트 계약 |
| P3 | frozen EXE: import smoke에 `core.export_text` | 패키징 |

**기존 유지 권장**: `tests/test_capture_chrome_parity_p1.py`, `tests/test_export_hardening.py`, `tests/test_hwpx_export.py`, `tests/test_review_20260323_regressions.py`.

---

## 부록 A. 신규 기능 대비 문서 정합

| 문서 주장 | 구현 | 판정 |
|-----------|------|------|
| `CHROME_EXTENSION_PARITY` P1-A/B 반영 | `capture_dom` / `capture_observer` | 정합 |
| HWPX 스키마 전면 개편 불필요 | `hwpx_export` 최소 패키지 유지 | 정합 |
| export sanitize / cue time | `export_text` + exports | 정합 |
| CLAUDE “pyright 0 errors” | 현재 5 errors | **불일치 (H1)** |
| README SRT/VTT 저장 | 벽시계 타임코드 | 명시 부족 (H7) |
| README Python 3.10–3.12 | 로컬 빌드 3.14 관측 | 편차 (H9) |

---

## 부록 B. CodeGraph 관찰 요약

- Export hot path: `_save_*` → `_save_in_background` → `FileSaveWorker` → 형식별 writer / `save_hwpx_document`.  
- Capture hot path: `_extraction_worker` → `_activate_subtitle` + `_read_subtitle_probe_by_selectors` → preview queue → pipeline.  
- multi-speaker·AI 버튼은 **수집 입력 품질**에, export_text는 **출력 무결성**에 영향. 파이프라인 suffix 코어는 이번 변경 비대상.

---

## 부록 C. 한 줄 요약

**신규 수집·export 방향은 타당하나, (1) pyright 게이트 붕괴, (2) AI 자막 버튼 토글 위험, (3) 병렬 저장·HWP COM·실 DOM 테스트 공백을 우선 다뤄야 한다. HWPX 스키마 전면 개편은 불필요 판정을 유지한다.**
