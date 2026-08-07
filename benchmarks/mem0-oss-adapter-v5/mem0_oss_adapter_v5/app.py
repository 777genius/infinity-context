"""Fail-closed HTTP boundary for the Mem0 OSS full-run v5 adapter."""

import hashlib
import hmac
import json
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mem0_oss_adapter_v5.http_models import (
    AdmissionReceipt,
    AdmitRequest,
    CleanupReceipt,
    CleanupRequest,
    DispatchRequest,
    ErrorResponse,
    HealthResponse,
    RuntimeReceiptEnvelope,
    ScopedSearchRequest,
    ScopedSearchResponse,
    StatusRequest,
    StorageObservationRequest,
    StorageObservationResponse,
)

MAX_REQUEST_BODY_BYTES = 64_000
MAX_BODY_FRAGMENTS = 256
_SAFE_SERVICE_ERRORS = frozenset(
    {
        "admission_conflict",
        "admission_invalid",
        "cleanup_conflict",
        "cleanup_failed",
        "corpus_not_found",
        "dispatch_conflict",
        "dispatch_failed",
        "manifest_invalid",
        "operation_not_found",
        "operation_cleaned",
        "request_binding_invalid",
        "run_not_found",
        "run_state_invalid",
        "status_unavailable",
        "storage_verification_failed",
    }
)


class AdapterServiceError(RuntimeError):
    """Fixed-code application error safe to return across the HTTP boundary."""

    def __init__(self, code: str, *, status_code: int = 409) -> None:
        self.code = code if code in _SAFE_SERVICE_ERRORS else "dispatch_failed"
        self.status_code = status_code if status_code in {400, 404, 409, 410, 503} else 503
        super().__init__(self.code)


class V5ApplicationService(Protocol):
    def admit(self, request: AdmitRequest, *, idempotency_key: str) -> AdmissionReceipt: ...

    def dispatch(
        self, request: DispatchRequest, *, idempotency_key: str
    ) -> RuntimeReceiptEnvelope: ...

    def status(self, request: StatusRequest, *, idempotency_key: str) -> RuntimeReceiptEnvelope: ...

    def cleanup(self, request: CleanupRequest, *, idempotency_key: str) -> CleanupReceipt: ...

    def storage_observation(
        self,
        request: StorageObservationRequest,
        *,
        idempotency_key: str,
    ) -> StorageObservationResponse: ...

    def scoped_search(
        self,
        request: ScopedSearchRequest,
        *,
        idempotency_key: str,
    ) -> ScopedSearchResponse: ...


class _BoundedBodyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self._app(scope, receive, send)
            return
        declared = _declared_content_length(scope)
        if declared is None or declared > MAX_REQUEST_BODY_BYTES:
            await _error_response(scope, receive, send, 413, "request_body_too_large")
            return
        body = bytearray()
        fragments = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                await _error_response(scope, receive, send, 400, "invalid_request")
                return
            fragment = message.get("body", b"")
            if type(fragment) is not bytes:
                await _error_response(scope, receive, send, 400, "invalid_request")
                return
            fragments += 1
            if fragments > MAX_BODY_FRAGMENTS or len(body) + len(fragment) > MAX_REQUEST_BODY_BYTES:
                await _error_response(scope, receive, send, 413, "request_body_too_large")
                return
            body.extend(fragment)
            if not message.get("more_body", False):
                break
        if len(body) != declared:
            await _error_response(scope, receive, send, 400, "invalid_request")
            return
        pending = True

        async def replay() -> Message:
            nonlocal pending
            if pending:
                pending = False
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self._app(scope, replay, send)


def create_app(*, service: V5ApplicationService, bearer_token: str) -> FastAPI:
    if not _valid_secret(bearer_token):
        raise ValueError("adapter_configuration_invalid")
    app = FastAPI(title="Mem0 OSS benchmark adapter v5", version="5")
    app.add_middleware(_BoundedBodyMiddleware)
    authenticate = _authenticate(bearer_token)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "invalid_request"})

    @app.exception_handler(AdapterServiceError)
    async def service_error(_request: Request, exc: AdapterServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.code})

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            ok=True,
            service="mem0-oss-adapter-v5",
            provider_calls="dispatch_only",
        )

    @app.post("/v5/runs/admit", response_model=AdmissionReceipt)
    def admit(
        payload: AdmitRequest,
        headers: Annotated[_AuthenticatedHeaders, Depends(authenticate)],
    ) -> AdmissionReceipt:
        _verify_request_commitment(payload, headers.request_commitment_sha256)
        return service.admit(payload, idempotency_key=headers.idempotency_key)

    @app.post(
        "/v5/operations/dispatch",
        response_model=RuntimeReceiptEnvelope,
        response_model_exclude_none=True,
    )
    def dispatch(
        payload: DispatchRequest,
        headers: Annotated[_AuthenticatedHeaders, Depends(authenticate)],
    ) -> RuntimeReceiptEnvelope:
        _verify_request_commitment(payload, headers.request_commitment_sha256)
        return service.dispatch(payload, idempotency_key=headers.idempotency_key)

    @app.post(
        "/v5/operations/status",
        response_model=RuntimeReceiptEnvelope,
        response_model_exclude_none=True,
    )
    def status(
        payload: StatusRequest,
        headers: Annotated[_AuthenticatedHeaders, Depends(authenticate)],
    ) -> RuntimeReceiptEnvelope:
        _verify_request_commitment(payload, headers.request_commitment_sha256)
        return service.status(payload, idempotency_key=headers.idempotency_key)

    @app.post("/v5/runs/cleanup", response_model=CleanupReceipt)
    def cleanup(
        payload: CleanupRequest,
        headers: Annotated[_AuthenticatedHeaders, Depends(authenticate)],
    ) -> CleanupReceipt:
        _verify_request_commitment(payload, headers.request_commitment_sha256)
        return service.cleanup(payload, idempotency_key=headers.idempotency_key)

    @app.post(
        "/v5/operations/storage-observation",
        response_model=StorageObservationResponse,
    )
    def storage_observation(
        payload: StorageObservationRequest,
        headers: Annotated[_AuthenticatedHeaders, Depends(authenticate)],
    ) -> StorageObservationResponse:
        _verify_request_commitment(payload, headers.request_commitment_sha256)
        return service.storage_observation(payload, idempotency_key=headers.idempotency_key)

    @app.post("/v5/runs/search", response_model=ScopedSearchResponse)
    def scoped_search(
        payload: ScopedSearchRequest,
        headers: Annotated[_AuthenticatedHeaders, Depends(authenticate)],
    ) -> ScopedSearchResponse:
        _verify_request_commitment(payload, headers.request_commitment_sha256)
        return service.scoped_search(payload, idempotency_key=headers.idempotency_key)

    return app


class _AuthenticatedHeaders:
    __slots__ = ("idempotency_key", "request_commitment_sha256")

    def __init__(self, idempotency_key: str, request_commitment_sha256: str) -> None:
        self.idempotency_key = idempotency_key
        self.request_commitment_sha256 = request_commitment_sha256


def _authenticate(expected_bearer: str):
    def dependency(
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None),
        x_request_commitment_sha256: str | None = Header(default=None),
    ) -> _AuthenticatedHeaders:
        if any(
            len(request.headers.getlist(name)) != 1
            for name in ("authorization", "idempotency-key", "x-request-commitment-sha256")
        ):
            raise HTTPException(status_code=401, detail="invalid_authentication")
        prefix = "Bearer "
        if authorization is None or not authorization.startswith(prefix):
            raise HTTPException(status_code=401, detail="invalid_authentication")
        presented = authorization[len(prefix) :]
        if not hmac.compare_digest(presented.encode(), expected_bearer.encode()):
            raise HTTPException(status_code=401, detail="invalid_authentication")
        if not _is_sha256(idempotency_key) or not _is_sha256(x_request_commitment_sha256):
            raise HTTPException(status_code=400, detail="invalid_request_headers")
        return _AuthenticatedHeaders(idempotency_key, x_request_commitment_sha256)

    return dependency


def _verify_request_commitment(payload: object, presented: str) -> None:
    dumped = payload.model_dump(mode="json")
    encoded = json.dumps(dumped, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    expected = hashlib.sha256(encoded).hexdigest()
    if not hmac.compare_digest(expected, presented):
        raise HTTPException(status_code=400, detail="request_commitment_invalid")


def _declared_content_length(scope: Scope) -> int | None:
    values = [value for key, value in scope.get("headers", []) if key.lower() == b"content-length"]
    if len(values) != 1:
        return None
    try:
        decoded = values[0].decode("ascii")
    except UnicodeDecodeError:
        return None
    if not decoded.isdecimal():
        return None
    return int(decoded)


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _valid_secret(value: object) -> bool:
    return type(value) is str and 32 <= len(value.encode()) <= 4_096 and value == value.strip()


async def _error_response(
    scope: Scope, receive: Receive, send: Send, status: int, detail: str
) -> None:
    response = JSONResponse(
        status_code=status,
        content=ErrorResponse(detail=detail).model_dump(mode="json"),
    )
    await response(scope, receive, send)
