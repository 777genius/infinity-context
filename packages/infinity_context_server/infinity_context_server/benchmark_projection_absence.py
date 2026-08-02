"""Server-owned exact absence proof for managed benchmark projections."""

from __future__ import annotations

from typing import cast

from infinity_context_core.application import validate_projection_manifest
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkProjectionCleanupProof,
    BenchmarkRunRegistryRecord,
)

from infinity_context_server.derived_identity_evidence import (
    CanonicalProjectionScope,
    DerivedIdentityEvidenceCoordinator,
)
from infinity_context_server.memory_comparison_managed_projection_manifest import (
    MANAGED_COGNEE_NOT_PROJECTED_POLICY_SHA256,
)


class ServerBenchmarkProjectionAbsence:
    """Reconstruct and delete only identities from the sealed canonical manifest."""

    def __init__(self, evidence: DerivedIdentityEvidenceCoordinator) -> None:
        self._evidence = evidence

    async def prove_absence(
        self,
        *,
        record: BenchmarkRunRegistryRecord,
    ) -> BenchmarkProjectionCleanupProof:
        manifest = self._validated_manifest(record)
        initiation = record.cleanup_receipt
        if initiation is None:
            raise MemoryConflictError("Benchmark cleanup initiation receipt is missing")

        for manifest_scope in _scopes(manifest):
            _require_cognee_not_projected(manifest_scope)
            scope = CanonicalProjectionScope(
                space_id=record.space_id,
                memory_scope_id=cast(str, manifest_scope["memory_scope_id"]),
                thread_id=cast(str | None, manifest_scope["thread_id"]),
            )
            await self._delete_qdrant(scope, manifest_scope, initiation.vector_delete_outbox_ids)
            await self._delete_graphiti(scope, manifest_scope, initiation.graph_delete_outbox_ids)

        projection_manifest_sha256 = record.projection_manifest_sha256
        if projection_manifest_sha256 is None:
            raise MemoryConflictError("Benchmark projection manifest digest is missing")
        return BenchmarkProjectionCleanupProof(
            run_id_sha256=record.run_id_sha256,
            projection_manifest_sha256=projection_manifest_sha256,
            cleanup_initiation_receipt_sha256=initiation.receipt_sha256,
            qdrant_absent=True,
            graphiti_absent=True,
            cognee_absent=True,
        )

    @staticmethod
    def _validated_manifest(record: BenchmarkRunRegistryRecord) -> dict[str, object]:
        if record.projection_manifest_json is None or record.projection_manifest_sha256 is None:
            raise MemoryConflictError("Benchmark projection manifest is missing")
        return validate_projection_manifest(
            record.projection_manifest_json,
            record.projection_manifest_sha256,
            run_id_sha256=record.run_id_sha256,
            binding_commitment_sha256=record.binding_commitment_sha256,
            infinity_target_identity_sha256=record.infinity_target_identity_sha256,
            space_id=record.space_id,
        )

    async def _delete_qdrant(
        self,
        scope: CanonicalProjectionScope,
        manifest_scope: dict[str, object],
        delete_outbox_ids: tuple[int, ...],
    ) -> None:
        lane = manifest_scope["qdrant"]
        if lane is None:
            return
        evidence = cast(dict[str, object], lane)
        result = await self._evidence.delete_qdrant_two_pass(
            scope=scope,
            chunk_ids=tuple(cast(list[str], manifest_scope["chunk_ids"])),
            target_commitment_sha256=cast(str, evidence["target_commitment_sha256"]),
            manifest_binding_sha256=cast(str, evidence["manifest_binding_sha256"]),
            delete_outbox_ids=delete_outbox_ids,
        )
        if not result.first_pass.verified_absent or not result.second_pass.verified_absent:
            raise MemoryConflictError("Qdrant exact absence proof is incomplete")

    async def _delete_graphiti(
        self,
        scope: CanonicalProjectionScope,
        manifest_scope: dict[str, object],
        delete_outbox_ids: tuple[int, ...],
    ) -> None:
        lane = manifest_scope["graphiti"]
        if lane is None:
            return
        evidence = cast(dict[str, object], lane)
        result = await self._evidence.delete_graphiti_two_pass(
            scope=scope,
            fact_ids=tuple(cast(list[str], manifest_scope["fact_ids"])),
            episode_ids=tuple(cast(list[str], evidence["episode_ids"])),
            entity_ids=tuple(cast(list[str], evidence["entity_ids"])),
            mentions_edge_ids=tuple(cast(list[str], evidence["mentions_edge_ids"])),
            relates_to_edge_ids=tuple(cast(list[str], evidence["relates_to_edge_ids"])),
            target_commitment_sha256=cast(str, evidence["target_commitment_sha256"]),
            manifest_binding_sha256=cast(str, evidence["manifest_binding_sha256"]),
            delete_outbox_ids=delete_outbox_ids,
        )
        if not result.evidence.verified_absent:
            raise MemoryConflictError("Graphiti exact absence proof is incomplete")


def _scopes(manifest: dict[str, object]) -> tuple[dict[str, object], ...]:
    return tuple(cast(list[dict[str, object]], manifest["scopes"]))


def _require_cognee_not_projected(manifest_scope: dict[str, object]) -> None:
    if manifest_scope["cognee"] != {
        "disposition": "not_projected",
        "policy_sha256": MANAGED_COGNEE_NOT_PROJECTED_POLICY_SHA256,
    }:
        raise MemoryConflictError("Cognee not-projected policy differs from server policy")


__all__ = ("ServerBenchmarkProjectionAbsence",)
