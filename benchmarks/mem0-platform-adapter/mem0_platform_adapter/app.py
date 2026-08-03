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

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Security
from fastapi.security import APIKeyHeader

from mem0_platform_adapter.manifest import capabilities_manifest, manifest_is_ready
from mem0_platform_adapter.models import (
    AddRequest,
    AddResponse,
    BenchmarkAttestationRefreshRequest,
    BenchmarkAuthChallengeRequest,
    BenchmarkAuthChallengeResponse,
    DeleteResponse,
    HealthResponse,
    PersistedMemoryIdentity,
    PersistedSourceMetadata,
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

_INGRESS_API_KEY_ENV = "MEM0_ADAPTER_INGRESS_API_KEY"
_INGRESS_API_KEY_HEADER_NAME = "X-API-Key"
_INGRESS_API_KEY_HEADER = APIKeyHeader(
    name=_INGRESS_API_KEY_HEADER_NAME,
    scheme_name="Mem0AdapterIngressApiKey",
    description="Dedicated authentication for benchmark data-plane operations.",
    auto_error=False,
)


def _configured_ingress_api_key() -> str | None:
    value = os.getenv(_INGRESS_API_KEY_ENV)
    return value if value is not None and value and value == value.strip() else None


def _require_ingress_api_key(
    request: Request,
    presented_key: Annotated[str | None, Security(_INGRESS_API_KEY_HEADER)],
) -> None:
    expected_key = _configured_ingress_api_key()
    if expected_key is None:
        raise HTTPException(status_code=503, detail="missing_adapter_ingress_api_key")
    presented_values = request.headers.getlist(_INGRESS_API_KEY_HEADER_NAME)
    if (
        len(presented_values) != 1
        or presented_key is None
        or not secrets.compare_digest(
            presented_key.encode(),
            expected_key.encode(),
        )
    ):
        raise HTTPException(status_code=401, detail="invalid_adapter_ingress_api_key")


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
        ingress_auth_configured = _configured_ingress_api_key() is not None
        ready = ingress_auth_configured and manifest_is_ready(runtime_manifest())
        return HealthResponse(
            status="ok" if ready else ("not_ready" if configured else "unconfigured"),
            configured=configured,
            ready=ready,
            attestation_status=service.attestation.status,
            ingress_auth_configured=ingress_auth_configured,
        )

    @app.post("/memories", response_model=AddResponse)
    def add_memories(
        request: AddRequest,
        _ingress_auth: Annotated[None, Depends(_require_ingress_api_key)],
    ) -> AddResponse:
        if not selected_platform.configured:
            raise HTTPException(status_code=503, detail="missing_mem0_api_key")
        proof = service.add(request)
        return AddResponse(
            request_id=proof.request_id,
            results=[
                PersistedMemoryIdentity(
                    id=item.memory_id,
                    metadata=PersistedSourceMetadata(
                        source_id=item.source_id,
                        source_sha256=item.source_sha256,
                    ),
                )
                for item in proof.results
            ],
        )

    @app.post("/search", response_model=SearchResponse)
    def search_memories(
        request: SearchRequest,
        _ingress_auth: Annotated[None, Depends(_require_ingress_api_key)],
    ) -> SearchResponse:
        if not selected_platform.configured:
            raise HTTPException(status_code=503, detail="missing_mem0_api_key")
        return SearchResponse(results=service.search(request))

    @app.delete("/memories", response_model=DeleteResponse)
    def delete_memories(
        user_id: Annotated[SafeIdentifier, Query()],
        run_id: Annotated[SafeIdentifier, Query()],
        _ingress_auth: Annotated[None, Depends(_require_ingress_api_key)],
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
