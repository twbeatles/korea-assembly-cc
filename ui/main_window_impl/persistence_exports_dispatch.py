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


class ExportFailureHandled(Exception):
    """UI 다이얼로그 등으로 이미 처리됨 — 백그라운드 에러 토스트를 생략한다."""


class MainWindowPersistenceExportsDispatchMixin(MainWindowHost):
    """저장 디스패치·공통 (SRP: 백그라운드 저장 실행/중복 방지)."""

    def _import_optional_module(self, module_name: str) -> Any:
            persistence_module = sys.modules.get("ui.main_window_persistence")
            helper = getattr(persistence_module, "_import_optional_module", None)
            if callable(helper):
                return helper(module_name)
            return _common_import_optional_module(module_name)

    def _ensure_file_save_registry(self) -> None:
            state = self.__dict__
            if state.get("_file_save_paths_lock") is None:
                self._file_save_paths_lock = threading.Lock()
            if state.get("_file_save_in_progress") is None:
                self._file_save_in_progress = set()

    def _save_in_background(
            self,
            save_func: Callable[[str], None],
            path: str,
            success_msg: str,
            error_prefix: str,
        ) -> None:
            """백그라운드에서 파일 저장 (자막 수집 중단 없이)

            Args:
                save_func: 실제 저장을 수행하는 함수 (path를 인자로 받음)
                path: 저장할 파일 경로
                success_msg: 성공 시 토스트 메시지
                error_prefix: 실패 시 에러 메시지 접두어
            """
            self._ensure_file_save_registry()
            path_key = canonical_path_key(path)

            with self._file_save_paths_lock:
                if path_key in self._file_save_in_progress:
                    self._show_toast(
                        f"이미 저장 중입니다: {Path(path).name}",
                        "warning",
                        2500,
                    )
                    return
                self._file_save_in_progress.add(path_key)

            def background_save():
                try:
                    save_func(path)
                    # UI 스레드로 안전하게 전달 (Queue 기반)
                    self._emit_control_message(
                        "toast",
                        {"message": success_msg, "toast_type": "success"},
                    )
                except ExportFailureHandled:
                    # HWP 실패 다이얼로그 등 — 에러 토스트 중복 방지
                    return
                except Exception as e:
                    logger.error(f"{error_prefix}: {e}")
                    self._emit_control_message(
                        "toast",
                        {
                            "message": f"{error_prefix}: {e}",
                            "toast_type": "error",
                            "duration": 5000,
                        },
                    )
                finally:
                    try:
                        with self._file_save_paths_lock:
                            self._file_save_in_progress.discard(path_key)
                    except Exception:
                        pass

            started = self._start_background_thread(background_save, "FileSaveWorker")
            if not started:
                with self._file_save_paths_lock:
                    self._file_save_in_progress.discard(path_key)
                self._show_toast("종료 중이라 새 저장 작업을 시작할 수 없습니다.", "warning")
                return

            # 저장 시작 알림 (즉시)
            self._show_toast(f"💾 저장 중... ({Path(path).name})", "info", 1500)

    def _get_accumulated_text(self):
            with self.subtitle_lock:
                return "\n".join(
                    text
                    for text in (
                        self._normalize_subtitle_text_for_option(s.text)
                        for s in self.subtitles
                    )
                    if text
                )
