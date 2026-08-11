from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import Config
from core.file_io import canonical_path_key, read_limited_json_file


@dataclass(frozen=True, slots=True)
class RecoveryCandidate:
    path: Path
    snapshot_type: str
    created_at: str
    entry_count: int
    source_url: str
    integrity: str
    warnings: tuple[str, ...] = ()


def _timestamp(value: str, path: Path) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError):
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0


def inspect_recovery_candidate(
    path: str | Path,
    *,
    snapshot_type: str = "session",
) -> RecoveryCandidate:
    candidate_path = Path(path).resolve()
    warnings: list[str] = []
    created_at = ""
    entry_count = 0
    source_url = ""
    integrity = "valid"
    try:
        raw = read_limited_json_file(
            candidate_path,
            max_bytes=int(Config.SESSION_RESOURCE_PER_FILE_MAX_BYTES),
            label=f"recovery {snapshot_type}",
        )
        if not isinstance(raw, dict):
            raise ValueError("recovery root is not an object")
        created_at = str(raw.get("created", raw.get("created_at", "")) or "")
        source_url = str(raw.get("url", "") or "")
        if str(raw.get("format", "") or "") == "runtime_session_manifest_v1":
            snapshot_type = "runtime_manifest"
            segments = raw.get("segments", [])
            if not isinstance(segments, list):
                raise ValueError("runtime segments is not a list")
            for item in segments:
                if not isinstance(item, dict):
                    warnings.append("invalid segment metadata")
                    continue
                entry_count += max(0, int(item.get("entry_count", 0) or 0))
                relative_path = str(item.get("path", "") or "")
                if not relative_path or not (candidate_path.parent / relative_path).is_file():
                    warnings.append(f"missing segment: {relative_path or '<empty>'}")
            tail_name = str(
                raw.get("tail_checkpoint", "tail_checkpoint.json")
                or "tail_checkpoint.json"
            )
            tail_path = candidate_path.parent / tail_name
            if tail_path.is_file():
                try:
                    tail = read_limited_json_file(
                        tail_path,
                        max_bytes=int(Config.SESSION_RESOURCE_PER_FILE_MAX_BYTES),
                        label="recovery tail",
                    )
                    if isinstance(tail, dict):
                        tail_count = tail.get("entry_count")
                        if tail_count is None and isinstance(tail.get("subtitles"), list):
                            tail_count = len(tail["subtitles"])
                        entry_count += max(0, int(tail_count or 0))
                except Exception as exc:
                    warnings.append(f"invalid tail: {exc}")
            else:
                warnings.append(f"missing tail: {tail_name}")
        else:
            subtitles = raw.get("subtitles", [])
            if not isinstance(subtitles, list):
                raise ValueError("session subtitles is not a list")
            entry_count = len(subtitles)
    except Exception as exc:
        integrity = "invalid"
        warnings.append(str(exc))
    else:
        if warnings:
            integrity = "warning"

    return RecoveryCandidate(
        path=candidate_path,
        snapshot_type=str(snapshot_type or "session"),
        created_at=created_at,
        entry_count=entry_count,
        source_url=source_url,
        integrity=integrity,
        warnings=tuple(warnings),
    )


def discover_recovery_candidates(
    *,
    recovery_state_file: str | Path,
    backup_dir: str | Path,
    runtime_session_dir: str | Path,
) -> list[RecoveryCandidate]:
    specs: list[tuple[Path, str]] = []
    state_path = Path(recovery_state_file)
    if state_path.is_file():
        try:
            state = read_limited_json_file(
                state_path,
                max_bytes=int(Config.URL_HISTORY_MAX_BYTES),
                label="recovery pointer",
            )
            if isinstance(state, dict):
                target = str(state.get("path", "") or "").strip()
                if target and Path(target).is_file():
                    specs.append(
                        (Path(target), str(state.get("snapshot_type", "session") or "session"))
                    )
        except Exception:
            pass

    backup_root = Path(backup_dir)
    if backup_root.is_dir():
        specs.extend((path, "backup") for path in backup_root.glob("backup_*.json"))
    runtime_root = Path(runtime_session_dir)
    if runtime_root.is_dir():
        specs.extend((path, "runtime_manifest") for path in runtime_root.rglob("manifest.json"))

    unique: dict[str, tuple[Path, str]] = {}
    for path, snapshot_type in specs:
        if not path.is_file():
            continue
        unique.setdefault(canonical_path_key(path), (path, snapshot_type))

    candidates = [
        inspect_recovery_candidate(path, snapshot_type=snapshot_type)
        for path, snapshot_type in unique.values()
    ]
    candidates.sort(
        key=lambda candidate: _timestamp(candidate.created_at, candidate.path),
        reverse=True,
    )
    return candidates[: int(Config.RECOVERY_CANDIDATE_MAX)]
