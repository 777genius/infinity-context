"""Provider-free ports and exact data contracts for Mem0 OSS full-run v5."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, final

MEM0_OSS_FULL_RUN_SCHEMA_VERSION = "mem0-benchmark-full-run.v5"
MEM0_OSS_FULL_RUN_MAX_OPERATIONS = 124_344
MEM0_OSS_FULL_RUN_MAX_EVIDENCE_PAGE = 100
MEM0_OSS_EMPTY_ROOT_SHA256 = hashlib.sha256(b"").hexdigest()

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SAFE_RUNTIME_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class Mem0OssFullRunError(RuntimeError):
    """Fixed-code error that never reflects remote or credential material."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Mem0OssFullRunState(StrEnum):
    UNBOUND = "unbound"
    ADMITTED = "admitted"
    ACTIVE = "active"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    FAILED = "failed"
    SEALED = "sealed"
    DELETING = "deleting"
    DELETED = "deleted"
    ABORTING = "aborting"
    ABORTED = "aborted"


class Mem0OssOperationState(StrEnum):
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    FAILED = "failed"
    RECEIPT_VERIFIED = "receipt_verified"
    STORAGE_VERIFIED = "storage_verified"
    COMMITTED = "committed"


class Mem0OssReceiptDisposition(StrEnum):
    COMPLETED = "completed"
    PROVIDER_FAILED = "provider_failed"
    REJECTED = "rejected"


def is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def canonical_sha256(value: Mapping[str, object] | Sequence[object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


@final
@dataclass(frozen=True, slots=True)
class Mem0OssManifestUnit:
    unit_identity_sha256: str
    unit_sha256: str
    scope_sha256: str

    def __post_init__(self) -> None:
        if any(
            not is_sha256(value)
            for value in (self.unit_identity_sha256, self.unit_sha256, self.scope_sha256)
        ):
            raise Mem0OssFullRunError("mem0_v5_manifest_unit_invalid")

    def payload(self) -> dict[str, str]:
        return {
            "unit_identity_sha256": self.unit_identity_sha256,
            "unit_sha256": self.unit_sha256,
            "scope_sha256": self.scope_sha256,
        }


def manifest_root_sha256(units: Sequence[Mem0OssManifestUnit]) -> str:
    if type(units) not in (tuple, list) or any(
        type(unit) is not Mem0OssManifestUnit for unit in units
    ):
        raise Mem0OssFullRunError("mem0_v5_manifest_inventory_invalid")
    return canonical_sha256({"units": [unit.payload() for unit in units]})


@final
@dataclass(frozen=True, slots=True)
class ManifestAuthorityResult:
    """Result returned by the configured authority port, not accepted from callers."""

    ingestion_manifest_sha256: str
    ingestion_root_sha256: str
    units: tuple[Mem0OssManifestUnit, ...]

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.ingestion_manifest_sha256)
            or not is_sha256(self.ingestion_root_sha256)
            or type(self.units) is not tuple
            or not 1 <= len(self.units) <= MEM0_OSS_FULL_RUN_MAX_OPERATIONS
            or any(type(unit) is not Mem0OssManifestUnit for unit in self.units)
        ):
            raise Mem0OssFullRunError("mem0_v5_manifest_authority_result_invalid")


class ManifestAuthorityVerificationPort(Protocol):
    def verify(self, *, payload: object) -> ManifestAuthorityResult: ...


@final
@dataclass(frozen=True, slots=True)
class Mem0OssAdmissionRequest:
    run_id: str
    route_sha256: str
    credential_binding_sha256: str
    model: str
    reasoning_effort: str
    service_tier: str
    runtime_source_revision: str
    runtime_source_sha256: str
    runtime_base_sha256: str
    expected_operation_count: int

    def __post_init__(self) -> None:
        if (
            type(self.run_id) is not str
            or _SAFE_ID.fullmatch(self.run_id) is None
            or any(
                not is_sha256(value)
                for value in (
                    self.route_sha256,
                    self.credential_binding_sha256,
                    self.runtime_source_sha256,
                    self.runtime_base_sha256,
                )
            )
            or type(self.runtime_source_revision) is not str
            or _SAFE_ID.fullmatch(self.runtime_source_revision) is None
            or any(
                type(value) is not str or _SAFE_RUNTIME_VALUE.fullmatch(value) is None
                for value in (self.model, self.reasoning_effort, self.service_tier)
            )
            or type(self.expected_operation_count) is not int
            or not 1 <= self.expected_operation_count <= MEM0_OSS_FULL_RUN_MAX_OPERATIONS
        ):
            raise Mem0OssFullRunError("mem0_v5_admission_request_invalid")


@final
@dataclass(frozen=True, slots=True)
class Mem0OssFullRunAdmission:
    """Immutable authority created by the application service after manifest verification."""

    request: Mem0OssAdmissionRequest
    ingestion_manifest_sha256: str
    ingestion_root_sha256: str
    ingestion_unit_count: int
    schema_version: str = MEM0_OSS_FULL_RUN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.request) is not Mem0OssAdmissionRequest
            or self.schema_version != MEM0_OSS_FULL_RUN_SCHEMA_VERSION
            or not is_sha256(self.ingestion_manifest_sha256)
            or not is_sha256(self.ingestion_root_sha256)
            or type(self.ingestion_unit_count) is not int
            or self.ingestion_unit_count != self.request.expected_operation_count
        ):
            raise Mem0OssFullRunError("mem0_v5_admission_invalid")

    @property
    def commitment_sha256(self) -> str:
        return canonical_sha256(self.public_payload())

    def public_payload(self) -> dict[str, object]:
        request = self.request
        return {
            "schema_version": self.schema_version,
            "run_id_sha256": hashlib.sha256(request.run_id.encode()).hexdigest(),
            "ingestion_manifest_sha256": self.ingestion_manifest_sha256,
            "ingestion_root_sha256": self.ingestion_root_sha256,
            "ingestion_unit_count": self.ingestion_unit_count,
            "route_sha256": request.route_sha256,
            "credential_binding_sha256": request.credential_binding_sha256,
            "model": request.model,
            "reasoning_effort": request.reasoning_effort,
            "service_tier": request.service_tier,
            "runtime_source_revision": request.runtime_source_revision,
            "runtime_source_sha256": request.runtime_source_sha256,
            "runtime_base_sha256": request.runtime_base_sha256,
            "expected_operation_count": request.expected_operation_count,
            "retries": 0,
            "extraction_calls_per_unit": 1,
        }


@final
@dataclass(frozen=True, slots=True)
class RuntimeReceiptVerificationContext:
    admission_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    route_sha256: str
    scope_sha256: str
    readback_only: bool

    def __post_init__(self) -> None:
        if (
            any(
                not is_sha256(value)
                for value in (
                    self.admission_commitment_sha256,
                    self.operation_id_sha256,
                    self.unit_identity_sha256,
                    self.unit_sha256,
                    self.route_sha256,
                    self.scope_sha256,
                )
            )
            or type(self.readback_only) is not bool
        ):
            raise Mem0OssFullRunError("mem0_v5_receipt_context_invalid")


@final
@dataclass(frozen=True, slots=True)
class RuntimeReceiptVerificationResult:
    admission_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    route_sha256: str
    scope_sha256: str
    provider_receipt_sha256: str
    sequence: int
    request_body_sha256: str
    output_text_sha256: str
    runtime_binding_commitment_sha256: str
    disposition: Mem0OssReceiptDisposition
    extraction_calls: int
    retry_count: int
    request_tokens: int
    response_tokens: int

    def __post_init__(self) -> None:
        digests = (
            self.admission_commitment_sha256,
            self.operation_id_sha256,
            self.unit_identity_sha256,
            self.unit_sha256,
            self.route_sha256,
            self.scope_sha256,
            self.provider_receipt_sha256,
            self.request_body_sha256,
            self.output_text_sha256,
            self.runtime_binding_commitment_sha256,
        )
        if (
            any(not is_sha256(value) for value in digests)
            or type(self.sequence) is not int
            or not 0 <= self.sequence < MEM0_OSS_FULL_RUN_MAX_OPERATIONS
            or type(self.disposition) is not Mem0OssReceiptDisposition
            or type(self.extraction_calls) is not int
            or self.extraction_calls != 1
            or type(self.retry_count) is not int
            or self.retry_count != 0
            or not _bounded_tokens(self.request_tokens)
            or not _bounded_tokens(self.response_tokens)
        ):
            raise Mem0OssFullRunError("mem0_v5_receipt_result_invalid")


class RuntimeReceiptVerificationPort(Protocol):
    def mark_outcome_unknown(
        self,
        *,
        context: RuntimeReceiptVerificationContext,
    ) -> None:
        """Idempotently mark one exact dispatch as outcome-unknown."""
        ...

    def verify_dispatch_receipt(
        self,
        *,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult: ...

    def verify_status_readback(
        self,
        *,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult: ...


@final
@dataclass(frozen=True, slots=True)
class StorageVerificationContext:
    admission_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    route_sha256: str
    scope_sha256: str
    provider_receipt_sha256: str

    def __post_init__(self) -> None:
        if any(
            not is_sha256(value)
            for value in (
                self.admission_commitment_sha256,
                self.operation_id_sha256,
                self.unit_identity_sha256,
                self.unit_sha256,
                self.route_sha256,
                self.scope_sha256,
                self.provider_receipt_sha256,
            )
        ):
            raise Mem0OssFullRunError("mem0_v5_storage_context_invalid")


@final
@dataclass(frozen=True, slots=True)
class StorageVerificationResult:
    admission_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    route_sha256: str
    scope_sha256: str
    provider_receipt_sha256: str
    stored_identity_sha256: str
    stored_record_count: int

    def __post_init__(self) -> None:
        values = (
            self.admission_commitment_sha256,
            self.operation_id_sha256,
            self.unit_identity_sha256,
            self.unit_sha256,
            self.route_sha256,
            self.scope_sha256,
            self.provider_receipt_sha256,
            self.stored_identity_sha256,
        )
        if (
            any(not is_sha256(value) for value in values)
            or type(self.stored_record_count) is not int
            or not 0 <= self.stored_record_count <= 1_000_000
        ):
            raise Mem0OssFullRunError("mem0_v5_storage_result_invalid")


class StorageVerificationPort(Protocol):
    def verify(
        self,
        *,
        payload: object,
        context: StorageVerificationContext,
    ) -> StorageVerificationResult: ...


@final
@dataclass(frozen=True, slots=True)
class CleanupVerificationContext:
    admission_commitment_sha256: str
    seal_commitment_sha256: str | None
    operation_root_sha256: str | None
    operation_inventory_root_sha256: str
    expected_operation_count: int
    aborting: bool

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.admission_commitment_sha256)
            or (
                self.seal_commitment_sha256 is not None
                and not is_sha256(self.seal_commitment_sha256)
            )
            or (
                self.operation_root_sha256 is not None and not is_sha256(self.operation_root_sha256)
            )
            or not is_sha256(self.operation_inventory_root_sha256)
            or type(self.expected_operation_count) is not int
            or self.expected_operation_count < 1
            or type(self.aborting) is not bool
        ):
            raise Mem0OssFullRunError("mem0_v5_cleanup_context_invalid")


@final
@dataclass(frozen=True, slots=True)
class CleanupVerificationResult:
    admission_commitment_sha256: str
    seal_commitment_sha256: str | None
    operation_root_sha256: str | None
    operation_inventory_root_sha256: str
    deleted_operation_count: int
    residual_record_count: int
    residual_root_sha256: str

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.admission_commitment_sha256)
            or (
                self.seal_commitment_sha256 is not None
                and not is_sha256(self.seal_commitment_sha256)
            )
            or (
                self.operation_root_sha256 is not None and not is_sha256(self.operation_root_sha256)
            )
            or not is_sha256(self.operation_inventory_root_sha256)
            or type(self.deleted_operation_count) is not int
            or self.deleted_operation_count < 0
            or type(self.residual_record_count) is not int
            or self.residual_record_count < 0
            or not is_sha256(self.residual_root_sha256)
        ):
            raise Mem0OssFullRunError("mem0_v5_cleanup_result_invalid")


class CleanupVerificationPort(Protocol):
    def verify(
        self,
        *,
        payload: object,
        context: CleanupVerificationContext,
    ) -> CleanupVerificationResult: ...


def _bounded_tokens(value: object) -> bool:
    return type(value) is int and 0 <= value <= 10_000_000


__all__ = [
    "CleanupVerificationContext",
    "CleanupVerificationPort",
    "CleanupVerificationResult",
    "MEM0_OSS_EMPTY_ROOT_SHA256",
    "MEM0_OSS_FULL_RUN_MAX_EVIDENCE_PAGE",
    "MEM0_OSS_FULL_RUN_MAX_OPERATIONS",
    "MEM0_OSS_FULL_RUN_SCHEMA_VERSION",
    "ManifestAuthorityResult",
    "ManifestAuthorityVerificationPort",
    "Mem0OssAdmissionRequest",
    "Mem0OssFullRunAdmission",
    "Mem0OssFullRunError",
    "Mem0OssFullRunState",
    "Mem0OssManifestUnit",
    "Mem0OssOperationState",
    "Mem0OssReceiptDisposition",
    "RuntimeReceiptVerificationContext",
    "RuntimeReceiptVerificationPort",
    "RuntimeReceiptVerificationResult",
    "StorageVerificationContext",
    "StorageVerificationPort",
    "StorageVerificationResult",
    "canonical_sha256",
    "is_sha256",
    "manifest_root_sha256",
]
