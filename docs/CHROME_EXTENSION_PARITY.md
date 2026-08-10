# 데스크톱 ↔ Chrome 확장 상호 의존·정합

업데이트: `2026-08-10`

이 문서는 **국회 의사중계 자막 추출기(데스크톱, 본 저장소)** 와  
**[korea-assembly-cc-chrome](https://github.com/twbeatles/korea-assembly-cc-chrome) (Chrome Extension)** 사이의  
**공유 계약·의도적 분기·이식 정책**을 정리한다.

두 제품은 **같은 국회 중계 사이트 DOM/URL 계약**을 소비하지만,  
코드베이스를 공유하지 않으며 **플랫폼이 다른 형제 제품**이다.

---

## 1. 제품 관계

| 항목 | 데스크톱 (`korea-assembly-cc`) | Chrome 확장 (`korea-assembly-cc-chrome`) |
|------|-------------------------------|------------------------------------------|
| 런타임 | PyQt6 + Selenium (별도 Chrome 프로세스) | Manifest V3 content script (페이지 안) |
| 수집 | MutationObserver 주입 + structured probe (execute_script) | page-world observer + DOM probe (직접 접근) |
| 저장 | SQLite + JSON session + runtime segment archive | IndexedDB (+ storage fallback) |
| 내보내기 | TXT/SRT/VTT/DOCX/**HWPX**/HWP/RTF | TXT/SRT/VTT/JSON/MD/CSV |
| 파이프라인 코어 | `core/subtitle_pipeline*` + `PIPELINE_LOCK.md` | `src/core/subtitle-pipeline/` (동일 의미론 이식) |

**의존 방향**

- **사이트 → 양쪽**: DOM 셀렉터·화자색·URL/xcode 계약은 **사이트가 단일 진실 원천**.
- **양쪽 간 코드 의존**: 없음 (서브모듈·공통 패키지 없음).
- **지식 의존**: 수집 버그/사이트 변경 대응 시 **서로 문서·로직을 대조**하는 것이 권장된다.
  - 확장 측 사이트 점검 예: `SITE_COMPATIBILITY_REVIEW_2026-08-10.md` (확장 저장소)
  - 데스크톱 측 고정: `PIPELINE_LOCK.md`, 본 문서

---

## 2. 공유해야 하는 계약 (사이트/수집)

아래는 **양쪽이 맞춰 두어야 하는 계약**이다. 한쪽만 바꾸면 수집 품질이 어긋난다.

### 2.1 URL / 호스트

- 주 호스트: `assembly.webcast.go.kr`
- 보조 호스트: `webcast.assembly.go.kr` (DNS 불안정 시에도 목록 유지 권장)
- 플레이어: `/main/player*`, 기자회견: `/main/pressplayer*`
- 본회의: `xcode=10` 또는 `xcgcd` prefix `DCM000010…`

### 2.2 자막 DOM

| 계약 | 값/패턴 |
|------|---------|
| 레이어 | `#viewSubtit` |
| 단어/문장 노드 | `.smi_word` (AI: `.stxt{segment}` + `span#segarr_*`) |
| 컨테이너 | `.incont` |
| AI/일반 토글 | `.btn_subtit_ai`, `.btn_subtit_def`, `.btn_subtit`, `#smi_btn` |
| 화자색 | primary `rgb(35, 124, 147)` (`#237c93`), secondary `rgb(30, 30, 30)` |
| 미확정 배경 | 불투명 배경(예: `#cfe5f7`, 인식 중 하이라이트) → commit 제외 정책 |

### 2.3 파이프라인 의미론 (양쪽 공통 의도)

- 글로벌 history + **suffix `rfind`**
- soft resync, keepalive(`end_time` 갱신)
- merge boundary: `source_node_key` / speaker color·channel / container `source_mode`
- 미확정(unconfirmed) 필터 기본 on

데스크톱 코어 수정 시 `PIPELINE_LOCK.md` §2 이력을 남긴다.  
확장 측은 자체 pipeline 모듈과 테스트를 갱신한다.

---

## 3. 구현 경로 차이 (의도적)

같은 계약이라도 **읽기 경로 구현은 달라도 된다.**

```text
[사이트 DOM]
      │
      ├─ Chrome: subtitle-rows.ts / injected-observer (structured row 직접 브리지)
      │
      └─ Desktop: capture_observer (변경/reset 신호)
                 + capture_dom probe JS (structured row SoT)
      │
      ▼
 live ledger → subtitle pipeline (rfind / merge)
```

- 데스크톱 Observer 버퍼의 **텍스트 본문**은 참고 신호에 가깝고,  
  실제 자막 row는 **`_read_subtitle_probe_by_selectors`** 가 SoT다.
- 따라서 확장의 observer 브리지 전면 이식이 **필수는 아니다.**

---

## 4. 정합 작업 이력 (2026-08-10)

확장 대비 데스크톱에 반영한 **수집 P1**:

| ID | 내용 | 데스크톱 위치 |
|----|------|----------------|
| P1-B | AI 자막 버튼 우선 클릭 (`.btn_subtit_ai` → `.btn_subtit_def` → …) | `ui/main_window_impl/capture_observer.py` |
| P1-A | 한 `.smi_word` 안 다중 화자 span 분할 (`#segarr_*`) | `ui/main_window_impl/capture_dom.py` probe JS |

회귀: `tests/test_capture_chrome_parity_p1.py`

### 의도적으로 이식하지 않은 것

| 항목 | 이유 |
|------|------|
| 확장 panel / history 편집 / IDB | 플랫폼 전용 |
| `mergeMaxChars` 1000 vs 데스크톱 300 | 제품 정책 상수 |
| unconfirmed fallback streak, bgImage 샘플링 | 사이트 실측상 당장 필수 아님 (P2) |
| Observer structured 전면 재작성 | probe SoT 유지로 충분 |
| 확장 export(MD/CSV) | 데스크톱은 HWPX/HWP 등 별도 경로 |

---

## 5. 사이트 변경 대응 절차

1. 가능하면 **확장 저장소**에서 오프라인/라이브 호환 검토 문서를 먼저 갱신한다.
2. 셀렉터·화자색·버튼·URL 계약이 바뀌면 **양쪽 모두** 수정 후보로 올린다.
3. 데스크톱은 probe JS + 활성화 스크립트 + (필요 시) `Config` 프리셋/`url_policy` 를 본다.
4. 파이프라인 suffix 의미론 변경은 **최후 수단**이며 `PIPELINE_LOCK.md` 필수.

---

## 6. 관련 경로

| 영역 | 데스크톱 | 확장 (참고) |
|------|----------|-------------|
| 셀렉터 후보 | `capture_dom._build_subtitle_selector_candidates` | `src/shared/constants.ts` |
| row / 화자 | `capture_dom` probe JS | `src/content/subtitle-rows.ts` |
| 레이어 활성 | `capture_observer._activate_subtitle` | `src/content/subtitle-layer.ts` |
| 파이프라인 | `core/subtitle_pipeline*` | `src/core/subtitle-pipeline/` |
| URL 정책 | `core/url_policy.py` | `isSupportedAssembly*Url` |

---

## 7. 요약

- **상호 코드 의존 없음**, **사이트 계약·수집 의미론은 공유**.
- 버그/사이트 변경 시 **형제 저장소를 대조**하는 운영 의존이 있다.
- 2026-08-10 기준 수집 P1(A/B) 정합 반영. 스키마·UI 전면 동기화는 하지 않는다.
