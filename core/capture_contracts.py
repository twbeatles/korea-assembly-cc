from __future__ import annotations

from typing import Any, Protocol


class SubtitleProbeReader(Protocol):
    """Selenium driver 없이 worker 입력을 주입·검증할 수 있도록 분리한 자막 probe 계약."""

    def read_subtitle_probe_by_selectors(
        self,
        driver: Any,
        selectors: list[str],
        *,
        preferred_frame_path: tuple[int, ...] = (),
        filter_unconfirmed_enabled: bool = True,
    ) -> dict[str, Any]:
        ...


class LiveBroadcastResolver(Protocol):
    """live_list 기반 xcode/xcgcd 보완 계약."""

    def detect_live_broadcast(
        self,
        driver: Any,
        original_url: str,
        *,
        force_refresh: bool = False,
    ) -> str:
        ...