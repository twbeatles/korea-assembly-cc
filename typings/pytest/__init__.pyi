from typing import Any, ContextManager


class _MarkDecorator:
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class _MarkNamespace:
    skip: _MarkDecorator
    skipif: _MarkDecorator
    requires_subprocess: _MarkDecorator


class Item:
    name: str
    keywords: set[str]

    def add_marker(self, marker: Any) -> None: ...


class MonkeyPatch:
    def setattr(
        self,
        target: Any,
        name: str | Any,
        value: Any = ...,
        raising: bool = ...,
    ) -> None: ...


class RaisesContext(ContextManager[BaseException]):
    ...


def importorskip(modname: str, minversion: str | None = None, reason: str | None = None) -> Any: ...
def raises(expected_exception: type[BaseException], *args: Any, **kwargs: Any) -> RaisesContext: ...
def skip(reason: str = "", *, allow_module_level: bool = False) -> None: ...

mark: _MarkNamespace
