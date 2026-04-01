# -*- coding: utf-8 -*-

from __future__ import annotations

from core import utils
from core.live_capture_impl.ledger import (
    _same_key_order,
    prune_live_capture_rows,
    set_fallback_capture_preview,
)
from core.live_capture_impl.models import (
    LiveCaptureLedger,
    LiveCaptureReconciliation,
    LiveCaptureRow,
    LivePanelRow,
    LiveRowChange,
    NormalizedCaptureEvent,
    build_live_row_key,
)
from core.models import ObservedSubtitleRow


def normalize_capture_event(
    *,
    raw: str = "",
    rows: list[ObservedSubtitleRow] | None = None,
    selector: str = "",
    frame_path: tuple[int, ...] | list[int] | None = None,
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

    pruned_rows, pruned_order = prune_live_capture_rows(
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
