# -*- coding: utf-8 -*-
"""container/unstable fallback 텍스트의 안정 관측 commit 게이트 (순수 함수).

Chrome 확장 `src/core/subtitle-pipeline/fallback-commit-gate.ts` 와 같은 규칙이며
`parity/pipeline-vectors.json` 의 `fallbackCommitGate` 벡터로 양쪽을 함께 검증한다.

- 같은 raw 가 ``observation_threshold`` 회 관측되거나 ``stable_ms`` 이상 유지되면 commit.
- raw 가 계속 바뀌어도 첫 미확정 관측(``pending_since_ms``)부터 ``max_wait_ms`` 가
  지나면 commit 한다. 연속 발언 중 commit/타임스탬프가 무기한 밀리지 않게 하는 상한이다.
- 후보가 다른 raw 로 바뀌어도 ``pending_since_ms`` 는 유지된다. commit 뒤 다음 관측은
  새 창에서 시작한다(호출 측이 후보를 비운다).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from core.config import Config
from core.text_utils import strip_subtitle_whitespace


@dataclass(frozen=True, slots=True)
class FallbackGateSettings:
    observation_threshold: int = int(Config.FALLBACK_COMMIT_OBSERVATION_THRESHOLD)
    stable_ms: int = int(Config.FALLBACK_COMMIT_STABLE_MS)
    max_wait_ms: int = int(Config.FALLBACK_COMMIT_MAX_WAIT_MS)


@dataclass(frozen=True, slots=True)
class FallbackGateCandidate:
    raw: str
    first_seen_ms: float
    pending_since_ms: float
    observation_count: int = 1


@dataclass(frozen=True, slots=True)
class FallbackGateDecision:
    candidate: FallbackGateCandidate
    commit_now: bool
    delay_ms: int
    replaced: bool
    max_wait_reached: bool


def decide_fallback_commit(
    previous: Optional[FallbackGateCandidate],
    raw: str,
    now_ms: float,
    settings: Optional[FallbackGateSettings] = None,
) -> FallbackGateDecision:
    """새 관측(raw, now_ms)을 반영한 후보와 commit 여부/대기 시간을 돌려준다."""
    active = settings or FallbackGateSettings()
    normalized = strip_subtitle_whitespace(raw)
    if previous is not None and previous.raw == normalized:
        candidate = replace(previous, observation_count=previous.observation_count + 1)
        replaced = False
    else:
        candidate = FallbackGateCandidate(
            raw=normalized,
            first_seen_ms=now_ms,
            pending_since_ms=previous.pending_since_ms if previous is not None else now_ms,
            observation_count=1,
        )
        replaced = previous is not None

    stable_elapsed = now_ms - candidate.first_seen_ms
    pending_elapsed = now_ms - candidate.pending_since_ms
    max_wait_reached = pending_elapsed >= int(active.max_wait_ms)
    commit_now = (
        candidate.observation_count >= int(active.observation_threshold)
        or stable_elapsed >= int(active.stable_ms)
        or max_wait_reached
    )
    delay_ms = (
        0
        if commit_now
        else max(
            0,
            int(
                min(
                    int(active.stable_ms) - stable_elapsed,
                    int(active.max_wait_ms) - pending_elapsed,
                )
            ),
        )
    )
    return FallbackGateDecision(
        candidate=candidate,
        commit_now=commit_now,
        delay_ms=delay_ms,
        replaced=replaced,
        max_wait_reached=bool(max_wait_reached and commit_now),
    )
