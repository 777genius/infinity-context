from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from mem0_oss_adapter.models import RunUsageEvidence
from mem0_oss_adapter.usage import (
    FIXED_EXTRACTION_MODEL,
    RunUsageAggregate,
    UsageEvidenceError,
)


def _raw_usage() -> RunUsageAggregate:
    return RunUsageAggregate(
        mode="raw_passthrough",
        operation_count=1,
        extraction_calls=0,
        request_bytes=0,
        response_bytes=0,
        model=FIXED_EXTRACTION_MODEL,
        first_operation_at="2026-08-04T12:34:56.123Z",
        last_operation_at="2026-08-04T12:34:56.123Z",
    )


def test_usage_aggregate_exposes_only_the_exact_sanitized_schema() -> None:
    usage = _raw_usage()

    assert RunUsageEvidence.model_validate(usage.as_dict()).model_dump() == usage.as_dict()
    assert set(usage.as_dict()) == {
        "mode",
        "operation_count",
        "extraction_calls",
        "request_bytes",
        "response_bytes",
        "model",
        "first_operation_at",
        "last_operation_at",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("operation_count", True),
        ("operation_count", 10_001),
        ("extraction_calls", 1),
        ("request_bytes", 1),
        ("response_bytes", 1_048_577),
        ("model", "other-model"),
        ("first_operation_at", "2026-08-04T12:34:56Z"),
        ("last_operation_at", "2026-08-04T12:34:55.123Z"),
    ),
)
def test_usage_aggregate_fails_closed_on_invalid_or_leaky_shape(
    field: str,
    value: object,
) -> None:
    with pytest.raises(UsageEvidenceError):
        replace(_raw_usage(), **{field: value})


def test_http_usage_schema_rejects_unknown_fields_and_non_strict_counts() -> None:
    payload = _raw_usage().as_dict()

    with pytest.raises(ValidationError):
        RunUsageEvidence.model_validate({**payload, "prompt": "secret"})
    with pytest.raises(ValidationError):
        RunUsageEvidence.model_validate({**payload, "operation_count": True})


def test_raw_usage_accepts_the_fixed_operation_bound_but_subscription_stays_single() -> None:
    raw = replace(_raw_usage(), operation_count=10_000)
    subscription = RunUsageAggregate(
        mode="subscription_llm",
        operation_count=1,
        extraction_calls=1,
        request_bytes=1,
        response_bytes=0,
        model=FIXED_EXTRACTION_MODEL,
        first_operation_at="2026-08-04T12:34:56.123Z",
        last_operation_at="2026-08-04T12:34:56.123Z",
    )

    assert raw.operation_count == 10_000
    assert RunUsageEvidence.model_validate(raw.as_dict()).operation_count == 10_000
    with pytest.raises(UsageEvidenceError, match="one isolated"):
        replace(subscription, operation_count=2)
    with pytest.raises(ValidationError, match="one isolated"):
        RunUsageEvidence.model_validate({**subscription.as_dict(), "operation_count": 2})
