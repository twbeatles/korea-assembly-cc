from typing import Any, Callable, ContextManager


class _MarkDecorator:
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class _MarkNamespace:
    skip: _MarkDecorator
    skipif: _MarkDecorator
    requires_subprocess: _MarkDecorator
    parametrize: _MarkDecorator


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


class ExceptionInfo:
    value: BaseException


class RaisesContext(ContextManager[ExceptionInfo]):
    ...


def importorskip(modname: str, minversion: str | None = None, reason: str | None = None) -> Any: ...
def fixture(fixture_function: Callable[..., Any] | None = ..., **kwargs: Any) -> Any: ...
def raises(expected_exception: type[BaseException], *args: Any, **kwargs: Any) -> RaisesContext: ...
def skip(reason: str = "", *, allow_module_level: bool = False) -> None: ...

mark: _MarkNamespace
