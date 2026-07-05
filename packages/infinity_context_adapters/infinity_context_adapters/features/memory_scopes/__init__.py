"""Adapter seams for the memory_scopes feature.

These classes mark feature-owned infrastructure boundaries for canonical
memory scope lifecycle and ownership transfer support. Runtime Postgres wiring
is intentionally deferred to later composition work.
"""

from infinity_context_core.features.memory_scopes.public import FEATURE_ID

from infinity_context_adapters.features.memory_scopes.postgres_scope_store import (
    PostgresMemoryScopeStore,
    PostgresMemoryScopeUnitOfWork,
    PostgresMemoryScopeUnitOfWorkFactory,
    create_postgres_memory_scope_store,
    create_postgres_memory_scope_unit_of_work_factory,
)

__all__ = (
    "FEATURE_ID",
    "PostgresMemoryScopeStore",
    "PostgresMemoryScopeUnitOfWork",
    "PostgresMemoryScopeUnitOfWorkFactory",
    "create_postgres_memory_scope_store",
    "create_postgres_memory_scope_unit_of_work_factory",
)
