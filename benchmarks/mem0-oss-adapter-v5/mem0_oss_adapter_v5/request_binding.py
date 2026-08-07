"""Authenticated, provider-free binding for one sealed extraction request."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from mem0_oss_adapter_v5.domain import canonical_json_bytes, canonical_sha256
from mem0_oss_adapter_v5.extraction_contract import ExtractionRequest
from mem0_oss_adapter_v5.sealed_manifest import InputUnit, SealedInputManifest
from mem0_oss_adapter_v5.state_sqlite import OperationState, SqliteOperationState

_SCHEMA = "mem0-oss-adapter-v5.request-binding.v1"
_KEY_DOMAIN = b"mem0-oss-adapter-v5/evidence-key/v1"
_SIGNATURE_DOMAIN = b"request-binding/v1"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
Sha256 = Annotated[StrictStr, Field(pattern=_SHA256_PATTERN)]


class _ExactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class RequestBindingRequest(_ExactModel):
    admission_commitment_sha256: Sha256
    operation_id_sha256: Sha256


class RequestBindingResponse(_ExactModel):
    schema_version: Literal["mem0-oss-adapter-v5.request-binding.v1"]
    admission_commitment_sha256: Sha256
    ingestion_manifest_sha256: Sha256
    ingestion_root_sha256: Sha256
    current_date_commitment_sha256: Sha256
    operation_id_sha256: Sha256
    unit_identity_sha256: Sha256
    unit_sha256: Sha256
    scope_sha256: Sha256
    source_id: Annotated[StrictStr, Field(min_length=1, max_length=512)]
    source_sha256: Sha256
    sequence: Annotated[StrictInt, Field(ge=0, lt=10_000)]
    request_body_sha256: Sha256
    response_format_sha256: Sha256
    request_binding_hmac_sha256: Sha256

    @field_validator("source_id")
    @classmethod
    def source_id_is_trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("request_binding_invalid")
        return value


class RequestBindingError(RuntimeError):
    def __init__(self, code: str, *, status_code: int) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class RequestBindingService:
    """Projects a signed binding without changing state or calling a provider."""

    def __init__(
        self,
        *,
        manifest: SealedInputManifest,
        state: SqliteOperationState,
        extraction_request: Callable[[InputUnit], ExtractionRequest],
        operation_id: Callable[[InputUnit], str],
        result_hmac_key: bytes,
    ) -> None:
        if type(result_hmac_key) is not bytes or len(result_hmac_key) < 32:
            raise ValueError("adapter_configuration_invalid")
        self._manifest = manifest
        self._state = state
        self._extraction_request = extraction_request
        self._operation_id = operation_id
        root = hmac.new(result_hmac_key, _KEY_DOMAIN, hashlib.sha256).digest()
        self._signing_key = hmac.new(root, _SIGNATURE_DOMAIN, hashlib.sha256).digest()

    def bind(
        self,
        request: RequestBindingRequest,
        *,
        current_admission_commitment_sha256: str | None,
        idempotency_key: str,
    ) -> RequestBindingResponse:
        del idempotency_key
        if current_admission_commitment_sha256 != request.admission_commitment_sha256:
            raise RequestBindingError("run_not_found", status_code=404)
        unit = self._unit_by_operation(request.operation_id_sha256)
        try:
            record = self._state.get(unit.unit_identity_sha256)
        except Exception:
            raise RequestBindingError("run_state_invalid", status_code=503) from None
        if record.state in {OperationState.CLEANED, OperationState.ABORT_CLEANED}:
            raise RequestBindingError("operation_cleaned", status_code=410)
        try:
            extraction = self._extraction_request(unit)
        except Exception:
            raise RequestBindingError("run_state_invalid", status_code=503) from None
        if not hmac.compare_digest(record.request_sha256, extraction.request_body_sha256):
            raise RequestBindingError("run_state_invalid", status_code=503)
        unsigned = {
            "schema_version": _SCHEMA,
            "admission_commitment_sha256": request.admission_commitment_sha256,
            "ingestion_manifest_sha256": self._manifest.ingestion_manifest_sha256,
            "ingestion_root_sha256": self._manifest.ingestion_root_sha256,
            "current_date_commitment_sha256": canonical_sha256(
                {"current_date": self._manifest.current_date}
            ),
            "operation_id_sha256": request.operation_id_sha256,
            "unit_identity_sha256": unit.unit_identity_sha256,
            "unit_sha256": unit.unit_sha256,
            "scope_sha256": unit.scope_sha256,
            "source_id": unit.source_id,
            "source_sha256": unit.source_sha256,
            "sequence": unit.sequence,
            "request_body_sha256": extraction.request_body_sha256,
            "response_format_sha256": extraction.response_format_sha256,
        }
        signed = {
            **unsigned,
            "request_binding_hmac_sha256": _signature(self._signing_key, unsigned),
        }
        return RequestBindingResponse.model_validate(signed)

    def _unit_by_operation(self, operation_id_sha256: str) -> InputUnit:
        for unit in self._manifest.units:
            if hmac.compare_digest(self._operation_id(unit), operation_id_sha256):
                return unit
        raise RequestBindingError("operation_not_found", status_code=404)


def verify_request_binding(response: RequestBindingResponse, *, result_hmac_key: bytes) -> bool:
    """Verify a response in tests and standalone adapter-side consumers."""

    if type(result_hmac_key) is not bytes or len(result_hmac_key) < 32:
        return False
    payload = response.model_dump(mode="json")
    presented = payload.pop("request_binding_hmac_sha256")
    root = hmac.new(result_hmac_key, _KEY_DOMAIN, hashlib.sha256).digest()
    key = hmac.new(root, _SIGNATURE_DOMAIN, hashlib.sha256).digest()
    return hmac.compare_digest(_signature(key, payload), presented)


def _signature(key: bytes, payload: dict[str, object]) -> str:
    return hmac.new(key, canonical_json_bytes(payload), hashlib.sha256).hexdigest()


__all__ = (
    "RequestBindingError",
    "RequestBindingRequest",
    "RequestBindingResponse",
    "RequestBindingService",
    "verify_request_binding",
)
