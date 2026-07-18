from __future__ import annotations

import pytest
from infinity_context_core.domain.aggregation_admission import (
    AggregationAdmissionCandidate,
    AggregationAdmissionPolicy,
    AggregationAdmissionReason,
    AggregationAdmissionSignals,
    AggregationIntent,
)


@pytest.mark.parametrize(
    ("intent", "relevance_sufficient", "distinctive_hits", "unique_hits", "expected"),
    [
        (AggregationIntent.LIST, True, 1, 1, AggregationAdmissionReason.SUFFICIENT_RELEVANCE),
        (
            AggregationIntent.COUNT,
            False,
            1,
            1,
            AggregationAdmissionReason.RELAXED_DISTINCTIVE_SUPPORT,
        ),
        (
            AggregationIntent.LIST,
            False,
            2,
            1,
            AggregationAdmissionReason.RELAXED_DISTINCTIVE_SUPPORT,
        ),
        (
            AggregationIntent.SEQUENCE,
            False,
            1,
            2,
            AggregationAdmissionReason.RELAXED_DISTINCTIVE_SUPPORT,
        ),
    ],
)
def test_admission_table_accepts_sufficient_and_bounded_relaxed_support(
    intent: AggregationIntent,
    relevance_sufficient: bool,
    distinctive_hits: int,
    unique_hits: int,
    expected: AggregationAdmissionReason,
) -> None:
    decision = AggregationAdmissionPolicy().decide(
        _candidate(
            intent=intent,
            relevance_sufficient=relevance_sufficient,
            distinctive_hits=distinctive_hits,
            unique_hits=unique_hits,
        )
    )

    assert decision.admitted
    assert decision.reason is expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"distinctive_hits": 0, "unique_hits": 0}, AggregationAdmissionReason.ZERO_OVERLAP),
        ({"anchor_conflict": True}, AggregationAdmissionReason.ANCHOR_CONFLICT),
        ({"temporal_conflict": True}, AggregationAdmissionReason.TEMPORAL_CONFLICT),
        (
            {"distinctive_hits": 0, "unique_hits": 0, "numeric_corroboration": True},
            AggregationAdmissionReason.NUMERIC_ONLY,
        ),
    ],
)
def test_admission_table_rejects_unsupported_or_conflicting_evidence(
    overrides: dict[str, object],
    expected: AggregationAdmissionReason,
) -> None:
    decision = AggregationAdmissionPolicy().decide(_candidate(**overrides))

    assert not decision.admitted
    assert decision.reason is expected


def test_selection_reserves_each_supported_plan_source_slot_before_capped_fill() -> None:
    candidates = (
        _candidate(
            candidate_id="family-a-first",
            source_family="family-a",
            query_plan_slot="slot-a",
        ),
        _candidate(
            candidate_id="family-a-duplicate",
            source_family="family-a",
            query_plan_slot="slot-a",
        ),
        _candidate(candidate_id="family-b", source_family="family-b", query_plan_slot="slot-a"),
        _candidate(
            candidate_id="family-a-slot-b",
            source_family="family-a",
            query_plan_slot="slot-b",
        ),
    )

    selection = AggregationAdmissionPolicy().select(
        candidates,
        limit=4,
        source_family_cap=2,
    )

    assert selection.reserved_ids == (
        "family-a-first",
        "family-a-slot-b",
        "family-b",
    )
    assert selection.selected_ids == selection.reserved_ids


def test_selection_can_preserve_bounded_slots_beyond_the_ordinary_fill_limit() -> None:
    candidates = tuple(
        _candidate(
            candidate_id=f"candidate-{index}",
            source_family=f"family-{index}",
        )
        for index in range(4)
    )

    selection = AggregationAdmissionPolicy().select(
        candidates,
        limit=2,
        source_family_cap=1,
        reservation_limit=4,
    )

    assert selection.selected_ids == tuple(f"candidate-{index}" for index in range(4))


def test_selection_reserves_query_plan_obligations_before_same_slot_families() -> None:
    candidates = (
        _candidate(candidate_id="slot-a-first", source_family="family-a"),
        _candidate(candidate_id="slot-a-second", source_family="family-b"),
        _candidate(
            candidate_id="slot-b-first",
            source_family="family-c",
            query_plan_slot="slot-b",
        ),
    )

    selection = AggregationAdmissionPolicy().select(
        candidates,
        limit=2,
        source_family_cap=1,
    )

    assert selection.selected_ids == ("slot-a-first", "slot-b-first")


def test_sufficient_candidates_keep_ordinary_rank_order() -> None:
    candidates = (
        _candidate(
            candidate_id="ranked-first",
            source_family="family-a",
            relevance_sufficient=True,
        ),
        _candidate(
            candidate_id="ranked-second",
            source_family="family-a",
            query_plan_slot="another-slot",
            relevance_sufficient=True,
        ),
        _candidate(
            candidate_id="ranked-third",
            source_family="family-b",
            relevance_sufficient=True,
        ),
    )

    selection = AggregationAdmissionPolicy().select(
        candidates,
        limit=2,
        source_family_cap=2,
        reserve_supported_slots=False,
    )

    assert selection.reserved_ids == ()
    assert selection.selected_ids == ("ranked-first", "ranked-second")


def _candidate(
    *,
    candidate_id: str = "candidate",
    intent: AggregationIntent | None = AggregationIntent.LIST,
    relevance_sufficient: bool = False,
    distinctive_hits: int = 1,
    unique_hits: int = 1,
    query_plan_slot: str = "requested-slot",
    source_family: str = "source-family",
    anchor_conflict: bool = False,
    temporal_conflict: bool = False,
    numeric_corroboration: bool = False,
) -> AggregationAdmissionCandidate:
    return AggregationAdmissionCandidate(
        candidate_id=candidate_id,
        signals=AggregationAdmissionSignals(
            intent=intent,
            relevance_sufficient=relevance_sufficient,
            distinctive_hits=distinctive_hits,
            unique_hits=unique_hits,
            query_plan_slot=query_plan_slot,
            source_family=source_family,
            anchor_conflict=anchor_conflict,
            temporal_conflict=temporal_conflict,
            numeric_corroboration=numeric_corroboration,
        ),
    )
