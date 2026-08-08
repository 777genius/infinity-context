"""Production lifecycle facade for the managed Mem0 v5 benchmark lane."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import weakref
from dataclasses import dataclass, replace
from typing import NoReturn, final

from infinity_context_server.memory_comparison_full_execution_validation import (
    VerifiedFullExecutionValidation,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    FullExecutionProviderCall,
)
from infinity_context_server.memory_comparison_full_run_evidence import FullComparisonRunBindings
from infinity_context_server.memory_comparison_managed_mem0_v5_cleanup_readback import (
    ManagedMem0V5CleanupReadbackWitness,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    ManagedMem0V5Composition,
    ManagedMem0V5PairedRuntimeBundle,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_execution_evidence_adapter import (
    ManagedMem0V5ExecutionEvidenceAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_ingest_receipts import (
    ManagedMem0V5CorpusIngestReceipt,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lifecycle_adapter import (
    ManagedMem0V5LifecycleAdapter,
    ManagedMem0V5LifecycleAdapterError,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_authority import (
    ManagedMem0V5ProductionAuthority,
    ManagedMem0V5ProductionAuthorityDescriptor,
    _authenticate_managed_mem0_v5_production_authority,
    _consume_managed_mem0_v5_production_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5AuthenticatedCleanStateWitness,
    ManagedMem0V5CorpusIngestEvidence,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_transport_evidence import (
    ManagedTransportCoverageCapabilityPort,
    VerifiedManagedTransportCoverage,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_managed_v5_live_private_dependencies import (
    ManagedMem0V5OperationReceiptAuthority,
    managed_v5_live_operation_policy_commitment,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    CleanupVerificationContext,
    Mem0OssFullRunAdmission,
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssRunSeal,
    Mem0OssTerminalCleanupEvidence,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5CleanupRequest
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_terminal import (
    cleanup_request_commitment,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
    SessionIdentityEvidence,
)
from infinity_context_server.resumable_operation_journal.domain import (
    OperationManifest,
    OperationRunIdentity,
    OperationRunPhase,
)
from infinity_context_server.resumable_operation_journal.service import (
    ResumableOperationJournalService,
)

_LOCK = threading.RLock()
_SECRET = secrets.token_bytes(32)


class ManagedMem0V5ProductionLifecycleError(RuntimeError):
    """Fixed-code facade failure that never reflects delegated data."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5IngestSnapshot:
    """Commitment-only snapshot of the accepted ordered corpus evidence."""

    ordered_corpus_id_sha256: tuple[str, ...]
    ordered_evidence_commitment_sha256: tuple[str, ...]
    receipt_count: int
    snapshot_commitment_sha256: str


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5IngestProjection:
    """Authenticated exact evidence retained for the pure cutover projector."""

    snapshot: ManagedMem0V5IngestSnapshot
    evidence: tuple[ManagedMem0V5CorpusIngestEvidence, ...]
    admission_commitment_sha256: str

    def __post_init__(self) -> None:
        expected = (
            _ingest_snapshot(self.evidence)
            if type(self.evidence) is tuple and self.evidence
            else None
        )
        if (
            type(self.snapshot) is not ManagedMem0V5IngestSnapshot
            or type(self.evidence) is not tuple
            or len(self.evidence) != self.snapshot.receipt_count
            or any(type(item) is not ManagedMem0V5CorpusIngestEvidence for item in self.evidence)
            or tuple(item.evidence_commitment_sha256 for item in self.evidence)
            != self.snapshot.ordered_evidence_commitment_sha256
            or expected != self.snapshot
            or any(
                item.target_identity_sha256
                != canonical_sha256(
                    {
                        "admission_commitment_sha256": self.admission_commitment_sha256,
                        "corpus_id": item.corpus_id,
                    }
                )
                for item in self.evidence
            )
            or not is_sha256(self.admission_commitment_sha256)
        ):
            _fail("receipt_projection_invalid")


@dataclass(frozen=True, slots=True)
class _LifecycleState:
    descriptor: ManagedMem0V5ProductionAuthorityDescriptor
    binding: ManagedRunnerCompositionBinding
    composition: ManagedMem0V5Composition
    paired_runtime_bundle: ManagedMem0V5PairedRuntimeBundle
    lifecycle: ManagedMem0V5LifecycleAdapter
    evidence: ManagedMem0V5ExecutionEvidenceAdapter
    journal: ResumableOperationJournalService
    journal_identity: OperationRunIdentity
    operation_manifest: OperationManifest
    operation_receipt_authority: ManagedMem0V5OperationReceiptAuthority
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority
    phase: str
    receipts: tuple[ManagedMem0V5CorpusIngestReceipt, ...]
    snapshot: ManagedMem0V5IngestSnapshot | None
    cleanup_terminal: Mem0OssTerminalCleanupEvidence | None
    cleanup_request: Mem0V5CleanupRequest | None
    integrity_mac: bytes


_STATES: weakref.WeakKeyDictionary[ManagedMem0V5ProductionLifecycleAdapter, _LifecycleState]
_INSTANCE_LOCKS: weakref.WeakKeyDictionary[ManagedMem0V5ProductionLifecycleAdapter, threading.RLock]


@final
class ManagedMem0V5ProductionLifecycleAdapter:
    """Thin one-shot facade that delegates the existing authenticated state machines."""

    __slots__ = ("__weakref__",)

    def __init__(
        self,
        *,
        production_authority: ManagedMem0V5ProductionAuthority,
        composition: ManagedMem0V5Composition,
        paired_runtime_bundle: ManagedMem0V5PairedRuntimeBundle,
        composition_binding: ManagedRunnerCompositionBinding,
        lifecycle: ManagedMem0V5LifecycleAdapter,
        execution_evidence: ManagedMem0V5ExecutionEvidenceAdapter,
        operation_journal: ResumableOperationJournalService,
        operation_run_identity: OperationRunIdentity,
        operation_receipt_authority: ManagedMem0V5OperationReceiptAuthority,
        budget_policy: ManagedMem0V5BudgetPolicy,
        origin: str,
        receipt_authority: Mem0V5ObservedExtractionReceiptAuthority,
        operation_manifest: OperationManifest,
    ) -> None:
        if (
            type(composition) is not ManagedMem0V5Composition
            or type(paired_runtime_bundle) is not ManagedMem0V5PairedRuntimeBundle
            or type(lifecycle) is not ManagedMem0V5LifecycleAdapter
            or type(execution_evidence) is not ManagedMem0V5ExecutionEvidenceAdapter
            or lifecycle.composition_binding is not composition_binding
            or execution_evidence.composition_binding is not composition_binding
            or type(operation_journal) is not ResumableOperationJournalService
            or type(operation_run_identity) is not OperationRunIdentity
            or type(operation_receipt_authority) is not ManagedMem0V5OperationReceiptAuthority
            or type(budget_policy) is not ManagedMem0V5BudgetPolicy
        ):
            _fail("composition_invalid")
        try:
            lifecycle._validate_production_composition(
                paired_runtime_bundle=paired_runtime_bundle,
                composition=composition,
                authority=composition.authority,
                request=composition.request,
                coordinator=composition.coordinator,
            )
        except ManagedMem0V5LifecycleAdapterError:
            _fail("composition_invalid")
        _validate_journal_identity(
            operation_run_identity,
            operation_manifest,
            composition,
            composition_binding,
        )
        try:
            descriptor = _authenticate_managed_mem0_v5_production_authority(
                production_authority,
                composition=composition,
                composition_binding=composition_binding,
                origin=origin,
                receipt_authority=receipt_authority,
                operation_manifest=operation_manifest,
            )
        except Exception:
            _fail("authority_invalid")
        try:
            expected_policy_commitment = managed_v5_live_operation_policy_commitment(
                production_authority_commitment_sha256=(descriptor.authority_commitment_sha256),
                budget_policy=budget_policy,
            )
        except Exception:
            _fail("journal_identity_invalid")
        if operation_run_identity.policy_commitment_sha256 != expected_policy_commitment:
            _fail("journal_identity_invalid")
        try:
            operation_journal.initialize(operation_run_identity, operation_manifest)
        except Exception:
            _fail("journal_initialize_failed")
        try:
            consumed_descriptor = _consume_managed_mem0_v5_production_authority(
                production_authority,
                composition=composition,
                composition_binding=composition_binding,
                origin=origin,
                receipt_authority=receipt_authority,
                operation_manifest=operation_manifest,
            )
        except Exception:
            _fail("authority_invalid")
        if consumed_descriptor != descriptor:
            _fail("authority_invalid")
        state = _LifecycleState(
            descriptor,
            composition_binding,
            composition,
            paired_runtime_bundle,
            lifecycle,
            execution_evidence,
            operation_journal,
            operation_run_identity,
            operation_manifest,
            operation_receipt_authority,
            receipt_authority,
            "new",
            (),
            None,
            None,
            None,
            b"",
        )
        with _LOCK:
            _INSTANCE_LOCKS[self] = threading.RLock()
            _store_locked(self, state)

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        return _state(self).binding

    @property
    def authority_descriptor(self) -> ManagedMem0V5ProductionAuthorityDescriptor:
        return _state(self).descriptor

    def admit_or_restore(
        self, *, restore: bool = False
    ) -> (
        ManagedMem0V5AuthenticatedCleanStateWitness
        | Mem0OssRunSeal
        | Mem0OssTerminalCleanupEvidence
    ):
        if type(restore) is not bool:
            _fail("admission_invalid")
        with _instance_lock(self):
            state = _require_phase(self, {"new"}, "admission_invalid")
            delegated = False
            try:
                if restore:
                    resumed = state.journal.resume(state.journal_identity.run_id)
                    if resumed.outcome_unknown_count:
                        _fail("restore_reconciliation_required")
                    delegated = True
                    result = state.lifecycle.restore()
                else:
                    delegated = True
                    result = state.lifecycle.admit()
            except ManagedMem0V5ProductionLifecycleError:
                raise
            except Exception:
                if delegated:
                    _store(
                        self,
                        replace(state, phase="admission_failed", integrity_mac=b""),
                    )
                _fail("admission_failed")
            if type(result) is ManagedMem0V5AuthenticatedCleanStateWitness:
                phase = "admitted"
            elif type(result) is Mem0OssRunSeal:
                phase = "sealed"
            elif type(result) is Mem0OssTerminalCleanupEvidence:
                phase = "terminal"
            else:
                _store(
                    self,
                    replace(state, phase="admission_failed", integrity_mac=b""),
                )
                _fail("admission_result_invalid")
            _store(self, replace(state, phase=phase, integrity_mac=b""))
            return result

    def dispatch_once(self) -> Mem0OssRunSeal:
        with _instance_lock(self):
            state = _require_phase(
                self,
                {"admitted", "dispatch_ambiguous"},
                "dispatch_invalid",
            )
            try:
                preparations = state.journal.prepare_dispatch_batch(
                    tuple(
                        (operation, observed.request_body_sha256)
                        for operation, observed in zip(
                            state.operation_manifest.operations,
                            state.receipt_authority.operations,
                            strict=True,
                        )
                    )
                )
                if not all(item.should_dispatch for item in preparations):
                    _fail("dispatch_replay_blocked")
            except ManagedMem0V5ProductionLifecycleError:
                raise
            except Exception:
                _fail("dispatch_failed")
            try:
                result = state.lifecycle.dispatch_once()
            except Exception:
                _store(
                    self,
                    replace(state, phase="dispatch_ambiguous", integrity_mac=b""),
                )
                _fail("dispatch_failed")
            if type(result) is not Mem0OssRunSeal:
                _store(
                    self,
                    replace(state, phase="dispatch_ambiguous", integrity_mac=b""),
                )
                _fail("dispatch_result_invalid")
            _store(self, replace(state, phase="sealed", integrity_mac=b""))
            return result

    def consume_transport_coverage(
        self, capability: ManagedTransportCoverageCapabilityPort
    ) -> VerifiedManagedTransportCoverage:
        with _instance_lock(self):
            state = _require_phase(self, {"sealed"}, "coverage_invalid")
            try:
                result = state.lifecycle.consume_transport_coverage(capability)
            except Exception:
                _fail("coverage_failed")
            if type(result) is not VerifiedManagedTransportCoverage:
                _fail("coverage_result_invalid")
            _store(self, replace(state, phase="covered", integrity_mac=b""))
            return result

    def issue_corpus_receipt(self, *, corpus_id: str) -> ManagedMem0V5CorpusIngestReceipt:
        with _instance_lock(self):
            state = _require_phase(self, {"covered", "receipts"}, "receipt_invalid")
            try:
                receipt = state.lifecycle.issue_corpus_receipt(corpus_id=corpus_id)
            except Exception:
                _fail("receipt_failed")
            if type(receipt) is not ManagedMem0V5CorpusIngestReceipt:
                _fail("receipt_result_invalid")
            _store(
                self,
                replace(
                    state,
                    phase="receipts",
                    receipts=(*state.receipts, receipt),
                    integrity_mac=b"",
                ),
            )
            return receipt

    def consume_exact_receipts(
        self, receipts: tuple[ManagedMem0V5CorpusIngestReceipt, ...]
    ) -> ManagedMem0V5IngestSnapshot:
        return self.consume_exact_receipts_for_projection(receipts).snapshot

    def consume_exact_receipts_for_projection(
        self, receipts: tuple[ManagedMem0V5CorpusIngestReceipt, ...]
    ) -> ManagedMem0V5IngestProjection:
        """Consume once and retain only authenticated redacted identity evidence."""

        with _instance_lock(self):
            state = _require_phase(self, {"receipts"}, "receipt_consume_invalid")
            if receipts != state.receipts:
                _fail("receipt_consume_invalid")
            try:
                evidence = state.lifecycle._authenticate_corpus_receipts_for_production(
                    composition_binding=state.binding,
                    receipts=receipts,
                )
                snapshot = _ingest_snapshot(evidence)
                admission = Mem0OssFullRunAdmission(
                    request=state.composition.request,
                    ingestion_manifest_sha256=(
                        state.composition.authority.ingestion_manifest_sha256
                    ),
                    ingestion_root_sha256=(state.composition.authority.ingestion_root_sha256),
                    ingestion_unit_count=state.composition.authority.operation_count,
                )
                projection = ManagedMem0V5IngestProjection(
                    snapshot,
                    evidence,
                    admission.commitment_sha256,
                )
                _commit_operation_evidence(state, evidence)
                state.journal.seal(state.journal_identity.run_id)
                accepted = state.lifecycle.consume_corpus_receipts(receipts)
                if tuple(item.evidence_commitment_sha256 for item in accepted) != tuple(
                    item.evidence_commitment_sha256 for item in evidence
                ):
                    _fail("receipt_snapshot_invalid")
            except ManagedMem0V5ProductionLifecycleError:
                raise
            except Exception:
                _fail("receipt_consume_failed")
            _store(
                self,
                replace(state, phase="ready", snapshot=snapshot, integrity_mac=b""),
            )
            return projection

    def authenticate_exact_receipts(
        self, receipts: tuple[ManagedMem0V5CorpusIngestReceipt, ...]
    ) -> ManagedMem0V5IngestSnapshot:
        """Authenticate this lifecycle's exact ordered receipts without consuming them."""

        with _instance_lock(self):
            state = _require_phase(self, {"receipts"}, "receipt_authenticate_invalid")
            if receipts != state.receipts:
                _fail("receipt_authenticate_invalid")
            try:
                evidence = state.lifecycle._authenticate_corpus_receipts_for_production(
                    composition_binding=state.binding,
                    receipts=receipts,
                )
                snapshot = _ingest_snapshot(evidence)
            except ManagedMem0V5ProductionLifecycleError:
                raise
            except Exception:
                _fail("receipt_authenticate_failed")
            return snapshot

    def consume_ready_execution_evidence(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
    ) -> None:
        with _instance_lock(self):
            state = _require_phase(self, {"ready"}, "execution_evidence_invalid")
            if composition_binding is not state.binding or state.snapshot is None:
                _fail("execution_evidence_invalid")
            try:
                state.evidence.consume_ready_evidence(
                    composition_binding=composition_binding,
                    bindings=bindings,
                    cases=cases,
                )
            except Exception:
                _fail("execution_evidence_failed")
            _store(self, replace(state, phase="evidence", integrity_mac=b""))

    def seal_execution_validation(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        bindings: FullComparisonRunBindings,
        benchmark: str,
        case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
        required_model: str,
        required_route: ProviderRouteAttestation,
        provider_calls: tuple[FullExecutionProviderCall, ...],
        session_verifier: RunScopedSessionHmacKey,
        session_evidence: tuple[SessionIdentityEvidence, ...],
    ) -> VerifiedFullExecutionValidation:
        """Seal only after this facade admitted, dispatched and consumed evidence."""

        with _instance_lock(self):
            state = _require_phase(self, {"evidence"}, "execution_validation_invalid")
            if composition_binding is not state.binding or state.snapshot is None:
                _fail("execution_validation_invalid")
            try:
                result = state.evidence.seal_execution_validation(
                    composition_binding=composition_binding,
                    bindings=bindings,
                    benchmark=benchmark,
                    case_manifest=case_manifest,
                    required_model=required_model,
                    required_route=required_route,
                    provider_calls=provider_calls,
                    session_verifier=session_verifier,
                    session_evidence=session_evidence,
                )
            except Exception:
                _fail("execution_validation_failed")
            if type(result) is not VerifiedFullExecutionValidation:
                _fail("execution_validation_result_invalid")
            _store(self, replace(state, phase="validated", integrity_mac=b""))
            return result

    def terminalize(
        self, *, pass_two_request: object | None = None
    ) -> Mem0OssTerminalCleanupEvidence | ManagedMem0V5CleanupReadbackWitness:
        """Delegate cleanup/abort ownership; never expose a cleanup port."""

        with _instance_lock(self):
            state = _require_phase(
                self,
                {
                    "admission_failed",
                    "admitted",
                    "dispatch_ambiguous",
                    "sealed",
                    "covered",
                    "receipts",
                    "ready",
                    "evidence",
                    "validated",
                },
                "terminalize_invalid",
            )
            try:
                before = _validated_terminal_journal_snapshot(state)
                result = state.lifecycle.terminalize(pass_two_request=pass_two_request)
                if type(result) is Mem0OssTerminalCleanupEvidence:
                    result.__post_init__()
                elif type(result) is ManagedMem0V5CleanupReadbackWitness:
                    result.public_payload()
                else:
                    _fail("terminalize_result_invalid")
                after = _validated_terminal_journal_snapshot(state)
                if after != before:
                    _fail("terminalize_journal_changed")
            except ManagedMem0V5ProductionLifecycleError:
                raise
            except Exception:
                _fail("terminalize_failed")
            _store(self, replace(state, phase="terminal", integrity_mac=b""))
            return result

    def cleanup_pass_one(self) -> Mem0OssTerminalCleanupEvidence:
        """Run exact completed-flow deletion once, retaining pass-two authority."""

        lock = _instance_lock(self)
        with lock:
            state = _require_phase(
                self,
                {"ready", "evidence", "validated", "cleanup_retry"},
                "cleanup_pass_one_invalid",
            )
            before = _validated_cleanup_journal_snapshot(state)
            _store(
                self,
                replace(state, phase="cleanup_pass_one_inflight", integrity_mac=b""),
            )
        try:
            terminal = state.lifecycle.cleanup_pass1()
            if type(terminal) is not Mem0OssTerminalCleanupEvidence:
                _fail("cleanup_pass_one_result_invalid")
            terminal.__post_init__()
            request = _cleanup_pass_two_request(terminal)
            after = _validated_cleanup_journal_snapshot(state)
            if after != before:
                _fail("cleanup_pass_one_journal_changed")
        except ManagedMem0V5ProductionLifecycleError:
            with lock:
                current = _state(self)
                if current.phase == "cleanup_pass_one_inflight":
                    _store(
                        self,
                        replace(
                            current,
                            phase="cleanup_integrity_failed",
                            integrity_mac=b"",
                        ),
                    )
            raise
        except Exception:
            with lock:
                current = _state(self)
                if current.phase == "cleanup_pass_one_inflight":
                    _store(
                        self,
                        replace(current, phase="cleanup_retry", integrity_mac=b""),
                    )
            _fail("cleanup_pass_one_failed")
        with lock:
            current = _require_phase(
                self,
                {"cleanup_pass_one_inflight"},
                "cleanup_pass_one_concurrent",
            )
            _store(
                self,
                replace(
                    current,
                    phase="cleanup_pass_one",
                    cleanup_terminal=terminal,
                    cleanup_request=request,
                    integrity_mac=b"",
                ),
            )
        return terminal

    def cleanup_pass_two(self) -> ManagedMem0V5CleanupReadbackWitness:
        """Run exact readback using only the pass-one-derived immutable request."""

        lock = _instance_lock(self)
        with lock:
            state = _require_phase(
                self,
                {"cleanup_pass_one", "cleanup_pass_two_retry"},
                "cleanup_pass_two_invalid",
            )
            if state.cleanup_terminal is None or state.cleanup_request is None:
                _fail("cleanup_pass_two_authority_invalid")
            before = _validated_cleanup_journal_snapshot(state)
            _store(
                self,
                replace(state, phase="cleanup_pass_two_inflight", integrity_mac=b""),
            )
        try:
            witness = state.lifecycle.cleanup_pass2(request=state.cleanup_request)
            if type(witness) is not ManagedMem0V5CleanupReadbackWitness:
                _fail("cleanup_pass_two_result_invalid")
            witness.public_payload()
            after = _validated_cleanup_journal_snapshot(state)
            if after != before:
                _fail("cleanup_pass_two_journal_changed")
        except ManagedMem0V5ProductionLifecycleError:
            with lock:
                current = _state(self)
                if current.phase == "cleanup_pass_two_inflight":
                    _store(
                        self,
                        replace(
                            current,
                            phase="cleanup_integrity_failed",
                            integrity_mac=b"",
                        ),
                    )
            raise
        except Exception:
            with lock:
                current = _state(self)
                if current.phase == "cleanup_pass_two_inflight":
                    _store(
                        self,
                        replace(current, phase="cleanup_pass_two_retry", integrity_mac=b""),
                    )
            _fail("cleanup_pass_two_failed")
        with lock:
            current = _require_phase(
                self,
                {"cleanup_pass_two_inflight"},
                "cleanup_pass_two_concurrent",
            )
            _store(self, replace(current, phase="terminal", integrity_mac=b""))
        return witness

    def observed_extraction_tokens(self) -> tuple[int, int]:
        """Return persisted terminal usage only after cleanup reaches pass two."""

        state = _require_phase(self, {"terminal"}, "observed_token_verification_invalid")
        terminal = state.cleanup_terminal
        if terminal is None:
            _fail("observed_token_verification_invalid")
        return (
            terminal.provider_observed_request_tokens,
            terminal.provider_observed_response_tokens,
        )

    def __repr__(self) -> str:
        return "ManagedMem0V5ProductionLifecycleAdapter(<redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("managed Mem0 v5 production lifecycle is nonserializable")


def _validated_terminal_journal_snapshot(state: _LifecycleState) -> object:
    snapshot = state.journal.snapshot(state.journal_identity.run_id)
    expected = state.journal_identity.expected_operation_count
    if snapshot.outcome_unknown_count:
        _fail("terminalize_journal_invalid")
    if snapshot.run.phase is OperationRunPhase.SEALED:
        valid = (
            state.phase in {"sealed", "ready", "evidence", "validated"}
            and snapshot.pending_count == 0
            and snapshot.dispatched_count == 0
            and snapshot.committed_count == expected
        )
    elif snapshot.run.phase is OperationRunPhase.ACTIVE:
        if state.phase in {"admission_failed", "admitted", "dispatch_ambiguous"}:
            valid = (
                snapshot.pending_count
                == (expected if state.phase in {"admission_failed", "admitted"} else 0)
                and snapshot.dispatched_count
                == (0 if state.phase in {"admission_failed", "admitted"} else expected)
                and snapshot.committed_count == 0
            )
        else:
            valid = (
                state.phase in {"sealed", "covered", "receipts"}
                and snapshot.pending_count == 0
                and snapshot.dispatched_count == expected
                and snapshot.committed_count == 0
            )
    else:
        valid = False
    if not valid:
        _fail("terminalize_journal_invalid")
    return snapshot


def _validated_cleanup_journal_snapshot(state: _LifecycleState) -> object:
    snapshot = state.journal.snapshot(state.journal_identity.run_id)
    if (
        snapshot.run.phase is not OperationRunPhase.SEALED
        or snapshot.outcome_unknown_count
        or snapshot.pending_count
        or snapshot.dispatched_count
        or snapshot.committed_count != state.journal_identity.expected_operation_count
    ):
        _fail("cleanup_journal_invalid")
    return snapshot


def _cleanup_pass_two_request(
    terminal: Mem0OssTerminalCleanupEvidence,
) -> Mem0V5CleanupRequest:
    context = CleanupVerificationContext(
        terminal.admission_commitment_sha256,
        terminal.seal_commitment_sha256,
        terminal.operation_root_sha256,
        terminal.operation_inventory_root_sha256,
        terminal.deleted_operation_count,
        False,
    )
    return Mem0V5CleanupRequest(
        context.admission_commitment_sha256,
        context.seal_commitment_sha256,
        context.operation_root_sha256,
        context.operation_inventory_root_sha256,
        context.expected_operation_count,
        context.aborting,
        canonical_sha256({"kind": "cleanup", "binding": cleanup_request_commitment(context)}),
    )


def _ingest_snapshot(
    evidence: tuple[ManagedMem0V5CorpusIngestEvidence, ...],
) -> ManagedMem0V5IngestSnapshot:
    if not evidence or any(
        type(item) is not ManagedMem0V5CorpusIngestEvidence for item in evidence
    ):
        _fail("receipt_snapshot_invalid")
    corpus = tuple(hashlib.sha256(item.corpus_id.encode()).hexdigest() for item in evidence)
    commitments = tuple(item.evidence_commitment_sha256 for item in evidence)
    material = {
        "ordered_corpus_id_sha256": corpus,
        "ordered_evidence_commitment_sha256": commitments,
        "receipt_count": len(evidence),
    }
    return ManagedMem0V5IngestSnapshot(
        corpus,
        commitments,
        len(evidence),
        canonical_sha256(material),
    )


def _validate_journal_identity(
    identity: OperationRunIdentity,
    manifest: OperationManifest,
    composition: ManagedMem0V5Composition,
    binding: ManagedRunnerCompositionBinding,
) -> None:
    if (
        identity.run_id != binding.run_id
        or identity.run_id != composition.request.run_id
        or identity.operation_namespace != "managed_mem0_v5_production"
        or identity.manifest_commitment_sha256 != manifest.commitment_sha256
        or identity.expected_operation_count != len(manifest.operations)
    ):
        _fail("journal_identity_invalid")


def _commit_operation_evidence(
    state: _LifecycleState,
    evidence: tuple[ManagedMem0V5CorpusIngestEvidence, ...],
) -> None:
    by_unit = {
        unit.unit_identity_sha256: (corpus, unit) for corpus in evidence for unit in corpus.units
    }
    observed_by_unit = {
        item.unit_identity_sha256: item for item in state.receipt_authority.operations
    }
    if set(by_unit) != set(observed_by_unit):
        _fail("journal_evidence_invalid")
    # Reviewed recovery invariant: every receipt below is derived only from the
    # immutable authority, manifest and authenticated corpus evidence. A partial
    # loop retry therefore replays byte-identical OperationReceipt values, and
    # journal.commit is idempotent for those exact bytes. Regression:
    # test_production_lifecycle_retries_journal_before_atomic_ingest_consume.
    for operation, observed in zip(
        state.operation_manifest.operations,
        state.receipt_authority.operations,
        strict=True,
    ):
        corpus, unit = by_unit[observed.unit_identity_sha256]
        result_commitment = canonical_sha256(
            {
                "production_authority_commitment_sha256": (
                    state.descriptor.authority_commitment_sha256
                ),
                "corpus_evidence_commitment_sha256": corpus.evidence_commitment_sha256,
                "unit": unit.payload(),
            }
        )
        receipt = state.operation_receipt_authority._issue_exact(
            identity=operation,
            request_commitment_sha256=observed.request_body_sha256,
            result_commitment_sha256=result_commitment,
        )
        state.journal.commit(operation, receipt)


def _state(adapter: object) -> _LifecycleState:
    with _LOCK:
        return _state_locked(adapter)


def _state_locked(adapter: object) -> _LifecycleState:
    if type(adapter) is not ManagedMem0V5ProductionLifecycleAdapter:
        _fail("invalid")
    state = _STATES.get(adapter)
    if state is None or not hmac.compare_digest(state.integrity_mac, _state_mac(adapter, state)):
        _fail("invalid")
    if (
        state.lifecycle.composition_binding is not state.binding
        or state.evidence.composition_binding is not state.binding
    ):
        _fail("composition_invalid")
    return state


def _require_phase(
    adapter: ManagedMem0V5ProductionLifecycleAdapter,
    allowed: set[str],
    suffix: str,
) -> _LifecycleState:
    state = _state(adapter)
    if state.phase not in allowed:
        _fail(suffix)
    return state


def _store(adapter: ManagedMem0V5ProductionLifecycleAdapter, state: _LifecycleState) -> None:
    with _LOCK:
        _store_locked(adapter, state)


def _store_locked(adapter: ManagedMem0V5ProductionLifecycleAdapter, state: _LifecycleState) -> None:
    _STATES[adapter] = replace(state, integrity_mac=_state_mac(adapter, state))


def _instance_lock(adapter: object) -> threading.RLock:
    if type(adapter) is not ManagedMem0V5ProductionLifecycleAdapter:
        _fail("invalid")
    with _LOCK:
        lock = _INSTANCE_LOCKS.get(adapter)
    if lock is None:
        _fail("invalid")
    return lock


def _state_mac(adapter: ManagedMem0V5ProductionLifecycleAdapter, state: _LifecycleState) -> bytes:
    material = json.dumps(
        {
            "adapter_identity": id(adapter),
            "authority_commitment_sha256": state.descriptor.authority_commitment_sha256,
            "binding_identity": id(state.binding),
            "composition_identity": id(state.composition),
            "paired_runtime_bundle_identity": id(state.paired_runtime_bundle),
            "lifecycle_identity": id(state.lifecycle),
            "evidence_identity": id(state.evidence),
            "journal_identity": id(state.journal),
            "operation_run_identity": id(state.journal_identity),
            "operation_manifest_identity": id(state.operation_manifest),
            "operation_receipt_authority_identity": id(state.operation_receipt_authority),
            "receipt_authority_identity": id(state.receipt_authority),
            "phase": state.phase,
            "receipt_identities": tuple(id(item) for item in state.receipts),
            "snapshot": None
            if state.snapshot is None
            else state.snapshot.snapshot_commitment_sha256,
            "cleanup_terminal": None
            if state.cleanup_terminal is None
            else state.cleanup_terminal.commitment_sha256,
            "cleanup_request_identity": None
            if state.cleanup_request is None
            else id(state.cleanup_request),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hmac.new(_SECRET, material, hashlib.sha256).digest()


def _fail(suffix: str) -> NoReturn:
    raise ManagedMem0V5ProductionLifecycleError(
        f"managed_mem0_v5_production_lifecycle_{suffix}"
    ) from None


_STATES = weakref.WeakKeyDictionary()
_INSTANCE_LOCKS = weakref.WeakKeyDictionary()

__all__ = (
    "ManagedMem0V5IngestProjection",
    "ManagedMem0V5IngestSnapshot",
    "ManagedMem0V5ProductionLifecycleAdapter",
    "ManagedMem0V5ProductionLifecycleError",
)
