import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

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


def test_storage_resolution_uses_launch_argv_for_onefile_portable_flag(tmp_path):
    temp_child = tmp_path / "temp" / "subtitle.exe"
    launch_exe = tmp_path / "portable" / "subtitle.exe"
    temp_child.parent.mkdir()
    launch_exe.parent.mkdir()
    temp_child.write_text("", encoding="utf-8")
    launch_exe.write_text("", encoding="utf-8")
    (launch_exe.parent / "portable.flag").write_text("", encoding="utf-8")

    resolution = resolve_storage_resolution(
        frozen=True,
        executable=str(temp_child),
        argv0=str(launch_exe),
        localappdata=str(tmp_path / "localdata"),
    )

    assert resolution.storage_mode == "portable"
    assert resolution.storage_dir == launch_exe.parent
    assert resolution.portable_flag_path == launch_exe.parent / "portable.flag"


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


def _assert_storage_preflight_payload(payload: dict, target: Path) -> None:
    assert payload["ok"] is True
    assert payload["kind"] == "storage_preflight"
    assert payload["storage"]["storage_mode"] == "override"
    assert Path(payload["storage"]["storage_dir"]) == target.resolve()


def _assert_window_smoke_payload(payload: dict, target: Path) -> None:
    assert payload["ok"] is True
    assert payload["hwpx_ok"] is True
    assert payload["window_instantiated"] is True
    assert "국회 의사중계 자막 추출기" in payload["window_title"]
    assert payload["storage"]["storage_mode"] == "override"
    assert Path(payload["storage"]["storage_dir"]) == target.resolve()


def _subprocess_env_for_smoke() -> dict[str, str]:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    # Windows CI 코드페이지에서 한글 smoke JSON 이 stdout 에서 유실되지 않도록 고정
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _load_smoke_payload(
    *,
    stdout: str,
    stderr: str,
    output_file: Path | None = None,
) -> dict:
    """stdout / --smoke-output / stderr 순으로 smoke JSON 한 줄을 파싱한다."""
    if output_file is not None and output_file.is_file():
        text = output_file.read_text(encoding="utf-8").strip()
        if text:
            return json.loads(text.splitlines()[-1])
    for stream_text in (stdout, stderr):
        for line in reversed((stream_text or "").splitlines()):
            candidate = line.strip()
            if not candidate.startswith("{"):
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    raise AssertionError(
        "smoke JSON payload not found\n"
        f"stdout={stdout!r}\n"
        f"stderr={stderr!r}\n"
        f"output_file={output_file}"
    )


def test_entrypoint_storage_preflight_smoke_outputs_json_in_process(tmp_path):
    from tests.test_support.subprocess_compat import run_entrypoint_main

    target = tmp_path / "smoke-storage"
    exit_code, stdout = run_entrypoint_main(
        [
            "--smoke-storage-preflight",
            "--smoke-storage-dir",
            str(target),
        ]
    )

    assert exit_code == 0
    _assert_storage_preflight_payload(json.loads(stdout), target)


@pytest.mark.requires_subprocess
def test_entrypoint_storage_preflight_smoke_outputs_json_subprocess(tmp_path):
    target = tmp_path / "smoke-storage"
    smoke_output = tmp_path / "storage-smoke.json"
    env = _subprocess_env_for_smoke()
    result = subprocess.run(
        [
            sys.executable,
            "국회의사중계 자막.py",
            "--smoke-storage-preflight",
            "--smoke-storage-dir",
            str(target),
            "--smoke-output",
            str(smoke_output),
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    assert result.returncode == 0, (
        f"returncode={result.returncode}\n"
        f"stdout={result.stdout!r}\n"
        f"stderr={result.stderr!r}"
    )
    payload = _load_smoke_payload(
        stdout=result.stdout,
        stderr=result.stderr,
        output_file=smoke_output,
    )
    _assert_storage_preflight_payload(payload, target)


def test_entrypoint_smoke_instantiate_window_outputs_json_in_process(tmp_path, monkeypatch):
    from tests.test_support.subprocess_compat import run_entrypoint_main

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    target = tmp_path / "window-smoke-storage"
    exit_code, stdout = run_entrypoint_main(
        [
            "--smoke",
            "--smoke-instantiate-window",
            "--smoke-storage-dir",
            str(target),
        ]
    )

    assert exit_code == 0, stdout
    _assert_window_smoke_payload(json.loads(stdout), target)


@pytest.mark.requires_subprocess
def test_entrypoint_smoke_instantiate_window_outputs_json_subprocess(tmp_path):
    target = tmp_path / "window-smoke-storage"
    smoke_output = tmp_path / "window-smoke.json"
    env = _subprocess_env_for_smoke()
    result = subprocess.run(
        [
            sys.executable,
            "국회의사중계 자막.py",
            "--smoke",
            "--smoke-instantiate-window",
            "--smoke-storage-dir",
            str(target),
            "--smoke-output",
            str(smoke_output),
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    assert result.returncode == 0, (
        f"returncode={result.returncode}\n"
        f"stdout={result.stdout!r}\n"
        f"stderr={result.stderr!r}"
    )
    payload = _load_smoke_payload(
        stdout=result.stdout,
        stderr=result.stderr,
        output_file=smoke_output,
    )
    _assert_window_smoke_payload(payload, target)


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


def test_entrypoint_json_output_uses_utf8_buffer_when_codepage_rejects_korean(
    monkeypatch,
):
    """cp1252 등 레거시 stdout 에서도 한글 smoke JSON 이 유실되지 않아야 한다."""
    entrypoint = _load_entrypoint_module()
    buffer = io.BytesIO()

    class LegacyCodepageStdout:
        encoding = "cp1252"

        def __init__(self) -> None:
            self.buffer = buffer

        def write(self, text: str) -> int:
            # Windows 기본 코드페이지처럼 한글을 거부한다.
            text.encode(self.encoding)
            raise AssertionError("text write should fail before this for Korean")

        def flush(self) -> None:
            return None

    stdout = LegacyCodepageStdout()
    stderr = io.StringIO()
    monkeypatch.setattr(entrypoint.sys, "stdout", stdout)
    monkeypatch.setattr(entrypoint.sys, "stderr", stderr)

    entrypoint._print_json_line(
        {
            "ok": True,
            "window_title": "국회 의사중계 자막 추출기 v16.14.8",
        }
    )

    raw = buffer.getvalue().decode("utf-8").strip()
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert "국회" in payload["window_title"]
    assert stderr.getvalue() == ""


def test_merge_and_streaming_config_defaults():
    assert Config.ENTRY_MERGE_MAX_GAP == 5
    assert Config.ENTRY_MERGE_MAX_CHARS == 300
    assert Config.CONFIRMED_COMPACT_MAX_LEN == 50000
    assert Config.MERGE_DEDUP_TIME_BUCKET_SECONDS == 30
