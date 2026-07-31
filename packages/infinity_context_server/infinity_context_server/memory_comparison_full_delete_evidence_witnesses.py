"""Typed scoped cleanup/readback witnesses for terminal delete verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.public_benchmark_models import BenchmarkValidationError

DELETE_REQUEST_SCHEMA_VERSION = "memory-comparison-full-delete-request.v1"
INFINITY_BACKEND_KIND = "infinity"
MEM0_BACKEND_KIND = "mem0"
BACKEND_KINDS = (INFINITY_BACKEND_KIND, MEM0_BACKEND_KIND)
MAX_DELETE_ID_CHARS = 512


class DeleteEvidenceVerificationError(BenchmarkValidationError):
    """Raised when terminal scoped absence cannot be proven exactly."""


@final
@dataclass(frozen=True, slots=True)
class DeleteScopeRequest:
    """Exact request passed to one cleanup or readback operation."""

    run_id: str
    profile_id: str
    backend_kind: str
    backend_id: str
    scope_id: str
    source_id: str
    attempt: int

    def __post_init__(self) -> None:
        for name, value in (
            ("run_id", self.run_id),
            ("profile_id", self.profile_id),
            ("backend_id", self.backend_id),
            ("scope_id", self.scope_id),
            ("source_id", self.source_id),
        ):
            validate_delete_id(value, field_name=f"delete request {name}")
        if self.backend_kind not in BACKEND_KINDS:
            raise DeleteEvidenceVerificationError("delete request backend kind is invalid")
        if type(self.attempt) is not int or self.attempt not in (1, 2):
            raise DeleteEvidenceVerificationError("delete request attempt is invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("DeleteScopeRequest is sealed")


@final
@dataclass(frozen=True, slots=True)
class InfinityCleanupWitness:
    run_id: str
    profile_id: str
    backend_id: str
    scope_id: str
    source_id: str
    attempt: int
    acknowledged: bool
    canonical_deleted_count: int
    derived_deleted_count: int
    already_absent: bool

    def __post_init__(self) -> None:
        validate_cleanup_witness(self, backend_kind=INFINITY_BACKEND_KIND)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("InfinityCleanupWitness is sealed")


@final
@dataclass(frozen=True, slots=True)
class InfinityReadbackWitness:
    run_id: str
    profile_id: str
    backend_id: str
    scope_id: str
    source_id: str
    attempt: int
    canonical_remaining_count: int
    derived_remaining_count: int

    def __post_init__(self) -> None:
        validate_readback_witness(self, backend_kind=INFINITY_BACKEND_KIND)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("InfinityReadbackWitness is sealed")


@final
@dataclass(frozen=True, slots=True)
class Mem0CleanupWitness:
    run_id: str
    profile_id: str
    backend_id: str
    scope_id: str
    source_id: str
    attempt: int
    acknowledged: bool
    deleted_count: int
    already_absent: bool

    def __post_init__(self) -> None:
        validate_cleanup_witness(self, backend_kind=MEM0_BACKEND_KIND)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("Mem0CleanupWitness is sealed")


@final
@dataclass(frozen=True, slots=True)
class Mem0ReadbackWitness:
    run_id: str
    profile_id: str
    backend_id: str
    scope_id: str
    source_id: str
    attempt: int
    remaining_count: int

    def __post_init__(self) -> None:
        validate_readback_witness(self, backend_kind=MEM0_BACKEND_KIND)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("Mem0ReadbackWitness is sealed")


CleanupWitness = InfinityCleanupWitness | Mem0CleanupWitness
ReadbackWitness = InfinityReadbackWitness | Mem0ReadbackWitness


class DeleteVerificationPort(Protocol):
    """Minimal backend boundary for scoped cleanup and exact readback."""

    def cleanup(self, request: DeleteScopeRequest) -> CleanupWitness: ...

    def readback(self, request: DeleteScopeRequest) -> ReadbackWitness: ...


def cleanup_witness_snapshot(
    witness: object,
    *,
    request: DeleteScopeRequest,
    require_idempotent: bool,
) -> tuple[object, ...]:
    expected_type = (
        InfinityCleanupWitness
        if request.backend_kind == INFINITY_BACKEND_KIND
        else Mem0CleanupWitness
    )
    if type(witness) is not expected_type:
        raise DeleteEvidenceVerificationError("delete cleanup witness type is invalid")
    identity = witness_identity(witness)
    acknowledged = witness.acknowledged
    already_absent = witness.already_absent
    counts = (
        (witness.canonical_deleted_count, witness.derived_deleted_count)
        if request.backend_kind == INFINITY_BACKEND_KIND
        else (witness.deleted_count,)
    )
    _validate_identity_snapshot(identity)
    if identity != request_identity(request):
        raise DeleteEvidenceVerificationError("delete witness scope binding mismatch")
    if type(acknowledged) is not bool or type(already_absent) is not bool:
        raise DeleteEvidenceVerificationError("delete cleanup flags must be exact booleans")
    if any(type(count) is not int or count < 0 for count in counts):
        raise DeleteEvidenceVerificationError("delete cleanup counts are invalid")
    if acknowledged is not True:
        raise DeleteEvidenceVerificationError("delete cleanup was not acknowledged")
    total = sum(counts)
    if already_absent is not (total == 0):
        raise DeleteEvidenceVerificationError("delete cleanup absence claim is inconsistent")
    if require_idempotent and (total != 0 or already_absent is not True):
        raise DeleteEvidenceVerificationError("second delete cleanup was not idempotent")
    return (*identity, True, *counts, already_absent)


def readback_witness_snapshot(
    witness: object,
    *,
    request: DeleteScopeRequest,
) -> tuple[object, ...]:
    expected_type = (
        InfinityReadbackWitness
        if request.backend_kind == INFINITY_BACKEND_KIND
        else Mem0ReadbackWitness
    )
    if type(witness) is not expected_type:
        raise DeleteEvidenceVerificationError("delete readback witness type is invalid")
    identity = witness_identity(witness)
    counts = (
        (witness.canonical_remaining_count, witness.derived_remaining_count)
        if request.backend_kind == INFINITY_BACKEND_KIND
        else (witness.remaining_count,)
    )
    _validate_identity_snapshot(identity)
    if identity != request_identity(request):
        raise DeleteEvidenceVerificationError("delete witness scope binding mismatch")
    if any(type(count) is not int or count < 0 for count in counts):
        raise DeleteEvidenceVerificationError("delete readback counts are invalid")
    if any(count != 0 for count in counts):
        raise DeleteEvidenceVerificationError("delete readback still contains scoped data")
    return (*identity, *counts)


def validate_cleanup_witness(witness: object, *, backend_kind: str) -> None:
    validate_witness_common(witness)
    if type(witness.acknowledged) is not bool or type(witness.already_absent) is not bool:
        raise DeleteEvidenceVerificationError("delete cleanup flags must be exact booleans")
    counts = (
        (witness.canonical_deleted_count, witness.derived_deleted_count)
        if backend_kind == INFINITY_BACKEND_KIND
        else (witness.deleted_count,)
    )
    if any(type(count) is not int or count < 0 for count in counts):
        raise DeleteEvidenceVerificationError("delete cleanup counts are invalid")


def validate_readback_witness(witness: object, *, backend_kind: str) -> None:
    validate_witness_common(witness)
    counts = (
        (witness.canonical_remaining_count, witness.derived_remaining_count)
        if backend_kind == INFINITY_BACKEND_KIND
        else (witness.remaining_count,)
    )
    if any(type(count) is not int or count < 0 for count in counts):
        raise DeleteEvidenceVerificationError("delete readback counts are invalid")


def validate_witness_common(witness: object) -> None:
    for name in ("run_id", "profile_id", "backend_id", "scope_id", "source_id"):
        validate_delete_id(getattr(witness, name), field_name=f"delete witness {name}")
    if type(witness.attempt) is not int or witness.attempt not in (1, 2):
        raise DeleteEvidenceVerificationError("delete witness attempt is invalid")


def validate_witness_binding(witness: object, request: DeleteScopeRequest) -> None:
    if witness_identity(witness) != (
        request.run_id,
        request.profile_id,
        request.backend_id,
        request.scope_id,
        request.source_id,
        request.attempt,
    ):
        raise DeleteEvidenceVerificationError("delete witness scope binding mismatch")


def witness_identity(witness: object) -> tuple[object, ...]:
    return (
        witness.run_id,
        witness.profile_id,
        witness.backend_id,
        witness.scope_id,
        witness.source_id,
        witness.attempt,
    )


def request_identity(request: DeleteScopeRequest) -> tuple[object, ...]:
    return (
        request.run_id,
        request.profile_id,
        request.backend_id,
        request.scope_id,
        request.source_id,
        request.attempt,
    )


def _validate_identity_snapshot(identity: tuple[object, ...]) -> None:
    for name, value in zip(
        ("run_id", "profile_id", "backend_id", "scope_id", "source_id"),
        identity[:5],
        strict=True,
    ):
        validate_delete_id(value, field_name=f"delete witness {name}")
    if type(identity[5]) is not int or identity[5] not in (1, 2):
        raise DeleteEvidenceVerificationError("delete witness attempt is invalid")


def validate_delete_id(value: object, *, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > MAX_DELETE_ID_CHARS
    ):
        raise DeleteEvidenceVerificationError(f"{field_name} is invalid")


__all__ = (
    "DELETE_REQUEST_SCHEMA_VERSION",
    "DeleteEvidenceVerificationError",
    "DeleteScopeRequest",
    "DeleteVerificationPort",
    "InfinityCleanupWitness",
    "InfinityReadbackWitness",
    "Mem0CleanupWitness",
    "Mem0ReadbackWitness",
)
