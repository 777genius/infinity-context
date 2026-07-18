from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import BuildContextQuery, ConsistencyMode, ContextItem
from infinity_context_core.application.use_cases import build_context as build_context_module
from infinity_context_core.application.use_cases.build_context import BuildContextUseCase
from infinity_context_core.application.use_cases.build_context_item_projection import (
    _partition_aggregation_continuity_items,
    _promote_aggregation_continuity_items,
)
from infinity_context_core.application.use_cases.build_context_keyword_aggregation import (
    _keyword_aggregation_chunk_items,
    _keyword_aggregation_intent,
)
from infinity_context_core.domain.aggregation_admission import AggregationIntent
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryScopeId,
    SpaceId,
)


def test_aggregation_admission_dedupes_and_preserves_source_families_under_cap() -> None:
    family_a = tuple(
        _chunk(
            f"project-{index}",
            f"A project used material {index}.",
            source_external_id="neutral:family-a:record:events",
        )
        for index in range(4)
    )
    family_b = _chunk(
        "project-other-family",
        "A project used a different material.",
        source_external_id="neutral:family-b:record:events",
    )

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query("List projects completed"),
        seed_chunks=(*family_a, family_a[0], family_b),
    )

    source_families = {
        item.diagnostics["provenance"]["keyword_aggregation_source_group"] for item in items
    }
    family_a_items = [
        item
        for item in items
        if item.diagnostics["provenance"]["keyword_aggregation_source_group"]
        == "neutral:family-a:record"
    ]
    assert len(family_a_items) == 3
    assert source_families == {"neutral:family-a:record", "neutral:family-b:record"}
    assert diagnostics["keyword_aggregation_chunks_deduplicated"] == 1
    assert diagnostics["keyword_aggregation_admitted_not_selected"] == 1
    assert diagnostics["keyword_aggregation_source_families_used"] == 2
    assert diagnostics["keyword_aggregation_slot_reservations_used"] == 2


def test_count_relaxation_requires_content_support_and_reports_decisions() -> None:
    supported = _chunk("supported", "A project used cedar.")
    numeric_only = _chunk("numeric", "The total was 3.")

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query("How many projects did Morgan complete?"),
        seed_chunks=(supported, numeric_only),
    )

    assert [item.item_id for item in items] == ["supported"]
    assert items[0].diagnostics["retrieval_source"] == "keyword_aggregation_chunks"
    assert items[0].score == 0.985
    assert diagnostics["keyword_aggregation_relaxed_relevance_used"] == 1
    assert diagnostics["keyword_aggregation_admission_reasons"] == {
        "relaxed_distinctive_support": 1,
        "numeric_only": 1,
    }
    assert (
        items[0].diagnostics["provenance"]["keyword_aggregation_admission_reason"]
        == "relaxed_distinctive_support"
    )


@pytest.mark.parametrize(
    "query",
    (
        "In what order did the trips happen?",
        "Which events happened in the order from first to last?",
        "What is the order of the museums from earliest to latest?",
        "Show the sequence of completed steps.",
    ),
)
def test_sequence_intent_accepts_generic_order_questions(query: str) -> None:
    assert _keyword_aggregation_intent(query) is AggregationIntent.SEQUENCE


def test_expanded_candidates_are_low_priority_continuity_items() -> None:
    ordinary = _chunk("ordinary", "Morgan completed a cedar project.")
    expanded = _chunk(
        "expanded",
        "Morgan completed an ash project.",
        source_external_id="neutral:expanded:record:events",
    )

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query("How many cedar and ash projects did Morgan complete?"),
        seed_chunks=(ordinary, expanded),
        ordinary_seed_ids=frozenset({str(ordinary.id)}),
    )

    by_id = {str(item.item_id): item for item in items}
    assert by_id["ordinary"].diagnostics["retrieval_source"] == "keyword_aggregation_chunks"
    assert by_id["expanded"].diagnostics["retrieval_source"] == "keyword_aggregation_chunks"
    assert by_id["expanded"].diagnostics["query_expansion_reason"] == "original_query"
    assert by_id["expanded"].score == 0.05
    assert "unique_term_hits" not in by_id["expanded"].diagnostics["score_signals"]
    assert (
        by_id["expanded"].diagnostics["score_signals"]["keyword_aggregation_continuity_only"] == 1
    )
    assert diagnostics["keyword_aggregation_continuity_items_used"] == 1
    ranked, continuity = _partition_aggregation_continuity_items(items)
    assert [item.item_id for item in ranked] == ["ordinary"]
    assert [item.item_id for item in continuity] == ["expanded"]


@pytest.mark.parametrize(
    ("query_text", "expected_limit"),
    (
        ("How many projects did Morgan complete?", 16),
        ("List projects Morgan completed", 8),
        ("In what order did Morgan complete the projects?", 32),
    ),
)
def test_continuity_materialization_matches_intent_source_slot_budget(
    query_text: str,
    expected_limit: int,
) -> None:
    ordinary = _chunk("ordinary-budget", "Morgan completed a project record.")
    expanded = tuple(
        _chunk(
            f"expanded-budget-{index}",
            f"Morgan completed project record {index}.",
            source_external_id=f"neutral:family-{index}:record:events",
        )
        for index in range(expected_limit + 10)
    )

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query(query_text),
        seed_chunks=(ordinary, *expanded),
        ordinary_seed_ids=frozenset({str(ordinary.id)}),
    )

    ranked, continuity = _partition_aggregation_continuity_items(items)
    promoted = _promote_aggregation_continuity_items(
        continuity,
        intent=_keyword_aggregation_intent(query_text),
        ordinary_count=len(ranked),
    )
    assert [item.item_id for item in ranked] == [ordinary.id]
    assert len(continuity) == expected_limit
    assert len(promoted) == expected_limit
    assert {item.score for item in promoted} == {0.985}
    assert diagnostics["keyword_aggregation_continuity_limit"] == expected_limit
    assert diagnostics["keyword_aggregation_continuity_items_used"] == expected_limit


@pytest.mark.parametrize("intent", (AggregationIntent.LIST, AggregationIntent.SEQUENCE))
def test_list_and_sequence_continuity_remain_promoted_with_strong_ordinary_pool(
    intent: AggregationIntent,
) -> None:
    continuity = (_continuity_item("continuity"),)

    promoted = _promote_aggregation_continuity_items(
        continuity,
        intent=intent,
        ordinary_count=4,
    )

    assert [item.item_id for item in promoted] == ["continuity"]
    assert promoted[0].score == 0.985


def test_count_continuity_does_not_displace_four_strong_ordinary_items() -> None:
    promoted = _promote_aggregation_continuity_items(
        (_continuity_item("continuity"),),
        intent=AggregationIntent.COUNT,
        ordinary_count=4,
    )

    assert promoted == ()


def test_relaxed_aggregation_evidence_reaches_the_pre_pack_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _chunk("prepack-project", "A project used cedar.")
    packer = _RecordingPacker()
    use_case = BuildContextUseCase(
        uow_factory=lambda: None,  # type: ignore[arg-type,return-value]
        ids=_Ids(),  # type: ignore[arg-type]
        vector_index=object(),  # type: ignore[arg-type]
        graph_index=object(),  # type: ignore[arg-type]
        embedder=object(),  # type: ignore[arg-type]
        packer=packer,
    )
    use_case._canonical_collector = _CanonicalCollector(candidate)  # type: ignore[assignment]
    use_case._hydrator = _Hydrator()  # type: ignore[assignment]
    use_case._artifact_evidence_collector = _ArtifactCollector()  # type: ignore[assignment]
    use_case._context_link_expander = _LinkExpander()  # type: ignore[assignment]

    async def empty_selection(**_kwargs: object) -> tuple[tuple[object, ...], dict[str, object]]:
        return (), {}

    async def temporal_passthrough(
        *,
        items: tuple[object, ...],
        **_kwargs: object,
    ) -> tuple[tuple[object, ...], dict[str, object]]:
        return items, {}

    async def empty_items(**_kwargs: object) -> tuple[object, ...]:
        return ()

    async def canonical_seeds(
        *, canonical_chunks: tuple[object, ...], **_kwargs: object
    ) -> tuple[tuple[object, ...], dict[str, object]]:
        return canonical_chunks, {}

    monkeypatch.setattr(build_context_module, "_aggregation_admission_seed_chunks", canonical_seeds)
    monkeypatch.setattr(build_context_module, "_keyword_neighbor_chunk_items", empty_selection)
    monkeypatch.setattr(
        build_context_module,
        "_keyword_source_sibling_chunk_items",
        empty_selection,
    )
    monkeypatch.setattr(build_context_module, "_pending_conflict_items", empty_items)
    monkeypatch.setattr(
        build_context_module,
        "_apply_temporal_relation_signals",
        temporal_passthrough,
    )

    result = asyncio.run(use_case.execute(_query("List projects completed")))

    admitted = next(item for item in packer.pre_pack_items if item.item_id == candidate.id)
    assert admitted.diagnostics["retrieval_source"] == "keyword_aggregation_chunks"
    assert admitted.diagnostics["score_signals"]["keyword_aggregation_relaxed_admission"] == 1
    assert result.diagnostics["keyword_aggregation_relaxed_relevance_used"] == 1


class _CanonicalCollector:
    def __init__(self, chunk: MemoryChunk) -> None:
        self._chunk = chunk

    async def collect(self, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            facts=(),
            anchors=(),
            keyword_chunks=(self._chunk,),
            keyword_query_count=1,
            keyword_query_reasons=("original_query",),
            anchor_lookup_keys_considered=0,
            anchors_loaded_by_lookup=0,
        )


class _Hydrator:
    async def revalidate_visible_items(self, items: tuple[object, ...], **_kwargs: object):
        return items


class _ArtifactCollector:
    async def collect(self, **_kwargs: object) -> tuple[object, ...]:
        return ()


class _LinkExpander:
    async def collect(self, *, items: tuple[object, ...], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(items=items, diagnostics={})


class _Ids:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_test"


class _RecordingPacker(ContextPacker):
    def __init__(self) -> None:
        self.pre_pack_items = ()

    def pack(self, **kwargs: object):
        self.pre_pack_items = kwargs["items"]
        return super().pack(**kwargs)  # type: ignore[arg-type]


def _query(text: str) -> BuildContextQuery:
    return BuildContextQuery(
        space_id=SpaceId("space-neutral"),
        memory_scope_ids=(MemoryScopeId("scope-neutral"),),
        query=text,
        max_chunks=10,
        token_budget=512,
        consistency_mode=ConsistencyMode.CANONICAL_ONLY,
    )


def _chunk(
    chunk_id: str,
    text: str,
    *,
    source_external_id: str | None = None,
) -> MemoryChunk:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryChunk.create(
        chunk_id=MemoryChunkId(chunk_id),
        space_id=SpaceId("space-neutral"),
        memory_scope_id=MemoryScopeId("scope-neutral"),
        document_id=MemoryDocumentId(f"{chunk_id}-document"),
        source_type="document",
        source_external_id=source_external_id or f"neutral:family:{chunk_id}:turn",
        source_hash=f"{chunk_id}-hash",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=text,
        normalized_text=text.casefold(),
        sequence=1,
        char_start=0,
        char_end=len(text),
        token_estimate=max(1, len(text.split())),
        now=now,
    )


def _continuity_item(item_id: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text="neutral continuity evidence",
        score=0.05,
        source_refs=(),
    )
