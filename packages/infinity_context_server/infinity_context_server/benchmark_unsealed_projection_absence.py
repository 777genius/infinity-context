"""Direct provider absence proof for manifestless benchmark recovery."""

from __future__ import annotations

import hmac
import re

from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_cleanup_plan import (
    COGNEE_NOT_PROJECTED_POLICY_SHA256,
    GRAPHITI_GROUP_MAPPING_POLICY_SHA256,
    GRAPHITI_SPACE_PREFIX_SCAN_POLICY_SHA256,
    QDRANT_COLLECTION_PROJECTION_POLICY_SHA256,
    QDRANT_SCOPE_MAPPING_POLICY_SHA256,
    QDRANT_SPACE_WIDE_SCAN_POLICY_SHA256,
)
from infinity_context_core.ports.benchmark_runs import BenchmarkRunRegistryRecord
from infinity_context_core.ports.benchmark_unsealed_projection import (
    BenchmarkGraphitiRecoveryEvidencePort,
    BenchmarkProjectionPassReceipt,
    BenchmarkQdrantRecoveryEvidencePort,
    BenchmarkUnsealedProjectionCleanupProof,
    BenchmarkUnsealedRecoveryInventory,
    BenchmarkUnsealedRecoveryInventoryPort,
    benchmark_unsealed_projection_proof_sha256,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ServerBenchmarkUnsealedProjectionAbsence:
    """Prove space-wide two-pass absence from a canonical recovery allowlist."""

    def __init__(
        self,
        *,
        inventory: BenchmarkUnsealedRecoveryInventoryPort,
        qdrant: BenchmarkQdrantRecoveryEvidencePort,
        graphiti: BenchmarkGraphitiRecoveryEvidencePort,
        qdrant_target_commitment_sha256: str | None,
        graphiti_target_commitment_sha256: str | None,
    ) -> None:
        self._inventory = inventory
        self._qdrant = qdrant
        self._graphiti = graphiti
        self._qdrant_target = qdrant_target_commitment_sha256
        self._graphiti_target = graphiti_target_commitment_sha256

    async def prove_absence(
        self, *, record: BenchmarkRunRegistryRecord
    ) -> BenchmarkUnsealedProjectionCleanupProof:
        _require_pending_unsealed(record)
        self._require_target_binding(record)
        inventory = await self._inventory.load_inventory(record=record)
        if type(inventory) is not BenchmarkUnsealedRecoveryInventory:
            raise MemoryConflictError("Unsealed recovery inventory type is invalid")
        _require_inventory_binding(record, inventory)
        qdrant = await self._qdrant.delete_benchmark_space_two_pass(
            space_id=record.space_id,
            scopes=inventory.scopes,
        )
        _require_passes(qdrant, lane="qdrant", target=self._qdrant_target)
        graphiti = await self._graphiti.delete_benchmark_space_two_pass(
            space_id=record.space_id,
            scopes=inventory.scopes,
        )
        _require_passes(graphiti, lane="graphiti", target=self._graphiti_target)
        cognee_policy = _require_cognee_policy(record)
        qdrant_digests = (qdrant[0].receipt_sha256, qdrant[1].receipt_sha256)
        graphiti_digests = (graphiti[0].receipt_sha256, graphiti[1].receipt_sha256)
        proof_sha256 = benchmark_unsealed_projection_proof_sha256(
            run_id_sha256=record.run_id_sha256,
            cleanup_plan_sha256=inventory.cleanup_plan_sha256,
            cleanup_receipt_sha256=inventory.cleanup_receipt_sha256,
            inventory_sha256=inventory.inventory_sha256,
            qdrant_pass_receipt_sha256s=qdrant_digests,
            graphiti_pass_receipt_sha256s=graphiti_digests,
            cognee_policy_sha256=cognee_policy,
        )
        return BenchmarkUnsealedProjectionCleanupProof(
            run_id_sha256=record.run_id_sha256,
            cleanup_plan_sha256=inventory.cleanup_plan_sha256,
            cleanup_receipt_sha256=inventory.cleanup_receipt_sha256,
            inventory_sha256=inventory.inventory_sha256,
            qdrant_pass_receipt_sha256s=qdrant_digests,
            graphiti_pass_receipt_sha256s=graphiti_digests,
            cognee_disposition="not_projected",
            cognee_policy_sha256=cognee_policy,
            proof_sha256=proof_sha256,
        )

    def _require_target_binding(self, record: BenchmarkRunRegistryRecord) -> None:
        plan = record.cleanup_plan_json
        qdrant = plan.get("qdrant") if type(plan) is dict else None
        graphiti = plan.get("graphiti") if type(plan) is dict else None
        expected_qdrant = qdrant.get("target_commitment_sha256") if type(qdrant) is dict else None
        expected_graphiti = (
            graphiti.get("target_commitment_sha256") if type(graphiti) is dict else None
        )
        if (
            type(self._qdrant_target) is not str
            or type(self._graphiti_target) is not str
            or type(expected_qdrant) is not str
            or type(expected_graphiti) is not str
            or not hmac.compare_digest(self._qdrant_target, expected_qdrant)
            or not hmac.compare_digest(self._graphiti_target, expected_graphiti)
            or qdrant
            != {
                "target_commitment_sha256": expected_qdrant,
                "collection_projection_policy_sha256": (QDRANT_COLLECTION_PROJECTION_POLICY_SHA256),
                "deterministic_scope_mapping_policy_sha256": (QDRANT_SCOPE_MAPPING_POLICY_SHA256),
                "space_wide_scan_policy_sha256": QDRANT_SPACE_WIDE_SCAN_POLICY_SHA256,
            }
            or graphiti
            != {
                "target_commitment_sha256": expected_graphiti,
                "group_mapping_policy_sha256": GRAPHITI_GROUP_MAPPING_POLICY_SHA256,
                "space_prefix_scan_policy_sha256": (GRAPHITI_SPACE_PREFIX_SCAN_POLICY_SHA256),
            }
        ):
            raise MemoryConflictError("Unsealed provider target authority differs")


def _require_pending_unsealed(record: BenchmarkRunRegistryRecord) -> None:
    if (
        record.state != "cleanup_pending"
        or record.projection_cleanup_state != "blocked"
        or record.projection_manifest_json is not None
        or record.projection_manifest_sha256 is not None
        or record.cleanup_receipt is None
        or record.cleanup_plan_json is None
        or record.cleanup_plan_sha256 is None
        or record.cleanup_plan_state != "sealed"
    ):
        raise MemoryConflictError("Unsealed projection cleanup is not provable")


def _require_inventory_binding(record: BenchmarkRunRegistryRecord, inventory: object) -> None:
    receipt = record.cleanup_receipt
    if receipt is None or record.cleanup_plan_sha256 is None:
        raise MemoryConflictError("Unsealed recovery inventory binding is incomplete")
    if (
        inventory.run_id_sha256 != record.run_id_sha256
        or inventory.space_id != record.space_id
        or not hmac.compare_digest(inventory.cleanup_plan_sha256, record.cleanup_plan_sha256)
        or not hmac.compare_digest(inventory.cleanup_receipt_sha256, receipt.receipt_sha256)
    ):
        raise MemoryConflictError("Unsealed recovery inventory binding differs")


def _require_passes(
    passes: tuple[BenchmarkProjectionPassReceipt, BenchmarkProjectionPassReceipt],
    *,
    lane: str,
    target: str | None,
) -> None:
    if (
        type(passes) is not tuple
        or len(passes) != 2
        or any(type(item) is not BenchmarkProjectionPassReceipt for item in passes)
        or tuple(item.pass_index for item in passes) != (1, 2)
        or any(item.lane != lane or not item.absent or item.observed_count != 0 for item in passes)
        or type(target) is not str
        or any(item.target_commitment_sha256 != target for item in passes)
        or any(_SHA256.fullmatch(item.receipt_sha256) is None for item in passes)
        or passes[0].receipt_sha256 == passes[1].receipt_sha256
    ):
        raise MemoryConflictError(f"{lane} direct two-pass absence proof is incomplete")


def _require_cognee_policy(record: BenchmarkRunRegistryRecord) -> str:
    plan = record.cleanup_plan_json
    receipt = record.cleanup_receipt
    if type(plan) is not dict or receipt is None:
        raise MemoryConflictError("Cognee recovery policy input is incomplete")
    lane = plan.get("cognee")
    expected = {
        "disposition": "not_projected",
        "policy_sha256": COGNEE_NOT_PROJECTED_POLICY_SHA256,
    }
    if lane != expected or receipt.cognee_delete_outbox_ids:
        raise MemoryConflictError("Cognee recovery policy differs from server policy")
    return COGNEE_NOT_PROJECTED_POLICY_SHA256


__all__ = ("ServerBenchmarkUnsealedProjectionAbsence",)
