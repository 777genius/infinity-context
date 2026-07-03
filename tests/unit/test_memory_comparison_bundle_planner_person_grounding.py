from __future__ import annotations

from infinity_context_server.memory_comparison_bundle_planner import (
    EvidenceBundleCandidate,
    EvidenceBundlePlanner,
)


def test_evidence_bundle_planner_prefers_person_grounded_temporal_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:10",),
        primary_signal=True,
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        query_has_entities=True,
        answerability_score=0.9,
    )
    unrelated_temporal = _candidate(
        item_id="unrelated-temporal",
        query_support_terms=("last", "week"),
        has_temporal_surface=True,
        entity_hits=("morgan",),
        query_has_entities=True,
        answerability_score=0.88,
    )
    person_grounded_temporal = _candidate(
        item_id="person-grounded-temporal",
        query_support_terms=("last", "week"),
        has_temporal_surface=True,
        entity_hits=("caroline",),
        query_has_entities=True,
        answerability_score=0.8,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, unrelated_temporal, person_grounded_temporal),
        case_group="temporal",
        required_roles=("primary", "temporal_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "person-grounded-temporal",
    ]
    assert plan.satisfied_required_roles == ("primary", "temporal_support")


def _candidate(
    *,
    item_id: str,
    covered_evidence_terms: tuple[str, ...] = (),
    query_support_terms: tuple[str, ...] = (),
    primary_signal: bool = False,
    has_temporal_surface: bool = False,
    answerability_score: float = 0.0,
    entity_hits: tuple[str, ...] = (),
    speaker_hits: tuple[str, ...] = (),
    query_has_entities: bool = False,
) -> EvidenceBundleCandidate:
    return EvidenceBundleCandidate(
        rank=1,
        retrieval_order=1,
        item_id=item_id,
        covered_expected_terms=(),
        covered_evidence_terms=covered_evidence_terms,
        query_support_terms=query_support_terms,
        query_support_score=0.0,
        bundle_strength_score=1.0,
        focused_evidence_score=0.0,
        primary_signal=primary_signal,
        dedupe_key=item_id,
        has_temporal_surface=has_temporal_surface,
        answerability_score=answerability_score,
        entity_hits=entity_hits,
        speaker_hits=speaker_hits,
        query_has_entities=query_has_entities,
    )
