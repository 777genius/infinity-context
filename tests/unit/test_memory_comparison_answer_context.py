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
                    "source_type_diversity": 2,
                    "retrieval_source_diversity": 3,
                    "source_proximity_support_count": 1,
                    "source_proximity_closest_distance": 2,
                    "causal_support_count": 1,
                    "communication_support_count": 9,
                    "event_support_count": 8,
                    "exchange_support_count": 10,
                    "inference_support_count": 2,
                    "location_support_count": 5,
                    "emotion_response_support_count": 6,
                    "symbolic_meaning_support_count": 7,
                    "preference_support_count": 3,
                    "visual_support_count": 4,
                    "contrast_count": 2,
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
        "noise",
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
    assert context.bundle_source_type_diversity == 2
    assert context.bundle_retrieval_source_diversity == 3
    assert context.bundle_source_proximity_support_count == 1
    assert context.bundle_source_proximity_closest_distance == 2
    assert context.bundle_causal_support_count == 1
    assert context.bundle_communication_support_count == 9
    assert context.bundle_event_support_count == 8
    assert context.bundle_exchange_support_count == 10
    assert context.bundle_inference_support_count == 2
    assert context.bundle_location_support_count == 5
    assert context.bundle_emotion_response_support_count == 6
    assert context.bundle_symbolic_meaning_support_count == 7
    assert context.bundle_preference_support_count == 3
    assert context.bundle_visual_support_count == 4
    assert context.bundle_contrast_count == 2
    assert context.memories[0].metadata["answer_context_bundle_bridge_count"] == 1
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
        context.memories[0].metadata["answer_context_bundle_visual_support_count"]
        == 4
    )
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
    assert context.memories[3].metadata["answer_context_role"] == (
        "retrieval_backfill"
    )
    assert context.to_diagnostics() == {
        "schema_version": "answer_context.v1",
        "source": "evidence_bundle",
        "memory_count": 4,
        "source_ref_count": 3,
        "source_ref_item_count": 3,
        "source_refless_item_count": 1,
        "source_ref_coverage_rate": 0.75,
        "avg_answerability_score": 0.4475,
        "avg_measured_answerability_score": 0.895,
        "unmeasured_answerability_count": 2,
        "avg_source_locality_score": 0.475,
        "avg_measured_source_locality_score": 0.95,
        "unmeasured_source_locality_count": 2,
        "selected_bundle_item_count": 2,
        "skipped_bundle_item_count": 0,
        "backfilled_retrieval_item_count": 2,
        "backfilled_broad_summary_count": 0,
        "backfilled_conflict_or_stale_count": 0,
        "backfilled_source_proximity_support_count": 0,
        "backfilled_source_proximity_closest_distance": None,
        "bundle_confidence_score": 0.68,
        "bundle_confidence_band": "medium",
        "bundle_bridge_count": 1,
        "bundle_source_type_diversity": 2,
        "bundle_retrieval_source_diversity": 3,
        "bundle_source_proximity_support_count": 1,
        "bundle_source_proximity_closest_distance": 2,
        "bundle_causal_support_count": 1,
        "bundle_communication_support_count": 9,
        "bundle_event_support_count": 8,
        "bundle_exchange_support_count": 10,
        "bundle_inference_support_count": 2,
        "bundle_location_support_count": 5,
        "bundle_emotion_response_support_count": 6,
        "bundle_symbolic_meaning_support_count": 7,
        "bundle_preference_support_count": 3,
        "bundle_visual_support_count": 4,
        "bundle_contrast_count": 2,
        "role_requirement_complete": False,
        "missing_required_roles": ["contrast"],
        "bundle_risk_reason_codes": [
            "risk:missing_required_role",
            "risk:missing_required_contrast",
        ],
        "fallback_reason": None,
        "item_ids": ["primary", "bridge", "contrast-support", "noise"],
        "retrieval_orders": [3, 2, 4, 1],
    }


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
        "source_turn_refs:D4:2",
    )
    assert context.memories[0].metadata["answer_context_retrieval_order"] == 2


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
        "summary-contrast",
    ]
    assert context.memories[1].metadata[
        "answer_context_backfill_missing_role_hits"
    ] == ("contrast",)
    assert context.backfilled_retrieval_item_count == 2
    diagnostics = context.to_diagnostics()
    assert diagnostics["backfilled_broad_summary_count"] == 1
    assert diagnostics["backfilled_conflict_or_stale_count"] == 1


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
        "measured-weak",
    ]
    assert "answer_context_answerability_score" not in context.memories[1].metadata
    assert "answer_context_source_locality_score" not in context.memories[1].metadata
    assert context.memories[2].metadata["answer_context_answerability_score"] == 0.4
    assert context.memories[2].metadata["answer_context_source_locality_score"] == 0.3


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
        "far-event",
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
    assert "source_proximity_support" not in context.memories[2].metadata[
        "answer_context_reason_codes"
    ]
    diagnostics = context.to_diagnostics()
    assert diagnostics["backfilled_source_proximity_support_count"] == 1
    assert diagnostics["backfilled_source_proximity_closest_distance"] == 2


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
        "metadata-only-time",
    ]
    assert context.memories[1].metadata[
        "answer_context_backfill_missing_role_hits"
    ] == ("temporal_support",)
    assert (
        "answer_context_backfill_missing_role_hits"
        not in context.memories[2].metadata
    )


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
                            "avg_answerability_score": 0.4,
                            "avg_measured_answerability_score": 0.8,
                            "unmeasured_answerability_count": 1,
                            "avg_source_locality_score": 0.35,
                            "avg_measured_source_locality_score": 0.7,
                            "unmeasured_source_locality_count": 1,
                            "selected_bundle_item_count": 1,
                            "skipped_bundle_item_count": 0,
                            "backfilled_retrieval_item_count": 1,
                            "backfilled_broad_summary_count": 0,
                            "backfilled_conflict_or_stale_count": 0,
                            "backfilled_source_proximity_support_count": 1,
                            "backfilled_source_proximity_closest_distance": 2,
                            "bundle_confidence_score": 0.68,
                            "bundle_confidence_band": "medium",
                            "bundle_bridge_count": 1,
                            "bundle_source_type_diversity": 2,
                            "bundle_retrieval_source_diversity": 3,
                            "bundle_source_proximity_support_count": 1,
                            "bundle_source_proximity_closest_distance": 2,
                            "bundle_causal_support_count": 1,
                            "bundle_event_support_count": 8,
                            "bundle_inference_support_count": 2,
                            "bundle_location_support_count": 5,
                            "bundle_emotion_response_support_count": 6,
                            "bundle_symbolic_meaning_support_count": 7,
                            "bundle_preference_support_count": 3,
                            "bundle_visual_support_count": 4,
                            "bundle_contrast_count": 2,
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
    assert metrics["primary_total_backfilled_source_proximity_support_count"] == 1
    assert metrics["primary_avg_backfilled_source_proximity_support_count"] == 0.5
    assert metrics["primary_avg_backfilled_source_proximity_closest_distance"] == 2.0
    assert metrics["primary_min_backfilled_source_proximity_closest_distance"] == 2
    assert metrics["primary_avg_source_ref_coverage_rate"] == 0.5
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
    assert primary["evidence_bundle_context_count"] == 1
    assert primary["fallback_context_count"] == 1
    assert primary["avg_backfilled_retrieval_item_count"] == 0.5
    assert primary["total_backfilled_retrieval_item_count"] == 1
    assert primary["total_backfilled_broad_summary_count"] == 0
    assert primary["total_backfilled_conflict_or_stale_count"] == 0
    assert primary["total_backfilled_source_proximity_support_count"] == 1
    assert primary["avg_backfilled_source_proximity_support_count"] == 0.5
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
    assert primary["avg_bundle_source_type_diversity"] == 1.0
    assert primary["max_bundle_source_type_diversity"] == 2
    assert primary["avg_bundle_retrieval_source_diversity"] == 1.5
    assert primary["max_bundle_retrieval_source_diversity"] == 3
    assert primary["avg_bundle_source_proximity_support_count"] == 0.5
    assert primary["total_bundle_source_proximity_support_count"] == 1
    assert primary["avg_bundle_source_proximity_closest_distance"] == 2.0
    assert primary["min_bundle_source_proximity_closest_distance"] == 2
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
    assert primary["avg_bundle_visual_support_count"] == 2.0
    assert primary["total_bundle_visual_support_count"] == 4
    assert primary["avg_bundle_contrast_count"] == 1.0
    assert primary["total_bundle_contrast_count"] == 2
    assert primary["avg_source_ref_count"] == 0.5
    assert primary["avg_source_ref_item_count"] == 0.5
    assert primary["avg_source_refless_item_count"] == 1.5
    assert primary["avg_source_ref_coverage_rate"] == 0.5
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
