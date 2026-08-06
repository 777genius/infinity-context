"""Postgres adapter package with cycle-safe lazy public exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "PostgresProjectionFence",
    "PostgresUnitOfWork",
    "PostgresUnitOfWorkFactory",
    "build_async_engine",
    "build_session_factory",
    "create_schema",
    "upgrade_schema",
]


def __getattr__(name: str) -> Any:
    if name == "PostgresProjectionFence":
        module = import_module("infinity_context_adapters.postgres.projection_fence")
        return getattr(module, name)
    if name in {
        "PostgresUnitOfWork",
        "PostgresUnitOfWorkFactory",
        "build_async_engine",
        "build_session_factory",
        "create_schema",
    }:
        module = import_module("infinity_context_adapters.postgres.unit_of_work")
        return getattr(module, name)
    if name == "upgrade_schema":
        module = import_module("infinity_context_adapters.postgres.migration_runner")
        return getattr(module, name)
    raise AttributeError(name)
