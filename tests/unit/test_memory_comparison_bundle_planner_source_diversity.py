from __future__ import annotations

from infinity_context_server.memory_comparison_bundle_planner import (
    EvidenceBundleCandidate,
    EvidenceBundlePlanner,
)


def test_evidence_bundle_planner_prefers_distinct_source_over_redundant_window() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("venue",),
        primary_signal=True,
        source_refs=("D4:10",),
    )
    local_support = _candidate(
        item_id="local-support",
        retrieval_order=2,
        dedupe_key="refs:D4:11",
        query_support_terms=("venue",),
        source_refs=("D4:11",),
        answerability_score=0.88,
    )
    redundant_local = _candidate(
        item_id="redundant-local",
        retrieval_order=3,
        dedupe_key="refs:D4:12",
        query_support_terms=("venue",),
        source_refs=("D4:12",),
        answerability_score=0.94,
        bundle_strength_score=10.0,
    )
    distinct_source = _candidate(
        item_id="distinct-source",
        retrieval_order=4,
        dedupe_key="refs:D8:5",
        query_support_terms=("venue",),
        source_refs=("D8:5",),
        answerability_score=0.8,
    )

    plan = EvidenceBundlePlanner(max_items=3).plan(
        (primary, local_support, redundant_local, distinct_source),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "local-support",
        "distinct-source",
    ]
    diagnostics = plan.to_diagnostics()
    assert diagnostics["dropped_diversity_count"] == 1
    assert diagnostics["bundle_quality"]["source_proximity_support_count"] == 1


def test_evidence_bundle_planner_drops_primary_window_filler_for_distinct_source() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("venue",),
        query_support_terms=("venue",),
        primary_signal=True,
        source_refs=("D4:10",),
    )
    redundant_local = _candidate(
        item_id="redundant-local",
        retrieval_order=2,
        dedupe_key="refs:D4:11",
        query_support_terms=("venue",),
        source_refs=("D4:11",),
        answerability_score=0.94,
        bundle_strength_score=10.0,
    )
    distinct_source = _candidate(
        item_id="distinct-source",
        retrieval_order=3,
        dedupe_key="refs:D8:5",
        query_support_terms=("venue",),
        source_refs=("D8:5",),
        answerability_score=0.8,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, redundant_local, distinct_source),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "distinct-source",
    ]
    diagnostics = plan.to_diagnostics()
    assert diagnostics["dropped_diversity_count"] == 1
    assert diagnostics["bundle_quality"]["source_identity_support_item_count"] == 2


def test_evidence_bundle_planner_prefers_distinct_source_for_equivalent_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("venue",),
        primary_signal=True,
        source_refs=("D4:10",),
    )
    redundant_local = _candidate(
        item_id="redundant-local",
        retrieval_order=2,
        dedupe_key="refs:D4:11",
        query_support_terms=("venue", "reservation"),
        source_refs=("D4:11",),
        focused_evidence_score=0.0,
        direct_speaker_turn=False,
        answerability_score=0.94,
        bundle_strength_score=10.0,
    )
    distinct_source = _candidate(
        item_id="distinct-source",
        retrieval_order=3,
        dedupe_key="refs:D8:5",
        query_support_terms=("venue", "reservation"),
        source_refs=("D8:5",),
        answerability_score=0.8,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, redundant_local, distinct_source),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "distinct-source",
    ]
    diagnostics = plan.to_diagnostics()
    assert diagnostics["dropped_diversity_count"] == 1
    assert diagnostics["bundle_quality"]["source_identity_support_item_count"] == 2


def test_evidence_bundle_planner_matches_qualified_and_unqualified_source_windows() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("venue",),
        primary_signal=True,
        source_refs=("D4:10",),
    )
    qualified_same_window = _candidate(
        item_id="qualified-same-window",
        retrieval_order=2,
        dedupe_key="source_session_turn_refs:session_1:D4:11",
        query_support_terms=("venue",),
        source_refs=("locomo:conversation:session_1:D4:11:turn",),
        focused_evidence_score=0.0,
        direct_speaker_turn=False,
        answerability_score=0.94,
        bundle_strength_score=10.0,
    )
    distinct_source = _candidate(
        item_id="distinct-source",
        retrieval_order=3,
        dedupe_key="refs:D8:5",
        query_support_terms=("venue",),
        source_refs=("D8:5",),
        answerability_score=0.8,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, qualified_same_window, distinct_source),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "distinct-source",
    ]
    diagnostics = plan.to_diagnostics()
    assert diagnostics["dropped_diversity_count"] == 1
    assert diagnostics["bundle_quality"]["source_proximity_closest_distance"] is None


def test_evidence_bundle_planner_reports_mixed_source_window_proximity() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("venue",),
        primary_signal=True,
        source_refs=("D4:10",),
    )
    qualified_same_window = _candidate(
        item_id="qualified-same-window",
        retrieval_order=2,
        dedupe_key="source_session_turn_refs:session_1:D4:11",
        query_support_terms=("venue",),
        source_refs=("locomo:conversation:session_1:D4:11:turn",),
        answerability_score=0.94,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, qualified_same_window),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "qualified-same-window",
    ]
    assert plan.to_diagnostics()["bundle_quality"][
        "source_proximity_closest_distance"
    ] == 1


def test_evidence_bundle_planner_keeps_different_qualified_sessions_distinct() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("venue",),
        primary_signal=True,
        source_refs=("locomo:conversation:session_1:D4:10:turn",),
    )
    other_session = _candidate(
        item_id="other-session",
        retrieval_order=2,
        dedupe_key="source_session_turn_refs:session_2:D4:11",
        query_support_terms=("venue",),
        source_refs=("locomo:conversation:session_2:D4:11:turn",),
        focused_evidence_score=0.0,
        direct_speaker_turn=False,
        answerability_score=0.94,
        bundle_strength_score=10.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, other_session),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "other-session",
    ]
    diagnostics = plan.to_diagnostics()
    assert diagnostics["dropped_diversity_count"] == 0
    assert diagnostics["bundle_quality"]["source_proximity_closest_distance"] is None


def test_evidence_bundle_planner_keeps_local_window_with_unique_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("venue",),
        primary_signal=True,
        source_refs=("D4:10",),
    )
    local_support = _candidate(
        item_id="local-support",
        retrieval_order=2,
        dedupe_key="refs:D4:11",
        query_support_terms=("venue", "reservation", "deposit"),
        source_refs=("D4:11",),
        answerability_score=0.94,
        bundle_strength_score=10.0,
    )
    distinct_source = _candidate(
        item_id="distinct-source",
        retrieval_order=3,
        dedupe_key="refs:D8:5",
        query_support_terms=("venue", "reservation"),
        source_refs=("D8:5",),
        answerability_score=0.8,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, local_support, distinct_source),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "local-support",
    ]
    assert plan.to_diagnostics()["dropped_diversity_count"] == 1


def test_evidence_bundle_planner_keeps_required_role_over_redundant_window() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("decision",),
        primary_signal=True,
        source_refs=("D4:10",),
    )
    local_support = _candidate(
        item_id="local-support",
        retrieval_order=2,
        dedupe_key="refs:D4:11",
        query_support_terms=("decision",),
        source_refs=("D4:11",),
        answerability_score=0.88,
    )
    redundant_local = _candidate(
        item_id="redundant-local",
        retrieval_order=3,
        dedupe_key="refs:D4:12",
        query_support_terms=("decision",),
        source_refs=("D4:12",),
        answerability_score=0.94,
        bundle_strength_score=10.0,
    )
    role_evidence = _candidate(
        item_id="role-evidence",
        retrieval_order=4,
        dedupe_key="refs:D8:5",
        query_support_terms=("decision",),
        source_refs=("D8:5",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        answerability_score=0.8,
    )

    plan = EvidenceBundlePlanner(max_items=3).plan(
        (primary, local_support, redundant_local, role_evidence),
        case_group="single",
        required_roles=("primary", "entity_disambiguation"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "local-support",
        "role-evidence",
    ]
    assert plan.satisfied_required_roles == ("primary", "entity_disambiguation")
    assert plan.repaired_required_roles == ()


def _candidate(
    *,
    item_id: str,
    retrieval_order: int = 1,
    covered_evidence_terms: tuple[str, ...] = (),
    query_support_terms: tuple[str, ...] = (),
    primary_signal: bool = False,
    dedupe_key: str | None = None,
    source_refs: tuple[str, ...] = (),
    relation_hits: tuple[str, ...] = (),
    entity_hits: tuple[str, ...] = (),
    speaker_hits: tuple[str, ...] = (),
    answerability_score: float = 0.0,
    bundle_strength_score: float = 1.0,
    focused_evidence_score: float = 1.0,
    direct_speaker_turn: bool = True,
) -> EvidenceBundleCandidate:
    return EvidenceBundleCandidate(
        rank=1,
        retrieval_order=retrieval_order,
        item_id=item_id,
        covered_expected_terms=(),
        covered_evidence_terms=covered_evidence_terms,
        query_support_terms=query_support_terms,
        query_support_score=0.0,
        bundle_strength_score=bundle_strength_score,
        focused_evidence_score=focused_evidence_score,
        primary_signal=primary_signal,
        dedupe_key=dedupe_key or item_id,
        source_refs=source_refs,
        direct_speaker_turn=direct_speaker_turn,
        relation_hits=relation_hits,
        entity_hits=entity_hits,
        speaker_hits=speaker_hits,
        answerability_score=answerability_score,
    )
