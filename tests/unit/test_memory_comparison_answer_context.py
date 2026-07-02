from infinity_context_server.memory_comparison_answer_context import (
    answer_context_from_evidence_bundle,
    answer_context_metrics,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


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
                    "source_proximity_support_count": 1,
                    "causal_support_count": 1,
                    "inference_support_count": 2,
                    "location_support_count": 5,
                    "preference_support_count": 3,
                    "visual_support_count": 4,
                    "reason_codes": [
                        "has_primary_evidence",
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
                    "relation_category_hits": ["location_transition"],
                    "answerability_score": 0.91,
                    "source_locality_score": 1.0,
                },
                {"id": "bridge", "retrieval_order": 2, "role": "bridge"},
            ]
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == ["primary", "bridge"]
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
    assert context.memories[0].metadata[
        "answer_context_relation_category_hits"
    ] == ("location_transition",)
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
    assert context.bundle_source_proximity_support_count == 1
    assert context.bundle_causal_support_count == 1
    assert context.bundle_inference_support_count == 2
    assert context.bundle_location_support_count == 5
    assert context.bundle_preference_support_count == 3
    assert context.bundle_visual_support_count == 4
    assert (
        context.memories[0].metadata[
            "answer_context_bundle_source_proximity_support_count"
        ]
        == 1
    )
    assert (
        context.memories[0].metadata["answer_context_bundle_causal_support_count"]
        == 1
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
            "answer_context_bundle_preference_support_count"
        ]
        == 3
    )
    assert (
        context.memories[0].metadata["answer_context_bundle_visual_support_count"]
        == 4
    )
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
        "risk:missing_required_role",
        "risk:missing_required_contrast",
    )
    assert context.to_diagnostics() == {
        "schema_version": "answer_context.v1",
        "source": "evidence_bundle",
        "memory_count": 2,
        "source_ref_count": 2,
        "source_ref_item_count": 2,
        "source_refless_item_count": 0,
        "source_ref_coverage_rate": 1.0,
        "selected_bundle_item_count": 2,
        "skipped_bundle_item_count": 0,
        "bundle_confidence_score": 0.68,
        "bundle_confidence_band": "medium",
        "bundle_source_proximity_support_count": 1,
        "bundle_causal_support_count": 1,
        "bundle_inference_support_count": 2,
        "bundle_location_support_count": 5,
        "bundle_preference_support_count": 3,
        "bundle_visual_support_count": 4,
        "role_requirement_complete": False,
        "missing_required_roles": ["contrast"],
        "bundle_risk_reason_codes": [
            "risk:missing_required_role",
            "risk:missing_required_contrast",
        ],
        "fallback_reason": None,
        "item_ids": ["primary", "bridge"],
        "retrieval_orders": [3, 2],
    }


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
                            "selected_bundle_item_count": 1,
                            "skipped_bundle_item_count": 0,
                            "bundle_confidence_score": 0.68,
                            "bundle_confidence_band": "medium",
                            "bundle_source_proximity_support_count": 1,
                            "bundle_causal_support_count": 1,
                            "bundle_inference_support_count": 2,
                            "bundle_location_support_count": 5,
                            "bundle_preference_support_count": 3,
                            "bundle_visual_support_count": 4,
                            "role_requirement_complete": False,
                            "missing_required_roles": ["contrast"],
                            "bundle_risk_reason_codes": [
                                "risk:missing_required_role",
                                "risk:missing_required_contrast",
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
    assert metrics["primary_avg_source_ref_coverage_rate"] == 0.5
    assert primary["evidence_bundle_context_count"] == 1
    assert primary["fallback_context_count"] == 1
    assert primary["source_counts"] == {
        "evidence_bundle": 1,
        "retrieval_slice": 1,
    }
    assert primary["fallback_reason_counts"] == {"empty_bundle": 1}
    assert primary["avg_bundle_confidence_score"] == 0.68
    assert primary["avg_bundle_source_proximity_support_count"] == 0.5
    assert primary["total_bundle_source_proximity_support_count"] == 1
    assert primary["avg_bundle_causal_support_count"] == 0.5
    assert primary["total_bundle_causal_support_count"] == 1
    assert primary["avg_bundle_inference_support_count"] == 1.0
    assert primary["total_bundle_inference_support_count"] == 2
    assert primary["avg_bundle_location_support_count"] == 2.5
    assert primary["total_bundle_location_support_count"] == 5
    assert primary["avg_bundle_preference_support_count"] == 1.5
    assert primary["total_bundle_preference_support_count"] == 3
    assert primary["avg_bundle_visual_support_count"] == 2.0
    assert primary["total_bundle_visual_support_count"] == 4
    assert primary["avg_source_ref_count"] == 0.5
    assert primary["avg_source_ref_item_count"] == 0.5
    assert primary["avg_source_refless_item_count"] == 1.5
    assert primary["avg_source_ref_coverage_rate"] == 0.5
    assert primary["bundle_confidence_band_counts"] == {"medium": 1}
    assert primary["incomplete_role_requirement_count"] == 1
    assert primary["missing_required_role_counts"] == {"contrast": 1}
    assert primary["bundle_risk_reason_counts"] == {
        "risk:missing_required_contrast": 1,
        "risk:missing_required_role": 1,
    }
