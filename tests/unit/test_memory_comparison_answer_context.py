from infinity_context_server.memory_comparison_answer_context import (
    AnswerContext,
    answer_context_from_evidence_bundle,
    answer_context_metrics,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_answer_context_risk_reasons_are_deduped_across_sources() -> None:
    context = AnswerContext(
        memories=(
            RetrievedMemory(
                text="backfilled summary",
                rank=1,
                metadata={
                    "answer_context_role": "retrieval_backfill",
                    "answer_context_risk_reason_codes": (
                        "risk:retrieval_backfill",
                        "risk:memory_specific",
                    ),
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "broad_summary": True,
                        }
                    },
                },
            ),
        ),
        source="evidence_bundle",
        backfilled_retrieval_item_count=1,
        skipped_redundant_risky_backfill_count=1,
        bundle_risk_reason_codes=(
            "risk:retrieval_backfill",
            "risk:bundle_specific",
        ),
    )

    assert context.to_diagnostics()["risk_reason_codes"] == [
        "risk:retrieval_backfill",
        "risk:bundle_specific",
        "risk:backfilled_broad_summary",
        "risk:skipped_redundant_risky_backfill",
        "risk:memory_specific",
    ]


def test_answer_context_propagates_selected_item_risk_reasons() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="D1:1 Morgan gave a low-confidence preference answer.",
                rank=1,
                item_id="selected",
                source_refs=("D1:1",),
            ),
        ),
        {
            "items": [
                {
                    "id": "selected",
                    "retrieval_order": 1,
                    "role": "primary",
                    "planner_reason_codes": [
                        "role:primary",
                        "risk:low_answerability",
                    ],
                    "eligibility_reason_codes": [
                        "query_support_terms",
                        "risk:wide_relation_expansion",
                    ],
                    "risk_reason_codes": [
                        "risk:selected_item_specific",
                        "not_a_risk",
                    ],
                }
            ]
        },
        cutoff=1,
    )

    assert context.memories[0].metadata["answer_context_risk_reason_codes"] == (
        "risk:low_answerability",
        "risk:wide_relation_expansion",
        "risk:selected_item_specific",
    )
    assert context.to_diagnostics()["risk_reason_codes"] == [
        "risk:low_answerability",
        "risk:wide_relation_expansion",
        "risk:selected_item_specific",
    ]


def test_answer_context_keeps_scalar_bundle_risk_reason_through_skip_and_backfill() -> None:
    memories = (
        RetrievedMemory(
            text="D1:1 Morgan chose the evening class.",
            rank=1,
            item_id="primary",
            source_refs=("D1:1",),
        ),
        RetrievedMemory(
            text="D1:1 Morgan picked the evening class.",
            rank=2,
            item_id="duplicate-contrast",
            source_refs=("D1:1",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.8,
                        "source_locality_score": 0.8,
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D1:3 Morgan said the schedule was the reason.",
            rank=3,
            item_id="backfill-contrast",
            source_refs=("D1:3",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.9,
                        "source_locality_score": 0.9,
                        "relation_category_hits": ["contrast"],
                        "query_roles": ["contrast"],
                        "risk_reason_codes": [
                            "risk:backfill_candidate_specific",
                            "not_a_risk",
                        ],
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "required_roles": ["contrast"],
            "bundle_planner": {
                "bundle_quality": {
                    "reason_codes": "risk:provenance_gap",
                }
            },
            "items": [
                {"id": "primary", "retrieval_order": 1, "role": "primary"},
                {
                    "id": "duplicate-contrast",
                    "retrieval_order": 2,
                    "role": "contrast",
                },
            ],
        },
        cutoff=3,
    )

    bundle_risks = (
        "risk:provenance_gap",
        "risk:missing_required_role",
        "risk:missing_required_contrast",
    )
    assert context.bundle_risk_reason_codes == bundle_risks
    assert context.memories[0].metadata["answer_context_bundle_risk_reason_codes"] == (
        bundle_risks
    )
    assert context.memories[1].metadata["answer_context_bundle_risk_reason_codes"] == (
        bundle_risks
    )
    assert context.skipped_duplicate_source_bundle_item_count == 1
    assert context.backfilled_retrieval_item_count == 1
    assert context.memories[1].metadata["answer_context_risk_reason_codes"] == (
        "risk:retrieval_backfill",
        "risk:backfill_candidate_specific",
        "risk:skipped_duplicate_source_bundle_item",
    )
    assert context.to_diagnostics()["risk_reason_codes"] == [
        "risk:provenance_gap",
        "risk:missing_required_role",
        "risk:missing_required_contrast",
        "risk:skipped_duplicate_source_bundle_item",
        "risk:retrieval_backfill",
        "risk:backfill_candidate_specific",
    ]


def test_answer_context_uses_bundle_order_within_cutoff() -> None:
    memories = (
        RetrievedMemory(text="noise", rank=1, item_id="noise"),
        RetrievedMemory(
            text="bridge",
            rank=2,
            item_id="bridge",
            source_refs=("D2:3",),
        ),
        RetrievedMemory(text="primary", rank=3, item_id="primary"),
        RetrievedMemory(
            text="D5:8 Morgan: I used to prefer solo work, but now I like teams.",
            rank=4,
            item_id="contrast-support",
            source_refs=("D5:8",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.88,
                        "source_locality_score": 0.9,
                        "relation_category_hits": ["contrast"],
                        "entity_hits": ["morgan"],
                        "speaker_hits": ["morgan"],
                        "contrast_surface": True,
                        "stale_surface": True,
                    }
                }
            },
        ),
    )
    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["contrast"],
            "bundle_planner": {
                "bundle_quality": {
                    "confidence_score": 0.68,
                    "confidence_band": "medium",
                    "bridge_count": 1,
                    "source_ref_support_item_count": 2,
                    "source_ref_support_ref_count": 3,
                    "source_identity_support_item_count": 2,
                    "source_identity_support_ref_count": 4,
                    "source_type_diversity": 2,
                    "retrieval_source_diversity": 3,
                    "source_type_support_diversity": 1,
                    "retrieval_source_support_diversity": 2,
                    "source_proximity_support_count": 1,
                    "source_proximity_closest_distance": 2,
                    "source_proximity_distance_counts": {"2": 1},
                    "source_chain_proximity_support_count": 1,
                    "source_chain_proximity_closest_distance": 3,
                    "source_chain_proximity_distance_counts": {"3": 1},
                    "diffuse_source_ref_count": 1,
                    "causal_support_count": 1,
                    "communication_support_count": 9,
                    "event_support_count": 8,
                    "exchange_support_count": 10,
                    "inference_support_count": 2,
                    "location_support_count": 5,
                    "emotion_response_support_count": 6,
                    "symbolic_meaning_support_count": 7,
                    "preference_support_count": 3,
                    "favorite_support_count": 11,
                    "visual_support_count": 4,
                    "typed_relation_support_count": 12,
                    "typed_relation_support_counts": {
                        "favorite_support": 11,
                        "health_support": 1,
                    },
                    "contrast_count": 2,
                    "reason_codes": [
                        "has_primary_evidence",
                        "risk:diffuse_source_refs",
                        "risk:missing_required_role",
                        "risk:missing_required_contrast",
                    ],
                }
            },
            "items": [
                {
                    "id": "primary",
                    "retrieval_order": 3,
                    "role": "primary",
                    "source_refs": ["D4:5"],
                    "planner_reason_codes": ["role:primary", "query_support"],
                    "eligibility_reason_codes": ["query_support_terms"],
                    "query_roles": ["location_support"],
                    "source_type": "raw_turn",
                    "source_types": ["raw_turn", "chunk"],
                    "retrieval_sources": ["raw_turns", "semantic_chunks"],
                    "relation_category_hits": ["location_transition"],
                    "entity_hits": ["caroline"],
                    "speaker_hits": ["caroline"],
                    "answerability_score": 0.91,
                    "source_locality_score": 1.0,
                },
                {"id": "bridge", "retrieval_order": 2, "role": "bridge"},
            ]
        },
        cutoff=4,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "bridge",
        "contrast-support",
    ]
    assert context.memories[0].source_refs == ("D4:5",)
    assert context.memories[0].metadata["answer_context_role"] == "primary"
    assert context.memories[0].metadata["answer_context_retrieval_order"] == 3
    assert context.memories[0].metadata["answer_context_reason_codes"] == (
        "role:primary",
        "query_support",
    )
    assert context.memories[0].metadata[
        "answer_context_eligibility_reason_codes"
    ] == ("query_support_terms",)
    assert context.memories[0].metadata["answer_context_query_roles"] == (
        "location_support",
    )
    assert context.memories[0].metadata["answer_context_source_type"] == "raw_turn"
    assert context.memories[0].metadata["answer_context_source_types"] == (
        "raw_turn",
        "chunk",
    )
    assert context.memories[0].metadata["answer_context_retrieval_sources"] == (
        "raw_turns",
        "semantic_chunks",
    )
    assert context.memories[0].metadata[
        "answer_context_relation_category_hits"
    ] == ("location_transition",)
    assert context.memories[0].metadata["answer_context_entity_hits"] == (
        "caroline",
    )
    assert context.memories[0].metadata["answer_context_speaker_hits"] == (
        "caroline",
    )
    assert context.memories[0].metadata["answer_context_answerability_score"] == 0.91
    assert context.memories[0].metadata["answer_context_source_locality_score"] == 1.0
    assert (
        context.memories[0].metadata["answer_context_bundle_confidence_score"]
        == 0.68
    )
    assert (
        context.memories[0].metadata["answer_context_bundle_confidence_band"]
        == "medium"
    )
    assert context.bundle_bridge_count == 1
    assert context.bundle_source_ref_support_item_count == 2
    assert context.bundle_source_ref_support_ref_count == 3
    assert context.bundle_source_identity_support_item_count == 2
    assert context.bundle_source_identity_support_ref_count == 4
    assert context.bundle_source_type_diversity == 2
    assert context.bundle_retrieval_source_diversity == 3
    assert context.bundle_source_type_support_diversity == 1
    assert context.bundle_retrieval_source_support_diversity == 2
    assert context.bundle_source_proximity_support_count == 1
    assert context.bundle_source_proximity_closest_distance == 2
    assert context.bundle_source_proximity_distance_counts == {"2": 1}
    assert context.bundle_source_chain_proximity_support_count == 1
    assert context.bundle_source_chain_proximity_closest_distance == 3
    assert context.bundle_source_chain_proximity_distance_counts == {"3": 1}
    assert context.bundle_diffuse_source_ref_count == 1
    assert context.bundle_causal_support_count == 1
    assert context.bundle_communication_support_count == 9
    assert context.bundle_event_support_count == 8
    assert context.bundle_exchange_support_count == 10
    assert context.bundle_inference_support_count == 2
    assert context.bundle_location_support_count == 5
    assert context.bundle_emotion_response_support_count == 6
    assert context.bundle_symbolic_meaning_support_count == 7
    assert context.bundle_preference_support_count == 3
    assert context.bundle_favorite_support_count == 11
    assert context.bundle_visual_support_count == 4
    assert context.bundle_typed_relation_support_count == 12
    assert context.bundle_typed_relation_support_counts == {
        "favorite_support": 11,
        "health_support": 1,
    }
    assert context.bundle_contrast_count == 2
    assert context.memories[0].metadata["answer_context_bundle_bridge_count"] == 1
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_source_ref_support_item_count"
        ]
        == 2
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_source_ref_support_ref_count"
        ]
        == 3
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_source_identity_support_item_count"
        ]
        == 2
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_source_identity_support_ref_count"
        ]
        == 4
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_source_type_diversity"
        ]
        == 2
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_retrieval_source_diversity"
        ]
        == 3
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_source_type_support_diversity"
        ]
        == 1
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_retrieval_source_support_diversity"
        ]
        == 2
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_source_proximity_support_count"
        ]
        == 1
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_source_proximity_closest_distance"
        ]
        == 2
    )
    assert context.memories[0].metadata[
        "answer_context_bundle_source_proximity_distance_counts"
    ] == {"2": 1}
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_source_chain_proximity_support_count"
        ]
        == 1
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_source_chain_proximity_closest_distance"
        ]
        == 3
    )
    assert context.memories[0].metadata[
        "answer_context_bundle_source_chain_proximity_distance_counts"
    ] == {"3": 1}
    assert (
        context.memories[0].metadata["answer_context_bundle_diffuse_source_ref_count"]
        == 1
    )
    assert (
        context.memories[0].metadata["answer_context_bundle_causal_support_count"]
        == 1
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_communication_support_count"
        ]
        == 9
    )
    assert (
        context.memories[0].metadata["answer_context_bundle_event_support_count"]
        == 8
    )
    assert (
        context.memories[0].metadata["answer_context_bundle_exchange_support_count"]
        == 10
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_inference_support_count"
        ]
        == 2
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_location_support_count"
        ]
        == 5
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_emotion_response_support_count"
        ]
        == 6
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_symbolic_meaning_support_count"
        ]
        == 7
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_preference_support_count"
        ]
        == 3
    )
    assert (
        context.memories[0].metadata["answer_context_bundle_favorite_support_count"]
        == 11
    )
    assert (
        context.memories[0].metadata["answer_context_bundle_visual_support_count"]
        == 4
    )
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_typed_relation_support_count"
        ]
        == 12
    )
    assert context.memories[0].metadata[
        "answer_context_bundle_typed_relation_support_counts"
    ] == {"favorite_support": 11, "health_support": 1}
    assert context.memories[0].metadata["answer_context_bundle_contrast_count"] == 2
    assert (
        context.memories[0].metadata["answer_context_role_requirement_complete"]
        is False
    )
    assert context.memories[0].metadata["answer_context_missing_required_roles"] == (
        "contrast",
    )
    assert context.memories[0].metadata[
        "answer_context_bundle_risk_reason_codes"
    ] == (
        "risk:diffuse_source_refs",
        "risk:missing_required_role",
        "risk:missing_required_contrast",
    )
    assert context.memories[2].metadata["answer_context_role"] == (
        "retrieval_backfill"
    )
    assert context.memories[2].metadata["answer_context_reason_codes"] == (
        "incomplete_bundle_backfill",
        "retrieval_slice_support",
        "missing_role_support",
    )
    assert context.memories[2].metadata[
        "answer_context_relation_category_hits"
    ] == ("contrast",)
    assert context.memories[2].metadata["answer_context_answerability_score"] == 0.88
    assert context.memories[2].metadata["answer_context_source_locality_score"] == 0.9
    assert context.memories[2].metadata[
        "answer_context_backfill_missing_role_hits"
    ] == ("contrast",)
    assert context.to_diagnostics() == {
        "schema_version": "answer_context.v1",
        "source": "evidence_bundle",
        "memory_count": 3,
        "source_ref_count": 3,
        "source_ref_item_count": 3,
        "source_refless_item_count": 0,
        "source_ref_coverage_rate": 1.0,
        "compacted_fusion_source_ref_item_count": 0,
        "compacted_fusion_source_ref_original_count": 0,
        "compacted_fusion_source_ref_selected_count": 0,
        "compacted_fusion_source_ref_saved_count": 0,
        "avg_answerability_score": 0.5967,
        "avg_measured_answerability_score": 0.895,
        "unmeasured_answerability_count": 1,
        "avg_source_locality_score": 0.6333,
        "avg_measured_source_locality_score": 0.95,
        "unmeasured_source_locality_count": 1,
        "selected_bundle_item_count": 2,
        "skipped_bundle_item_count": 0,
        "skipped_duplicate_source_bundle_item_count": 0,
        "skipped_noisy_overlap_bundle_item_count": 0,
        "backfilled_retrieval_item_count": 1,
        "backfilled_precise_source_overlap_count": 0,
        "skipped_redundant_risky_backfill_count": 0,
        "skipped_redundant_source_backfill_count": 0,
        "skipped_redundant_role_backfill_count": 0,
        "skipped_target_limit_backfill_count": 0,
        "backfilled_broad_summary_count": 0,
        "backfilled_conflict_or_stale_count": 0,
        "backfilled_low_answerability_count": 0,
        "backfilled_weak_source_locality_count": 0,
        "backfilled_low_answerability_role_counts": {},
        "backfilled_weak_source_locality_role_counts": {},
        "backfilled_source_proximity_support_count": 0,
        "backfilled_chained_source_proximity_support_count": 0,
        "backfilled_source_proximity_closest_distance": None,
        "bundle_confidence_score": 0.68,
        "bundle_confidence_band": "medium",
        "bundle_bridge_count": 1,
        "bundle_source_ref_support_item_count": 2,
        "bundle_source_ref_support_ref_count": 3,
        "bundle_source_identity_support_item_count": 2,
        "bundle_source_identity_support_ref_count": 4,
        "bundle_source_type_diversity": 2,
        "bundle_retrieval_source_diversity": 3,
        "bundle_source_type_support_diversity": 1,
        "bundle_retrieval_source_support_diversity": 2,
        "bundle_source_proximity_support_count": 1,
        "bundle_source_proximity_closest_distance": 2,
        "bundle_source_proximity_distance_counts": {"2": 1},
        "bundle_source_chain_proximity_support_count": 1,
        "bundle_source_chain_proximity_closest_distance": 3,
        "bundle_source_chain_proximity_distance_counts": {"3": 1},
        "bundle_diffuse_source_ref_count": 1,
        "bundle_causal_support_count": 1,
        "bundle_communication_support_count": 9,
        "bundle_event_support_count": 8,
        "bundle_exchange_support_count": 10,
        "bundle_inference_support_count": 2,
        "bundle_location_support_count": 5,
        "bundle_emotion_response_support_count": 6,
        "bundle_symbolic_meaning_support_count": 7,
        "bundle_preference_support_count": 3,
        "bundle_favorite_support_count": 11,
        "bundle_visual_support_count": 4,
        "bundle_typed_relation_support_count": 12,
        "bundle_typed_relation_support_counts": {
            "favorite_support": 11,
            "health_support": 1,
        },
        "bundle_contrast_count": 2,
        "role_requirement_complete": False,
        "missing_required_roles": ["contrast"],
        "bundle_risk_reason_codes": [
            "risk:diffuse_source_refs",
            "risk:missing_required_role",
            "risk:missing_required_contrast",
        ],
        "risk_reason_codes": [
            "risk:diffuse_source_refs",
            "risk:missing_required_role",
            "risk:missing_required_contrast",
            "risk:retrieval_backfill",
        ],
        "fallback_reason": None,
        "item_ids": ["primary", "bridge", "contrast-support"],
        "retrieval_orders": [3, 2, 4],
    }


def test_answer_context_preserves_zero_support_source_diversity() -> None:
    memories = (
        RetrievedMemory(
            text="D1:1 Caroline discussed a support group.",
            rank=1,
            item_id="primary",
            source_refs=("D1:1",),
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "bundle_planner": {
                "bundle_quality": {
                    "source_type_diversity": 2,
                    "retrieval_source_diversity": 2,
                    "source_type_support_diversity": 0,
                    "retrieval_source_support_diversity": 0,
                }
            },
            "items": [
                {
                    "id": "primary",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["D1:1"],
                }
            ],
        },
        cutoff=1,
    )

    memory = context.memories[0]

    assert (
        memory.metadata["answer_context_bundle_source_type_support_diversity"]
        == 0
    )
    assert (
        memory.metadata[
            "answer_context_bundle_retrieval_source_support_diversity"
        ]
        == 0
    )
    assert context.bundle_source_type_support_diversity == 0
    assert context.bundle_retrieval_source_support_diversity == 0
    diagnostics = context.to_diagnostics()
    assert diagnostics["bundle_source_type_support_diversity"] == 0
    assert diagnostics["bundle_retrieval_source_support_diversity"] == 0


def test_answer_context_merges_role_completion_from_bundle_and_planner() -> None:
    memories = (
        RetrievedMemory(
            text="primary evidence",
            rank=1,
            item_id="primary",
            source_refs=("D1:1",),
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": True,
            "missing_required_roles": ["contrast"],
            "bundle_planner": {
                "role_requirement_complete": False,
                "missing_required_roles": ["visual_support"],
                "bundle_quality": {
                    "confidence_score": 0.42,
                    "confidence_band": "low",
                    "reason_codes": ["risk:missing_required_visual_support"],
                },
            },
            "items": [
                {
                    "id": "primary",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["D1:1"],
                }
            ],
        },
        cutoff=1,
    )

    metadata = context.memories[0].metadata
    assert metadata["answer_context_role_requirement_complete"] is False
    assert metadata["answer_context_missing_required_roles"] == (
        "contrast",
        "visual_support",
    )
    assert context.to_diagnostics()["role_requirement_complete"] is False
    assert context.to_diagnostics()["missing_required_roles"] == [
        "contrast",
        "visual_support",
    ]


def test_answer_context_surfaces_inspection_flags_for_weak_bundle() -> None:
    memories = (
        RetrievedMemory(
            text="primary evidence",
            rank=1,
            item_id="primary",
            source_refs=("D1:1",),
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["contrast"],
            "bundle_planner": {
                "bundle_quality": {
                    "confidence_score": 0.42,
                    "confidence_band": "low",
                    "source_type_diversity": 1,
                },
            },
            "items": [
                {
                    "id": "primary",
                    "retrieval_order": 1,
                    "role": "primary",
                    "answerability_score": 0.4,
                    "source_locality_score": 0.3,
                }
            ],
        },
        cutoff=1,
    )

    assert context.to_diagnostics()["inspection_flags"] == [
        "missing_required_roles",
        "low_bundle_confidence",
        "weak_bundle_source_support",
        "low_context_answerability",
        "weak_context_source_locality",
    ]


def test_answer_context_matches_source_turn_dedupe_key_without_retrieval_order() -> None:
    memories = (
        RetrievedMemory(text="noise", rank=1),
        RetrievedMemory(
            text="D4:2 Caroline: I found the support group helpful.",
            rank=2,
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.91,
                        "source_ref_dedupe_key": "source_turn_refs:D4:2",
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "role": "primary",
                    "source_ref_dedupe_key": "source_turn_refs:D4:2",
                    "answerability_score": 0.91,
                }
            ]
        },
        cutoff=2,
    )

    assert [memory.text for memory in context.memories] == [
        "D4:2 Caroline: I found the support group helpful."
    ]
    assert context.memories[0].source_refs == ("source_turn_refs:D4:2",)
    assert context.memories[0].metadata["answer_context_retrieval_order"] == 2
    assert context.to_diagnostics()["source_ref_count"] == 1
    assert context.to_diagnostics()["source_ref_item_count"] == 1


def test_answer_context_matches_canonical_source_ref_to_source_turn_key() -> None:
    memories = (
        RetrievedMemory(text="noise", rank=1),
        RetrievedMemory(
            text="Caroline found the support group helpful.",
            rank=2,
            source_refs=("locomo:conv-19:session_4:D4:2:chunk",),
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "role": "primary",
                    "source_ref_dedupe_key": "source_turn_refs:D4:2",
                }
            ]
        },
        cutoff=2,
    )

    assert [memory.text for memory in context.memories] == [
        "Caroline found the support group helpful."
    ]
    assert context.memories[0].source_refs == (
        "locomo:conv-19:session_4:D4:2:chunk",
        "source_session_turn_refs:session_4:D4:2",
        "source_turn_refs:D4:2",
    )
    assert context.memories[0].metadata["answer_context_retrieval_order"] == 2


def test_answer_context_matches_session_qualified_turn_key() -> None:
    memories = (
        RetrievedMemory(
            text="session_11 date: Friday D1:8 Caroline discussed old adoption notes.",
            rank=1,
            item_id="cross-session-noise",
        ),
        RetrievedMemory(
            text="session_1 date: Monday D1:8 Caroline discussed adoption support.",
            rank=2,
            item_id="session-evidence",
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "role": "primary",
                    "source_ref_dedupe_key": "source_session_turn_refs:session_1:D1:8",
                }
            ]
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == ["session-evidence"]
    assert context.memories[0].source_refs == (
        "source_session_turn_refs:session_1:D1:8",
        "source_turn_refs:D1:8",
    )


def test_answer_context_does_not_match_same_dialogue_different_session_source_ref() -> None:
    memories = (
        RetrievedMemory(
            text="wrong session evidence",
            rank=1,
            item_id="wrong-session",
            source_refs=("locomo:conv-19:session_11:D1:8:turn",),
        ),
        RetrievedMemory(
            text="correct session evidence",
            rank=2,
            item_id="correct-session",
            source_refs=("locomo:conv-19:session_1:D1:8:turn",),
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "role": "primary",
                    "source_refs": ["locomo:conv-19:session_1:D1:8:turn"],
                }
            ]
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == ["correct-session"]
    assert "source_session_turn_refs:session_1:D1:8" in context.memories[0].source_refs
    assert (
        "source_session_turn_refs:session_11:D1:8"
        not in context.memories[0].source_refs
    )


def test_answer_context_requires_session_match_for_session_qualified_bundle_key() -> None:
    memories = (
        RetrievedMemory(
            text="D1:8 unqualified evidence from a hydrated source sibling.",
            rank=1,
            item_id="unqualified",
            source_refs=("D1:8",),
        ),
        RetrievedMemory(
            text="session_11 date: Friday D1:8 wrong session evidence.",
            rank=2,
            item_id="wrong-session",
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "role": "primary",
                    "source_ref_dedupe_key": "source_session_turn_refs:session_1:D1:8",
                }
            ]
        },
        cutoff=2,
    )

    assert context.source == "retrieval_slice"
    assert context.fallback_reason == "no_bundle_items_within_cutoff"


def test_answer_context_matches_partial_multi_turn_source_identity() -> None:
    memories = (
        RetrievedMemory(text="noise", rank=1),
        RetrievedMemory(
            text="D2:8 Caroline: I wrote the note after the meeting.",
            rank=2,
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "role": "primary",
                    "source_ref_dedupe_key": "source_turn_refs:D2:8|D2:9",
                }
            ]
        },
        cutoff=2,
    )

    assert [memory.text for memory in context.memories] == [
        "D2:8 Caroline: I wrote the note after the meeting."
    ]
    assert context.memories[0].source_refs == (
        "source_turn_refs:D2:8",
        "source_turn_refs:D2:9",
    )
    assert context.memories[0].metadata["answer_context_retrieval_order"] == 2


def test_answer_context_matches_fusion_turn_ref_dedupe_key() -> None:
    memories = (
        RetrievedMemory(
            text="Caroline adoption evidence",
            rank=1,
            metadata={
                "diagnostics": {
                    "benchmark_candidate_fusion": {
                        "dedupe_key": "turn_refs:D2:8|D2:9"
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "role": "primary",
                    "source_ref_dedupe_key": "source_turn_refs:D2:9",
                }
            ]
        },
        cutoff=1,
    )

    assert [memory.text for memory in context.memories] == [
        "Caroline adoption evidence"
    ]
    assert context.memories[0].source_refs == (
        "source_turn_refs:D2:8",
        "source_turn_refs:D2:9",
    )


def test_answer_context_matches_fusion_source_identity_dedupe_key() -> None:
    memories = (
        RetrievedMemory(
            text="Caroline adoption evidence",
            rank=1,
            metadata={
                "diagnostics": {
                    "benchmark_candidate_fusion": {
                        "dedupe_key": "source_identity:source_turn_refs:D2:9"
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "role": "primary",
                    "source_ref_dedupe_key": "source_turn_refs:D2:9",
                }
            ]
        },
        cutoff=1,
    )

    assert [memory.text for memory in context.memories] == [
        "Caroline adoption evidence"
    ]
    assert context.memories[0].source_refs == ("source_turn_refs:D2:9",)


def test_answer_context_skips_duplicate_source_bundle_items() -> None:
    memories = (
        RetrievedMemory(
            text="Caroline found the support group helpful.",
            rank=1,
            item_id="turn-chunk-a",
            source_refs=("locomo:conv-19:session_4:D4:2:chunk-a",),
        ),
        RetrievedMemory(
            text="Caroline found the support group helpful again.",
            rank=2,
            item_id="turn-chunk-b",
            source_refs=("locomo:conv-19:session_4:D4:2:chunk-b",),
        ),
        RetrievedMemory(
            text="Caroline said the group met nearby.",
            rank=3,
            item_id="nearby-turn",
            source_refs=("D4:3",),
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "id": "turn-chunk-a",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["locomo:conv-19:session_4:D4:2:chunk-a"],
                },
                {
                    "id": "turn-chunk-b",
                    "retrieval_order": 2,
                    "role": "support",
                    "source_refs": ["locomo:conv-19:session_4:D4:2:chunk-b"],
                },
                {
                    "id": "nearby-turn",
                    "retrieval_order": 3,
                    "role": "support",
                    "source_refs": ["D4:3"],
                },
            ]
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "turn-chunk-a",
        "nearby-turn",
    ]
    assert context.memories[0].metadata[
        "answer_context_skipped_duplicate_source_bundle_item_count"
    ] == 1
    assert context.selected_bundle_item_count == 2
    assert context.skipped_bundle_item_count == 1
    assert context.skipped_duplicate_source_bundle_item_count == 1
    assert context.memories[0].metadata["answer_context_risk_reason_codes"] == (
        "risk:skipped_duplicate_source_bundle_item",
    )
    diagnostics = context.to_diagnostics()
    assert diagnostics["skipped_bundle_item_count"] == 1
    assert diagnostics["skipped_duplicate_source_bundle_item_count"] == 1
    assert diagnostics["risk_reason_codes"] == [
        "risk:skipped_duplicate_source_bundle_item",
    ]


def test_answer_context_skips_duplicate_exact_and_canonical_turn_sources() -> None:
    memories = (
        RetrievedMemory(
            text="D4:2 Caroline found the support group helpful.",
            rank=1,
            item_id="exact-turn",
            source_refs=("D4:2",),
        ),
        RetrievedMemory(
            text="Caroline found the support group helpful.",
            rank=2,
            item_id="canonical-turn",
            source_refs=("locomo:conv-19:session_4:D4:2:chunk",),
        ),
        RetrievedMemory(
            text="D4:3 Caroline said the group met nearby.",
            rank=3,
            item_id="sibling-turn",
            source_refs=("D4:3",),
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "id": "exact-turn",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["D4:2"],
                },
                {
                    "id": "canonical-turn",
                    "retrieval_order": 2,
                    "role": "support",
                    "source_refs": ["locomo:conv-19:session_4:D4:2:chunk"],
                },
                {
                    "id": "sibling-turn",
                    "retrieval_order": 3,
                    "role": "support",
                    "source_refs": ["D4:3"],
                },
            ]
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "exact-turn",
        "sibling-turn",
    ]
    assert context.skipped_duplicate_source_bundle_item_count == 1


def test_answer_context_keeps_cross_session_canonical_chunk_sources() -> None:
    memories = (
        RetrievedMemory(
            text="session_1 D1:8 Caroline discussed adoption support.",
            rank=1,
            item_id="session-one",
            source_refs=("locomo:conv-19:session_1:D1:8:chunk-a",),
        ),
        RetrievedMemory(
            text="session_11 D1:8 Caroline discussed old adoption notes.",
            rank=2,
            item_id="session-eleven",
            source_refs=("locomo:conv-19:session_11:D1:8:chunk-b",),
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "id": "session-one",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["locomo:conv-19:session_1:D1:8:chunk-a"],
                },
                {
                    "id": "session-eleven",
                    "retrieval_order": 2,
                    "role": "support",
                    "source_refs": ["locomo:conv-19:session_11:D1:8:chunk-b"],
                },
            ]
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == [
        "session-one",
        "session-eleven",
    ]
    assert context.memories[0].source_refs == (
        "locomo:conv-19:session_1:D1:8:chunk-a",
        "source_session_turn_refs:session_1:D1:8",
        "source_turn_refs:D1:8",
    )
    assert context.memories[1].source_refs == (
        "locomo:conv-19:session_11:D1:8:chunk-b",
        "source_session_turn_refs:session_11:D1:8",
        "source_turn_refs:D1:8",
    )
    assert context.skipped_duplicate_source_bundle_item_count == 0


def test_answer_context_skips_noisy_overlapping_bundle_summary() -> None:
    memories = (
        RetrievedMemory(
            text="D4:2 Caroline found the support group helpful.",
            rank=1,
            item_id="primary-turn",
            source_refs=("D4:2",),
        ),
        RetrievedMemory(
            text=(
                "Conversation summary: related turns D4:2 and D4:3 say "
                "Caroline discussed the support group."
            ),
            rank=2,
            item_id="overlapping-summary",
            source_refs=("D4:2", "D4:3"),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {"broad_summary": True}
                }
            },
        ),
        RetrievedMemory(
            text="D4:3 Caroline said the group met nearby.",
            rank=3,
            item_id="sibling-turn",
            source_refs=("D4:3",),
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "id": "primary-turn",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["D4:2"],
                },
                {
                    "id": "overlapping-summary",
                    "retrieval_order": 2,
                    "role": "support",
                    "source_refs": ["D4:2", "D4:3"],
                },
                {
                    "id": "sibling-turn",
                    "retrieval_order": 3,
                    "role": "support",
                    "source_refs": ["D4:3"],
                },
            ]
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary-turn",
        "sibling-turn",
    ]
    assert context.memories[0].metadata[
        "answer_context_skipped_noisy_overlap_bundle_item_count"
    ] == 1
    assert context.memories[0].metadata["answer_context_risk_reason_codes"] == (
        "risk:skipped_noisy_overlap_bundle_item",
    )
    assert context.skipped_duplicate_source_bundle_item_count == 0
    assert context.skipped_noisy_overlap_bundle_item_count == 1
    assert context.to_diagnostics()["risk_reason_codes"] == [
        "risk:skipped_noisy_overlap_bundle_item",
    ]


def test_answer_context_skips_noisy_summary_even_when_ranked_first() -> None:
    memories = (
        RetrievedMemory(
            text=(
                "Conversation summary: related turns D4:2 and D4:3 say "
                "Caroline discussed the support group."
            ),
            rank=1,
            item_id="overlapping-summary",
            source_refs=("D4:2", "D4:3"),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {"broad_summary": True}
                }
            },
        ),
        RetrievedMemory(
            text="D4:2 Caroline found the support group helpful.",
            rank=2,
            item_id="primary-turn",
            source_refs=("D4:2",),
        ),
        RetrievedMemory(
            text="D4:3 Caroline said the group met nearby.",
            rank=3,
            item_id="sibling-turn",
            source_refs=("D4:3",),
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "id": "overlapping-summary",
                    "retrieval_order": 1,
                    "role": "support",
                    "source_refs": ["D4:2", "D4:3"],
                },
                {
                    "id": "primary-turn",
                    "retrieval_order": 2,
                    "role": "primary",
                    "source_refs": ["D4:2"],
                },
                {
                    "id": "sibling-turn",
                    "retrieval_order": 3,
                    "role": "support",
                    "source_refs": ["D4:3"],
                },
            ]
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary-turn",
        "sibling-turn",
    ]
    assert context.skipped_duplicate_source_bundle_item_count == 0
    assert context.skipped_noisy_overlap_bundle_item_count == 1


def test_answer_context_backfill_carries_text_turn_source_identity() -> None:
    memories = (
        RetrievedMemory(text="primary", rank=1, item_id="primary"),
        RetrievedMemory(
            text="D5:3 Morgan: I used to prefer solo work, but now I prefer teams.",
            rank=2,
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.82,
                        "relation_category_hits": ["contrast"],
                        "contrast_surface": True,
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["contrast"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=2,
    )

    assert context.memories[1].metadata["answer_context_role"] == (
        "retrieval_backfill"
    )
    assert context.memories[1].source_refs == ("source_turn_refs:D5:3",)
    assert context.to_diagnostics()["source_ref_count"] == 1
    assert context.to_diagnostics()["source_ref_item_count"] == 1


def test_answer_context_diagnostics_distinguish_unmeasured_quality_scores() -> None:
    memories = (
        RetrievedMemory(text="unmeasured evidence", rank=1, item_id="unmeasured"),
        RetrievedMemory(text="measured evidence", rank=2, item_id="measured"),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "id": "unmeasured",
                    "retrieval_order": 1,
                    "role": "primary",
                    "answerability_score": 0.0,
                    "source_locality_score": 0.0,
                },
                {
                    "id": "measured",
                    "retrieval_order": 2,
                    "role": "bridge",
                    "answerability_score": 0.8,
                    "source_locality_score": 0.7,
                },
            ]
        },
        cutoff=2,
    )

    diagnostics = context.to_diagnostics()

    assert "answer_context_answerability_score" not in context.memories[0].metadata
    assert "answer_context_source_locality_score" not in context.memories[0].metadata
    assert diagnostics["avg_answerability_score"] == 0.4
    assert diagnostics["avg_measured_answerability_score"] == 0.8
    assert diagnostics["unmeasured_answerability_count"] == 1
    assert diagnostics["avg_source_locality_score"] == 0.35
    assert diagnostics["avg_measured_source_locality_score"] == 0.7
    assert diagnostics["unmeasured_source_locality_count"] == 1


def test_answer_context_respects_cutoff_and_falls_back_to_raw_slice() -> None:
    memories = (
        RetrievedMemory(text="first", rank=1, item_id="first"),
        RetrievedMemory(text="selected late", rank=2, item_id="late"),
    )
    context = answer_context_from_evidence_bundle(
        memories,
        {"items": [{"id": "late", "retrieval_order": 2, "role": "primary"}]},
        cutoff=1,
    )

    assert [memory.item_id for memory in context.memories] == ["first"]
    assert context.source == "retrieval_slice"
    assert context.fallback_reason == "no_bundle_items_within_cutoff"
    assert context.skipped_bundle_item_count == 1
    assert context.memories[0].metadata["answer_context_retrieval_order"] == 1
    assert context.memories[0].metadata["answer_context_fallback_reason"] == (
        "no_bundle_items_within_cutoff"
    )


def test_answer_context_backfill_prefers_local_role_evidence_over_summary() -> None:
    memories = (
        RetrievedMemory(text="primary", rank=1, item_id="primary"),
        RetrievedMemory(
            text=(
                "Conversation summary: Morgan used to prefer solo work, "
                "but now prefers teams."
            ),
            rank=2,
            item_id="summary-contrast",
            source_refs=("D5:1", "D5:2", "D5:3", "D5:4"),
            metadata={
                "diagnostics": {
                    "stale_reason": "older_preference_summary",
                    "benchmark_candidate_features": {
                        "answerability_score": 0.98,
                        "source_locality_score": 0.45,
                        "relation_category_hits": ["contrast"],
                        "contrast_surface": True,
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D5:3 Morgan: I used to prefer solo work, but now I prefer teams.",
            rank=3,
            item_id="localized-contrast",
            source_refs=("D5:3",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.82,
                        "source_locality_score": 1.0,
                        "relation_category_hits": ["contrast"],
                        "contrast_surface": True,
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["contrast"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "localized-contrast",
    ]
    assert context.memories[1].metadata[
        "answer_context_backfill_missing_role_hits"
    ] == ("contrast",)
    assert context.backfilled_retrieval_item_count == 1
    assert context.skipped_redundant_risky_backfill_count == 1
    assert (
        context.memories[0].metadata["answer_context_risk_reason_codes"]
        == ("risk:skipped_redundant_risky_backfill",)
    )
    diagnostics = context.to_diagnostics()
    assert diagnostics["skipped_redundant_risky_backfill_count"] == 1
    assert "risk:skipped_redundant_risky_backfill" in diagnostics[
        "risk_reason_codes"
    ]
    assert diagnostics["backfilled_broad_summary_count"] == 0
    assert diagnostics["backfilled_conflict_or_stale_count"] == 0


def test_answer_context_backfill_skips_when_no_missing_roles_are_reported() -> None:
    memories = (
        RetrievedMemory(text="primary", rank=1, item_id="primary"),
        RetrievedMemory(
            text="D5:3 Morgan: I used to prefer solo work, but now I prefer teams.",
            rank=2,
            item_id="localized-contrast",
            source_refs=("D5:3",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.82,
                        "source_locality_score": 1.0,
                        "relation_category_hits": ["contrast"],
                        "contrast_surface": True,
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == ["primary"]
    assert context.backfilled_retrieval_item_count == 0
    diagnostics = context.to_diagnostics()
    assert diagnostics["backfilled_broad_summary_count"] == 0
    assert diagnostics["skipped_redundant_role_backfill_count"] == 0


def test_answer_context_backfill_honors_selected_bundle_role_metadata() -> None:
    memories = (
        RetrievedMemory(
            text="D5:3 Morgan: I used to prefer solo work, but now I prefer teams.",
            rank=1,
            item_id="selected-contrast",
            source_refs=("D5:3",),
        ),
        RetrievedMemory(
            text="D9:20 Morgan mentioned a weaker contrast later.",
            rank=2,
            item_id="far-contrast",
            source_refs=("D9:20",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.7,
                        "source_locality_score": 0.6,
                        "relation_category_hits": ["contrast"],
                        "contrast_surface": True,
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["contrast"],
            "items": [
                {
                    "id": "selected-contrast",
                    "retrieval_order": 1,
                    "role": "support",
                    "relation_category_hits": ["contrast"],
                }
            ],
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == ["selected-contrast"]
    assert context.backfilled_retrieval_item_count == 0
    assert context.skipped_redundant_role_backfill_count == 1
    assert context.to_diagnostics()["skipped_redundant_role_backfill_count"] == 1


def test_answer_context_backfill_honors_selected_bundle_direct_role() -> None:
    memories = (
        RetrievedMemory(
            text="D5:3 Morgan: I used to prefer solo work, but now I prefer teams.",
            rank=1,
            item_id="selected-contrast",
            source_refs=("D5:3",),
        ),
        RetrievedMemory(
            text="D9:20 Morgan mentioned a weaker contrast later.",
            rank=2,
            item_id="far-contrast",
            source_refs=("D9:20",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.7,
                        "source_locality_score": 0.6,
                        "relation_category_hits": ["contrast"],
                        "contrast_surface": True,
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["contrast_support"],
            "items": [
                {
                    "id": "selected-contrast",
                    "retrieval_order": 1,
                    "role": "contrast",
                }
            ],
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == ["selected-contrast"]
    assert context.backfilled_retrieval_item_count == 0
    assert context.skipped_redundant_role_backfill_count == 1


def test_answer_context_backfill_keeps_risky_role_evidence_when_no_compact_support() -> None:
    memories = (
        RetrievedMemory(
            text="D5:1 Morgan: I prefer teams now.",
            rank=1,
            item_id="primary",
            source_refs=("D5:1",),
        ),
        RetrievedMemory(
            text=(
                "Conversation summary: D5:1 D5:2 D5:3 D5:4 Morgan used to "
                "prefer solo work, but now prefers teams."
            ),
            rank=2,
            item_id="summary-contrast",
            source_refs=("D5:1", "D5:2", "D5:3", "D5:4"),
            metadata={
                "diagnostics": {
                    "stale_reason": "older_preference_summary",
                    "benchmark_candidate_features": {
                        "answerability_score": 0.98,
                        "source_locality_score": 0.45,
                        "relation_category_hits": ["contrast"],
                        "contrast_surface": True,
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["contrast"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "summary-contrast",
    ]
    assert context.backfilled_retrieval_item_count == 1
    assert context.skipped_redundant_risky_backfill_count == 0
    diagnostics = context.to_diagnostics()
    assert diagnostics["skipped_redundant_risky_backfill_count"] == 0
    assert diagnostics["backfilled_broad_summary_count"] == 1
    assert diagnostics["backfilled_conflict_or_stale_count"] == 1


def test_answer_context_backfill_matches_profile_support_categories() -> None:
    memories = (
        RetrievedMemory(text="primary", rank=1, item_id="primary"),
        RetrievedMemory(
            text="D2:4 Alex: Maria is my sister.",
            rank=2,
            item_id="status-profile",
            source_refs=("D2:4",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.86,
                        "source_locality_score": 0.9,
                        "query_roles": ["compact_relation"],
                        "relation_category_hits": ["status_profile"],
                        "entity_hits": ["alex", "maria"],
                        "speaker_hits": ["alex"],
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["status_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "status-profile",
    ]
    assert context.memories[1].metadata[
        "answer_context_backfill_missing_role_hits"
    ] == ("status_support",)
    assert context.memories[1].metadata["answer_context_relation_category_hits"] == (
        "status_profile",
    )
    assert context.backfilled_retrieval_item_count == 1


def test_answer_context_backfill_matches_goal_support_categories() -> None:
    memories = (
        RetrievedMemory(text="primary", rank=1, item_id="primary"),
        RetrievedMemory(
            text=(
                "D2:4 Caroline: The support I received growing up shaped why "
                "I want to become a counselor."
            ),
            rank=2,
            item_id="support-goal",
            source_refs=("D2:4",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.86,
                        "source_locality_score": 0.9,
                        "query_roles": ["compact_relation"],
                        "relation_category_hits": ["support_goal"],
                        "entity_hits": ["caroline"],
                        "speaker_hits": ["caroline"],
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["support_goal_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "support-goal",
    ]
    assert context.memories[1].metadata[
        "answer_context_backfill_missing_role_hits"
    ] == ("support_goal_support",)
    assert context.memories[1].metadata["answer_context_relation_category_hits"] == (
        "support_goal",
    )
    assert context.backfilled_retrieval_item_count == 1


def test_answer_context_backfill_matches_current_goal_categories() -> None:
    memories = (
        RetrievedMemory(text="primary", rank=1, item_id="primary"),
        RetrievedMemory(
            text="D2:4 Caroline: My current goal is to stay local this year.",
            rank=2,
            item_id="current-goal",
            source_refs=("D2:4",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.86,
                        "source_locality_score": 0.9,
                        "query_roles": ["compact_relation"],
                        "relation_category_hits": ["current_goal"],
                        "entity_hits": ["caroline"],
                        "speaker_hits": ["caroline"],
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["current_goal_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "current-goal",
    ]
    assert context.memories[1].metadata[
        "answer_context_backfill_missing_role_hits"
    ] == ("current_goal_support",)
    assert context.memories[1].metadata["answer_context_relation_category_hits"] == (
        "current_goal",
    )
    assert context.backfilled_retrieval_item_count == 1


def test_answer_context_backfill_requires_typed_role_evidence_over_query_role() -> None:
    memories = (
        RetrievedMemory(text="primary", rank=1, item_id="primary"),
        RetrievedMemory(
            text="D2:4 Alex: I like green paint in that mural.",
            rank=2,
            item_id="generic-preference",
            source_refs=("D2:4",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.95,
                        "source_locality_score": 1.0,
                        "query_roles": ["favorite_support"],
                        "relation_category_hits": ["preference"],
                        "has_preference_evidence": True,
                        "entity_hits": ["alex"],
                        "speaker_hits": ["alex"],
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D2:5 Alex: My favorite color is green.",
            rank=3,
            item_id="favorite-preference",
            source_refs=("D2:5",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.82,
                        "source_locality_score": 0.9,
                        "query_roles": ["favorite_support"],
                        "relation_category_hits": [
                            "favorite_preference",
                            "preference",
                        ],
                        "has_preference_evidence": True,
                        "entity_hits": ["alex"],
                        "speaker_hits": ["alex"],
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["favorite_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "favorite-preference",
    ]
    assert context.memories[1].metadata[
        "answer_context_backfill_missing_role_hits"
    ] == ("favorite_support",)
    assert context.backfilled_retrieval_item_count == 1


def test_answer_context_backfill_prefers_unmeasured_grounded_role_evidence() -> None:
    memories = (
        RetrievedMemory(text="primary", rank=1, item_id="primary"),
        RetrievedMemory(
            text="D5:2 Morgan maybe changed their preference.",
            rank=2,
            item_id="measured-weak",
            source_refs=("D5:2",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.4,
                        "source_locality_score": 0.3,
                        "relation_category_hits": ["contrast"],
                        "contrast_surface": True,
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D5:3 Morgan: I used to prefer solo work, but now I prefer teams.",
            rank=3,
            item_id="unmeasured-grounded",
            source_refs=("D5:3",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.0,
                        "source_locality_score": 0.0,
                        "relation_category_hits": ["contrast"],
                        "contrast_surface": True,
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["contrast"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "unmeasured-grounded",
    ]
    assert "answer_context_answerability_score" not in context.memories[1].metadata
    assert "answer_context_source_locality_score" not in context.memories[1].metadata
    assert context.skipped_redundant_role_backfill_count == 1


def test_answer_context_backfill_does_not_prefer_low_quality_sibling() -> None:
    memories = (
        RetrievedMemory(
            text="D6:1 Alex mentioned Maria.",
            rank=1,
            item_id="primary",
            source_refs=("D6:1",),
        ),
        RetrievedMemory(
            text="D8:9 Maria is Alex's sister.",
            rank=2,
            item_id="clean-status",
            source_refs=("D8:9",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "query_roles": ["status_support"],
                        "relation_category_hits": ["status_profile"],
                        "entity_hits": ["alex", "maria"],
                        "answerability_score": 0.84,
                        "source_locality_score": 0.9,
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D6:2 Maria might be Alex's sister.",
            rank=3,
            item_id="weak-near-status",
            source_refs=("D6:2",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "query_roles": ["status_support"],
                        "relation_category_hits": ["status_profile"],
                        "entity_hits": ["alex", "maria"],
                        "answerability_score": 0.4,
                        "source_locality_score": 0.3,
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["status_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "clean-status",
    ]
    assert "source_proximity_support" not in context.memories[1].metadata[
        "answer_context_reason_codes"
    ]
    assert context.skipped_redundant_role_backfill_count == 1
    assert (
        context.memories[0].metadata[
            "answer_context_skipped_redundant_role_backfill_count"
        ]
        == 1
    )
    assert (
        context.memories[1].metadata[
            "answer_context_skipped_redundant_role_backfill_count"
        ]
        == 1
    )
    diagnostics = context.to_diagnostics()
    assert diagnostics["backfilled_low_answerability_count"] == 0
    assert diagnostics["backfilled_weak_source_locality_count"] == 0
    assert diagnostics["backfilled_source_proximity_support_count"] == 0


def test_answer_context_diagnostics_bucket_weak_backfill_by_missing_role() -> None:
    memories = (
        RetrievedMemory(
            text="D6:1 Alex mentioned Maria.",
            rank=1,
            item_id="primary",
            source_refs=("D6:1",),
        ),
        RetrievedMemory(
            text="D6:2 Maria might be Alex's sister.",
            rank=2,
            item_id="weak-status",
            source_refs=("D6:2",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "query_roles": ["status_support"],
                        "relation_category_hits": ["status_profile"],
                        "entity_hits": ["alex", "maria"],
                        "answerability_score": 0.4,
                        "source_locality_score": 0.3,
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["status_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=2,
    )

    diagnostics = context.to_diagnostics()

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "weak-status",
    ]
    assert diagnostics["backfilled_low_answerability_count"] == 1
    assert diagnostics["backfilled_weak_source_locality_count"] == 1
    assert diagnostics["backfilled_low_answerability_role_counts"] == {
        "status_support": 1
    }
    assert diagnostics["backfilled_weak_source_locality_role_counts"] == {
        "status_support": 1
    }
    assert context.memories[1].metadata["answer_context_risk_reason_codes"] == (
        "risk:retrieval_backfill",
        "risk:backfilled_low_answerability",
        "risk:backfilled_weak_source_locality",
    )
    assert diagnostics["risk_reason_codes"] == [
        "risk:retrieval_backfill",
        "risk:backfilled_low_answerability",
        "risk:backfilled_weak_source_locality",
    ]


def test_answer_context_backfill_prefers_source_proximate_role_evidence() -> None:
    memories = (
        RetrievedMemory(
            text="D2:10 Morgan: I signed up for the class.",
            rank=1,
            item_id="primary",
            source_refs=("D2:10",),
        ),
        RetrievedMemory(
            text="D2:20 Morgan: I mentioned a different class later.",
            rank=2,
            item_id="far-event",
            source_refs=("D2:20",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.95,
                        "source_locality_score": 0.9,
                        "relation_category_hits": ["registration_event"],
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D2:12 Morgan: The class registration email arrived.",
            rank=3,
            item_id="near-event",
            source_refs=("D2:12",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.6,
                        "source_locality_score": 0.7,
                        "relation_category_hits": ["registration_event"],
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["event_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "near-event",
    ]
    assert "source_proximity_support" in context.memories[1].metadata[
        "answer_context_reason_codes"
    ]
    assert (
        context.memories[1].metadata[
            "answer_context_backfill_source_proximity_distance"
        ]
        == 2
    )
    assert context.skipped_redundant_role_backfill_count == 1
    diagnostics = context.to_diagnostics()
    assert diagnostics["skipped_redundant_role_backfill_count"] == 1
    assert diagnostics["backfilled_source_proximity_support_count"] == 1
    assert diagnostics["backfilled_source_proximity_closest_distance"] == 2


def test_answer_context_backfill_extends_source_proximity_from_added_support() -> None:
    memories = (
        RetrievedMemory(
            text="D2:10 Morgan: I signed up for the class.",
            rank=1,
            item_id="primary",
            source_refs=("D2:10",),
        ),
        RetrievedMemory(
            text="D2:13 Morgan: The class registration email arrived.",
            rank=2,
            item_id="near-event",
            source_refs=("D2:13",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.8,
                        "source_locality_score": 0.85,
                        "relation_category_hits": ["registration_event"],
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D2:15 Morgan: I replied to the registration email.",
            rank=3,
            item_id="near-added-event",
            source_refs=("D2:15",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.7,
                        "source_locality_score": 0.8,
                        "relation_category_hits": ["registration_event"],
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["event_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "near-event",
        "near-added-event",
    ]
    assert (
        context.memories[2].metadata[
            "answer_context_backfill_source_proximity_distance"
        ]
        == 2
    )
    assert (
        context.memories[2].metadata[
            "answer_context_backfill_chained_source_proximity"
        ]
        is True
    )
    assert "chained_source_proximity_support" in context.memories[2].metadata[
        "answer_context_reason_codes"
    ]
    assert context.backfilled_retrieval_item_count == 2


def test_answer_context_backfill_skips_duplicate_source_role_evidence() -> None:
    memories = (
        RetrievedMemory(
            text="D2:10 Morgan: I signed up for the class.",
            rank=1,
            item_id="primary",
            source_refs=("locomo:conv-1:session_2:D2:10:turn",),
        ),
        RetrievedMemory(
            text="D2:12 Morgan: The class registration email arrived.",
            rank=2,
            item_id="event-turn",
            source_refs=("locomo:conv-1:session_2:D2:12:turn",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.84,
                        "source_locality_score": 0.95,
                        "relation_category_hits": ["registration_event"],
                    }
                }
            },
        ),
        RetrievedMemory(
            text="Chunk: Morgan received the class registration email.",
            rank=3,
            item_id="event-duplicate-chunk",
            source_refs=("locomo:conv-1:session_2:D2:12:turn",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.72,
                        "source_locality_score": 0.9,
                        "relation_category_hits": ["registration_event"],
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["event_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "event-turn",
    ]
    assert context.backfilled_retrieval_item_count == 1
    assert context.skipped_redundant_source_backfill_count == 1
    assert (
        context.memories[0].metadata["answer_context_risk_reason_codes"]
        == ("risk:skipped_redundant_source_backfill",)
    )
    diagnostics = context.to_diagnostics()
    assert diagnostics["skipped_redundant_source_backfill_count"] == 1
    assert "risk:skipped_redundant_source_backfill" in diagnostics[
        "risk_reason_codes"
    ]
    assert diagnostics["backfilled_source_proximity_support_count"] == 1


def test_answer_context_backfill_skips_selected_source_duplicate() -> None:
    memories = (
        RetrievedMemory(
            text="D2:10 Morgan: I signed up for the class.",
            rank=1,
            item_id="primary",
            source_refs=("D2:10",),
        ),
        RetrievedMemory(
            text="Morgan signed up for the class.",
            rank=2,
            item_id="duplicate-primary-chunk",
            source_refs=("locomo:conv-1:session_2:D2:10:chunk",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.97,
                        "source_locality_score": 1.0,
                        "relation_category_hits": ["activity"],
                        "query_roles": ["event_support"],
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D2:12 Morgan: The class registration went through.",
            rank=3,
            item_id="sibling-event",
            source_refs=("D2:12",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.88,
                        "source_locality_score": 0.92,
                        "relation_category_hits": ["registration_event"],
                        "query_roles": ["event_support"],
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["event_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "sibling-event",
    ]
    assert context.backfilled_retrieval_item_count == 1
    assert context.skipped_redundant_source_backfill_count == 1
    assert context.to_diagnostics()["skipped_redundant_source_backfill_count"] == 1


def test_answer_context_backfill_requires_content_time_for_temporal_role_hit() -> None:
    memories = (
        RetrievedMemory(text="primary", rank=1, item_id="primary"),
        RetrievedMemory(
            text=(
                "session_1 turn D1:1 date: 10:00 am "
                "D1:1 Alex mentioned the checklist."
            ),
            rank=2,
            item_id="metadata-only-time",
            source_refs=("D1:1",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.9,
                        "source_locality_score": 0.9,
                        "entity_hits": ["alex"],
                        "speaker_hits": ["alex"],
                        "relation_hits": ["mention", "checklist"],
                        "query_roles": ["temporal_support"],
                        "has_explicit_time_surface": True,
                        "has_explicit_time_content_surface": False,
                        "time_intent_kind": "explicit_time",
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D2:3 Alex: I mentioned the checklist on Friday afternoon.",
            rank=3,
            item_id="content-time",
            source_refs=("D2:3",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.82,
                        "source_locality_score": 0.9,
                        "entity_hits": ["alex"],
                        "speaker_hits": ["alex"],
                        "relation_hits": ["mention", "checklist"],
                        "query_roles": ["temporal_support"],
                        "has_explicit_time_surface": True,
                        "has_explicit_time_content_surface": True,
                        "time_intent_kind": "explicit_time",
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["temporal_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "content-time",
    ]
    assert context.memories[1].metadata[
        "answer_context_backfill_missing_role_hits"
    ] == ("temporal_support",)
    assert context.backfilled_retrieval_item_count == 1


def test_answer_context_backfill_requires_visual_and_time_for_visual_temporal_role() -> None:
    memories = (
        RetrievedMemory(text="primary", rank=1, item_id="primary"),
        RetrievedMemory(
            text="D1:1 Alex sent Maria a photo from the appointment.",
            rank=2,
            item_id="visual-only",
            source_refs=("D1:1",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.9,
                        "source_locality_score": 0.9,
                        "entity_hits": ["alex"],
                        "speaker_hits": ["alex"],
                        "relation_hits": ["photo"],
                        "query_roles": ["visual_temporal_support"],
                        "has_visual_evidence": True,
                        "time_intent_kind": "explicit_time",
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D2:3 Alex: I sent Maria the photo on Friday afternoon.",
            rank=3,
            item_id="visual-time",
            source_refs=("D2:3",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.82,
                        "source_locality_score": 0.9,
                        "entity_hits": ["alex"],
                        "speaker_hits": ["alex"],
                        "relation_hits": ["photo"],
                        "query_roles": ["visual_temporal_support"],
                        "has_visual_evidence": True,
                        "has_explicit_time_content_surface": True,
                        "time_intent_kind": "explicit_time",
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["visual_temporal_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "visual-time",
    ]
    assert context.memories[1].metadata[
        "answer_context_backfill_missing_role_hits"
    ] == ("visual_temporal_support",)
    assert context.backfilled_retrieval_item_count == 1


def test_answer_context_backfill_requires_action_category_for_action_role() -> None:
    memories = (
        RetrievedMemory(text="primary", rank=1, item_id="primary"),
        RetrievedMemory(
            text="D1:1 Alex mentioned class supplies.",
            rank=2,
            item_id="query-role-only",
            source_refs=("D1:1",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.95,
                        "source_locality_score": 0.9,
                        "entity_hits": ["alex"],
                        "speaker_hits": ["alex"],
                        "relation_hits": ["class"],
                        "query_roles": ["action_support"],
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D2:3 Alex: I took the notebook to class.",
            rank=3,
            item_id="action-evidence",
            source_refs=("D2:3",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.82,
                        "source_locality_score": 0.9,
                        "entity_hits": ["alex"],
                        "speaker_hits": ["alex"],
                        "relation_hits": ["take", "class"],
                        "query_roles": ["action_support"],
                        "relation_category_hits": ["action_event"],
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["action_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "action-evidence",
    ]
    assert context.memories[1].metadata[
        "answer_context_backfill_missing_role_hits"
    ] == ("action_support",)
    assert context.backfilled_retrieval_item_count == 1


def test_answer_context_backfills_required_role_skipped_after_bundle_planning() -> None:
    memories = (
        RetrievedMemory(
            text="D1:10 Alex: I chose the class because the schedule fit.",
            rank=1,
            item_id="primary",
            source_refs=("D1:10",),
        ),
        RetrievedMemory(
            text="Conversation summary: D1:10 Alex chose the class because it fit.",
            rank=2,
            item_id="noisy-causal",
            source_refs=("D1:10",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.9,
                        "source_locality_score": 0.9,
                        "broad_summary": True,
                        "entity_hits": ["alex"],
                        "speaker_hits": ["alex"],
                        "relation_hits": ["because", "choose"],
                        "relation_category_hits": ["causal"],
                        "query_roles": ["causal_support"],
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D1:12 Alex: The evening schedule was the reason I signed up.",
            rank=3,
            item_id="precise-causal",
            source_refs=("D1:12",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.86,
                        "source_locality_score": 0.92,
                        "entity_hits": ["alex"],
                        "speaker_hits": ["alex"],
                        "relation_hits": ["reason", "signed"],
                        "relation_category_hits": ["causal"],
                        "query_roles": ["causal_support"],
                    }
                }
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": True,
            "required_roles": ["primary", "causal_support"],
            "missing_required_roles": [],
            "items": [
                {
                    "id": "primary",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["D1:10"],
                },
                {
                    "id": "noisy-causal",
                    "retrieval_order": 2,
                    "role": "causal_support",
                    "source_refs": ["D1:10"],
                    "query_roles": ["causal_support"],
                },
            ],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "precise-causal",
    ]
    assert context.role_requirement_complete is False
    assert context.missing_required_roles == ("causal_support",)
    assert context.backfilled_retrieval_item_count == 1
    assert context.skipped_duplicate_source_bundle_item_count == 1
    assert context.memories[0].metadata[
        "answer_context_missing_required_roles"
    ] == ("causal_support",)
    assert context.memories[1].metadata[
        "answer_context_backfill_missing_role_hits"
    ] == ("causal_support",)


def test_answer_context_falls_back_for_empty_bundle() -> None:
    memories = (
        RetrievedMemory(text="first", rank=1, item_id="first"),
        RetrievedMemory(text="second", rank=2, item_id="second"),
    )
    context = answer_context_from_evidence_bundle(memories, {"items": []}, cutoff=2)

    assert [memory.item_id for memory in context.memories] == ["first", "second"]
    assert context.source == "retrieval_slice"
    assert context.fallback_reason == "empty_bundle"


def test_answer_context_metrics_aggregates_sources_and_compression() -> None:
    metrics = answer_context_metrics(
        (
            {
                "scored": True,
                "cutoff_results": {
                    "3": {
                        "memories_evaluated": 3,
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 1,
                            "source_ref_count": 1,
                            "source_ref_item_count": 1,
                            "source_refless_item_count": 0,
                            "source_ref_coverage_rate": 1.0,
                            "compacted_fusion_source_ref_item_count": 1,
                            "compacted_fusion_source_ref_saved_count": 3,
                            "avg_answerability_score": 0.4,
                            "avg_measured_answerability_score": 0.8,
                            "unmeasured_answerability_count": 1,
                            "avg_source_locality_score": 0.35,
                            "avg_measured_source_locality_score": 0.7,
                            "unmeasured_source_locality_count": 1,
                            "selected_bundle_item_count": 1,
                            "skipped_bundle_item_count": 0,
                            "skipped_duplicate_source_bundle_item_count": 1,
                            "skipped_noisy_overlap_bundle_item_count": 1,
                            "backfilled_retrieval_item_count": 1,
                            "backfilled_precise_source_overlap_count": 1,
                            "skipped_redundant_risky_backfill_count": 1,
                            "skipped_redundant_source_backfill_count": 1,
                            "skipped_redundant_role_backfill_count": 1,
                            "skipped_target_limit_backfill_count": 1,
                            "backfilled_broad_summary_count": 0,
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
                            "bundle_confidence_score": 0.68,
                            "bundle_confidence_band": "medium",
                            "bundle_bridge_count": 1,
                            "bundle_source_ref_support_item_count": 2,
                            "bundle_source_ref_support_ref_count": 3,
                            "bundle_source_identity_support_item_count": 2,
                            "bundle_source_identity_support_ref_count": 4,
                            "bundle_source_type_diversity": 2,
                            "bundle_retrieval_source_diversity": 3,
                            "bundle_source_type_support_diversity": 1,
                            "bundle_retrieval_source_support_diversity": 2,
                            "bundle_source_proximity_support_count": 1,
                            "bundle_source_proximity_closest_distance": 2,
                            "bundle_source_proximity_distance_counts": {
                                "2": 1,
                            },
                            "bundle_source_chain_proximity_support_count": 1,
                            "bundle_source_chain_proximity_closest_distance": 3,
                            "bundle_source_chain_proximity_distance_counts": {
                                "3": 1,
                            },
                            "bundle_diffuse_source_ref_count": 1,
                            "bundle_causal_support_count": 1,
                            "bundle_event_support_count": 8,
                            "bundle_inference_support_count": 2,
                            "bundle_location_support_count": 5,
                            "bundle_emotion_response_support_count": 6,
                            "bundle_symbolic_meaning_support_count": 7,
                            "bundle_preference_support_count": 3,
                            "bundle_favorite_support_count": 11,
                            "bundle_visual_support_count": 4,
                            "bundle_typed_relation_support_count": 12,
                            "bundle_typed_relation_support_counts": {
                                "favorite_support": 11,
                                "health_support": 1,
                            },
                            "bundle_contrast_count": 2,
                            "role_requirement_complete": False,
                            "missing_required_roles": ["contrast"],
                            "bundle_risk_reason_codes": [
                                "risk:missing_required_role",
                                "risk:missing_required_contrast",
                            ],
                            "risk_reason_codes": [
                                "risk:missing_required_role",
                                "risk:missing_required_contrast",
                                "risk:skipped_duplicate_source_bundle_item",
                                "risk:skipped_noisy_overlap_bundle_item",
                                "risk:retrieval_backfill",
                                "risk:backfilled_low_answerability",
                                "risk:backfilled_weak_source_locality",
                                "risk:skipped_redundant_risky_backfill",
                                "risk:skipped_redundant_source_backfill",
                                "risk:skipped_redundant_role_backfill",
                                "risk:skipped_target_limit_backfill",
                            ],
                            "inspection_flags": [
                                "missing_required_roles",
                                "low_answerability_backfill",
                                "weak_source_locality_backfill",
                            ],
                        },
                    }
                },
            },
            {
                "scored": True,
                "cutoff_results": {
                    "3": {
                        "memories_evaluated": 3,
                        "answer_context": {
                            "source": "retrieval_slice",
                            "memory_count": 3,
                            "source_ref_count": 0,
                            "source_ref_item_count": 0,
                            "source_refless_item_count": 3,
                            "source_ref_coverage_rate": 0.0,
                            "fallback_reason": "empty_bundle",
                            "selected_bundle_item_count": 0,
                            "skipped_bundle_item_count": 0,
                            "skipped_duplicate_source_bundle_item_count": 0,
                            "skipped_noisy_overlap_bundle_item_count": 0,
                            "inspection_flags": ["retrieval_slice_fallback"],
                        },
                    }
                },
            },
        ),
        configured_cutoffs=(3,),
        primary_cutoff=3,
    )

    primary = metrics["by_cutoff"]["3"]

    assert metrics["schema_version"] == "answer_context_metrics.v1"
    assert metrics["primary_evidence_bundle_context_rate"] == 0.5
    assert metrics["primary_avg_context_memory_count"] == 2.0
    assert metrics["primary_avg_context_compression_ratio"] == 0.6667
    assert metrics["primary_total_skipped_redundant_risky_backfill_count"] == 1
    assert metrics["primary_avg_skipped_redundant_risky_backfill_count"] == 0.5
    assert metrics["primary_total_skipped_redundant_source_backfill_count"] == 1
    assert metrics["primary_avg_skipped_redundant_source_backfill_count"] == 0.5
    assert metrics["primary_total_skipped_redundant_role_backfill_count"] == 1
    assert metrics["primary_avg_skipped_redundant_role_backfill_count"] == 0.5
    assert metrics["primary_total_skipped_target_limit_backfill_count"] == 1
    assert metrics["primary_avg_skipped_target_limit_backfill_count"] == 0.5
    assert metrics["primary_total_skipped_duplicate_source_bundle_item_count"] == 1
    assert metrics["primary_avg_skipped_duplicate_source_bundle_item_count"] == 0.5
    assert metrics["primary_total_skipped_noisy_overlap_bundle_item_count"] == 1
    assert metrics["primary_avg_skipped_noisy_overlap_bundle_item_count"] == 0.5
    assert metrics["primary_risk_reason_counts"] == {
        "risk:backfilled_low_answerability": 1,
        "risk:backfilled_weak_source_locality": 1,
        "risk:missing_required_contrast": 1,
        "risk:missing_required_role": 1,
        "risk:retrieval_backfill": 1,
        "risk:skipped_duplicate_source_bundle_item": 1,
        "risk:skipped_noisy_overlap_bundle_item": 1,
        "risk:skipped_redundant_risky_backfill": 1,
        "risk:skipped_redundant_role_backfill": 1,
        "risk:skipped_redundant_source_backfill": 1,
        "risk:skipped_target_limit_backfill": 1,
    }
    assert metrics["primary_inspection_flag_counts"] == {
        "low_answerability_backfill": 1,
        "missing_required_roles": 1,
        "retrieval_slice_fallback": 1,
        "weak_source_locality_backfill": 1,
    }
    assert metrics["primary_total_backfilled_low_answerability_count"] == 1
    assert metrics["primary_total_backfilled_precise_source_overlap_count"] == 1
    assert metrics["primary_avg_backfilled_precise_source_overlap_count"] == 0.5
    assert metrics["primary_avg_backfilled_low_answerability_count"] == 0.5
    assert metrics["primary_total_backfilled_weak_source_locality_count"] == 1
    assert metrics["primary_avg_backfilled_weak_source_locality_count"] == 0.5
    assert metrics["primary_backfilled_low_answerability_role_counts"] == {
        "contrast": 1
    }
    assert metrics["primary_backfilled_weak_source_locality_role_counts"] == {
        "contrast": 1
    }
    assert metrics["primary_total_backfilled_source_proximity_support_count"] == 1
    assert metrics["primary_avg_backfilled_source_proximity_support_count"] == 0.5
    assert (
        metrics[
            "primary_total_backfilled_chained_source_proximity_support_count"
        ]
        == 1
    )
    assert (
        metrics["primary_avg_backfilled_chained_source_proximity_support_count"]
        == 0.5
    )
    assert metrics["primary_avg_backfilled_source_proximity_closest_distance"] == 2.0
    assert metrics["primary_min_backfilled_source_proximity_closest_distance"] == 2
    assert metrics["primary_avg_source_ref_coverage_rate"] == 0.5
    assert metrics["primary_total_compacted_fusion_source_ref_item_count"] == 1
    assert metrics["primary_total_compacted_fusion_source_ref_saved_count"] == 3
    assert metrics["primary_avg_context_answerability_score"] == 0.2
    assert metrics["primary_avg_measured_context_answerability_score"] == 0.8
    assert metrics["primary_total_unmeasured_context_answerability_count"] == 1
    assert metrics["primary_avg_context_source_locality_score"] == 0.175
    assert metrics["primary_avg_measured_context_source_locality_score"] == 0.7
    assert metrics["primary_total_unmeasured_context_source_locality_count"] == 1
    assert metrics["primary_avg_bundle_source_type_diversity"] == 1.0
    assert metrics["primary_max_bundle_source_type_diversity"] == 2
    assert metrics["primary_avg_bundle_retrieval_source_diversity"] == 1.5
    assert metrics["primary_max_bundle_retrieval_source_diversity"] == 3
    assert metrics["primary_avg_bundle_source_type_support_diversity"] == 0.5
    assert metrics["primary_max_bundle_source_type_support_diversity"] == 1
    assert (
        metrics["primary_avg_bundle_retrieval_source_support_diversity"]
        == 1.0
    )
    assert metrics["primary_max_bundle_retrieval_source_support_diversity"] == 2
    assert metrics["primary_avg_bundle_source_ref_support_item_count"] == 1.0
    assert metrics["primary_total_bundle_source_ref_support_item_count"] == 2
    assert (
        metrics["primary_avg_bundle_source_identity_support_item_count"]
        == 1.0
    )
    assert (
        metrics["primary_total_bundle_source_identity_support_item_count"]
        == 2
    )
    assert metrics["primary_avg_bundle_source_proximity_support_count"] == 0.5
    assert (
        metrics["primary_total_bundle_source_proximity_support_count"]
        == 1
    )
    assert (
        metrics["primary_avg_bundle_source_proximity_closest_distance"]
        == 2.0
    )
    assert metrics["primary_min_bundle_source_proximity_closest_distance"] == 2
    assert metrics["primary_bundle_source_proximity_distance_counts"] == {
        "2": 1,
    }
    assert (
        metrics["primary_avg_bundle_source_chain_proximity_support_count"]
        == 0.5
    )
    assert (
        metrics["primary_total_bundle_source_chain_proximity_support_count"]
        == 1
    )
    assert (
        metrics["primary_avg_bundle_source_chain_proximity_closest_distance"]
        == 3.0
    )
    assert (
        metrics["primary_min_bundle_source_chain_proximity_closest_distance"]
        == 3
    )
    assert metrics["primary_bundle_source_chain_proximity_distance_counts"] == {
        "3": 1,
    }
    assert metrics["primary_avg_bundle_diffuse_source_ref_count"] == 0.5
    assert metrics["primary_total_bundle_diffuse_source_ref_count"] == 1
    assert primary["evidence_bundle_context_count"] == 1
    assert primary["fallback_context_count"] == 1
    assert primary["avg_backfilled_retrieval_item_count"] == 0.5
    assert primary["total_backfilled_retrieval_item_count"] == 1
    assert primary["avg_backfilled_precise_source_overlap_count"] == 0.5
    assert primary["total_backfilled_precise_source_overlap_count"] == 1
    assert primary["avg_skipped_redundant_risky_backfill_count"] == 0.5
    assert primary["total_skipped_redundant_risky_backfill_count"] == 1
    assert primary["avg_skipped_redundant_source_backfill_count"] == 0.5
    assert primary["total_skipped_redundant_source_backfill_count"] == 1
    assert primary["avg_skipped_redundant_role_backfill_count"] == 0.5
    assert primary["total_skipped_redundant_role_backfill_count"] == 1
    assert primary["avg_skipped_target_limit_backfill_count"] == 0.5
    assert primary["total_skipped_target_limit_backfill_count"] == 1
    assert primary["avg_skipped_duplicate_source_bundle_item_count"] == 0.5
    assert primary["total_skipped_duplicate_source_bundle_item_count"] == 1
    assert primary["avg_skipped_noisy_overlap_bundle_item_count"] == 0.5
    assert primary["total_skipped_noisy_overlap_bundle_item_count"] == 1
    assert primary["total_backfilled_broad_summary_count"] == 0
    assert primary["total_backfilled_conflict_or_stale_count"] == 0
    assert primary["total_backfilled_low_answerability_count"] == 1
    assert primary["avg_backfilled_low_answerability_count"] == 0.5
    assert primary["total_backfilled_weak_source_locality_count"] == 1
    assert primary["avg_backfilled_weak_source_locality_count"] == 0.5
    assert primary["backfilled_low_answerability_role_counts"] == {"contrast": 1}
    assert primary["backfilled_weak_source_locality_role_counts"] == {"contrast": 1}
    assert primary["total_backfilled_source_proximity_support_count"] == 1
    assert primary["avg_backfilled_source_proximity_support_count"] == 0.5
    assert primary["total_backfilled_chained_source_proximity_support_count"] == 1
    assert primary["avg_backfilled_chained_source_proximity_support_count"] == 0.5
    assert primary["avg_backfilled_source_proximity_closest_distance"] == 2.0
    assert primary["min_backfilled_source_proximity_closest_distance"] == 2
    assert primary["source_counts"] == {
        "evidence_bundle": 1,
        "retrieval_slice": 1,
    }
    assert primary["fallback_reason_counts"] == {"empty_bundle": 1}
    assert primary["avg_bundle_confidence_score"] == 0.68
    assert primary["avg_bundle_bridge_count"] == 0.5
    assert primary["total_bundle_bridge_count"] == 1
    assert primary["avg_bundle_source_ref_support_item_count"] == 1.0
    assert primary["total_bundle_source_ref_support_item_count"] == 2
    assert primary["avg_bundle_source_ref_support_ref_count"] == 1.5
    assert primary["total_bundle_source_ref_support_ref_count"] == 3
    assert primary["avg_bundle_source_identity_support_item_count"] == 1.0
    assert primary["total_bundle_source_identity_support_item_count"] == 2
    assert primary["avg_bundle_source_identity_support_ref_count"] == 2.0
    assert primary["total_bundle_source_identity_support_ref_count"] == 4
    assert primary["avg_bundle_source_type_diversity"] == 1.0
    assert primary["max_bundle_source_type_diversity"] == 2
    assert primary["avg_bundle_retrieval_source_diversity"] == 1.5
    assert primary["max_bundle_retrieval_source_diversity"] == 3
    assert primary["avg_bundle_source_type_support_diversity"] == 0.5
    assert primary["max_bundle_source_type_support_diversity"] == 1
    assert primary["avg_bundle_retrieval_source_support_diversity"] == 1.0
    assert primary["max_bundle_retrieval_source_support_diversity"] == 2
    assert primary["avg_bundle_source_proximity_support_count"] == 0.5
    assert primary["total_bundle_source_proximity_support_count"] == 1
    assert primary["avg_bundle_source_proximity_closest_distance"] == 2.0
    assert primary["min_bundle_source_proximity_closest_distance"] == 2
    assert primary["bundle_source_proximity_distance_counts"] == {"2": 1}
    assert primary["avg_bundle_source_chain_proximity_support_count"] == 0.5
    assert primary["total_bundle_source_chain_proximity_support_count"] == 1
    assert primary["avg_bundle_source_chain_proximity_closest_distance"] == 3.0
    assert primary["min_bundle_source_chain_proximity_closest_distance"] == 3
    assert primary["bundle_source_chain_proximity_distance_counts"] == {"3": 1}
    assert primary["avg_bundle_diffuse_source_ref_count"] == 0.5
    assert primary["total_bundle_diffuse_source_ref_count"] == 1
    assert primary["avg_bundle_causal_support_count"] == 0.5
    assert primary["total_bundle_causal_support_count"] == 1
    assert primary["avg_bundle_event_support_count"] == 4.0
    assert primary["total_bundle_event_support_count"] == 8
    assert primary["avg_bundle_inference_support_count"] == 1.0
    assert primary["total_bundle_inference_support_count"] == 2
    assert primary["avg_bundle_location_support_count"] == 2.5
    assert primary["total_bundle_location_support_count"] == 5
    assert primary["avg_bundle_emotion_response_support_count"] == 3.0
    assert primary["total_bundle_emotion_response_support_count"] == 6
    assert primary["avg_bundle_symbolic_meaning_support_count"] == 3.5
    assert primary["total_bundle_symbolic_meaning_support_count"] == 7
    assert primary["avg_bundle_preference_support_count"] == 1.5
    assert primary["total_bundle_preference_support_count"] == 3
    assert primary["avg_bundle_favorite_support_count"] == 5.5
    assert primary["total_bundle_favorite_support_count"] == 11
    assert primary["avg_bundle_visual_support_count"] == 2.0
    assert primary["total_bundle_visual_support_count"] == 4
    assert primary["avg_bundle_typed_relation_support_count"] == 6.0
    assert primary["total_bundle_typed_relation_support_count"] == 12
    assert primary["bundle_typed_relation_support_role_counts"] == {
        "favorite_support": 11,
        "health_support": 1,
    }
    assert primary["avg_bundle_contrast_count"] == 1.0
    assert primary["total_bundle_contrast_count"] == 2
    assert primary["avg_source_ref_count"] == 0.5
    assert primary["avg_source_ref_item_count"] == 0.5
    assert primary["avg_source_refless_item_count"] == 1.5
    assert primary["avg_source_ref_coverage_rate"] == 0.5
    assert primary["avg_compacted_fusion_source_ref_item_count"] == 0.5
    assert primary["total_compacted_fusion_source_ref_item_count"] == 1
    assert primary["avg_compacted_fusion_source_ref_saved_count"] == 1.5
    assert primary["total_compacted_fusion_source_ref_saved_count"] == 3
    assert primary["avg_context_answerability_score"] == 0.2
    assert primary["avg_measured_context_answerability_score"] == 0.8
    assert primary["total_unmeasured_context_answerability_count"] == 1
    assert primary["avg_context_source_locality_score"] == 0.175
    assert primary["avg_measured_context_source_locality_score"] == 0.7
    assert primary["total_unmeasured_context_source_locality_count"] == 1
    assert primary["bundle_confidence_band_counts"] == {"medium": 1}
    assert primary["incomplete_role_requirement_count"] == 1
    assert primary["missing_required_role_counts"] == {"contrast": 1}
    assert primary["bundle_risk_reason_counts"] == {
        "risk:missing_required_contrast": 1,
        "risk:missing_required_role": 1,
    }
    assert primary["risk_reason_counts"] == {
        "risk:backfilled_low_answerability": 1,
        "risk:backfilled_weak_source_locality": 1,
        "risk:missing_required_contrast": 1,
        "risk:missing_required_role": 1,
        "risk:retrieval_backfill": 1,
        "risk:skipped_duplicate_source_bundle_item": 1,
        "risk:skipped_noisy_overlap_bundle_item": 1,
        "risk:skipped_redundant_risky_backfill": 1,
        "risk:skipped_redundant_role_backfill": 1,
        "risk:skipped_redundant_source_backfill": 1,
        "risk:skipped_target_limit_backfill": 1,
    }
    assert primary["inspection_flag_counts"] == {
        "low_answerability_backfill": 1,
        "missing_required_roles": 1,
        "retrieval_slice_fallback": 1,
        "weak_source_locality_backfill": 1,
    }
