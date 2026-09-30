# -*- coding: utf-8 -*-

from __future__ import annotations

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowUIRuntimeControlsMixin(MainWindowHost):
    def _apply_capture_controls_state(self, running: bool) -> None:
            """수집 시작/중지에 따라 컨트롤·창 제목·시작 버튼 라벨을 한 번에 맞춘다."""
            self.start_btn.setEnabled(not running)
            self.stop_btn.setEnabled(running)
            self.url_combo.setEnabled(not running)
            self.selector_combo.setEnabled(not running)
            self.start_btn.setText(
                CAPTURE_RUNNING_BUTTON_TEXT if running else CAPTURE_START_BUTTON_TEXT
            )
            set_state_property(self.start_btn, "capturing", "true" if running else "false")
            self._update_capture_window_title(running)

    def _update_capture_window_title(self, running: bool) -> None:
            """작업 표시줄에서도 수집 중인지 알 수 있도록 창 제목에 상태를 표시한다."""
            base_title = f"{Config.APP_NAME} v{Config.VERSION}"
            title = base_title
            if running:
                committee = ""
                try:
                    committee = self._get_capture_source_committee(fallback_to_url=False)
                except Exception:
                    committee = ""
                label = f"● 수집 중 · {committee}" if committee else "● 수집 중"
                title = f"{label} — {base_title}"
            try:
                if self.windowTitle() != title:
                    self.setWindowTitle(title)
            except Exception:
                pass

    def _build_capture_summary_text(self) -> str:
            """중지/완료 상태 메시지용 수집 요약 (예: '12문장 · 3,456자 · 00:10:05')."""
            try:
                count = int(self._get_global_subtitle_count())
                chars = int(self._get_global_total_chars())
                elapsed = int(self._get_capture_elapsed_seconds())
            except Exception:
                return ""
            h, r = divmod(max(0, elapsed), 3600)
            m, sec = divmod(r, 60)
            return f"{count:,}문장 · {chars:,}자 · {h:02d}:{m:02d}:{sec:02d}"

    def _reset_ui(self):
            self.is_running = False
            self._close_realtime_save_file()
            self._reset_realtime_save_run_state()
            self._initial_recovery_snapshot_done = False
            # 중지 후에는 실행 시간이 계속 늘어나지 않도록 종료 시각을 고정한다.
            if self.__dict__.get("start_time") and not self.__dict__.get(
                "_capture_end_time"
            ):
                self._capture_end_time = time.time()
            self._apply_capture_controls_state(False)
            self.progress.hide()
            self.stats_timer.stop()
            self.backup_timer.stop()
            scroll_btn = self.__dict__.get("scroll_to_bottom_btn")
            if scroll_btn is not None:
                scroll_btn.hide()
            self._sync_runtime_action_state()
            self._update_stats_now()
