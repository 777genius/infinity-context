from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from infinity_context_core.application import (
    BuildContextQuery,
    BuildContextUseCase,
    ConsistencyMode,
    ContextRetrievalDeadlines,
)
from infinity_context_core.application.use_cases import build_context as module
from infinity_context_core.domain.entities import MemoryScopeId, SourceRef, SpaceId
from infinity_context_core.ports.capabilities import (
    CapabilityRecallCandidate,
    CapabilityRecallResult,
    CapabilityStatus,
    MemoryCapability,
)

from tests.unit.test_context_provider_consistency import (
    FakeEmbeddingAdapter,
    FakeGraphAdapter,
    FakeVectorAdapter,
    auth_headers,
    make_client,
)


async def sequential_collection(*, vector, graph, rag, diagnostics):
    """Retain the original scheduling behavior as the comparison oracle."""
    return await vector(diagnostics), await graph(diagnostics), await rag(diagnostics)


def without_timings(value):
    if isinstance(value, dict):
        return {
            key: without_timings(item)
            for key, item in value.items()
            if key not in {"bundle_id", "stage_timings_ms"}
        }
    if isinstance(value, tuple | list):
        return [without_timings(item) for item in value]
    return value


class RagRecall:
    def __init__(self, chunk_id):
        self.chunk_id = chunk_id
        self.calls = 0

    async def recall(self, query):
        self.calls += 1
        return CapabilityRecallResult(
            status=CapabilityStatus.OK,
            items=(
                CapabilityRecallCandidate(
                    item_id=self.chunk_id,
                    item_type="chunk",
                    text="ignored provider text",
                    score=0.9,
                    source_refs=(
                        SourceRef(
                            source_type="chunk", source_id=self.chunk_id, chunk_id=self.chunk_id
                        ),
                    ),
                    capability=MemoryCapability.RAG_RECALL,
                    adapter_name="test-rag",
                ),
            ),
        )


@pytest.mark.parametrize("mode", ["all", "vector", "graph", "canonical", "timeout"])
def test_build_context_preserves_exact_output_and_provider_fallback(tmp_path, monkeypatch, mode):
    class SlowVector(FakeVectorAdapter):
        async def search_chunks(self, **kwargs):
            await asyncio.Event().wait()

    with make_client(tmp_path) as client:
        document = client.post(
            "/v1/documents",
            headers=auth_headers(),
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "title": "Atlas retrieval evidence",
                "text": (
                    "Project Atlas release uses durable outbox delivery with canonical hydration."
                ),
                "source_type": "document",
                "source_external_id": "derived-document",
                "classification": "internal",
            },
        )
        assert document.status_code == 201, document.text
        chunk_id = client.get(
            f"/v1/documents/{document.json()['data']['id']}/chunks", headers=auth_headers()
        ).json()["data"][0]["id"]
        fact = client.post(
            "/v1/facts",
            headers=auth_headers(),
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "text": (
                    "Project Atlas requires canonical hydration before outbox evidence is used."
                ),
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "atlas"}],
            },
        )
        assert fact.status_code == 201, fact.text
        vector = (SlowVector if mode == "timeout" else FakeVectorAdapter)(chunk_id)
        graph = FakeGraphAdapter(fact.json()["data"]["id"])
        rag = RagRecall(chunk_id)
        container = client.app.state.container
        builder = BuildContextUseCase(
            uow_factory=container.uow_factory,
            ids=container.ids,
            vector_index=vector,
            graph_index=graph,
            embedder=FakeEmbeddingAdapter(),
            rag_recall=rag if mode in {"all", "timeout", "canonical"} else None,
            clock=SimpleNamespace(now=lambda: datetime(2026, 10, 22, tzinfo=UTC)),
            retrieval_deadlines=ContextRetrievalDeadlines(
                vector_search_seconds=0.001 if mode == "timeout" else 5.0
            ),
        )
        query = BuildContextQuery(
            space_id=SpaceId("space_client_app"),
            memory_scope_ids=(MemoryScopeId("memory_scope_default"),),
            query="Project Atlas outbox canonical hydration",
            token_budget=1024,
            max_chunks=0 if mode == "graph" else 5,
            include_graph=mode != "vector",
            consistency_mode=(
                ConsistencyMode.CANONICAL_ONLY
                if mode == "canonical"
                else ConsistencyMode.BEST_EFFORT
            ),
        )
        concurrent = module.collect_derived_context
        monkeypatch.setattr(module, "collect_derived_context", sequential_collection)
        baseline = asyncio.run(builder.execute(query))
        baseline_calls = (len(vector.search_calls), len(graph.search_calls), rag.calls)
        monkeypatch.setattr(module, "collect_derived_context", concurrent)
        candidate = asyncio.run(builder.execute(query))
        assert without_timings(asdict(candidate)) == without_timings(asdict(baseline))
        assert "Atlas" in candidate.rendered_text
        if mode == "canonical":
            assert baseline_calls == (0, 0, 0)
            assert (len(vector.search_calls), len(graph.search_calls), rag.calls) == (0, 0, 0)
        elif mode == "timeout":
            assert candidate.diagnostics["vector_degraded_reason"] == "vector.timeout"
            assert candidate.diagnostics["graph_status"] == "ok"
            assert candidate.diagnostics["rag_status"] == "ok"
