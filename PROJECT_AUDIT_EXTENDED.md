# Project Audit — Extended Scopes

> **감사 일자**: 2026-07-29  
> **대상 버전**: v16.14.8  
> **선행 문서**: [`PROJECT_AUDIT.md`](PROJECT_AUDIT.md) (기능 구현 관점)  
> **본 문서 범위**: 기능 구현 **이외** — 보안·프라이버시, 동시성·라이프사이클, 성능·리소스, 아키텍처·유지보수, 테스트·품질 게이트, 패키징·운영  
> **방법**: README/CLAUDE + CodeGraph MCP 우선 → 필요 시 grep/파일 열람.  
> **후속 구현**: 2026-07-29 — 1~2단계 + 3단계 안전 항목 반영 (`tests/test_project_audit_extended_20260729.py`, `.github/workflows/ci.yml`, `docs/RELEASE_CHECKLIST.md`).  
>   - 저장소 암호화·접근성 전면·star import 일괄 제거·코드 서명 인프라는 보류.  
> **검증 기준선 (후속 후)**: `pytest -q` **332 passed / 2 skipped**, `pyright` **0 errors**

---

## 1. Executive Summary

기능 감사(`PROJECT_AUDIT.md`) 이후에도 이 코드베이스는 **로컬 Windows 데스크톱 + Selenium + SQLite** 특성상 위험 모델이 비교적 좁다.  
다만 **국회 생중계 자막(정치·정책 발화)** 을 장시간 디스크에 쌓는 앱이므로, 보안 점수와 별개로 **프라이버시·보존·디스크/메모리** 관점의 리스크가 더 실무적이다.

| 범위 | 전체 위험도 | 한 줄 요약 |
|------|-------------|------------|
| **보안 (공격면)** | **Low** | host/selector/SQL/path 가드, 원격 서버 없음 |
| **프라이버시·데이터 보존** | **Medium** | 자막·로그·DB 평문 저장, 암호화/보존 정책 UI 약함 |
| **동시성·라이프사이클** | **Low–Medium** | 큐/락/run_id 성숙, 종료·driver orphan·processEvents 재진입 잔존 |
| **성능·리소스** | **Low–Medium** | tail/archive/render 상한 있음, hydrate·clone·장시간 I/O 비용 |
| **아키텍처·유지보수** | **Medium** | facade/mixin 분리는 성공, 계약 약함·파일 수 과다 |
| **테스트·품질 게이트** | **Low–Medium** | 단위/회귀 풍부, Chrome E2E·CI 매트릭스 부재 |
| **패키징·운영** | **Low** | PyInstaller/portable/preflight 견고, 서명·자동 업데이트 없음 |

**기능 감사와 겹치지 않는 핵심 메시지**

1. 원격 공격면은 작지만, **로컬에 쌓이는 발화 데이터·로그**가 실질 자산이다.  
2. 종료 경로에서 **Chrome 프로세스 잔존**과 **`processEvents` 재진입**은 운영 이슈로 남을 수 있다.  
3. 장시간 세션은 메모리 설계가 좋지만, **편집/hydrate 시 full materialization** 비용이 남는다.  
4. 품질 게이트는 로컬 중심이며 **저장소 CI(`.github`) 부재**가 협업/회귀 자동화를 제한한다.

---

## 2. Scope Map (기능 감사와의 관계)

| 문서 | 초점 |
|------|------|
| `PROJECT_AUDIT.md` | 기능 결함, 입력 검증, 상태 흐름, 파이프라인 정확성, 테스트 제안(기능) |
| **본 문서** | 보안/프라이버시, 스레드·종료, 성능, 구조 부채, 테스트 전략, 배포 운영 |

기능 감사에서 이미 다룬 항목(suffix 한계, overflow drop, URL path allowlist 등)은 **중복 서술하지 않고 참조만** 한다.

---

## 3. Security & Privacy

### 3.1 공격면 요약

| 경로 | 평가 | 근거 |
|------|------|------|
| 네트워크 | 국회 의사중계 host로 제한된 HTTP(S) | `validate_assembly_url` |
| DOM 자동화 | Selenium `execute_script` — selector는 **인자 전달** | `capture_observer._inject_mutation_observer_here` |
| SQL | 파라미터 바인딩 + LIKE escape | `DatabaseSearchStatsMixin.search_subtitles` |
| 파일 경로 | runtime relative path root 이탈 차단 | `_resolve_runtime_relative_path` |
| 코드 실행 | 앱 런타임에 `shell=True`/`pickle`/`eval` 없음 | scripts/tests 의 `subprocess`만 개발용 |
| 시크릿 | API 키·패스워드 저장 경로 없음 | 공개 사이트 스크래핑 앱 |

**우선순위 관점**: 원격 RCE/SQLi 수준의 Critical은 확인되지 않음.

### 3.2 이슈 — 로컬 데이터 평문 보존 (프라이버시)

* **위치**: `Config.DATABASE_PATH`, `sessions/`, `backups/`, `realtime_output/`, `logs/subtitle.log`  
  (`resolve_storage_resolution` → development / portable / `%LOCALAPPDATA%`)
* **문제**: 세션 JSON·SQLite·실시간 TXT·로그가 **평문**이다. 디스크 접근 권한만 있으면 과거 생중계 자막 전문 열람 가능.
* **영향**: 공유 PC, portable USB, 백업 동기화(OneDrive 등) 시 **정치 발화 기록 유출** 가능. 법적 “기밀”보다 평판·운영 리스크.
* **근거**: DB `save_session` 텍스트 저장, `atomic_write_json_stream`, `TimedRotatingFileHandler(encoding=utf-8)`, realtime `utf-8-sig` open.
* **권장**:  
  1. 설정에 “로그에 자막 전문 기록 안 함” / 보존 일수 UI  
  2. portable 모드 사용 시 저장소 민감성 안내  
  3. (선택) OS DPAPI 기반 DB 암호화 — 비용 큼, 우선순위 낮음
* **우선순위**: **Medium** (보안 점수보다 데이터 거버넌스)

### 3.3 이슈 — 로그 민감 정보 노출 가능성

* **위치**: `core/logging_utils.py` (DEBUG 파일 로그), capture/pipeline `logger.info/warning`
* **문제**: 파일 로그는 DEBUG, 보존 `LOG_RETENTION_DAYS`(기본 14일). URL·에러 메시지·일부 자막 관련 문자열이 남을 수 있음.
* **영향**: 지원 목적 로그 공유 시 불필요 정보 유출.
* **권장**: 운영 기본 레벨 INFO, 자막 본문 로깅 금지 정책, 로그 마스킹 가이드.
* **우선순위**: **Low–Medium**

### 3.4 이슈 — Chrome 프로필/프로세스 잔존

* **위치**: `capture_browser._build_chrome_options` — 커스텀 `user-data-dir` 없음(Selenium 기본 temp 프로필 의존)  
  `_force_quit_driver_with_timeout` — daemon quit thread + 타임아웃 시 포기
* **문제**: quit 타임아웃(2s) 후 **chromedriver/chrome 잔존** 가능. 장시간 사용·강제 종료 시 좀비 프로세스 누적 **추정**.
* **영향**: 메모리/핸들 누수, 다음 시작 지연. 보안상 프로필 잔존보다는 운영 이슈에 가깝다.
* **권장**: 타임아웃 시 PID 추적 정리(Windows taskkill 신중), 종료 진단에 chrome 프로세스 수 기록.
* **우선순위**: **Low–Medium**

### 3.5 이슈 — URL path allowlist 부재 (기능 감사 §3.6 참조)

* host만 제한, path/query 자유. 로컬 사용자 입력 공격면. **Low** 유지.

### 3.6 보안 강점

- selector 문자 화이트리스트 (`selector_policy`)
- runtime path traversal 회귀 테스트 존재
- DB degraded mode (FTS 실패 시 앱 전체 크래시 회피)
- storage preflight (쓰기 불가 시 UI 조립 전 중단)

---

## 4. Concurrency & Lifecycle

### 4.1 모델 요약

```
UI thread (Qt)
  ├─ QTimer: queue / stats / backup / detached cleanup
  ├─ message_queue (worker, run_id envelope, max 500)
  ├─ app_control_queue (control plane, max 200)
  └─ locks: subtitle_lock, _driver_lock, overflow/terminal locks, DB RLock

ExtractionWorker (non-daemon)
  └─ Selenium driver + stop_event

Background threads (save/export/flush/hydrate/DBWorker)
  └─ registry + shutdown gate
```

### 4.2 이슈 — 종료 대기 중 `processEvents` 재진입

* **위치**: `runtime_lifecycle._wait_for_background_threads_during_exit`  
  `app.processEvents()` + `_process_message_queue()` 루프
* **문제**: 종료 대기 중 Qt 이벤트를 펌핑하므로, **모달/타이머/슬롯이 재진입**할 수 있다. 의도(UI 응답성)와 트레이드오프.
* **영향**: 드물게 종료 중 추가 액션·이중 저장 시도. 기존 dirty deferred와 결합 시 복잡도 증가.
* **근거**: L764–772 부근 while 루프.
* **권장**: 종료 중 `_exit_in_progress` 플래그로 사용자 액션 전면 차단(이미 상당 부분 존재하는지 점검 후 보강), processEvents 범위를 최소화.
* **우선순위**: **Medium**

### 4.3 이슈 — ExtractionWorker 종료 타임아웃 후 orphan

* **위치**: `_stop` → `_wait_worker_shutdown(THREAD_STOP_TIMEOUT=3)`  
  실패 시 경고 후 계속, `self.worker = None`
* **문제**: 스레드 참조를 버려도 **OS 스레드는 살아 있을 수 있음**. driver 강제 quit으로 대부분 풀리지만, 네트워크 블로킹 시 지연 가능.
* **영향**: 재시작 직후 이중 Chrome, 리소스 경합.
* **권장**: 살아 있는 worker 재join 상한, 진단 JSON에 worker ident 기록(shutdown diagnostic과 연계).
* **우선순위**: **Low–Medium**

### 4.4 이슈 — Hydrate 워커가 세그먼트를 백그라운드에서 읽어 UI에 대량 전달

* **위치**: `persistence_runtime_hydration._run_after_full_session_hydrated`  
  `hydrate_done` payload에 `full_entries` 리스트
* **문제**: control 메시지로 **전체 엔트리 객체를 큐에 실어 UI 스레드로 전달**. 초장시간 세션에서 피크 메모리 2× 가능(아카이브 + full list).
* **영향**: 수십만 엔트리 시 OOM·UI 멈춤 **추정**(일반 위원회 세션에서는 드묾).
* **권장**: 파일 경로/토큰만 전달 후 UI에서 스트리밍 적용, 또는 청크 hydrate.
* **우선순위**: **Medium** (장시간 편집 UX 한정)

### 4.5 동시성 강점

- `run_id` envelope + stale drop  
- worker/control 큐 분리  
- terminal/overflow stash  
- DB single worker 직렬화 + RLock  
- segment flush `archive_token`/`run_id` stale-drop  
- stop 중 finished/error 멱등  
- background shutdown 시 신규 스레드 거부

### 4.6 추정 (미확정)

- **추정**: `is_running` / 일부 플래그는 UI 스레드 가정이지만 worker가 읽는 경로가 있어 가시성 이슈 가능(CPython GIL로 완화).  
- **추정**: `keep_browser_on_stop` + 즉시 재시작 시 driver handoff 레이스 잔존 가능.

---

## 5. Performance & Resources

### 5.1 의도된 상한 (Config)

| 상수 | 값 | 역할 |
|------|-----|------|
| `MESSAGE_QUEUE_MAX_SIZE` | 500 | worker 백프레셔 |
| `OVERFLOW_PASSTHROUGH_MAX` | 128 | 포화 시 보존 한도 |
| `MAX_RENDER_ENTRIES` | 500 | QTextEdit 렌더 창 |
| `RUNTIME_ACTIVE_TAIL_ENTRIES` | 1000 | 메모리 tail |
| `RUNTIME_SEGMENT_FLUSH_THRESHOLD` | 2000 | segment flush 트리거 |
| `CONFIRMED_COMPACT_MAX_LEN` | 50000 | compact 히스토리 상한 |
| queue drain | ≈8ms / 50건 | UI 스톨 방지 |
| segment entry cache | 최근 3개 | LRU |

### 5.2 이슈 — 렌더는 윈도우지만 clone/스냅샷 비용

* **위치**: `_render_subtitles`, `_build_persistent_entries_snapshot`, segment flush 시 `entry.clone()` 일괄
* **문제**: 저장/백업/flush마다 엔트리 clone. 정확성(동시 수정 격리)을 위한 대가.
* **영향**: 장시간 + 자동 백업 주기에서 CPU/할당 스파이크.
* **권장**: 이미 streaming export 경로 존재 — 백업도 iterator 경로 비중 유지, flush clone 배치 프로파일.
* **우선순위**: **Low**

### 5.3 이슈 — full-session 검색 매치 상한

* **위치**: `RUNTIME_SEARCH_MATCH_LIMIT = 5000`
* **문제**: 매우 흔한 검색어는 결과 절단. UX상 “더 있음” 표시 여부는 구현 의존.
* **영향**: 사용자 오해(결과 전부로 착각).
* **권장**: UI에 “상위 N건” 명시.
* **우선순위**: **Low**

### 5.4 이슈 — FTS rebuild 샘플 프로브

* **위치**: `database_impl/fts._fts_sample_index_missing` — 최근 20행 MATCH 프로브
* **문제**: 대규모 DB 시작 시 rebuild 판정이 무거울 수 있음. 조건부로만 rebuild — 양호.
* **영향**: 콜드 스타트 지연 **추정**.
* **우선순위**: **Low**

### 5.5 성능 강점

- tail patch 렌더, coalesced UI refresh  
- confirmed_segments 증분 경로 (파이프라인 v2)  
- streaming JSON/export  
- 큐 시간 예산 + follow-up drain  
- 통계 캐시(`_cached_total_chars` 등)

---

## 6. Architecture & Maintainability

### 6.1 구조 평가

| 항목 | 평가 |
|------|------|
| 엔트리포인트 / Config / storage | 명확 |
| facade + `main_window_impl/*` 분리 | 운영 성숙, 파일 수 많음 |
| core pipeline / live_capture facade | PIPELINE_LOCK과 정합 |
| Protocol 계약 | 공개 `MainWindowHost`는 두껍고, impl `contracts`는 의도적으로 얇음 |
| 호환 shim (`database.py`, `core/utils.py`) | 테스트/import 안정 |

### 6.2 이슈 — Mixin 조합 복잡도 (인지 부하)

* **위치**: `ui/main_window.py` 다중 mixin, `main_window_impl/` 30+ 파일
* **문제**: “어느 파일이 진실인가” 탐색 비용. CodeGraph 없으면 온보딩 어려움.
* **영향**: 수정 시 잘못된 레이어 패치, 중복 로직 위험.
* **권장**: 모듈 인덱스(기존 CLAUDE 구조 표 유지), 공개 API 표면 문서화, 신규 기능은 facade 확장 금지.
* **우선순위**: **Medium** (기술 부채, 장애 아님)

### 6.3 이슈 — star import

* **위치**: 일부 `persistence_runtime_*.py` 등 `from ui.main_window_common import *`
* **문제**: 심볼 출처 불명확, 정적 분석·리팩터 방해.
* **권장**: 점진적 명시 import (대규모 일괄 변경은 회귀 비용 큼).
* **우선순위**: **Low**

### 6.4 이슈 — 버전/문서 수치 혼재

* **위치**: CLAUDE.md 중간 절 과거 pytest 수치
* **문제**: 에이전트/개발자가 구 기준선 오인. 기능 감사에서도 지적.
* **권장**: “Current Baseline” 단일 표 + 역사는 CHANGELOG만.
* **우선순위**: **Low**

### 6.5 아키텍처 강점

- 도메인 경계(capture / pipeline / persistence / database / view) 실존  
- 회귀 테스트가 리팩터를 뒷받침  
- 파이프라인 의미론 잠금 문서(`PIPELINE_LOCK.md`)

---

## 7. Testing & Quality Gates

### 7.1 현황

| 항목 | 수치/상태 |
|------|-----------|
| 테스트 파일 | 약 43개 (`tests/test_*.py`) |
| 최근 기준선 | 321 passed / 2 skipped |
| 정적 분석 | pyright 0 errors, suppression policy 테스트 |
| 인코딩 | UTF-8 without BOM 검사 |
| 릴리스 스크립트 | `scripts/run_release_verification.py` |
| Live smoke | opt-in `RUN_LIVE_SMOKE=1` |
| CI | **리포에 `.github` 없음** |

### 7.2 이슈 — CI 부재

* **문제**: 푸시/PR 자동 게이트 없음. 로컬/수동 `run_release_verification`에 의존.
* **영향**: 협업·포크 시 회귀 유입.
* **권장**: GitHub Actions: `pytest -q` + `pyright` + smoke (Windows runner 또는 가능한 범위).  
  빌드/Live는 nightly 또는 manual.
* **우선순위**: **Medium**

### 7.3 이슈 — “no covering tests found” (CodeGraph 관점)

* CodeGraph blast radius가 여러 mixin 메서드에 **직접 단위 테스트 없음**을 표시.  
  간접 통합 테스트로 커버되는 경우가 많음.
* **권장**: 변경 빈도가 높은 경로(lifecycle start/stop, hydrate, DB worker)만 단위 테스트 밀도 유지 — 이미 다수 존재.
* **우선순위**: **Low** (현황 기술)

### 7.4 이슈 — Chrome/Selenium E2E 부재

* 기능 감사와 동일. DOM 실사이트 변동에 취약.
* **권장**: FakeCaptureProbe 확장 → 레코딩 픽스처 재생 테스트.
* **우선순위**: **Medium** (장기)

### 7.5 강점

- plan 단위 회귀 파일 축적 (`test_*_plan_*.py`, `test_project_audit_*.py`)  
- subprocess 샌드박스 fallback  
- encoding / pyright policy 자동 검증

---

## 8. Packaging & Operations

### 8.1 강점

- `subtitle_extractor.spec` hidden import 광범위, 불필요 Qt 모듈 exclude  
- portable.flag vs LOCALAPPDATA 저장소 분리  
- storage preflight + smoke CLI (`--smoke`, `--smoke-storage-preflight`, `--smoke-instantiate-window`)  
- live-list drift 스크립트

### 8.2 이슈 — 코드 서명·자동 업데이트 없음

* **문제**: Windows SmartScreen, 배포 신뢰. 자동 패치 경로 없음.
* **영향**: 기관 배포 시 마찰, 구버전 잔존.
* **권장**: 릴리스 체크리스트에 서명, 버전 고지 URL(선택).
* **우선순위**: **Low** (제품 정책)

### 8.3 이슈 — 런타임 세션 디스크 성장

* **위치**: `backups/runtime_sessions/`, 5분 백업 `MAX_BACKUP_COUNT=10`
* **문제**: 비정상 종료 후 runtime root 잔존 시 디스크 사용. 정상 종료는 `remove_files=True`로 정리.
* **권장**: 시작 시 orphan runtime 디렉터리 정리(보존 기간 N일).
* **우선순위**: **Low–Medium**

### 8.4 이슈 — 플랫폼 단일성

* README Platform=Windows, HWP/pywin32/LOCALAPPDATA.
* **추정**: Linux/macOS는 비지원. 문서에 “Windows 전용” 고정 권장.

---

## 9. UX / Accessibility (경량)

> UI 전문 감사가 아닌, 코드에서 보이는 운영 UX만.

| 항목 | 관찰 |
|------|------|
| 테마 | 토큰 기반 다크/라이트 |
| 트레이 | 추출 중 최소화 vs 종료 분기 명확 |
| 접근성 | 스크린리더/고대비 전용 경로 미확인 — **추정: 기본 Qt 위젯 수준** |
| 오류 메시지 | 한국어 toast/status 풍부 |
| 검색 결과 절단 | §5.3 |

* **우선순위**: 접근성 본격 개선은 **Low** (제품 우선순위 따름)

---

## 10. Cross-Cutting Risk Matrix

| ID | 범위 | 요약 | 우선순위 |
|----|------|------|----------|
| E1 | 프라이버시 | 자막/DB/로그 평문 보존 | Medium |
| E2 | 동시성 | 종료 중 processEvents 재진입 | Medium |
| E3 | 성능 | hydrate full materialization | Medium |
| E4 | 품질 | CI 부재 | Medium |
| E5 | 운영 | Chrome/worker orphan | Low–Medium |
| E6 | 운영 | runtime session 디스크 잔존 | Low–Medium |
| E7 | 아키텍처 | mixin 인지 부하 | Medium (부채) |
| E8 | 보안 | URL path allowlist | Low |
| E9 | 테스트 | Selenium E2E | Medium (장기) |
| E10 | 배포 | 코드 서명/업데이트 | Low |

기능 감사 High였던 `_start` dirty는 **이미 해소** — 본 문서 재발 없음.

---

## 11. Recommended Plan (범위별)

### 1단계 — 운영·데이터 보호 — ✅ 반영 (2026-07-29)

| 항목 | 상태 | 구현 |
|------|------|------|
| 로그/보존 정책 | ✅ | `LOG_FILE_LEVEL=INFO`, `safe_log_text`, `SUBTITLE_LOG_LEVEL` env |
| stale runtime_sessions 정리 | ✅ | `RUNTIME_ARCHIVE_MAX_AGE_DAYS` + KEEP_RECENT |
| 종료 중 액션 가드 | ✅ | `_exit_in_progress` + mutation/start 차단 |
| CI 최소 세트 | ✅ | `.github/workflows/ci.yml` |

### 2단계 — 안정성·성능 — ✅ 반영 (2026-07-29)

| 항목 | 상태 | 구현 |
|------|------|------|
| hydrate 상한·취소·메모리 | ✅ | `HYDRATE_MAX_ENTRIES`, 토큰 슬롯 전달, 엔트리 단위 cancel |
| driver quit 진단 | ✅ | `_driver_quit_failures` + shutdown diagnostic |
| 검색 상위 N건 UI | ✅ | `상위 N건+` 라벨 |
| FakeCaptureProbe 라이브러리 | ✅ | `tests/test_support/capture_probe.py` |

### 3단계 — 구조·제품화

| 항목 | 상태 | 비고 |
|------|------|------|
| 배포 체크리스트 | ✅ | `docs/RELEASE_CHECKLIST.md` |
| star import 점진 제거 | 보류 | 대규모 회귀 비용 |
| 저장소 암호화 | 보류 | 제품 승인 필요 |
| 접근성 전면 | 보류 | 제품 우선순위 |
| 코드 서명 인프라 | 보류 | 인증서/프로세스 — 체크리스트만 |

---

## 12. Test Recommendations (확장 범위)

| 테스트 | 범위 |
|--------|------|
| 종료 중 액션 차단 | processEvents 재진입 시 start/save no-op |
| hydrate cancel + memory | 취소 후 부분 리스트 미적용 |
| orphan runtime GC | 시작 시 오래된 runtime root 삭제 |
| log retention | TimedRotating backupCount 정책 스모크 |
| packaging | frozen smoke + portable preflight (기존 유지) |
| CI workflow | 푸시 시 pytest/pyright |

기능 회귀 스위트(`test_project_audit_*.py`)는 그대로 유지.

---

## 13. What We Did Not Over-Claim

- 원격 공격자 시나리오를 Critical로 과장하지 않음 (로컬 앱 + host 제한).  
- 측정 없는 “느리다/빠르다” 단정 대신 Config 상한·코드 경로 근거.  
- suffix 알고리즘 재설계는 기능 감사·PIPELINE_LOCK 영역 — 여기서 재제안하지 않음.  
- 법률 자문(개인정보보호법 적용 여부)은 범위 밖 — **데이터 민감성만 기술**.

---

## 14. Appendix — Key Symbols (CodeGraph)

| 심볼 | 파일 | 관련 범위 |
|------|------|-----------|
| `validate_assembly_url` | `core/url_policy.py` | 보안 |
| `validate_subtitle_selector` | `core/selector_policy.py` | 보안 |
| `_resolve_runtime_relative_path` | `persistence_runtime_segments.py` | 보안·I/O |
| `_emit_worker_message` / drain | `pipeline_queue.py` / `pipeline_messages.py` | 동시성 |
| `closeEvent` / `_wait_for_background_threads_during_exit` | `runtime_lifecycle.py` | 라이프사이클 |
| `_run_after_full_session_hydrated` | `persistence_runtime_hydration.py` | 성능·동시성 |
| `_render_subtitles` | `view_render.py` | 성능 |
| `DatabaseCoreMixin` / FTS | `database_impl/*` | DB·성능 |
| `resolve_storage_resolution` | `core/config.py` | 운영·프라이버시 |
| `ensure_file_logging` | `core/logging_utils.py` | 프라이버시 |

---

*확장 범위 감사 리포트. 구현 착수 시 1단계(E1·E2·E4·E6)부터 권장. 기능 이슈는 `PROJECT_AUDIT.md`를 우선 따른다.*
