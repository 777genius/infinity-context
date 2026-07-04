from __future__ import annotations

from collections.abc import Mapping

from infinity_context_server.memory_comparison_quality_diagnostics import (
    evidence_ref_rank_gate_metrics,
    fast_gate_metrics,
    quality_diagnostics,
)


def test_evidence_ref_rank_gate_counts_ref_positions_and_focused_refs() -> None:
    metrics = evidence_ref_rank_gate_metrics(
        (
            _item(
                case_id="case-1",
                evidence_bundle={
                    "evidence_term_count": 2,
                    "bundle_complete": True,
                    "covered_evidence_terms": ["D1:1", "D2:3"],
                    "items": [
                        {
                            "retrieval_order": 1,
                            "covered_evidence_terms": ["D1:1"],
                            "focused_evidence_score": 1.0,
                        },
                        {
                            "retrieval_order": 2,
                            "covered_evidence_terms": ["D2:3"],
                            "focused_evidence_score": 1.0,
                        },
                    ],
                },
            ),
        )
    )

    assert metrics["evaluation_count"] == 1
    assert metrics["all_refs_top1_count"] == 0
    assert metrics["all_refs_top2_count"] == 1
    assert metrics["all_refs_top5_ok"] is True
    assert metrics["focused_refs_top5_count"] == 1


def test_quality_diagnostics_reports_intents_policies_bundle_gaps_and_leakage() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="pass",
                score=1.0,
                retrieval_quality={
                    "expected_term_recall": 1.0,
                    "evidence_term_recall": 1.0,
                },
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary", "bridge"),
                    relation_categories=("preference",),
                    risk_flags=("wide_relation_expansion",),
                    policy_score=0.2,
                    candidate_features={
                        "source_type": "raw_turn",
                        "source_types": ["raw_turn", "chunk"],
                        "retrieval_sources": ["raw_turns"],
                        "query_roles": ["multi_hop_bridge"],
                        "bridge_query_hit": True,
                        "relation_categories": ["preference"],
                        "relation_category_hits": ["preference"],
                        "direct_speaker_turn": True,
                        "time_intent_kind": "duration",
                        "has_duration_surface": True,
                        "has_explicit_time_surface": True,
                        "has_explicit_time_content_surface": True,
                        "source_locality_score": 1.0,
                        "source_locality_reason_codes": ["direct_localized_turn"],
                        "answerability_score": 0.9,
                        "answerability_reason_codes": [
                            "duration_temporal_evidence",
                            "high_answerability",
                        ],
                    },
                ),
                evidence_bundle={
                    "bundle_complete": True,
                    "item_count": 2,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 1,
                    "query_support_term_recall": 1.0,
                    "bundle_planner": {
                        "average_selected_source_locality_score": 0.9,
                        "dropped_source_ref_overlap_count": 1,
                        "dropped_source_ref_overlap_keys_sample": ["D1:1"],
                        "bundle_quality": _bundle_quality(
                            confidence_score=0.86,
                            confidence_band="high",
                            reason_codes=(
                                "has_primary_evidence",
                                "has_supporting_evidence",
                                "has_source_refs",
                                "high_answerability",
                                "has_bridge_evidence",
                                "has_contrast_evidence",
                            ),
                            selected_item_count=2,
                            primary_count=1,
                            supporting_count=1,
                            bridge_count=1,
                                causal_support_count=1,
                                inference_support_count=1,
                                location_support_count=1,
                                emotion_response_support_count=1,
                                preference_support_count=1,
                                visual_support_count=1,
                            contrast_count=1,
                            location_relation_category_hit_count=1,
                            source_proximity_support_count=1,
                            source_ref_item_count=2,
                            source_ref_support_item_count=2,
                            source_ref_support_ref_count=2,
                            source_identity_support_item_count=2,
                            source_identity_support_ref_count=2,
                            source_type_diversity=2,
                            retrieval_source_diversity=2,
                            source_type_support_diversity=2,
                            retrieval_source_support_diversity=2,
                        )
                    },
                    "items": [
                        {
                            "role": "bridge",
                            "query_roles": ["multi_hop_bridge"],
                            "bridge_query_hit": True,
                            "answerability_score": 0.9,
                            "covered_evidence_terms": ["D1:1"],
                            "focused_evidence_score": 1.0,
                        }
                    ],
                },
            ),
            _item(
                case_id="fail",
                score=0.0,
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D2:3"],
                },
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    risk_flags=("broad_query",),
                    query_overlap_count=1,
                    policy_score=0.0,
                    candidate_features={
                        "source_type": "chunk",
                        "retrieval_sources": ["semantic_chunks"],
                        "query_roles": ["temporal_support"],
                        "relation_categories": ["temporal"],
                        "contrast_surface": True,
                        "currentness_surface": True,
                        "negation_surface": True,
                        "stale_surface": True,
                        "time_intent_kind": "relative_time",
                        "has_relative_time_surface": True,
                        "source_locality_score": 0.35,
                        "source_locality_reason_codes": [
                            "broad_turn_refs",
                            "broad_summary_locality_cap",
                        ],
                        "answerability_score": 0.42,
                        "answerability_reason_codes": ["low_answerability"],
                    },
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 0,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.0,
                    "bundle_planner": {
                        "average_selected_source_locality_score": 0.35,
                        "dropped_source_ref_overlap_count": 2,
                        "dropped_source_ref_overlap_keys_sample": ["D2:3", "D2:4"],
                        "dropped_noisy_source_overlap_count": 2,
                        "dropped_noisy_source_overlap_keys_sample": ["D2:3", "D2:4"],
                        "bundle_quality": _bundle_quality(
                            confidence_score=0.18,
                            confidence_band="low",
                            risk_penalty=0.21,
                            reason_codes=(
                                "risk:low_answerability",
                                "risk:broad_summary",
                                "risk:all_broad_summary",
                            ),
                            selected_item_count=1,
                            low_answerability_count=1,
                            broad_summary_count=1,
                        )
                    },
                    "items": [
                        {
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 0.0,
                        }
                    ],
                },
            ),
        )
    )

    assert diagnostics["schema_version"] == "quality_diagnostics.v2"
    assert diagnostics["per_intent"]["need:preference"]["accuracy"] == 1.0
    assert diagnostics["per_intent"]["role:bridge"]["accuracy"] == 1.0
    assert diagnostics["per_intent"]["relation:preference"]["accuracy"] == 1.0
    assert diagnostics["per_intent"]["need:temporal_support"]["accuracy"] == 0.0
    assert diagnostics["per_intent"]["role:temporal_support"]["accuracy"] == 0.0
    assert diagnostics["per_intent"]["relation:temporal"]["accuracy"] == 0.0
    risk_flags = diagnostics["risk_flag_table"]
    assert risk_flags["schema_version"] == "retrieval_intent_risk_flags.v1"
    assert risk_flags["risk_flag_case_count"] == 2
    assert risk_flags["no_risk_flag_case_count"] == 0
    assert risk_flags["flag_counts"] == {
        "broad_query": 1,
        "wide_relation_expansion": 1,
    }
    assert risk_flags["flag_stats"]["wide_relation_expansion"]["accuracy"] == 1.0
    assert risk_flags["flag_stats"]["broad_query"]["accuracy"] == 0.0
    assert risk_flags["flag_stats"]["broad_query"]["bundle_complete_rate"] == 0.0
    assert risk_flags["flag_stats"]["broad_query"]["query_overlap_count"] == 1
    assert risk_flags["flag_stats"]["broad_query"]["samples"][0]["case_id"] == "fail"
    assert diagnostics["bundle_incomplete"]["reason_counts"]["missing_primary"] == 1
    assert diagnostics["bundle_incomplete"]["reason_counts"]["missing_evidence_refs"] == 1
    assert diagnostics["bundle_incomplete"]["reason_counts"]["missing_bridge"] == 1
    assert diagnostics["bundle_incomplete"]["reason_counts"]["missing_bridge_entity"] == 1
    assert diagnostics["bundle_incomplete"]["reason_counts"]["missing_bridge_relation"] == 1
    assert diagnostics["bundle_incomplete"]["reason_counts"]["missing_temporal_bridge"] == 1
    assert diagnostics["bundle_incomplete"]["reason_counts"]["weak_source_locality"] == 1
    assert diagnostics["bundle_incomplete"]["samples"][0][
        "average_selected_source_locality_score"
    ] == 0.35
    bundle_quality = diagnostics["bundle_quality_table"]
    assert bundle_quality["bundle_count"] == 2
    assert bundle_quality["avg_confidence_score"] == 0.52
    assert bundle_quality["avg_risk_penalty"] == 0.105
    assert bundle_quality["avg_bridge_count"] == 0.5
    assert bundle_quality["total_bridge_count"] == 1
    assert bundle_quality["bridge_bundle_count"] == 1
    assert bundle_quality["avg_causal_support_count"] == 0.5
    assert bundle_quality["total_causal_support_count"] == 1
    assert bundle_quality["causal_support_bundle_count"] == 1
    assert bundle_quality["avg_inference_support_count"] == 0.5
    assert bundle_quality["total_inference_support_count"] == 1
    assert bundle_quality["inference_support_bundle_count"] == 1
    assert bundle_quality["avg_location_support_count"] == 0.5
    assert bundle_quality["total_location_support_count"] == 1
    assert bundle_quality["location_support_bundle_count"] == 1
    assert bundle_quality["avg_preference_support_count"] == 0.5
    assert bundle_quality["total_preference_support_count"] == 1
    assert bundle_quality["preference_support_bundle_count"] == 1
    assert bundle_quality["avg_visual_support_count"] == 0.5
    assert bundle_quality["total_visual_support_count"] == 1
    assert bundle_quality["visual_support_bundle_count"] == 1
    assert bundle_quality["avg_contrast_count"] == 0.5
    assert bundle_quality["total_contrast_count"] == 1
    assert bundle_quality["contrast_bundle_count"] == 1
    assert bundle_quality["total_location_relation_category_hit_count"] == 1
    assert bundle_quality["avg_source_proximity_support_count"] == 0.5
    assert bundle_quality["total_source_proximity_support_count"] == 1
    assert bundle_quality["source_proximity_bundle_count"] == 1
    assert bundle_quality["avg_source_ref_support_item_count"] == 1.0
    assert bundle_quality["total_source_ref_support_item_count"] == 2
    assert bundle_quality["source_ref_support_bundle_count"] == 1
    assert bundle_quality["avg_source_ref_support_ref_count"] == 1.0
    assert bundle_quality["total_source_ref_support_ref_count"] == 2
    assert bundle_quality["avg_source_identity_support_item_count"] == 1.0
    assert bundle_quality["total_source_identity_support_item_count"] == 2
    assert bundle_quality["source_identity_support_bundle_count"] == 1
    assert bundle_quality["avg_source_identity_support_ref_count"] == 1.0
    assert bundle_quality["total_source_identity_support_ref_count"] == 2
    assert bundle_quality["avg_source_type_support_diversity"] == 1.0
    assert bundle_quality["max_source_type_support_diversity"] == 2
    assert bundle_quality["avg_retrieval_source_support_diversity"] == 1.0
    assert bundle_quality["max_retrieval_source_support_diversity"] == 2
    assert bundle_quality["avg_selected_source_locality_score"] == 0.625
    assert bundle_quality["avg_dropped_source_ref_overlap_count"] == 1.5
    assert bundle_quality["total_dropped_source_ref_overlap_count"] == 3
    assert bundle_quality["source_ref_overlap_drop_bundle_count"] == 2
    assert bundle_quality["top_dropped_source_ref_overlap_keys"] == {
        "D1:1": 1,
        "D2:3": 1,
        "D2:4": 1,
    }
    assert bundle_quality["avg_dropped_noisy_source_overlap_count"] == 1.0
    assert bundle_quality["total_dropped_noisy_source_overlap_count"] == 2
    assert bundle_quality["noisy_source_overlap_drop_bundle_count"] == 1
    assert bundle_quality["top_dropped_noisy_source_overlap_keys"] == {
        "D2:3": 1,
        "D2:4": 1,
    }
    assert bundle_quality["weak_bundle_count"] == 1
    assert bundle_quality["medium_or_high_bundle_count"] == 1
    assert bundle_quality["confidence_band_counts"] == {"high": 1, "low": 1}
    assert bundle_quality["risk_reason_counts"] == {
        "risk:all_broad_summary": 1,
        "risk:broad_summary": 1,
        "risk:low_answerability": 1,
    }
    assert bundle_quality["weak_samples"][0]["case_id"] == "fail"
    assert bundle_quality["weak_samples"][0]["confidence_band"] == "low"
    policy = diagnostics["policy_contribution_table"]["FocusedTurnPolicy"]
    assert policy["active_count"] == 1
    assert policy["reason_counts"]["focused_turn"] == 1
    feature_table = diagnostics["evidence_feature_table"]
    assert feature_table["candidate_count"] == 2
    assert feature_table["avg_answerability_score"] == 0.66
    assert feature_table["avg_source_locality_score"] == 0.675
    assert feature_table["low_answerability_count"] == 1
    assert feature_table["surface_counts"]["contrast_surface"] == 1
    assert feature_table["relation_category_counts"] == {
        "preference": 1,
        "temporal": 1,
    }
    assert feature_table["relation_category_hit_counts"] == {"preference": 1}
    assert feature_table["surface_counts"]["currentness_surface"] == 1
    assert feature_table["source_type_counts"] == {
        "chunk": 2,
        "raw_turn": 1,
    }
    assert feature_table["retrieval_source_counts"]["raw_turns"] == 1
    assert feature_table["retrieval_source_counts"]["semantic_chunks"] == 1
    assert feature_table["query_role_counts"] == {
        "multi_hop_bridge": 1,
        "temporal_support": 1,
    }
    assert feature_table["time_intent_kind_counts"] == {
        "duration": 1,
        "relative_time": 1,
    }
    assert feature_table["typed_temporal_surface_counts"] == {
        "has_duration_surface": 1,
        "has_explicit_time_content_surface": 1,
        "has_explicit_time_surface": 1,
        "has_relative_time_surface": 1,
    }
    assert feature_table["bridge_query_hit_count"] == 1
    assert feature_table["surface_counts"]["bridge_query_hit"] == 1
    assert feature_table["source_locality_reason_counts"] == {
        "broad_summary_locality_cap": 1,
        "broad_turn_refs": 1,
        "direct_localized_turn": 1,
    }
    lift_table = diagnostics["rerank_lift_table"]
    assert lift_table["boosted_candidate_count"] == 1
    assert lift_table["avg_positive_policy_score"] == 0.2
    assert lift_table["top_policy_counts"]["FocusedTurnPolicy"] == 1
    assert lift_table["top_policy_reason_counts"]["focused_turn"] == 1
    assert lift_table["relation_category_hit_counts"] == {"preference": 1}
    assert lift_table["direct_speaker_lift_count"] == 1
    assert lift_table["samples"][0]["query_roles"] == ("multi_hop_bridge",)
    assert lift_table["samples"][0]["bridge_query_hit"] is True
    query_roles = diagnostics["query_role_effectiveness_table"]
    assert query_roles["schema_version"] == "query_role_effectiveness.v1"
    assert query_roles["candidate_role_counts"] == {
        "multi_hop_bridge": 1,
        "temporal_support": 1,
    }
    assert query_roles["lifted_candidate_role_counts"] == {"multi_hop_bridge": 1}
    assert query_roles["selected_item_role_counts"] == {"multi_hop_bridge": 1}
    assert query_roles["candidate_role_family_counts"] == {
        "multi_hop": 1,
        "temporal_support": 1,
    }
    assert query_roles["lifted_candidate_role_family_counts"] == {"multi_hop": 1}
    assert query_roles["selected_item_role_family_counts"] == {"multi_hop": 1}
    assert query_roles["bridge_query_hit_candidate_counts"] == {"multi_hop_bridge": 1}
    assert query_roles["bridge_query_hit_selected_counts"] == {"multi_hop_bridge": 1}
    assert query_roles["roles_without_selected_items"] == ["temporal_support"]
    assert query_roles["roles_without_lifted_candidates"] == ["temporal_support"]
    assert query_roles["role_stats"]["multi_hop_bridge"] == {
        "candidate_count": 1,
        "lifted_candidate_count": 1,
        "selected_item_count": 1,
        "typed_relation_hit_count": 0,
        "typed_relation_lifted_hit_count": 0,
        "selection_rate": 1.0,
        "lifted_rate": 1.0,
        "typed_relation_hit_rate": 0.0,
        "bridge_query_hit_candidate_count": 1,
        "bridge_query_hit_selected_count": 1,
        "selected_low_answerability_count": 0,
        "selected_weak_source_locality_count": 0,
        "avg_candidate_answerability_score": 0.9,
        "avg_measured_candidate_answerability_score": 0.9,
        "candidate_unmeasured_answerability_count": 0,
        "avg_candidate_source_locality_score": 1.0,
        "avg_measured_candidate_source_locality_score": 1.0,
        "candidate_unmeasured_source_locality_count": 0,
        "avg_selected_answerability_score": 0.9,
        "avg_measured_selected_answerability_score": 0.9,
        "selected_unmeasured_answerability_count": 0,
        "avg_selected_source_locality_score": 0.0,
        "avg_measured_selected_source_locality_score": 0.0,
        "selected_unmeasured_source_locality_count": 0,
        "selected_bundle_role_counts": {"bridge": 1},
    }
    assert query_roles["role_stats"]["temporal_support"] == {
        "candidate_count": 1,
        "lifted_candidate_count": 0,
        "selected_item_count": 0,
        "typed_relation_hit_count": 0,
        "typed_relation_lifted_hit_count": 0,
        "selection_rate": 0.0,
        "lifted_rate": 0.0,
        "typed_relation_hit_rate": 0.0,
        "bridge_query_hit_candidate_count": 0,
        "bridge_query_hit_selected_count": 0,
        "selected_low_answerability_count": 0,
        "selected_weak_source_locality_count": 0,
        "avg_candidate_answerability_score": 0.42,
        "avg_measured_candidate_answerability_score": 0.42,
        "candidate_unmeasured_answerability_count": 0,
        "avg_candidate_source_locality_score": 0.35,
        "avg_measured_candidate_source_locality_score": 0.35,
        "candidate_unmeasured_source_locality_count": 0,
        "avg_selected_answerability_score": 0.0,
        "avg_measured_selected_answerability_score": 0.0,
        "selected_unmeasured_answerability_count": 0,
        "avg_selected_source_locality_score": 0.0,
        "avg_measured_selected_source_locality_score": 0.0,
        "selected_unmeasured_source_locality_count": 0,
        "selected_bundle_role_counts": {},
    }
    assert diagnostics["false_positive_categories"]["query_leakage_risk"] == 1
    assert diagnostics["query_leakage_report"]["clean"] is False
    assert diagnostics["query_leakage_report"]["query_overlap_case_count"] == 1


def test_quality_diagnostics_groups_profile_support_query_roles() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="profile-role",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("profile_fact",),
                    bundle_evidence_roles=("primary", "health_support"),
                    policy_score=0.25,
                    candidate_features={
                        "query_roles": ("health_support",),
                        "answerability_score": 0.8,
                        "source_locality_score": 0.9,
                    },
                    score_signals={
                        "benchmark_typed_relation_support_hit_roles": [
                            "health_support"
                        ],
                    },
                ),
                evidence_bundle={
                    "bundle_complete": True,
                    "evidence_term_count": 1,
                    "covered_evidence_terms": ["D1:1"],
                    "items": [
                        {
                            "role": "health_support",
                            "retrieval_order": 1,
                            "covered_evidence_terms": ["D1:1"],
                            "focused_evidence_score": 1.0,
                            "query_roles": ["health_support"],
                            "answerability_score": 0.82,
                            "source_locality_score": 0.88,
                        }
                    ],
                },
            ),
        )
    )

    query_roles = diagnostics["query_role_effectiveness_table"]

    assert query_roles["candidate_role_counts"] == {"health_support": 1}
    assert query_roles["lifted_candidate_role_counts"] == {"health_support": 1}
    assert query_roles["selected_item_role_counts"] == {"health_support": 1}
    assert query_roles["typed_relation_hit_role_counts"] == {"health_support": 1}
    assert query_roles["typed_relation_lifted_hit_role_counts"] == {
        "health_support": 1
    }
    assert query_roles["candidate_role_family_counts"] == {"relation_compact": 1}
    assert query_roles["lifted_candidate_role_family_counts"] == {
        "relation_compact": 1
    }
    assert query_roles["selected_item_role_family_counts"] == {
        "relation_compact": 1
    }
    assert query_roles["roles_without_selected_items"] == []
    assert query_roles["roles_without_typed_relation_hits"] == []
    assert query_roles["role_stats"]["health_support"]["selected_bundle_role_counts"] == {
        "health_support": 1
    }
    assert query_roles["role_stats"]["health_support"]["typed_relation_hit_count"] == 1


def test_quality_diagnostics_tracks_typed_relation_hit_roles_separately() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="mixed-profile-role",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("health_profile", "status_profile"),
                    bundle_evidence_roles=(
                        "primary",
                        "health_support",
                        "status_support",
                    ),
                    policy_score=0.25,
                    candidate_features={
                        "query_roles": ("health_support", "status_support"),
                        "answerability_score": 0.8,
                        "source_locality_score": 0.9,
                    },
                    score_signals={
                        "benchmark_typed_relation_support_hit_roles": [
                            "health_support"
                        ],
                    },
                ),
            ),
        )
    )

    query_roles = diagnostics["query_role_effectiveness_table"]

    assert query_roles["candidate_role_counts"] == {
        "health_support": 1,
        "status_support": 1,
    }
    assert query_roles["lifted_candidate_role_counts"] == {
        "health_support": 1,
        "status_support": 1,
    }
    assert query_roles["typed_relation_hit_role_counts"] == {"health_support": 1}
    assert query_roles["typed_relation_lifted_hit_role_counts"] == {
        "health_support": 1
    }
    assert query_roles["roles_without_typed_relation_hits"] == ["status_support"]
    assert query_roles["role_stats"]["health_support"]["typed_relation_hit_rate"] == 1.0
    assert query_roles["role_stats"]["status_support"]["typed_relation_hit_rate"] == 0.0


def test_quality_diagnostics_does_not_require_typed_hits_for_preference_support() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="preference-role",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary", "preference_support"),
                    policy_score=0.25,
                    candidate_features={
                        "query_roles": ("preference_support",),
                        "answerability_score": 0.8,
                        "source_locality_score": 0.9,
                    },
                ),
            ),
        )
    )

    query_roles = diagnostics["query_role_effectiveness_table"]

    assert query_roles["candidate_role_counts"] == {"preference_support": 1}
    assert query_roles["typed_relation_hit_role_counts"] == {}
    assert query_roles["roles_without_typed_relation_hits"] == []


def test_quality_diagnostics_false_positive_counts_typed_intent_leakage() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="intent-leak",
                score=0.0,
                retrieval=_retrieval_payload(
                    evidence_need=("single_fact",),
                    risk_flags=("wide_relation_expansion",),
                    retrieval_intent_overlap_count=2,
                    policy_score=0.0,
                ),
                evidence_bundle={"bundle_complete": True, "items": []},
                retrieval_quality={"expected_term_recall": 1.0},
            ),
        )
    )

    assert diagnostics["false_positive_categories"]["query_leakage_risk"] == 1
    assert diagnostics["query_leakage_report"]["clean"] is False
    assert diagnostics["query_leakage_report"][
        "retrieval_intent_overlap_case_count"
    ] == 1
    risk_stats = diagnostics["risk_flag_table"]["flag_stats"][
        "wide_relation_expansion"
    ]
    assert risk_stats["query_overlap_count"] == 0
    assert risk_stats["profile_overlap_count"] == 0
    assert risk_stats["retrieval_intent_overlap_count"] == 2
    assert risk_stats["query_leakage_count"] == 2
    assert risk_stats["samples"][0]["query_overlap_count"] == 2


def test_quality_diagnostics_per_intent_merges_profile_and_typed_intent() -> None:
    retrieval = _retrieval_payload(
        evidence_need=("single_fact",),
        bundle_evidence_roles=("primary",),
        relation_categories=("status_profile",),
        policy_score=0.0,
    )
    query_decomposition = retrieval["metadata"]["query_decomposition"]
    query_decomposition["retrieval_intent"]["evidence_need"] = [
        "single_fact",
        "visual_evidence",
    ]
    query_decomposition["retrieval_intent"]["bundle_evidence_roles"] = [
        "primary",
        "visual_support",
    ]
    query_decomposition["retrieval_intent"]["relations"] = {
        "intents": [{"category": "preference"}]
    }

    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="mixed-profile-intent-per-intent",
                group="single-hop",
                score=1.0,
                retrieval=retrieval,
            ),
        )
    )

    assert diagnostics["per_intent"]["need:single_fact"]["total"] == 1
    assert diagnostics["per_intent"]["need:visual_evidence"]["total"] == 1
    assert diagnostics["per_intent"]["role:primary"]["total"] == 1
    assert diagnostics["per_intent"]["role:visual_support"]["total"] == 1
    assert diagnostics["per_intent"]["relation:status_profile"]["total"] == 1
    assert diagnostics["per_intent"]["relation:preference"]["total"] == 1


def test_quality_diagnostics_per_intent_reads_query_expansion_intent() -> None:
    retrieval = _retrieval_payload(
        evidence_need=("single_fact",),
        bundle_evidence_roles=("primary",),
        relation_categories=("status_profile",),
        policy_score=0.0,
    )
    retrieval["metadata"]["query_expansion"] = {
        "retrieval_intent": {
            "evidence_need": ["visual_evidence"],
            "bundle_evidence_roles": ["visual_support"],
            "relations": {"intents": [{"category": "preference"}]},
            "time_intent": {"kind": "relative_time"},
        }
    }

    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="query-expansion-per-intent",
                group="single-hop",
                score=1.0,
                retrieval=retrieval,
            ),
        )
    )

    assert diagnostics["per_intent"]["need:single_fact"]["total"] == 1
    assert diagnostics["per_intent"]["need:visual_evidence"]["total"] == 1
    assert diagnostics["per_intent"]["role:primary"]["total"] == 1
    assert diagnostics["per_intent"]["role:visual_support"]["total"] == 1
    assert diagnostics["per_intent"]["relation:status_profile"]["total"] == 1
    assert diagnostics["per_intent"]["relation:preference"]["total"] == 1
    assert diagnostics["per_intent"]["time:relative_time"]["total"] == 1


def test_quality_diagnostics_reports_source_ref_provenance_table() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="fused-ref",
                retrieval={
                    "metadata": {},
                    "results": [
                        {
                            "id": "fused-evidence",
                            "rank": 1,
                            "source_refs": ["chunk-ref"],
                            "metadata": {
                                "diagnostics": {
                                    "benchmark_candidate_fusion": {
                                        "source_refs": ["chunk-ref", "D2:8"]
                                    }
                                }
                            },
                        }
                    ],
                },
                evidence_bundle={
                    "items": [
                        {
                            "id": "fused-evidence",
                            "role": "primary",
                            "retrieval_order": 1,
                            "source_refs": ["chunk-ref", "D2:8"],
                        }
                    ]
                },
            ),
            _item(
                case_id="missing-ref",
                retrieval={
                    "metadata": {},
                    "results": [
                        {
                            "id": "ref-less",
                            "rank": 1,
                            "metadata": {"diagnostics": {}},
                        }
                    ],
                },
                evidence_bundle={
                    "items": [
                        {
                            "id": "ref-less",
                            "role": "primary",
                            "retrieval_order": 1,
                        }
                    ]
                },
            ),
        )
    )

    table = diagnostics["source_ref_provenance_table"]
    assert table["schema_version"] == "source_ref_provenance.v1"
    assert table["retrieval_candidate_count"] == 2
    assert table["retrieval_source_ref_candidate_count"] == 1
    assert table["retrieval_source_ref_count"] == 2
    assert table["retrieval_source_refless_candidate_count"] == 1
    assert table["retrieval_source_ref_coverage_rate"] == 0.5
    assert table["fused_candidate_count"] == 1
    assert table["fused_source_ref_candidate_count"] == 1
    assert table["fused_source_ref_count"] == 2
    assert table["fused_ref_rescue_candidate_count"] == 1
    assert table["fused_ref_added_count"] == 1
    assert table["selected_bundle_item_count"] == 2
    assert table["selected_bundle_source_ref_item_count"] == 1
    assert table["selected_bundle_source_ref_count"] == 2
    assert table["selected_bundle_source_refless_item_count"] == 1
    assert table["selected_bundle_source_ref_coverage_rate"] == 0.5
    assert table["source_refless_selected_samples"] == [
        {
            "case_id": "missing-ref",
            "item_id": "ref-less",
            "role": "primary",
            "retrieval_order": 1,
        }
    ]


def test_quality_diagnostics_counts_source_ref_dedupe_identity() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="turn-ref-dedupe",
                retrieval={
                    "metadata": {},
                    "results": [
                        {
                            "id": "raw-turn",
                            "rank": 1,
                            "text": "D4:2 Caroline: I found the support group helpful.",
                            "metadata": {
                                "diagnostics": {
                                    "benchmark_candidate_features": {
                                        "source_ref_dedupe_key": (
                                            "source_turn_refs:D4:2"
                                        )
                                    }
                                }
                            },
                        }
                    ],
                },
                evidence_bundle={
                    "items": [
                        {
                            "id": "raw-turn",
                            "role": "primary",
                            "retrieval_order": 1,
                            "source_ref_dedupe_key": "source_turn_refs:D4:2",
                        }
                    ]
                },
            ),
        )
    )

    table = diagnostics["source_ref_provenance_table"]
    assert table["retrieval_source_ref_candidate_count"] == 1
    assert table["retrieval_source_ref_count"] == 1
    assert table["selected_bundle_source_ref_item_count"] == 1
    assert table["selected_bundle_source_ref_count"] == 1
    assert table["selected_bundle_source_refless_item_count"] == 0
    assert table["source_refless_selected_samples"] == []


def test_quality_diagnostics_counts_fusion_turn_ref_dedupe_identity() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="fusion-turn-ref-dedupe",
                retrieval={
                    "metadata": {},
                    "results": [
                        {
                            "id": "fused",
                            "rank": 1,
                            "metadata": {
                                "diagnostics": {
                                    "benchmark_candidate_fusion": {
                                        "dedupe_key": "turn_refs:D4:2|D4:3"
                                    }
                                }
                            },
                        }
                    ],
                },
                evidence_bundle={
                    "items": [
                        {
                            "id": "fused",
                            "role": "primary",
                            "retrieval_order": 1,
                            "source_ref_dedupe_key": "source_turn_refs:D4:3",
                        }
                    ]
                },
            ),
        )
    )

    table = diagnostics["source_ref_provenance_table"]
    assert table["retrieval_source_ref_candidate_count"] == 1
    assert table["retrieval_source_ref_count"] == 2
    assert table["selected_bundle_source_ref_item_count"] == 1
    assert table["selected_bundle_source_ref_count"] == 1
    assert table["selected_bundle_source_refless_item_count"] == 0


def test_quality_diagnostics_normalizes_fusion_canonical_source_refs() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="fusion-canonical-ref",
                retrieval={
                    "metadata": {},
                    "results": [
                        {
                            "id": "fused",
                            "rank": 1,
                            "metadata": {
                                "diagnostics": {
                                    "benchmark_candidate_fusion": {
                                        "source_refs": [
                                            "locomo:conv-19:session_4:D4:2:chunk"
                                        ]
                                    }
                                }
                            },
                        }
                    ],
                },
                evidence_bundle={
                    "items": [
                        {
                            "id": "fused",
                            "role": "primary",
                            "retrieval_order": 1,
                            "source_ref_dedupe_key": "source_turn_refs:D4:2",
                        }
                    ]
                },
            ),
        )
    )

    table = diagnostics["source_ref_provenance_table"]
    assert table["retrieval_source_ref_candidate_count"] == 1
    assert table["retrieval_source_ref_count"] == 2
    assert table["fused_source_ref_count"] == 1
    assert table["fused_ref_added_count"] == 1
    assert table["selected_bundle_source_ref_count"] == 1
    assert table["selected_bundle_source_refless_item_count"] == 0


def test_quality_diagnostics_reports_answer_context_provenance_table() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="bundle-context",
                cutoff_results={
                    "200": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 2,
                            "source_ref_count": 3,
                            "source_ref_item_count": 2,
                            "source_refless_item_count": 0,
                            "source_ref_coverage_rate": 1.0,
                            "bundle_source_type_support_diversity": 1,
                            "bundle_retrieval_source_support_diversity": 2,
                            "avg_answerability_score": 0.4,
                            "avg_measured_answerability_score": 0.8,
                            "unmeasured_answerability_count": 1,
                            "avg_source_locality_score": 0.35,
                            "avg_measured_source_locality_score": 0.7,
                            "unmeasured_source_locality_count": 1,
                            "backfilled_retrieval_item_count": 1,
                            "backfilled_precise_source_overlap_count": 1,
                            "skipped_duplicate_source_bundle_item_count": 1,
                            "skipped_noisy_overlap_bundle_item_count": 1,
                            "skipped_redundant_risky_backfill_count": 1,
                            "skipped_redundant_source_backfill_count": 1,
                            "skipped_redundant_role_backfill_count": 1,
                            "backfilled_broad_summary_count": 1,
                            "backfilled_conflict_or_stale_count": 0,
                            "backfilled_low_answerability_count": 1,
                            "backfilled_weak_source_locality_count": 1,
                            "backfilled_low_answerability_role_counts": {
                                "contrast": 1,
                            },
                            "backfilled_weak_source_locality_role_counts": {
                                "contrast": 1,
                            },
                            "backfilled_source_proximity_support_count": 1,
                            "backfilled_chained_source_proximity_support_count": 1,
                            "backfilled_source_proximity_closest_distance": 2,
                            "missing_required_roles": ["contrast"],
                            "risk_reason_codes": [
                                "risk:skipped_duplicate_source_bundle_item",
                                "risk:skipped_noisy_overlap_bundle_item",
                                "risk:retrieval_backfill",
                                "risk:backfilled_broad_summary",
                                "risk:backfilled_low_answerability",
                                "risk:backfilled_weak_source_locality",
                                "risk:skipped_redundant_risky_backfill",
                                "risk:skipped_redundant_source_backfill",
                                "risk:skipped_redundant_role_backfill",
                            ],
                        }
                    }
                },
            ),
            _item(
                case_id="fallback-context",
                cutoff_results={
                    "200": {
                        "answer_context": {
                            "source": "retrieval_slice",
                            "fallback_reason": "empty_bundle",
                            "memory_count": 3,
                            "source_ref_count": 1,
                            "source_ref_item_count": 1,
                            "source_refless_item_count": 2,
                            "source_ref_coverage_rate": 0.3333,
                        }
                    }
                },
            ),
        )
    )

    table = diagnostics["answer_context_provenance_table"]
    assert table["schema_version"] == "answer_context_provenance.v1"
    assert table["context_count"] == 2
    assert table["evidence_bundle_context_count"] == 1
    assert table["fallback_context_count"] == 1
    assert table["source_ref_context_count"] == 2
    assert table["source_refless_context_count"] == 1
    assert table["mixed_source_context_count"] == 1
    assert table["memory_count"] == 5
    assert table["source_ref_count"] == 4
    assert table["source_ref_item_count"] == 3
    assert table["source_refless_item_count"] == 2
    assert table["backfilled_context_count"] == 1
    assert table["duplicate_source_bundle_skip_context_count"] == 1
    assert table["noisy_overlap_bundle_skip_context_count"] == 1
    assert table["backfill_skip_context_count"] == 1
    assert table["backfilled_retrieval_item_count"] == 1
    assert table["skipped_duplicate_source_bundle_item_count"] == 1
    assert table["avg_skipped_duplicate_source_bundle_item_count"] == 0.5
    assert table["skipped_noisy_overlap_bundle_item_count"] == 1
    assert table["avg_skipped_noisy_overlap_bundle_item_count"] == 0.5
    assert table["skipped_redundant_risky_backfill_count"] == 1
    assert table["avg_skipped_redundant_risky_backfill_count"] == 0.5
    assert table["skipped_redundant_source_backfill_count"] == 1
    assert table["avg_skipped_redundant_source_backfill_count"] == 0.5
    assert table["skipped_redundant_role_backfill_count"] == 1
    assert table["avg_skipped_redundant_role_backfill_count"] == 0.5
    assert table["backfilled_broad_summary_count"] == 1
    assert table["backfilled_conflict_or_stale_count"] == 0
    assert table["backfilled_precise_source_overlap_count"] == 1
    assert table["avg_backfilled_precise_source_overlap_count"] == 0.5
    assert table["backfilled_low_answerability_count"] == 1
    assert table["avg_backfilled_low_answerability_count"] == 0.5
    assert table["backfilled_weak_source_locality_count"] == 1
    assert table["avg_backfilled_weak_source_locality_count"] == 0.5
    assert table["backfilled_low_answerability_role_counts"] == {"contrast": 1}
    assert table["backfilled_weak_source_locality_role_counts"] == {"contrast": 1}
    assert table["backfilled_source_proximity_support_count"] == 1
    assert table["avg_backfilled_source_proximity_support_count"] == 0.5
    assert table["backfilled_chained_source_proximity_support_count"] == 1
    assert table["avg_backfilled_chained_source_proximity_support_count"] == 0.5
    assert table["avg_backfilled_source_proximity_closest_distance"] == 2.0
    assert table["min_backfilled_source_proximity_closest_distance"] == 2
    assert table["avg_backfilled_retrieval_item_count"] == 0.5
    assert table["source_ref_context_rate"] == 1.0
    assert table["source_ref_item_coverage_rate"] == 0.6
    assert table["avg_context_answerability_score"] == 0.2
    assert table["avg_measured_context_answerability_score"] == 0.8
    assert table["total_unmeasured_context_answerability_count"] == 1
    assert table["avg_context_source_locality_score"] == 0.175
    assert table["avg_measured_context_source_locality_score"] == 0.7
    assert table["total_unmeasured_context_source_locality_count"] == 1
    assert table["avg_bundle_source_type_support_diversity"] == 0.5
    assert table["max_bundle_source_type_support_diversity"] == 1
    assert table["avg_bundle_retrieval_source_support_diversity"] == 1.0
    assert table["max_bundle_retrieval_source_support_diversity"] == 2
    assert table["source_counts"] == {
        "evidence_bundle": 1,
        "retrieval_slice": 1,
    }
    assert table["fallback_reason_counts"] == {"empty_bundle": 1}
    assert table["missing_required_role_context_count"] == 1
    assert table["missing_required_role_total"] == 1
    assert table["missing_required_role_counts"] == {"contrast": 1}
    assert table["backfilled_missing_required_role_counts"] == {"contrast": 1}
    assert table["risk_reason_counts"] == {
        "risk:backfilled_broad_summary": 1,
        "risk:backfilled_low_answerability": 1,
        "risk:backfilled_weak_source_locality": 1,
        "risk:retrieval_backfill": 1,
        "risk:skipped_duplicate_source_bundle_item": 1,
        "risk:skipped_noisy_overlap_bundle_item": 1,
        "risk:skipped_redundant_risky_backfill": 1,
        "risk:skipped_redundant_role_backfill": 1,
        "risk:skipped_redundant_source_backfill": 1,
    }
    assert table["backfilled_context_samples"] == [
        {
            "case_id": "bundle-context",
            "cutoff": "200",
            "source": "evidence_bundle",
            "memory_count": 2,
            "backfilled_retrieval_item_count": 1,
            "skipped_duplicate_source_bundle_item_count": 1,
            "skipped_noisy_overlap_bundle_item_count": 1,
            "skipped_redundant_risky_backfill_count": 1,
            "skipped_redundant_source_backfill_count": 1,
            "skipped_redundant_role_backfill_count": 1,
            "backfilled_broad_summary_count": 1,
            "backfilled_conflict_or_stale_count": 0,
            "backfilled_precise_source_overlap_count": 1,
            "backfilled_low_answerability_count": 1,
            "backfilled_weak_source_locality_count": 1,
            "backfilled_low_answerability_role_counts": {"contrast": 1},
            "backfilled_weak_source_locality_role_counts": {"contrast": 1},
            "backfilled_source_proximity_support_count": 1,
            "backfilled_chained_source_proximity_support_count": 1,
            "backfilled_source_proximity_closest_distance": 2,
            "missing_required_roles": ["contrast"],
            "risk_reason_codes": [
                "risk:skipped_duplicate_source_bundle_item",
                "risk:skipped_noisy_overlap_bundle_item",
                "risk:retrieval_backfill",
                "risk:backfilled_broad_summary",
                "risk:backfilled_low_answerability",
                "risk:backfilled_weak_source_locality",
                "risk:skipped_redundant_risky_backfill",
                "risk:skipped_redundant_source_backfill",
                "risk:skipped_redundant_role_backfill",
            ],
        }
    ]
    assert table["backfill_skip_context_samples"] == [
        {
            "case_id": "bundle-context",
            "cutoff": "200",
            "source": "evidence_bundle",
            "memory_count": 2,
            "backfilled_retrieval_item_count": 1,
            "skipped_redundant_risky_backfill_count": 1,
            "skipped_redundant_source_backfill_count": 1,
            "skipped_redundant_role_backfill_count": 1,
            "missing_required_roles": ["contrast"],
            "risk_reason_codes": [
                "risk:skipped_duplicate_source_bundle_item",
                "risk:skipped_noisy_overlap_bundle_item",
                "risk:retrieval_backfill",
                "risk:backfilled_broad_summary",
                "risk:backfilled_low_answerability",
                "risk:backfilled_weak_source_locality",
                "risk:skipped_redundant_risky_backfill",
                "risk:skipped_redundant_source_backfill",
                "risk:skipped_redundant_role_backfill",
            ],
        }
    ]
    assert table["duplicate_source_bundle_skip_context_samples"] == [
        {
            "case_id": "bundle-context",
            "cutoff": "200",
            "source": "evidence_bundle",
            "memory_count": 2,
            "skipped_duplicate_source_bundle_item_count": 1,
            "source_ref_count": 3,
            "source_ref_item_count": 2,
            "risk_reason_codes": [
                "risk:skipped_duplicate_source_bundle_item",
                "risk:skipped_noisy_overlap_bundle_item",
                "risk:retrieval_backfill",
                "risk:backfilled_broad_summary",
                "risk:backfilled_low_answerability",
                "risk:backfilled_weak_source_locality",
                "risk:skipped_redundant_risky_backfill",
                "risk:skipped_redundant_source_backfill",
                "risk:skipped_redundant_role_backfill",
            ],
        }
    ]
    assert table["noisy_overlap_bundle_skip_context_samples"] == [
        {
            "case_id": "bundle-context",
            "cutoff": "200",
            "source": "evidence_bundle",
            "memory_count": 2,
            "skipped_noisy_overlap_bundle_item_count": 1,
            "source_ref_count": 3,
            "source_ref_item_count": 2,
            "risk_reason_codes": [
                "risk:skipped_duplicate_source_bundle_item",
                "risk:skipped_noisy_overlap_bundle_item",
                "risk:retrieval_backfill",
                "risk:backfilled_broad_summary",
                "risk:backfilled_low_answerability",
                "risk:backfilled_weak_source_locality",
                "risk:skipped_redundant_risky_backfill",
                "risk:skipped_redundant_source_backfill",
                "risk:skipped_redundant_role_backfill",
            ],
        }
    ]
    assert table["source_refless_context_samples"] == [
        {
            "case_id": "fallback-context",
            "cutoff": "200",
            "source": "retrieval_slice",
            "memory_count": 3,
            "source_refless_item_count": 2,
            "fallback_reason": "empty_bundle",
        }
    ]
    assert table["mixed_source_context_samples"] == [
        {
            "case_id": "fallback-context",
            "cutoff": "200",
            "source": "retrieval_slice",
            "memory_count": 3,
            "source_ref_count": 1,
            "source_ref_item_count": 1,
            "source_refless_item_count": 2,
            "fallback_reason": "empty_bundle",
        }
    ]


def test_quality_diagnostics_derives_answer_context_risk_reasons_from_counts() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="legacy-context",
                cutoff_results={
                    "3": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 2,
                            "bundle_risk_reason_codes": [
                                "risk:missing_required_role",
                            ],
                            "backfilled_retrieval_item_count": 1,
                            "skipped_duplicate_source_bundle_item_count": 1,
                            "skipped_noisy_overlap_bundle_item_count": 1,
                            "skipped_redundant_risky_backfill_count": 1,
                            "skipped_redundant_source_backfill_count": 1,
                            "skipped_redundant_role_backfill_count": 1,
                            "backfilled_broad_summary_count": 1,
                            "backfilled_conflict_or_stale_count": 1,
                            "backfilled_low_answerability_count": 1,
                            "backfilled_weak_source_locality_count": 1,
                        }
                    }
                },
            ),
        )
    )

    table = diagnostics["answer_context_provenance_table"]
    expected_reasons = [
        "risk:missing_required_role",
        "risk:skipped_duplicate_source_bundle_item",
        "risk:skipped_noisy_overlap_bundle_item",
        "risk:retrieval_backfill",
        "risk:backfilled_broad_summary",
        "risk:backfilled_conflict_or_stale",
        "risk:backfilled_low_answerability",
        "risk:backfilled_weak_source_locality",
        "risk:skipped_redundant_risky_backfill",
        "risk:skipped_redundant_source_backfill",
        "risk:skipped_redundant_role_backfill",
    ]
    assert table["risk_reason_counts"] == {
        reason: 1 for reason in expected_reasons
    }
    assert table["backfilled_context_samples"][0]["risk_reason_codes"] == (
        expected_reasons
    )
    assert table["backfill_skip_context_samples"][0]["risk_reason_codes"] == (
        expected_reasons
    )


def test_quality_diagnostics_merges_explicit_and_derived_answer_context_risks() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="partial-context",
                cutoff_results={
                    "3": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 2,
                            "risk_reason_codes": ["risk:item_specific"],
                            "backfilled_retrieval_item_count": 1,
                            "skipped_duplicate_source_bundle_item_count": 1,
                            "backfilled_low_answerability_count": 1,
                        }
                    }
                },
            ),
        )
    )

    table = diagnostics["answer_context_provenance_table"]
    expected_reasons = [
        "risk:item_specific",
        "risk:skipped_duplicate_source_bundle_item",
        "risk:retrieval_backfill",
        "risk:backfilled_low_answerability",
    ]
    assert table["risk_reason_counts"] == {
        reason: 1 for reason in expected_reasons
    }
    assert table["backfilled_context_samples"][0]["risk_reason_codes"] == (
        expected_reasons
    )


def test_quality_diagnostics_does_not_flag_missing_bridge_when_bridge_is_present() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="incomplete-with-bridge",
                group="multi-hop",
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.5,
                    "missing_evidence_terms": ["D3:4"],
                },
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 2,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 1,
                    "query_support_term_recall": 0.8,
                    "bundle_planner": {
                        "average_selected_source_locality_score": 0.84,
                        "role_counts": {
                            "primary": 1,
                            "bridge": 1,
                            "temporal_support": 1,
                        },
                        "bundle_quality": _bundle_quality(
                            confidence_score=0.64,
                            confidence_band="medium",
                            reason_codes=(
                                "has_primary_evidence",
                                "has_bridge_evidence",
                            ),
                            selected_item_count=2,
                            primary_count=1,
                            supporting_count=1,
                            bridge_count=1,
                        ),
                    },
                    "items": [
                        {
                            "role": "primary",
                            "covered_evidence_terms": ["D1:1"],
                            "focused_evidence_score": 1.0,
                            "source_locality_score": 0.9,
                        },
                        {
                            "role": "bridge",
                            "planner_reason_codes": [
                                "multi_hop_bridge",
                                "bridge_entity_hits",
                                "bridge_relation_hits",
                                "duration_surface",
                            ],
                            "has_duration_surface": True,
                            "focused_evidence_score": 1.0,
                            "source_locality_score": 0.78,
                        },
                    ],
                },
            ),
        )
    )

    reason_counts = diagnostics["bundle_incomplete"]["reason_counts"]
    assert reason_counts["missing_evidence_refs"] == 1
    assert "missing_bridge" not in reason_counts
    assert "missing_bridge_entity" not in reason_counts
    assert "missing_bridge_relation" not in reason_counts
    assert "missing_temporal_bridge" not in reason_counts
    assert "weak_source_locality" not in reason_counts
    assert diagnostics["bundle_incomplete"]["samples"][0]["bundle_roles"] == [
        "bridge",
        "primary",
        "temporal_support",
    ]


def test_quality_diagnostics_reports_rerank_lifts_without_memory_text() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="lifted-low-answerability",
                retrieval=_retrieval_payload(
                    evidence_need=("contrast",),
                    relation_categories=("status_profile",),
                    policy_score=0.18,
                    item_id="broad-summary",
                    rank=3,
                    score=0.71,
                    memory_text=(
                        "Conversation summary: private source text should not be copied."
                    ),
                    stale_reason="older_generated_summary",
                    score_signals={
                        "benchmark_answerability_boost": 0.08,
                        "benchmark_effective_boost_cap": 0.24,
                        "benchmark_provenance_safety_cap_applied": True,
                        "benchmark_provenance_safety_reason_codes": [
                            "broad_summary_low_provenance_cap",
                            "low_answerability_cap",
                        ],
                        "benchmark_strong_relation_evidence": True,
                        "benchmark_uncapped_boost_cap": 0.5,
                        "ignored_zero_signal": 0.0,
                    },
                    candidate_features={
                        "source_type": "summary",
                        "relation_category_hits": ["status_profile"],
                        "answerability_score": 0.31,
                    },
                ),
            ),
            _item(
                case_id="not-lifted",
                retrieval=_retrieval_payload(
                    evidence_need=("single_fact",),
                    policy_score=0.0,
                    item_id="plain-hit",
                    score_signals={"ignored_zero_signal": 0.0},
                    candidate_features={
                        "source_type": "raw_turn",
                        "answerability_score": 0.92,
                    },
                ),
            ),
        )
    )

    lift_table = diagnostics["rerank_lift_table"]

    assert lift_table["boosted_candidate_count"] == 1
    assert lift_table["avg_positive_policy_score"] == 0.18
    assert lift_table["top_signal_counts"] == {
        "benchmark_answerability_boost": 1,
        "benchmark_effective_boost_cap": 1,
        "benchmark_provenance_safety_cap_applied": 1,
        "benchmark_strong_relation_evidence": 1,
        "benchmark_uncapped_boost_cap": 1,
    }
    assert lift_table["relation_category_hit_counts"] == {"status_profile": 1}
    assert lift_table["low_answerability_lift_count"] == 1
    assert lift_table["broad_summary_lift_count"] == 1
    assert lift_table["conflict_or_stale_lift_count"] == 1
    assert lift_table["provenance_safety_cap_count"] == 1
    assert lift_table["provenance_safety_reason_counts"] == {
        "broad_summary_low_provenance_cap": 1,
        "low_answerability_cap": 1,
    }
    assert lift_table["samples"] == [
        {
            "case_id": "lifted-low-answerability",
            "group": "multi-hop",
            "item_id": "broad-summary",
            "rank": 3,
            "score": 0.71,
            "positive_policy_score": 0.18,
            "policy_reasons": {"FocusedTurnPolicy": ["focused_turn"]},
            "top_signals": {
                "benchmark_answerability_boost": 0.08,
                "benchmark_effective_boost_cap": 0.24,
                "benchmark_provenance_safety_cap_applied": True,
                "benchmark_strong_relation_evidence": True,
                "benchmark_uncapped_boost_cap": 0.5,
            },
            "relation_category_hits": ("status_profile",),
            "answerability_score": 0.31,
            "source_type": "summary",
            "direct_speaker_turn": False,
            "broad_summary": True,
            "conflict_or_stale": True,
            "provenance_safety_cap_applied": True,
            "provenance_safety_reason_codes": (
                "broad_summary_low_provenance_cap",
                "low_answerability_cap",
            ),
            "effective_boost_cap": 0.24,
            "uncapped_boost_cap": 0.5,
        }
    ]
    assert "memory" not in lift_table["samples"][0]


def test_quality_diagnostics_reports_rerank_signal_selection_gaps() -> None:
    retrieval = _retrieval_payload(
        evidence_need=("single_fact",),
        policy_score=0.0,
    )
    retrieval["results"] = [
        _rerank_candidate_payload(
            item_id="selected-strong",
            rank=1,
            score=0.93,
            policy_score=0.11,
            score_signals={"benchmark_answerability_boost": 0.04},
            candidate_features={
                "answerability_score": 0.91,
                "source_locality_score": 0.86,
                "query_roles": ["primary"],
                "relation_category_hits": ["preference"],
            },
        ),
        _rerank_candidate_payload(
            item_id="selected-weak",
            rank=2,
            score=0.82,
            policy_score=0.0,
            score_signals={"benchmark_rank_penalty": -0.03},
            candidate_features={
                "answerability_score": 0.72,
                "source_locality_score": 0.64,
                "query_roles": ["supporting"],
            },
        ),
        _rerank_candidate_payload(
            item_id="unselected-positive",
            rank=3,
            score=0.79,
            policy_score=0.2,
            boosted=True,
            score_signals={
                "benchmark_answerability_boost": 0.08,
                "benchmark_effective_boost_cap": 0.18,
                "benchmark_rank_penalty": -0.02,
            },
            candidate_features={
                "answerability_score": 0.88,
                "source_locality_score": 0.81,
                "source_type": "raw_turn",
                "query_roles": ["bridge"],
                "relation_category_hits": ["preference"],
            },
        ),
    ]
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="rerank-gaps",
                evidence_bundle={
                    "items": [
                        {
                            "id": "selected-strong",
                            "role": "primary",
                            "retrieval_order": 1,
                            "answerability_score": 0.91,
                            "source_locality_score": 0.86,
                            "query_roles": ["primary"],
                            "planner_reason_codes": ["primary_signal"],
                        },
                        {
                            "id": "selected-weak",
                            "role": "supporting",
                            "retrieval_order": 2,
                            "answerability_score": 0.72,
                            "source_locality_score": 0.64,
                            "query_roles": ["supporting"],
                            "planner_reason_codes": ["support_signal"],
                        },
                    ]
                },
                retrieval=retrieval,
            ),
        )
    )

    gaps = diagnostics["rerank_signal_gap_breakdown"]

    assert gaps["schema_version"] == "rerank_signal_gaps.v1"
    assert gaps["candidate_count"] == 3
    assert gaps["selected_item_count"] == 2
    assert gaps["positive_rerank_candidate_count"] == 2
    assert gaps["positive_unselected_candidate_count"] == 1
    assert gaps["positive_unselected_case_count"] == 1
    assert gaps["selected_with_positive_rerank_count"] == 1
    assert gaps["selected_without_positive_rerank_count"] == 1
    assert gaps["selected_without_positive_rerank_case_count"] == 1
    assert gaps["positive_unselected_signal_counts"] == {
        "benchmark_answerability_boost": 1,
        "benchmark_effective_boost_cap": 1,
    }
    assert gaps["positive_unselected_cap_signal_counts"] == {
        "benchmark_effective_boost_cap": 1
    }
    assert gaps["positive_unselected_penalty_signal_counts"] == {
        "benchmark_rank_penalty": 1
    }
    assert gaps["selected_without_positive_reason_counts"] == {
        "no_positive_rerank_signal": 1
    }
    assert gaps["selected_without_positive_penalty_signal_counts"] == {
        "benchmark_rank_penalty": 1
    }
    assert gaps["positive_unselected_samples"] == [
        {
            "case_id": "rerank-gaps",
            "group": "multi-hop",
            "item_id": "unselected-positive",
            "rank": 3,
            "score": 0.79,
            "benchmark_rerank_boosted": True,
            "positive_policy_score": 0.2,
            "policy_reasons": {"FocusedTurnPolicy": ["focused_turn"]},
            "top_signals": {
                "benchmark_answerability_boost": 0.08,
                "benchmark_effective_boost_cap": 0.18,
            },
            "answerability_score": 0.88,
            "source_locality_score": 0.81,
            "source_type": "raw_turn",
            "query_roles": ("bridge",),
            "relation_category_hits": ("preference",),
            "cap_signals": {"benchmark_effective_boost_cap": 0.18},
            "penalty_signals": {"benchmark_rank_penalty": -0.02},
            "selected_item_ids": ["selected-strong", "selected-weak"],
        }
    ]
    assert gaps["selected_without_positive_samples"] == [
        {
            "case_id": "rerank-gaps",
            "group": "multi-hop",
            "item_id": "selected-weak",
            "reason": "no_positive_rerank_signal",
            "matched_retrieval_candidate": True,
            "role": "supporting",
            "retrieval_order": 2,
            "positive_policy_score": 0.0,
            "top_signals": {},
            "answerability_score": 0.72,
            "source_locality_score": 0.64,
            "source_type": "unknown",
            "query_roles": ("supporting",),
            "planner_reason_codes": ("support_signal",),
            "penalty_signals": {"benchmark_rank_penalty": -0.03},
        }
    ]


def test_fast_gate_metrics_includes_rerank_signal_gap_breakdown() -> None:
    retrieval = _retrieval_payload(
        evidence_need=("single_fact",),
        policy_score=0.0,
    )
    retrieval["results"] = [
        _rerank_candidate_payload(
            item_id="unselected-positive",
            rank=1,
            policy_score=0.12,
            score_signals={"benchmark_effective_boost_cap": 0.16},
        )
    ]

    gate = fast_gate_metrics(
        (
            _item(
                case_id="fast-gate-rerank-gap",
                evidence_bundle={
                    "bundle_complete": True,
                    "evidence_term_count": 1,
                    "covered_evidence_terms": ["D1:1"],
                    "items": [
                        {
                            "id": "selected-weak",
                            "retrieval_order": 1,
                            "covered_evidence_terms": ["D1:1"],
                            "focused_evidence_score": 1.0,
                        }
                    ],
                },
                retrieval=retrieval,
            ),
        ),
        expected_case_count=1,
    )

    gaps = gate["rerank_signal_gap_breakdown"]
    assert gaps["positive_unselected_candidate_count"] == 1
    assert gaps["selected_without_positive_rerank_count"] == 1


def test_quality_diagnostics_treats_zero_answerability_as_unmeasured() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="unmeasured-answerability",
                retrieval=_retrieval_payload(
                    evidence_need=("single_fact",),
                    policy_score=0.2,
                    candidate_features={
                        "answerability_score": 0.0,
                        "source_locality_score": 0.0,
                    },
                ),
            ),
            _item(
                case_id="measured-low-answerability",
                retrieval=_retrieval_payload(
                    evidence_need=("single_fact",),
                    policy_score=0.0,
                    candidate_features={
                        "answerability_score": 0.42,
                        "source_locality_score": 0.84,
                    },
                ),
            ),
        )
    )

    feature_table = diagnostics["evidence_feature_table"]
    lift_table = diagnostics["rerank_lift_table"]
    assert feature_table["candidate_count"] == 2
    assert feature_table["low_answerability_count"] == 1
    assert feature_table["unmeasured_answerability_count"] == 1
    assert feature_table["avg_measured_answerability_score"] == 0.42
    assert feature_table["unmeasured_source_locality_count"] == 1
    assert feature_table["avg_measured_source_locality_score"] == 0.84
    assert lift_table["boosted_candidate_count"] == 1
    assert lift_table["low_answerability_lift_count"] == 0


def test_quality_diagnostics_propagates_selected_evidence_risk_reasons() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="selected-risk",
                evidence_bundle={
                    "items": [
                        {
                            "id": "selected",
                            "role": "support",
                            "retrieval_order": 2,
                            "query_roles": ["contrast_support"],
                            "answerability_score": 0.54,
                            "source_locality_score": 0.44,
                            "planner_reason_codes": [
                                "role:support",
                                "risk:broad_summary",
                                "risk:conflict_or_stale",
                            ],
                            "risk_reason_codes": [
                                "risk:broad_summary",
                                "risk:selected_custom",
                            ],
                        }
                    ]
                },
            ),
        )
    )

    breakdown = gate["selected_evidence_weakness"]

    assert breakdown["reason_counts"] == {
        "selected_broad_summary": 1,
        "selected_conflict_or_stale": 1,
        "selected_low_answerability": 1,
        "selected_weak_source_locality": 1,
    }
    assert breakdown["risk_reason_counts"] == {
        "risk:broad_summary": 1,
        "risk:conflict_or_stale": 1,
        "risk:selected_custom": 1,
    }
    assert breakdown["samples"][0]["risk_reason_codes"] == [
        "risk:broad_summary",
        "risk:conflict_or_stale",
        "risk:selected_custom",
    ]
    assert breakdown["samples"][0]["broad_summary"] is True
    assert breakdown["samples"][0]["conflict_or_stale"] is True


def test_quality_diagnostics_reports_empty_bundle_quality_table() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(case_id="without-quality"),
        )
    )

    table = diagnostics["bundle_quality_table"]

    assert table["bundle_count"] == 0
    assert table["avg_confidence_score"] == 0.0
    assert table["avg_bridge_count"] == 0.0
    assert table["avg_selected_source_locality_score"] == 0.0
    assert table["weak_bundle_count"] == 0
    assert table["confidence_band_counts"] == {}
    assert table["weak_samples"] == []


def test_quality_diagnostics_reports_measured_bundle_score_averages() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="unmeasured-static",
                evidence_bundle={
                    "bundle_planner": {
                        "average_selected_source_locality_score": 0.0,
                        "average_measured_selected_source_locality_score": 0.0,
                        "unmeasured_selected_source_locality_count": 1,
                        "bundle_quality": _bundle_quality(
                            confidence_score=0.34,
                            confidence_band="low",
                            average_measured_answerability_score=0.0,
                            unmeasured_answerability_count=1,
                        ),
                    }
                },
            ),
            _item(
                case_id="measured-static",
                evidence_bundle={
                    "bundle_planner": {
                        "average_selected_source_locality_score": 0.84,
                        "average_measured_selected_source_locality_score": 0.84,
                        "unmeasured_selected_source_locality_count": 0,
                        "bundle_quality": _bundle_quality(
                            confidence_score=0.76,
                            confidence_band="high",
                            average_measured_answerability_score=0.72,
                            unmeasured_answerability_count=0,
                        ),
                    }
                },
            ),
        )
    )

    table = diagnostics["bundle_quality_table"]
    assert table["avg_selected_source_locality_score"] == 0.42
    assert table["avg_measured_selected_source_locality_score"] == 0.84
    assert table["total_unmeasured_selected_source_locality_count"] == 1
    assert table["avg_measured_answerability_score"] == 0.72
    assert table["total_unmeasured_answerability_count"] == 1


def test_fast_gate_metrics_passes_when_locomo_fast_thresholds_are_met() -> None:
    items = tuple(
        _item(
            case_id=f"case-{index}",
            evidence_bundle={
                "bundle_complete": True,
                "evidence_term_count": 1,
                "covered_evidence_terms": [f"D{index}:1"],
                "items": [
                    {
                        "retrieval_order": 1 if index <= 30 else 2,
                        "covered_evidence_terms": [f"D{index}:1"],
                        "focused_evidence_score": 1.0,
                    }
                ],
            },
        )
        for index in range(1, 41)
    )

    gate = fast_gate_metrics(items)

    assert gate["schema_version"] == "fast_gate.v1"
    assert gate["passed"] is True
    assert gate["ready_for_full_locomo"] is True
    assert gate["failed_gates"] == []
    assert gate["gates"]["all_refs_top1"]["actual"] == 30
    assert gate["gates"]["all_refs_top2"]["actual"] == 40
    assert gate["gates"]["query_profile_leakage_zero"]["passed"] is True
    assert gate["bundle_quality_gate_applied"] is False
    assert gate["bundle_gap_breakdown"]["incomplete_case_count"] == 0
    assert gate["bundle_gap_breakdown"]["bridge_gap_reason_counts"] == {}
    assert gate["query_role_gap_breakdown"]["schema_version"] == (
        "query_role_gap_breakdown.v1"
    )
    assert gate["query_role_gap_breakdown"]["role_gap_count"] == 0
    assert "bundle_quality_medium_or_high" not in gate["gates"]


def test_fast_gate_metrics_treats_required_role_gaps_as_incomplete() -> None:
    complete_items = [
        _item(
            case_id=f"case-{index}",
            evidence_bundle={
                "bundle_complete": True,
                "role_requirement_complete": True,
                "missing_required_roles": [],
                "evidence_term_count": 1,
                "covered_evidence_terms": [f"D{index}:1"],
                "items": [
                    {
                        "retrieval_order": 1,
                        "covered_evidence_terms": [f"D{index}:1"],
                        "focused_evidence_score": 1.0,
                    }
                ],
            },
        )
        for index in range(1, 39)
    ]
    top_level_gap = _item(
        case_id="top-level-role-gap",
        evidence_bundle={
            "bundle_complete": True,
            "role_requirement_complete": False,
            "missing_required_roles": ["temporal_support"],
            "evidence_term_count": 1,
            "covered_evidence_terms": ["D39:1"],
            "items": [
                {
                    "retrieval_order": 1,
                    "covered_evidence_terms": ["D39:1"],
                    "focused_evidence_score": 1.0,
                }
            ],
        },
    )
    planner_gap = _item(
        case_id="planner-role-gap",
        evidence_bundle={
            "bundle_complete": True,
            "evidence_term_count": 1,
            "covered_evidence_terms": ["D40:1"],
            "bundle_planner": {
                "role_requirement_complete": False,
                "missing_required_roles": ["location_support"],
            },
            "items": [
                {
                    "retrieval_order": 1,
                    "covered_evidence_terms": ["D40:1"],
                    "focused_evidence_score": 1.0,
                }
            ],
        },
    )

    gate = fast_gate_metrics(
        (*complete_items, top_level_gap, planner_gap),
        expected_case_count=40,
    )
    diagnostics = quality_diagnostics((*complete_items, top_level_gap, planner_gap))

    assert gate["gates"]["evidence_bundle_complete"]["actual"] == 38
    assert "evidence_bundle_complete" in gate["failed_gates"]
    assert gate["bundle_gap_breakdown"]["incomplete_case_count"] == 2
    assert gate["bundle_gap_breakdown"]["reason_counts"][
        "missing_required_temporal_support"
    ] == 1
    assert gate["bundle_gap_breakdown"]["reason_counts"][
        "missing_required_location_support"
    ] == 1
    assert diagnostics["per_intent"]["need:unknown"]["bundle_complete_rate"] == 0.95


def test_fast_gate_metrics_fails_when_thresholds_or_leakage_fail() -> None:
    items = tuple(
        _item(
            case_id=f"case-{index}",
            retrieval=_retrieval_payload(
                evidence_need=("single_fact",),
                policy_score=0.0,
                risk_flags=("broad_query",) if index == 1 else (),
                query_overlap_count=1 if index == 1 else 0,
            ),
            evidence_bundle={
                "bundle_complete": index <= 20,
                "evidence_term_count": 1,
                "covered_evidence_terms": [f"D{index}:1"] if index <= 10 else [],
                "items": [
                    {
                        "retrieval_order": 6,
                        "covered_evidence_terms": [f"D{index}:1"] if index <= 10 else [],
                        "focused_evidence_score": 0.0,
                    }
                ],
            },
            retrieval_quality={
                "expected_term_recall": 1.0,
                "evidence_term_recall": 0.0,
                "missing_evidence_terms": [] if index <= 10 else [f"D{index}:1"],
            },
        )
        for index in range(1, 41)
    )

    gate = fast_gate_metrics(items)

    assert gate["passed"] is False
    assert gate["ready_for_full_locomo"] is False
    assert "query_profile_leakage_zero" in gate["failed_gates"]
    assert "all_refs_top5" in gate["failed_gates"]
    assert "evidence_bundle_complete" in gate["failed_gates"]
    assert gate["query_overlap_count"] == 1
    assert gate["risk_flag_table"]["flag_counts"] == {"broad_query": 1}
    assert gate["risk_flag_table"]["flag_stats"]["broad_query"][
        "query_overlap_count"
    ] == 1
    assert gate["bundle_gap_breakdown"]["incomplete_case_count"] == 20
    assert gate["bundle_gap_breakdown"]["bridge_gap_reason_counts"] == {
        "missing_bridge": 20,
        "missing_bridge_entity": 20,
        "missing_bridge_relation": 20,
    }


def test_fast_gate_metrics_ignores_unscored_bundle_completion() -> None:
    scored_items = tuple(
        _item(
            case_id=f"scored-{index}",
            evidence_bundle={
                "bundle_complete": index != 40,
                "evidence_term_count": 1,
                "covered_evidence_terms": [f"D{index}:1"],
                "items": [
                    {
                        "retrieval_order": 1,
                        "covered_evidence_terms": [f"D{index}:1"],
                        "focused_evidence_score": 1.0,
                    }
                ],
            },
        )
        for index in range(1, 41)
    )
    unscored_item = _item(
        case_id="unscored-complete",
        scored=False,
        evidence_bundle={"bundle_complete": True},
    )

    gate = fast_gate_metrics((*scored_items, unscored_item))

    assert gate["evaluation_count"] == 40
    assert gate["gates"]["evidence_bundle_complete"]["actual"] == 39
    assert "evidence_bundle_complete" in gate["failed_gates"]


def test_fast_gate_metrics_reports_bundle_gap_breakdown() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="weak-multi-hop",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D2:3"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 0,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.0,
                    "covered_evidence_terms": [],
                    "bundle_planner": {
                        "average_selected_source_locality_score": 0.35,
                    },
                    "items": [
                        {
                            "role": "supporting",
                            "retrieval_order": 6,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 0.0,
                            "source_locality_score": 0.35,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["schema_version"] == "bundle_gap_breakdown.v1"
    assert breakdown["incomplete_case_count"] == 1
    assert breakdown["bridge_gap_reason_counts"] == {
        "missing_bridge": 1,
        "missing_bridge_entity": 1,
        "missing_bridge_relation": 1,
        "missing_temporal_bridge": 1,
        "weak_source_locality": 1,
    }
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_temporal_support": 1
    }
    assert breakdown["samples"][0]["case_id"] == "weak-multi-hop"
    assert breakdown["samples"][0]["average_selected_source_locality_score"] == 0.35
    assert breakdown["samples"][0][
        "average_measured_selected_source_locality_score"
    ] == 0.35
    assert breakdown["samples"][0]["unmeasured_selected_source_locality_count"] == 0


def test_fast_gate_metrics_uses_measured_locality_for_bundle_gaps() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="mixed-locality",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 2,
                    "covered_evidence_terms": [],
                    "bundle_planner": {
                        "average_selected_source_locality_score": 0.42,
                        "average_measured_selected_source_locality_score": 0.84,
                        "unmeasured_selected_source_locality_count": 1,
                    },
                    "items": [
                        {
                            "role": "supporting",
                            "source_locality_score": 0.0,
                        },
                        {
                            "role": "supporting",
                            "source_locality_score": 0.84,
                        },
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "weak_source_locality" not in breakdown["bridge_gap_reason_counts"]
    assert breakdown["samples"][0]["average_selected_source_locality_score"] == 0.42
    assert breakdown["samples"][0][
        "average_measured_selected_source_locality_score"
    ] == 0.84
    assert breakdown["samples"][0]["unmeasured_selected_source_locality_count"] == 1


def test_fast_gate_metrics_reports_answerability_gap_breakdown() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-typed-evidence",
                group="open-domain",
                retrieval=_retrieval_payload(
                    evidence_need=("inference_support",),
                    relation_categories=("preference", "contrast"),
                    policy_score=0.0,
                    item_id="topic-only",
                    candidate_features={
                        "answerability_score": 0.42,
                        "source_locality_score": 0.9,
                        "answerability_reason_codes": [
                            "missing_preference_evidence",
                            "missing_contrast_evidence",
                            "low_answerability",
                        ],
                        "relation_categories": ["preference", "contrast"],
                        "relation_category_hits": [],
                        "query_roles": ["compact_relation"],
                    },
                ),
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["answerability_gap_breakdown"]

    assert breakdown["schema_version"] == "answerability_gap_breakdown.v1"
    assert breakdown["gap_candidate_count"] == 1
    assert breakdown["gap_case_count"] == 1
    assert breakdown["lifted_gap_candidate_count"] == 0
    assert breakdown["lifted_gap_case_count"] == 0
    assert breakdown["reason_counts"] == {
        "missing_contrast_evidence": 1,
        "missing_preference_evidence": 1,
    }
    assert breakdown["lifted_reason_counts"] == {}
    assert breakdown["category_counts"] == {"contrast": 1, "preference": 1}
    assert breakdown["lifted_category_counts"] == {}
    assert breakdown["samples"][0]["case_id"] == "missing-typed-evidence"
    assert breakdown["samples"][0]["memory_id"] == "topic-only"
    assert breakdown["samples"][0]["lifted"] is False
    assert breakdown["samples"][0]["positive_policy_score"] == 0
    assert breakdown["samples"][0]["answerability_score"] == 0.42
    assert breakdown["samples"][0]["relation_categories"] == [
        "preference",
        "contrast",
    ]


def test_fast_gate_metrics_blocks_lifted_answerability_gaps() -> None:
    items = tuple(
        _item(
            case_id=f"case-{index}",
            evidence_bundle={
                "bundle_complete": True,
                "evidence_term_count": 1,
                "covered_evidence_terms": [f"D{index}:1"],
                "items": [
                    {
                        "retrieval_order": 1 if index <= 30 else 2,
                        "covered_evidence_terms": [f"D{index}:1"],
                        "focused_evidence_score": 1.0,
                    }
                ],
            },
            retrieval=_retrieval_payload(
                evidence_need=("health_support",),
                policy_score=0.2 if index == 1 else 0.0,
                item_id=f"candidate-{index}",
                candidate_features={
                    "answerability_score": 0.35,
                    "source_locality_score": 0.8,
                    "answerability_reason_codes": ["missing_health_evidence"],
                    "relation_categories": ["health"],
                    "relation_category_hits": [],
                }
                if index == 1
                else {},
            ),
        )
        for index in range(1, 41)
    )

    gate = fast_gate_metrics(items)
    breakdown = gate["answerability_gap_breakdown"]

    assert gate["passed"] is False
    assert gate["ready_for_full_locomo"] is False
    assert "lifted_answerability_gaps_clear" in gate["failed_gates"]
    assert gate["gates"]["lifted_answerability_gaps_clear"]["actual"] == 1
    assert breakdown["gap_candidate_count"] == 1
    assert breakdown["lifted_gap_candidate_count"] == 1
    assert breakdown["lifted_reason_counts"] == {"missing_health_evidence": 1}
    assert breakdown["lifted_category_counts"] == {"health": 1}
    assert breakdown["samples"][0]["lifted"] is True
    assert breakdown["samples"][0]["positive_policy_score"] == 0.2


def test_fast_gate_metrics_reports_bundle_support_summaries() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="complete-supported",
                evidence_bundle={
                    "bundle_complete": True,
                    "evidence_term_count": 1,
                    "covered_evidence_terms": ["D1:1"],
                    "bundle_planner": {
                        "bundle_quality": _bundle_quality(
                            confidence_score=0.86,
                            confidence_band="high",
                            selected_item_count=3,
                            primary_count=1,
                            supporting_count=2,
                            bridge_count=1,
                            causal_support_count=1,
                            event_support_count=1,
                            exchange_support_count=1,
                            inference_support_count=1,
                            location_support_count=1,
                            emotion_response_support_count=1,
                            symbolic_meaning_support_count=1,
                            preference_support_count=1,
                            visual_support_count=1,
                            contrast_count=1,
                            source_proximity_support_count=2,
                            source_proximity_closest_distance=1,
                            source_proximity_distance_counts={"1": 1, "3": 1},
                            source_identity_item_count=2,
                            source_identity_ref_count=3,
                        )
                    },
                    "items": [
                        {
                            "retrieval_order": 1,
                            "covered_evidence_terms": ["D1:1"],
                            "focused_evidence_score": 1.0,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    assert gate["bundle_quality_gate_applied"] is True
    assert gate["bundle_support_counts"] == {
        "bridge": 1,
        "causal": 1,
        "communication": 0,
        "contrast": 1,
        "emotion_response": 1,
        "event": 1,
        "exchange": 1,
        "inference": 1,
        "location": 1,
        "preference": 1,
        "source_proximity": 2,
        "symbolic_meaning": 1,
        "visual": 1,
    }
    assert gate["bundle_support_bundle_counts"] == {
        "bridge": 1,
        "causal": 1,
        "communication": 0,
        "contrast": 1,
        "emotion_response": 1,
        "event": 1,
        "exchange": 1,
        "inference": 1,
        "location": 1,
        "preference": 1,
        "source_proximity": 1,
        "symbolic_meaning": 1,
        "visual": 1,
    }
    assert gate["bundle_source_proximity"] == {
        "support_count": 2,
        "bundle_count": 1,
        "avg_support_count": 2.0,
        "avg_closest_distance": 1.0,
        "closest_distance_min": 1.0,
        "distance_counts": {"1": 1, "3": 1},
    }
    assert gate["bundle_source_identity"] == {
        "item_count": 2,
        "ref_count": 3,
        "bundle_count": 1,
        "avg_item_count": 2.0,
        "avg_ref_count": 3.0,
    }


def test_fast_gate_metrics_reports_candidate_fusion_summary() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="fusion-1",
                retrieval={
                    "metadata": {
                        "multi_query_merge": {
                            "raw_result_count": 6,
                            "unique_result_count": 4,
                            "duplicate_result_count": 2,
                            "multi_query_hit_count": 2,
                            "bridge_query_hit_count": 1,
                            "lower_score_evidence_selection_count": 1,
                            "source_type_evidence_selection_count": 1,
                            "focused_query_evidence_selection_count": 0,
                            "query_role_counts": {
                                "original_question": 4,
                                "location_support": 2,
                            },
                            "score_winner_query_role_counts": {
                                "original_question": 1,
                            },
                            "selected_evidence_query_role_counts": {
                                "location_support": 1,
                            },
                            "focused_query_evidence_selection_role_counts": {
                                "location_support": 1,
                            },
                            "max_query_match_count": 3,
                            "max_source_diversity_count": 2,
                            "max_rrf_score": 0.047,
                        }
                    },
                    "results": [],
                },
            ),
            _item(
                case_id="fusion-2",
                retrieval={
                    "metadata": {
                        "multi_query_merge": {
                            "raw_result_count": 3,
                            "unique_result_count": 2,
                            "duplicate_result_count": 1,
                            "multi_query_hit_count": 1,
                            "lower_score_evidence_selection_count": 1,
                            "source_type_evidence_selection_count": 0,
                            "focused_query_evidence_selection_count": 1,
                            "query_role_counts": {
                                "original_question": 2,
                                "contrast_support": 1,
                            },
                            "score_winner_query_role_counts": {
                                "original_question": 1,
                            },
                            "selected_evidence_query_role_counts": {
                                "contrast_support": 1,
                            },
                            "focused_query_evidence_selection_role_counts": {
                                "contrast_support": 1,
                            },
                            "max_query_match_count": 2,
                            "max_source_diversity_count": 3,
                            "max_rrf_score": 0.061,
                        }
                    },
                    "results": [],
                },
            ),
        ),
        expected_case_count=2,
    )

    assert gate["candidate_fusion"] == {
        "evaluation_count": 2,
        "raw_result_count": 9,
        "unique_result_count": 6,
        "duplicate_result_count": 3,
        "multi_query_hit_count": 3,
        "bridge_query_hit_count": 1,
        "lower_score_evidence_selection_count": 2,
        "source_type_evidence_selection_count": 1,
        "focused_query_evidence_selection_count": 1,
        "query_role_counts": {
            "contrast_support": 1,
            "location_support": 2,
            "original_question": 6,
        },
        "score_winner_query_role_counts": {
            "original_question": 2,
        },
        "selected_evidence_query_role_counts": {
            "contrast_support": 1,
            "location_support": 1,
        },
        "focused_query_evidence_selection_role_counts": {
            "contrast_support": 1,
            "location_support": 1,
        },
        "max_query_match_count": 3,
        "max_source_diversity_count": 3,
        "max_rrf_score": 0.061,
    }


def test_fast_gate_metrics_reports_missing_required_bundle_roles() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-required-bridge",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("multi_hop",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 1.0,
                    "evidence_term_recall": 0.0,
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.8,
                    "missing_required_roles": ["bridge"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_required_bridge"] == 1
    assert breakdown["evidence_need_gap_reason_counts"]["missing_required_bridge"] == 1
    assert "missing_required_bridge" in breakdown["samples"][0]["reasons"]


def test_query_plan_integrity_maps_location_required_role_to_query_family() -> None:
    missing_location_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 1,
        "dropped_query_count": 0,
        "selected_roles": ["original_question"],
        "dropped_roles": [],
        "recommended_role_families": ["base_query", "location_support"],
        "selected_role_families": ["base_query"],
        "missing_recommended_role_families": ["location_support"],
        "role_family_counts": {"base_query": 1, "location_support": 1},
        "selected_role_family_counts": {"base_query": 1},
        "dropped_role_family_counts": {},
        "candidate_type_counts": {"semantic": 1, "lexical": 1},
        "selected_type_counts": {"semantic": 1},
        "fanout_integrity": {"bounded": True},
    }
    location_plan = {
        **missing_location_plan,
        "selected_query_count": 2,
        "selected_roles": ["original_question", "location_support"],
        "selected_role_families": ["base_query", "location_support"],
        "missing_recommended_role_families": [],
        "selected_role_family_counts": {
            "base_query": 1,
            "location_support": 1,
        },
        "selected_type_counts": {"semantic": 1, "lexical": 1},
    }

    missing_item = _item(
        case_id="missing-location-query",
        group="single-hop",
        retrieval=_retrieval_payload(
            evidence_need=("location_support",),
            bundle_evidence_roles=("primary", "location_support"),
            relation_categories=("location_transition",),
            policy_score=0.0,
            query_plan=missing_location_plan,
        ),
    )
    satisfied_item = _item(
        case_id="has-location-query",
        group="single-hop",
        retrieval=_retrieval_payload(
            evidence_need=("location_support",),
            bundle_evidence_roles=("primary", "location_support"),
            relation_categories=("location_transition",),
            policy_score=0.0,
            query_plan=location_plan,
        ),
    )

    diagnostics = quality_diagnostics((missing_item, satisfied_item))
    table = diagnostics["query_plan_integrity_table"]

    assert table["missing_evidence_role_query_family_counts"] == {
        "location_support": 1
    }
    assert table["samples"][0]["missing_evidence_role_query_families"] == (
        "location_support",
    )


def test_query_plan_integrity_maps_preference_and_visual_support_roles() -> None:
    base_only_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 1,
        "dropped_query_count": 0,
        "selected_roles": ["original_question"],
        "dropped_roles": [],
        "recommended_role_families": ["base_query"],
        "selected_role_families": ["base_query"],
        "missing_recommended_role_families": [],
        "selected_role_family_counts": {"base_query": 1},
        "fanout_integrity": {"bounded": True},
    }
    preference_item = _item(
        case_id="has-preference-query-family",
        group="single-hop",
        retrieval=_retrieval_payload(
            evidence_need=("preference",),
            bundle_evidence_roles=("primary", "preference_support"),
            relation_categories=("preference",),
            policy_score=0.0,
            query_plan=base_only_plan,
        ),
    )
    visual_item = _item(
        case_id="missing-visual-query-family",
        group="single-hop",
        retrieval=_retrieval_payload(
            evidence_need=("visual_evidence",),
            bundle_evidence_roles=("primary", "visual_support"),
            relation_categories=("visual",),
            policy_score=0.0,
            query_plan=base_only_plan,
        ),
    )

    diagnostics = quality_diagnostics((preference_item, visual_item))
    table = diagnostics["query_plan_integrity_table"]

    assert table["missing_evidence_role_query_family_counts"] == {
        "visual_support": 1
    }
    assert table["samples"][0]["case_id"] == "missing-visual-query-family"
    assert table["samples"][0]["missing_evidence_role_query_families"] == (
        "visual_support",
    )


def test_query_plan_integrity_merges_required_roles_from_profile_and_intent() -> None:
    base_only_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 1,
        "dropped_query_count": 0,
        "selected_roles": ["original_question"],
        "dropped_roles": [],
        "recommended_role_families": ["base_query"],
        "selected_role_families": ["base_query"],
        "missing_recommended_role_families": [],
        "selected_role_family_counts": {"base_query": 1},
        "fanout_integrity": {"bounded": True},
    }
    retrieval = _retrieval_payload(
        evidence_need=(),
        bundle_evidence_roles=("primary",),
        relation_categories=(),
        policy_score=0.0,
        query_plan=base_only_plan,
    )
    query_decomposition = retrieval["metadata"]["query_decomposition"]
    query_decomposition["retrieval_intent"]["bundle_evidence_roles"] = [
        "primary",
        "visual_support",
    ]

    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="intent-only-required-visual-role",
                group="single-hop",
                retrieval=retrieval,
            ),
        )
    )
    table = diagnostics["query_plan_integrity_table"]

    assert table["missing_evidence_role_query_family_counts"] == {
        "visual_support": 1
    }
    assert table["samples"][0]["required_evidence_roles"] == (
        "primary",
        "visual_support",
    )
    assert table["samples"][0]["missing_evidence_role_query_families"] == (
        "visual_support",
    )


def test_query_plan_integrity_reads_query_expansion_plan_and_roles() -> None:
    base_only_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 1,
        "dropped_query_count": 0,
        "selected_roles": ["original_question"],
        "dropped_roles": [],
        "recommended_role_families": ["base_query"],
        "selected_role_families": ["base_query"],
        "missing_recommended_role_families": [],
        "selected_role_family_counts": {"base_query": 1},
        "fanout_integrity": {"bounded": True},
    }
    retrieval = _retrieval_payload(
        evidence_need=(),
        bundle_evidence_roles=("primary",),
        relation_categories=(),
        policy_score=0.0,
    )
    retrieval["metadata"]["query_expansion"] = {
        "query_plan": base_only_plan,
        "retrieval_intent": {
            "bundle_evidence_roles": ["primary", "visual_support"]
        },
    }

    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="expansion-only-required-visual-role",
                group="single-hop",
                retrieval=retrieval,
            ),
        )
    )
    table = diagnostics["query_plan_integrity_table"]

    assert table["plan_count"] == 1
    assert table["missing_evidence_role_query_family_counts"] == {
        "visual_support": 1
    }
    assert table["samples"][0]["case_id"] == "expansion-only-required-visual-role"
    assert table["samples"][0]["required_evidence_roles"] == (
        "primary",
        "visual_support",
    )
    assert table["samples"][0]["missing_evidence_role_query_families"] == (
        "visual_support",
    )


def test_query_plan_integrity_maps_emotion_response_support_role() -> None:
    base_only_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 1,
        "dropped_query_count": 0,
        "selected_roles": ["original_question"],
        "dropped_roles": [],
        "recommended_role_families": ["base_query", "relation_compact"],
        "selected_role_families": ["base_query"],
        "missing_recommended_role_families": ["relation_compact"],
        "selected_role_family_counts": {"base_query": 1},
        "fanout_integrity": {"bounded": True},
    }
    relation_plan = {
        **base_only_plan,
        "selected_query_count": 2,
        "selected_roles": ["original_question", "compact_relation"],
        "selected_role_families": ["base_query", "relation_compact"],
        "missing_recommended_role_families": [],
        "selected_role_family_counts": {
            "base_query": 1,
            "relation_compact": 1,
        },
    }
    missing_item = _item(
        case_id="missing-emotion-query-family",
        group="single-hop",
        retrieval=_retrieval_payload(
            evidence_need=("emotion_response",),
            bundle_evidence_roles=("primary", "emotion_response_support"),
            relation_categories=("emotion_response",),
            policy_score=0.0,
            query_plan=base_only_plan,
        ),
    )
    satisfied_item = _item(
        case_id="has-emotion-query-family",
        group="single-hop",
        retrieval=_retrieval_payload(
            evidence_need=("emotion_response",),
            bundle_evidence_roles=("primary", "emotion_response_support"),
            relation_categories=("emotion_response",),
            policy_score=0.0,
            query_plan=relation_plan,
        ),
    )

    diagnostics = quality_diagnostics((missing_item, satisfied_item))
    table = diagnostics["query_plan_integrity_table"]

    assert table["missing_evidence_role_query_family_counts"] == {
        "emotion_response_support": 1
    }
    assert table["samples"][0]["case_id"] == "missing-emotion-query-family"
    assert table["samples"][0]["missing_evidence_role_query_families"] == (
        "emotion_response_support",
    )


def test_query_plan_integrity_maps_symbolic_meaning_support_role() -> None:
    base_only_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 1,
        "dropped_query_count": 0,
        "selected_roles": ["original_question"],
        "dropped_roles": [],
        "recommended_role_families": ["base_query", "relation_compact"],
        "selected_role_families": ["base_query"],
        "missing_recommended_role_families": ["relation_compact"],
        "selected_role_family_counts": {"base_query": 1},
        "fanout_integrity": {"bounded": True},
    }
    relation_plan = {
        **base_only_plan,
        "selected_query_count": 2,
        "selected_roles": ["original_question", "compact_relation"],
        "selected_role_families": ["base_query", "relation_compact"],
        "missing_recommended_role_families": [],
        "selected_role_family_counts": {
            "base_query": 1,
            "relation_compact": 1,
        },
    }
    missing_item = _item(
        case_id="missing-symbolic-query-family",
        group="single-hop",
        retrieval=_retrieval_payload(
            evidence_need=("symbolic_meaning",),
            bundle_evidence_roles=("primary", "symbolic_meaning_support"),
            relation_categories=("symbolic_meaning",),
            policy_score=0.0,
            query_plan=base_only_plan,
        ),
    )
    satisfied_item = _item(
        case_id="has-symbolic-query-family",
        group="single-hop",
        retrieval=_retrieval_payload(
            evidence_need=("symbolic_meaning",),
            bundle_evidence_roles=("primary", "symbolic_meaning_support"),
            relation_categories=("symbolic_meaning",),
            policy_score=0.0,
            query_plan=relation_plan,
        ),
    )

    diagnostics = quality_diagnostics((missing_item, satisfied_item))
    table = diagnostics["query_plan_integrity_table"]

    assert table["missing_evidence_role_query_family_counts"] == {
        "symbolic_meaning_support": 1
    }
    assert table["samples"][0]["case_id"] == "missing-symbolic-query-family"
    assert table["samples"][0]["missing_evidence_role_query_families"] == (
        "symbolic_meaning_support",
    )


def test_query_plan_integrity_maps_event_support_role() -> None:
    base_only_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 1,
        "dropped_query_count": 0,
        "selected_roles": ["original_question"],
        "dropped_roles": [],
        "recommended_role_families": ["base_query", "relation_compact"],
        "selected_role_families": ["base_query"],
        "missing_recommended_role_families": ["relation_compact"],
        "selected_role_family_counts": {"base_query": 1},
        "fanout_integrity": {"bounded": True},
    }
    relation_plan = {
        **base_only_plan,
        "selected_query_count": 2,
        "selected_roles": ["original_question", "compact_relation"],
        "selected_role_families": ["base_query", "relation_compact"],
        "missing_recommended_role_families": [],
        "selected_role_family_counts": {
            "base_query": 1,
            "relation_compact": 1,
        },
    }
    missing_item = _item(
        case_id="missing-event-query-family",
        group="single-hop",
        retrieval=_retrieval_payload(
            evidence_need=("registration_event",),
            bundle_evidence_roles=("primary", "event_support"),
            relation_categories=("registration_event",),
            policy_score=0.0,
            query_plan=base_only_plan,
        ),
    )
    satisfied_item = _item(
        case_id="has-event-query-family",
        group="single-hop",
        retrieval=_retrieval_payload(
            evidence_need=("participation_event",),
            bundle_evidence_roles=("primary", "event_support"),
            relation_categories=("participation_event",),
            policy_score=0.0,
            query_plan=relation_plan,
        ),
    )

    diagnostics = quality_diagnostics((missing_item, satisfied_item))
    table = diagnostics["query_plan_integrity_table"]

    assert table["missing_evidence_role_query_family_counts"] == {
        "event_support": 1
    }
    assert table["samples"][0]["case_id"] == "missing-event-query-family"
    assert table["samples"][0]["missing_evidence_role_query_families"] == (
        "event_support",
    )


def test_fast_gate_metrics_reports_query_role_gap_breakdown_as_diagnostic_only() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="role-gap",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    policy_score=0.12,
                    candidate_features={
                        "query_roles": ("relative_temporal_support",),
                        "answerability_score": 0.72,
                    },
                ),
                evidence_bundle={
                    "bundle_complete": True,
                    "evidence_term_count": 1,
                    "covered_evidence_terms": ["D1:1"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": ["D1:1"],
                            "focused_evidence_score": 1.0,
                            "query_roles": ["primary"],
                            "answerability_score": 0.86,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["query_role_gap_breakdown"]

    assert gate["ready_for_full_locomo"] is True
    assert "query_role_gaps_clear" not in gate["failed_gates"]
    assert breakdown["schema_version"] == "query_role_gap_breakdown.v1"
    assert breakdown["role_count"] == 2
    assert breakdown["role_family_count"] == 2
    assert breakdown["candidate_role_count"] == 1
    assert breakdown["role_gap_count"] == 1
    assert breakdown["candidate_role_counts"] == {"relative_temporal_support": 1}
    assert breakdown["selected_item_role_counts"] == {"primary": 1}
    assert breakdown["typed_relation_hit_role_counts"] == {}
    assert breakdown["typed_relation_lifted_hit_role_counts"] == {}
    assert breakdown["candidate_role_family_counts"] == {"temporal_support": 1}
    assert breakdown["selected_item_role_family_counts"] == {"primary": 1}
    assert breakdown["roles_without_selected_items"] == ["relative_temporal_support"]
    assert breakdown["roles_without_lifted_candidates"] == []
    assert breakdown["roles_without_typed_relation_hits"] == []
    assert breakdown["role_gaps"]["relative_temporal_support"] == {
        "candidate_count": 1,
        "lifted_candidate_count": 1,
        "selected_item_count": 0,
        "typed_relation_hit_count": 0,
        "typed_relation_lifted_hit_count": 0,
        "selection_rate": 0.0,
        "lifted_rate": 1.0,
        "typed_relation_hit_rate": 0.0,
        "bridge_query_hit_candidate_count": 0,
        "bridge_query_hit_selected_count": 0,
        "avg_candidate_answerability_score": 0.72,
        "avg_measured_candidate_answerability_score": 0.72,
        "candidate_unmeasured_answerability_count": 0,
        "avg_candidate_source_locality_score": 0.0,
        "avg_measured_candidate_source_locality_score": 0.0,
        "candidate_unmeasured_source_locality_count": 1,
        "avg_selected_answerability_score": 0.0,
        "avg_measured_selected_answerability_score": 0.0,
        "selected_unmeasured_answerability_count": 0,
        "avg_selected_source_locality_score": 0.0,
        "avg_measured_selected_source_locality_score": 0.0,
        "selected_unmeasured_source_locality_count": 0,
        "selected_bundle_role_counts": {},
        "gap_reasons": ["not_selected"],
    }


def test_fast_gate_metrics_uses_fusion_selected_evidence_role_counts() -> None:
    retrieval = _retrieval_payload(
        evidence_need=("location",),
        bundle_evidence_roles=("primary", "location_support"),
        policy_score=0.2,
        candidate_features={
            "query_roles": ("location_support",),
            "answerability_score": 0.8,
            "source_locality_score": 0.84,
        },
    )
    retrieval["metadata"]["multi_query_merge"] = {
        "raw_result_count": 2,
        "unique_result_count": 1,
        "query_role_counts": {"original_question": 1, "location_support": 1},
        "selected_evidence_query_role_counts": {"location_support": 1},
    }

    gate = fast_gate_metrics(
        (
            _item(
                case_id="fusion-selected-role",
                group="single-hop",
                retrieval=retrieval,
                evidence_bundle={
                    "bundle_complete": True,
                    "evidence_term_count": 1,
                    "covered_evidence_terms": ["D1:1"],
                    "items": [
                        {
                            "role": "location_support",
                            "retrieval_order": 1,
                            "covered_evidence_terms": ["D1:1"],
                            "focused_evidence_score": 1.0,
                            "answerability_score": 0.8,
                            "source_locality_score": 0.84,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["query_role_gap_breakdown"]

    assert gate["ready_for_full_locomo"] is True
    assert breakdown["candidate_fusion_query_role_counts"] == {
        "location_support": 1,
        "original_question": 1,
    }
    assert breakdown["selected_evidence_query_role_counts"] == {
        "location_support": 1
    }
    assert breakdown["roles_without_selected_items"] == ["location_support"]
    assert breakdown["roles_without_selected_evidence"] == []
    assert breakdown["roles_with_selected_evidence_only_in_fusion"] == [
        "location_support"
    ]
    assert breakdown["role_gaps"]["location_support"]["gap_reasons"] == [
        "selected_evidence_not_bundle_tagged"
    ]
    assert (
        breakdown["role_gaps"]["location_support"][
            "selected_evidence_query_role_count"
        ]
        == 1
    )


def test_fast_gate_metrics_reports_typed_relation_hit_role_gaps() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="typed-hit-gap",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("health_profile", "status_profile"),
                    bundle_evidence_roles=(
                        "primary",
                        "health_support",
                        "status_support",
                    ),
                    policy_score=0.2,
                    candidate_features={
                        "query_roles": ("health_support", "status_support"),
                        "answerability_score": 0.8,
                        "source_locality_score": 0.9,
                    },
                    score_signals={
                        "benchmark_typed_relation_support_hit_roles": [
                            "health_support"
                        ],
                    },
                ),
                evidence_bundle={
                    "bundle_complete": True,
                    "evidence_term_count": 1,
                    "covered_evidence_terms": ["D1:1"],
                    "items": [
                        {
                            "role": "health_support",
                            "retrieval_order": 1,
                            "covered_evidence_terms": ["D1:1"],
                            "focused_evidence_score": 1.0,
                            "query_roles": ["health_support"],
                            "answerability_score": 0.8,
                            "source_locality_score": 0.9,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["query_role_gap_breakdown"]

    assert gate["ready_for_full_locomo"] is True
    assert "query_role_gaps_clear" not in gate["failed_gates"]
    assert breakdown["typed_relation_hit_role_counts"] == {"health_support": 1}
    assert breakdown["typed_relation_lifted_hit_role_counts"] == {
        "health_support": 1
    }
    assert breakdown["roles_without_typed_relation_hits"] == ["status_support"]
    assert breakdown["role_gaps"]["status_support"] == {
        "candidate_count": 1,
        "lifted_candidate_count": 1,
        "selected_item_count": 0,
        "typed_relation_hit_count": 0,
        "typed_relation_lifted_hit_count": 0,
        "selection_rate": 0.0,
        "lifted_rate": 1.0,
        "typed_relation_hit_rate": 0.0,
        "bridge_query_hit_candidate_count": 0,
        "bridge_query_hit_selected_count": 0,
        "avg_candidate_answerability_score": 0.8,
        "avg_measured_candidate_answerability_score": 0.8,
        "candidate_unmeasured_answerability_count": 0,
        "avg_candidate_source_locality_score": 0.9,
        "avg_measured_candidate_source_locality_score": 0.9,
        "candidate_unmeasured_source_locality_count": 0,
        "avg_selected_answerability_score": 0.0,
        "avg_measured_selected_answerability_score": 0.0,
        "selected_unmeasured_answerability_count": 0,
        "avg_selected_source_locality_score": 0.0,
        "avg_measured_selected_source_locality_score": 0.0,
        "selected_unmeasured_source_locality_count": 0,
        "selected_bundle_role_counts": {},
        "gap_reasons": ["not_selected", "typed_relation_not_hit"],
    }


def test_fast_gate_metrics_does_not_fail_typed_hit_gate_for_preference_support() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="preference-role",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary", "preference_support"),
                    policy_score=0.2,
                    candidate_features={
                        "query_roles": ("preference_support",),
                        "answerability_score": 0.8,
                        "source_locality_score": 0.9,
                    },
                ),
                evidence_bundle={
                    "bundle_complete": True,
                    "evidence_term_count": 1,
                    "covered_evidence_terms": ["D1:1"],
                    "items": [
                        {
                            "role": "preference_support",
                            "retrieval_order": 1,
                            "covered_evidence_terms": ["D1:1"],
                            "query_roles": ["preference_support"],
                            "answerability_score": 0.8,
                            "source_locality_score": 0.9,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["query_role_gap_breakdown"]

    assert breakdown["roles_without_typed_relation_hits"] == []
    assert breakdown["role_gap_count"] == 0
    assert "query_role_gaps_clear" not in gate["failed_gates"]


def test_fast_gate_metrics_reports_source_ref_provenance() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="fused-ref",
                retrieval={
                    "metadata": {},
                    "results": [
                        {
                            "id": "fused-evidence",
                            "rank": 1,
                            "source_refs": ["chunk-ref"],
                            "metadata": {
                                "diagnostics": {
                                    "benchmark_candidate_fusion": {
                                        "source_refs": ["chunk-ref", "D2:8"]
                                    }
                                }
                            },
                        }
                    ],
                },
                evidence_bundle={
                    "items": [
                        {
                            "id": "fused-evidence",
                            "role": "primary",
                            "retrieval_order": 1,
                            "source_refs": ["chunk-ref", "D2:8"],
                        }
                    ]
                },
            ),
            _item(
                case_id="missing-ref",
                retrieval={
                    "metadata": {},
                    "results": [
                        {
                            "id": "ref-less",
                            "rank": 1,
                            "metadata": {"diagnostics": {}},
                        }
                    ],
                },
                evidence_bundle={
                    "items": [
                        {
                            "id": "ref-less",
                            "role": "primary",
                            "retrieval_order": 1,
                        }
                    ]
                },
            ),
        ),
        expected_case_count=2,
    )

    provenance = gate["source_ref_provenance"]
    assert provenance["schema_version"] == "source_ref_provenance.v1"
    assert provenance["retrieval_candidate_count"] == 2
    assert provenance["retrieval_source_refless_candidate_count"] == 1
    assert provenance["fused_ref_rescue_candidate_count"] == 1
    assert provenance["fused_ref_added_count"] == 1
    assert provenance["selected_bundle_item_count"] == 2
    assert provenance["selected_bundle_source_refless_item_count"] == 1
    assert provenance["source_refless_selected_samples"] == [
        {
            "case_id": "missing-ref",
            "item_id": "ref-less",
            "role": "primary",
            "retrieval_order": 1,
        }
    ]


def test_fast_gate_metrics_reports_answer_context_provenance() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="bundle-context",
                cutoff_results={
                    "200": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 1,
                            "source_ref_count": 1,
                            "source_ref_item_count": 1,
                            "source_refless_item_count": 0,
                            "bundle_source_type_diversity": 2,
                            "bundle_retrieval_source_diversity": 3,
                            "bundle_source_type_support_diversity": 1,
                            "bundle_retrieval_source_support_diversity": 2,
                            "avg_answerability_score": 0.4,
                            "avg_measured_answerability_score": 0.8,
                            "unmeasured_answerability_count": 1,
                            "avg_source_locality_score": 0.35,
                            "avg_measured_source_locality_score": 0.7,
                            "unmeasured_source_locality_count": 1,
                        }
                    }
                },
            ),
            _item(
                case_id="weak-context",
                cutoff_results={
                    "200": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 2,
                            "source_ref_count": 0,
                            "source_ref_item_count": 0,
                            "source_refless_item_count": 2,
                            "backfilled_retrieval_item_count": 2,
                            "skipped_duplicate_source_bundle_item_count": 1,
                            "skipped_noisy_overlap_bundle_item_count": 1,
                            "skipped_redundant_risky_backfill_count": 1,
                            "skipped_redundant_source_backfill_count": 1,
                            "skipped_redundant_role_backfill_count": 1,
                            "backfilled_broad_summary_count": 1,
                            "backfilled_conflict_or_stale_count": 1,
                            "backfilled_source_proximity_support_count": 1,
                            "backfilled_chained_source_proximity_support_count": 1,
                            "backfilled_source_proximity_closest_distance": 1,
                            "bundle_source_type_diversity": 1,
                            "bundle_retrieval_source_diversity": 1,
                            "bundle_source_type_support_diversity": 0,
                            "bundle_retrieval_source_support_diversity": 0,
                            "missing_required_roles": ["visual"],
                        }
                    }
                },
            ),
        ),
        expected_case_count=2,
    )

    provenance = gate["answer_context_provenance"]
    assert provenance["schema_version"] == "answer_context_provenance.v1"
    assert provenance["context_count"] == 2
    assert provenance["evidence_bundle_context_count"] == 2
    assert provenance["source_ref_context_count"] == 1
    assert provenance["source_refless_context_count"] == 1
    assert provenance["mixed_source_context_count"] == 0
    assert provenance["source_ref_item_coverage_rate"] == 0.3333
    assert provenance["backfilled_context_count"] == 1
    assert provenance["duplicate_source_bundle_skip_context_count"] == 1
    assert provenance["noisy_overlap_bundle_skip_context_count"] == 1
    assert provenance["backfill_skip_context_count"] == 1
    assert provenance["backfilled_retrieval_item_count"] == 2
    assert provenance["skipped_duplicate_source_bundle_item_count"] == 1
    assert provenance["avg_skipped_duplicate_source_bundle_item_count"] == 0.5
    assert provenance["skipped_noisy_overlap_bundle_item_count"] == 1
    assert provenance["avg_skipped_noisy_overlap_bundle_item_count"] == 0.5
    assert provenance["skipped_redundant_risky_backfill_count"] == 1
    assert provenance["avg_skipped_redundant_risky_backfill_count"] == 0.5
    assert provenance["skipped_redundant_source_backfill_count"] == 1
    assert provenance["avg_skipped_redundant_source_backfill_count"] == 0.5
    assert provenance["skipped_redundant_role_backfill_count"] == 1
    assert provenance["avg_skipped_redundant_role_backfill_count"] == 0.5
    assert provenance["backfilled_broad_summary_count"] == 1
    assert provenance["backfilled_conflict_or_stale_count"] == 1
    assert provenance["backfilled_precise_source_overlap_count"] == 0
    assert provenance["avg_backfilled_precise_source_overlap_count"] == 0.0
    assert provenance["backfilled_low_answerability_count"] == 0
    assert provenance["avg_backfilled_low_answerability_count"] == 0.0
    assert provenance["backfilled_weak_source_locality_count"] == 0
    assert provenance["avg_backfilled_weak_source_locality_count"] == 0.0
    assert provenance["backfilled_source_proximity_support_count"] == 1
    assert provenance["avg_backfilled_source_proximity_support_count"] == 0.5
    assert provenance["backfilled_chained_source_proximity_support_count"] == 1
    assert provenance["avg_backfilled_chained_source_proximity_support_count"] == 0.5
    assert provenance["avg_backfilled_source_proximity_closest_distance"] == 1.0
    assert provenance["min_backfilled_source_proximity_closest_distance"] == 1
    assert provenance["avg_backfilled_retrieval_item_count"] == 1.0
    assert provenance["avg_context_answerability_score"] == 0.2
    assert provenance["avg_measured_context_answerability_score"] == 0.8
    assert provenance["total_unmeasured_context_answerability_count"] == 1
    assert provenance["avg_context_source_locality_score"] == 0.175
    assert provenance["avg_measured_context_source_locality_score"] == 0.7
    assert provenance["total_unmeasured_context_source_locality_count"] == 1
    assert provenance["avg_bundle_source_type_diversity"] == 1.5
    assert provenance["max_bundle_source_type_diversity"] == 2
    assert provenance["avg_bundle_retrieval_source_diversity"] == 2.0
    assert provenance["max_bundle_retrieval_source_diversity"] == 3
    assert provenance["avg_bundle_source_type_support_diversity"] == 0.5
    assert provenance["max_bundle_source_type_support_diversity"] == 1
    assert provenance["avg_bundle_retrieval_source_support_diversity"] == 1.0
    assert provenance["max_bundle_retrieval_source_support_diversity"] == 2
    assert provenance["missing_required_role_context_count"] == 1
    assert provenance["missing_required_role_total"] == 1
    assert provenance["missing_required_role_counts"] == {"visual": 1}
    assert provenance["backfilled_missing_required_role_counts"] == {"visual": 1}
    expected_risk_reason_codes = [
        "risk:skipped_duplicate_source_bundle_item",
        "risk:skipped_noisy_overlap_bundle_item",
        "risk:retrieval_backfill",
        "risk:backfilled_broad_summary",
        "risk:backfilled_conflict_or_stale",
        "risk:skipped_redundant_risky_backfill",
        "risk:skipped_redundant_source_backfill",
        "risk:skipped_redundant_role_backfill",
    ]
    assert provenance["backfilled_context_samples"] == [
        {
            "case_id": "weak-context",
            "cutoff": "200",
            "source": "evidence_bundle",
            "memory_count": 2,
            "backfilled_retrieval_item_count": 2,
            "skipped_duplicate_source_bundle_item_count": 1,
            "skipped_noisy_overlap_bundle_item_count": 1,
            "skipped_redundant_risky_backfill_count": 1,
            "skipped_redundant_source_backfill_count": 1,
            "skipped_redundant_role_backfill_count": 1,
            "backfilled_broad_summary_count": 1,
            "backfilled_conflict_or_stale_count": 1,
            "backfilled_precise_source_overlap_count": 0,
            "backfilled_low_answerability_count": 0,
            "backfilled_weak_source_locality_count": 0,
            "backfilled_source_proximity_support_count": 1,
            "backfilled_chained_source_proximity_support_count": 1,
            "backfilled_source_proximity_closest_distance": 1,
            "missing_required_roles": ["visual"],
            "risk_reason_codes": expected_risk_reason_codes,
        }
    ]
    assert provenance["backfill_skip_context_samples"] == [
        {
            "case_id": "weak-context",
            "cutoff": "200",
            "source": "evidence_bundle",
            "memory_count": 2,
            "backfilled_retrieval_item_count": 2,
            "skipped_redundant_risky_backfill_count": 1,
            "skipped_redundant_source_backfill_count": 1,
            "skipped_redundant_role_backfill_count": 1,
            "missing_required_roles": ["visual"],
            "risk_reason_codes": expected_risk_reason_codes,
        }
    ]
    assert provenance["duplicate_source_bundle_skip_context_samples"] == [
        {
            "case_id": "weak-context",
            "cutoff": "200",
            "source": "evidence_bundle",
            "memory_count": 2,
            "skipped_duplicate_source_bundle_item_count": 1,
            "source_ref_count": 0,
            "source_ref_item_count": 0,
            "risk_reason_codes": expected_risk_reason_codes,
        }
    ]
    assert provenance["noisy_overlap_bundle_skip_context_samples"] == [
        {
            "case_id": "weak-context",
            "cutoff": "200",
            "source": "evidence_bundle",
            "memory_count": 2,
            "skipped_noisy_overlap_bundle_item_count": 1,
            "source_ref_count": 0,
            "source_ref_item_count": 0,
            "risk_reason_codes": expected_risk_reason_codes,
        }
    ]
    assert provenance["source_refless_context_samples"] == [
        {
            "case_id": "weak-context",
            "cutoff": "200",
            "source": "evidence_bundle",
            "memory_count": 2,
            "source_refless_item_count": 2,
            "fallback_reason": "",
        }
    ]
    assert provenance["mixed_source_context_samples"] == []


def test_quality_diagnostics_reports_query_plan_integrity() -> None:
    query_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 3,
        "dropped_query_count": 2,
        "selected_roles": [
            "original_question",
            "expanded_focus",
            "compact_relation",
        ],
        "dropped_roles": [
            "relative_temporal_support",
            "multi_hop_bridge",
        ],
        "dropped_type_limit_roles": ["relative_temporal_support"],
        "recommended_role_families": [
            "base_query",
            "temporal_support",
            "multi_hop",
        ],
        "selected_role_families": [
            "base_query",
            "expanded_focus",
            "relation_compact",
        ],
        "missing_recommended_role_families": [
            "temporal_support",
            "multi_hop",
        ],
        "role_family_counts": {
            "base_query": 1,
            "expanded_focus": 1,
            "relation_compact": 1,
            "temporal_support": 1,
            "multi_hop": 1,
        },
        "selected_role_family_counts": {
            "base_query": 1,
            "expanded_focus": 1,
            "relation_compact": 1,
        },
        "dropped_role_family_counts": {
            "temporal_support": 1,
            "multi_hop": 1,
        },
        "candidate_type_counts": {"semantic": 3, "lexical": 2},
        "selected_type_counts": {"semantic": 2, "lexical": 1},
        "fanout_integrity": {
            "bounded": True,
            "fanout_limit_hit": True,
            "type_limit_hit": True,
            "empty_query_candidate_count": 1,
            "max_selected_query_token_count": 12,
        },
    }
    item = _item(
        case_id="plan-gap",
        group="temporal",
        retrieval=_retrieval_payload(
            evidence_need=("temporal_support", "multi_hop"),
            bundle_evidence_roles=("primary", "bridge", "temporal_support"),
            relation_categories=("temporal",),
            policy_score=0.0,
            query_plan=query_plan,
        ),
    )

    diagnostics = quality_diagnostics((item,))
    table = diagnostics["query_plan_integrity_table"]

    assert table["schema_version"] == "query_plan_integrity.v1"
    assert table["plan_count"] == 1
    assert table["plan_gap_case_count"] == 1
    assert table["avg_selected_query_count"] == 3.0
    assert table["dropped_query_count"] == 2
    assert table["fanout_limit_hit_count"] == 1
    assert table["type_limit_hit_count"] == 1
    assert table["empty_query_candidate_count"] == 1
    assert table["max_selected_query_token_count"] == 12
    assert table["missing_recommended_role_family_total"] == 2
    assert table["recommended_role_family_counts"] == {
        "base_query": 1,
        "multi_hop": 1,
        "temporal_support": 1,
    }
    assert table["missing_recommended_role_family_counts"] == {
        "multi_hop": 1,
        "temporal_support": 1,
    }
    assert table["required_evidence_role_counts"] == {
        "bridge": 1,
        "primary": 1,
        "temporal_support": 1,
    }
    assert table["missing_evidence_role_query_family_total"] == 0
    assert table["missing_evidence_role_query_family_counts"] == {}
    assert table["selected_role_family_counts"] == {
        "base_query": 1,
        "expanded_focus": 1,
        "relation_compact": 1,
    }
    assert table["dropped_role_family_counts"] == {
        "multi_hop": 1,
        "temporal_support": 1,
    }
    assert table["gap_reason_counts"] == {
        "dropped_queries": 1,
        "empty_query_candidate": 1,
        "fanout_limit_hit": 1,
        "missing_recommended_role_family": 1,
        "type_limit_hit": 1,
    }
    assert table["samples"][0]["case_id"] == "plan-gap"
    assert table["samples"][0]["missing_recommended_role_families"] == (
        "temporal_support",
        "multi_hop",
    )
    assert table["samples"][0]["required_evidence_roles"] == (
        "primary",
        "bridge",
        "temporal_support",
    )
    assert table["samples"][0]["missing_evidence_role_query_families"] == ()

    gate = fast_gate_metrics((item,), expected_case_count=1)
    breakdown = gate["query_plan_gap_breakdown"]

    assert breakdown["schema_version"] == "query_plan_gap_breakdown.v1"
    assert breakdown["plan_count"] == 1
    assert breakdown["plan_gap_case_count"] == 1
    assert breakdown["missing_recommended_role_family_total"] == 2
    assert breakdown["missing_evidence_role_query_family_total"] == 0
    assert breakdown["missing_evidence_role_query_family_counts"] == {}
    assert breakdown["fanout_limit_hit_count"] == 1
    assert breakdown["type_limit_hit_count"] == 1
    assert breakdown["empty_query_candidate_count"] == 1
    assert breakdown["missing_recommended_role_family_counts"] == {
        "multi_hop": 1,
        "temporal_support": 1,
    }
    assert breakdown["samples"][0]["gap_reasons"] == [
        "missing_recommended_role_family",
        "dropped_queries",
        "fanout_limit_hit",
        "type_limit_hit",
        "empty_query_candidate",
    ]


def test_quality_diagnostics_reports_query_plan_type_limit_replacements() -> None:
    query_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 2,
        "dropped_query_count": 2,
        "selected_roles": [
            "original_question",
            "location_support",
        ],
        "dropped_roles": [
            "compact_relation",
            "expanded_focus",
        ],
        "dropped_type_limit_roles": ["expanded_focus"],
        "replaced_type_limit_roles": ["compact_relation"],
        "type_limit_replacement_roles": ["location_support"],
        "recommended_role_families": [
            "base_query",
            "location_support",
            "relation_compact",
        ],
        "selected_role_families": [
            "base_query",
            "location_support",
        ],
        "missing_recommended_role_families": ["relation_compact"],
        "selected_role_family_counts": {
            "base_query": 1,
            "location_support": 1,
        },
        "dropped_role_family_counts": {
            "expanded_focus": 1,
            "relation_compact": 1,
        },
        "candidate_type_counts": {"semantic": 1, "lexical": 3},
        "selected_type_counts": {"semantic": 1, "lexical": 1},
        "fanout_integrity": {
            "bounded": True,
            "type_limit_hit": True,
        },
    }
    item = _item(
        case_id="type-limit-replacement",
        group="location",
        retrieval=_retrieval_payload(
            evidence_need=("location_support",),
            bundle_evidence_roles=("primary", "location"),
            policy_score=0.0,
            query_plan=query_plan,
        ),
    )

    diagnostics = quality_diagnostics((item,))
    table = diagnostics["query_plan_integrity_table"]

    assert table["type_limit_hit_count"] == 1
    assert table["dropped_type_limit_role_counts"] == {"expanded_focus": 1}
    assert table["replaced_type_limit_role_counts"] == {"compact_relation": 1}
    assert table["type_limit_replacement_role_counts"] == {
        "location_support": 1
    }
    assert table["gap_reason_counts"] == {
        "dropped_queries": 1,
        "missing_recommended_role_family": 1,
        "type_limit_hit": 1,
        "type_limit_replacement": 1,
    }
    assert table["samples"][0]["dropped_type_limit_roles"] == ("expanded_focus",)
    assert table["samples"][0]["replaced_type_limit_roles"] == (
        "compact_relation",
    )
    assert table["samples"][0]["type_limit_replacement_roles"] == (
        "location_support",
    )

    gate = fast_gate_metrics((item,), expected_case_count=1)
    breakdown = gate["query_plan_gap_breakdown"]

    assert breakdown["dropped_type_limit_role_counts"] == {"expanded_focus": 1}
    assert breakdown["replaced_type_limit_role_counts"] == {
        "compact_relation": 1
    }
    assert breakdown["type_limit_replacement_role_counts"] == {
        "location_support": 1
    }
    assert breakdown["gap_reason_counts"]["type_limit_replacement"] == 1


def test_quality_diagnostics_reports_evidence_role_query_family_gap() -> None:
    query_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 1,
        "dropped_query_count": 0,
        "selected_roles": ["original_question"],
        "dropped_roles": [],
        "recommended_role_families": ["base_query"],
        "selected_role_families": ["base_query"],
        "missing_recommended_role_families": [],
        "selected_role_family_counts": {"base_query": 1},
        "fanout_integrity": {"bounded": True},
    }
    item = _item(
        case_id="role-query-gap",
        group="temporal",
        retrieval=_retrieval_payload(
            evidence_need=("temporal_support",),
            bundle_evidence_roles=("primary", "temporal_support"),
            policy_score=0.0,
            query_plan=query_plan,
        ),
    )

    diagnostics = quality_diagnostics((item,))
    table = diagnostics["query_plan_integrity_table"]

    assert table["plan_gap_case_count"] == 1
    assert table["missing_evidence_role_query_family_total"] == 1
    assert table["missing_evidence_role_query_family_counts"] == {
        "temporal_support": 1
    }
    assert table["gap_reason_counts"] == {
        "missing_evidence_role_query_family": 1
    }
    assert table["samples"][0]["required_evidence_roles"] == (
        "primary",
        "temporal_support",
    )
    assert table["samples"][0]["missing_evidence_role_query_families"] == (
        "temporal_support",
    )

    gate = fast_gate_metrics((item,), expected_case_count=1)
    breakdown = gate["query_plan_gap_breakdown"]

    assert breakdown["missing_evidence_role_query_family_details"] == {
        "temporal_support": {
            "role_family": "temporal_support",
            "role_family_label": "temporal support",
            "impact_count": 1,
            "accepted_query_families": ["temporal_support", "expanded_focus"],
            "accepted_query_family_labels": [
                "temporal support",
                "expanded focus",
            ],
            "action": (
                "Add query-plan coverage for the temporal support role family "
                "using temporal support or expanded focus queries."
            ),
            "sample_case_ids": ["role-query-gap"],
        }
    }
    assert breakdown["compact_samples"] == [
        {
            "case_id": "role-query-gap",
            "group": "temporal",
            "gap_reasons": ["missing_evidence_role_query_family"],
            "missing_evidence_role_query_families": ["temporal_support"],
            "selected_role_families": ["base_query"],
            "required_evidence_roles": ["primary", "temporal_support"],
            "selected_query_count": 1,
        }
    ]


def test_quality_diagnostics_accepts_relation_compact_for_profile_support_roles() -> None:
    query_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 1,
        "dropped_query_count": 0,
        "selected_roles": ["health_support"],
        "dropped_roles": [],
        "recommended_role_families": ["relation_compact"],
        "selected_role_families": ["relation_compact"],
        "missing_recommended_role_families": [],
        "selected_role_family_counts": {"relation_compact": 1},
        "fanout_integrity": {"bounded": True},
    }
    item = _item(
        case_id="profile-role-query-covered",
        group="single-hop",
        retrieval=_retrieval_payload(
            evidence_need=("profile_fact",),
            bundle_evidence_roles=("primary", "health_support"),
            policy_score=0.0,
            query_plan=query_plan,
        ),
    )

    diagnostics = quality_diagnostics((item,))
    table = diagnostics["query_plan_integrity_table"]

    assert table["plan_gap_case_count"] == 0
    assert table["missing_evidence_role_query_family_total"] == 0
    assert table["missing_evidence_role_query_family_counts"] == {}
    assert table["gap_reason_counts"] == {}
    assert table["samples"] == []


def test_query_plan_integrity_requires_typed_favorite_query_family() -> None:
    base_only_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 1,
        "dropped_query_count": 0,
        "selected_roles": ["original_question"],
        "dropped_roles": [],
        "recommended_role_families": ["base_query"],
        "selected_role_families": ["base_query"],
        "missing_recommended_role_families": [],
        "selected_role_family_counts": {"base_query": 1},
        "fanout_integrity": {"bounded": True},
    }
    favorite_item = _item(
        case_id="favorite-role-base-only",
        group="single-hop",
        retrieval=_retrieval_payload(
            evidence_need=("favorite_preference", "preference"),
            bundle_evidence_roles=("primary", "favorite_support"),
            relation_categories=("favorite_preference", "preference"),
            policy_score=0.0,
            query_plan=base_only_plan,
        ),
    )

    diagnostics = quality_diagnostics((favorite_item,))
    table = diagnostics["query_plan_integrity_table"]

    assert table["missing_evidence_role_query_family_counts"] == {
        "favorite_support": 1
    }
    assert table["samples"][0]["case_id"] == "favorite-role-base-only"
    assert table["samples"][0]["missing_evidence_role_query_families"] == (
        "favorite_support",
    )


def test_fast_gate_metrics_blocks_missing_query_plan_evidence_role_family() -> None:
    base_only_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 1,
        "dropped_query_count": 0,
        "selected_roles": ["original_question"],
        "dropped_roles": [],
        "recommended_role_families": ["base_query"],
        "selected_role_families": ["base_query"],
        "missing_recommended_role_families": [],
        "selected_role_family_counts": {"base_query": 1},
        "fanout_integrity": {"bounded": True},
    }
    items = tuple(
        _item(
            case_id=f"case-{index}",
            evidence_bundle={
                "bundle_complete": True,
                "evidence_term_count": 1,
                "covered_evidence_terms": [f"D{index}:1"],
                "items": [
                    {
                        "retrieval_order": 1 if index <= 30 else 2,
                        "covered_evidence_terms": [f"D{index}:1"],
                        "focused_evidence_score": 1.0,
                    }
                ],
            },
            retrieval=_retrieval_payload(
                evidence_need=("favorite_preference", "preference"),
                bundle_evidence_roles=("primary", "favorite_support"),
                relation_categories=("favorite_preference", "preference"),
                policy_score=0.0,
                query_plan=base_only_plan if index == 1 else {},
            ),
        )
        for index in range(1, 41)
    )

    gate = fast_gate_metrics(items)
    breakdown = gate["query_plan_gap_breakdown"]

    assert gate["passed"] is False
    assert gate["ready_for_full_locomo"] is False
    assert "query_plan_evidence_roles_clear" in gate["failed_gates"]
    assert gate["gates"]["query_plan_evidence_roles_clear"]["actual"] == 1
    assert breakdown["plan_gap_case_count"] == 1
    assert breakdown["missing_evidence_role_query_family_total"] == 1
    assert breakdown["missing_evidence_role_query_family_counts"] == {
        "favorite_support": 1
    }


def test_fast_gate_metrics_passes_bundle_quality_when_all_bundles_are_usable() -> None:
    items = tuple(
        _item(
            case_id=f"case-{index}",
            evidence_bundle=_fast_gate_bundle(
                index,
                bundle_quality=_bundle_quality(
                    confidence_score=0.76,
                    confidence_band="high",
                    reason_codes=("has_primary_evidence", "high_answerability"),
                    selected_item_count=2,
                    primary_count=1,
                    supporting_count=1,
                ),
            ),
        )
        for index in range(1, 41)
    )

    gate = fast_gate_metrics(items)

    assert gate["passed"] is True
    assert gate["bundle_quality_gate_applied"] is True
    assert gate["bundle_quality_count"] == 40
    assert gate["weak_bundle_count"] == 0
    assert gate["gates"]["bundle_quality_present"]["actual"] == 40
    assert gate["gates"]["bundle_quality_medium_or_high"]["actual"] == 40


def test_fast_gate_metrics_blocks_full_run_for_weak_bundle_quality() -> None:
    items = tuple(
        _item(
            case_id=f"case-{index}",
            evidence_bundle=_fast_gate_bundle(
                index,
                bundle_quality=_bundle_quality(
                    confidence_score=0.2 if index == 1 else 0.76,
                    confidence_band="low" if index == 1 else "high",
                    risk_penalty=0.21 if index == 1 else 0.0,
                    reason_codes=("risk:low_answerability",)
                    if index == 1
                    else ("has_primary_evidence", "high_answerability"),
                    selected_item_count=2,
                    primary_count=1,
                    supporting_count=1,
                    low_answerability_count=1 if index == 1 else 0,
                ),
            ),
        )
        for index in range(1, 41)
    )

    gate = fast_gate_metrics(items)

    assert gate["passed"] is False
    assert gate["ready_for_full_locomo"] is False
    assert gate["bundle_quality_gate_applied"] is True
    assert gate["weak_bundle_count"] == 1
    assert "bundle_quality_medium_or_high" in gate["failed_gates"]
    assert gate["gates"]["bundle_quality_medium_or_high"]["actual"] == 39
    assert gate["gates"]["bundle_quality_medium_or_high"]["target"] == 40
    breakdown = gate["bundle_quality_failure_breakdown"]
    assert breakdown["schema_version"] == "bundle_quality_failure_breakdown.v1"
    assert breakdown["required_medium_or_high_bundle_count"] == 40
    assert breakdown["medium_or_high_bundle_count"] == 39
    assert breakdown["medium_or_high_bundle_gap"] == 1
    assert breakdown["weak_bundle_count"] == 1
    assert breakdown["risk_reason_counts"] == {"risk:low_answerability": 1}
    assert breakdown["weak_samples"][0]["case_id"] == "case-1"
    assert breakdown["weak_samples"][0]["reason_codes"] == ("risk:low_answerability",)


def _item(
    *,
    case_id: str,
    score: float = 1.0,
    group: str = "multi-hop",
    scored: bool = True,
    retrieval_quality: dict[str, object] | None = None,
    evidence_bundle: dict[str, object] | None = None,
    retrieval: dict[str, object] | None = None,
    cutoff_results: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "group": group,
        "scored": scored,
        "judgment": {"score": score},
        "retrieval_quality": retrieval_quality or {},
        "evidence_bundle": evidence_bundle or {},
        "retrieval": retrieval or {"metadata": {}, "results": []},
        "cutoff_results": cutoff_results or {},
    }


def _fast_gate_bundle(
    index: int,
    *,
    bundle_quality: dict[str, object],
) -> dict[str, object]:
    return {
        "bundle_complete": True,
        "evidence_term_count": 1,
        "covered_evidence_terms": [f"D{index}:1"],
        "bundle_planner": {"bundle_quality": bundle_quality},
        "items": [
            {
                "retrieval_order": 1 if index <= 30 else 2,
                "covered_evidence_terms": [f"D{index}:1"],
                "focused_evidence_score": 1.0,
            }
        ],
    }


def _retrieval_payload(
    *,
    evidence_need: tuple[str, ...],
    policy_score: float,
    bundle_evidence_roles: tuple[str, ...] = (),
    relation_categories: tuple[str, ...] = (),
    entities: tuple[str, ...] = (),
    risk_flags: tuple[str, ...] = (),
    query_overlap_count: int = 0,
    query_profile_overlap_count: int = 0,
    retrieval_intent_overlap_count: int = 0,
    query_plan: dict[str, object] | None = None,
    candidate_features: dict[str, object] | None = None,
    score_signals: dict[str, object] | None = None,
    item_id: str | None = None,
    rank: int = 1,
    score: float = 0.5,
    memory_text: str = "",
    stale_reason: str = "",
) -> dict[str, object]:
    return {
        "metadata": {
            "query_decomposition": {
                "query_profile": {
                    "evidence_need": evidence_need,
                    "bundle_evidence_roles": bundle_evidence_roles,
                    "relation_categories": relation_categories,
                    "entities": entities,
                    "risk_flags": risk_flags,
                },
                "retrieval_intent": {
                    "entity_count": len(entities),
                    "entities": [
                        {"canonical": entity, "surfaces": [entity]}
                        for entity in entities
                    ],
                    "evidence_need": list(evidence_need),
                    "bundle_evidence_roles": list(bundle_evidence_roles),
                    "risk_flags": list(risk_flags),
                    "relations": {
                        "intents": [
                            {"category": category}
                            for category in relation_categories
                        ]
                    },
                },
                "query_plan": query_plan or {},
            },
            "query_integrity": {
                "expected_answer_query_overlap_count": query_overlap_count,
                "expected_answer_query_overlap_terms": ["answer"]
                if query_overlap_count
                else [],
                "expected_answer_query_profile_overlap_count": (
                    query_profile_overlap_count
                ),
                "expected_answer_query_profile_overlap_terms": ["profile-answer"]
                if query_profile_overlap_count
                else [],
                "expected_answer_retrieval_intent_overlap_count": (
                    retrieval_intent_overlap_count
                ),
                "expected_answer_retrieval_intent_overlap_terms": ["intent-answer"]
                if retrieval_intent_overlap_count
                else [],
                "retrieval_intent_risk_flags": list(risk_flags),
            },
        },
        "results": [
            {
                **({"id": item_id} if item_id else {}),
                "rank": rank,
                "score": score,
                "memory": memory_text,
                "metadata": {
                    "diagnostics": {
                        **({"stale_reason": stale_reason} if stale_reason else {}),
                        "benchmark_rerank_boosted": bool(policy_score),
                        "score_signals": score_signals or {},
                        "benchmark_candidate_features": candidate_features or {},
                        "benchmark_rerank_policy": {
                            "contributions": [
                                {
                                    "policy": "FocusedTurnPolicy",
                                    "score": policy_score,
                                    "reason_codes": ["focused_turn"]
                                    if policy_score
                                    else [],
                                }
                            ]
                        }
                    }
                }
            }
        ],
    }


def _rerank_candidate_payload(
    *,
    item_id: str,
    rank: int,
    score: float = 0.5,
    policy_score: float,
    boosted: bool | None = None,
    score_signals: dict[str, object] | None = None,
    candidate_features: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": item_id,
        "rank": rank,
        "score": score,
        "metadata": {
            "diagnostics": {
                "benchmark_rerank_boosted": bool(policy_score)
                if boosted is None
                else boosted,
                "score_signals": score_signals or {},
                "benchmark_candidate_features": candidate_features or {},
                "benchmark_rerank_policy": {
                    "contributions": [
                        {
                            "policy": "FocusedTurnPolicy",
                            "score": policy_score,
                            "reason_codes": ["focused_turn"]
                            if policy_score
                            else [],
                        }
                    ]
                },
            }
        },
    }


def _bundle_quality(
    *,
    confidence_score: float,
    confidence_band: str,
    risk_penalty: float = 0.0,
    reason_codes: tuple[str, ...] = (),
    selected_item_count: int = 0,
    primary_count: int = 0,
    supporting_count: int = 0,
    source_ref_item_count: int = 0,
    source_ref_support_item_count: int = 0,
    source_ref_support_ref_count: int = 0,
    source_identity_item_count: int = 0,
    source_identity_ref_count: int = 0,
    source_identity_support_item_count: int = 0,
    source_identity_support_ref_count: int = 0,
    source_type_diversity: int = 0,
    retrieval_source_diversity: int = 0,
    source_type_support_diversity: int = 0,
    retrieval_source_support_diversity: int = 0,
    bridge_count: int = 0,
    causal_support_count: int = 0,
    event_support_count: int = 0,
    exchange_support_count: int = 0,
    inference_support_count: int = 0,
    location_support_count: int = 0,
    emotion_response_support_count: int = 0,
    symbolic_meaning_support_count: int = 0,
    preference_support_count: int = 0,
    visual_support_count: int = 0,
    contrast_count: int = 0,
    location_relation_category_hit_count: int = 0,
    low_answerability_count: int = 0,
    average_measured_answerability_score: float = 0.0,
    unmeasured_answerability_count: int = 0,
    broad_summary_count: int = 0,
    conflict_or_stale_count: int = 0,
    source_proximity_support_count: int = 0,
    source_proximity_closest_distance: int | None = None,
    source_proximity_distance_counts: Mapping[str, int] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "evidence_bundle_quality.v1",
        "confidence_score": confidence_score,
        "confidence_band": confidence_band,
        "risk_penalty": risk_penalty,
        "reason_codes": list(reason_codes),
        "selected_item_count": selected_item_count,
        "primary_count": primary_count,
        "supporting_count": supporting_count,
        "source_ref_item_count": source_ref_item_count,
        "source_ref_support_item_count": source_ref_support_item_count,
        "source_ref_support_ref_count": source_ref_support_ref_count,
        "source_identity_item_count": source_identity_item_count,
        "source_identity_ref_count": source_identity_ref_count,
        "source_identity_support_item_count": source_identity_support_item_count,
        "source_identity_support_ref_count": source_identity_support_ref_count,
        "source_type_diversity": source_type_diversity,
        "retrieval_source_diversity": retrieval_source_diversity,
        "source_type_support_diversity": source_type_support_diversity,
        "retrieval_source_support_diversity": retrieval_source_support_diversity,
        "bridge_count": bridge_count,
        "causal_support_count": causal_support_count,
        "event_support_count": event_support_count,
        "exchange_support_count": exchange_support_count,
        "inference_support_count": inference_support_count,
        "location_support_count": location_support_count,
        "emotion_response_support_count": emotion_response_support_count,
        "symbolic_meaning_support_count": symbolic_meaning_support_count,
        "preference_support_count": preference_support_count,
        "visual_support_count": visual_support_count,
        "contrast_count": contrast_count,
        "location_relation_category_hit_count": location_relation_category_hit_count,
        "low_answerability_count": low_answerability_count,
        "average_measured_answerability_score": average_measured_answerability_score,
        "unmeasured_answerability_count": unmeasured_answerability_count,
        "broad_summary_count": broad_summary_count,
        "conflict_or_stale_count": conflict_or_stale_count,
        "source_proximity_support_count": source_proximity_support_count,
        "source_proximity_closest_distance": source_proximity_closest_distance,
        "source_proximity_distance_counts": dict(
            source_proximity_distance_counts or {}
        ),
    }
