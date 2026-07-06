from __future__ import annotations

from infinity_context_server.memory_comparison_quality_actionable_gaps import (
    actionable_gap_summary,
)


def test_actionable_gap_summary_reports_required_query_role_coverage_gaps() -> None:
    summary = actionable_gap_summary(
        evaluation_count=5,
        expected_case_count=5,
        failed_gates=(),
        query_overlap_count=0,
        profile_overlap_count=0,
        intent_overlap_count=0,
        query_role_gap_breakdown={
            "required_role_coverage_gap_counts": {
                "candidate_query": 2,
                "selected_evidence_query": 1,
            },
            "required_role_coverage_gap_samples": [
                {
                    "case_id": "temporal-gap",
                    "group": "temporal",
                    "required_role": "relative_temporal_support",
                    "gap_reasons": ["candidate_query", "selected_evidence_query"],
                    "required_query_family": "temporal_support",
                    "required_selected_query_families": [
                        "temporal_support",
                        "expanded_focus",
                    ],
                    "candidate_query_role_families": ["base_query"],
                    "selected_query_role_families": ["base_query"],
                    "selected_evidence_query_role_families": [],
                },
                {
                    "case_id": "location-gap",
                    "group": "multi-hop",
                    "required_role": "location_support",
                    "gap_reasons": ["candidate_query"],
                    "required_query_family": "location_support",
                    "required_selected_query_families": [
                        "location_support",
                        "relation_compact",
                    ],
                    "candidate_query_role_families": ["base_query"],
                    "selected_query_role_families": ["base_query"],
                    "selected_evidence_query_role_families": [],
                },
            ],
        },
    )

    ranked_gaps = summary["ranked_gaps"]
    candidate_gap = ranked_gaps[0]
    selected_evidence_gap = next(
        gap for gap in ranked_gaps if gap["gap"] == "selected_evidence_query"
    )

    assert candidate_gap["category"] == "query_role_coverage"
    assert candidate_gap["gap"] == "candidate_query"
    assert candidate_gap["severity"] == "diagnostic"
    assert candidate_gap["impact_count"] == 2
    assert candidate_gap["source_metric"] == (
        "query_role_gap_breakdown.required_role_coverage_gap_counts"
    )
    assert candidate_gap["action"] == (
        "Add candidate query families for required evidence roles before rerank "
        "and bundle selection."
    )
    assert candidate_gap["sample_case_ids"] == ["temporal-gap", "location-gap"]
    assert candidate_gap["evidence"] == {
        "required_roles": ["relative_temporal_support", "location_support"]
    }
    assert candidate_gap["samples"][0] == {
        "case_id": "temporal-gap",
        "group": "temporal",
        "required_role": "relative_temporal_support",
        "required_query_family": "temporal_support",
        "gap_reasons": ["candidate_query", "selected_evidence_query"],
        "required_selected_query_families": [
            "temporal_support",
            "expanded_focus",
        ],
        "candidate_query_role_families": ["base_query"],
        "selected_query_role_families": ["base_query"],
    }
    assert selected_evidence_gap["sample_case_ids"] == ["temporal-gap"]
    assert selected_evidence_gap["evidence"] == {
        "required_roles": ["relative_temporal_support"]
    }


def test_actionable_gap_summary_ignores_zero_required_role_coverage_counts() -> None:
    summary = actionable_gap_summary(
        evaluation_count=1,
        expected_case_count=1,
        failed_gates=(),
        query_overlap_count=0,
        profile_overlap_count=0,
        intent_overlap_count=0,
        query_role_gap_breakdown={
            "required_role_coverage_gap_counts": {"selected_query": 0},
            "required_role_coverage_gap_samples": [
                {
                    "case_id": "covered",
                    "required_role": "temporal_support",
                    "gap_reasons": ["selected_query"],
                }
            ],
        },
    )

    assert summary["ranked_gaps"] == []
