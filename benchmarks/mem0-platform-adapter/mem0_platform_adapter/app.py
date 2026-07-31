"""Strict FastAPI compatibility surface expected by the benchmark harness."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Query

from mem0_platform_adapter.manifest import capabilities_manifest, manifest_is_ready
from mem0_platform_adapter.models import (
    AddRequest,
    AddResponse,
    BenchmarkAttestationRefreshRequest,
    BenchmarkAuthChallengeRequest,
    BenchmarkAuthChallengeResponse,
    DeleteResponse,
    HealthResponse,
    SafeIdentifier,
    SearchRequest,
    SearchResponse,
)
from mem0_platform_adapter.port import PlatformPort
from mem0_platform_adapter.sdk_platform import platform_from_environment
from mem0_platform_adapter.service import (
    AdapterError,
    Mem0CompatibilityService,
    PollingPolicy,
)


def create_app(
    platform: PlatformPort | None = None,
    *,
    policy: PollingPolicy | None = None,
    sleeper: Any = None,
    token_factory: Callable[[], str] | None = None,
    attest_on_startup: bool = True,
) -> FastAPI:
    selected_platform = platform or platform_from_environment()
    service_kwargs: dict[str, Any] = {"policy": policy}
    if sleeper is not None:
        service_kwargs["sleeper"] = sleeper
    if token_factory is not None:
        service_kwargs["token_factory"] = token_factory
    service = Mem0CompatibilityService(selected_platform, **service_kwargs)
    latest_refresh_binding: dict[str, str | None] | None = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if attest_on_startup and selected_platform.configured:
            try:
                service.attest_timestamp()
            except Exception:
                service.mark_attestation_failed("startup_attestation_failed")
        yield

    app = FastAPI(
        title="Mem0 Platform benchmark adapter",
        version="2",
        lifespan=lifespan,
    )

    @app.exception_handler(AdapterError)
    async def adapter_error_handler(_request: Any, exc: AdapterError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.status_code, content={"detail": exc.code})

    def runtime_manifest() -> dict[str, Any]:
        return capabilities_manifest(
            configured=selected_platform.configured,
            attestation=service.attestation,
            policy=service.policy,
            wrapper_revision=os.getenv("MEM0_ADAPTER_SOURCE_REVISION"),
        )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        configured = selected_platform.configured
        ready = manifest_is_ready(runtime_manifest())
        return HealthResponse(
            status="ok" if ready else ("not_ready" if configured else "unconfigured"),
            configured=configured,
            ready=ready,
            attestation_status=service.attestation.status,
        )

    @app.post("/memories", response_model=AddResponse)
    def add_memories(request: AddRequest) -> AddResponse:
        if not selected_platform.configured:
            raise HTTPException(status_code=503, detail="missing_mem0_api_key")
        return AddResponse(results=service.add(request))

    @app.post("/search", response_model=SearchResponse)
    def search_memories(request: SearchRequest) -> SearchResponse:
        if not selected_platform.configured:
            raise HTTPException(status_code=503, detail="missing_mem0_api_key")
        return SearchResponse(results=service.search(request))

    @app.delete("/memories", response_model=DeleteResponse)
    def delete_memories(
        user_id: Annotated[SafeIdentifier, Query()],
        run_id: Annotated[SafeIdentifier, Query()],
    ) -> DeleteResponse:
        if not selected_platform.configured:
            raise HTTPException(status_code=503, detail="missing_mem0_api_key")
        proof = service.delete(user_id=user_id, run_id=run_id)
        return DeleteResponse(
            deleted=proof.deleted,
            verified_absent=proof.verified_absent,
        )

    @app.get("/benchmark/capabilities")
    def benchmark_capabilities() -> dict[str, Any]:
        payload = runtime_manifest()
        if latest_refresh_binding is not None:
            payload["refresh_binding"] = dict(latest_refresh_binding)
        return payload

    @app.post(
        "/benchmark/auth-challenge",
        response_model=BenchmarkAuthChallengeResponse,
    )
    def benchmark_auth_challenge(
        request: BenchmarkAuthChallengeRequest,
        probe_token: Annotated[
            str | None,
            Header(alias="X-Benchmark-Probe-Token"),
        ] = None,
    ) -> BenchmarkAuthChallengeResponse:
        expected_token = os.getenv("MEM0_BENCHMARK_PROBE_TOKEN", "").strip()
        if not expected_token:
            raise HTTPException(status_code=503, detail="missing_benchmark_probe_token")
        if not probe_token or not secrets.compare_digest(probe_token, expected_token):
            raise HTTPException(status_code=401, detail="invalid_benchmark_probe_token")
        schema_version = "mem0-benchmark-auth-challenge.v1"
        message = f"{schema_version}\n{request.nonce}".encode()
        return BenchmarkAuthChallengeResponse(
            schema_version=schema_version,
            nonce_sha256=hashlib.sha256(request.nonce.encode()).hexdigest(),
            signature=hmac.new(expected_token.encode(), message, hashlib.sha256).hexdigest(),
        )

    @app.post("/benchmark/attest-timestamp")
    def refresh_benchmark_attestation(
        request: BenchmarkAttestationRefreshRequest,
        probe_token: Annotated[
            str | None,
            Header(alias="X-Benchmark-Probe-Token"),
        ] = None,
    ) -> dict[str, Any]:
        nonlocal latest_refresh_binding
        expected_token = os.getenv("MEM0_BENCHMARK_PROBE_TOKEN", "").strip()
        if not expected_token:
            raise HTTPException(status_code=503, detail="missing_benchmark_probe_token")
        if not probe_token or not secrets.compare_digest(probe_token, expected_token):
            raise HTTPException(status_code=401, detail="invalid_benchmark_probe_token")
        if not selected_platform.configured:
            raise HTTPException(status_code=503, detail="missing_mem0_api_key")
        attestation = service.attest_timestamp()
        latest_refresh_binding = {
            "status": attestation.status,
            "run_id_sha256": hashlib.sha256(request.run_id.encode()).hexdigest(),
            "probe_nonce_sha256": hashlib.sha256(request.probe_nonce.encode()).hexdigest(),
            "target_identity_sha256": request.target_identity_sha256,
            "refreshed_at": attestation.checked_at,
        }
        payload = benchmark_capabilities()
        manifest_fingerprint = _fingerprint(payload)
        payload["refresh_witness"] = {
            "algorithm": "hmac-sha256",
            "manifest_fingerprint_sha256": manifest_fingerprint,
            "signature": _refresh_witness_signature(
                expected_token,
                latest_refresh_binding,
                manifest_fingerprint,
            ),
        }
        return payload

    return app


app = create_app()


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _refresh_witness_signature(
    token: str,
    binding: dict[str, str | None],
    manifest_fingerprint: str,
) -> str:
    message = "\n".join(
        (
            "mem0-benchmark-runtime-witness.v1",
            str(binding.get("run_id_sha256") or ""),
            str(binding.get("probe_nonce_sha256") or ""),
            str(binding.get("target_identity_sha256") or ""),
            str(binding.get("refreshed_at") or ""),
            manifest_fingerprint,
        )
    ).encode()
    return hmac.new(token.encode(), message, hashlib.sha256).hexdigest()
