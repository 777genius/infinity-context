"""Typed authority and verifier for adapter-v5 extraction request bindings."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5HttpError

REQUEST_BINDING_SCHEMA = "mem0-oss-adapter-v5.request-binding.v1"
REQUEST_BINDING_DOMAIN = b"request-binding/v1"


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5RequestBindingContext:
    admission_commitment_sha256: str
    ingestion_manifest_sha256: str
    ingestion_root_sha256: str
    current_date_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    scope_sha256: str
    source_id: str
    source_sha256: str
    sequence: int

    @classmethod
    def from_authority(
        cls,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> ManagedMem0V5RequestBindingContext:
        if (
            type(authority) is not ManagedMem0V5ManifestAuthority
            or type(unit) is not ManagedMem0V5SourceUnit
            or type(admission) is not Mem0OssFullRunAdmission
            or unit.sequence >= len(authority.units)
            or authority.units[unit.sequence] != unit
            or admission.ingestion_manifest_sha256 != authority.ingestion_manifest_sha256
            or admission.ingestion_root_sha256 != authority.ingestion_root_sha256
        ):
            _fail("mem0_v5_managed_request_binding_authority_invalid")
        return cls(
            admission.commitment_sha256,
            authority.ingestion_manifest_sha256,
            authority.ingestion_root_sha256,
            canonical_sha256({"current_date": authority.current_date}),
            operation_id_sha256,
            unit.unit_identity_sha256,
            unit.unit_sha256,
            unit.scope_sha256,
            unit.source_id,
            unit.source_sha256,
            unit.sequence,
        )

    def __post_init__(self) -> None:
        digests = (
            self.admission_commitment_sha256,
            self.ingestion_manifest_sha256,
            self.ingestion_root_sha256,
            self.current_date_commitment_sha256,
            self.operation_id_sha256,
            self.unit_identity_sha256,
            self.unit_sha256,
            self.scope_sha256,
            self.source_sha256,
        )
        if (
            any(not is_sha256(value) for value in digests)
            or not _text(self.source_id)
            or type(self.sequence) is not int
            or not 0 <= self.sequence < 10_000
        ):
            _fail("mem0_v5_managed_request_binding_context_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5RequestBindingReceipt:
    request_body_sha256: str
    response_format_sha256: str
    evidence_commitment_sha256: str

    def __post_init__(self) -> None:
        if not all(
            is_sha256(value)
            for value in (
                self.request_body_sha256,
                self.response_format_sha256,
                self.evidence_commitment_sha256,
            )
        ):
            _fail("mem0_v5_managed_request_binding_result_invalid")


class ManagedMem0V5DispatchBindingPort(Protocol):
    def verify_request_binding(
        self,
        *,
        payload: object,
        context: ManagedMem0V5RequestBindingContext,
    ) -> ManagedMem0V5RequestBindingReceipt: ...


def verify_request_binding_payload(
    *,
    payload: object,
    context: ManagedMem0V5RequestBindingContext,
    hmac_key: bytes,
) -> ManagedMem0V5RequestBindingReceipt:
    if type(context) is not ManagedMem0V5RequestBindingContext or type(hmac_key) is not bytes:
        _fail("mem0_v5_managed_request_binding_context_invalid")
    value = _dict(payload)
    signature_field = "request_binding_hmac_sha256"
    expected_fields = {
        "schema_version",
        "admission_commitment_sha256",
        "ingestion_manifest_sha256",
        "ingestion_root_sha256",
        "current_date_commitment_sha256",
        "operation_id_sha256",
        "unit_identity_sha256",
        "unit_sha256",
        "scope_sha256",
        "source_id",
        "source_sha256",
        "sequence",
        "request_body_sha256",
        "response_format_sha256",
        signature_field,
    }
    if set(value) != expected_fields:
        _fail("mem0_v5_managed_request_binding_evidence_invalid")
    unsigned = {key: item for key, item in value.items() if key != signature_field}
    signature = value[signature_field]
    if not is_sha256(signature) or not hmac.compare_digest(
        hmac.new(hmac_key, _canonical(unsigned), hashlib.sha256).hexdigest(), signature
    ):
        _fail("mem0_v5_managed_request_binding_unauthenticated")
    expected = {
        "schema_version": REQUEST_BINDING_SCHEMA,
        "admission_commitment_sha256": context.admission_commitment_sha256,
        "ingestion_manifest_sha256": context.ingestion_manifest_sha256,
        "ingestion_root_sha256": context.ingestion_root_sha256,
        "current_date_commitment_sha256": context.current_date_commitment_sha256,
        "operation_id_sha256": context.operation_id_sha256,
        "unit_identity_sha256": context.unit_identity_sha256,
        "unit_sha256": context.unit_sha256,
        "scope_sha256": context.scope_sha256,
        "source_id": context.source_id,
        "source_sha256": context.source_sha256,
        "sequence": context.sequence,
    }
    if any(value[key] != expected_value for key, expected_value in expected.items()) or not all(
        is_sha256(value[key]) for key in ("request_body_sha256", "response_format_sha256")
    ):
        _fail("mem0_v5_managed_request_binding_evidence_invalid")
    return ManagedMem0V5RequestBindingReceipt(
        value["request_body_sha256"],
        value["response_format_sha256"],
        canonical_sha256(unsigned),
    )


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def _dict(value: object) -> dict[str, object]:
    if type(value) is not dict:
        _fail("mem0_v5_managed_request_binding_evidence_invalid")
    return value


def _text(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip() and len(value) <= 512


def _fail(code: str) -> None:
    raise Mem0V5HttpError(code)


__all__ = (
    "ManagedMem0V5DispatchBindingPort",
    "ManagedMem0V5RequestBindingContext",
    "ManagedMem0V5RequestBindingReceipt",
    "REQUEST_BINDING_DOMAIN",
    "REQUEST_BINDING_SCHEMA",
    "verify_request_binding_payload",
)
