# parity/ — 데스크톱 ↔ Chrome 확장 수집 알고리즘 공유 계약

이 폴더는 두 저장소에 **내용이 같은 사본**으로 존재합니다 (줄바꿈 CRLF/LF 차이는 동기화 검사에서 무시).

| 저장소                                                    | 경로      |
| --------------------------------------------------------- | --------- |
| 데스크톱 `korea-assembly-cc` (PySide6 + Selenium)         | `parity/` |
| Chrome 확장 `korea-assembly-cc-chrome` (MV3 + TypeScript) | `parity/` |

두 제품은 코드를 공유하지 않지만 같은 국회 의사중계 사이트 DOM을 읽고 같은 자막 파이프라인 의미론(글로벌 history + suffix `rfind`)을 씁니다. 이 폴더가 그 공통분모를 기계적으로 고정합니다.

## 파일

| 파일                    | 내용                                                                                                               | 각 저장소의 검증 테스트                                                           |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| `capture-contract.json` | 사이트 호스트·DOM 셀렉터·화자색·미확정 판정·placeholder·파이프라인 상수, 의도적 차이 목록                          | Chrome `tests/parity-contract.test.ts` / 데스크톱 `tests/test_parity_contract.py` |
| `pipeline-vectors.json` | 순수 함수 입력→기대값 벡터 (정규화, 증분 추출, 결합, commit 가능 판정, 병합, keepalive, 미확정 하이라이트, 샘플링) | 같은 테스트 파일                                                                  |
| `README.md`             | 이 문서                                                                                                            | —                                                                                 |

각 저장소의 테스트는 **자기 구현 상수/함수가 이 파일과 같은 값을 내는지** 검사합니다. 따라서 한쪽만 바꾸면 그쪽 테스트가 깨지거나, 사본이 달라져 동기화 검사가 실패합니다.

## 동기화 검사

형제 저장소가 옆 폴더(`../korea-assembly-cc`, `../korea-assembly-cc-chrome`)에 있거나 환경 변수로 경로를 주면 두 사본을 비교합니다. 형제 저장소가 없으면(CI 등) 건너뜁니다.

```bash
# Chrome 확장 저장소에서
npm run check:parity            # KOREA_ASSEMBLY_CC_DIR 로 데스크톱 경로 지정 가능

# 데스크톱 저장소에서
python scripts/check_parity_sync.py   # KOREA_ASSEMBLY_CC_CHROME_DIR 로 확장 경로 지정 가능
```

## 변경 절차

1. 사이트 실측 또는 버그로 수집 의미론을 바꿔야 하면, 먼저 이 폴더의 계약/벡터를 고친다.
2. 두 저장소 구현을 모두 고치고 각자의 parity 테스트를 통과시킨다.
3. 수정한 `parity/` 파일을 다른 저장소에 그대로 복사한다 (`check:parity` / `check_parity_sync.py --write` 로 확인).
4. 데스크톱 코어 의미론 변경이면 데스크톱 `PIPELINE_LOCK.md` §2.1 이력을 남긴다.
5. 의도적으로 다르게 두는 항목은 `capture-contract.json` 의 `intentionalDifferences` 에 이유와 함께 적는다.

자세한 대조 결과와 이력은 Chrome 저장소 `DESKTOP_PARITY.md`, 데스크톱 저장소 `docs/CHROME_EXTENSION_PARITY.md` 를 본다.
