# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.models import ObservedSubtitleRow, SpeakerChannel
from core import utils


CaptureMode = str

LIVE_LEDGER_MAX_ROWS = 300


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
class StructuredPreviewPayload:
    raw: str
    rows: list[ObservedSubtitleRow]
    selector: str = ""
    frame_path: tuple[int, ...] = ()

    def to_legacy_dict(self) -> dict[str, object]:
        return {
            "raw": self.raw,
            "rows": [
                {
                    "nodeKey": row.node_key,
                    "text": row.text,
                    "speakerColor": row.speaker_color,
                    "speakerChannel": row.speaker_channel,
                    "unstableKey": row.unstable_key,
                }
                for row in self.rows
            ],
            "selector": self.selector,
            "frame_path": self.frame_path,
        }


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


def create_empty_live_capture_ledger() -> LiveCaptureLedger:
    return LiveCaptureLedger()


def clear_live_capture_ledger() -> LiveCaptureLedger:
    return create_empty_live_capture_ledger()


def normalize_capture_event(
    *,
    raw: str = "",
    rows: Optional[list[ObservedSubtitleRow]] = None,
    selector: str = "",
    frame_path: Optional[tuple[int, ...] | list[int]] = None,
    timestamp: float,
) -> NormalizedCaptureEvent:
    normalized_rows = [
        ObservedSubtitleRow(
            node_key=row.node_key,
            text=utils.normalize_subtitle_text(row.text),
            speaker_color=row.speaker_color,
            speaker_channel=row.speaker_channel,
            unstable_key=row.unstable_key,
        )
        for row in (rows or [])
        if utils.normalize_subtitle_text(row.text)
    ]
    preview_from_rows = " ".join(row.text for row in normalized_rows).strip()
    preview_text = utils.normalize_subtitle_text(raw) or preview_from_rows
    return NormalizedCaptureEvent(
        preview_text=preview_text,
        rows=normalized_rows,
        selector=selector or "",
        frame_path=tuple(frame_path or ()),
        timestamp=timestamp,
        capture_mode="structured" if normalized_rows else ("fallback" if preview_text else "idle"),
    )


def _same_key_order(left: list[str], right: list[str]) -> bool:
    return len(left) == len(right) and all(
        left_item == right_item for left_item, right_item in zip(left, right)
    )


def _prune_ledger_rows(
    rows: dict[str, LiveCaptureRow],
    order: list[str],
    active_row_keys: list[str],
    max_rows: int = LIVE_LEDGER_MAX_ROWS,
) -> tuple[dict[str, LiveCaptureRow], list[str]]:
    if len(order) <= max_rows:
        return rows, order

    keep_keys = set(active_row_keys)
    for index in range(len(order) - 1, -1, -1):
        if len(keep_keys) >= max_rows:
            break
        key = order[index]
        if key in rows:
            keep_keys.add(key)

    next_order = [key for key in order if key in keep_keys]
    next_rows = {key: rows[key] for key in next_order if key in rows}
    return next_rows, next_order


def set_fallback_capture_preview(
    ledger: LiveCaptureLedger,
    preview_text: str,
) -> LiveCaptureLedger:
    pruned_rows, pruned_order = _prune_ledger_rows(
        ledger.rows,
        ledger.order,
        [],
    )
    ledger.rows = pruned_rows
    ledger.order = pruned_order
    ledger.active_row_keys = []
    ledger.preview_text = preview_text
    ledger.capture_mode = "fallback" if preview_text else "idle"
    return ledger


def get_live_row(ledger: LiveCaptureLedger, key: str) -> Optional[LiveCaptureRow]:
    row = ledger.rows.get(key)
    return row.clone() if row else None


def list_live_panel_rows(ledger: LiveCaptureLedger) -> list[LivePanelRow]:
    results: list[LivePanelRow] = []
    for key in ledger.order:
        row = ledger.rows.get(key)
        if not row:
            continue
        results.append(
            LivePanelRow(
                key=row.key,
                text=row.text,
                node_key=row.node_key,
                speaker_color=row.speaker_color,
                speaker_channel=row.speaker_channel,
                updated_at=row.updated_at,
            )
        )
    return results


def set_live_row_baseline(
    ledger: LiveCaptureLedger,
    key: str,
    baseline_compact: str,
) -> LiveCaptureLedger:
    row = ledger.rows.get(key)
    if row:
        row.baseline_compact = baseline_compact
    return ledger


def mark_live_row_committed(
    ledger: LiveCaptureLedger,
    key: str,
    entry_id: str,
) -> LiveCaptureLedger:
    row = ledger.rows.get(key)
    if row:
        row.committed_entry_id = entry_id
    return ledger


def reconcile_live_capture(
    ledger: LiveCaptureLedger,
    event: NormalizedCaptureEvent,
) -> LiveCaptureReconciliation:
    previous_preview_text = ledger.preview_text
    previous_capture_mode = ledger.capture_mode
    previous_active_row_keys = list(ledger.active_row_keys)

    if not event.rows:
        next_ledger = set_fallback_capture_preview(ledger, event.preview_text)
        return LiveCaptureReconciliation(
            ledger=next_ledger,
            changed=(
                next_ledger.preview_text != previous_preview_text
                or next_ledger.capture_mode != previous_capture_mode
                or not _same_key_order(
                    next_ledger.active_row_keys,
                    previous_active_row_keys,
                )
            ),
            row_changes=[],
            live_rows=[],
            active_row=None,
        )

    next_active_row_keys: list[str] = []
    row_changes: list[LiveRowChange] = []

    for row in event.rows:
        text = utils.normalize_subtitle_text(row.text)
        if not text:
            continue

        key = build_live_row_key(row.node_key, event.frame_path)
        next_active_row_keys.append(key)
        previous = ledger.rows.get(key)

        if previous is None:
            next_row = LiveCaptureRow(
                key=key,
                text=text,
                node_key=row.node_key,
                speaker_color=row.speaker_color,
                speaker_channel=row.speaker_channel,
                updated_at=event.timestamp,
                frame_path=tuple(event.frame_path),
                selector=event.selector,
                unstable_key=row.unstable_key,
                first_seen_at=event.timestamp,
            )
            ledger.rows[key] = next_row
            ledger.order.append(key)
            row_changes.append(
                LiveRowChange(
                    key=key,
                    row=next_row.clone(),
                    is_new=True,
                    text_changed=True,
                )
            )
            continue

        text_changed = (
            previous.text != text
            or previous.speaker_color != row.speaker_color
            or previous.speaker_channel != row.speaker_channel
        )
        previous.text = text
        previous.speaker_color = row.speaker_color
        previous.speaker_channel = row.speaker_channel
        previous.updated_at = event.timestamp
        previous.frame_path = tuple(event.frame_path)
        previous.selector = event.selector
        previous.unstable_key = row.unstable_key

        if text_changed:
            row_changes.append(
                LiveRowChange(
                    key=key,
                    row=previous.clone(),
                    is_new=False,
                    text_changed=True,
                )
            )

    pruned_rows, pruned_order = _prune_ledger_rows(
        ledger.rows,
        ledger.order,
        next_active_row_keys,
    )
    ledger.rows = pruned_rows
    ledger.order = pruned_order
    ledger.active_row_keys = next_active_row_keys
    ledger.preview_text = event.preview_text
    ledger.capture_mode = "structured"

    live_rows = [
        LivePanelRow(
            key=row.key,
            text=row.text,
            node_key=row.node_key,
            speaker_color=row.speaker_color,
            speaker_channel=row.speaker_channel,
            updated_at=row.updated_at,
        )
        for key in next_active_row_keys
        if (row := ledger.rows.get(key))
    ]
    active_row_key = next_active_row_keys[-1] if next_active_row_keys else None
    active_row = (
        ledger.rows[active_row_key].clone()
        if active_row_key and active_row_key in ledger.rows
        else None
    )
    changed = (
        bool(row_changes)
        or ledger.preview_text != previous_preview_text
        or ledger.capture_mode != previous_capture_mode
        or not _same_key_order(ledger.active_row_keys, previous_active_row_keys)
    )
    return LiveCaptureReconciliation(
        ledger=ledger,
        changed=changed,
        row_changes=row_changes,
        live_rows=live_rows,
        active_row=active_row,
    )
