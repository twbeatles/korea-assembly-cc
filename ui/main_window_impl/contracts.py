from __future__ import annotations

from typing import Any, Protocol


class RuntimeHost(Protocol):
    def __getattr__(self, name: str) -> Any: ...
    def __setattr__(self, name: str, value: Any) -> None: ...


class CaptureLiveHost(RuntimeHost, Protocol):
    pass


class CaptureBrowserHost(RuntimeHost, Protocol):
    pass


class CaptureDomHost(RuntimeHost, Protocol):
    pass


class CaptureObserverHost(RuntimeHost, Protocol):
    pass


class PipelineStateHost(RuntimeHost, Protocol):
    pass


class PipelineQueueHost(RuntimeHost, Protocol):
    pass


class PipelineStreamHost(RuntimeHost, Protocol):
    pass


class PipelineMessagesHost(RuntimeHost, Protocol):
    pass


class UiShellHost(RuntimeHost, Protocol):
    pass


class UiPresetsHost(RuntimeHost, Protocol):
    pass


class UiHelpHost(RuntimeHost, Protocol):
    pass


class ViewRenderHost(RuntimeHost, Protocol):
    pass


class ViewSearchHost(RuntimeHost, Protocol):
    pass


class ViewEditingHost(RuntimeHost, Protocol):
    pass


class MainWindowHost(RuntimeHost, Protocol):
    pass
