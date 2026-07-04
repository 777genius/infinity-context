from __future__ import annotations

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
