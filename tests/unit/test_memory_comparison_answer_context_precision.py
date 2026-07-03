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
