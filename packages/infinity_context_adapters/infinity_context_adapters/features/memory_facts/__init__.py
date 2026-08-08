"""Adapter seams for the memory_facts feature.

These classes intentionally do not perform infrastructure side effects yet.
They mark the package boundary where feature-owned Postgres, Qdrant and
Graphiti implementations will be wired in later slices.
"""

from infinity_context_core.features.memory_facts.public import FEATURE_ID

from infinity_context_adapters.features.memory_facts.graphiti_fact_projection import (
    GraphitiMemoryFactProjection,
    create_graphiti_memory_fact_projection,
)
from infinity_context_adapters.features.memory_facts.id_generator import (
    MemoryFactIdAdapter,
    create_memory_fact_id_adapter,
)
from infinity_context_adapters.features.memory_facts.in_memory_fact_store import (
    InMemoryMemoryFactOutbox,
    InMemoryMemoryFactRepository,
    InMemoryMemoryFactUnitOfWork,
    InMemoryMemoryFactUnitOfWorkFactory,
    create_in_memory_memory_fact_store,
    create_in_memory_memory_fact_unit_of_work_factory,
)
from infinity_context_adapters.features.memory_facts.postgres_fact_read_model import (
    PostgresMemoryFactReadModel,
    create_postgres_memory_fact_read_model,
)
from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactOutbox,
    PostgresMemoryFactStore,
    PostgresMemoryFactTransaction,
    PostgresMemoryFactUnitOfWork,
    PostgresMemoryFactUnitOfWorkFactory,
    create_postgres_memory_fact_store,
    create_postgres_memory_fact_unit_of_work_factory,
)
from infinity_context_adapters.features.memory_facts.qdrant_fact_projection import (
    QdrantMemoryFactProjection,
    create_qdrant_memory_fact_projection,
)

__all__ = (
    "FEATURE_ID",
    "GraphitiMemoryFactProjection",
    "InMemoryMemoryFactOutbox",
    "InMemoryMemoryFactRepository",
    "InMemoryMemoryFactUnitOfWork",
    "InMemoryMemoryFactUnitOfWorkFactory",
    "MemoryFactIdAdapter",
    "PostgresMemoryFactOutbox",
    "PostgresMemoryFactStore",
    "PostgresMemoryFactTransaction",
    "PostgresMemoryFactUnitOfWork",
    "PostgresMemoryFactUnitOfWorkFactory",
    "QdrantMemoryFactProjection",
    "create_graphiti_memory_fact_projection",
    "create_in_memory_memory_fact_store",
    "create_in_memory_memory_fact_unit_of_work_factory",
    "create_memory_fact_id_adapter",
    "create_postgres_memory_fact_store",
    "create_postgres_memory_fact_unit_of_work_factory",
    "PostgresMemoryFactReadModel",
    "create_postgres_memory_fact_read_model",
    "create_qdrant_memory_fact_projection",
)
