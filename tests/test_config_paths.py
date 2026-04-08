from pathlib import Path

from core.config import Config, resolve_storage_resolution, run_storage_preflight


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
    ok, error = run_storage_preflight(
        tmp_path / "storage",
        settings_ini_path=tmp_path / "storage" / "settings.ini",
    )

    assert ok is True
    assert error == ""
    assert (tmp_path / "storage" / "logs").exists()
    assert (tmp_path / "storage" / "sessions").exists()


def test_storage_preflight_returns_failure_details_when_probe_write_fails(
    tmp_path, monkeypatch
):
    def fail_write(self, *_args, **_kwargs):
        raise OSError("probe denied")

    monkeypatch.setattr(Path, "write_text", fail_write)

    ok, error = run_storage_preflight(tmp_path / "storage")

    assert ok is False
    assert "probe denied" in error


def test_merge_and_streaming_config_defaults():
    assert Config.ENTRY_MERGE_MAX_GAP == 5
    assert Config.ENTRY_MERGE_MAX_CHARS == 300
    assert Config.CONFIRMED_COMPACT_MAX_LEN == 50000
    assert Config.MERGE_DEDUP_TIME_BUCKET_SECONDS == 30
