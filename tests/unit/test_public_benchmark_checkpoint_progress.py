from __future__ import annotations

import json
import time
from pathlib import Path

from infinity_context_server.public_benchmark import (
    _BenchmarkProgress,
    _emit_case_progress_snapshot,
)
from infinity_context_server.public_benchmark_checkpoint import (
    BenchmarkSeedStats,
    CaseRunResult,
)
from infinity_context_server.public_benchmark_manifest import build_execution_manifest


def _case_result(
    case_id: str = "case-one",
    *,
    benchmark: str = "locomo",
    capability: str = "locomo:temporal_reasoning",
    ok: bool = True,
    question_preview: str = "",
) -> CaseRunResult:
    return CaseRunResult(
        benchmark=benchmark,
        case_id=case_id,
        capability=capability,
        ok=ok,
        expected_ok=ok,
        forbidden_ok=True,
        missing_terms=() if ok else ("answer",),
        leaked_terms=(),
        item_ids=("chunk-one",),
        latency_ms=12.5,
        question_preview=question_preview,
    )


def test_public_benchmark_progress_writes_time_interval_checkpoint(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    progress = _BenchmarkProgress(
        dataset_path=tmp_path / "dataset.json",
        dataset_hash="dataset-hash",
        total_case_count=3,
        case_selection={"strategy": "first"},
        started=time.perf_counter() - 10,
        checkpoint_out=checkpoint,
        checkpoint_every_cases=100,
        checkpoint_min_interval_seconds=1.0,
    )

    progress.checkpoint(
        processed_case_count=1,
        run_results=(_case_result(),),
        failures=(),
        seeded_source_count=1,
    )

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert payload["checkpoint_policy"] == {
        "checkpoint_every_cases": 100,
        "checkpoint_min_interval_seconds": 1.0,
        "checkpoint_reason": "time_interval",
    }
    assert payload["progress"]["checkpoint_reason"] == "time_interval"
    assert payload["progress"]["processed_case_count"] == 1
    assert payload["progress"]["remaining_case_count"] == 2
    assert payload["progress"]["resume_pending_case_count"] == 2
    assert payload["progress"]["succeeded_case_count"] == 1
    assert payload["progress"]["failed_case_count"] == 0
    assert payload["progress"]["failure_case_ratio"] == 0.0
    assert payload["progress"]["last_case_id"] == "case-one"
    assert payload["progress"]["last_case_status"] == "ok"
    assert payload["progress"]["elapsed_since_checkpoint_ms"] >= 1000
    assert payload["progress"]["average_case_ms"] > 0
    assert (
        payload["progress"]["estimated_total_ms"]
        >= payload["progress"]["estimated_remaining_ms"]
    )
    assert payload["progress"]["eta_confidence"] == "warming_up"


def test_public_benchmark_progress_checkpoint_includes_recent_failure_diagnostics(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    progress = _BenchmarkProgress(
        dataset_path=tmp_path / "dataset.json",
        dataset_hash="dataset-hash",
        total_case_count=3,
        case_selection=None,
        started=time.perf_counter() - 10,
        checkpoint_out=checkpoint,
        checkpoint_every_cases=100,
        checkpoint_min_interval_seconds=1.0,
    )

    progress.checkpoint(
        processed_case_count=2,
        run_results=(
            _case_result("case-ok"),
            _case_result("case-failed", ok=False, question_preview="Who supports Caroline?"),
        ),
        failures=({"case_id": "case-failed", "reason": "missing_expected_terms"},),
        seeded_source_count=1,
    )

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))

    assert payload["progress"]["remaining_case_count"] == 1
    assert payload["progress"]["resume_pending_case_count"] == 2
    assert payload["progress"]["succeeded_case_count"] == 1
    assert payload["progress"]["failed_case_count"] == 1
    assert payload["progress"]["failure_count"] == 1
    assert payload["progress"]["failure_report_count"] == 1
    assert payload["progress"]["failure_case_ratio"] == 0.5
    assert payload["progress"]["recent_failed_case_ids"] == ["case-failed"]
    assert payload["progress"]["last_case_id"] == "case-failed"
    assert payload["progress"]["last_case_status"] == "failed"
    assert payload["progress"]["last_question_preview"] == "Who supports Caroline?"


def test_public_benchmark_checkpoint_sanitizes_failure_artifact_fields(
    tmp_path: Path,
) -> None:
    bearer_payload = "Bearer " + ("a" * 16)
    key_payload = "MEMORY_TOKEN=" + ("b" * 16)
    raw_ref = "locomo:conv-private:session_3:D3:11:turn-secret"
    checkpoint = tmp_path / "checkpoint.json"
    progress = _BenchmarkProgress(
        dataset_path=tmp_path / "dataset.json",
        dataset_hash="dataset-hash",
        total_case_count=1,
        case_selection=None,
        started=time.perf_counter() - 10,
        checkpoint_out=checkpoint,
        checkpoint_every_cases=1,
    )

    progress.checkpoint(
        processed_case_count=1,
        run_results=(_case_result("case-failed", ok=False),),
        failures=(
            {
                "case_id": f"case-failed {bearer_payload}",
                "reason": key_payload,
                "question_preview": f"Who supports Caroline? {bearer_payload}",
                "item_ids": [bearer_payload, raw_ref, "safe-chunk"],
                "evidence_refs": [raw_ref, f"authorization {bearer_payload} D4:5"],
            },
        ),
        seeded_source_count=1,
    )

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    rendered = json.dumps(
        {"failures": payload["failures"], "recent_failures": payload["recent_failures"]},
        sort_keys=True,
    )

    assert "Bearer" not in rendered
    assert "MEMORY_TOKEN" not in rendered
    assert "conv-private" not in rendered
    assert "turn-secret" not in rendered
    assert payload["failures"][0]["case_id"] == "case-failed [redacted]"
    assert "safe-chunk" in rendered
    assert "source_session_turn_refs:session_3:D3:11" in rendered
    assert "source_turn_refs:D4:5" in rendered


def test_public_benchmark_checkpoint_sanitizes_progress_case_identifiers(
    tmp_path: Path,
) -> None:
    bearer_payload = "Bearer " + ("a" * 16)
    raw_ref = "locomo:conv-private:session_3:D3:11:turn-secret"
    checkpoint = tmp_path / "checkpoint.json"
    progress = _BenchmarkProgress(
        dataset_path=tmp_path / "dataset.json",
        dataset_hash="dataset-hash",
        total_case_count=2,
        case_selection=None,
        started=time.perf_counter() - 10,
        checkpoint_out=checkpoint,
        checkpoint_every_cases=1,
    )

    progress.checkpoint(
        processed_case_count=2,
        run_results=(
            _case_result(f"case-ok {bearer_payload}"),
            _case_result(
                raw_ref,
                benchmark=f"locomo {bearer_payload}",
                capability=f"locomo:temporal_reasoning {bearer_payload}",
                ok=False,
            ),
        ),
        failures=({"case_id": raw_ref, "reason": "missing_expected_terms"},),
        seeded_source_count=1,
    )

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    rendered = json.dumps(payload["progress"], sort_keys=True)

    assert "Bearer" not in rendered
    assert "conv-private" not in rendered
    assert "turn-secret" not in rendered
    assert payload["progress"]["recent_failed_case_ids"] == ["[redacted]"]
    assert payload["progress"]["last_case_benchmark"] == "locomo [redacted]"
    assert payload["progress"]["last_case_id"] == "[redacted]"
    assert payload["progress"]["last_case_capability"] == "[redacted]"


def test_public_benchmark_progress_event_includes_actionable_outcome_snapshot(
    tmp_path: Path,
) -> None:
    progress_out = tmp_path / "progress.jsonl"
    progress = _BenchmarkProgress(
        dataset_path=tmp_path / "dataset.json",
        dataset_hash="dataset-hash",
        total_case_count=2,
        case_selection=None,
        started=time.perf_counter() - 10,
        progress_out=progress_out,
    )

    _emit_case_progress_snapshot(
        progress=progress,
        run_results=(
            _case_result("case-ok"),
            _case_result("case-failed", ok=False),
        ),
        failures=({"case_id": "case-failed", "reason": "missing_expected_terms"},),
        seeded_source_count=1,
        seed_stats=BenchmarkSeedStats(source_attempt_count=1, seeded_source_count=1),
        effective_parallelism=1,
    )

    event = json.loads(progress_out.read_text(encoding="utf-8").splitlines()[0])

    assert event["event_type"] == "case_progress"
    assert event["remaining_case_count"] == 0
    assert event["resume_pending_case_count"] == 1
    assert event["succeeded_case_count"] == 1
    assert event["failed_case_count"] == 1
    assert event["recent_failed_case_ids"] == ["case-failed"]
    assert event["last_case_status"] == "failed"


def test_public_benchmark_progress_throttles_time_checkpoint_until_due(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    progress = _BenchmarkProgress(
        dataset_path=tmp_path / "dataset.json",
        dataset_hash="dataset-hash",
        total_case_count=3,
        case_selection=None,
        started=time.perf_counter(),
        checkpoint_out=checkpoint,
        checkpoint_every_cases=100,
        checkpoint_min_interval_seconds=3600.0,
    )

    progress.checkpoint(
        processed_case_count=1,
        run_results=(_case_result(),),
        failures=(),
        seeded_source_count=1,
    )

    assert not checkpoint.exists()

    progress.checkpoint(
        processed_case_count=1,
        run_results=(_case_result(),),
        failures=(),
        seeded_source_count=1,
        force=True,
    )

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["checkpoint_policy"]["checkpoint_reason"] == "forced"
    assert payload["progress"]["checkpoint_reason"] == "forced"


def test_public_benchmark_progress_writes_completed_checkpoint_without_force(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    progress = _BenchmarkProgress(
        dataset_path=tmp_path / "dataset.json",
        dataset_hash="dataset-hash",
        total_case_count=1,
        case_selection=None,
        started=time.perf_counter(),
        checkpoint_out=checkpoint,
        checkpoint_every_cases=100,
        checkpoint_min_interval_seconds=3600.0,
    )

    progress.checkpoint(
        processed_case_count=1,
        run_results=(_case_result(),),
        failures=(),
        seeded_source_count=1,
    )

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["checkpoint_policy"]["checkpoint_reason"] == "completed"


def test_public_benchmark_checkpoint_includes_execution_manifest(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    progress = _BenchmarkProgress(
        dataset_path=tmp_path / "dataset.json",
        dataset_hash="dataset-hash",
        total_case_count=1,
        case_selection=None,
        started=time.perf_counter(),
        checkpoint_out=checkpoint,
        checkpoint_every_cases=1,
        execution_manifest={
            "schema_version": "public-benchmark-execution-manifest-v1",
            "execution_fingerprint": "execution-fingerprint",
            "manifest_fingerprint": "manifest-fingerprint",
        },
    )

    progress.checkpoint(
        processed_case_count=1,
        run_results=(_case_result(),),
        failures=(),
        seeded_source_count=1,
    )

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["execution_fingerprint"] == "execution-fingerprint"
    assert payload["execution_manifest"] == {
        "schema_version": "public-benchmark-execution-manifest-v1",
        "execution_fingerprint": "execution-fingerprint",
        "manifest_fingerprint": "manifest-fingerprint",
    }


def test_public_benchmark_execution_manifest_redacts_requested_case_ids(
    tmp_path: Path,
) -> None:
    bearer_payload = "Bearer " + ("a" * 16)

    manifest = build_execution_manifest(
        suite="public-memory-benchmark",
        evaluation_mode="retrieved_expected_terms",
        dataset_path=tmp_path / "dataset.json",
        dataset_hash="dataset-hash",
        selected_case_count=1,
        selected_case_fingerprint="selected-fingerprint",
        case_selection={
            "requested_case_ids": [f"locomo:conv-26:qa:70 {bearer_payload}"],
        },
        requested_case_ids=(f"locomo:conv-26:qa:70 {bearer_payload}",),
        requested_capabilities=(),
        transport_mode="custom_adapter",
        requested_parallelism=1,
        effective_parallelism=1,
        parallelism_degraded_reason=None,
        request_timeout_seconds=30.0,
        checkpoint_every_cases=1,
        checkpoint_min_interval_seconds=0.0,
        resume_from_checkpoint=True,
        resume_reuse_policy="successful_cases_only",
        retrieval_contract={},
    )
    rendered = json.dumps(manifest, sort_keys=True)

    assert "Bearer" not in rendered
    assert manifest["selection"]["requested_case_ids"] == [
        "locomo:conv-26:qa:70 [redacted]"
    ]
    assert manifest["selection"]["case_selection"]["requested_case_ids"] == [
        "locomo:conv-26:qa:70 [redacted]"
    ]
