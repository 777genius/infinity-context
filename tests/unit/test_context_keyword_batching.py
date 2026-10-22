from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.dto import BuildContextQuery
from infinity_context_core.application.use_cases.build_context_source_selection import (
    _keyword_neighbor_chunk_items,
    _keyword_source_sibling_chunk_items,
)
from infinity_context_core.domain.entities import (
    LifecycleStatus,
    MemoryChunk,
    MemoryChunkKind,
    MemoryScopeId,
    SpaceId,
    ThreadId,
)

_QUERY = "What is the order of the six museums I visited from earliest to latest?"


def _chunk(
    chunk_id: str,
    *,
    source_id: str,
    sequence: int,
    text: str,
    document_id: str = "document",
) -> MemoryChunk:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryChunk(
        id=chunk_id,
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        document_id=document_id,
        episode_id=None,
        source_type="archive_session",
        source_external_id=source_id,
        source_hash=f"hash-{chunk_id}",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=text,
        normalized_text=text.casefold(),
        status=LifecycleStatus.ACTIVE,
        sequence=sequence,
        char_start=0,
        char_end=len(text),
        token_estimate=max(1, len(text.split())),
        created_at=now,
        updated_at=now,
        metadata={},
    )


def _query() -> BuildContextQuery:
    return BuildContextQuery(
        space_id=SpaceId("space"),
        memory_scope_ids=(MemoryScopeId("scope"),),
        thread_id=ThreadId("thread"),
        query=_QUERY,
        max_chunks=12,
    )


class _NeighborDocumentRepository:
    def __init__(self, chunks_by_document: dict[str, tuple[MemoryChunk, ...]]) -> None:
        self._chunks_by_document = chunks_by_document
        self.single_calls: list[str] = []
        self.batch_calls: list[tuple[tuple[str, ...], int]] = []

    async def list_chunks(
        self,
        document_id: str,
        *,
        limit: int | None = None,
        cursor_sequence: int | None = None,
        cursor_id: str | None = None,
    ) -> list[MemoryChunk]:
        self.single_calls.append(document_id)
        return list(self._chunks_by_document.get(document_id, ()))

    async def list_chunks_by_document_ids(
        self,
        document_ids: tuple[str, ...],
        *,
        limit_per_document: int,
    ) -> list[MemoryChunk]:
        self.batch_calls.append((tuple(document_ids), limit_per_document))
        chunks: list[MemoryChunk] = []
        for document_id in document_ids:
            chunks.extend(list(self._chunks_by_document.get(document_id, ()))[:limit_per_document])
        return chunks


class _NeighborUnitOfWork:
    def __init__(self, repository: _NeighborDocumentRepository) -> None:
        self.documents = repository

    async def __aenter__(self) -> _NeighborUnitOfWork:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def test_keyword_neighbors_fetch_documents_in_one_batch() -> None:
    chunks_by_document = {
        "document-a": (
            _chunk(
                "seed-a",
                source_id="doc-a:turn:1",
                sequence=10,
                text="Primary turn about Atlas renewal budget.",
                document_id="document-a",
            ),
            _chunk(
                "neighbor-a",
                source_id="doc-a:turn:2",
                sequence=11,
                text="Adjacent turn with follow-up owner evidence.",
                document_id="document-a",
            ),
        ),
        "document-b": (
            _chunk(
                "seed-b",
                source_id="doc-b:turn:1",
                sequence=10,
                text="Primary turn about museum visit planning.",
                document_id="document-b",
            ),
            _chunk(
                "neighbor-b",
                source_id="doc-b:turn:2",
                sequence=11,
                text="Adjacent turn with dated tour confirmation.",
                document_id="document-b",
            ),
        ),
        "document-c": (
            _chunk(
                "seed-c",
                source_id="doc-c:turn:1",
                sequence=10,
                text="Primary turn about pottery glazing temperature.",
                document_id="document-c",
            ),
            _chunk(
                "neighbor-c",
                source_id="doc-c:turn:2",
                sequence=11,
                text="Adjacent turn about kiln firing schedule.",
                document_id="document-c",
            ),
        ),
    }
    repository = _NeighborDocumentRepository(chunks_by_document)

    items, diagnostics = asyncio.run(
        _keyword_neighbor_chunk_items(
            uow_factory=lambda: _NeighborUnitOfWork(repository),
            query=_query(),
            query_plan=build_query_expansion_plan(_QUERY),
            memory_scope_ids=("scope",),
            seed_chunks=(
                chunks_by_document["document-a"][0],
                chunks_by_document["document-b"][0],
                chunks_by_document["document-c"][0],
            ),
            query_relevance_cache={},
        )
    )

    assert repository.single_calls == []
    assert len(repository.batch_calls) == 1
    assert repository.batch_calls[0][1] == 400
    assert {item.item_id for item in items} == {"neighbor-a", "neighbor-b", "neighbor-c"}
    assert diagnostics["keyword_neighbor_chunks_used"] == 3


class _BackfillChunkRepository:
    def __init__(
        self,
        *,
        initial: tuple[MemoryChunk, ...],
        backfill: tuple[MemoryChunk, ...],
    ) -> None:
        self._initial = initial
        self._backfill = backfill
        self.calls: list[dict[str, object]] = []

    async def list_by_source_external_id_groups(
        self,
        **kwargs: object,
    ) -> tuple[MemoryChunk, ...]:
        self.calls.append(dict(kwargs))
        return self._initial if len(self.calls) == 1 else self._backfill


class _BackfillUnitOfWork:
    def __init__(self, repository: _BackfillChunkRepository) -> None:
        self.chunks = repository

    async def __aenter__(self) -> _BackfillUnitOfWork:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def test_source_sibling_backfill_queries_groups_in_one_call() -> None:
    first_group = "archive:account:opaque-museum-session-a"
    second_group = "archive:account:opaque-museum-session-b"
    tail_a = _chunk(
        "museum-tail-a",
        source_id=first_group,
        sequence=4,
        text="Museum conservation advice about archival framing materials.",
    )
    tail_b = _chunk(
        "museum-tail-b",
        source_id=second_group,
        sequence=4,
        text="Museum storage advice about climate-controlled rooms.",
    )
    direct_a = _chunk(
        "museum-direct-a",
        source_id=first_group,
        sequence=0,
        text=(
            "session-0033 date: 2023/02/20 (Mon) 22:50 user: I'm planning to visit "
            "the Modern Art Museum again soon and I was wondering if you could recommend "
            "any upcoming exhibitions or events that I shouldn't miss. By the way, I "
            'attended their guided tour of "The Evolution of Abstract Expressionism" '
            "today, led by Dr. Patel, which was fantastic - her insights into Pollock "
            "and Rothko's works were incredibly enlightening. assistant: I can suggest "
            "some general planning tips for the visit and future exhibitions."
        ),
    )
    direct_b = _chunk(
        "museum-direct-b",
        source_id=second_group,
        sequence=0,
        text=(
            "session-0041 date: 2023/03/02 (Thu) 11:05 user: I visited the Museum of "
            "Modern Art's guided tour today and I learned about the conservation "
            "techniques used for their paintings collection. assistant: That sounds "
            "like a wonderful experience worth remembering."
        ),
    )
    repository = _BackfillChunkRepository(
        initial=(tail_a, tail_b),
        backfill=(direct_a, direct_b),
    )

    _items, diagnostics = asyncio.run(
        _keyword_source_sibling_chunk_items(
            uow_factory=lambda: _BackfillUnitOfWork(repository),
            query=_query(),
            query_plan=build_query_expansion_plan(_QUERY),
            memory_scope_ids=("scope",),
            seed_chunks=(tail_a, tail_b),
            query_relevance_cache={},
        )
    )

    assert diagnostics["keyword_source_sibling_group_backfill_limit"] == 96
    assert len(repository.calls) == 2
    backfill_call = repository.calls[1]
    assert set(backfill_call["source_external_id_groups"]) == {first_group, second_group}
    assert backfill_call["limit_per_group"] == 96
