"""Graphiti projection seam for memory_facts.

Graphiti is a derived index, not canonical memory storage. This first-pass
feature-owned adapter mirror exposes only a disabled placeholder boundary.
"""

from __future__ import annotations

from typing import NoReturn

from infinity_context_core.features.memory_facts.public import FEATURE_ID
from infinity_context_core.ports.capabilities import (
    CapabilityDescriptor,
    CapabilityMode,
    CapabilityRecallQuery,
    CapabilityRecallResult,
    CapabilityStatus,
    EngineHealthSnapshot,
    FactProjectionWrite,
    MemoryCapability,
    ProjectionForgetRequest,
    ProjectionForgetResult,
    ProjectionFreshness,
    ProjectionWriteResult,
)


class GraphitiMemoryFactProjection:
    """Placeholder for the future feature-owned Graphiti fact projection."""

    adapter_name = "graphiti"
    feature_id = FEATURE_ID

    async def capability_descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return (
            _disabled_descriptor(
                adapter_name=self.adapter_name,
                capability=MemoryCapability.TEMPORAL_FACT_GRAPH,
            ),
            _disabled_descriptor(
                adapter_name=self.adapter_name,
                capability=MemoryCapability.FACT_PROJECTION,
            ),
            _disabled_descriptor(
                adapter_name=self.adapter_name,
                capability=MemoryCapability.PROJECTION_FORGET,
                supports_delete=True,
            ),
        )

    async def health(self) -> EngineHealthSnapshot:
        return EngineHealthSnapshot(
            adapter_name=self.adapter_name,
            status=CapabilityStatus.DISABLED,
            capabilities=await self.capability_descriptors(),
        )

    async def upsert_fact(self, _command: FactProjectionWrite) -> ProjectionWriteResult:
        _raise_not_implemented("upsert_fact")

    async def upsert_fact_projection(
        self,
        _command: FactProjectionWrite,
    ) -> ProjectionWriteResult:
        _raise_not_implemented("upsert_fact_projection")

    async def forget_projection(
        self,
        _command: ProjectionForgetRequest,
    ) -> ProjectionForgetResult:
        _raise_not_implemented("forget_projection")

    async def search_facts(self, _query: CapabilityRecallQuery) -> CapabilityRecallResult:
        _raise_not_implemented("search_facts")


def create_graphiti_memory_fact_projection() -> GraphitiMemoryFactProjection:
    """Create the feature-owned Graphiti projection placeholder."""

    return GraphitiMemoryFactProjection()


def _disabled_descriptor(
    *,
    adapter_name: str,
    capability: MemoryCapability,
    supports_delete: bool = False,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability=capability,
        adapter_name=adapter_name,
        mode=CapabilityMode.DISABLED,
        status=CapabilityStatus.DISABLED,
        enabled=False,
        supports_scope_filter=False,
        supports_source_refs=False,
        supports_delete=supports_delete,
        projection_freshness=ProjectionFreshness.NOT_APPLICABLE,
        degraded_reason="not_implemented",
        metadata={"feature_id": FEATURE_ID},
    )


def _raise_not_implemented(operation: str) -> NoReturn:
    raise NotImplementedError(
        f"memory_facts Graphiti projection {operation} is a placeholder seam; "
        "real Graphiti wiring is deferred."
    )


__all__ = ("GraphitiMemoryFactProjection", "create_graphiti_memory_fact_projection")
