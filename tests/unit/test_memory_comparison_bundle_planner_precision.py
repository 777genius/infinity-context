from __future__ import annotations

from infinity_context_server.memory_comparison_bundle_planner import (
    EvidenceBundleCandidate,
    EvidenceBundlePlanner,
)


def test_evidence_bundle_planner_prefers_near_sibling_over_noisy_support_gain() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="refs:D4:10",
        covered_evidence_terms=("plan",),
        primary_signal=True,
        source_refs=("D4:10",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.92,
    )
    broad_far_support = _candidate(
        item_id="broad-far-support",
        retrieval_order=2,
        dedupe_key="refs:D4:30",
        query_support_terms=("origin", "country", "move", "support"),
        source_refs=("D4:30",),
        broad_summary=True,
        answerability_score=0.78,
    )
    near_sibling_support = _candidate(
        item_id="near-sibling-support",
        retrieval_order=3,
        dedupe_key="refs:D4:12",
        query_support_terms=("origin", "country"),
        source_refs=("D4:12",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.84,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, broad_far_support, near_sibling_support),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "near-sibling-support",
    ]
    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["source_proximity_support_count"] == 1
    assert quality["source_proximity_closest_distance"] == 2
    assert quality["broad_summary_count"] == 0


def test_evidence_bundle_quality_does_not_reward_noisy_source_proximity() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="refs:D4:10",
        covered_evidence_terms=("plan",),
        primary_signal=True,
        source_refs=("D4:10",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.92,
    )
    broad_near_support = _candidate(
        item_id="broad-near-support",
        retrieval_order=2,
        dedupe_key="refs:D4:12",
        query_support_terms=("origin", "country"),
        source_refs=("D4:12",),
        broad_summary=True,
        answerability_score=0.78,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, broad_near_support),
        case_group="single",
    )

    quality = plan.to_diagnostics()["bundle_quality"]
    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "broad-near-support",
    ]
    assert quality["source_proximity_support_count"] == 0
    assert quality["source_proximity_closest_distance"] is None
    assert quality["component_scores"]["source_proximity"] == 0.0
    assert "has_source_proximity_support" not in quality["reason_codes"]
    assert "risk:broad_summary" in quality["reason_codes"]


def test_evidence_bundle_planner_does_not_select_noisy_source_proximity() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="refs:D4:10",
        covered_evidence_terms=("plan",),
        primary_signal=True,
        source_refs=("D4:10",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.92,
    )
    broad_near_support = _candidate(
        item_id="broad-near-support",
        retrieval_order=2,
        dedupe_key="refs:D4:11",
        query_support_terms=("origin", "country"),
        source_refs=("D4:11",),
        broad_summary=True,
        answerability_score=0.9,
    )
    clean_far_support = _candidate(
        item_id="clean-far-support",
        retrieval_order=3,
        dedupe_key="refs:D4:30",
        query_support_terms=("origin", "country"),
        source_refs=("D4:30",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.82,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, broad_near_support, clean_far_support),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "clean-far-support",
    ]
    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["broad_summary_count"] == 0
    assert quality["source_proximity_support_count"] == 0


def test_evidence_bundle_planner_prefers_compact_chained_sibling_support() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="refs:D4:10",
        covered_evidence_terms=("plan",),
        primary_signal=True,
        source_refs=("D4:10",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.92,
    )
    first_sibling = _candidate(
        item_id="first-sibling",
        retrieval_order=2,
        dedupe_key="refs:D4:12",
        query_support_terms=("origin", "country"),
        source_refs=("D4:12",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.84,
    )
    broad_far_support = _candidate(
        item_id="broad-far-support",
        retrieval_order=3,
        dedupe_key="refs:D4:25",
        query_support_terms=("origin", "country", "move", "support"),
        source_refs=("D4:25",),
        broad_summary=True,
        answerability_score=0.8,
    )
    chained_sibling = _candidate(
        item_id="chained-sibling",
        retrieval_order=4,
        dedupe_key="refs:D4:15",
        query_support_terms=("origin", "country"),
        source_refs=("D4:15",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.82,
    )

    plan = EvidenceBundlePlanner(max_items=3).plan(
        (primary, first_sibling, broad_far_support, chained_sibling),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "first-sibling",
        "chained-sibling",
    ]
    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["broad_summary_count"] == 0
    assert quality["source_proximity_support_count"] == 1
    assert quality["source_chain_proximity_support_count"] == 1
    assert quality["source_chain_proximity_closest_distance"] == 3
    assert quality["source_chain_proximity_distance_counts"] == {"3": 1}
    assert "has_source_chain_proximity_support" in quality["reason_codes"]


def _candidate(
    *,
    item_id: str,
    rank: int = 1,
    retrieval_order: int = 1,
    covered_expected_terms: tuple[str, ...] = (),
    covered_evidence_terms: tuple[str, ...] = (),
    query_support_terms: tuple[str, ...] = (),
    query_support_score: float = 0.0,
    bundle_strength_score: float = 1.0,
    focused_evidence_score: float = 0.0,
    primary_signal: bool = False,
    dedupe_key: str | None = None,
    source_refs: tuple[str, ...] = (),
    source_type: str = "unknown",
    retrieval_sources: tuple[str, ...] = (),
    direct_speaker_turn: bool = False,
    broad_summary: bool = False,
    answerability_score: float = 0.0,
    source_locality_score: float = 0.0,
) -> EvidenceBundleCandidate:
    return EvidenceBundleCandidate(
        rank=rank,
        retrieval_order=retrieval_order,
        item_id=item_id,
        covered_expected_terms=covered_expected_terms,
        covered_evidence_terms=covered_evidence_terms,
        query_support_terms=query_support_terms,
        query_support_score=query_support_score,
        bundle_strength_score=bundle_strength_score,
        focused_evidence_score=focused_evidence_score,
        primary_signal=primary_signal,
        dedupe_key=dedupe_key or item_id,
        source_refs=source_refs,
        source_type=source_type,
        retrieval_sources=retrieval_sources,
        direct_speaker_turn=direct_speaker_turn,
        broad_summary=broad_summary,
        answerability_score=answerability_score,
        source_locality_score=source_locality_score,
    )
