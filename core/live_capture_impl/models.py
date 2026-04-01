# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.models import ObservedSubtitleRow, SpeakerChannel


CaptureMode = str


@dataclass(slots=True)
class LivePanelRow:
    key: str
    text: str
    node_key: str
    speaker_color: str
    speaker_channel: SpeakerChannel
    updated_at: float


@dataclass(slots=True)
class LiveCaptureRow(LivePanelRow):
    frame_path: tuple[int, ...] = ()
    selector: str = ""
    unstable_key: bool = False
    first_seen_at: float = 0.0
    committed_entry_id: Optional[str] = None
    baseline_compact: Optional[str] = None

    def clone(self) -> "LiveCaptureRow":
        return LiveCaptureRow(
            key=self.key,
            text=self.text,
            node_key=self.node_key,
            speaker_color=self.speaker_color,
            speaker_channel=self.speaker_channel,
            updated_at=self.updated_at,
            frame_path=tuple(self.frame_path),
            selector=self.selector,
            unstable_key=self.unstable_key,
            first_seen_at=self.first_seen_at,
            committed_entry_id=self.committed_entry_id,
            baseline_compact=self.baseline_compact,
        )


@dataclass
class LiveCaptureLedger:
    rows: dict[str, LiveCaptureRow] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    active_row_keys: list[str] = field(default_factory=list)
    preview_text: str = ""
    capture_mode: CaptureMode = "idle"


@dataclass(slots=True)
class NormalizedCaptureEvent:
    preview_text: str
    rows: list[ObservedSubtitleRow]
    selector: str = ""
    frame_path: tuple[int, ...] = ()
    timestamp: float = 0.0
    capture_mode: CaptureMode = "fallback"


@dataclass(slots=True)
class LiveRowChange:
    key: str
    row: LiveCaptureRow
    is_new: bool
    text_changed: bool


@dataclass(slots=True)
class LiveCaptureReconciliation:
    ledger: LiveCaptureLedger
    changed: bool
    row_changes: list[LiveRowChange]
    live_rows: list[LivePanelRow]
    active_row: Optional[LiveCaptureRow]


def build_live_row_key(node_key: str, frame_path: tuple[int, ...] = ()) -> str:
    path = ".".join(str(idx) for idx in frame_path) if frame_path else "top"
    return f"{path}::{node_key}"
