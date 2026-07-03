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
    assert quality["source_identity_item_count"] == 2
    assert quality["source_identity_support_item_count"] == 1
    assert quality["source_ref_support_item_count"] == 1
    assert quality["component_scores"]["source_refs"] == 0.08
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


def test_evidence_bundle_planner_keeps_precise_support_above_broad_term_gain() -> None:
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
    broad_support = _candidate(
        item_id="broad-support",
        retrieval_order=2,
        dedupe_key="refs:D8:30",
        query_support_terms=("origin", "country", "move", "support"),
        source_refs=("D8:30",),
        broad_summary=True,
        answerability_score=0.86,
        source_locality_score=0.45,
    )
    precise_support = _candidate(
        item_id="precise-support",
        retrieval_order=3,
        dedupe_key="refs:D9:4",
        query_support_terms=("origin", "country"),
        source_refs=("D9:4",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.82,
        source_locality_score=1.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, broad_support, precise_support),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "precise-support",
    ]
    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["broad_summary_count"] == 0
    assert quality["average_measured_answerability_score"] == 0.87


def test_evidence_bundle_planner_keeps_answerable_relation_support_near_top() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="refs:D2:1",
        covered_evidence_terms=("reason",),
        primary_signal=True,
        source_refs=("D2:1",),
        direct_speaker_turn=True,
        focused_evidence_score=1.0,
        answerability_score=0.92,
    )
    lower_precision_causal = _candidate(
        item_id="lower-precision-causal",
        retrieval_order=2,
        dedupe_key="refs:D2:8",
        query_support_terms=("because", "reason", "support", "choice"),
        source_refs=("D2:8",),
        relation_hits=("because", "reason"),
        relation_category_hits=("causal",),
        entity_hits=("morgan",),
        answerability_score=0.62,
        source_locality_score=0.65,
    )
    answerable_causal = _candidate(
        item_id="answerable-causal",
        retrieval_order=3,
        dedupe_key="refs:D2:9",
        query_support_terms=("because", "reason"),
        source_refs=("D2:9",),
        relation_hits=("because", "reason"),
        relation_category_hits=("causal",),
        entity_hits=("morgan",),
        direct_speaker_turn=True,
        focused_evidence_score=1.0,
        answerability_score=0.86,
        source_locality_score=1.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, lower_precision_causal, answerable_causal),
        case_group="single",
        required_roles=("primary", "causal_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "answerable-causal",
    ]
    diagnostics = plan.to_diagnostics()
    assert diagnostics["satisfied_required_roles"] == ["primary", "causal_support"]
    assert diagnostics["bundle_quality"]["causal_support_count"] == 1


def test_evidence_bundle_planner_drops_noisy_partial_source_overlap() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="refs:D4:2",
        covered_evidence_terms=("support",),
        primary_signal=True,
        source_refs=("D4:2",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.92,
    )
    noisy_overlap = _candidate(
        item_id="noisy-overlap",
        retrieval_order=2,
        dedupe_key="refs:D4:2,D4:3",
        query_support_terms=("meeting", "nearby"),
        source_refs=("D4:2", "D4:3"),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.95,
        source_locality_score=0.3,
    )
    clean_far_support = _candidate(
        item_id="clean-far-support",
        retrieval_order=3,
        dedupe_key="refs:D4:20",
        query_support_terms=("meeting", "nearby"),
        source_refs=("D4:20",),
        answerability_score=0.75,
        source_locality_score=0.8,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, noisy_overlap, clean_far_support),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "clean-far-support",
    ]
    diagnostics = plan.to_diagnostics()
    assert diagnostics["dropped_source_ref_overlap_count"] == 1
    assert diagnostics["dropped_source_ref_overlap_keys_sample"] == ["D4:2"]
    assert diagnostics["dropped_noisy_source_overlap_count"] == 1
    assert diagnostics["dropped_noisy_source_overlap_keys_sample"] == ["D4:2"]
    quality = diagnostics["bundle_quality"]
    assert quality["source_proximity_support_count"] == 0
    assert quality["source_proximity_closest_distance"] is None


def test_evidence_bundle_quality_does_not_reward_noisy_source_diversity() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="refs:D4:10",
        covered_evidence_terms=("plan",),
        primary_signal=True,
        source_refs=("D4:10",),
        source_type="raw_turn",
        retrieval_sources=("raw_turns",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.92,
    )
    broad_summary = _candidate(
        item_id="broad-summary",
        retrieval_order=2,
        dedupe_key="refs:D4:30",
        query_support_terms=("origin", "country"),
        source_refs=("D4:30",),
        source_type="summary",
        retrieval_sources=("semantic_chunks",),
        broad_summary=True,
        answerability_score=0.86,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, broad_summary),
        case_group="single",
    )

    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["source_type_diversity"] == 2
    assert quality["retrieval_source_diversity"] == 2
    assert quality["source_type_support_diversity"] == 1
    assert quality["retrieval_source_support_diversity"] == 1
    assert quality["component_scores"]["source_diversity"] == 0.0
    assert "source_type_diverse" not in quality["reason_codes"]
    assert "retrieval_source_diverse" not in quality["reason_codes"]


def test_evidence_bundle_planner_requires_same_session_source_proximity() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="primary",
        covered_evidence_terms=("plan",),
        primary_signal=True,
        source_refs=("locomo:conv-19:session_1:D1:10:turn",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.92,
    )
    cross_session_support = _candidate(
        item_id="cross-session-support",
        retrieval_order=2,
        dedupe_key="cross-session",
        query_support_terms=("origin", "country", "move", "support"),
        source_refs=("locomo:conv-19:session_2:D1:12:turn",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.84,
    )

    cross_session_plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, cross_session_support),
        case_group="single",
    )

    cross_session_quality = cross_session_plan.to_diagnostics()["bundle_quality"]
    assert cross_session_quality["source_proximity_support_count"] == 0
    assert cross_session_quality["source_proximity_closest_distance"] is None
    assert cross_session_quality["component_scores"]["source_proximity"] == 0.0
    assert "has_source_proximity_support" not in cross_session_quality["reason_codes"]

    same_session_support = _candidate(
        item_id="same-session-support",
        retrieval_order=3,
        dedupe_key="same-session",
        query_support_terms=("origin", "country"),
        source_refs=("locomo:conv-19:session_1:D1:12:turn",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.82,
    )

    same_session_plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, cross_session_support, same_session_support),
        case_group="single",
    )

    assert [item.candidate.item_id for item in same_session_plan.items] == [
        "primary",
        "same-session-support",
    ]
    same_session_quality = same_session_plan.to_diagnostics()["bundle_quality"]
    assert same_session_quality["source_proximity_support_count"] == 1
    assert same_session_quality["source_proximity_closest_distance"] == 2
    assert same_session_quality["source_proximity_distance_counts"] == {"2": 1}


def test_evidence_bundle_planner_prefers_compact_source_refs_over_diffuse_support_gain() -> None:
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
    diffuse_support = _candidate(
        item_id="diffuse-support",
        retrieval_order=2,
        dedupe_key="refs:D4:2,D4:11,D4:28",
        query_support_terms=("origin", "country", "move", "support"),
        source_refs=("D4:2", "D4:11", "D4:28"),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.9,
    )
    compact_support = _candidate(
        item_id="compact-support",
        retrieval_order=3,
        dedupe_key="refs:D4:12",
        query_support_terms=("origin", "country"),
        source_refs=("D4:12",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.84,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, diffuse_support, compact_support),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "compact-support",
    ]
    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["diffuse_source_ref_count"] == 0
    assert "risk:diffuse_source_refs" not in quality["reason_codes"]


def test_evidence_bundle_quality_flags_diffuse_source_refs() -> None:
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
    diffuse_support = _candidate(
        item_id="diffuse-support",
        retrieval_order=2,
        dedupe_key="refs:D4:2,D4:11,D4:28",
        query_support_terms=("origin", "country"),
        source_refs=("D4:2", "D4:11", "D4:28"),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.9,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, diffuse_support),
        case_group="single",
    )

    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["diffuse_source_ref_count"] == 1
    assert "risk:diffuse_source_refs" in quality["reason_codes"]


def test_evidence_bundle_quality_preserves_mixed_session_and_plain_refs() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="refs:session_1:D1:10",
        covered_evidence_terms=("plan",),
        primary_signal=True,
        source_refs=("locomo:conv-19:session_1:D1:10:turn",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.92,
    )
    mixed_support = _candidate(
        item_id="mixed-support",
        retrieval_order=2,
        dedupe_key="refs:D2:50",
        query_support_terms=("origin", "country"),
        source_refs=(
            "locomo:conv-19:session_1:D1:12:turn",
            "legacy:D2:50",
        ),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.9,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, mixed_support),
        case_group="single",
    )

    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["diffuse_source_ref_count"] == 1
    assert "risk:diffuse_source_refs" in quality["reason_codes"]


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


def test_evidence_bundle_quality_does_not_chain_through_noisy_sibling() -> None:
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
    broad_bridge = _candidate(
        item_id="broad-bridge",
        retrieval_order=2,
        dedupe_key="refs:D4:20",
        covered_evidence_terms=("context",),
        query_support_terms=("origin", "country"),
        source_refs=("D4:20",),
        broad_summary=True,
        answerability_score=0.88,
    )
    clean_near_broad = _candidate(
        item_id="clean-near-broad",
        retrieval_order=3,
        dedupe_key="refs:D4:22",
        query_support_terms=("move", "support"),
        source_refs=("D4:22",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.84,
    )

    plan = EvidenceBundlePlanner(max_items=3).plan(
        (primary, broad_bridge, clean_near_broad),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "broad-bridge",
        "clean-near-broad",
    ]
    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["broad_summary_count"] == 1
    assert quality["source_proximity_support_count"] == 0
    assert quality["source_chain_proximity_support_count"] == 0
    assert quality["source_chain_proximity_distance_counts"] == {}
    assert "has_source_chain_proximity_support" not in quality["reason_codes"]


def test_evidence_bundle_quality_credits_grounded_contrast_source_refs() -> None:
    primary = _candidate(
        item_id="current",
        retrieval_order=1,
        dedupe_key="refs:D5:8",
        covered_evidence_terms=("team",),
        primary_signal=True,
        source_refs=("D5:8",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.92,
        source_locality_score=0.9,
    )
    stale_contrast = _candidate(
        item_id="stale-contrast",
        retrieval_order=2,
        dedupe_key="refs:D5:3",
        query_support_terms=("solo", "used"),
        source_refs=("D5:3",),
        conflict_or_stale=True,
        contrast_surface=True,
        stale_surface=True,
        answerability_score=0.86,
        source_locality_score=0.9,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, stale_contrast),
        case_group="single",
    )

    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["source_ref_item_count"] == 2
    assert quality["source_ref_support_item_count"] == 2
    assert quality["source_identity_support_item_count"] == 2
    assert quality["component_scores"]["source_refs"] == 0.16
    assert "has_source_refs" in quality["reason_codes"]
    assert "risk:conflict_or_stale" in quality["reason_codes"]


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
    relation_hits: tuple[str, ...] = (),
    relation_category_hits: tuple[str, ...] = (),
    entity_hits: tuple[str, ...] = (),
    direct_speaker_turn: bool = False,
    broad_summary: bool = False,
    conflict_or_stale: bool = False,
    contrast_surface: bool = False,
    stale_surface: bool = False,
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
        relation_hits=relation_hits,
        relation_category_hits=relation_category_hits,
        entity_hits=entity_hits,
        direct_speaker_turn=direct_speaker_turn,
        broad_summary=broad_summary,
        conflict_or_stale=conflict_or_stale,
        contrast_surface=contrast_surface,
        stale_surface=stale_surface,
        answerability_score=answerability_score,
        source_locality_score=source_locality_score,
    )
