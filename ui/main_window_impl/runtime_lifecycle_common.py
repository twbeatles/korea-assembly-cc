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

def _main_window_public():
    return import_module("ui.main_window")


RuntimeLifecycleBase = RuntimeHost if TYPE_CHECKING else object
