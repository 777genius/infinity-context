"""Narrow authority port for strict-v4 managed benchmark writes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_core.domain.errors import MemoryValidationError

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManagedBenchmarkStrictV4WriteError(MemoryValidationError):
    """Fail-closed strict-v4 write-authority rejection."""


def _digest(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedBenchmarkStrictV4WriteError("managed_benchmark_strict_v4_write_digest_invalid")
    return value


def _text(value: object) -> str:
    if type(value) is not str or not value:
        raise ManagedBenchmarkStrictV4WriteError("managed_benchmark_strict_v4_write_text_invalid")
    return value


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkStrictV4CorpusClaim:
    """Exact scope/thread pair presented before canonical corpus creation."""

    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_id: str
    space_slug: str
    memory_scope_external_ref: str
    thread_external_ref: str

    def __post_init__(self) -> None:
        for value in (
            self.run_id_sha256,
            self.binding_commitment_sha256,
            self.infinity_target_identity_sha256,
        ):
            _digest(value)
        for value in (
            self.space_id,
            self.space_slug,
            self.memory_scope_external_ref,
            self.thread_external_ref,
        ):
            _text(value)


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkStrictV4CorpusAdmission:
    corpus_identity_sha256: str

    def __post_init__(self) -> None:
        _digest(self.corpus_identity_sha256)


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkStrictV4FactClaim:
    """Canonical fact material presented to the sealed strict-v4 authority."""

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
            *self.ordered_source_ref_descriptor_sha256,
        ):
            _digest(value)
        for value in (
            self.space_id,
            self.space_slug,
            self.memory_scope_external_ref,
            self.thread_external_ref,
        ):
            _text(value)
        if len(self.ordered_source_ref_descriptor_sha256) != 1:
            raise ManagedBenchmarkStrictV4WriteError(
                "managed_benchmark_strict_v4_write_source_refs_invalid"
            )


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkStrictV4FactAdmission:
    operation_sha256: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _digest(self.operation_sha256)
        if (
            type(self.idempotency_key) is not str
            or not self.idempotency_key.startswith("managed-benchmark-fact-v4-")
            or len(self.idempotency_key) != len("managed-benchmark-fact-v4-") + 64
        ):
            raise ManagedBenchmarkStrictV4WriteError(
                "managed_benchmark_strict_v4_write_admission_invalid"
            )


class ManagedBenchmarkStrictV4CorpusAuthorityPort(Protocol):
    """Authenticate an exact scope/thread corpus before canonical creation."""

    def admit_corpus(
        self, claim: ManagedBenchmarkStrictV4CorpusClaim
    ) -> ManagedBenchmarkStrictV4CorpusAdmission: ...


class ManagedBenchmarkStrictV4FactAuthorityPort(
    ManagedBenchmarkStrictV4CorpusAuthorityPort, Protocol
):
    """Authenticate one exact fact operation against durable strict-v4 state."""

    def admit_fact(
        self, claim: ManagedBenchmarkStrictV4FactClaim
    ) -> ManagedBenchmarkStrictV4FactAdmission: ...


__all__ = (
    "ManagedBenchmarkStrictV4CorpusAuthorityPort",
    "ManagedBenchmarkStrictV4FactAdmission",
    "ManagedBenchmarkStrictV4FactAuthorityPort",
    "ManagedBenchmarkStrictV4FactClaim",
    "ManagedBenchmarkStrictV4CorpusAdmission",
    "ManagedBenchmarkStrictV4CorpusClaim",
    "ManagedBenchmarkStrictV4WriteError",
)
