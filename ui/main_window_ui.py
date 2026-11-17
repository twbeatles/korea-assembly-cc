# -*- coding: utf-8 -*-
"""Public UI facade for 국회 의사중계 자막 추출기 MainWindow.

The concrete UI responsibilities live under ``ui.main_window_impl.ui``.
This module keeps the historical import and monkeypatch surface stable.
"""

# explicit re-exports for test patch targets (were star-provided)
from ui.main_window_common import (
    Path as Path,
)
from ui.main_window_common import (
    QFileDialog as QFileDialog,
)
from ui.main_window_common import (
    QInputDialog as QInputDialog,
)
from ui.main_window_common import (
    QMessageBox as QMessageBox,
)
from ui.main_window_common import (
    utils as utils,
)
from ui.main_window_impl.ui import MainWindowUIMixin
