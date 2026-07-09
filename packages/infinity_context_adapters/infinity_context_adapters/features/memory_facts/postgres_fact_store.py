"""Postgres canonical store seam for memory_facts.

Postgres remains the canonical lifecycle store, but this feature-owned package
does not implement persistence yet. The classes below exist to mark the adapter
boundary for the memory_facts feature without importing SQLAlchemy or touching
the legacy layer-first repositories.
"""

from __future__ import annotations

from types import TracebackType
from typing import NoReturn

from infinity_context_core.features.memory_facts.public import (
    FEATURE_ID,
    MemoryFactIdentity,
    MemoryFactOutboxMessage,
    MemoryFactOutboxPort,
    MemoryFactRepositoryPort,
    MemoryFactSnapshot,
    MemoryFactUnitOfWorkFactoryPort,
)


class PostgresMemoryFactStore:
    """Placeholder for the future Postgres MemoryFactRepositoryPort adapter."""

    adapter_name = "postgres"
    feature_id = FEATURE_ID

    async def create(self, _fact: MemoryFactSnapshot) -> MemoryFactSnapshot:
        _raise_not_implemented("create")

    async def get(self, _identity: MemoryFactIdentity) -> MemoryFactSnapshot | None:
        _raise_not_implemented("get")

    async def get_for_update(
        self,
        _identity: MemoryFactIdentity,
    ) -> MemoryFactSnapshot | None:
        _raise_not_implemented("get_for_update")

    async def save(self, _fact: MemoryFactSnapshot) -> MemoryFactSnapshot:
        _raise_not_implemented("save")


class PostgresMemoryFactOutbox:
    """Placeholder for fact lifecycle outbox writes in the Postgres transaction."""

    adapter_name = "postgres"
    feature_id = FEATURE_ID

    async def enqueue(self, _message: MemoryFactOutboxMessage) -> None:
        _raise_not_implemented("enqueue")


class PostgresMemoryFactUnitOfWork:
    """Placeholder unit of work for future canonical fact transactions."""

    adapter_name = "postgres"
    feature_id = FEATURE_ID

    def __init__(
        self,
        *,
        facts: MemoryFactRepositoryPort | None = None,
        outbox: MemoryFactOutboxPort | None = None,
    ) -> None:
        self.facts = facts or PostgresMemoryFactStore()
        self.outbox = outbox or PostgresMemoryFactOutbox()

    async def __aenter__(self) -> PostgresMemoryFactUnitOfWork:
        _raise_not_implemented("__aenter__")

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        _raise_not_implemented("__aexit__")

    async def commit(self) -> None:
        _raise_not_implemented("commit")

    async def rollback(self) -> None:
        _raise_not_implemented("rollback")


class PostgresMemoryFactUnitOfWorkFactory:
    """Factory seam for creating feature-owned Postgres fact units of work."""

    adapter_name = "postgres"
    feature_id = FEATURE_ID

    def __call__(self) -> PostgresMemoryFactUnitOfWork:
        return PostgresMemoryFactUnitOfWork()


def create_postgres_memory_fact_store() -> MemoryFactRepositoryPort:
    """Create the feature-owned Postgres fact store placeholder."""

    return PostgresMemoryFactStore()


def create_postgres_memory_fact_unit_of_work_factory() -> MemoryFactUnitOfWorkFactoryPort:
    """Create the feature-owned Postgres unit-of-work factory placeholder."""

    return PostgresMemoryFactUnitOfWorkFactory()


def _raise_not_implemented(operation: str) -> NoReturn:
    raise NotImplementedError(
        f"memory_facts Postgres fact store {operation} is a placeholder seam; "
        "real canonical persistence wiring is deferred."
    )


__all__ = (
    "PostgresMemoryFactOutbox",
    "PostgresMemoryFactStore",
    "PostgresMemoryFactUnitOfWork",
    "PostgresMemoryFactUnitOfWorkFactory",
    "create_postgres_memory_fact_store",
    "create_postgres_memory_fact_unit_of_work_factory",
)
