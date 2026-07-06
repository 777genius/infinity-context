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
from infinity_context_adapters.features.memory_facts.in_memory_fact_store import (
    InMemoryMemoryFactOutbox,
    InMemoryMemoryFactRepository,
    InMemoryMemoryFactUnitOfWork,
    InMemoryMemoryFactUnitOfWorkFactory,
    create_in_memory_memory_fact_store,
    create_in_memory_memory_fact_unit_of_work_factory,
)
from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactOutbox,
    PostgresMemoryFactStore,
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
    "PostgresMemoryFactOutbox",
    "PostgresMemoryFactStore",
    "PostgresMemoryFactUnitOfWork",
    "PostgresMemoryFactUnitOfWorkFactory",
    "QdrantMemoryFactProjection",
    "create_graphiti_memory_fact_projection",
    "create_in_memory_memory_fact_store",
    "create_in_memory_memory_fact_unit_of_work_factory",
    "create_postgres_memory_fact_store",
    "create_postgres_memory_fact_unit_of_work_factory",
    "create_qdrant_memory_fact_projection",
)
