"""Application DTOs for internal managed benchmark run lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.ports.benchmark_runs import (
    BenchmarkCleanupReceipt,
    BenchmarkRunRegistryRecord,
)


@dataclass(frozen=True, slots=True)
class RegisterBenchmarkRunCommand:
    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_slug: str
    idempotency_key_sha256: str


@dataclass(frozen=True, slots=True)
class RegisterBenchmarkRunResult:
    record: BenchmarkRunRegistryRecord
    created: bool


@dataclass(frozen=True, slots=True)
class CleanupBenchmarkRunCommand:
    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_id: str
    space_slug: str
    idempotency_key_sha256: str


@dataclass(frozen=True, slots=True)
class CleanupBenchmarkRunResult:
    receipt: BenchmarkCleanupReceipt
    replayed: bool


__all__ = (
    "CleanupBenchmarkRunCommand",
    "CleanupBenchmarkRunResult",
    "RegisterBenchmarkRunCommand",
    "RegisterBenchmarkRunResult",
)
