"""Minimal compatibility HTTP surface for the real pinned Mem0 OSS adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mem0_oss_adapter.manifest import capabilities_manifest, manifest_is_ready, seal_manifest
from mem0_oss_adapter.models import (
    MAX_REQUEST_BODY_BYTES,
    AddRequest,
    AddResponse,
    BenchmarkAttestationRefreshRequest,
    BenchmarkAuthChallengeRequest,
    BenchmarkAuthChallengeResponse,
    BenchmarkUsageAttestationRequest,
    BenchmarkUsageAttestationResponse,
    DeleteResponse,
    HealthResponse,
    PersistedMemoryIdentity,
    PersistedSourceMetadata,
    RunUsageEvidence,
    SafeIdentifier,
    SearchRequest,
    SearchResponse,
    TimestampAttestation,
)
from mem0_oss_adapter.port import OssPort
from mem0_oss_adapter.sdk_oss import oss_from_environment
from mem0_oss_adapter.service import AdapterError, OssCompatibilityService
from mem0_oss_adapter.usage import (
    usage_attested_at,
    usage_fingerprint_sha256,
    usage_witness_signature,
)

_INGRESS_API_KEY_ENV = "MEM0_ADAPTER_INGRESS_API_KEY"
_BENCHMARK_PROBE_TOKEN_ENV = "MEM0_BENCHMARK_PROBE_TOKEN"
_INGRESS_API_KEY_HEADER_NAME = "X-API-Key"
_MAX_BODY_FRAGMENTS = 1_024
_MAX_EMPTY_BODY_FRAGMENTS = 16
_INGRESS_API_KEY_HEADER = APIKeyHeader(
    name=_INGRESS_API_KEY_HEADER_NAME,
    scheme_name="Mem0AdapterIngressApiKey",
    description="Dedicated authentication for benchmark data-plane operations.",
    auto_error=False,
)


class _BoundedIngressBodyMiddleware:
    """Read a mutation body in bounded ASGI chunks before FastAPI parses it."""

    def __init__(self, app: ASGIApp, *, maximum_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self._app = app
        self._maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self._app(scope, receive, send)
            return

        status_code = _declared_content_length_status(scope)
        if status_code is not None:
            await _send_ingress_error(scope, receive, send, status_code=status_code)
            return

        body_buffer = bytearray()
        fragment_count = 0
        empty_fragment_count = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                await _send_ingress_error(
                    scope,
                    receive,
                    send,
                    status_code=400,
                    detail="invalid_request_body",
                )
                return
            body = message.get("body", b"")
            if not isinstance(body, bytes):
                await _send_ingress_error(
                    scope,
                    receive,
                    send,
                    status_code=400,
                    detail="invalid_request_body",
                )
                return
            fragment_count += 1
            if not body:
                empty_fragment_count += 1
            if (
                fragment_count > _MAX_BODY_FRAGMENTS
                or empty_fragment_count > _MAX_EMPTY_BODY_FRAGMENTS
                or len(body_buffer) + len(body) > self._maximum_bytes
            ):
                await _send_ingress_error(scope, receive, send, status_code=413)
                return
            body_buffer.extend(body)
            if not message.get("more_body", False):
                break

        replay_pending = True
        replay_body = bytes(body_buffer)

        async def replay_receive() -> Message:
            nonlocal replay_pending
            if replay_pending:
                replay_pending = False
                return {"type": "http.request", "body": replay_body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self._app(scope, replay_receive, send)


def _declared_content_length_status(scope: Scope) -> int | None:
    values = [value for key, value in scope.get("headers", []) if key.lower() == b"content-length"]
    if not values:
        return None
    if len(values) != 1:
        return 400
    try:
        declared = values[0].decode("ascii")
    except UnicodeDecodeError:
        return 400
    if not declared.isdecimal():
        return 400
    return 413 if int(declared) > MAX_REQUEST_BODY_BYTES else None


async def _send_ingress_error(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    status_code: int,
    detail: str | None = None,
) -> None:
    response_detail = detail or (
        "request_body_too_large" if status_code == 413 else "invalid_content_length"
    )
    await JSONResponse(status_code=status_code, content={"detail": response_detail})(
        scope,
        receive,
        send,
    )


@dataclass(frozen=True, slots=True)
class _RefreshBinding:
    status: Literal["not_run", "passed", "failed"]
    run_id_sha256: str
    probe_nonce_sha256: str
    target_identity_sha256: str
    refreshed_at: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "run_id_sha256": self.run_id_sha256,
            "probe_nonce_sha256": self.probe_nonce_sha256,
            "target_identity_sha256": self.target_identity_sha256,
            "refreshed_at": self.refreshed_at,
        }


def _configured_ingress_api_key() -> str | None:
    value = os.getenv(_INGRESS_API_KEY_ENV)
    return value if value is not None and value and value == value.strip() else None


def _configured_probe_token() -> str | None:
    value = os.getenv(_BENCHMARK_PROBE_TOKEN_ENV)
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
        or not secrets.compare_digest(presented_key.encode(), expected_key.encode())
    ):
        raise HTTPException(status_code=401, detail="invalid_adapter_ingress_api_key")


def _require_probe_token(request: Request, probe_token: str | None) -> str:
    expected_token = _configured_probe_token()
    if expected_token is None:
        raise HTTPException(status_code=503, detail="missing_benchmark_probe_token")
    presented_values = request.headers.getlist("X-Benchmark-Probe-Token")
    if (
        len(presented_values) != 1
        or probe_token is None
        or not secrets.compare_digest(probe_token.encode(), expected_token.encode())
    ):
        raise HTTPException(status_code=401, detail="invalid_benchmark_probe_token")
    return expected_token


def create_app(
    port: OssPort | None = None,
    *,
    service_factory: Callable[[OssPort], OssCompatibilityService] = OssCompatibilityService,
) -> FastAPI:
    """Create a provider-isolated app without running a canary at import time."""

    selected_port = port or oss_from_environment()
    service = service_factory(selected_port)
    static_attestation = TimestampAttestation()

    app = FastAPI(title="Mem0 OSS benchmark adapter", version="4")
    app.add_middleware(_BoundedIngressBodyMiddleware)

    @app.exception_handler(AdapterError)
    async def adapter_error_handler(_request: Any, exc: AdapterError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.code})

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(_request: Any, _exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": "invalid_request"})

    def runtime_manifest(
        *,
        attestation: TimestampAttestation = static_attestation,
        source_identity_attested: bool = False,
    ) -> dict[str, Any]:
        return capabilities_manifest(
            configured=selected_port.configured,
            extraction_mode=selected_port.extraction_mode,
            timestamp_attestation=attestation,
            source_identity_attested=source_identity_attested,
        )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        configured = selected_port.configured
        ingress_auth_configured = _configured_ingress_api_key() is not None
        ready = ingress_auth_configured and manifest_is_ready(runtime_manifest())
        return HealthResponse(
            status="ok" if ready else ("not_ready" if configured else "unconfigured"),
            configured=configured,
            ready=ready,
            attestation_status=static_attestation.status,
            ingress_auth_configured=ingress_auth_configured,
        )

    @app.post("/memories", response_model=AddResponse)
    def add_memories(
        request: AddRequest,
        _ingress_auth: Annotated[None, Depends(_require_ingress_api_key)],
    ) -> AddResponse:
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
        return SearchResponse(results=service.search(request))

    @app.delete("/memories", response_model=DeleteResponse)
    def delete_memories(
        user_id: Annotated[SafeIdentifier, Query()],
        run_id: Annotated[SafeIdentifier, Query()],
        _ingress_auth: Annotated[None, Depends(_require_ingress_api_key)],
    ) -> DeleteResponse:
        proof = service.delete(user_id=user_id, run_id=run_id)
        return DeleteResponse(deleted=proof.deleted, verified_absent=proof.verified_absent)

    @app.get("/benchmark/capabilities")
    def benchmark_capabilities() -> dict[str, Any]:
        # Deliberately immutable/static: only POST attestation carries a fresh witness.
        return runtime_manifest()

    @app.post("/benchmark/auth-challenge", response_model=BenchmarkAuthChallengeResponse)
    def benchmark_auth_challenge(
        request: BenchmarkAuthChallengeRequest,
        raw_request: Request,
        probe_token: Annotated[str | None, Header(alias="X-Benchmark-Probe-Token")] = None,
    ) -> BenchmarkAuthChallengeResponse:
        expected_token = _require_probe_token(raw_request, probe_token)
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
        raw_request: Request,
        probe_token: Annotated[str | None, Header(alias="X-Benchmark-Probe-Token")] = None,
    ) -> dict[str, Any]:
        expected_token = _require_probe_token(raw_request, probe_token)
        if not selected_port.configured:
            raise HTTPException(status_code=503, detail="missing_mem0_oss_runtime_configuration")
        attestation = service.attest_timestamp()
        binding = _RefreshBinding(
            status=attestation.status,
            run_id_sha256=hashlib.sha256(request.run_id.encode()).hexdigest(),
            probe_nonce_sha256=hashlib.sha256(request.probe_nonce.encode()).hexdigest(),
            target_identity_sha256=request.target_identity_sha256,
            refreshed_at=attestation.checked_at,
        )
        payload = runtime_manifest(
            attestation=attestation,
            source_identity_attested=attestation.status == "passed",
        )
        payload["refresh_binding"] = binding.as_dict()
        payload = seal_manifest(payload)
        manifest_fingerprint = _fingerprint(payload)
        payload["refresh_witness"] = {
            "algorithm": "hmac-sha256",
            "manifest_fingerprint_sha256": manifest_fingerprint,
            "signature": _refresh_witness_signature(
                expected_token,
                binding.as_dict(),
                manifest_fingerprint,
            ),
        }
        return payload

    @app.post(
        "/benchmark/attest-usage",
        response_model=BenchmarkUsageAttestationResponse,
    )
    def attest_benchmark_usage(
        request: BenchmarkUsageAttestationRequest,
        raw_request: Request,
        _ingress_auth: Annotated[None, Depends(_require_ingress_api_key)],
        probe_token: Annotated[str | None, Header(alias="X-Benchmark-Probe-Token")] = None,
    ) -> BenchmarkUsageAttestationResponse:
        expected_token = _require_probe_token(raw_request, probe_token)
        usage = service.usage_for_run(run_id=request.run_id)
        attested_at = usage_attested_at()
        usage_fingerprint = usage_fingerprint_sha256(usage, attested_at=attested_at)
        run_id_sha256 = hashlib.sha256(request.run_id.encode()).hexdigest()
        probe_nonce_sha256 = hashlib.sha256(request.probe_nonce.encode()).hexdigest()
        signature = usage_witness_signature(
            token=expected_token,
            run_id_sha256=run_id_sha256,
            probe_nonce_sha256=probe_nonce_sha256,
            target_identity_sha256=request.target_identity_sha256,
            attested_at=attested_at,
            usage_fingerprint_sha256=usage_fingerprint,
        )
        return BenchmarkUsageAttestationResponse(
            schema_version="mem0-benchmark-usage-attestation.v1",
            run_id_sha256=run_id_sha256,
            probe_nonce_sha256=probe_nonce_sha256,
            target_identity_sha256=request.target_identity_sha256,
            attested_at=attested_at,
            usage=RunUsageEvidence.model_validate(usage.as_dict()),
            usage_fingerprint_sha256=usage_fingerprint,
            algorithm="hmac-sha256",
            signature=signature,
        )

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
