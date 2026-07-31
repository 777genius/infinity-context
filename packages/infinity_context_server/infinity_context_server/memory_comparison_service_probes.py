"""HTTP service probes for memory-comparison benchmark adapters."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite

from infinity_context_server.memory_comparison_mem0_contract import (
    MEM0_BENCHMARK_CAPABILITIES_PATH,
    evaluate_mem0_openapi_contract,
    evaluate_mem0_runtime_capabilities,
    mem0_openapi_request_properties,
    public_mem0_runtime_manifest,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    build_verified_mem0_runtime_attestation,
    public_mem0_runtime_attestation,
)
from infinity_context_server.memory_comparison_probe_transport import (
    ProbeHttpClient,
    VettedProbeTransport,
    vet_probe_target,
)

MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH = "/benchmark/attest-timestamp"
_MAX_RESPONSE_BODY_BYTES = 1_048_576
_SAFE_MEMORY_REQUEST_FIELDS = frozenset({"messages", "user_id", "run_id", "metadata", "timestamp"})


@dataclass(frozen=True)
class ServiceProbeOutcome:
    """Sanitized provider-neutral service probe result."""

    passed: bool
    reason: str | None = None
    reason_code: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)


def probe_memo_api(
    base_url: str,
    *,
    timeout_seconds: float,
    allowed_target_hosts: Sequence[str] = (),
    vetted_transport: VettedProbeTransport | None = None,
    target_resolver: Callable[[str], Sequence[str]] | None = None,
) -> ServiceProbeOutcome:
    health_path = "/v1/health"
    contract_path = "/openapi.json"
    timeout = _valid_timeout(timeout_seconds)
    if timeout is None:
        return _invalid_timeout("memo_api_probe_timeout_invalid", health_path)
    target = vet_probe_target(
        base_url,
        allowed_hosts=allowed_target_hosts,
        vetted_transport=vetted_transport,
    )
    if target is None or target_resolver is not None:
        return ServiceProbeOutcome(
            False,
            "memo probe target did not satisfy the explicit network policy",
            "memo_api_target_unsafe",
            {"health_path": health_path, "contract_path": contract_path},
        )
    try:
        return asyncio.run(
            _probe_memo_api(
                target.transport,
                base_url=target.base_url,
                timeout_seconds=timeout,
                health_path=health_path,
                contract_path=contract_path,
            )
        )
    except Exception as exc:
        return ServiceProbeOutcome(
            False,
            "memo API did not expose required health and OpenAPI probes",
            "memo_api_probe_failed",
            {
                "health_path": health_path,
                "contract_path": contract_path,
                "error_type": _safe_error_type(exc),
            },
        )


async def _probe_memo_api(
    transport: VettedProbeTransport,
    *,
    base_url: str,
    timeout_seconds: float,
    health_path: str,
    contract_path: str,
) -> ServiceProbeOutcome:
    required_paths = frozenset({"/v1/context/benchmark-search"})
    async with asyncio.timeout(timeout_seconds):
        async with transport.open_client(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        ) as client:
            health_response = await _bounded_request(
                client, method="GET", path=health_path, parse_json=False
            )
            contract_response = await _bounded_request(
                client, method="GET", path=contract_path, parse_json=True
            )
    available_paths = _openapi_paths(contract_response.payload)
    matched_paths = required_paths.intersection(available_paths)
    health_ok = health_response.status_code < 400
    contract_ok = contract_response.status_code < 400
    paths_ok = required_paths.issubset(available_paths)
    passed = health_ok and contract_ok and paths_ok
    reason = None
    reason_code = None
    if not health_ok:
        reason = "memo API health endpoint returned an error"
        reason_code = "memo_api_health_unreachable"
    elif not contract_ok:
        reason = "memo API OpenAPI contract endpoint returned an error"
        reason_code = "memo_api_contract_unreachable"
    elif not paths_ok:
        reason = "memo API contract is missing the benchmark-search endpoint"
        reason_code = "memo_api_contract_missing_required_paths"
    return ServiceProbeOutcome(
        passed,
        reason,
        reason_code,
        {
            "health_path": health_path,
            "health_status_code": health_response.status_code,
            "contract_path": contract_path,
            "contract_status_code": contract_response.status_code,
            "required_paths": sorted(required_paths),
            "matched_paths": sorted(matched_paths),
        },
    )


def probe_mem0_api(
    base_url: str,
    *,
    require_timestamp: bool,
    require_runtime_contract: bool,
    timeout_seconds: float,
    refresh_runtime_attestation: bool = False,
    benchmark_probe_token: str | None = None,
    run_id: str | None = None,
    probe_nonce: str | None = None,
    allowed_target_hosts: Sequence[str] = (),
    vetted_transport: VettedProbeTransport | None = None,
    target_resolver: Callable[[str], Sequence[str]] | None = None,
) -> ServiceProbeOutcome:
    path = "/openapi.json"
    timeout = _valid_timeout(timeout_seconds)
    if timeout is None:
        return _invalid_timeout("mem0_api_probe_timeout_invalid", path)
    target = vet_probe_target(
        base_url,
        allowed_hosts=allowed_target_hosts,
        vetted_transport=vetted_transport,
    )
    if target is None or target_resolver is not None:
        return ServiceProbeOutcome(
            False,
            "mem0 probe target did not satisfy the explicit network policy",
            "mem0_api_target_unsafe",
            {"path": path},
        )
    if refresh_runtime_attestation and not all(
        _nonempty_text(value) for value in (benchmark_probe_token, run_id, probe_nonce)
    ):
        return ServiceProbeOutcome(
            False,
            "managed mem0 probe binding inputs are missing",
            "mem0_runtime_attestation_binding_missing",
            {"path": path},
        )
    try:
        return asyncio.run(
            _probe_mem0_api(
                target.transport,
                base_url=target.base_url,
                target_identity_sha256=target.identity_sha256,
                require_timestamp=require_timestamp,
                require_runtime_contract=require_runtime_contract,
                timeout_seconds=timeout,
                refresh_runtime_attestation=refresh_runtime_attestation,
                benchmark_probe_token=benchmark_probe_token,
                run_id=run_id,
                probe_nonce=probe_nonce,
            )
        )
    except Exception as exc:
        return ServiceProbeOutcome(
            False,
            "mem0 API did not expose a valid benchmark contract",
            "mem0_api_openapi_probe_failed",
            {"path": path, "error_type": _safe_error_type(exc)},
        )


async def _probe_mem0_api(
    transport: VettedProbeTransport,
    *,
    base_url: str,
    target_identity_sha256: str,
    require_timestamp: bool,
    require_runtime_contract: bool,
    timeout_seconds: float,
    refresh_runtime_attestation: bool,
    benchmark_probe_token: str | None,
    run_id: str | None,
    probe_nonce: str | None,
) -> ServiceProbeOutcome:
    path = "/openapi.json"
    required_paths = frozenset({"/memories", "/search"})
    async with asyncio.timeout(timeout_seconds):
        async with transport.open_client(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        ) as client:
            response = await _bounded_request(client, method="GET", path=path, parse_json=True)
            payload = _require_mapping(response.payload, "openapi")
            pre_refresh_contract = evaluate_mem0_openapi_contract(
                payload, require_timestamp=require_timestamp
            )
            refresh_preconditions_met = (
                response.status_code < 400
                and required_paths.issubset(_openapi_paths(payload))
                and not pre_refresh_contract["violations"]
                and _openapi_operation_exists(
                    payload,
                    path=MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH,
                    method="post",
                )
            )
            refresh_response = None
            if refresh_runtime_attestation and refresh_preconditions_met:
                refresh_response = await _bounded_request(
                    client,
                    method="POST",
                    path=MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH,
                    parse_json=True,
                    headers={"X-Benchmark-Probe-Token": str(benchmark_probe_token)},
                    json_body={
                        "run_id": str(run_id),
                        "probe_nonce": str(probe_nonce),
                        "target_identity_sha256": target_identity_sha256,
                    },
                )
            capabilities_response = refresh_response
            if not refresh_runtime_attestation and require_runtime_contract:
                capabilities_response = await _bounded_request(
                    client,
                    method="GET",
                    path=MEM0_BENCHMARK_CAPABILITIES_PATH,
                    parse_json=True,
                )

            capabilities: Mapping[str, object] = {}
            if capabilities_response is not None and capabilities_response.status_code < 400:
                capabilities = _require_mapping(
                    capabilities_response.payload, "runtime capabilities"
                )
            return _evaluate_mem0_probe(
                response=response,
                payload=payload,
                capabilities_response=capabilities_response,
                capabilities=capabilities,
                target_identity_sha256=target_identity_sha256,
                require_timestamp=require_timestamp,
                require_runtime_contract=require_runtime_contract,
                refresh_runtime_attestation=refresh_runtime_attestation,
                benchmark_probe_token=benchmark_probe_token,
                run_id=run_id,
                probe_nonce=probe_nonce,
            )


def _evaluate_mem0_probe(
    *,
    response: _BoundedResponse,
    payload: Mapping[str, object],
    capabilities_response: _BoundedResponse | None,
    capabilities: Mapping[str, object],
    target_identity_sha256: str,
    require_timestamp: bool,
    require_runtime_contract: bool,
    refresh_runtime_attestation: bool,
    benchmark_probe_token: str | None,
    run_id: str | None,
    probe_nonce: str | None,
) -> ServiceProbeOutcome:
    required_paths = frozenset({"/memories", "/search"})
    available_paths = _openapi_paths(payload)
    matched_paths = required_paths.intersection(available_paths)
    observed_fields = mem0_openapi_request_properties(payload, path="/memories", method="post")
    timestamp_supported = "timestamp" in observed_fields
    paths_ok = required_paths.issubset(available_paths)
    exact_contract = evaluate_mem0_openapi_contract(payload, require_timestamp=require_timestamp)
    exact_violations = tuple(exact_contract["violations"])
    capability_issues = (
        evaluate_mem0_runtime_capabilities(capabilities, require_timestamp=require_timestamp)
        if require_runtime_contract
        else ()
    )
    capabilities_reachable = (
        capabilities_response is not None and capabilities_response.status_code < 400
        if require_runtime_contract
        else True
    )
    refresh_succeeded = (
        capabilities_response is not None and capabilities_response.status_code < 400
        if refresh_runtime_attestation
        else True
    )
    contract_passed = (
        response.status_code < 400
        and paths_ok
        and (not require_timestamp or timestamp_supported)
        and (not require_runtime_contract or not exact_violations)
        and capabilities_reachable
        and refresh_succeeded
        and not capability_issues
    )
    verified = None
    if refresh_runtime_attestation and refresh_succeeded:
        verified = build_verified_mem0_runtime_attestation(
            runtime_manifest=capabilities,
            benchmark_probe_token=str(benchmark_probe_token),
            openapi_fingerprint_sha256=exact_contract["fingerprint_sha256"],
            openapi_contract_violations=exact_violations,
            probe_passed=contract_passed,
            run_id=str(run_id),
            probe_nonce=str(probe_nonce),
            target_identity_sha256=target_identity_sha256,
        )
        refresh_succeeded = verified is not None
    passed = contract_passed and (not refresh_runtime_attestation or refresh_succeeded)
    reason, reason_code = _mem0_failure_reason(
        passed=passed,
        response_ok=response.status_code < 400,
        paths_ok=paths_ok,
        timestamp_supported=timestamp_supported,
        require_timestamp=require_timestamp,
        require_runtime_contract=require_runtime_contract,
        exact_violations=exact_violations,
        capabilities_reachable=capabilities_reachable,
        refresh_runtime_attestation=refresh_runtime_attestation,
        refresh_succeeded=refresh_succeeded,
        capability_issues=capability_issues,
    )
    public_attestation = (
        public_mem0_runtime_attestation(verified.payload) if verified is not None else None
    )
    return ServiceProbeOutcome(
        passed,
        reason,
        reason_code,
        {
            "path": "/openapi.json",
            "status_code": response.status_code,
            "required_paths": sorted(required_paths),
            "matched_paths": sorted(matched_paths),
            "timestamp_required": require_timestamp,
            "timestamp_supported": timestamp_supported,
            "memory_add_request_fields": sorted(observed_fields & _SAFE_MEMORY_REQUEST_FIELDS),
            "runtime_contract_required": require_runtime_contract,
            "runtime_attestation_refresh_requested": refresh_runtime_attestation,
            "runtime_attestation_refresh_path": (
                MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH if refresh_runtime_attestation else None
            ),
            "runtime_attestation_refresh_status_code": (
                capabilities_response.status_code
                if refresh_runtime_attestation and capabilities_response is not None
                else None
            ),
            "openapi_fingerprint_sha256": exact_contract["fingerprint_sha256"],
            "exact_contract_violations": list(exact_violations),
            "capabilities_path": MEM0_BENCHMARK_CAPABILITIES_PATH,
            "capabilities_status_code": (
                capabilities_response.status_code if capabilities_response is not None else None
            ),
            "capability_issues": list(capability_issues),
            "runtime_manifest": public_mem0_runtime_manifest(capabilities),
            "runtime_attestation": public_attestation,
            "verified_runtime_attestation": verified,
        },
    )


def _mem0_failure_reason(**state: object) -> tuple[str | None, str | None]:
    if state["passed"]:
        return None, None
    if not state["response_ok"]:
        return "mem0 API OpenAPI endpoint returned an error", "mem0_api_openapi_unreachable"
    if not state["paths_ok"]:
        return (
            "mem0 API contract is missing required OSS benchmark endpoints",
            "mem0_api_contract_missing_required_paths",
        )
    if state["require_timestamp"] and not state["timestamp_supported"]:
        return (
            "mem0 API contract is missing timestamp support for LoCoMo ingest",
            "mem0_api_contract_missing_timestamp_field",
        )
    if state["require_runtime_contract"] and state["exact_violations"]:
        return (
            "mem0 API does not satisfy the exact benchmark request contract",
            "mem0_api_exact_contract_invalid",
        )
    if state["require_runtime_contract"] and not state["capabilities_reachable"]:
        return (
            "mem0 API did not expose benchmark runtime capabilities",
            "mem0_runtime_capabilities_unreachable",
        )
    if state["refresh_runtime_attestation"] and not state["refresh_succeeded"]:
        return (
            "mem0 API rejected the same-run runtime attestation refresh",
            "mem0_runtime_attestation_refresh_failed",
        )
    if state["capability_issues"]:
        return (
            "mem0 runtime provenance or timestamp capabilities are not publishable",
            "mem0_runtime_capabilities_invalid",
        )
    return "mem0 API contract probe failed", "mem0_api_openapi_unreachable"


def _openapi_paths(payload: object) -> frozenset[str]:
    paths = payload.get("paths") if isinstance(payload, Mapping) else None
    return frozenset(str(path) for path in paths) if isinstance(paths, Mapping) else frozenset()


def _openapi_operation_exists(payload: object, *, path: str, method: str) -> bool:
    paths = payload.get("paths") if isinstance(payload, Mapping) else None
    operation = paths.get(path) if isinstance(paths, Mapping) else None
    return isinstance(operation, Mapping) and isinstance(operation.get(method.casefold()), Mapping)


@dataclass(frozen=True)
class _BoundedResponse:
    status_code: int
    payload: object


class _ResponseBodyTooLarge(ValueError):
    pass


class _UnsupportedContentEncoding(ValueError):
    pass


async def _bounded_request(
    client: ProbeHttpClient,
    *,
    method: str,
    path: str,
    parse_json: bool,
    headers: Mapping[str, str] | None = None,
    json_body: Mapping[str, object] | None = None,
) -> _BoundedResponse:
    async with client.stream(method, path, headers=headers, json=json_body) as response:
        status_code = response.status_code
        if (
            isinstance(status_code, bool)
            or not isinstance(status_code, int)
            or not 100 <= status_code <= 599
        ):
            raise ValueError("service probe returned an invalid HTTP status")
        encoding = str(response.headers.get("content-encoding", "")).strip().casefold()
        if encoding not in {"", "identity"}:
            raise _UnsupportedContentEncoding("compressed probe responses are not accepted")
        body = await _bounded_response_body(response)
    if not parse_json or status_code >= 400:
        return _BoundedResponse(status_code, {})
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("service probe returned invalid JSON") from exc
    return _BoundedResponse(status_code, payload)


async def _bounded_response_body(response: object) -> bytes:
    iterator = getattr(response, "aiter_raw", None)
    if not callable(iterator):
        raise TypeError("HTTP response does not support raw bounded streaming")
    chunks: list[bytes] = []
    total = 0
    async for chunk in iterator(chunk_size=65_536):
        if not isinstance(chunk, bytes):
            raise TypeError("HTTP response stream yielded non-bytes")
        total += len(chunk)
        if total > _MAX_RESPONSE_BODY_BYTES:
            raise _ResponseBodyTooLarge("service probe response body exceeds limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _require_mapping(payload: object, label: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} response must be a JSON object")
    return payload


def _valid_timeout(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    timeout = float(value)
    return timeout if isfinite(timeout) and timeout > 0 else None


def _invalid_timeout(reason_code: str, path: str) -> ServiceProbeOutcome:
    return ServiceProbeOutcome(
        False,
        "service probe timeout must be finite and positive",
        reason_code,
        {"path": path},
    )


def _safe_error_type(exc: Exception) -> str:
    if isinstance(exc, _ResponseBodyTooLarge):
        return "response_body_too_large"
    if isinstance(exc, TimeoutError):
        return "deadline_exceeded"
    if isinstance(exc, _UnsupportedContentEncoding):
        return "unsupported_content_encoding"
    if isinstance(exc, ValueError):
        return "invalid_response"
    return "request_failed"


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 4_096


__all__ = (
    "ServiceProbeOutcome",
    "probe_mem0_api",
    "probe_memo_api",
)
