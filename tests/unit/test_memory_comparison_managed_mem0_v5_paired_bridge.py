from __future__ import annotations

import hashlib
import threading
from dataclasses import fields, replace

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    HmacSha256ManagedMem0V5CheckpointSigner,
    ManagedMem0V5Checkpoint,
    ManagedMem0V5CheckpointPhase,
    ManagedMem0V5CheckpointUnit,
    ManagedMem0V5RunPhase,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5SearchReceipt,
    ManagedMem0V5SearchRecord,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5AuthenticatedSearchWitness,
    ManagedMem0V5BudgetPolicy,
    ManagedMem0V5LaneCoordinator,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_paired_bridge import (
    ManagedMem0V5PairedEvidenceProjector,
    ManagedMem0V5PairedRun,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
    create_managed_mem0_v5_storage_witness_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    CleanupVerificationContext,
    CleanupVerificationResult,
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    Mem0OssFullRunState,
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationResult,
    StorageVerificationContext,
    StorageVerificationResult,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssRunSeal,
    Mem0OssTerminalCleanupEvidence,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import Mem0OssFullRunService
from infinity_context_server.memory_comparison_mem0_oss_v5_terminal import (
    Mem0OssTerminalBasis,
    cleanup_request_commitment,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _authority() -> ManagedMem0V5ManifestAuthority:
    corpus_id = f"locomo-corpus-{'a' * 64}"
    record = {
        "schema_version": "memory-comparison-managed-corpus.v2",
        "benchmark": "locomo",
        "corpus_id": corpus_id,
        "thread_id": f"locomo-thread-{'b' * 64}",
        "memories": [
            {
                "kind": "fact",
                "role": "user",
                "session_alias": "session-0001",
                "source_alias": "memory-000001",
                "speaker": "Alice",
                "session_date": "2024-03-10",
                "text": "Alice likes tea.",
                "timestamp": 1,
            }
        ],
        "documents": [],
        "conversations": [],
    }
    return ManagedMem0V5ManifestProjector().project(
        (ManagedRunCase("case-1", corpus_id, record),),
        current_date="2026-08-07",
    )


def _request(operation_count: int) -> Mem0OssAdmissionRequest:
    return Mem0OssAdmissionRequest(
        run_id="paired-v5-test",
        route_sha256=_sha("route"),
        credential_binding_sha256=_sha("credential"),
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="source-r1",
        runtime_source_sha256=_sha("runtime-source"),
        runtime_base_sha256=_sha("runtime-base"),
        expected_operation_count=operation_count,
    )


def _admission(authority: ManagedMem0V5ManifestAuthority, request: Mem0OssAdmissionRequest) -> str:
    return Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    ).commitment_sha256


def _seal(authority: ManagedMem0V5ManifestAuthority, admission: str) -> Mem0OssRunSeal:
    return Mem0OssRunSeal(
        admission_commitment_sha256=admission,
        operation_count=authority.operation_count,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        operation_root_sha256=_sha("operation-root"),
        provider_observed_extraction_calls=authority.operation_count,
        provider_observed_request_tokens=10,
        provider_observed_response_tokens=5,
    )


def _terminal(
    authority: ManagedMem0V5ManifestAuthority,
    admission: str,
    *,
    terminal_state: str = Mem0OssFullRunState.DELETED.value,
) -> Mem0OssTerminalCleanupEvidence:
    seal = _seal(authority, admission)
    aborted = terminal_state == Mem0OssFullRunState.ABORTED.value
    return Mem0OssTerminalCleanupEvidence(
        terminal_state=terminal_state,
        admission_commitment_sha256=admission,
        seal_commitment_sha256=None if aborted else seal.commitment_sha256,
        operation_root_sha256=None if aborted else seal.operation_root_sha256,
        operation_inventory_root_sha256=_sha("inventory"),
        deleted_operation_count=0 if aborted else authority.operation_count,
        residual_record_count=0,
        residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
        provider_observed_extraction_calls=authority.operation_count,
        provider_observed_request_tokens=10,
        provider_observed_response_tokens=5,
        failed_receipts=(),
    )


def _checkpoint(
    authority: ManagedMem0V5ManifestAuthority,
    admission: str,
    phase: ManagedMem0V5RunPhase,
    *,
    aborting: bool = False,
) -> ManagedMem0V5Checkpoint:
    seal = _seal(authority, admission)
    unit_phase = (
        ManagedMem0V5CheckpointPhase.RESERVED
        if phase is ManagedMem0V5RunPhase.ACTIVE
        else ManagedMem0V5CheckpointPhase.COMMITTED
    )
    unit = (
        ManagedMem0V5CheckpointUnit(0, _sha("operation"), unit_phase)
        if unit_phase is ManagedMem0V5CheckpointPhase.RESERVED
        else ManagedMem0V5CheckpointUnit(
            0,
            _sha("operation"),
            unit_phase,
            _sha("receipt"),
            _sha("observation"),
            (),
        )
    )
    cleanup_context = None
    basis = None
    terminal = None
    cleanup_commitment = None
    phase_seal = seal if phase is not ManagedMem0V5RunPhase.ACTIVE and not aborting else None
    if phase in {
        ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED,
        ManagedMem0V5RunPhase.TERMINAL,
    }:
        cleanup_context = CleanupVerificationContext(
            admission,
            None if aborting else seal.commitment_sha256,
            None if aborting else seal.operation_root_sha256,
            _sha("inventory"),
            authority.operation_count,
            aborting,
        )
        cleanup_commitment = cleanup_request_commitment(cleanup_context)
        basis = Mem0OssTerminalBasis(
            (Mem0OssFullRunState.ABORTED.value if aborting else Mem0OssFullRunState.DELETED.value),
            cleanup_context,
            authority.operation_count,
            10,
            5,
            (),
        )
        if phase is ManagedMem0V5RunPhase.TERMINAL:
            terminal = _terminal(
                authority,
                admission,
                terminal_state=(
                    Mem0OssFullRunState.ABORTED.value
                    if aborting
                    else Mem0OssFullRunState.DELETED.value
                ),
            )
    return ManagedMem0V5Checkpoint.create(
        authority_commitment_sha256=authority.authority_commitment_sha256,
        admission_commitment_sha256=admission,
        generation=0,
        previous_checkpoint_commitment_sha256=None,
        units=(unit,),
        run_phase=phase,
        seal=phase_seal,
        cleanup_context=cleanup_context,
        cleanup_request_commitment_sha256=cleanup_commitment,
        terminal_basis=basis,
        terminal_evidence=terminal,
        signer=HmacSha256ManagedMem0V5CheckpointSigner(key=b"k" * 32),
    )


def _record(*, record_id: str, source_id: str, source_sha256: str):
    memory = f"retrieved {record_id}"
    return ManagedMem0V5SearchRecord(
        record_id,
        memory,
        _sha(memory),
        source_id,
        source_sha256,
        0.9,
    )


def _receipt(
    authority: ManagedMem0V5ManifestAuthority,
    admission: str,
    *,
    query: str,
    limit: int,
    source_id: str | None = None,
    source_sha256: str | None = None,
) -> ManagedMem0V5SearchReceipt:
    unit = authority.units[0]
    records = tuple(
        _record(
            record_id=f"record-{index:03d}",
            source_id=source_id or unit.source_id,
            source_sha256=source_sha256 or unit.source_sha256,
        )
        for index in range(limit)
    )
    root = canonical_sha256(
        {"results": [record.public_payload(rank) for rank, record in enumerate(records)]}
    )
    return ManagedMem0V5SearchReceipt(
        admission,
        unit.corpus_id,
        canonical_sha256({"query": query}),
        limit,
        records,
        root,
        _sha("verified-evidence"),
    )


class _ReceiptVerifier:
    def mark_outcome_unknown(self, *, context: object) -> None:
        del context

    def verify_dispatch_receipt(
        self, *, payload: object, context: RuntimeReceiptVerificationContext
    ) -> RuntimeReceiptVerificationResult:
        assert payload == {"receipt": "dispatch"}
        return RuntimeReceiptVerificationResult(
            context.admission_commitment_sha256,
            context.operation_id_sha256,
            context.unit_identity_sha256,
            context.unit_sha256,
            context.route_sha256,
            context.scope_sha256,
            _sha("provider-receipt"),
            Mem0OssReceiptDisposition.COMPLETED,
            1,
            0,
            10,
            5,
        )

    verify_status_readback = verify_dispatch_receipt


class _StorageVerifier:
    def verify(
        self, *, payload: object, context: StorageVerificationContext
    ) -> StorageVerificationResult:
        assert type(payload) is ManagedMem0V5AuthenticatedStorageWitness
        return StorageVerificationResult(
            context.admission_commitment_sha256,
            context.operation_id_sha256,
            context.unit_identity_sha256,
            context.unit_sha256,
            context.route_sha256,
            context.scope_sha256,
            context.provider_receipt_sha256,
            payload.storage_commitment_sha256,
            len(payload.created_record_ids),
        )


class _CleanupVerifier:
    def verify(
        self, *, payload: object, context: CleanupVerificationContext
    ) -> CleanupVerificationResult:
        assert payload == {"cleanup": context.aborting}
        return CleanupVerificationResult(
            context.admission_commitment_sha256,
            context.seal_commitment_sha256,
            context.operation_root_sha256,
            context.operation_inventory_root_sha256,
            context.expected_operation_count,
            0,
            MEM0_OSS_EMPTY_ROOT_SHA256,
        )


class _VerifiedSearchLane:
    def __init__(
        self,
        authority: ManagedMem0V5ManifestAuthority,
        *,
        query: str,
        limit: int,
        receipt_admission: str,
    ) -> None:
        self.authority = authority
        self.query = query
        self.limit = limit
        self.receipt_admission = receipt_admission
        self.issuer, _ = create_managed_mem0_v5_storage_witness_authority()

    def admit(self, **kwargs: object) -> None:
        del kwargs

    def dispatch(self, **kwargs: object) -> object:
        del kwargs
        return {"receipt": "dispatch"}

    def status(self, **kwargs: object) -> object:
        del kwargs
        return {"receipt": "dispatch"}

    def inspect_storage(self, **kwargs: object):
        unit = kwargs["unit"]
        return self.issuer.issue_authenticated_storage(
            operation_id_sha256=kwargs["operation_id_sha256"],
            unit_identity_sha256=unit.unit_identity_sha256,
            storage_commitment_sha256=_sha("storage"),
            created_record_ids=tuple(f"record-{index:03d}" for index in range(200)),
            source_pairs=((unit.source_id, unit.source_sha256),),
        )

    def search(self, **kwargs: object) -> ManagedMem0V5SearchReceipt:
        assert kwargs["query"] == self.query
        assert kwargs["limit"] == self.limit
        return _receipt(
            self.authority,
            self.receipt_admission,
            query=self.query,
            limit=self.limit,
        )

    def cleanup(self, **kwargs: object) -> object:
        return {"cleanup": kwargs["aborting"]}


def _verified_witness(
    authority: ManagedMem0V5ManifestAuthority,
    request: Mem0OssAdmissionRequest,
    *,
    query: str,
    limit: int,
    receipt_admission: str,
) -> ManagedMem0V5AuthenticatedSearchWitness:
    lane = _VerifiedSearchLane(
        authority,
        query=query,
        limit=limit,
        receipt_admission=receipt_admission,
    )
    coordinator = ManagedMem0V5LaneCoordinator(
        service=Mem0OssFullRunService(
            manifest_port=ManagedMem0V5ManifestProjector(),
            receipt_port=_ReceiptVerifier(),
            storage_port=_StorageVerifier(),
            cleanup_port=_CleanupVerifier(),
        ),
        lane_port=lane,
    )
    coordinator.admit(
        authority=authority,
        request=request,
        budget_policy=ManagedMem0V5BudgetPolicy(10_000),
    )
    coordinator.dispatch_pending()
    witness = coordinator.search_authenticated_evidence(
        corpus_id=authority.units[0].corpus_id,
        query=query,
        limit=limit,
    )
    coordinator.cleanup()
    return witness


class _Coordinator:
    def __init__(
        self,
        authority: ManagedMem0V5ManifestAuthority,
        request: Mem0OssAdmissionRequest,
    ) -> None:
        self.authority = authority
        self.request = request
        self.admission = _admission(authority, request)
        self.restore_phase = ManagedMem0V5RunPhase.SEALED
        self.restore_aborting = False
        self.admit_calls = 0
        self.dispatch_calls = 0
        self.restore_calls = 0
        self.seal_restored_calls = 0
        self.search_calls: list[int] = []
        self.cleanup_calls = 0
        self.abort_calls = 0
        self.cleanup_failures = 0
        self.abort_failures = 0
        self.dispatch_failures = 0
        self.start_gate: threading.Event | None = None
        self.release_gate: threading.Event | None = None

    @property
    def terminal_evidence(self) -> Mem0OssTerminalCleanupEvidence:
        return _terminal(
            self.authority,
            self.admission,
            terminal_state=(
                Mem0OssFullRunState.ABORTED.value
                if self.restore_aborting
                else Mem0OssFullRunState.DELETED.value
            ),
        )

    def admit(self, **kwargs: object) -> None:
        assert kwargs["authority"] is self.authority
        self.admit_calls += 1

    def dispatch_pending(self) -> Mem0OssRunSeal:
        self.dispatch_calls += 1
        self._block_if_configured()
        if self.dispatch_failures:
            self.dispatch_failures -= 1
            raise RuntimeError("dispatch failed")
        return _seal(self.authority, self.admission)

    def restore(self, **kwargs: object) -> ManagedMem0V5Checkpoint:
        assert kwargs["authority"] is self.authority
        self.restore_calls += 1
        return _checkpoint(
            self.authority,
            self.admission,
            self.restore_phase,
            aborting=self.restore_aborting,
        )

    def seal_restored_completed(self) -> Mem0OssRunSeal:
        self.seal_restored_calls += 1
        return _seal(self.authority, self.admission)

    def search_authenticated_evidence(
        self, *, corpus_id: str, query: str, limit: int
    ) -> ManagedMem0V5AuthenticatedSearchWitness:
        assert corpus_id == self.authority.units[0].corpus_id
        self.search_calls.append(limit)
        self._block_if_configured()
        return _verified_witness(
            self.authority,
            self.request,
            query=query,
            limit=limit,
            receipt_admission=self.admission,
        )

    def cleanup(self) -> Mem0OssTerminalCleanupEvidence:
        self.cleanup_calls += 1
        if self.cleanup_failures:
            self.cleanup_failures -= 1
            raise RuntimeError("cleanup failed")
        return _terminal(self.authority, self.admission)

    def abort(self) -> Mem0OssTerminalCleanupEvidence:
        self.abort_calls += 1
        if self.abort_failures:
            self.abort_failures -= 1
            raise RuntimeError("abort failed")
        return _terminal(
            self.authority,
            self.admission,
            terminal_state=Mem0OssFullRunState.ABORTED.value,
        )

    def _block_if_configured(self) -> None:
        if self.start_gate is not None:
            self.start_gate.set()
        if self.release_gate is not None:
            assert self.release_gate.wait(timeout=2)


def _run():
    authority = _authority()
    request = _request(authority.operation_count)
    coordinator = _Coordinator(authority, request)
    return (
        authority,
        coordinator,
        ManagedMem0V5PairedRun(
            authority=authority,
            request=request,
            budget_policy=ManagedMem0V5BudgetPolicy(10_000),
            coordinator=coordinator,
        ),
    )


@pytest.mark.parametrize(("top_k", "cutoff"), [(50, 50), (200, 50), (200, 200)])
def test_run_projects_top_slices_with_authoritative_time(top_k: int, cutoff: int) -> None:
    authority, coordinator, run = _run()
    run.start()
    evidence = run.search(
        corpus_id=authority.units[0].corpus_id,
        query="What does Alice like?",
        top_k=top_k,
        cutoff=cutoff,
    )
    assert len(evidence) == cutoff
    assert tuple(item.rank for item in evidence) == tuple(range(1, cutoff + 1))
    assert {item.created_at for item in evidence} == {"2024-03-10"}
    assert coordinator.admit_calls == coordinator.dispatch_calls == 1


@pytest.mark.parametrize("phase", tuple(ManagedMem0V5RunPhase))
def test_restore_routes_each_exact_checkpoint_phase(phase: ManagedMem0V5RunPhase) -> None:
    _authority_value, coordinator, run = _run()
    coordinator.restore_phase = phase
    result = run.restore()
    assert coordinator.restore_calls == 1
    if phase is ManagedMem0V5RunPhase.ACTIVE:
        assert type(result) is Mem0OssRunSeal
        assert coordinator.dispatch_calls == 1
        assert coordinator.seal_restored_calls == 0
    elif phase is ManagedMem0V5RunPhase.SEALED:
        assert type(result) is Mem0OssRunSeal
        assert coordinator.dispatch_calls == 0
        assert coordinator.seal_restored_calls == 1
    else:
        assert type(result) is Mem0OssTerminalCleanupEvidence
        assert coordinator.dispatch_calls == coordinator.seal_restored_calls == 0
        assert run.cleanup() is result


@pytest.mark.parametrize(
    "phase",
    [ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED, ManagedMem0V5RunPhase.TERMINAL],
)
def test_restore_accepts_exact_aborted_terminal_phases(
    phase: ManagedMem0V5RunPhase,
) -> None:
    _authority_value, coordinator, run = _run()
    coordinator.restore_phase = phase
    coordinator.restore_aborting = True

    result = run.restore()

    assert type(result) is Mem0OssTerminalCleanupEvidence
    assert result.terminal_state == Mem0OssFullRunState.ABORTED.value
    assert result.seal_commitment_sha256 is None
    assert result.operation_root_sha256 is None
    assert coordinator.dispatch_calls == coordinator.seal_restored_calls == 0
    with pytest.raises(ManagedRunError, match="cleanup terminal is not deleted"):
        run.cleanup()


def test_projector_rejects_raw_self_consistent_receipt() -> None:
    authority, coordinator, _run_value = _run()
    projector = ManagedMem0V5PairedEvidenceProjector(
        authority=authority,
        expected_admission_commitment_sha256=coordinator.admission,
    )
    receipt = _receipt(authority, coordinator.admission, query="query", limit=1)
    with pytest.raises(ManagedRunError, match="unauthenticated"):
        projector.project(  # type: ignore[arg-type]
            authenticated_receipt=receipt,
            corpus_id=authority.units[0].corpus_id,
            query="query",
            top_k=1,
            cutoff=1,
        )


def test_projector_rejects_mutated_witness_records_over_limit() -> None:
    authority, coordinator, _run_value = _run()
    witness = _verified_witness(
        authority,
        coordinator.request,
        query="query",
        limit=1,
        receipt_admission=coordinator.admission,
    )
    receipt = witness.receipt
    object.__setattr__(receipt, "records", receipt.records * 2)
    projector = ManagedMem0V5PairedEvidenceProjector(
        authority=authority,
        expected_admission_commitment_sha256=coordinator.admission,
    )

    with pytest.raises(ManagedRunError, match="witness differs"):
        projector.project(
            authenticated_receipt=witness,
            corpus_id=authority.units[0].corpus_id,
            query="query",
            top_k=1,
            cutoff=1,
        )


def test_run_rejects_foreign_admission_receipt() -> None:
    authority, coordinator, run = _run()
    run.start()
    coordinator.admission = _sha("foreign-admission")
    with pytest.raises(ManagedRunError, match="search evidence binding differs"):
        run.search(corpus_id=authority.units[0].corpus_id, query="query", top_k=1)


def test_projection_fails_closed_for_source_and_manifest_tampering() -> None:
    authority, coordinator, run = _run()
    run.start()
    original = coordinator.search_authenticated_evidence

    def structural_fake(*, corpus_id: str, query: str, limit: int):
        del corpus_id
        return _receipt(
            authority,
            coordinator.admission,
            query=query,
            limit=limit,
        )

    coordinator.search_authenticated_evidence = structural_fake  # type: ignore[method-assign]
    with pytest.raises(ManagedRunError, match="unauthenticated"):
        run.search(corpus_id=authority.units[0].corpus_id, query="query", top_k=1)
    coordinator.search_authenticated_evidence = original  # type: ignore[method-assign]

    forged = object.__new__(ManagedMem0V5ManifestAuthority)
    for field in fields(ManagedMem0V5ManifestAuthority):
        value = getattr(authority, field.name)
        if field.name == "units":
            value = (authority.units[0], authority.units[0])
        object.__setattr__(forged, field.name, value)
    with pytest.raises(ManagedRunError, match="manifest authority is invalid"):
        ManagedMem0V5PairedEvidenceProjector(
            authority=forged,
            expected_admission_commitment_sha256=coordinator.admission,
        )


def test_cleanup_rejects_foreign_or_residual_terminal() -> None:
    authority, coordinator, run = _run()
    run.start()
    valid = _terminal(authority, coordinator.admission)
    foreign = replace(valid, admission_commitment_sha256=_sha("foreign"))
    coordinator.cleanup = lambda: foreign  # type: ignore[method-assign]
    with pytest.raises(ManagedRunError, match="terminal binding differs"):
        run.cleanup()


def test_cleanup_failure_retries_without_reopening_run() -> None:
    _authority_value, coordinator, run = _run()
    run.start()
    coordinator.cleanup_failures = 1

    with pytest.raises(RuntimeError, match="cleanup failed"):
        run.cleanup()
    terminal = run.cleanup()

    assert terminal.terminal_state == Mem0OssFullRunState.DELETED.value
    assert coordinator.cleanup_calls == 2
    assert coordinator.admit_calls == coordinator.dispatch_calls == 1


def test_cached_deleted_cleanup_revalidates_mutated_terminal() -> None:
    _authority_value, _coordinator, run = _run()
    run.start()
    terminal = run.cleanup()
    object.__setattr__(terminal, "operation_root_sha256", _sha("mutated-root"))

    with pytest.raises(ManagedRunError, match="terminal binding differs"):
        run.cleanup()


def test_abort_failure_has_explicit_retry_without_redispatch() -> None:
    _authority_value, coordinator, run = _run()
    coordinator.dispatch_failures = 1
    coordinator.abort_failures = 1

    with pytest.raises(RuntimeError, match="dispatch failed"):
        run.start()
    terminal = run.retry_abort()

    assert terminal.terminal_state == Mem0OssFullRunState.ABORTED.value
    assert coordinator.abort_calls == 2
    assert coordinator.admit_calls == coordinator.dispatch_calls == 1


def test_successful_start_abort_is_not_cached_as_deleted_cleanup() -> None:
    _authority_value, coordinator, run = _run()
    coordinator.dispatch_failures = 1

    with pytest.raises(RuntimeError, match="dispatch failed"):
        run.start()
    with pytest.raises(ManagedRunError, match="cleanup terminal is not deleted"):
        run.cleanup()

    assert coordinator.abort_calls == 1
    assert coordinator.admit_calls == coordinator.dispatch_calls == 1


def test_cached_aborted_cleanup_cannot_be_mutated_into_deleted() -> None:
    _authority_value, coordinator, run = _run()
    coordinator.dispatch_failures = 1

    with pytest.raises(RuntimeError, match="dispatch failed"):
        run.start()
    terminal = coordinator.terminal_evidence
    object.__setattr__(terminal, "terminal_state", Mem0OssFullRunState.DELETED.value)
    object.__setattr__(run, "_terminal", terminal)

    with pytest.raises(ManagedRunError, match="terminal binding differs"):
        run.cleanup()


def test_active_restore_dispatch_failure_retries_only_abort() -> None:
    _authority_value, coordinator, run = _run()
    coordinator.restore_phase = ManagedMem0V5RunPhase.ACTIVE
    coordinator.dispatch_failures = 1
    coordinator.abort_failures = 1

    with pytest.raises(RuntimeError, match="dispatch failed"):
        run.restore()
    terminal = run.retry_abort()

    assert terminal.terminal_state == Mem0OssFullRunState.ABORTED.value
    assert coordinator.restore_calls == coordinator.dispatch_calls == 1
    assert coordinator.abort_calls == 2


def test_restore_revalidates_forged_exact_checkpoint_dto() -> None:
    authority, coordinator, run = _run()
    checkpoint = _checkpoint(
        authority,
        coordinator.admission,
        ManagedMem0V5RunPhase.SEALED,
    )
    object.__setattr__(checkpoint, "units", ())
    coordinator.restore = lambda **kwargs: checkpoint  # type: ignore[method-assign]

    with pytest.raises(ManagedRunError, match="checkpoint binding differs"):
        run.restore()


def test_cleanup_rejects_same_admission_divergent_seal_terminal() -> None:
    authority, coordinator, run = _run()
    run.start()
    terminal = _terminal(authority, coordinator.admission)
    object.__setattr__(terminal, "seal_commitment_sha256", _sha("divergent-seal"))
    object.__setattr__(terminal, "operation_root_sha256", _sha("divergent-root"))
    coordinator.cleanup = lambda: terminal  # type: ignore[method-assign]

    with pytest.raises(ManagedRunError, match="terminal binding differs"):
        run.cleanup()

    _authority_value, coordinator, run = _run()
    run.start()
    residual = _terminal(authority, coordinator.admission)
    object.__setattr__(residual, "residual_record_count", 1)
    object.__setattr__(residual, "residual_root_sha256", _sha("residual"))
    coordinator.cleanup = lambda: residual  # type: ignore[method-assign]
    with pytest.raises(ManagedRunError, match="terminal binding differs"):
        run.cleanup()


def test_two_thread_start_dispatches_once() -> None:
    _authority_value, coordinator, run = _run()
    coordinator.start_gate = threading.Event()
    coordinator.release_gate = threading.Event()
    outcomes: list[type[BaseException] | str] = []

    def start() -> None:
        try:
            run.start()
            outcomes.append("sealed")
        except BaseException as error:
            outcomes.append(type(error))

    first = threading.Thread(target=start)
    second = threading.Thread(target=start)
    first.start()
    assert coordinator.start_gate.wait(timeout=2)
    second.start()
    coordinator.release_gate.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert sorted(str(item) for item in outcomes) == sorted(("sealed", str(ManagedRunError)))
    assert coordinator.admit_calls == coordinator.dispatch_calls == 1


def test_search_and_cleanup_are_serialized() -> None:
    authority, coordinator, run = _run()
    run.start()
    coordinator.start_gate = threading.Event()
    coordinator.release_gate = threading.Event()
    order: list[str] = []

    def search() -> None:
        run.search(corpus_id=authority.units[0].corpus_id, query="query", top_k=1)
        order.append("search")

    def cleanup() -> None:
        run.cleanup()
        order.append("cleanup")

    search_thread = threading.Thread(target=search)
    cleanup_thread = threading.Thread(target=cleanup)
    search_thread.start()
    assert coordinator.start_gate.wait(timeout=2)
    cleanup_thread.start()
    coordinator.release_gate.set()
    search_thread.join(timeout=2)
    cleanup_thread.join(timeout=2)
    assert order == ["search", "cleanup"]
    assert coordinator.search_calls == [1]
    assert coordinator.cleanup_calls == 1
