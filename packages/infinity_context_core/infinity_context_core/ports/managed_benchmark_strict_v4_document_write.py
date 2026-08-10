"""Narrow authority port for strict-v4 managed document writes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_core.domain.errors import MemoryValidationError

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManagedBenchmarkStrictV4DocumentWriteError(MemoryValidationError):
    """Fail-closed strict-v4 document-authority rejection."""


def _digest(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedBenchmarkStrictV4DocumentWriteError(
            "managed_benchmark_strict_v4_document_write_digest_invalid"
        )
    return value


def _text(value: object) -> str:
    if type(value) is not str or not value:
        raise ManagedBenchmarkStrictV4DocumentWriteError(
            "managed_benchmark_strict_v4_document_write_text_invalid"
        )
    return value


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkStrictV4DocumentClaim:
    """Exact document material presented to the sealed expected-row index."""

    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_id: str
    space_slug: str
    memory_scope_external_ref: str
    thread_external_ref: str
    source_identity_sha256: str
    source_content_sha256: str
    operation_commitment_sha256: str
    source_refs_sha256: str
    source_ref_root_sha256: str
    ordered_source_ref_descriptor_sha256: tuple[str, ...]
    fragments_sha256: str
    fragment_root_sha256: str
    ordered_fragment_descriptor_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (
            self.run_id_sha256,
            self.binding_commitment_sha256,
            self.infinity_target_identity_sha256,
            self.source_identity_sha256,
            self.source_content_sha256,
            self.operation_commitment_sha256,
            self.source_refs_sha256,
            self.source_ref_root_sha256,
            self.fragments_sha256,
            self.fragment_root_sha256,
            *self.ordered_source_ref_descriptor_sha256,
            *self.ordered_fragment_descriptor_sha256,
        ):
            _digest(value)
        for value in (
            self.space_id,
            self.space_slug,
            self.memory_scope_external_ref,
            self.thread_external_ref,
        ):
            _text(value)
        if not self.ordered_fragment_descriptor_sha256:
            raise ManagedBenchmarkStrictV4DocumentWriteError(
                "managed_benchmark_strict_v4_document_write_fragments_invalid"
            )


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkStrictV4DocumentAdmission:
    operation_sha256: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _digest(self.operation_sha256)
        prefix = "managed-benchmark-document-v4-"
        if (
            type(self.idempotency_key) is not str
            or not self.idempotency_key.startswith(prefix)
            or len(self.idempotency_key) != len(prefix) + 64
        ):
            raise ManagedBenchmarkStrictV4DocumentWriteError(
                "managed_benchmark_strict_v4_document_write_admission_invalid"
            )


class ManagedBenchmarkStrictV4DocumentAuthorityPort(Protocol):
    """Authenticate one exact document operation against durable v4 state."""

    def admit_document(
        self, claim: ManagedBenchmarkStrictV4DocumentClaim
    ) -> ManagedBenchmarkStrictV4DocumentAdmission: ...


__all__ = (
    "ManagedBenchmarkStrictV4DocumentAdmission",
    "ManagedBenchmarkStrictV4DocumentAuthorityPort",
    "ManagedBenchmarkStrictV4DocumentClaim",
    "ManagedBenchmarkStrictV4DocumentWriteError",
)
