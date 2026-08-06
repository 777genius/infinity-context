"""Mem0 OSS full-run v5 benchmark adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mem0_oss_adapter_v5.app import create_app as create_app

__all__ = ["create_app"]


def __getattr__(name: str) -> Any:
    """Resolve the optional HTTP boundary only through its public export."""
    if name != "create_app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from mem0_oss_adapter_v5.app import create_app

    globals()[name] = create_app
    return create_app
