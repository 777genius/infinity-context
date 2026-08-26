"""Postgres adapter package with cycle-safe lazy public exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "PostgresProjectionFence",
    "PostgresCanonicalProjectionSource",
    "PostgresRetrievalProfileRegistry",
    "RuntimeDeathProof",
    "RuntimeProcessSupervisor",
    "SupervisorTrustRegistry",
    "load_pinned_supervisor_trust",
    "registry_document",
    "PostgresUnitOfWork",
    "PostgresUnitOfWorkFactory",
    "build_async_engine",
    "build_locator_retrieval_indexes",
    "build_session_factory",
    "create_schema",
    "upgrade_schema",
    "preflight_reconciliation_0049",
]


def __getattr__(name: str) -> Any:
    if name == "PostgresProjectionFence":
        module = import_module("infinity_context_adapters.postgres.projection_fence")
        return getattr(module, name)
    if name in {"PostgresCanonicalProjectionSource", "PostgresRetrievalProfileRegistry"}:
        module = import_module("infinity_context_adapters.postgres.locator_profile_lifecycle")
        return getattr(module, name)
    if name in {"RuntimeDeathProof", "RuntimeProcessSupervisor"}:
        module = import_module("infinity_context_adapters.postgres.runtime_supervisor")
        return getattr(module, name)
    if name in {"SupervisorTrustRegistry", "load_pinned_supervisor_trust", "registry_document"}:
        module = import_module("infinity_context_adapters.postgres.supervisor_trust")
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
    if name in {"upgrade_schema", "preflight_reconciliation_0049"}:
        module = import_module("infinity_context_adapters.postgres.migration_runner")
        return getattr(module, name)
    if name == "build_locator_retrieval_indexes":
        module = import_module("infinity_context_adapters.postgres.locator_index_maintenance")
        return getattr(module, name)
    raise AttributeError(name)
