from __future__ import annotations

import sys
import types

if "httpx" not in sys.modules:
    httpx_stub = types.ModuleType("httpx")
    httpx_stub.Client = object
    sys.modules["httpx"] = httpx_stub

from infinity_context_server.memory_comparison_answer_context import (
    answer_context_from_evidence_bundle,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_answer_context_reads_structured_metadata_evidence_identity_refs() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="Caroline confirmed the plan.",
                rank=1,
                metadata={
                    "source_refs": {
                        "source_external_id": "locomo:conv-private:turn-secret",
                        "session_key": "session_4",
                        "evidence_ids": ("5", "6"),
                    }
                },
            ),
        ),
        {},
        cutoff=1,
    )

    assert context.memories[0].source_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_session_turn_refs:session_4:D4:6",
        "source_turn_refs:D4:5",
        "source_turn_refs:D4:6",
    )
    assert context.to_diagnostics()["source_identity_refs"] == [
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
        "source_session_turn_refs:session_4:D4:6",
        "source_turn_refs:D4:6",
    ]


def test_answer_context_suppresses_broad_numeric_metadata_evidence_refs() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="Caroline confirmed the plan.",
                rank=1,
                metadata={
                    "source_refs": {
                        "source_external_id": "locomo:conv-private:turn-secret",
                        "session_key": "session_4",
                        "source_evidence_refs": ("1", "2", "3", "4"),
                    }
                },
            ),
        ),
        {},
        cutoff=1,
    )

    assert context.memories[0].source_refs == ("session_4",)
    diagnostics = context.to_diagnostics()
    assert diagnostics["source_identity_refs"] == []
    assert diagnostics["source_ref_count"] == 1


def test_answer_context_reads_nested_numeric_metadata_evidence_refs() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="Caroline confirmed the plan.",
                rank=1,
                metadata={
                    "source_refs": {
                        "source_external_id": "locomo:conv-private:turn-secret",
                        "session_key": "session_4",
                        "supporting_evidence": [
                            {"source_evidence_ref": "5"},
                            {"turn_ids": ("6",)},
                        ],
                    }
                },
            ),
        ),
        {},
        cutoff=1,
    )

    assert context.memories[0].source_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_session_turn_refs:session_4:D4:6",
        "source_turn_refs:D4:5",
        "source_turn_refs:D4:6",
    )


def test_answer_context_backfill_reads_structured_metadata_evidence_identity_refs() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="D4:1 Caroline primary detail.",
                rank=1,
                item_id="primary",
                source_refs=("D4:1",),
            ),
            RetrievedMemory(
                text="Caroline contrast detail.",
                rank=2,
                item_id="metadata-contrast",
                metadata={
                    "source_refs": {
                        "source_external_id": "locomo:conv-private:turn-secret",
                        "session_key": "session_4",
                        "evidence_ids": ("5", "6"),
                    },
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "query_roles": ["contrast"],
                            "contrast_surface": True,
                            "answerability_score": 0.9,
                            "source_locality_score": 0.9,
                        }
                    },
                },
            ),
        ),
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["contrast"],
            "items": [
                {
                    "id": "primary",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["D4:1"],
                }
            ],
        },
        cutoff=2,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "metadata-contrast",
    ]
    assert context.backfilled_retrieval_item_count == 1
    assert context.memories[1].source_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_session_turn_refs:session_4:D4:6",
        "source_turn_refs:D4:5",
        "source_turn_refs:D4:6",
    )
    assert context.to_diagnostics()["source_identity_refs"] == [
        "source_turn_refs:D4:1",
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
        "source_session_turn_refs:session_4:D4:6",
        "source_turn_refs:D4:6",
    ]


def test_answer_context_backfill_metadata_refs_support_precise_overlap() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="D4:5 Caroline primary detail.",
                rank=1,
                item_id="primary",
                source_refs=("D4:5",),
            ),
            RetrievedMemory(
                text="Caroline contrast detail.",
                rank=2,
                item_id="metadata-contrast",
                metadata={
                    "source_refs": {
                        "source_external_id": "locomo:conv-private:turn-secret",
                        "session_key": "session_4",
                        "evidence_ids": ("5", "6"),
                    },
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "query_roles": ["contrast"],
                            "contrast_surface": True,
                            "answerability_score": 0.9,
                            "source_locality_score": 0.9,
                        }
                    },
                },
            ),
        ),
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["contrast"],
            "items": [
                {
                    "id": "primary",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["D4:5"],
                }
            ],
        },
        cutoff=2,
    )

    assert context.backfilled_retrieval_item_count == 1
    assert context.backfilled_precise_source_overlap_count == 1
    assert context.memories[1].metadata["answer_context_backfill_precise_source_overlap"]
    assert context.memories[1].metadata[
        "answer_context_backfill_source_proximity_distance"
    ] == 0
