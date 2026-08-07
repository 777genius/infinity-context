"""Checkpoint-backed lifecycle progress port for the managed Mem0-v5 lane."""

from __future__ import annotations

from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    ManagedMem0V5Checkpoint,
    ManagedMem0V5CheckpointPhase,
    ManagedMem0V5CheckpointSignerPort,
    ManagedMem0V5CheckpointStorePort,
    ManagedMem0V5CheckpointUnit,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
    canonical_sha256,
    is_sha256,
)


class ManagedMem0V5CheckpointHeadPort(Protocol):
    """Externally authenticated CAS authority for the latest checkpoint head."""

    def load_head(
        self,
        *,
        authority_commitment_sha256: str,
        admission_commitment_sha256: str,
    ) -> str | None: ...

    def compare_and_swap_head(
        self,
        *,
        authority_commitment_sha256: str,
        admission_commitment_sha256: str,
        expected_commitment_sha256: str | None,
        next_commitment_sha256: str,
    ) -> None: ...


class ManagedMem0V5ProgressPort(Protocol):
    def initialize(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
    ) -> ManagedMem0V5Checkpoint: ...

    def load(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
    ) -> ManagedMem0V5Checkpoint: ...

    def advance(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        unit_index: int,
        phase: ManagedMem0V5CheckpointPhase,
        provider_receipt_commitment_sha256: str | None = None,
        observation_commitment_sha256: str | None = None,
        record_ids: tuple[str, ...] = (),
    ) -> ManagedMem0V5Checkpoint: ...


@final
class ManagedMem0V5CheckpointProgress:
    """Forward-only progress with local atomic state and external rollback head."""

    __slots__ = ("_head", "_signer", "_store")

    def __init__(
        self,
        *,
        store: ManagedMem0V5CheckpointStorePort,
        signer: ManagedMem0V5CheckpointSignerPort,
        head: ManagedMem0V5CheckpointHeadPort,
    ) -> None:
        if (
            not all(callable(getattr(store, name, None)) for name in ("load", "save"))
            or not all(callable(getattr(signer, name, None)) for name in ("sign", "verify"))
            or not all(
                callable(getattr(head, name, None))
                for name in ("load_head", "compare_and_swap_head")
            )
        ):
            raise ManagedRunError("managed Mem0 v5 progress composition is invalid")
        self._store = store
        self._signer = signer
        self._head = head

    def initialize(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
    ) -> ManagedMem0V5Checkpoint:
        self._require_binding(authority, admission)
        existing_head = self._load_head(authority, admission)
        if existing_head is not None:
            return self.load(authority=authority, admission=admission)
        existing = self._store.load(
            expected_authority_commitment_sha256=authority.authority_commitment_sha256,
            expected_admission_commitment_sha256=admission.commitment_sha256,
        )
        if existing is not None:
            if (
                existing.generation != 0
                or existing.previous_checkpoint_commitment_sha256 is not None
            ):
                raise ManagedRunError("managed Mem0 v5 initial progress differs")
            self._require_checkpoint(authority, admission, existing)
            self._head.compare_and_swap_head(
                authority_commitment_sha256=authority.authority_commitment_sha256,
                admission_commitment_sha256=admission.commitment_sha256,
                expected_commitment_sha256=None,
                next_commitment_sha256=existing.checkpoint_commitment_sha256,
            )
            return existing
        units = tuple(
            ManagedMem0V5CheckpointUnit(
                unit_index=index,
                operation_id_sha256=_operation_id(admission, unit.unit_identity_sha256, index),
                phase=ManagedMem0V5CheckpointPhase.RESERVED,
            )
            for index, unit in enumerate(authority.units)
        )
        checkpoint = ManagedMem0V5Checkpoint.create(
            authority_commitment_sha256=authority.authority_commitment_sha256,
            admission_commitment_sha256=admission.commitment_sha256,
            generation=0,
            previous_checkpoint_commitment_sha256=None,
            units=units,
            signer=self._signer,
        )
        self._store.save(checkpoint, expected_previous_commitment_sha256=None)
        self._head.compare_and_swap_head(
            authority_commitment_sha256=authority.authority_commitment_sha256,
            admission_commitment_sha256=admission.commitment_sha256,
            expected_commitment_sha256=None,
            next_commitment_sha256=checkpoint.checkpoint_commitment_sha256,
        )
        return checkpoint

    def load(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
    ) -> ManagedMem0V5Checkpoint:
        self._require_binding(authority, admission)
        head = self._load_head(authority, admission)
        if head is None:
            raise ManagedRunError("managed Mem0 v5 progress head is missing")
        checkpoint = self._store.load(
            expected_authority_commitment_sha256=authority.authority_commitment_sha256,
            expected_admission_commitment_sha256=admission.commitment_sha256,
        )
        if checkpoint is None:
            raise ManagedRunError("managed Mem0 v5 progress checkpoint is missing")
        self._require_checkpoint(authority, admission, checkpoint)
        if checkpoint.checkpoint_commitment_sha256 != head:
            if checkpoint.previous_checkpoint_commitment_sha256 != head:
                raise ManagedRunError("managed Mem0 v5 progress head differs")
            self._head.compare_and_swap_head(
                authority_commitment_sha256=authority.authority_commitment_sha256,
                admission_commitment_sha256=admission.commitment_sha256,
                expected_commitment_sha256=head,
                next_commitment_sha256=checkpoint.checkpoint_commitment_sha256,
            )
        return checkpoint

    def advance(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        unit_index: int,
        phase: ManagedMem0V5CheckpointPhase,
        provider_receipt_commitment_sha256: str | None = None,
        observation_commitment_sha256: str | None = None,
        record_ids: tuple[str, ...] = (),
    ) -> ManagedMem0V5Checkpoint:
        current = self.load(authority=authority, admission=admission)
        if type(unit_index) is not int or not 0 <= unit_index < len(current.units):
            raise ManagedRunError("managed Mem0 v5 progress unit is invalid")
        updated_unit = ManagedMem0V5CheckpointUnit(
            unit_index,
            current.units[unit_index].operation_id_sha256,
            phase,
            provider_receipt_commitment_sha256,
            observation_commitment_sha256,
            record_ids,
        )
        units = list(current.units)
        units[unit_index] = updated_unit
        updated = ManagedMem0V5Checkpoint.create(
            authority_commitment_sha256=current.authority_commitment_sha256,
            admission_commitment_sha256=current.admission_commitment_sha256,
            generation=current.generation + 1,
            previous_checkpoint_commitment_sha256=current.checkpoint_commitment_sha256,
            units=tuple(units),
            seal_commitment_sha256=current.seal_commitment_sha256,
            cleanup_commitment_sha256=current.cleanup_commitment_sha256,
            signer=self._signer,
        )
        self._store.save(
            updated,
            expected_previous_commitment_sha256=current.checkpoint_commitment_sha256,
        )
        self._head.compare_and_swap_head(
            authority_commitment_sha256=current.authority_commitment_sha256,
            admission_commitment_sha256=current.admission_commitment_sha256,
            expected_commitment_sha256=current.checkpoint_commitment_sha256,
            next_commitment_sha256=updated.checkpoint_commitment_sha256,
        )
        return updated

    def _load_head(
        self,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
    ) -> str | None:
        head = self._head.load_head(
            authority_commitment_sha256=authority.authority_commitment_sha256,
            admission_commitment_sha256=admission.commitment_sha256,
        )
        if head is not None and not is_sha256(head):
            raise ManagedRunError("managed Mem0 v5 progress head is invalid")
        return head

    @staticmethod
    def _require_binding(
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
    ) -> None:
        if (
            type(authority) is not ManagedMem0V5ManifestAuthority
            or type(admission) is not Mem0OssFullRunAdmission
            or authority.ingestion_manifest_sha256 != admission.ingestion_manifest_sha256
            or authority.ingestion_root_sha256 != admission.ingestion_root_sha256
            or authority.operation_count != admission.ingestion_unit_count
        ):
            raise ManagedRunError("managed Mem0 v5 progress binding differs")

    @staticmethod
    def _require_checkpoint(
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        checkpoint: ManagedMem0V5Checkpoint,
    ) -> None:
        if len(checkpoint.units) != authority.operation_count:
            raise ManagedRunError("managed Mem0 v5 progress checkpoint coverage differs")
        for index, unit in enumerate(authority.units):
            expected = _operation_id(admission, unit.unit_identity_sha256, index)
            if checkpoint.units[index].operation_id_sha256 != expected:
                raise ManagedRunError("managed Mem0 v5 progress operation binding differs")


def _operation_id(
    admission: Mem0OssFullRunAdmission,
    unit_identity_sha256: str,
    unit_index: int,
) -> str:
    return canonical_sha256(
        {
            "admission_commitment_sha256": admission.commitment_sha256,
            "unit_index": unit_index,
            "unit_identity_sha256": unit_identity_sha256,
        }
    )


__all__ = (
    "ManagedMem0V5CheckpointHeadPort",
    "ManagedMem0V5CheckpointProgress",
    "ManagedMem0V5ProgressPort",
)
