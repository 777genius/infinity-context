"""Strict PR34-compatible v5 HTTP client using a no-proxy loopback transport."""

from __future__ import annotations

import http.client
import json
from dataclasses import dataclass
from typing import Protocol

from .canonical import (
    E2EVerificationError,
    canonical_bytes,
    canonical_sha256,
    exact_object,
    require_digest,
)

_PATHS = {
    "admit": "/v5/runs/admit",
    "dispatch": "/v5/operations/dispatch",
    "status": "/v5/operations/status",
    "cleanup": "/v5/runs/cleanup",
}


class HttpTransport(Protocol):
    def post(self, path: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]: ...


class LoopbackHttpTransport:
    def __init__(self, *, port: int = 19091, timeout_seconds: float = 30.0) -> None:
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("e2e_http_configuration_invalid")
        self._port = port
        self._timeout = timeout_seconds

    def post(self, path: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self._port, timeout=self._timeout)
        try:
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
            content = response.read(256_001)
            return response.status, content
        finally:
            connection.close()


@dataclass(frozen=True, slots=True)
class AdmissionReceipt:
    admission_commitment_sha256: str
    runtime_binding_commitment_sha256: str
    accepted: bool


@dataclass(frozen=True, slots=True)
class RuntimeEnvelope:
    admission_commitment_sha256: str
    operation_id_sha256: str
    runtime_receipt: dict[str, object]


@dataclass(frozen=True, slots=True)
class CleanupReceipt:
    admission_commitment_sha256: str
    seal_commitment_sha256: str | None
    operation_root_sha256: str | None
    operation_inventory_root_sha256: str
    deleted_operation_count: int
    residual_record_count: int
    residual_root_sha256: str


class AdapterHttpClient:
    """Authenticates request commitments and rejects non-exact response DTOs."""

    def __init__(self, *, bearer_token: str, transport: HttpTransport) -> None:
        if (
            not isinstance(bearer_token, str)
            or not 32 <= len(bearer_token.encode()) <= 4096
            or bearer_token != bearer_token.strip()
        ):
            raise ValueError("e2e_http_configuration_invalid")
        self._bearer = bearer_token
        self._transport = transport

    def health(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", 19091, timeout=2)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            value = json.loads(response.read(4097))
        except Exception:
            raise E2EVerificationError("e2e_adapter_unhealthy") from None
        finally:
            connection.close()
        if response.status != 200 or value != {
            "ok": True,
            "service": "mem0-oss-adapter-v5",
            "provider_calls": "dispatch_only",
        }:
            raise E2EVerificationError("e2e_adapter_unhealthy")

    def admit(self, body: dict[str, object], idempotency_key: str) -> AdmissionReceipt:
        value = self._post("admit", body, idempotency_key)
        exact_object(
            value,
            {"admission_commitment_sha256", "runtime_binding_commitment_sha256", "accepted"},
            "e2e_admission_receipt_invalid",
        )
        if not isinstance(value["accepted"], bool):
            raise E2EVerificationError("e2e_admission_receipt_invalid")
        require_digest(value["admission_commitment_sha256"], "e2e_admission_receipt_invalid")
        require_digest(value["runtime_binding_commitment_sha256"], "e2e_admission_receipt_invalid")
        return AdmissionReceipt(**value)  # type: ignore[arg-type]

    def dispatch(self, body: dict[str, object], idempotency_key: str) -> RuntimeEnvelope:
        return self._envelope(self._post("dispatch", body, idempotency_key))

    def status(self, body: dict[str, object], idempotency_key: str) -> RuntimeEnvelope:
        return self._envelope(self._post("status", body, idempotency_key))

    def cleanup(self, body: dict[str, object], idempotency_key: str) -> CleanupReceipt:
        value = self._post("cleanup", body, idempotency_key)
        exact_object(
            value,
            {
                "admission_commitment_sha256",
                "seal_commitment_sha256",
                "operation_root_sha256",
                "operation_inventory_root_sha256",
                "deleted_operation_count",
                "residual_record_count",
                "residual_root_sha256",
            },
            "e2e_cleanup_receipt_invalid",
        )
        if (
            not isinstance(value["deleted_operation_count"], int)
            or isinstance(value["deleted_operation_count"], bool)
            or not isinstance(value["residual_record_count"], int)
            or isinstance(value["residual_record_count"], bool)
        ):
            raise E2EVerificationError("e2e_cleanup_receipt_invalid")
        return CleanupReceipt(**value)  # type: ignore[arg-type]

    def _envelope(self, value: dict[str, object]) -> RuntimeEnvelope:
        exact_object(
            value,
            {"admission_commitment_sha256", "operation_id_sha256", "runtime_receipt"},
            "e2e_runtime_envelope_invalid",
        )
        if not isinstance(value["runtime_receipt"], dict):
            raise E2EVerificationError("e2e_runtime_envelope_invalid")
        require_digest(value["admission_commitment_sha256"], "e2e_runtime_envelope_invalid")
        require_digest(value["operation_id_sha256"], "e2e_runtime_envelope_invalid")
        return RuntimeEnvelope(**value)  # type: ignore[arg-type]

    def _post(
        self, endpoint: str, body: dict[str, object], idempotency_key: str
    ) -> dict[str, object]:
        encoded = canonical_bytes(body)
        require_digest(idempotency_key, "e2e_http_request_invalid")
        if len(encoded) > 64_000:
            raise E2EVerificationError("e2e_http_request_invalid")
        headers = {
            "Authorization": "Bearer " + self._bearer,
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
            "X-Request-Commitment-SHA256": canonical_sha256(body),
        }
        try:
            status, content = self._transport.post(_PATHS[endpoint], headers, encoded)
        except Exception:
            raise E2EVerificationError("e2e_http_transport_failed") from None
        if status != 200:
            raise E2EVerificationError("e2e_http_remote_failed")
        if not 1 <= len(content) <= 256_000:
            raise E2EVerificationError("e2e_http_response_invalid")
        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise E2EVerificationError("e2e_http_response_invalid") from None
        if not isinstance(value, dict):
            raise E2EVerificationError("e2e_http_response_invalid")
        return value
