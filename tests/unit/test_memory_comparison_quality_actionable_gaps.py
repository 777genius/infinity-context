from __future__ import annotations

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
