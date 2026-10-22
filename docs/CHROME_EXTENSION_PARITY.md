# 데스크톱 ↔ Chrome 확장 상호 의존·정합

업데이트: `2026-10-22` (공유 계약 `parity/` 도입, 수집 알고리즘 정합 2차)

이 문서는 **국회 의사중계 자막 추출기(데스크톱, 본 저장소)** 와  
**[korea-assembly-cc-chrome](https://github.com/twbeatles/korea-assembly-cc-chrome) (Chrome Extension)** 사이의  
**공유 계약·의도적 분기·이식 정책**을 정리한다.

두 제품은 **같은 국회 중계 사이트 DOM/URL 계약**을 소비하지만,  
코드베이스를 공유하지 않으며 **플랫폼이 다른 형제 제품**이다.

---

## 1. 제품 관계

| 항목 | 데스크톱 (`korea-assembly-cc`) | Chrome 확장 (`korea-assembly-cc-chrome`) |
|------|-------------------------------|------------------------------------------|
| 런타임 | PySide6 + Selenium (별도 Chrome 프로세스) | Manifest V3 content script (페이지 안) |
| 수집 | MutationObserver 주입 + structured probe (execute_script) | page-world observer + DOM probe (직접 접근) |
| 저장 | SQLite + JSON session + runtime segment archive | IndexedDB (+ storage fallback) |
| 내보내기 | TXT/SRT/VTT/DOCX/**HWPX**/HWP/RTF | TXT/SRT/VTT/JSON/MD/CSV |
| 파이프라인 코어 | `core/subtitle_pipeline*` + `PIPELINE_LOCK.md` | `src/core/subtitle-pipeline/` (동일 의미론 이식) |

**의존 방향**

- **사이트 → 양쪽**: DOM 셀렉터·화자색·URL/xcode 계약은 **사이트가 단일 진실 원천**.
- **양쪽 간 코드 의존**: 없음 (서브모듈·공통 패키지 없음).
- **계약 의존 (2026-10-22~)**: 두 저장소의 `parity/` 폴더에 같은 내용의
  `capture-contract.json`(사이트·DOM·상수·의도적 차이)과 `pipeline-vectors.json`(순수 함수 벡터)을 두고,
  각자 테스트(`tests/test_parity_contract.py` ↔ 확장 `tests/parity-contract.test.ts`)로 구현을 대조한다.
  사본 일치는 `python scripts/check_parity_sync.py`(pre-push `check_before_push.py`에 포함) /
  확장 `npm run check:parity` 가 검사하며, 형제 저장소가 옆 폴더에 없으면 건너뛴다.
- **지식 의존**: 수집 버그/사이트 변경 대응 시 **서로 문서·로직을 대조**하는 것이 권장된다.
  - 확장 측 사이트 점검·정합 문서: `SITE_COMPATIBILITY_REVIEW_2026-09-17.md`, `DESKTOP_PARITY.md` (확장 저장소)
  - 데스크톱 측 고정: `PIPELINE_LOCK.md`, 본 문서

---

## 2. 공유해야 하는 계약 (사이트/수집)

아래는 **양쪽이 맞춰 두어야 하는 계약**이다. 한쪽만 바꾸면 수집 품질이 어긋난다.

### 2.1 URL / 호스트

- 주 호스트: `assembly.webcast.go.kr`
- 보조 호스트: `webcast.assembly.go.kr`는 2026-09 기준 DNS 실패. 데스크톱 `url_policy`는 `assembly.webcast.go.kr` 계열만 허용한다.
- 플레이어: `/main/player*`, 기자회견: `/main/pressplayer*`
- 본회의: `xcode=10` 또는 `xcgcd` prefix `DCM000010…`
- 청문회/공청회: live_list `xcode=97` (구 `99`는 레거시 호환)
- 기후노동위 공식명: `기후에너지환경노동위원회` (xcode `62`, 약칭 `기후노동위`)

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
| P1-B | AI 자막 버튼 우선 + **ON(active)이면 재클릭 안 함** (끄기/토글 OFF 방지), `layerSubtit` 후에도 AI active 재확인 | `ui/main_window_impl/capture_observer.py` |
| P1-A | 한 `.smi_word` 안 다중 화자 span 분할 (`#segarr_*`) | `ui/main_window_impl/capture_dom.py` probe JS · `core/subtitle_row_split.py` 미러 |

회귀: `tests/test_capture_chrome_parity_p1.py`, `tests/test_subtitle_row_split.py`

### 의도적으로 이식하지 않은 것 (2026-10-22 갱신)

| 항목 | 이유 |
|------|------|
| 확장 panel / history 편집 / IDB | 플랫폼 전용 |
| `mergeMaxChars` 1000 vs 데스크톱 300 | 제품 정책 상수 (`parity/capture-contract.json` `intentionalDifferences`) |
| 사용자 지정 셀렉터 우선순위 | 데스크톱만 입력 UI 가 있어 `.smi_word` 다음·container 앞에 둔다 |
| 중지 시 preview 확정 | 데스크톱 정책(PIPELINE_LOCK §4.6). 확장은 committed 만 저장 |
| Observer structured 전면 재작성 | probe SoT 유지로 충분 |
| 확장 export(MD/CSV) | 데스크톱은 HWPX/HWP 등 별도 경로 |

> 2026-08-10 당시 P2로 미뤘던 unconfirmed fallback streak·배경 이미지 샘플링은 2026-10-22에 이식했다 (§4.1).

---

## 4.1 정합 작업 이력 (2026-10-22)

사이트 실측(국정감사 기간, `openos_util.js` v=20261020)과 양쪽 코드 줄 단위 대조 결과.
상세 표는 확장 저장소 `DESKTOP_PARITY.md` §3 과 같다.

**사이트 실측 요점**

- AI 자막: `p.smi_word.stxt{seg} > span#segarr_{seg}_{n}`, 미확정 `background:#cfe5f7`, 화자색 `#1e1e1e`/`#237c93` — 기존 계약 유지.
- AI 자막(화자분리 없음): 최신 줄 span 에 `background:rgba(54,160,255,0.2)` (다음 segment 전까지 미확정).
- 일반 자막(본회의 smi-dw): `p.smi_word` 에 stxt 클래스·id 가 없음 → **unstable row**.
- `#viewSubtit > #smiLoading .loadingmsg` 에 `로딩중..` 문구가 있어 `#viewSubtit` container fallback 이 읽을 수 있음.

**데스크톱 수정**

| ID | 내용 | 위치 |
|----|------|------|
| D1 | `clean_text_display`/`clean_text` 가 `\b\d{4}년\b` 를 본문에서 지우던 동작 제거 (데이터 손실) | `core/text_utils.py` |
| D2 | placeholder(`로딩중..`, `Loading...`) commit 차단 | `core/text_utils.py` `is_placeholder_subtitle_text` |
| D3 | 미확정 판정: 배경 이미지 포함, 텍스트 노드 우선 96개 샘플 + 마지막 노드 | `capture_dom` probe JS, 미러 `core/subtitle_confirmation.py` |
| D4 | container fallback 차단 조건 확장 + 연속 6회 차단 시 일시 허용 streak | `capture_dom` probe JS + `_read_subtitle_probe_by_selectors` |
| D5 | stable key row 만 commit, unstable-only snapshot 은 fallback 경로 | `pipeline_state._apply_structured_preview_payload` |
| D6 | fallback 안정 관측 게이트(같은 raw 2회 또는 400ms) | `pipeline_state._observe_fallback_commit_candidate`, keepalive 재관측 집계 |
| D7 | 기본 셀렉터 순서를 확장과 동일하게 (`#viewSubtit span` 을 container 뒤로) | `capture_dom._build_subtitle_selector_candidates` |
| D8 | container 내부 raw 4KB tail(본회의 전체), UI preview 만 400자 축약 | probe JS `normalizeContainerText`, `utils.format_fallback_preview_text` |
| D9 | 코어 결합 문장부호에 `” ’ … “ ‘` 추가 | `core/subtitle_pipeline_impl/entries.py` |
| M1–M4, K1 | 병합 경계(알려진 channel 만, fallback 경계, fallback gap ×0.4), `speaker_changed` 설정, keepalive 접미 규칙 — **확장과 같은 순수 함수** | `core/subtitle_pipeline_impl/entry_policy.py` |

확장 쪽도 M1–M3·K1 을 같은 규칙으로 바꿨다(`src/core/subtitle-pipeline/entry-policy.ts`).

회귀: `tests/test_parity_contract.py` (계약 + 공유 벡터), `tests/test_pipeline_risk_hardening.py` (container 안정 관측).

---

## 5. 사이트 변경 대응 절차

1. 가능하면 **확장 저장소**에서 오프라인/라이브 호환 검토 문서를 먼저 갱신한다.
2. 셀렉터·화자색·버튼·URL 계약이 바뀌면 **`parity/capture-contract.json` 을 먼저 고치고** 양쪽 모두 수정한다.
   수집 의미론 변경은 `parity/pipeline-vectors.json` 에 벡터를 추가해 양쪽 테스트로 고정한 뒤
   `python scripts/check_parity_sync.py --write` 로 사본을 맞춘다.
3. 데스크톱은 probe JS + 활성화 스크립트 + (필요 시) `Config` 프리셋/`url_policy`/`committee_catalog` 를 본다.
4. 파이프라인 suffix 의미론 변경은 **최후 수단**이며 `PIPELINE_LOCK.md` 필수.

---

## 6. 관련 경로

| 영역 | 데스크톱 | 확장 (참고) |
|------|----------|-------------|
| 공유 계약/벡터 | `parity/`, `tests/test_parity_contract.py` | `parity/`, `tests/parity-contract.test.ts` |
| 셀렉터 후보 | `capture_dom._build_subtitle_selector_candidates` | `src/shared/constants.ts`, `src/content/dom-probe.ts` |
| 병합/keepalive 정책 | `core/subtitle_pipeline_impl/entry_policy.py` | `src/core/subtitle-pipeline/entry-policy.ts` |
| 미확정 판정 | `capture_dom` probe JS, `core/subtitle_confirmation.py` | `src/content/subtitle-rows.ts`, `src/content/unconfirmed-fallback.ts` |
| fallback 안정 관측 | `pipeline_state._observe_fallback_commit_candidate` | `runtime-core/fallback-commit.ts` |
| row / 화자 | `capture_dom` probe JS | `src/content/subtitle-rows.ts` |
| 레이어 활성 | `capture_observer._activate_subtitle` | `src/content/subtitle-layer.ts` |
| 파이프라인 | `core/subtitle_pipeline*` | `src/core/subtitle-pipeline/` |
| URL 정책 | `core/url_policy.py` | `isSupportedAssembly*Url` |
| 위원회 xcode/명칭 | `core/committee_catalog.py`, `core/config.py` | 확장 측 위원회 상수 |

---

## 7. 요약

- **상호 코드 의존 없음**, **사이트 계약·수집 의미론은 공유**.
- 버그/사이트 변경 시 **형제 저장소를 대조**하는 운영 의존이 있다.
- 2026-08-10 기준 수집 P1(A/B), 2026-10-22 기준 수집 2차(D1–D9, M1–M4, K1) 정합 반영.
- 2026-10-22부터 `parity/` 공유 계약·벡터로 두 구현을 기계적으로 대조한다. 스키마·UI 전면 동기화는 하지 않는다.
