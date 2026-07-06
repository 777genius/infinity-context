"""Environment preflight checks for public benchmark local execution."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class BenchmarkEnvironmentPreflight:
    ok: bool
    reason: str | None
    diagnostics: Mapping[str, object]


def check_local_benchmark_environment() -> BenchmarkEnvironmentPreflight:
    """Check local in-process benchmark dependencies without leaking raw paths."""

    module_checks = [
        _module_import_check("sqlite3", reason="local_environment_sqlite3_unavailable"),
        _module_import_check("aiosqlite", reason="local_environment_aiosqlite_unavailable"),
        _module_import_check(
            "fastapi.testclient",
            reason="local_environment_testclient_unavailable",
        ),
    ]
    failed = next((item for item in module_checks if not item["available"]), None)
    diagnostics = {
        "schema_version": "public-benchmark-local-environment-v1",
        "transport": "local_in_process_testclient",
        "database_url_scheme": "sqlite+aiosqlite",
        "module_checks": tuple(module_checks),
    }
    if failed is not None:
        return BenchmarkEnvironmentPreflight(
            ok=False,
            reason=str(failed["reason"]),
            diagnostics=MappingProxyType(diagnostics),
        )
    return BenchmarkEnvironmentPreflight(
        ok=True,
        reason=None,
        diagnostics=MappingProxyType(diagnostics),
    )


def local_environment_failure_result(
    preflight: BenchmarkEnvironmentPreflight,
    *,
    suite: str,
    case_count: int,
) -> dict[str, object]:
    reason = preflight.reason or "local_environment_unavailable"
    return {
        "suite": suite,
        "status": "failed",
        "ok": False,
        "checks": {
            "dataset_loaded": True,
            "case_count": case_count > 0,
            "auth_token_configured": True,
            "local_environment_ready": False,
        },
        "metrics": {
            "case_count": case_count,
            "benchmark_count": 0,
            "accuracy": 0.0,
            "local_environment_ready": False,
        },
        "benchmarks": [],
        "cases": [],
        "failures": [
            {
                "case_id": "suite_setup",
                "category": "setup",
                "reason": reason,
            }
        ],
        "diagnostics": {
            "local_environment": dict(preflight.diagnostics),
        },
    }


def _module_import_check(module_name: str, *, reason: str) -> dict[str, object]:
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        return {
            "module": module_name,
            "available": False,
            "reason": reason,
            "error_type": type(exc).__name__,
        }
    return {
        "module": module_name,
        "available": True,
        "reason": None,
        "error_type": None,
    }
