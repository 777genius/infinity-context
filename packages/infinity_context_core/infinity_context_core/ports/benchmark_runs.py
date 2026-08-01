"""Ports and immutable records for managed benchmark run lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

BenchmarkRunState = Literal["active", "cleanup_pending"]
ProjectionCleanupState = Literal[
    "unsealed",
    "sealed",
    "pending",
    "blocked",
]


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
    created_at: datetime
    updated_at: datetime


class BenchmarkRunRepositoryPort(Protocol):
    async def get_by_run_id_sha256(
        self,
        run_id_sha256: str,
        *,
        for_update: bool = False,
    ) -> BenchmarkRunRegistryRecord | None: ...

    async def get_by_idempotency_key_sha256(
        self,
        idempotency_key_sha256: str,
    ) -> BenchmarkRunRegistryRecord | None: ...

    async def add(self, record: BenchmarkRunRegistryRecord) -> None: ...

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


__all__ = (
    "BenchmarkCleanupCounts",
    "BenchmarkCleanupReceipt",
    "BenchmarkRunRegistryRecord",
    "BenchmarkRunRepositoryPort",
    "BenchmarkRunState",
    "ProjectionCleanupState",
)
