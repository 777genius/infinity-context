from infinity_context_server.memory_comparison_candidate_fusion import fuse_query_results
from infinity_context_server.memory_comparison_evidence import evidence_bundle
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase


def test_evidence_bundle_includes_feature_backed_entity_disambiguation() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:1",
        question="Which note connects Morgan's checklist and the studio desk?",
        expected_terms=("blue notebook",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 1,
            "answer_preview": "blue notebook",
            "evidence_terms": ("D1:1",),
        },
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D1:1 Morgan put the checklist in the blue notebook.",
                rank=1,
                item_id="primary",
            ),
            RetrievedMemory(
                text="D1:2 Morgan: I moved it after talking to Eli.",
                rank=2,
                item_id="entity-context",
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.66,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "entity_hits": ["morgan"],
                            "speaker_hits": ["morgan"],
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
        ),
    )

    roles_by_id = {item["id"]: item["role"] for item in bundle["items"]}
    entity_context = next(
        item for item in bundle["items"] if item["id"] == "entity-context"
    )

    assert roles_by_id["primary"] == "primary"
    assert roles_by_id["entity-context"] == "entity_disambiguation"
    assert entity_context["eligibility_reason_codes"] == [
        "feature_backed",
        "answerability_feature",
        "source_locality_feature",
        "direct_speaker_grounding",
    ]
    assert bundle["bundle_planner"]["role_counts"]["entity_disambiguation"] == 1


def test_evidence_bundle_allows_unmeasured_feature_backed_static_evidence() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:static-relation",
        question="What helped the plan?",
        expected_terms=("blue envelope",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 1,
            "evidence_terms": ("D3:9",),
        },
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D3:9 The blue envelope connected Morgan's plan to the studio.",
                rank=1,
                item_id="static-relation",
                source_refs=("D3:9",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.0,
                            "source_locality_score": 0.0,
                            "entity_hits": ["morgan"],
                            "relation_hits": ["plan", "studio"],
                            "source_type": "chunk",
                        }
                    }
                },
            ),
        ),
    )

    item = bundle["items"][0]
    assert item["id"] == "static-relation"
    assert item["role"] == "primary"
    assert item["eligibility_reason_codes"] == [
        "feature_backed",
        "answerability_unmeasured",
        "source_locality_unmeasured",
        "entity_relation_grounding",
    ]
    assert bundle["satisfied_required_roles"] == ["primary"]
    assert bundle["covered_evidence_terms"] == ["D3:9"]


def test_evidence_bundle_rejects_measured_weak_static_primary_signal() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:weak-static-relation",
        question="What helped the plan?",
        expected_terms=("blue envelope",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 1,
            "evidence_terms": ("D3:9",),
        },
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D3:9 The blue envelope connected Morgan's plan to the studio.",
                rank=1,
                item_id="weak-static-relation",
                source_refs=("D3:9",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.42,
                            "source_locality_score": 0.9,
                            "entity_hits": ["morgan"],
                            "relation_hits": ["plan", "studio"],
                            "source_type": "chunk",
                        }
                    }
                },
            ),
        ),
    )

    assert bundle["items"] == []
    assert bundle["satisfied_required_roles"] == []


def test_evidence_bundle_requires_location_support_for_location_queries() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-location:qa:1",
        question="Where did Caroline move from?",
        expected_terms=("Canada",),
        memory_scope_external_ref="locomo-conv-location",
        thread_external_ref="locomo-conv-location",
        metadata={"category": 4},
    )

    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D1:4 Caroline: I moved from my home country, Canada.",
                rank=1,
                item_id="origin",
                source_refs=("D1:4",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.94,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "relation_categories": ["location_transition"],
                            "relation_category_hits": ["location_transition"],
                            "relation_hits": ["move", "home", "country"],
                            "entity_hits": ["caroline"],
                            "speaker_hits": ["caroline"],
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
            RetrievedMemory(
                text="D1:3 Caroline: I moved the meeting after work.",
                rank=2,
                item_id="move-distractor",
                source_refs=("D1:3",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.62,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "relation_categories": ["location_transition"],
                            "relation_hits": ["move"],
                            "entity_hits": ["caroline"],
                            "speaker_hits": ["caroline"],
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
        ),
    )

    planner = bundle["bundle_planner"]
    roles_by_id = {item["id"]: item["role"] for item in bundle["items"]}

    assert bundle["required_roles"] == ["primary", "location_support"]
    assert bundle["satisfied_required_roles"] == ["primary", "location_support"]
    assert bundle["role_requirement_complete"] is True
    assert roles_by_id["origin"] == "primary"
    assert planner["bundle_quality"]["location_relation_category_hit_count"] == 1
    assert "has_location_relation_category_evidence" in planner["bundle_quality"][
        "reason_codes"
    ]
    origin_item = next(item for item in bundle["items"] if item["id"] == "origin")
    assert origin_item["relation_category_hits"] == ["location_transition"]


def test_evidence_bundle_requires_preference_support_for_preference_queries() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-preference:qa:1",
        question="What does Melanie like?",
        expected_terms=("animals",),
        memory_scope_external_ref="locomo-conv-preference",
        thread_external_ref="locomo-conv-preference",
        metadata={"category": 4},
    )

    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D1:1 Melanie mentioned animals.",
                rank=1,
                item_id="primary",
                source_refs=("D1:1",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.95,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "relation_hits": ["animal"],
                            "speaker_hits": ["melanie"],
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
            RetrievedMemory(
                text="D2:3 Melanie: The kids love learning about animals.",
                rank=2,
                item_id="preference-support",
                source_refs=("D2:3",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.74,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "has_preference_evidence": True,
                            "relation_categories": ["preference"],
                            "relation_category_hits": ["preference"],
                            "relation_hits": ["like", "love", "animal"],
                            "speaker_hits": ["melanie"],
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
        ),
    )

    roles_by_id = {item["id"]: item["role"] for item in bundle["items"]}
    support_item = next(
        item for item in bundle["items"] if item["id"] == "preference-support"
    )

    assert bundle["required_roles"] == ["primary", "preference_support"]
    assert bundle["satisfied_required_roles"] == ["primary", "preference_support"]
    assert bundle["role_requirement_complete"] is True
    assert roles_by_id["primary"] == "primary"
    assert roles_by_id["preference-support"] == "preference_support"
    assert support_item["has_preference_evidence"] is True
    assert bundle["bundle_planner"]["bundle_quality"]["preference_support_count"] == 1
    assert "preference_support" in support_item["planner_reason_codes"]


def test_evidence_bundle_requires_visual_support_for_visual_queries() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-visual:qa:1",
        question="What painting did Melanie show?",
        expected_terms=("lake sunrise",),
        memory_scope_external_ref="locomo-conv-visual",
        thread_external_ref="locomo-conv-visual",
        metadata={"category": 4},
    )

    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D1:1 Melanie mentioned the lake sunrise.",
                rank=1,
                item_id="primary",
                source_refs=("D1:1",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.95,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "relation_hits": ["paint"],
                            "speaker_hits": ["melanie"],
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
            RetrievedMemory(
                text=(
                    "D2:3 Melanie: Look at my painting. "
                    "The image shows a watercolor lake sunrise."
                ),
                rank=2,
                item_id="visual-support",
                source_refs=("D2:3",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.74,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "has_visual_evidence": True,
                            "relation_categories": ["visual"],
                            "relation_category_hits": ["visual"],
                            "relation_hits": ["paint", "image"],
                            "speaker_hits": ["melanie"],
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
        ),
    )

    roles_by_id = {item["id"]: item["role"] for item in bundle["items"]}
    support_item = next(item for item in bundle["items"] if item["id"] == "visual-support")

    assert bundle["required_roles"] == ["primary", "visual_support"]
    assert bundle["satisfied_required_roles"] == ["primary", "visual_support"]
    assert bundle["role_requirement_complete"] is True
    assert roles_by_id["primary"] == "primary"
    assert roles_by_id["visual-support"] == "visual_support"
    assert support_item["has_visual_evidence"] is True
    assert bundle["bundle_planner"]["bundle_quality"]["visual_support_count"] == 1
    assert "visual_support" in support_item["planner_reason_codes"]


def test_evidence_bundle_preserves_typed_temporal_feature_provenance() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:duration",
        question="How long has Caroline known her current friends?",
        expected_terms=("four years",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={"category": 2},
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D2:4 Caroline: I have known those friends for 4 years.",
                rank=1,
                item_id="duration-evidence",
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.88,
                            "answerability_reason_codes": [
                                "duration_temporal_evidence",
                                "high_answerability",
                            ],
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "entity_hits": ["caroline"],
                            "speaker_hits": ["caroline"],
                            "relation_hits": ["known", "friend"],
                            "time_intent_kind": "duration",
                            "has_duration_surface": True,
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
        ),
    )

    item = bundle["items"][0]
    assert item["id"] == "duration-evidence"
    assert item["time_intent_kind"] == "duration"
    assert item["has_duration_surface"] is True
    assert "duration_temporal_evidence" in item["answerability_reason_codes"]
    assert "temporal_grounding" in item["eligibility_reason_codes"]
    assert bundle["required_roles"] == [
        "primary",
        "temporal_support",
    ]
    assert bundle["satisfied_required_roles"] == [
        "primary",
        "temporal_support",
    ]
    assert bundle["missing_required_roles"] == []
    assert bundle["role_requirement_complete"] is True


def test_evidence_bundle_uses_source_refs_preserved_by_candidate_fusion() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:fused-ref",
        question="What did Caroline research?",
        expected_terms=("adoption agencies",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 4,
            "answer_preview": "adoption agencies",
            "evidence_terms": ("D2:8",),
        },
    )
    fused, _diagnostics = fuse_query_results(
        (
            (
                "semantic",
                (
                    RetrievedMemory(
                        item_id="adoption-support",
                        rank=1,
                        score=0.91,
                        text="Caroline looked into adoption agencies for summer.",
                        source_refs=("chunk-ref",),
                    ),
                ),
            ),
            (
                "raw-turn",
                (
                    RetrievedMemory(
                        item_id="adoption-support",
                        rank=2,
                        score=0.82,
                        text="Caroline discussed the same research plan.",
                        source_refs=("D2:8",),
                    ),
                ),
            ),
        )
    )

    bundle = evidence_bundle(case, fused)

    assert fused[0].source_refs == ("chunk-ref", "D2:8")
    assert bundle["covered_evidence_terms"] == ["D2:8"]
    assert bundle["items"][0]["source_refs"] == ["chunk-ref", "D2:8"]


def test_evidence_bundle_uses_text_turn_refs_for_source_proximity() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:text-turn-proximity",
        question="What did Morgan move after talking to Eli?",
        expected_terms=("blue notebook",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={"category": 4},
    )

    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D2:3 Morgan: I moved the blue notebook after the call.",
                rank=1,
                item_id="primary-text-turn",
            ),
            RetrievedMemory(
                text="D2:5 Morgan: I talked to Eli about the notebook.",
                rank=2,
                item_id="support-text-turn",
            ),
        ),
    )

    quality = bundle["bundle_planner"]["bundle_quality"]

    assert [item["id"] for item in bundle["items"]] == [
        "primary-text-turn",
        "support-text-turn",
    ]
    assert quality["source_ref_item_count"] == 0
    assert quality["source_identity_item_count"] == 2
    assert quality["source_identity_ref_count"] == 2
    assert quality["component_scores"]["source_refs"] == 0.16
    assert "has_source_identity" in quality["reason_codes"]
    assert quality["source_proximity_support_count"] == 1
    assert quality["source_proximity_closest_distance"] == 2
    assert quality["source_proximity_distance_counts"] == {"2": 1}


def test_evidence_bundle_dedupes_mirrored_items_by_canonical_source_ref() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:mirror",
        question="What did Caroline say about the support group?",
        expected_terms=("support group",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 4,
            "answer_preview": "support group",
            "evidence_terms": ("D4:2",),
        },
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="Caroline mentioned the LGBTQ support group.",
                rank=1,
                item_id="mirrored-fact",
                source_refs=("D4:2", "conv-1"),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.76,
                            "source_locality_score": 0.65,
                            "entity_hits": ["caroline"],
                            "relation_hits": ["support", "group"],
                            "source_type": "fact",
                            "source_ref_dedupe_key": "source_turn_refs:D4:2",
                        }
                    }
                },
            ),
            RetrievedMemory(
                text="D4:2 Caroline: I found the LGBTQ support group helpful.",
                rank=2,
                item_id="raw-turn",
                source_refs=("D4:2",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.93,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "entity_hits": ["caroline"],
                            "speaker_hits": ["caroline"],
                            "relation_hits": ["support", "group"],
                            "source_type": "raw_turn",
                            "source_ref_dedupe_key": "source_turn_refs:D4:2",
                        }
                    }
                },
            ),
        ),
    )

    assert bundle["candidate_item_count"] == 2
    assert bundle["item_count"] == 1
    assert bundle["deduplicated_item_count"] == 1
    assert bundle["items"][0]["id"] == "raw-turn"
    assert bundle["bundle_planner"]["dropped_duplicate_keys"] == [
        "source_turn_refs:D4:2"
    ]
    assert bundle["bundle_planner"]["selected_dedupe_keys"] == [
        "source_turn_refs:D4:2"
    ]


def test_evidence_bundle_does_not_use_expected_or_evidence_labels_for_selection() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:label-only",
        question="Which note did Morgan move?",
        expected_terms=("blue notebook",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 1,
            "answer_preview": "blue notebook",
            "evidence_terms": ("D1:1",),
        },
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D1:1 blue notebook",
                rank=1,
                item_id="label-only",
            ),
        ),
    )

    assert bundle["item_count"] == 0
    assert bundle["candidate_item_count"] == 0
    assert bundle["covered_expected_terms"] == []
    assert bundle["covered_evidence_terms"] == []


def test_evidence_bundle_keeps_eval_coverage_for_question_selected_items() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:safe-selected",
        question="Which note did Morgan move?",
        expected_terms=("blue notebook",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 1,
            "answer_preview": "blue notebook",
            "evidence_terms": ("D1:1",),
        },
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D1:1 Morgan move note blue notebook",
                rank=1,
                item_id="question-selected",
            ),
        ),
    )

    assert bundle["item_count"] == 1
    assert bundle["covered_expected_terms"] == ["blue notebook"]
    assert bundle["covered_evidence_terms"] == ["D1:1"]
    assert bundle["items"][0]["eligibility_reason_codes"] == [
        "query_support_terms"
    ]


def test_evidence_bundle_reports_missing_required_bridge_role() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:missing-bridge",
        question="Why did Morgan move the note after talking to Eli?",
        expected_terms=("because Eli asked",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={"category": 1},
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D1:1 Morgan: I moved the note because Eli asked.",
                rank=1,
                item_id="primary-only",
                source_refs=("D1:1",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.91,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "entity_hits": ["morgan"],
                            "speaker_hits": ["morgan"],
                            "relation_hits": ["move", "note"],
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
        ),
    )

    assert bundle["required_roles"] == [
        "primary",
        "bridge",
        "temporal_support",
        "causal_support",
    ]
    assert bundle["satisfied_required_roles"] == ["primary"]
    assert bundle["missing_required_roles"] == [
        "bridge",
        "temporal_support",
        "causal_support",
    ]
    assert bundle["role_requirement_complete"] is False
    assert bundle["bundle_complete"] is False
    assert bundle["bundle_planner"]["missing_required_roles"] == [
        "bridge",
        "temporal_support",
        "causal_support",
    ]


def test_evidence_bundle_required_roles_respect_metadata_evidence_need() -> None:
    case = PublicBenchmarkCase(
        benchmark="custom",
        case_id="custom:contrast",
        question="What status did Morgan mention?",
        expected_terms=("current status",),
        metadata={"evidence_need": ("contrast", "temporal_support")},
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D1:1 Morgan mentioned the current status.",
                rank=1,
                item_id="status-primary",
                source_refs=("D1:1",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.88,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "entity_hits": ["morgan"],
                            "speaker_hits": ["morgan"],
                            "relation_hits": ["status", "current"],
                            "currentness_surface": True,
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
        ),
    )

    assert bundle["required_roles"] == ["primary", "temporal_support", "contrast"]
    assert bundle["satisfied_required_roles"] == ["primary", "temporal_support"]
    assert bundle["missing_required_roles"] == ["contrast"]
    assert bundle["bundle_complete"] is False


def test_evidence_bundle_flags_summary_and_stale_risks_without_feature_flags() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:summary-risk",
        question="What notebook did Morgan change to?",
        expected_terms=("green notebook",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={"category": 4},
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D1:5 Morgan: I changed to the green notebook.",
                rank=1,
                item_id="direct-current",
                source_refs=("D1:5",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.95,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "entity_hits": ["morgan"],
                            "speaker_hits": ["morgan"],
                            "relation_hits": ["change", "notebook"],
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
            RetrievedMemory(
                text=(
                    "Conversation summary: D1:1 Morgan used the blue notebook. "
                    "D1:5 Morgan changed to the green notebook."
                ),
                rank=2,
                item_id="generated-summary",
                source_refs=("D1:1", "D1:5"),
                metadata={
                    "diagnostics": {
                        "stale_reason": "older_preference_summary",
                        "benchmark_candidate_features": {
                            "answerability_score": 0.93,
                            "source_locality_score": 0.9,
                            "entity_hits": ["morgan"],
                            "speaker_hits": ["morgan"],
                            "relation_hits": ["change", "notebook"],
                            "relation_category_hits": ["contrast"],
                            "contrast_surface": True,
                            "source_type": "generated_summary",
                        },
                    }
                },
            ),
        ),
    )

    quality = bundle["bundle_planner"]["bundle_quality"]
    summary_item = next(
        item for item in bundle["items"] if item["id"] == "generated-summary"
    )

    assert {item["id"]: item["role"] for item in bundle["items"]}[
        "direct-current"
    ] == "primary"
    assert summary_item["role"] == "contrast"
    assert "broad_summary" in summary_item["planner_reason_codes"]
    assert "conflict_or_stale" in summary_item["planner_reason_codes"]
    assert quality["broad_summary_count"] == 1
    assert quality["conflict_or_stale_count"] == 1
    assert "risk:broad_summary" in quality["reason_codes"]
    assert "risk:conflict_or_stale" in quality["reason_codes"]


def test_evidence_bundle_keeps_duration_temporal_role_missing_without_duration_evidence() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:duration-missing",
        question="How long has Caroline had her current group of friends for?",
        expected_terms=("4 years",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={"category": 2},
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D1:1 Caroline mentioned her current group of friends.",
                rank=1,
                item_id="current-only",
                source_refs=("D1:1",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.74,
                            "source_locality_score": 0.9,
                            "direct_speaker_turn": True,
                            "entity_hits": ["caroline"],
                            "speaker_hits": ["caroline"],
                            "relation_hits": ["friend"],
                            "currentness_surface": True,
                            "time_intent_kind": "duration",
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
        ),
    )

    assert bundle["required_roles"] == [
        "primary",
        "temporal_support",
    ]
    assert bundle["satisfied_required_roles"] == ["primary"]
    assert bundle["missing_required_roles"] == ["temporal_support"]
    assert bundle["role_requirement_complete"] is False
    assert bundle["bundle_complete"] is False
    assert bundle["bundle_planner"]["bundle_quality"]["missing_required_roles"] == [
        "temporal_support"
    ]


def test_evidence_bundle_keeps_duration_temporal_role_missing_for_broad_summary() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:duration-broad-summary",
        question="How long has Caroline had her current group of friends for?",
        expected_terms=("4 years",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={"category": 2},
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text=(
                    "Conversation summary: D1:1 D1:2 D1:3 Caroline has had "
                    "her current group of friends for 4 years."
                ),
                rank=1,
                item_id="broad-duration-summary",
                source_refs=("D1:1", "D1:2", "D1:3"),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.9,
                            "source_locality_score": 0.9,
                            "entity_hits": ["caroline"],
                            "speaker_hits": ["caroline"],
                            "relation_hits": ["current", "friend"],
                            "has_duration_surface": True,
                            "time_intent_kind": "duration",
                            "source_type": "generated_summary",
                        }
                    }
                },
            ),
        ),
    )

    assert bundle["satisfied_required_roles"] == ["primary"]
    assert bundle["missing_required_roles"] == [
        "temporal_support",
    ]
    assert bundle["role_requirement_complete"] is False
    assert bundle["bundle_complete"] is False
    quality = bundle["bundle_planner"]["bundle_quality"]
    assert quality["broad_summary_count"] == 1
    assert "risk:broad_summary" in quality["reason_codes"]


def test_evidence_bundle_rejects_ungrounded_query_role_candidate() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-1:qa:2",
        question="When did Morgan sign up for pottery?",
        expected_terms=("Monday",),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={
            "category": 2,
            "answer_preview": "Monday",
            "evidence_terms": ("D2:4",),
        },
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D9:9 Clear weather near the park.",
                rank=1,
                item_id="ungrounded-temporal-role",
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.9,
                            "source_locality_score": 1.0,
                            "query_roles": ["temporal_support"],
                            "has_temporal_surface": True,
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
        ),
    )

    assert bundle["item_count"] == 0
    assert bundle["candidate_item_count"] == 0


def test_evidence_bundle_includes_feature_backed_contrast_support() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-26:qa:contrast",
        question="How is Caroline's current career path different from before?",
        expected_terms=("writing",),
        memory_scope_external_ref="locomo-conv-26",
        thread_external_ref="locomo-conv-26",
        metadata={
            "category": 4,
            "answer_preview": "writing",
            "evidence_terms": ("D8:4",),
        },
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                text="D8:3 Caroline discussed her current career path.",
                rank=1,
                item_id="career-primary",
                source_refs=("D8:3",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.91,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "entity_hits": ["caroline"],
                            "speaker_hits": ["caroline"],
                            "relation_hits": ["current", "career", "path"],
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
            RetrievedMemory(
                text=(
                    "D8:4 Caroline: It changed, but now the current path "
                    "feels different from before."
                ),
                rank=2,
                item_id="career-contrast",
                source_refs=("D8:4",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.72,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "entity_hits": ["caroline"],
                            "speaker_hits": ["caroline"],
                            "relation_hits": ["current", "path", "different"],
                            "contrast_surface": True,
                            "currentness_surface": True,
                            "stale_surface": True,
                            "query_roles": ["contrast_support"],
                            "source_type": "raw_turn",
                        }
                    }
                },
            ),
        ),
    )

    assert bundle["item_count"] == 2
    item = next(item for item in bundle["items"] if item["id"] == "career-contrast")
    assert item["role"] == "contrast"
    assert item["query_roles"] == ["contrast_support"]
    assert item["contrast_surface"] is True
    assert "feature_backed" in item["eligibility_reason_codes"]
    assert "contrast_grounding" in item["eligibility_reason_codes"]
    assert bundle["bundle_planner"]["role_counts"] == {"contrast": 1, "primary": 1}
    assert bundle["required_roles"] == ["primary", "temporal_support", "contrast"]
    assert bundle["satisfied_required_roles"] == [
        "primary",
        "temporal_support",
        "contrast",
    ]
    assert bundle["missing_required_roles"] == []
