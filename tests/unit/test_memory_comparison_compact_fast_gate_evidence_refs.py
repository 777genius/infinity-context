from __future__ import annotations

import json

from infinity_context_server.memory_comparison_benchmark import (
    _compact_fast_gate_summary,
    _compact_report,
)
from infinity_context_server.memory_comparison_compact_gap_report import (
    compact_evidence_bundle_gap_report,
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


def test_compact_fast_gate_summary_sanitizes_selected_weakness_source_refs() -> None:
    private_refs = [
        f"locomo:conv-private:session_8:D8:{turn}:turn-secret"
        for turn in range(1, 5)
    ]

    summary = _compact_fast_gate_summary(
        (
            _item(
                case_id="selected-weakness-private-refs",
                retrieval_quality={},
                evidence_bundle={
                    "items": [
                        {
                            "id": "weak-selected",
                            "role": "primary",
                            "answerability_score": 0.1,
                            "source_locality_score": 0.1,
                            "source_refs": private_refs,
                            "text": "PRIVATE SELECTED MEMORY TEXT",
                        }
                    ]
                },
                retrieval_results=[],
            ),
        )
    )

    sample = summary["selected_evidence_weakness_samples"]["samples"][0]

    assert sample["source_refs"] == [
        "source_session_turn_refs:session_8:D8:1",
        "source_turn_refs:D8:1",
        "source_session_turn_refs:session_8:D8:2",
        "source_turn_refs:D8:2",
        "source_session_turn_refs:session_8:D8:3",
        "source_turn_refs:D8:3",
    ]
    assert sample["source_ref_count"] == 4
    serialized = json.dumps(summary)
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized
    assert "PRIVATE SELECTED MEMORY TEXT" not in serialized


def test_compact_fast_gate_summary_normalizes_fuzzed_refs_without_provider_leak() -> None:
    raw_private_ref = "LoCoMo:conv-private:SESSION_4:d4:5:TURN-secret"
    invalid_provider_ref = "provider:private-token-abc123"
    raw_long_ref = f"D5:{'9' * 220}"

    summary = _compact_fast_gate_summary(
        (
            _item(
                case_id="fuzzed-source-refs",
                retrieval_quality={
                    "expected_term_recall": 1.0,
                    "evidence_term_recall": 0.0,
                    "covered_evidence_terms": [
                        "",
                        raw_private_ref,
                        "source_turn_refs:d1:2",
                        invalid_provider_ref,
                        raw_private_ref,
                    ],
                    "missing_evidence_terms": [
                        "SOURCE_SESSION_TURN_REFS:SESSION_2:d2:3",
                        raw_long_ref,
                        invalid_provider_ref,
                    ],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "items": [
                        {
                            "id": "weak-selected",
                            "role": "primary",
                            "answerability_score": 0.1,
                            "source_locality_score": 0.1,
                            "source_refs": [
                                "",
                                "source_turn_refs:d1:2",
                                "SOURCE_SESSION_TURN_REFS:SESSION_1:d1:3",
                                raw_private_ref,
                                invalid_provider_ref,
                                f"source_turn_refs:D1:{'9' * 90}",
                                "source_turn_refs:D1:2",
                            ],
                        }
                    ],
                },
                retrieval_results=[],
            ),
        )
    )

    weakness_sample = summary["selected_evidence_weakness_samples"]["samples"][0]

    assert weakness_sample["source_refs"] == [
        "source_session_turn_refs:session_1:D1:3",
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D1:2",
    ]

    serialized = json.dumps(summary)
    assert "locomo:conv-private" not in serialized.lower()
    assert "turn-secret" not in serialized.lower()
    assert invalid_provider_ref not in serialized
    assert raw_long_ref not in serialized


def test_compact_gap_report_normalizes_locality_window_private_refs() -> None:
    raw_ref = "locomo:conv-private:session_2:D2:3:turn-secret"
    raw_nearest_ref = "locomo:conv-private:session_2:D2:2:turn-secret"
    report = compact_evidence_bundle_gap_report(
        {
            "schema_version": "evidence_bundle_gap_report.v1",
            "status": "gaps_found",
            "evaluation_count": 1,
            "incomplete_case_count": 1,
            "top_coverage_gaps": [
                {
                    "reason": "missing_evidence_refs",
                    "count": 1,
                    "case_rate": 1.0,
                    "sample_case_ids": ["case-private-ref"],
                    "source_window_locality_samples": [
                        {
                            "case_id": "case-private-ref",
                            "missing_turn_ref_count": 1,
                            "same_source_missing_count": 1,
                            "near_retrieved_window_count": 1,
                            "source_absent_count": 0,
                            "missing_ref_windows": [
                                {
                                    "ref": raw_ref,
                                    "source_id": raw_ref,
                                    "retrieved_same_source": True,
                                    "bundle_same_source": False,
                                    "nearest_retrieved_turn_ref": raw_nearest_ref,
                                    "nearest_retrieved_turn_distance": 1,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )

    window = report["top_coverage_gaps"][0]["source_window_locality_samples"][0][
        "missing_ref_windows"
    ][0]

    assert window["ref"] == "session_2:D2:3"
    assert window["source_id"] == "session_2:D2"
    assert window["nearest_retrieved_turn_ref"] == "session_2:D2:2"
    serialized = json.dumps(report)
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized


def test_compact_gap_report_redacts_raw_payload_text_fields() -> None:
    raw_payload = "provider_payload private-token-abc raw_provider body"
    report = compact_evidence_bundle_gap_report(
        {
            "schema_version": "evidence_bundle_gap_report.v1",
            "status": "gaps_found",
            "evaluation_count": 1,
            "incomplete_case_count": 1,
            "top_action": raw_payload,
            "top_coverage_gaps": [
                {
                    "reason": raw_payload,
                    "count": 1,
                    "case_rate": 1.0,
                    "action": raw_payload,
                    "sample_case_ids": [raw_payload],
                }
            ],
            "weak_provenance_signals": [
                {
                    "name": raw_payload,
                    "count": 1,
                    "rate": 1.0,
                    "action": raw_payload,
                    "sample_case_ids": [raw_payload],
                }
            ],
        }
    )

    serialized = json.dumps(report)

    assert "provider_payload" not in serialized
    assert "private-token" not in serialized
    assert "raw_provider" not in serialized
    assert "[redacted]" in serialized


def test_compact_report_sanitizes_failure_payloads_private_ids_and_refs() -> None:
    raw_locomo_ref = "locomo:conv-private:session_2:D2:3:turn-secret"
    raw_nearest_ref = "locomo:conv-private:session_2:D2:2:turn-secret"
    raw_provider_payload = "provider_payload private-token-abc raw_provider body"
    private_item_id = "provider:private-token-item-123"
    oversized_ref = f"D9:{'7' * 220}"

    compact = _compact_report(
        {
            "schema_version": "memory-comparison-benchmark-v1",
            "suite": "memory-comparison-benchmark",
            "source_suite": "public-memory-benchmark",
            "status": "failed",
            "ok": False,
            "evaluations": [],
            "metadata": {"raw_provider_payload": raw_provider_payload},
            "metrics": {},
            "backend_metrics": {},
            "backend_comparison": {},
            "failure_analysis": [
                {
                    "case_id": "failure-safety",
                    "backend": "memo-stack",
                    "group": "single-hop",
                    "reason": raw_provider_payload,
                    "diagnostic_reason_codes": ["missing_evidence_refs"],
                    "diagnostics": {
                        "item_id": private_item_id,
                        "item_ids": [private_item_id, "safe-item"],
                        "source_refs": [raw_locomo_ref, oversized_ref],
                        "provider_payload": {"raw": raw_provider_payload},
                        "missing_evidence_source_locality": {
                            "missing_turn_ref_count": 1,
                            "same_source_missing_count": 1,
                            "near_retrieved_window_count": 1,
                            "source_absent_count": 0,
                            "missing_ref_windows": [
                                {
                                    "ref": raw_locomo_ref,
                                    "source_id": raw_locomo_ref,
                                    "retrieved_same_source": True,
                                    "bundle_same_source": False,
                                    "nearest_retrieved_turn_ref": raw_nearest_ref,
                                    "nearest_bundle_turn_ref": oversized_ref,
                                    "nearest_retrieved_turn_distance": 1,
                                    "nearest_bundle_turn_distance": 2,
                                }
                            ],
                        },
                    },
                }
            ],
            "failures": [],
            "elapsed_ms": 1.0,
        },
        failure_limit=5,
    )

    serialized = json.dumps(compact, sort_keys=True)

    assert "locomo:conv-private" not in serialized.lower()
    assert "turn-secret" not in serialized.lower()
    assert "provider_payload" not in serialized
    assert "private-token" not in serialized
    assert private_item_id not in serialized
    assert oversized_ref not in serialized
    assert "safe-item" in serialized
    provenance = compact["diagnostics"]["failure_provenance_summary"]
    sample_window = provenance["missing_evidence_source_locality"]["sample_windows"][0]
    assert "session_2" in sample_window["ref"]


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
