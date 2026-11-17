# -*- coding: utf-8 -*-

# explicit re-exports for test patch targets (were star-provided)
from collections.abc import Iterable
from typing import cast

from core.resource_budget import ResourceBudget, ResourceBudgetLimits
from ui.main_window_common import (
    QInputDialog as QInputDialog,
)
from ui.main_window_impl.database_dialogs_base import (
    MainWindowDatabaseDialogsBaseMixin,
)
from ui.main_window_impl.database_dialogs_history import (
    MainWindowDatabaseDialogsHistoryMixin,
)
from ui.main_window_impl.database_dialogs_search import (
    MainWindowDatabaseDialogsSearchMixin,
)
from ui.main_window_impl.database_dialogs_stats_merge import (
    MainWindowDatabaseDialogsStatsMergeMixin,
)
from ui.main_window_types import MainWindowHost


class MainWindowDatabaseDialogsMixin(
    MainWindowDatabaseDialogsBaseMixin,
    MainWindowDatabaseDialogsHistoryMixin,
    MainWindowDatabaseDialogsSearchMixin,
    MainWindowDatabaseDialogsStatsMergeMixin,
    MainWindowHost,
):
    """DB 다이얼로그 퍼사드 (얇은 조합; 실제 구현은 분리 mixin)."""
