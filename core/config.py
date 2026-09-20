# -*- coding: utf-8 -*-

"""프로그램 설정 (SOLID 분할 후 얇은 퍼사드).

버전/경로 계산/상수는 `core.config_impl` 패키지가 소유한다.
저장소 preflight(probe + runner)는 테스트의 `core.config._probe_*`
monkeypatch 계약을 보존하기 위해 이 퍼사드가 직접 소유한다.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from uuid import uuid4

from core.config_impl.app_config import Config, _STORAGE_RESOLUTION
from core.config_impl.storage import (
    StorageResolution,
    _resolve_existing_file_path,
    _resolve_install_dir,
    _resolve_local_appdata_dir,
    build_storage_preflight_targets,
    resolve_storage_resolution,
)
from core.config_impl.version import _load_version_from_readme

def _probe_writable_file_surface(target_path: str | Path, *, sample_text: str) -> None:
    path = Path(target_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.write_text(sample_text, encoding="utf-8")
        path.unlink(missing_ok=True)
        return

    with path.open("r+b") as handle:
        original_size = path.stat().st_size
        if original_size > 0:
            handle.seek(0)
            first_byte = handle.read(1)
            handle.seek(0)
            handle.write(first_byte)
            handle.flush()
            os.fsync(handle.fileno())
            return

        handle.write(b" ")
        handle.truncate(0)
        handle.flush()
        os.fsync(handle.fileno())


def _probe_sqlite_database_surface(database_path: str | Path) -> None:
    path = Path(database_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    probe_table = f"__storage_preflight_{uuid4().hex}"
    transaction_started = False
    try:
        journal_mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        journal_value = str(journal_mode[0] if journal_mode else "").strip().lower()
        if journal_value != "wal":
            raise RuntimeError(f"journal_mode=WAL 적용 실패 (actual={journal_value or 'unknown'})")

        conn.execute("BEGIN IMMEDIATE")
        transaction_started = True
        conn.execute(f'CREATE TABLE "{probe_table}" (id INTEGER PRIMARY KEY, note TEXT)')
        conn.execute(
            f'INSERT INTO "{probe_table}" (note) VALUES (?)',
            ("storage-preflight",),
        )
        conn.execute("ROLLBACK")
        transaction_started = False
    finally:
        if transaction_started:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        conn.close()


def run_storage_preflight(
    storage_dir: str | Path,
    *,
    settings_ini_path: str | Path | None = None,
    database_path: str | Path | None = None,
    preset_file: str | Path | None = None,
    url_history_file: str | Path | None = None,
    recovery_state_file: str | Path | None = None,
) -> tuple[bool, str]:
    """필수 저장소 경로 생성/쓰기 가능 여부를 검증한다."""
    failing_path = ""
    root = Path(storage_dir).resolve()
    preset_path = Path(preset_file).resolve() if preset_file else root / "committee_presets.json"
    url_history_path = (
        Path(url_history_file).resolve() if url_history_file else root / "url_history.json"
    )
    recovery_path = (
        Path(recovery_state_file).resolve()
        if recovery_state_file
        else root / "session_recovery.json"
    )
    settings_path = Path(settings_ini_path).resolve() if settings_ini_path else None
    db_path = Path(database_path).resolve() if database_path else root / "subtitle_history.db"
    try:
        for target_dir in build_storage_preflight_targets(storage_dir, settings_ini_path):
            failing_path = str(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            probe_path = target_dir / ".storage_probe"
            probe_path.write_text("ok", encoding="utf-8")
            probe_path.unlink(missing_ok=True)
        file_surfaces = [
            (preset_path, '{"presets": {}, "custom": {}}\n'),
            (url_history_path, "{}\n"),
            (recovery_path, "{}\n"),
        ]
        if settings_path is not None:
            file_surfaces.append((settings_path, "[General]\n"))
        for path, sample_text in file_surfaces:
            failing_path = str(path)
            _probe_writable_file_surface(path, sample_text=sample_text)
        failing_path = str(db_path)
        _probe_sqlite_database_surface(db_path)
        return True, ""
    except Exception as exc:
        return False, f"{failing_path}\n{exc}"

__all__ = [
    "Config",
    "StorageResolution",
    "_STORAGE_RESOLUTION",
    "_load_version_from_readme",
    "_probe_sqlite_database_surface",
    "_probe_writable_file_surface",
    "_resolve_existing_file_path",
    "_resolve_install_dir",
    "_resolve_local_appdata_dir",
    "build_storage_preflight_targets",
    "resolve_storage_resolution",
    "run_storage_preflight",
]
