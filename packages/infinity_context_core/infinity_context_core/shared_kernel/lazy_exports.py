"""Resolve explicit compatibility exports without constructing proxy objects."""

from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module


def resolve_lazy_export(
    name: str,
    exports: Mapping[str, tuple[str, str | None]],
    namespace: dict[str, object],
    package: str,
) -> object:
    """Import and cache the original object, preserving genuine import failures."""
    try:
        module_name, attribute = exports[name]
    except KeyError:
        raise AttributeError(f"module {package!r} has no attribute {name!r}") from None
    module = import_module(module_name)
    value = getattr(module, attribute) if attribute is not None else module
    namespace[name] = value
    return value
