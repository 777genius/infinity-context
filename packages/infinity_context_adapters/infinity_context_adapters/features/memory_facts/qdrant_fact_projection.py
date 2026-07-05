"""Qdrant projection seam for memory_facts.

Qdrant is a derived index for recall candidates. This module establishes the
feature-owned adapter boundary without importing qdrant_client or writing any
vectors.
"""

from __future__ import annotations

from typing import NoReturn

from infinity_context_core.features.memory_facts.public import FEATURE_ID
from infinity_context_core.ports.capabilities import (
    CapabilityDescriptor,
    CapabilityMode,
    CapabilityStatus,
    EngineHealthSnapshot,
    FactProjectionWrite,
    MemoryCapability,
    ProjectionForgetRequest,
    ProjectionForgetResult,
    ProjectionFreshness,
    ProjectionWriteResult,
)


class QdrantMemoryFactProjection:
    """Placeholder for the future feature-owned Qdrant fact projection."""

    adapter_name = "qdrant"
    feature_id = FEATURE_ID

    async def capability_descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return (
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


def create_qdrant_memory_fact_projection() -> QdrantMemoryFactProjection:
    """Create the feature-owned Qdrant projection placeholder."""

    return QdrantMemoryFactProjection()


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
        f"memory_facts Qdrant projection {operation} is a placeholder seam; "
        "real Qdrant wiring is deferred."
    )


__all__ = ("QdrantMemoryFactProjection", "create_qdrant_memory_fact_projection")
