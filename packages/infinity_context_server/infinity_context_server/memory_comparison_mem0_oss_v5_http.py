"""Exact sibling HTTP DTOs and Phase-C-backed receipt verification for Mem0 v5."""

from __future__ import annotations

import importlib
import json
import threading
from dataclasses import dataclass
from typing import Protocol, final
from urllib.parse import urlsplit

import httpx

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunError,
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationPort,
    RuntimeReceiptVerificationResult,
    canonical_sha256,
    is_sha256,
)

_MAX_RESPONSE_BYTES = 256_000
_MAX_REQUEST_BYTES = 64_000
_PATHS = {
    "admit": "/v5/runs/admit",
    "dispatch": "/v5/operations/dispatch",
    "status": "/v5/operations/status",
    "cleanup": "/v5/runs/cleanup",
}
_SAFE_ERROR_CODES = frozenset(
    {
        "mem0_v5_http_configuration_invalid",
        "mem0_v5_http_request_invalid",
        "mem0_v5_http_response_invalid",
        "mem0_v5_http_remote_failed",
        "mem0_v5_runtime_receipt_invalid",
        "mem0_v5_runtime_receipt_replayed",
        "mem0_v5_runtime_receipt_state_invalid",
        "mem0_v5_runtime_receipt_unauthenticated",
    }
)


class Mem0V5HttpError(RuntimeError):
    def __init__(self, code: str) -> None:
        safe = code if code in _SAFE_ERROR_CODES else "mem0_v5_http_remote_failed"
        self.code = safe
        super().__init__(safe)


class Mem0V5TransportPort(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes,
        timeout: float,
        follow_redirects: bool,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class Mem0V5AdmitRequest:
    admission_commitment_sha256: str
    ingestion_manifest_sha256: str
    ingestion_root_sha256: str
    expected_operation_count: int
    route_sha256: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if (
            any(
                not is_sha256(value)
                for value in (
                    self.admission_commitment_sha256,
                    self.ingestion_manifest_sha256,
                    self.ingestion_root_sha256,
                    self.route_sha256,
                    self.idempotency_key,
                )
            )
            or type(self.expected_operation_count) is not int
            or not 1 <= self.expected_operation_count <= 10_000
        ):
            _fail("mem0_v5_http_request_invalid")

    def body(self) -> dict[str, object]:
        return {
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "ingestion_manifest_sha256": self.ingestion_manifest_sha256,
            "ingestion_root_sha256": self.ingestion_root_sha256,
            "expected_operation_count": self.expected_operation_count,
            "route_sha256": self.route_sha256,
        }


@dataclass(frozen=True, slots=True)
class Mem0V5DispatchRequest:
    admission_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    scope_sha256: str
    request_body_sha256: str
    sequence: int
    idempotency_key: str

    def __post_init__(self) -> None:
        if (
            any(
                not is_sha256(value)
                for value in (
                    self.admission_commitment_sha256,
                    self.operation_id_sha256,
                    self.unit_identity_sha256,
                    self.unit_sha256,
                    self.scope_sha256,
                    self.request_body_sha256,
                    self.idempotency_key,
                )
            )
            or type(self.sequence) is not int
            or not 0 <= self.sequence < 10_000
        ):
            _fail("mem0_v5_http_request_invalid")

    def body(self) -> dict[str, object]:
        return {
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "operation_id_sha256": self.operation_id_sha256,
            "unit_identity_sha256": self.unit_identity_sha256,
            "unit_sha256": self.unit_sha256,
            "scope_sha256": self.scope_sha256,
            "request_body_sha256": self.request_body_sha256,
            "sequence": self.sequence,
        }


@dataclass(frozen=True, slots=True)
class Mem0V5StatusRequest:
    admission_commitment_sha256: str
    operation_id_sha256: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if any(
            not is_sha256(value)
            for value in (
                self.admission_commitment_sha256,
                self.operation_id_sha256,
                self.idempotency_key,
            )
        ):
            _fail("mem0_v5_http_request_invalid")

    def body(self) -> dict[str, object]:
        return {
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "operation_id_sha256": self.operation_id_sha256,
        }


@dataclass(frozen=True, slots=True)
class Mem0V5CleanupRequest:
    admission_commitment_sha256: str
    seal_commitment_sha256: str | None
    operation_root_sha256: str | None
    operation_inventory_root_sha256: str
    expected_operation_count: int
    aborting: bool
    idempotency_key: str

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.admission_commitment_sha256)
            or type(self.aborting) is not bool
            or (
                self.aborting
                and (
                    self.seal_commitment_sha256 is not None
                    or self.operation_root_sha256 is not None
                )
            )
            or (
                not self.aborting
                and (
                    not is_sha256(self.seal_commitment_sha256)
                    or not is_sha256(self.operation_root_sha256)
                )
            )
            or not is_sha256(self.operation_inventory_root_sha256)
            or type(self.expected_operation_count) is not int
            or not 1 <= self.expected_operation_count <= 10_000
            or not is_sha256(self.idempotency_key)
        ):
            _fail("mem0_v5_http_request_invalid")

    def body(self) -> dict[str, object]:
        return {
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "seal_commitment_sha256": self.seal_commitment_sha256,
            "operation_root_sha256": self.operation_root_sha256,
            "operation_inventory_root_sha256": self.operation_inventory_root_sha256,
            "expected_operation_count": self.expected_operation_count,
            "aborting": self.aborting,
        }


@dataclass(frozen=True, slots=True)
class Mem0V5AdmissionReceipt:
    admission_commitment_sha256: str
    runtime_binding_commitment_sha256: str
    accepted: bool


@dataclass(frozen=True, slots=True)
class Mem0V5RuntimeReceiptEnvelope:
    admission_commitment_sha256: str
    operation_id_sha256: str
    runtime_receipt: dict[str, object]


@dataclass(frozen=True, slots=True)
class Mem0V5CleanupReceipt:
    admission_commitment_sha256: str
    seal_commitment_sha256: str | None
    operation_root_sha256: str | None
    operation_inventory_root_sha256: str
    deleted_operation_count: int
    residual_record_count: int
    residual_root_sha256: str


@final
class Mem0V5HttpPort:
    __slots__ = ("_bearer", "_origin", "_timeout", "_transport")

    def __init__(
        self,
        *,
        origin: str,
        bearer_token: str,
        timeout_seconds: float,
        transport: Mem0V5TransportPort | None = None,
    ) -> None:
        self._origin = _loopback_origin(origin)
        if (
            type(bearer_token) is not str
            or not 16 <= len(bearer_token.encode()) <= 4_096
            or type(timeout_seconds) not in (int, float)
            or isinstance(timeout_seconds, bool)
            or not 0.01 <= float(timeout_seconds) <= 120.0
        ):
            _fail("mem0_v5_http_configuration_invalid")
        self._bearer = bearer_token
        self._timeout = float(timeout_seconds)
        self._transport = transport or _HttpxTransport()

    def admit(self, request: Mem0V5AdmitRequest) -> Mem0V5AdmissionReceipt:
        if type(request) is not Mem0V5AdmitRequest:
            _fail("mem0_v5_http_request_invalid")
        value = self._post("admit", request.body(), request.idempotency_key)
        _exact(
            value, {"admission_commitment_sha256", "runtime_binding_commitment_sha256", "accepted"}
        )
        if (
            not is_sha256(value["admission_commitment_sha256"])
            or not is_sha256(value["runtime_binding_commitment_sha256"])
            or type(value["accepted"]) is not bool
        ):
            _fail("mem0_v5_http_response_invalid")
        return Mem0V5AdmissionReceipt(**value)

    def dispatch(self, request: Mem0V5DispatchRequest) -> Mem0V5RuntimeReceiptEnvelope:
        if type(request) is not Mem0V5DispatchRequest:
            _fail("mem0_v5_http_request_invalid")
        return _runtime_envelope(self._post("dispatch", request.body(), request.idempotency_key))

    def status(self, request: Mem0V5StatusRequest) -> Mem0V5RuntimeReceiptEnvelope:
        if type(request) is not Mem0V5StatusRequest:
            _fail("mem0_v5_http_request_invalid")
        return _runtime_envelope(self._post("status", request.body(), request.idempotency_key))

    def cleanup(self, request: Mem0V5CleanupRequest) -> Mem0V5CleanupReceipt:
        if type(request) is not Mem0V5CleanupRequest:
            _fail("mem0_v5_http_request_invalid")
        value = self._post("cleanup", request.body(), request.idempotency_key)
        keys = {
            "admission_commitment_sha256",
            "seal_commitment_sha256",
            "operation_root_sha256",
            "operation_inventory_root_sha256",
            "deleted_operation_count",
            "residual_record_count",
            "residual_root_sha256",
        }
        _exact(value, keys)
        if (
            value["admission_commitment_sha256"] != request.admission_commitment_sha256
            or value["seal_commitment_sha256"] != request.seal_commitment_sha256
            or value["operation_root_sha256"] != request.operation_root_sha256
            or value["operation_inventory_root_sha256"] != request.operation_inventory_root_sha256
            or not is_sha256(value["residual_root_sha256"])
            or type(value["deleted_operation_count"]) is not int
            or not 0 <= value["deleted_operation_count"] <= request.expected_operation_count
            or type(value["residual_record_count"]) is not int
            or not 0 <= value["residual_record_count"] <= 10_000
        ):
            _fail("mem0_v5_http_response_invalid")
        return Mem0V5CleanupReceipt(**value)

    def _post(
        self, endpoint: str, body: dict[str, object], idempotency_key: str
    ) -> dict[str, object]:
        encoded = json.dumps(
            body, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode()
        if len(encoded) > _MAX_REQUEST_BYTES:
            _fail("mem0_v5_http_request_invalid")
        headers = {
            "Authorization": "Bearer " + self._bearer,
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
            "X-Request-Commitment-SHA256": canonical_sha256(body),
        }
        try:
            response = self._transport.request(
                "POST",
                self._origin + _PATHS[endpoint],
                headers=headers,
                content=encoded,
                timeout=self._timeout,
                follow_redirects=False,
            )
            status_code = response.status_code
            content = bytes(response.content)
        except Exception:
            raise Mem0V5HttpError("mem0_v5_http_remote_failed") from None
        if status_code != 200:
            _fail("mem0_v5_http_remote_failed")
        if not 1 <= len(content) <= _MAX_RESPONSE_BYTES:
            _fail("mem0_v5_http_response_invalid")
        try:
            parsed = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise Mem0V5HttpError("mem0_v5_http_response_invalid") from None
        if type(parsed) is not dict:
            _fail("mem0_v5_http_response_invalid")
        return parsed


@dataclass(frozen=True, slots=True)
class Mem0V5OperationReceiptAuthority:
    operation_id_sha256: str
    sequence: int
    thread_id: str
    turn_id: str
    request_body_sha256: str
    output_text_sha256: str

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.operation_id_sha256)
            or type(self.sequence) is not int
            or self.sequence < 0
            or not _safe_text(self.thread_id)
            or not _safe_text(self.turn_id)
            or not is_sha256(self.request_body_sha256)
            or not is_sha256(self.output_text_sha256)
        ):
            _fail("mem0_v5_http_configuration_invalid")


@dataclass(frozen=True, slots=True)
class Mem0V5ReceiptAuthority:
    model: str
    reasoning_effort: str
    service_tier: str
    base_instructions_sha256: str
    runtime_source_sha256: str
    route_binding_sha256: str
    account_binding_hmac_sha256: str
    response_format_type: str
    response_format_sha256: str
    response_schema_sha256: str
    requested_output_tokens: int
    operations: tuple[Mem0V5OperationReceiptAuthority, ...]

    def __post_init__(self) -> None:
        digests = (
            self.base_instructions_sha256,
            self.runtime_source_sha256,
            self.route_binding_sha256,
            self.account_binding_hmac_sha256,
            self.response_format_sha256,
            self.response_schema_sha256,
        )
        if (
            any(not is_sha256(value) for value in digests)
            or any(
                not _safe_text(value)
                for value in (
                    self.model,
                    self.reasoning_effort,
                    self.service_tier,
                    self.response_format_type,
                )
            )
            or type(self.requested_output_tokens) is not int
            or self.requested_output_tokens <= 0
            or type(self.operations) is not tuple
            or not self.operations
            or any(type(item) is not Mem0V5OperationReceiptAuthority for item in self.operations)
            or len({item.operation_id_sha256 for item in self.operations}) != len(self.operations)
        ):
            _fail("mem0_v5_http_configuration_invalid")


@final
class Mem0V5RuntimeReceiptVerifier(RuntimeReceiptVerificationPort):
    """Concrete adapter around PR #32's verifier-issued receipt authority."""

    __slots__ = (
        "_authority",
        "_boundary",
        "_consumed",
        "_lock",
        "_module",
        "_operations",
        "_runtime_binding",
        "_secret",
        "_unknown",
    )

    def __init__(
        self,
        *,
        boundary: object,
        runtime_binding: object,
        receipt_secret: str,
        authority: Mem0V5ReceiptAuthority,
    ) -> None:
        try:
            module = importlib.import_module("phase_c_canary.runtime_receipt_v2")
            binding_module = importlib.import_module("phase_c_canary.runtime_binding")
            if type(boundary) is not module.RuntimeReceiptV2Boundary:
                raise TypeError
            if type(runtime_binding) is not binding_module.TrustedRuntimeBinding:
                raise TypeError
            binding_module.require_trusted_runtime_binding(runtime_binding)
        except Exception:
            raise Mem0V5HttpError("mem0_v5_http_configuration_invalid") from None
        if (
            type(receipt_secret) is not str
            or not 32 <= len(receipt_secret.encode()) <= 4_096
            or type(authority) is not Mem0V5ReceiptAuthority
            or authority.runtime_source_sha256 != runtime_binding.runtime_source_sha256
            or authority.route_binding_sha256 != runtime_binding.route_binding_sha256
        ):
            _fail("mem0_v5_http_configuration_invalid")
        self._module = module
        self._boundary = boundary
        self._runtime_binding = runtime_binding
        self._secret = receipt_secret
        self._authority = authority
        self._operations = {item.operation_id_sha256: item for item in authority.operations}
        self._unknown: set[str] = set()
        self._consumed: set[str] = set()
        self._lock = threading.Lock()

    def mark_outcome_unknown(self, *, context: RuntimeReceiptVerificationContext) -> None:
        with self._lock:
            self._context_operation(context)
            if context.readback_only or context.operation_id_sha256 in self._consumed:
                _fail("mem0_v5_runtime_receipt_state_invalid")
            self._unknown.add(context.operation_id_sha256)

    def verify_dispatch_receipt(
        self, *, payload: object, context: RuntimeReceiptVerificationContext
    ) -> RuntimeReceiptVerificationResult:
        if context.readback_only:
            raise Mem0OssFullRunError("mem0_v5_receipt_context_invalid")
        return self._verify(payload, context, readback=False)

    def verify_status_readback(
        self, *, payload: object, context: RuntimeReceiptVerificationContext
    ) -> RuntimeReceiptVerificationResult:
        if not context.readback_only:
            raise Mem0OssFullRunError("mem0_v5_receipt_context_invalid")
        return self._verify(payload, context, readback=True)

    def _verify(
        self,
        payload: object,
        context: RuntimeReceiptVerificationContext,
        *,
        readback: bool,
    ) -> RuntimeReceiptVerificationResult:
        with self._lock:
            operation = self._context_operation(context)
            operation_id = context.operation_id_sha256
            if operation_id in self._consumed:
                _fail("mem0_v5_runtime_receipt_replayed")
            if readback != (operation_id in self._unknown):
                _fail("mem0_v5_runtime_receipt_state_invalid")
            if type(payload) is not Mem0V5RuntimeReceiptEnvelope:
                _fail("mem0_v5_runtime_receipt_invalid")
            if (
                payload.admission_commitment_sha256 != context.admission_commitment_sha256
                or payload.operation_id_sha256 != operation_id
            ):
                _fail("mem0_v5_runtime_receipt_invalid")
            expectation = self._module.RuntimeReceiptExpectation(
                model=self._authority.model,
                reasoning_effort=self._authority.reasoning_effort,
                service_tier=self._authority.service_tier,
                base_instructions_sha256=self._authority.base_instructions_sha256,
                runtime_source_sha256=self._authority.runtime_source_sha256,
                route_binding_sha256=self._authority.route_binding_sha256,
                account_binding_hmac_sha256=self._authority.account_binding_hmac_sha256,
                thread_id=operation.thread_id,
                turn_id=operation.turn_id,
                request_body_sha256=operation.request_body_sha256,
                output_text_sha256=operation.output_text_sha256,
                response_format_type=self._authority.response_format_type,
                response_format_sha256=self._authority.response_format_sha256,
                response_schema_sha256=self._authority.response_schema_sha256,
                requested_output_tokens=self._authority.requested_output_tokens,
            )
            try:
                safe = self._boundary.verify(
                    receipt=payload.runtime_receipt,
                    secret=self._secret,
                    expectation=expectation,
                    runtime_binding=self._runtime_binding,
                    call_kind=self._module.RuntimeCallKind.EXTRACTION,
                    sequence=operation.sequence,
                    operation_id_sha256=operation_id,
                )
                self._module.require_verified_safe_receipt(safe)
            except Exception:
                raise Mem0V5HttpError("mem0_v5_runtime_receipt_unauthenticated") from None
            if (
                safe.operation_id_sha256 != operation_id
                or safe.route_binding_sha256 != context.route_sha256
                or safe.request_body_sha256 != operation.request_body_sha256
                or safe.output_text_sha256 != operation.output_text_sha256
            ):
                _fail("mem0_v5_runtime_receipt_invalid")
            self._consumed.add(operation_id)
            self._unknown.discard(operation_id)
            return RuntimeReceiptVerificationResult(
                admission_commitment_sha256=context.admission_commitment_sha256,
                operation_id_sha256=operation_id,
                unit_identity_sha256=context.unit_identity_sha256,
                unit_sha256=context.unit_sha256,
                route_sha256=context.route_sha256,
                scope_sha256=context.scope_sha256,
                provider_receipt_sha256=safe.receipt_sha256,
                disposition=Mem0OssReceiptDisposition.COMPLETED,
                extraction_calls=1,
                retry_count=0,
                request_tokens=safe.usage.prompt_tokens,
                response_tokens=safe.usage.completion_tokens,
            )

    def _context_operation(
        self, context: RuntimeReceiptVerificationContext
    ) -> Mem0V5OperationReceiptAuthority:
        if type(context) is not RuntimeReceiptVerificationContext:
            _fail("mem0_v5_runtime_receipt_invalid")
        operation = self._operations.get(context.operation_id_sha256)
        if operation is None or context.route_sha256 != self._authority.route_binding_sha256:
            _fail("mem0_v5_runtime_receipt_invalid")
        return operation


@final
class _HttpxTransport:
    __slots__ = ()

    def request(self, method: str, url: str, **kwargs: object) -> object:
        transport = httpx.HTTPTransport(retries=0, trust_env=False)
        with httpx.Client(transport=transport, follow_redirects=False, trust_env=False) as client:
            return client.request(method, url, **kwargs)


def _runtime_envelope(value: dict[str, object]) -> Mem0V5RuntimeReceiptEnvelope:
    _exact(value, {"admission_commitment_sha256", "operation_id_sha256", "runtime_receipt"})
    if (
        not is_sha256(value["admission_commitment_sha256"])
        or not is_sha256(value["operation_id_sha256"])
        or type(value["runtime_receipt"]) is not dict
    ):
        _fail("mem0_v5_http_response_invalid")
    return Mem0V5RuntimeReceiptEnvelope(**value)


def _exact(value: dict[str, object], keys: set[str]) -> None:
    if set(value) != keys:
        _fail("mem0_v5_http_response_invalid")


def _safe_text(value: object) -> bool:
    return type(value) is str and 1 <= len(value) <= 512


def _loopback_origin(value: object) -> str:
    if type(value) is not str or not 1 <= len(value) <= 2_048:
        _fail("mem0_v5_http_configuration_invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise Mem0V5HttpError("mem0_v5_http_configuration_invalid") from None
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        _fail("mem0_v5_http_configuration_invalid")
    return value.rstrip("/")


def _fail(code: str) -> None:
    raise Mem0V5HttpError(code)


__all__ = (
    "Mem0V5AdmitRequest",
    "Mem0V5AdmissionReceipt",
    "Mem0V5CleanupReceipt",
    "Mem0V5CleanupRequest",
    "Mem0V5DispatchRequest",
    "Mem0V5HttpError",
    "Mem0V5HttpPort",
    "Mem0V5OperationReceiptAuthority",
    "Mem0V5ReceiptAuthority",
    "Mem0V5RuntimeReceiptEnvelope",
    "Mem0V5RuntimeReceiptVerifier",
    "Mem0V5StatusRequest",
    "Mem0V5TransportPort",
)
