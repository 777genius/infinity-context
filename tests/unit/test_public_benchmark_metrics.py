from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from infinity_context_server.public_benchmark_checkpoint import (
    CaseRunResult,
    load_checkpoint_resume_state_with_diagnostics,
)
from infinity_context_server.public_benchmark_metrics import (
    benchmark_summaries,
    bounded_progress_fields,
    case_failures,
    case_payload,
    coverage_summary,
    progress_case_outcome_fields,
    progress_timing_fields,
    run_metric_summary,
)


def test_public_benchmark_case_payload_includes_bounded_question_preview() -> None:
    result = _case_result(question_preview="What did Alex decide about Atlas?" * 20)

    payload = case_payload(result)

    assert payload["question_preview"].startswith("What did Alex decide")
    assert len(payload["question_preview"]) == 240


def test_public_benchmark_case_failures_include_question_preview() -> None:
    result = _case_result(
        ok=False,
        missing_terms=("answer",),
        question_preview="Who supports Caroline?",
    )

    failures = case_failures((result,))

    assert failures == [
        {
            "case_id": "case-one",
            "category": "locomo",
            "capability": "locomo:temporal_reasoning",
            "reason": "missing_expected_terms",
            "missing_terms": ["answer"],
            "leaked_terms": [],
            "question_preview": "Who supports Caroline?",
        }
    ]


def test_public_benchmark_case_failures_include_answer_and_evidence_diagnostics() -> None:
    result = _case_result(
        ok=False,
        missing_terms=("D3:11",),
        question_preview="Who supports Caroline?",
        answer_preview="Her mentors, family, and friends",
        expected_terms_preview=("D12:1", "D3:11"),
        evidence_refs=("D12:1", "D3:11"),
        evidence_ref_previews=(
            "D12:1: Caroline values support from friends.",
            "D3:11: Caroline is supported by mentors.",
        ),
        missing_evidence_ref_previews=("D3:11: Caroline is supported by mentors.",),
    )

    failures = case_failures((result,))
    payload = case_payload(result)

    assert failures[0]["answer_preview"] == "Her mentors, family, and friends"
    assert failures[0]["expected_terms_preview"] == ["D12:1", "D3:11"]
    assert failures[0]["evidence_refs"] == ["D12:1", "D3:11"]
    assert failures[0]["evidence_ref_previews"] == [
        "D12:1: Caroline values support from friends.",
        "D3:11: Caroline is supported by mentors.",
    ]
    assert failures[0]["missing_evidence_ref_previews"] == [
        "D3:11: Caroline is supported by mentors.",
    ]
    assert payload["answer_preview"] == "Her mentors, family, and friends"
    assert payload["expected_terms_preview"] == ["D12:1", "D3:11"]
    assert payload["evidence_refs"] == ["D12:1", "D3:11"]
    assert payload["missing_evidence_ref_previews"] == [
        "D3:11: Caroline is supported by mentors.",
    ]


def test_public_benchmark_payloads_sanitize_auth_previews_refs_and_item_ids() -> None:
    bearer_payload = "Bearer " + ("a" * 16)
    key_payload = "MEMORY_TOKEN=" + ("b" * 16)
    raw_ref = "locomo:conv-private:session_3:D3:11:turn-secret"
    private_auth_path = "/home/alice/.config/openai/auth.json"

    result = _case_result(
        case_id=f"case-one {bearer_payload}",
        ok=False,
        missing_terms=(key_payload,),
        item_ids=(bearer_payload, raw_ref, private_auth_path, "safe-chunk"),
        question_preview=f"Who supports Caroline? {bearer_payload}",
        answer_preview=f"Her mentors. {key_payload}",
        expected_terms_preview=(key_payload,),
        evidence_refs=(
            raw_ref,
            private_auth_path,
            f"authorization {bearer_payload} D4:5",
        ),
        evidence_ref_previews=(
            f"{raw_ref}: private text {bearer_payload}",
            f"{private_auth_path}: private auth index",
        ),
        covered_terms=(key_payload,),
        covered_evidence_refs=(raw_ref,),
        missing_evidence_refs=(
            private_auth_path,
            f"authorization {bearer_payload} D4:5",
        ),
        missing_evidence_ref_previews=(f"D4:5 private text {key_payload}",),
    )

    rendered = json.dumps(
        {"payload": case_payload(result), "failures": case_failures((result,))},
        sort_keys=True,
    )

    assert "Bearer" not in rendered
    assert "MEMORY_TOKEN" not in rendered
    assert "conv-private" not in rendered
    assert "turn-secret" not in rendered
    assert "/home/alice" not in rendered
    assert "auth.json" not in rendered
    assert "\"case_id\": \"case-one [redacted]\"" in rendered
    assert "safe-chunk" in rendered
    assert "source_session_turn_refs:session_3:D3:11" in rendered
    assert "source_turn_refs:D4:5" in rendered
    assert '"capability": "locomo:temporal_reasoning"' in rendered
    assert "[redacted]" in rendered


def test_public_benchmark_progress_outcome_fields_sanitize_case_ids() -> None:
    bearer_payload = "Bearer " + ("a" * 16)
    result = _case_result(
        case_id=f"case-failed {bearer_payload}",
        ok=False,
        missing_terms=("answer",),
    )

    fields = progress_case_outcome_fields(
        processed_case_count=1,
        run_results=(result,),
        failures=case_failures((result,)),
        total_case_count=1,
    )
    rendered = json.dumps(fields, sort_keys=True)

    assert "Bearer" not in rendered
    assert fields["last_case_id"] == "case-failed [redacted]"
    assert fields["recent_failed_case_ids"] == ["case-failed [redacted]"]


def test_public_benchmark_progress_fields_sanitize_refs_previews_and_item_ids() -> None:
    bearer_payload = "Bearer " + ("a" * 16)
    key_payload = "MEMORY_TOKEN=" + ("b" * 16)
    raw_ref = "locomo:conv-private:session_3:D3:11:turn-secret"

    fields = bounded_progress_fields(
        {
            "case_id": f"locomo:conv-26:qa:70 {bearer_payload}",
            "question_preview": f"Who supports Caroline? {bearer_payload}",
            "item_ids": [bearer_payload, raw_ref, "safe-chunk"],
            "evidence_refs": [raw_ref, f"authorization {bearer_payload} D4:5"],
            "diagnostics": {
                "answer_preview": f"Her mentors. {key_payload}",
                "missing_evidence_refs": [raw_ref],
            },
        }
    )
    rendered = json.dumps(fields, sort_keys=True)

    assert "Bearer" not in rendered
    assert "MEMORY_TOKEN" not in rendered
    assert "conv-private" not in rendered
    assert "turn-secret" not in rendered
    assert fields["case_id"] == "locomo:conv-26:qa:70 [redacted]"
    assert "safe-chunk" in rendered
    assert "source_session_turn_refs:session_3:D3:11" in rendered
    assert "source_turn_refs:D4:5" in rendered
    assert "[redacted]" in rendered


def test_public_benchmark_case_payload_includes_bounded_coverage() -> None:
    result = _case_result(
        covered_terms=("D12:1", "single parent"),
        missing_terms=("D3:11",),
        evidence_refs=("D12:1", "D3:11", "D7:4"),
        covered_evidence_refs=("D12:1",),
        missing_evidence_refs=("D3:11", "D7:4"),
    )

    payload = case_payload(result)

    assert payload["coverage"] == {
        "expected_term_count": 3,
        "covered_expected_term_count": 2,
        "expected_term_coverage": 0.6667,
        "evidence_ref_count": 3,
        "covered_evidence_ref_count": 1,
        "evidence_ref_coverage": 0.3333,
    }
    assert payload["covered_terms"] == ["D12:1", "single parent"]
    assert payload["covered_evidence_refs"] == ["D12:1"]
    assert payload["missing_evidence_refs"] == ["D3:11", "D7:4"]


def test_public_benchmark_metric_summaries_include_coverage() -> None:
    first = _case_result(
        case_id="case-one",
        covered_terms=("D1:1",),
        missing_terms=("D1:2",),
        covered_evidence_refs=("D1:1",),
        missing_evidence_refs=("D1:2",),
    )
    second = _case_result(
        case_id="case-two",
        covered_terms=("D2:1", "D2:2"),
        covered_evidence_refs=("D2:1", "D2:2"),
    )

    summary = coverage_summary((first, second))
    metrics = run_metric_summary((first, second))
    benchmark = benchmark_summaries((first, second), min_accuracy=1.0)[0]
    capability = next(iter(benchmark["capability_breakdown"].values()))

    assert summary == {
        "expected_term_count": 4,
        "covered_expected_term_count": 3,
        "expected_term_coverage": 0.75,
        "evidence_ref_count": 4,
        "covered_evidence_ref_count": 3,
        "evidence_ref_coverage": 0.75,
    }
    assert metrics["expected_term_coverage"] == 0.75
    assert metrics["evidence_ref_coverage"] == 0.75
    assert benchmark["metrics"]["expected_term_coverage"] == 0.75
    assert capability["expected_term_coverage"] == 0.75


def test_public_benchmark_progress_timing_includes_eta_diagnostics() -> None:
    fields = progress_timing_fields(
        processed_case_count=2,
        total_case_count=4,
        started=time.perf_counter() - 10,
    )

    assert fields["eta_confidence"] == "warming_up"
    assert 4_900 <= fields["average_case_ms"] <= 5_100
    assert 9_800 <= fields["estimated_remaining_ms"] <= 10_300
    assert 19_800 <= fields["estimated_total_ms"] <= 20_400


def test_public_benchmark_progress_timing_marks_stable_after_three_cases() -> None:
    fields = progress_timing_fields(
        processed_case_count=3,
        total_case_count=3,
        started=time.perf_counter() - 3,
    )

    assert fields["eta_confidence"] == "stable"
    assert fields["estimated_remaining_ms"] == 0.0
    assert fields["estimated_total_ms"] >= 3_000


def test_public_benchmark_progress_timing_handles_unavailable_eta() -> None:
    fields = progress_timing_fields(
        processed_case_count=0,
        total_case_count=4,
        started=time.perf_counter(),
    )

    assert fields == {
        "average_case_ms": 0.0,
        "cases_per_second": 0.0,
        "estimated_remaining_ms": 0.0,
        "estimated_total_ms": 0.0,
        "eta_confidence": "unavailable",
    }


def test_public_benchmark_resume_accepts_checkpoint_without_question_preview(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "schema_version": "public-benchmark-checkpoint-v1",
                "dataset_hash": "dataset-hash",
                "case_selection": {"strategy": "first"},
                "cases": [
                    {
                        "benchmark": "locomo",
                        "case_id": "case-one",
                        "capability": "locomo:temporal_reasoning",
                        "status": "ok",
                        "expected_ok": True,
                        "forbidden_ok": True,
                        "missing_terms": [],
                        "leaked_terms": [],
                        "item_ids": ["chunk-one"],
                        "latency_ms": 12.5,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_checkpoint_resume_state_with_diagnostics(
        checkpoint_out=checkpoint,
        dataset_hash="dataset-hash",
        case_selection={"strategy": "first"},
        cases=(_Case("locomo", "case-one"),),
    )

    assert loaded.status == "loaded"
    assert loaded.state is not None
    assert loaded.state.run_results[0].question_preview == ""


def test_public_benchmark_resume_preserves_checkpoint_failure_diagnostics(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "schema_version": "public-benchmark-checkpoint-v1",
                "dataset_hash": "dataset-hash",
                "case_selection": {},
                "cases": [
                    {
                        "benchmark": "locomo",
                        "case_id": "case-ok",
                        "capability": "locomo:temporal_reasoning",
                        "status": "ok",
                        "expected_ok": True,
                        "forbidden_ok": True,
                        "missing_terms": [],
                        "leaked_terms": [],
                        "item_ids": ["chunk-one"],
                        "latency_ms": 12.5,
                    },
                    {
                        "benchmark": "locomo",
                        "case_id": "case-failed",
                        "capability": "locomo:temporal_reasoning",
                        "status": "failed",
                        "expected_ok": False,
                        "forbidden_ok": True,
                        "missing_terms": ["answer"],
                        "leaked_terms": [],
                        "item_ids": [],
                        "latency_ms": 15.0,
                        "question_preview": "Who supports Caroline?",
                        "answer_preview": "Her mentors, family, and friends",
                        "expected_terms_preview": ["D12:1", "D3:11"],
                        "evidence_refs": ["D12:1", "D3:11"],
                        "evidence_ref_previews": [
                            "D12:1: Caroline values support from friends.",
                            "D3:11: Caroline is supported by mentors.",
                        ],
                        "missing_evidence_ref_previews": [
                            "D3:11: Caroline is supported by mentors.",
                        ],
                    },
                ],
                "failures": [
                    {
                        "case_id": "case-failed",
                        "category": "locomo",
                        "reason": "missing_expected_terms",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_checkpoint_resume_state_with_diagnostics(
        checkpoint_out=checkpoint,
        dataset_hash="dataset-hash",
        case_selection=None,
        cases=(_Case("locomo", "case-ok"), _Case("locomo", "case-failed")),
    )

    assert loaded.status == "loaded"
    assert loaded.checkpoint_failed_case_count == 1
    assert loaded.state is not None
    assert [result.case_id for result in loaded.state.run_results] == ["case-ok"]
    assert loaded.checkpoint_failures == (
        {
            "case_id": "case-failed",
            "category": "locomo",
            "capability": "locomo:temporal_reasoning",
            "reason": "missing_expected_terms",
            "missing_terms": ["answer"],
            "leaked_terms": [],
            "checkpoint_status": "failed",
            "retry_pending": True,
            "from_checkpoint": True,
            "question_preview": "Who supports Caroline?",
            "answer_preview": "Her mentors, family, and friends",
            "expected_terms_preview": ["D12:1", "D3:11"],
            "evidence_refs": ["D12:1", "D3:11"],
            "evidence_ref_previews": [
                "D12:1: Caroline values support from friends.",
                "D3:11: Caroline is supported by mentors.",
            ],
            "missing_evidence_ref_previews": [
                "D3:11: Caroline is supported by mentors.",
            ],
        },
    )


def test_public_benchmark_resume_sanitizes_checkpoint_failure_diagnostics(
    tmp_path: Path,
) -> None:
    bearer_payload = "Bearer " + ("a" * 16)
    key_payload = "MEMORY_TOKEN=" + ("b" * 16)
    raw_ref = "locomo:conv-private:session_3:D3:11:turn-secret"
    unsafe_case_id = f"case-failed {bearer_payload}"
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "schema_version": "public-benchmark-checkpoint-v1",
                "dataset_hash": "dataset-hash",
                "case_selection": {},
                "cases": [
                    {
                        "benchmark": "locomo",
                        "case_id": "case-ok",
                        "capability": "locomo:temporal_reasoning",
                        "status": "ok",
                        "expected_ok": True,
                        "forbidden_ok": True,
                        "missing_terms": [],
                        "leaked_terms": [],
                        "item_ids": ["chunk-one"],
                        "latency_ms": 12.5,
                    },
                    {
                        "benchmark": "locomo",
                        "case_id": unsafe_case_id,
                        "capability": "locomo:temporal_reasoning",
                        "status": "failed",
                        "expected_ok": False,
                        "forbidden_ok": True,
                        "missing_terms": [key_payload],
                        "leaked_terms": [bearer_payload],
                        "item_ids": [bearer_payload, raw_ref],
                        "latency_ms": 15.0,
                        "question_preview": f"Who supports Caroline? {bearer_payload}",
                        "answer_preview": f"Her mentors. {key_payload}",
                        "expected_terms_preview": [key_payload],
                        "evidence_refs": [raw_ref, f"authorization {bearer_payload} D4:5"],
                        "evidence_ref_previews": [
                            f"{raw_ref}: private text {bearer_payload}",
                        ],
                        "covered_terms": [key_payload],
                        "covered_evidence_refs": [raw_ref],
                        "missing_evidence_refs": [
                            f"authorization {bearer_payload} D4:5",
                        ],
                        "missing_evidence_ref_previews": [
                            f"D4:5 private text {key_payload}",
                        ],
                    },
                ],
                "failures": [
                    {
                        "case_id": unsafe_case_id,
                        "category": "locomo",
                        "reason": key_payload,
                        "question_preview": f"fallback {bearer_payload}",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_checkpoint_resume_state_with_diagnostics(
        checkpoint_out=checkpoint,
        dataset_hash="dataset-hash",
        case_selection=None,
        cases=(_Case("locomo", "case-ok"), _Case("locomo", unsafe_case_id)),
    )

    rendered = json.dumps(loaded.checkpoint_failures, sort_keys=True)

    assert loaded.status == "loaded"
    assert "Bearer" not in rendered
    assert "MEMORY_TOKEN" not in rendered
    assert unsafe_case_id not in rendered
    assert "conv-private" not in rendered
    assert "turn-secret" not in rendered
    assert '"case_id": "case-failed [redacted]"' in rendered
    assert "source_session_turn_refs:session_3:D3:11" in rendered
    assert "source_turn_refs:D4:5" in rendered
    assert "[redacted]" in rendered


@dataclass(frozen=True)
class _Case:
    benchmark: str
    case_id: str
    memory_scope_external_ref: str | None = None
    thread_external_ref: str | None = None
    memories: tuple[object, ...] = ()
    documents: tuple[object, ...] = ()


def _case_result(
    *,
    case_id: str = "case-one",
    ok: bool = True,
    missing_terms: tuple[str, ...] = (),
    item_ids: tuple[str, ...] = ("chunk-one",),
    question_preview: str = "",
    answer_preview: str = "",
    expected_terms_preview: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
    evidence_ref_previews: tuple[str, ...] = (),
    covered_terms: tuple[str, ...] = (),
    covered_evidence_refs: tuple[str, ...] = (),
    missing_evidence_refs: tuple[str, ...] = (),
    missing_evidence_ref_previews: tuple[str, ...] = (),
) -> CaseRunResult:
    return CaseRunResult(
        benchmark="locomo",
        case_id=case_id,
        capability="locomo:temporal_reasoning",
        ok=ok,
        expected_ok=not missing_terms,
        forbidden_ok=True,
        missing_terms=missing_terms,
        leaked_terms=(),
        item_ids=item_ids,
        latency_ms=12.5,
        question_preview=question_preview,
        answer_preview=answer_preview,
        expected_terms_preview=expected_terms_preview,
        evidence_refs=evidence_refs,
        evidence_ref_previews=evidence_ref_previews,
        covered_terms=covered_terms,
        covered_evidence_refs=covered_evidence_refs,
        missing_evidence_refs=missing_evidence_refs,
        missing_evidence_ref_previews=missing_evidence_ref_previews,
    )
