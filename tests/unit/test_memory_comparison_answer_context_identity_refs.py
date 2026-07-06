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


def test_answer_context_filters_auth_source_payloads_without_losing_text_identity() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text=(
                    "session_1 turn D1:2 source identity is in text while the "
                    "provider auth marker must stay out."
                ),
                rank=1,
                item_id="provider-auth-private-marker",
                source_refs=("provider-auth-private-marker",),
            ),
        ),
        {},
        cutoff=1,
    )

    diagnostics = context.to_diagnostics()

    assert context.memories[0].source_refs == (
        "source_session_turn_refs:session_1:D1:2",
        "source_turn_refs:D1:2",
    )
    assert diagnostics["item_ids"] == []
    assert diagnostics["source_ref_count"] == 2
    assert diagnostics["source_identity_refs"] == [
        "source_session_turn_refs:session_1:D1:2",
        "source_turn_refs:D1:2",
    ]
    serialized = json.dumps((context.memories[0].source_refs, diagnostics))
    assert "provider-auth-private-marker" not in serialized


def test_answer_context_backfill_filters_auth_source_payloads_without_losing_identity() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="D1:1 Caroline asked about the support group.",
                rank=1,
                item_id="primary-turn",
                source_refs=("D1:1",),
            ),
            RetrievedMemory(
                text="session_1 turn D1:2 Caroline confirmed the support group date.",
                rank=2,
                item_id="provider-auth-private-marker",
                source_refs=("provider-auth-private-marker",),
                metadata={
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.91,
                            "source_locality_score": 0.9,
                            "query_roles": ["event_support"],
                            "relation_category_hits": ["participation_event"],
                        }
                    }
                },
            ),
        ),
        {
            "required_roles": ["event_support"],
            "role_requirement_complete": False,
            "missing_required_roles": ["event_support"],
            "items": [
                {
                    "id": "primary-turn",
                    "retrieval_order": 1,
                    "role": "primary",
                    "source_refs": ["D1:1"],
                }
            ],
        },
        cutoff=2,
    )

    assert [memory.metadata["answer_context_role"] for memory in context.memories] == [
        "primary",
        "retrieval_backfill",
    ]
    assert context.memories[1].source_refs == (
        "source_session_turn_refs:session_1:D1:2",
        "source_turn_refs:D1:2",
    )
    diagnostics = context.to_diagnostics()
    serialized = json.dumps((context.memories[1].source_refs, diagnostics))
    assert "provider-auth-private-marker" not in serialized


def test_answer_context_keeps_exact_turn_identity_unqualified_when_text_has_session() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="session_9 D7:2 Morgan checked in about the workshop.",
                rank=1,
                item_id="exact-turn-with-session-text",
                source_refs=("D7:2",),
            ),
        ),
        {
            "items": [
                {
                    "id": "exact-turn-with-session-text",
                    "retrieval_order": 1,
                    "role": "relative_temporal_support",
                    "source_refs": ["D7:2"],
                }
            ]
        },
        cutoff=1,
    )

    diagnostics = context.to_diagnostics()

    assert context.memories[0].source_refs == ("D7:2",)
    assert diagnostics["source_identity_refs"] == ["source_turn_refs:D7:2"]
    assert diagnostics["source_identity_items"] == [
        {
            "source_identity_refs": ["source_turn_refs:D7:2"],
            "item_id": "exact-turn-with-session-text",
            "retrieval_order": 1,
        }
    ]
    assert not any(
        ref.startswith("source_session_turn_refs:")
        for ref in diagnostics["source_identity_refs"]
    )


def test_answer_context_preserves_text_turn_identity_with_generic_source_ref() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="session_3 turn D3:4 Alex confirmed the planning date.",
                rank=1,
                item_id="generic-source-ref-turn",
                source_refs=("document:profile-note",),
            ),
        ),
        {},
        cutoff=1,
    )

    diagnostics = context.to_diagnostics()

    assert context.memories[0].source_refs == (
        "document:profile-note",
        "source_session_turn_refs:session_3:D3:4",
        "source_turn_refs:D3:4",
    )
    assert diagnostics["source_ref_count"] == 3
    assert diagnostics["source_identity_refs"] == [
        "source_session_turn_refs:session_3:D3:4",
        "source_turn_refs:D3:4",
    ]


def test_answer_context_preserves_human_labeled_session_turn_identity() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="Session 3 turn D3:6 Alex confirmed the planning date.",
                rank=1,
                item_id="human-session-label-turn",
                source_refs=("document:profile-note",),
            ),
        ),
        {},
        cutoff=1,
    )

    diagnostics = context.to_diagnostics()

    assert context.memories[0].source_refs == (
        "document:profile-note",
        "source_session_turn_refs:session_3:D3:6",
        "source_turn_refs:D3:6",
    )
    assert diagnostics["source_identity_refs"] == [
        "source_session_turn_refs:session_3:D3:6",
        "source_turn_refs:D3:6",
    ]


def test_answer_context_preserves_punctuated_session_turn_identity() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="Session 3, turn D3:6 Alex confirmed the planning date.",
                rank=1,
                item_id="punctuated-session-label-turn",
                source_refs=("document:profile-note",),
            ),
        ),
        {},
        cutoff=1,
    )

    diagnostics = context.to_diagnostics()

    assert context.memories[0].source_refs == (
        "document:profile-note",
        "source_session_turn_refs:session_3:D3:6",
        "source_turn_refs:D3:6",
    )
    assert diagnostics["source_identity_refs"] == [
        "source_session_turn_refs:session_3:D3:6",
        "source_turn_refs:D3:6",
    ]


def test_answer_context_diagnostics_filters_raw_provider_item_ids() -> None:
    context = answer_context_from_evidence_bundle(
        (
            RetrievedMemory(
                text="session_1 turn D1:2 raw note should not expose provider ids.",
                rank=1,
                item_id="locomo:conv-private:session_1:D1:2:turn-secret",
                source_refs=(
                    "locomo:conv-private:session_1:D1:2:turn-secret",
                ),
            ),
        ),
        {},
        cutoff=1,
    )

    diagnostics = context.to_diagnostics()

    assert context.memories[0].source_refs == (
        "source_session_turn_refs:session_1:D1:2",
        "source_turn_refs:D1:2",
    )
    assert diagnostics["item_ids"] == []
    assert diagnostics["source_identity_refs"] == [
        "source_session_turn_refs:session_1:D1:2",
        "source_turn_refs:D1:2",
    ]
    assert "item_id" not in diagnostics["source_identity_items"][0]
    serialized = json.dumps(diagnostics)
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized
