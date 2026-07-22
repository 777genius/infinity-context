"""Pure outcome classification policy for public benchmark accounting."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol

CaseOutcome = Literal["success", "semantic_failure", "request_failure"]

_LEGACY_REQUEST_FAILURE_REASONS = frozenset(
    {
        "ConnectError",
        "ConnectTimeout",
        "ConnectionError",
        "HTTPStatusError",
        "NetworkError",
        "PoolTimeout",
        "ReadError",
        "ReadTimeout",
        "RequestError",
        "TimeoutError",
        "WriteError",
        "WriteTimeout",
    }
)


class CaseResult(Protocol):
    ok: bool
    outcome: CaseOutcome


def terminal_outcome(*, ok: bool, has_valid_context_response: bool) -> CaseOutcome:
    """Classify one case into exactly one terminal outcome."""

    if not has_valid_context_response:
        return "request_failure"
    return "success" if ok else "semantic_failure"


def is_request_failure(result: CaseResult) -> bool:
    return result.outcome == "request_failure"


def is_semantic_result(result: CaseResult) -> bool:
    return result.outcome != "request_failure"


def is_semantic_failure(result: CaseResult) -> bool:
    return result.outcome == "semantic_failure"


def outcome_from_checkpoint(
    *,
    status: str,
    case_payload: Mapping[str, object] | None = None,
    failure_report: Mapping[str, object] | None = None,
) -> CaseOutcome:
    """Read new outcome values while safely interpreting legacy checkpoints."""

    case_outcome = _explicit_outcome(case_payload)
    if case_outcome is not None:
        return case_outcome
    report_outcome = _explicit_outcome(failure_report)
    if report_outcome is not None:
        return report_outcome
    case_status = _legacy_status(
        case_payload.get("status", status) if case_payload is not None else status
    )
    if case_status is not None:
        return case_status
    report_status = _legacy_status(
        failure_report.get("status") if failure_report is not None else None
    )
    if report_status is not None:
        return report_status
    evidence_sources = tuple(
        source for source in (case_payload, failure_report) if source is not None
    )
    if any(_has_transport_failure_reason(source) for source in evidence_sources):
        return "request_failure"
    if any(_has_semantic_failure_fields(source) for source in evidence_sources):
        return "semantic_failure"
    return "semantic_failure"


def _explicit_outcome(source: Mapping[str, object] | None) -> CaseOutcome | None:
    if source is None:
        return None
    value = source.get("outcome")
    if value in {"success", "semantic_failure", "request_failure"}:
        return value  # type: ignore[return-value]
    return None


def _legacy_status(value: object) -> CaseOutcome | None:
    if value == "ok":
        return "success"
    if value in {"success", "semantic_failure", "request_failure"}:
        return value  # type: ignore[return-value]
    return None


def _has_semantic_failure_fields(failure_report: Mapping[str, object]) -> bool:
    if failure_report.get("expected_ok") is False:
        return True
    if failure_report.get("forbidden_ok") is False:
        return True
    return any(
        bool(failure_report.get(field))
        for field in ("missing_terms", "leaked_terms", "missing_evidence_refs")
    )


def _has_transport_failure_reason(evidence: Mapping[str, object]) -> bool:
    reason = str(evidence.get("reason") or "").strip()
    return reason in _LEGACY_REQUEST_FAILURE_REASONS
