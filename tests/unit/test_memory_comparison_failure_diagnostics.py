from __future__ import annotations

from infinity_context_server.memory_comparison_failure_diagnostics import (
    failure_diagnostic_reason_codes,
    failure_diagnostics,
)


def test_failure_diagnostics_report_structured_failure_reasons() -> None:
    evaluation = {
        "backend": "mem0",
        "case_id": "conv-1:qa:diagnostics",
        "group": "multi-hop",
        "capability": "qa",
        "scored": True,
        "retrieval": {
            "total_results": 3,
            "context_token_count": 128,
            "results": [
                {
                    "id": "partial",
                    "rank": 1,
                    "memory": "Morgan discussed the checklist.",
                    "source_refs": ["D1:1"],
                    "metadata": {
                        "diagnostics": {
                            "retrieval_sources": ["postgres_facts", "qdrant"]
                        }
                    },
                },
                {
                    "id": "support",
                    "rank": 2,
                    "memory": "Taylor mentioned a related launch note.",
                    "source_refs": ["D1:2"],
                    "metadata": {
                        "diagnostics": {"retrieval_source": "keyword_chunks"}
                    },
                },
            ],
        },
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.5,
            "missing_terms": ["blue notebook"],
            "missing_evidence_terms": ["D1:3"],
        },
        "evidence_bundle": {
            "bundle_complete": False,
            "item_count": 2,
            "primary_evidence_count": 1,
            "supporting_evidence_count": 0,
            "missing_required_roles": ["bridge"],
            "items": [
                {"role": "primary", "source_refs": ["D1:1"]},
                {"role": "supporting", "source_refs": ["D1:2"]},
            ],
            "bundle_planner": {
                "bundle_quality": {
                    "confidence_score": 0.22,
                    "confidence_band": "low",
                    "missing_required_roles": ["bridge"],
                    "reason_codes": [
                        "risk:missing_required_bridge",
                        "risk:low_answerability",
                    ],
                }
            },
        },
        "generation": {
            "answer": "The checklist was discussed.",
            "token_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "total_tokens": 14,
            },
        },
        "judgment": {
            "score": 0.25,
            "reason": "partial support only",
            "token_usage": {
                "prompt_tokens": 7,
                "completion_tokens": 3,
                "total_tokens": 10,
            },
        },
    }

    diagnostics = failure_diagnostics(evaluation)
    reasons = failure_diagnostic_reason_codes(
        evaluation,
        score=0.25,
        retrieval_recall=0.5,
        diagnostics=diagnostics,
    )

    assert reasons == [
        "judge_score_below_threshold",
        "partial_expected_term_support",
        "missing_expected_terms",
        "missing_evidence_refs",
        "partial_evidence_ref_support",
        "bundle_incomplete",
        "missing_required_roles",
        "weak_evidence_bundle",
        "bundle_risk_reasons_present",
    ]
    assert diagnostics["retrieved_item_count"] == 2
    assert diagnostics["total_results"] == 3
    assert diagnostics["context_token_count"] == 128
    assert diagnostics["source_ref_count"] == 2
    assert diagnostics["retrieval_source_counts"] == {
        "keyword_chunks": 1,
        "postgres_facts": 1,
        "qdrant": 1,
    }
    assert diagnostics["token_usage"] == {
        "answerer": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        "judge": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    }
    assert diagnostics["cost"] == {
        "scope": "answerer_judge_token_usage",
        "unmeasured_backend_provider_costs": True,
    }
    assert diagnostics["partial_expected_support"] is True
    assert diagnostics["partial_evidence_support"] is True
    assert diagnostics["bundle"] == {
        "complete": False,
        "item_count": 2,
        "roles": ["primary", "supporting"],
        "missing_required_roles": ("bridge",),
        "primary_evidence_count": 1,
        "supporting_evidence_count": 0,
        "confidence_score": 0.22,
        "confidence_band": "low",
        "reason_codes": (
            "risk:missing_required_bridge",
            "risk:low_answerability",
        ),
    }
