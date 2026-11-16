# -*- coding: utf-8 -*-
"""데스크톱 ↔ Chrome 확장 수집 알고리즘 차등 검증 (parity differential).

공유 벡터(`parity/pipeline-vectors.json`)는 손으로 고른 사례만 본다. 이 스크립트는 같은
무작위 입력을 두 구현에 넣어 결과를 비교한다. 대상은 정규화·compact, 증분 추출 2종,
결합, commit 가능 판정, keepalive, 병합 판정, 미확정 배경, 균등 샘플링, fallback commit
게이트다.

  python scripts/parity_differential.py                 # 형제 저장소 ../korea-assembly-cc-chrome
  python scripts/parity_differential.py --cases 3000 --seed 7
  KOREA_ASSEMBLY_CC_CHROME_DIR=... python scripts/parity_differential.py

Chrome 저장소의 `tests/parity-differential.test.ts` 가 PARITY_DIFF_IN 입력을 계산해
PARITY_DIFF_OUT 에 쓴다(환경 변수가 없으면 아무 일도 하지 않는다). 불일치가 있으면
exit 1 과 함께 첫 사례를 출력한다. 새 불일치는 원인을 고친 뒤 공유 벡터에 사례로 고정한다.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core import utils  # noqa: E402
from core.fallback_commit import FallbackGateSettings, decide_fallback_commit  # noqa: E402
from core.models import SubtitleEntry  # noqa: E402
from core.subtitle_confirmation import has_visible_background_highlight, sample_evenly  # noqa: E402
from core.subtitle_pipeline import (  # noqa: E402
    PipelineSourceMeta,
    extract_incremental_text_from_history,
    extract_incremental_text_with_recent_history,
    should_apply_keepalive,
    should_merge_into_last_entry,
)
from core.subtitle_pipeline_impl.entries import _join_stream_text  # noqa: E402
from core.subtitle_pipeline_impl.history import _normalize_runtime_text  # noqa: E402


def generate_cases(SEED: int, N: int) -> dict[str, list]:
    rng = random.Random(SEED)
    FLATTEN = {"auto_clean_newlines": True}

    WORDS = (
        "존경하는 위원장님 그리고 동료 위원 여러분 오늘 회의에서는 예산안 심사와 관련된 "
        "주요 쟁점을 순서대로 논의하겠습니다 먼저 기획재정부 차관께서 보고해 주시기 바랍니다 "
        "질의를 마치겠습니다 다음은 김철수 위원님 2026년 3조 원 AI 반도체 법안 제1조 네 아니요 예"
    ).split()
    PUNCT = [".", ",", "?", "!", "…", "”", "’", "(", ")", "“", "‘", "%", ":", ";", '"', "'"]
    WS = [" ", "  ", chr(13) + chr(10), chr(10), chr(9), chr(8203), chr(65279), chr(160), chr(28), chr(31), chr(133), chr(12288), chr(8232), chr(8239), chr(5760), chr(11), chr(12), chr(8288), chr(6158)]


    def words(n: int) -> list[str]:
        return [rng.choice(WORDS) for _ in range(n)]


    def noisy(tokens: list[str]) -> str:
        out = []
        for tok in tokens:
            if rng.random() < 0.15:
                tok = tok + rng.choice(PUNCT)
            if rng.random() < 0.05:
                tok = rng.choice(PUNCT) + tok
            out.append(tok)
            out.append(rng.choice(WS) if rng.random() < 0.2 else " ")
        return "".join(out).strip() if rng.random() < 0.8 else "".join(out)


    def random_text(lo: int = 0, hi: int = 12) -> str:
        return noisy(words(rng.randint(lo, hi)))


    def ex_dict(r) -> dict:
        return {
            "text": r.text,
            "matched": r.matched,
            "duplicate": r.duplicate,
            "ambiguous": r.ambiguous,
            "reason": r.reason,
        }


    cases: dict[str, list] = {k: [] for k in (
        "normalize", "extractIncremental", "extractWithRecentHistory", "joinStreamText",
        "committable", "keepalive", "shouldMerge", "backgroundHighlight", "sampleEvenly",
        "fallbackCommitGate",
    )}

    for _ in range(N):
        s = random_text(0, 10)
        if rng.random() < 0.1:
            s = rng.choice(["", "   ", "로딩중..", "Loading...", "123", "...", "!!", "가", "a", "1.", "-"])
        cases["normalize"].append({
            "input": s,
            "desktop": {"normalized": _normalize_runtime_text(s, FLATTEN), "compact": utils.compact_subtitle_text(s)},
        })
        cases["committable"].append({"text": s, "desktop": utils.is_meaningful_subtitle_text(s)})

    for _ in range(N):
        stream = words(rng.randint(5, 60))
        cut = rng.randint(0, len(stream))
        history = " ".join(stream[:cut])
        mode = rng.random()
        if mode < 0.4:  # raw = tail window of history + extension
            start = rng.randint(0, cut)
            raw = noisy(stream[start: min(len(stream), cut + rng.randint(0, 8))])
        elif mode < 0.6:  # raw entirely inside history
            a = rng.randint(0, max(0, cut - 1))
            raw = noisy(stream[a: rng.randint(a, cut)])
        elif mode < 0.8:  # unrelated raw
            raw = random_text(0, 15)
        else:  # repeated phrases
            raw = noisy(stream[max(0, cut - 5): cut] * rng.randint(1, 3) + words(rng.randint(0, 4)))
        if rng.random() < 0.1:
            history = ""
        r = extract_incremental_text_from_history(raw, history, FLATTEN)
        cases["extractIncremental"].append({"raw": raw, "history": history, "desktop": ex_dict(r)})
        recent_cut = rng.randint(0, cut)
        recent = utils.compact_subtitle_text(" ".join(stream[recent_cut:cut]))
        r2 = extract_incremental_text_with_recent_history(raw, history, recent, FLATTEN)
        cases["extractWithRecentHistory"].append(
            {"raw": raw, "history": history, "recent": recent, "desktop": ex_dict(r2)}
        )

    for _ in range(N):
        base = random_text(0, 5)
        add = random_text(0, 5)
        if rng.random() < 0.3:
            add = rng.choice(PUNCT) + add
        if rng.random() < 0.3:
            base = base + rng.choice(PUNCT)
        cases["joinStreamText"].append({"base": base, "addition": add, "desktop": _join_stream_text(base, add)})

    for _ in range(N):
        last = random_text(0, 6)
        tail_mode = rng.random()
        if tail_mode < 0.3:
            raw = last
        elif tail_mode < 0.6:
            raw = random_text(0, 4) + " " + last
        elif tail_mode < 0.8:
            raw = last + " " + random_text(1, 3)
        else:
            raw = random_text(0, 6)
        cases["keepalive"].append({"raw": raw, "lastEntryText": last, "desktop": should_apply_keepalive(raw, last)})

    BASE = datetime(2026, 10, 22, 10, 0, 0)
    CHANNELS = ["primary", "secondary", "unknown"]
    COLORS = ["", "rgb(30, 30, 30)", "rgb(35, 124, 147)"]
    for _ in range(N):
        last_row: dict[str, Any] = {"text": random_text(1, 20)}
        if rng.random() < 0.5:
            last_row["sourceNodeKey"] = rng.choice(["k1", "k2", "row_gen0"])
        if rng.random() < 0.5:
            last_row["speakerColor"] = rng.choice(COLORS[1:])
        if rng.random() < 0.6:
            last_row["speakerChannel"] = rng.choice(CHANNELS)
        meta: dict[str, Any] = {}
        if rng.random() < 0.5:
            meta["sourceNodeKey"] = rng.choice(["k1", "k2", "row_gen0"])
        if rng.random() < 0.5:
            meta["speakerColor"] = rng.choice(COLORS[1:])
        if rng.random() < 0.6:
            meta["speakerChannel"] = rng.choice(CHANNELS)
        if rng.random() < 0.15:
            meta["forceNewEntry"] = True
        if rng.random() < 0.6:
            meta["sourceCaptureMode"] = rng.choice(["fallback", "structured"])
        text = random_text(1, 20)
        offset = rng.choice([0, 500, 1000, 1999, 2000, 2001, 3000, 4999, 5000, 5001, 8000])
        max_chars = rng.choice([1000, 300, 40, 20])
        after_reset = rng.random() < 0.1
        entry = SubtitleEntry(
            last_row["text"], BASE,
            source_node_key=last_row.get("sourceNodeKey"),
            speaker_color=last_row.get("speakerColor"),
            speaker_channel=last_row.get("speakerChannel", "unknown"),
        )
        entry.start_time = BASE
        entry.end_time = BASE
        pm = PipelineSourceMeta(
            source_node_key=meta.get("sourceNodeKey", ""),
            speaker_color=meta.get("speakerColor", ""),
            speaker_channel=meta.get("speakerChannel", "unknown"),
            force_new_entry=bool(meta.get("forceNewEntry", False)),
            source_mode={"fallback": "fallback", "structured": "smi-window"}.get(meta.get("sourceCaptureMode", ""), ""),
        )
        merged = should_merge_into_last_entry(
            entry, text, BASE + timedelta(milliseconds=offset), pm,
            merge_gap_seconds=5, merge_max_chars=max_chars, after_reset=after_reset,
        )
        cases["shouldMerge"].append({
            "last": last_row, "meta": meta, "text": text, "nowOffsetMs": offset,
            "mergeMaxChars": max_chars, "afterReset": after_reset, "desktop": merged,
        })

    BGS = ["", "transparent", "rgba(0, 0, 0, 0)", "rgba(0,0,0,0)", "rgb(207, 229, 247)", "#cfe5f7",
           "rgba(54, 160, 255, 0.2)", " TRANSPARENT ", "rgba(0, 0, 0, 0.0)"]
    IMGS = ["", "none", " NONE ", "url(x.png)", "linear-gradient(red, blue)"]
    for bg in BGS:
        for img in IMGS:
            cases["backgroundHighlight"].append(
                {"backgroundColor": bg, "backgroundImage": img, "desktop": has_visible_background_highlight(bg, img)}
            )

    for _ in range(N):
        count = rng.randint(0, 300)
        take = rng.randint(-1, 120)
        cases["sampleEvenly"].append(
            {"count": count, "maxTake": take, "desktop": sample_evenly(list(range(count)), take)}
        )

    settings = FallbackGateSettings(observation_threshold=2, stable_ms=400, max_wait_ms=2000)
    for _ in range(N):
        t = 0
        steps = []
        candidate = None
        pool = [random_text(1, 6) for _ in range(3)]
        for _ in range(rng.randint(1, 15)):
            t += rng.choice([0, 50, 100, 199, 200, 300, 399, 400, 401, 1000, 1999, 2000])
            raw = rng.choice(pool) if rng.random() < 0.6 else random_text(1, 6)
            d = decide_fallback_commit(candidate, raw, t, settings)
            steps.append({"raw": raw, "atMs": t, "desktop": {
                "commitNow": d.commit_now, "delayMs": d.delay_ms,
                "observationCount": d.candidate.observation_count, "replaced": d.replaced,
                "maxWaitReached": d.max_wait_reached, "pendingSince": d.candidate.pending_since_ms,
            }})
            candidate = None if d.commit_now else d.candidate
        cases["fallbackCommitGate"].append({"steps": steps})
    return cases


def compare(cases: dict[str, list], chrome: dict[str, list]) -> tuple[int, dict[str, list]]:
    total = 0
    mismatches: dict[str, list] = {}
    for key, items in cases.items():
        got = chrome[key]
        if len(got) != len(items):
            raise SystemExit(f"{key}: chrome returned {len(got)} results for {len(items)} cases")
        for case, result in zip(items, got):
            if key == "fallbackCommitGate":
                for step, step_result in zip(case["steps"], result):
                    total += 1
                    if step["desktop"] != step_result:
                        mismatches.setdefault(key, []).append({"step": step, "chrome": step_result})
                continue
            total += 1
            if case["desktop"] != result:
                mismatches.setdefault(key, []).append({"case": case, "chrome": result})
    return total, mismatches


def _chrome_dir(explicit: str | None) -> Path:
    override = explicit or os.environ.get("KOREA_ASSEMBLY_CC_CHROME_DIR", "").strip()
    return (Path(override) if override else REPO.parent / "korea-assembly-cc-chrome").resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=int, default=1500, help="함수별 무작위 사례 수 (기본 1500)")
    parser.add_argument("--seed", type=int, default=20261116)
    parser.add_argument("--chrome-dir", default=None)
    args = parser.parse_args(argv)

    chrome_dir = _chrome_dir(args.chrome_dir)
    harness = chrome_dir / "tests" / "parity-differential.test.ts"
    if not harness.is_file():
        print(f"Parity differential skipped: {harness} not found")
        return 0
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        print("Parity differential skipped: npx not found")
        return 0

    cases = generate_cases(args.seed, args.cases)
    with tempfile.TemporaryDirectory(prefix="kacc-parity-diff-") as tmp:
        cases_path = Path(tmp) / "cases.json"
        out_path = Path(tmp) / "chrome.json"
        cases_path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ, PARITY_DIFF_IN=str(cases_path), PARITY_DIFF_OUT=str(out_path))
        completed = subprocess.run(
            [npx, "vitest", "run", "tests/parity-differential.test.ts"],
            cwd=chrome_dir,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 or not out_path.is_file():
            print(completed.stdout[-2000:])
            print(completed.stderr[-2000:])
            print("Parity differential failed: chrome harness did not produce results")
            return 2
        chrome = json.loads(out_path.read_text(encoding="utf-8"))

    total, mismatches = compare(cases, chrome)
    print(f"Parity differential: seed={args.seed} compared {total} results")
    for key in cases:
        count = len(mismatches.get(key, []))
        print(f"  {key:26s} {'OK' if count == 0 else f'MISMATCH {count}'}")
    for key, items in mismatches.items():
        print(f"\n--- {key} (first 3)")
        for item in items[:3]:
            print(json.dumps(item, ensure_ascii=True)[:800])
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
