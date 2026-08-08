"""Ports owned by the memory_facts feature.

Adapters will implement ports here once memory_facts runtime behavior moves out
of the legacy layer-first compatibility modules.
"""

from infinity_context_core.features.memory_facts.ports.clock import (
    MemoryFactClockPort,
)
from infinity_context_core.features.memory_facts.ports.idempotency import (
    MemoryFactIdempotencyConflict,
    MemoryFactOperationReceipt,
    MemoryFactOperationReceiptPort,
)
from infinity_context_core.features.memory_facts.ports.ids import MemoryFactIdPort
from infinity_context_core.features.memory_facts.ports.outbox import (
    MemoryFactOutboxMessage,
    MemoryFactOutboxPort,
)
from infinity_context_core.features.memory_facts.ports.read_models import (
    MemoryFactListSpec,
    MemoryFactReadModelPort,
)
from infinity_context_core.features.memory_facts.ports.repositories import (
    MemoryFactRepositoryPort,
)
from infinity_context_core.features.memory_facts.ports.selection import (
    MemoryFactSelectionPort,
)
from infinity_context_core.features.memory_facts.ports.temporal_decisions import (
    FactSupersessionRepositoryPort,
    FactTemporalDecisionRepositoryPort,
)
from infinity_context_core.features.memory_facts.ports.unit_of_work import (
    MemoryFactTransactionPort,
    MemoryFactUnitOfWorkFactoryPort,
    MemoryFactUnitOfWorkPort,
)

__all__ = (
    "FactSupersessionRepositoryPort",
    "FactTemporalDecisionRepositoryPort",
    "MemoryFactClockPort",
    "MemoryFactIdPort",
    "MemoryFactIdempotencyConflict",
    "MemoryFactOutboxMessage",
    "MemoryFactOutboxPort",
    "MemoryFactOperationReceipt",
    "MemoryFactOperationReceiptPort",
    "MemoryFactRepositoryPort",
    "MemoryFactListSpec",
    "MemoryFactReadModelPort",
    "MemoryFactSelectionPort",
    "MemoryFactTransactionPort",
    "MemoryFactUnitOfWorkFactoryPort",
    "MemoryFactUnitOfWorkPort",
)
