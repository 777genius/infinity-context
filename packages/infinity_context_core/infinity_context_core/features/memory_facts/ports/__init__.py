"""Ports owned by the memory_facts feature.

Adapters will implement ports here once memory_facts runtime behavior moves out
of the legacy layer-first compatibility modules.
"""

from infinity_context_core.features.memory_facts.ports.clock import (
    MemoryFactClockPort,
)
from infinity_context_core.features.memory_facts.ports.ids import MemoryFactIdPort
from infinity_context_core.features.memory_facts.ports.outbox import (
    MemoryFactOutboxMessage,
    MemoryFactOutboxPort,
)
from infinity_context_core.features.memory_facts.ports.repositories import (
    MemoryFactRepositoryPort,
)
from infinity_context_core.features.memory_facts.ports.unit_of_work import (
    MemoryFactUnitOfWorkFactoryPort,
    MemoryFactUnitOfWorkPort,
)

__all__ = (
    "MemoryFactClockPort",
    "MemoryFactIdPort",
    "MemoryFactOutboxMessage",
    "MemoryFactOutboxPort",
    "MemoryFactRepositoryPort",
    "MemoryFactUnitOfWorkFactoryPort",
    "MemoryFactUnitOfWorkPort",
)
