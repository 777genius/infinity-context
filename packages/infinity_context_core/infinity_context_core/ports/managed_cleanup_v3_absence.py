"""Two-pass target absence evidence for future cleanup v3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    commitment,
    digest,
    exact_int,
)
from infinity_context_core.ports.managed_cleanup_v3_recovery import (
    ManagedCleanupV3InventoryTerminal,
)

ABSENCE_PASS_SCHEMA: Final = "memory-comparison-paged-cleanup-absence-pass.v4"
DELETION_RECEIPT_SCHEMA: Final = "memory-comparison-paged-cleanup-deletion-receipt.v4"
TERMINAL_EVIDENCE_SCHEMA: Final = "memory-comparison-paged-cleanup-terminal-evidence.v4"
EMPTY_EXHAUSTIVE_SCAN_ROOT_SHA256: Final = commitment("absence-empty-scan/v4", [])
EMPTY_GLOBAL_READBACK_ROOT_SHA256: Final = commitment("absence-empty-global/v4", [])


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV3DeletionReceipt:
    lane: str
    authority_terminal_sha256: str
    inventory_terminal_sha256: str
    cleanup_receipt_sha256: str
    expected_identity_root_sha256: str
    expected_secondary_identity_root_sha256: str
    expected_identity_count: int
    deletion_operation_receipt_sha256: str
    receipt_sha256: str
    schema_version: str = DELETION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        for value in (
            self.authority_terminal_sha256,
            self.inventory_terminal_sha256,
            self.cleanup_receipt_sha256,
            self.expected_identity_root_sha256,
            self.expected_secondary_identity_root_sha256,
            self.deletion_operation_receipt_sha256,
        ):
            digest(value)
        exact_int(self.expected_identity_count)
        body = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "receipt_sha256"
        }
        if (
            self.schema_version != DELETION_RECEIPT_SCHEMA
            or self.lane not in {"qdrant", "graphiti"}
            or self.receipt_sha256 != commitment("deletion-receipt/v4", body)
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_deletion_receipt_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV3AbsencePass:
    lane: str
    pass_index: int
    authority_terminal_sha256: str
    inventory_terminal_sha256: str
    cleanup_receipt_sha256: str
    lane_authority_sha256: str
    target_commitment_sha256: str
    policy_commitment_sha256: str
    fresh_snapshot_nonce_sha256: str
    prior_pass_sha256: str | None
    expected_identity_root_sha256: str
    expected_secondary_identity_root_sha256: str
    expected_identity_count: int
    exhaustive_space_or_prefix_count: int
    exhaustive_space_or_prefix_root_sha256: str
    global_expected_readback_count: int
    global_expected_readback_root_sha256: str
    unknown_foreign_malformed_count: int
    pass_sha256: str
    schema_version: str = ABSENCE_PASS_SCHEMA

    def __post_init__(self) -> None:
        for value in (
            self.authority_terminal_sha256,
            self.inventory_terminal_sha256,
            self.cleanup_receipt_sha256,
            self.lane_authority_sha256,
            self.target_commitment_sha256,
            self.policy_commitment_sha256,
            self.fresh_snapshot_nonce_sha256,
            self.expected_identity_root_sha256,
            self.expected_secondary_identity_root_sha256,
            self.exhaustive_space_or_prefix_root_sha256,
            self.global_expected_readback_root_sha256,
        ):
            digest(value)
        if self.prior_pass_sha256 is not None:
            digest(self.prior_pass_sha256)
        for value in (
            self.expected_identity_count,
            self.exhaustive_space_or_prefix_count,
            self.global_expected_readback_count,
            self.unknown_foreign_malformed_count,
        ):
            exact_int(value)
        body = {
            name: getattr(self, name) for name in self.__dataclass_fields__ if name != "pass_sha256"
        }
        if (
            self.schema_version != ABSENCE_PASS_SCHEMA
            or self.lane not in {"qdrant", "graphiti"}
            or self.pass_index not in {1, 2}
            or (self.pass_index == 1) != (self.prior_pass_sha256 is None)
            or self.exhaustive_space_or_prefix_count != 0
            or self.exhaustive_space_or_prefix_root_sha256 != EMPTY_EXHAUSTIVE_SCAN_ROOT_SHA256
            or self.global_expected_readback_count != 0
            or self.global_expected_readback_root_sha256 != EMPTY_GLOBAL_READBACK_ROOT_SHA256
            or self.unknown_foreign_malformed_count != 0
            or self.pass_sha256 != commitment("absence-pass/v4", body)
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_absence_pass_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV3TerminalEvidence:
    context: ManagedCleanupV3Context
    authority_terminal_sha256: str
    inventory: ManagedCleanupV3InventoryTerminal
    qdrant_deletion: ManagedCleanupV3DeletionReceipt
    graphiti_deletion: ManagedCleanupV3DeletionReceipt
    qdrant_passes: tuple[ManagedCleanupV3AbsencePass, ManagedCleanupV3AbsencePass]
    graphiti_passes: tuple[ManagedCleanupV3AbsencePass, ManagedCleanupV3AbsencePass]
    terminal_sha256: str
    schema_version: str = TERMINAL_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if type(self.context) is not ManagedCleanupV3Context:
            raise ManagedCleanupV3Error("managed_cleanup_v3_terminal_evidence_invalid")
        self.context.__post_init__()
        digest(self.authority_terminal_sha256)
        if type(self.inventory) is not ManagedCleanupV3InventoryTerminal:
            raise ManagedCleanupV3Error("managed_cleanup_v3_terminal_evidence_invalid")
        self.inventory.__post_init__()
        if (
            type(self.qdrant_deletion) is not ManagedCleanupV3DeletionReceipt
            or type(self.graphiti_deletion) is not ManagedCleanupV3DeletionReceipt
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_terminal_evidence_invalid")
        self.qdrant_deletion.__post_init__()
        self.graphiti_deletion.__post_init__()
        if (
            type(self.qdrant_passes) is not tuple
            or type(self.graphiti_passes) is not tuple
            or len(self.qdrant_passes) != 2
            or len(self.graphiti_passes) != 2
            or any(
                type(item) is not ManagedCleanupV3AbsencePass
                for item in (*self.qdrant_passes, *self.graphiti_passes)
            )
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_terminal_evidence_invalid")
        passes = (*self.qdrant_passes, *self.graphiti_passes)
        for item in passes:
            item.__post_init__()
        body = {
            "schema_version": self.schema_version,
            "context_sha256": self.context.context_sha256,
            "authority_terminal_sha256": self.authority_terminal_sha256,
            "inventory_terminal_sha256": self.inventory.terminal_sha256,
            "cleanup_receipt_sha256": self.inventory.cleanup_receipt_sha256,
            "qdrant_deletion_receipt_sha256": self.qdrant_deletion.receipt_sha256,
            "graphiti_deletion_receipt_sha256": self.graphiti_deletion.receipt_sha256,
            "qdrant_pass_sha256": [x.pass_sha256 for x in self.qdrant_passes],
            "graphiti_pass_sha256": [x.pass_sha256 for x in self.graphiti_passes],
            "cognee_policy_sha256": self.context.cognee_policy_sha256,
        }
        qdrant = self.qdrant_passes
        graphiti = self.graphiti_passes
        if (
            self.schema_version != TERMINAL_EVIDENCE_SCHEMA
            or self.inventory.context_sha256 != self.context.context_sha256
            or self.inventory.profile_id != self.context.profile_id
            or self.inventory.authority_terminal_sha256 != self.authority_terminal_sha256
            or tuple(item.lane for item in passes) != ("qdrant", "qdrant", "graphiti", "graphiti")
            or tuple(item.pass_index for item in passes) != (1, 2, 1, 2)
            or self.qdrant_passes[1].prior_pass_sha256 != self.qdrant_passes[0].pass_sha256
            or self.graphiti_passes[1].prior_pass_sha256 != self.graphiti_passes[0].pass_sha256
            or any(
                item.authority_terminal_sha256 != self.authority_terminal_sha256
                or item.inventory_terminal_sha256 != self.inventory.terminal_sha256
                or item.cleanup_receipt_sha256 != self.inventory.cleanup_receipt_sha256
                for item in passes
            )
            or any(
                first.target_commitment_sha256 != second.target_commitment_sha256
                or first.policy_commitment_sha256 != second.policy_commitment_sha256
                or first.lane_authority_sha256 != second.lane_authority_sha256
                or first.expected_identity_root_sha256 != second.expected_identity_root_sha256
                or first.expected_secondary_identity_root_sha256
                != second.expected_secondary_identity_root_sha256
                or first.expected_identity_count != second.expected_identity_count
                for first, second in (qdrant, graphiti)
            )
            or qdrant[0].lane_authority_sha256 != self.context.qdrant_authority_sha256
            or qdrant[0].target_commitment_sha256 != self.context.qdrant_target_commitment_sha256
            or qdrant[0].policy_commitment_sha256 != self.context.qdrant_policy_commitment_sha256
            or graphiti[0].lane_authority_sha256 != self.context.graphiti_authority_sha256
            or graphiti[0].target_commitment_sha256
            != self.context.graphiti_target_commitment_sha256
            or graphiti[0].policy_commitment_sha256
            != self.context.graphiti_policy_commitment_sha256
            or qdrant[0].expected_identity_root_sha256
            != self.inventory.expected_qdrant_identity_root_sha256
            or qdrant[0].expected_secondary_identity_root_sha256
            != self.inventory.expected_qdrant_identity_root_sha256
            or qdrant[0].expected_identity_count != self.inventory.expected_qdrant_identity_count
            or graphiti[0].expected_identity_root_sha256
            != self.inventory.expected_graphiti_name_root_sha256
            or graphiti[0].expected_secondary_identity_root_sha256
            != self.inventory.expected_graphiti_uuid_root_sha256
            or graphiti[0].expected_identity_count
            != self.inventory.expected_graphiti_identity_count
            or not _deletion_matches(
                self.qdrant_deletion,
                lane="qdrant",
                authority_terminal_sha256=self.authority_terminal_sha256,
                inventory=self.inventory,
            )
            or not _deletion_matches(
                self.graphiti_deletion,
                lane="graphiti",
                authority_terminal_sha256=self.authority_terminal_sha256,
                inventory=self.inventory,
            )
            or len({item.fresh_snapshot_nonce_sha256 for item in passes}) != 4
            or self.terminal_sha256 != commitment("terminal-evidence/v4", body)
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_terminal_evidence_invalid")


def _deletion_matches(
    receipt: ManagedCleanupV3DeletionReceipt,
    *,
    lane: str,
    authority_terminal_sha256: str,
    inventory: ManagedCleanupV3InventoryTerminal,
) -> bool:
    if lane == "qdrant":
        primary = secondary = inventory.expected_qdrant_identity_root_sha256
        count = inventory.expected_qdrant_identity_count
    else:
        primary = inventory.expected_graphiti_name_root_sha256
        secondary = inventory.expected_graphiti_uuid_root_sha256
        count = inventory.expected_graphiti_identity_count
    return (
        receipt.lane == lane
        and receipt.authority_terminal_sha256 == authority_terminal_sha256
        and receipt.inventory_terminal_sha256 == inventory.terminal_sha256
        and receipt.cleanup_receipt_sha256 == inventory.cleanup_receipt_sha256
        and receipt.expected_identity_root_sha256 == primary
        and receipt.expected_secondary_identity_root_sha256 == secondary
        and receipt.expected_identity_count == count
    )


__all__ = (
    "EMPTY_EXHAUSTIVE_SCAN_ROOT_SHA256",
    "EMPTY_GLOBAL_READBACK_ROOT_SHA256",
    "ManagedCleanupV3AbsencePass",
    "ManagedCleanupV3DeletionReceipt",
    "ManagedCleanupV3TerminalEvidence",
)
