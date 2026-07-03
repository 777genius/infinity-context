from __future__ import annotations

from infinity_context_server.memory_comparison_answer_context import (
    answer_context_from_evidence_bundle,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_answer_context_skips_low_quality_overlapping_bundle_item() -> None:
    memories = (
        RetrievedMemory(
            text="D4:2 Caroline found the support group helpful.",
            rank=1,
            item_id="primary-turn",
            source_refs=("D4:2",),
        ),
        RetrievedMemory(
            text="D4:2 Caroline found the support group helpful in a noisy chunk.",
            rank=2,
            item_id="weak-overlap",
            source_refs=("D4:2", "D4:3"),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "answerability_score": 0.4,
                        "source_locality_score": 0.9,
                    }
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
                    "id": "weak-overlap",
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
    assert context.skipped_duplicate_source_bundle_item_count == 0
    assert context.skipped_noisy_overlap_bundle_item_count == 1


def test_answer_context_keeps_unmeasured_overlapping_bundle_item() -> None:
    memories = (
        RetrievedMemory(
            text="D4:2 Caroline found the support group helpful.",
            rank=1,
            item_id="primary-turn",
            source_refs=("D4:2",),
        ),
        RetrievedMemory(
            text="D4:2 Caroline added source detail without measured scores.",
            rank=2,
            item_id="unmeasured-overlap",
            source_refs=("D4:2", "D4:3"),
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
                    "id": "unmeasured-overlap",
                    "retrieval_order": 2,
                    "role": "support",
                    "source_refs": ["D4:2", "D4:3"],
                },
            ]
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary-turn",
        "unmeasured-overlap",
    ]
    assert context.skipped_noisy_overlap_bundle_item_count == 0


def test_answer_context_backfill_rejects_stale_only_contrast_candidate() -> None:
    memories = (
        RetrievedMemory(
            text="D5:1 Morgan now prefers team projects.",
            rank=1,
            item_id="primary-turn",
            source_refs=("D5:1",),
        ),
        RetrievedMemory(
            text="D5:2 Morgan used to prefer solo projects.",
            rank=2,
            item_id="stale-only",
            source_refs=("D5:2",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "query_roles": ["contrast"],
                        "stale_surface": True,
                        "answerability_score": 0.9,
                        "source_locality_score": 0.9,
                    }
                }
            },
        ),
        RetrievedMemory(
            text="D5:3 Morgan used to prefer solo work, but now prefers teams.",
            rank=3,
            item_id="current-contrast",
            source_refs=("D5:3",),
            metadata={
                "diagnostics": {
                    "benchmark_candidate_features": {
                        "query_roles": ["contrast"],
                        "currentness_surface": True,
                        "stale_surface": True,
                        "answerability_score": 0.88,
                        "source_locality_score": 0.9,
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
                    "id": "primary-turn",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["D5:1"],
                }
            ],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary-turn",
        "current-contrast",
    ]
    assert context.backfilled_retrieval_item_count == 1
    assert context.memories[1].metadata["answer_context_backfill_missing_role_hits"] == (
        "contrast",
    )


def test_answer_context_keeps_compacted_fusion_source_refs_local() -> None:
    memories = (
        RetrievedMemory(
            text="D2:9 Caroline: I found an adoption agency that can help.",
            rank=1,
            item_id="local-agency-turn",
            source_refs=("D2:9",),
            metadata={
                "diagnostics": {
                    "benchmark_compacted_selected_source_refs": True,
                    "benchmark_candidate_fusion": {
                        "source_refs": ["D2:9", "D2:8", "D2:10", "D2:11"],
                    },
                },
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "items": [
                {
                    "id": "local-agency-turn",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["D2:9"],
                },
            ]
        },
        cutoff=1,
    )

    assert context.memories[0].source_refs == ("D2:9",)
    diagnostics = context.to_diagnostics()
    assert diagnostics["source_ref_count"] == 1


def test_answer_context_backfill_keeps_compacted_fusion_source_refs_local() -> None:
    memories = (
        RetrievedMemory(
            text="D2:9 Caroline: I found an adoption agency that can help.",
            rank=1,
            item_id="primary-turn",
            source_refs=("D2:9",),
        ),
        RetrievedMemory(
            text="D2:10 Caroline: The agency confirmed my application status.",
            rank=2,
            item_id="status-turn",
            source_refs=("D2:10",),
            metadata={
                "diagnostics": {
                    "benchmark_compacted_selected_source_refs": True,
                    "benchmark_candidate_fusion": {
                        "source_refs": ["D2:10", "D2:11", "D2:12", "D2:13"],
                    },
                    "benchmark_candidate_features": {
                        "query_roles": ["status_support"],
                        "relation_category_hits": ["status_profile"],
                        "entity_hits": ["caroline"],
                        "answerability_score": 0.9,
                        "source_locality_score": 0.9,
                    },
                },
            },
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["status_support"],
            "items": [
                {
                    "id": "primary-turn",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["D2:9"],
                }
            ],
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary-turn",
        "status-turn",
    ]
    assert "D2:10" in context.memories[1].source_refs
    assert "D2:11" not in context.memories[1].source_refs
    assert "D2:12" not in context.memories[1].source_refs
    assert "D2:13" not in context.memories[1].source_refs


def test_answer_context_diagnostics_count_low_quality_backfill() -> None:
    memories = (
        RetrievedMemory(text="D6:1 Alex mentioned Maria.", rank=1, item_id="primary"),
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
                        "source_type": "raw_turn",
                        "source_types": ["raw_turn"],
                        "retrieval_sources": ["keyword_source_sibling_chunks"],
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
    assert context.memories[1].metadata["answer_context_source_type"] == "raw_turn"
    assert context.memories[1].metadata["answer_context_source_types"] == (
        "raw_turn",
    )
    assert context.memories[1].metadata["answer_context_retrieval_sources"] == (
        "keyword_source_sibling_chunks",
    )
