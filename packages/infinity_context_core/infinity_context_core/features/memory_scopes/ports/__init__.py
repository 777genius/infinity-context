"""Ports owned by the memory_scopes feature.

Adapters will implement these protocols when canonical memory scope persistence
moves into the feature-owned runtime path.
"""

from infinity_context_core.features.memory_scopes.ports.clock import (
    MemoryScopeClockPort,
)
from infinity_context_core.features.memory_scopes.ports.ids import MemoryScopeIdPort
from infinity_context_core.features.memory_scopes.ports.repositories import (
    MemoryScopeRepositoryPort,
)
from infinity_context_core.features.memory_scopes.ports.unit_of_work import (
    MemoryScopeUnitOfWorkFactoryPort,
    MemoryScopeUnitOfWorkPort,
)

__all__ = (
    "MemoryScopeClockPort",
    "MemoryScopeIdPort",
    "MemoryScopeRepositoryPort",
    "MemoryScopeUnitOfWorkFactoryPort",
    "MemoryScopeUnitOfWorkPort",
)
