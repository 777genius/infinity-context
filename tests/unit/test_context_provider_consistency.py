import asyncio
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from memo_stack_adapters.noop import (
    NoopEmbeddingAdapter,
    NoopGraphMemoryAdapter,
    NoopVectorMemoryAdapter,
)
from memo_stack_core.application import (
    BuildContextQuery,
    BuildContextUseCase,
    ConsistencyMode,
    ContextItem,
    EnsureScopeCommand,
    ForgetFactCommand,
)
from memo_stack_core.domain.entities import ProfileId, SourceRef, SpaceId
from memo_stack_core.ports.adapters import (
    AdapterCapabilities,
    EmbeddingResult,
    GraphCandidate,
    GraphSearchResult,
    PortStatus,
    VectorCandidate,
    VectorSearchResult,
)
from memo_stack_core.ports.capabilities import (
    CapabilityRecallCandidate,
    CapabilityRecallQuery,
    CapabilityRecallResult,
    CapabilityStatus,
    MemoryCapability,
)
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.main import create_app
from memo_stack_server.provider_budget import QueryEmbeddingBudgetAdapter
from memo_stack_server.provider_circuit import (
    CircuitBreakingEmbeddingAdapter,
    CircuitBreakingGraphMemoryAdapter,
    CircuitBreakingVectorMemoryAdapter,
    ProviderCircuitBreaker,
)


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            legacy_client_enabled=True,
        )
    )
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def legacy_event(session_id: str, event_id: str, text: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "event_id": event_id,
        "source": "system_audio",
        "seq_start": 1,
        "seq_end": 1,
        "text": text,
        "language": "ru",
        "kind_hint": "constraint",
        "metadata": {
            "source_event_id": event_id,
            "explicit_interview_context": True,
            "attached_to_prompt": False,
            "final_answer": False,
            "request_scoped": False,
        },
    }


class FakeGraphAdapter:
    def __init__(self, fact_id: str) -> None:
        self._fact_id = fact_id
        self.search_calls: list[dict[str, object]] = []

    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name="fake-graph",
            enabled=True,
            healthy=True,
            supports_upsert=True,
            supports_delete=True,
            supports_search=True,
            supports_filters=True,
            supports_temporal_queries=True,
        )

    async def search(self, **_kwargs: object) -> GraphSearchResult:
        self.search_calls.append(_kwargs)
        return GraphSearchResult.ok(
            [
                GraphCandidate(
                    source_fact_ids=(self._fact_id,),
                    source_chunk_ids=(),
                    relation_label="test",
                    score=1.0,
                    diagnostics={},
                )
            ]
        )


class OrphanGraphAdapter:
    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name="orphan-graph",
            enabled=True,
            healthy=True,
            supports_upsert=True,
            supports_delete=True,
            supports_search=True,
            supports_filters=True,
            supports_temporal_queries=True,
        )

    async def search(self, **_kwargs: object) -> GraphSearchResult:
        return GraphSearchResult.ok(
            [
                GraphCandidate(
                    source_fact_ids=(),
                    source_chunk_ids=(),
                    relation_label="orphan_relation",
                    score=0.99,
                    diagnostics={"provider": "test"},
                )
            ]
        )


class SchemaMismatchGraphAdapter:
    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name="schema-mismatch-graph",
            enabled=True,
            healthy=True,
            supports_upsert=True,
            supports_delete=True,
            supports_search=True,
            supports_filters=True,
            supports_temporal_queries=True,
        )

    async def search(self, **_kwargs: object) -> GraphSearchResult:
        return GraphSearchResult.degraded("graph.schema_mismatch", retryable=False)


class FakeEmbeddingAdapter:
    async def embed_texts(self, *_args: object, **_kwargs: object) -> EmbeddingResult:
        return EmbeddingResult(status=PortStatus.OK, vectors=((0.1, 0.2, 0.3),))


class FakeVectorAdapter:
    def __init__(self, chunk_id: str) -> None:
        self._chunk_id = chunk_id
        self.search_calls: list[dict[str, object]] = []

    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name="fake-vector",
            enabled=True,
            healthy=True,
            supports_upsert=True,
            supports_delete=True,
            supports_search=True,
            supports_filters=True,
        )

    async def search_chunks(self, **_kwargs: object) -> VectorSearchResult:
        self.search_calls.append(_kwargs)
        return VectorSearchResult.ok(
            [
                VectorCandidate(
                    chunk_id=self._chunk_id,
                    space_id="",
                    profile_id="",
                    score=1.0,
                    projection_version="test",
                )
            ]
        )


def test_context_revalidation_drops_provider_only_raw_items(tmp_path: Path) -> None:
    class ProviderOnlyGraphCollector:
        async def collect(
            self,
            *,
            query: BuildContextQuery,
            profile_ids: tuple[str, ...],
            diagnostics: dict[str, object],
        ) -> tuple[ContextItem, ...]:
            diagnostics["graph_status"] = "ok"
            return (
                ContextItem(
                    item_id="provider_only_graph_item",
                    item_type="provider_raw",
                    text="PROVIDER_ONLY_GRAPH_TEXT_SHOULD_NOT_RENDER",
                    score=0.99,
                    source_refs=(SourceRef(source_type="graphiti", source_id="provider-only"),),
                    diagnostics={"profile_id": str(profile_ids[0])},
                ),
            )

    with make_client(tmp_path) as client:
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=NoopVectorMemoryAdapter(),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=NoopEmbeddingAdapter(),
        )
        use_case._graph_collector = ProviderOnlyGraphCollector()  # noqa: SLF001
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="provider only graph text",
                    token_budget=512,
                )
            )
        )

    assert "PROVIDER_ONLY_GRAPH_TEXT_SHOULD_NOT_RENDER" not in context.rendered_text
    assert context.items == ()


def test_canonical_only_context_skips_all_provider_adapters(tmp_path: Path) -> None:
    class FailingEmbeddingAdapter:
        async def embed_texts(self, *_args: object, **_kwargs: object) -> EmbeddingResult:
            raise AssertionError("canonical_only context must not call embeddings")

    class FailingVectorAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            raise AssertionError("canonical_only context must not inspect vector capabilities")

        async def search_chunks(self, **_kwargs: object) -> VectorSearchResult:
            raise AssertionError("canonical_only context must not search vectors")

    class FailingGraphAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            raise AssertionError("canonical_only context must not inspect graph capabilities")

        async def search(self, **_kwargs: object) -> GraphSearchResult:
            raise AssertionError("canonical_only context must not search graph")

    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "CANONICAL_ONLY_FACT_MARKER comes only from Postgres facts.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "canonical-fact"}],
            },
            headers=auth_headers(),
        )
        document = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Canonical only",
                "text": "CANONICAL_ONLY_CHUNK_MARKER comes only from keyword chunks.",
                "source_type": "document",
                "source_external_id": "canonical-only-doc",
            },
            headers=auth_headers(),
        )
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=FailingVectorAdapter(),
            graph_index=FailingGraphAdapter(),
            embedder=FailingEmbeddingAdapter(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="CANONICAL_ONLY",
                    consistency_mode=ConsistencyMode.CANONICAL_ONLY,
                    token_budget=512,
                )
            )
        )

    assert fact.status_code == 201
    assert document.status_code == 201
    assert "CANONICAL_ONLY_FACT_MARKER" in context.rendered_text
    assert "CANONICAL_ONLY_CHUNK_MARKER" in context.rendered_text
    assert context.diagnostics["consistency_mode"] == "canonical_only"
    assert context.diagnostics["vector_status"] == "skipped"
    assert context.diagnostics["vector_skip_reason"] == "canonical_only"
    assert context.diagnostics["graph_status"] == "skipped"
    assert context.diagnostics["graph_skip_reason"] == "canonical_only"


def test_v1_context_accepts_consistency_mode_without_changing_defaults(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "CONTEXT_CONSISTENCY_MODE_MARKER is a canonical fact.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "consistency-mode"}],
            },
            headers=auth_headers(),
        )
        default_context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "profile_ids": ["profile_default"],
                "query": "CONTEXT_CONSISTENCY_MODE_MARKER",
                "token_budget": 512,
            },
            headers=auth_headers(),
        )
        canonical_context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "profile_ids": ["profile_default"],
                "query": "CONTEXT_CONSISTENCY_MODE_MARKER",
                "consistency_mode": "canonical_only",
                "token_budget": 512,
            },
            headers=auth_headers(),
        )

    assert default_context.status_code == 200
    assert canonical_context.status_code == 200
    assert default_context.json()["data"]["diagnostics"]["consistency_mode"] == "best_effort"
    assert canonical_context.json()["data"]["diagnostics"]["consistency_mode"] == "canonical_only"
    assert "CONTEXT_CONSISTENCY_MODE_MARKER" in canonical_context.json()["data"]["rendered_text"]


def test_context_surfaces_pending_conflict_suggestions_for_visible_facts(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        fact_response = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "CONFLICT_CONTEXT_ACTIVE: Postgres owns document vector retrieval.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "active-decision"}],
            },
            headers=auth_headers(),
        )
        fact_id = fact_response.json()["data"]["id"]
        suggestion_response = client.post(
            "/v1/suggestions",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "candidate_text": (
                    "CONFLICT_CONTEXT_PENDING: Docs retrieval should use Qdrant vectors."
                ),
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "pending-decision"}],
                "confidence": "medium",
                "trust_level": "medium",
                "safe_reason": "test_conflict_requires_review",
                "review_payload": {
                    "conflicting_fact_id": fact_id,
                    "conflict_source": "unit_test",
                },
            },
            headers=auth_headers(),
        )
        context_response = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "profile_ids": ["profile_default"],
                "query": "document vector retrieval",
                "token_budget": 512,
            },
            headers=auth_headers(),
        )

    assert fact_response.status_code == 201
    assert suggestion_response.status_code == 201
    assert context_response.status_code == 200
    data = context_response.json()["data"]
    rendered = data["rendered_text"]
    assert "CONFLICT_CONTEXT_ACTIVE" in rendered
    assert "CONFLICT_CONTEXT_PENDING" in rendered
    assert "Pending review add suggestion for active fact" in rendered
    assert data["diagnostics"]["pending_conflict_suggestions_considered"] == 1
    suggestion_items = [item for item in data["items"] if item["item_type"] == "suggestion"]
    assert len(suggestion_items) == 1
    assert suggestion_items[0]["diagnostics"]["retrieval_source"] == (
        "pending_conflict_suggestion"
    )
    assert suggestion_items[0]["diagnostics"]["canonical"] is False
    assert suggestion_items[0]["diagnostics"]["conflicting_fact_id"] == fact_id


def test_context_can_include_rag_recall_candidates_when_adapter_is_enabled(
    tmp_path: Path,
) -> None:
    class FakeRagRecall:
        async def recall(self, query: CapabilityRecallQuery) -> CapabilityRecallResult:
            assert query.scope.space_id == "space_client_app"
            assert query.scope.profile_ids == ("profile_default",)
            return CapabilityRecallResult(
                status=CapabilityStatus.OK,
                items=(
                    CapabilityRecallCandidate(
                        item_id=chunk_id,
                        item_type="chunk",
                        text="STALE_RAG_PROVIDER_TEXT_SHOULD_NOT_RENDER",
                        score=0.88,
                        source_refs=(
                            SourceRef(
                                source_type="chunk",
                                source_id=chunk_id,
                                chunk_id=chunk_id,
                            ),
                        ),
                        capability=MemoryCapability.RAG_RECALL,
                        adapter_name="cognee",
                        metadata={
                            "provider": "cognee",
                            "dataset_id": "client-app/default",
                            "raw_text": "RAW_RAG_METADATA_SECRET should not leak",
                            "secret_token": "RAG_METADATA_SECRET_TOKEN",
                        },
                    ),
                ),
            )

    with make_client(tmp_path) as client:
        document = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "RAG canonical source",
                "text": "RAG_CANONICAL_MARKER is hydrated from the canonical chunk.",
                "source_type": "document",
                "source_external_id": "rag-source",
            },
            headers=auth_headers(),
        )
        document_id = document.json()["data"]["id"]
        chunk_id = client.get(
            f"/v1/documents/{document_id}/chunks",
            headers=auth_headers(),
        ).json()["data"][0]["id"]
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=NoopVectorMemoryAdapter(),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=NoopEmbeddingAdapter(),
            rag_recall=FakeRagRecall(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="semantic rag recall",
                    token_budget=512,
                )
            )
        )

    assert "RAG_CANONICAL_MARKER" in context.rendered_text
    assert "STALE_RAG_PROVIDER_TEXT_SHOULD_NOT_RENDER" not in context.rendered_text
    assert context.diagnostics["rag_status"] == "ok"
    assert context.diagnostics["stale_rag_drop_count"] == 0
    assert context.items[0].diagnostics["retrieval_source"] == "rag_recall"
    assert context.items[0].diagnostics["adapter_name"] == "cognee"
    assert context.items[0].diagnostics["provider"] == "cognee"
    assert context.items[0].diagnostics["dataset_id"] == "client-app/default"
    assert "RAW_RAG_METADATA_SECRET" not in str(context.items[0].diagnostics)
    assert "RAG_METADATA_SECRET_TOKEN" not in str(context.items[0].diagnostics)


def test_context_drops_rag_recall_without_canonical_chunk_source(tmp_path: Path) -> None:
    class FakeRagRecall:
        async def recall(self, _query: CapabilityRecallQuery) -> CapabilityRecallResult:
            return CapabilityRecallResult(
                status=CapabilityStatus.OK,
                items=(
                    CapabilityRecallCandidate(
                        item_id="provider_only_chunk",
                        item_type="rag_chunk",
                        text="PROVIDER_ONLY_RAG_TEXT_SHOULD_NOT_RENDER",
                        score=0.88,
                        source_refs=(
                            SourceRef(source_type="cognee", source_id="provider_only_chunk"),
                        ),
                        capability=MemoryCapability.RAG_RECALL,
                        adapter_name="cognee",
                    ),
                ),
            )

    with make_client(tmp_path) as client:
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=NoopVectorMemoryAdapter(),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=NoopEmbeddingAdapter(),
            rag_recall=FakeRagRecall(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="semantic rag recall",
                    token_budget=512,
                )
            )
        )

    assert "PROVIDER_ONLY_RAG_TEXT_SHOULD_NOT_RENDER" not in context.rendered_text
    assert context.diagnostics["rag_status"] == "ok"
    assert context.diagnostics["stale_rag_drop_count"] == 1


def test_context_does_not_embed_when_vector_adapter_is_disabled(tmp_path: Path) -> None:
    class FailingEmbeddingAdapter:
        calls = 0

        async def embed_texts(self, *_args: object, **_kwargs: object) -> EmbeddingResult:
            self.calls += 1
            raise AssertionError("disabled vector retrieval must not call embeddings")

    with make_client(tmp_path) as client:
        embedder = FailingEmbeddingAdapter()
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=NoopVectorMemoryAdapter(),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=embedder,
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="VECTOR_DISABLED_COST_GUARD",
                    token_budget=512,
                )
            )
        )

    assert embedder.calls == 0
    assert context.diagnostics["vector_status"] == "disabled"
    assert context.diagnostics["vector_degraded_reason"] == "disabled"


def test_context_marks_unavailable_vector_adapter_degraded_without_embedding(
    tmp_path: Path,
) -> None:
    class UnavailableVectorAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="qdrant",
                enabled=False,
                healthy=True,
                supports_upsert=False,
                supports_delete=False,
                supports_search=False,
                supports_filters=False,
                degraded_reason="qdrant_sdk_missing",
            )

        async def search_chunks(self, **_kwargs: object) -> VectorSearchResult:
            raise AssertionError("unavailable vector adapter must not be searched")

    class FailingEmbeddingAdapter:
        calls = 0

        async def embed_texts(self, *_args: object, **_kwargs: object) -> EmbeddingResult:
            self.calls += 1
            raise AssertionError("unavailable vector retrieval must not call embeddings")

    with make_client(tmp_path) as client:
        embedder = FailingEmbeddingAdapter()
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=UnavailableVectorAdapter(),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=embedder,
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="VECTOR_UNAVAILABLE_COST_GUARD",
                    token_budget=512,
                )
            )
        )

    assert embedder.calls == 0
    assert context.diagnostics["vector_status"] == "degraded"
    assert context.diagnostics["vector_degraded_reason"] == "qdrant_sdk_missing"


def test_degraded_context_has_safe_diagnostics(tmp_path: Path) -> None:
    class DegradedVectorAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="qdrant",
                enabled=False,
                healthy=False,
                supports_upsert=False,
                supports_delete=False,
                supports_search=False,
                supports_filters=False,
                degraded_reason="qdrant_sdk_missing",
            )

        async def search_chunks(self, **_kwargs: object) -> VectorSearchResult:
            raise AssertionError("degraded vector adapter must not be searched")

    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "DEGRADED_CONTEXT_MARKER should still render from Postgres.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "degraded-context"}],
            },
            headers=auth_headers(),
        )
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=DegradedVectorAdapter(),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=NoopEmbeddingAdapter(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="DEGRADED_CONTEXT_MARKER",
                    token_budget=512,
                )
            )
        )

    assert created.status_code == 201
    assert "DEGRADED_CONTEXT_MARKER" in context.rendered_text
    assert context.diagnostics["vector_status"] == "degraded"
    assert context.diagnostics["vector_degraded_reason"] == "qdrant_sdk_missing"
    assert "Traceback" not in str(context.diagnostics)
    assert "payload_json" not in str(context.diagnostics)


def test_qdrant_timeout_degrades_to_postgres_facts(tmp_path: Path) -> None:
    class TimeoutVectorAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="qdrant",
                enabled=True,
                healthy=True,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
            )

        async def search_chunks(self, **_kwargs: object) -> VectorSearchResult:
            raise TimeoutError("RAW_VECTOR_TIMEOUT_SECRET")

    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "VECTOR_TIMEOUT_CANONICAL_MARKER still renders from Postgres.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "vector-timeout"}],
            },
            headers=auth_headers(),
        )
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=TimeoutVectorAdapter(),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=FakeEmbeddingAdapter(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="VECTOR_TIMEOUT_CANONICAL_MARKER",
                    token_budget=512,
                )
            )
        )

    assert created.status_code == 201
    assert "VECTOR_TIMEOUT_CANONICAL_MARKER" in context.rendered_text
    assert context.diagnostics["vector_status"] == "degraded"
    assert context.diagnostics["vector_degraded_reason"] == "vector.timeout"
    assert "RAW_VECTOR_TIMEOUT_SECRET" not in str(context.diagnostics)


def test_qdrant_circuit_opens_after_repeated_timeout(tmp_path: Path) -> None:
    class TimeoutVectorAdapter:
        calls = 0

        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="qdrant",
                enabled=True,
                healthy=True,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
            )

        async def search_chunks(self, **_kwargs: object) -> VectorSearchResult:
            self.calls += 1
            raise TimeoutError("RAW_QDRANT_TIMEOUT_SECRET")

    with make_client(tmp_path) as client:
        client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "VECTOR_CIRCUIT_MARKER should remain available from Postgres.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "vector-circuit"}],
            },
            headers=auth_headers(),
        )
        container = client.app.state.container
        raw_vector = TimeoutVectorAdapter()
        circuit = ProviderCircuitBreaker(
            adapter_name="qdrant",
            operation_kind="vector",
            clock=container.clock,
            failure_threshold=2,
            reset_after_seconds=60,
        )
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=CircuitBreakingVectorMemoryAdapter(raw_vector, circuit),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=FakeEmbeddingAdapter(),
        )
        first = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="VECTOR_CIRCUIT_MARKER",
                    token_budget=512,
                )
            )
        )
        second = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="VECTOR_CIRCUIT_MARKER",
                    token_budget=512,
                )
            )
        )
        third = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="VECTOR_CIRCUIT_MARKER",
                    token_budget=512,
                )
            )
        )

    assert "VECTOR_CIRCUIT_MARKER" in third.rendered_text
    assert first.diagnostics["vector_degraded_reason"] == "vector.timeout"
    assert second.diagnostics["vector_degraded_reason"] == "vector.timeout"
    assert third.diagnostics["vector_degraded_reason"] == "vector.circuit_open"
    assert raw_vector.calls == 2
    snapshot = circuit.snapshot()
    assert snapshot["state"] == "open"
    assert snapshot["last_failure_code"] == "vector.exception"
    assert "RAW_QDRANT_TIMEOUT_SECRET" not in str(snapshot)


def test_query_embedding_timeout_degrades_to_keyword_context(tmp_path: Path) -> None:
    class EnabledVectorAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="qdrant",
                enabled=True,
                healthy=True,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
            )

        async def search_chunks(self, **_kwargs: object) -> VectorSearchResult:
            raise AssertionError("embedding timeout must stop vector search")

    class TimeoutEmbeddingAdapter:
        async def embed_texts(self, *_args: object, **_kwargs: object) -> EmbeddingResult:
            raise TimeoutError("RAW_EMBEDDING_TIMEOUT_SECRET")

    with make_client(tmp_path) as client:
        document = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Embedding timeout fallback",
                "text": "EMBEDDING_TIMEOUT_KEYWORD_MARKER still renders from keyword chunks.",
                "source_type": "document",
                "source_external_id": "embedding-timeout-doc",
            },
            headers=auth_headers(),
        )
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=EnabledVectorAdapter(),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=TimeoutEmbeddingAdapter(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="EMBEDDING_TIMEOUT_KEYWORD_MARKER",
                    token_budget=512,
                )
            )
        )

    assert document.status_code == 201
    assert "EMBEDDING_TIMEOUT_KEYWORD_MARKER" in context.rendered_text
    assert context.diagnostics["vector_status"] == "degraded"
    assert context.diagnostics["vector_degraded_reason"] == "embeddings.timeout"
    assert "RAW_EMBEDDING_TIMEOUT_SECRET" not in str(context.diagnostics)


def test_embedding_circuit_opens_after_repeated_timeout(tmp_path: Path) -> None:
    class EnabledVectorAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="qdrant",
                enabled=True,
                healthy=True,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
            )

        async def search_chunks(self, **_kwargs: object) -> VectorSearchResult:
            raise AssertionError("open embedding circuit must stop vector search")

    class TimeoutEmbeddingAdapter:
        calls = 0

        async def embed_texts(self, *_args: object, **_kwargs: object) -> EmbeddingResult:
            self.calls += 1
            raise TimeoutError("RAW_EMBEDDING_CIRCUIT_SECRET")

    with make_client(tmp_path) as client:
        client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Embedding circuit fallback",
                "text": "EMBEDDING_CIRCUIT_KEYWORD_MARKER still renders from keyword chunks.",
                "source_type": "document",
                "source_external_id": "embedding-circuit-doc",
            },
            headers=auth_headers(),
        )
        container = client.app.state.container
        raw_embedder = TimeoutEmbeddingAdapter()
        circuit = ProviderCircuitBreaker(
            adapter_name="embeddings",
            operation_kind="embeddings",
            clock=container.clock,
            failure_threshold=2,
            reset_after_seconds=60,
        )
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=EnabledVectorAdapter(),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=CircuitBreakingEmbeddingAdapter(raw_embedder, circuit),
        )
        first = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="EMBEDDING_CIRCUIT_KEYWORD_MARKER",
                    token_budget=512,
                )
            )
        )
        second = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="EMBEDDING_CIRCUIT_KEYWORD_MARKER",
                    token_budget=512,
                )
            )
        )
        third = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="EMBEDDING_CIRCUIT_KEYWORD_MARKER",
                    token_budget=512,
                )
            )
        )

    assert "EMBEDDING_CIRCUIT_KEYWORD_MARKER" in third.rendered_text
    assert first.diagnostics["vector_degraded_reason"] == "embeddings.timeout"
    assert second.diagnostics["vector_degraded_reason"] == "embeddings.timeout"
    assert third.diagnostics["vector_degraded_reason"] == "embeddings.circuit_open"
    assert raw_embedder.calls == 2
    assert circuit.snapshot()["state"] == "open"
    assert "RAW_EMBEDDING_CIRCUIT_SECRET" not in str(circuit.snapshot())


def test_query_embedding_rate_limit_degrades_to_keyword(tmp_path: Path) -> None:
    class EnabledVectorAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="qdrant",
                enabled=True,
                healthy=True,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
            )

        async def search_chunks(self, **_kwargs: object) -> VectorSearchResult:
            raise AssertionError("rate-limited query embeddings must stop vector search")

    with make_client(tmp_path) as client:
        document = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "Query embedding rate limit",
                "text": "QUERY_RATE_LIMIT_KEYWORD_MARKER still renders from keyword chunks.",
                "source_type": "document",
                "source_external_id": "query-rate-limit-doc",
            },
            headers=auth_headers(),
        )
        container = client.app.state.container
        budgeted_embedder = QueryEmbeddingBudgetAdapter(
            inner=FakeEmbeddingAdapter(),
            clock=container.clock,
            max_per_minute=1,
        )
        asyncio.run(budgeted_embedder.embed_texts(("prewarm budget",)))
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=EnabledVectorAdapter(),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=budgeted_embedder,
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="QUERY_RATE_LIMIT_KEYWORD_MARKER",
                    token_budget=512,
                )
            )
        )

    assert document.status_code == 201
    assert "QUERY_RATE_LIMIT_KEYWORD_MARKER" in context.rendered_text
    assert context.diagnostics["vector_status"] == "degraded"
    assert context.diagnostics["vector_degraded_reason"] == "embeddings.query_rate_limited"


def test_context_does_not_search_when_graph_adapter_is_disabled(tmp_path: Path) -> None:
    class DisabledGraphAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="graphiti",
                enabled=False,
                healthy=True,
                supports_upsert=False,
                supports_delete=False,
                supports_search=False,
                supports_filters=False,
                supports_temporal_queries=False,
                degraded_reason="disabled",
            )

        async def search(self, **_kwargs: object) -> GraphSearchResult:
            raise AssertionError("disabled graph retrieval must not call search")

    with make_client(tmp_path) as client:
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=NoopVectorMemoryAdapter(),
            graph_index=DisabledGraphAdapter(),
            embedder=NoopEmbeddingAdapter(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="GRAPH_DISABLED_COST_GUARD",
                    token_budget=512,
                )
            )
        )

    assert context.diagnostics["graph_status"] == "disabled"
    assert context.diagnostics["graph_degraded_reason"] == "disabled"


def test_context_marks_unavailable_graph_adapter_degraded_without_search(
    tmp_path: Path,
) -> None:
    class UnavailableGraphAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="graphiti",
                enabled=False,
                healthy=False,
                supports_upsert=False,
                supports_delete=False,
                supports_search=False,
                supports_filters=False,
                supports_temporal_queries=True,
                degraded_reason="graphiti_unavailable",
            )

        async def search(self, **_kwargs: object) -> GraphSearchResult:
            raise AssertionError("unavailable graph retrieval must not call search")

    with make_client(tmp_path) as client:
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=NoopVectorMemoryAdapter(),
            graph_index=UnavailableGraphAdapter(),
            embedder=NoopEmbeddingAdapter(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="GRAPH_UNAVAILABLE_COST_GUARD",
                    token_budget=512,
                )
            )
        )

    assert context.diagnostics["graph_status"] == "degraded"
    assert context.diagnostics["graph_degraded_reason"] == "graphiti_unavailable"


def test_graphiti_timeout_degrades_to_postgres_facts(tmp_path: Path) -> None:
    class TimeoutGraphAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="graphiti",
                enabled=True,
                healthy=True,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
                supports_temporal_queries=True,
            )

        async def search(self, **_kwargs: object) -> GraphSearchResult:
            raise TimeoutError("RAW_GRAPH_TIMEOUT_SECRET")

    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "GRAPH_TIMEOUT_CANONICAL_MARKER still renders from Postgres.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "graph-timeout"}],
            },
            headers=auth_headers(),
        )
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=NoopVectorMemoryAdapter(),
            graph_index=TimeoutGraphAdapter(),
            embedder=NoopEmbeddingAdapter(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="GRAPH_TIMEOUT_CANONICAL_MARKER",
                    token_budget=512,
                )
            )
        )

    assert created.status_code == 201
    assert "GRAPH_TIMEOUT_CANONICAL_MARKER" in context.rendered_text
    assert context.diagnostics["graph_status"] == "degraded"
    assert context.diagnostics["graph_degraded_reason"] == "graph.timeout"
    assert "RAW_GRAPH_TIMEOUT_SECRET" not in str(context.diagnostics)


def test_open_graph_circuit_returns_degraded_context_fast(tmp_path: Path) -> None:
    class TimeoutGraphAdapter:
        calls = 0

        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="graphiti",
                enabled=True,
                healthy=True,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
                supports_temporal_queries=True,
            )

        async def search(self, **_kwargs: object) -> GraphSearchResult:
            self.calls += 1
            raise TimeoutError("RAW_GRAPH_CIRCUIT_SECRET")

    with make_client(tmp_path) as client:
        client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "GRAPH_CIRCUIT_MARKER should remain available from Postgres.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "graph-circuit"}],
            },
            headers=auth_headers(),
        )
        container = client.app.state.container
        raw_graph = TimeoutGraphAdapter()
        circuit = ProviderCircuitBreaker(
            adapter_name="graphiti",
            operation_kind="graph",
            clock=container.clock,
            failure_threshold=2,
            reset_after_seconds=60,
        )
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=NoopVectorMemoryAdapter(),
            graph_index=CircuitBreakingGraphMemoryAdapter(raw_graph, circuit),
            embedder=NoopEmbeddingAdapter(),
        )
        for _ in range(2):
            context = asyncio.run(
                use_case.execute(
                    BuildContextQuery(
                        space_id=SpaceId("space_client_app"),
                        profile_ids=(ProfileId("profile_default"),),
                        query="GRAPH_CIRCUIT_MARKER",
                        token_budget=512,
                    )
                )
            )
            assert context.diagnostics["graph_degraded_reason"] == "graph.timeout"
        opened = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="GRAPH_CIRCUIT_MARKER",
                    token_budget=512,
                )
            )
        )

    assert "GRAPH_CIRCUIT_MARKER" in opened.rendered_text
    assert opened.diagnostics["graph_degraded_reason"] == "graph.circuit_open"
    assert raw_graph.calls == 2
    assert circuit.snapshot()["state"] == "open"
    assert "RAW_GRAPH_CIRCUIT_SECRET" not in str(circuit.snapshot())


def test_context_revalidates_direct_facts_after_adapter_delay(tmp_path: Path) -> None:
    class EmptyEnabledVectorAdapter:
        async def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                name="fake-vector",
                enabled=True,
                healthy=True,
                supports_upsert=True,
                supports_delete=True,
                supports_search=True,
                supports_filters=True,
            )

        async def search_chunks(self, **_kwargs: object) -> VectorSearchResult:
            return VectorSearchResult.ok([])

    class ForgetDuringEmbeddingAdapter:
        def __init__(self, container, fact_id: str) -> None:
            self._container = container
            self._fact_id = fact_id

        async def embed_texts(self, *_args: object, **_kwargs: object) -> EmbeddingResult:
            await self._container.forget_fact.execute(ForgetFactCommand(fact_id=self._fact_id))
            return EmbeddingResult.degraded("test.embedding_disabled", retryable=False)

    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "RACE_DELETE_FACT_MARKER must not survive final context validation.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "race-delete"}],
            },
            headers=auth_headers(),
        )
        fact_id = fact.json()["data"]["id"]
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=EmptyEnabledVectorAdapter(),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=ForgetDuringEmbeddingAdapter(container, fact_id),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="RACE_DELETE_FACT_MARKER",
                    token_budget=512,
                )
            )
        )

    assert fact.status_code == 201
    assert "RACE_DELETE_FACT_MARKER" not in context.rendered_text
    assert context.items == ()


def test_graph_relation_from_deleted_fact_not_rendered(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "Graph-only canonical memory marker.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "manual-graph"}],
            },
            headers=auth_headers(),
        )
        fact_id = fact.json()["data"]["id"]
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=NoopVectorMemoryAdapter(),
            graph_index=FakeGraphAdapter(fact_id),
            embedder=NoopEmbeddingAdapter(),
        )
        active = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="unrelated graph query",
                    token_budget=512,
                )
            )
        )
        client.delete(f"/v1/facts/{fact_id}", headers=auth_headers())
        deleted = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="unrelated graph query",
                    token_budget=512,
                )
            )
        )

    assert "Graph-only canonical memory marker" in active.rendered_text
    assert active.diagnostics["graph_candidate_count"] == 1
    assert active.diagnostics["graph_hydrated_count"] == 1
    assert active.diagnostics["stale_graph_drop_count"] == 0
    assert "Graph-only canonical memory marker" not in deleted.rendered_text
    assert deleted.diagnostics["graph_candidate_count"] == 1
    assert deleted.diagnostics["graph_hydrated_count"] == 0
    assert deleted.diagnostics["stale_graph_drop_count"] == 1


def test_graph_candidate_without_canonical_source_is_low_confidence_or_dropped(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=NoopVectorMemoryAdapter(),
            graph_index=OrphanGraphAdapter(),
            embedder=NoopEmbeddingAdapter(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="orphan graph relation",
                    token_budget=512,
                )
            )
        )

    assert context.items == ()
    assert "orphan_relation" not in context.rendered_text
    assert context.diagnostics["graph_status"] == "ok"
    assert context.diagnostics["graph_candidate_count"] == 1
    assert context.diagnostics["graph_hydrated_count"] == 0
    assert context.diagnostics["stale_graph_drop_count"] == 1


def test_graph_adapter_schema_mismatch_degrades_context(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "SCHEMA_MISMATCH_CANONICAL_MARKER still renders from Postgres.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "schema-mismatch"}],
            },
            headers=auth_headers(),
        )
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=NoopVectorMemoryAdapter(),
            graph_index=SchemaMismatchGraphAdapter(),
            embedder=NoopEmbeddingAdapter(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="SCHEMA_MISMATCH_CANONICAL_MARKER",
                    token_budget=512,
                )
            )
        )

    assert fact.status_code == 201
    assert "SCHEMA_MISMATCH_CANONICAL_MARKER" in context.rendered_text
    assert context.diagnostics["graph_status"] == "degraded"
    assert context.diagnostics["graph_degraded_reason"] == "graph.schema_mismatch"


def test_graph_candidates_from_same_profile_wrong_thread_are_filtered(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        container = client.app.state.container
        current_scope = asyncio.run(
            container.ensure_scope.execute(
                EnsureScopeCommand(
                    space_slug="client-app",
                    profile_external_ref="default",
                    thread_external_ref="graph-thread-current",
                )
            )
        )
        other_scope = asyncio.run(
            container.ensure_scope.execute(
                EnsureScopeCommand(
                    space_slug="client-app",
                    profile_external_ref="default",
                    thread_external_ref="graph-thread-other",
                )
            )
        )
        fact = client.post(
            "/v1/facts",
            json={
                "space_id": str(other_scope.space_id),
                "profile_id": str(other_scope.profile_id),
                "thread_id": str(other_scope.thread_id),
                "text": "WRONG_THREAD_GRAPH_MARKER must not hydrate into current context.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "wrong-thread-graph"}],
            },
            headers=auth_headers(),
        )
        graph_adapter = FakeGraphAdapter(fact.json()["data"]["id"])
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=NoopVectorMemoryAdapter(),
            graph_index=graph_adapter,
            embedder=NoopEmbeddingAdapter(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=current_scope.space_id,
                    profile_ids=(current_scope.profile_id,),
                    thread_id=current_scope.thread_id,
                    query="unrelated graph query",
                    token_budget=512,
                )
            )
        )

    assert fact.status_code == 201
    assert graph_adapter.search_calls[0]["thread_id"] == str(current_scope.thread_id)
    assert "WRONG_THREAD_GRAPH_MARKER" not in context.rendered_text
    assert context.diagnostics["stale_graph_drop_count"] == 1


def test_vector_candidates_are_hydrated_and_deleted_chunks_are_filtered(tmp_path: Path) -> None:
    session_id = "vector-stale-session"
    with make_client(tmp_path) as client:
        client.post(
            "/api/v1/interview-memory/ingest",
            json=legacy_event(
                session_id,
                "vector-event",
                "VECTOR_ONLY_MARKER: hydrate this only through canonical chunk.",
            ),
            headers=auth_headers(),
        )
        container = client.app.state.container
        scope = asyncio.run(
            container.ensure_scope.execute(
                EnsureScopeCommand(
                    space_slug=container.settings.default_space_slug,
                    profile_external_ref=container.settings.default_profile_external_ref,
                    thread_external_ref=session_id,
                )
            )
        )
        chunk_id = asyncio.run(_first_chunk_id(container, scope, "VECTOR_ONLY_MARKER"))
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=FakeVectorAdapter(chunk_id),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=FakeEmbeddingAdapter(),
        )
        active = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=scope.space_id,
                    profile_ids=(scope.profile_id,),
                    thread_id=scope.thread_id,
                    query="unrelated vector query",
                    token_budget=512,
                )
            )
        )
        client.delete(f"/api/v1/interview-memory/sessions/{session_id}", headers=auth_headers())
        deleted = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=scope.space_id,
                    profile_ids=(scope.profile_id,),
                    thread_id=scope.thread_id,
                    query="unrelated vector query",
                    token_budget=512,
                )
            )
        )

    assert "VECTOR_ONLY_MARKER" in active.rendered_text
    assert active.diagnostics["vector_candidate_count"] == 1
    assert active.diagnostics["vector_hydrated_count"] == 1
    assert active.diagnostics["stale_vector_drop_count"] == 0
    assert "VECTOR_ONLY_MARKER" not in deleted.rendered_text
    assert deleted.diagnostics["vector_candidate_count"] == 1
    assert deleted.diagnostics["vector_hydrated_count"] == 0
    assert deleted.diagnostics["stale_vector_drop_count"] == 1


def test_vector_candidates_from_same_profile_wrong_thread_are_filtered(
    tmp_path: Path,
) -> None:
    current_session_id = "vector-thread-current"
    other_session_id = "vector-thread-other"
    with make_client(tmp_path) as client:
        container = client.app.state.container
        current_scope = asyncio.run(
            container.ensure_scope.execute(
                EnsureScopeCommand(
                    space_slug=container.settings.default_space_slug,
                    profile_external_ref=container.settings.default_profile_external_ref,
                    thread_external_ref=current_session_id,
                )
            )
        )
        client.post(
            "/api/v1/interview-memory/ingest",
            json=legacy_event(
                other_session_id,
                "wrong-thread-vector-event",
                "WRONG_THREAD_VECTOR_MARKER must not hydrate into current context.",
            ),
            headers=auth_headers(),
        )
        other_scope = asyncio.run(
            container.ensure_scope.execute(
                EnsureScopeCommand(
                    space_slug=container.settings.default_space_slug,
                    profile_external_ref=container.settings.default_profile_external_ref,
                    thread_external_ref=other_session_id,
                )
            )
        )
        other_chunk_id = asyncio.run(
            _first_chunk_id(container, other_scope, "WRONG_THREAD_VECTOR_MARKER")
        )
        vector_adapter = FakeVectorAdapter(other_chunk_id)
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=vector_adapter,
            graph_index=NoopGraphMemoryAdapter(),
            embedder=FakeEmbeddingAdapter(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=current_scope.space_id,
                    profile_ids=(current_scope.profile_id,),
                    thread_id=current_scope.thread_id,
                    query="unrelated vector query",
                    token_budget=512,
                )
            )
        )

    assert vector_adapter.search_calls[0]["thread_id"] == str(current_scope.thread_id)
    assert "WRONG_THREAD_VECTOR_MARKER" not in context.rendered_text
    assert context.diagnostics["stale_vector_drop_count"] == 1


def test_wrong_profile_vector_hit_is_dropped(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        document = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_secondary",
                "title": "Wrong profile vector source",
                "text": "WRONG_PROFILE_VECTOR_MARKER must not hydrate into default profile.",
                "source_type": "document",
                "source_external_id": "wrong-profile-vector-doc",
                "classification": "internal",
            },
            headers=auth_headers(),
        )
        document_id = document.json()["data"]["id"]
        wrong_profile_chunk_id = client.get(
            f"/v1/documents/{document_id}/chunks",
            headers=auth_headers(),
        ).json()["data"][0]["id"]
        container = client.app.state.container
        use_case = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=FakeVectorAdapter(wrong_profile_chunk_id),
            graph_index=NoopGraphMemoryAdapter(),
            embedder=FakeEmbeddingAdapter(),
        )
        context = asyncio.run(
            use_case.execute(
                BuildContextQuery(
                    space_id=SpaceId("space_client_app"),
                    profile_ids=(ProfileId("profile_default"),),
                    query="unrelated vector query",
                    token_budget=512,
                )
            )
        )

    assert document.status_code == 201
    assert "WRONG_PROFILE_VECTOR_MARKER" not in context.rendered_text
    assert context.items == ()
    assert context.diagnostics["stale_vector_drop_count"] == 1



async def _first_chunk_id(container, scope, query: str) -> str:
    async with container.uow_factory() as uow:
        chunks = await uow.chunks.keyword_search(
            space_id=str(scope.space_id),
            profile_ids=(str(scope.profile_id),),
            thread_id=str(scope.thread_id) if scope.thread_id else None,
            query=query,
            limit=1,
        )
    return str(chunks[0].id)
