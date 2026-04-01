# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_impl.pipeline_messages import MainWindowPipelineMessagesMixin
from ui.main_window_impl.pipeline_queue import (
    COALESCED_WORKER_MESSAGE_ORDER,
    COALESCED_WORKER_MESSAGE_TYPES,
    MainWindowPipelineQueueMixin,
)
from ui.main_window_impl.pipeline_state import MainWindowPipelineStateMixin
from ui.main_window_impl.pipeline_stream import MainWindowPipelineStreamMixin
from ui.main_window_types import MainWindowHost


class MainWindowPipelineMixin(
    MainWindowPipelineStateMixin,
    MainWindowPipelineQueueMixin,
    MainWindowPipelineStreamMixin,
    MainWindowPipelineMessagesMixin,
    MainWindowHost,
):
    pass
