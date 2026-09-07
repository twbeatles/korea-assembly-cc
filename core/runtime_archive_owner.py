from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from core.file_io import atomic_write_json
from core.process_wait import is_process_alive

OWNER_FILENAME = "owner.json"


def write_owner_file(
    archive_dir: str | Path,
    *,
    pid: int,
    token: str,
    run_id: int | None = None,
) -> Path:
    root = Path(archive_dir)
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    payload: dict[str, object] = {
        "pid": int(pid),
        "token": str(token or ""),
        "started_at": now,
        "heartbeat_at": now,
    }
    if run_id is not None:
        payload["run_id"] = int(run_id)
    path = root / OWNER_FILENAME
    atomic_write_json(path, payload, ensure_ascii=False)
    return path


def release_owner_file(archive_dir: str | Path) -> None:
    path = Path(archive_dir) / OWNER_FILENAME
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def read_owner_file(archive_dir: str | Path) -> dict[str, object] | None:
    path = Path(archive_dir) / OWNER_FILENAME
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def is_archive_owner_alive(
    archive_dir: str | Path,
    *,
    alive_impl: Callable[[int], bool] | None = None,
) -> bool:
    payload = read_owner_file(archive_dir)
    if payload is None:
        return False
    raw_pid = payload.get("pid", 0)
    try:
        if isinstance(raw_pid, bool) or not isinstance(raw_pid, (int, str)):
            return False
        pid = int(raw_pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if alive_impl is not None:
        try:
            return bool(alive_impl(pid))
        except Exception:
            return True
    return is_process_alive(pid)
