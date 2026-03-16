# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Literal, Optional, cast


SpeakerChannel = Literal["primary", "secondary", "unknown"]


def _clone_frame_path(frame_path: Optional[list[int]]) -> Optional[list[int]]:
    if frame_path is None:
        return None
    return list(frame_path)


class SubtitleEntry:
    """Subtitle item with cached counts and optional runtime source metadata."""

    def __init__(
        self,
        text: str,
        timestamp: Optional[datetime] = None,
        *,
        entry_id: Optional[str] = None,
        source_selector: Optional[str] = None,
        source_frame_path: Optional[list[int]] = None,
        source_node_key: Optional[str] = None,
        speaker_color: Optional[str] = None,
        speaker_channel: SpeakerChannel = "unknown",
        speaker_changed: bool = False,
    ):
        self.entry_id: Optional[str] = entry_id
        self.text: str = text
        self.timestamp: datetime = timestamp or datetime.now()
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.source_selector: Optional[str] = source_selector
        self.source_frame_path: Optional[list[int]] = _clone_frame_path(source_frame_path)
        self.source_node_key: Optional[str] = source_node_key
        self.speaker_color: Optional[str] = speaker_color
        self.speaker_channel: SpeakerChannel = speaker_channel
        self.speaker_changed: bool = speaker_changed
        self._char_count: int = len(text)
        self._word_count: int = len(text.split())

    @property
    def char_count(self) -> int:
        return self._char_count

    @property
    def word_count(self) -> int:
        return self._word_count

    def update_text(self, new_text: str) -> None:
        self.text = new_text
        self._char_count = len(new_text)
        self._word_count = len(new_text.split())

    def append(self, additional_text: str, separator: str = " ") -> None:
        if additional_text:
            self.update_text(self.text + separator + additional_text)
            self.end_time = datetime.now()

    def clone(self) -> "SubtitleEntry":
        copied = SubtitleEntry(
            self.text,
            self.timestamp,
            entry_id=self.entry_id,
            source_selector=self.source_selector,
            source_frame_path=self.source_frame_path,
            source_node_key=self.source_node_key,
            speaker_color=self.speaker_color,
            speaker_channel=self.speaker_channel,
            speaker_changed=self.speaker_changed,
        )
        copied.start_time = self.start_time
        copied.end_time = self.end_time
        return copied

    def to_dict(self) -> Dict[str, Optional[str] | list[int] | bool]:
        data: Dict[str, Optional[str] | list[int] | bool] = {
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
        }
        if self.entry_id:
            data["entry_id"] = self.entry_id
        if self.source_selector:
            data["source_selector"] = self.source_selector
        if self.source_frame_path:
            data["source_frame_path"] = list(self.source_frame_path)
        if self.source_node_key:
            data["source_node_key"] = self.source_node_key
        if self.speaker_color:
            data["speaker_color"] = self.speaker_color
        if self.speaker_channel != "unknown":
            data["speaker_channel"] = self.speaker_channel
        if self.speaker_changed:
            data["speaker_changed"] = True
        return data

    @classmethod
    def from_dict(cls, data: object) -> "SubtitleEntry":
        if not isinstance(data, dict):
            raise ValueError("자막 항목은 dict 타입이어야 합니다.")

        text = data.get("text", "")
        timestamp_str = data.get("timestamp")

        if not text:
            raise ValueError("자막 텍스트가 비어 있습니다.")
        if not timestamp_str:
            raise ValueError("타임스탬프가 없습니다.")

        frame_path = data.get("source_frame_path")
        source_frame_path = list(frame_path) if isinstance(frame_path, list) else None
        speaker_channel = str(data.get("speaker_channel") or "unknown")
        if speaker_channel not in ("primary", "secondary", "unknown"):
            speaker_channel = "unknown"

        entry = cls(
            str(text),
            entry_id=cast(Optional[str], data.get("entry_id")),
            source_selector=cast(Optional[str], data.get("source_selector")),
            source_frame_path=source_frame_path,
            source_node_key=cast(Optional[str], data.get("source_node_key")),
            speaker_color=cast(Optional[str], data.get("speaker_color")),
            speaker_channel=cast(SpeakerChannel, speaker_channel),
            speaker_changed=bool(data.get("speaker_changed", False)),
        )
        entry.timestamp = datetime.fromisoformat(str(timestamp_str))
        if data.get("start_time"):
            entry.start_time = datetime.fromisoformat(str(data["start_time"]))
        if data.get("end_time"):
            entry.end_time = datetime.fromisoformat(str(data["end_time"]))
        return entry


@dataclass(slots=True)
class ObservedSubtitleRow:
    node_key: str
    text: str
    speaker_color: str = ""
    speaker_channel: SpeakerChannel = "unknown"
    unstable_key: bool = False


@dataclass
class CaptureSessionState:
    entries: list[SubtitleEntry] = field(default_factory=list)
    preview_text: str = ""
    confirmed_compact: str = ""
    trailing_suffix: str = ""
    last_observed_raw: str = ""
    last_processed_raw: str = ""
    preview_desync_count: int = 0
    preview_ambiguous_skip_count: int = 0
    current_selector: str = ""
    current_frame_path: tuple[int, ...] = ()
    observer_active: bool = False
    last_observer_event_at: float | None = None
    last_keepalive_at: float | None = None
    last_committed_reset_at: float | None = None

    def clone(self) -> "CaptureSessionState":
        return CaptureSessionState(
            entries=[entry.clone() for entry in self.entries],
            preview_text=self.preview_text,
            confirmed_compact=self.confirmed_compact,
            trailing_suffix=self.trailing_suffix,
            last_observed_raw=self.last_observed_raw,
            last_processed_raw=self.last_processed_raw,
            preview_desync_count=self.preview_desync_count,
            preview_ambiguous_skip_count=self.preview_ambiguous_skip_count,
            current_selector=self.current_selector,
            current_frame_path=tuple(self.current_frame_path),
            observer_active=self.observer_active,
            last_observer_event_at=self.last_observer_event_at,
            last_keepalive_at=self.last_keepalive_at,
            last_committed_reset_at=self.last_committed_reset_at,
        )
