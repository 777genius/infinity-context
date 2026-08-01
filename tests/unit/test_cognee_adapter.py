import asyncio

from infinity_context_adapters.cognee import CogneeMemoryAdapter
from infinity_context_core.application.use_cases.get_capabilities import (
    GetCapabilitiesUseCase,
)
from infinity_context_core.ports.capabilities import (
    CapabilityRecallQuery,
    CapabilityStatus,
    DocumentMemoryWrite,
    MemoryCapability,
    MemoryScopeFilter,
    ProjectionForgetRequest,
)
from infinity_context_server.config import Settings


class FakeCognee:
    def __init__(self) -> None:
        self.remember_calls: list[dict[str, object]] = []
        self.recall_calls: list[dict[str, object]] = []

    async def remember(self, data: str, **kwargs: object) -> None:
        self.remember_calls.append({"data": data, **kwargs})

    async def recall(self, query: str, **kwargs: object) -> list[dict[str, object]]:
        self.recall_calls.append({"query": query, **kwargs})
        return [
            {
                "id": "cognee_chunk_1",
                "chunk_id": "chunk_canonical_1",
                "text": "Cognee recalled tenant scoped document chunk.",
                "score": 0.87,
            }
        ]


def test_cognee_skeleton_is_disabled_without_importing_runtime_sdk() -> None:
    async def run() -> None:
        adapter = CogneeMemoryAdapter()

        capabilities = await adapter.capabilities()
        descriptors = await adapter.capability_descriptors()
        health = await adapter.health()
        recalled = await adapter.recall(
            CapabilityRecallQuery(
                scope=MemoryScopeFilter(
                    space_id="space",
                    memory_scope_ids=("memory_scope",),
                ),
                query="anything",
                limit=1,
            )
        )

        assert capabilities.name == "cognee"
        assert capabilities.enabled is False
        assert {descriptor.capability for descriptor in descriptors} == {
            MemoryCapability.DOCUMENT_MEMORY,
            MemoryCapability.RAG_RECALL,
        }
        assert health.status == CapabilityStatus.DISABLED
        assert recalled.status == CapabilityStatus.DISABLED
        assert recalled.items == ()

    asyncio.run(run())


def test_cognee_runtime_is_read_only_without_exact_delete_and_live_readback() -> None:
    async def run() -> None:
        fake = FakeCognee()
        adapter = CogneeMemoryAdapter(enabled=True, client=fake, dataset_prefix="mp")

        capabilities = await adapter.capabilities()
        descriptors = {
            descriptor.capability: descriptor
            for descriptor in await adapter.capability_descriptors()
        }
        health = await adapter.health()
        projected = await adapter.ingest_document(
            DocumentMemoryWrite(
                document_id="doc_1",
                space_id="space_client_app",
                memory_scope_id="memory_scope_default",
                title="Architecture note",
                text="Tenant scoped retrieval belongs in Cognee RAG.",
                source_refs=(),
                chunk_ids=("chunk_canonical_1",),
            )
        )
        forgotten = await adapter.forget_document(
            ProjectionForgetRequest(
                canonical_ids=("doc_1", "chunk_canonical_1"),
                reason="canonical_document_deleted",
            )
        )
        recalled = await adapter.recall(
            CapabilityRecallQuery(
                scope=MemoryScopeFilter(
                    space_id="space_client_app",
                    memory_scope_ids=("memory_scope_default",),
                ),
                query="tenant scoped retrieval",
                limit=5,
            )
        )

        assert capabilities.enabled is True
        assert capabilities.healthy is True
        assert capabilities.supports_upsert is False
        assert capabilities.supports_delete is False
        assert capabilities.supports_search is True
        assert capabilities.supports_filters is False
        assert descriptors[MemoryCapability.DOCUMENT_MEMORY].enabled is False
        assert descriptors[MemoryCapability.DOCUMENT_MEMORY].status == CapabilityStatus.DISABLED
        assert descriptors[MemoryCapability.DOCUMENT_MEMORY].supports_update is False
        assert descriptors[MemoryCapability.DOCUMENT_MEMORY].supports_delete is False
        assert (
            descriptors[MemoryCapability.DOCUMENT_MEMORY].degraded_reason
            == "cognee_exact_delete_readback_unavailable"
        )
        assert descriptors[MemoryCapability.RAG_RECALL].enabled is True
        assert descriptors[MemoryCapability.RAG_RECALL].status == CapabilityStatus.OK
        assert descriptors[MemoryCapability.RAG_RECALL].supports_scope_filter is False
        assert health.status == CapabilityStatus.OK
        assert projected.status == CapabilityStatus.DISABLED
        assert projected.affected_ids == ()
        assert projected.diagnostics[0].code == "cognee.exact_delete_readback_unavailable"
        assert fake.remember_calls == []
        assert forgotten.status == CapabilityStatus.DEGRADED
        assert forgotten.forgotten_ids == ()
        assert forgotten.diagnostics[0].code == "cognee.exact_delete_readback_unavailable"
        assert fake.recall_calls[0]["datasets"] == ["mp__space_client_app__memory_scope_default"]
        assert fake.recall_calls[0]["top_k"] == 5
        assert recalled.status == CapabilityStatus.OK
        assert recalled.items[0].text == "Cognee recalled tenant scoped document chunk."
        assert recalled.items[0].source_refs[0].source_type == "chunk"
        assert recalled.items[0].source_refs[0].chunk_id == "chunk_canonical_1"

    asyncio.run(run())


def test_cognee_enabled_but_unavailable_forget_fails_closed() -> None:
    async def run() -> None:
        adapter = CogneeMemoryAdapter(enabled=True, configured=False)

        forgotten = await adapter.forget_document(
            ProjectionForgetRequest(
                canonical_ids=("doc_1",),
                reason="canonical_document_deleted",
            )
        )

        assert forgotten.status == CapabilityStatus.DEGRADED
        assert forgotten.forgotten_ids == ()
        assert forgotten.diagnostics[0].code == "cognee.runtime_unavailable"
        assert forgotten.diagnostics[0].retryable is True

    asyncio.run(run())


def test_capability_discovery_preserves_cognee_read_only_descriptors() -> None:
    async def run() -> None:
        adapter = CogneeMemoryAdapter(enabled=True, client=FakeCognee())
        result = await GetCapabilitiesUseCase(
            service_name="memory",
            deploy_profile="server",
            policy_mode="active_context",
            adapters=(adapter,),
            capability_descriptor_providers=(adapter,),
            supported_policy_modes=("active_context",),
            limits={},
        ).execute()
        descriptors = {descriptor.capability: descriptor for descriptor in result.capabilities}

        document_memory = descriptors[MemoryCapability.DOCUMENT_MEMORY]
        assert document_memory.status == CapabilityStatus.DISABLED
        assert document_memory.mode.value == "disabled"
        assert document_memory.enabled is False
        assert document_memory.degraded_reason == "cognee_exact_delete_readback_unavailable"
        assert descriptors[MemoryCapability.RAG_RECALL].status == CapabilityStatus.OK

    asyncio.run(run())


def test_cognee_config_is_disabled_by_default() -> None:
    settings = Settings()

    assert settings.cognee_enabled is False
    assert settings.cognee_runtime_configured is False
