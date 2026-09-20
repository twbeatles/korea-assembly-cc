# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import threading
from pathlib import Path

from ui.main_window_common import *
from ui.main_window_common import _import_optional_module as _common_import_optional_module
from ui.main_window_types import MainWindowHost
from core.export_text import (
    format_srt_relative,
    format_vtt_relative,
    normalize_hwp_insert_text,
    resolve_cue_time_range,
    sanitize_document_text,
    sanitize_subtitle_cue_text,
)
from core.hwpx_export import save_hwpx_document
from core.file_io import canonical_path_key

from ui.main_window_impl.persistence_exports_dispatch import (
    ExportFailureHandled,
    MainWindowPersistenceExportsDispatchMixin,
)
from ui.main_window_impl.persistence_exports_documents import (
    MainWindowPersistenceExportsDocumentsMixin,
)
from ui.main_window_impl.persistence_exports_session import (
    MainWindowPersistenceExportsSessionMixin,
)
from ui.main_window_impl.persistence_exports_text import (
    MainWindowPersistenceExportsTextMixin,
)


class MainWindowPersistenceExportsMixin(
    MainWindowPersistenceExportsDispatchMixin,
    MainWindowPersistenceExportsTextMixin,
    MainWindowPersistenceExportsDocumentsMixin,
    MainWindowPersistenceExportsSessionMixin,
    MainWindowHost,
):
    """내보내기 퍼사드 (얇은 조합; 형식별 구현은 분리 mixin)."""
