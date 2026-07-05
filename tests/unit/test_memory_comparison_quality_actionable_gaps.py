from __future__ import annotations

import json

from infinity_context_server.memory_comparison_quality_actionable_gaps import (
    actionable_gap_summary,
)
from infinity_context_server.memory_comparison_quality_diagnostics import (
    fast_gate_metrics,
)

from tests.unit.test_memory_comparison_quality_diagnostics import (
    _bundle_quality,
    _fast_gate_bundle,
    _item,
    _rerank_candidate_payload,
    _retrieval_payload,
)


def test_fast_gate_metrics_ranks_actionable_gaps_by_observed_impact() -> None:
    items: list[dict[str, object]] = []
    for index in range(1, 4):
        bundle = _fast_gate_bundle(
            index,
            bundle_quality=_bundle_quality(
                confidence_score=0.76,
                confidence_band="high",
                reason_codes=("has_primary_evidence", "high_answerability"),
                selected_item_count=1,
                primary_count=1,
            ),
        )
        bundle["items"][0].update(
            {
                "answerability_score": 0.4,
                "source_refs": [f"D{index}:1"],
            }
        )
        items.append(_item(case_id=f"weak-{index}", evidence_bundle=bundle))

    for index in range(4, 6):
        items.append(
            _item(
                case_id=f"missing-contrast-{index}",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("contrast",),
                    relation_categories=("contrast",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "evidence_term_count": 1,
                    "covered_evidence_terms": [f"D{index}:1"],
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "items": [
                        {
                            "retrieval_order": 1,
                            "covered_evidence_terms": [f"D{index}:1"],
                            "focused_evidence_score": 1.0,
                            "source_refs": [f"D{index}:1"],
                        }
                    ],
                },
            )
        )

    gate = fast_gate_metrics(tuple(items), expected_case_count=40)
    summary = gate["actionable_gap_summary"]
    ranked_gaps = summary["ranked_gaps"]

    assert summary["schema_version"] == "actionable_gap_summary.v1"
    assert summary["evaluation_count"] == 5
    assert ranked_gaps[0]["category"] == "bundle_quality"
    assert ranked_gaps[0]["gap"] == "weak_bundle_quality"
    assert ranked_gaps[0]["impact_count"] == 3
    assert ranked_gaps[0]["failed_gate"] == "bundle_quality_medium_or_high"
    assert ranked_gaps[0]["sample_case_ids"] == ["weak-1", "weak-2", "weak-3"]
    selected_gap = next(
        gap for gap in ranked_gaps if gap["gap"] == "selected_low_answerability"
    )
    assert selected_gap["impact_count"] == 3
    assert selected_gap["failed_gate"] == "selected_low_answerability_clear"
    assert [gap["impact_count"] for gap in ranked_gaps] == sorted(
        (gap["impact_count"] for gap in ranked_gaps),
        reverse=True,
    )
    assert "case_count" in gate["failed_gates"]
    assert all(gap["gap"] != "case_count" for gap in ranked_gaps)


def test_fast_gate_metrics_actionable_summary_is_empty_when_no_observed_gaps() -> None:
    items = tuple(
        _item(
            case_id=f"case-{index}",
            evidence_bundle=_fast_gate_bundle(
                index,
                bundle_quality=_bundle_quality(
                    confidence_score=0.76,
                    confidence_band="high",
                    reason_codes=("has_primary_evidence", "high_answerability"),
                    selected_item_count=1,
                    primary_count=1,
                ),
            ),
        )
        for index in range(1, 41)
    )
    for index, item in enumerate(items, start=1):
        bundle = item["evidence_bundle"]
        assert isinstance(bundle, dict)
        bundle["items"][0]["source_refs"] = [f"D{index}:1"]

    gate = fast_gate_metrics(items)
    summary = gate["actionable_gap_summary"]

    assert gate["schema_version"] == "fast_gate.v1"
    assert gate["passed"] is True
    assert summary["top_gap"] is None
    assert summary["ranked_gaps"] == []
    assert summary["gap_count"] == 0


def test_fast_gate_metrics_actionable_summary_is_empty_for_missing_sections() -> None:
    gate = fast_gate_metrics((), expected_case_count=40)
    summary = gate["actionable_gap_summary"]

    assert gate["schema_version"] == "fast_gate.v1"
    assert gate["passed"] is False
    assert "case_count" in gate["failed_gates"]
    assert summary == {
        "schema_version": "actionable_gap_summary.v1",
        "evaluation_count": 0,
        "expected_case_count": 40,
        "gap_count": 0,
        "blocking_gap_count": 0,
        "diagnostic_gap_count": 0,
        "rank_basis": "observed_impact_desc_blocking_tie_break",
        "top_gap": None,
        "ranked_gaps": [],
    }


def test_actionable_gap_summary_accepts_missing_optional_sections() -> None:
    summary = actionable_gap_summary(
        evaluation_count=0,
        expected_case_count=40,
        failed_gates=("case_count",),
        query_overlap_count=0,
        profile_overlap_count=0,
        intent_overlap_count=0,
    )

    assert summary == {
        "schema_version": "actionable_gap_summary.v1",
        "evaluation_count": 0,
        "expected_case_count": 40,
        "gap_count": 0,
        "blocking_gap_count": 0,
        "diagnostic_gap_count": 0,
        "rank_basis": "observed_impact_desc_blocking_tie_break",
        "top_gap": None,
        "ranked_gaps": [],
    }


def test_fast_gate_metrics_actionable_summary_explains_query_plan_role_gap() -> None:
    bundle = _fast_gate_bundle(
        1,
        bundle_quality=_bundle_quality(
            confidence_score=0.76,
            confidence_band="high",
            reason_codes=("has_primary_evidence", "high_answerability"),
            selected_item_count=1,
            primary_count=1,
        ),
    )
    bundle["items"][0]["source_refs"] = ["D1:1"]
    query_plan = {
        "schema_version": "query_plan.v2",
        "selected_query_count": 1,
        "dropped_query_count": 0,
        "selected_roles": ["original_question"],
        "dropped_roles": [],
        "recommended_role_families": ["base_query"],
        "selected_role_families": ["base_query"],
        "missing_recommended_role_families": [],
        "selected_role_family_counts": {"base_query": 1},
        "fanout_integrity": {"bounded": True},
    }
    item = _item(
        case_id="favorite-actionable",
        group="single-hop",
        evidence_bundle=bundle,
        retrieval=_retrieval_payload(
            evidence_need=("favorite_preference", "preference"),
            bundle_evidence_roles=("primary", "favorite_support"),
            relation_categories=("favorite_preference", "preference"),
            policy_score=0.0,
            query_plan=query_plan,
        ),
    )

    gate = fast_gate_metrics((item,), expected_case_count=1)
    summary = gate["actionable_gap_summary"]
    ranked_gaps = summary["ranked_gaps"]
    role_gap = next(
        gap
        for gap in ranked_gaps
        if gap["source_metric"]
        == (
            "query_plan_gap_breakdown."
            "missing_evidence_role_query_family_counts"
        )
        and gap["gap"] == "favorite_support"
    )
    reason_gap = next(
        gap
        for gap in ranked_gaps
        if gap["source_metric"] == "query_plan_gap_breakdown.gap_reason_counts"
        and gap["gap"] == "missing_evidence_role_query_family"
    )

    assert role_gap["failed_gate"] == "query_plan_evidence_roles_clear"
    assert role_gap["action"] == (
        "Add query-plan coverage for the favorite support role family using "
        "relation compact or expanded focus queries."
    )
    assert role_gap["evidence"] == {
        "role_family": "favorite_support",
        "role_family_label": "favorite support",
        "accepted_query_families": ["relation_compact", "expanded_focus"],
    }
    assert role_gap["sample_case_ids"] == ["favorite-actionable"]
    assert role_gap["samples"] == [
        {
            "case_id": "favorite-actionable",
            "group": "single-hop",
            "gap_reasons": ["missing_evidence_role_query_family"],
            "missing_evidence_role_query_families": ["favorite_support"],
            "selected_role_families": ["base_query"],
            "required_evidence_roles": ["primary", "favorite_support"],
            "selected_query_count": 1,
        }
    ]
    assert reason_gap["action"] == (
        "Add selected query families that satisfy required evidence role "
        "families."
    )
    assert reason_gap["samples"] == role_gap["samples"]


def test_fast_gate_actionable_summary_reports_evidence_recall_gaps() -> None:
    long_ref = f"D3:{'9' * 200}"
    items = (
        _item(
            case_id="missing-ref",
            group="multi-hop",
            retrieval_quality={
                "expected_term_recall": 1.0,
                "evidence_term_recall": 0.0,
                "missing_evidence_terms": ["D3:4", long_ref],
            },
            evidence_bundle={"bundle_complete": False},
        ),
        _item(
            case_id="weak-recall",
            group="single-hop",
            retrieval_quality={
                "expected_term_recall": 1.0,
                "evidence_term_recall": 0.5,
                "missing_evidence_terms": [],
            },
            evidence_bundle={"bundle_complete": True},
        ),
        _item(
            case_id="unmeasured-missing-ref",
            group="single-hop",
            retrieval_quality={
                "expected_term_recall": 0.5,
                "missing_evidence_terms": ["D7:1"],
            },
            evidence_bundle={"bundle_complete": False},
        ),
    )

    gate = fast_gate_metrics(items, expected_case_count=3)
    ranked_gaps = gate["actionable_gap_summary"]["ranked_gaps"]
    missing_gap = next(
        gap
        for gap in ranked_gaps
        if gap["source_metric"]
        == "evidence_recall_gap_summary.missing_evidence_ref_case_count"
    )
    weak_gap = next(
        gap
        for gap in ranked_gaps
        if gap["source_metric"]
        == "evidence_recall_gap_summary.weak_evidence_recall_case_count"
    )

    assert missing_gap["category"] == "evidence_recall"
    assert missing_gap["gap"] == "missing_evidence_refs"
    assert missing_gap["severity"] == "diagnostic"
    assert missing_gap["impact_count"] == 2
    assert missing_gap["sample_case_ids"] == [
        "missing-ref",
        "unmeasured-missing-ref",
    ]
    assert missing_gap["evidence"] == {
        "top_missing_evidence_terms": {
            "D3:4": 1,
            "D7:1": 1,
            f"D3:{'9' * 122}...": 1,
        },
        "measured_evidence_recall_count": 2,
        "avg_evidence_term_recall": 0.25,
    }
    assert missing_gap["samples"] == [
        {
            "case_id": "missing-ref",
            "group": "multi-hop",
            "expected_term_recall": 1.0,
            "evidence_term_recall": 0.0,
            "evidence_term_recall_measured": True,
            "missing_evidence_terms": ["D3:4", f"D3:{'9' * 122}..."],
            "missing_evidence_term_count": 2,
            "bundle_complete": False,
        },
        {
            "case_id": "unmeasured-missing-ref",
            "group": "single-hop",
            "expected_term_recall": 0.5,
            "evidence_term_recall_measured": False,
            "missing_evidence_terms": ["D7:1"],
            "missing_evidence_term_count": 1,
            "bundle_complete": False,
        },
    ]
    assert weak_gap["gap"] == "weak_evidence_term_recall"
    assert weak_gap["impact_count"] == 2
    assert weak_gap["sample_case_ids"] == ["missing-ref", "weak-recall"]


def test_actionable_summary_reports_answer_context_provenance_gap() -> None:
    bundle = _fast_gate_bundle(
        1,
        bundle_quality=_bundle_quality(
            confidence_score=0.76,
            confidence_band="high",
            reason_codes=("has_primary_evidence", "high_answerability"),
            selected_item_count=1,
            primary_count=1,
        ),
    )
    bundle["items"][0]["source_refs"] = ["D1:1"]
    item = _item(
        case_id="prompt-provenance-gap",
        evidence_bundle=bundle,
        cutoff_results={
            "200": {
                "answer_context": {
                    "source": "evidence_bundle",
                    "memory_count": 2,
                    "source_ref_count": 0,
                    "source_ref_item_count": 0,
                    "source_refless_item_count": 2,
                }
            }
        },
    )

    gate = fast_gate_metrics((item,), expected_case_count=1)
    summary = gate["actionable_gap_summary"]
    gap = next(
        gap
        for gap in summary["ranked_gaps"]
        if gap["category"] == "answer_context_provenance"
    )

    assert gate["passed"] is True
    assert gap["gap"] == "answer_context_missing_source_refs"
    assert gap["impact_count"] == 2
    assert gap["source_metric"] == "answer_context_provenance.source_refless_item_count"
    assert gap["severity"] == "diagnostic"
    assert gap["sample_case_ids"] == ["prompt-provenance-gap"]
    assert gap["evidence"] == {
        "source_refless_context_count": 1,
        "source_ref_item_coverage_rate": 0.0,
        "source_counts": {"evidence_bundle": 1},
    }
    assert gap["samples"] == [
        {
            "case_id": "prompt-provenance-gap",
            "cutoff": "200",
            "source": "evidence_bundle",
            "memory_count": 2,
            "source_refless_item_count": 2,
        }
    ]


def test_actionable_summary_bounds_answer_context_provenance_samples() -> None:
    long_value = "x" * 200
    summary = actionable_gap_summary(
        evaluation_count=4,
        expected_case_count=4,
        failed_gates=(),
        query_overlap_count=0,
        profile_overlap_count=0,
        intent_overlap_count=0,
        answer_context_provenance={
            "source_refless_context_count": 4,
            "source_refless_item_count": 4,
            "source_ref_item_coverage_rate": 0.25,
            "source_counts": {"evidence_bundle": 4},
            "source_refless_context_samples": [
                {
                    "case_id": f"case-{index}-{long_value}",
                    "cutoff": "200",
                    "source": "evidence_bundle",
                    "memory_count": index,
                    "source_ref_count": 1,
                    "source_ref_item_count": 1,
                    "source_refless_item_count": 1,
                    "fallback_reason": f"fallback-{long_value}",
                    "raw_provider_payload": "excluded",
                    "memory_text": "excluded",
                }
                for index in range(1, 5)
            ],
        },
    )

    gap = summary["top_gap"]
    assert isinstance(gap, dict)
    assert gap["sample_case_ids"] == [
        f"case-1-{long_value[:118]}...",
        f"case-2-{long_value[:118]}...",
        f"case-3-{long_value[:118]}...",
    ]
    assert len(gap["samples"]) == 3
    assert gap["samples"][0] == {
        "case_id": f"case-1-{long_value[:118]}...",
        "cutoff": "200",
        "source": "evidence_bundle",
        "fallback_reason": f"fallback-{long_value[:116]}...",
        "memory_count": 1,
        "source_ref_count": 1,
        "source_ref_item_count": 1,
        "source_refless_item_count": 1,
    }
    assert "raw_provider_payload" not in gap["samples"][0]
    assert "memory_text" not in gap["samples"][0]


def test_answer_context_provenance_samples_include_safe_audit_detail() -> None:
    bundle = _fast_gate_bundle(
        1,
        bundle_quality=_bundle_quality(
            confidence_score=0.76,
            confidence_band="high",
            reason_codes=("has_primary_evidence", "high_answerability"),
            selected_item_count=1,
            primary_count=1,
        ),
    )
    bundle["items"][0]["source_refs"] = ["D1:1"]
    item = _item(
        case_id="context-audit-gap",
        evidence_bundle=bundle,
        cutoff_results={
            "200": {
                "answer_context": {
                    "source": "evidence_bundle",
                    "memory_count": 2,
                    "source_ref_count": 1,
                    "source_ref_item_count": 1,
                    "source_refless_item_count": 1,
                    "source_identity_ref_count": 3,
                    "source_identity_item_count": 2,
                    "source_identity_refs": [
                        "source_turn_refs:D1:2",
                        "source_session_turn_refs:session_1:D1:3",
                        "locomo:conv-private:session_1:D1:4:turn-secret",
                    ],
                    "source_identity_items": [
                        {
                            "item_id": "selected",
                            "retrieval_order": 1,
                            "source_identity_refs": [
                                "source_turn_refs:D1:2",
                                "raw provider payload must not appear",
                            ],
                        }
                    ],
                    "item_ids": ["selected", "support"],
                    "retrieval_orders": [1, 2],
                    "missing_required_roles": ["supporting"],
                    "risk_reason_codes": ["risk:missing_required_role"],
                    "text": "raw memory text must not appear",
                }
            }
        },
    )

    gate = fast_gate_metrics((item,), expected_case_count=1)
    provenance_sample = gate["answer_context_provenance"][
        "source_refless_context_samples"
    ][0]
    gap = next(
        gap
        for gap in gate["actionable_gap_summary"]["ranked_gaps"]
        if gap["category"] == "answer_context_provenance"
    )

    assert provenance_sample["item_ids"] == ["selected", "support"]
    assert provenance_sample["retrieval_orders"] == [1, 2]
    assert provenance_sample["source_identity_refs"] == [
        "source_turn_refs:D1:2",
        "source_session_turn_refs:session_1:D1:3",
    ]
    assert provenance_sample["source_identity_items"] == [
        {
            "source_identity_refs": ["source_turn_refs:D1:2"],
            "item_id": "selected",
            "retrieval_order": 1,
        }
    ]
    assert provenance_sample["missing_required_roles"] == ["supporting"]
    assert provenance_sample["risk_reason_codes"] == ["risk:missing_required_role"]
    assert gap["samples"] == [
        {
            "case_id": "context-audit-gap",
            "cutoff": "200",
            "source": "evidence_bundle",
            "item_ids": ["selected", "support"],
            "missing_required_roles": ["supporting"],
            "risk_reason_codes": ["risk:missing_required_role"],
            "source_identity_refs": [
                "source_turn_refs:D1:2",
                "source_session_turn_refs:session_1:D1:3",
            ],
            "retrieval_orders": [1, 2],
            "memory_count": 2,
            "source_ref_count": 1,
            "source_ref_item_count": 1,
            "source_refless_item_count": 1,
            "source_identity_ref_count": 3,
            "source_identity_item_count": 2,
        }
    ]
    serialized = json.dumps(gate)
    assert "locomo:conv-private" not in serialized
    assert "raw provider payload must not appear" not in serialized
    assert "raw memory text must not appear" not in serialized


def test_actionable_temporal_grounding_samples_filter_unsafe_source_refs() -> None:
    long_exact_ref = f"D1:{'8' * 120}"
    summary = actionable_gap_summary(
        evaluation_count=1,
        expected_case_count=1,
        failed_gates=(),
        query_overlap_count=0,
        profile_overlap_count=0,
        intent_overlap_count=0,
        temporal_grounding={
            "temporal_case_count": 1,
            "selected_temporal_grounding_issue_item_count": 1,
            "selected_strong_temporal_grounding_item_count": 0,
            "selected_temporal_grounding_issue_reason_counts": {
                "missing_date_or_range": 1
            },
            "selected_temporal_grounding_issue_samples": [
                {
                    "case_id": "temporal-actionable",
                    "group": "temporal",
                    "item_id": "unsafe-source-item",
                    "role": "temporal_sequence_support",
                    "query_roles": ["temporal_sequence_support"],
                    "source_refs": [
                        "source_turn_refs:D1:2",
                        "source_turn_refs:D1:2",
                        f"D2:{'8' * 120}",
                        "locomo:conv-private:session_2:D2:3:turn-secret",
                        long_exact_ref,
                        f"source_turn_refs:D1:{'9' * 90}",
                    ],
                    "source_ref_count": 5,
                    "issue_reasons": ["missing_date_or_range"],
                    "grounding_signals": {
                        "source_window": True,
                        "session_boundary": True,
                        "date_or_range": False,
                    },
                }
            ],
        },
    )

    gap = summary["top_gap"]

    assert isinstance(gap, dict)
    assert gap["category"] == "temporal_grounding"
    assert gap["samples"] == [
        {
            "case_id": "temporal-actionable",
            "group": "temporal",
            "item_id": "unsafe-source-item",
            "role": "temporal_sequence_support",
            "query_roles": ["temporal_sequence_support"],
            "issue_reasons": ["missing_date_or_range"],
            "source_refs": [
                "source_turn_refs:D1:2",
                "source_session_turn_refs:session_2:D2:3",
                "source_turn_refs:D2:3",
            ],
            "source_ref_count": 5,
            "grounding_signals": {
                "source_window": True,
                "session_boundary": True,
                "date_or_range": False,
            },
        }
    ]
    serialized = json.dumps(summary)
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized
    assert long_exact_ref not in serialized
    assert "888888888888888888888888888888888888888888888888888888888888" not in (
        serialized
    )
    assert "999999999999999999999999999999999999999999999999999999999999" not in (
        serialized
    )


def test_fast_gate_actionable_summary_reports_rerank_selection_conflicts() -> None:
    long_value = "x" * 200
    retrieval = _retrieval_payload(
        evidence_need=("single_fact",),
        policy_score=0.0,
    )
    retrieval["results"] = [
        _rerank_candidate_payload(
            item_id=f"unselected-positive-{long_value}",
            rank=1,
            score=0.91,
            policy_score=0.12,
            score_signals={
                f"benchmark_signal_{index}_{long_value}": index / 100
                for index in range(1, 7)
            }
            | {"benchmark_effective_boost_cap": 0.16},
            candidate_features={
                "answerability_score": 0.88,
                "source_locality_score": 0.81,
                "source_type": "raw_turn",
                "query_roles": tuple(
                    f"role-{index}-{long_value}" for index in range(1, 7)
                ),
                "relation_category_hits": ("preference",),
            },
        ),
        _rerank_candidate_payload(
            item_id="selected-weak",
            rank=2,
            score=0.74,
            policy_score=0.0,
            score_signals={"benchmark_rank_penalty": -0.04},
            candidate_features={
                "answerability_score": 0.9,
                "source_locality_score": 0.9,
            },
        ),
    ]
    item = _item(
        case_id="rerank-action-gap",
        evidence_bundle={
            "bundle_complete": True,
            "evidence_term_count": 1,
            "covered_evidence_terms": ["D1:1"],
            "items": [
                {
                    "id": "selected-weak",
                    "role": "supporting",
                    "retrieval_order": 1,
                    "covered_evidence_terms": ["D1:1"],
                    "focused_evidence_score": 1.0,
                    "source_refs": ["D1:1"],
                    "answerability_score": 0.9,
                    "source_locality_score": 0.9,
                    "query_roles": ["supporting"],
                    "planner_reason_codes": ["fallback_selection"],
                }
            ],
        },
        retrieval=retrieval,
    )

    gate = fast_gate_metrics((item,), expected_case_count=1)
    summary = gate["actionable_gap_summary"]
    gap = next(
        gap
        for gap in summary["ranked_gaps"]
        if gap["category"] == "rerank_signal_selection"
    )

    assert gap["gap"] == "selection_conflict"
    assert gap["severity"] == "diagnostic"
    assert gap["impact_count"] == 1
    assert gap["source_metric"] == (
        "rerank_signal_gap_breakdown.selection_conflict_case_count"
    )
    assert gap["sample_case_ids"] == ["rerank-action-gap"]
    assert gap["evidence"]["selection_conflict_pair_count"] == 1
    assert len(gap["evidence"]["positive_unselected_signal_counts"]) == 5
    assert gap["evidence"]["selected_without_positive_reason_counts"] == {
        "no_positive_rerank_signal": 1
    }
    samples = gap["samples"]
    assert len(samples) == 1
    assert samples[0] == {
        "case_id": "rerank-action-gap",
        "group": "multi-hop",
        "positive_unselected_candidate_count": 1,
        "selected_without_positive_rerank_count": 1,
        "positive_unselected_signal_counts": {
            "benchmark_effective_boost_cap": 1,
            f"benchmark_signal_1_{long_value[:106]}...": 1,
            f"benchmark_signal_2_{long_value[:106]}...": 1,
            f"benchmark_signal_3_{long_value[:106]}...": 1,
            f"benchmark_signal_4_{long_value[:106]}...": 1,
        },
        "positive_unselected_candidate_ids": [
            f"unselected-positive-{long_value[:105]}..."
        ],
        "selected_without_positive_items": [
            {
                "item_id": "selected-weak",
                "reason": "no_positive_rerank_signal",
                "role": "supporting",
                "matched_retrieval_candidate": True,
            }
        ],
    }
    assert len(samples[0]["positive_unselected_signal_counts"]) == 5
    assert len(samples[0]["positive_unselected_candidate_ids"][0]) <= 128


def test_actionable_gap_summary_uses_stable_tie_breaks_and_gap_schema() -> None:
    summary = actionable_gap_summary(
        evaluation_count=4,
        expected_case_count=4,
        failed_gates=("query_plan_evidence_roles_clear",),
        query_overlap_count=1,
        profile_overlap_count=0,
        intent_overlap_count=0,
        ref_gate={},
        bundle_quality_failure_breakdown={},
        bundle_gap_breakdown={},
        answerability_gap_breakdown={},
        selected_evidence_weakness={},
        query_role_gap_breakdown={
            "role_family_gaps": {
                "temporal_support": {
                    "candidate_count": 1,
                    "selected_item_count": 0,
                    "gap_reasons": ["not_selected"],
                }
            }
        },
        query_plan_gap_breakdown={
            "missing_evidence_role_query_family_counts": {
                "favorite_support": 1,
                "temporal_support": 1,
            },
            "gap_reason_counts": {"missing_evidence_role_query_family": 1},
            "samples": [
                {
                    "case_id": "case-plan",
                    "missing_evidence_role_query_families": ("favorite_support",),
                }
            ],
        },
        source_ref_provenance={},
    )

    ranked_gaps = summary["ranked_gaps"]

    assert summary["blocking_gap_count"] == 3
    assert summary["diagnostic_gap_count"] == 2
    assert [(gap["severity"], gap["category"], gap["gap"]) for gap in ranked_gaps] == [
        ("blocking", "query_plan", "favorite_support"),
        ("blocking", "query_plan", "missing_evidence_role_query_family"),
        ("blocking", "query_plan", "temporal_support"),
        ("diagnostic", "query_leakage", "expected_answer_query_overlap"),
        ("diagnostic", "query_role_family", "temporal_support"),
    ]
    assert ranked_gaps[0]["sample_case_ids"] == ["case-plan"]
    diagnostic_gap = ranked_gaps[-1]
    assert diagnostic_gap["failed_gate"] == ""
    assert diagnostic_gap["sample_case_ids"] == []
    assert diagnostic_gap["evidence"] == {"gap_reasons": ["not_selected"]}


def test_actionable_gap_summary_caps_ranked_gaps_and_sample_case_ids() -> None:
    samples = [
        {"case_id": f"case-{index}", "reasons": ["selected_low_answerability"]}
        for index in range(1, 8)
    ]
    summary = actionable_gap_summary(
        evaluation_count=20,
        expected_case_count=20,
        failed_gates=("selected_low_answerability_clear",),
        query_overlap_count=0,
        profile_overlap_count=0,
        intent_overlap_count=0,
        ref_gate={},
        bundle_quality_failure_breakdown={},
        bundle_gap_breakdown={},
        answerability_gap_breakdown={},
        selected_evidence_weakness={
            "reason_counts": {
                f"selected_gap_{index:02d}": 1 for index in range(12)
            }
            | {"selected_low_answerability": 7},
            "low_answerability_item_count": 7,
            "samples": samples,
        },
        query_role_gap_breakdown={},
        query_plan_gap_breakdown={},
        source_ref_provenance={},
    )

    ranked_gaps = summary["ranked_gaps"]

    assert summary["gap_count"] == 13
    assert len(ranked_gaps) == 10
    assert ranked_gaps[0]["gap"] == "selected_low_answerability"
    assert ranked_gaps[0]["sample_case_ids"] == [
        "case-1",
        "case-2",
        "case-3",
        "case-4",
        "case-5",
    ]


def test_actionable_gap_summary_caps_non_query_plan_sample_case_id_text() -> None:
    long_case_id = f"case-{'x' * 200}"
    summary = actionable_gap_summary(
        evaluation_count=1,
        expected_case_count=1,
        failed_gates=("selected_low_answerability_clear",),
        query_overlap_count=0,
        profile_overlap_count=0,
        intent_overlap_count=0,
        selected_evidence_weakness={
            "reason_counts": {"selected_low_answerability": 1},
            "samples": [
                {
                    "case_id": long_case_id,
                    "reasons": ["selected_low_answerability"],
                }
            ],
        },
    )

    top_gap = summary["top_gap"]
    assert isinstance(top_gap, dict)
    assert top_gap["sample_case_ids"] == [long_case_id[:125] + "..."]


def test_actionable_gap_summary_includes_selected_weakness_sample_payloads() -> None:
    long_value = "x" * 200
    summary = actionable_gap_summary(
        evaluation_count=2,
        expected_case_count=2,
        failed_gates=("selected_low_answerability_clear",),
        query_overlap_count=0,
        profile_overlap_count=0,
        intent_overlap_count=0,
        selected_evidence_weakness={
            "reason_counts": {
                "selected_low_answerability": 2,
                "selected_weak_source_locality": 1,
            },
            "samples": [
                {
                    "case_id": "weak-answerability",
                    "group": "open-domain",
                    "item_id": "candidate-1",
                    "role": "supporting",
                    "reasons": [
                        "selected_low_answerability",
                        "selected_weak_source_locality",
                    ],
                    "risk_reason_codes": ["risk:low_answerability"],
                    "query_roles": ["original_question", f"role-{long_value}"],
                    "source_refs": ["D1:1", f"D1:{long_value}"],
                    "retrieval_order": 4,
                    "source_ref_count": 2,
                    "answerability_score": 0.1234567,
                    "source_locality_score": 0.35,
                    "broad_summary": False,
                    "unlisted_field": "excluded",
                },
                {
                    "case_id": "weak-answerability-2",
                    "reasons": ["selected_low_answerability"],
                    "source_refs": ["D2:1"],
                },
            ],
        },
    )

    selected_gap = next(
        gap
        for gap in summary["ranked_gaps"]
        if gap["gap"] == "selected_low_answerability"
    )
    locality_gap = next(
        gap
        for gap in summary["ranked_gaps"]
        if gap["gap"] == "selected_weak_source_locality"
    )

    assert selected_gap["samples"][0] == {
        "case_id": "weak-answerability",
        "group": "open-domain",
        "item_id": "candidate-1",
        "role": "supporting",
        "reasons": [
            "selected_low_answerability",
            "selected_weak_source_locality",
        ],
        "risk_reason_codes": ["risk:low_answerability"],
        "query_roles": ["original_question", f"role-{long_value[:120]}..."],
        "source_refs": ["D1:1"],
        "retrieval_order": 4,
        "source_ref_count": 2,
        "answerability_score": 0.123457,
        "source_locality_score": 0.35,
    }
    assert "unlisted_field" not in selected_gap["samples"][0]
    assert selected_gap["samples"][1]["case_id"] == "weak-answerability-2"
    assert locality_gap["samples"] == [selected_gap["samples"][0]]
    assert f"D1:{long_value[:122]}..." not in json.dumps(summary)


def test_actionable_selected_evidence_samples_filter_unsafe_source_refs() -> None:
    long_ref = f"D3:{'7' * 120}"
    summary = actionable_gap_summary(
        evaluation_count=1,
        expected_case_count=1,
        failed_gates=("selected_low_answerability_clear",),
        query_overlap_count=0,
        profile_overlap_count=0,
        intent_overlap_count=0,
        selected_evidence_weakness={
            "reason_counts": {"selected_low_answerability": 1},
            "samples": [
                {
                    "case_id": "unsafe-selected-source",
                    "group": "multi-hop",
                    "item_id": "selected-evidence",
                    "role": "supporting",
                    "reasons": ["selected_low_answerability"],
                    "source_refs": [
                        "source_turn_refs:D1:2",
                        "locomo:conv-private:session_2:D2:3:turn-secret",
                        "provider-private-payload",
                        long_ref,
                    ],
                    "source_ref_count": 4,
                    "answerability_score": 0.2,
                }
            ],
        },
    )

    gap = summary["top_gap"]

    assert isinstance(gap, dict)
    assert gap["samples"] == [
        {
            "case_id": "unsafe-selected-source",
            "group": "multi-hop",
            "item_id": "selected-evidence",
            "role": "supporting",
            "reasons": ["selected_low_answerability"],
            "source_refs": [
                "source_turn_refs:D1:2",
                "source_session_turn_refs:session_2:D2:3",
                "source_turn_refs:D2:3",
            ],
            "source_ref_count": 4,
            "answerability_score": 0.2,
        }
    ]
    serialized = json.dumps(summary)
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized
    assert "provider-private-payload" not in serialized
    assert long_ref not in serialized


def test_actionable_gap_summary_caps_query_plan_actionable_samples() -> None:
    long_text = "x" * 200
    samples = [
        {
            "case_id": f"case-{index}-{long_text}",
            "group": f"group-{long_text}",
            "gap_reasons": ("missing_evidence_role_query_family",),
            "missing_evidence_role_query_families": ("favorite_support",),
            "selected_role_families": tuple(
                f"family-{family_index}-{long_text}" for family_index in range(7)
            ),
            "required_evidence_roles": (
                "primary",
                "favorite_support",
                f"oversized-{long_text}",
            ),
            "selected_query_count": index,
        }
        for index in range(1, 8)
    ]
    summary = actionable_gap_summary(
        evaluation_count=7,
        expected_case_count=7,
        failed_gates=("query_plan_evidence_roles_clear",),
        query_overlap_count=0,
        profile_overlap_count=0,
        intent_overlap_count=0,
        ref_gate={},
        bundle_quality_failure_breakdown={},
        bundle_gap_breakdown={},
        answerability_gap_breakdown={},
        selected_evidence_weakness={},
        query_role_gap_breakdown={},
        query_plan_gap_breakdown={
            "missing_evidence_role_query_family_counts": {"favorite_support": 7},
            "gap_reason_counts": {"missing_evidence_role_query_family": 7},
            "missing_evidence_role_query_family_details": {
                "favorite_support": {
                    "accepted_query_families": (
                        "relation_compact",
                        "expanded_focus",
                    )
                }
            },
            "samples": samples,
        },
        source_ref_provenance={},
    )

    role_gap = next(
        gap
        for gap in summary["ranked_gaps"]
        if gap["source_metric"]
        == (
            "query_plan_gap_breakdown."
            "missing_evidence_role_query_family_counts"
        )
    )

    assert len(role_gap["sample_case_ids"]) == 5
    assert all(len(case_id) <= 128 for case_id in role_gap["sample_case_ids"])
    assert len(role_gap["samples"]) == 3
    assert role_gap["samples"][0]["case_id"].endswith("...")
    assert role_gap["samples"][0]["group"].endswith("...")
    assert len(role_gap["samples"][0]["selected_role_families"]) == 5
    assert all(
        len(value) <= 128
        for value in role_gap["samples"][0]["selected_role_families"]
    )


def test_actionable_gap_summary_matches_query_plan_samples_before_compaction() -> None:
    long_suffix = "x" * 200
    first_family = f"first_support_{long_suffix}"
    second_family = f"second_support_{long_suffix}"
    samples = [
        {
            "case_id": "first-case",
            "gap_reasons": ("missing_evidence_role_query_family",),
            "missing_evidence_role_query_families": (first_family,),
            "selected_role_families": ("base_query",),
        },
        {
            "case_id": "second-case",
            "gap_reasons": ("missing_evidence_role_query_family",),
            "missing_evidence_role_query_families": (second_family,),
            "selected_role_families": ("base_query",),
        },
    ]
    compact_samples = [
        {
            "case_id": sample["case_id"],
            "gap_reasons": sample["gap_reasons"],
            "missing_evidence_role_query_families": (
                str(sample["missing_evidence_role_query_families"][0])[:125] + "...",
            ),
            "selected_role_families": sample["selected_role_families"],
        }
        for sample in samples
    ]

    summary = actionable_gap_summary(
        evaluation_count=2,
        expected_case_count=2,
        failed_gates=("query_plan_evidence_roles_clear",),
        query_overlap_count=0,
        profile_overlap_count=0,
        intent_overlap_count=0,
        query_plan_gap_breakdown={
            "missing_evidence_role_query_family_counts": {
                first_family: 1,
                second_family: 1,
            },
            "gap_reason_counts": {},
            "compact_samples": compact_samples,
            "samples": samples,
        },
    )

    second_gap = next(
        gap for gap in summary["ranked_gaps"] if gap["gap"] == second_family
    )

    assert second_gap["sample_case_ids"] == ["second-case"]
    assert second_gap["samples"] == [
        {
            "case_id": "second-case",
            "gap_reasons": ["missing_evidence_role_query_family"],
            "missing_evidence_role_query_families": [second_family[:125] + "..."],
            "selected_role_families": ["base_query"],
        }
    ]
