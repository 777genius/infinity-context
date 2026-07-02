from __future__ import annotations

from infinity_context_server.memory_comparison_bundle_planner import (
    EvidenceBundleCandidate,
    EvidenceBundlePlanner,
)


def test_evidence_bundle_planner_prefers_focused_direct_primary() -> None:
    broad = _candidate(
        item_id="broad-session",
        retrieval_order=1,
        bundle_strength_score=10.0,
        primary_signal=True,
        covered_expected_terms=("adoption agencies",),
        broad_summary=True,
    )
    focused = _candidate(
        item_id="focused-turn",
        retrieval_order=2,
        bundle_strength_score=6.0,
        focused_evidence_score=1.0,
        primary_signal=True,
        covered_expected_terms=("adoption agencies",),
        direct_speaker_turn=True,
        source_type="raw_turn",
    )

    plan = EvidenceBundlePlanner().plan((broad, focused), case_group="multi-hop")

    assert [item.candidate.item_id for item in plan.items] == [
        "focused-turn",
        "broad-session",
    ]
    assert plan.items[0].role == "primary"
    assert "focused_turn" in plan.primary_selection_reason_codes
    assert "direct_speaker_turn" in plan.primary_selection_reason_codes
    assert plan.to_diagnostics()["schema_version"] == "evidence_bundle_planner.v1"


def test_evidence_bundle_planner_promotes_answerable_direct_turn_to_primary() -> None:
    broad = _candidate(
        item_id="broad-summary",
        retrieval_order=1,
        bundle_strength_score=8.0,
        primary_signal=True,
        query_support_terms=("caroline", "support"),
        broad_summary=True,
        source_locality_score=0.35,
        answerability_score=0.58,
    )
    precise = _candidate(
        item_id="precise-turn",
        retrieval_order=2,
        primary_signal=False,
        query_support_terms=("support",),
        direct_speaker_turn=True,
        source_type="raw_turn",
        source_locality_score=1.0,
        answerability_score=0.88,
        relation_hits=("support", "family"),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
    )

    plan = EvidenceBundlePlanner().plan((broad, precise), case_group="single")

    assert [item.candidate.item_id for item in plan.items] == [
        "precise-turn",
        "broad-summary",
    ]
    assert plan.items[0].role == "primary"
    assert "answerable_direct_primary" in plan.primary_selection_reason_codes
    assert "direct_speaker_turn" in plan.primary_selection_reason_codes


def test_evidence_bundle_planner_dedupes_and_caps_source_type_diversity() -> None:
    duplicate_weaker = _candidate(
        item_id="duplicate-summary",
        dedupe_key="refs:D1:1",
        source_type="chunk",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
    )
    duplicate_stronger = _candidate(
        item_id="duplicate-turn",
        dedupe_key="refs:D1:1",
        source_type="raw_turn",
        direct_speaker_turn=True,
        focused_evidence_score=1.0,
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
    )
    chunk_one = _candidate(
        item_id="chunk-one",
        dedupe_key="refs:D1:2",
        source_type="chunk",
        query_support_terms=("morgan", "checklist"),
    )
    chunk_two = _candidate(
        item_id="chunk-two",
        dedupe_key="refs:D1:3",
        source_type="chunk",
        query_support_terms=("morgan", "checklist"),
    )
    chunk_three = _candidate(
        item_id="chunk-three",
        dedupe_key="refs:D1:4",
        source_type="chunk",
        query_support_terms=("morgan", "checklist"),
    )
    raw_support = _candidate(
        item_id="raw-support",
        dedupe_key="refs:D1:5",
        source_type="raw_turn",
        query_support_terms=("morgan", "checklist"),
    )

    plan = EvidenceBundlePlanner(max_items_per_source_type=2).plan(
        (
            duplicate_weaker,
            duplicate_stronger,
            chunk_one,
            chunk_two,
            chunk_three,
            raw_support,
        ),
        case_group="multi-hop",
    )

    selected_ids = [item.candidate.item_id for item in plan.items]
    assert selected_ids[0] == "duplicate-turn"
    assert "duplicate-summary" not in selected_ids
    assert plan.deduplicated_item_count == 1
    assert plan.dropped_diversity_count == 1
    assert plan.source_type_counts["chunk"] == 2
    assert plan.source_type_counts["raw_turn"] == 2


def test_evidence_bundle_planner_drops_redundant_source_ref_overlap() -> None:
    primary = _candidate(
        item_id="primary-turn",
        dedupe_key="raw:D1:1",
        source_refs=("D1:1",),
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        direct_speaker_turn=True,
        focused_evidence_score=1.0,
    )
    duplicate_context = _candidate(
        item_id="duplicate-context",
        dedupe_key="chunk:D1:1",
        source_refs=("D1:1", "conv-1"),
        source_type="chunk",
        answerability_score=0.7,
    )
    unique_support = _candidate(
        item_id="unique-support",
        dedupe_key="raw:D1:2",
        source_refs=("D1:2",),
        source_type="raw_turn",
        query_support_terms=("morgan", "checklist"),
    )

    plan = EvidenceBundlePlanner().plan(
        (primary, duplicate_context, unique_support),
        case_group="single",
    )

    selected_ids = [item.candidate.item_id for item in plan.items]
    diagnostics = plan.to_diagnostics()

    assert selected_ids == ["primary-turn", "unique-support"]
    assert "duplicate-context" not in selected_ids
    assert plan.dropped_diversity_count == 1
    assert diagnostics["dropped_source_ref_overlap_count"] == 1
    assert diagnostics["selected_dedupe_keys"] == ["raw:D1:1", "raw:D1:2"]


def test_evidence_bundle_planner_caps_repeated_retrieval_sources() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("agency",),
        primary_signal=True,
        source_type="raw_turn",
        retrieval_sources=("raw_turns",),
    )
    semantic_one = _candidate(
        item_id="semantic-one",
        dedupe_key="refs:D1:1",
        source_type="chunk",
        retrieval_sources=("semantic_chunks",),
        query_support_terms=("caroline", "agency"),
    )
    semantic_two = _candidate(
        item_id="semantic-two",
        dedupe_key="refs:D1:2",
        source_type="chunk",
        retrieval_sources=("semantic_chunks",),
        query_support_terms=("caroline", "agency"),
    )
    semantic_three = _candidate(
        item_id="semantic-three",
        dedupe_key="refs:D1:3",
        source_type="chunk",
        retrieval_sources=("semantic_chunks",),
        query_support_terms=("caroline", "agency"),
    )
    keyword = _candidate(
        item_id="keyword",
        dedupe_key="refs:D1:4",
        source_type="chunk",
        retrieval_sources=("keyword_chunks",),
        query_support_terms=("caroline", "agency"),
    )

    plan = EvidenceBundlePlanner(
        max_items_per_source_type=10,
        max_items_per_retrieval_source=2,
    ).plan(
        (primary, semantic_one, semantic_two, semantic_three, keyword),
        case_group="multi-hop",
    )

    selected_ids = [item.candidate.item_id for item in plan.items]
    assert "semantic-three" not in selected_ids
    assert "keyword" in selected_ids
    assert plan.dropped_diversity_count == 1
    assert plan.dropped_source_type_diversity_count == 0
    assert plan.dropped_retrieval_source_diversity_count == 1
    diagnostics = plan.to_diagnostics()
    assert diagnostics["retrieval_source_counts"]["semantic_chunks"] == 2
    assert diagnostics["retrieval_source_counts"]["keyword_chunks"] == 1


def test_evidence_bundle_planner_exempts_typed_support_roles_from_drop_counts() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("photo",),
        primary_signal=True,
        source_type="raw_turn",
        retrieval_sources=("semantic_chunks",),
        answerability_score=0.9,
    )
    generic_one = _candidate(
        item_id="generic-one",
        dedupe_key="refs:D1:1",
        source_type="chunk",
        retrieval_sources=("semantic_chunks",),
        query_support_terms=("photo", "album"),
        answerability_score=0.8,
    )
    visual_support = _candidate(
        item_id="visual-support",
        dedupe_key="refs:D1:3",
        source_type="chunk",
        retrieval_sources=("semantic_chunks",),
        query_support_terms=("photo", "album"),
        relation_categories=("visual",),
        relation_category_hits=("visual",),
        has_visual_evidence=True,
        source_locality_score=0.9,
        answerability_score=0.82,
    )

    plan = EvidenceBundlePlanner(
        max_items=1,
        max_items_per_source_type=10,
        max_items_per_retrieval_source=1,
    ).plan(
        (primary, generic_one, visual_support),
        case_group="single",
        required_roles=("primary", "visual_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == ["primary"]
    assert plan.dropped_diversity_count == 2
    assert plan.dropped_retrieval_source_diversity_count == 1
    assert plan.satisfied_required_roles == ("primary",)
    assert plan.missing_required_roles == ("visual_support",)


def test_evidence_bundle_planner_assigns_specialized_support_roles() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("blue notebook",),
        primary_signal=True,
    )
    temporal = _candidate(
        item_id="temporal",
        dedupe_key="refs:D2:1",
        has_temporal_surface=True,
        query_support_terms=("after", "studio"),
    )
    typed_temporal = _candidate(
        item_id="typed-temporal",
        dedupe_key="refs:D2:4",
        time_intent_kind="duration",
        has_duration_surface=True,
        query_support_terms=("known", "years"),
        answerability_reason_codes=("duration_temporal_evidence",),
    )
    contrast = _candidate(
        item_id="contrast",
        dedupe_key="refs:D2:2",
        conflict_or_stale=True,
        query_support_terms=("studio", "desk"),
    )
    entity = _candidate(
        item_id="entity",
        dedupe_key="refs:D2:3",
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        query_support_terms=("caroline", "agency"),
    )

    plan = EvidenceBundlePlanner().plan(
        (primary, temporal, typed_temporal, contrast, entity),
        case_group="multi-hop",
    )

    roles = {item.candidate.item_id: item.role for item in plan.items}
    assert roles == {
        "primary": "primary",
        "temporal": "temporal_support",
        "typed-temporal": "temporal_support",
        "entity": "entity_disambiguation",
        "contrast": "contrast",
    }
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"]["temporal_support"] == 2
    assert diagnostics["role_counts"]["entity_disambiguation"] == 1
    assert diagnostics["role_counts"]["contrast"] == 1
    typed_item = next(
        item for item in plan.items if item.candidate.item_id == "typed-temporal"
    )
    assert "duration_surface" in typed_item.reason_codes
    assert typed_item.to_payload()["time_intent_kind"] == "duration"
    assert typed_item.to_payload()["has_duration_surface"] is True


def test_evidence_bundle_planner_tracks_location_support_role() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("Canada",),
        primary_signal=True,
        relation_categories=("location_transition",),
        relation_category_hits=("location_transition",),
        relation_hits=("move", "home", "country"),
        source_refs=("D1:4",),
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    generic_move = _candidate(
        item_id="generic-move",
        dedupe_key="refs:D1:3",
        relation_categories=("location_transition",),
        relation_hits=("move",),
        query_support_terms=("caroline", "move"),
    )
    location_support = _candidate(
        item_id="location-support",
        dedupe_key="refs:D1:5",
        relation_categories=("location_transition",),
        relation_category_hits=("location_transition",),
        relation_hits=("origin", "country"),
        query_support_terms=("origin", "country"),
        source_refs=("D1:5",),
        answerability_score=0.82,
        source_locality_score=0.9,
    )

    plan = EvidenceBundlePlanner().plan(
        (primary, generic_move, location_support),
        case_group="single",
        required_roles=("primary", "location_support"),
    )

    roles = {item.candidate.item_id: item.role for item in plan.items}
    diagnostics = plan.to_diagnostics()
    support_payload = next(
        item.to_payload()
        for item in plan.items
        if item.candidate.item_id == "location-support"
    )

    assert roles["primary"] == "primary"
    assert roles["location-support"] == "location_support"
    assert plan.satisfied_required_roles == ("primary", "location_support")
    assert diagnostics["bundle_quality"]["location_support_count"] == 1
    assert diagnostics["bundle_quality"]["location_relation_category_hit_count"] == 2
    assert "has_location_support_evidence" in diagnostics["bundle_quality"][
        "reason_codes"
    ]
    assert "location_relation_category_hits" in support_payload[
        "planner_reason_codes"
    ]
    assert support_payload["relation_category_hits"] == ["location_transition"]


def test_evidence_bundle_planner_requires_grounded_location_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("Canada",),
        primary_signal=True,
        source_refs=("D1:4",),
        direct_speaker_turn=True,
        focused_evidence_score=1.0,
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    generic_support = _candidate(
        item_id="generic-support",
        dedupe_key="refs:D1:3",
        query_support_terms=("caroline", "move"),
        bundle_strength_score=9.0,
    )
    direct_speaker_distractor = _candidate(
        item_id="direct-speaker-distractor",
        dedupe_key="refs:D2:2",
        query_support_terms=("move", "country"),
        relation_hits=("move", "country", "from"),
        relation_category_hits=("location_transition",),
        query_has_entities=True,
        direct_speaker_turn=True,
        source_refs=("D2:2",),
        source_locality_score=0.95,
        answerability_score=0.88,
        bundle_strength_score=10.0,
    )
    location_support = _candidate(
        item_id="location-support",
        dedupe_key="refs:D2:3",
        query_support_terms=("caroline", "move", "country"),
        relation_hits=("move", "country", "from"),
        relation_category_hits=("location_transition",),
        entity_hits=("caroline",),
        query_has_entities=True,
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.74,
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, generic_support, direct_speaker_distractor, location_support),
        case_group="single",
        required_roles=("primary", "location_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "location-support",
    ]
    support_item = plan.items[1]
    assert support_item.role == "location_support"
    assert "location_support" in support_item.reason_codes
    assert "location_relation_category_hits" in support_item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "location_support": 1}
    assert diagnostics["satisfied_required_roles"] == [
        "primary",
        "location_support",
    ]
    assert diagnostics["bundle_quality"]["location_support_count"] == 1
    assert "has_location_support_evidence" in diagnostics["bundle_quality"][
        "reason_codes"
    ]


def test_evidence_bundle_planner_rejects_broad_location_support_role() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("Canada",),
        primary_signal=True,
        source_refs=("D1:4",),
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    broad_location = _candidate(
        item_id="broad-location",
        dedupe_key="refs:summary",
        broad_summary=True,
        relation_categories=("location_transition",),
        relation_category_hits=("location_transition",),
        relation_hits=("origin", "country"),
        query_support_terms=("origin", "country"),
        source_refs=("D1:1", "D1:9"),
        answerability_score=0.7,
        source_locality_score=0.45,
    )

    plan = EvidenceBundlePlanner().plan(
        (primary, broad_location),
        case_group="single",
        required_roles=("primary", "location_support"),
    )

    diagnostics = plan.to_diagnostics()

    assert plan.satisfied_required_roles == ("primary",)
    assert plan.missing_required_roles == ("location_support",)
    assert diagnostics["bundle_quality"]["location_support_count"] == 0
    assert "has_location_support_evidence" not in diagnostics["bundle_quality"][
        "reason_codes"
    ]


def test_evidence_bundle_planner_requires_matching_temporal_evidence_type() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("current friends",),
        primary_signal=True,
    )
    current_only = _candidate(
        item_id="current-only",
        dedupe_key="refs:D2:1",
        time_intent_kind="duration",
        currentness_surface=True,
        query_support_terms=("current", "friends"),
    )
    duration = _candidate(
        item_id="duration",
        dedupe_key="refs:D2:2",
        time_intent_kind="duration",
        has_duration_surface=True,
        query_support_terms=("4", "years"),
        source_locality_score=0.9,
        answerability_score=0.8,
    )

    incomplete = EvidenceBundlePlanner().plan(
        (primary, current_only),
        case_group="temporal",
        required_roles=("primary", "temporal_support"),
    )
    complete = EvidenceBundlePlanner().plan(
        (primary, current_only, duration),
        case_group="temporal",
        required_roles=("primary", "temporal_support"),
    )

    assert incomplete.role_counts["temporal_support"] == 1
    assert incomplete.satisfied_required_roles == ("primary",)
    assert incomplete.missing_required_roles == ("temporal_support",)
    assert incomplete.role_requirement_complete is False
    assert complete.satisfied_required_roles == ("primary", "temporal_support")
    assert complete.missing_required_roles == ()


def test_evidence_bundle_planner_rejects_weak_temporal_role_completion() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("current friends",),
        primary_signal=True,
    )
    broad_duration = _candidate(
        item_id="broad-duration-summary",
        dedupe_key="refs:D2:1|D2:2|D2:3",
        time_intent_kind="duration",
        has_duration_surface=True,
        query_support_terms=("4", "years"),
        broad_summary=True,
        source_locality_score=0.9,
        answerability_score=0.86,
    )
    grounded_duration = _candidate(
        item_id="grounded-duration-turn",
        dedupe_key="refs:D2:2",
        time_intent_kind="duration",
        has_duration_surface=True,
        query_support_terms=("4", "years"),
        direct_speaker_turn=True,
        source_locality_score=1.0,
        answerability_score=0.9,
    )

    weak = EvidenceBundlePlanner().plan(
        (primary, broad_duration),
        case_group="temporal",
        required_roles=("primary", "temporal_support"),
    )
    grounded = EvidenceBundlePlanner().plan(
        (primary, broad_duration, grounded_duration),
        case_group="temporal",
        required_roles=("primary", "temporal_support"),
    )

    assert weak.satisfied_required_roles == ("primary",)
    assert weak.missing_required_roles == ("temporal_support",)
    assert grounded.satisfied_required_roles == ("primary", "temporal_support")
    assert grounded.missing_required_roles == ()


def test_evidence_bundle_planner_repairs_missing_required_role_selection() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("agency",),
        primary_signal=True,
        bundle_strength_score=8.0,
    )
    optional_bridge = _candidate(
        item_id="optional-bridge",
        dedupe_key="refs:D2:3",
        query_support_terms=("caroline", "agency", "support"),
        relation_hits=("agency", "support"),
        entity_hits=("caroline",),
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.82,
        bundle_strength_score=7.0,
        bridge_query_hit=True,
    )
    required_temporal = _candidate(
        item_id="required-temporal",
        dedupe_key="refs:D3:1",
        time_intent_kind="duration",
        has_duration_surface=True,
        query_support_terms=("known", "years"),
        source_refs=("D3:1",),
        source_locality_score=0.9,
        answerability_score=0.8,
        bundle_strength_score=1.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, optional_bridge, required_temporal),
        case_group="multi-hop",
        required_roles=("primary", "temporal_support"),
    )

    selected_ids = [item.candidate.item_id for item in plan.items]
    diagnostics = plan.to_diagnostics()

    assert selected_ids == ["primary", "required-temporal"]
    assert "optional-bridge" not in selected_ids
    assert plan.satisfied_required_roles == ("primary", "temporal_support")
    assert plan.missing_required_roles == ()
    assert plan.repaired_required_roles == ("temporal_support",)
    assert diagnostics["required_role_repair_count"] == 1
    assert diagnostics["repaired_required_roles"] == ["temporal_support"]
    assert diagnostics["role_requirement_complete"] is True


def test_evidence_bundle_planner_repair_prefers_nearby_required_support() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="refs:D4:10",
        covered_expected_terms=("move",),
        primary_signal=True,
        source_refs=("D4:10",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.9,
    )
    optional_support = _candidate(
        item_id="optional-location-support",
        retrieval_order=2,
        query_support_terms=("optional", "location"),
        relation_category_hits=("location_transition",),
        source_refs=("D4:9",),
        source_locality_score=0.9,
        answerability_score=0.9,
        bundle_strength_score=1.0,
    )
    far_temporal = _candidate(
        item_id="far-temporal",
        retrieval_order=3,
        dedupe_key="refs:D4:30",
        time_intent_kind="duration",
        has_duration_surface=True,
        query_support_terms=("years",),
        source_refs=("D4:30",),
        source_locality_score=0.9,
        answerability_score=0.82,
    )
    near_temporal = _candidate(
        item_id="near-temporal",
        retrieval_order=4,
        dedupe_key="refs:D4:12",
        time_intent_kind="duration",
        has_duration_surface=True,
        query_support_terms=("years",),
        source_refs=("D4:12",),
        source_locality_score=0.9,
        answerability_score=0.82,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, optional_support, far_temporal, near_temporal),
        case_group="single",
        required_roles=("primary", "temporal_support"),
    )

    selected_ids = [item.candidate.item_id for item in plan.items]
    quality = plan.to_diagnostics()["bundle_quality"]

    assert selected_ids == ["primary", "near-temporal"]
    assert "far-temporal" not in selected_ids
    assert "optional-location-support" not in selected_ids
    assert plan.satisfied_required_roles == ("primary", "temporal_support")
    assert plan.repaired_required_roles == ("temporal_support",)
    assert quality["source_proximity_support_count"] == 1
    assert quality["source_proximity_closest_distance"] == 2


def test_evidence_bundle_planner_prefers_more_answerable_primary() -> None:
    weaker = _candidate(
        item_id="weak-primary",
        retrieval_order=1,
        covered_expected_terms=("support",),
        primary_signal=True,
        bundle_strength_score=4.0,
        answerability_score=0.45,
    )
    stronger = _candidate(
        item_id="answerable-primary",
        retrieval_order=2,
        covered_expected_terms=("support",),
        primary_signal=True,
        bundle_strength_score=4.0,
        answerability_score=0.88,
        answerability_reason_codes=("high_answerability", "direct_provenance"),
    )

    plan = EvidenceBundlePlanner().plan((weaker, stronger), case_group="single")

    assert plan.items[0].candidate.item_id == "answerable-primary"
    assert plan.items[0].role == "primary"
    assert "high_answerability" in plan.primary_selection_reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["max_answerability_score"] == 0.88
    assert diagnostics["average_selected_answerability_score"] == 0.665


def test_evidence_bundle_planner_uses_source_locality_for_primary_tie_breaks() -> None:
    broad_refs = _candidate(
        item_id="broad-refs-primary",
        retrieval_order=1,
        covered_expected_terms=("support",),
        primary_signal=True,
        bundle_strength_score=4.0,
        answerability_score=0.8,
        source_locality_score=0.35,
    )
    localized = _candidate(
        item_id="localized-primary",
        retrieval_order=2,
        covered_expected_terms=("support",),
        primary_signal=True,
        bundle_strength_score=4.0,
        answerability_score=0.8,
        source_locality_score=0.9,
    )

    plan = EvidenceBundlePlanner().plan((broad_refs, localized), case_group="single")

    assert plan.items[0].candidate.item_id == "localized-primary"
    assert plan.items[0].role == "primary"
    diagnostics = plan.to_diagnostics()
    assert diagnostics["average_selected_source_locality_score"] == 0.625
    assert plan.items[0].to_payload()["source_locality_score"] == 0.9


def test_evidence_bundle_planner_keeps_answerability_above_locality_tie_break() -> None:
    precise_but_weak = _candidate(
        item_id="precise-but-weak",
        retrieval_order=1,
        covered_expected_terms=("support",),
        primary_signal=True,
        bundle_strength_score=4.0,
        answerability_score=0.45,
        source_locality_score=1.0,
    )
    answerable_but_wider = _candidate(
        item_id="answerable-but-wider",
        retrieval_order=2,
        covered_expected_terms=("support",),
        primary_signal=True,
        bundle_strength_score=4.0,
        answerability_score=0.82,
        source_locality_score=0.35,
    )

    plan = EvidenceBundlePlanner().plan(
        (precise_but_weak, answerable_but_wider),
        case_group="single",
    )

    assert plan.items[0].candidate.item_id == "answerable-but-wider"
    assert plan.items[0].role == "primary"


def test_evidence_bundle_planner_labels_textual_contrast_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("counseling",),
        primary_signal=True,
    )
    contrast = _candidate(
        item_id="changed-plan",
        dedupe_key="refs:D7:5",
        query_support_terms=("current", "plan"),
        negation_surface=True,
        currentness_surface=True,
        stale_surface=True,
        contrast_surface=True,
    )

    plan = EvidenceBundlePlanner().plan((primary, contrast), case_group="multi-hop")

    roles = {item.candidate.item_id: item.role for item in plan.items}
    assert roles["changed-plan"] == "contrast"
    changed_plan = next(
        item for item in plan.items if item.candidate.item_id == "changed-plan"
    )
    assert "contrast_surface" in changed_plan.reason_codes
    assert "currentness_surface" in changed_plan.reason_codes
    payload = changed_plan.to_payload()
    assert payload["contrast_surface"] is True
    assert payload["currentness_surface"] is True
    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["contrast_count"] == 1
    assert quality["contrast_surface_count"] == 1
    assert quality["currentness_surface_count"] == 1
    assert quality["stale_surface_count"] == 1
    assert quality["component_scores"]["contrast_support"] == 0.08
    assert "has_contrast_evidence" in quality["reason_codes"]
    assert "has_currentness_evidence" in quality["reason_codes"]
    assert "has_stale_evidence" in quality["reason_codes"]


def test_evidence_bundle_planner_keeps_contrast_before_generic_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("counseling",),
        primary_signal=True,
        bundle_strength_score=5.0,
    )
    generic_support = _candidate(
        item_id="generic-support",
        dedupe_key="refs:D7:4",
        query_support_terms=("career", "plan", "support"),
        bundle_strength_score=6.0,
    )
    contrast = _candidate(
        item_id="changed-plan",
        dedupe_key="refs:D7:5",
        query_support_terms=("current", "plan"),
        bundle_strength_score=1.0,
        currentness_surface=True,
        contrast_surface=True,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, generic_support, contrast),
        case_group="multi-hop",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "changed-plan",
    ]
    assert plan.items[1].role == "contrast"
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "contrast": 1}
    assert diagnostics["covered_query_support_term_count"] == 2
    assert diagnostics["bundle_quality"]["contrast_count"] == 1


def test_evidence_bundle_planner_keeps_contrast_before_generic_temporal_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("writing",),
        primary_signal=True,
        bundle_strength_score=5.0,
    )
    temporal_support = _candidate(
        item_id="temporal-support",
        dedupe_key="refs:D7:4",
        query_support_terms=("current", "now", "recent"),
        has_temporal_surface=True,
        currentness_surface=True,
        bundle_strength_score=6.0,
    )
    contrast = _candidate(
        item_id="contrast",
        dedupe_key="refs:D7:5",
        query_support_terms=("previous", "current"),
        contrast_surface=True,
        stale_surface=True,
        currentness_surface=True,
        bundle_strength_score=1.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, temporal_support, contrast),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "contrast",
    ]
    assert plan.items[1].role == "contrast"
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "contrast": 1}
    assert diagnostics["bundle_quality"]["contrast_count"] == 1
    assert diagnostics["bundle_quality"]["contrast_surface_count"] == 1


def test_evidence_bundle_planner_rejects_weak_required_contrast_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("writing",),
        primary_signal=True,
        source_locality_score=1.0,
        answerability_score=0.9,
    )
    weak_contrast = _candidate(
        item_id="weak-contrast",
        dedupe_key="refs:D7:5",
        query_support_terms=("previous", "current"),
        contrast_surface=True,
        source_locality_score=0.2,
        focused_evidence_score=0.0,
        answerability_score=0.4,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, weak_contrast),
        case_group="single",
        required_roles=("primary", "contrast"),
    )

    assert plan.missing_required_roles == ("contrast",)
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_requirement_complete"] is False
    assert diagnostics["bundle_quality"]["missing_required_roles"] == ["contrast"]
    assert diagnostics["bundle_quality"]["contrast_count"] == 0
    assert diagnostics["bundle_quality"]["contrast_surface_count"] == 1
    assert diagnostics["bundle_quality"]["component_scores"]["contrast_support"] == 0
    assert "risk:missing_required_contrast" in diagnostics["bundle_quality"][
        "reason_codes"
    ]
    assert "has_contrast_evidence" not in diagnostics["bundle_quality"][
        "reason_codes"
    ]
    assert "has_contrast_surface" in diagnostics["bundle_quality"]["reason_codes"]


def test_evidence_bundle_planner_accepts_grounded_required_contrast_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("writing",),
        primary_signal=True,
        source_locality_score=1.0,
        answerability_score=0.9,
    )
    contrast = _candidate(
        item_id="grounded-contrast",
        dedupe_key="refs:D7:5",
        query_support_terms=("previous", "current"),
        contrast_surface=True,
        source_locality_score=0.9,
        focused_evidence_score=1.0,
        answerability_score=0.82,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, contrast),
        case_group="single",
        required_roles=("primary", "contrast"),
    )

    assert plan.missing_required_roles == ()
    assert plan.role_requirement_complete is True
    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "grounded-contrast",
    ]
    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["contrast_count"] == 1
    assert quality["contrast_surface_count"] == 1
    assert quality["component_scores"]["contrast_support"] == 0.08
    assert "has_contrast_evidence" in quality["reason_codes"]


def test_evidence_bundle_planner_prioritizes_multi_hop_bridge_evidence() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        bundle_strength_score=8.0,
    )
    generic_support = _candidate(
        item_id="generic-support",
        dedupe_key="refs:D1:2",
        query_support_terms=("caroline", "agency", "support"),
        bundle_strength_score=9.0,
    )
    bridge = _candidate(
        item_id="bridge-turn",
        dedupe_key="refs:D2:3",
        query_support_terms=("caroline", "agency"),
        relation_hits=("agency",),
        entity_hits=("caroline",),
        source_refs=("D2:3",),
        source_type="raw_turn",
        source_locality_score=0.9,
        answerability_score=0.72,
        bundle_strength_score=2.0,
        query_roles=("multi_hop_bridge",),
        bridge_query_hit=True,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, generic_support, bridge),
        case_group="multi-hop",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "bridge-turn",
    ]
    bridge_item = plan.items[1]
    assert bridge_item.role == "bridge"
    assert "multi_hop_bridge" in bridge_item.reason_codes
    assert "bridge_query_hit" in bridge_item.reason_codes
    assert "bridge_relation_hits" in bridge_item.reason_codes
    assert bridge_item.to_payload()["query_roles"] == ["multi_hop_bridge"]
    assert bridge_item.to_payload()["bridge_query_hit"] is True
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "bridge": 1}
    assert diagnostics["bundle_quality"]["bridge_count"] == 1
    assert diagnostics["bundle_quality"]["bridge_query_hit_count"] == 1
    assert "has_bridge_evidence" in diagnostics["bundle_quality"]["reason_codes"]


def test_evidence_bundle_planner_keeps_temporal_bridge_query_hit_as_bridge() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        bundle_strength_score=8.0,
    )
    temporal_support = _candidate(
        item_id="temporal-support",
        dedupe_key="refs:D2:1",
        query_support_terms=("after", "session"),
        has_temporal_surface=True,
        has_sequence_surface=True,
        bundle_strength_score=6.0,
    )
    temporal_bridge = _candidate(
        item_id="temporal-bridge",
        dedupe_key="refs:D2:3",
        query_support_terms=("caroline", "agency", "support"),
        relation_hits=("agency", "support"),
        entity_hits=("caroline",),
        has_temporal_surface=True,
        has_sequence_surface=True,
        source_refs=("D2:3",),
        query_roles=("multi_hop_bridge",),
        bridge_query_hit=True,
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, temporal_support, temporal_bridge),
        case_group="multi-hop",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "temporal-bridge",
    ]
    bridge_item = plan.items[1]
    assert bridge_item.role == "bridge"
    assert "multi_hop_bridge" in bridge_item.reason_codes
    assert "temporal_surface" in bridge_item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "bridge": 1}
    assert diagnostics["bundle_quality"]["bridge_count"] == 1


def test_evidence_bundle_planner_selects_required_inference_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        source_refs=("D1:1",),
        direct_speaker_turn=True,
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    generic_support = _candidate(
        item_id="generic-support",
        dedupe_key="refs:D1:2",
        query_support_terms=("caroline", "decision"),
        bundle_strength_score=9.0,
    )
    inference_support = _candidate(
        item_id="inference-support",
        dedupe_key="refs:D2:3",
        query_support_terms=("caroline", "adoption", "decision"),
        relation_hits=("adoption", "decision"),
        relation_category_hits=("support_goal",),
        entity_hits=("caroline",),
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.72,
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, generic_support, inference_support),
        case_group="single",
        required_roles=("primary", "inference_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "inference-support",
    ]
    support_item = plan.items[1]
    assert support_item.role == "inference_support"
    assert "inference_support" in support_item.reason_codes
    assert "inference_relation_hits" in support_item.reason_codes
    assert "inference_entity_hits" in support_item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "inference_support": 1}
    assert diagnostics["satisfied_required_roles"] == [
        "primary",
        "inference_support",
    ]
    assert diagnostics["bundle_quality"]["inference_support_count"] == 1
    assert "has_inference_support_evidence" in diagnostics["bundle_quality"][
        "reason_codes"
    ]


def test_evidence_bundle_planner_requires_relation_inference_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        source_refs=("D1:1",),
        direct_speaker_turn=True,
        focused_evidence_score=1.0,
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    generic_person_mention = _candidate(
        item_id="generic-person-mention",
        dedupe_key="refs:D1:2",
        query_support_terms=("caroline", "decision"),
        entity_hits=("caroline",),
        source_refs=("D1:2",),
        source_locality_score=0.95,
        answerability_score=0.86,
        bundle_strength_score=10.0,
    )
    inference_support = _candidate(
        item_id="inference-support",
        dedupe_key="refs:D2:3",
        query_support_terms=("caroline", "adoption", "decision"),
        relation_hits=("adoption", "decision"),
        entity_hits=("caroline",),
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.72,
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, generic_person_mention, inference_support),
        case_group="single",
        required_roles=("primary", "inference_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "inference-support",
    ]
    support_item = plan.items[1]
    assert support_item.role == "inference_support"
    assert "inference_support" in support_item.reason_codes
    assert "inference_relation_hits" in support_item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "inference_support": 1}
    assert diagnostics["satisfied_required_roles"] == [
        "primary",
        "inference_support",
    ]


def test_evidence_bundle_planner_selects_required_preference_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        source_refs=("D1:1",),
        direct_speaker_turn=True,
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    generic_support = _candidate(
        item_id="generic-support",
        dedupe_key="refs:D1:2",
        query_support_terms=("melanie", "like"),
        bundle_strength_score=9.0,
    )
    direct_speaker_distractor = _candidate(
        item_id="direct-speaker-distractor",
        dedupe_key="refs:D2:2",
        query_support_terms=("like", "animal"),
        relation_hits=("like", "animal"),
        relation_category_hits=("preference",),
        has_preference_evidence=True,
        query_has_entities=True,
        direct_speaker_turn=True,
        source_refs=("D2:2",),
        source_locality_score=0.95,
        answerability_score=0.88,
        bundle_strength_score=10.0,
    )
    preference_support = _candidate(
        item_id="preference-support",
        dedupe_key="refs:D2:3",
        query_support_terms=("melanie", "like", "animal"),
        relation_hits=("like", "animal"),
        relation_category_hits=("preference",),
        entity_hits=("melanie",),
        has_preference_evidence=True,
        query_has_entities=True,
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.74,
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, generic_support, direct_speaker_distractor, preference_support),
        case_group="single",
        required_roles=("primary", "preference_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "preference-support",
    ]
    support_item = plan.items[1]
    assert support_item.role == "preference_support"
    assert "preference_support" in support_item.reason_codes
    assert "preference_evidence" in support_item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "preference_support": 1}
    assert diagnostics["satisfied_required_roles"] == [
        "primary",
        "preference_support",
    ]
    assert diagnostics["bundle_quality"]["preference_support_count"] == 1
    assert "has_preference_support_evidence" in diagnostics["bundle_quality"][
        "reason_codes"
    ]


def test_evidence_bundle_planner_selects_required_visual_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        source_refs=("D1:1",),
        direct_speaker_turn=True,
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    generic_support = _candidate(
        item_id="generic-support",
        dedupe_key="refs:D1:2",
        query_support_terms=("melanie", "painting"),
        bundle_strength_score=9.0,
    )
    direct_speaker_distractor = _candidate(
        item_id="direct-speaker-distractor",
        dedupe_key="refs:D2:2",
        query_support_terms=("painting", "image"),
        relation_hits=("paint", "image"),
        relation_category_hits=("visual",),
        has_visual_evidence=True,
        query_has_entities=True,
        direct_speaker_turn=True,
        source_refs=("D2:2",),
        source_locality_score=0.95,
        answerability_score=0.88,
        bundle_strength_score=10.0,
    )
    visual_support = _candidate(
        item_id="visual-support",
        dedupe_key="refs:D2:3",
        query_support_terms=("melanie", "painting", "image"),
        relation_hits=("paint", "image"),
        relation_category_hits=("visual",),
        entity_hits=("melanie",),
        has_visual_evidence=True,
        query_has_entities=True,
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.74,
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, generic_support, direct_speaker_distractor, visual_support),
        case_group="single",
        required_roles=("primary", "visual_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "visual-support",
    ]
    support_item = plan.items[1]
    assert support_item.role == "visual_support"
    assert "visual_support" in support_item.reason_codes
    assert "visual_evidence" in support_item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "visual_support": 1}
    assert diagnostics["satisfied_required_roles"] == [
        "primary",
        "visual_support",
    ]
    assert diagnostics["bundle_quality"]["visual_support_count"] == 1
    assert "has_visual_support_evidence" in diagnostics["bundle_quality"][
        "reason_codes"
    ]


def test_evidence_bundle_planner_selects_required_emotion_response_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        source_refs=("D1:1",),
        direct_speaker_turn=True,
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    generic_support = _candidate(
        item_id="generic-support",
        dedupe_key="refs:D1:2",
        query_support_terms=("melanie", "adoption"),
        bundle_strength_score=9.0,
    )
    emotion_support = _candidate(
        item_id="emotion-support",
        dedupe_key="refs:D2:3",
        query_support_terms=("melanie", "felt", "adoption"),
        relation_hits=("felt", "relieved"),
        relation_category_hits=("emotion_response",),
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.76,
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, generic_support, emotion_support),
        case_group="single",
        required_roles=("primary", "emotion_response_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "emotion-support",
    ]
    support_item = plan.items[1]
    assert support_item.role == "emotion_response_support"
    assert "emotion_response_support" in support_item.reason_codes
    assert "emotion_response_relation_category_hits" in support_item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {
        "primary": 1,
        "emotion_response_support": 1,
    }
    assert diagnostics["satisfied_required_roles"] == [
        "primary",
        "emotion_response_support",
    ]
    assert diagnostics["bundle_quality"]["emotion_response_support_count"] == 1
    assert "has_emotion_response_support_evidence" in diagnostics["bundle_quality"][
        "reason_codes"
    ]


def test_evidence_bundle_planner_selects_required_symbolic_meaning_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        source_refs=("D1:1",),
        direct_speaker_turn=True,
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    generic_support = _candidate(
        item_id="generic-support",
        dedupe_key="refs:D1:2",
        query_support_terms=("caroline", "necklace"),
        bundle_strength_score=9.0,
    )
    symbolic_support = _candidate(
        item_id="symbolic-support",
        dedupe_key="refs:D2:3",
        query_support_terms=("caroline", "necklace", "represents"),
        relation_hits=("necklace", "represents", "roots"),
        relation_category_hits=("symbolic_meaning",),
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.76,
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, generic_support, symbolic_support),
        case_group="single",
        required_roles=("primary", "symbolic_meaning_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "symbolic-support",
    ]
    support_item = plan.items[1]
    assert support_item.role == "symbolic_meaning_support"
    assert "symbolic_meaning_support" in support_item.reason_codes
    assert "symbolic_meaning_relation_category_hits" in support_item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {
        "primary": 1,
        "symbolic_meaning_support": 1,
    }
    assert diagnostics["satisfied_required_roles"] == [
        "primary",
        "symbolic_meaning_support",
    ]
    assert diagnostics["bundle_quality"]["symbolic_meaning_support_count"] == 1
    assert "has_symbolic_meaning_support_evidence" in diagnostics["bundle_quality"][
        "reason_codes"
    ]


def test_evidence_bundle_planner_selects_required_event_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        source_refs=("D1:1",),
        direct_speaker_turn=True,
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    generic_support = _candidate(
        item_id="generic-support",
        dedupe_key="refs:D1:2",
        query_support_terms=("morgan", "studio"),
        bundle_strength_score=9.0,
    )
    event_support = _candidate(
        item_id="event-support",
        dedupe_key="refs:D2:3",
        query_support_terms=("morgan", "visited", "studio"),
        relation_hits=("visited", "studio"),
        relation_category_hits=("participation_event",),
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.76,
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, generic_support, event_support),
        case_group="single",
        required_roles=("primary", "event_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "event-support",
    ]
    support_item = plan.items[1]
    assert support_item.role == "event_support"
    assert "event_support" in support_item.reason_codes
    assert "event_relation_category_hits" in support_item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "event_support": 1}
    assert diagnostics["satisfied_required_roles"] == [
        "primary",
        "event_support",
    ]
    assert diagnostics["bundle_quality"]["event_support_count"] == 1
    assert "has_event_support_evidence" in diagnostics["bundle_quality"][
        "reason_codes"
    ]


def test_evidence_bundle_planner_requires_grounded_typed_support_for_entity_query() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        source_refs=("D1:1",),
        direct_speaker_turn=True,
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    ungrounded_event = _candidate(
        item_id="ungrounded-event",
        dedupe_key="refs:D2:2",
        query_support_terms=("visited", "studio"),
        relation_hits=("visited", "studio"),
        relation_category_hits=("participation_event",),
        query_has_entities=True,
        source_refs=("D2:2",),
        source_locality_score=0.95,
        answerability_score=0.86,
        bundle_strength_score=9.0,
    )
    direct_speaker_distractor = _candidate(
        item_id="direct-speaker-distractor",
        dedupe_key="refs:D2:4",
        query_support_terms=("visited", "studio"),
        relation_hits=("visited", "studio"),
        relation_category_hits=("participation_event",),
        query_has_entities=True,
        direct_speaker_turn=True,
        source_refs=("D2:4",),
        source_locality_score=0.95,
        answerability_score=0.88,
        bundle_strength_score=10.0,
    )
    grounded_event = _candidate(
        item_id="grounded-event",
        dedupe_key="refs:D2:3",
        query_support_terms=("morgan", "visited", "studio"),
        relation_hits=("visited", "studio"),
        relation_category_hits=("participation_event",),
        entity_hits=("morgan",),
        query_has_entities=True,
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.76,
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, ungrounded_event, direct_speaker_distractor, grounded_event),
        case_group="single",
        required_roles=("primary", "event_support"),
    )

    selected_ids = [item.candidate.item_id for item in plan.items]
    assert selected_ids == ["primary", "grounded-event"]
    assert plan.items[1].role == "event_support"
    assert plan.items[1].to_payload()["entity_hits"] == ["morgan"]
    diagnostics = plan.to_diagnostics()
    assert diagnostics["satisfied_required_roles"] == ["primary", "event_support"]
    assert diagnostics["bundle_quality"]["event_support_count"] == 1


def test_evidence_bundle_planner_selects_required_communication_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        source_refs=("D1:1",),
        direct_speaker_turn=True,
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    generic_support = _candidate(
        item_id="generic-support",
        dedupe_key="refs:D1:2",
        query_support_terms=("alex", "delay"),
        relation_category_hits=("communication",),
        query_has_entities=True,
        direct_speaker_turn=True,
        source_refs=("D1:2",),
        source_locality_score=0.9,
        answerability_score=0.8,
        bundle_strength_score=9.0,
    )
    communication_support = _candidate(
        item_id="communication-support",
        dedupe_key="refs:D2:3",
        query_support_terms=("alex", "told", "maria", "delay"),
        relation_hits=("told",),
        relation_category_hits=("communication",),
        speaker_hits=("alex",),
        direct_speaker_turn=True,
        query_has_entities=True,
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.8,
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, generic_support, communication_support),
        case_group="single",
        required_roles=("primary", "communication_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "communication-support",
    ]
    support_item = plan.items[1]
    assert support_item.role == "communication_support"
    assert "communication_support" in support_item.reason_codes
    assert "communication_speaker_hits" in support_item.reason_codes
    assert "communication_direct_speaker_turn" in support_item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {
        "primary": 1,
        "communication_support": 1,
    }
    assert diagnostics["satisfied_required_roles"] == [
        "primary",
        "communication_support",
    ]
    assert diagnostics["bundle_quality"]["communication_support_count"] == 1
    assert "has_communication_support_evidence" in diagnostics["bundle_quality"][
        "reason_codes"
    ]


def test_evidence_bundle_planner_selects_required_exchange_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        source_refs=("D1:1",),
        direct_speaker_turn=True,
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    generic_support = _candidate(
        item_id="generic-support",
        dedupe_key="refs:D1:2",
        query_support_terms=("melanie", "bought"),
        relation_hits=("bought",),
        source_refs=("D1:2",),
        source_locality_score=0.9,
        answerability_score=0.8,
        bundle_strength_score=9.0,
    )
    exchange_support = _candidate(
        item_id="exchange-support",
        dedupe_key="refs:D2:3",
        query_support_terms=("melanie", "bought", "got"),
        relation_hits=("bought", "got"),
        relation_category_hits=("exchange",),
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.8,
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, generic_support, exchange_support),
        case_group="single",
        required_roles=("primary", "exchange_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "exchange-support",
    ]
    support_item = plan.items[1]
    assert support_item.role == "exchange_support"
    assert "exchange_support" in support_item.reason_codes
    assert "exchange_relation_category_hits" in support_item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "exchange_support": 1}
    assert diagnostics["satisfied_required_roles"] == [
        "primary",
        "exchange_support",
    ]
    assert diagnostics["bundle_quality"]["exchange_support_count"] == 1
    assert "has_exchange_support_evidence" in diagnostics["bundle_quality"][
        "reason_codes"
    ]


def test_evidence_bundle_planner_selects_required_causal_support() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        source_refs=("D1:1",),
        direct_speaker_turn=True,
        answerability_score=0.9,
        source_locality_score=1.0,
    )
    causal_support = _candidate(
        item_id="causal-support",
        dedupe_key="refs:D2:3",
        query_support_terms=("caroline", "agency", "reason"),
        relation_hits=("because", "reason", "fit"),
        relation_category_hits=("causal",),
        entity_hits=("caroline",),
        source_refs=("D2:3",),
        source_locality_score=0.9,
        answerability_score=0.76,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, causal_support),
        case_group="single",
        required_roles=("primary", "causal_support"),
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "causal-support",
    ]
    support_item = plan.items[1]
    assert support_item.role == "causal_support"
    assert "causal_support" in support_item.reason_codes
    assert "causal_relation_hits" in support_item.reason_codes
    assert "causal_relation_category_hits" in support_item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "causal_support": 1}
    assert diagnostics["satisfied_required_roles"] == [
        "primary",
        "causal_support",
    ]
    assert diagnostics["bundle_quality"]["causal_support_count"] == 1
    assert "has_causal_support_evidence" in diagnostics["bundle_quality"][
        "reason_codes"
    ]


def test_evidence_bundle_planner_does_not_treat_ungrounded_bridge_query_hit_as_bridge() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
    )
    ungrounded = _candidate(
        item_id="ungrounded-bridge-query",
        dedupe_key="refs:D2:4",
        query_support_terms=("caroline", "support"),
        has_temporal_surface=True,
        query_roles=("multi_hop_bridge",),
        bridge_query_hit=True,
    )

    plan = EvidenceBundlePlanner().plan((primary, ungrounded), case_group="multi-hop")

    item = next(
        item
        for item in plan.items
        if item.candidate.item_id == "ungrounded-bridge-query"
    )
    assert item.role == "temporal_support"
    assert "bridge_query_hit" in item.reason_codes
    assert "multi_hop_bridge" not in item.reason_codes
    diagnostics = plan.to_diagnostics()
    assert diagnostics["role_counts"] == {"primary": 1, "temporal_support": 1}
    assert diagnostics["bundle_quality"]["bridge_count"] == 0
    assert diagnostics["bundle_quality"]["bridge_query_hit_count"] == 1


def test_evidence_bundle_planner_prefers_marginal_evidence_coverage() -> None:
    primary = _candidate(
        item_id="primary",
        covered_evidence_terms=("D1:1",),
        primary_signal=True,
        bundle_strength_score=10.0,
    )
    redundant = _candidate(
        item_id="redundant-strong",
        dedupe_key="refs:D1:2",
        covered_evidence_terms=("D1:1",),
        query_support_terms=("caroline", "agency"),
        bundle_strength_score=9.0,
    )
    complementary = _candidate(
        item_id="complementary-weaker",
        dedupe_key="refs:D2:3",
        covered_evidence_terms=("D2:3",),
        query_support_terms=("adoption", "support"),
        bundle_strength_score=2.0,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, redundant, complementary),
        case_group="multi-hop",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "complementary-weaker",
    ]
    diagnostics = plan.to_diagnostics()
    assert diagnostics["covered_required_term_count"] == 2
    assert diagnostics["covered_query_support_term_count"] == 2
    assert plan.dropped_diversity_count == 1


def test_evidence_bundle_planner_reports_high_confidence_evidence_package() -> None:
    primary = _candidate(
        item_id="direct-primary",
        covered_evidence_terms=("D1:1",),
        query_support_terms=("caroline", "agency"),
        primary_signal=True,
        source_refs=("D1:1",),
        source_type="raw_turn",
        retrieval_sources=("raw_turns",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.9,
    )
    support = _candidate(
        item_id="chunk-support",
        dedupe_key="refs:D2:3",
        covered_evidence_terms=("D2:3",),
        query_support_terms=("support", "inclusive"),
        source_refs=("D2:3",),
        source_type="chunk",
        retrieval_sources=("semantic_chunks",),
        focused_evidence_score=1.0,
        answerability_score=0.8,
    )

    plan = EvidenceBundlePlanner().plan((primary, support), case_group="multi-hop")

    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["schema_version"] == "evidence_bundle_quality.v1"
    assert quality["confidence_band"] == "high"
    assert quality["confidence_score"] >= 0.75
    assert quality["source_type_diversity"] == 2
    assert quality["retrieval_source_diversity"] == 2
    assert quality["reason_codes"] == [
        "has_primary_evidence",
        "has_supporting_evidence",
        "has_focused_evidence",
        "has_direct_speaker_evidence",
        "has_source_refs",
        "source_type_diverse",
        "retrieval_source_diverse",
        "high_answerability",
    ]


def test_evidence_bundle_planner_counts_fused_source_type_provenance() -> None:
    fused = _candidate(
        item_id="fused-evidence",
        covered_evidence_terms=("D2:8",),
        query_support_terms=("caroline", "adoption"),
        primary_signal=True,
        source_refs=("D2:8",),
        source_type="chunk",
        source_types=("chunk", "raw_turn"),
        retrieval_sources=("semantic_chunks", "raw_turns"),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.9,
    )

    plan = EvidenceBundlePlanner().plan((fused,), case_group="single")
    diagnostics = plan.to_diagnostics()
    item = plan.items[0].to_payload()
    quality = diagnostics["bundle_quality"]

    assert plan.source_type_counts == {"chunk": 1, "raw_turn": 1}
    assert item["source_types"] == ["chunk", "raw_turn"]
    assert quality["source_type_diversity"] == 2
    assert quality["retrieval_source_diversity"] == 2
    assert "source_type_diverse" in quality["reason_codes"]
    assert "retrieval_source_diverse" in quality["reason_codes"]


def test_evidence_bundle_quality_penalizes_missing_required_roles() -> None:
    primary = _candidate(
        item_id="direct-primary",
        covered_evidence_terms=("D1:1",),
        query_support_terms=("caroline", "career"),
        primary_signal=True,
        source_refs=("D1:1",),
        source_type="raw_turn",
        retrieval_sources=("raw_turns",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.92,
    )
    supporting = _candidate(
        item_id="supporting",
        dedupe_key="refs:D1:2",
        query_support_terms=("career", "plan"),
        source_refs=("D1:2",),
        source_type="chunk",
        retrieval_sources=("semantic_chunks",),
        answerability_score=0.82,
    )

    plan = EvidenceBundlePlanner().plan(
        (primary, supporting),
        case_group="single",
        required_roles=("primary", "contrast"),
    )

    quality = plan.to_diagnostics()["bundle_quality"]
    assert plan.missing_required_roles == ("contrast",)
    assert quality["missing_required_role_count"] == 1
    assert quality["missing_required_roles"] == ["contrast"]
    assert quality["risk_penalty"] == 0.18
    assert "risk:missing_required_role" in quality["reason_codes"]
    assert "risk:missing_required_contrast" in quality["reason_codes"]
    assert quality["confidence_score"] < 0.75


def test_evidence_bundle_planner_reports_low_confidence_broad_bundle() -> None:
    broad = _candidate(
        item_id="broad-only",
        covered_expected_terms=("support",),
        primary_signal=True,
        source_type="summary",
        broad_summary=True,
        answerability_score=0.2,
    )

    plan = EvidenceBundlePlanner().plan((broad,), case_group="open-domain")

    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["confidence_band"] == "low"
    assert quality["confidence_score"] < 0.1
    assert quality["risk_penalty"] == 0.21
    assert quality["broad_summary_count"] == 1
    assert quality["low_answerability_count"] == 1
    assert "risk:low_answerability" in quality["reason_codes"]
    assert "risk:broad_summary" in quality["reason_codes"]
    assert "risk:all_broad_summary" in quality["reason_codes"]


def test_evidence_bundle_planner_scores_source_proximity_support() -> None:
    primary = _candidate(
        item_id="primary",
        dedupe_key="refs:D4:10",
        covered_evidence_terms=("D4:10",),
        primary_signal=True,
        source_refs=("D4:10",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.9,
    )
    near_support = _candidate(
        item_id="near-support",
        dedupe_key="refs:D4:12",
        query_support_terms=("origin", "country", "nearby"),
        source_refs=("D4:12",),
        answerability_score=0.82,
    )
    far_support = _candidate(
        item_id="far-support",
        dedupe_key="refs:D4:30",
        query_support_terms=("origin", "country", "later"),
        source_refs=("D4:30",),
        answerability_score=0.82,
    )
    other_dialogue_support = _candidate(
        item_id="other-dialogue-support",
        dedupe_key="refs:D5:12",
        query_support_terms=("origin", "country", "elsewhere"),
        source_refs=("D5:12",),
        answerability_score=0.82,
    )

    plan = EvidenceBundlePlanner(
        max_items_per_source_type=10,
        max_items_per_retrieval_source=10,
    ).plan(
        (primary, far_support, other_dialogue_support, near_support),
        case_group="single",
    )

    quality = plan.to_diagnostics()["bundle_quality"]

    assert quality["source_proximity_support_count"] == 1
    assert quality["source_proximity_closest_distance"] == 2
    assert quality["source_proximity_distance_counts"] == {"2": 1}
    assert quality["source_proximity_window"] == 3
    assert quality["component_scores"]["source_proximity"] == 0.03
    assert "has_source_proximity_support" in quality["reason_codes"]


def test_evidence_bundle_planner_prefers_nearby_support_after_primary() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="refs:D4:10",
        covered_evidence_terms=("plan",),
        primary_signal=True,
        source_refs=("D4:10",),
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.9,
    )
    far_support = _candidate(
        item_id="far-support",
        retrieval_order=2,
        dedupe_key="refs:D4:28",
        query_support_terms=("origin", "country"),
        source_refs=("D4:28",),
        answerability_score=0.82,
    )
    near_support = _candidate(
        item_id="near-support",
        retrieval_order=3,
        dedupe_key="refs:D4:12",
        query_support_terms=("origin", "country"),
        source_refs=("D4:12",),
        answerability_score=0.82,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, far_support, near_support),
        case_group="single",
    )

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "near-support",
    ]
    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["source_proximity_support_count"] == 1
    assert quality["source_proximity_closest_distance"] == 2
    assert quality["source_proximity_distance_counts"] == {"2": 1}
    assert quality["component_scores"]["source_proximity"] == 0.03


def test_evidence_bundle_planner_uses_dedupe_turn_refs_for_proximity() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="source_turn_refs:D4:10",
        covered_evidence_terms=("plan",),
        primary_signal=True,
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.9,
    )
    near_support = _candidate(
        item_id="near-support",
        retrieval_order=2,
        dedupe_key="source_turn_refs:D4:12",
        query_support_terms=("origin", "country"),
        answerability_score=0.82,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, near_support),
        case_group="single",
    )

    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["source_ref_item_count"] == 0
    assert quality["source_identity_item_count"] == 2
    assert quality["source_identity_ref_count"] == 2
    assert quality["component_scores"]["source_refs"] == 0.16
    assert "has_source_identity" in quality["reason_codes"]
    assert quality["source_proximity_support_count"] == 1
    assert quality["source_proximity_closest_distance"] == 2
    assert quality["source_proximity_distance_counts"] == {"2": 1}
    assert quality["component_scores"]["source_proximity"] == 0.03
    assert plan.items[0].to_payload()["source_ref_dedupe_key"] == (
        "source_turn_refs:D4:10"
    )
    assert plan.items[1].to_payload()["source_ref_dedupe_key"] == (
        "source_turn_refs:D4:12"
    )


def test_evidence_bundle_quality_normalizes_canonical_source_refs() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="primary",
        covered_evidence_terms=("plan",),
        primary_signal=True,
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        source_refs=("locomo:conv-19:session_4:D4:10:chunk",),
        answerability_score=0.9,
    )
    near_support = _candidate(
        item_id="near-support",
        retrieval_order=2,
        dedupe_key="support",
        query_support_terms=("origin", "country"),
        source_refs=("locomo:conv-19:session_4:D4:12:turn",),
        answerability_score=0.82,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, near_support),
        case_group="single",
    )

    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["source_ref_item_count"] == 2
    assert quality["source_identity_item_count"] == 2
    assert quality["source_identity_ref_count"] == 4
    assert "has_source_refs" in quality["reason_codes"]
    assert quality["source_proximity_support_count"] == 1
    assert quality["source_proximity_closest_distance"] == 2
    assert quality["source_proximity_distance_counts"] == {"2": 1}


def test_evidence_bundle_quality_counts_multi_ref_source_identity() -> None:
    primary = _candidate(
        item_id="primary",
        retrieval_order=1,
        dedupe_key="source_turn_refs:D4:10|D4:11",
        covered_evidence_terms=("plan",),
        primary_signal=True,
        focused_evidence_score=1.0,
        direct_speaker_turn=True,
        answerability_score=0.9,
    )
    support = _candidate(
        item_id="support",
        retrieval_order=2,
        dedupe_key="refs:D4:12|chunk-8",
        query_support_terms=("origin", "country"),
        answerability_score=0.82,
    )

    plan = EvidenceBundlePlanner(max_items=2).plan(
        (primary, support),
        case_group="single",
    )

    quality = plan.to_diagnostics()["bundle_quality"]
    assert quality["source_ref_item_count"] == 0
    assert quality["source_identity_item_count"] == 2
    assert quality["source_identity_ref_count"] == 4
    assert quality["source_proximity_support_count"] == 1


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
    source_types: tuple[str, ...] = (),
    retrieval_sources: tuple[str, ...] = (),
    direct_speaker_turn: bool = False,
    broad_summary: bool = False,
    time_intent_kind: str = "",
    has_temporal_surface: bool = False,
    has_sequence_surface: bool = False,
    has_duration_surface: bool = False,
    has_relative_time_surface: bool = False,
    has_explicit_time_surface: bool = False,
    has_temporal_sequence_surface: bool = False,
    conflict_or_stale: bool = False,
    negation_surface: bool = False,
    currentness_surface: bool = False,
    stale_surface: bool = False,
    contrast_surface: bool = False,
    answerability_score: float = 0.0,
    answerability_reason_codes: tuple[str, ...] = (),
    source_locality_score: float = 0.0,
    relation_hits: tuple[str, ...] = (),
    relation_categories: tuple[str, ...] = (),
    relation_category_hits: tuple[str, ...] = (),
    entity_hits: tuple[str, ...] = (),
    speaker_hits: tuple[str, ...] = (),
    query_has_entities: bool = False,
    has_preference_evidence: bool = False,
    has_visual_evidence: bool = False,
    query_roles: tuple[str, ...] = (),
    bridge_query_hit: bool = False,
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
        source_types=source_types,
        retrieval_sources=retrieval_sources,
        direct_speaker_turn=direct_speaker_turn,
        broad_summary=broad_summary,
        time_intent_kind=time_intent_kind,
        has_temporal_surface=has_temporal_surface,
        has_sequence_surface=has_sequence_surface,
        has_duration_surface=has_duration_surface,
        has_relative_time_surface=has_relative_time_surface,
        has_explicit_time_surface=has_explicit_time_surface,
        has_temporal_sequence_surface=has_temporal_sequence_surface,
        conflict_or_stale=conflict_or_stale,
        negation_surface=negation_surface,
        currentness_surface=currentness_surface,
        stale_surface=stale_surface,
        contrast_surface=contrast_surface,
        answerability_score=answerability_score,
        answerability_reason_codes=answerability_reason_codes,
        source_locality_score=source_locality_score,
        relation_hits=relation_hits,
        relation_categories=relation_categories,
        relation_category_hits=relation_category_hits,
        entity_hits=entity_hits,
        speaker_hits=speaker_hits,
        query_has_entities=query_has_entities,
        has_preference_evidence=has_preference_evidence,
        has_visual_evidence=has_visual_evidence,
        query_roles=query_roles,
        bridge_query_hit=bridge_query_hit,
    )
