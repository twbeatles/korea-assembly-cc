# -*- coding: utf-8 -*-

"""Config implementation package (version/storage/app_config)."""

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

__all__ = [
    "Config",
    "StorageResolution",
    "_STORAGE_RESOLUTION",
    "_load_version_from_readme",
    "_resolve_existing_file_path",
    "_resolve_install_dir",
    "_resolve_local_appdata_dir",
    "build_storage_preflight_targets",
    "resolve_storage_resolution",
]
