"""Exact canonical and provider evidence for unsealed benchmark recovery."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from infinity_context_core.ports.benchmark_runs import BenchmarkRunRegistryRecord

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_SCOPES = 10_000
_MAX_IDENTITIES = 100_000


@dataclass(frozen=True, slots=True)
class BenchmarkUnsealedProjectionScope:
    memory_scope_id: str
    thread_id: str | None
    chunk_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _identity(self.memory_scope_id)
        if self.thread_id is not None:
            _identity(self.thread_id)
        _identities(self.chunk_ids)
        _identities(self.fact_ids)


@dataclass(frozen=True, slots=True)
class BenchmarkUnsealedRecoveryInventory:
    """Bound allowlist reconstructed from canonical tombstones and cleanup jobs."""

    run_id_sha256: str
    space_id: str
    cleanup_plan_sha256: str
    cleanup_receipt_sha256: str
    scopes: tuple[BenchmarkUnsealedProjectionScope, ...]
    document_source_external_ids: tuple[str, ...]
    episode_source_external_ids: tuple[str, ...]
    chunk_source_external_ids: tuple[str, ...]
    chunk_source_hashes: tuple[str, ...]
    delete_outbox_ids: tuple[int, ...]
    inventory_sha256: str

    def __post_init__(self) -> None:
        _digest(self.run_id_sha256)
        _identity(self.space_id)
        for value in (
            self.cleanup_plan_sha256,
            self.cleanup_receipt_sha256,
            self.inventory_sha256,
        ):
            _digest(value)
        if (
            not self.scopes
            or len(self.scopes) > _MAX_SCOPES
            or any(type(item) is not BenchmarkUnsealedProjectionScope for item in self.scopes)
        ):
            raise ValueError("recovery inventory scopes are invalid")
        for values in (
            self.document_source_external_ids,
            self.episode_source_external_ids,
            self.chunk_source_external_ids,
            self.chunk_source_hashes,
        ):
            _identities(values)
        if self.delete_outbox_ids != tuple(sorted(set(self.delete_outbox_ids))) or any(
            type(value) is not int or value <= 0 for value in self.delete_outbox_ids
        ):
            raise ValueError("recovery inventory outbox IDs are invalid")


@dataclass(frozen=True, slots=True)
class BenchmarkProjectionPassReceipt:
    lane: Literal["qdrant", "graphiti"]
    target_commitment_sha256: str
    pass_index: Literal[1, 2]
    observed_count: int
    absent: bool
    receipt_sha256: str

    def __post_init__(self) -> None:
        if self.lane not in {"qdrant", "graphiti"} or self.pass_index not in {1, 2}:
            raise ValueError("projection pass identity is invalid")
        if type(self.observed_count) is not int or self.observed_count < 0:
            raise ValueError("projection pass count is invalid")
        if type(self.absent) is not bool:
            raise ValueError("projection pass absence is invalid")
        _digest(self.target_commitment_sha256)
        _digest(self.receipt_sha256)


class BenchmarkQdrantRecoveryEvidencePort(Protocol):
    async def delete_benchmark_space_two_pass(
        self,
        *,
        space_id: str,
        scopes: tuple[BenchmarkUnsealedProjectionScope, ...],
    ) -> tuple[BenchmarkProjectionPassReceipt, BenchmarkProjectionPassReceipt]: ...


class BenchmarkGraphitiRecoveryEvidencePort(Protocol):
    async def delete_benchmark_space_two_pass(
        self,
        *,
        space_id: str,
        scopes: tuple[BenchmarkUnsealedProjectionScope, ...],
    ) -> tuple[BenchmarkProjectionPassReceipt, BenchmarkProjectionPassReceipt]: ...


@dataclass(frozen=True, slots=True)
class BenchmarkUnsealedProjectionCleanupProof:
    """Direct two-pass absence proof bound to all pending recovery inputs."""

    run_id_sha256: str
    cleanup_plan_sha256: str
    cleanup_receipt_sha256: str
    inventory_sha256: str
    qdrant_pass_receipt_sha256s: tuple[str, str]
    graphiti_pass_receipt_sha256s: tuple[str, str]
    cognee_disposition: Literal["not_projected"]
    cognee_policy_sha256: str
    proof_sha256: str

    def __post_init__(self) -> None:
        for value in (
            self.run_id_sha256,
            self.cleanup_plan_sha256,
            self.cleanup_receipt_sha256,
            self.inventory_sha256,
            *self.qdrant_pass_receipt_sha256s,
            *self.graphiti_pass_receipt_sha256s,
            self.cognee_policy_sha256,
            self.proof_sha256,
        ):
            _digest(value)
        if (
            self.cognee_disposition != "not_projected"
            or len(self.qdrant_pass_receipt_sha256s) != 2
            or len(self.graphiti_pass_receipt_sha256s) != 2
            or len(set(self.qdrant_pass_receipt_sha256s)) != 2
            or len(set(self.graphiti_pass_receipt_sha256s)) != 2
        ):
            raise ValueError("unsealed projection proof shape is invalid")
        expected = benchmark_unsealed_projection_proof_sha256(
            run_id_sha256=self.run_id_sha256,
            cleanup_plan_sha256=self.cleanup_plan_sha256,
            cleanup_receipt_sha256=self.cleanup_receipt_sha256,
            inventory_sha256=self.inventory_sha256,
            qdrant_pass_receipt_sha256s=self.qdrant_pass_receipt_sha256s,
            graphiti_pass_receipt_sha256s=self.graphiti_pass_receipt_sha256s,
            cognee_policy_sha256=self.cognee_policy_sha256,
        )
        if self.proof_sha256 != expected:
            raise ValueError("unsealed projection proof digest differs")


class BenchmarkUnsealedRecoveryInventoryPort(Protocol):
    async def load_inventory(
        self, *, record: BenchmarkRunRegistryRecord
    ) -> BenchmarkUnsealedRecoveryInventory: ...


class BenchmarkUnsealedProjectionAbsencePort(Protocol):
    async def prove_absence(
        self, *, record: BenchmarkRunRegistryRecord
    ) -> BenchmarkUnsealedProjectionCleanupProof: ...


def benchmark_unsealed_projection_proof_sha256(
    *,
    run_id_sha256: str,
    cleanup_plan_sha256: str,
    cleanup_receipt_sha256: str,
    inventory_sha256: str,
    qdrant_pass_receipt_sha256s: tuple[str, str],
    graphiti_pass_receipt_sha256s: tuple[str, str],
    cognee_policy_sha256: str,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "schema_version": "benchmark-unsealed-projection-cleanup-proof.v1",
                "run_id_sha256": run_id_sha256,
                "cleanup_plan_sha256": cleanup_plan_sha256,
                "cleanup_receipt_sha256": cleanup_receipt_sha256,
                "inventory_sha256": inventory_sha256,
                "qdrant_pass_receipt_sha256s": list(qdrant_pass_receipt_sha256s),
                "graphiti_pass_receipt_sha256s": list(graphiti_pass_receipt_sha256s),
                "cognee": {
                    "disposition": "not_projected",
                    "policy_sha256": cognee_policy_sha256,
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _digest(value: object) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError("recovery evidence digest is invalid")


def _identity(value: object) -> None:
    if type(value) is not str or not value or value != value.strip() or len(value) > 512:
        raise ValueError("recovery evidence identity is invalid")


def _identities(value: object) -> None:
    if type(value) is not tuple or len(value) > _MAX_IDENTITIES:
        raise ValueError("recovery evidence identities are invalid")
    for item in value:
        _identity(item)
    if value != tuple(sorted(set(value))):
        raise ValueError("recovery evidence identities are not canonical")


__all__ = (
    "BenchmarkProjectionPassReceipt",
    "BenchmarkGraphitiRecoveryEvidencePort",
    "BenchmarkQdrantRecoveryEvidencePort",
    "BenchmarkUnsealedProjectionAbsencePort",
    "BenchmarkUnsealedProjectionCleanupProof",
    "BenchmarkUnsealedProjectionScope",
    "BenchmarkUnsealedRecoveryInventory",
    "BenchmarkUnsealedRecoveryInventoryPort",
    "benchmark_unsealed_projection_proof_sha256",
)
