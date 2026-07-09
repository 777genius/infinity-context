"""Domain errors owned by the memory_scopes feature."""

from __future__ import annotations


class MemoryScopeDomainError(ValueError):
    """Raised when a memory scope domain invariant is violated."""


class MemoryScopeOwnershipError(MemoryScopeDomainError):
    """Raised when ownership policy blocks a memory scope operation."""


class MemoryScopeLifecycleError(MemoryScopeDomainError):
    """Raised when lifecycle policy blocks a memory scope operation."""


__all__ = (
    "MemoryScopeDomainError",
    "MemoryScopeLifecycleError",
    "MemoryScopeOwnershipError",
)
