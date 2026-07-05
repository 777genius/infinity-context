from __future__ import annotations

import json

from infinity_context_server import memory_comparison_benchmark as benchmark
from infinity_context_server.memory_comparison_answer_context import (
    answer_context_from_evidence_bundle,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_compact_answer_context_support_gap_samples_keeps_identity_refs() -> None:
    samples = benchmark._compact_answer_context_support_gap_samples(
        [
            {
                "case_id": "case-answer-context",
                "group": "single-hop",
                "cutoff": "5",
                "source": "evidence_bundle",
                "memory_count": 2,
                "source_ref_item_count": 0,
                "source_refless_item_count": 2,
                "source_identity_ref_count": 2,
                "source_identity_item_count": 1,
                "backfilled_retrieval_item_count": 1,
                "skipped_redundant_risky_backfill_count": 1,
                "avg_measured_answerability_score": 0.43,
                "avg_measured_source_locality_score": 0.41,
                "gap_reasons": ["missing_context_source_refs"],
                "missing_required_roles": ["emotion_response_support"],
                "risk_reason_codes": ["risk:missing_required_role"],
                "item_ids": ["weak-selected", "backfilled-context"],
                "source_identity_refs": [
                    "source_turn_refs:D1:1",
                    "source_session_turn_refs:session_1:D1:2",
                ],
                "retrieval_orders": [1, "3", "bad"],
                "raw_payload": "must stay out",
            }
        ]
    )

    assert samples == [
        {
            "case_id": "case-answer-context",
            "group": "single-hop",
            "cutoff": "5",
            "source": "evidence_bundle",
            "memory_count": 2,
            "source_ref_item_count": 0,
            "source_refless_item_count": 2,
            "source_identity_ref_count": 2,
            "source_identity_item_count": 1,
            "backfilled_retrieval_item_count": 1,
            "skipped_redundant_risky_backfill_count": 1,
            "avg_measured_answerability_score": 0.43,
            "avg_measured_source_locality_score": 0.41,
            "gap_reasons": ["missing_context_source_refs"],
            "missing_required_roles": ["emotion_response_support"],
            "risk_reason_codes": ["risk:missing_required_role"],
            "item_ids": ["weak-selected", "backfilled-context"],
            "source_identity_refs": [
                "source_turn_refs:D1:1",
                "source_session_turn_refs:session_1:D1:2",
            ],
            "retrieval_orders": [1, 3],
        }
    ]
    assert "raw_payload" not in samples[0]


def test_compact_answer_context_support_gap_samples_filters_unsafe_identity_refs() -> None:
    samples = benchmark._compact_answer_context_support_gap_samples(
        [
            {
                "case_id": "case-answer-context",
                "source_identity_refs": [
                    "source_turn_refs:D1:1",
                    "source_turn_refs:d1:1",
                    "source_session_turn_refs:session_2:D3:4",
                    "locomo:conv-private:session_2:D3:4:turn-secret",
                    f"source_turn_refs:D1:{'9' * 90}",
                ],
            }
        ]
    )

    assert samples == [
        {
            "case_id": "case-answer-context",
            "source_identity_refs": [
                "source_turn_refs:D1:1",
                "source_session_turn_refs:session_2:D3:4",
            ],
        }
    ]
    serialized = json.dumps(samples)
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized
    assert "999999999999999999999999999999999999999999999999999999999999" not in (
        serialized
    )


def test_compact_fast_gate_summary_keeps_safe_identity_refs_end_to_end() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text=(
                    "session_1 turn D1:2 should be the only compact source "
                    "identity; raw provider payload provider-auth-private-marker "
                    "must stay out."
                ),
                rank=1,
                item_id="safe-memory-id",
                source_refs=(
                    "locomo:conv-private:session_1:D1:2:turn-secret",
                ),
            ),
        ),
        {},
        cutoff=5,
    )

    summary = benchmark._compact_fast_gate_summary(
        (
            {
                "case_id": "locomo-identity-endtoend",
                "group": "single-hop",
                "cutoff_results": {
                    "5": {"answer_context": context.to_diagnostics()}
                },
            },
        )
    )

    sample = summary["answer_context_support_gap_samples"][0]

    assert sample["source_identity_ref_count"] == 2
    assert sample["source_identity_item_count"] == 1
    assert sample["source_identity_refs"] == [
        "source_session_turn_refs:session_1:D1:2",
        "source_turn_refs:D1:2",
    ]
    assert sample["item_ids"] == ["safe-memory-id"]
    serialized = json.dumps(summary)
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized
    assert "provider-auth-private-marker" not in serialized


def test_answer_context_matches_source_refs_dedupe_key_with_safe_identity_refs() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="session_4 D4:5 Caroline confirmed the support group.",
                rank=1,
                item_id="safe-session-turn",
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "source_ref_dedupe_key": (
                                "source_session_turn_refs:session_4:D4:5"
                            )
                        }
                    }
                },
            ),
        ),
        {
            "items": [
                {
                    "role": "primary",
                    "source_ref_dedupe_key": (
                        "source_refs:"
                        "LoCoMo:conv-private:SESSION_4:d4:5:TURN-secret|"
                        "provider:private-token-abc123"
                    ),
                }
            ]
        },
        cutoff=1,
    )

    assert [memory.item_id for memory in context.memories] == ["safe-session-turn"]
    assert context.memories[0].source_refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    )
    diagnostics = context.to_diagnostics()
    assert diagnostics["source_identity_refs"] == [
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
    ]
    serialized = json.dumps((context.memories[0].source_refs, diagnostics))
    assert "locomo:conv-private" not in serialized.lower()
    assert "turn-secret" not in serialized.lower()
    assert "provider:private-token" not in serialized
