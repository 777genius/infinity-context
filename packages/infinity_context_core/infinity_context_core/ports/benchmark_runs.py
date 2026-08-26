"""Ports and immutable records for managed benchmark run lifecycle."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from infinity_context_core.ports.benchmark_cleanup_plan import ManagedBenchmarkCleanupPlan

_MANAGED_BENCHMARK_SPACE_ID = re.compile(r"^benchmark-space-[0-9a-f]{48}$")


def is_managed_benchmark_space_id(value: object) -> bool:
    """Return whether a space ID can belong to the managed benchmark registry."""

    return type(value) is str and _MANAGED_BENCHMARK_SPACE_ID.fullmatch(value) is not None


BenchmarkRunState = Literal[
    "active",
    "cleanup_pending",
    "cleanup_complete",
    "cleanup_aborted",
]
ProjectionCleanupState = Literal[
    "unsealed",
    "sealed",
    "pending",
    "blocked",
    "complete",
    "unsealed_abort_complete",
]
CleanupPlanState = Literal["sealed", "recovery_blocked"]


@dataclass(frozen=True, slots=True)
class BenchmarkCleanupCounts:
    facts: int
    documents: int
    chunks: int
    episodes: int
    threads: int
    memory_scopes: int
    obsolete_upsert_jobs: int
    vector_delete_jobs: int
    graph_delete_jobs: int
    cognee_delete_jobs: int


@dataclass(frozen=True, slots=True)
class BenchmarkCleanupReceipt:
    run_id_sha256: str
    space_id: str
    space_slug: str
    disposition: Literal["cleanup_pending"]
    projection_cleanup: Literal["pending", "blocked"]
    counts: BenchmarkCleanupCounts
    vector_delete_outbox_ids: tuple[int, ...]
    graph_delete_outbox_ids: tuple[int, ...]
    cognee_delete_outbox_ids: tuple[int, ...]
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class BenchmarkProjectionCleanupProof:
    """Internal provider-absence proof bound to one pending cleanup."""

    run_id_sha256: str
    projection_manifest_sha256: str
    cleanup_initiation_receipt_sha256: str
    qdrant_absent: bool
    graphiti_absent: bool
    cognee_absent: bool


@dataclass(frozen=True, slots=True)
class BenchmarkCleanupCompletionReceipt:
    """Immutable server-generated proof of terminal benchmark cleanup."""

    run_id_sha256: str
    space_id: str
    space_slug: str
    disposition: Literal["cleanup_complete"]
    projection_cleanup: Literal["complete"]
    projection_manifest_sha256: str
    cleanup_initiation_receipt_sha256: str
    projection_absence_proof_sha256: str
    completed_at: datetime
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class BenchmarkAbortCompletionReceipt:
    """Terminal proof for manifestless abort cleanup without provider probing."""

    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_id: str
    space_slug: str
    disposition: Literal["abort_complete"]
    projection_cleanup: Literal["unsealed_abort_complete"]
    cleanup_initiation_receipt_sha256: str
    cleanup_plan_sha256: str
    projection_absence_proof_sha256: str
    completed_at: datetime
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class BenchmarkRunRegistryRecord:
    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_id: str
    space_slug: str
    idempotency_key_sha256: str
    registration_fingerprint_sha256: str
    state: BenchmarkRunState
    projection_manifest_json: dict[str, object] | None
    projection_manifest_sha256: str | None
    projection_cleanup_state: ProjectionCleanupState
    cleanup_fingerprint_sha256: str | None
    cleanup_receipt: BenchmarkCleanupReceipt | None
    finalization_fingerprint_sha256: str | None
    completion_receipt: BenchmarkCleanupCompletionReceipt | BenchmarkAbortCompletionReceipt | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    cleanup_plan_json: dict[str, object] | None = None
    cleanup_plan_sha256: str | None = None
    cleanup_plan_state: CleanupPlanState = "recovery_blocked"


class BenchmarkProjectionAbsencePort(Protocol):
    async def prove_absence(
        self,
        *,
        record: BenchmarkRunRegistryRecord,
    ) -> BenchmarkProjectionCleanupProof: ...


class BenchmarkRunRepositoryPort(Protocol):
    async def get_by_run_id_sha256(
        self,
        run_id_sha256: str,
        *,
        for_update: bool = False,
    ) -> BenchmarkRunRegistryRecord | None: ...

    async def get_by_space_id(
        self,
        space_id: str,
    ) -> BenchmarkRunRegistryRecord | None: ...

    async def get_by_space_slug(
        self,
        space_slug: str,
    ) -> BenchmarkRunRegistryRecord | None: ...

    async def get_by_idempotency_key_sha256(
        self,
        idempotency_key_sha256: str,
    ) -> BenchmarkRunRegistryRecord | None: ...

    async def add(self, record: BenchmarkRunRegistryRecord) -> None: ...

    async def load_cleanup_plan(self, space_id: str) -> ManagedBenchmarkCleanupPlan | None: ...

    async def seal_projection_manifest(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        projection_manifest_json: dict[str, object],
        projection_manifest_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord: ...

    async def begin_cleanup(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        cleanup_fingerprint_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord: ...

    async def finalize_cleanup(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        finalization_fingerprint_sha256: str,
        projection_absence_proof_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord: ...

    async def finalize_unsealed_abort(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        finalization_fingerprint_sha256: str,
        projection_absence_proof_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord: ...


__all__ = (
    "BenchmarkCleanupCompletionReceipt",
    "BenchmarkAbortCompletionReceipt",
    "BenchmarkCleanupCounts",
    "BenchmarkCleanupReceipt",
    "BenchmarkProjectionAbsencePort",
    "BenchmarkProjectionCleanupProof",
    "BenchmarkRunRegistryRecord",
    "BenchmarkRunRepositoryPort",
    "BenchmarkRunState",
    "CleanupPlanState",
    "ProjectionCleanupState",
    "is_managed_benchmark_space_id",
)
