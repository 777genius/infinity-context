"""Provider-free, externally verified Mem0 v5 hosting E2E harness."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .contracts import RunFixture as RunFixture
    from .contracts import SyntheticUnit as SyntheticUnit
    from .scenario import E2EResult as E2EResult
    from .scenario import ProviderFreeE2EScenario as ProviderFreeE2EScenario

__all__ = ("E2EResult", "ProviderFreeE2EScenario", "RunFixture", "SyntheticUnit")

_EXPORT_MODULES = {
    "E2EResult": ".scenario",
    "ProviderFreeE2EScenario": ".scenario",
    "RunFixture": ".contracts",
    "SyntheticUnit": ".contracts",
}


def __getattr__(name: str) -> Any:
    """Resolve public harness types without loading scenario dependencies eagerly."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
