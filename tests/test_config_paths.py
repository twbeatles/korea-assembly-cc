import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import core.config as config_mod
from core.config import Config, resolve_storage_resolution, run_storage_preflight


def _load_entrypoint_module():
    module_path = Path("국회의사중계 자막.py").resolve()
    spec = importlib.util.spec_from_file_location(
        "assembly_subtitle_entrypoint_for_test",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_config_paths_are_absolute():
    path_fields = [
        "LOG_DIR",
        "SESSION_DIR",
        "REALTIME_DIR",
        "BACKUP_DIR",
        "PRESET_FILE",
        "URL_HISTORY_FILE",
        "RECOVERY_STATE_FILE",
        "DATABASE_PATH",
    ]
    for field in path_fields:
        value = Path(getattr(Config, field))
        assert value.is_absolute(), f"{field} must be absolute: {value}"


def test_config_paths_resolve_under_app_base_dir():
    base = Path(Config.STORAGE_DIR).resolve()
    assert base.is_absolute()

    path_fields = [
        "LOG_DIR",
        "SESSION_DIR",
        "REALTIME_DIR",
        "BACKUP_DIR",
        "PRESET_FILE",
        "URL_HISTORY_FILE",
        "RECOVERY_STATE_FILE",
        "DATABASE_PATH",
    ]
    for field in path_fields:
        value = Path(getattr(Config, field)).resolve()
        assert value == base or base in value.parents, (
            f"{field} must be within storage dir: {value}"
        )


def test_storage_resolution_uses_install_dir_in_development(tmp_path):
    resolution = resolve_storage_resolution(
        frozen=False,
        module_file=str(tmp_path / "core" / "config.py"),
    )

    assert resolution.storage_mode == "development"
    assert resolution.storage_dir == tmp_path


def test_storage_resolution_uses_localappdata_for_default_frozen(tmp_path):
    resolution = resolve_storage_resolution(
        frozen=True,
        executable=str(tmp_path / "app" / "subtitle.exe"),
        portable_flag_exists=False,
        localappdata=str(tmp_path / "localdata"),
    )

    assert resolution.storage_mode == "localappdata"
    assert resolution.storage_dir == (tmp_path / "localdata" / "AssemblySubtitle" / "Extractor")


def test_storage_resolution_uses_portable_flag_when_present(tmp_path):
    resolution = resolve_storage_resolution(
        frozen=True,
        executable=str(tmp_path / "portable" / "subtitle.exe"),
        portable_flag_exists=True,
    )

    assert resolution.storage_mode == "portable"
    assert resolution.storage_dir == (tmp_path / "portable")
    assert resolution.settings_ini_path == (tmp_path / "portable" / "settings.ini")


def test_storage_preflight_creates_required_directories(tmp_path):
    db_path = tmp_path / "storage" / "subtitle_history.db"
    ok, error = run_storage_preflight(
        tmp_path / "storage",
        settings_ini_path=tmp_path / "storage" / "settings.ini",
        database_path=db_path,
    )

    assert ok is True
    assert error == ""
    assert (tmp_path / "storage" / "logs").exists()
    assert (tmp_path / "storage" / "sessions").exists()
    assert db_path.exists()


def test_storage_preflight_checks_portable_settings_file_surface(tmp_path, monkeypatch):
    probed_paths: list[Path] = []

    def record_probe(path, *, sample_text):
        probed_paths.append(Path(path).resolve())
        assert sample_text

    monkeypatch.setattr(config_mod, "_probe_writable_file_surface", record_probe)
    monkeypatch.setattr(config_mod, "_probe_sqlite_database_surface", lambda *_args: None)

    settings_ini = tmp_path / "storage" / "settings.ini"
    ok, error = run_storage_preflight(
        tmp_path / "storage",
        settings_ini_path=settings_ini,
        database_path=tmp_path / "storage" / "subtitle_history.db",
    )

    assert ok is True
    assert error == ""
    assert settings_ini.resolve() in probed_paths


def test_storage_preflight_returns_failure_details_when_probe_write_fails(
    tmp_path, monkeypatch
):
    def fail_probe(*_args, **_kwargs):
        raise OSError("probe denied")

    monkeypatch.setattr(config_mod, "_probe_writable_file_surface", fail_probe)

    ok, error = run_storage_preflight(tmp_path / "storage")

    assert ok is False
    assert "probe denied" in error


def test_storage_preflight_returns_failure_details_when_db_probe_fails(
    tmp_path, monkeypatch
):
    def fail_db_probe(*_args, **_kwargs):
        raise OSError("wal denied")

    monkeypatch.setattr(config_mod, "_probe_sqlite_database_surface", fail_db_probe)

    ok, error = run_storage_preflight(tmp_path / "storage")

    assert ok is False
    assert "wal denied" in error
    assert "subtitle_history.db" in error


def test_entrypoint_storage_preflight_smoke_outputs_json(tmp_path):
    target = tmp_path / "smoke-storage"
    result = subprocess.run(
        [
            sys.executable,
            "국회의사중계 자막.py",
            "--smoke-storage-preflight",
            "--smoke-storage-dir",
            str(target),
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    assert payload["kind"] == "storage_preflight"
    assert payload["storage"]["storage_mode"] == "override"
    assert Path(payload["storage"]["storage_dir"]) == target.resolve()


def test_entrypoint_smoke_instantiate_window_outputs_json(tmp_path):
    target = tmp_path / "window-smoke-storage"
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [
            sys.executable,
            "국회의사중계 자막.py",
            "--smoke",
            "--smoke-instantiate-window",
            "--smoke-storage-dir",
            str(target),
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    assert payload["window_instantiated"] is True
    assert "국회 의사중계 자막 추출기" in payload["window_title"]
    assert payload["storage"]["storage_mode"] == "override"
    assert Path(payload["storage"]["storage_dir"]) == target.resolve()


def test_entrypoint_json_output_prefers_working_stdout(monkeypatch):
    entrypoint = _load_entrypoint_module()
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(entrypoint.sys, "stdout", stdout)
    monkeypatch.setattr(entrypoint.sys, "stderr", stderr)

    entrypoint._print_json_line({"ok": True})

    assert json.loads(stdout.getvalue()) == {"ok": True}
    assert stderr.getvalue() == ""


def test_entrypoint_json_output_falls_back_when_stdout_is_invalid(monkeypatch):
    entrypoint = _load_entrypoint_module()
    stderr = io.StringIO()

    class BrokenStream:
        def write(self, _text):
            raise OSError(22, "Invalid argument")

        def flush(self):
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(entrypoint.sys, "stdout", BrokenStream())
    monkeypatch.setattr(entrypoint.sys, "stderr", stderr)

    entrypoint._print_json_line({"ok": True})

    assert json.loads(stderr.getvalue()) == {"ok": True}


def test_merge_and_streaming_config_defaults():
    assert Config.ENTRY_MERGE_MAX_GAP == 5
    assert Config.ENTRY_MERGE_MAX_CHARS == 300
    assert Config.CONFIRMED_COMPACT_MAX_LEN == 50000
    assert Config.MERGE_DEDUP_TIME_BUCKET_SECONDS == 30
