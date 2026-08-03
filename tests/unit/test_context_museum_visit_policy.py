from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from infinity_context_core.application.context_museum_visit_policy import (
    ordered_museum_visit_query,
    strong_dated_museum_visit_evidence,
)
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_relation_requirement import (
    relation_requirement_signal,
)
from infinity_context_core.application.dto import BuildContextQuery
from infinity_context_core.application.use_cases.build_context_source_selection import (
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


def test_ordered_museum_visit_query_requires_visit_target_and_order() -> None:
    assert ordered_museum_visit_query(_QUERY)
    assert not ordered_museum_visit_query("Which museums should I visit next?")
    assert not ordered_museum_visit_query("What is the order of my six appointments?")


def test_strong_museum_visit_evidence_accepts_dated_direct_tours() -> None:
    assert strong_dated_museum_visit_evidence(
        query=_QUERY,
        text=(
            "session-0020 date: 2023/02/15 (Wed) 12:20 user: I participated in a "
            "behind-the-scenes tour of the Museum of History's conservation lab today."
        ),
    )
    assert strong_dated_museum_visit_evidence(
        query=_QUERY,
        text=(
            "session-0033 date: 2023/02/20 (Mon) 22:50 user: I am planning to visit "
            "the Modern Art Museum again soon. I attended their guided tour today."
        ),
    )


def test_strong_museum_visit_evidence_rejects_later_recollections_and_plans() -> None:
    assert not strong_dated_museum_visit_evidence(
        query=_QUERY,
        text=(
            "session-0033 date: 2023/02/20 (Mon) 22:50 user: I recently saw artifacts "
            "at the Metropolitan Museum and learned about feminist art in a lecture "
            "series at the Museum of Contemporary Art."
        ),
    )
    assert not strong_dated_museum_visit_evidence(
        query=_QUERY,
        text=(
            "session-0040 date: 2023/02/27 (Mon) 09:00 user: I plan to visit the City Museum today."
        ),
    )


def test_strong_museum_visit_evidence_satisfies_relation_guard() -> None:
    signal = relation_requirement_signal(
        query=_QUERY,
        text=(
            "session-0020 date: 2023/02/15 (Wed) 12:20 user: I participated in a "
            "behind-the-scenes tour of the Museum of History's conservation lab today."
        ),
    )

    assert signal.reason == "relation_requirement_match"
    assert signal.boost == 0.018


def test_ordered_museum_selection_backfills_full_group_and_promotes_direct_turn() -> None:
    source_id = "archive:account:opaque-museum-session"
    direct = _chunk(
        "museum-direct",
        source_id=source_id,
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
    tail = _chunk(
        "museum-tail",
        source_id=source_id,
        sequence=4,
        text="Museum conservation advice about archival framing materials.",
    )
    trailing_noise = _chunk(
        "museum-trailing-noise",
        source_id=source_id,
        sequence=5,
        text="General archive storage guidance without a dated visit.",
    )
    repository = _BackfillChunkRepository(
        initial=(tail,),
        backfill=(direct, trailing_noise),
    )

    items, diagnostics = asyncio.run(
        _keyword_source_sibling_chunk_items(
            uow_factory=lambda: _BackfillUnitOfWork(repository),
            query=BuildContextQuery(
                space_id=SpaceId("space"),
                memory_scope_ids=(MemoryScopeId("scope"),),
                thread_id=ThreadId("thread"),
                query=_QUERY,
                max_chunks=10,
            ),
            query_plan=build_query_expansion_plan(_QUERY),
            memory_scope_ids=("scope",),
            seed_chunks=(tail,),
            query_relevance_cache={},
        )
    )

    direct_item = next(item for item in items if item.item_id == direct.id)
    assert len(repository.calls) == 2
    assert direct_item.score == 0.99
    assert "today, led by Dr. Patel" in direct_item.text
    assert direct_item.diagnostics["score_signals"]["source_sibling_answer_evidence"] == 1
    assert (
        relation_requirement_signal(query=_QUERY, text=direct_item.text).reason
        == "relation_requirement_match"
    )
    assert diagnostics["keyword_source_sibling_ordered_museum_coverage"] is True
    assert diagnostics["keyword_source_sibling_group_backfill_limit"] == 96
    assert diagnostics["keyword_source_sibling_group_backfill_chunks_used"] == 2


def _chunk(
    chunk_id: str,
    *,
    source_id: str,
    sequence: int,
    text: str,
) -> MemoryChunk:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryChunk(
        id=chunk_id,
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        document_id="document",
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


class _BackfillChunkRepository:
    def __init__(
        self,
        *,
        initial: tuple[MemoryChunk, ...],
        backfill: tuple[MemoryChunk, ...],
    ) -> None:
        self._initial = initial
        self._backfill = backfill
        self.calls: list[tuple[str, ...]] = []

    async def list_by_source_external_id_groups(
        self,
        **kwargs: object,
    ) -> tuple[MemoryChunk, ...]:
        groups = tuple(str(value) for value in kwargs["source_external_id_groups"])
        self.calls.append(groups)
        return self._initial if len(self.calls) == 1 else self._backfill


class _BackfillUnitOfWork:
    def __init__(self, repository: _BackfillChunkRepository) -> None:
        self.chunks = repository

    async def __aenter__(self) -> _BackfillUnitOfWork:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None
