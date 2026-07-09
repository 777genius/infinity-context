"""Application errors owned by the memory_scopes feature."""

from __future__ import annotations


class MemoryScopeApplicationError(RuntimeError):
    """Base application error for memory scope use cases."""


class MemoryScopeNotFoundError(MemoryScopeApplicationError):
    """Raised when a command targets a scope that does not exist."""


class MemoryScopeConflictError(MemoryScopeApplicationError):
    """Raised when a memory scope command conflicts with current state."""


class DuplicateMemoryScopeExternalRefError(MemoryScopeConflictError):
    """Raised when a space already owns the requested external reference."""


__all__ = (
    "DuplicateMemoryScopeExternalRefError",
    "MemoryScopeApplicationError",
    "MemoryScopeConflictError",
    "MemoryScopeNotFoundError",
)
