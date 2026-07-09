"""Identifier port owned by the memory_scopes feature."""

from __future__ import annotations

from typing import Protocol


class MemoryScopeIdPort(Protocol):
    def new_memory_scope_id(self) -> str:
        """Return a new canonical memory scope id."""


__all__ = ("MemoryScopeIdPort",)
