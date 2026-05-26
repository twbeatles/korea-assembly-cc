# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from core.config import Config
from core.models import CaptureSessionState, SpeakerChannel, SubtitleEntry

MIN_COMPACT_ANCHOR = 10
LARGE_APPEND_MIN = 200
RECENT_DUPLICATE_MIN_LENGTH = 8
RECENT_HISTORY_ENTRIES = 12
RECENT_HISTORY_COMPACT_LENGTH = int(Config.RECENT_HISTORY_COMPACT_LENGTH)
RECENT_RESYNC_ENTRIES = 5
SUFFIX_LENGTH = 50
PREVIEW_RESYNC_THRESHOLD = 10
PREVIEW_AMBIGUOUS_RESYNC_THRESHOLD = 6

@dataclass(slots=True)
class PipelineSourceMeta:
    selector: str = ""
    frame_path: tuple[int, ...] = ()
    source_node_key: str = ""
    source_entry_id: str = ""
    speaker_color: str = ""
    speaker_channel: SpeakerChannel = "unknown"
    force_new_entry: bool = False
    source_mode: str = ""

@dataclass(slots=True)
class LiveRowCommitMeta(PipelineSourceMeta):
    baseline_compact: Optional[str] = None

@dataclass(slots=True)
class PipelineResult:
    state: CaptureSessionState
    changed: bool
    appended_entry: Optional[SubtitleEntry] = None
    updated_entry: Optional[SubtitleEntry] = None
    reason: str = ""

@dataclass(slots=True)
class IncrementalExtractResult:
    text: str
    matched: bool
    duplicate: bool
    ambiguous: bool
    reason: str

def create_empty_capture_state() -> CaptureSessionState:
    return CaptureSessionState()

def _create_entry_id() -> str:
    return f"subtitle_{uuid4().hex}"
