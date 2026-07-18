"""Characterization tests for the behavior-preserving candidate fusion extraction."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from infinity_context_core.application.context_building_legacy_candidate_adapter import (
    _bounded_derived_retrieval_queries,
    _fused_ranked_keys,
    _protected_query_head_keys,
    _query_policy_for_reason,
)
from infinity_context_core.application.context_collectors import (
    CanonicalContextCollector,
    GraphContextCollector,
    RagContextCollector,
    VectorContextCollector,
)
from infinity_context_core.application.context_query_expansion import (
    QueryExpansion,
    QueryExpansionPlan,
)
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryScopeId,
    SpaceId,
)
from infinity_context_core.features.context_building.public import (
    CandidateQueryPolicy,
    CandidateRanking,
    fuse_ranked_candidate_keys,
)
from infinity_context_core.ports.adapters import (
    AdapterCapabilities,
    EmbeddingResult,
    GraphCandidate,
    GraphSearchResult,
    PortStatus,
    VectorCandidate,
    VectorSearchResult,
)
from infinity_context_core.ports.capabilities import (
    CapabilityRecallCandidate,
    CapabilityRecallResult,
    CapabilityStatus,
    MemoryCapability,
)


@pytest.mark.parametrize(
    ("reason", "head_count"),
    (
        ("business_networking_event_bridge", 2),
        ("food_recipe_recommendation_bridge", 3),
        ("store_promotion_inventory_bridge", 4),
        ("animal_care_instruction_bridge", 2),
    ),
)
def test_legacy_special_and_multi_evidence_head_limits_are_exact(
    reason: str,
    head_count: int,
) -> None:
    ranking = tuple(f"candidate_{index}" for index in range(1, 7))

    protected = _protected_query_head_keys({f"1:{reason}": ranking})

    assert protected == ranking[:head_count]


@pytest.mark.parametrize(
    ("reason", "weight", "max_rank", "protected_head_count"),
    (
        ("original_query", 1.5, 50, 0),
        ("animal_care_instruction_bridge", 1.12, 120, 2),
        ("decomposition_activity_duration", 1.0, 50, 1),
        ("decomposition_relationship_status", 1.0, 120, 1),
        ("decomposition_unknown", 0.7, 50, 0),
        ("legacy_unknown", 1.0, 50, 0),
    ),
)
def test_legacy_reason_policy_mapping_preserves_exact_fusion_values(
    reason: str,
    weight: float,
    max_rank: int,
    protected_head_count: int,
) -> None:
    policy = _query_policy_for_reason(reason)

    assert policy == CandidateQueryPolicy(
        weight=weight,
        max_rank=max_rank,
        protected_head_count=protected_head_count,
    )


def test_legacy_fusion_preserves_weights_max_rank_dedupe_order_and_tie_break() -> None:
    ordinary = tuple(f"ordinary_{index}" for index in range(1, 52))
    multi_evidence = tuple(f"multi_{index}" for index in range(1, 122))

    ranked = _fused_ranked_keys(
        {
            "0:original_query": ("exact", " exact ", *ordinary),
            "1:decomposition_clause": ("noise",),
            "2:animal_care_instruction_bridge": multi_evidence,
        },
        limit=200,
    )

    assert ranked.index("exact") < ranked.index("noise")
    assert ranked.count("exact") == 1
    assert "ordinary_48" in ranked
    assert "ordinary_49" not in ranked
    assert "multi_120" in ranked
    assert "multi_121" not in ranked

    equal_policy = CandidateQueryPolicy(
        weight=1.0,
        max_rank=10,
        protected_head_count=0,
    )
    tied = fuse_ranked_candidate_keys(
        (
            CandidateRanking(ranked_keys=("first_seen",), policy=equal_policy),
            CandidateRanking(ranked_keys=("second_seen",), policy=equal_policy),
        ),
        limit=2,
        rank_constant=60.0,
    )
    assert tied == ("first_seen", "second_seen")


def test_legacy_query_planning_preserves_fallback_dedupe_order_and_ceiling() -> None:
    fallback = _bounded_derived_retrieval_queries(
        QueryExpansionPlan(original_query="  ", expansions=()),
        fallback=" fallback text ",
    )
    plan = QueryExpansionPlan(
        original_query="original",
        decompositions=(
            QueryExpansion(query=" duplicate  query ", reason="legacy_duplicate_1"),
            QueryExpansion(query="DUPLICATE QUERY", reason="legacy_duplicate_2"),
        ),
        expansions=tuple(
            QueryExpansion(query=f"candidate {index}", reason=f"legacy_reason_{index}")
            for index in range(1, 10)
        ),
    )

    selected = _bounded_derived_retrieval_queries(plan, fallback="unused")

    assert fallback == (QueryExpansion(query=" fallback text ", reason="original_query"),)
    assert len(selected) == 8
    assert selected == (
        QueryExpansion(query="original", reason="original_query"),
        QueryExpansion(query="duplicate query", reason="legacy_duplicate_1"),
        QueryExpansion(query="candidate 1", reason="legacy_reason_1"),
        QueryExpansion(query="candidate 2", reason="legacy_reason_2"),
        QueryExpansion(query="candidate 3", reason="legacy_reason_3"),
        QueryExpansion(query="candidate 4", reason="legacy_reason_4"),
        QueryExpansion(query="candidate 5", reason="legacy_reason_5"),
        QueryExpansion(query="candidate 6", reason="legacy_reason_6"),
    )


def test_all_collector_types_preserve_legacy_fusion_and_protected_head_order() -> None:
    plan = QueryExpansionPlan(
        original_query="original",
        expansions=(
            QueryExpansion(
                query="transcript evidence",
                reason="conversation_transcript_evidence_bridge",
            ),
        ),
    )
    results_by_query = {
        "original": ("candidate_a", "shared"),
        "transcript evidence": ("candidate_b", "shared"),
    }
    chunks = {
        candidate_id: _chunk(candidate_id)
        for candidate_id in ("candidate_a", "candidate_b", "shared")
    }
    query = BuildContextQuery(
        space_id=SpaceId("space_test"),
        memory_scope_ids=(MemoryScopeId("scope_test"),),
        query="original",
        max_facts=4,
        max_chunks=4,
    )

    canonical_uow = _CanonicalUnitOfWork(results_by_query, chunks)
    canonical = asyncio.run(
        CanonicalContextCollector(uow_factory=lambda: canonical_uow).collect(
            query=query,
            memory_scope_ids=("scope_test",),
            keyword_query_plan=plan,
        )
    )
    assert tuple(str(chunk.id) for chunk in canonical.keyword_chunks) == (
        "candidate_b",
        "shared",
        "candidate_a",
    )

    hydrator = _RecordingHydrator(chunks)
    vector = asyncio.run(
        VectorContextCollector(
            vector_index=_VectorIndex(results_by_query),
            embedder=_Embedder(),
            hydrator=hydrator,
        ).collect(
            query=query,
            memory_scope_ids=("scope_test",),
            diagnostics={},
            query_plan=plan,
        )
    )
    assert tuple(str(chunk.id) for chunk in vector) == (
        "shared",
        "candidate_a",
        "candidate_b",
    )

    graph = asyncio.run(
        GraphContextCollector(
            graph_index=_GraphIndex(results_by_query),
            hydrator=hydrator,
        ).collect(
            query=query,
            memory_scope_ids=("scope_test",),
            diagnostics={},
            query_plan=plan,
        )
    )
    assert tuple(item.item_id for item in graph) == (
        "shared",
        "candidate_a",
        "candidate_b",
    )

    rag = asyncio.run(
        RagContextCollector(
            rag_recall=_RagRecall(results_by_query),
            hydrator=hydrator,
        ).collect(
            query=query,
            memory_scope_ids=("scope_test",),
            diagnostics={},
            query_plan=plan,
        )
    )
    assert tuple(item.item_id for item in rag) == (
        "shared",
        "candidate_a",
        "candidate_b",
    )


def _capabilities() -> AdapterCapabilities:
    return AdapterCapabilities(
        name="test",
        enabled=True,
        healthy=True,
        supports_upsert=False,
        supports_delete=False,
        supports_search=True,
        supports_filters=True,
    )


class _Embedder:
    async def embed_texts(self, texts: tuple[str, ...]) -> EmbeddingResult:
        return EmbeddingResult(
            status=PortStatus.OK,
            vectors=tuple((float(index),) for index, _ in enumerate(texts, start=1)),
        )


class _VectorIndex:
    def __init__(self, results_by_query: dict[str, tuple[str, ...]]) -> None:
        self._results_by_query = results_by_query

    async def capabilities(self) -> AdapterCapabilities:
        return _capabilities()

    async def search_chunks(self, *, query_text: str, **_: object) -> VectorSearchResult:
        return VectorSearchResult.ok(
            [
                VectorCandidate(
                    chunk_id=candidate_id,
                    space_id="space_test",
                    memory_scope_id="scope_test",
                    score=0.8,
                    projection_version="1",
                )
                for candidate_id in self._results_by_query[query_text]
            ]
        )


class _GraphIndex:
    def __init__(self, results_by_query: dict[str, tuple[str, ...]]) -> None:
        self._results_by_query = results_by_query

    async def capabilities(self) -> AdapterCapabilities:
        return _capabilities()

    async def search(self, *, query: str, **_: object) -> GraphSearchResult:
        return GraphSearchResult.ok(
            [
                GraphCandidate(
                    source_fact_ids=(candidate_id,),
                    source_chunk_ids=(),
                    relation_label="test",
                    score=0.8,
                    diagnostics={},
                )
                for candidate_id in self._results_by_query[query]
            ]
        )


class _RagRecall:
    def __init__(self, results_by_query: dict[str, tuple[str, ...]]) -> None:
        self._results_by_query = results_by_query

    async def recall(self, query: object) -> CapabilityRecallResult:
        query_text = query.query
        return CapabilityRecallResult(
            status=CapabilityStatus.OK,
            items=tuple(
                CapabilityRecallCandidate(
                    item_id=candidate_id,
                    item_type="chunk",
                    text="provider preview",
                    score=0.8,
                    source_refs=(),
                    capability=MemoryCapability.RAG_RECALL,
                    adapter_name="test",
                )
                for candidate_id in self._results_by_query[query_text]
            ),
        )


class _RecordingHydrator:
    def __init__(self, chunks: dict[str, MemoryChunk]) -> None:
        self._chunks = chunks

    async def hydrate_visible_chunks(
        self,
        *,
        chunk_ids: tuple[str, ...],
        **_: object,
    ) -> tuple[MemoryChunk, ...]:
        return tuple(self._chunks[chunk_id] for chunk_id in chunk_ids)

    async def hydrate_graph_facts(
        self,
        *,
        fact_ids: tuple[str, ...],
        **_: object,
    ) -> tuple[tuple[ContextItem, ...], int]:
        return (
            tuple(
                ContextItem(
                    item_id=fact_id,
                    item_type="fact",
                    text=fact_id,
                    score=0.8,
                    source_refs=(),
                )
                for fact_id in fact_ids
            ),
            0,
        )


class _CanonicalUnitOfWork:
    def __init__(
        self,
        results_by_query: dict[str, tuple[str, ...]],
        chunks: dict[str, MemoryChunk],
    ) -> None:
        self.facts = _Facts()
        self.chunks = _KeywordChunks(results_by_query, chunks)
        self.anchors = _Anchors()

    async def __aenter__(self) -> _CanonicalUnitOfWork:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _Facts:
    async def find_active(self, **_: object) -> tuple[object, ...]:
        return ()


class _KeywordChunks:
    def __init__(
        self,
        results_by_query: dict[str, tuple[str, ...]],
        chunks: dict[str, MemoryChunk],
    ) -> None:
        self._results_by_query = results_by_query
        self._chunks = chunks

    async def keyword_search(
        self,
        *,
        query: str,
        limit: int,
        **_: object,
    ) -> tuple[MemoryChunk, ...]:
        return tuple(
            self._chunks[candidate_id]
            for candidate_id in self._results_by_query[query][:limit]
        )


class _Anchors:
    async def list_for_scope(self, **_: object) -> tuple[object, ...]:
        return ()

    async def find_active_by_key(self, **_: object) -> None:
        return None


def _chunk(chunk_id: str) -> MemoryChunk:
    text = f"Canonical text for {chunk_id}."
    return MemoryChunk.create(
        chunk_id=MemoryChunkId(chunk_id),
        space_id=SpaceId("space_test"),
        memory_scope_id=MemoryScopeId("scope_test"),
        document_id=MemoryDocumentId(f"document_{chunk_id}"),
        source_type="document",
        source_external_id=f"source_{chunk_id}",
        source_hash=f"hash_{chunk_id}",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=text,
        normalized_text=text.casefold(),
        sequence=1,
        char_start=0,
        char_end=len(text),
        token_estimate=5,
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
