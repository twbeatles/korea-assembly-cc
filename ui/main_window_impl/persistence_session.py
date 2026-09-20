# -*- coding: utf-8 -*-

import uuid

from core.file_io import canonical_path_key
from core.recovery_candidates import (
    discover_recovery_candidates,
    inspect_recovery_candidate,
)
from ui.dialogs import RecoveryCandidateDialog
from ui.main_window_common import *
from ui.main_window_types import MainWindowHost

from ui.main_window_impl.persistence_session_deferred import MainWindowPersistenceSessionDeferredMixin

from ui.main_window_impl.persistence_session_save import MainWindowPersistenceSessionSaveMixin

from ui.main_window_impl.persistence_session_load import MainWindowPersistenceSessionLoadMixin

from ui.main_window_impl.persistence_session_recovery import MainWindowPersistenceSessionRecoveryMixin

from ui.main_window_impl.persistence_session_backup import MainWindowPersistenceSessionBackupMixin


class MainWindowPersistenceSessionMixin(
    MainWindowPersistenceSessionDeferredMixin,
    MainWindowPersistenceSessionSaveMixin,
    MainWindowPersistenceSessionLoadMixin,
    MainWindowPersistenceSessionRecoveryMixin,
    MainWindowPersistenceSessionBackupMixin,
    MainWindowHost,
):
    """세션 퍼사드 (얇은 조합; 저장/로드/복구/백업 분리)."""
