from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from infinity_context_server.public_benchmark import _execute_cases, _load_cases
from infinity_context_server.public_benchmark_checkpoint import (
    CaseRunResult,
    _case_run_result_from_payload,
    load_checkpoint_resume_state_with_diagnostics,
    selected_case_fingerprint,
)
from infinity_context_server.public_benchmark_execution import case_error_result
from infinity_context_server.public_benchmark_metrics import (
    benchmark_summaries,
    capability_breakdown,
    case_failures,
    case_payload,
    coverage_summary,
    run_metric_summary,
)
from infinity_context_server.public_benchmark_metrics_policy import outcome_from_checkpoint


@dataclass(frozen=True)
class _Case:
    benchmark: str = "suite"
    case_id: str = "case"
    expected_terms: tuple[str, ...] = ("alpha", "beta")
    question: str = "question"
    answer: str = "answer"
    evidence_refs: tuple[str, ...] = ()
    memories: tuple[object, ...] = ()
    documents: tuple[object, ...] = ()


class _Response:
    status_code = 201
    text = "{}"

    @staticmethod
    def json() -> dict[str, object]:
        return {"data": {}}


class _TimeoutAdapter:
    def post(
        self,
        path: str,
        *,
        json_body: dict[str, object],
        headers: dict[str, str],
    ) -> _Response:
        del json_body, headers
        if path == "/v1/context":
            raise TimeoutError
        return _Response()


def _result(
    case_id: str,
    *,
    capability: str = "recall",
    ok: bool,
    missing_terms: tuple[str, ...] = (),
    covered_terms: tuple[str, ...] = (),
    outcome: str | None = None,
) -> CaseRunResult:
    kwargs = {} if outcome is None else {"outcome": outcome}
    return CaseRunResult(
        benchmark="suite",
        case_id=case_id,
        capability=capability,
        ok=ok,
        expected_ok=not missing_terms,
        forbidden_ok=True,
        missing_terms=missing_terms,
        leaked_terms=(),
        item_ids=(),
        latency_ms=1.0,
        covered_terms=covered_terms,
        **kwargs,
    )


def test_request_failure_has_no_synthetic_semantic_miss() -> None:
    result = case_error_result(_Case(), lambda _: "recall")

    assert result.outcome == "request_failure"
    assert result.missing_terms == ()
    assert result.missing_evidence_refs == ()
    assert case_failures((result,)) == []
    assert coverage_summary((result,))["expected_term_count"] == 0


def test_valid_empty_context_is_a_semantic_miss() -> None:
    result = _result("empty", ok=False, missing_terms=("alpha", "beta"))

    assert result.outcome == "semantic_failure"
    assert case_failures((result,))[0]["reason"] == "missing_expected_terms"
    assert coverage_summary((result,))["expected_term_coverage"] == 0.0


def test_partial_expected_term_miss_preserves_coverage() -> None:
    result = _result(
        "partial",
        ok=False,
        missing_terms=("beta",),
        covered_terms=("alpha",),
    )

    assert case_failures((result,))[0]["missing_terms"] == ["beta"]
    assert coverage_summary((result,))["expected_term_coverage"] == 0.5


def test_request_failure_is_counted_once_and_aggregated_by_capability() -> None:
    results = (
        _result("ok", ok=True),
        _result("semantic", ok=False, missing_terms=("alpha",)),
        _result("request", capability="search", ok=False, outcome="request_failure"),
    )

    summary = run_metric_summary(results)
    breakdown = capability_breakdown(results)

    assert summary["case_count"] == 3
    assert summary["failure_count"] == 2
    assert summary["semantic_case_count"] == 2
    assert summary["semantic_failure_count"] == 1
    assert summary["request_failure_count"] == 1
    assert summary["accuracy"] == 0.5
    assert len(case_failures(results)) == 1
    assert breakdown["search"]["case_count"] == 1
    assert breakdown["search"]["request_failure_count"] == 1
    assert breakdown["search"]["semantic_case_count"] == 0
    assert breakdown["search"]["accuracy"] == 0.0


def test_permissive_threshold_still_fails_closed_on_request_failure() -> None:
    results = (
        _result("ok", ok=True),
        _result("request", ok=False, outcome="request_failure"),
    )

    benchmark = benchmark_summaries(results, min_accuracy=0.0)[0]

    assert benchmark["ok"] is False
    assert benchmark["metrics"]["accuracy"] == 1.0
    assert benchmark["metrics"]["request_failure_count"] == 1


def test_public_benchmark_final_ok_fails_closed_with_permissive_threshold(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "request-failure.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "benchmark": "locomo",
                        "id": "request-failure",
                        "question": "Where is alpha?",
                        "facts": ["Alpha is here."],
                        "expected_terms": ["alpha"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = _execute_cases(
        adapter=_TimeoutAdapter(),
        headers={},
        cases=_load_cases(dataset),
        dataset_path=dataset,
        min_accuracy=0.0,
        started=time.perf_counter(),
    )

    assert result["ok"] is False
    assert result["checks"]["minimum_accuracy_met"] is False
    assert result["checks"]["no_request_failures"] is False
    assert result["metrics"]["accuracy"] == 0.0
    assert result["metrics"]["request_failure_count"] == 1
    assert result["failures"][0]["reason"] == "TimeoutError"


def test_legacy_evidence_only_failure_remains_semantic() -> None:
    assert outcome_from_checkpoint(
        status="failed",
        failure_report={
            "reason": "missing_evidence_refs",
            "missing_evidence_refs": ["D1:2"],
        },
    ) == "semantic_failure"


def test_legacy_unknown_or_ambiguous_failure_remains_semantic() -> None:
    assert outcome_from_checkpoint(
        status="failed",
        failure_report={"reason": "backend_returned_an_odd_result"},
    ) == "semantic_failure"


@pytest.mark.parametrize(
    ("case_payload", "failure_report", "expected"),
    [
        ({"outcome": "success"}, {"outcome": "request_failure"}, "success"),
        (
            {"outcome": "request_failure"},
            {"outcome": "semantic_failure"},
            "request_failure",
        ),
        (
            {"outcome": "semantic_failure"},
            {"status": "ok"},
            "semantic_failure",
        ),
        ({"outcome": "invalid"}, {"outcome": "success"}, "success"),
        ({"outcome": "invalid", "status": "ok"}, {"outcome": "invalid"}, "success"),
        (
            {"status": "request_failure"},
            {"status": "semantic_failure"},
            "request_failure",
        ),
        ({"status": "invalid"}, {"status": "ok"}, "success"),
        (
            {"outcome": "invalid", "status": "invalid"},
            {"outcome": "invalid", "status": "invalid"},
            "semantic_failure",
        ),
        ({"reason": "ReadTimeout"}, {"leaked_terms": ["secret"]}, "request_failure"),
        ({"leaked_terms": ["secret"]}, {"reason": "ReadTimeout"}, "request_failure"),
        ({"missing_terms": ["alpha"]}, {}, "semantic_failure"),
        ({}, {"missing_evidence_refs": ["D1:2"]}, "semantic_failure"),
    ],
    ids=[
        "case-explicit-success-wins",
        "case-explicit-request-failure-wins",
        "case-explicit-semantic-failure-wins",
        "report-explicit-follows-invalid-case-outcome",
        "case-legacy-success-follows-invalid-outcomes",
        "case-legacy-request-failure-wins",
        "report-legacy-success-follows-invalid-case-status",
        "all-invalid-fails-closed",
        "case-transport-precedes-report-leak",
        "report-transport-precedes-case-leak",
        "case-semantic-diagnostic",
        "report-semantic-diagnostic",
    ],
)
def test_checkpoint_outcome_adversarial_source_matrix(
    case_payload: dict[str, object],
    failure_report: dict[str, object],
    expected: str,
) -> None:
    assert outcome_from_checkpoint(
        status="failed",
        case_payload=case_payload,
        failure_report=failure_report,
    ) == expected


def test_explicit_success_preserves_contradictory_raw_diagnostics() -> None:
    result = _case_run_result_from_payload(
        {
            "benchmark": "suite",
            "case_id": "modern-success",
            "outcome": "success",
            "expected_ok": False,
            "forbidden_ok": False,
            "missing_terms": ["alpha"],
            "leaked_terms": ["secret"],
        }
    )

    assert result is not None
    assert result.ok is True
    assert result.outcome == "success"
    assert result.expected_ok is False
    assert result.forbidden_ok is False
    assert result.missing_terms == ("alpha",)
    assert result.leaked_terms == ("secret",)


def test_legacy_ok_preserves_contradictory_raw_diagnostics() -> None:
    result = _case_run_result_from_payload(
        {
            "benchmark": "suite",
            "case_id": "legacy-success",
            "status": "ok",
            "expected_ok": False,
            "forbidden_ok": False,
            "missing_terms": ["alpha"],
            "leaked_terms": ["secret"],
        }
    )

    assert result is not None
    assert result.ok is True
    assert result.outcome == "success"
    assert result.expected_ok is False
    assert result.forbidden_ok is False
    assert result.missing_terms == ("alpha",)
    assert result.leaked_terms == ("secret",)


def test_direct_legacy_false_result_normalizes_to_semantic_failure() -> None:
    result = _result("legacy-constructor", ok=False)

    assert result.ok is False
    assert result.outcome == "semantic_failure"


def test_success_checkpoint_payload_round_trip_uses_terminal_outcome() -> None:
    original = CaseRunResult(
        benchmark="suite",
        case_id="round-trip",
        capability="recall",
        ok=True,
        expected_ok=False,
        forbidden_ok=False,
        missing_terms=("alpha",),
        leaked_terms=(),
        item_ids=("item",),
        latency_ms=2.5,
        outcome="success",
    )

    restored = _case_run_result_from_payload(case_payload(original))

    assert restored == original


@pytest.mark.parametrize(
    ("failure_report", "expected"),
    [
        ({"outcome": "request_failure", "status": "ok"}, "request_failure"),
        ({"outcome": "invalid", "status": "ok"}, "success"),
        ({"outcome": "invalid", "status": "invalid"}, "semantic_failure"),
    ],
    ids=["explicit-outcome", "legacy-status", "invalid-fails-closed"],
)
def test_failure_report_terminal_value_checkpoint_round_trip(
    failure_report: dict[str, object],
    expected: str,
) -> None:
    result = _case_run_result_from_payload(
        {
            "benchmark": "suite",
            "case_id": "failure-report-round-trip",
            "status": "failed",
        },
        failure_report,
    )

    assert result is not None
    assert result.outcome == expected
    assert result.ok is (expected == "success")


def test_legacy_known_transport_failure_is_request_failure() -> None:
    assert outcome_from_checkpoint(
        status="failed",
        failure_report={"reason": "ReadTimeout"},
    ) == "request_failure"


@pytest.mark.parametrize("source", ["case_payload", "failure_report"])
def test_legacy_transport_reason_in_either_source_is_request_failure(
    source: str,
) -> None:
    sources = {source: {"reason": "ReadTimeout"}}

    assert outcome_from_checkpoint(status="failed", **sources) == "request_failure"


def test_legacy_transport_reason_precedes_semantic_fields() -> None:
    assert outcome_from_checkpoint(
        status="failed",
        failure_report={
            "reason": "ReadTimeout",
            "missing_evidence_refs": ["D1:2"],
        },
    ) == "request_failure"


@pytest.mark.parametrize(
    "semantic_fields",
    [
        {"missing_terms": ["alpha"]},
        {"leaked_terms": ["secret"]},
        {"missing_evidence_refs": ["D1:2"]},
        {"expected_ok": False},
        {"forbidden_ok": False},
    ],
    ids=[
        "missing-terms",
        "leaked-terms",
        "missing-evidence",
        "expected-false",
        "forbidden-false",
    ],
)
@pytest.mark.parametrize(
    ("semantic_source", "transport_source"),
    [
        ("case_payload", "failure_report"),
        ("failure_report", "case_payload"),
    ],
)
def test_legacy_transport_reason_in_either_source_precedes_semantics(
    semantic_fields: dict[str, object],
    semantic_source: str,
    transport_source: str,
) -> None:
    sources = {
        semantic_source: semantic_fields,
        transport_source: {"reason": "ReadTimeout"},
    }

    assert outcome_from_checkpoint(status="failed", **sources) == "request_failure"


@pytest.mark.parametrize("source", ["case_payload", "failure_report"])
@pytest.mark.parametrize("reason", ["backend_returned_an_odd_result", "timeout"])
def test_legacy_unknown_or_ambiguous_reason_in_either_source_remains_semantic(
    source: str,
    reason: str,
) -> None:
    sources = {source: {"reason": reason}}

    assert outcome_from_checkpoint(status="failed", **sources) == "semantic_failure"


def test_resume_replay_keeps_request_failure_classification_and_deduplicates(
    tmp_path: Path,
) -> None:
    case = _Case()
    checkpoint = tmp_path / "checkpoint.json"
    failed_case = {
        "benchmark": "suite",
        "case_id": "case",
        "capability": "recall",
        "status": "failed",
        "outcome": "request_failure",
        "expected_ok": False,
        "forbidden_ok": True,
        "missing_terms": [],
        "leaked_terms": [],
        "item_ids": [],
        "latency_ms": 0.0,
    }
    checkpoint.write_text(
        json.dumps(
            {
                "schema_version": "public-benchmark-checkpoint-v1",
                "dataset_hash": "hash",
                "case_selection": {},
                "selected_case_fingerprint": selected_case_fingerprint((case,)),
                "cases": [failed_case, failed_case],
                "failures": [
                    {"case_id": "case", "category": "suite", "reason": "TimeoutError"}
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_checkpoint_resume_state_with_diagnostics(
        checkpoint_out=checkpoint,
        dataset_hash="hash",
        case_selection=None,
        cases=(case,),
    )

    assert loaded.state is None
    assert loaded.checkpoint_failed_case_count == 1
    assert len(loaded.checkpoint_failures) == 1
    assert loaded.checkpoint_failures[0]["reason"] == "TimeoutError"
    assert loaded.checkpoint_failures[0]["missing_terms"] == []
