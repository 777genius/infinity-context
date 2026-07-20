from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from infinity_context_core.application.context_distinct_set_evidence import (
    project_distinct_set_evidence,
)
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent_extraction import (
    build_query_anchor_intent,
)
from infinity_context_core.application.context_query_intent_matching import (
    query_anchor_intent_text_conflicts,
)
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
from infinity_context_core.application.use_cases.build_context_keyword_aggregation_seeds import (
    aggregation_admission_seed_chunks,
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


def test_distinct_set_members_are_reserved_as_source_backed_user_assertions() -> None:
    community = _chunk(
        "community-tank",
        "user: I need plants for my community tank.\n"
        "assistant: You could buy a quarantine tank next.",
        source_external_id="neutral:tanks:community:turn",
    )
    five_gallon = _chunk(
        "five-gallon-tank",
        "user: I have a 5-gallon tank with a betta fish.",
        source_external_id="neutral:tanks:five-gallon:turn",
    )

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query("How many tanks do I currently have?"),
        seed_chunks=(community, five_gallon),
    )

    assert {item.item_id for item in items} == {community.id, five_gallon.id}
    assert all("user assertion:" in item.text for item in items)
    assert any("my community tank" in item.text for item in items)
    assert all("quarantine tank" not in item.text for item in items)
    assert all(
        item.diagnostics["score_signals"]["keyword_aggregation_distinct_member_support"] == 1
        for item in items
    )
    assert diagnostics["keyword_aggregation_distinct_member_reservations_used"] == 2
    assert diagnostics["keyword_aggregation_distinct_member_slots_used"] == 2
    assert diagnostics["keyword_aggregation_admission_reasons"] == {"distinct_member_support": 2}


def test_distinct_set_aggregation_dedupes_member_identity_across_event_context() -> None:
    lime_daiquiri = _chunk(
        "lime-daiquiri",
        "user: I learned a Daiquiri using fresh lime juice.",
        source_external_id="neutral:recipes:daiquiri:turn",
    )
    lime_gimlet = _chunk(
        "lime-gimlet",
        "user: I made a Cucumber Gimlet using lime juice.",
        source_external_id="neutral:recipes:gimlet:turn",
    )
    orange_bitters = _chunk(
        "orange-bitters",
        "user: I made orange bitters using orange peels.",
        source_external_id="neutral:recipes:bitters:turn",
    )

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query("How many different types of citrus fruits have I used in cocktail recipes?"),
        seed_chunks=(lime_daiquiri, lime_gimlet, orange_bitters),
    )

    assert {item.item_id for item in items} == {lime_daiquiri.id, orange_bitters.id}
    selected_lime = next(item for item in items if item.item_id == lime_daiquiri.id)
    assert {ref.source_id for ref in selected_lime.source_refs} == {
        "neutral:recipes:daiquiri:turn",
        "neutral:recipes:gimlet:turn",
    }
    assert diagnostics["keyword_aggregation_distinct_member_candidates"] == 3
    assert diagnostics["keyword_aggregation_distinct_member_reservations_used"] == 2
    assert diagnostics["keyword_aggregation_distinct_member_slots_used"] == 2


def test_distinct_set_aggregation_keeps_source_with_novel_referenced_member() -> None:
    table_only = _chunk(
        "table-only",
        "user: I got a new coffee table for my den.",
        source_external_id="neutral:furniture:table-only:turn",
    )
    table_and_mattress = _chunk(
        "table-and-mattress",
        (
            "user: I got a new coffee table for my den. "
            "I've been meaning to replace my mattress, and last week I finally "
            "took the plunge and ordered one from a local shop."
        ),
        source_external_id="neutral:furniture:table-and-mattress:turn",
    )

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query("How many pieces of furniture did I buy recently?"),
        seed_chunks=(table_only, table_and_mattress),
    )

    assert [item.item_id for item in items] == [table_and_mattress.id]
    assert {ref.source_id for ref in items[0].source_refs} == {
        "neutral:furniture:table-only:turn",
        "neutral:furniture:table-and-mattress:turn",
    }
    assert diagnostics["keyword_aggregation_distinct_member_candidates"] == 2
    assert diagnostics["keyword_aggregation_distinct_member_reservations_used"] == 1
    assert diagnostics["keyword_aggregation_distinct_member_slots_used"] == 2


def test_distinct_set_provenance_excludes_conflicts_and_has_hard_ref_cap() -> None:
    safe_duplicates = tuple(
        _chunk(
            f"lime-safe-{index}",
            "user: I used fresh lime juice in a cocktail recipe.",
            source_external_id=f"neutral:recipes:lime-safe-{index}:turn",
        )
        for index in range(10)
    )
    stale_duplicate = _chunk(
        "lime-stale",
        "user: I used fresh lime juice in a cocktail recipe last year.",
        source_external_id="neutral:recipes:lime-stale:turn",
    )

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query(
            "How many different types of citrus fruits have I used "
            "in cocktail recipes this year?"
        ),
        seed_chunks=(*safe_duplicates, stale_duplicate),
    )

    assert len(items) == 1
    assert len(items[0].source_refs) == 8
    assert all("lime-safe" in ref.source_id for ref in items[0].source_refs)
    assert all("lime-stale" not in ref.source_id for ref in items[0].source_refs)
    assert diagnostics["keyword_aggregation_distinct_member_candidates"] == 10
    assert diagnostics["keyword_aggregation_admission_reasons"]["temporal_conflict"] == 1


def test_distinct_set_rejects_last_year_wedding_evidence_for_this_year_query() -> None:
    last_year = _chunk(
        "last-year-wedding",
        "user: I attended Robin's wedding last year.",
    )

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query("How many weddings have I attended this year?"),
        seed_chunks=(last_year,),
    )

    assert items == ()
    assert diagnostics["keyword_aggregation_distinct_member_candidates"] == 0
    assert diagnostics["keyword_aggregation_admission_reasons"] == {"temporal_conflict": 1}


def test_distinct_set_keeps_only_in_window_member_from_mixed_temporal_clauses() -> None:
    mixed = _chunk(
        "mixed-weddings",
        "user: I attended Robin's wedding last year, "
        "but I attended a wedding last weekend.",
    )

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query("How many weddings have I attended this year?"),
        seed_chunks=(mixed,),
    )

    assert [item.item_id for item in items] == [mixed.id]
    assert "Robin" not in items[0].text
    assert "wedding last weekend" in items[0].text
    assert diagnostics["keyword_aggregation_admission_reasons"] == {
        "distinct_member_support": 1
    }


def test_distinct_set_uses_safe_projection_despite_unrelated_chunk_anchor_conflict() -> None:
    query_text = "How many weddings have I attended this year for Project Atlas?"
    evidence = _chunk(
        "atlas-wedding",
        "user: I attended Rachel's wedding this year.\n"
        "assistant: Project Beacon planning starts next year.",
    )
    projection = project_distinct_set_evidence(query=query_text, text=evidence.text)
    anchor_intent = build_query_anchor_intent(query_text)

    assert query_anchor_intent_text_conflicts(anchor_intent, evidence.text)
    assert projection.present
    assert not query_anchor_intent_text_conflicts(anchor_intent, projection.rendered_text)

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query(query_text),
        seed_chunks=(evidence,),
    )

    assert [item.item_id for item in items] == [evidence.id]
    assert "wedding this year" in items[0].text
    assert "Project Beacon" not in items[0].text
    assert diagnostics["keyword_aggregation_distinct_member_reservations_used"] == 1


@pytest.mark.parametrize(
    ("query_text", "evidence_text"),
    (
        (
            "How many museums did I visit in February?",
            "user: I visited the Natural History Museum on 2/8.",
        ),
        (
            "How many properties did I view before offering on the Brookside townhouse?",
            "user: I've seen a property in Cedar Creek that did not fit my budget.",
        ),
    ),
)
def test_distinct_set_projection_does_not_treat_time_or_place_as_named_subject(
    query_text: str,
    evidence_text: str,
) -> None:
    evidence = _chunk("grounded-member", evidence_text)

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query(query_text),
        seed_chunks=(evidence,),
    )

    assert [item.item_id for item in items] == [evidence.id]
    assert diagnostics["keyword_aggregation_distinct_member_reservations_used"] == 1


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


def test_requirement_guard_cannot_be_bypassed_by_distinct_evidence_restoration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _chunk(
        "guarded-wedding",
        "user: I attended Robin's wedding this year.",
    )
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
    real_rerank = build_context_module.apply_deterministic_rerank_adjustments
    rerank_calls: list[tuple[str, tuple[ContextItem, ...]]] = []

    def recording_rerank(
        items: tuple[ContextItem, ...],
        **kwargs: object,
    ) -> tuple[ContextItem, ...]:
        rerank_calls.append((str(kwargs["query"]), items))
        return real_rerank(items, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        build_context_module,
        "apply_deterministic_rerank_adjustments",
        recording_rerank,
    )

    result = asyncio.run(
        use_case.execute(
            _query("How many weddings have I attended this year for Project Atlas?")
        )
    )

    assert all(item.item_id != candidate.id for item in packer.pre_pack_items)
    assert len(rerank_calls) == 1
    assert rerank_calls[0][0] == (
        "How many weddings have I attended this year for Project Atlas?"
    )
    reranked_candidate = next(item for item in rerank_calls[0][1] if item.item_id == candidate.id)
    assert reranked_candidate.text.startswith("user assertion:")
    assert "deterministic_rerank_applied" not in reranked_candidate.diagnostics["provenance"]
    assert result.diagnostics["requirement_guard_status"] == "dropped_missing_project_anchor"
    assert result.diagnostics["requirement_guard_items_dropped"] > 0


def test_aggregation_seed_helper_fans_out_distinct_set_queries_and_dedupes() -> None:
    canonical = _chunk("canonical-seed", "user: I used orange peels in a recipe.")
    recovered = _chunk("recovered-seed", "user: I used lime juice in a recipe.")
    chunks = _RecordingKeywordChunks((canonical, recovered))
    uow = _KeywordSeedUow(chunks)
    query = _query(
        "How many different types of citrus fruits have I used in cocktail recipes?"
    )

    seeds, diagnostics = asyncio.run(
        aggregation_admission_seed_chunks(
            uow_factory=lambda: uow,  # type: ignore[arg-type]
            query=query,
            query_plan=build_query_expansion_plan(query.query),
            canonical_chunks=(canonical,),
        )
    )

    assert [chunk.id for chunk in seeds] == [canonical.id, recovered.id]
    assert chunks.queries[0] == query.query
    assert "citrus fruit" in chunks.queries
    assert "use citrus fruit" in chunks.queries
    assert diagnostics == {
        "keyword_aggregation_admission_queries": len(chunks.queries),
        "keyword_aggregation_admission_seed_chunks": 2,
        "keyword_aggregation_admission_seed_chunks_added": 1,
    }


def test_provider_seed_fanout_recovers_implicit_events_without_counting_noise() -> None:
    canonical = _chunk("canonical-seed", "user: I planned weekday lunches.")
    implicit = _chunk(
        "implicit-provider",
        "user: My evenings have been all about Cedar Cart lately.",
        source_external_id="neutral:provider:implicit:event",
    )
    category = _chunk(
        "category-provider",
        "user: I used Harbor Spoon, a meal delivery platform, recently.",
        source_external_id="neutral:provider:category:event",
    )
    noise = _chunk(
        "dash-noise",
        "user: I used Dash as a document heading.",
        source_external_id="neutral:writing:dash:event",
    )
    recommendation = _chunk(
        "assistant-recommendation",
        "assistant: I recommend Amber Table for food delivery.",
        source_external_id="neutral:assistant:recommendation:event",
    )
    chunks = _ProviderKeywordChunks(
        implicit=implicit,
        category=category,
        noise=noise,
        recommendation=recommendation,
    )
    query = _query(
        "How many different types of food delivery services have I used recently?"
    )

    seeds, diagnostics = asyncio.run(
        aggregation_admission_seed_chunks(
            uow_factory=lambda: _KeywordSeedUow(chunks),  # type: ignore[arg-type]
            query=query,
            query_plan=build_query_expansion_plan(query.query),
            canonical_chunks=(canonical,),
        )
    )
    items, _ = _keyword_aggregation_chunk_items(
        query=query,
        query_plan=build_query_expansion_plan(query.query),
        seed_chunks=seeds,
        ordinary_seed_ids=frozenset({str(canonical.id)}),
    )

    projected_ids = {
        item.item_id
        for item in items
        if item.diagnostics["score_signals"].get(
            "keyword_aggregation_distinct_member_support"
        )
        == 1
    }
    assert projected_ids == {str(implicit.id), str(category.id)}
    assert str(noise.id) not in projected_ids
    assert str(recommendation.id) not in projected_ids
    assert any("all about rely relying relied" in value for value in chunks.queries)
    assert "food delivery" in chunks.queries
    assert any("recent recently lately" in value for value in chunks.queries)
    assert diagnostics["keyword_aggregation_admission_seed_chunks_added"] == 4


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


class _RecordingKeywordChunks:
    def __init__(self, chunks: tuple[MemoryChunk, ...]) -> None:
        self._chunks = chunks
        self.queries: list[str] = []

    async def keyword_search(self, **kwargs: object) -> tuple[MemoryChunk, ...]:
        self.queries.append(str(kwargs["query"]))
        return self._chunks


class _ProviderKeywordChunks(_RecordingKeywordChunks):
    def __init__(
        self,
        *,
        implicit: MemoryChunk,
        category: MemoryChunk,
        noise: MemoryChunk,
        recommendation: MemoryChunk,
    ) -> None:
        super().__init__(())
        self._implicit = implicit
        self._category = category
        self._noise = noise
        self._recommendation = recommendation

    async def keyword_search(self, **kwargs: object) -> tuple[MemoryChunk, ...]:
        query = str(kwargs["query"])
        self.queries.append(query)
        if "recent recently lately" in query:
            return self._implicit, self._noise, self._recommendation
        if query == "food delivery":
            return (self._category,)
        return ()


class _KeywordSeedUow:
    def __init__(self, chunks: _RecordingKeywordChunks) -> None:
        self.chunks = chunks

    async def __aenter__(self) -> _KeywordSeedUow:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


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
