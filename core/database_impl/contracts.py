from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    class DatabaseMixinHost:
        def __getattr__(self, name: str) -> Any: ...

else:
    class DatabaseMixinHost:
        def __getattr__(self, name: str) -> Any:
            raise AttributeError(name)
