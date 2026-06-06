"""Noop adapters used when optional engines are disabled."""

from memo_stack_core.ports.adapters import (
    AdapterCapabilities,
    EmbeddingResult,
    GraphSearchResult,
    VectorSearchResult,
    VectorWriteResult,
)
from memo_stack_core.ports.capabilities import (
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
    ProjectionWriteResult,
)


class NoopVectorMemoryAdapter:
    def __init__(self, name: str = "qdrant") -> None:
        self._name = name

    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name=self._name,
            enabled=False,
            healthy=True,
            supports_upsert=False,
            supports_delete=False,
            supports_search=False,
            supports_filters=False,
            degraded_reason="disabled",
        )

    async def search_chunks(self, *_args: object, **_kwargs: object) -> VectorSearchResult:
        return VectorSearchResult.degraded("vector.disabled", retryable=False)

    async def upsert_chunks(self, *_args: object, **_kwargs: object) -> VectorWriteResult:
        return VectorWriteResult.degraded("vector.disabled", retryable=False)

    async def delete_chunks(self, *_args: object, **_kwargs: object) -> VectorWriteResult:
        return VectorWriteResult.degraded("vector.disabled", retryable=False)


class NoopGraphMemoryAdapter:
    def __init__(self, name: str = "graphiti") -> None:
        self._name = name

    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name=self._name,
            enabled=False,
            healthy=True,
            supports_upsert=False,
            supports_delete=False,
            supports_search=False,
            supports_filters=False,
            supports_temporal_queries=False,
            degraded_reason="disabled",
        )

    async def capability_descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return (
            _disabled_capability(self._name, MemoryCapability.TEMPORAL_FACT_GRAPH),
            _disabled_capability(self._name, MemoryCapability.FACT_PROJECTION),
            _disabled_capability(
                self._name,
                MemoryCapability.PROJECTION_FORGET,
                supports_delete=False,
            ),
        )

    async def health(self) -> EngineHealthSnapshot:
        return EngineHealthSnapshot(
            adapter_name=self._name,
            status=CapabilityStatus.DISABLED,
            capabilities=await self.capability_descriptors(),
        )

    async def search(self, *_args: object, **_kwargs: object) -> GraphSearchResult:
        return GraphSearchResult.degraded("graph.disabled", retryable=False)

    async def upsert_fact(self, *_args: object, **_kwargs: object) -> VectorWriteResult:
        return VectorWriteResult.degraded("graph.disabled", retryable=False)

    async def upsert_fact_projection(
        self,
        _command: FactProjectionWrite,
    ) -> ProjectionWriteResult:
        return ProjectionWriteResult(
            status=CapabilityStatus.DISABLED,
            affected_ids=(),
        )

    async def delete_fact(self, *_args: object, **_kwargs: object) -> VectorWriteResult:
        return VectorWriteResult.degraded("graph.disabled", retryable=False)

    async def forget_projection(
        self,
        _command: ProjectionForgetRequest,
    ) -> ProjectionForgetResult:
        return ProjectionForgetResult(
            status=CapabilityStatus.DISABLED,
            forgotten_ids=(),
        )

    async def search_facts(self, _query: CapabilityRecallQuery) -> CapabilityRecallResult:
        return CapabilityRecallResult(
            status=CapabilityStatus.DISABLED,
            items=(),
        )


class NoopEmbeddingAdapter:
    def __init__(self, name: str = "embeddings") -> None:
        self._name = name

    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name=self._name,
            enabled=False,
            healthy=True,
            supports_upsert=False,
            supports_delete=False,
            supports_search=False,
            supports_filters=False,
            degraded_reason="disabled",
        )

    async def embed_texts(self, *_args: object, **_kwargs: object) -> EmbeddingResult:
        return EmbeddingResult.degraded("embeddings.disabled", retryable=False)


def _disabled_capability(
    adapter_name: str,
    capability: MemoryCapability,
    *,
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
        degraded_reason="disabled",
    )
