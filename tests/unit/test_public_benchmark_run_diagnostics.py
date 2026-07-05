from __future__ import annotations

from infinity_context_server.public_benchmark import PublicBenchmarkCase
from infinity_context_server.public_benchmark_run_diagnostics import (
    bounded_case_id_details,
    bounded_checkpoint_failure_case_id_details,
    public_request_artifact_fields,
)


def test_public_benchmark_resume_case_id_details_redact_sensitive_tokens() -> None:
    bearer_payload = "Bearer " + ("a" * 16)
    cases = (
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="conv-26:qa:70",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
        ),
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id=f"resume-detail {bearer_payload}",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
        ),
    )

    case_ids, truncated_count = bounded_case_id_details(cases)
    checkpoint_case_ids, checkpoint_truncated_count = (
        bounded_checkpoint_failure_case_id_details(
            ({"case_id": f"resume-failed {bearer_payload}"},)
        )
    )

    assert case_ids == ["locomo:conv-26:qa:70", "locomo:resume-detail [redacted]"]
    assert truncated_count == 0
    assert checkpoint_case_ids == ["resume-failed [redacted]"]
    assert checkpoint_truncated_count == 0


def test_public_benchmark_request_fields_preserve_safe_nested_diagnostics() -> None:
    bearer_payload = "Bearer " + ("a" * 16)

    fields = public_request_artifact_fields(
        case_selection={
            "unsupported_case_id_reasons": [
                {
                    "case_id": f"locomo:conv-no-evidence-mini:qa:1 {bearer_payload}",
                    "reason": "official_locomo.no_retrieval_terms",
                }
            ],
        },
        requested_case_ids=(f"locomo:conv-no-evidence-mini:qa:1 {bearer_payload}",),
        requested_capabilities=(),
    )

    assert fields["requested_case_ids"] == [
        "locomo:conv-no-evidence-mini:qa:1 [redacted]"
    ]
    assert fields["case_selection"]["unsupported_case_id_reasons"] == [
        {
            "case_id": "locomo:conv-no-evidence-mini:qa:1 [redacted]",
            "reason": "official_locomo.no_retrieval_terms",
        }
    ]


def test_public_benchmark_request_fields_bound_requested_lists() -> None:
    requested_case_ids = tuple(f"locomo:conv-26:qa:{index}" for index in range(25))
    requested_capabilities = tuple(f"locomo:capability:{index}" for index in range(22))

    fields = public_request_artifact_fields(
        case_selection={},
        requested_case_ids=requested_case_ids,
        requested_capabilities=requested_capabilities,
    )

    assert fields["requested_case_id_count"] == 25
    assert fields["requested_case_id_truncated_count"] == 5
    assert fields["requested_case_ids"] == list(requested_case_ids[:20])
    assert fields["requested_capability_count"] == 22
    assert fields["requested_capability_truncated_count"] == 2
    assert fields["requested_capabilities"] == list(requested_capabilities[:20])
