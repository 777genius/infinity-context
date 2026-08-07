"""Contract-first coordinator for the managed Mem0 OSS v5 benchmark lane."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    Mem0OssFullRunState,
    Mem0OssOperationState,
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import (
    Mem0OssFullRunService,
    Mem0OssOperationRecoveryState,
    Mem0OssRunSeal,
    Mem0OssTerminalCleanupEvidence,
)

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5Budget:
    case_count: int
    extraction_call_count: int
    benchmark_call_count: int
    total_call_count: int

    @classmethod
    def for_authority(cls, authority: ManagedMem0V5ManifestAuthority) -> ManagedMem0V5Budget:
        if type(authority) is not ManagedMem0V5ManifestAuthority:
            raise ManagedRunError("managed Mem0 v5 budget authority is invalid")
        authority.__post_init__()
        extraction = authority.operation_count
        benchmark = authority.case_count * 4
        return cls(authority.case_count, extraction, benchmark, extraction + benchmark)

    def __post_init__(self) -> None:
        if (
            type(self.case_count) is not int
            or self.case_count < 1
            or type(self.extraction_call_count) is not int
            or self.extraction_call_count < 1
            or self.benchmark_call_count != self.case_count * 4
            or self.total_call_count != self.extraction_call_count + self.benchmark_call_count
        ):
            raise ManagedRunError("managed Mem0 v5 budget is invalid")

    def public_payload(self) -> dict[str, int]:
        return {
            "case_count": self.case_count,
            "extraction_call_count": self.extraction_call_count,
            "benchmark_call_count": self.benchmark_call_count,
            "total_call_count": self.total_call_count,
        }


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5BudgetPolicy:
    maximum_total_call_count: int

    def __post_init__(self) -> None:
        if type(self.maximum_total_call_count) is not int or self.maximum_total_call_count < 1:
            raise ManagedRunError("managed Mem0 v5 budget policy is invalid")

    def require(self, budget: ManagedMem0V5Budget) -> None:
        if type(budget) is not ManagedMem0V5Budget:
            raise ManagedRunError("managed Mem0 v5 budget type differs")
        if budget.total_call_count > self.maximum_total_call_count:
            raise ManagedRunError("managed Mem0 v5 call budget exceeded")


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5SourcePair:
    source_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.source_id) is not str
            or _SAFE_RECORD_ID.fullmatch(self.source_id) is None
            or not is_sha256(self.source_sha256)
        ):
            raise ManagedRunError("managed Mem0 v5 storage source pair is invalid")

    def payload(self) -> dict[str, str]:
        return {"source_id": self.source_id, "source_sha256": self.source_sha256}


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5StorageObservation:
    """Untrusted storage observation whose self-hash is not authentication.

    Only acceptance by the service's configured StorageVerificationPort makes
    an observation eligible for coordinator coverage.
    """

    operation_id_sha256: str
    unit_identity_sha256: str
    created_record_ids: tuple[str, ...]
    source_pairs: tuple[ManagedMem0V5SourcePair, ...]
    evidence_commitment_sha256: str

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.operation_id_sha256)
            or not is_sha256(self.unit_identity_sha256)
            or type(self.created_record_ids) is not tuple
            or any(
                type(item) is not str or _SAFE_RECORD_ID.fullmatch(item) is None
                for item in self.created_record_ids
            )
            or len(set(self.created_record_ids)) != len(self.created_record_ids)
            or type(self.source_pairs) is not tuple
            or not self.source_pairs
            or any(type(item) is not ManagedMem0V5SourcePair for item in self.source_pairs)
            or len({(item.source_id, item.source_sha256) for item in self.source_pairs})
            != len(self.source_pairs)
            or not is_sha256(self.evidence_commitment_sha256)
            or self.evidence_commitment_sha256 != canonical_sha256(self.commitment_payload())
        ):
            raise ManagedRunError("managed Mem0 v5 storage observation is invalid")

    @classmethod
    def create(
        cls,
        *,
        operation_id_sha256: str,
        unit_identity_sha256: str,
        created_record_ids: tuple[str, ...],
        source_pairs: tuple[ManagedMem0V5SourcePair, ...],
    ) -> ManagedMem0V5StorageObservation:
        payload = {
            "operation_id_sha256": operation_id_sha256,
            "unit_identity_sha256": unit_identity_sha256,
            "created_record_ids": list(created_record_ids),
            "source_pairs": [item.payload() for item in source_pairs],
        }
        return cls(
            operation_id_sha256=operation_id_sha256,
            unit_identity_sha256=unit_identity_sha256,
            created_record_ids=created_record_ids,
            source_pairs=source_pairs,
            evidence_commitment_sha256=canonical_sha256(payload),
        )

    def commitment_payload(self) -> dict[str, object]:
        return {
            "operation_id_sha256": self.operation_id_sha256,
            "unit_identity_sha256": self.unit_identity_sha256,
            "created_record_ids": list(self.created_record_ids),
            "source_pairs": [item.payload() for item in self.source_pairs],
        }

    def public_payload(self) -> dict[str, object]:
        return {
            **self.commitment_payload(),
            "evidence_commitment_sha256": self.evidence_commitment_sha256,
        }


class ManagedMem0V5LanePort(Protocol):
    """Remote HTTP/storage seam; implementations may compose v5 HTTP and persistence."""

    def admit(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
    ) -> None: ...

    def dispatch(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> object: ...

    def status(
        self,
        *,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> object: ...

    def inspect_storage(
        self,
        *,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> ManagedMem0V5StorageObservation: ...

    def cleanup(
        self,
        *,
        admission: Mem0OssFullRunAdmission,
        seal: Mem0OssRunSeal | None,
        aborting: bool,
    ) -> object: ...


@final
class ManagedMem0V5LaneCoordinator:
    """Drives v5 state transitions without owning provider or transport details."""

    __slots__ = (
        "_authority",
        "_budget",
        "_completed",
        "_dispatched",
        "_lane",
        "_operation_ids",
        "_service",
        "_storage_observations",
    )

    def __init__(
        self,
        *,
        service: Mem0OssFullRunService,
        lane_port: ManagedMem0V5LanePort,
    ) -> None:
        if type(service) is not Mem0OssFullRunService or not _lane_port(lane_port):
            raise ManagedRunError("managed Mem0 v5 lane composition is invalid")
        self._service = service
        self._lane = lane_port
        self._authority: ManagedMem0V5ManifestAuthority | None = None
        self._budget: ManagedMem0V5Budget | None = None
        self._operation_ids: dict[int, str] = {}
        self._dispatched: set[int] = set()
        self._completed: set[int] = set()
        self._storage_observations: dict[int, ManagedMem0V5StorageObservation] = {}

    @property
    def budget(self) -> ManagedMem0V5Budget:
        if self._budget is None:
            raise ManagedRunError("managed Mem0 v5 lane is not admitted")
        return self._budget

    @property
    def storage_observations(self) -> tuple[ManagedMem0V5StorageObservation, ...]:
        """Return only observations accepted by the configured storage verifier."""

        if len(self._storage_observations) != len(self._completed):
            raise ManagedRunError("managed Mem0 v5 storage observation coverage differs")
        return tuple(
            self._storage_observations[index] for index in sorted(self._storage_observations)
        )

    @property
    def terminal_evidence(self) -> Mem0OssTerminalCleanupEvidence:
        return self._service.terminal_cleanup_evidence

    def admit(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        request: Mem0OssAdmissionRequest,
        budget_policy: ManagedMem0V5BudgetPolicy,
    ) -> None:
        if (
            type(authority) is not ManagedMem0V5ManifestAuthority
            or type(request) is not Mem0OssAdmissionRequest
            or type(budget_policy) is not ManagedMem0V5BudgetPolicy
            or request.expected_operation_count != authority.operation_count
        ):
            raise ManagedRunError("managed Mem0 v5 admission binding differs")
        budget = ManagedMem0V5Budget.for_authority(authority)
        budget_policy.require(budget)
        self._service.admit(request, manifest_authority_payload=authority)
        self._service.activate(
            admission_commitment_sha256=self._service.admission.commitment_sha256
        )
        self._authority = authority
        self._budget = budget
        try:
            self._lane.admit(authority=authority, admission=self._service.admission)
        except Exception as primary:
            try:
                self.abort()
            except Exception as cleanup_error:
                primary.add_note(
                    f"managed Mem0 v5 admission cleanup failed: {type(cleanup_error).__name__}"
                )
            raise

    def dispatch_pending(self) -> Mem0OssRunSeal:
        authority = self._required_authority()
        if self._service.state is Mem0OssFullRunState.RECONCILIATION_REQUIRED:
            raise ManagedRunError("managed Mem0 v5 status reconciliation is required")
        for index, unit in enumerate(authority.units):
            if index in self._completed or index in self._dispatched:
                continue
            operation_id = self._service.reserve(unit_index=index)
            self._operation_ids[index] = operation_id
            self._service.record_dispatched(unit_index=index)
            self._dispatched.add(index)
            receipt = self._lane.dispatch(
                authority=authority,
                unit=unit,
                operation_id_sha256=operation_id,
                admission=self._service.admission,
            )
            self._service.verify_dispatch_receipt(unit_index=index, receipt_payload=receipt)
            self._finish_storage(index, unit, operation_id)
        return self._service.seal()

    def reconcile_after_crash(self) -> tuple[int, ...]:
        authority = self._required_authority()
        safe_reserved = self._service.recover_after_crash()
        states = self._recovery_states(authority)

        # Resolve every receipt-unknown operation first. The service intentionally
        # remains globally fail-closed while any status readback is outstanding.
        for index, recovery in sorted(states.items()):
            if recovery.state is not Mem0OssOperationState.RECONCILIATION_REQUIRED:
                continue
            receipt = self._lane.status(
                operation_id_sha256=recovery.operation_id_sha256,
                admission=self._service.admission,
            )
            self._service.reconcile_receipt_readback(
                unit_index=index,
                receipt_payload=receipt,
            )

        states = self._recovery_states(authority)
        for index, recovery in sorted(states.items()):
            unit = authority.units[index]
            if recovery.state is Mem0OssOperationState.RESERVED:
                self._service.record_dispatched(unit_index=index)
                self._dispatched.add(index)
                receipt = self._lane.dispatch(
                    authority=authority,
                    unit=unit,
                    operation_id_sha256=recovery.operation_id_sha256,
                    admission=self._service.admission,
                )
                self._service.verify_dispatch_receipt(
                    unit_index=index,
                    receipt_payload=receipt,
                )
                self._finish_storage(index, unit, recovery.operation_id_sha256)
            elif recovery.state is Mem0OssOperationState.RECEIPT_VERIFIED:
                self._finish_storage(index, unit, recovery.operation_id_sha256)
            elif recovery.state is Mem0OssOperationState.STORAGE_VERIFIED:
                self._restore_verified_storage(index, unit, recovery)
                self._service.commit(unit_index=index)
                self._completed.add(index)
            elif recovery.state is Mem0OssOperationState.COMMITTED:
                self._restore_verified_storage(index, unit, recovery)
                self._completed.add(index)
            else:
                raise ManagedRunError("managed Mem0 v5 recovery stage is invalid")
        return safe_reserved

    def cleanup(self) -> Mem0OssTerminalCleanupEvidence:
        if self._service.state is Mem0OssFullRunState.SEALED:
            self._service.begin_delete()
        elif self._service.state is not Mem0OssFullRunState.DELETING:
            raise ManagedRunError("managed Mem0 v5 cleanup state is invalid")
        payload = self._lane.cleanup(
            admission=self._service.admission,
            seal=self._service.seal_evidence,
            aborting=False,
        )
        self._service.finish_delete(cleanup_payload=payload)
        return self._service.terminal_cleanup_evidence

    def abort(self) -> Mem0OssTerminalCleanupEvidence:
        if self._service.state in {
            Mem0OssFullRunState.ACTIVE,
            Mem0OssFullRunState.RECONCILIATION_REQUIRED,
            Mem0OssFullRunState.FAILED,
        }:
            self._service.begin_abort()
        elif self._service.state is not Mem0OssFullRunState.ABORTING:
            raise ManagedRunError("managed Mem0 v5 abort state is invalid")
        payload = self._lane.cleanup(
            admission=self._service.admission,
            seal=None,
            aborting=True,
        )
        self._service.finish_abort(cleanup_payload=payload)
        return self._service.terminal_cleanup_evidence

    def _finish_storage(
        self,
        index: int,
        unit: ManagedMem0V5SourceUnit,
        operation_id: str,
    ) -> None:
        evidence = self._inspect_storage(unit, operation_id)
        self._service.verify_storage(unit_index=index, storage_payload=evidence)
        recovery = self._recovery_state(index)
        self._require_verified_storage_binding(evidence, recovery)
        self._storage_observations[index] = evidence
        self._service.commit(unit_index=index)
        self._completed.add(index)

    def _inspect_storage(
        self,
        unit: ManagedMem0V5SourceUnit,
        operation_id: str,
    ) -> ManagedMem0V5StorageObservation:
        evidence = self._lane.inspect_storage(
            unit=unit,
            operation_id_sha256=operation_id,
            admission=self._service.admission,
        )
        if (
            type(evidence) is not ManagedMem0V5StorageObservation
            or evidence.operation_id_sha256 != operation_id
            or evidence.unit_identity_sha256 != unit.unit_identity_sha256
            or evidence.source_pairs
            != (ManagedMem0V5SourcePair(unit.source_id, unit.source_sha256),)
        ):
            raise ManagedRunError("managed Mem0 v5 storage observation binding differs")
        return evidence

    def _recovery_states(
        self,
        authority: ManagedMem0V5ManifestAuthority,
    ) -> dict[int, Mem0OssOperationRecoveryState]:
        states = {item.unit_index: item for item in self._service.operation_recovery_states()}
        if any(
            index >= len(authority.units)
            or self._operation_ids.get(index) != item.operation_id_sha256
            for index, item in states.items()
        ):
            raise ManagedRunError("managed Mem0 v5 durable reconciliation state is missing")
        return states

    def _recovery_state(self, index: int) -> Mem0OssOperationRecoveryState:
        states = self._service.operation_recovery_states()
        if index >= len(states) or states[index].unit_index != index:
            raise ManagedRunError("managed Mem0 v5 recovery coverage differs")
        return states[index]

    def _restore_verified_storage(
        self,
        index: int,
        unit: ManagedMem0V5SourceUnit,
        recovery: Mem0OssOperationRecoveryState,
    ) -> None:
        evidence = self._storage_observations.get(index)
        if evidence is None:
            evidence = self._inspect_storage(unit, recovery.operation_id_sha256)
        self._require_verified_storage_binding(evidence, recovery)
        self._storage_observations[index] = evidence

    @staticmethod
    def _require_verified_storage_binding(
        evidence: ManagedMem0V5StorageObservation,
        recovery: Mem0OssOperationRecoveryState,
    ) -> None:
        if (
            evidence.evidence_commitment_sha256 != recovery.stored_identity_sha256
            or len(evidence.created_record_ids) != recovery.stored_record_count
        ):
            raise ManagedRunError("managed Mem0 v5 verified storage binding differs")

    def _required_authority(self) -> ManagedMem0V5ManifestAuthority:
        if self._authority is None:
            raise ManagedRunError("managed Mem0 v5 lane is not admitted")
        return self._authority


def _lane_port(value: object) -> bool:
    return all(
        callable(getattr(value, name, None))
        for name in ("admit", "dispatch", "status", "inspect_storage", "cleanup")
    )


__all__ = (
    "ManagedMem0V5Budget",
    "ManagedMem0V5BudgetPolicy",
    "ManagedMem0V5LaneCoordinator",
    "ManagedMem0V5LanePort",
    "ManagedMem0V5SourcePair",
    "ManagedMem0V5StorageObservation",
)
