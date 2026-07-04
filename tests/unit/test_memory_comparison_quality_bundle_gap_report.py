from __future__ import annotations

from infinity_context_server.memory_comparison_quality_diagnostics import (
    fast_gate_metrics,
    quality_diagnostics,
)


def test_fast_gate_metrics_compacts_bundle_coverage_and_provenance_gaps() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="locomo-gap",
                retrieval_quality={"missing_evidence_terms": ["D7:5"]},
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.0,
                    "items": [
                        {
                            "id": "selected-1",
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 0.0,
                        }
                    ],
                },
                cutoff_results={
                    "3": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 1,
                            "source_ref_count": 0,
                            "source_ref_item_count": 0,
                            "source_refless_item_count": 1,
                        }
                    }
                },
            ),
        ),
        expected_case_count=1,
    )

    report = gate["evidence_bundle_gap_report"]

    assert report["schema_version"] == "evidence_bundle_gap_report.v1"
    assert report["status"] == "gaps_found"
    assert report["incomplete_case_count"] == 1
    assert {
        (gap["reason"], gap["count"], tuple(gap["sample_case_ids"]))
        for gap in report["top_coverage_gaps"]
    } >= {
        ("missing_evidence_refs", 1, ("locomo-gap",)),
        ("no_focused_evidence", 1, ("locomo-gap",)),
    }
    assert {
        (signal["name"], signal["count"], tuple(signal["sample_case_ids"]))
        for signal in report["weak_provenance_signals"]
    } >= {
        ("selected_bundle_source_refless_items", 1, ("locomo-gap",)),
        ("answer_context_source_refless_items", 1, ("locomo-gap",)),
    }
    assert report["top_action"]


def test_quality_diagnostics_reports_no_observed_bundle_gaps_for_sourced_bundle() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="locomo-complete",
                evidence_bundle={
                    "bundle_complete": True,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 1.0,
                    "items": [
                        {
                            "id": "selected-1",
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "source_refs": ["D1:1"],
                        }
                    ],
                },
            ),
        )
    )

    report = diagnostics["evidence_bundle_gap_report"]

    assert report == {
        "schema_version": "evidence_bundle_gap_report.v1",
        "status": "no_observed_gaps",
        "evaluation_count": 1,
        "incomplete_case_count": 0,
        "coverage_gap_reason_total": 0,
        "coverage_gap_count": 0,
        "weak_provenance_signal_count": 0,
        "top_coverage_gaps": [],
        "weak_provenance_signals": [],
        "top_action": "",
    }


def _item(
    *,
    case_id: str,
    retrieval_quality: dict[str, object] | None = None,
    evidence_bundle: dict[str, object] | None = None,
    cutoff_results: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "group": "single-hop",
        "scored": True,
        "judgment": {"score": 1.0},
        "retrieval_quality": retrieval_quality or {},
        "evidence_bundle": evidence_bundle or {},
        "retrieval": {"metadata": {}, "results": []},
        "cutoff_results": cutoff_results or {},
    }
