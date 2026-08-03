"""Fail-closed service-probe policy for memory-comparison benchmarks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from infinity_context_server.mem0_benchmark_auth_challenge import (
    MEM0_BENCHMARK_AUTH_CHALLENGE_PATH,
    MEM0_BENCHMARK_PROBE_TOKEN_ENV,
    is_safe_auth_challenge_target,
    probe_mem0_benchmark_auth_challenge,
)

MEM0_BENCHMARK_REQUIRE_RUNTIME_CONTRACT_ENV = (
    "MEM0_BENCHMARK_REQUIRE_RUNTIME_CONTRACT"
)
_TRUE_MARKER_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_MARKER_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class ServiceProbeCheck:
    """One sanitized service-probe result."""

    name: str
    passed: bool
    reason: str | None = None
    reason_code: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ServiceProbeOutcome:
    """Service-probe checks plus the resolved managed-runtime policy."""

    checks: tuple[ServiceProbeCheck, ...]
    require_mem0_runtime_contract: bool
    skipped: bool = False


def run_memory_comparison_service_probe(
    *,
    memo_api_url: str,
    mem0_url: str,
    timeout_seconds: float,
    probe_services: bool,
    require_mem0_runtime_contract: bool,
    env: Mapping[str, str],
) -> ServiceProbeOutcome:
    """Resolve probe policy and execute only a fail-closed, safe probe sequence."""

    marker = _runtime_contract_marker(env)
    if marker is None:
        return ServiceProbeOutcome(
            checks=(
                ServiceProbeCheck(
                    name="mem0_runtime_contract_marker_valid",
                    passed=False,
                    reason="managed mem0 runtime marker has an invalid value",
                    reason_code="mem0_runtime_contract_marker_invalid",
                ),
            ),
            require_mem0_runtime_contract=True,
        )

    token = str(env.get(MEM0_BENCHMARK_PROBE_TOKEN_ENV, ""))
    require_runtime_contract = (
        require_mem0_runtime_contract or marker or MEM0_BENCHMARK_PROBE_TOKEN_ENV in env
    )
    if not probe_services:
        if require_runtime_contract:
            return ServiceProbeOutcome(
                checks=(
                    ServiceProbeCheck(
                        name="mem0_runtime_contract_probe_required",
                        passed=False,
                        reason="managed mem0 runtime contract requires service probing",
                        reason_code="mem0_runtime_contract_probe_required",
                    ),
                ),
                require_mem0_runtime_contract=True,
            )
        return ServiceProbeOutcome(
            checks=(),
            require_mem0_runtime_contract=False,
            skipped=True,
        )

    if not require_runtime_contract:
        return ServiceProbeOutcome(
            checks=(
                _probe_memo_api(memo_api_url, timeout_seconds=timeout_seconds),
                _probe_mem0_api(mem0_url, timeout_seconds=timeout_seconds),
            ),
            require_mem0_runtime_contract=False,
        )

    if not token.strip():
        return ServiceProbeOutcome(
            checks=(
                ServiceProbeCheck(
                    name="mem0_benchmark_auth_challenge",
                    passed=False,
                    reason="managed mem0 runtime probe token is not configured",
                    reason_code="mem0_benchmark_probe_token_missing",
                    details={
                        "path": MEM0_BENCHMARK_AUTH_CHALLENGE_PATH,
                        "token_configured": False,
                    },
                ),
            ),
            require_mem0_runtime_contract=True,
        )
    if not is_safe_auth_challenge_target(mem0_url):
        return ServiceProbeOutcome(
            checks=(
                ServiceProbeCheck(
                    name="mem0_benchmark_auth_challenge",
                    passed=False,
                    reason=(
                        "managed mem0 auth challenge requires HTTPS or a loopback target"
                    ),
                    reason_code="mem0_benchmark_auth_challenge_unsafe_target",
                    details={"path": MEM0_BENCHMARK_AUTH_CHALLENGE_PATH},
                ),
            ),
            require_mem0_runtime_contract=True,
        )

    challenge = _probe_mem0_auth_challenge(
        mem0_url,
        token=token,
        timeout_seconds=timeout_seconds,
    )
    if not challenge.passed:
        return ServiceProbeOutcome(
            checks=(challenge,),
            require_mem0_runtime_contract=True,
        )

    checks = [challenge]
    checks.append(_probe_memo_api(memo_api_url, timeout_seconds=timeout_seconds))
    checks.append(_probe_mem0_api(mem0_url, timeout_seconds=timeout_seconds))
    return ServiceProbeOutcome(
        checks=tuple(checks),
        require_mem0_runtime_contract=True,
    )


def _probe_mem0_auth_challenge(
    base_url: str,
    *,
    token: str,
    timeout_seconds: float,
) -> ServiceProbeCheck:
    probe = probe_mem0_benchmark_auth_challenge(
        base_url,
        token=token,
        timeout_seconds=timeout_seconds,
    )
    details: dict[str, object] = {"path": MEM0_BENCHMARK_AUTH_CHALLENGE_PATH}
    if probe.status_code is not None:
        details["status_code"] = probe.status_code
    if probe.error_type is not None:
        details["error_type"] = probe.error_type
    return ServiceProbeCheck(
        name="mem0_benchmark_auth_challenge",
        passed=probe.passed,
        reason=(
            None
            if probe.passed
            else "managed mem0 auth challenge response failed verification"
        ),
        reason_code=probe.reason_code,
        details=details,
    )


def _probe_memo_api(
    base_url: str,
    *,
    timeout_seconds: float,
) -> ServiceProbeCheck:
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
        return ServiceProbeCheck(
            name="memo_api_reachable",
            passed=False,
            reason="memo API did not respond to unauthenticated health probe",
            reason_code="memo_api_probe_failed",
            details={"path": path, "error_type": type(exc).__name__},
        )
    passed = response.status_code < 400
    return ServiceProbeCheck(
        name="memo_api_reachable",
        passed=passed,
        reason=None if passed else "memo API health endpoint did not return HTTP 2xx/3xx",
        reason_code=None if passed else "memo_api_unhealthy_status",
        details={"path": path, "status_code": response.status_code},
    )


def _probe_mem0_api(
    base_url: str,
    *,
    timeout_seconds: float,
) -> ServiceProbeCheck:
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
        return ServiceProbeCheck(
            name="mem0_api_reachable",
            passed=False,
            reason="mem0 API did not expose an unauthenticated OpenAPI contract",
            reason_code="mem0_api_openapi_probe_failed",
            details={"path": path, "error_type": type(exc).__name__},
        )

    available_paths = _openapi_paths(payload)
    matched_paths = required_paths.intersection(available_paths)
    passed = response.status_code < 400 and required_paths.issubset(available_paths)
    return ServiceProbeCheck(
        name="mem0_api_reachable",
        passed=passed,
        reason=(
            None
            if passed
            else "mem0 API contract is missing required OSS benchmark endpoints"
        ),
        reason_code=None if passed else "mem0_api_contract_missing_required_paths",
        details={
            "path": path,
            "status_code": response.status_code,
            "required_paths": sorted(required_paths),
            "matched_paths": sorted(matched_paths),
        },
    )


def _openapi_paths(payload: object) -> frozenset[str]:
    if not isinstance(payload, Mapping):
        return frozenset()
    paths = payload.get("paths")
    if not isinstance(paths, Mapping):
        return frozenset()
    return frozenset(str(path) for path in paths)


def _runtime_contract_marker(env: Mapping[str, str]) -> bool | None:
    if MEM0_BENCHMARK_REQUIRE_RUNTIME_CONTRACT_ENV not in env:
        return False
    value = str(env.get(MEM0_BENCHMARK_REQUIRE_RUNTIME_CONTRACT_ENV, ""))
    normalized = value.strip().lower()
    if normalized in _TRUE_MARKER_VALUES:
        return True
    if normalized in _FALSE_MARKER_VALUES:
        return False
    return None
