"""Result builders for public benchmark setup failures."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from infinity_context_server.public_benchmark_artifacts import write_json_atomic
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase


def setup_failure_result(
    *,
    suite: str,
    reason: str,
    case_count: int,
) -> dict[str, object]:
    return {
        "suite": suite,
        "status": "failed",
        "ok": False,
        "checks": {
            "dataset_loaded": True,
            "case_count": case_count > 0,
            "auth_token_configured": False,
        },
        "metrics": {
            "case_count": case_count,
            "benchmark_count": 0,
            "accuracy": 0.0,
        },
        "benchmarks": [],
        "cases": [],
        "failures": [{"case_id": "suite_setup", "category": "setup", "reason": reason}],
    }


def duplicate_case_failure_result(
    *,
    suite: str,
    cases: Sequence[PublicBenchmarkCase],
    duplicate_case_keys: Sequence[str],
) -> dict[str, object]:
    return {
        "suite": suite,
        "status": "failed",
        "ok": False,
        "checks": {
            "dataset_loaded": True,
            "case_count": bool(cases),
            "unique_case_ids": False,
        },
        "metrics": {
            "case_count": len(cases),
            "benchmark_count": len({case.benchmark for case in cases}),
            "accuracy": 0.0,
            "duplicate_case_id_count": len(duplicate_case_keys),
        },
        "benchmarks": [],
        "cases": [],
        "failures": [
            {
                "case_id": key,
                "category": "setup",
                "reason": "duplicate_case_id",
            }
            for key in duplicate_case_keys[:20]
        ],
    }


def write_report(result: dict[str, object], report_out: Path | None) -> None:
    if report_out is None:
        return
    report_out.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(report_out, result)
