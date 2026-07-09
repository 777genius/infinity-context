"""Postgres canonical store seam for memory_scopes.

Postgres owns memory scope lifecycle and ownership transfer state. These
feature-owned placeholders implement the memory_scopes repository and
unit-of-work port shapes without importing SQLAlchemy or touching legacy
layer-first repositories.
"""

from __future__ import annotations

from types import TracebackType
from typing import NoReturn

from infinity_context_core.features.memory_scopes.public import (
    FEATURE_ID,
    MemoryScopeIdentity,
    MemoryScopeRepositoryPort,
    MemoryScopeSnapshot,
    MemoryScopeUnitOfWorkFactoryPort,
)


class PostgresMemoryScopeStore:
    """Placeholder for the future Postgres MemoryScopeRepositoryPort adapter."""

    adapter_name = "postgres"
    feature_id = FEATURE_ID

    async def create(self, _scope: MemoryScopeSnapshot) -> MemoryScopeSnapshot:
        _raise_not_implemented("create")

    async def get(
        self,
        _identity: MemoryScopeIdentity,
    ) -> MemoryScopeSnapshot | None:
        _raise_not_implemented("get")

    async def get_for_update(
        self,
        _identity: MemoryScopeIdentity,
    ) -> MemoryScopeSnapshot | None:
        _raise_not_implemented("get_for_update")

    async def get_by_external_ref(
        self,
        _space_id: str,
        _external_ref: str,
    ) -> MemoryScopeSnapshot | None:
        _raise_not_implemented("get_by_external_ref")

    async def save(self, _scope: MemoryScopeSnapshot) -> MemoryScopeSnapshot:
        _raise_not_implemented("save")


class PostgresMemoryScopeUnitOfWork:
    """Placeholder unit of work for canonical memory scope transactions."""

    adapter_name = "postgres"
    feature_id = FEATURE_ID

    def __init__(
        self,
        *,
        memory_scopes: MemoryScopeRepositoryPort | None = None,
    ) -> None:
        self.memory_scopes = memory_scopes or PostgresMemoryScopeStore()

    async def __aenter__(self) -> PostgresMemoryScopeUnitOfWork:
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


class PostgresMemoryScopeUnitOfWorkFactory:
    """Factory seam for feature-owned Postgres memory scope units of work."""

    adapter_name = "postgres"
    feature_id = FEATURE_ID

    def __call__(self) -> PostgresMemoryScopeUnitOfWork:
        return PostgresMemoryScopeUnitOfWork()


def create_postgres_memory_scope_store() -> MemoryScopeRepositoryPort:
    """Create the feature-owned Postgres memory scope store placeholder."""

    return PostgresMemoryScopeStore()


def create_postgres_memory_scope_unit_of_work_factory() -> MemoryScopeUnitOfWorkFactoryPort:
    """Create the feature-owned Postgres memory scope unit-of-work factory."""

    return PostgresMemoryScopeUnitOfWorkFactory()


def _raise_not_implemented(operation: str) -> NoReturn:
    raise NotImplementedError(
        f"memory_scopes Postgres scope store {operation} is a placeholder seam; "
        "real canonical memory scope persistence wiring is deferred."
    )


__all__ = (
    "PostgresMemoryScopeStore",
    "PostgresMemoryScopeUnitOfWork",
    "PostgresMemoryScopeUnitOfWorkFactory",
    "create_postgres_memory_scope_store",
    "create_postgres_memory_scope_unit_of_work_factory",
)
