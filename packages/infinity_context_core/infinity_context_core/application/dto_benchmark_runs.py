"""Application DTOs for internal managed benchmark run lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from infinity_context_core.ports.benchmark_runs import (
    BenchmarkCleanupCompletionReceipt,
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
class SealProjectionManifestCommand:
    run_id_sha256: str
    projection_manifest_json: dict[str, object]
    projection_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class SealProjectionManifestResult:
    record: BenchmarkRunRegistryRecord
    replayed: bool


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
    projection_cleanup_state: Literal["pending", "blocked"]
    replayed: bool


@dataclass(frozen=True, slots=True)
class FinalizeBenchmarkRunCleanupCommand:
    run_id_sha256: str
    expected_cleanup_receipt_sha256: str
    idempotency_key_sha256: str


@dataclass(frozen=True, slots=True)
class FinalizeBenchmarkRunCleanupResult:
    receipt: BenchmarkCleanupCompletionReceipt
    replayed: bool


@dataclass(frozen=True, slots=True)
class GetBenchmarkRunLifecycleQuery:
    run_id_sha256: str


@dataclass(frozen=True, slots=True)
class GetBenchmarkRunLifecycleResult:
    record: BenchmarkRunRegistryRecord


__all__ = (
    "CleanupBenchmarkRunCommand",
    "CleanupBenchmarkRunResult",
    "FinalizeBenchmarkRunCleanupCommand",
    "FinalizeBenchmarkRunCleanupResult",
    "RegisterBenchmarkRunCommand",
    "GetBenchmarkRunLifecycleQuery",
    "GetBenchmarkRunLifecycleResult",
    "RegisterBenchmarkRunResult",
    "SealProjectionManifestCommand",
    "SealProjectionManifestResult",
)
