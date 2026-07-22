from __future__ import annotations

from datetime import UTC, datetime

from infinity_context_core.application.context_count_cardinality import (
    keyword_aggregation_intent,
)
from infinity_context_core.application.context_query_decomposition import (
    build_query_decomposition_plan,
)
from infinity_context_core.application.context_temporal_intent_policy import (
    TemporalOrderingKind,
    temporal_ordering_intent,
)
from infinity_context_core.application.dto import BuildContextQuery, ConsistencyMode
from infinity_context_core.application.use_cases.build_context_keyword_aggregation import (
    _keyword_aggregation_chunk_items,
)
from infinity_context_core.domain.aggregation_admission import (
    AggregationAdmissionCandidate,
    AggregationAdmissionPolicy,
    AggregationAdmissionSignals,
    AggregationIntent,
)
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryScopeId,
    SpaceId,
)


def test_which_happened_last_produces_two_bounded_production_decompositions() -> None:
    query = "Which happened last, Morgan started Atlas or Riley finished Orion?"

    intent = temporal_ordering_intent(query)
    plan = build_query_decomposition_plan(query)

    assert intent.kind is TemporalOrderingKind.ORDER
    assert [endpoint.query for endpoint in intent.endpoints] == [
        "Morgan started Atlas",
        "Riley finished Orion",
    ]
    assert [(item.reason, item.query) for item in plan.decompositions[:2]] == [
        ("decomposition_temporal_endpoint_1", "Morgan started Atlas"),
        ("decomposition_temporal_endpoint_2", "Riley finished Orion"),
    ]
    assert keyword_aggregation_intent(query) is AggregationIntent.SEQUENCE


def test_exact_three_recent_trips_has_order_intent_without_invented_endpoints() -> None:
    query = (
        "What were the exact three trips in the past three months "
        "from earliest to latest?"
    )

    intent = temporal_ordering_intent(query)
    plan = build_query_decomposition_plan(query)

    assert intent.kind is TemporalOrderingKind.ORDER
    assert intent.endpoints == ()
    assert plan.decompositions[0].reason == "decomposition_temporal_ordering"
    assert not any("endpoint" in item.reason for item in plan.decompositions)
    assert keyword_aggregation_intent(query) is AggregationIntent.SEQUENCE


def test_named_ordering_endpoints_are_explicit_and_bounded() -> None:
    intent = temporal_ordering_intent(
        "In what order did the Lisbon trip, Kyoto trip, and Oslo trip happen?"
    )

    assert [endpoint.query for endpoint in intent.endpoints] == [
        "the Lisbon trip",
        "Kyoto trip",
        "Oslo trip",
    ]
    assert len(intent.endpoints) <= 4


def test_ordinary_numbers_durations_and_single_recency_are_inert() -> None:
    for query in (
        "How long did Morgan work on Atlas?",
        "Morgan worked on Atlas for three months.",
        "What happened on Morgan's last trip?",
        "Which three trips did Morgan take?",
    ):
        assert not temporal_ordering_intent(query).explicit


def test_sequence_admission_cannot_double_fill_from_one_semantic_family() -> None:
    def candidate(candidate_id: str, slot: str, family: str) -> AggregationAdmissionCandidate:
        return AggregationAdmissionCandidate(
            candidate_id=candidate_id,
            signals=AggregationAdmissionSignals(
                intent=AggregationIntent.SEQUENCE,
                relevance_sufficient=True,
                distinctive_hits=2,
                unique_hits=2,
                query_plan_slot=slot,
                source_family=family,
            ),
        )

    selection = AggregationAdmissionPolicy().select(
        (
            candidate("mirror-a", "decomposition_temporal_endpoint_1", "session-7"),
            candidate("mirror-b", "decomposition_temporal_endpoint_2", "session-7"),
            candidate("independent", "decomposition_temporal_endpoint_2", "session-8"),
        ),
        limit=3,
        source_family_cap=3,
    )

    assert selection.selected_ids == ("mirror-a", "independent")
    assert selection.reserved_ids == ("mirror-a", "independent")


def test_sequence_family_guard_does_not_cap_same_source_non_sequence_evidence() -> None:
    def candidate(candidate_id: str, intent: AggregationIntent) -> AggregationAdmissionCandidate:
        return AggregationAdmissionCandidate(
            candidate_id=candidate_id,
            signals=AggregationAdmissionSignals(
                intent=intent,
                relevance_sufficient=True,
                distinctive_hits=2,
                unique_hits=2,
                query_plan_slot="original_query",
                source_family="session-7",
            ),
        )

    selection = AggregationAdmissionPolicy().select(
        (
            candidate("sequence", AggregationIntent.SEQUENCE),
            candidate("list-a", AggregationIntent.LIST),
            candidate("list-b", AggregationIntent.LIST),
        ),
        limit=3,
        source_family_cap=3,
        reserve_supported_slots=False,
    )

    assert selection.selected_ids == ("sequence", "list-a", "list-b")


def test_sequence_family_guard_fills_cap_from_independent_families() -> None:
    def candidate(candidate_id: str, family: str) -> AggregationAdmissionCandidate:
        return AggregationAdmissionCandidate(
            candidate_id=candidate_id,
            signals=AggregationAdmissionSignals(
                intent=AggregationIntent.SEQUENCE,
                relevance_sufficient=True,
                distinctive_hits=2,
                unique_hits=2,
                query_plan_slot="original_query",
                source_family=family,
            ),
        )

    selection = AggregationAdmissionPolicy().select(
        (
            candidate("mirror-a", "session-7"),
            candidate("mirror-b", "session-7"),
            candidate("event-b", "session-8"),
            candidate("event-c", "session-9"),
        ),
        limit=3,
        source_family_cap=3,
        reserve_supported_slots=False,
    )

    assert selection.selected_ids == ("mirror-a", "event-b", "event-c")


def test_production_sequence_selection_does_not_double_fill_mirrored_family() -> None:
    query_text = "Which happened last, Morgan started Atlas or Riley finished Orion?"
    query = BuildContextQuery(
        space_id=SpaceId("space-neutral"),
        memory_scope_ids=(MemoryScopeId("scope-neutral"),),
        query=query_text,
        max_chunks=10,
        token_budget=512,
        consistency_mode=ConsistencyMode.CANONICAL_ONLY,
    )
    chunks = (
        _chunk(
            "mirror-event",
            "Morgan started Atlas before Riley finished Orion.",
            "neutral:session-7:record:events",
        ),
        _chunk(
            "mirror-summary",
            "Morgan started Atlas; later Riley finished Orion.",
            "neutral:session-7:record:summary",
        ),
        _chunk(
            "independent",
            "Riley finished Orion during the final review.",
            "neutral:session-8:record:events",
        ),
    )

    items, diagnostics = _keyword_aggregation_chunk_items(query=query, seed_chunks=chunks)

    selected_ids = {str(item.item_id) for item in items}
    assert len(selected_ids & {"mirror-event", "mirror-summary"}) == 1
    assert "independent" in selected_ids
    assert diagnostics["keyword_aggregation_source_families_used"] == 2


def _chunk(chunk_id: str, text: str, source_external_id: str) -> MemoryChunk:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryChunk.create(
        chunk_id=MemoryChunkId(chunk_id),
        space_id=SpaceId("space-neutral"),
        memory_scope_id=MemoryScopeId("scope-neutral"),
        document_id=MemoryDocumentId(f"{chunk_id}-document"),
        source_type="document",
        source_external_id=source_external_id,
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
