from __future__ import annotations

import json

from infinity_context_server.memory_comparison_quality_answer_context_gaps import (
    answer_context_support_gap_summary,
)
from infinity_context_server.memory_comparison_quality_diagnostics import (
    fast_gate_metrics,
)


def test_fast_gate_metrics_reports_missing_contrast_evidence_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-contrast",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("contrast",),
                    relation_categories=("contrast",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D7:5"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_contrast"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {"missing_contrast": 1}
    assert breakdown["samples"][0]["reasons"] == [
        "missing_supporting",
        "missing_evidence_refs",
        "missing_contrast",
    ]


def test_answer_context_support_gap_samples_include_safe_context_identity() -> None:
    summary = answer_context_support_gap_summary(
        (
            {
                "case_id": "risky-context",
                "group": "single-hop",
                "cutoff_results": {
                    "5": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 2,
                            "source_ref_item_count": 0,
                            "source_refless_item_count": 2,
                            "missing_required_roles": ["primary"],
                            "source_identity_ref_count": 5,
                            "source_identity_item_count": 2,
                            "source_identity_refs": [
                                "source_turn_refs:D1:2",
                                "source_session_turn_refs:session_1:D1:3",
                                "source_session_turn_refs:session-2:D2-5",
                                "locomo:conv-private:session_1:D1:4:turn-secret",
                                "raw payload source identity must not appear",
                            ],
                            "item_ids": ["selected", "backfilled"],
                            "retrieval_orders": [1, "3", "not-an-order"],
                            "text": "raw payload text must not appear",
                            "risk_reason_codes": [
                                "risk:missing_required_role",
                            ],
                        }
                    }
                },
            },
        )
    )

    sample = summary["samples"][0]

    assert sample["item_ids"] == ["selected", "backfilled"]
    assert sample["retrieval_orders"] == [1, 3]
    assert sample["source_identity_ref_count"] == 5
    assert sample["source_identity_item_count"] == 2
    assert sample["source_identity_refs"] == [
        "source_turn_refs:D1:2",
        "source_session_turn_refs:session_1:D1:3",
        "source_session_turn_refs:session_2:D2:5",
    ]
    assert sample["risk_reason_codes"] == ["risk:missing_required_role"]
    assert "text" not in sample
    serialized = json.dumps(summary)
    assert "locomo:conv-private" not in serialized
    assert "raw payload source identity must not appear" not in serialized


def test_answer_context_support_gaps_accept_source_identity_grounding() -> None:
    summary = answer_context_support_gap_summary(
        (
            {
                "case_id": "source-identity-grounded-context",
                "group": "single-hop",
                "cutoff_results": {
                    "10": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 0,
                            "source_ref_item_count": 0,
                            "source_refless_item_count": 2,
                            "source_identity_ref_count": 2,
                            "source_identity_item_count": 2,
                            "source_identity_refs": [
                                "source_turn_refs:D1:1",
                                "source_turn_refs:D1:2",
                            ],
                        }
                    }
                },
            },
        )
    )

    assert summary["support_gap_context_count"] == 0
    assert summary["gap_reason_counts"] == {}
    assert summary["samples"] == []


def test_answer_context_support_gaps_do_not_double_count_identity_refless_items() -> None:
    summary = answer_context_support_gap_summary(
        (
            {
                "case_id": "identity-grounded-refless-context",
                "group": "single-hop",
                "cutoff_results": {
                    "10": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 2,
                            "source_ref_item_count": 0,
                            "source_refless_item_count": 2,
                            "source_identity_ref_count": 2,
                            "source_identity_item_count": 2,
                            "source_identity_refs": [
                                "source_turn_refs:D1:1",
                                "source_turn_refs:D1:2",
                            ],
                        }
                    }
                },
            },
        )
    )

    assert summary["support_gap_context_count"] == 0
    assert summary["gap_reason_counts"] == {}
    assert summary["samples"] == []


def test_answer_context_support_gaps_flag_partial_source_identity_grounding() -> None:
    summary = answer_context_support_gap_summary(
        (
            {
                "case_id": "partial-source-identity-grounded-context",
                "group": "temporal",
                "cutoff_results": {
                    "10": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 2,
                            "source_ref_item_count": 0,
                            "source_refless_item_count": 2,
                            "source_identity_ref_count": 1,
                            "source_identity_item_count": 1,
                            "source_identity_refs": ["source_turn_refs:D1:1"],
                        }
                    }
                },
            },
        )
    )

    assert summary["gap_reason_counts"] == {"partial_context_source_refs": 1}
    sample = summary["samples"][0]
    assert sample["gap_reasons"] == ["partial_context_source_refs"]
    assert sample["source_identity_ref_count"] == 1
    assert sample["source_identity_item_count"] == 1


def test_answer_context_support_gap_sample_metrics_are_json_safe() -> None:
    summary = answer_context_support_gap_summary(
        (
            {
                "case_id": "non-finite-answer-context-metrics",
                "cutoff_results": {
                    "3": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 1,
                            "source_ref_item_count": 0,
                            "avg_measured_answerability_score": "nan",
                            "avg_measured_source_locality_score": "inf",
                        }
                    }
                },
            },
        )
    )

    sample = summary["samples"][0]

    assert sample["avg_measured_answerability_score"] == 0.0
    assert sample["avg_measured_source_locality_score"] == 0.0
    json.dumps(sample, allow_nan=False)


def test_answer_context_support_gap_samples_include_skipped_bundle_counts() -> None:
    summary = answer_context_support_gap_summary(
        (
            {
                "case_id": "skipped-answer-context-support",
                "cutoff_results": {
                    "5": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 2,
                            "source_ref_item_count": 2,
                            "skipped_duplicate_source_bundle_item_count": 1,
                            "skipped_noisy_overlap_bundle_item_count": 2,
                            "skipped_redundant_risky_backfill_count": 3,
                            "backfilled_retrieval_item_count": 4,
                        }
                    }
                },
            },
        )
    )

    sample = summary["samples"][0]

    assert summary["gap_reason_counts"] == {
        "skipped_duplicate_source_bundle_item": 1,
        "skipped_noisy_overlap_bundle_item": 1,
        "skipped_redundant_risky_backfill": 1,
    }
    assert sample["backfilled_retrieval_item_count"] == 4
    assert sample["skipped_redundant_risky_backfill_count"] == 3
    assert sample["skipped_duplicate_source_bundle_item_count"] == 1
    assert sample["skipped_noisy_overlap_bundle_item_count"] == 2



def test_answer_context_support_gap_samples_omit_zero_skipped_bundle_counts() -> None:
    summary = answer_context_support_gap_summary(
        (
            {
                "case_id": "zero-skipped-answer-context-support",
                "cutoff_results": {
                    "5": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 2,
                            "source_ref_item_count": 0,
                            "source_refless_item_count": 2,
                            "skipped_duplicate_source_bundle_item_count": 0,
                            "skipped_noisy_overlap_bundle_item_count": 0,
                        }
                    }
                },
            },
        )
    )

    sample = summary["samples"][0]

    assert sample["source_refless_item_count"] == 2
    assert "skipped_duplicate_source_bundle_item_count" not in sample
    assert "skipped_noisy_overlap_bundle_item_count" not in sample

def test_answer_context_support_gaps_report_missing_and_unsupported_contexts() -> None:
    summary = answer_context_support_gap_summary(
        (
            {
                "case_id": "missing-answer-context",
                "group": "single-hop",
                "cutoff_results": {
                    "3": {},
                    "5": {"answer_context": []},
                    "10": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 1,
                            "source_ref_item_count": 1,
                        }
                    },
                },
            },
        )
    )

    assert summary["expected_context_count"] == 3
    assert summary["context_count"] == 1
    assert summary["answer_context_availability_gap_count"] == 2
    assert summary["missing_answer_context_count"] == 1
    assert summary["unsupported_answer_context_count"] == 1
    assert summary["availability_gap_samples"] == [
        {
            "case_id": "missing-answer-context",
            "group": "single-hop",
            "cutoff": "3",
            "source": "missing",
            "gap_reasons": ["missing_answer_context"],
        },
        {
            "case_id": "missing-answer-context",
            "group": "single-hop",
            "cutoff": "5",
            "source": "unsupported",
            "gap_reasons": ["unsupported_answer_context"],
        },
    ]


def test_answer_context_support_gaps_derive_low_confidence_context() -> None:
    items = (
        _item(
            case_id="preserved-low-confidence-context",
            cutoff_results={
                "10": {
                    "answer_context": {
                        "source": "evidence_bundle",
                        "memory_count": 1,
                        "source_ref_item_count": 1,
                        "bundle_confidence_score": 0.42,
                        "bundle_confidence_band": "low",
                        "bundle_source_ref_support_item_count": 1,
                    }
                }
            },
        ),
    )

    summary = answer_context_support_gap_summary(items)

    assert summary["gap_reason_counts"] == {"low_bundle_confidence": 1}
    assert summary["samples"][0]["gap_reasons"] == ["low_bundle_confidence"]


def test_fast_gate_metrics_rejects_contrast_role_label_without_surface() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="label-only-contrast",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("contrast",),
                    bundle_evidence_roles=("primary", "contrast"),
                    relation_categories=("contrast",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "contrast",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["role:contrast"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_contrast"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {"missing_contrast": 1}
    assert "missing_contrast" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_contrast_surface_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-contrast-surface",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("contrast",),
                    bundle_evidence_roles=("primary", "contrast"),
                    relation_categories=("contrast",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "contrast_surface": True,
                            "planner_reason_codes": ["contrast_surface"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_contrast" not in breakdown["reason_counts"]
    assert "missing_contrast" not in breakdown["evidence_need_gap_reason_counts"]


def test_fast_gate_metrics_rejects_weak_contrast_surface_evidence() -> None:
    weak_cases: tuple[tuple[str, dict[str, object]], ...] = (
        ("broad-summary", {"broad_summary": True}),
        ("conflict", {"conflict_or_stale": True}),
        ("weak-locality", {"source_locality_score": 0.3}),
        ("low-answerability", {"answerability_score": 0.4}),
    )

    for case_id, weak_fields in weak_cases:
        gate = fast_gate_metrics(
            (
                _item(
                    case_id=f"weak-contrast-{case_id}",
                    group="single-hop",
                    retrieval=_retrieval_payload(
                        evidence_need=("contrast",),
                        bundle_evidence_roles=("primary", "contrast"),
                        relation_categories=("contrast",),
                        policy_score=0.0,
                    ),
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [
                            {
                                "role": "contrast",
                                "retrieval_order": 1,
                                "focused_evidence_score": 1.0,
                                "contrast_surface": True,
                                "planner_reason_codes": ["contrast_surface"],
                                **weak_fields,
                            }
                        ],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"]["missing_contrast"] == 1
        assert breakdown["evidence_need_gap_reason_counts"] == {
            "missing_contrast": 1
        }
        assert "missing_contrast" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_rejects_stale_or_negation_without_current_contrast() -> None:
    for surface_key, reason_code in (
        ("stale_surface", "stale_surface"),
        ("negation_surface", "negation_surface"),
    ):
        gate = fast_gate_metrics(
            (
                _item(
                    case_id=f"{surface_key}-only",
                    group="single-hop",
                    retrieval=_retrieval_payload(
                        evidence_need=("contrast",),
                        bundle_evidence_roles=("primary", "contrast"),
                        relation_categories=("contrast",),
                        policy_score=0.0,
                    ),
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [
                            {
                                "role": "contrast",
                                "retrieval_order": 1,
                                "focused_evidence_score": 1.0,
                                surface_key: True,
                                "planner_reason_codes": [reason_code],
                            }
                        ],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"]["missing_contrast"] == 1
        assert breakdown["evidence_need_gap_reason_counts"] == {
            "missing_contrast": 1
        }
        assert "missing_contrast" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_currentness_with_stale_as_contrast() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="current-and-stale",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("contrast",),
                    bundle_evidence_roles=("primary", "contrast"),
                    relation_categories=("contrast",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "contrast",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "currentness_surface": True,
                            "stale_surface": True,
                            "planner_reason_codes": [
                                "currentness_surface",
                                "stale_surface",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_contrast" not in breakdown["reason_counts"]
    assert "missing_contrast" not in breakdown["evidence_need_gap_reason_counts"]


def test_fast_gate_metrics_rejects_temporal_role_label_without_surface() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="label-only-temporal",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "bundle_planner": {
                        "role_counts": {
                            "primary": 1,
                            "temporal_support": 1,
                        }
                    },
                    "items": [
                        {
                            "role": "temporal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["temporal_support"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_temporal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_temporal_support": 1
    }
    assert "missing_temporal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_rejects_currentness_for_duration_temporal_support() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="duration-currentness-only",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "temporal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "time_intent_kind": "duration",
                            "currentness_surface": True,
                            "planner_reason_codes": ["currentness_surface"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_temporal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_temporal_support": 1
    }
    assert "missing_temporal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_duration_temporal_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-duration-temporal",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "temporal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "has_duration_surface": True,
                            "planner_reason_codes": ["duration_surface"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_temporal_support" not in breakdown["reason_counts"]
    assert "missing_temporal_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_rejects_metadata_only_explicit_temporal_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="metadata-only-explicit-time",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "temporal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "time_intent_kind": "explicit_time",
                            "has_explicit_time_surface": True,
                            "has_explicit_time_content_surface": False,
                            "planner_reason_codes": ["explicit_time_surface"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_temporal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_temporal_support": 1
    }
    assert "missing_temporal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_content_explicit_temporal_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="content-explicit-time",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "temporal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "time_intent_kind": "explicit_time",
                            "has_explicit_time_surface": True,
                            "has_explicit_time_content_surface": True,
                            "planner_reason_codes": [
                                "explicit_time_surface",
                                "explicit_time_content_surface",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_temporal_support" not in breakdown["reason_counts"]
    assert "missing_temporal_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_rejects_broad_duration_temporal_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="broad-duration-temporal",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "temporal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 0.0,
                            "time_intent_kind": "duration",
                            "has_duration_surface": True,
                            "planner_reason_codes": [
                                "duration_surface",
                                "broad_summary",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_temporal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_temporal_support": 1
    }


def test_fast_gate_metrics_reads_support_need_from_retrieval_intent_relation() -> None:
    cases = (
        ("temporal", "missing_temporal_support"),
        ("contrast", "missing_contrast"),
        ("preference", "missing_preference_support"),
    )

    for relation_category, missing_reason in cases:
        retrieval = _retrieval_payload(
            evidence_need=(),
            relation_categories=(),
            policy_score=0.0,
        )
        query_decomposition = retrieval["metadata"]["query_decomposition"]
        query_decomposition["retrieval_intent"]["relations"] = {
            "intents": [{"category": relation_category}]
        }

        gate = fast_gate_metrics(
            (
                _item(
                    case_id=f"intent-relation-{relation_category}",
                    group="single-hop",
                    retrieval=retrieval,
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [
                            {
                                "role": "primary",
                                "retrieval_order": 1,
                                "focused_evidence_score": 1.0,
                            }
                        ],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"][missing_reason] == 1
        assert breakdown["evidence_need_gap_reason_counts"] == {missing_reason: 1}
        assert missing_reason in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_reads_support_need_from_bundle_roles() -> None:
    cases = (
        ("temporal_support", "missing_temporal_support"),
        ("explicit_temporal_support", "missing_temporal_support"),
        ("contrast", "missing_contrast"),
        ("location_support", "missing_location_support"),
    )

    for bundle_role, missing_reason in cases:
        gate = fast_gate_metrics(
            (
                _item(
                    case_id=f"role-need-{bundle_role}",
                    group="single-hop",
                    retrieval=_retrieval_payload(
                        evidence_need=(),
                        bundle_evidence_roles=("primary", bundle_role),
                        relation_categories=(),
                        policy_score=0.0,
                    ),
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [
                            {
                                "role": "primary",
                                "retrieval_order": 1,
                                "focused_evidence_score": 1.0,
                            }
                        ],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"][missing_reason] == 1
        assert breakdown["evidence_need_gap_reason_counts"] == {missing_reason: 1}
        assert missing_reason in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_reads_temporal_support_need_from_typed_evidence_need() -> None:
    cases = (
        "duration_temporal_support",
        "explicit_temporal_support",
        "relative_temporal_support",
        "temporal_sequence_support",
        "visual_temporal_support",
    )

    for evidence_need in cases:
        gate = fast_gate_metrics(
            (
                _item(
                    case_id=f"need-{evidence_need}",
                    group="single-hop",
                    retrieval=_retrieval_payload(
                        evidence_need=(evidence_need,),
                        relation_categories=(),
                        policy_score=0.0,
                    ),
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [
                            {
                                "role": "primary",
                                "retrieval_order": 1,
                                "focused_evidence_score": 1.0,
                            }
                        ],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"]["missing_temporal_support"] == 1
        assert breakdown["evidence_need_gap_reason_counts"] == {
            "missing_temporal_support": 1
        }
        assert "missing_temporal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_merges_support_need_from_profile_and_intent() -> None:
    retrieval = _retrieval_payload(
        evidence_need=(),
        bundle_evidence_roles=("primary",),
        relation_categories=("status_profile",),
        policy_score=0.0,
    )
    query_decomposition = retrieval["metadata"]["query_decomposition"]
    query_decomposition["retrieval_intent"]["evidence_need"] = ["visual_evidence"]
    query_decomposition["retrieval_intent"]["bundle_evidence_roles"] = [
        "primary",
        "visual_support",
    ]
    query_decomposition["retrieval_intent"]["relations"] = {
        "intents": [{"category": "preference"}]
    }

    gate = fast_gate_metrics(
        (
            _item(
                case_id="mixed-profile-intent-support",
                group="single-hop",
                retrieval=retrieval,
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_visual_support"] == 1
    assert breakdown["reason_counts"]["missing_preference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_preference_support": 1,
        "missing_visual_support": 1,
    }
    assert "missing_visual_support" in breakdown["samples"][0]["reasons"]
    assert "missing_preference_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_reads_support_need_from_query_expansion_intent() -> None:
    retrieval = _retrieval_payload(
        evidence_need=(),
        bundle_evidence_roles=("primary",),
        relation_categories=(),
        policy_score=0.0,
    )
    retrieval["metadata"]["query_expansion"] = {
        "retrieval_intent": {
            "evidence_need": ["visual_evidence"],
            "bundle_evidence_roles": ["primary", "visual_support"],
            "relations": {"intents": [{"category": "preference"}]},
        }
    }

    gate = fast_gate_metrics(
        (
            _item(
                case_id="query-expansion-intent-support",
                group="single-hop",
                retrieval=retrieval,
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_visual_support"] == 1
    assert breakdown["reason_counts"]["missing_preference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_preference_support": 1,
        "missing_visual_support": 1,
    }


def test_fast_gate_metrics_rejects_weak_preference_flag_without_relation() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="weak-preference-flag",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary", "preference_support"),
                    relation_categories=("preference",),
                    entities=("melanie",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "supporting",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["melanie"],
                            "has_preference_evidence": True,
                            "planner_reason_codes": ["role:supporting"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_preference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_preference_support": 1
    }


def test_fast_gate_metrics_accepts_planned_preference_relation_support() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="valid-preference-relation",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary", "preference_support"),
                    relation_categories=("preference",),
                    entities=("melanie",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "preference_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["melanie"],
                            "has_preference_evidence": True,
                            "relation_category_hits": ["preference"],
                            "planner_reason_codes": [
                                "preference_support",
                                "preference_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_preference_support" not in breakdown["reason_counts"]
    assert "missing_preference_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_rejects_stale_only_preference_support() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="stale-only-preference",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary", "preference_support"),
                    relation_categories=("preference",),
                    entities=("melanie",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "preference_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["melanie"],
                            "relation_category_hits": ["preference"],
                            "stale_surface": True,
                            "planner_reason_codes": [
                                "preference_relation_category_hits",
                                "stale_surface",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_preference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_preference_support": 1
    }
    assert "missing_preference_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_reports_missing_location_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-location",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("location_support",),
                    relation_categories=("location_transition",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D8:2"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": [],
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_location_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_location_support": 1
    }
    assert breakdown["samples"][0]["reasons"] == [
        "missing_supporting",
        "missing_evidence_refs",
        "missing_location_support",
    ]


def test_fast_gate_metrics_accepts_location_relation_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-location",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("location_support",),
                    relation_categories=("location_transition",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["caroline"],
                            "relation_category_hits": ["location_transition"],
                            "planner_reason_codes": [
                                "location_relation_category_hits"
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_location_support" not in breakdown["reason_counts"]
    assert "missing_location_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_rejects_weak_location_relation_evidence() -> None:
    weak_cases: tuple[tuple[str, dict[str, object]], ...] = (
        ("broad-summary", {"broad_summary": True}),
        ("stale-conflict", {"conflict_or_stale": True}),
        ("weak-locality", {"source_locality_score": 0.3}),
        ("low-answerability", {"answerability_score": 0.31}),
    )
    for case_id, weak_fields in weak_cases:
        gate = fast_gate_metrics(
            (
                _item(
                    case_id=f"weak-location-{case_id}",
                    group="single-hop",
                    retrieval=_retrieval_payload(
                        evidence_need=("location_support",),
                        bundle_evidence_roles=("primary", "location_support"),
                        relation_categories=("location_transition",),
                        entities=("caroline",),
                        policy_score=0.0,
                    ),
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [
                            {
                                "role": "location_support",
                                "retrieval_order": 1,
                                "focused_evidence_score": 1.0,
                                "entity_hits": ["caroline"],
                                "relation_category_hits": ["location_transition"],
                                "source_locality_score": 0.9,
                                "answerability_score": 0.72,
                                "planner_reason_codes": [
                                    "location_support",
                                    "location_relation_category_hits",
                                ],
                                **weak_fields,
                            }
                        ],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"]["missing_location_support"] == 1
        assert breakdown["evidence_need_gap_reason_counts"] == {
            "missing_location_support": 1
        }
        assert "missing_location_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_unmeasured_location_locality() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="unmeasured-location",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("location_support",),
                    bundle_evidence_roles=("primary", "location_support"),
                    relation_categories=("location_transition",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "location_support",
                            "retrieval_order": 1,
                            "entity_hits": ["caroline"],
                            "relation_category_hits": ["location_transition"],
                            "source_locality_score": 0.0,
                            "answerability_score": 0.72,
                            "planner_reason_codes": [
                                "location_support",
                                "location_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_location_support" not in breakdown["reason_counts"]
    assert "missing_location_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_accepts_unmeasured_location_answerability() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="unmeasured-location-answerability",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("location_support",),
                    bundle_evidence_roles=("primary", "location_support"),
                    relation_categories=("location_transition",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "location_support",
                            "retrieval_order": 1,
                            "entity_hits": ["caroline"],
                            "relation_category_hits": ["location_transition"],
                            "source_locality_score": 0.9,
                            "answerability_score": 0.0,
                            "planner_reason_codes": [
                                "location_support",
                                "location_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_location_support" not in breakdown["reason_counts"]
    assert "missing_location_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_requires_grounded_location_relation_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="ungrounded-location",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("location_support",),
                    bundle_evidence_roles=("primary", "location_support"),
                    relation_categories=("location_transition",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "location_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["location_transition"],
                            "planner_reason_codes": [
                                "location_support",
                                "location_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_location_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_location_support": 1
    }
    assert "missing_location_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_rejects_support_role_labels_without_typed_evidence() -> None:
    cases = (
        (
            "location",
            ("location_support",),
            ("primary", "location_support"),
            ("location_transition",),
            "location_support",
            "missing_location_support",
        ),
        (
            "preference",
            ("preference",),
            ("primary", "preference_support"),
            ("preference",),
            "preference_support",
            "missing_preference_support",
        ),
        (
            "visual",
            ("visual_evidence",),
            ("primary", "visual_support"),
            ("visual",),
            "visual_support",
            "missing_visual_support",
        ),
        (
            "emotion",
            ("emotion_response",),
            ("primary", "emotion_response_support"),
            ("emotion_response",),
            "emotion_response_support",
            "missing_emotion_response_support",
        ),
        (
            "symbolic",
            ("symbolic_meaning",),
            ("primary", "symbolic_meaning_support"),
            ("symbolic_meaning",),
            "symbolic_meaning_support",
            "missing_symbolic_meaning_support",
        ),
        (
            "event",
            ("registration_event",),
            ("primary", "event_support"),
            ("registration_event",),
            "event_support",
            "missing_event_support",
        ),
        (
            "exchange",
            ("exchange",),
            ("primary", "exchange_support"),
            ("exchange",),
            "exchange_support",
            "missing_exchange_support",
        ),
        (
            "communication",
            ("communication",),
            ("primary", "communication_support"),
            ("communication",),
            "communication_support",
            "missing_communication_support",
        ),
    )

    for (
        case_suffix,
        evidence_need,
        bundle_roles,
        relation_categories,
        support_role,
        missing_reason,
    ) in cases:
        item_payload = {
            "role": support_role,
            "retrieval_order": 1,
            "focused_evidence_score": 1.0,
            "entity_hits": ["caroline"],
            "planner_reason_codes": [support_role],
        }
        if support_role == "communication_support":
            item_payload["speaker_hits"] = ["caroline"]
            item_payload["planner_reason_codes"].append(
                "communication_speaker_hits"
            )
        gate = fast_gate_metrics(
            (
                _item(
                    case_id=f"label-only-{case_suffix}",
                    group="single-hop",
                    retrieval=_retrieval_payload(
                        evidence_need=evidence_need,
                        bundle_evidence_roles=bundle_roles,
                        relation_categories=relation_categories,
                        entities=("caroline",),
                        policy_score=0.0,
                    ),
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [item_payload],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"][missing_reason] == 1
        assert breakdown["evidence_need_gap_reason_counts"] == {missing_reason: 1}
        assert missing_reason in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_reports_missing_inference_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-inference",
                group="open-domain",
                retrieval=_retrieval_payload(
                    evidence_need=("inference_support",),
                    bundle_evidence_roles=("primary", "inference_support"),
                    relation_categories=("support_goal",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D2:3"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["inference_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_inference_support"] == 1
    assert breakdown["reason_counts"]["missing_required_inference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_inference_support": 1,
        "missing_required_inference_support": 1,
    }
    assert "missing_inference_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_inference_support" in breakdown["samples"][0][
        "reasons"
    ]


def test_fast_gate_metrics_reads_multihop_gap_from_typed_intent_need_or_marker() -> None:
    cases = (
        ("intent-only-inference-need", {"evidence_need": ["inference_support"]}),
        ("intent-only-hop-marker", {"multi_hop_markers": ["how"]}),
    )
    for case_id, intent_fields in cases:
        retrieval = _retrieval_payload(
            evidence_need=(),
            bundle_evidence_roles=("primary",),
            relation_categories=(),
            policy_score=0.0,
        )
        query_decomposition = retrieval["metadata"]["query_decomposition"]
        query_decomposition["retrieval_intent"].update(intent_fields)
        query_decomposition["retrieval_intent"]["bundle_evidence_roles"] = [
            "primary",
            "inference_support",
        ]

        gate = fast_gate_metrics(
            (
                _item(
                    case_id=case_id,
                    group="single-hop",
                    retrieval=retrieval,
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [
                            {
                                "role": "primary",
                                "retrieval_order": 1,
                                "focused_evidence_score": 1.0,
                            }
                        ],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"]["missing_bridge"] == 1
        assert breakdown["reason_counts"]["missing_bridge_entity"] == 1
        assert breakdown["reason_counts"]["missing_bridge_relation"] == 1
        assert breakdown["bridge_gap_reason_counts"] == {
            "missing_bridge": 1,
            "missing_bridge_entity": 1,
            "missing_bridge_relation": 1,
        }


def test_fast_gate_metrics_requires_relation_inference_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="ungrounded-inference",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("inference_support",),
                    bundle_evidence_roles=("primary", "inference_support"),
                    relation_categories=("status_profile",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "inference_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["caroline"],
                            "planner_reason_codes": [
                                "inference_support",
                                "inference_entity_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_inference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_inference_support": 1
    }
    assert "missing_inference_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_relation_inference_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="grounded-inference",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("inference_support",),
                    bundle_evidence_roles=("primary", "inference_support"),
                    relation_categories=("status_profile",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "inference_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["caroline"],
                            "relation_category_hits": ["status_profile"],
                            "planner_reason_codes": [
                                "inference_support",
                                "inference_entity_hits",
                                "inference_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_inference_support" not in breakdown["reason_counts"]
    assert "missing_inference_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_causal_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-causal",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("causal_support",),
                    bundle_evidence_roles=("primary", "causal_support"),
                    relation_categories=("causal",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D3:4"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["causal_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_causal_support"] == 1
    assert breakdown["reason_counts"]["missing_required_causal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_causal_support": 1,
        "missing_required_causal_support": 1,
    }
    assert "missing_causal_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_causal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_requires_grounded_causal_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="ungrounded-causal",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("causal_support",),
                    bundle_evidence_roles=("primary", "causal_support"),
                    relation_categories=("causal",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "causal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["causal"],
                            "planner_reason_codes": [
                                "causal_support",
                                "causal_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_causal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_causal_support": 1
    }
    assert "missing_causal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_requires_relation_causal_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="relationless-causal",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("causal_support",),
                    bundle_evidence_roles=("primary", "causal_support"),
                    relation_categories=("causal",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "causal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["caroline"],
                            "planner_reason_codes": [
                                "causal_support",
                                "causal_entity_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_causal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_causal_support": 1
    }
    assert "missing_causal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_relation_causal_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="grounded-causal",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("causal_support",),
                    bundle_evidence_roles=("primary", "causal_support"),
                    relation_categories=("causal",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "causal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["caroline"],
                            "relation_category_hits": ["causal"],
                            "planner_reason_codes": [
                                "causal_support",
                                "causal_entity_hits",
                                "causal_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_causal_support" not in breakdown["reason_counts"]
    assert "missing_causal_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_preference_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-preference",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary", "preference_support"),
                    relation_categories=("preference",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D4:1"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["preference_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_preference_support"] == 1
    assert breakdown["reason_counts"]["missing_required_preference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_preference_support": 1,
        "missing_required_preference_support": 1,
    }
    assert "missing_preference_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_preference_support" in breakdown["samples"][0][
        "reasons"
    ]


def test_fast_gate_metrics_accepts_preference_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-preference",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary", "preference_support"),
                    relation_categories=("preference",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "preference_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "has_preference_evidence": True,
                            "relation_category_hits": ["preference"],
                            "planner_reason_codes": [
                                "preference_support",
                                "preference_evidence",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_preference_support" not in breakdown["reason_counts"]
    assert "missing_required_preference_support" not in breakdown["reason_counts"]
    assert "missing_preference_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_emotion_response_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-emotion-response",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("emotion_response",),
                    bundle_evidence_roles=("primary", "emotion_response_support"),
                    relation_categories=("emotion_response",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["emotion_response_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_emotion_response_support"] == 1
    assert (
        breakdown["reason_counts"]["missing_required_emotion_response_support"]
        == 1
    )
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_emotion_response_support": 1,
        "missing_required_emotion_response_support": 1,
    }
    assert "missing_emotion_response_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_emotion_response_support" in breakdown["samples"][0][
        "reasons"
    ]


def test_fast_gate_metrics_accepts_emotion_response_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-emotion-response",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("emotion_response",),
                    bundle_evidence_roles=("primary", "emotion_response_support"),
                    relation_categories=("emotion_response",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "emotion_response_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["emotion_response"],
                            "planner_reason_codes": [
                                "emotion_response_support",
                                "emotion_response_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_emotion_response_support" not in breakdown["reason_counts"]
    assert "missing_required_emotion_response_support" not in breakdown[
        "reason_counts"
    ]
    assert "missing_emotion_response_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_symbolic_meaning_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-symbolic-meaning",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("symbolic_meaning",),
                    bundle_evidence_roles=("primary", "symbolic_meaning_support"),
                    relation_categories=("symbolic_meaning",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["symbolic_meaning_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_symbolic_meaning_support"] == 1
    assert (
        breakdown["reason_counts"]["missing_required_symbolic_meaning_support"]
        == 1
    )
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_required_symbolic_meaning_support": 1,
        "missing_symbolic_meaning_support": 1,
    }
    assert "missing_symbolic_meaning_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_symbolic_meaning_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-symbolic-meaning",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("symbolic_meaning",),
                    bundle_evidence_roles=("primary", "symbolic_meaning_support"),
                    relation_categories=("symbolic_meaning",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "symbolic_meaning_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["symbolic_meaning"],
                            "planner_reason_codes": [
                                "symbolic_meaning_support",
                                "symbolic_meaning_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_symbolic_meaning_support" not in breakdown["reason_counts"]
    assert "missing_required_symbolic_meaning_support" not in breakdown[
        "reason_counts"
    ]
    assert "missing_symbolic_meaning_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_event_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-event",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("participation_event",),
                    bundle_evidence_roles=("primary", "event_support"),
                    relation_categories=("participation_event",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["event_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_event_support"] == 1
    assert breakdown["reason_counts"]["missing_required_event_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_event_support": 1,
        "missing_required_event_support": 1,
    }
    assert "missing_event_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_event_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-event",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("registration_event",),
                    bundle_evidence_roles=("primary", "event_support"),
                    relation_categories=("registration_event",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "event_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["registration_event"],
                            "planner_reason_codes": [
                                "event_support",
                                "event_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_event_support" not in breakdown["reason_counts"]
    assert "missing_required_event_support" not in breakdown["reason_counts"]
    assert "missing_event_support" not in breakdown["evidence_need_gap_reason_counts"]


def test_fast_gate_metrics_reports_missing_exchange_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-exchange",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("exchange",),
                    bundle_evidence_roles=("primary", "exchange_support"),
                    relation_categories=("exchange",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["exchange_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_exchange_support"] == 1
    assert breakdown["reason_counts"]["missing_required_exchange_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_exchange_support": 1,
        "missing_required_exchange_support": 1,
    }


def test_fast_gate_metrics_accepts_exchange_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-exchange",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("exchange",),
                    bundle_evidence_roles=("primary", "exchange_support"),
                    relation_categories=("exchange",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "exchange_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["exchange"],
                            "planner_reason_codes": [
                                "exchange_support",
                                "exchange_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_exchange_support" not in breakdown["reason_counts"]
    assert "missing_required_exchange_support" not in breakdown["reason_counts"]
    assert "missing_exchange_support" not in breakdown["evidence_need_gap_reason_counts"]


def test_fast_gate_metrics_reports_missing_communication_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-communication",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("communication",),
                    bundle_evidence_roles=("primary", "communication_support"),
                    relation_categories=("communication",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["communication_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_communication_support"] == 1
    assert breakdown["reason_counts"]["missing_required_communication_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_communication_support": 1,
        "missing_required_communication_support": 1,
    }


def test_fast_gate_metrics_accepts_communication_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-communication",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("communication",),
                    bundle_evidence_roles=("primary", "communication_support"),
                    relation_categories=("communication",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "communication_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["communication"],
                            "planner_reason_codes": [
                                "communication_support",
                                "communication_relation_category_hits",
                                "communication_speaker_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_communication_support" not in breakdown["reason_counts"]
    assert "missing_required_communication_support" not in breakdown["reason_counts"]
    assert (
        "missing_communication_support"
        not in breakdown["evidence_need_gap_reason_counts"]
    )


def test_fast_gate_metrics_reports_missing_visual_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-visual",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("visual_evidence",),
                    bundle_evidence_roles=("primary", "visual_support"),
                    relation_categories=("visual",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D5:2"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["visual_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_visual_support"] == 1
    assert breakdown["reason_counts"]["missing_required_visual_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_visual_support": 1,
        "missing_required_visual_support": 1,
    }
    assert "missing_visual_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_visual_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_visual_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-visual",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("visual_evidence",),
                    bundle_evidence_roles=("primary", "visual_support"),
                    relation_categories=("visual",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "visual_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "has_visual_evidence": True,
                            "relation_category_hits": ["visual"],
                            "planner_reason_codes": [
                                "visual_support",
                                "visual_grounding",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_visual_support" not in breakdown["reason_counts"]
    assert "missing_required_visual_support" not in breakdown["reason_counts"]
    assert "missing_visual_support" not in breakdown["evidence_need_gap_reason_counts"]


def test_fast_gate_metrics_reports_missing_typed_relation_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-health-support",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("health_profile",),
                    bundle_evidence_roles=("primary", "health_support"),
                    relation_categories=("health_profile",),
                    entities=("alex",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["health_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["alex"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_typed_relation_support"] == 1
    assert breakdown["reason_counts"]["missing_health_support"] == 1
    assert breakdown["reason_counts"]["missing_required_health_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"][
        "missing_typed_relation_support"
    ] == 1
    assert breakdown["evidence_need_gap_reason_counts"]["missing_health_support"] == 1
    assert "missing_health_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_grounded_typed_relation_support() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-health-support",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("health_profile",),
                    bundle_evidence_roles=("primary", "health_support"),
                    relation_categories=("health_profile",),
                    entities=("alex",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 2,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 1,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["alex"],
                        },
                        {
                            "role": "health_support",
                            "retrieval_order": 2,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["health_profile"],
                            "entity_hits": ["alex"],
                            "answerability_score": 0.74,
                            "source_locality_score": 0.9,
                            "planner_reason_codes": [
                                "health_support",
                                "typed_relation_category_hits",
                            ],
                        },
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_typed_relation_support" not in breakdown["reason_counts"]
    assert "missing_health_support" not in breakdown["reason_counts"]
    assert "missing_required_health_support" not in breakdown["reason_counts"]
    assert (
        "missing_typed_relation_support"
        not in breakdown["evidence_need_gap_reason_counts"]
    )


def test_fast_gate_metrics_does_not_require_unpromoted_typed_relation_category() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="unpromoted-support-goal",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("multi_hop", "causal_support"),
                    bundle_evidence_roles=("primary", "bridge", "causal_support"),
                    relation_categories=("causal", "support_goal"),
                    entities=("morgan",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 2,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 1,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["morgan"],
                        },
                        {
                            "role": "causal_support",
                            "retrieval_order": 2,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["causal"],
                            "entity_hits": ["morgan"],
                            "answerability_score": 0.74,
                            "source_locality_score": 0.9,
                        },
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_typed_relation_support" not in breakdown["reason_counts"]
    assert "missing_support_goal_support" not in breakdown["reason_counts"]


def test_fast_gate_metrics_reports_missing_community_membership_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-community-membership-support",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("community_membership",),
                    bundle_evidence_roles=(
                        "primary",
                        "community_membership_support",
                    ),
                    relation_categories=("community_membership",),
                    entities=("alex",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["community_membership_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["alex"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_typed_relation_support"] == 1
    assert breakdown["reason_counts"]["missing_community_membership_support"] == 1
    assert (
        breakdown["reason_counts"][
            "missing_required_community_membership_support"
        ]
        == 1
    )
    assert "missing_community_membership_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_grounded_community_membership_support() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-community-membership-support",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("community_membership",),
                    bundle_evidence_roles=(
                        "primary",
                        "community_membership_support",
                    ),
                    relation_categories=("community_membership",),
                    entities=("alex",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 2,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 1,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["alex"],
                        },
                        {
                            "role": "community_membership_support",
                            "retrieval_order": 2,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["community_membership"],
                            "entity_hits": ["alex"],
                            "answerability_score": 0.74,
                            "source_locality_score": 0.9,
                            "planner_reason_codes": [
                                "community_membership_support",
                                "typed_relation_category_hits",
                            ],
                        },
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_typed_relation_support" not in breakdown["reason_counts"]
    assert "missing_community_membership_support" not in breakdown["reason_counts"]
    assert (
        "missing_required_community_membership_support"
        not in breakdown["reason_counts"]
    )


def test_fast_gate_metrics_surfaces_selected_evidence_weakness() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="weak-selected-evidence",
                group="single-hop",
                evidence_bundle={
                    "bundle_complete": True,
                    "item_count": 5,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 4,
                    "items": [
                        {
                            "id": "low-answerability",
                            "role": "primary",
                            "query_roles": ["original_question"],
                            "retrieval_order": 1,
                            "answerability_score": 0.42,
                            "source_locality_score": 0.7,
                            "source_refs": ["D1:1"],
                        },
                        {
                            "id": "weak-locality",
                            "role": "supporting",
                            "query_roles": ["location_support"],
                            "retrieval_order": 2,
                            "answerability_score": 0.72,
                            "source_locality_score": 0.3,
                            "source_refs": ["D1:2"],
                        },
                        {
                            "id": "broad-summary",
                            "role": "supporting",
                            "retrieval_order": 3,
                            "answerability_score": 0.73,
                            "source_locality_score": 0.8,
                            "broad_summary": True,
                            "source_refs": ["D1:3"],
                        },
                        {
                            "id": "stale-conflict",
                            "role": "supporting",
                            "retrieval_order": 4,
                            "answerability_score": 0.71,
                            "source_locality_score": 0.75,
                            "planner_reason_codes": ["conflict_or_stale"],
                            "source_refs": ["D1:4"],
                        },
                        {
                            "id": "unmeasured",
                            "role": "supporting",
                            "retrieval_order": 5,
                            "answerability_score": 0.0,
                            "source_locality_score": 0.0,
                        },
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    weakness = gate["selected_evidence_weakness"]

    assert gate["passed"] is False
    assert "selected_low_answerability_clear" in gate["failed_gates"]
    assert "selected_weak_source_locality_clear" in gate["failed_gates"]
    assert "selected_broad_summary_clear" in gate["failed_gates"]
    assert "selected_conflict_or_stale_clear" in gate["failed_gates"]
    assert weakness["weak_case_count"] == 1
    assert weakness["low_answerability_item_count"] == 1
    assert weakness["weak_source_locality_item_count"] == 1
    assert weakness["broad_summary_item_count"] == 1
    assert weakness["conflict_or_stale_item_count"] == 1
    assert weakness["reason_counts"] == {
        "selected_broad_summary": 1,
        "selected_conflict_or_stale": 1,
        "selected_low_answerability": 1,
        "selected_weak_source_locality": 1,
    }
    assert weakness["reason_role_counts"] == {
        "selected_broad_summary": {"supporting": 1},
        "selected_conflict_or_stale": {"supporting": 1},
        "selected_low_answerability": {"primary": 1},
        "selected_weak_source_locality": {"supporting": 1},
    }
    assert weakness["weak_support_role_reason_counts"] == {
        "supporting": {
            "selected_broad_summary": 1,
            "selected_conflict_or_stale": 1,
            "selected_weak_source_locality": 1,
        }
    }
    assert weakness["role_counts"] == {"primary": 1, "supporting": 3}
    assert weakness["query_role_counts"] == {
        "location_support": 1,
        "original_question": 1,
    }
    assert weakness["low_answerability_query_role_counts"] == {
        "original_question": 1
    }
    assert weakness["weak_source_locality_query_role_counts"] == {
        "location_support": 1
    }
    assert weakness["low_answerability_samples"][0]["item_id"] == "low-answerability"
    assert weakness["low_answerability_samples"][0]["source_refs"] == ["D1:1"]
    assert weakness["samples"][0]["query_roles"] == ["original_question"]
    assert weakness["samples"][0]["source_refs"] == ["D1:1"]
    assert weakness["samples"][2]["broad_summary"] is True
    assert weakness["samples"][3]["conflict_or_stale"] is True


def test_fast_gate_metrics_flags_backfilled_selected_stale_risk_codes() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="backfilled-risk-selected",
                group="temporal",
                evidence_bundle={
                    "bundle_complete": True,
                    "items": [
                        {
                            "id": "backfilled-stale",
                            "role": "supporting",
                            "retrieval_order": 1,
                            "answerability_score": 0.82,
                            "source_locality_score": 0.76,
                            "risk_reason_codes": [
                                "risk:backfilled_conflict_or_stale",
                                "risk:backfilled_broad_summary",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    weakness = gate["selected_evidence_weakness"]

    assert "selected_broad_summary_clear" in gate["failed_gates"]
    assert "selected_conflict_or_stale_clear" in gate["failed_gates"]
    assert weakness["broad_summary_item_count"] == 1
    assert weakness["conflict_or_stale_item_count"] == 1
    assert weakness["reason_counts"] == {
        "selected_broad_summary": 1,
        "selected_conflict_or_stale": 1,
    }
    assert weakness["risk_reason_counts"] == {
        "risk:backfilled_broad_summary": 1,
        "risk:backfilled_conflict_or_stale": 1,
    }
    assert weakness["samples"][0]["broad_summary"] is True
    assert weakness["samples"][0]["conflict_or_stale"] is True


def test_fast_gate_metrics_caps_selected_low_answerability_samples() -> None:
    gate = fast_gate_metrics(
        tuple(
            _item(
                case_id=f"low-answerability-{index}",
                evidence_bundle={"bundle_complete": True, "items": [_weak_item(index)]},
            )
            for index in range(7)
        ),
        expected_case_count=7,
    )

    samples = gate["selected_evidence_weakness"]["low_answerability_samples"]

    assert [sample["item_id"] for sample in samples] == [
        "low-0",
        "low-1",
        "low-2",
        "low-3",
        "low-4",
    ]
    assert len(samples[0]["query_roles"]) == 6
    assert samples[0]["query_role_count"] == 8
    assert len(samples[0]["source_refs"]) == 5
    assert samples[0]["source_ref_count"] == 7
    assert samples[0]["risk_reason_codes"] == [
        "risk:reason-0",
        "risk:reason-1",
        "risk:reason-2",
        "risk:reason-3",
        "risk:reason-4",
        "risk:reason-5",
    ]
    assert samples[0]["risk_reason_count"] == 8
    assert samples[0]["planner_reason_codes"] == [
        "planner-reason-0",
        "planner-reason-1",
        "planner-reason-2",
        "planner-reason-3",
        "planner-reason-4",
        "planner-reason-5",
    ]
    assert samples[0]["planner_reason_count"] == 8


def test_fast_gate_metrics_caps_selected_evidence_weakness_sample_values() -> None:
    long_value = "diagnostic-value-" + ("x" * 200)
    gate = fast_gate_metrics(
        (
            _item(
                case_id=long_value,
                group=long_value,
                evidence_bundle={
                    "bundle_complete": True,
                    "items": [
                        {
                            "id": long_value,
                            "role": long_value,
                            "query_roles": [long_value],
                            "answerability_score": 0.42,
                            "source_locality_score": 0.8,
                            "source_refs": [long_value],
                            "risk_reason_codes": [f"risk:{long_value}"],
                            "planner_reason_codes": [long_value],
                            "answerability_reason_codes": [long_value],
                            "source_type": long_value,
                            "stale_reason": long_value,
                            "conflict_reason": long_value,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    sample = gate["selected_evidence_weakness"]["low_answerability_samples"][0]

    for key in ("case_id", "group", "item_id", "role"):
        assert len(sample[key]) == 120
        assert sample[key].endswith("...")
    for key in (
        "query_roles",
        "source_refs",
        "risk_reason_codes",
        "planner_reason_codes",
        "answerability_reason_codes",
    ):
        assert len(sample[key][0]) == 120
        assert sample[key][0].endswith("...")
    for key in ("source_type", "stale_reason", "conflict_reason"):
        assert len(sample[key]) == 120
        assert sample[key].endswith("...")
    assert sample["query_role_count"] == 1
    assert sample["source_ref_count"] == 1


def test_fast_gate_metrics_keeps_selected_evidence_sample_metrics_json_safe() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="non-finite-selected-metrics",
                evidence_bundle={
                    "bundle_complete": True,
                    "items": [
                        {
                            "id": "non-finite",
                            "role": "supporting",
                            "answerability_score": "nan",
                            "source_locality_score": "inf",
                            "broad_summary": True,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    sample = gate["selected_evidence_weakness"]["broad_summary_samples"][0]

    assert sample["answerability_score"] == 0.0
    assert sample["source_locality_score"] == 0.0
    json.dumps(sample, allow_nan=False)


def _weak_item(index: int) -> dict[str, object]:
    return {
        "id": f"low-{index}",
        "role": "primary",
        "query_roles": [f"role-{role_index}" for role_index in range(8)],
        "answerability_score": 0.42,
        "source_locality_score": 0.8,
        "source_refs": [f"D{index}:{ref_index}" for ref_index in range(1, 8)],
        "risk_reason_codes": [
            " risk:reason-0 ",
            *[f"risk:reason-{reason_index}" for reason_index in range(8)],
        ],
        "planner_reason_codes": [
            " planner-reason-0 ",
            *[f"planner-reason-{reason_index}" for reason_index in range(8)],
        ],
    }


def test_fast_gate_metrics_clusters_selected_evidence_weakness_by_group() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="temporal-low-answerability",
                group="temporal",
                evidence_bundle={
                    "bundle_complete": True,
                    "items": [
                        {
                            "id": "temporal-weak",
                            "role": "primary",
                            "query_roles": ["temporal_anchor"],
                            "answerability_score": 0.45,
                            "source_locality_score": 0.82,
                        },
                    ],
                },
            ),
            _item(
                case_id="open-domain-low-answerability",
                group="open-domain",
                evidence_bundle={
                    "bundle_complete": True,
                    "items": [
                        {
                            "id": "open-domain-weak",
                            "role": "primary",
                            "query_roles": ["original_question"],
                            "answerability_score": 0.46,
                            "source_locality_score": 0.8,
                        },
                    ],
                },
            ),
            _item(
                case_id="open-domain-locality",
                group="open-domain",
                evidence_bundle={
                    "bundle_complete": True,
                    "items": [
                        {
                            "id": "open-domain-locality",
                            "role": "supporting",
                            "query_roles": ["location_support"],
                            "answerability_score": 0.72,
                            "source_locality_score": 0.35,
                        },
                    ],
                },
            ),
        ),
        expected_case_count=3,
    )

    weakness = gate["selected_evidence_weakness"]

    assert weakness["weak_case_count"] == 3
    assert weakness["group_counts"] == {"open-domain": 2, "temporal": 1}
    assert weakness["group_case_counts"] == {"open-domain": 2, "temporal": 1}
    assert weakness["reason_group_counts"] == {
        "selected_low_answerability": {"open-domain": 1, "temporal": 1},
        "selected_weak_source_locality": {"open-domain": 1},
    }
    assert weakness["reason_role_counts"] == {
        "selected_low_answerability": {"primary": 2},
        "selected_weak_source_locality": {"supporting": 1},
    }


def _item(
    *,
    case_id: str,
    score: float = 1.0,
    group: str = "multi-hop",
    retrieval_quality: dict[str, object] | None = None,
    evidence_bundle: dict[str, object] | None = None,
    retrieval: dict[str, object] | None = None,
    cutoff_results: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "group": group,
        "scored": True,
        "judgment": {"score": score},
        "retrieval_quality": retrieval_quality or {},
        "evidence_bundle": evidence_bundle or {},
        "retrieval": retrieval or {"metadata": {}, "results": []},
        "cutoff_results": cutoff_results or {},
    }


def _retrieval_payload(
    *,
    evidence_need: tuple[str, ...],
    policy_score: float,
    bundle_evidence_roles: tuple[str, ...] = (),
    relation_categories: tuple[str, ...] = (),
    entities: tuple[str, ...] = (),
    risk_flags: tuple[str, ...] = (),
    query_overlap_count: int = 0,
    query_plan: dict[str, object] | None = None,
    candidate_features: dict[str, object] | None = None,
    score_signals: dict[str, object] | None = None,
    item_id: str | None = None,
    rank: int = 1,
    score: float = 0.5,
    memory_text: str = "",
) -> dict[str, object]:
    return {
        "metadata": {
            "query_decomposition": {
                "query_profile": {
                    "evidence_need": evidence_need,
                    "bundle_evidence_roles": bundle_evidence_roles,
                    "relation_categories": relation_categories,
                    "entities": entities,
                    "risk_flags": risk_flags,
                },
                "retrieval_intent": {
                    "entity_count": len(entities),
                    "entities": [
                        {"canonical": entity, "surfaces": [entity]}
                        for entity in entities
                    ],
                    "evidence_need": list(evidence_need),
                    "bundle_evidence_roles": list(bundle_evidence_roles),
                    "risk_flags": list(risk_flags),
                    "relations": {
                        "intents": [
                            {"category": category}
                            for category in relation_categories
                        ]
                    },
                },
                "query_plan": query_plan or {},
            },
            "query_integrity": {
                "expected_answer_query_overlap_count": query_overlap_count,
                "expected_answer_query_overlap_terms": ["answer"]
                if query_overlap_count
                else [],
                "retrieval_intent_risk_flags": list(risk_flags),
            },
        },
        "results": [
            {
                **({"id": item_id} if item_id else {}),
                "rank": rank,
                "score": score,
                "memory": memory_text,
                "metadata": {
                    "diagnostics": {
                        "benchmark_rerank_boosted": bool(policy_score),
                        "score_signals": score_signals or {},
                        "benchmark_candidate_features": candidate_features or {},
                        "benchmark_rerank_policy": {
                            "contributions": [
                                {
                                    "policy": "FocusedTurnPolicy",
                                    "score": policy_score,
                                    "reason_codes": ["focused_turn"]
                                    if policy_score
                                    else [],
                                }
                            ]
                        }
                    }
                }
            }
        ],
    }
