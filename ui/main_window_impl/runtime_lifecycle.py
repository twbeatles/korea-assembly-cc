# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from core.config import Config
from core.live_capture import create_empty_live_capture_ledger
from core.logging_utils import logger
from core.subtitle_pipeline import create_empty_capture_state, finalize_session
from core.selector_policy import validate_subtitle_selector
from core.url_policy import validate_assembly_url
from ui.main_window_impl.contracts import RuntimeHost

from ui.main_window_impl.runtime_lifecycle_background import (
    MainWindowRuntimeLifecycleBackgroundMixin,
)
from ui.main_window_impl.runtime_lifecycle_common import (
    RuntimeLifecycleBase,
    _main_window_public,
)
from ui.main_window_impl.runtime_lifecycle_detached import (
    MainWindowRuntimeLifecycleDetachedMixin,
)
from ui.main_window_impl.runtime_lifecycle_extraction import (
    MainWindowRuntimeLifecycleExtractionMixin,
)
from ui.main_window_impl.runtime_lifecycle_shutdown import (
    MainWindowRuntimeLifecycleShutdownMixin,
)
from ui.main_window_impl.runtime_lifecycle_stop import (
    MainWindowRuntimeLifecycleStopMixin,
)


class MainWindowRuntimeLifecycleMixin(
    MainWindowRuntimeLifecycleExtractionMixin,
    MainWindowRuntimeLifecycleStopMixin,
    MainWindowRuntimeLifecycleDetachedMixin,
    MainWindowRuntimeLifecycleBackgroundMixin,
    MainWindowRuntimeLifecycleShutdownMixin,
    RuntimeLifecycleBase,
):
    """런타임 라이프사이클 퍼사드 (얇은 조합; 시작/중지/종료 분리)."""
