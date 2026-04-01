# -*- coding: utf-8 -*-

from __future__ import annotations

from core.live_capture_impl.models import LiveCaptureLedger, LiveCaptureRow, LivePanelRow


LIVE_LEDGER_MAX_ROWS = 300


def create_empty_live_capture_ledger() -> LiveCaptureLedger:
    return LiveCaptureLedger()


def clear_live_capture_ledger() -> LiveCaptureLedger:
    return create_empty_live_capture_ledger()


def _same_key_order(left: list[str], right: list[str]) -> bool:
    return len(left) == len(right) and all(
        left_item == right_item for left_item, right_item in zip(left, right)
    )


def prune_live_capture_rows(
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
    pruned_rows, pruned_order = prune_live_capture_rows(
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


def get_live_row(ledger: LiveCaptureLedger, key: str) -> LiveCaptureRow | None:
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
