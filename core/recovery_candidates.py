from __future__ import annotations

from dataclasses import dataclass
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.config import Config
from core.file_io import canonical_path_key, read_limited_json_file
from core.runtime_archive_owner import is_archive_owner_alive
from core.resource_budget import ResourceLimitExceeded


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


def _resolve_candidate_resource(root: Path, name: str) -> Path:
    relative = Path(name)
    if not name or relative.anchor:
        raise ValueError("recovery resource must use a relative path")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("recovery resource is outside the archive") from exc
    return resolved


def inspect_recovery_candidate(
    path: str | Path,
    *,
    snapshot_type: str = "session",
    cancel_check: Callable[[], bool] | None = None,
    consume_bytes: Callable[[int], None] | None = None,
) -> RecoveryCandidate:
    candidate_path = Path(path).resolve()
    warnings: list[str] = []
    created_at = ""
    entry_count = 0
    source_url = ""
    integrity = "valid"
    def read_candidate(file_path: Path, label: str) -> object:
        if consume_bytes is not None:
            consume_bytes(file_path.stat().st_size)
        return read_limited_json_file(
            file_path, max_bytes=int(Config.SESSION_RESOURCE_PER_FILE_MAX_BYTES),
            label=label, cancel_check=cancel_check,
        )
    try:
        raw = read_candidate(candidate_path, f"recovery {snapshot_type}")
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
                if cancel_check is not None and cancel_check():
                    raise ResourceLimitExceeded("cancelled", limit=None, observed=None, label="recovery scan")
                if not isinstance(item, dict):
                    warnings.append("invalid segment metadata")
                    continue
                entry_count += max(0, int(item.get("entry_count", 0) or 0))
                relative_path = str(item.get("path", "") or "")
                segment_path = _resolve_candidate_resource(candidate_path.parent, relative_path)
                if not segment_path.is_file():
                    warnings.append(f"missing segment: {relative_path or '<empty>'}")
            tail_name = str(
                raw.get("tail_checkpoint", "tail_checkpoint.json")
                or "tail_checkpoint.json"
            )
            tail_path = _resolve_candidate_resource(candidate_path.parent, tail_name)
            if tail_path.is_file():
                try:
                    tail = read_candidate(tail_path, "recovery tail")
                    if isinstance(tail, dict):
                        tail_count = tail.get("entry_count")
                        if tail_count is None and isinstance(tail.get("subtitles"), list):
                            tail_count = len(tail["subtitles"])
                        entry_count += max(0, int(tail_count or 0))
                except ResourceLimitExceeded as exc:
                    if exc.resource in {"cancelled", "total_bytes"}:
                        raise
                    warnings.append(f"invalid tail: {exc}")
                except Exception as exc:
                    warnings.append(f"invalid tail: {exc}")
            else:
                warnings.append(f"missing tail: {tail_name}")
        else:
            subtitles = raw.get("subtitles", [])
            if not isinstance(subtitles, list):
                raise ValueError("session subtitles is not a list")
            entry_count = len(subtitles)
    except ResourceLimitExceeded as exc:
        if exc.resource in {"cancelled", "total_bytes"}:
            raise
        integrity = "invalid"
        warnings.append(str(exc))
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
    cancel_check: Callable[[], bool] | None = None,
    progress: Callable[[int], None] | None = None,
    max_candidates: int = 1000,
    max_total_bytes: int = 256 * 1024 * 1024,
    max_paths: int = 10_000,
) -> list[RecoveryCandidate]:
    specs: list[tuple[Path, str]] = []
    total_bytes = 0
    def check_cancelled() -> None:
        if cancel_check is not None and cancel_check():
            raise ResourceLimitExceeded("cancelled", limit=None, observed=None, label="recovery scan")
    def consume_bytes(size: int) -> None:
        nonlocal total_bytes
        check_cancelled()
        total_bytes += size
        if total_bytes > max_total_bytes:
            raise ResourceLimitExceeded("total_bytes", limit=max_total_bytes, observed=total_bytes, label="recovery scan")
    def add_spec(path: Path, kind: str) -> None:
        check_cancelled()
        specs.append((path, kind))
        if len(specs) > max_candidates:
            raise ResourceLimitExceeded("candidates", limit=max_candidates, observed=len(specs), label="recovery scan")
    check_cancelled()
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
                    add_spec(Path(target), str(state.get("snapshot_type", "session") or "session"))
        except ResourceLimitExceeded as exc:
            if exc.resource in {"cancelled", "candidates"}:
                raise
        except Exception:
            pass

    backup_root = Path(backup_dir)
    if backup_root.is_dir():
        for path in backup_root.glob("backup_*.json"):
            add_spec(path, "backup")
    runtime_root = Path(runtime_session_dir)
    if runtime_root.is_dir():
        visited = 0
        for directory, dirs, files in os.walk(runtime_root, followlinks=False):
            check_cancelled()
            visited += 1 + len(dirs) + len(files)
            if visited > max_paths:
                raise ResourceLimitExceeded("paths", limit=max_paths, observed=visited, label="recovery scan")
            if "manifest.json" not in files:
                continue
            path = Path(directory) / "manifest.json"
            try:
                if is_archive_owner_alive(path.parent):
                    continue
            except Exception:
                pass
            add_spec(path, "runtime_manifest")

    unique: dict[str, tuple[Path, str]] = {}
    for path, snapshot_type in specs:
        if not path.is_file():
            continue
        unique.setdefault(canonical_path_key(path), (path, snapshot_type))

    candidates = []
    for index, (path, snapshot_type) in enumerate(unique.values(), 1):
        check_cancelled()
        candidates.append(inspect_recovery_candidate(
            path, snapshot_type=snapshot_type, cancel_check=cancel_check,
            consume_bytes=consume_bytes,
        ))
        if progress is not None:
            progress(index)
    candidates.sort(
        key=lambda candidate: _timestamp(candidate.created_at, candidate.path),
        reverse=True,
    )
    return candidates[: int(Config.RECOVERY_CANDIDATE_MAX)]
