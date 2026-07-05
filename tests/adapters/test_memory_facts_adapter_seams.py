"""Import and placeholder checks for memory_facts adapter seams."""

from __future__ import annotations

import asyncio
import importlib
import sys

import pytest

from infinity_context_core.features.memory_facts.public import (
    FEATURE_ID,
    MemoryFactIdentity,
    MemoryFactScope,
)
from infinity_context_core.ports.capabilities import CapabilityStatus


def test_memory_facts_adapter_package_mirrors_feature_id() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")

    assert module.FEATURE_ID == FEATURE_ID == "memory_facts"
    assert module.PostgresMemoryFactStore.feature_id == FEATURE_ID
    assert module.QdrantMemoryFactProjection.feature_id == FEATURE_ID
    assert module.GraphitiMemoryFactProjection.feature_id == FEATURE_ID


def test_memory_facts_adapter_imports_do_not_load_provider_sdks() -> None:
    for module_name in ("sqlalchemy", "qdrant_client", "graphiti"):
        sys.modules.pop(module_name, None)

    importlib.import_module("infinity_context_adapters.features.memory_facts")

    assert "sqlalchemy" not in sys.modules
    assert "qdrant_client" not in sys.modules
    assert "graphiti" not in sys.modules


def test_postgres_fact_store_is_explicit_placeholder() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.memory_facts.postgres_fact_store"
    )
    identity = MemoryFactIdentity(
        fact_id="fact-1",
        scope=MemoryFactScope(space_id="space-1", memory_scope_id="scope-1"),
    )

    with pytest.raises(NotImplementedError, match="canonical persistence wiring is deferred"):
        asyncio.run(module.PostgresMemoryFactStore().get(identity))

    factory = module.create_postgres_memory_fact_unit_of_work_factory()
    assert factory.feature_id == FEATURE_ID
    assert factory().facts.feature_id == FEATURE_ID


def test_fact_projection_seams_report_disabled_health() -> None:
    qdrant = importlib.import_module(
        "infinity_context_adapters.features.memory_facts.qdrant_fact_projection"
    ).QdrantMemoryFactProjection()
    graphiti = importlib.import_module(
        "infinity_context_adapters.features.memory_facts.graphiti_fact_projection"
    ).GraphitiMemoryFactProjection()

    qdrant_health = asyncio.run(qdrant.health())
    graphiti_health = asyncio.run(graphiti.health())

    assert qdrant_health.status is CapabilityStatus.DISABLED
    assert graphiti_health.status is CapabilityStatus.DISABLED
    assert all(
        descriptor.metadata["feature_id"] == FEATURE_ID
        for descriptor in qdrant_health.capabilities
    )
    assert all(
        descriptor.metadata["feature_id"] == FEATURE_ID
        for descriptor in graphiti_health.capabilities
    )
