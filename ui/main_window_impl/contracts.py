from __future__ import annotations

from typing import Any, Protocol


class RuntimeHost(Protocol):
    """impl mixin 공통 기반 (동적 속성 허용).

    세부 시그니처는 공개 계약 `ui.main_window_types.MainWindowHost` 와
    각 mixin 구현을 따른다. Protocol 메서드를 과도하게 적으면
    TYPE_CHECKING 기반 mixin 상속에서 pyright abstract/override 오류가 난다.
    """

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
    """impl 내부 좁은 Host. 공개 계약은 ui.main_window_types.MainWindowHost."""

    pass
