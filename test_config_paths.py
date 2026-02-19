from pathlib import Path

from core.config import Config


def test_config_paths_are_absolute():
    path_fields = [
        "LOG_DIR",
        "SESSION_DIR",
        "REALTIME_DIR",
        "BACKUP_DIR",
        "PRESET_FILE",
        "URL_HISTORY_FILE",
        "DATABASE_PATH",
    ]
    for field in path_fields:
        value = Path(getattr(Config, field))
        assert value.is_absolute(), f"{field} must be absolute: {value}"


def test_config_paths_resolve_under_app_base_dir():
    base = Path(Config.APP_BASE_DIR).resolve()
    assert base.is_absolute()

    path_fields = [
        "LOG_DIR",
        "SESSION_DIR",
        "REALTIME_DIR",
        "BACKUP_DIR",
        "PRESET_FILE",
        "URL_HISTORY_FILE",
        "DATABASE_PATH",
    ]
    for field in path_fields:
        value = Path(getattr(Config, field)).resolve()
        assert value == base or base in value.parents, (
            f"{field} must be within app base dir: {value}"
        )
