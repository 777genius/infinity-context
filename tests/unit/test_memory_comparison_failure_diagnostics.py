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
        "missing_evidence_source_window_miss",
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
    assert diagnostics["missing_evidence_source_locality"] == {
        "schema_version": "missing_evidence_source_locality.v1",
        "missing_turn_ref_count": 1,
        "retrieved_source_id_count": 1,
        "retrieved_source_ids": ["D1"],
        "bundle_source_id_count": 1,
        "bundle_source_ids": ["D1"],
        "same_source_missing_count": 1,
        "near_retrieved_window_count": 1,
        "source_absent_count": 0,
        "cause_counts": {"near_retrieved_window": 1},
        "missing_ref_window_count": 1,
        "missing_ref_window_omitted_count": 0,
        "missing_ref_windows": [
            {
                "ref": "D1:3",
                "source_id": "D1",
                "retrieved_same_source": True,
                "bundle_same_source": True,
                "nearest_retrieved_turn_ref": "D1:2",
                "nearest_retrieved_turn_distance": 1,
                "nearest_bundle_turn_ref": "D1:2",
                "nearest_bundle_turn_distance": 1,
                "cause": "near_retrieved_window",
            }
        ],
    }
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
        "selected_bundle_source_ref_count": 2,
        "selected_bundle_source_ref_item_count": 2,
        "selected_bundle_source_refless_item_count": 0,
        "selected_bundle_source_ref_coverage_rate": 1.0,
        "confidence_score": 0.22,
        "confidence_band": "low",
        "selected_low_answerability_count": 0,
        "selected_weak_source_locality_count": 0,
        "reason_codes": (
            "risk:missing_required_bridge",
            "risk:low_answerability",
        ),
    }


def test_failure_diagnostics_report_selected_answerability_and_locality_weakness() -> None:
    evaluation = {
        "retrieval": {"total_results": 2, "results": []},
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.0,
        },
        "evidence_bundle": {
            "bundle_complete": False,
            "item_count": 2,
            "items": [
                {
                    "role": "supporting",
                    "answerability_score": 0.42,
                    "source_locality_score": 0.8,
                },
                {
                    "role": "supporting",
                    "answerability_score": 0.7,
                    "source_locality_score": 0.35,
                },
            ],
            "bundle_planner": {
                "bundle_quality": {
                    "confidence_score": 0.18,
                    "confidence_band": "low",
                    "low_answerability_count": 1,
                    "reason_codes": [
                        "risk:low_answerability",
                        "risk:missing_required_primary",
                    ],
                }
            },
        },
        "generation": {},
        "judgment": {},
    }

    diagnostics = failure_diagnostics(evaluation)
    reasons = failure_diagnostic_reason_codes(
        evaluation,
        score=0.0,
        retrieval_recall=0.5,
        diagnostics=diagnostics,
    )

    assert diagnostics["bundle"]["selected_low_answerability_count"] == 1
    assert diagnostics["bundle"]["selected_weak_source_locality_count"] == 1
    assert "selected_low_answerability_evidence" in reasons
    assert "selected_weak_source_locality_evidence" in reasons


def test_failure_diagnostics_reports_selected_bundle_source_ref_gaps() -> None:
    evaluation = {
        "retrieval": {"total_results": 1, "results": []},
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.5,
        },
        "evidence_bundle": {
            "bundle_complete": False,
            "item_count": 2,
            "items": [
                {
                    "id": "grounded",
                    "role": "primary",
                    "source_refs": ["D1:7"],
                },
                {
                    "id": "ungrounded-support",
                    "role": "supporting",
                },
            ],
            "bundle_planner": {
                "bundle_quality": {
                    "confidence_score": 0.3,
                    "confidence_band": "low",
                }
            },
        },
        "generation": {},
        "judgment": {},
    }

    diagnostics = failure_diagnostics(evaluation)
    reasons = failure_diagnostic_reason_codes(
        evaluation,
        score=0.0,
        retrieval_recall=0.5,
        diagnostics=diagnostics,
    )

    assert diagnostics["bundle"]["selected_bundle_source_ref_count"] == 1
    assert diagnostics["bundle"]["selected_bundle_source_ref_item_count"] == 1
    assert diagnostics["bundle"]["selected_bundle_source_refless_item_count"] == 1
    assert diagnostics["bundle"]["selected_bundle_source_ref_coverage_rate"] == 0.5
    assert "selected_bundle_source_refless_evidence" in reasons


def test_failure_diagnostics_reports_bounded_temporal_grounding_issue_summary() -> None:
    evaluation = {
        "case_id": "locomo:conv-1:qa:temporal",
        "group": "temporal",
        "retrieval": {
            "metadata": {
                "query_decomposition": {
                    "query_profile": {"evidence_need": ["temporal_support"]}
                }
            },
            "results": [],
        },
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.5,
        },
        "evidence_bundle": {
            "bundle_complete": False,
            "items": [
                {
                    "id": f"temporal-gap-{index}",
                    "role": "temporal_support",
                    "query_roles": ["temporal_support"],
                }
                for index in range(7)
            ],
        },
        "generation": {},
        "judgment": {},
    }

    diagnostics = failure_diagnostics(evaluation)
    reasons = failure_diagnostic_reason_codes(
        evaluation,
        score=0.0,
        retrieval_recall=0.5,
        diagnostics=diagnostics,
    )

    temporal = diagnostics["temporal_grounding"]
    assert temporal["schema_version"] == "failure_temporal_grounding.v1"
    assert temporal["temporal_case"] is True
    assert temporal["selected_item_count"] == 7
    assert temporal["strong_item_count"] == 0
    assert temporal["issue_item_count"] == 7
    assert temporal["issue_reason_counts"] == {
        "missing_date_or_range": 7,
        "missing_session_boundary": 7,
        "missing_source_window": 7,
        "missing_temporal_grounding": 7,
    }
    assert temporal["issue_sample_limit"] == 5
    assert temporal["issue_sample_count"] == 5
    assert temporal["issue_sample_omitted_count"] == 2
    assert len(temporal["issue_samples"]) == 5
    assert temporal["issue_samples"][0] == {
        "case_id": "locomo:conv-1:qa:temporal",
        "group": "temporal",
        "item_id": "temporal-gap-0",
        "role": "temporal_support",
        "query_roles": ["temporal_support"],
        "source_refs": [],
        "issue_reasons": [
            "missing_source_window",
            "missing_session_boundary",
            "missing_date_or_range",
            "missing_temporal_grounding",
        ],
        "grounding_signals": {
            "source_window": False,
            "session_boundary": False,
            "date_or_range": False,
            "temporal_order": False,
        },
    }
    assert "text" not in temporal["issue_samples"][0]
    assert "selected_temporal_grounding_issues" in reasons


def test_failure_diagnostics_does_not_over_penalize_current_goal_recency() -> None:
    evaluation = {
        "case_id": "locomo:conv-1:qa:current-goal",
        "group": "temporal",
        "retrieval": {
            "metadata": {
                "query_decomposition": {
                    "query_profile": {"evidence_need": ["current_goal"]}
                }
            },
            "results": [
                {
                    "id": "current-goal",
                    "source_refs": ["D2:4"],
                    "memory": "D2:4 Caroline: My current goal is to stay local now.",
                    "metadata": {
                        "diagnostics": {
                            "benchmark_candidate_features": {
                                "query_roles": ["current_goal_support"],
                                "relation_category_hits": ["current_goal"],
                            }
                        }
                    },
                }
            ],
        },
        "retrieval_quality": {
            "expected_term_recall": 1.0,
            "evidence_term_recall": 1.0,
        },
        "evidence_bundle": {
            "bundle_complete": True,
            "items": [
                {
                    "id": "current-goal",
                    "role": "current_goal_support",
                    "query_roles": ["current_goal_support"],
                    "source_refs": ["D2:4"],
                    "text": "D2:4 Caroline: My current goal is to stay local now.",
                }
            ],
        },
        "generation": {},
        "judgment": {},
    }

    diagnostics = failure_diagnostics(evaluation)
    reasons = failure_diagnostic_reason_codes(
        evaluation,
        score=0.0,
        retrieval_recall=1.0,
        diagnostics=diagnostics,
    )

    temporal = diagnostics["temporal_grounding"]
    assert temporal["temporal_case"] is True
    assert temporal["selected_item_count"] == 1
    assert temporal["strong_item_count"] == 1
    assert temporal["issue_item_count"] == 0
    assert temporal["issue_reason_counts"] == {}
    assert temporal["issue_samples"] == []
    assert "selected_temporal_grounding_issues" not in reasons


def test_failure_diagnostics_counts_source_identity_refs_as_provenance() -> None:
    evaluation = {
        "retrieval": {
            "total_results": 1,
            "results": [
                {
                    "id": "dedupe-grounded",
                    "rank": 1,
                    "metadata": {
                        "diagnostics": {
                            "benchmark_candidate_features": {
                                "source_ref_dedupe_key": "source_turn_refs:D4:2",
                            }
                        }
                    },
                }
            ],
        },
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.0,
            "missing_evidence_terms": ["D4:3"],
        },
        "evidence_bundle": {
            "bundle_complete": False,
            "items": [
                {
                    "id": "dedupe-grounded",
                    "role": "primary",
                    "source_ref_dedupe_key": "source_turn_refs:D4:2",
                }
            ],
        },
        "generation": {},
        "judgment": {},
    }

    diagnostics = failure_diagnostics(evaluation)
    reasons = failure_diagnostic_reason_codes(
        evaluation,
        score=0.0,
        retrieval_recall=0.5,
        diagnostics=diagnostics,
    )

    assert diagnostics["source_ref_count"] == 1
    assert diagnostics["missing_evidence_source_locality"] == {
        "schema_version": "missing_evidence_source_locality.v1",
        "missing_turn_ref_count": 1,
        "retrieved_source_id_count": 1,
        "retrieved_source_ids": ["D4"],
        "bundle_source_id_count": 1,
        "bundle_source_ids": ["D4"],
        "same_source_missing_count": 1,
        "near_retrieved_window_count": 1,
        "source_absent_count": 0,
        "cause_counts": {"near_retrieved_window": 1},
        "missing_ref_window_count": 1,
        "missing_ref_window_omitted_count": 0,
        "missing_ref_windows": [
            {
                "ref": "D4:3",
                "source_id": "D4",
                "retrieved_same_source": True,
                "bundle_same_source": True,
                "nearest_retrieved_turn_ref": "D4:2",
                "nearest_retrieved_turn_distance": 1,
                "nearest_bundle_turn_ref": "D4:2",
                "nearest_bundle_turn_distance": 1,
                "cause": "near_retrieved_window",
            }
        ],
    }
    assert diagnostics["bundle"]["selected_bundle_source_ref_count"] == 1
    assert diagnostics["bundle"]["selected_bundle_source_ref_item_count"] == 1
    assert diagnostics["bundle"]["selected_bundle_source_refless_item_count"] == 0
    assert diagnostics["bundle"]["selected_bundle_source_ref_coverage_rate"] == 1.0
    assert "missing_evidence_source_window_miss" in reasons
    assert "selected_bundle_source_refless_evidence" not in reasons


def test_failure_diagnostics_uses_dedupe_identity_when_direct_refs_are_generic() -> None:
    evaluation = {
        "retrieval": {
            "total_results": 1,
            "results": [
                {
                    "id": "generic-direct-with-identity",
                    "rank": 1,
                    "source_refs": ["locomo-conv-4"],
                    "metadata": {
                        "diagnostics": {
                            "benchmark_candidate_features": {
                                "source_ref_dedupe_key": "source_turn_refs:D4:2",
                            }
                        }
                    },
                }
            ],
        },
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.0,
            "missing_evidence_terms": ["D4:3"],
        },
        "evidence_bundle": {
            "bundle_complete": False,
            "items": [
                {
                    "id": "generic-direct-with-identity",
                    "role": "primary",
                    "source_refs": ["locomo-conv-4"],
                    "source_ref_dedupe_key": "source_turn_refs:D4:2",
                }
            ],
        },
        "generation": {},
        "judgment": {},
    }

    diagnostics = failure_diagnostics(evaluation)
    reasons = failure_diagnostic_reason_codes(
        evaluation,
        score=0.0,
        retrieval_recall=0.5,
        diagnostics=diagnostics,
    )

    assert diagnostics["source_ref_count"] == 2
    assert diagnostics["missing_evidence_source_locality"] == {
        "schema_version": "missing_evidence_source_locality.v1",
        "missing_turn_ref_count": 1,
        "retrieved_source_id_count": 1,
        "retrieved_source_ids": ["D4"],
        "bundle_source_id_count": 1,
        "bundle_source_ids": ["D4"],
        "same_source_missing_count": 1,
        "near_retrieved_window_count": 1,
        "source_absent_count": 0,
        "cause_counts": {"near_retrieved_window": 1},
        "missing_ref_window_count": 1,
        "missing_ref_window_omitted_count": 0,
        "missing_ref_windows": [
            {
                "ref": "D4:3",
                "source_id": "D4",
                "retrieved_same_source": True,
                "bundle_same_source": True,
                "nearest_retrieved_turn_ref": "D4:2",
                "nearest_retrieved_turn_distance": 1,
                "nearest_bundle_turn_ref": "D4:2",
                "nearest_bundle_turn_distance": 1,
                "cause": "near_retrieved_window",
            }
        ],
    }
    assert diagnostics["bundle"]["selected_bundle_source_ref_count"] == 2
    assert diagnostics["bundle"]["selected_bundle_source_ref_item_count"] == 1
    assert diagnostics["bundle"]["selected_bundle_source_refless_item_count"] == 0
    assert "missing_evidence_source_window_miss" in reasons
    assert "missing_evidence_source_absent" not in reasons


def test_failure_diagnostics_uses_bundle_quality_weak_locality_fallback() -> None:
    evaluation = {
        "retrieval": {"total_results": 1, "results": []},
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.0,
        },
        "evidence_bundle": {
            "bundle_complete": False,
            "item_count": 1,
            "items": [{"role": "supporting"}],
            "bundle_planner": {
                "bundle_quality": {
                    "confidence_score": 0.2,
                    "confidence_band": "low",
                    "weak_source_locality_count": 1,
                    "reason_codes": ["risk:weak_source_locality"],
                }
            },
        },
        "generation": {},
        "judgment": {},
    }

    diagnostics = failure_diagnostics(evaluation)
    reasons = failure_diagnostic_reason_codes(
        evaluation,
        score=0.0,
        retrieval_recall=0.5,
        diagnostics=diagnostics,
    )

    assert diagnostics["bundle"]["selected_weak_source_locality_count"] == 1
    assert "selected_weak_source_locality_evidence" in reasons


def test_failure_diagnostics_reports_missing_evidence_source_absence() -> None:
    evaluation = {
        "retrieval": {
            "total_results": 2,
            "results": [
                {"source_refs": ["locomo:session_1:D1:4:turn"]},
                {"source_refs": ["locomo:session_2:D2:8:turn"]},
            ],
        },
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.0,
            "missing_evidence_terms": ["D3:2"],
        },
        "evidence_bundle": {
            "bundle_complete": False,
            "items": [{"role": "primary", "source_refs": ["D1:4"]}],
        },
        "generation": {},
        "judgment": {},
    }

    diagnostics = failure_diagnostics(evaluation)
    reasons = failure_diagnostic_reason_codes(
        evaluation,
        score=0.0,
        retrieval_recall=0.5,
        diagnostics=diagnostics,
    )

    assert diagnostics["missing_evidence_source_locality"] == {
        "schema_version": "missing_evidence_source_locality.v1",
        "missing_turn_ref_count": 1,
        "retrieved_source_id_count": 2,
        "retrieved_source_ids": ["session_1:D1", "session_2:D2"],
        "bundle_source_id_count": 1,
        "bundle_source_ids": ["D1"],
        "same_source_missing_count": 0,
        "near_retrieved_window_count": 0,
        "source_absent_count": 1,
        "cause_counts": {"source_absent": 1},
        "missing_ref_window_count": 1,
        "missing_ref_window_omitted_count": 0,
        "missing_ref_windows": [
            {
                "ref": "D3:2",
                "source_id": "D3",
                "retrieved_same_source": False,
                "bundle_same_source": False,
                "cause": "source_absent",
            }
        ],
    }
    assert "missing_evidence_source_absent" in reasons


def test_failure_diagnostics_reports_same_source_far_turn_cause() -> None:
    evaluation = {
        "retrieval": {
            "total_results": 1,
            "results": [{"source_refs": ["D4:2"]}],
        },
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.0,
            "missing_evidence_terms": ["D4:9"],
        },
        "evidence_bundle": {
            "bundle_complete": False,
            "items": [{"role": "primary", "source_refs": ["D4:2"]}],
        },
        "generation": {},
        "judgment": {},
    }

    diagnostics = failure_diagnostics(evaluation)
    reasons = failure_diagnostic_reason_codes(
        evaluation,
        score=0.0,
        retrieval_recall=0.5,
        diagnostics=diagnostics,
    )

    locality = diagnostics["missing_evidence_source_locality"]
    assert locality["cause_counts"] == {"same_source_miss": 1}
    assert locality["missing_ref_windows"] == [
        {
            "ref": "D4:9",
            "source_id": "D4",
            "retrieved_same_source": True,
            "bundle_same_source": True,
            "nearest_retrieved_turn_ref": "D4:2",
            "nearest_retrieved_turn_distance": 7,
            "nearest_bundle_turn_ref": "D4:2",
            "nearest_bundle_turn_distance": 7,
            "cause": "same_source_miss",
        }
    ]
    assert "missing_evidence_same_source_miss" in reasons
    assert "missing_evidence_source_window_miss" not in reasons


def test_failure_diagnostics_keeps_session_scoped_missing_evidence_sources() -> None:
    evaluation = {
        "retrieval": {
            "total_results": 1,
            "results": [{"source_refs": ["session_2:D4:10"]}],
        },
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.0,
            "missing_evidence_terms": ["session_1:D4:12", "D9:2"],
        },
        "evidence_bundle": {"bundle_complete": False, "items": []},
        "generation": {},
        "judgment": {},
    }

    diagnostics = failure_diagnostics(evaluation)
    reasons = failure_diagnostic_reason_codes(
        evaluation,
        score=0.0,
        retrieval_recall=0.5,
        diagnostics=diagnostics,
    )

    assert diagnostics["missing_evidence_source_locality"] == {
        "schema_version": "missing_evidence_source_locality.v1",
        "missing_turn_ref_count": 2,
        "retrieved_source_id_count": 1,
        "retrieved_source_ids": ["session_2:D4"],
        "bundle_source_id_count": 0,
        "bundle_source_ids": [],
        "same_source_missing_count": 0,
        "near_retrieved_window_count": 0,
        "source_absent_count": 2,
        "cause_counts": {"source_absent": 2},
        "missing_ref_window_count": 2,
        "missing_ref_window_omitted_count": 0,
        "missing_ref_windows": [
            {
                "ref": "session_1:D4:12",
                "source_id": "session_1:D4",
                "retrieved_same_source": False,
                "bundle_same_source": False,
                "cause": "source_absent",
            },
            {
                "ref": "D9:2",
                "source_id": "D9",
                "retrieved_same_source": False,
                "bundle_same_source": False,
                "cause": "source_absent",
            },
        ],
    }
    assert "missing_evidence_source_absent" in reasons
    assert "missing_evidence_source_window_miss" not in reasons


def test_failure_diagnostics_bounds_missing_evidence_source_samples_with_counts() -> None:
    evaluation = {
        "retrieval": {
            "total_results": 20,
            "results": [
                {"source_refs": [f"D{index}:1"]}
                for index in range(1, 21)
            ],
        },
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.0,
            "missing_evidence_terms": [
                f"D{index}:3"
                for index in range(1, 12)
            ],
        },
        "evidence_bundle": {
            "bundle_complete": False,
            "items": [
                {"role": "primary", "source_refs": [f"D{index}:1"]}
                for index in range(1, 16)
            ],
        },
        "generation": {},
        "judgment": {},
    }

    diagnostics = failure_diagnostics(evaluation)

    locality = diagnostics["missing_evidence_source_locality"]
    assert locality["retrieved_source_id_count"] == 20
    assert len(locality["retrieved_source_ids"]) == 12
    assert locality["bundle_source_id_count"] == 15
    assert len(locality["bundle_source_ids"]) == 12
    assert locality["missing_ref_window_count"] == 11
    assert locality["missing_ref_window_omitted_count"] == 3
    assert len(locality["missing_ref_windows"]) == 8
    assert locality["cause_counts"] == {"near_retrieved_window": 11}


def test_failure_diagnostics_report_primary_answer_context_support_gaps() -> None:
    evaluation = {
        "retrieval": {"total_results": 3, "results": []},
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.0,
        },
        "evidence_bundle": {
            "bundle_complete": False,
            "items": [],
            "bundle_planner": {
                "bundle_quality": {
                    "confidence_score": 0.2,
                    "confidence_band": "low",
                }
            },
        },
        "generation": {},
        "judgment": {},
        "cutoff_results": {
            "1": {
                "answer_context": {
                    "source": "evidence_bundle",
                    "memory_count": 1,
                    "source_ref_count": 1,
                    "source_ref_item_count": 1,
                    "source_refless_item_count": 0,
                    "source_ref_coverage_rate": 1.0,
                    "selected_bundle_item_count": 1,
                    "retrieval_orders": [1],
                    "item_ids": ["supported"],
                }
            },
            "3": {
                "answer_context": {
                    "source": "retrieval_slice",
                    "fallback_reason": "no_bundle_items_within_cutoff",
                    "memory_count": 2,
                    "source_ref_count": 0,
                    "source_ref_item_count": 0,
                    "source_refless_item_count": 2,
                    "source_identity_ref_count": 3,
                    "source_identity_item_count": 2,
                    "source_identity_refs": [
                        "source_turn_refs:D1:2",
                        "source_session_turn_refs:session_1:D1:3",
                        "raw memory text should not pass through",
                    ],
                    "source_identity_items": [
                        {
                            "item_id": "fallback-a",
                            "retrieval_order": 1,
                            "source_identity_refs": [
                                "source_turn_refs:D1:2",
                                "provider payload should not pass through",
                            ],
                        },
                        {
                            "item_id": "fallback-b",
                            "retrieval_order": 3,
                            "source_identity_refs": [
                                "source_session_turn_refs:session_1:D1:3",
                            ],
                        },
                    ],
                    "source_ref_coverage_rate": 0.0,
                    "selected_bundle_item_count": 0,
                    "skipped_bundle_item_count": 2,
                    "backfilled_retrieval_item_count": 1,
                    "role_requirement_complete": False,
                    "missing_required_roles": ["bridge"],
                    "risk_reason_codes": ["risk:retrieval_backfill"],
                    "retrieval_orders": [1, 3],
                    "item_ids": ["fallback-a", "fallback-b"],
                }
            },
        },
    }

    diagnostics = failure_diagnostics(evaluation)
    reasons = failure_diagnostic_reason_codes(
        evaluation,
        score=0.0,
        retrieval_recall=0.5,
        diagnostics=diagnostics,
    )

    assert diagnostics["answer_context"] == {
        "present": True,
        "cutoff": 3,
        "source": "retrieval_slice",
        "fallback_reason": "no_bundle_items_within_cutoff",
        "memory_count": 2,
        "source_ref_count": 0,
        "source_ref_item_count": 0,
        "source_refless_item_count": 2,
        "source_identity_ref_count": 3,
        "source_identity_item_count": 2,
        "source_identity_refs": (
            "source_turn_refs:D1:2",
            "source_session_turn_refs:session_1:D1:3",
        ),
        "source_identity_ref_sample_limit": 8,
        "source_identity_ref_sample_count": 2,
        "source_identity_ref_omitted_count": 1,
        "source_identity_item_sample_limit": 8,
        "source_identity_item_sample_count": 2,
        "source_identity_item_omitted_count": 0,
        "source_identity_refs_per_item_limit": 4,
        "source_identity_items": (
            {
                "source_identity_refs": ("source_turn_refs:D1:2",),
                "item_id": "fallback-a",
                "retrieval_order": 1,
            },
            {
                "source_identity_refs": (
                    "source_session_turn_refs:session_1:D1:3",
                ),
                "item_id": "fallback-b",
                "retrieval_order": 3,
            },
        ),
        "source_ref_coverage_rate": 0.0,
        "selected_bundle_item_count": 0,
        "skipped_bundle_item_count": 2,
        "backfilled_retrieval_item_count": 1,
        "role_requirement_complete": False,
        "missing_required_roles": ("bridge",),
        "risk_reason_codes": ("risk:retrieval_backfill",),
        "item_ids": ("fallback-a", "fallback-b"),
        "retrieval_orders": (1, 3),
    }
    assert "answer_context_fallback" in reasons
    assert "answer_context_source_refless" in reasons
    assert "answer_context_missing_required_roles" in reasons
    assert "answer_context_backfilled_retrieval" in reasons
    assert "answer_context_risk_reasons_present" in reasons
    rendered_source_identity = repr(
        (
            diagnostics["answer_context"]["source_identity_refs"],
            diagnostics["answer_context"]["source_identity_items"],
        )
    )
    assert "raw memory text should not pass through" not in rendered_source_identity
    assert "provider payload should not pass through" not in rendered_source_identity


def test_failure_diagnostics_reports_answer_context_identity_sample_bounds() -> None:
    source_identity_refs = [f"source_turn_refs:D{index}:2" for index in range(1, 11)]
    source_identity_items = [
        {
            "item_id": f"fallback-{index}",
            "retrieval_order": index,
            "source_identity_refs": [
                f"source_turn_refs:D{index}:{turn}" for turn in range(1, 6)
            ],
        }
        for index in range(1, 11)
    ]
    evaluation = {
        "retrieval": {"total_results": 10, "results": []},
        "retrieval_quality": {
            "expected_term_recall": 0.5,
            "evidence_term_recall": 0.0,
        },
        "evidence_bundle": {"bundle_complete": False, "items": []},
        "generation": {},
        "judgment": {},
        "answer_context": {
            "source": "retrieval_slice",
            "memory_count": 10,
            "source_ref_count": 0,
            "source_ref_item_count": 0,
            "source_refless_item_count": 10,
            "source_identity_ref_count": 10,
            "source_identity_item_count": 10,
            "source_identity_refs": source_identity_refs,
            "source_identity_items": source_identity_items,
        },
    }

    diagnostics = failure_diagnostics(evaluation)

    context = diagnostics["answer_context"]
    assert context["source_identity_ref_count"] == 10
    assert context["source_identity_ref_sample_limit"] == 8
    assert context["source_identity_ref_sample_count"] == 8
    assert context["source_identity_ref_omitted_count"] == 2
    assert context["source_identity_refs"] == tuple(source_identity_refs[:8])
    assert context["source_identity_item_count"] == 10
    assert context["source_identity_item_sample_limit"] == 8
    assert context["source_identity_item_sample_count"] == 8
    assert context["source_identity_item_omitted_count"] == 2
    assert context["source_identity_refs_per_item_limit"] == 4
    assert len(context["source_identity_items"]) == 8
    assert context["source_identity_items"][0]["source_identity_refs"] == (
        "source_turn_refs:D1:1",
        "source_turn_refs:D1:2",
        "source_turn_refs:D1:3",
        "source_turn_refs:D1:4",
    )
