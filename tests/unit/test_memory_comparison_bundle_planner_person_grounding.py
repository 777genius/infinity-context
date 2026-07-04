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
        relation_hits=("career", "path"),
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


def test_evidence_bundle_planner_rejects_person_only_temporal_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:10",),
        primary_signal=True,
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        query_has_entities=True,
        answerability_score=0.9,
    )
    person_only_temporal = _candidate(
        item_id="person-only-temporal",
        query_support_terms=("last", "week"),
        has_temporal_surface=True,
        entity_hits=("caroline",),
        query_has_entities=True,
        answerability_score=0.88,
    )
    relation_grounded_temporal = _candidate(
        item_id="relation-grounded-temporal",
        query_support_terms=("last", "week"),
        has_temporal_surface=True,
        entity_hits=("caroline",),
        relation_hits=("career", "path"),
        query_has_entities=True,
        answerability_score=0.8,
    )

    incomplete = EvidenceBundlePlanner(max_items=2).plan(
        (primary, person_only_temporal),
        case_group="temporal",
        required_roles=("primary", "temporal_support"),
    )
    complete = EvidenceBundlePlanner(max_items=2).plan(
        (primary, person_only_temporal, relation_grounded_temporal),
        case_group="temporal",
        required_roles=("primary", "temporal_support"),
    )

    assert incomplete.satisfied_required_roles == ("primary",)
    assert incomplete.missing_required_roles == ("temporal_support",)
    assert [item.candidate.item_id for item in complete.items] == [
        "primary",
        "relation-grounded-temporal",
    ]
    assert complete.satisfied_required_roles == ("primary", "temporal_support")


def test_event_location_activity_support_must_match_selected_person() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:10",),
        primary_signal=True,
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        query_has_entities=True,
        answerability_score=0.9,
    )
    wrong_event_place = _candidate(
        item_id="wrong-event-place",
        query_support_terms=("charity", "race"),
        relation_hits=("registered", "race"),
        relation_category_hits=("participation_event",),
        entity_hits=("harbor hall",),
        query_has_entities=True,
        answerability_score=0.88,
    )
    grounded_event_place = _candidate(
        item_id="grounded-event-place",
        query_support_terms=("caroline", "charity", "race"),
        relation_hits=("registered", "race"),
        relation_category_hits=("participation_event",),
        entity_hits=("caroline",),
        query_has_entities=True,
        answerability_score=0.76,
    )
    wrong_location = _candidate(
        item_id="wrong-location",
        query_support_terms=("studio", "moved"),
        relation_hits=("moved", "studio"),
        relation_category_hits=("location_transition",),
        entity_hits=("north studio",),
        query_has_entities=True,
        answerability_score=0.88,
    )
    grounded_location = _candidate(
        item_id="grounded-location",
        query_support_terms=("caroline", "studio", "moved"),
        relation_hits=("moved", "studio"),
        relation_category_hits=("location_transition",),
        entity_hits=("caroline",),
        query_has_entities=True,
        answerability_score=0.76,
    )
    wrong_activity = _candidate(
        item_id="wrong-activity",
        query_support_terms=("painting",),
        relation_hits=("painting",),
        relation_category_hits=("activity_profile",),
        entity_hits=("community studio",),
        query_has_entities=True,
        answerability_score=0.88,
    )
    grounded_activity = _candidate(
        item_id="grounded-activity",
        query_support_terms=("caroline", "painting"),
        relation_hits=("painting",),
        relation_category_hits=("activity_profile",),
        entity_hits=("caroline",),
        query_has_entities=True,
        answerability_score=0.76,
    )

    event_plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, wrong_event_place, grounded_event_place),
        case_group="single",
        required_roles=("primary", "event_support"),
    )
    location_plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, wrong_location, grounded_location),
        case_group="single",
        required_roles=("primary", "location_support"),
    )
    activity_plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, wrong_activity, grounded_activity),
        case_group="single",
        required_roles=("primary", "activity_support"),
    )

    assert [item.candidate.item_id for item in event_plan.items] == [
        "primary",
        "grounded-event-place",
    ]
    assert event_plan.satisfied_required_roles == ("primary", "event_support")
    assert event_plan.to_diagnostics()["bundle_quality"]["event_support_count"] == 1
    assert [item.candidate.item_id for item in location_plan.items] == [
        "primary",
        "grounded-location",
    ]
    assert location_plan.satisfied_required_roles == ("primary", "location_support")
    assert location_plan.to_diagnostics()["bundle_quality"][
        "location_support_count"
    ] == 1
    assert [item.candidate.item_id for item in activity_plan.items] == [
        "primary",
        "grounded-activity",
    ]
    assert activity_plan.satisfied_required_roles == ("primary", "activity_support")
    assert activity_plan.to_diagnostics()["bundle_quality"][
        "typed_relation_support_counts"
    ] == {"activity_support": 1}


def test_event_support_with_only_event_anchor_does_not_satisfy_person_request() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:10",),
        primary_signal=True,
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        query_has_entities=True,
        answerability_score=0.9,
    )
    event_only = _candidate(
        item_id="event-only",
        query_support_terms=("charity", "race"),
        relation_hits=("registered", "race"),
        relation_category_hits=("participation_event",),
        entity_hits=("charity race",),
        query_has_entities=True,
        answerability_score=0.88,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, event_only),
        case_group="single",
        required_roles=("primary", "event_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "event-only",
    ]
    assert plan.satisfied_required_roles == ("primary",)
    assert plan.missing_required_roles == ("event_support",)
    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["event_support_count"] == 0
    assert quality["participant_grounding_blocked_required_role_count"] == 1
    assert quality["participant_grounding_blocked_required_role_counts"] == {
        "event_support": 1
    }
    assert quality["participant_grounding_blocked_required_role_samples"] == [
        {
            "id": "event-only",
            "role": "event_support",
            "required_role": "event_support",
            "requested_person_terms": ["caroline"],
            "candidate_person_terms": ["charity race"],
            "relation_hits": ["registered", "race"],
            "relation_category_hits": ["participation_event"],
        }
    ]
    assert "risk:participant_grounding_mismatch" in quality["reason_codes"]


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
    relation_hits: tuple[str, ...] = (),
    relation_category_hits: tuple[str, ...] = (),
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
        relation_hits=relation_hits,
        relation_category_hits=relation_category_hits,
        query_has_entities=query_has_entities,
    )
