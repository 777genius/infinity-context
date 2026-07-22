"""Focused coverage for canonical collector repository batching."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import infinity_context_core.application.context_collectors as collectors
import pytest
from infinity_context_core.application.context_collectors import (
    CanonicalContextCollector,
    _keyword_search_chunks,
)
from infinity_context_core.application.context_query_expansion import (
    QueryExpansion,
    QueryExpansionPlan,
)
from infinity_context_core.application.dto import BuildContextQuery
from infinity_context_core.domain.entities import (
    MemoryAnchor,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryScopeId,
    SpaceId,
)
from infinity_context_core.ports.repositories import (
    ActiveAnchorKey,
    AnchorScopeQuery,
    ChunkKeywordSearch,
)


def test_keyword_batch_dedupes_normalized_queries_and_keeps_original_rank_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _chunk("original")
    duplicate = _chunk("duplicate")
    support = _chunk("support")
    shared = _chunk("shared")
    results = {
        " Original  Query ": [original, shared],
        "  DUPLICATE query ": [duplicate, shared],
        "support": [support, shared],
    }
    batch_chunks = _BatchChunks(results)
    scalar_chunks = _ScalarChunks(results)
    retrieval_queries = (
        QueryExpansion(" Original  Query ", "original_query"),
        QueryExpansion(" \n ", "blank"),
        QueryExpansion("  DUPLICATE query ", "decomposition_clause"),
        QueryExpansion("duplicate   QUERY", "duplicate_reason"),
        QueryExpansion("support", "conversation_transcript_evidence_bridge"),
    )
    recorded_rankings: list[tuple[str, ...]] = []
    fused_ranked_keys = collectors._fused_ranked_keys

    def _record_fusion(
        rankings: dict[str, tuple[str, ...]],
        *,
        limit: int,
    ) -> tuple[str, ...]:
        recorded_rankings.append(tuple(rankings))
        return fused_ranked_keys(rankings, limit=limit)

    monkeypatch.setattr(collectors, "_fused_ranked_keys", _record_fusion)

    batch_result = asyncio.run(
        _keyword_search_chunks(
            _KeywordUow(batch_chunks),
            space_id="space_test",
            memory_scope_ids=("scope_a", "scope_b"),
            thread_id="thread_test",
            retrieval_queries=retrieval_queries,
            limit=4,
        )
    )
    scalar_result = asyncio.run(
        _keyword_search_chunks(
            _KeywordUow(scalar_chunks),
            space_id="space_test",
            memory_scope_ids=("scope_a", "scope_b"),
            thread_id="thread_test",
            retrieval_queries=retrieval_queries,
            limit=4,
        )
    )

    assert batch_result == scalar_result
    assert tuple(str(chunk.id) for chunk in batch_result) == (
        "support",
        "shared",
        "original",
        "duplicate",
    )
    assert batch_chunks.call_count == 1
    assert scalar_chunks.queries == [
        " Original  Query ",
        "  DUPLICATE query ",
        "support",
    ]
    assert batch_chunks.requests == tuple(
        ChunkKeywordSearch(
            "space_test",
            ("scope_a", "scope_b"),
            "thread_test",
            query,
            20,
        )
        for query in scalar_chunks.queries
    )
    assert recorded_rankings == [
        (
            "0:original_query",
            "2:decomposition_clause",
            "4:conversation_transcript_evidence_bridge",
        ),
        (
            "0:original_query",
            "2:decomposition_clause",
            "4:conversation_transcript_evidence_bridge",
        ),
    ]


def test_collect_batches_scopes_and_capped_scope_major_anchor_keys_once() -> None:
    listed_a = _anchor("listed_a", "scope_a")
    listed_b = _anchor("listed_b", "scope_a")
    listed_c = _anchor("listed_c", "scope_b")
    lookup_a = _anchor("lookup_a", "scope_a")
    lookup_b = _anchor("lookup_b", "scope_a")
    chunk = _chunk("topic")
    operations: list[str] = []
    chunks = _BatchChunks({"topic": [chunk]}, operations=operations)
    lookup_results: list[MemoryAnchor | None] = [None] * 64
    lookup_results[0] = lookup_a
    lookup_results[1] = None
    lookup_results[2] = listed_b
    lookup_results[32] = lookup_a
    lookup_results[33] = lookup_b
    anchors = _BatchAnchors(
        scope_groups=(
            (listed_a,),
            (listed_a, listed_b),
            (listed_c,),
        ),
        lookup_results=tuple(lookup_results),
        operations=operations,
    )
    uow = _Uow(chunks=chunks, anchors=anchors, operations=operations)
    memory_scope_ids = ("scope_a", "scope_a", "scope_b")
    lookup_keys = (
        (" ", "ignored"),
        (" PERSON ", " Key   0 "),
        ("person", "key 0"),
        *((" PERSON ", f" Key   {index} ") for index in range(1, 32)),
        ("person", "not considered"),
    )

    result = asyncio.run(
        CanonicalContextCollector(uow_factory=lambda: uow).collect(
            query=_query("topic", memory_scope_ids=memory_scope_ids),
            memory_scope_ids=memory_scope_ids,
            anchor_lookup_keys=lookup_keys,
        )
    )

    assert uow.enter_count == 1
    assert uow.exit_count == 1
    assert operations == ["facts", "keyword_many", "scope_many", "key_many"]
    assert chunks.call_count == 1
    assert anchors.scope_call_count == 1
    assert anchors.key_call_count == 1
    assert anchors.scope_requests == tuple(
        AnchorScopeQuery("space_test", scope_id, None, "active", 20)
        for scope_id in memory_scope_ids
    )
    expected_key_requests = tuple(
        ActiveAnchorKey("space_test", "scope_a", "person", f"key {index}")
        for _ in range(2)
        for index in range(32)
    )
    assert anchors.key_requests == expected_key_requests
    assert len(anchors.key_requests) == 64
    assert {request.memory_scope_id for request in anchors.key_requests} == {"scope_a"}
    assert tuple(str(anchor.id) for anchor in result.anchors) == (
        "listed_a",
        "listed_b",
        "listed_c",
        "lookup_a",
        "lookup_b",
    )
    assert result.anchor_lookup_keys_considered == 64
    assert result.anchors_loaded_by_lookup == 2
    assert result.keyword_chunks == (chunk,)
    assert result.keyword_query_count == 1
    assert result.keyword_query_reasons == ("original_query",)


def test_scalar_only_repositories_use_narrow_sequential_compatibility_fallback() -> None:
    chunk_a = _chunk("topic")
    chunk_b = _chunk("more")
    listed_a = _anchor("listed_a", "scope_a")
    listed_b = _anchor("listed_b", "scope_b")
    lookup_a = _anchor("lookup_a", "scope_a")
    operations: list[str] = []
    chunks = _ScalarChunks(
        {"topic": [chunk_a], "more": [chunk_b]},
        operations=operations,
    )
    anchors = _ScalarAnchors(
        scope_results={"scope_a": [listed_a], "scope_b": [listed_b]},
        key_results={
            ("scope_a", "person", "ada"): lookup_a,
            ("scope_b", "project", "atlas"): listed_b,
        },
        operations=operations,
    )
    uow = _Uow(chunks=chunks, anchors=anchors, operations=operations)
    plan = QueryExpansionPlan(
        original_query="topic",
        expansions=(QueryExpansion("more", "decomposition_clause"),),
    )

    result = asyncio.run(
        CanonicalContextCollector(uow_factory=lambda: uow).collect(
            query=_query("topic", memory_scope_ids=("scope_a", "scope_b")),
            memory_scope_ids=("scope_a", "scope_b"),
            keyword_query_plan=plan,
            anchor_lookup_keys=(("Person", " Ada "), ("project", "Atlas")),
        )
    )

    assert chunks.queries == ["topic", "more"]
    assert anchors.scope_ids == ["scope_a", "scope_b"]
    assert anchors.key_requests == [
        ("scope_a", "person", "ada"),
        ("scope_a", "project", "atlas"),
        ("scope_b", "person", "ada"),
        ("scope_b", "project", "atlas"),
    ]
    assert operations == [
        "facts",
        "keyword:topic",
        "keyword:more",
        "scope:scope_a",
        "scope:scope_b",
        "key:scope_a:person:ada",
        "key:scope_a:project:atlas",
        "key:scope_b:person:ada",
        "key:scope_b:project:atlas",
    ]
    assert tuple(str(anchor.id) for anchor in result.anchors) == (
        "listed_a",
        "listed_b",
        "lookup_a",
    )
    assert result.anchor_lookup_keys_considered == 4
    assert result.anchors_loaded_by_lookup == 1


class _KeywordUow:
    def __init__(self, chunks: object) -> None:
        self.chunks = chunks


class _Facts:
    def __init__(self, operations: list[str]) -> None:
        self._operations = operations

    async def find_active(self, **_: object) -> tuple[object, ...]:
        self._operations.append("facts")
        return ()


class _BatchChunks:
    def __init__(
        self,
        results: dict[str, list[MemoryChunk]],
        *,
        operations: list[str] | None = None,
    ) -> None:
        self._results = results
        self._operations = operations
        self.call_count = 0
        self.requests: tuple[ChunkKeywordSearch, ...] = ()

    async def keyword_search_many(
        self,
        requests: tuple[ChunkKeywordSearch, ...],
    ) -> list[list[MemoryChunk]]:
        self.call_count += 1
        self.requests = requests
        if self._operations is not None:
            self._operations.append("keyword_many")
        return [list(self._results.get(request.query, ()))[: request.limit] for request in requests]

    async def keyword_search(self, **_: object) -> list[MemoryChunk]:
        raise AssertionError("scalar keyword search must not run when batching is available")


class _ScalarChunks:
    def __init__(
        self,
        results: dict[str, list[MemoryChunk]],
        *,
        operations: list[str] | None = None,
    ) -> None:
        self._results = results
        self._operations = operations
        self.queries: list[str] = []

    async def keyword_search(self, *, query: str, limit: int, **_: object) -> list[MemoryChunk]:
        self.queries.append(query)
        if self._operations is not None:
            self._operations.append(f"keyword:{query}")
        return list(self._results.get(query, ()))[:limit]


class _BatchAnchors:
    def __init__(
        self,
        *,
        scope_groups: tuple[tuple[MemoryAnchor, ...], ...],
        lookup_results: tuple[MemoryAnchor | None, ...],
        operations: list[str],
    ) -> None:
        self._scope_groups = scope_groups
        self._lookup_results = lookup_results
        self._operations = operations
        self.scope_call_count = 0
        self.key_call_count = 0
        self.scope_requests: tuple[AnchorScopeQuery, ...] = ()
        self.key_requests: tuple[ActiveAnchorKey, ...] = ()

    async def list_for_scopes(
        self,
        requests: tuple[AnchorScopeQuery, ...],
    ) -> list[list[MemoryAnchor]]:
        self.scope_call_count += 1
        self.scope_requests = requests
        self._operations.append("scope_many")
        return [list(group) for group in self._scope_groups]

    async def find_active_by_keys(
        self,
        requests: tuple[ActiveAnchorKey, ...],
    ) -> list[MemoryAnchor | None]:
        self.key_call_count += 1
        self.key_requests = requests
        self._operations.append("key_many")
        return list(self._lookup_results)

    async def list_for_scope(self, **_: object) -> list[MemoryAnchor]:
        raise AssertionError("scalar scope listing must not run when batching is available")

    async def find_active_by_key(self, **_: object) -> MemoryAnchor | None:
        raise AssertionError("scalar key lookup must not run when batching is available")


class _ScalarAnchors:
    def __init__(
        self,
        *,
        scope_results: dict[str, list[MemoryAnchor]],
        key_results: dict[tuple[str, str, str], MemoryAnchor],
        operations: list[str],
    ) -> None:
        self._scope_results = scope_results
        self._key_results = key_results
        self._operations = operations
        self.scope_ids: list[str] = []
        self.key_requests: list[tuple[str, str, str]] = []

    async def list_for_scope(
        self,
        *,
        memory_scope_id: str,
        **_: object,
    ) -> list[MemoryAnchor]:
        self.scope_ids.append(memory_scope_id)
        self._operations.append(f"scope:{memory_scope_id}")
        return list(self._scope_results.get(memory_scope_id, ()))

    async def find_active_by_key(
        self,
        *,
        memory_scope_id: str,
        kind: str,
        normalized_key: str,
        **_: object,
    ) -> MemoryAnchor | None:
        key = (memory_scope_id, kind, normalized_key)
        self.key_requests.append(key)
        self._operations.append(f"key:{memory_scope_id}:{kind}:{normalized_key}")
        return self._key_results.get(key)


class _Uow:
    def __init__(self, *, chunks: object, anchors: object, operations: list[str]) -> None:
        self.facts = _Facts(operations)
        self.chunks = chunks
        self.anchors = anchors
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self) -> _Uow:
        self.enter_count += 1
        return self

    async def __aexit__(self, *_: object) -> None:
        self.exit_count += 1


def _query(
    text: str,
    *,
    memory_scope_ids: tuple[str, ...],
) -> BuildContextQuery:
    return BuildContextQuery(
        space_id=SpaceId("space_test"),
        memory_scope_ids=tuple(MemoryScopeId(value) for value in memory_scope_ids),
        query=text,
        max_facts=2,
        max_chunks=4,
    )


def _chunk(chunk_id: str) -> MemoryChunk:
    text = f"Canonical text for {chunk_id}."
    return MemoryChunk.create(
        chunk_id=MemoryChunkId(chunk_id),
        space_id=SpaceId("space_test"),
        memory_scope_id=MemoryScopeId("scope_a"),
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
        now=datetime(2026, 7, 22, tzinfo=UTC),
    )


def _anchor(anchor_id: str, memory_scope_id: str) -> MemoryAnchor:
    return MemoryAnchor.create(
        anchor_id=MemoryAnchorId(anchor_id),
        space_id=SpaceId("space_test"),
        memory_scope_id=MemoryScopeId(memory_scope_id),
        kind=MemoryAnchorKind.PERSON,
        normalized_key=anchor_id,
        label=anchor_id,
        now=datetime(2026, 7, 22, tzinfo=UTC),
    )
