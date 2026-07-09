import asyncio
import importlib.util
import json
from types import SimpleNamespace

from infinity_context_adapters.cognee import CogneeMemoryAdapter
from infinity_context_adapters.embeddings import OpenAIEmbeddingAdapter
from infinity_context_adapters.extraction import OpenAIJsonMemoryExtractor
from infinity_context_adapters.extraction.openai_json import _prompt_text
from infinity_context_adapters.graphiti import GraphitiGraphMemoryAdapter
from infinity_context_adapters.noop import (
    NoopEmbeddingAdapter,
    NoopGraphMemoryAdapter,
    NoopVectorMemoryAdapter,
)
from infinity_context_adapters.qdrant import QdrantVectorMemoryAdapter
from infinity_context_core.domain.entities import TrustLevel
from infinity_context_core.domain.errors import MemoryInfrastructureError, MemoryValidationError
from infinity_context_core.ports.adapters import PortStatus, VectorUpsertItem
from infinity_context_core.ports.auto_memory import CandidateOperation, SourceProvenance
from infinity_context_core.ports.capabilities import (
    CapabilityRecallQuery,
    CapabilityStatus,
    DocumentMemoryWrite,
    FactProjectionWrite,
    MemoryCapability,
    MemoryScopeFilter,
    ProjectionForgetRequest,
)
from infinity_context_server.config import Settings


class FakeGraphiti:
    def __init__(self) -> None:
        self.built = 0
        self.episodes: list[dict[str, object]] = []
        self.deleted: list[str] = []
        self.search_calls: list[dict[str, object]] = []

    async def build_indices_and_constraints(self) -> None:
        self.built += 1

    async def add_episode(self, **kwargs: object) -> None:
        self.episodes.append(kwargs)

    async def delete_episode(self, *, name: str) -> None:
        self.deleted.append(name)

    async def search(self, **kwargs: object) -> list[object]:
        self.search_calls.append(kwargs)
        return [SimpleNamespace(episodes=["fact_graphiti"], score=0.8)]


class FakeModernGraphiti(FakeGraphiti):
    delete_episode = None

    async def remove_episode(self, episode_uuid: str) -> None:
        self.deleted.append(episode_uuid)


class FakeGraphitiWithoutSearch:
    async def add_episode(self, **_kwargs: object) -> None:
        return None

    async def delete_episode(self, *, name: str) -> None:
        return None


class FakeFailingGraphiti(FakeGraphiti):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def add_episode(self, **kwargs: object) -> None:
        self.episodes.append(kwargs)
        raise self.error


class FakeGraphitiWithManyResults(FakeGraphiti):
    async def search(self, **kwargs: object) -> list[object]:
        self.search_calls.append(kwargs)
        return [
            SimpleNamespace(episodes=[f"fact_many_{index}"], score=0.9 - index * 0.01)
            for index in range(5)
        ]


class NodeNotFoundError(RuntimeError):
    pass


class FakeOpenAIResponses:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object):
        self.calls.append(kwargs)
        if self.payload is None:
            raise RuntimeError("provider down")
        return SimpleNamespace(output_text=json.dumps(self.payload))


class FakeOpenAIClient:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.responses = FakeOpenAIResponses(payload)
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeOpenAIEmbeddings:
    def __init__(self, response: object | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeOpenAIEmbeddingClient:
    def __init__(self, response: object | None = None, error: Exception | None = None) -> None:
        self.embeddings = FakeOpenAIEmbeddings(response=response, error=error)
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeOpenAIEmbeddingAdapter(OpenAIEmbeddingAdapter):
    def __init__(self, client: FakeOpenAIEmbeddingClient) -> None:
        super().__init__(api_key="test-key", model="text-embedding-3-small", dimensions=3)
        self.client = client

    async def _client(self) -> FakeOpenAIEmbeddingClient:
        return self.client


def _openai_candidate_payload(
    *,
    text: str,
    evidence_quote: str | None,
    operation: str = "add",
    kind: str = "note",
    confidence: str = "medium",
    safe_reason: str = "explicit_user_memory",
    target_hint: str | None = None,
    ttl_policy: str | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
    expires_at: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, object]:
    return {
        "text": text,
        "kind": kind,
        "confidence": confidence,
        "safe_reason": safe_reason,
        "operation": operation,
        "evidence_quote": evidence_quote,
        "category": None,
        "tags": tags if tags is not None else [],
        "ttl_policy": ttl_policy,
        "target_fact_id": None,
        "target_fact_version": None,
        "target_hint": target_hint,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "expires_at": expires_at,
    }


class FakeOpenAIError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__("redacted provider error")
        self.status_code = status_code
        self.code = code


class FakeGraphitiDriver:
    def __init__(self) -> None:
        self.name_lookup_count = 0

    async def execute_query(self, query: str, **kwargs: object):
        if "RETURN e.name AS name" in query:
            return ([{"name": "fact:fact_lookup"}], None, None)
        if "RETURN e.uuid AS uuid" in query:
            self.name_lookup_count += 1
            if self.name_lookup_count == 1:
                return ([], None, None)
            return ([{"uuid": "generated_episode_uuid"}], None, None)
        return ([], None, None)


class FakeClosableGraphitiDriver:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeGraphitiWithNestedDriver:
    def __init__(self) -> None:
        self.driver = FakeClosableGraphitiDriver()


class FakeGraphitiWithEpisodeLookup(FakeGraphiti):
    delete_episode = None

    def __init__(self) -> None:
        super().__init__()
        self.driver = FakeGraphitiDriver()

    async def remove_episode(self, episode_uuid: str) -> None:
        if episode_uuid == "fact_lookup":
            raise NodeNotFoundError("fact_lookup")
        self.deleted.append(episode_uuid)

    async def search(self, **kwargs: object) -> list[object]:
        self.search_calls.append(kwargs)
        return [SimpleNamespace(episodes=["generated_episode_uuid"], score=0.91)]


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


def test_graphiti_adapter_hydrates_only_canonical_fact_ids() -> None:
    async def run() -> None:
        fake = FakeGraphiti()
        adapter = GraphitiGraphMemoryAdapter(client=fake, build_indices=True)

        capabilities = await adapter.capabilities()
        upsert = await adapter.upsert_fact(
            "fact_graphiti",
            "Graphiti projection source text.",
            {
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "updated_at": "2026-05-25T10:00:00+00:00",
            },
        )
        search = await adapter.search(
            space_id="space_client_app",
            memory_scope_ids=("memory_scope_default",),
            query="Graphiti projection",
            limit=3,
        )
        deleted = await adapter.delete_fact("fact_graphiti")

        assert capabilities.enabled is True
        assert fake.built == 1
        assert upsert.status == PortStatus.OK
        assert fake.episodes[0]["name"] == "fact:fact_graphiti"
        assert "uuid" not in fake.episodes[0]
        assert fake.episodes[0]["group_id"] == "memory__space_client_app__memory_scope_default"
        assert fake.search_calls[0]["group_ids"] == [
            "memory__space_client_app__memory_scope_default"
        ]
        assert search.items[0].source_fact_ids == ("fact_graphiti",)
        assert deleted.status == PortStatus.OK
        assert fake.deleted == ["fact:fact_graphiti"]

    asyncio.run(run())


def test_graphiti_adapter_overfetches_thread_queries_for_postgres_visibility_hydration() -> None:
    async def run() -> None:
        fake = FakeGraphiti()
        adapter = GraphitiGraphMemoryAdapter(client=fake)

        search = await adapter.search(
            space_id="space_client_app",
            memory_scope_ids=("memory_scope_default",),
            thread_id="thread_current",
            query="Graphiti projection",
            limit=3,
        )

        assert search.status == PortStatus.OK
        assert fake.search_calls[0]["num_results"] == 12

    asyncio.run(run())


def test_graphiti_adapter_reports_invalid_provider_key_without_retry() -> None:
    async def run() -> None:
        fake = FakeFailingGraphiti(FakeOpenAIError(status_code=401, code="invalid_api_key"))
        adapter = GraphitiGraphMemoryAdapter(client=fake)

        result = await adapter.upsert_fact(
            "fact_graphiti",
            "Graphiti projection source text.",
            {"space_id": "space_client_app", "memory_scope_id": "memory_scope_default"},
        )

        assert result.status == PortStatus.DEGRADED
        assert result.diagnostics[0].code == "graph.invalid_api_key"
        assert result.diagnostics[0].retryable is False

    asyncio.run(run())


def test_graphiti_adapter_reports_rate_limit_as_retryable() -> None:
    async def run() -> None:
        fake = FakeFailingGraphiti(FakeOpenAIError(status_code=429))
        adapter = GraphitiGraphMemoryAdapter(client=fake)

        result = await adapter.upsert_fact(
            "fact_graphiti",
            "Graphiti projection source text.",
            {"space_id": "space_client_app", "memory_scope_id": "memory_scope_default"},
        )

        assert result.status == PortStatus.DEGRADED
        assert result.diagnostics[0].code == "graph.rate_limited"
        assert result.diagnostics[0].retryable is True

    asyncio.run(run())


def test_graphiti_search_facts_caps_thread_overfetch_to_requested_limit() -> None:
    async def run() -> None:
        fake = FakeGraphitiWithManyResults()
        adapter = GraphitiGraphMemoryAdapter(client=fake)

        recalled = await adapter.search_facts(
            CapabilityRecallQuery(
                scope=MemoryScopeFilter(
                    space_id="space_client_app",
                    memory_scope_ids=("memory_scope_default",),
                    thread_id="thread_current",
                ),
                query="Graphiti projection",
                limit=2,
            )
        )

        assert recalled.status == CapabilityStatus.OK
        assert fake.search_calls[0]["num_results"] == 8
        assert [item.item_id for item in recalled.items] == ["fact_many_0", "fact_many_1"]

    asyncio.run(run())


def test_graphiti_adapter_exposes_temporal_capability_ports() -> None:
    async def run() -> None:
        fake = FakeGraphiti()
        adapter = GraphitiGraphMemoryAdapter(client=fake)

        descriptors = await adapter.capability_descriptors()
        health = await adapter.health()
        projected = await adapter.upsert_fact_projection(
            FactProjectionWrite(
                fact_id="fact_graphiti",
                space_id="space_client_app",
                memory_scope_id="memory_scope_default",
                text="Graphiti projection source text must not be returned from search.",
                version=1,
                source_refs=(),
            )
        )
        recalled = await adapter.search_facts(
            CapabilityRecallQuery(
                scope=MemoryScopeFilter(
                    space_id="space_client_app",
                    memory_scope_ids=("memory_scope_default",),
                ),
                query="Graphiti projection",
                limit=3,
            )
        )
        forgotten = await adapter.forget_projection(
            ProjectionForgetRequest(canonical_ids=("fact_graphiti",), reason="test cleanup")
        )

        descriptor_pairs = {
            (descriptor.adapter_name, descriptor.capability) for descriptor in descriptors
        }
        assert descriptor_pairs == {
            ("graphiti", MemoryCapability.TEMPORAL_FACT_GRAPH),
            ("graphiti", MemoryCapability.FACT_PROJECTION),
            ("graphiti", MemoryCapability.PROJECTION_FORGET),
        }
        assert health.status == CapabilityStatus.OK
        assert projected.status == CapabilityStatus.OK
        assert projected.affected_ids == ("fact_graphiti",)
        assert recalled.status == CapabilityStatus.OK
        assert recalled.items[0].item_id == "fact_graphiti"
        assert recalled.items[0].text == "fact_graphiti"
        assert "projection source text" not in recalled.items[0].text
        assert forgotten.status == CapabilityStatus.OK

    asyncio.run(run())


def test_graphiti_adapter_resolves_generated_episode_uuid_by_name() -> None:
    async def run() -> None:
        fake = FakeGraphitiWithEpisodeLookup()
        adapter = GraphitiGraphMemoryAdapter(client=fake)

        upsert = await adapter.upsert_fact(
            "fact_lookup",
            "Graphiti generated episode UUID must still hydrate canonical fact id.",
            {
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "updated_at": "2026-05-25T10:00:00+00:00",
            },
        )
        search = await adapter.search(
            space_id="space_client_app",
            memory_scope_ids=("memory_scope_default",),
            query="generated episode uuid",
            limit=3,
        )
        deleted = await adapter.delete_fact("fact_lookup")

        assert upsert.status == PortStatus.OK
        assert "uuid" not in fake.episodes[0]
        assert search.items[0].source_fact_ids == ("fact_lookup",)
        assert deleted.status == PortStatus.OK
        assert fake.deleted == ["generated_episode_uuid"]

    asyncio.run(run())


def test_graphiti_capability_mismatch_disables_graph() -> None:
    async def run() -> None:
        adapter = GraphitiGraphMemoryAdapter(client=FakeGraphitiWithoutSearch())

        capabilities = await adapter.capabilities()
        descriptors = await adapter.capability_descriptors()
        search = await adapter.search(
            space_id="space_client_app",
            memory_scope_ids=("memory_scope_default",),
            query="Graphiti projection",
            limit=3,
        )

        temporal = next(
            descriptor
            for descriptor in descriptors
            if descriptor.capability == MemoryCapability.TEMPORAL_FACT_GRAPH
        )
        assert capabilities.enabled is True
        assert capabilities.healthy is False
        assert capabilities.supports_search is False
        assert capabilities.degraded_reason == "graphiti.capability_mismatch"
        assert temporal.enabled is False
        assert temporal.status == CapabilityStatus.UNAVAILABLE
        assert temporal.degraded_reason == "graphiti.capability_mismatch"
        assert search.status == PortStatus.DEGRADED
        assert search.diagnostics[0].code == "graph.missing_search"
        assert search.diagnostics[0].retryable is False

    asyncio.run(run())


def test_noop_graph_adapter_exposes_disabled_temporal_capabilities() -> None:
    async def run() -> None:
        adapter = NoopGraphMemoryAdapter()

        descriptors = await adapter.capability_descriptors()
        health = await adapter.health()
        recalled = await adapter.search_facts(
            CapabilityRecallQuery(
                scope=MemoryScopeFilter(space_id="space", memory_scope_ids=("memory_scope",)),
                query="anything",
                limit=1,
            )
        )

        assert all(descriptor.status == CapabilityStatus.DISABLED for descriptor in descriptors)
        assert health.status == CapabilityStatus.DISABLED
        assert recalled.status == CapabilityStatus.DISABLED
        assert recalled.items == ()

    asyncio.run(run())


def test_noop_vector_adapter_contract_fails_closed_without_candidates() -> None:
    async def run() -> None:
        adapter = NoopVectorMemoryAdapter()

        capabilities = await adapter.capabilities()
        search = await adapter.search_chunks(
            space_id="space",
            memory_scope_ids=("memory_scope",),
            query_vector=(0.1, 0.2, 0.3),
            limit=3,
        )
        upsert = await adapter.upsert_chunks(
            (
                VectorUpsertItem(
                    chunk_id="chunk_1",
                    space_id="space",
                    memory_scope_id="memory_scope",
                    thread_id=None,
                    text="Noop vector source text.",
                    vector=(0.1, 0.2, 0.3),
                    projection_version="v1",
                ),
            )
        )
        deleted = await adapter.delete_chunks(("chunk_1",))

        assert capabilities.enabled is False
        assert capabilities.supports_search is False
        assert search.status == PortStatus.DEGRADED
        assert search.items == ()
        assert search.diagnostics[0].code == "vector.disabled"
        assert search.diagnostics[0].retryable is False
        assert upsert.status == PortStatus.DEGRADED
        assert upsert.diagnostics[0].retryable is False
        assert deleted.status == PortStatus.DEGRADED
        assert deleted.diagnostics[0].retryable is False

    asyncio.run(run())


def test_noop_embedding_adapter_contract_fails_closed_without_vectors() -> None:
    async def run() -> None:
        adapter = NoopEmbeddingAdapter()

        capabilities = await adapter.capabilities()
        result = await adapter.embed_texts(("query text",))

        assert capabilities.enabled is False
        assert capabilities.supports_search is False
        assert result.status == PortStatus.DEGRADED
        assert result.vectors == ()
        assert result.diagnostics[0].code == "embeddings.disabled"
        assert result.diagnostics[0].retryable is False

    asyncio.run(run())


def test_openai_embedding_adapter_returns_vectors_and_closes_client() -> None:
    async def run() -> None:
        client = FakeOpenAIEmbeddingClient(
            response=SimpleNamespace(
                data=[
                    SimpleNamespace(embedding=[0.1, 0.2, 0.3]),
                    SimpleNamespace(embedding=[0.4, 0.5, 0.6]),
                ]
            )
        )
        adapter = FakeOpenAIEmbeddingAdapter(client)

        result = await adapter.embed_texts(("first", "second"))

        assert result.status == PortStatus.OK
        assert result.vectors == ((0.1, 0.2, 0.3), (0.4, 0.5, 0.6))
        assert result.model == "text-embedding-3-small"
        assert result.dimensions == 3
        assert client.embeddings.calls == [
            {
                "model": "text-embedding-3-small",
                "input": ["first", "second"],
                "dimensions": 3,
            }
        ]
        assert client.closed is True

    asyncio.run(run())


def test_openai_embedding_adapter_reports_invalid_key_without_retry() -> None:
    async def run() -> None:
        client = FakeOpenAIEmbeddingClient(
            error=FakeOpenAIError(status_code=401, code="invalid_api_key")
        )
        adapter = FakeOpenAIEmbeddingAdapter(client)

        result = await adapter.embed_texts(("query",))

        assert result.status == PortStatus.DEGRADED
        assert result.vectors == ()
        assert result.diagnostics[0].code == "embeddings.invalid_api_key"
        assert result.diagnostics[0].retryable is False
        assert client.closed is True

    asyncio.run(run())


def test_openai_embedding_adapter_reports_rate_limit_as_retryable() -> None:
    async def run() -> None:
        client = FakeOpenAIEmbeddingClient(error=FakeOpenAIError(status_code=429))
        adapter = FakeOpenAIEmbeddingAdapter(client)

        result = await adapter.embed_texts(("query",))

        assert result.status == PortStatus.DEGRADED
        assert result.diagnostics[0].code == "embeddings.rate_limited"
        assert result.diagnostics[0].retryable is True
        assert client.closed is True

    asyncio.run(run())


def test_openai_embedding_adapter_keeps_unknown_errors_retryable() -> None:
    async def run() -> None:
        client = FakeOpenAIEmbeddingClient(error=RuntimeError("redacted provider down"))
        adapter = FakeOpenAIEmbeddingAdapter(client)

        result = await adapter.embed_texts(("query",))

        assert result.status == PortStatus.DEGRADED
        assert result.diagnostics[0].code == "embeddings.provider_error"
        assert result.diagnostics[0].retryable is True
        assert client.closed is True

    asyncio.run(run())


def test_cognee_skeleton_is_disabled_without_importing_runtime_sdk() -> None:
    async def run() -> None:
        adapter = CogneeMemoryAdapter()

        capabilities = await adapter.capabilities()
        descriptors = await adapter.capability_descriptors()
        health = await adapter.health()
        recalled = await adapter.recall(
            CapabilityRecallQuery(
                scope=MemoryScopeFilter(space_id="space", memory_scope_ids=("memory_scope",)),
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


def test_cognee_runtime_adapter_remembers_and_recalls_by_scoped_dataset() -> None:
    async def run() -> None:
        fake = FakeCognee()
        adapter = CogneeMemoryAdapter(enabled=True, client=fake, dataset_prefix="mp")

        capabilities = await adapter.capabilities()
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
        assert projected.status == CapabilityStatus.OK
        assert projected.affected_ids == ("doc_1",)
        assert (
            fake.remember_calls[0]["dataset_name"] == "mp__space_client_app__memory_scope_default"
        )
        assert fake.remember_calls[0]["node_set"] == ["chunk_canonical_1"]
        assert fake.recall_calls[0]["datasets"] == ["mp__space_client_app__memory_scope_default"]
        assert fake.recall_calls[0]["top_k"] == 5
        assert recalled.status == CapabilityStatus.OK
        assert recalled.items[0].text == "Cognee recalled tenant scoped document chunk."
        assert recalled.items[0].source_refs[0].source_type == "chunk"
        assert recalled.items[0].source_refs[0].chunk_id == "chunk_canonical_1"

    asyncio.run(run())


def test_graphiti_adapter_supports_modern_remove_episode_delete() -> None:
    async def run() -> None:
        fake = FakeModernGraphiti()
        adapter = GraphitiGraphMemoryAdapter(client=fake)

        deleted = await adapter.delete_fact("fact_graphiti")

        assert deleted.status == PortStatus.OK
        assert fake.deleted == ["fact_graphiti"]

    asyncio.run(run())


def test_graphiti_adapter_closes_nested_driver_resource() -> None:
    async def run() -> None:
        fake = FakeGraphitiWithNestedDriver()
        adapter = GraphitiGraphMemoryAdapter(client=fake)

        await adapter.aclose()

        assert fake.driver.closed is True

    asyncio.run(run())


def test_configured_graphiti_without_client_degrades_instead_of_disabling(monkeypatch) -> None:
    class BrokenGraphiti:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("neo4j unavailable")

    async def run() -> None:
        if importlib.util.find_spec("graphiti_core") is not None:
            import graphiti_core

            monkeypatch.setattr(graphiti_core, "Graphiti", BrokenGraphiti)
        adapter = GraphitiGraphMemoryAdapter(
            neo4j_uri="bolt://graphiti.test:7687",
            neo4j_user="neo4j",
            neo4j_password="infinitycontextgraph",
        )
        try:
            capabilities = await adapter.capabilities()
            upsert = await adapter.upsert_fact(
                "fact_graphiti_missing",
                "Graphiti unavailable projection text.",
                {
                    "space_id": "space_client_app",
                    "memory_scope_id": "memory_scope_default",
                    "updated_at": "2026-05-25T10:00:00+00:00",
                },
            )
            search = await adapter.search(
                space_id="space_client_app",
                memory_scope_ids=("memory_scope_default",),
                query="Graphiti unavailable",
                limit=3,
            )

            assert capabilities.enabled is False
            assert capabilities.healthy is False
            assert capabilities.degraded_reason == "graphiti_unavailable"
            assert upsert.status == PortStatus.DEGRADED
            assert upsert.diagnostics[0].code in {"graph.unavailable", "graph.upsert_failed"}
            assert upsert.diagnostics[0].retryable is True
            assert search.status == PortStatus.DEGRADED
            assert search.diagnostics[0].code in {"graph.unavailable", "graph.search_failed"}
            assert search.diagnostics[0].retryable is True
        finally:
            await adapter.aclose()

    asyncio.run(run())


class FakeQdrantModels:
    class Distance:
        COSINE = "Cosine"

    class Modifier:
        IDF = "idf"

    class VectorParams:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class SparseVectorParams:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class SparseVector:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class PointStruct:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class PointIdsList:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class Filter:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class FieldCondition:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class MatchValue:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class MatchAny:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class PayloadField:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class IsNullCondition:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class IsEmptyCondition:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class MinShould:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs


class FakeQdrantClient:
    def __init__(self) -> None:
        self.collections: set[str] = set()
        self.upserts = 0
        self.create_collection_calls: list[dict[str, object]] = []
        self.upsert_points: list[list[object]] = []
        self.query_calls: list[dict[str, object]] = []
        self.query_points_by_using: dict[object, list[object]] = {}

    async def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    async def create_collection(self, **kwargs: object) -> None:
        collection_name = str(kwargs["collection_name"])
        vectors_config = kwargs["vectors_config"]
        self.collections.add(collection_name)
        self.create_collection_calls.append(kwargs)
        assert vectors_config is not None

    async def upsert(self, *, collection_name: str, points: list[object], wait: bool) -> None:
        assert collection_name in self.collections
        assert points
        assert wait is True
        self.upserts += 1
        self.upsert_points.append(points)

    async def delete(self, **_kwargs: object) -> None:
        assert _kwargs["wait"] is True
        return None

    async def query_points(self, **_kwargs: object) -> object:
        self.query_calls.append(_kwargs)
        points = self.query_points_by_using.get(_kwargs.get("using"))
        if points is None:
            points = [
                _fake_qdrant_point(
                    chunk_id="chunk_1",
                    score=0.9,
                )
            ]
        return SimpleNamespace(points=points)


def _fake_qdrant_point(
    *,
    chunk_id: str,
    score: float,
    space_id: str = "space_client_app",
    memory_scope_id: str = "memory_scope_default",
    projection_version: str = "v1",
) -> object:
    return SimpleNamespace(
        payload={
            "chunk_id": chunk_id,
            "space_id": space_id,
            "memory_scope_id": memory_scope_id,
            "projection_version": projection_version,
        },
        score=score,
    )


class FakeSparseEmbedding:
    def __init__(self, *, indices: tuple[int, ...], values: tuple[float, ...]) -> None:
        self.indices = indices
        self.values = values


class FakeSparseEncoder:
    def __init__(self) -> None:
        self.documents: list[str] = []
        self.queries: list[str] = []

    def embed(self, *, documents: list[str]) -> list[FakeSparseEmbedding]:
        self.documents.extend(documents)
        return [FakeSparseEmbedding(indices=(7, 11), values=(1.0, 0.5))]

    def query_embed(self, *, query: list[str]) -> list[FakeSparseEmbedding]:
        self.queries.extend(query)
        return [FakeSparseEmbedding(indices=(11, 19), values=(1.5, 0.75))]


class FakeQdrantWrongSizeClient(FakeQdrantClient):
    def __init__(self) -> None:
        super().__init__()
        self.collections.add("infinity_context_chunks_v1")

    async def get_collection(self, *, collection_name: str) -> object:
        assert collection_name == "infinity_context_chunks_v1"
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(vectors=SimpleNamespace(size=2)),
            )
        )


class FakeQdrantUnavailableClient(FakeQdrantClient):
    async def collection_exists(self, collection_name: str) -> bool:
        raise TimeoutError("qdrant unavailable")


def test_qdrant_adapter_creates_collection_before_upsert_and_search() -> None:
    async def run() -> None:
        fake = FakeQdrantClient()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test",
            collection_name="infinity_context_chunks_v1",
            vector_size=3,
        )
        adapter._client = lambda: _fake_qdrant_client(fake)  # type: ignore[method-assign]

        upsert = await adapter.upsert_chunks(
            (
                VectorUpsertItem(
                    chunk_id="chunk_1",
                    space_id="space_client_app",
                    memory_scope_id="memory_scope_default",
                    thread_id=None,
                    text="Qdrant projection text.",
                    vector=(0.1, 0.2, 0.3),
                    projection_version="v1",
                ),
            )
        )
        search = await adapter.search_chunks(
            space_id="space_client_app",
            memory_scope_ids=("memory_scope_default",),
            query_vector=(0.1, 0.2, 0.3),
            limit=3,
        )

        assert upsert.status == PortStatus.OK
        assert fake.upserts == 1
        assert search.items[0].chunk_id == "chunk_1"

    asyncio.run(run())


def test_qdrant_adapter_search_contract_uses_scope_and_projection_filters() -> None:
    async def run() -> None:
        fake = FakeQdrantClient()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test",
            collection_name="infinity_context_chunks_v1",
            vector_size=3,
            projection_version="projection_v2",
        )
        adapter._client = lambda: _fake_qdrant_client(fake)  # type: ignore[method-assign]

        search = await adapter.search_chunks(
            space_id="space_client_app",
            memory_scope_ids=("memory_scope_default", "memory_scope_candidate"),
            query_vector=(0.1, 0.2, 0.3),
            limit=3,
        )

        assert search.status == PortStatus.OK
        assert len(fake.query_calls) == 1
        query_filter = fake.query_calls[0]["query_filter"]
        must = query_filter.kwargs["must"]
        filters = {condition.kwargs["key"]: condition.kwargs["match"].kwargs for condition in must}
        assert filters == {
            "space_id": {"value": "space_client_app"},
            "projection_version": {"value": "projection_v2"},
            "memory_scope_id": {"any": ["memory_scope_default", "memory_scope_candidate"]},
        }

    asyncio.run(run())


def test_qdrant_adapter_search_contract_filters_current_thread_or_memory_scope_wide_chunks() -> (
    None
):
    async def run() -> None:
        fake = FakeQdrantClient()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test",
            collection_name="infinity_context_chunks_v1",
            vector_size=3,
        )
        adapter._client = lambda: _fake_qdrant_client(fake)  # type: ignore[method-assign]

        search = await adapter.search_chunks(
            space_id="space_client_app",
            memory_scope_ids=("memory_scope_default",),
            thread_id="thread_current",
            query_vector=(0.1, 0.2, 0.3),
            limit=3,
        )

        assert search.status == PortStatus.OK
        query_filter = fake.query_calls[0]["query_filter"]
        min_should = query_filter.kwargs["min_should"]
        conditions = min_should.kwargs["conditions"]
        assert min_should.kwargs["min_count"] == 1
        assert conditions[0].kwargs["key"] == "thread_id"
        assert conditions[0].kwargs["match"].kwargs == {"value": "thread_current"}
        assert conditions[1].kwargs["is_null"].kwargs == {"key": "thread_id"}
        assert conditions[2].kwargs["is_empty"].kwargs == {"key": "thread_id"}

    asyncio.run(run())


def test_qdrant_hybrid_sparse_mode_creates_named_vectors_and_indexes_bm25() -> None:
    async def run() -> None:
        fake = FakeQdrantClient()
        sparse_encoder = FakeSparseEncoder()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test",
            collection_name="infinity_context_chunks_v1",
            vector_size=3,
            hybrid_sparse_enabled=True,
            sparse_encoder_factory=lambda: sparse_encoder,
        )
        adapter._client = lambda: _fake_qdrant_client(fake)  # type: ignore[method-assign]

        upsert = await adapter.upsert_chunks(
            (
                VectorUpsertItem(
                    chunk_id="chunk_hybrid",
                    space_id="space_client_app",
                    memory_scope_id="memory_scope_default",
                    thread_id=None,
                    text="Project Atlas uses BM25 sparse retrieval for exact markers.",
                    vector=(0.1, 0.2, 0.3),
                    projection_version="v1",
                ),
            )
        )

        assert upsert.status == PortStatus.OK
        create_call = fake.create_collection_calls[0]
        assert set(create_call["vectors_config"]) == {"dense"}
        assert set(create_call["sparse_vectors_config"]) == {"bm25"}
        dense_config = create_call["vectors_config"]["dense"]
        sparse_config = create_call["sparse_vectors_config"]["bm25"]
        assert dense_config.kwargs == {"size": 3, "distance": "Cosine"}
        assert sparse_config.kwargs == {"modifier": "idf"}
        point_vector = fake.upsert_points[0][0].kwargs["vector"]
        assert point_vector["dense"] == [0.1, 0.2, 0.3]
        assert point_vector["bm25"].kwargs == {"indices": [7, 11], "values": [1.0, 0.5]}
        assert sparse_encoder.documents == [
            "Project Atlas uses BM25 sparse retrieval for exact markers."
        ]

    asyncio.run(run())


def test_qdrant_hybrid_sparse_search_returns_sparse_only_candidates() -> None:
    async def run() -> None:
        fake = FakeQdrantClient()
        sparse_encoder = FakeSparseEncoder()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test",
            collection_name="infinity_context_chunks_v1",
            vector_size=3,
            hybrid_sparse_enabled=True,
            sparse_encoder_factory=lambda: sparse_encoder,
        )
        adapter._client = lambda: _fake_qdrant_client(fake)  # type: ignore[method-assign]
        fake.query_points_by_using = {
            "dense": [_fake_qdrant_point(chunk_id="dense_hit", score=0.9)],
            "bm25": [_fake_qdrant_point(chunk_id="sparse_only", score=0.7)],
        }

        search = await adapter.search_chunks(
            space_id="space_client_app",
            memory_scope_ids=("memory_scope_default",),
            query_vector=(0.1, 0.2, 0.3),
            query_text="exact BM25 marker",
            limit=3,
        )

        assert search.status == PortStatus.OK
        assert {candidate.chunk_id for candidate in search.items} == {
            "dense_hit",
            "sparse_only",
        }
        assert [call["using"] for call in fake.query_calls] == ["dense", "bm25"]
        assert fake.query_calls[1]["query"].kwargs == {
            "indices": [11, 19],
            "values": [1.5, 0.75],
        }
        assert sparse_encoder.queries == ["exact BM25 marker"]

    asyncio.run(run())


def test_qdrant_zero_limit_search_is_noop() -> None:
    async def run() -> None:
        fake = FakeQdrantClient()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test",
            collection_name="infinity_context_chunks_v1",
            vector_size=3,
        )
        adapter._client = lambda: _fake_qdrant_client(fake)  # type: ignore[method-assign]

        search = await adapter.search_chunks(
            space_id="space_client_app",
            memory_scope_ids=("memory_scope_default",),
            query_vector=(0.1, 0.2, 0.3),
            limit=0,
        )

        assert search.status == PortStatus.OK
        assert search.items == ()
        assert fake.collections == set()

    asyncio.run(run())


def test_qdrant_dimension_mismatch_fails_closed() -> None:
    async def run() -> None:
        fake = FakeQdrantWrongSizeClient()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test",
            collection_name="infinity_context_chunks_v1",
            vector_size=3,
        )
        adapter._client = lambda: _fake_qdrant_client(fake)  # type: ignore[method-assign]

        capabilities = await adapter.capabilities()
        upsert = await adapter.upsert_chunks(
            (
                VectorUpsertItem(
                    chunk_id="chunk_1",
                    space_id="space_client_app",
                    memory_scope_id="memory_scope_default",
                    thread_id=None,
                    text="Qdrant projection text.",
                    vector=(0.1, 0.2, 0.3),
                    projection_version="v1",
                ),
            )
        )
        search = await adapter.search_chunks(
            space_id="space_client_app",
            memory_scope_ids=("memory_scope_default",),
            query_vector=(0.1, 0.2, 0.3),
            limit=3,
        )

        assert capabilities.healthy is False
        assert capabilities.degraded_reason == "qdrant.dimension_mismatch"
        assert upsert.status == PortStatus.DEGRADED
        assert upsert.diagnostics[0].code == "qdrant.dimension_mismatch"
        assert upsert.diagnostics[0].retryable is False
        assert search.status == PortStatus.DEGRADED
        assert search.diagnostics[0].code == "qdrant.dimension_mismatch"
        assert fake.upserts == 0

    asyncio.run(run())


def test_qdrant_client_unavailable_fails_capability_closed() -> None:
    async def run() -> None:
        async def unavailable_client():
            raise ModuleNotFoundError("qdrant_client")

        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test",
            collection_name="infinity_context_chunks_v1",
            vector_size=3,
        )
        adapter._client = unavailable_client  # type: ignore[method-assign]

        capabilities = await adapter.capabilities()

        assert capabilities.enabled is False
        assert capabilities.healthy is False
        assert capabilities.degraded_reason == "qdrant_sdk_missing"

    asyncio.run(run())


def test_qdrant_server_unavailable_reports_configured_adapter_degraded() -> None:
    async def run() -> None:
        fake = FakeQdrantUnavailableClient()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test",
            collection_name="infinity_context_chunks_v1",
            vector_size=3,
        )
        adapter._client = lambda: _fake_qdrant_client(fake)  # type: ignore[method-assign]

        capabilities = await adapter.capabilities()

        assert capabilities.enabled is True
        assert capabilities.healthy is False
        assert capabilities.supports_search is False
        assert capabilities.degraded_reason == "qdrant_unavailable"

    asyncio.run(run())


def test_openai_json_memory_extractor_prompt_requires_rich_durable_evidence() -> None:
    prompt = _prompt_text()

    assert "durable incidental facts" in prompt
    assert "Assistant text can still be extracted" in prompt
    assert "concrete decision, recommendation, implementation result, or plan" in prompt
    assert "Split unrelated durable facts into separate candidates" in prompt
    assert "Do not convert relative dates by guessing" in prompt
    assert "Each candidate must include an exact evidence_quote substring" in prompt


def test_openai_json_memory_extractor_maps_structured_response() -> None:
    async def run() -> None:
        fake = FakeOpenAIClient(
            {
                "candidates": [
                    {
                        "text": "OPENAI_EXTRACT_MARKER Graphiti owns temporal projections.",
                        "kind": "architecture_decision",
                        "confidence": "high",
                        "safe_reason": "explicit_user_memory",
                        "operation": "add",
                        "evidence_quote": (
                            "OPENAI_EXTRACT_MARKER Graphiti owns temporal projections."
                        ),
                        "category": "architecture",
                        "tags": ["graphiti", "temporal"],
                        "ttl_policy": "durable",
                        "target_fact_id": None,
                        "target_fact_version": None,
                        "target_hint": None,
                        "valid_from": None,
                        "valid_until": None,
                        "expires_at": None,
                    }
                ]
            }
        )
        extractor = OpenAIJsonMemoryExtractor(
            api_key=None,
            model="test-extractor-model",
            client_factory=lambda: fake,
        )
        source = SourceProvenance(
            source_type="capture:hook",
            source_id="cap_test",
            trust_level=TrustLevel.MEDIUM,
        )

        candidates = await extractor.extract_facts(
            text="Remember: OPENAI_EXTRACT_MARKER Graphiti owns temporal projections.",
            source=source,
        )

        assert fake.closed is True
        assert fake.responses.calls[0]["model"] == "test-extractor-model"
        assert fake.responses.calls[0]["store"] is False
        assert fake.responses.calls[0]["text"]["format"]["type"] == "json_schema"
        assert len(candidates) == 1
        assert candidates[0].kind.value == "architecture_decision"
        assert candidates[0].confidence.value == "high"
        assert candidates[0].category == "architecture"
        assert candidates[0].tags == ("graphiti", "temporal")
        assert candidates[0].ttl_policy == "durable"
        assert candidates[0].target_hint is None
        assert candidates[0].source_refs[0].source_id == "cap_test"

    asyncio.run(run())


def test_openai_json_memory_extractor_maps_update_delete_and_noop() -> None:
    async def run() -> None:
        fake = FakeOpenAIClient(
            {
                "candidates": [
                    _openai_candidate_payload(
                        text="OPENAI_EVOLVE_MODE: Agent benchmark mode is stable.",
                        operation="update",
                        evidence_quote="Update memory: Agent benchmark mode alpha -> stable",
                        target_hint="Agent benchmark mode alpha",
                    ),
                    _openai_candidate_payload(
                        text="OPENAI_EVOLVE_REMOVE legacy hook cache",
                        operation="delete",
                        confidence="low",
                        evidence_quote="Forget legacy hook cache",
                        target_hint="legacy hook cache",
                        ttl_policy="delete_review",
                    ),
                    _openai_candidate_payload(
                        text="No durable memory.",
                        operation="noop",
                        confidence="low",
                        evidence_quote=None,
                    ),
                ]
            }
        )
        extractor = OpenAIJsonMemoryExtractor(
            api_key=None,
            model="test-extractor-model",
            client_factory=lambda: fake,
        )
        source = SourceProvenance(
            source_type="capture:hook",
            source_id="cap_evolution",
            trust_level=TrustLevel.MEDIUM,
        )

        candidates = await extractor.extract_facts(
            text=(
                "Update memory: Agent benchmark mode alpha -> stable. "
                "Forget legacy hook cache. This last sentence is noise."
            ),
            source=source,
        )

        assert [candidate.operation_hint for candidate in candidates] == [
            CandidateOperation.UPDATE,
            CandidateOperation.DELETE,
            CandidateOperation.NOOP,
        ]
        assert candidates[0].target_hint == "Agent benchmark mode alpha"
        assert candidates[1].target_hint == "legacy hook cache"
        assert candidates[1].ttl_policy == "delete_review"
        assert candidates[0].source_refs[0].quote_preview == (
            "Update memory: Agent benchmark mode alpha -> stable"
        )
        assert candidates[2].source_refs == ()

    asyncio.run(run())


def test_openai_json_memory_extractor_rejects_missing_evidence_for_memory_candidate() -> None:
    async def run() -> None:
        fake = FakeOpenAIClient(
            {
                "candidates": [
                    _openai_candidate_payload(
                        text="MISSING_EVIDENCE_MARKER should fail.",
                        operation="add",
                        evidence_quote=None,
                    )
                ]
            }
        )
        extractor = OpenAIJsonMemoryExtractor(
            api_key=None,
            model="test-extractor-model",
            client_factory=lambda: fake,
        )
        source = SourceProvenance(
            source_type="capture:hook",
            source_id="cap_missing_evidence",
            trust_level=TrustLevel.MEDIUM,
        )

        try:
            await extractor.extract_facts(text="MISSING_EVIDENCE_MARKER", source=source)
        except MemoryValidationError as exc:
            assert "evidence_quote_required" in str(exc)
        else:
            raise AssertionError("Expected missing evidence quote to fail")

    asyncio.run(run())


def test_openai_json_memory_extractor_rejects_invented_evidence_quote() -> None:
    async def run() -> None:
        fake = FakeOpenAIClient(
            {
                "candidates": [
                    _openai_candidate_payload(
                        text="INVENTED_EVIDENCE_MARKER should fail.",
                        operation="add",
                        evidence_quote="not present in source text",
                    )
                ]
            }
        )
        extractor = OpenAIJsonMemoryExtractor(
            api_key=None,
            model="test-extractor-model",
            client_factory=lambda: fake,
        )
        source = SourceProvenance(
            source_type="capture:hook",
            source_id="cap_invented_evidence",
            trust_level=TrustLevel.MEDIUM,
        )

        try:
            await extractor.extract_facts(text="INVENTED_EVIDENCE_MARKER", source=source)
        except MemoryValidationError as exc:
            assert "evidence_quote_not_found" in str(exc)
        else:
            raise AssertionError("Expected invented evidence quote to fail")

    asyncio.run(run())


def test_openai_json_memory_extractor_rejects_invalid_ttl_policy() -> None:
    async def run() -> None:
        fake = FakeOpenAIClient(
            {
                "candidates": [
                    _openai_candidate_payload(
                        text="INVALID_TTL_MARKER should fail.",
                        operation="add",
                        evidence_quote="INVALID_TTL_MARKER",
                        ttl_policy="forever",
                    )
                ]
            }
        )
        extractor = OpenAIJsonMemoryExtractor(
            api_key=None,
            model="test-extractor-model",
            client_factory=lambda: fake,
        )
        source = SourceProvenance(
            source_type="capture:hook",
            source_id="cap_invalid_ttl",
            trust_level=TrustLevel.MEDIUM,
        )

        try:
            await extractor.extract_facts(text="INVALID_TTL_MARKER", source=source)
        except MemoryValidationError as exc:
            assert "invalid_ttl_policy" in str(exc)
        else:
            raise AssertionError("Expected invalid TTL policy to fail")

    asyncio.run(run())


def test_openai_json_memory_extractor_rejects_naive_datetime() -> None:
    async def run() -> None:
        fake = FakeOpenAIClient(
            {
                "candidates": [
                    _openai_candidate_payload(
                        text="NAIVE_TIME_MARKER should fail.",
                        operation="add",
                        evidence_quote="NAIVE_TIME_MARKER",
                        valid_from="2026-01-01T12:00:00",
                    )
                ]
            }
        )
        extractor = OpenAIJsonMemoryExtractor(
            api_key=None,
            model="test-extractor-model",
            client_factory=lambda: fake,
        )
        source = SourceProvenance(
            source_type="capture:hook",
            source_id="cap_naive_datetime",
            trust_level=TrustLevel.MEDIUM,
        )

        try:
            await extractor.extract_facts(text="NAIVE_TIME_MARKER", source=source)
        except MemoryValidationError as exc:
            assert "valid_from_invalid" in str(exc)
        else:
            raise AssertionError("Expected naive extractor datetime to fail")

    asyncio.run(run())


def test_openai_json_memory_extractor_rejects_oversized_candidate_text() -> None:
    async def run() -> None:
        fake = FakeOpenAIClient(
            {
                "candidates": [
                    _openai_candidate_payload(
                        text="TEXT_SIZE_MARKER " + ("x" * 1200),
                        operation="add",
                        evidence_quote="TEXT_SIZE_MARKER",
                    )
                ]
            }
        )
        extractor = OpenAIJsonMemoryExtractor(
            api_key=None,
            model="test-extractor-model",
            client_factory=lambda: fake,
        )
        source = SourceProvenance(
            source_type="capture:hook",
            source_id="cap_text_size",
            trust_level=TrustLevel.MEDIUM,
        )

        try:
            await extractor.extract_facts(text="TEXT_SIZE_MARKER", source=source)
        except MemoryValidationError as exc:
            assert "text_too_large" in str(exc)
        else:
            raise AssertionError("Expected oversized extractor text to fail")

    asyncio.run(run())


def test_openai_json_memory_extractor_rejects_oversized_target_hint() -> None:
    async def run() -> None:
        fake = FakeOpenAIClient(
            {
                "candidates": [
                    _openai_candidate_payload(
                        text="TARGET_HINT_SIZE_MARKER should fail.",
                        operation="update",
                        evidence_quote="TARGET_HINT_SIZE_MARKER",
                        target_hint="h" * 241,
                    )
                ]
            }
        )
        extractor = OpenAIJsonMemoryExtractor(
            api_key=None,
            model="test-extractor-model",
            client_factory=lambda: fake,
        )
        source = SourceProvenance(
            source_type="capture:hook",
            source_id="cap_target_hint_size",
            trust_level=TrustLevel.MEDIUM,
        )

        try:
            await extractor.extract_facts(text="TARGET_HINT_SIZE_MARKER", source=source)
        except MemoryValidationError as exc:
            assert "target_hint_too_large" in str(exc)
        else:
            raise AssertionError("Expected oversized extractor target hint to fail")

    asyncio.run(run())


def test_openai_json_memory_extractor_rejects_schema_invalid_tags() -> None:
    async def run_too_many() -> None:
        fake = FakeOpenAIClient(
            {
                "candidates": [
                    _openai_candidate_payload(
                        text="TOO_MANY_TAGS_MARKER should fail.",
                        operation="add",
                        evidence_quote="TOO_MANY_TAGS_MARKER",
                        tags=[f"tag_{index}" for index in range(11)],
                    )
                ]
            }
        )
        extractor = OpenAIJsonMemoryExtractor(
            api_key=None,
            model="test-extractor-model",
            client_factory=lambda: fake,
        )
        source = SourceProvenance(
            source_type="capture:hook",
            source_id="cap_too_many_tags",
            trust_level=TrustLevel.MEDIUM,
        )

        try:
            await extractor.extract_facts(text="TOO_MANY_TAGS_MARKER", source=source)
        except MemoryValidationError as exc:
            assert "too_many_tags" in str(exc)
        else:
            raise AssertionError("Expected too many extractor tags to fail")

    async def run_too_large() -> None:
        fake = FakeOpenAIClient(
            {
                "candidates": [
                    _openai_candidate_payload(
                        text="TAG_SIZE_MARKER should fail.",
                        operation="add",
                        evidence_quote="TAG_SIZE_MARKER",
                        tags=["x" * 49],
                    )
                ]
            }
        )
        extractor = OpenAIJsonMemoryExtractor(
            api_key=None,
            model="test-extractor-model",
            client_factory=lambda: fake,
        )
        source = SourceProvenance(
            source_type="capture:hook",
            source_id="cap_tag_size",
            trust_level=TrustLevel.MEDIUM,
        )

        try:
            await extractor.extract_facts(text="TAG_SIZE_MARKER", source=source)
        except MemoryValidationError as exc:
            assert "tag_too_large" in str(exc)
        else:
            raise AssertionError("Expected oversized extractor tag to fail")

    asyncio.run(run_too_many())
    asyncio.run(run_too_large())


def test_openai_json_memory_extractor_rejects_unknown_output_fields() -> None:
    async def run() -> None:
        fake = FakeOpenAIClient(
            {
                "candidates": [
                    {
                        "text": "UNKNOWN_FIELD_MARKER should fail.",
                        "kind": "note",
                        "confidence": "medium",
                        "safe_reason": "explicit_user_memory",
                        "operation": "add",
                        "evidence_quote": "UNKNOWN_FIELD_MARKER",
                        "category": None,
                        "tags": [],
                        "ttl_policy": None,
                        "target_fact_id": None,
                        "target_fact_version": None,
                        "target_hint": None,
                        "valid_from": None,
                        "valid_until": None,
                        "expires_at": None,
                        "unexpected": "must fail",
                    }
                ]
            }
        )
        extractor = OpenAIJsonMemoryExtractor(
            api_key=None,
            model="test-extractor-model",
            client_factory=lambda: fake,
        )
        source = SourceProvenance(
            source_type="capture:hook",
            source_id="cap_test",
            trust_level=TrustLevel.MEDIUM,
        )

        try:
            await extractor.extract_facts(text="UNKNOWN_FIELD_MARKER", source=source)
        except MemoryValidationError as exc:
            assert "candidate_unknown_field" in str(exc)
        else:
            raise AssertionError("Expected unknown extractor field to fail")

    asyncio.run(run())


def test_openai_json_memory_extractor_provider_error_is_retryable_infra_error() -> None:
    async def run() -> None:
        fake = FakeOpenAIClient(payload=None)
        extractor = OpenAIJsonMemoryExtractor(
            api_key=None,
            model="test-extractor-model",
            client_factory=lambda: fake,
        )
        source = SourceProvenance(
            source_type="capture:hook",
            source_id="cap_test",
            trust_level=TrustLevel.MEDIUM,
        )

        try:
            await extractor.extract_facts(text="Remember: RETRY_MARKER.", source=source)
        except MemoryInfrastructureError as exc:
            assert "provider_error" in str(exc)
        else:
            raise AssertionError("Expected provider error")

    asyncio.run(run())


async def _fake_qdrant_client(client: FakeQdrantClient) -> tuple[FakeQdrantClient, type]:
    return client, FakeQdrantModels


def test_graphiti_enabled_requires_neo4j_password() -> None:
    settings = Settings(graphiti_enabled=True)

    try:
        settings.validate_for_startup()
    except RuntimeError as exc:
        assert "MEMORY_GRAPHITI_NEO4J_PASSWORD" in str(exc)
    else:
        raise AssertionError("Expected Graphiti config validation to fail")


def test_qdrant_hybrid_sparse_requires_qdrant_enabled() -> None:
    settings = Settings(qdrant_hybrid_sparse_enabled=True)

    try:
        settings.validate_for_startup()
    except RuntimeError as exc:
        assert "MEMORY_QDRANT_HYBRID_SPARSE_ENABLED" in str(exc)
    else:
        raise AssertionError("Expected Qdrant hybrid config validation to fail")


def test_qdrant_hybrid_sparse_vector_names_must_differ() -> None:
    settings = Settings(
        qdrant_enabled=True,
        qdrant_hybrid_sparse_enabled=True,
        qdrant_dense_vector_name="bm25",
        qdrant_sparse_vector_name="bm25",
        embeddings_enabled=True,
        embeddings_provider="openai",
        openai_api_key="test-key",
    )

    try:
        settings.validate_for_startup()
    except RuntimeError as exc:
        assert "MEMORY_QDRANT_DENSE_VECTOR_NAME" in str(exc)
    else:
        raise AssertionError("Expected Qdrant vector name validation to fail")


def test_cognee_config_is_disabled_by_default() -> None:
    settings = Settings()

    assert settings.cognee_enabled is False
    assert settings.cognee_runtime_configured is False


def test_embeddings_enabled_requires_supported_provider_and_api_key() -> None:
    noop_settings = Settings(embeddings_enabled=True, embeddings_provider="noop")
    missing_key_settings = Settings(embeddings_enabled=True, embeddings_provider="openai")

    try:
        noop_settings.validate_for_startup()
    except RuntimeError as exc:
        assert "MEMORY_EMBEDDINGS_PROVIDER" in str(exc)
    else:
        raise AssertionError("Expected noop embedding provider validation to fail")

    try:
        missing_key_settings.validate_for_startup()
    except RuntimeError as exc:
        assert "MEMORY_OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected missing OpenAI key validation to fail")


def test_capture_openai_extractor_requires_supported_provider_and_api_key() -> None:
    bad_provider = Settings(capture_extractor_provider="unsupported")
    missing_key = Settings(
        capture_extractor_provider="openai",
        capture_external_ai_enabled=True,
    )

    try:
        bad_provider.validate_for_startup()
    except RuntimeError as exc:
        assert "MEMORY_CAPTURE_EXTRACTOR_PROVIDER" in str(exc)
    else:
        raise AssertionError("Expected unsupported extractor provider validation to fail")

    try:
        missing_key.validate_for_startup()
    except RuntimeError as exc:
        assert "MEMORY_OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected missing OpenAI key validation to fail")


def test_real_provider_disabled_in_test_memory_scope() -> None:
    settings = Settings(
        deploy_profile="test",
        embeddings_enabled=True,
        embeddings_provider="openai",
        openai_api_key="test-key",
    )

    try:
        settings.validate_for_startup()
    except RuntimeError as exc:
        assert "test deploy profile cannot use external adapters" in str(exc)
    else:
        raise AssertionError("Expected test deploy profile external provider validation to fail")
