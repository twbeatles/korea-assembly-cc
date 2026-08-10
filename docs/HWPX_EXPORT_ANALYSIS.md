# HWPX 내보내기 구조 분석 — 스키마 전면 개편 필요성

업데이트: `2026-08-10`  
대상 구현: `core/hwpx_export.py`, `assets/hwpx/header.xml`, `ui/main_window_impl/persistence_exports.py` (`_save_hwpx` / HWP 폴백)

---

## 1. 결론

**HWPX 스키마 전면 개편은 필요하지 않다.**

본 앱의 HWPX는 “한컴 미설치 환경에서도 자막을 한글로 열 수 있는 **최소 유효 문서**”를 만드는 것이 목적이다.  
KS X 6101 전체를 구현한 범용 워드 엔진이 아니며, 현재 패키지 골격은 그 목적에 충분하다.

전면 개편을 검토할 시점은 아래 **차단 신호**가 반복 재현될 때뿐이다.

- 한컴/주요 뷰어에서 “손상된 파일”·열기 실패
- 초대형 세션(수만 문단)에서 메모리·열기 실패 → section 분할 필요
- 공공 제출용 스키마 검증 도구 통과 요구
- 표·머리말·이미지 등 고급 서식 export 요구

---

## 2. 현재 패키지 구조

ZIP 내부 (구현 기준):

```text
mimetype                    # application/hwp+zip, 첫 엔트리, 무압축(ZIP_STORED)
version.xml
Contents/
  header.xml                # assets/hwpx/header.xml 템플릿 (폰트·글자/문단 속성·스타일)
  section0.xml              # 본문 hs:sec / hp:p / hp:run / hp:t
  content.hpf               # OPF metadata + manifest + spine
settings.xml
Preview/PrvText.txt
META-INF/
  container.xml
  manifest.xml
```

### 설계 의도

| 항목 | 정책 |
|------|------|
| 첫 문단 | `secPr`(용지/여백) + 빈 `hp:t` + `linesegarray` 1회 |
| 본문 문단 | `paraPrIDRef`/`charPrIDRef`로 헤더 스타일 참조, **동적 linesegarray 생략** (한글이 재계산) |
| 엔트리 개행 | 한 `SubtitleEntry` = 한 문단, 내부 `\n` → `hp:lineBreak` |
| 타임스탬프 | 60초 간격 표시 (TXT/DOCX 표시 정책과 유사) |
| 안전성 | XML 금지 제어문자 제거, 빈 텍스트 skip, `atomic_write_bytes` |

---

## 3. 전면 개편이 의미하는 범위 (과잉)

- KS/HWPML XSD 전수 준수 검증
- 표·그림·머리말/바닥글·각주·필드·다단
- 다구역(`section1.xml`…), 스타일 동적 생성
- `BinData/`, `PrvImage.png`, DRM
- 줄 단위 `linesegarray` 정밀 계산

자막 목록 export 요구와 불일치하며 유지비 대비 이득이 작다.

---

## 4. 전면 개편 대신 유지·선택 개선

**이미 반영 (export hardening, 2026-08)**

- 제어문자 sanitize (`core/export_text.py` + `hwpx_export`)
- 빈 엔트리 skip
- header 템플릿 부재 시 명확한 오류
- HWP 경로: smart filename, multiline `\r\n`, InsertText 전 GetDefault, pywin32 없으면 HWPX 폴백

**선택 (이슈 관측 시)**

| 우선순위 | 항목 |
|----------|------|
| 낮음 | 탐색기 미리보기용 `PrvImage.png` |
| 낮음 | 제목/타임스탬프용 charPr 분리 (가독성 UX) |
| 중간 | 문단 수 임계 시 section 분할 (초대형 세션) |
| 관측 | 한컴 2018/2020/2022 실기 open 스모크 |

---

## 5. 관련 테스트·코드

| 경로 | 역할 |
|------|------|
| `core/hwpx_export.py` | 패키지 생성 |
| `core/export_text.py` | 공통 sanitize / cue time (SRT·VTT 등과 공유) |
| `assets/hwpx/header.xml` | 스타일 SoT 템플릿 |
| `tests/test_hwpx_export.py` | 패키지·escape·multiline·제어문자 |
| `tests/test_export_hardening.py` | SRT/VTT/HWP/HWPX export 견고성 |
| `tests/test_review_20260323_regressions.py` | HWPX/HWP UI 경로 smoke |

---

## 6. 요약 한 줄

**현재 HWPX는 자막 export용 최소 유효 패키지로 유지하고, 스키마 전면 개편은 하지 않는다. 호환 사고·대용량·고급 서식 요구가 쌓이면 재검토한다.**
