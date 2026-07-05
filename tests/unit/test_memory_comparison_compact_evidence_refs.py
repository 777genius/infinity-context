from __future__ import annotations

from infinity_context_server import memory_comparison_benchmark as benchmark


def test_compact_evidence_bundle_coverage_surfaces_bounded_evidence_refs() -> None:
    coverage = benchmark._compact_evidence_bundle_coverage(
        (
            {
                "case_id": "conv-1:qa:missing-bridge",
                "group": "multi-hop",
                "retrieval_quality": {
                    "covered_evidence_terms": ["D1:1"],
                    "missing_evidence_terms": ["D2:3"],
                    "missing_terms": ["red folder"],
                },
                "evidence_bundle": {
                    "bundle_complete": False,
                    "item_count": 1,
                    "evidence_term_recall": 0.5,
                    "covered_evidence_terms": ["D1:1"],
                },
            },
        )
    )

    sample = coverage["incomplete_samples"][0]

    assert sample["case_id"] == "conv-1:qa:missing-bridge"
    assert sample["evidence_refs"] == ["D1:1", "D2:3"]
    assert sample["covered_evidence_refs"] == ["D1:1"]
    assert sample["missing_evidence_refs"] == ["D2:3"]
    assert sample["missing_evidence_terms"] == ["D2:3"]
    assert sample["missing_expected_terms"] == ["red folder"]


def test_compact_evidence_bundle_coverage_bounds_evidence_refs() -> None:
    refs = [f"D1:{index}" for index in range(1, 14)]
    coverage = benchmark._compact_evidence_bundle_coverage(
        (
            {
                "case_id": "conv-1:qa:bounded",
                "group": "multi-hop",
                "retrieval_quality": {
                    "covered_evidence_terms": refs[:7],
                    "missing_evidence_terms": refs[7:],
                },
                "evidence_bundle": {
                    "bundle_complete": False,
                    "item_count": 1,
                    "evidence_term_recall": 0.0,
                },
            },
        )
    )

    sample = coverage["incomplete_samples"][0]

    assert sample["evidence_refs"] == refs[:8]
    assert sample["covered_evidence_refs"] == refs[:7]
    assert sample["missing_evidence_refs"] == refs[7:]
