# -*- coding: utf-8 -*-
"""Chrome 없는 수집 시뮬용 probe 더블 라이브러리 (확장 감사 E9)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CaptureProbeProtocol(Protocol):
    def read_subtitle_probe(
        self,
        selector_candidates: list[str],
        *,
        preferred_frame_path: tuple[int, ...] = (),
    ) -> dict[str, Any]: ...


class FakeCaptureProbe:
    """순차 텍스트를 반환하는 최소 probe 더블."""

    def __init__(self, texts: list[str] | None = None) -> None:
        self._texts = list(texts or [])
        self._index = 0
        self.calls: list[tuple[tuple[str, ...], tuple[int, ...]]] = []

    def read_subtitle_probe(
        self,
        selector_candidates: list[str],
        *,
        preferred_frame_path: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        self.calls.append((tuple(selector_candidates), preferred_frame_path))
        if not self._texts:
            text = ""
        elif self._index >= len(self._texts):
            text = self._texts[-1]
        else:
            text = self._texts[self._index]
            self._index += 1
        return {
            "text": text,
            "found": bool(text),
            "matched_selector": selector_candidates[0] if selector_candidates else "",
            "frame_path": list(preferred_frame_path),
        }


def scenario_incremental_speech() -> FakeCaptureProbe:
    """점진 확장 발화 시나리오."""
    return FakeCaptureProbe(
        [
            "안녕",
            "안녕하세요",
            "안녕하세요 위원님",
            "안녕하세요 위원님 질의드리겠습니다",
        ]
    )


def scenario_speaker_reset() -> FakeCaptureProbe:
    """발언 전환 후 새 문장."""
    return FakeCaptureProbe(
        [
            "정부 측 답변드리겠습니다",
            "정부 측 답변드리겠습니다 예산안은",
            "다음 위원 질의해 주십시오",
        ]
    )


def scenario_short_utterances() -> FakeCaptureProbe:
    """짧은 호응 발화."""
    return FakeCaptureProbe(["네", "예", "맞습니다"])
