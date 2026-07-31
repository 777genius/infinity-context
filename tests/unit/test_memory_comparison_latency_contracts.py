from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from infinity_context_server.memory_comparison_latency import (
    aggregate_server_diagnostics,
    aggregate_server_stage_timings,
    context_server_diagnostic_metrics,
    context_stage_latency_metrics,
)
from infinity_context_server.memory_comparison_token_latency import (
    _stage_totals,
    _token_latency_telemetry,
)


def test_stage_timings_keep_milliseconds_allowlisted_and_bounded() -> None:
    totals = aggregate_server_stage_timings(
        (
            {
                "stage_timings_ms": {
                    "canonical_collect": -5,
                    "derived_collect": 12.345,
                    "request-derived-stage": 999,
                }
            },
            {
                "stage_timings_ms": {
                    "canonical_collect": 10**10_000,
                    "derived_collect": 100_000_000,
                }
            },
        )
    )

    assert totals == {
        "canonical_collect": 86_400_000.0,
        "derived_collect": 86_400_000.0,
    }


def test_server_diagnostic_counts_reject_dynamic_or_non_finite_values() -> None:
    totals = aggregate_server_diagnostics(
        (
            {
                "canonical_keyword_search_candidate_sql_ms": 2.12555,
                "canonical_keyword_search_rescore_candidate_count": True,
                "state_pair_candidates_considered": -10,
                "request_controlled": 900,
            },
            {
                "canonical_keyword_search_candidate_sql_ms": float("nan"),
                "canonical_keyword_search_rescore_candidate_count": 1_000_000_001,
                "state_pair_candidates_considered": 3,
            },
        )
    )

    assert totals == {
        "canonical_keyword_search_candidate_sql_ms": 2.1256,
        "canonical_keyword_search_rescore_candidate_count": 1_000_000_000,
        "state_pair_candidates_considered": 3,
    }


def test_transport_latency_is_milliseconds_and_cannot_escape_bounds() -> None:
    metrics = context_stage_latency_metrics(
        (
            {
                "retrieval": {
                    "latency_ms": float("inf"),
                    "metadata": {"server_stage_timings_ms": {"total": 5.0}},
                }
            },
        )
    )

    assert metrics["client_transport_overhead_ms"] == {
        "count": 1,
        "avg": 0.0,
        "min": 0.0,
        "max": 0.0,
    }
    assert metrics["publishable"] is False
    json.dumps(metrics, allow_nan=False, sort_keys=True)


def test_server_diagnostic_artifact_is_strict_json_and_nonpublishable() -> None:
    metrics = context_server_diagnostic_metrics(
        (
            {
                "retrieval": {
                    "metadata": {
                        "server_diagnostics": {
                            "state_pair_candidates_considered": 3,
                            "canonical_keyword_search_candidate_sql_ms": 2.5,
                        }
                    }
                }
            },
        )
    )

    assert metrics["publishable"] is False
    json.dumps(metrics, allow_nan=False, sort_keys=True)


def test_token_latency_telemetry_uses_exact_bounded_provider_units() -> None:
    telemetry = _token_latency_telemetry(
        (
            {
                "generation": {
                    "latency_ms": float("inf"),
                    "token_usage": {"prompt_tokens": True, "completion_tokens": -1},
                },
                "judgment": {
                    "latency_ms": 10**10_000,
                    "token_usage": {
                        "prompt_tokens": 1_000_000_001,
                        "completion_tokens": "2",
                    },
                },
                "cutoff_results": {},
            },
        ),
    )

    assert telemetry["primary"] == {
        "provider_call_count": 2,
        "prompt_tokens": 1_000_000_000,
        "completion_tokens": 0,
        "total_tokens": 1_000_000_000,
        "latency_ms": 86_400_000.0,
    }
    assert telemetry["primary_cutoff"] == 50
    assert telemetry["publishable"] is False
    json.dumps(telemetry, allow_nan=False, sort_keys=True)


def test_missing_generation_or_judgment_does_not_create_phantom_provider_calls() -> None:
    telemetry = _token_latency_telemetry(
        (
            {
                "generation": {},
                "cutoff_results": {
                    "50": {
                        "generation": {
                            "latency_ms": 2,
                            "token_usage": {"prompt_tokens": 3, "completion_tokens": 1},
                        }
                    }
                },
            },
            {
                "judgment": {
                    "latency_ms": 4,
                    "token_usage": {"prompt_tokens": 5, "completion_tokens": 2},
                }
            },
        )
    )

    assert telemetry["primary"]["provider_call_count"] == 1
    assert telemetry["actual_all_cutoffs"]["provider_call_count"] == 1


def test_latency_entries_reject_bool_and_non_mapping_values_without_raising() -> None:
    assert aggregate_server_stage_timings(True) == {}  # type: ignore[arg-type]
    assert aggregate_server_diagnostics(False) == {}  # type: ignore[arg-type]

    server_metrics = context_server_diagnostic_metrics(
        (True, 7, "raw", {}),  # type: ignore[arg-type]
    )
    stage_metrics = context_stage_latency_metrics(
        (True, 7, "raw", {}),  # type: ignore[arg-type]
    )
    token_metrics = _token_latency_telemetry(
        (True, 7, "raw", {}),  # type: ignore[arg-type]
    )

    assert server_metrics["invalid_evaluation_count"] == 3
    assert stage_metrics["invalid_evaluation_count"] == 3
    assert token_metrics["invalid_evaluation_count"] == 3
    assert token_metrics["primary"]["provider_call_count"] == 0
    totals = _stage_totals((True, 7, "raw"))  # type: ignore[arg-type]
    assert totals["provider_call_count"] == 0


def test_non_sequence_token_latency_input_is_explicitly_invalid() -> None:
    telemetry = _token_latency_telemetry(True)  # type: ignore[arg-type]

    assert (
        context_server_diagnostic_metrics(True)[  # type: ignore[arg-type]
            "evaluation_input_valid"
        ]
        is False
    )
    assert (
        context_stage_latency_metrics(False)[  # type: ignore[arg-type]
            "evaluation_input_valid"
        ]
        is False
    )
    assert telemetry["input_valid"] is False
    assert telemetry["primary"]["provider_call_count"] == 0


def test_importing_contract_slice_does_not_load_benchmark_or_provider_helpers() -> None:
    root = Path.cwd()
    import_paths = [
        str(root / "packages" / "infinity_context_core"),
        str(root / "packages" / "infinity_context_server"),
    ]
    module_names = [
        "memory_comparison_latency",
        "memory_comparison_retrieval_policy",
        "memory_comparison_retrieval_width",
        "memory_comparison_session_identity_contract",
        "memory_comparison_token_budget_contract",
        "memory_comparison_token_latency",
    ]
    code = f"""
import json
import sys
sys.path[:0] = {import_paths!r}
for name in {module_names!r}:
    __import__(f"infinity_context_server.{{name}}")
forbidden = (
    "infinity_context_server.memory_comparison_benchmark_shared",
    "infinity_context_server.memory_comparison_chat_completions",
    "infinity_context_server.memory_comparison_models",
    "infinity_context_server.longmemeval_session_identity",
    "openai",
)
print(json.dumps(sorted(name for name in sys.modules if name.startswith(forbidden))))
"""

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == []
