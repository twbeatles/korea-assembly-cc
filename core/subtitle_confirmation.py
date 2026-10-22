# -*- coding: utf-8 -*-
"""probe JS 미확정(인식 중) 하이라이트 판정 규칙의 순수 Python 미러.

브라우저 execute_script 안의 hasVisibleBackgroundHighlight / sampleEvenly 와
동일 의미론을 단위 테스트로 고정한다. Chrome 확장 `src/content/subtitle-rows.ts` 와
같은 규칙이며 `parity/pipeline-vectors.json` 의 `backgroundHighlight` 벡터로 검증한다.
JS 수정 시 이 모듈·테스트를 함께 갱신한다.
"""

from __future__ import annotations

from typing import Sequence, TypeVar

T = TypeVar("T")


def has_opaque_background(background_color: str) -> bool:
    normalized = "".join(str(background_color or "").split()).lower()
    return bool(normalized) and normalized not in ("transparent", "rgba(0,0,0,0)")


def has_highlight_background_image(background_image: str) -> bool:
    normalized = str(background_image or "").strip().lower()
    return bool(normalized) and normalized != "none"


def has_visible_background_highlight(background_color: str, background_image: str = "") -> bool:
    return has_opaque_background(background_color) or has_highlight_background_image(
        background_image
    )


def sample_evenly(items: Sequence[T], max_take: int) -> list[T]:
    """균등 샘플링하되 마지막 항목(하이라이트가 붙기 쉬운 말단)은 항상 포함한다."""
    if max_take <= 0 or not items:
        return []
    if len(items) <= max_take:
        return list(items)
    sampled: list[T] = []
    seen: set[int] = set()
    step = len(items) / max_take
    for index in range(max_take):
        sampled_index = min(len(items) - 1, int(index * step))
        if sampled_index in seen:
            continue
        seen.add(sampled_index)
        sampled.append(items[sampled_index])
    last_index = len(items) - 1
    if last_index not in seen:
        if len(sampled) >= max_take:
            sampled[-1] = items[last_index]
        else:
            sampled.append(items[last_index])
    return sampled
