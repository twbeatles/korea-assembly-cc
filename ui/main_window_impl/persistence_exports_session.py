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


class MainWindowPersistenceExportsSessionMixin(MainWindowHost):
    """세션 저장 진입점 (SRP: 세션 스냅샷 저장 요청)."""

    def _save_session(self):
            if self._is_background_shutdown_active():
                self._show_toast("종료 중이라 세션 저장을 시작할 수 없습니다.", "warning")
                return

            prepared_entries = self._build_persistent_entries_snapshot()
            runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
            has_subtitles = bool(prepared_entries) or bool(runtime_manifest)
            if not has_subtitles:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            if self._session_save_in_progress:
                self._show_toast("이미 세션 저장이 진행 중입니다.", "info")
                return

            try:
                path = self._choose_session_snapshot_path(dialog_title="세션 저장")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"세션 저장 경로 준비 실패: {e}")
                return
            if not path:
                return
            self._start_async_session_snapshot_save(
                path,
                prepared_entries,
                runtime_root=runtime_root,
                runtime_manifest=runtime_manifest,
            )
