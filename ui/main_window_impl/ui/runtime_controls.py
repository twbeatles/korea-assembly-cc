# -*- coding: utf-8 -*-

from __future__ import annotations

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowUIRuntimeControlsMixin(MainWindowHost):
    def _reset_ui(self):
            self.is_running = False
            self._close_realtime_save_file()
            self._reset_realtime_save_run_state()
            self._initial_recovery_snapshot_done = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.url_combo.setEnabled(True)
            self.selector_combo.setEnabled(True)
            self.progress.hide()
            self.stats_timer.stop()
            self.backup_timer.stop()
            self._sync_runtime_action_state()


