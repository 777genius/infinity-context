from __future__ import annotations

import json

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


def test_compact_evidence_bundle_coverage_dedupes_evidence_refs() -> None:
    coverage = benchmark._compact_evidence_bundle_coverage(
        (
            {
                "case_id": "conv-1:qa:deduped",
                "group": "multi-hop",
                "retrieval_quality": {
                    "covered_evidence_terms": ["D1:1", "D1:1"],
                    "missing_evidence_terms": ["D2:3", "D2:3", "D1:1"],
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

    assert sample["evidence_refs"] == ["D1:1", "D2:3"]
    assert sample["covered_evidence_refs"] == ["D1:1"]
    assert sample["missing_evidence_refs"] == ["D2:3", "D1:1"]


def test_compact_evidence_bundle_coverage_truncates_long_evidence_refs() -> None:
    raw_covered_ref = f"D1:{'8' * 220}"
    raw_missing_ref = f"D2:{'9' * 220}"
    compact_covered_ref = f"D1:{'8' * 122}..."
    compact_missing_ref = f"D2:{'9' * 122}..."

    coverage = benchmark._compact_evidence_bundle_coverage(
        (
            {
                "case_id": "conv-1:qa:long-ref",
                "group": "multi-hop",
                "retrieval_quality": {
                    "covered_evidence_terms": [raw_covered_ref],
                    "missing_evidence_terms": [raw_missing_ref],
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

    assert sample["evidence_refs"] == [compact_covered_ref, compact_missing_ref]
    assert sample["covered_evidence_refs"] == [compact_covered_ref]
    assert sample["missing_evidence_refs"] == [compact_missing_ref]
    assert sample["missing_evidence_terms"] == [compact_missing_ref]
    serialized = json.dumps(sample)
    assert raw_covered_ref not in serialized
    assert raw_missing_ref not in serialized


def test_compact_evidence_bundle_coverage_normalizes_raw_locomo_refs() -> None:
    raw_covered_ref = "locomo:conv-private:session_1:D1:2:turn-secret"
    raw_missing_ref = "locomo:conv-private:session_2:D2:3:turn-secret"
    coverage = benchmark._compact_evidence_bundle_coverage(
        (
            {
                "case_id": "conv-1:qa:private-ref",
                "group": "multi-hop",
                "retrieval_quality": {
                    "covered_evidence_terms": [raw_covered_ref],
                    "missing_evidence_terms": [raw_missing_ref],
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

    assert sample["evidence_refs"] == ["session_1:D1:2", "session_2:D2:3"]
    assert sample["covered_evidence_refs"] == ["session_1:D1:2"]
    assert sample["missing_evidence_refs"] == ["session_2:D2:3"]
    serialized = json.dumps(sample)
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized



def test_compact_evidence_bundle_coverage_bounds_incomplete_samples() -> None:
    coverage = benchmark._compact_evidence_bundle_coverage(
        tuple(
            {
                "case_id": f"conv-1:qa:incomplete-{index}",
                "group": "multi-hop",
                "retrieval_quality": {
                    "covered_evidence_terms": [f"D1:{index}"],
                    "missing_evidence_terms": [f"D2:{index}"],
                    "missing_terms": [f"expected-{index}"],
                },
                "evidence_bundle": {
                    "bundle_complete": False,
                    "item_count": 1,
                    "evidence_term_recall": 0.0,
                },
            }
            for index in range(8)
        )
    )

    samples = coverage["incomplete_samples"]

    assert coverage["bundle_incomplete_count"] == 8
    assert len(samples) == 5
    assert samples[-1]["case_id"] == "conv-1:qa:incomplete-4"


def test_compact_evidence_bundle_coverage_filters_fuzzed_source_refs() -> None:
    raw_private_ref = "LoCoMo:conv-private:SESSION_4:d4:5:TURN-secret"
    invalid_provider_ref = "provider:private-token-abc123"
    raw_provider_ref = "provider-ref-abc123"
    raw_long_ref = f"D5:{'9' * 220}"
    compact_long_ref = f"D5:{'9' * 122}..."
    coverage = benchmark._compact_evidence_bundle_coverage(
        (
            {
                "case_id": "conv-1:qa:fuzzed-refs",
                "group": "multi-hop",
                "retrieval_quality": {
                    "covered_evidence_terms": [
                        "",
                        raw_private_ref,
                        "source_turn_refs:d1:2",
                        invalid_provider_ref,
                        raw_provider_ref,
                        raw_private_ref,
                    ],
                    "missing_evidence_terms": [
                        "SOURCE_SESSION_TURN_REFS:SESSION_2:d2:3",
                        raw_long_ref,
                        invalid_provider_ref,
                        raw_provider_ref,
                    ],
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

    assert sample["evidence_refs"] == [
        "session_4:D4:5",
        "D1:2",
        "session_2:D2:3",
        compact_long_ref,
    ]
    assert sample["covered_evidence_refs"] == ["session_4:D4:5", "D1:2"]
    assert sample["missing_evidence_refs"] == [
        "session_2:D2:3",
        compact_long_ref,
    ]
    serialized = json.dumps(sample)
    assert "locomo:conv-private" not in serialized.lower()
    assert "turn-secret" not in serialized.lower()
    assert invalid_provider_ref not in serialized
    assert raw_provider_ref not in serialized
    assert raw_long_ref not in serialized


def test_compact_evidence_bundle_coverage_filters_auth_marker_refs() -> None:
    raw_auth_refs = [
        "auth-payload-private-marker",
        "access-token-private-marker",
        "api-key-private-marker",
        "provider-auth-private-marker",
    ]
    coverage = benchmark._compact_evidence_bundle_coverage(
        (
            {
                "case_id": "conv-1:qa:auth-marker-refs",
                "group": "multi-hop",
                "retrieval_quality": {
                    "covered_evidence_terms": raw_auth_refs[:2],
                    "missing_evidence_terms": raw_auth_refs[2:],
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
    serialized = json.dumps(sample)

    assert "evidence_refs" not in sample
    assert sample["missing_evidence_terms"] == []
    for raw_ref in raw_auth_refs:
        assert raw_ref not in serialized


def test_compact_evidence_bundle_coverage_filters_secret_like_evidence_refs() -> None:
    secret_ref = "provider-ref-compact-redacted-1234567890"
    coverage = benchmark._compact_evidence_bundle_coverage(
        (
            {
                "case_id": "conv-1:qa:secret-ref",
                "group": "multi-hop",
                "retrieval_quality": {
                    "covered_evidence_terms": [secret_ref, "D1:2"],
                    "missing_evidence_terms": [secret_ref, "D2:3"],
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
    serialized = json.dumps(sample)

    assert sample["covered_evidence_refs"] == ["D1:2"]
    assert sample["missing_evidence_refs"] == ["D2:3"]
    assert secret_ref not in serialized
    assert "[redacted]" not in serialized


def test_compact_evidence_bundle_coverage_filters_provider_auth_refs() -> None:
    provider_auth_ref = "provider-auth-private-marker"
    coverage = benchmark._compact_evidence_bundle_coverage(
        (
            {
                "case_id": "conv-1:qa:auth-ref-case",
                "group": "multi-hop",
                "retrieval_quality": {
                    "covered_evidence_terms": [provider_auth_ref, "D1:2"],
                    "missing_evidence_terms": [provider_auth_ref, "D2:3"],
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
    serialized = json.dumps(sample)

    assert sample["covered_evidence_refs"] == ["D1:2"]
    assert sample["missing_evidence_refs"] == ["D2:3"]
    assert provider_auth_ref not in serialized
    assert "[redacted]" not in serialized
