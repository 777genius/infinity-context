"""Contract-first coordinator for the managed Mem0 OSS v5 benchmark lane."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    ManagedMem0V5Checkpoint,
    ManagedMem0V5CheckpointPhase,
    ManagedMem0V5RunPhase,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5SearchReceipt,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_progress import (
    ManagedMem0V5ProgressPort,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    CleanupVerificationContext,
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
from infinity_context_server.memory_comparison_mem0_oss_v5_terminal import (
    build_terminal_evidence,
    cleanup_request_commitment,
)

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")
_AUTHENTICATED_SEARCH_TOKEN = object()
_AUTHENTICATED_SEARCH_KEY = secrets.token_bytes(32)


@final
class ManagedMem0V5AuthenticatedSearchWitness:
    """Opaque proof issued only after coordinator search verification succeeds."""

    __slots__ = ("_commitment", "_receipt")

    def __init__(self, *, receipt: ManagedMem0V5SearchReceipt, _token: object) -> None:
        if (
            _token is not _AUTHENTICATED_SEARCH_TOKEN
            or type(receipt) is not ManagedMem0V5SearchReceipt
        ):
            raise ManagedRunError("managed Mem0 v5 authenticated search witness is invalid")
        self._receipt = receipt
        self._commitment = _authenticated_search_commitment(receipt)

    @property
    def receipt(self) -> ManagedMem0V5SearchReceipt:
        if not hmac.compare_digest(
            self._commitment, _authenticated_search_commitment(self._receipt)
        ):
            raise ManagedRunError("managed Mem0 v5 authenticated search witness differs")
        return self._receipt

    def __repr__(self) -> str:
        return "ManagedMem0V5AuthenticatedSearchWitness(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("managed Mem0 v5 authenticated search witnesses are nonserializable")


def _authenticated_search_commitment(receipt: ManagedMem0V5SearchReceipt) -> str:
    payload = {
        "admission_commitment_sha256": receipt.admission_commitment_sha256,
        "corpus_id": receipt.corpus_id,
        "query_commitment_sha256": receipt.query_commitment_sha256,
        "limit": receipt.limit,
        "records": [item.public_payload(rank) for rank, item in enumerate(receipt.records)],
        "result_root_sha256": receipt.result_root_sha256,
        "evidence_commitment_sha256": receipt.evidence_commitment_sha256,
    }
    return hmac.new(
        _AUTHENTICATED_SEARCH_KEY,
        canonical_sha256(payload).encode(),
        hashlib.sha256,
    ).hexdigest()


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
    storage_commitment_sha256: str
    created_record_ids: tuple[str, ...]
    source_pairs: tuple[ManagedMem0V5SourcePair, ...]
    evidence_commitment_sha256: str

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.operation_id_sha256)
            or not is_sha256(self.unit_identity_sha256)
            or not is_sha256(self.storage_commitment_sha256)
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
        storage_commitment_sha256: str,
        created_record_ids: tuple[str, ...],
        source_pairs: tuple[ManagedMem0V5SourcePair, ...],
    ) -> ManagedMem0V5StorageObservation:
        payload = {
            "operation_id_sha256": operation_id_sha256,
            "unit_identity_sha256": unit_identity_sha256,
            "storage_commitment_sha256": storage_commitment_sha256,
            "created_record_ids": list(created_record_ids),
            "source_pairs": [item.payload() for item in source_pairs],
        }
        return cls(
            operation_id_sha256=operation_id_sha256,
            unit_identity_sha256=unit_identity_sha256,
            storage_commitment_sha256=storage_commitment_sha256,
            created_record_ids=created_record_ids,
            source_pairs=source_pairs,
            evidence_commitment_sha256=canonical_sha256(payload),
        )

    def commitment_payload(self) -> dict[str, object]:
        return {
            "operation_id_sha256": self.operation_id_sha256,
            "unit_identity_sha256": self.unit_identity_sha256,
            "storage_commitment_sha256": self.storage_commitment_sha256,
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
    ) -> ManagedMem0V5AuthenticatedStorageWitness: ...

    def search(
        self,
        *,
        admission: Mem0OssFullRunAdmission,
        corpus_id: str,
        query: str,
        limit: int,
    ) -> ManagedMem0V5SearchReceipt: ...

    def cleanup(
        self,
        *,
        admission: Mem0OssFullRunAdmission,
        seal: Mem0OssRunSeal | None,
        aborting: bool,
        context: CleanupVerificationContext | None = None,
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
        "_pending_terminal",
        "_progress",
        "_service",
        "_storage_observations",
        "_terminal",
    )

    def __init__(
        self,
        *,
        service: Mem0OssFullRunService,
        lane_port: ManagedMem0V5LanePort,
        progress_port: ManagedMem0V5ProgressPort | None = None,
    ) -> None:
        if type(service) is not Mem0OssFullRunService or not _lane_port(lane_port):
            raise ManagedRunError("managed Mem0 v5 lane composition is invalid")
        self._service = service
        self._lane = lane_port
        if progress_port is not None and not all(
            callable(getattr(progress_port, name, None))
            for name in (
                "initialize",
                "load",
                "advance",
                "record_seal",
                "record_cleanup_attempt",
                "record_terminal",
            )
        ):
            raise ManagedRunError("managed Mem0 v5 progress port is invalid")
        self._progress = progress_port
        self._authority: ManagedMem0V5ManifestAuthority | None = None
        self._budget: ManagedMem0V5Budget | None = None
        self._operation_ids: dict[int, str] = {}
        self._pending_terminal: Mem0OssTerminalCleanupEvidence | None = None
        self._dispatched: set[int] = set()
        self._completed: set[int] = set()
        self._storage_observations: dict[int, ManagedMem0V5AuthenticatedStorageWitness] = {}
        self._terminal: Mem0OssTerminalCleanupEvidence | None = None

    @property
    def budget(self) -> ManagedMem0V5Budget:
        if self._budget is None:
            raise ManagedRunError("managed Mem0 v5 lane is not admitted")
        return self._budget

    @property
    def storage_observations(self) -> tuple[ManagedMem0V5AuthenticatedStorageWitness, ...]:
        """Return only observations accepted by the configured storage verifier."""

        if len(self._storage_observations) != len(self._completed):
            raise ManagedRunError("managed Mem0 v5 storage observation coverage differs")
        return tuple(
            self._storage_observations[index] for index in sorted(self._storage_observations)
        )

    @property
    def terminal_evidence(self) -> Mem0OssTerminalCleanupEvidence:
        return self._terminal or self._service.terminal_cleanup_evidence

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
        if self._progress is not None:
            self._progress.initialize(authority=authority, admission=self._service.admission)
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
        if self._terminal is not None:
            raise ManagedRunError("managed Mem0 v5 lane is terminal")
        authority = self._required_authority()
        if self._service.state is Mem0OssFullRunState.RECONCILIATION_REQUIRED:
            raise ManagedRunError("managed Mem0 v5 status reconciliation is required")
        for index, unit in enumerate(authority.units):
            if index in self._completed or index in self._dispatched:
                continue
            operation_id = self._service.reserve(unit_index=index)
            self._operation_ids[index] = operation_id
            self._advance(
                index,
                ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED,
            )
            self._service.record_dispatched(unit_index=index)
            self._dispatched.add(index)
            receipt = self._lane.dispatch(
                authority=authority,
                unit=unit,
                operation_id_sha256=operation_id,
                admission=self._service.admission,
            )
            self._service.verify_dispatch_receipt(unit_index=index, receipt_payload=receipt)
            self._advance_receipt(index)
            self._finish_storage(index, unit, operation_id)
        seal = self._service.seal()
        if self._progress is not None:
            self._progress.record_seal(
                authority=authority,
                admission=self._service.admission,
                seal=seal,
            )
        return seal

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
                self._advance(index, ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED)
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
                self._advance_receipt(index)
                self._finish_storage(index, unit, recovery.operation_id_sha256)
            elif recovery.state is Mem0OssOperationState.RECEIPT_VERIFIED:
                self._finish_storage(index, unit, recovery.operation_id_sha256)
            elif recovery.state is Mem0OssOperationState.STORAGE_VERIFIED:
                self._restore_verified_storage(index, unit, recovery)
                self._service.commit(unit_index=index)
                self._completed.add(index)
                evidence = self._storage_observations[index]
                self._advance(
                    index,
                    ManagedMem0V5CheckpointPhase.COMMITTED,
                    provider_receipt_commitment_sha256=recovery.provider_receipt_sha256,
                    observation_commitment_sha256=evidence.evidence_commitment_sha256,
                    record_ids=evidence.created_record_ids,
                )
            elif recovery.state is Mem0OssOperationState.COMMITTED:
                self._restore_verified_storage(index, unit, recovery)
                self._completed.add(index)
            else:
                raise ManagedRunError("managed Mem0 v5 recovery stage is invalid")
        return safe_reserved

    def restore(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        request: Mem0OssAdmissionRequest,
        budget_policy: ManagedMem0V5BudgetPolicy,
    ) -> ManagedMem0V5Checkpoint:
        """Rebuild a fresh RAM service from authenticated progress without redispatch."""

        if self._progress is None:
            raise ManagedRunError("managed Mem0 v5 durable progress is required")
        if self._service.state is not Mem0OssFullRunState.UNBOUND:
            raise ManagedRunError("managed Mem0 v5 restore requires a fresh service")
        budget = ManagedMem0V5Budget.for_authority(authority)
        budget_policy.require(budget)
        self._service.admit(request, manifest_authority_payload=authority)
        self._service.activate(
            admission_commitment_sha256=self._service.admission.commitment_sha256
        )
        checkpoint = self._progress.load(authority=authority, admission=self._service.admission)
        self._authority = authority
        self._budget = budget
        if checkpoint.run_phase is ManagedMem0V5RunPhase.TERMINAL:
            self._terminal = checkpoint.terminal_evidence
            return checkpoint
        if checkpoint.run_phase is ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED:
            self._resume_cleanup(checkpoint)
            return checkpoint
        self._lane.admit(authority=authority, admission=self._service.admission)
        attempted: list[int] = []
        for index, unit_progress in enumerate(checkpoint.units):
            unit = authority.units[index]
            expected_operation_id = canonical_sha256(
                {
                    "admission_commitment_sha256": self._service.admission.commitment_sha256,
                    "unit_index": index,
                    "unit_identity_sha256": unit.unit_identity_sha256,
                }
            )
            if unit_progress.operation_id_sha256 != expected_operation_id:
                raise ManagedRunError("managed Mem0 v5 restore operation binding differs")
            if unit_progress.phase is ManagedMem0V5CheckpointPhase.RESERVED:
                continue
            operation_id = self._service.reserve(unit_index=index)
            if operation_id != expected_operation_id:
                raise ManagedRunError("managed Mem0 v5 restore operation binding differs")
            self._operation_ids[index] = operation_id
            self._service.record_dispatched(unit_index=index)
            self._dispatched.add(index)
            attempted.append(index)
        if attempted:
            self._service.recover_after_crash()
            for index in attempted:
                progress = checkpoint.units[index]
                receipt = self._lane.status(
                    operation_id_sha256=progress.operation_id_sha256,
                    admission=self._service.admission,
                )
                self._service.reconcile_receipt_readback(
                    unit_index=index,
                    receipt_payload=receipt,
                )
                recovery = self._recovery_state(index)
                if (
                    progress.provider_receipt_commitment_sha256 is not None
                    and progress.provider_receipt_commitment_sha256
                    != recovery.provider_receipt_sha256
                ):
                    raise ManagedRunError("managed Mem0 v5 restore receipt binding differs")
            for index in attempted:
                progress = checkpoint.units[index]
                unit = authority.units[index]
                evidence = self._inspect_storage(unit, progress.operation_id_sha256)
                self._service.verify_storage(unit_index=index, storage_payload=evidence)
                recovery = self._recovery_state(index)
                self._require_verified_storage_binding(evidence, recovery)
                if progress.observation_commitment_sha256 is not None and (
                    progress.observation_commitment_sha256 != evidence.evidence_commitment_sha256
                    or progress.record_ids != evidence.created_record_ids
                ):
                    raise ManagedRunError("managed Mem0 v5 restore storage binding differs")
                self._storage_observations[index] = evidence
                self._service.commit(unit_index=index)
                self._completed.add(index)
                if checkpoint.run_phase is ManagedMem0V5RunPhase.ACTIVE:
                    self._advance(
                        index,
                        ManagedMem0V5CheckpointPhase.COMMITTED,
                        provider_receipt_commitment_sha256=recovery.provider_receipt_sha256,
                        observation_commitment_sha256=evidence.evidence_commitment_sha256,
                        record_ids=evidence.created_record_ids,
                    )
        if checkpoint.run_phase is ManagedMem0V5RunPhase.SEALED:
            seal = self._service.seal()
            if seal != checkpoint.seal:
                raise ManagedRunError("managed Mem0 v5 restore seal differs")
        return checkpoint

    def seal_restored_completed(self) -> Mem0OssRunSeal:
        """Seal only fully restored committed operations, without dispatching."""

        if self._terminal is not None or self._pending_terminal is not None:
            raise ManagedRunError("managed Mem0 v5 lane is terminal")
        authority = self._required_authority()
        if self._service.state is Mem0OssFullRunState.SEALED:
            return self._service.seal_evidence
        expected = set(range(authority.operation_count))
        if (
            self._service.state is not Mem0OssFullRunState.ACTIVE
            or self._completed != expected
            or self._dispatched != expected
            or set(self._storage_observations) != expected
        ):
            raise ManagedRunError("managed Mem0 v5 restored completion coverage differs")
        seal = self._service.seal()
        if self._progress is not None:
            self._progress.record_seal(
                authority=authority,
                admission=self._service.admission,
                seal=seal,
            )
        return seal

    def search_evidence(
        self,
        *,
        corpus_id: str,
        query: str,
        limit: int,
    ) -> ManagedMem0V5SearchReceipt:
        if self._terminal is not None or self._pending_terminal is not None:
            raise ManagedRunError("managed Mem0 v5 lane is terminal")
        authority = self._required_authority()
        if self._service.state is not Mem0OssFullRunState.SEALED:
            raise ManagedRunError("managed Mem0 v5 search requires sealed state")
        corpus_units = tuple(
            (index, unit)
            for index, unit in enumerate(authority.units)
            if unit.corpus_id == corpus_id
        )
        if not corpus_units:
            raise ManagedRunError("managed Mem0 v5 search corpus binding differs")
        allowed_records: set[tuple[str, str, str]] = set()
        for index, unit in corpus_units:
            evidence = self._storage_observations.get(index)
            if evidence is None or evidence.source_pairs != ((unit.source_id, unit.source_sha256),):
                raise ManagedRunError("managed Mem0 v5 search source coverage differs")
            allowed_records.update(
                (record_id, unit.source_id, unit.source_sha256)
                for record_id in evidence.created_record_ids
            )
        search = getattr(self._lane, "search", None)
        if not callable(search):
            raise ManagedRunError("managed Mem0 v5 authenticated search port is unavailable")
        receipt = search(
            admission=self._service.admission,
            corpus_id=corpus_id,
            query=query,
            limit=limit,
        )
        if (
            type(receipt) is not ManagedMem0V5SearchReceipt
            or receipt.admission_commitment_sha256 != self._service.admission.commitment_sha256
            or receipt.corpus_id != corpus_id
            or receipt.query_commitment_sha256 != canonical_sha256({"query": query})
            or receipt.limit != limit
            or any(
                (record.record_id, record.source_id, record.source_sha256) not in allowed_records
                for record in receipt.records
            )
        ):
            raise ManagedRunError("managed Mem0 v5 search evidence binding differs")
        return receipt

    def search_authenticated_evidence(
        self,
        *,
        corpus_id: str,
        query: str,
        limit: int,
    ) -> ManagedMem0V5AuthenticatedSearchWitness:
        """Issue an opaque witness only after the full authenticated search path."""

        receipt = self.search_evidence(corpus_id=corpus_id, query=query, limit=limit)
        return ManagedMem0V5AuthenticatedSearchWitness(
            receipt=receipt,
            _token=_AUTHENTICATED_SEARCH_TOKEN,
        )

    def cleanup(self) -> Mem0OssTerminalCleanupEvidence:
        if self._pending_terminal is not None:
            pending = self._pending_terminal
            self._record_terminal(pending)
            return pending
        if self._terminal is not None:
            if self._terminal.terminal_state != Mem0OssFullRunState.DELETED.value:
                raise ManagedRunError("managed Mem0 v5 cleanup terminal state differs")
            return self._terminal
        if self._service.state is Mem0OssFullRunState.SEALED:
            self._service.begin_delete()
        elif self._service.state is not Mem0OssFullRunState.DELETING:
            raise ManagedRunError("managed Mem0 v5 cleanup state is invalid")
        return self._execute_cleanup(aborting=False)

    def abort(self) -> Mem0OssTerminalCleanupEvidence:
        if self._pending_terminal is not None:
            pending = self._pending_terminal
            self._record_terminal(pending)
            return pending
        if self._terminal is not None:
            if self._terminal.terminal_state != Mem0OssFullRunState.ABORTED.value:
                raise ManagedRunError("managed Mem0 v5 abort terminal state differs")
            return self._terminal
        if self._service.state in {
            Mem0OssFullRunState.ACTIVE,
            Mem0OssFullRunState.RECONCILIATION_REQUIRED,
            Mem0OssFullRunState.FAILED,
        }:
            self._service.begin_abort()
        elif self._service.state is not Mem0OssFullRunState.ABORTING:
            raise ManagedRunError("managed Mem0 v5 abort state is invalid")
        return self._execute_cleanup(aborting=True)

    def _execute_cleanup(self, *, aborting: bool) -> Mem0OssTerminalCleanupEvidence:
        context = self._service.cleanup_verification_context(aborting=aborting)
        basis = self._service.terminal_basis(aborting=aborting)
        if self._progress is not None:
            self._progress.record_cleanup_attempt(
                authority=self._required_authority(),
                admission=self._service.admission,
                cleanup_context=context,
                cleanup_request_commitment_sha256=cleanup_request_commitment(context),
                terminal_basis=basis,
            )
        payload = self._lane.cleanup(
            admission=self._service.admission,
            seal=None if aborting else self._service.seal_evidence,
            aborting=aborting,
            context=context,
        )
        if aborting:
            self._service.finish_abort(cleanup_payload=payload)
        else:
            self._service.finish_delete(cleanup_payload=payload)
        terminal = self._service.terminal_cleanup_evidence
        self._record_terminal(terminal)
        return terminal

    def _resume_cleanup(self, checkpoint: ManagedMem0V5Checkpoint) -> None:
        context = checkpoint.cleanup_context
        basis = checkpoint.terminal_basis
        if context is None or basis is None:
            raise ManagedRunError("managed Mem0 v5 cleanup checkpoint is incomplete")
        if cleanup_request_commitment(context) != checkpoint.cleanup_request_commitment_sha256:
            raise ManagedRunError("managed Mem0 v5 cleanup request binding differs")
        payload = self._lane.cleanup(
            admission=self._service.admission,
            seal=checkpoint.seal,
            aborting=context.aborting,
            context=context,
        )
        result = self._service.verify_cleanup_payload(payload=payload, context=context)
        terminal = build_terminal_evidence(basis=basis, result=result)
        self._record_terminal(terminal)

    def _record_terminal(self, terminal: Mem0OssTerminalCleanupEvidence) -> None:
        self._pending_terminal = terminal
        if self._progress is not None:
            current = self._progress.load(
                authority=self._required_authority(),
                admission=self._service.admission,
            )
            if current.run_phase is ManagedMem0V5RunPhase.TERMINAL:
                if current.terminal_evidence != terminal:
                    raise ManagedRunError("managed Mem0 v5 terminal evidence differs")
                self._terminal = terminal
                self._pending_terminal = None
                return
            self._progress.record_terminal(
                authority=self._required_authority(),
                admission=self._service.admission,
                terminal_evidence=terminal,
            )
        self._terminal = terminal
        self._pending_terminal = None

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
        self._advance(
            index,
            ManagedMem0V5CheckpointPhase.STORAGE_VERIFIED,
            provider_receipt_commitment_sha256=recovery.provider_receipt_sha256,
            observation_commitment_sha256=evidence.evidence_commitment_sha256,
            record_ids=evidence.created_record_ids,
        )
        self._service.commit(unit_index=index)
        self._completed.add(index)
        self._advance(
            index,
            ManagedMem0V5CheckpointPhase.COMMITTED,
            provider_receipt_commitment_sha256=recovery.provider_receipt_sha256,
            observation_commitment_sha256=evidence.evidence_commitment_sha256,
            record_ids=evidence.created_record_ids,
        )

    def _advance_receipt(self, index: int) -> None:
        recovery = self._recovery_state(index)
        self._advance(
            index,
            ManagedMem0V5CheckpointPhase.RECEIPT_VERIFIED,
            provider_receipt_commitment_sha256=recovery.provider_receipt_sha256,
        )

    def _advance(
        self,
        index: int,
        phase: ManagedMem0V5CheckpointPhase,
        *,
        provider_receipt_commitment_sha256: str | None = None,
        observation_commitment_sha256: str | None = None,
        record_ids: tuple[str, ...] = (),
    ) -> None:
        if self._progress is None:
            return
        self._progress.advance(
            authority=self._required_authority(),
            admission=self._service.admission,
            unit_index=index,
            phase=phase,
            provider_receipt_commitment_sha256=provider_receipt_commitment_sha256,
            observation_commitment_sha256=observation_commitment_sha256,
            record_ids=record_ids,
        )

    def _inspect_storage(
        self,
        unit: ManagedMem0V5SourceUnit,
        operation_id: str,
    ) -> ManagedMem0V5AuthenticatedStorageWitness:
        evidence = self._lane.inspect_storage(
            unit=unit,
            operation_id_sha256=operation_id,
            admission=self._service.admission,
        )
        if (
            type(evidence) is not ManagedMem0V5AuthenticatedStorageWitness
            or evidence.operation_id_sha256 != operation_id
            or evidence.unit_identity_sha256 != unit.unit_identity_sha256
            or evidence.source_pairs != ((unit.source_id, unit.source_sha256),)
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
        evidence: ManagedMem0V5AuthenticatedStorageWitness,
        recovery: Mem0OssOperationRecoveryState,
    ) -> None:
        if (
            evidence.storage_commitment_sha256 != recovery.stored_identity_sha256
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
    "ManagedMem0V5AuthenticatedSearchWitness",
    "ManagedMem0V5LaneCoordinator",
    "ManagedMem0V5LanePort",
    "ManagedMem0V5SearchReceipt",
    "ManagedMem0V5SourcePair",
    "ManagedMem0V5StorageObservation",
)
