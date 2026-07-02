from __future__ import annotations

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
                            source_type_diversity=2,
                            retrieval_source_diversity=2,
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
    assert bundle_quality["avg_selected_source_locality_score"] == 0.625
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
        "selection_rate": 1.0,
        "lifted_rate": 1.0,
        "bridge_query_hit_candidate_count": 1,
        "bridge_query_hit_selected_count": 1,
        "avg_candidate_answerability_score": 0.9,
        "avg_selected_answerability_score": 0.9,
        "selected_bundle_role_counts": {"bridge": 1},
    }
    assert query_roles["role_stats"]["temporal_support"] == {
        "candidate_count": 1,
        "lifted_candidate_count": 0,
        "selected_item_count": 0,
        "selection_rate": 0.0,
        "lifted_rate": 0.0,
        "bridge_query_hit_candidate_count": 0,
        "bridge_query_hit_selected_count": 0,
        "avg_candidate_answerability_score": 0.42,
        "avg_selected_answerability_score": 0.0,
        "selected_bundle_role_counts": {},
    }
    assert diagnostics["false_positive_categories"]["query_leakage_risk"] == 1
    assert diagnostics["query_leakage_report"]["clean"] is False
    assert diagnostics["query_leakage_report"]["query_overlap_case_count"] == 1


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
    assert table["source_refless_context_count"] == 0
    assert table["memory_count"] == 5
    assert table["source_ref_count"] == 4
    assert table["source_ref_item_count"] == 3
    assert table["source_refless_item_count"] == 2
    assert table["source_ref_context_rate"] == 1.0
    assert table["source_ref_item_coverage_rate"] == 0.6
    assert table["source_counts"] == {
        "evidence_bundle": 1,
        "retrieval_slice": 1,
    }
    assert table["fallback_reason_counts"] == {"empty_bundle": 1}
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
                            ],
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
                    memory_text="Private source text should not be copied.",
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
                        "broad_summary": True,
                        "conflict_or_stale": True,
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
    assert breakdown["reason_counts"] == {
        "missing_contrast_evidence": 1,
        "missing_preference_evidence": 1,
    }
    assert breakdown["category_counts"] == {"contrast": 1, "preference": 1}
    assert breakdown["samples"][0]["case_id"] == "missing-typed-evidence"
    assert breakdown["samples"][0]["memory_id"] == "topic-only"
    assert breakdown["samples"][0]["answerability_score"] == 0.42
    assert breakdown["samples"][0]["relation_categories"] == [
        "preference",
        "contrast",
    ]


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


def test_fast_gate_metrics_reports_missing_contrast_evidence_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-contrast",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("contrast",),
                    relation_categories=("contrast",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D7:5"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_contrast"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {"missing_contrast": 1}
    assert breakdown["samples"][0]["reasons"] == [
        "missing_supporting",
        "missing_evidence_refs",
        "missing_contrast",
    ]


def test_fast_gate_metrics_reports_missing_location_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-location",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("location_support",),
                    relation_categories=("location_transition",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D8:2"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": [],
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_location_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_location_support": 1
    }
    assert breakdown["samples"][0]["reasons"] == [
        "missing_supporting",
        "missing_evidence_refs",
        "missing_location_support",
    ]


def test_fast_gate_metrics_accepts_location_relation_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-location",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("location_support",),
                    relation_categories=("location_transition",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["location_transition"],
                            "planner_reason_codes": [
                                "location_relation_category_hits"
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_location_support" not in breakdown["reason_counts"]
    assert "missing_location_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_inference_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-inference",
                group="open-domain",
                retrieval=_retrieval_payload(
                    evidence_need=("inference_support",),
                    bundle_evidence_roles=("primary", "inference_support"),
                    relation_categories=("support_goal",),
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
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["inference_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_inference_support"] == 1
    assert breakdown["reason_counts"]["missing_required_inference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_inference_support": 1,
        "missing_required_inference_support": 1,
    }
    assert "missing_inference_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_inference_support" in breakdown["samples"][0][
        "reasons"
    ]


def test_fast_gate_metrics_reports_missing_causal_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-causal",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("causal_support",),
                    bundle_evidence_roles=("primary", "causal_support"),
                    relation_categories=("causal",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D3:4"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["causal_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_causal_support"] == 1
    assert breakdown["reason_counts"]["missing_required_causal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_causal_support": 1,
        "missing_required_causal_support": 1,
    }
    assert "missing_causal_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_causal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_reports_missing_preference_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-preference",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary", "preference_support"),
                    relation_categories=("preference",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D4:1"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["preference_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_preference_support"] == 1
    assert breakdown["reason_counts"]["missing_required_preference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_preference_support": 1,
        "missing_required_preference_support": 1,
    }
    assert "missing_preference_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_preference_support" in breakdown["samples"][0][
        "reasons"
    ]


def test_fast_gate_metrics_accepts_preference_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-preference",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary", "preference_support"),
                    relation_categories=("preference",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "preference_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "has_preference_evidence": True,
                            "relation_category_hits": ["preference"],
                            "planner_reason_codes": [
                                "preference_support",
                                "preference_evidence",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_preference_support" not in breakdown["reason_counts"]
    assert "missing_required_preference_support" not in breakdown["reason_counts"]
    assert "missing_preference_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_emotion_response_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-emotion-response",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("emotion_response",),
                    bundle_evidence_roles=("primary", "emotion_response_support"),
                    relation_categories=("emotion_response",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["emotion_response_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_emotion_response_support"] == 1
    assert (
        breakdown["reason_counts"]["missing_required_emotion_response_support"]
        == 1
    )
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_emotion_response_support": 1,
        "missing_required_emotion_response_support": 1,
    }
    assert "missing_emotion_response_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_emotion_response_support" in breakdown["samples"][0][
        "reasons"
    ]


def test_fast_gate_metrics_accepts_emotion_response_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-emotion-response",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("emotion_response",),
                    bundle_evidence_roles=("primary", "emotion_response_support"),
                    relation_categories=("emotion_response",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "emotion_response_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["emotion_response"],
                            "planner_reason_codes": [
                                "emotion_response_support",
                                "emotion_response_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_emotion_response_support" not in breakdown["reason_counts"]
    assert "missing_required_emotion_response_support" not in breakdown[
        "reason_counts"
    ]
    assert "missing_emotion_response_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_symbolic_meaning_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-symbolic-meaning",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("symbolic_meaning",),
                    bundle_evidence_roles=("primary", "symbolic_meaning_support"),
                    relation_categories=("symbolic_meaning",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["symbolic_meaning_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_symbolic_meaning_support"] == 1
    assert (
        breakdown["reason_counts"]["missing_required_symbolic_meaning_support"]
        == 1
    )
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_required_symbolic_meaning_support": 1,
        "missing_symbolic_meaning_support": 1,
    }
    assert "missing_symbolic_meaning_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_symbolic_meaning_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-symbolic-meaning",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("symbolic_meaning",),
                    bundle_evidence_roles=("primary", "symbolic_meaning_support"),
                    relation_categories=("symbolic_meaning",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "symbolic_meaning_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["symbolic_meaning"],
                            "planner_reason_codes": [
                                "symbolic_meaning_support",
                                "symbolic_meaning_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_symbolic_meaning_support" not in breakdown["reason_counts"]
    assert "missing_required_symbolic_meaning_support" not in breakdown[
        "reason_counts"
    ]
    assert "missing_symbolic_meaning_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_event_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-event",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("participation_event",),
                    bundle_evidence_roles=("primary", "event_support"),
                    relation_categories=("participation_event",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["event_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_event_support"] == 1
    assert breakdown["reason_counts"]["missing_required_event_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_event_support": 1,
        "missing_required_event_support": 1,
    }
    assert "missing_event_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_event_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-event",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("registration_event",),
                    bundle_evidence_roles=("primary", "event_support"),
                    relation_categories=("registration_event",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "event_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["registration_event"],
                            "planner_reason_codes": [
                                "event_support",
                                "event_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_event_support" not in breakdown["reason_counts"]
    assert "missing_required_event_support" not in breakdown["reason_counts"]
    assert "missing_event_support" not in breakdown["evidence_need_gap_reason_counts"]


def test_fast_gate_metrics_reports_missing_exchange_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-exchange",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("exchange",),
                    bundle_evidence_roles=("primary", "exchange_support"),
                    relation_categories=("exchange",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["exchange_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_exchange_support"] == 1
    assert breakdown["reason_counts"]["missing_required_exchange_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_exchange_support": 1,
        "missing_required_exchange_support": 1,
    }


def test_fast_gate_metrics_accepts_exchange_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-exchange",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("exchange",),
                    bundle_evidence_roles=("primary", "exchange_support"),
                    relation_categories=("exchange",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "exchange_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["exchange"],
                            "planner_reason_codes": [
                                "exchange_support",
                                "exchange_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_exchange_support" not in breakdown["reason_counts"]
    assert "missing_required_exchange_support" not in breakdown["reason_counts"]
    assert "missing_exchange_support" not in breakdown["evidence_need_gap_reason_counts"]


def test_fast_gate_metrics_reports_missing_communication_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-communication",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("communication",),
                    bundle_evidence_roles=("primary", "communication_support"),
                    relation_categories=("communication",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["communication_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_communication_support"] == 1
    assert breakdown["reason_counts"]["missing_required_communication_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_communication_support": 1,
        "missing_required_communication_support": 1,
    }


def test_fast_gate_metrics_accepts_communication_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-communication",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("communication",),
                    bundle_evidence_roles=("primary", "communication_support"),
                    relation_categories=("communication",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "communication_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["communication"],
                            "planner_reason_codes": [
                                "communication_support",
                                "communication_relation_category_hits",
                                "communication_speaker_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_communication_support" not in breakdown["reason_counts"]
    assert "missing_required_communication_support" not in breakdown["reason_counts"]
    assert (
        "missing_communication_support"
        not in breakdown["evidence_need_gap_reason_counts"]
    )


def test_fast_gate_metrics_reports_missing_visual_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-visual",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("visual_evidence",),
                    bundle_evidence_roles=("primary", "visual_support"),
                    relation_categories=("visual",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D5:2"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["visual_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_visual_support"] == 1
    assert breakdown["reason_counts"]["missing_required_visual_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_visual_support": 1,
        "missing_required_visual_support": 1,
    }
    assert "missing_visual_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_visual_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_visual_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-visual",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("visual_evidence",),
                    bundle_evidence_roles=("primary", "visual_support"),
                    relation_categories=("visual",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "visual_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "has_visual_evidence": True,
                            "relation_category_hits": ["visual"],
                            "planner_reason_codes": [
                                "visual_support",
                                "visual_grounding",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_visual_support" not in breakdown["reason_counts"]
    assert "missing_required_visual_support" not in breakdown["reason_counts"]
    assert "missing_visual_support" not in breakdown["evidence_need_gap_reason_counts"]


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


def test_fast_gate_metrics_reports_query_role_gap_breakdown() -> None:
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

    assert breakdown["schema_version"] == "query_role_gap_breakdown.v1"
    assert breakdown["role_count"] == 2
    assert breakdown["role_family_count"] == 2
    assert breakdown["candidate_role_count"] == 1
    assert breakdown["role_gap_count"] == 1
    assert breakdown["candidate_role_counts"] == {"relative_temporal_support": 1}
    assert breakdown["selected_item_role_counts"] == {"primary": 1}
    assert breakdown["candidate_role_family_counts"] == {"temporal_support": 1}
    assert breakdown["selected_item_role_family_counts"] == {"primary": 1}
    assert breakdown["roles_without_selected_items"] == ["relative_temporal_support"]
    assert breakdown["roles_without_lifted_candidates"] == []
    assert breakdown["role_gaps"]["relative_temporal_support"] == {
        "candidate_count": 1,
        "lifted_candidate_count": 1,
        "selected_item_count": 0,
        "selection_rate": 0.0,
        "lifted_rate": 1.0,
        "bridge_query_hit_candidate_count": 0,
        "bridge_query_hit_selected_count": 0,
        "avg_candidate_answerability_score": 0.72,
        "avg_selected_answerability_score": 0.0,
        "selected_bundle_role_counts": {},
        "gap_reasons": ["not_selected"],
    }


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
    assert provenance["source_ref_item_coverage_rate"] == 0.3333
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


def _item(
    *,
    case_id: str,
    score: float = 1.0,
    group: str = "multi-hop",
    retrieval_quality: dict[str, object] | None = None,
    evidence_bundle: dict[str, object] | None = None,
    retrieval: dict[str, object] | None = None,
    cutoff_results: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "group": group,
        "scored": True,
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
    risk_flags: tuple[str, ...] = (),
    query_overlap_count: int = 0,
    query_plan: dict[str, object] | None = None,
    candidate_features: dict[str, object] | None = None,
    score_signals: dict[str, object] | None = None,
    item_id: str | None = None,
    rank: int = 1,
    score: float = 0.5,
    memory_text: str = "",
) -> dict[str, object]:
    return {
        "metadata": {
            "query_decomposition": {
                "query_profile": {
                    "evidence_need": evidence_need,
                    "bundle_evidence_roles": bundle_evidence_roles,
                    "relation_categories": relation_categories,
                    "risk_flags": risk_flags,
                },
                "retrieval_intent": {
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
    source_type_diversity: int = 0,
    retrieval_source_diversity: int = 0,
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
    broad_summary_count: int = 0,
    conflict_or_stale_count: int = 0,
    source_proximity_support_count: int = 0,
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
        "source_type_diversity": source_type_diversity,
        "retrieval_source_diversity": retrieval_source_diversity,
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
        "broad_summary_count": broad_summary_count,
        "conflict_or_stale_count": conflict_or_stale_count,
        "source_proximity_support_count": source_proximity_support_count,
    }
