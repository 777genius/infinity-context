"""Safe preflight checks for memory-comparison benchmark runs."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

MEMORY_COMPARISON_PREFLIGHT_SUITE = "memory-comparison-preflight"
MEMORY_COMPARISON_PREFLIGHT_SCHEMA_VERSION = "memory-comparison-preflight.v1"
_FAST_CASE_SETS = frozenset(
    {
        "locomo-fast",
        "locomo-fast-multi-hop",
        "locomo-fast-temporal",
        "locomo-fast-open-domain",
        "locomo-fast-single-hop",
    }
)
_REQUIRED_FAST_CUTOFFS = frozenset({10, 20, 50, 200})


@dataclass(frozen=True)
class MemoryComparisonPreflightConfig:
    """Input contract for memory-comparison readiness checks."""

    dataset_path: Path
    memo_api_url: str
    mem0_url: str
    case_set: str
    locomo_ingest_mode: str
    report_mode: str
    top_k: int
    top_k_cutoffs: Sequence[int]
    allow_live: bool
    allow_paid_llm: bool
    answerer_provider: str
    judge_provider: str
    answerer_model: str | None
    judge_model: str | None
    openai_api_key_env: str
    mem0_api_key_env: str
    auth_token_configured: bool
    probe_services: bool = False
    probe_timeout_seconds: float = 1.5
    env: Mapping[str, str] = field(default_factory=lambda: os.environ)


@dataclass(frozen=True)
class MemoryComparisonPreflightCheck:
    """One sanitized preflight check."""

    name: str
    passed: bool
    severity: str
    reason: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def to_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "severity": self.severity,
            "reason": self.reason,
            "details": dict(self.details),
        }


def run_memory_comparison_preflight(
    config: MemoryComparisonPreflightConfig,
) -> dict[str, object]:
    """Return a sanitized readiness report without starting benchmark state."""

    checks = [
        _dataset_check(config.dataset_path),
        _url_check("memo_api_url_valid", config.memo_api_url),
        _url_check("mem0_url_valid", config.mem0_url),
        _required_check(
            "allow_live_gate",
            passed=config.allow_live,
            reason="pass --allow-live before live benchmark execution",
        ),
        _required_check(
            "memo_auth_token_configured",
            passed=config.auth_token_configured,
            reason="configure MEMORY_EVAL_AUTH_TOKEN or MEMORY_SERVICE_TOKEN",
        ),
        *_llm_checks(config),
        _warning_check(
            "mem0_api_key_configured",
            passed=_env_is_set(config.env, config.mem0_api_key_env),
            reason=(
                f"{config.mem0_api_key_env} is not set; this is allowed only when "
                "the target mem0 OSS wrapper accepts unauthenticated requests"
            ),
            details={
                "env_var": config.mem0_api_key_env,
                "set": _env_is_set(config.env, config.mem0_api_key_env),
            },
        ),
        *_fast_readiness_checks(config),
    ]
    if config.probe_services:
        checks.extend(_service_probe_checks(config))
    else:
        checks.append(
            MemoryComparisonPreflightCheck(
                name="service_probe_skipped",
                passed=False,
                severity="info",
                reason="pass --preflight-probe-services to verify HTTP reachability",
            )
        )

    failed_required = tuple(
        check for check in checks if check.severity == "required" and not check.passed
    )
    warnings = tuple(
        check for check in checks if check.severity == "warning" and not check.passed
    )
    fast_blockers = tuple(
        check for check in checks if check.severity == "fast-readiness" and not check.passed
    )
    service_probe_failures = tuple(
        check for check in checks if check.severity == "service-probe" and not check.passed
    )
    blocking_failures = (*failed_required, *service_probe_failures)
    ok = not blocking_failures
    safe_to_run_paid_llm = _safe_to_run_paid_llm(config, checks)
    safe_to_run_live = ok and safe_to_run_paid_llm and not service_probe_failures
    ready_for_locomo_fast = safe_to_run_live and not fast_blockers
    status = "failed" if not ok else "degraded" if warnings or fast_blockers else "ok"
    return {
        "suite": MEMORY_COMPARISON_PREFLIGHT_SUITE,
        "schema_version": MEMORY_COMPARISON_PREFLIGHT_SCHEMA_VERSION,
        "ok": ok,
        "status": status,
        "safe_to_run_live": safe_to_run_live,
        "safe_to_run_paid_llm": safe_to_run_paid_llm,
        "ready_for_locomo_fast": ready_for_locomo_fast,
        "failed_checks": [check.name for check in blocking_failures],
        "warnings": [check.name for check in warnings],
        "fast_readiness_blockers": [check.name for check in fast_blockers],
        "checks": [check.to_payload() for check in checks],
        "diagnostics": {
            "dataset_path_label": config.dataset_path.name,
            "case_set": config.case_set,
            "locomo_ingest_mode": config.locomo_ingest_mode,
            "report_mode": config.report_mode,
            "top_k": config.top_k,
            "top_k_cutoffs": list(_normalized_cutoffs(config.top_k_cutoffs)),
            "answerer_provider": config.answerer_provider,
            "judge_provider": config.judge_provider,
            "uses_openai": _uses_openai(config),
            "probe_services": config.probe_services,
            "secrets": {
                "auth_token_configured": config.auth_token_configured,
                config.mem0_api_key_env: _env_is_set(config.env, config.mem0_api_key_env),
                config.openai_api_key_env: _env_is_set(config.env, config.openai_api_key_env),
                "OPENAI_API_KEY": _env_is_set(config.env, "OPENAI_API_KEY"),
            },
        },
    }


def _dataset_check(dataset_path: Path) -> MemoryComparisonPreflightCheck:
    if not dataset_path.exists():
        return _required_check(
            "dataset_readable",
            passed=False,
            reason="dataset file does not exist",
            details={"dataset_path_label": dataset_path.name},
        )
    if not dataset_path.is_file():
        return _required_check(
            "dataset_readable",
            passed=False,
            reason="dataset path is not a file",
            details={"dataset_path_label": dataset_path.name},
        )
    try:
        size_bytes = dataset_path.stat().st_size
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _required_check(
            "dataset_readable",
            passed=False,
            reason="dataset file is not readable JSON",
            details={
                "dataset_path_label": dataset_path.name,
                "error_type": type(exc).__name__,
            },
        )
    top_level_count = _top_level_count(payload)
    return _required_check(
        "dataset_readable",
        passed=size_bytes > 0 and top_level_count > 0,
        reason="dataset must contain at least one top-level case/sample",
        details={
            "dataset_path_label": dataset_path.name,
            "size_bytes": size_bytes,
            "top_level_type": type(payload).__name__,
            "top_level_count": top_level_count,
        },
    )


def _url_check(name: str, value: str) -> MemoryComparisonPreflightCheck:
    parsed = urlparse(str(value or ""))
    valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    return _required_check(
        name,
        passed=valid,
        reason="URL must use http(s) and include a host",
        details={
            "scheme": parsed.scheme or None,
            "host_configured": bool(parsed.netloc),
        },
    )


def _llm_checks(
    config: MemoryComparisonPreflightConfig,
) -> tuple[MemoryComparisonPreflightCheck, ...]:
    if not _uses_openai(config):
        return (
            _required_check(
                "paid_llm_gate",
                passed=True,
                reason=None,
                details={"uses_openai": False},
            ),
        )
    checks: list[MemoryComparisonPreflightCheck] = [
        _required_check(
            "paid_llm_gate",
            passed=config.allow_paid_llm,
            reason="pass --allow-paid-llm before OpenAI answerer or judge calls",
            details={"uses_openai": True},
        ),
        _required_check(
            "openai_api_key_configured",
            passed=_env_is_set(config.env, config.openai_api_key_env)
            or _env_is_set(config.env, "OPENAI_API_KEY"),
            reason=f"set {config.openai_api_key_env} or OPENAI_API_KEY",
            details={
                config.openai_api_key_env: _env_is_set(config.env, config.openai_api_key_env),
                "OPENAI_API_KEY": _env_is_set(config.env, "OPENAI_API_KEY"),
            },
        ),
    ]
    if config.answerer_provider == "openai":
        checks.append(
            _required_check(
                "openai_answerer_model_configured",
                passed=bool(
                    (config.answerer_model or "").strip()
                    or _env_is_set(config.env, "MEMORY_COMPARISON_ANSWERER_MODEL")
                ),
                reason=(
                    "pass --answerer-model or set "
                    "MEMORY_COMPARISON_ANSWERER_MODEL"
                ),
            )
        )
    if config.judge_provider == "openai":
        checks.append(
            _required_check(
                "openai_judge_model_configured",
                passed=bool(
                    (config.judge_model or "").strip()
                    or _env_is_set(config.env, "MEMORY_COMPARISON_JUDGE_MODEL")
                ),
                reason="pass --judge-model or set MEMORY_COMPARISON_JUDGE_MODEL",
            )
        )
    return tuple(checks)


def _fast_readiness_checks(
    config: MemoryComparisonPreflightConfig,
) -> tuple[MemoryComparisonPreflightCheck, ...]:
    cutoffs = frozenset(_normalized_cutoffs(config.top_k_cutoffs))
    return (
        _fast_check(
            "locomo_fast_case_set",
            passed=config.case_set in _FAST_CASE_SETS,
            reason="use --case-set locomo-fast or another locomo-fast subset",
            details={"case_set": config.case_set},
        ),
        _fast_check(
            "official_turn_ingest_mode",
            passed=config.locomo_ingest_mode == "official-turns",
            reason="use --locomo-ingest-mode official-turns for mem0-style parity",
            details={"locomo_ingest_mode": config.locomo_ingest_mode},
        ),
        _fast_check(
            "top_k_fast_gate",
            passed=config.top_k >= 200,
            reason="use --top-k 200 or higher before evaluating evidence-ref rank gates",
            details={"top_k": config.top_k},
        ),
        _fast_check(
            "top_k_cutoffs_fast_gate",
            passed=_REQUIRED_FAST_CUTOFFS.issubset(cutoffs),
            reason="include --top-k-cutoff 10/20/50/200 for comparable fast gates",
            details={
                "configured": sorted(cutoffs),
                "required": sorted(_REQUIRED_FAST_CUTOFFS),
            },
        ),
        _fast_check(
            "compact_report_mode",
            passed=config.report_mode == "compact",
            reason="use --report-mode compact for fast iteration unless debugging cases",
            details={"report_mode": config.report_mode},
        ),
    )


def _service_probe_checks(
    config: MemoryComparisonPreflightConfig,
) -> tuple[MemoryComparisonPreflightCheck, ...]:
    return (
        _probe_memo_api(
            "memo_api_reachable",
            config.memo_api_url,
            timeout_seconds=config.probe_timeout_seconds,
        ),
        _probe_mem0_api(
            "mem0_api_reachable",
            config.mem0_url,
            timeout_seconds=config.probe_timeout_seconds,
        ),
    )


def _probe_memo_api(
    name: str,
    base_url: str,
    *,
    timeout_seconds: float,
) -> MemoryComparisonPreflightCheck:
    path = "/v1/health"
    try:
        import httpx

        with httpx.Client(
            base_url=str(base_url).rstrip("/"),
            timeout=max(0.1, timeout_seconds),
            follow_redirects=False,
        ) as client:
            response = client.get(path)
    except Exception as exc:
        return MemoryComparisonPreflightCheck(
            name=name,
            passed=False,
            severity="service-probe",
            reason="memo API did not respond to unauthenticated health probe",
            details={"path": path, "error_type": type(exc).__name__},
        )
    passed = response.status_code < 400
    return MemoryComparisonPreflightCheck(
        name=name,
        passed=passed,
        severity="service-probe",
        reason=None if passed else "memo API health endpoint did not return HTTP 2xx/3xx",
        details={"path": path, "status_code": response.status_code},
    )


def _probe_mem0_api(
    name: str,
    base_url: str,
    *,
    timeout_seconds: float,
) -> MemoryComparisonPreflightCheck:
    path = "/openapi.json"
    required_paths = frozenset({"/memories", "/search"})
    try:
        import httpx

        with httpx.Client(
            base_url=str(base_url).rstrip("/"),
            timeout=max(0.1, timeout_seconds),
            follow_redirects=False,
        ) as client:
            response = client.get(path)
            payload = response.json() if response.status_code < 400 else {}
    except Exception as exc:
        return MemoryComparisonPreflightCheck(
            name=name,
            passed=False,
            severity="service-probe",
            reason="mem0 API did not expose an unauthenticated OpenAPI contract",
            details={"path": path, "error_type": type(exc).__name__},
        )

    available_paths = _openapi_paths(payload)
    matched_paths = required_paths.intersection(available_paths)
    passed = response.status_code < 400 and required_paths.issubset(available_paths)
    return MemoryComparisonPreflightCheck(
        name=name,
        passed=passed,
        severity="service-probe",
        reason=None if passed else "mem0 API contract is missing required OSS benchmark endpoints",
        details={
            "path": path,
            "status_code": response.status_code,
            "required_paths": sorted(required_paths),
            "matched_paths": sorted(matched_paths),
        },
    )


def _required_check(
    name: str,
    *,
    passed: bool,
    reason: str | None,
    details: Mapping[str, object] | None = None,
) -> MemoryComparisonPreflightCheck:
    return MemoryComparisonPreflightCheck(
        name=name,
        passed=passed,
        severity="required",
        reason=None if passed else reason,
        details=details or {},
    )


def _warning_check(
    name: str,
    *,
    passed: bool,
    reason: str,
    details: Mapping[str, object] | None = None,
) -> MemoryComparisonPreflightCheck:
    return MemoryComparisonPreflightCheck(
        name=name,
        passed=passed,
        severity="warning",
        reason=None if passed else reason,
        details=details or {},
    )


def _fast_check(
    name: str,
    *,
    passed: bool,
    reason: str,
    details: Mapping[str, object] | None = None,
) -> MemoryComparisonPreflightCheck:
    return MemoryComparisonPreflightCheck(
        name=name,
        passed=passed,
        severity="fast-readiness",
        reason=None if passed else reason,
        details=details or {},
    )


def _safe_to_run_paid_llm(
    config: MemoryComparisonPreflightConfig,
    checks: Sequence[MemoryComparisonPreflightCheck],
) -> bool:
    if not _uses_openai(config):
        return True
    return not any(
        check.name.startswith("openai_") and not check.passed
        or check.name == "paid_llm_gate" and not check.passed
        for check in checks
    )


def _uses_openai(config: MemoryComparisonPreflightConfig) -> bool:
    return config.answerer_provider == "openai" or config.judge_provider == "openai"


def _env_is_set(env: Mapping[str, str], name: str) -> bool:
    return bool(str(env.get(name, "")).strip())


def _normalized_cutoffs(values: Sequence[int]) -> tuple[int, ...]:
    return tuple(sorted({int(value) for value in values if int(value) > 0}))


def _top_level_count(payload: object) -> int:
    if isinstance(payload, Sequence) and not isinstance(payload, str | bytes):
        return len(payload)
    if isinstance(payload, Mapping):
        for key in ("data", "cases", "samples", "conversations"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, str | bytes):
                return len(value)
        return len(payload)
    return 0


def _openapi_paths(payload: object) -> frozenset[str]:
    if not isinstance(payload, Mapping):
        return frozenset()
    paths = payload.get("paths")
    if not isinstance(paths, Mapping):
        return frozenset()
    return frozenset(str(path) for path in paths)
