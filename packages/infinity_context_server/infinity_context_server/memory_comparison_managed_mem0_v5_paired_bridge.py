"""Provider-free bridge from sealed managed Mem0 v5 to paired answer evidence."""

from __future__ import annotations

import hashlib
import hmac
import threading
from enum import Enum
from typing import Protocol, final

from infinity_context_server.memory_comparison_gold_blind_answer_contract import GoldBlindEvidence
from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    ManagedMem0V5Checkpoint,
    ManagedMem0V5RunPhase,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_cleanup_readback import (
    ManagedMem0V5CleanupReadbackWitness,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5SearchRecord,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import ManagedMem0V5BudgetPolicy
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5AuthenticatedCleanStateWitness,
    ManagedMem0V5CleanCorpusScope,
    ManagedMem0V5CleanStateSnapshotPort,
    ManagedMem0V5CleanStateWitnessVerifierPort,
    ManagedMem0V5CorpusEvidenceProjector,
    ManagedMem0V5CorpusIngestEvidence,
    ManagedMem0V5DurableCleanStatePort,
    managed_mem0_v5_clean_evidence_commitment_sha256,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_search_witness import (
    ManagedMem0V5AuthenticatedSearchWitness,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
    ManagedMem0V5StorageWitnessVerifierPort,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_transport_evidence import (
    ManagedTransportCoverageCapabilityPort,
    VerifiedManagedTransportCoverage,
    authenticate_managed_transport_coverage,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    Mem0OssFullRunState,
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssRunSeal,
    Mem0OssTerminalCleanupEvidence,
)


@final
class ManagedMem0V5PairedEvidenceProjector:
    """Join contract-issued retrieval to canonical source time, never provider time."""

    __slots__ = (
        "_authority_commitment_sha256",
        "_expected_admission_commitment_sha256",
        "_sources",
    )

    def __init__(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        expected_admission_commitment_sha256: str,
    ) -> None:
        if type(authority) is not ManagedMem0V5ManifestAuthority:
            raise ManagedRunError("managed Mem0 v5 paired manifest authority is invalid")
        authority.__post_init__()
        if not is_sha256(expected_admission_commitment_sha256):
            raise ManagedRunError("managed Mem0 v5 paired admission authority is invalid")
        sources: dict[tuple[str, str], tuple[str, str]] = {}
        for unit in authority.units:
            key = (unit.corpus_id, unit.source_id)
            if key in sources:
                raise ManagedRunError("managed Mem0 v5 paired source authority is duplicated")
            sources[key] = (unit.source_sha256, unit.observation_date)
        self._sources = sources
        self._authority_commitment_sha256 = authority.authority_commitment_sha256
        self._expected_admission_commitment_sha256 = expected_admission_commitment_sha256

    @property
    def authority_commitment_sha256(self) -> str:
        return self._authority_commitment_sha256

    def project(
        self,
        *,
        authenticated_receipt: ManagedMem0V5AuthenticatedSearchWitness,
        corpus_id: str,
        query: str,
        top_k: int,
        cutoff: int,
    ) -> tuple[GoldBlindEvidence, ...]:
        _require_search_request(corpus_id=corpus_id, query=query, top_k=top_k, cutoff=cutoff)
        if type(authenticated_receipt) is not ManagedMem0V5AuthenticatedSearchWitness:
            raise ManagedRunError("managed Mem0 v5 paired search receipt is unauthenticated")
        receipt = authenticated_receipt.receipt
        receipt.__post_init__()
        expected_root = canonical_sha256(
            {
                "results": [
                    record.public_payload(rank) for rank, record in enumerate(receipt.records)
                ]
            }
        )
        if (
            receipt.admission_commitment_sha256 != self._expected_admission_commitment_sha256
            or receipt.corpus_id != corpus_id
            or receipt.query_commitment_sha256 != canonical_sha256({"query": query})
            or receipt.limit != top_k
            or len(receipt.records) > receipt.limit
            or receipt.result_root_sha256 != expected_root
        ):
            raise ManagedRunError("managed Mem0 v5 paired search binding differs")

        evidence: list[GoldBlindEvidence] = []
        seen_record_ids: set[str] = set()
        for rank, record in enumerate(receipt.records[:cutoff], start=1):
            if type(record) is not ManagedMem0V5SearchRecord:
                raise ManagedRunError("managed Mem0 v5 paired search record is invalid")
            record.__post_init__()
            if record.record_id in seen_record_ids:
                raise ManagedRunError("managed Mem0 v5 paired search record is duplicated")
            seen_record_ids.add(record.record_id)
            source = self._sources.get((corpus_id, record.source_id))
            if source is None:
                raise ManagedRunError("managed Mem0 v5 paired source authority is missing")
            source_sha256, created_at = source
            if not hmac.compare_digest(source_sha256, record.source_sha256):
                raise ManagedRunError("managed Mem0 v5 paired source authority differs")
            evidence.append(
                GoldBlindEvidence(
                    item_id=record.record_id,
                    text=record.memory,
                    rank=rank,
                    created_at=created_at,
                )
            )
        return tuple(evidence)


class ManagedMem0V5PairedCoordinatorPort(Protocol):
    def admit(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        request: Mem0OssAdmissionRequest,
        budget_policy: ManagedMem0V5BudgetPolicy,
    ) -> None: ...

    def dispatch_pending(self) -> Mem0OssRunSeal: ...

    def restore(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        request: Mem0OssAdmissionRequest,
        budget_policy: ManagedMem0V5BudgetPolicy,
    ) -> ManagedMem0V5Checkpoint: ...

    def seal_restored_completed(self) -> Mem0OssRunSeal: ...

    def search_authenticated_evidence(
        self, *, corpus_id: str, query: str, limit: int
    ) -> ManagedMem0V5AuthenticatedSearchWitness: ...

    def cleanup(self) -> Mem0OssTerminalCleanupEvidence: ...

    def abort(self) -> Mem0OssTerminalCleanupEvidence: ...

    @property
    def terminal_evidence(self) -> Mem0OssTerminalCleanupEvidence: ...

    @property
    def storage_observations(self) -> tuple[ManagedMem0V5AuthenticatedStorageWitness, ...]: ...


class ManagedMem0V5CleanupReadbackCapabilityPort(Protocol):
    def readback(
        self, *, pass_index: int, request: object, terminal: Mem0OssTerminalCleanupEvidence
    ) -> ManagedMem0V5CleanupReadbackWitness: ...


class _RunState(Enum):
    NEW = "new"
    ADMITTING = "admitting"
    ADMITTED = "admitted"
    DISPATCHING = "dispatching"
    RESTORING = "restoring"
    SEALED = "sealed"
    SEARCHING = "searching"
    CLEANING = "cleaning"
    CLEANUP_RETRY = "cleanup_retry"
    ABORT_RETRY = "abort_retry"
    TERMINAL = "terminal"
    FAILED = "failed"


@final
class ManagedMem0V5PairedRun:
    __slots__ = (
        "_authority",
        "_accepted_seal",
        "_accepted_seal_commitment_sha256",
        "_budget_policy",
        "_clean_state",
        "_clean_state_snapshot",
        "_clean_state_verifier",
        "_cleanup_readback_consumed",
        "_coordinator",
        "_corpus_projector",
        "_durable_clean_state",
        "_expected_admission_commitment_sha256",
        "_expected_clean_scopes",
        "_lock",
        "_projector",
        "_request",
        "_state",
        "_terminal",
        "_transport_coverage_consumed",
    )

    def __init__(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        request: Mem0OssAdmissionRequest,
        budget_policy: ManagedMem0V5BudgetPolicy,
        coordinator: ManagedMem0V5PairedCoordinatorPort,
        clean_state_snapshot_port: ManagedMem0V5CleanStateSnapshotPort,
        clean_state_verifier: ManagedMem0V5CleanStateWitnessVerifierPort,
        durable_clean_state_port: ManagedMem0V5DurableCleanStatePort,
        storage_witness_verifier: ManagedMem0V5StorageWitnessVerifierPort,
    ) -> None:
        if (
            type(authority) is not ManagedMem0V5ManifestAuthority
            or type(request) is not Mem0OssAdmissionRequest
            or type(budget_policy) is not ManagedMem0V5BudgetPolicy
            or not _coordinator_port(coordinator)
            or not _clean_state_snapshot_port(clean_state_snapshot_port)
            or not _clean_state_verifier_port(clean_state_verifier)
            or not _durable_clean_state_port(durable_clean_state_port)
        ):
            raise ManagedRunError("managed Mem0 v5 paired run composition is invalid")
        authority.__post_init__()
        admission = Mem0OssFullRunAdmission(
            request=request,
            ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
            ingestion_root_sha256=authority.ingestion_root_sha256,
            ingestion_unit_count=authority.operation_count,
        )
        self._authority = authority
        self._accepted_seal: Mem0OssRunSeal | None = None
        self._accepted_seal_commitment_sha256: str | None = None
        self._request = request
        self._budget_policy = budget_policy
        self._coordinator = coordinator
        self._clean_state_snapshot = clean_state_snapshot_port
        self._clean_state_verifier = clean_state_verifier
        self._durable_clean_state = durable_clean_state_port
        self._corpus_projector = ManagedMem0V5CorpusEvidenceProjector(
            authority=authority,
            admission_commitment_sha256=admission.commitment_sha256,
            storage_verifier=storage_witness_verifier,
        )
        self._expected_admission_commitment_sha256 = admission.commitment_sha256
        self._expected_clean_scopes = _expected_clean_scopes(
            authority=authority,
            admission_commitment_sha256=admission.commitment_sha256,
        )
        self._projector = ManagedMem0V5PairedEvidenceProjector(
            authority=authority,
            expected_admission_commitment_sha256=admission.commitment_sha256,
        )
        self._lock = threading.RLock()
        self._state = _RunState.NEW
        self._clean_state: ManagedMem0V5AuthenticatedCleanStateWitness | None = None
        self._terminal: Mem0OssTerminalCleanupEvidence | None = None
        self._transport_coverage_consumed = False
        self._cleanup_readback_consumed = False

    def start(self) -> Mem0OssRunSeal:
        self.admit()
        return self.dispatch()

    def admit(self) -> ManagedMem0V5AuthenticatedCleanStateWitness:
        with self._lock:
            self._require_new()
            self._state = _RunState.ADMITTING
            try:
                self._coordinator.admit(
                    authority=self._authority,
                    request=self._request,
                    budget_policy=self._budget_policy,
                )
                witness = self._clean_state_snapshot.prove_empty_scopes(
                    expected_admission_commitment_sha256=(
                        self._expected_admission_commitment_sha256
                    ),
                    expected_run_id_sha256=_run_id_sha256(self._request.run_id),
                    expected_authority_commitment_sha256=(
                        self._authority.authority_commitment_sha256
                    ),
                    expected_scopes=self._expected_clean_scopes,
                )
                authenticated = self._authenticate_clean_state(witness)
                self._durable_clean_state.save_original(authenticated)
            except Exception as primary:
                self._abort_after_failure(primary)
                raise
            self._clean_state = authenticated
            self._state = _RunState.ADMITTED
            return authenticated

    def dispatch(self) -> Mem0OssRunSeal:
        with self._lock:
            if self._state is not _RunState.ADMITTED:
                raise ManagedRunError("managed Mem0 v5 paired dispatch requires admission")
            self._state = _RunState.DISPATCHING
            try:
                seal = self._coordinator.dispatch_pending()
                self._require_seal_binding(seal)
            except Exception as primary:
                self._abort_after_failure(primary)
                raise
            self._accept_seal(seal)
            self._state = _RunState.SEALED
            return seal

    def restore(self) -> Mem0OssRunSeal | Mem0OssTerminalCleanupEvidence:
        with self._lock:
            self._require_new()
            self._state = _RunState.RESTORING
            try:
                replayed = self._durable_clean_state.load_original(
                    expected_admission_commitment_sha256=(
                        self._expected_admission_commitment_sha256
                    ),
                    expected_run_id_sha256=_run_id_sha256(self._request.run_id),
                    expected_authority_commitment_sha256=(
                        self._authority.authority_commitment_sha256
                    ),
                    expected_evidence_commitment_sha256=(
                        managed_mem0_v5_clean_evidence_commitment_sha256(
                            admission_commitment_sha256=(
                                self._expected_admission_commitment_sha256
                            ),
                            run_id_sha256=_run_id_sha256(self._request.run_id),
                            authority_commitment_sha256=(
                                self._authority.authority_commitment_sha256
                            ),
                            scopes=self._expected_clean_scopes,
                        )
                    ),
                )
                self._clean_state = self._authenticate_clean_state(replayed)
                checkpoint = self._coordinator.restore(
                    authority=self._authority,
                    request=self._request,
                    budget_policy=self._budget_policy,
                )
                self._require_checkpoint_binding(checkpoint)
                if checkpoint.run_phase is ManagedMem0V5RunPhase.ACTIVE:
                    try:
                        seal = self._coordinator.dispatch_pending()
                        self._require_seal_binding(seal)
                    except Exception as primary:
                        self._abort_after_failure(primary)
                        raise
                    self._state = _RunState.SEALED
                    self._accept_seal(seal)
                    return seal
                if checkpoint.run_phase is ManagedMem0V5RunPhase.SEALED:
                    seal = self._coordinator.seal_restored_completed()
                    self._require_seal_binding(seal)
                    self._state = _RunState.SEALED
                    self._accept_seal(seal)
                    return seal
                if checkpoint.run_phase in {
                    ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED,
                    ManagedMem0V5RunPhase.TERMINAL,
                }:
                    terminal = self._coordinator.terminal_evidence
                    self._require_restored_terminal_binding(
                        terminal=terminal,
                        checkpoint=checkpoint,
                    )
                    if checkpoint.seal is not None:
                        self._require_seal_binding(checkpoint.seal)
                        self._accept_seal(checkpoint.seal)
                    self._terminal = terminal
                    self._state = _RunState.TERMINAL
                    return terminal
                raise ManagedRunError("managed Mem0 v5 paired restore phase is invalid")
            except Exception:
                if self._state not in {_RunState.TERMINAL, _RunState.ABORT_RETRY}:
                    self._state = _RunState.FAILED
                raise

    def search(
        self, *, corpus_id: str, query: str, top_k: int, cutoff: int | None = None
    ) -> tuple[GoldBlindEvidence, ...]:
        with self._lock:
            if self._state is not _RunState.SEALED:
                raise ManagedRunError("managed Mem0 v5 paired search requires sealed state")
            selected_cutoff = top_k if cutoff is None else cutoff
            _require_search_request(
                corpus_id=corpus_id,
                query=query,
                top_k=top_k,
                cutoff=selected_cutoff,
            )
            self._state = _RunState.SEARCHING
            try:
                authenticated = self._coordinator.search_authenticated_evidence(
                    corpus_id=corpus_id,
                    query=query,
                    limit=top_k,
                )
                return self._projector.project(
                    authenticated_receipt=authenticated,
                    corpus_id=corpus_id,
                    query=query,
                    top_k=top_k,
                    cutoff=selected_cutoff,
                )
            finally:
                self._state = _RunState.SEALED

    @property
    def clean_state_evidence(self) -> ManagedMem0V5AuthenticatedCleanStateWitness:
        with self._lock:
            if self._clean_state is None:
                raise ManagedRunError("managed Mem0 v5 paired clean-state evidence is missing")
            return self._authenticate_clean_state(self._clean_state)

    def corpus_ingest_evidence(self, *, corpus_id: str) -> ManagedMem0V5CorpusIngestEvidence:
        with self._lock:
            if (
                self._state is not _RunState.SEALED
                or self._accepted_seal is None
                or self._accepted_seal_commitment_sha256 is None
            ):
                raise ManagedRunError("managed Mem0 v5 corpus evidence requires sealed state")
            observations = self._coordinator.storage_observations
            return self._corpus_projector.project(
                run_id=self._request.run_id,
                corpus_id=corpus_id,
                seal=self._accepted_seal,
                expected_seal_commitment_sha256=self._accepted_seal_commitment_sha256,
                observations=observations,
            )

    def consume_transport_coverage(
        self, capability: ManagedTransportCoverageCapabilityPort
    ) -> VerifiedManagedTransportCoverage:
        with self._lock:
            if self._state is not _RunState.SEALED:
                raise ManagedRunError("managed Mem0 v5 transport coverage requires sealed state")
            if self._transport_coverage_consumed:
                raise ManagedRunError("managed Mem0 v5 transport coverage is already consumed")
            consume = getattr(capability, "consume_complete_transport_coverage", None)
            if not callable(consume):
                raise ManagedRunError("managed Mem0 v5 transport capability is invalid")
            observations = self._coordinator.storage_observations
            if len(observations) != self._authority.operation_count:
                raise ManagedRunError("managed Mem0 v5 transport coverage differs")
            self._transport_coverage_consumed = True
            coverage = consume(
                expected_admission_commitment_sha256=(self._expected_admission_commitment_sha256),
                expected_operation_ids=tuple(item.operation_id_sha256 for item in observations),
            )
            try:
                authenticated_coverage = authenticate_managed_transport_coverage(coverage)
            except ManagedRunError:
                raise ManagedRunError(
                    "managed Mem0 v5 transport coverage witness differs"
                ) from None
            if (
                authenticated_coverage.run_id_sha256 != _run_id_sha256(self._request.run_id)
                or authenticated_coverage.operation_count != len(observations)
                or authenticated_coverage.admission_commitment_sha256
                != self._expected_admission_commitment_sha256
                or authenticated_coverage.authority_commitment_sha256
                != self._authority.authority_commitment_sha256
            ):
                raise ManagedRunError("managed Mem0 v5 transport coverage witness differs")
            return authenticated_coverage

    def cleanup(self) -> Mem0OssTerminalCleanupEvidence:
        with self._lock:
            if self._state is _RunState.TERMINAL:
                if self._terminal is None:
                    raise ManagedRunError("managed Mem0 v5 paired terminal evidence is missing")
                if self._terminal.terminal_state != Mem0OssFullRunState.DELETED.value:
                    raise ManagedRunError("managed Mem0 v5 paired cleanup terminal is not deleted")
                self._require_terminal_binding(self._terminal)
                return self._terminal
            if self._state not in {_RunState.SEALED, _RunState.CLEANUP_RETRY}:
                raise ManagedRunError("managed Mem0 v5 paired cleanup requires sealed state")
            self._state = _RunState.CLEANING
            try:
                terminal = self._coordinator.cleanup()
                self._require_terminal_binding(terminal)
            except Exception:
                self._state = _RunState.CLEANUP_RETRY
                raise
            self._terminal = terminal
            self._state = _RunState.TERMINAL
            return terminal

    def cleanup_readback(
        self,
        *,
        pass_index: int,
        capability: ManagedMem0V5CleanupReadbackCapabilityPort,
        request: object,
    ) -> ManagedMem0V5CleanupReadbackWitness:
        with self._lock:
            terminal = self._terminal
            if (
                self._state is not _RunState.TERMINAL
                or terminal is None
                or terminal.terminal_state != Mem0OssFullRunState.DELETED.value
            ):
                raise ManagedRunError("managed Mem0 v5 cleanup readback requires deleted terminal")
            if self._cleanup_readback_consumed:
                raise ManagedRunError("managed Mem0 v5 cleanup readback is already consumed")
            readback = getattr(capability, "readback", None)
            if not callable(readback):
                raise ManagedRunError("managed Mem0 v5 cleanup readback capability is invalid")
            self._cleanup_readback_consumed = True
            witness = readback(pass_index=pass_index, request=request, terminal=terminal)
            if type(witness) is not ManagedMem0V5CleanupReadbackWitness:
                raise ManagedRunError("managed Mem0 v5 cleanup readback witness differs")
            witness.public_payload()
            if witness.terminal_commitment_sha256 != terminal.commitment_sha256:
                raise ManagedRunError("managed Mem0 v5 cleanup readback terminal differs")
            return witness

    def retry_abort(self) -> Mem0OssTerminalCleanupEvidence:
        """Retry only terminal abort cleanup; never re-admit or redispatch."""

        with self._lock:
            if self._state is not _RunState.ABORT_RETRY:
                raise ManagedRunError("managed Mem0 v5 paired abort retry is invalid")
            try:
                terminal = self._coordinator.abort()
                self._require_abort_binding(terminal)
            except Exception:
                self._state = _RunState.ABORT_RETRY
                raise
            self._terminal = terminal
            self._state = _RunState.TERMINAL
            return terminal

    def _authenticate_clean_state(
        self, witness: object
    ) -> ManagedMem0V5AuthenticatedCleanStateWitness:
        authenticated = self._clean_state_verifier.authenticate_clean_state(witness)
        if (
            type(authenticated) is not ManagedMem0V5AuthenticatedCleanStateWitness
            or authenticated.admission_commitment_sha256
            != self._expected_admission_commitment_sha256
            or authenticated.run_id_sha256 != _run_id_sha256(self._request.run_id)
            or authenticated.authority_commitment_sha256
            != self._authority.authority_commitment_sha256
            or authenticated.scopes != self._expected_clean_scopes
        ):
            raise ManagedRunError("managed Mem0 v5 paired clean-state binding differs")
        return authenticated

    def _abort_after_failure(self, primary: Exception) -> None:
        self._state = _RunState.CLEANING
        try:
            terminal = self._coordinator.abort()
            self._require_abort_binding(terminal)
            self._terminal = terminal
            self._state = _RunState.TERMINAL
        except Exception as cleanup_error:
            self._state = _RunState.ABORT_RETRY
            primary.add_note(f"managed Mem0 v5 paired abort failed: {type(cleanup_error).__name__}")

    def _require_new(self) -> None:
        if self._state is not _RunState.NEW:
            raise ManagedRunError("managed Mem0 v5 paired run is already started")

    def _require_checkpoint_binding(self, checkpoint: object) -> None:
        if type(checkpoint) is ManagedMem0V5Checkpoint:
            try:
                checkpoint.__post_init__()
            except Exception:
                raise ManagedRunError("managed Mem0 v5 paired checkpoint binding differs") from None
        if (
            type(checkpoint) is not ManagedMem0V5Checkpoint
            or checkpoint.authority_commitment_sha256 != self._authority.authority_commitment_sha256
            or checkpoint.admission_commitment_sha256 != self._expected_admission_commitment_sha256
        ):
            raise ManagedRunError("managed Mem0 v5 paired checkpoint binding differs")

    def _require_seal_binding(self, seal: object) -> None:
        if type(seal) is Mem0OssRunSeal:
            try:
                seal.__post_init__()
            except Exception:
                raise ManagedRunError("managed Mem0 v5 paired seal binding differs") from None
        if (
            type(seal) is not Mem0OssRunSeal
            or seal.admission_commitment_sha256 != self._expected_admission_commitment_sha256
            or seal.operation_count != self._authority.operation_count
            or seal.ingestion_root_sha256 != self._authority.ingestion_root_sha256
        ):
            raise ManagedRunError("managed Mem0 v5 paired seal binding differs")

    def _accept_seal(self, seal: Mem0OssRunSeal) -> None:
        self._accepted_seal = seal
        self._accepted_seal_commitment_sha256 = seal.commitment_sha256

    def _require_terminal_binding(self, terminal: object) -> None:
        seal = self._accepted_seal
        if type(terminal) is Mem0OssTerminalCleanupEvidence:
            try:
                terminal.__post_init__()
            except Exception:
                raise ManagedRunError("managed Mem0 v5 paired terminal binding differs") from None
        if (
            type(terminal) is not Mem0OssTerminalCleanupEvidence
            or type(seal) is not Mem0OssRunSeal
            or terminal.terminal_state != Mem0OssFullRunState.DELETED.value
            or terminal.admission_commitment_sha256 != self._expected_admission_commitment_sha256
            or terminal.deleted_operation_count != self._authority.operation_count
            or terminal.seal_commitment_sha256 != seal.commitment_sha256
            or terminal.operation_root_sha256 != seal.operation_root_sha256
            or terminal.residual_record_count != 0
            or terminal.residual_root_sha256 != MEM0_OSS_EMPTY_ROOT_SHA256
        ):
            raise ManagedRunError("managed Mem0 v5 paired terminal binding differs")

    def _require_abort_binding(self, terminal: object) -> None:
        if type(terminal) is Mem0OssTerminalCleanupEvidence:
            try:
                terminal.__post_init__()
            except Exception:
                raise ManagedRunError("managed Mem0 v5 paired abort binding differs") from None
        if (
            type(terminal) is not Mem0OssTerminalCleanupEvidence
            or terminal.terminal_state != Mem0OssFullRunState.ABORTED.value
            or terminal.admission_commitment_sha256 != self._expected_admission_commitment_sha256
            or terminal.seal_commitment_sha256 is not None
            or terminal.operation_root_sha256 is not None
            or terminal.deleted_operation_count > self._authority.operation_count
            or terminal.residual_record_count != 0
            or terminal.residual_root_sha256 != MEM0_OSS_EMPTY_ROOT_SHA256
        ):
            raise ManagedRunError("managed Mem0 v5 paired abort binding differs")

    def _require_restored_terminal_binding(
        self,
        *,
        terminal: object,
        checkpoint: ManagedMem0V5Checkpoint,
    ) -> None:
        context = checkpoint.cleanup_context
        basis = checkpoint.terminal_basis
        if type(terminal) is Mem0OssTerminalCleanupEvidence:
            try:
                terminal.__post_init__()
            except Exception:
                raise ManagedRunError(
                    "managed Mem0 v5 paired restored terminal binding differs"
                ) from None
        if context is None or basis is None:
            raise ManagedRunError("managed Mem0 v5 paired terminal checkpoint is incomplete")
        if (
            type(terminal) is not Mem0OssTerminalCleanupEvidence
            or terminal.terminal_state != basis.terminal_state
            or terminal.admission_commitment_sha256 != self._expected_admission_commitment_sha256
            or terminal.operation_inventory_root_sha256 != context.operation_inventory_root_sha256
            or terminal.provider_observed_extraction_calls
            != basis.provider_observed_extraction_calls
            or terminal.provider_observed_request_tokens != basis.provider_observed_request_tokens
            or terminal.provider_observed_response_tokens != basis.provider_observed_response_tokens
            or terminal.failed_receipts != basis.failed_receipts
            or terminal.residual_record_count != 0
            or terminal.residual_root_sha256 != MEM0_OSS_EMPTY_ROOT_SHA256
        ):
            raise ManagedRunError("managed Mem0 v5 paired restored terminal binding differs")
        if context.aborting:
            self._require_abort_binding(terminal)
            return
        if (
            checkpoint.seal is None
            or terminal.seal_commitment_sha256 != checkpoint.seal.commitment_sha256
            or terminal.operation_root_sha256 != checkpoint.seal.operation_root_sha256
            or terminal.deleted_operation_count != self._authority.operation_count
        ):
            raise ManagedRunError("managed Mem0 v5 paired restored terminal seal differs")


def _require_search_request(
    *, corpus_id: object, query: object, top_k: object, cutoff: object
) -> None:
    if (
        type(corpus_id) is not str
        or not corpus_id
        or corpus_id != corpus_id.strip()
        or type(query) is not str
        or not query
        or query != query.strip()
        or type(top_k) is not int
        or not 1 <= top_k <= 200
        or type(cutoff) is not int
        or not 1 <= cutoff <= top_k
    ):
        raise ManagedRunError("managed Mem0 v5 paired search request is invalid")


def _coordinator_port(value: object) -> bool:
    return all(
        callable(getattr(value, name, None))
        for name in (
            "admit",
            "dispatch_pending",
            "restore",
            "seal_restored_completed",
            "search_authenticated_evidence",
            "cleanup",
            "abort",
        )
    ) and all(
        isinstance(getattr(type(value), name, None), property)
        for name in ("terminal_evidence", "storage_observations")
    )


def _expected_clean_scopes(
    *,
    authority: ManagedMem0V5ManifestAuthority,
    admission_commitment_sha256: str,
) -> tuple[ManagedMem0V5CleanCorpusScope, ...]:
    grouped: dict[str, list[ManagedMem0V5SourceUnit]] = {}
    for unit in authority.units:
        grouped.setdefault(unit.corpus_id, []).append(unit)
    scopes = []
    for corpus_id, units in grouped.items():
        source_scope_root = canonical_sha256(
            {
                "source_scopes": [
                    {"source_id": item.source_id, "source_sha256": item.source_sha256}
                    for item in units
                ]
            }
        )
        scopes.append(
            ManagedMem0V5CleanCorpusScope(
                corpus_identity_sha256=canonical_sha256({"corpus_id": corpus_id}),
                scope_identity_sha256=canonical_sha256(
                    {
                        "admission_commitment_sha256": admission_commitment_sha256,
                        "corpus_id": corpus_id,
                        "source_scope_root_sha256": source_scope_root,
                    }
                ),
                source_scope_count=len(units),
                residual_record_count=0,
                residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
            )
        )
    return tuple(scopes)


def _run_id_sha256(run_id: str) -> str:
    return hashlib.sha256(run_id.encode()).hexdigest()


def _clean_state_snapshot_port(value: object) -> bool:
    return callable(getattr(value, "prove_empty_scopes", None))


def _clean_state_verifier_port(value: object) -> bool:
    return callable(getattr(value, "authenticate_clean_state", None))


def _durable_clean_state_port(value: object) -> bool:
    return all(callable(getattr(value, name, None)) for name in ("save_original", "load_original"))


__all__ = (
    "ManagedMem0V5PairedCoordinatorPort",
    "ManagedMem0V5CleanupReadbackCapabilityPort",
    "ManagedMem0V5PairedEvidenceProjector",
    "ManagedMem0V5PairedRun",
)
