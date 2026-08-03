from __future__ import annotations

from datetime import UTC, datetime

import pytest
from infinity_context_core.application.context_distinct_set_evidence import (
    DistinctSetEvidenceProjection,
)
from infinity_context_core.application.context_query_intent import (
    QueryAnchorIntent,
    build_query_anchor_intent,
    query_anchor_intent_text_conflicts,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.dto import BuildContextQuery, ConsistencyMode
from infinity_context_core.application.use_cases import (
    build_context_keyword_aggregation as keyword_aggregation,
)
from infinity_context_core.application.use_cases import (
    build_context_keyword_aggregation_selection as aggregation_selection,
)
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryScopeId,
    SpaceId,
)

_INTERVAL_QUERY = (
    "How many days passed between the day Morgan called Project Atlas and the day "
    "Riley attended a workshop for Project Beacon?"
)
_ORDERING_QUERY = (
    "Which happened first, Morgan called Project Atlas or Riley attended a workshop "
    "for Project Beacon?"
)
_FIRST_EVIDENCE = "user: Morgan called Project Atlas on Monday."
_SECOND_EVIDENCE = "user: Riley attended a workshop for Project Beacon on Friday."
_UNRELATED_EVIDENCE = "user: Jordan called Project Noise on Tuesday."


@pytest.mark.parametrize(
    ("query", "reasons"),
    (
        (
            _INTERVAL_QUERY,
            (
                "decomposition_temporal_interval_endpoint_1",
                "decomposition_temporal_interval_endpoint_2",
            ),
        ),
        (
            _ORDERING_QUERY,
            (
                "decomposition_temporal_endpoint_1",
                "decomposition_temporal_endpoint_2",
            ),
        ),
    ),
)
def test_verified_temporal_endpoints_admit_both_local_evidence_candidates(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    reasons: tuple[str, str],
) -> None:
    endpoint_intents = aggregation_selection.temporal_endpoint_anchor_intents(query)
    first_key = next(key for key in endpoint_intents if key[0] == reasons[0])
    second_key = next(key for key in endpoint_intents if key[0] == reasons[1])
    conflicting_full_query_intent = build_query_anchor_intent(
        "Did Jordan call Project Noise?"
    )
    first_projection = _member_projection(_FIRST_EVIDENCE, member_id="morgan-call")
    second_projection = _member_projection(_SECOND_EVIDENCE, member_id="riley-workshop")

    assert aggregation_selection.distinct_set_anchor_conflict(
        conflicting_full_query_intent,
        projection=first_projection,
        fallback_text=_FIRST_EVIDENCE,
    )
    assert aggregation_selection.distinct_set_anchor_conflict(
        conflicting_full_query_intent,
        projection=second_projection,
        fallback_text=_SECOND_EVIDENCE,
    )

    def endpoint_relevance(*, text: str, **_kwargs: object) -> tuple[str, str, QueryRelevance]:
        key = first_key if "Morgan" in text else second_key
        return key[1], key[0], _relevance()

    def member_projection(*, text: str, **_kwargs: object) -> DistinctSetEvidenceProjection:
        return first_projection if "Morgan" in text else second_projection

    monkeypatch.setattr(
        keyword_aggregation,
        "build_query_anchor_intent",
        lambda _query: conflicting_full_query_intent,
    )
    monkeypatch.setattr(keyword_aggregation, "_aggregation_query_relevance", endpoint_relevance)
    monkeypatch.setattr(
        keyword_aggregation,
        "project_distinct_set_evidence",
        member_projection,
    )

    items, diagnostics = keyword_aggregation._keyword_aggregation_chunk_items(
        query=_query(query),
        seed_chunks=(
            _chunk("morgan-call", _FIRST_EVIDENCE),
            _chunk("riley-workshop", _SECOND_EVIDENCE),
        ),
    )

    assert {item.item_id for item in items} == {"morgan-call", "riley-workshop"}
    assert {item.source_refs[0].source_id for item in items} == {
        "neutral:morgan-call:turn",
        "neutral:riley-workshop:turn",
    }
    assert diagnostics["keyword_aggregation_admission_reasons"] == {
        "distinct_member_support": 2
    }


def test_endpoint_local_intent_still_rejects_unrelated_evidence() -> None:
    endpoint_intents = aggregation_selection.temporal_endpoint_anchor_intents(_INTERVAL_QUERY)
    reason = "decomposition_temporal_interval_endpoint_1"
    aggregation_query = next(query for slot, query in endpoint_intents if slot == reason)
    local_intent = aggregation_selection.keyword_aggregation_candidate_anchor_intent(
        full_query_anchor_intent=build_query_anchor_intent("Did Jordan call Project Noise?"),
        aggregation_reason=reason,
        aggregation_query=aggregation_query,
        temporal_endpoint_intents=endpoint_intents,
    )

    assert query_anchor_intent_text_conflicts(local_intent, _UNRELATED_EVIDENCE)


def test_ordinary_candidate_keeps_full_query_anchor_conflict() -> None:
    full_query_anchor_intent = build_query_anchor_intent("Did Jordan call Project Noise?")
    endpoint_intents = aggregation_selection.temporal_endpoint_anchor_intents(_INTERVAL_QUERY)
    selected_intent = aggregation_selection.keyword_aggregation_candidate_anchor_intent(
        full_query_anchor_intent=full_query_anchor_intent,
        aggregation_reason="original_query",
        aggregation_query=_INTERVAL_QUERY,
        temporal_endpoint_intents=endpoint_intents,
    )

    assert selected_intent is full_query_anchor_intent
    assert query_anchor_intent_text_conflicts(selected_intent, _FIRST_EVIDENCE)


@pytest.mark.parametrize(
    ("aggregation_reason", "aggregation_query"),
    (
        (
            "decomposition_temporal_interval_endpoint_3",
            "the day Morgan called Project Atlas",
        ),
        (
            "decomposition_temporal_interval_endpoint_1_spoofed",
            "the day Morgan called Project Atlas",
        ),
        (
            "decomposition_temporal_interval_endpoint_1",
            "the day Jordan called Project Noise",
        ),
    ),
)
def test_invalid_or_spoofed_endpoint_reason_does_not_bypass_full_anchor_intent(
    aggregation_reason: str,
    aggregation_query: str,
) -> None:
    full_query_anchor_intent: QueryAnchorIntent = build_query_anchor_intent(
        "Did Jordan call Project Noise?"
    )
    selected_intent = aggregation_selection.keyword_aggregation_candidate_anchor_intent(
        full_query_anchor_intent=full_query_anchor_intent,
        aggregation_reason=aggregation_reason,
        aggregation_query=aggregation_query,
        temporal_endpoint_intents=aggregation_selection.temporal_endpoint_anchor_intents(
            _INTERVAL_QUERY
        ),
    )

    assert selected_intent is full_query_anchor_intent
    assert query_anchor_intent_text_conflicts(selected_intent, _FIRST_EVIDENCE)


def _member_projection(text: str, *, member_id: str) -> DistinctSetEvidenceProjection:
    return DistinctSetEvidenceProjection(
        member_ids=(member_id,),
        identities=(member_id,),
        evidence_sentences=(text,),
        rendered_text=text,
    )


def _relevance() -> QueryRelevance:
    return QueryRelevance(
        score_boost=0.12,
        query_term_count=3,
        unique_term_hits=3,
        capped_frequency_hits=3,
        hit_ratio=1.0,
        distinctive_term_count=3,
        distinctive_term_hits=3,
    )


def _query(text: str) -> BuildContextQuery:
    return BuildContextQuery(
        space_id=SpaceId("space-neutral"),
        memory_scope_ids=(MemoryScopeId("scope-neutral"),),
        query=text,
        max_chunks=10,
        token_budget=512,
        consistency_mode=ConsistencyMode.CANONICAL_ONLY,
    )


def _chunk(chunk_id: str, text: str) -> MemoryChunk:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryChunk.create(
        chunk_id=MemoryChunkId(chunk_id),
        space_id=SpaceId("space-neutral"),
        memory_scope_id=MemoryScopeId("scope-neutral"),
        document_id=MemoryDocumentId(f"{chunk_id}-document"),
        source_type="document",
        source_external_id=f"neutral:{chunk_id}:turn",
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
