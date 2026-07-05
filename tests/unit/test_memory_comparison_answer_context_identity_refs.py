from __future__ import annotations

from infinity_context_server import memory_comparison_benchmark as benchmark


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
