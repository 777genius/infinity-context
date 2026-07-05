from __future__ import annotations

import json

from infinity_context_server.memory_comparison_benchmark import (
    _compact_fast_gate_summary,
)


def test_compact_fast_gate_summary_surfaces_evidence_ref_gap_report_safely() -> None:
    summary = _compact_fast_gate_summary(
        tuple(
            _item(
                case_id=f"locomo-window-gap-{index}",
                retrieval_quality={
                    "expected_term_recall": 1.0,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D1:9", "D1:10", "D1:11", "D1:12"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.0,
                    "items": [
                        {
                            "id": f"selected-{index}",
                            "role": "primary",
                            "focused_evidence_score": 0.0,
                            "source_refs": ["D1:7"],
                            "text": "PRIVATE SELECTED MEMORY TEXT",
                        }
                    ],
                },
                retrieval_results=[
                    {
                        "id": f"retrieved-{index}",
                        "source_refs": ["D1:8"],
                        "text": "PRIVATE RETRIEVED MEMORY TEXT",
                        "provider_payload": {"raw": "PRIVATE PROVIDER PAYLOAD"},
                    }
                ],
            )
            for index in range(6)
        )
    )

    report = summary["evidence_bundle_gap_report"]
    missing_ref_gap = next(
        gap
        for gap in report["top_coverage_gaps"]
        if gap["reason"] == "missing_evidence_refs"
    )

    assert report["schema_version"] == "evidence_bundle_gap_report.v1"
    assert report["status"] == "gaps_found"
    assert report["evaluation_count"] == 6
    assert report["incomplete_case_count"] == 6
    assert missing_ref_gap["count"] == 6
    assert missing_ref_gap["sample_case_ids"] == [
        "locomo-window-gap-0",
        "locomo-window-gap-1",
        "locomo-window-gap-2",
        "locomo-window-gap-3",
        "locomo-window-gap-4",
    ]
    assert len(missing_ref_gap["source_window_locality_samples"]) == 5
    assert all(
        len(sample["missing_ref_windows"]) <= 3
        for sample in missing_ref_gap["source_window_locality_samples"]
    )
    assert summary["top_gap"]["gap"] == "missing_evidence_refs"
    assert summary["top_gap"]["source_metric"] == "bundle_gap_breakdown.reason_counts"
    assert "samples" not in summary["top_gap"]
    assert "evidence" not in summary["top_gap"]

    serialized = json.dumps(summary)
    assert "PRIVATE RETRIEVED MEMORY TEXT" not in serialized
    assert "PRIVATE SELECTED MEMORY TEXT" not in serialized
    assert "PRIVATE PROVIDER PAYLOAD" not in serialized


def _item(
    *,
    case_id: str,
    retrieval_quality: dict[str, object],
    evidence_bundle: dict[str, object],
    retrieval_results: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "backend": "memo-stack",
        "group": "single-hop",
        "scored": True,
        "judgment": {"score": 1.0},
        "retrieval_quality": retrieval_quality,
        "evidence_bundle": evidence_bundle,
        "retrieval": {"metadata": {}, "results": retrieval_results},
        "cutoff_results": {},
    }
