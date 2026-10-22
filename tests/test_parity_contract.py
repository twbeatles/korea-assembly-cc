# -*- coding: utf-8 -*-
"""parity/ 공유 계약 회귀 테스트.

Chrome 확장 저장소(korea-assembly-cc-chrome)의 `tests/parity-contract.test.ts` 와
같은 `parity/capture-contract.json`, `parity/pipeline-vectors.json` 을 검증한다.
한쪽 구현만 바꾸면 이 테스트 또는 Chrome 쪽 테스트가 깨진다.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from core import utils
from core.config import Config
from core.live_capture_impl.ledger import LIVE_LEDGER_MAX_ROWS
from core.models import SubtitleEntry
from core.subtitle_confirmation import has_visible_background_highlight, sample_evenly
from core.subtitle_pipeline import (
    LARGE_APPEND_MIN,
    MIN_COMPACT_ANCHOR,
    PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD,
    PREVIEW_RESYNC_THRESHOLD,
    RECENT_DUPLICATE_MIN_LENGTH,
    RECENT_HISTORY_COMPACT_LENGTH,
    RECENT_HISTORY_ENTRIES,
    RECENT_RESYNC_ENTRIES,
    SUFFIX_LENGTH,
    PipelineSourceMeta,
    extract_incremental_text_from_history,
    extract_incremental_text_with_recent_history,
    should_apply_keepalive,
    should_merge_into_last_entry,
)
from core.subtitle_pipeline_impl.entries import _join_stream_text
from core.subtitle_pipeline_impl.history import _normalize_runtime_text
from ui.main_window_impl import capture_dom
from ui.main_window_impl.capture_dom import MainWindowCaptureDomMixin

PARITY_DIR = Path(__file__).resolve().parents[1] / "parity"
FLATTEN_SETTINGS = {"auto_clean_newlines": True}


def _load(name: str) -> Any:
    return json.loads((PARITY_DIR / name).read_text(encoding="utf-8"))


CONTRACT = _load("capture-contract.json")
VECTORS = _load("pipeline-vectors.json")
DEFAULTS = VECTORS["defaults"]
BASE_TIME = datetime.fromisoformat(DEFAULTS["baseTimeIso"].replace("Z", "+00:00"))

_CAPTURE_DOM_SOURCE = inspect.getsource(capture_dom)


def test_parity_files_exist() -> None:
    for name in ("README.md", "capture-contract.json", "pipeline-vectors.json"):
        assert (PARITY_DIR / name).is_file(), name


def test_selector_candidates_match_contract() -> None:
    # 인스턴스 상태를 쓰지 않는 메서드이므로 더미 self 로 호출한다.
    candidates = MainWindowCaptureDomMixin._build_subtitle_selector_candidates(
        cast(Any, object()), ""
    )
    assert candidates == CONTRACT["selectorCandidatesOrdered"]


def test_probe_js_uses_contract_dom_and_speaker_colors() -> None:
    for color in CONTRACT["speakerColors"].values():
        assert f"'{color}'" in _CAPTURE_DOM_SOURCE
    for selector in CONTRACT["containerFallbackSelectors"]:
        assert selector in _CAPTURE_DOM_SOURCE
    assert CONTRACT["dom"]["row"] in _CAPTURE_DOM_SOURCE
    # 미확정 판정: 배경색 + 배경 이미지, 샘플 상한은 Config 로 전달
    assert "hasHighlightBackgroundImage" in _CAPTURE_DOM_SOURCE
    assert "Config.UNCONFIRMED_DESCENDANT_SAMPLE_LIMIT" in _CAPTURE_DOM_SOURCE
    plenary = CONTRACT["site"]["plenary"]
    assert f"xcode === '{plenary['xcode']}'" in _CAPTURE_DOM_SOURCE
    assert f"'{plenary['xcgcdPrefix']}'" in _CAPTURE_DOM_SOURCE


def test_pipeline_constants_match_contract() -> None:
    p = CONTRACT["pipeline"]
    assert SUFFIX_LENGTH == p["suffixLength"]
    assert MIN_COMPACT_ANCHOR == p["minCompactAnchor"]
    assert LARGE_APPEND_MIN == p["largeAppendMin"]
    assert RECENT_DUPLICATE_MIN_LENGTH == p["recentDuplicateMinLength"]
    assert RECENT_HISTORY_ENTRIES == p["recentHistoryEntries"]
    assert RECENT_HISTORY_COMPACT_LENGTH == p["recentHistoryCompactLength"]
    assert RECENT_RESYNC_ENTRIES == p["recentResyncEntries"]
    assert PREVIEW_RESYNC_THRESHOLD == p["previewResyncThreshold"]
    assert PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD == p["previewAmbiguousResyncThreshold"]
    assert Config.CONFIRMED_COMPACT_MAX_LEN == p["confirmedCompactMaxLength"]
    assert Config.ENTRY_MERGE_MAX_GAP == p["mergeGapSeconds"]
    assert Config.FALLBACK_MERGE_GAP_FACTOR == p["fallbackMergeGapFactor"]
    assert int(Config.SUBTITLE_KEEPALIVE_INTERVAL * 1000) == p["keepaliveIntervalMs"]
    assert Config.SUBTITLE_RESET_GRACE_MS == p["subtitleResetGraceMs"]
    assert LIVE_LEDGER_MAX_ROWS == p["liveLedgerMaxRows"]
    assert Config.FALLBACK_COMMIT_OBSERVATION_THRESHOLD == p["fallbackCommitObservationThreshold"]
    assert Config.FALLBACK_COMMIT_STABLE_MS == p["fallbackCommitStableMs"]
    assert Config.FALLBACK_INTERNAL_RAW_MAX_CHARS == p["fallbackInternalRawMaxChars"]
    assert Config.FALLBACK_PREVIEW_MAX_CHARS == p["fallbackPreviewMaxChars"]
    unconfirmed = CONTRACT["unconfirmed"]
    assert Config.UNCONFIRMED_DESCENDANT_SAMPLE_LIMIT == unconfirmed["descendantSampleLimit"]
    assert Config.UNCONFIRMED_FALLBACK_ALLOW_STREAK == unconfirmed["containerFallbackAllowStreak"]
    assert (
        Config.ENTRY_MERGE_MAX_CHARS
        == CONTRACT["intentionalDifferences"]["mergeMaxChars"]["desktop"]
    )


def test_contract_placeholders_and_highlights_are_rejected() -> None:
    for text in CONTRACT["placeholderTexts"]:
        assert utils.is_placeholder_subtitle_text(f"{text}...")
        assert not utils.is_meaningful_subtitle_text(f"{text}..")
    for color in CONTRACT["unconfirmed"]["knownHighlightBackgrounds"]:
        assert has_visible_background_highlight(color, "none")


@pytest.mark.parametrize("case", VECTORS["normalize"])
def test_normalize_vectors(case: dict[str, str]) -> None:
    assert _normalize_runtime_text(case["input"], FLATTEN_SETTINGS) == case["normalized"]
    assert utils.compact_subtitle_text(case["input"]) == case["compact"]


def _as_dict(result: Any) -> dict[str, Any]:
    return {
        "text": result.text,
        "matched": result.matched,
        "duplicate": result.duplicate,
        "ambiguous": result.ambiguous,
        "reason": result.reason,
    }


@pytest.mark.parametrize("case", VECTORS["extractIncremental"], ids=lambda c: c["name"])
def test_extract_incremental_vectors(case: dict[str, Any]) -> None:
    result = extract_incremental_text_from_history(
        case["raw"], case["history"], FLATTEN_SETTINGS
    )
    assert _as_dict(result) == case["expected"]


@pytest.mark.parametrize(
    "case", VECTORS["extractWithRecentHistory"], ids=lambda c: c["name"]
)
def test_extract_with_recent_history_vectors(case: dict[str, Any]) -> None:
    result = extract_incremental_text_with_recent_history(
        case["raw"], case["history"], case["recent"], FLATTEN_SETTINGS
    )
    assert _as_dict(result) == case["expected"]


@pytest.mark.parametrize("case", VECTORS["joinStreamText"])
def test_join_stream_text_vectors(case: dict[str, str]) -> None:
    assert _join_stream_text(case["base"], case["addition"]) == case["expected"]


@pytest.mark.parametrize("case", VECTORS["committable"], ids=lambda c: c["text"])
def test_committable_vectors(case: dict[str, Any]) -> None:
    assert utils.is_meaningful_subtitle_text(case["text"]) is case["expected"]


def _source_mode(capture_mode: str | None) -> str:
    # Chrome sourceCaptureMode → 데스크톱 source_mode
    return {"fallback": "fallback", "structured": "smi-window"}.get(capture_mode or "", "")


@pytest.mark.parametrize("case", VECTORS["shouldMerge"], ids=lambda c: c["name"])
def test_should_merge_vectors(case: dict[str, Any]) -> None:
    last = case["last"]
    entry = SubtitleEntry(
        last.get("text", DEFAULTS["lastEntryText"]),
        BASE_TIME,
        source_node_key=last.get("sourceNodeKey"),
        speaker_color=last.get("speakerColor"),
        speaker_channel=last.get("speakerChannel", "unknown"),
    )
    entry.start_time = BASE_TIME
    entry.end_time = BASE_TIME
    meta_input = case["meta"]
    meta = PipelineSourceMeta(
        source_node_key=meta_input.get("sourceNodeKey", ""),
        speaker_color=meta_input.get("speakerColor", ""),
        speaker_channel=meta_input.get("speakerChannel", "unknown"),
        force_new_entry=bool(meta_input.get("forceNewEntry", False)),
        source_mode=_source_mode(meta_input.get("sourceCaptureMode")),
    )
    merged = should_merge_into_last_entry(
        entry,
        case.get("text", DEFAULTS["nextText"]),
        BASE_TIME + timedelta(milliseconds=case["nowOffsetMs"]),
        meta,
        merge_gap_seconds=DEFAULTS["mergeGapSeconds"],
        merge_max_chars=case.get("mergeMaxChars", DEFAULTS["mergeMaxChars"]),
        after_reset=bool(case.get("afterReset", False)),
    )
    assert merged is case["expected"]


@pytest.mark.parametrize("case", VECTORS["keepalive"])
def test_keepalive_vectors(case: dict[str, Any]) -> None:
    assert should_apply_keepalive(case["raw"], case["lastEntryText"]) is case["expected"]


@pytest.mark.parametrize("case", VECTORS["backgroundHighlight"])
def test_background_highlight_vectors(case: dict[str, Any]) -> None:
    assert (
        has_visible_background_highlight(case["backgroundColor"], case["backgroundImage"])
        is case["expected"]
    )


@pytest.mark.parametrize("case", VECTORS["sampleEvenly"])
def test_sample_evenly_vectors(case: dict[str, Any]) -> None:
    assert sample_evenly(list(range(case["count"])), case["maxTake"]) == case["expectedIndices"]
